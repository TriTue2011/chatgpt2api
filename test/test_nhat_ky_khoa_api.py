"""Nhật ký Agent run phải chỉ ra ĐÚNG model và ĐÚNG tài khoản/khoá đã dùng.

Yêu cầu: cột "mục tới" giữ tên combo ("AI image"), còn cột model phải là model
THẬT đã dựng, kèm tài khoản. Đo trên máy chạy thật 10/08/2026:

    14:31  flow / banana-pro / Main                     ✓
    18:00  flow / banana-pro / Main                     ✓
    22:00  (trống) / (trống) / (trống)                  ✗
    nv-image/flux.1-dev → nvidia_nim_image / flux.1-dev / (trống tài khoản)

Hai lỗ hổng:

  1. Nhà cung cấp dùng KHOÁ API (NVIDIA, Agnes, custom OpenAI…) không có "tài
     khoản" để đặt tên, nên cột đó luôn trống. Khi một khoá bị chặn thì không
     lần ra được khoá nào từ lịch sử chạy.
  2. Khai một lần ở đầu là chỉ biết khoá ĐẦU TIÊN. Khi khoá 1 bị 429 và khoá 3
     mới chạy được, nhật ký vẫn ghi khoá 1 — đúng lúc cần biết khoá nào còn
     sống thì nó nói sai.

Không import được `openai_v1_image_generations` trên Python 3.9 (lỗi có sẵn:
`utils/pow.py` dùng `str | None` trong annotation được evaluate lúc tạo lớp), nên
bóc riêng hàm thuần ra để vẫn kiểm hành vi thật thay vì chỉ soi chuỗi.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
DUONG = GOC / "services/protocol/openai_v1_image_generations.py"
NGUON = DUONG.read_text(encoding="utf-8")
MA = "\n".join(l for l in NGUON.splitlines() if not l.lstrip().startswith("#"))


def _nap(ten: str):
    cay = ast.parse(NGUON)
    for nut in cay.body:
        if isinstance(nut, ast.FunctionDef) and nut.name == ten:
            mod = ast.Module(body=[nut], type_ignores=[])
            ast.fix_missing_locations(mod)
            ns: dict = {"Any": object}
            exec(compile(mod, "<img>", "exec"), ns)
            return ns[ten]
    raise AssertionError(f"không tìm thấy {ten} trong nguồn")


_nhan_khoa = _nap("_nhan_khoa")


class NhanKhoaDuNhanDangKhongLoBiMat(unittest.TestCase):
    def test_nhieu_khoa_thi_neu_ro_khoa_thu_may(self):
        c = {"apiKeys": ["aaaa1111", "bbbb2222", "cccc3333"]}
        self.assertEqual(_nhan_khoa(c, 0), "khoá #1/3 (…1111)")
        self.assertEqual(_nhan_khoa(c, 2), "khoá #3/3 (…3333)")

    def test_chi_lay_4_ky_tu_cuoi_KHONG_ghi_ca_khoa(self):
        """Nhật ký đi vào file và hiện trên giao diện — ghi cả khoá là rò bí mật."""
        khoa = "sk-live-RATDAI-KHONG-DUOC-XUAT-HIEN-9xyz"
        nhan = _nhan_khoa({"apiKey": khoa}, 0)
        self.assertIn("9xyz", nhan)
        self.assertNotIn(khoa, nhan)
        self.assertNotIn("RATDAI", nhan)

    def test_key_try_vuot_so_khoa_khong_no(self):
        """Vòng thử có thể vượt số khoá; chỉ số phải quay vòng, không IndexError."""
        self.assertEqual(_nhan_khoa({"apiKeys": ["aaaa1111", "bbbb2222"]}, 5),
                         "khoá #2/2 (…2222)")

    def test_khong_co_khoa_thi_tra_rong(self):
        """Provider không dùng khoá (vd Flow dùng hồ sơ trình duyệt) → để adapter
        tự khai tên tài khoản thật, đừng bịa ra nhãn khoá."""
        self.assertEqual(_nhan_khoa({}, 0), "")
        self.assertEqual(_nhan_khoa(None, 0), "")
        self.assertEqual(_nhan_khoa({"apiKeys": []}, 0), "")

    def test_khoa_ngan_khong_no(self):
        self.assertIn("…", _nhan_khoa({"apiKey": "ab"}, 0))


class KhaiLaiTrongVongXoayKhoa(unittest.TestCase):
    def test_khai_o_TRONG_vong_thu_khoa(self):
        """Khai ngoài vòng thì chỉ biết khoá đầu tiên."""
        i = MA.index("for key_try in range(")
        j = MA.index("_khai_tai_khoan(route, credentials, key_try)")
        k = MA.index("resp = cffi_requests.post(", i)
        self.assertLess(i, j, "phải khai BÊN TRONG vòng thử khoá")
        self.assertLess(j, k, "phải khai TRƯỚC khi gửi, để lượt hỏng cũng có dấu")

    def test_khong_ghi_de_tai_khoan_co_ten_that(self):
        """Flow khai "Main"/"Spare 2" trong `build_headers`, chạy TRƯỚC chỗ này.
        Ghi đè bằng "khoá #1" là làm nhật ký kém đi."""
        i = MA.index("def _khai_tai_khoan")
        than = MA[i:i + 900]
        self.assertIn("get_dest()", than)
        self.assertIn('cu.get("account")', than)
        self.assertIn("return", than)

    def test_van_khai_o_cua_vao_de_luot_hong_som_co_dau(self):
        """Hỏng ngay trong `build_body` thì vòng khoá chưa chạy tới — cửa vào
        `_handle_single_image` vẫn phải khai provider + model."""
        i = MA.index("def _handle_single_image")
        self.assertIn("note_provider_account(route.provider, model=route.model)",
                      MA[i:i + 1500])


if __name__ == "__main__":
    unittest.main()
