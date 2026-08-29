"""Xoá tài khoản phải xoá ở ĐỦ BỐN nơi, và mọi ô chọn phải cùng thấy một sự thật.

SỰ CỐ 29/08/2026 — chủ máy báo ba chuyện xảy ra cùng lúc trên trang Settings:
"một số tài khoản đã xoá từ lâu mà không mất, đã xoá chỗ khác mà không đồng bộ,
rồi cả lặp lại tài khoản".

Đối chiếu ảnh chụp hai ô chọn với đĩa máy chủ:

  · Đĩa `/app/data/captcha/profiles` có đúng 12 hồ sơ lọt bộ lọc.
  · Ô "ChatGPT" hiện 12 — đúng.
  · Ô "Gemini Web API" hiện 17, thừa `google-AngianoLandro8821`,
    `google-DegaustGellert3920`, `google-ErkerSchopper0973`,
    `google-MorkveJorie191`, `google-StelmackMalagarie974` — năm thư mục này
    KHÔNG còn tồn tại trên đĩa.
  · `google-bios-disused99-6e84t67f` và `openai-bios-disused99-6e84t67f` là
    CÙNG một tài khoản, hiện thành hai dòng.

BA NGUYÊN NHÂN RIÊNG BIỆT

1. Mỗi ô chọn là một instance `ReuseProfilePicker` với `useState` riêng, chỉ nạp
   lúc mount và chỉ nạp lại sau khi CHÍNH NÓ xoá. Xoá ở ô này thì các ô kia giữ
   nguyên danh sách cũ tới khi tải lại trang. Kèm `catch {}` nuốt lỗi im lặng
   nên danh sách quá hạn trông y hệt danh sách vừa nạp.

2. `_cleanup_captcha_profiles` chỉ xoá MỘT thư mục (`google-<localpart>` suy
   theo quy ước) và MỘT kho credential (`loai` để trống → mặc định `google`).
   Một tài khoản Google có tới bốn thư mục anh em (`google-`, `chatgpt-`,
   `codex-`, `github-`), mỗi cái một bộ cookie. Đo trên máy chủ: còn
   `chatgpt-benbap115`, `chatgpt-smarthomebenbap` (22/06), `codex-*` (25–30/07),
   `github-*` (12/06) — 16 thư mục, khoảng 110 MB.

3. Bộ lọc của ô chọn loại `github-`, `codex-`, `chatgpt-` nhưng quên `openai-`,
   nên tài khoản OpenAI gốc vừa hiện thừa vừa hiện trùng.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from api.accounts import _cleanup_captcha_profiles, _duoi_ho_so, _profile_for_email

GOC = Path(__file__).resolve().parents[1]
PICKER = (GOC / "web/src/app/settings/components/reuse-profile-picker.tsx").read_text(encoding="utf-8")


class DuoiHoSoTests(unittest.TestCase):
    """So khớp NGUYÊN VĂN — ở đây đang xoá, nhận nhầm là mất phiên người khác."""

    def test_cac_tien_to_dich_vu_cho_ra_cung_mot_duoi(self):
        for ten in ("google-benbap115", "chatgpt-benbap115", "codex-benbap115",
                    "github-benbap115", "openai-benbap115"):
            self.assertEqual(_duoi_ho_so(ten), "benbap115", ten)

    def test_KHONG_gop_dau_cham_va_gach(self):
        """`ben.bap@` và `benbap@` là hai tài khoản khác nhau."""
        self.assertNotEqual(_duoi_ho_so(_profile_for_email("ben.bap@gmail.com")),
                            _duoi_ho_so(_profile_for_email("benbap@gmail.com")))

    def test_ten_khong_co_tien_to_thi_khong_khop_gi(self):
        self.assertEqual(_duoi_ho_so("default"), "")


class _DapGia:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload


class XoaDuBonNoiTests(unittest.TestCase):
    """Xoá tài khoản = thư mục anh em + cả hai kho + tham chiếu config."""

    TREN_DIA = [
        "google-benbap115", "chatgpt-benbap115", "codex-benbap115",
        "github-benbap115", "gemini-web-default", "google-nguoi-khac",
    ]

    def _chay(self):
        da_xoa_ho_so: list[str] = []
        da_xoa_kho: list[tuple[str, str]] = []
        da_don_config: list[set] = []

        def gia_get(url, **kw):
            return _DapGia({"profiles": self.TREN_DIA})

        def gia_delete(url, **kw):
            if "/v1/profiles/" in url:
                da_xoa_ho_so.append(url.rsplit("/", 1)[-1])
            elif "/v1/accounts/saved/" in url:
                da_xoa_kho.append((url.rsplit("/", 1)[-1],
                                   str((kw.get("params") or {}).get("loai") or "")))
            return _DapGia()

        cfg = {"providers": {"flow": {"captcha_solver_url": "http://solver",
                                      "captcha_solver_api_key": "k"}}}
        with mock.patch("httpx.get", gia_get), \
             mock.patch("httpx.delete", gia_delete), \
             mock.patch("api.accounts.config") as gia_config, \
             mock.patch("api.accounts._strip_web_profiles_from_config",
                        lambda p: da_don_config.append(set(p))):
            gia_config.data = cfg
            _cleanup_captcha_profiles([{"email": "benbap115@gmail.com"}])
        return da_xoa_ho_so, da_xoa_kho, da_don_config

    def test_xoa_MOI_thu_muc_anh_em(self):
        ho_so, _, _ = self._chay()
        for ten in ("google-benbap115", "chatgpt-benbap115",
                    "codex-benbap115", "github-benbap115"):
            self.assertIn(ten, ho_so, f"{ten} còn nằm lại trên đĩa")

    def test_khong_dung_vao_ho_so_cua_tai_khoan_khac(self):
        ho_so, _, _ = self._chay()
        self.assertNotIn("google-nguoi-khac", ho_so)

    def test_khong_dung_vao_ho_so_placeholder_dung_chung(self):
        ho_so, _, _ = self._chay()
        self.assertNotIn("gemini-web-default", ho_so,
                         "hồ sơ placeholder dùng chung cho cả hệ thống")

    def test_xoa_credential_o_CA_HAI_kho(self):
        _, kho, _ = self._chay()
        self.assertEqual(sorted(k for _, k in kho), ["google", "openai"],
                         "để trống `loai` thì solver mặc định kho 'google', "
                         "bản ghi kho 'openai' không bao giờ xoá được")

    def test_don_luon_tham_chieu_trong_config(self):
        _, _, don = self._chay()
        self.assertTrue(don, "không dọn config thì provider-tree bơm lại tài khoản")
        self.assertIn("chatgpt-benbap115", don[0])

    def test_khong_co_email_thi_khong_dung_gi(self):
        with mock.patch("httpx.delete") as xoa:
            with mock.patch("api.accounts.config") as gia_config:
                gia_config.data = {"providers": {"flow": {"captcha_solver_url": "http://solver"}}}
                _cleanup_captcha_profiles([{"email": ""}, {}])
            xoa.assert_not_called()


class OChonMotNguonSuThatTests(unittest.TestCase):
    """Năm ô chọn trên cùng một trang phải cùng thấy một danh sách."""

    def test_danh_sach_nam_o_kho_dung_chung(self):
        self.assertIn("let khoDanhSach: string[] = []", PICKER,
                      "danh sách phải nằm ngoài component, không phải useState riêng")
        self.assertIn("const nguoiNghe = new Set<() => void>()", PICKER,
                      "thiếu cơ chế báo cho các ô khác khi danh sách đổi")

    def test_khong_con_useState_rieng_cho_danh_sach(self):
        self.assertNotIn("useState<string[]>([])", PICKER,
                         "còn state danh sách riêng của từng ô — xoá ở ô này thì "
                         "ô kia vẫn hiện tên đã xoá")

    def test_xoa_xong_thi_MOI_o_cung_nap_lai(self):
        i = PICKER.index("async function deleteSession")
        than = PICKER[i:PICKER.index("return (", i)]
        self.assertIn("napKho(cs)", than,
                      "xoá xong phải nạp lại kho dùng chung, không phải chỉ ô này")

    def test_khong_nuot_im_loi_nap(self):
        self.assertNotIn("} catch {", PICKER,
                         "còn `catch` trống — nuốt lỗi im lặng làm một danh sách "
                         "quá hạn trông y hệt danh sách vừa nạp")
        i = PICKER.index("function napKho")
        than = PICKER[i:PICKER.index("/**", i)]
        self.assertIn("khoLoi =", than, "nạp hỏng phải ghi lại lý do")
        self.assertIn("toast.error", PICKER, "và phải nói ra cho người dùng")

    def test_lco_ho_so_openai_khoi_o_chon(self):
        i = PICKER.index("function isAccountProfile")
        than = PICKER[i:PICKER.index("let khoDanhSach", i)]
        self.assertIn('/^openai-/i.test(n)', than,
                      "hồ sơ openai-* không có phiên Google — để lọt vào là vừa "
                      "thừa vừa trùng với google-* cùng tên")


if __name__ == "__main__":
    unittest.main()
