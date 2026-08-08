"""Phiên trình duyệt: cookie HttpOnly + CSRF, và KHÔNG đụng đường Bearer.

Ràng buộc quan trọng nhất không phải "cookie chạy được" mà là **Bearer không
đổi hành vi**. Home Assistant, Zalo, script và mọi API ngoài đều đi bằng
Bearer; nếu bản thay đổi này bắt chúng gửi CSRF thì cả nhà tự động hoá chết
lặng, và triệu chứng sẽ hiện ra ở chỗ khác nguyên nhân — đúng kiểu lỗi đã tốn
nhiều thời gian nhất trong dự án này.

Cờ `security.browser_sessions_enabled` mặc định TẮT nên bản này không đổi gì
cho tới khi frontend sẵn sàng.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import browser_session as bs  # noqa: E402
from services.browser_session import KhoPhienTrinhDuyet  # noqa: E402
from services.browser_session_middleware import origin_hop_le  # noqa: E402
from services.config import config  # noqa: E402


class _KhoTam(unittest.TestCase):
    """Mỗi test một thư mục riêng — không đụng data/ thật."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cu = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self._tmp.name
        self.kho = KhoPhienTrinhDuyet()

    def tearDown(self):
        if self._cu is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self._cu
        self._tmp.cleanup()

    ADMIN = {"id": "admin", "name": "Quản trị viên", "role": "admin"}


class KhoPhienTests(_KhoTam):
    def test_tao_roi_tra_cuu_duoc(self):
        sid, csrf = self.kho.tao(self.ADMIN)
        ban_ghi = self.kho.tra_cuu(sid)
        self.assertIsNotNone(ban_ghi)
        self.assertEqual(ban_ghi["vai_tro"], "admin")
        self.assertTrue(self.kho.kiem_csrf(sid, csrf))

    def test_KHONG_luu_session_id_dang_goc(self):
        """Đọc được file phiên cũng không mạo danh được ai."""
        sid, csrf = self.kho.tao(self.ADMIN)
        thoi = (Path(self._tmp.name) / "browser_sessions.json").read_text(encoding="utf-8")
        self.assertNotIn(sid, thoi, "session id nằm nguyên trong file")
        self.assertNotIn(csrf, thoi, "csrf secret nằm nguyên trong file")

    def test_sid_sai_thi_khong_ra_gi(self):
        self.kho.tao(self.ADMIN)
        self.assertIsNone(self.kho.tra_cuu("sid-bia-ra"))

    def test_csrf_sai_thi_tu_choi(self):
        sid, _ = self.kho.tao(self.ADMIN)
        self.assertFalse(self.kho.kiem_csrf(sid, "token-sai"))
        self.assertFalse(self.kho.kiem_csrf(sid, ""))

    def test_csrf_co_ky_tu_ngoai_ascii_khong_lam_sap(self):
        """Header là do CLIENT gửi — họ gửi được bất cứ thứ gì.

        `compare_digest` trên chuỗi ném TypeError với ký tự ngoài ASCII; ở đây
        nó sẽ thành HTTP 500 thay vì 403, tức là biến một request rác thành
        cách làm ồn log (và che mất tấn công thật).
        """
        sid, _ = self.kho.tao(self.ADMIN)
        self.assertFalse(self.kho.kiem_csrf(sid, "khóa-tiếng-việt-có-dấu"))

    def test_thu_hoi_tung_phien(self):
        sid1, _ = self.kho.tao(self.ADMIN)
        sid2, _ = self.kho.tao(self.ADMIN)
        self.assertTrue(self.kho.thu_hoi(sid1))
        self.assertIsNone(self.kho.tra_cuu(sid1))
        self.assertIsNotNone(self.kho.tra_cuu(sid2), "thu hồi một phiên đá luôn phiên khác")

    def test_het_han_thi_khong_dung_duoc(self):
        sid, _ = self.kho.tao(self.ADMIN)
        khoa = bs._bam(sid)
        self.kho._phien[khoa]["het_han"] = 1.0        # đã qua từ 1970
        self.assertIsNone(self.kho.tra_cuu(sid))

    def test_bo_lau_khong_dung_thi_het_hieu_luc(self):
        sid, _ = self.kho.tao(self.ADMIN)
        khoa = bs._bam(sid)
        self.kho._phien[khoa]["lan_cuoi"] = 1.0
        self.assertIsNone(self.kho.tra_cuu(sid),
                          "phiên bỏ quên vẫn mở cửa dù chưa hết hạn tuyệt đối")

    def test_song_qua_khoi_dong_lai(self):
        """Redeploy KHÔNG được đá mọi người ra ngoài."""
        sid, csrf = self.kho.tao(self.ADMIN)
        kho_moi = KhoPhienTrinhDuyet()          # như tiến trình vừa khởi động
        self.assertIsNotNone(kho_moi.tra_cuu(sid))
        self.assertTrue(kho_moi.kiem_csrf(sid, csrf))

    def test_file_hong_khong_lam_chet_tien_trinh(self):
        (Path(self._tmp.name) / "browser_sessions.json").write_text("{ hong", encoding="utf-8")
        kho_moi = KhoPhienTrinhDuyet()
        self.assertIsNone(kho_moi.tra_cuu("bat-ky"))
        sid, _ = kho_moi.tao(self.ADMIN)        # vẫn tạo mới được
        self.assertIsNotNone(kho_moi.tra_cuu(sid))

    def test_khong_phinh_vo_han(self):
        for _ in range(bs.GIOI_HAN_PHIEN + 20):
            self.kho.tao(self.ADMIN)
        self.assertLessEqual(self.kho.so_phien(), bs.GIOI_HAN_PHIEN)

    def test_quyen_file_chi_chu_so_huu(self):
        self.kho.tao(self.ADMIN)
        che_do = (Path(self._tmp.name) / "browser_sessions.json").stat().st_mode & 0o777
        self.assertEqual(che_do, 0o600, f"file phiên đang là {oct(che_do)}")


