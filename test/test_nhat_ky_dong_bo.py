"""Đồng bộ nhật ký hằng ngày lên đám mây + dọn tệp online quá hạn giữ.

Điều chủ máy dặn kỹ nhất: đồng bộ là **ghi thêm chứ không ghi đè** — cục bộ giữ
10 ngày mà online giữ 20 thì bản online phải đủ 20. Bài kiểm quan trọng nhất ở
đây là `GhiThemKhongGhiDeTests`: dựng đúng cảnh cục bộ đã xoá ngày cũ rồi đòi
bản online của ngày đó KHÔNG bị đụng tới.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import chatlog  # noqa: E402
from services.agent import luu_tru_online as lt  # noqa: E402
from services.agent import nhat_ky_dong_bo as nk  # noqa: E402


class _CauHinhGia:
    def __init__(self, data):
        self.data = data

    def get(self):
        return self.data

    def update(self, moi):
        self.data.update(moi)


class _KhoGia:
    """Kho đám mây giả — nhớ đường dẫn nào đang có, ai ghi đè cái gì."""

    def __init__(self):
        self.tep: dict[str, str] = {}
        self.lan_ghi: list[str] = []
        self.da_xoa: list[str] = []

    def gui_len(self, cuc_bo, thu_muc):
        dich = thu_muc.rstrip("/") + "/" + Path(cuc_bo).name
        self.tep[dich] = Path(cuc_bo).read_text("utf-8")
        self.lan_ghi.append(dich)
        return {"ok": True, "duong_dan": dich, "co": len(self.tep[dich])}

    def xoa(self, duong_dan):
        self.da_xoa.append(duong_dan)
        self.tep.pop(duong_dan, None)
        return {"ok": True, "error": ""}


class _Nen(unittest.TestCase):
    """Nền chung: nhật ký SQLite tạm, kho giả, thư mục làm việc tạm, sổ tạm."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        goc = Path(self.tmp.name)

        chatlog._reset_for_tests(goc / "chatlog.sqlite")
        self.addCleanup(chatlog._reset_for_tests, None)

        self._cfg_goc = lt.config
        lt.config = _CauHinhGia({
            "chatlog_settings": {"zalop": {"enabled": True, "retention_days": 10}},
            "luu_tru_online": {"zalop": {"enabled": True, "kho": "drive",
                                         "thu_muc": "GD", "gio_dong_bo": "03:00"}},
        })
        self.addCleanup(setattr, lt, "config", self._cfg_goc)

        self._so_goc = lt._SO_PATH
        lt._SO_PATH = goc / "so.json"
        self.addCleanup(setattr, lt, "_SO_PATH", self._so_goc)

        self._trang_goc = nk._TRANG_PATH
        nk._TRANG_PATH = goc / "trang.json"
        self.addCleanup(setattr, nk, "_TRANG_PATH", self._trang_goc)

        from services import rclone_service as rcl
        self.kho = _KhoGia()
        self._ws, self._gui, self._xoa = rcl.workspace_dir, rcl.gui_len, rcl.xoa
        rcl.workspace_dir = lambda: goc
        rcl.gui_len = self.kho.gui_len
        rcl.xoa = self.kho.xoa
        self.addCleanup(setattr, rcl, "workspace_dir", self._ws)
        self.addCleanup(setattr, rcl, "gui_len", self._gui)
        self.addCleanup(setattr, rcl, "xoa", self._xoa)

    def _ghi_tin(self, ngay: str, *cac_text: str, scope: str = "v1|zalop|nhom1||"):
        """Ghi thẳng vào SQLite — `chatlog.ghi` chốt ngày theo đồng hồ thật."""
        db = chatlog._db()
        t = datetime.strptime(ngay, "%Y-%m-%d").timestamp()
        for i, txt in enumerate(cac_text):
            db.execute(
                "INSERT INTO chatlog (scope, ts, day, sender_id, sender_name,"
                " text, text_fold, mentions_fold) VALUES (?,?,?,?,?,?,?,?)",
                (scope, t + i, ngay, "u1", "Việt", txt, txt, ""))
        db.commit()

    def _xoa_ngay(self, ngay: str):
        """Giả cảnh hạn giữ CỤC BỘ đã dọn ngày này đi."""
        db = chatlog._db()
        db.execute("DELETE FROM chatlog WHERE day=?", (ngay,))
        db.commit()