class GhiDiaDinhKyTests(_KhoTam):
    """Người dùng CÀNG hoạt động thì càng dễ bị đá — nên rất khó lần.

    Bản đầu so mốc rồi cũng cập nhật chính mốc đó trong RAM, nên với người bấm
    liên tục thì khoảng cách không bao giờ vượt 5 phút và ĐĨA KHÔNG BAO GIỜ
    được ghi. Dùng ba ngày rồi redeploy là mất phiên, dù vẫn đang dùng.
    """

    def _doc_dia(self) -> dict:
        return json.loads(
            (Path(self._tmp.name) / "browser_sessions.json").read_text(encoding="utf-8"))

    def test_dung_lien_tuc_van_duoc_ghi_dia_dinh_ky(self):
        sid, _ = self.kho.tao(self.ADMIN)
        khoa = bs._bam(sid)
        moc_dau = float(self._doc_dia()[khoa]["lan_cuoi"])
        # Giả lập: phiên đã sống 10 phút, người dùng bấm liên tục nên `lan_cuoi`
        # luôn mới, nhưng lần GHI ĐĨA gần nhất là 10 phút trước.
        self.kho._phien[khoa]["da_ghi_luc"] = time.time() - 600
        self.kho._phien[khoa]["lan_cuoi"] = time.time() - 1
        self.kho.tra_cuu(sid)
        self.assertGreater(float(self._doc_dia()[khoa]["lan_cuoi"]), moc_dau,
                           "đĩa vẫn giữ mốc cũ dù phiên đang được dùng")

    def test_dung_lien_tuc_KHONG_ghi_dia_moi_request(self):
        """Ghi mỗi request là I/O vô ích ở đường nóng."""
        sid, _ = self.kho.tao(self.ADMIN)
        p = Path(self._tmp.name) / "browser_sessions.json"
        truoc = p.stat().st_mtime_ns
        for _ in range(20):
            self.kho.tra_cuu(sid)
        self.assertEqual(p.stat().st_mtime_ns, truoc, "ghi đĩa mỗi request")

    def test_phien_dung_lien_tuc_song_qua_khoi_dong_lai(self):
        """Ràng buộc cuối cùng, đúng thứ người dùng cảm nhận được."""
        sid, csrf = self.kho.tao(self.ADMIN)
        khoa = bs._bam(sid)
        self.kho._phien[khoa]["da_ghi_luc"] = time.time() - 600
        self.kho.tra_cuu(sid)                       # một request "gần đây"
        kho_moi = KhoPhienTrinhDuyet()              # như vừa redeploy
        self.assertIsNotNone(kho_moi.tra_cuu(sid))
        self.assertTrue(kho_moi.kiem_csrf(sid, csrf))


class CookieBatBuocHttpsTests(unittest.TestCase):
    """Phát cookie phiên trên HTTP thuần = ai nghe đường truyền là lấy được."""

    def test_http_thuan_bi_TU_CHOI_chu_khong_ha_co_am_tham(self):
        src = (GOC / "api/browser_auth.py").read_text(encoding="utf-8")
        i = src.index("secure = _la_https(request)")
        than = src[i:i + 900]
        self.assertIn("https_required", than)
        self.assertIn("status_code=400", than)

    def test_co_duong_thoat_tuong_minh_cho_LAN(self):
        """Fail-closed mà không có lối ra là buộc người ta tắt cả tính năng."""
        src = (GOC / "api/browser_auth.py").read_text(encoding="utf-8")
        self.assertIn("allow_insecure_cookie", src)

    def test_co_do_mac_dinh_TAT(self):
        """Đọc mã nguồn thay vì import: `api.browser_auth` kéo theo pydantic,
        vốn cần cú pháp Python 3.10+ để giải chú thích kiểu."""
        src = (GOC / "api/browser_auth.py").read_text(encoding="utf-8")
        i = src.index("def _cho_phep_cookie_khong_secure")
        than = src[i:i + 900]
        self.assertIn("return False", than,
                      "không đọc được config thì phải coi như TẮT")
        self.assertNotIn("return True", than.split("return False")[0],
                         "có đường trả True trước khi tới mặc định")


class OriginTests(unittest.TestCase):
    def setUp(self):
        self._cu = config.data
        self.addCleanup(lambda: setattr(config, "data", self._cu))

    def test_khong_co_origin_thi_cho_qua(self):
        """Trình duyệt LUÔN gửi Origin cho request cross-site đổi trạng thái.

        Vắng Origin là curl / điều hướng thường, không phải dấu hiệu tấn công.
        Chặn nó chỉ làm hỏng đường nội bộ mà không thêm an toàn nào.
        """
        config.data = {}
        self.assertTrue(origin_hop_le("", "vidu.com"))

    def test_chua_khai_allowlist_thi_theo_same_origin(self):
        config.data = {}
        self.assertTrue(origin_hop_le("https://vidu.com", "vidu.com"))
        self.assertFalse(origin_hop_le("https://ke-tan-cong.com", "vidu.com"))

    def test_co_allowlist_thi_theo_allowlist(self):
        config.data = {"cors_allow_origins": ["https://admin.vidu.com"]}
        self.assertTrue(origin_hop_le("https://admin.vidu.com", "vidu.com"))
        self.assertFalse(origin_hop_le("https://vidu.com", "vidu.com"),
                         "đã khai allowlist thì same-origin không tự động được phép")

    def test_origin_rac_bi_tu_choi(self):
        config.data = {}
        for xau in ("null", "khong-phai-url", "javascript:alert(1)"):
            self.assertFalse(origin_hop_le(xau, "vidu.com"), f"{xau!r} lọt qua")


class MacDinhTatTests(unittest.TestCase):
    """Bật lên là đổi cách cả web admin xác thực — phải có frontend rồi mới bật."""

    def setUp(self):
        self._cu = config.data
        self.addCleanup(lambda: setattr(config, "data", self._cu))

    def test_mac_dinh_tat(self):
        from services.browser_session_middleware import bat_phien_trinh_duyet
        config.data = {}
        self.assertFalse(bat_phien_trinh_duyet())

    def test_bat_duoc_qua_config(self):
        from services.browser_session_middleware import bat_phien_trinh_duyet
        config.data = {"security": {"browser_sessions_enabled": True}}
        self.assertTrue(bat_phien_trinh_duyet())


class BearerKhongDoiHanhViTests(unittest.TestCase):
    """Ràng buộc quan trọng nhất của cả nhánh này."""

    def test_bearer_duoc_uu_tien_va_khong_doc_cookie(self):
        src = (GOC / "api/support.py").read_text(encoding="utf-8")
        i = src.index("def require_identity")
        than = src[i:i + 700]
        self.assertIn("if token:", than,
                      "phải thử Bearer TRƯỚC, cookie chỉ là đường dự phòng")

    def test_middleware_tha_request_mang_bearer_di_thang(self):
        src = (GOC / "services/browser_session_middleware.py").read_text(encoding="utf-8")
        i = src.index('headers.get("authorization"')
        self.assertIn("await self.app(scope, receive, send)", src[i:i + 260],
                      "request mang Bearer phải đi thẳng, không qua kiểm CSRF")

    def test_tat_co_thi_middleware_khong_lam_gi(self):
        src = (GOC / "services/browser_session_middleware.py").read_text(encoding="utf-8")
        i = src.index("async def __call__")
        self.assertIn("not bat_phien_trinh_duyet()", src[i:i + 300],
                      "phải thoát ngay ở dòng đầu khi cờ chưa bật")

    def test_khong_phai_BaseHTTPMiddleware(self):
        """BaseHTTPMiddleware chạy phần dưới ở task khác → ContextVar mất.

        Kiểm bằng lớp cha thật, không grep chuỗi: chính docstring của module
        có nhắc tên đó để giải thích vì sao KHÔNG dùng, nên grep sẽ bắt vào
        chú thích của chính mình.
        """
        from starlette.middleware.base import BaseHTTPMiddleware

        from services.browser_session_middleware import PhienTrinhDuyetMiddleware
        self.assertFalse(issubclass(PhienTrinhDuyetMiddleware, BaseHTTPMiddleware))