class TachScopeTests(unittest.TestCase):

    def test_doc_lai_dung_khoa_nhat_ky(self):
        self.assertEqual(nk.tach_scope("v1|zalop|nhom1||"), ("zalop", "nhom1", ""))

    def test_giai_ma_phan_da_quote(self):
        self.assertEqual(nk.tach_scope("v1|tg|-100123|7|"), ("tg", "-100123", "7"))
        self.assertEqual(nk.tach_scope("v1|zalop|nh%C3%B3m%201||")[1], "nhóm 1")

    def test_khoa_la_thi_tra_rong(self):
        for xau in ("", "linh tinh", "v1|zalop"):
            with self.subTest(xau=xau):
                self.assertEqual(nk.tach_scope(xau), ("", "", ""))


class TenTepTests(unittest.TestCase):

    def test_moi_ngay_mot_ten_khac_nhau(self):
        a = nk.ten_tep("zalop", "nhom1", "", "2026-08-05")
        b = nk.ten_tep("zalop", "nhom1", "", "2026-08-06")
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith(".jsonl"))

    def test_hai_nhom_khong_dung_chung_ten(self):
        """Cấu hình khai ở cấp cả kênh thì mọi nhóm chung một thư mục."""
        self.assertNotEqual(nk.ten_tep("zalop", "nhom1", "", "2026-08-06"),
                            nk.ten_tep("zalop", "nhom2", "", "2026-08-06"))

    def test_topic_tach_khoi_nhom(self):
        self.assertNotEqual(nk.ten_tep("tg", "-100", "7", "2026-08-06"),
                            nk.ten_tep("tg", "-100", "", "2026-08-06"))

    def test_ten_khong_chua_ky_tu_pha_duong_dan(self):
        t = nk.ten_tep("zalop", "nhóm/lạ ../x", "", "2026-08-06")
        for xau in ("/", "..", " "):
            self.assertNotIn(xau, t)


class XuatJsonlTests(unittest.TestCase):

    def test_moi_tin_mot_dong_doc_lai_duoc(self):
        s = nk.xuat_jsonl([{"ts": 1.5, "ngay": "2026-08-06", "sender": "Việt",
                            "sender_id": "u1", "text": "chào"},
                           {"ts": 2.0, "ngay": "2026-08-06", "sender": "Lan",
                            "sender_id": "u2", "text": "ừ"}])
        dong = [d for d in s.splitlines() if d.strip()]
        self.assertEqual(len(dong), 2)
        self.assertEqual(json.loads(dong[0])["text"], "chào")

    def test_giu_nguyen_tieng_viet_co_dau(self):
        s = nk.xuat_jsonl([{"ts": 1, "ngay": "", "sender": "", "sender_id": "",
                            "text": "họp lúc mấy giờ"}])
        self.assertIn("họp lúc mấy giờ", s)

    def test_rong_thi_khong_ra_dong_trong(self):
        self.assertEqual(nk.xuat_jsonl([]), "")


class CanChayTests(unittest.TestCase):

    def _luc(self, gio: int, phut: int = 0) -> float:
        return datetime(2026, 8, 6, gio, phut, tzinfo=nk._TZ).timestamp()

    def test_chua_toi_gio_thi_chua_chay(self):
        self.assertFalse(nk.can_chay("03:00", now=self._luc(2, 59), lan_cuoi=""))

    def test_toi_gio_thi_chay(self):
        self.assertTrue(nk.can_chay("03:00", now=self._luc(3, 0), lan_cuoi=""))

    def test_hom_nay_chay_roi_thi_thoi(self):
        self.assertFalse(nk.can_chay("03:00", now=self._luc(9),
                                     lan_cuoi="2026-08-06"))

    def test_lo_mot_hom_thi_hom_sau_chay_ngay(self):
        """Máy chủ tắt cả ngày hôm qua — hôm nay tới giờ là chạy, không chờ bù."""
        self.assertTrue(nk.can_chay("03:00", now=self._luc(3, 5),
                                    lan_cuoi="2026-08-04"))

    def test_gio_hong_thi_ve_mac_dinh_chu_khong_chay_lien(self):
        self.assertFalse(nk.can_chay("25:99", now=self._luc(1), lan_cuoi=""))
        self.assertTrue(nk.can_chay("25:99", now=self._luc(4), lan_cuoi=""))


class QuaHanTests(unittest.TestCase):

    def test_khong_dat_han_thi_giu_mai(self):
        """0 ngày = giữ mãi. Hiểu nhầm chỗ này là xoá sạch kho của chủ máy."""
        self.assertFalse(nk.qua_han(0, 0, now=time.time()))

    def test_chua_du_ngay_thi_giu(self):
        now = time.time()
        self.assertFalse(nk.qua_han(now - 5 * 86400, 10, now=now))

    def test_qua_ngay_thi_xoa(self):
        now = time.time()
        self.assertTrue(nk.qua_han(now - 11 * 86400, 10, now=now))


class DongBoMotNgayTests(_Nen):

    def test_day_len_dung_thu_muc_nhat_ky(self):
        self._ghi_tin("2026-08-05", "chào", "ừ")
        cd = lt.cai_dat("zalop", "nhom1")
        kq = nk.dong_bo_mot_ngay("v1|zalop|nhom1||", "2026-08-05", cd)
        self.assertTrue(kq["ok"], kq)
        self.assertTrue(kq["dich"].startswith("drive:GD/Nhật ký/"))
        self.assertEqual(kq["so_tin"], 2)

    def test_noi_dung_len_may_du_tin(self):
        self._ghi_tin("2026-08-05", "một", "hai", "ba")
        nk.dong_bo_mot_ngay("v1|zalop|nhom1||", "2026-08-05",
                            lt.cai_dat("zalop", "nhom1"))
        noi_dung = list(self.kho.tep.values())[0]
        self.assertEqual(len([d for d in noi_dung.splitlines() if d.strip()]), 3)

    def test_khong_de_lai_rac_trong_thu_muc_lam_viec(self):
        self._ghi_tin("2026-08-05", "x")
        nk.dong_bo_mot_ngay("v1|zalop|nhom1||", "2026-08-05",
                            lt.cai_dat("zalop", "nhom1"))
        con = list((Path(self.tmp.name) / "nhat_ky").glob("*.jsonl"))
        self.assertEqual(con, [], "bản xuất tạm phải xoá sau khi đẩy")

    def test_ghi_vao_so_de_sau_nay_don_duoc(self):
        self._ghi_tin("2026-08-05", "x")
        kq = nk.dong_bo_mot_ngay("v1|zalop|nhom1||", "2026-08-05",
                                 lt.cai_dat("zalop", "nhom1"))
        self.assertIn(kq["dich"], lt.so_da_day())

    def test_ngay_khong_co_tin_thi_khong_day(self):
        kq = nk.dong_bo_mot_ngay("v1|zalop|nhom1||", "2026-08-05",
                                 lt.cai_dat("zalop", "nhom1"))
        self.assertFalse(kq["ok"])
        self.assertEqual(self.kho.tep, {})


class GhiThemKhongGhiDeTests(_Nen):
    """Điều chủ máy dặn kỹ nhất: cục bộ 10 ngày, online 20 → online phải đủ 20."""

    def _chay(self, gio="09:00"):
        """Chạy một vòng đồng bộ ở thời điểm đã qua giờ, chưa chạy hôm nay."""
        nk._ghi_trang({"lan_cuoi": {}, "dau_ngay": _giu_dau_ngay()})
        return nk.dong_bo(now=_bay_gio(gio))

    def test_ngay_cuc_bo_da_xoa_thi_ban_online_khong_bi_dung_toi(self):
        self._ghi_tin("2026-07-20", "tin ngày cũ")
        self._ghi_tin("2026-07-30", "tin ngày mới")
        nk.dong_bo(now=_bay_gio("09:00"))
        cu = [d for d in self.kho.tep if "2026-07-20" in d]
        self.assertEqual(len(cu), 1, "ngày cũ phải có mặt trên mây")
        noi_dung_cu = self.kho.tep[cu[0]]

        # Hạn giữ CỤC BỘ dọn ngày cũ đi, rồi đồng bộ lại vào hôm sau.
        self._xoa_ngay("2026-07-20")
        nk._ghi_trang({"lan_cuoi": {}, "dau_ngay": {}})
        nk.dong_bo(now=_bay_gio("09:00"))

        self.assertIn(cu[0], self.kho.tep, "bản online của ngày cũ bị xoá mất")
        self.assertEqual(self.kho.tep[cu[0]], noi_dung_cu,
                         "bản online của ngày cũ bị ghi đè bằng bản rỗng")

    def test_ngay_khong_doi_thi_khong_day_lai(self):
        self._ghi_tin("2026-07-30", "x")
        nk.dong_bo(now=_bay_gio("09:00"))
        so_lan = len(self.kho.lan_ghi)
        nk._ghi_trang({**nk._doc_trang(), "lan_cuoi": {}})   # cho phép chạy lại
        nk.dong_bo(now=_bay_gio("09:00"))
        self.assertEqual(len(self.kho.lan_ghi), so_lan,
                         "ngày không đổi mà vẫn đẩy lại — tốn băng thông mỗi đêm")

    def test_ngay_co_them_tin_thi_day_lai_ban_day_hon(self):
        self._ghi_tin("2026-07-30", "một")
        nk.dong_bo(now=_bay_gio("09:00"))
        self._ghi_tin("2026-07-30", "hai")
        nk._ghi_trang({**nk._doc_trang(), "lan_cuoi": {}})
        nk.dong_bo(now=_bay_gio("09:00"))
        noi_dung = list(self.kho.tep.values())[0]
        self.assertEqual(len([d for d in noi_dung.splitlines() if d.strip()]), 2)

    def test_moi_ngay_mot_tep_rieng(self):
        self._ghi_tin("2026-07-28", "a")
        self._ghi_tin("2026-07-29", "b")
        self._ghi_tin("2026-07-30", "c")
        nk.dong_bo(now=_bay_gio("09:00"))
        self.assertEqual(len(self.kho.tep), 3)