class MiddlewareChayThatTests(_KhoTam):
    """Chạy middleware qua giao thức ASGI thật, không grep mã nguồn.

    Grep chỉ chứng minh mã CÓ MẶT. Nó không bắt được thứ đã suýt lọt ở đây:
    header `Authorization: Bearer ` rỗng khớp tiền tố "bearer " nên middleware
    coi là request Bearer và bỏ qua cookie, rồi `require_identity` cũng không
    có token nào — người dùng có phiên hợp lệ vẫn nhận 401.
    """

    def setUp(self):
        super().setUp()
        import services.browser_session_middleware as mw
        from services.config import config
        self.mw = mw
        self._kho_cu = mw.kho_phien
        self._data_cu = config.data
        self.config = config
        mw.kho_phien = self.kho
        config.data = {"security": {"browser_sessions_enabled": True}}
        self.addCleanup(self._tra_lai_mw)
        self.sid, self.csrf = self.kho.tao(self.ADMIN)

    def _tra_lai_mw(self):
        self.mw.kho_phien = self._kho_cu
        self.config.data = self._data_cu

    def _chay(self, headers: dict, method: str = "GET", path: str = "/api/settings"):
        """Trả (đã_xuống_dưới, danh_tính_thấy_được, các_message_đã_gửi)."""
        import asyncio

        thay: dict = {}
        gui: list = []

        async def app_duoi(scope, receive, send):
            thay["xuong"] = True
            thay["danh_tinh"] = self.mw.danh_tinh_cookie.get()

        async def send(msg):
            gui.append(msg)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http", "method": method, "path": path,
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
        asyncio.run(self.mw.PhienTrinhDuyetMiddleware(app_duoi)(scope, receive, send))
        return thay.get("xuong", False), thay.get("danh_tinh"), gui

    def _ma_tra_ve(self, gui: list) -> int:
        for m in gui:
            if m.get("type") == "http.response.start":
                return int(m.get("status") or 0)
        return 0

    def test_bearer_that_di_thang_khong_doc_cookie(self):
        xuong, danh_tinh, _ = self._chay(
            {"authorization": "Bearer khoa-that", "cookie": f"c2a_session={self.sid}"})
        self.assertTrue(xuong)
        self.assertIsNone(danh_tinh, "có Bearer mà vẫn giải danh tính từ cookie")

    def test_bearer_RONG_khong_duoc_chan_duong_cookie(self):
        """Đúng lỗi đã suýt ship: frontend dựng `Bearer ${khoa}` với khoá rỗng."""
        xuong, danh_tinh, _ = self._chay(
            {"authorization": "Bearer ", "cookie": f"c2a_session={self.sid}"})
        self.assertTrue(xuong)
        self.assertIsNotNone(danh_tinh, "header Bearer rỗng đã nuốt mất phiên cookie")
        self.assertEqual(danh_tinh["role"], "admin")

    def test_cookie_hop_le_thi_giai_duoc_danh_tinh(self):
        xuong, danh_tinh, _ = self._chay({"cookie": f"c2a_session={self.sid}"})
        self.assertTrue(xuong)
        self.assertEqual(danh_tinh["role"], "admin")
        self.assertEqual(danh_tinh["nguon"], "cookie")

    def test_khong_co_cookie_thi_khong_dung_gi(self):
        xuong, danh_tinh, _ = self._chay({})
        self.assertTrue(xuong)
        self.assertIsNone(danh_tinh)

    def test_POST_bang_cookie_thieu_CSRF_thi_403(self):
        xuong, _, gui = self._chay(
            {"cookie": f"c2a_session={self.sid}", "host": "vidu.com"}, method="POST")
        self.assertFalse(xuong, "request đổi trạng thái lọt xuống dù thiếu CSRF")
        self.assertEqual(self._ma_tra_ve(gui), 403)

    def test_POST_du_CSRF_va_origin_thi_qua(self):
        xuong, danh_tinh, _ = self._chay(
            {"cookie": f"c2a_session={self.sid}", "host": "vidu.com",
             "origin": "https://vidu.com", "x-csrf-token": self.csrf}, method="POST")
        self.assertTrue(xuong)
        self.assertEqual(danh_tinh["role"], "admin")

    def test_POST_origin_la_trang_khac_thi_403(self):
        xuong, _, gui = self._chay(
            {"cookie": f"c2a_session={self.sid}", "host": "vidu.com",
             "origin": "https://ke-tan-cong.com", "x-csrf-token": self.csrf},
            method="POST")
        self.assertFalse(xuong)
        self.assertEqual(self._ma_tra_ve(gui), 403)

    def test_GET_bang_cookie_khong_doi_CSRF(self):
        """GET không đổi trạng thái — bắt CSRF ở đây chỉ làm hỏng việc đọc."""
        xuong, danh_tinh, _ = self._chay(
            {"cookie": f"c2a_session={self.sid}", "host": "vidu.com"}, method="GET")
        self.assertTrue(xuong)
        self.assertIsNotNone(danh_tinh)

    def test_dang_nhap_duoc_mien_CSRF(self):
        """Chưa có phiên thì chưa có token nào để mà gửi."""
        xuong, _, gui = self._chay(
            {"cookie": f"c2a_session={self.sid}", "host": "vidu.com"},
            method="POST", path="/auth/browser-login")
        self.assertTrue(xuong)

    def test_tat_co_thi_khong_giai_danh_tinh(self):
        self.config.data = {}
        xuong, danh_tinh, _ = self._chay({"cookie": f"c2a_session={self.sid}"})
        self.assertTrue(xuong)
        self.assertIsNone(danh_tinh)

    def test_khong_ro_ri_danh_tinh_sang_request_sau(self):
        """ContextVar không reset là request kế tiếp thừa hưởng quyền admin."""
        self._chay({"cookie": f"c2a_session={self.sid}"})
        self.assertIsNone(self.mw.danh_tinh_cookie.get())
        _, danh_tinh, _ = self._chay({})
        self.assertIsNone(danh_tinh)