class ChayTheoPhamViTests(_Nen):

    def test_pham_vi_tat_luu_tru_thi_khong_dong_bo(self):
        lt.config = _CauHinhGia({"luu_tru_online": {}})
        self._ghi_tin("2026-07-30", "x")
        kq = nk.dong_bo(now=_bay_gio("09:00"))
        self.assertEqual(kq["pham_vi"], 0)
        self.assertEqual(self.kho.tep, {})

    def test_chua_toi_gio_thi_chua_chay(self):
        self._ghi_tin("2026-07-30", "x")
        kq = nk.dong_bo(now=_bay_gio("01:00"))
        self.assertEqual(kq["pham_vi"], 0)
        self.assertEqual(self.kho.tep, {})

    def test_chay_roi_thi_trong_ngay_khong_chay_lai(self):
        self._ghi_tin("2026-07-30", "x")
        nk.dong_bo(now=_bay_gio("09:00"))
        kq = nk.dong_bo(now=_bay_gio("10:00"))
        self.assertEqual(kq["pham_vi"], 0)


class DonQuaHanTests(_Nen):

    def test_chi_xoa_tep_co_trong_so(self):
        """Thư mục chủ máy chọn có thể đang chứa tài liệu riêng của họ."""
        now = time.time()
        lt.ghi_so("drive:GD/PDF/cua-bot.pdf", "zalop", "nhom1")
        so = lt.so_da_day()
        so["drive:GD/PDF/cua-bot.pdf"]["luc"] = now - 400 * 86400
        lt._ghi_so_file(so)
        self.kho.tep["drive:GD/PDF/cua-chu-may.pdf"] = "x"
        nk.don_qua_han(now=now)
        self.assertEqual(self.kho.da_xoa, ["drive:GD/PDF/cua-bot.pdf"])

    def test_chua_qua_han_thi_giu(self):
        now = time.time()
        lt.ghi_so("drive:GD/PDF/moi.pdf", "zalop", "nhom1")
        nk.don_qua_han(now=now)
        self.assertEqual(self.kho.da_xoa, [])

    def test_han_rieng_tung_muc(self):
        """Ảnh giữ 60 ngày, PDF giữ 400 — cùng tuổi 100 ngày thì chỉ ảnh bị xoá."""
        lt.config = _CauHinhGia({"luu_tru_online": {"zalop": {
            "enabled": True, "kho": "drive", "thu_muc": "GD",
            "giu_ngay": {"PDF": 400, "Ảnh": 60}}}})
        now = time.time()
        for dd in ("drive:GD/PDF/a.pdf", "drive:GD/Ảnh/b.jpg"):
            lt.ghi_so(dd, "zalop", "nhom1")
        so = lt.so_da_day()
        for v in so.values():
            v["luc"] = now - 100 * 86400
        lt._ghi_so_file(so)
        nk.don_qua_han(now=now)
        self.assertEqual(self.kho.da_xoa, ["drive:GD/Ảnh/b.jpg"])

    def test_han_bang_khong_thi_giu_mai(self):
        lt.config = _CauHinhGia({"luu_tru_online": {"zalop": {
            "enabled": True, "kho": "drive", "thu_muc": "GD",
            "giu_ngay": {m: 0 for m in lt.CAC_MUC}}}})
        now = time.time()
        lt.ghi_so("drive:GD/PDF/rat-cu.pdf", "zalop", "nhom1")
        so = lt.so_da_day()
        so["drive:GD/PDF/rat-cu.pdf"]["luc"] = now - 9999 * 86400
        lt._ghi_so_file(so)
        nk.don_qua_han(now=now)
        self.assertEqual(self.kho.da_xoa, [])

    def test_so_rong_thi_khong_xoa_gi(self):
        """Mất sổ = không xoá gì. Hỏng về phía an toàn, không phía mất dữ liệu."""
        self.kho.tep["drive:GD/PDF/cua-chu-may.pdf"] = "x"
        nk.don_qua_han(now=time.time())
        self.assertEqual(self.kho.da_xoa, [])

    def test_xoa_xong_thi_bo_khoi_so(self):
        now = time.time()
        lt.ghi_so("drive:GD/PDF/cu.pdf", "zalop", "nhom1")
        so = lt.so_da_day()
        so["drive:GD/PDF/cu.pdf"]["luc"] = now - 400 * 86400
        lt._ghi_so_file(so)
        nk.don_qua_han(now=now)
        self.assertEqual(lt.so_da_day(), {})