@unittest.skipIf(sys.version_info < (3, 10),
                 "cú pháp `str | None` trong chuỗi import cần Python 3.10+")
class NapDuocThatTests(unittest.TestCase):
    """Router hỏng lúc import thì cả app chết khi khởi động, không chỉ một endpoint.

    Các test khác trong file đọc mã dưới dạng VĂN BẢN nên không bắt được lỗi
    import. Test này nạp thật.
    """

    def test_router_nap_va_dang_ky_du_ba_duong(self):
        from api.browser_auth import create_router
        duong = {r.path for r in create_router().routes}
        self.assertEqual(duong, {"/auth/browser-login", "/auth/browser-logout",
                                 "/auth/browser-session"})

    def test_app_van_khai_bao_middleware(self):
        src = (GOC / "api/app.py").read_text(encoding="utf-8")
        self.assertIn("PhienTrinhDuyetMiddleware", src)
        self.assertIn("browser_auth.create_router()", src)


class KhongLoBiMatTests(_KhoTam):
    def test_dang_nhap_khong_tra_session_id_trong_body(self):
        """Session id chỉ được đi trong cookie HttpOnly, không lọt vào JSON."""
        src = (GOC / "api/browser_auth.py").read_text(encoding="utf-8")
        i = src.index("resp = JSONResponse({")
        than = src[i:src.index("resp.set_cookie")]
        self.assertNotIn("sid", than, "session id lọt vào body JSON")
        self.assertIn("csrf_token", than)

    def test_cookie_dat_dung_thuoc_tinh(self):
        src = (GOC / "api/browser_auth.py").read_text(encoding="utf-8")
        i = src.index("resp.set_cookie")
        than = src[i:i + 900]
        self.assertIn("httponly=True", than)
        self.assertIn('samesite="lax"', than)
        self.assertIn("secure=secure", than)
        self.assertIn('path="/"', than)


if __name__ == "__main__":
    unittest.main()