def _bay_gio(gio: str) -> float:
    """Epoch của HÔM NAY lúc `gio` — trạng thái «hôm nay đã chạy chưa» so theo
    ngày thật, nên mốc thử phải nằm trong ngày thật."""
    h, m = (int(x) for x in gio.split(":"))
    t = datetime.now(nk._TZ).replace(hour=h, minute=m, second=0, microsecond=0)
    return t.timestamp()


def _giu_dau_ngay() -> dict:
    return dict(nk._doc_trang().get("dau_ngay") or {})


class DungKhoaNhatKyThatTests(unittest.TestCase):
    """Khoá test tự bịa mà lệch khoá thật thì mọi bài trên đều vô nghĩa."""

    def test_khoa_scope_khop_scope_khoa_nhat_ky(self):
        """Tên kênh giải ra phải ĐÚNG tên kênh mà cấu hình lưu trữ dùng.

        Lệch một chữ ('zalo_p' thay vì 'zalop') là `lt.cai_dat` không bao giờ
        khớp, và cả phần đồng bộ im lặng không làm gì mà không báo lỗi nào.
        """
        from services.agent.scope import khoa_nhat_ky
        cap = [("zalop_nhom1", ("zalop", "nhom1", "")),
               ("zalo_5566", ("zalo", "5566", "")),
               ("-100123#7", ("tg", "-100123", "7"))]
        for khoa_phien, mong in cap:
            with self.subTest(khoa_phien=khoa_phien):
                self.assertEqual(nk.tach_scope(khoa_nhat_ky(khoa_phien)), mong)

    def test_ten_kenh_nam_trong_bo_khoa_cau_hinh(self):
        from services.agent.scope import khoa_nhat_ky
        kenh = nk.tach_scope(khoa_nhat_ky("zalop_nhom1"))[0]
        self.assertIn(f"{kenh}:nhom1", lt._cac_khoa_cai_dat(kenh, "nhom1", "", ""))


if __name__ == "__main__":
    unittest.main()


class LogGoiDungMotThamSoTests(unittest.TestCase):
    """`utils.log.Logger` nhận ĐÚNG MỘT tham số, không phải %-format nhiều vế.

    Đo thật 06/08 trên máy chủ: `start()` gọi `logger.info("... %d giây", n)` →
    TypeError ngay trong lời gọi khởi động, nên vòng nền KHÔNG BAO GIỜ chạy, và
    dấu hiệu duy nhất là một dòng `startup_step_failed` lẫn giữa log. Lần trước
    tôi lọc bằng grep `%s` nên bỏ sót đúng dòng dùng `%d` — nay soi bằng AST.
    """

    MODULE = ("services/agent/nhat_ky_dong_bo.py", "services/agent/luu_tru_day.py",
              "services/agent/luu_tru_online.py")

    def test_khong_loi_goi_logger_nao_nhieu_tham_so(self):
        import ast
        for f in self.MODULE:
            src = (GOC / f).read_text("utf-8")
            for n in ast.walk(ast.parse(src)):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "logger"
                        and len(n.args) + len(n.keywords) > 1):
                    self.fail(f"{f}:{n.lineno} logger.{n.func.attr} có "
                              f"{len(n.args)} tham số — utils.log.Logger chỉ nhận 1")

    def test_logger_that_su_chi_nhan_mot_tham_so(self):
        """Nếu Logger đổi sang nhận %-format thì bài trên thành vô nghĩa."""
        import inspect
        from utils.log import Logger
        for ten in ("info", "warning"):
            sig = inspect.signature(getattr(Logger, ten))
            self.assertEqual(len(sig.parameters), 2,  # self + message
                             f"Logger.{ten} đã đổi chữ ký — xem lại bài kiểm trên")
