"""Yêu cầu tạo ẢNH không được biến thành video — và ngược lại.

SỰ CỐ THẬT 08/08/2026. Một request `/v1/images/generations` (combo "AI image")
chạy 98 giây rồi trừ tín dụng **video Omni Flash 8 giây** của tài khoản Flow.

Chuỗi nhân quả, không có bước nào báo lỗi:

  1. Bộ lái chọn model bằng cách bấm dropdown trên giao diện Flow.
     `_set_dropdown` trả `False` khi không tìm thấy nhãn, nhưng nơi gọi ở đường
     ẢNH bỏ qua giá trị trả về rồi bấm Tạo luôn.
  2. Không tìm thấy nhãn thì dropdown GIỮ NGUYÊN lựa chọn của lượt trước — lượt
     đó là video Omni Flash 8s.
  3. Nhãn không tìm thấy thật, vì hai bảng tên lệch nhau: phía dịch vụ gửi
     `NARWHAL` và `IMAGEN_3_5`, còn bảng nhãn bên bộ lái chỉ biết
     `NANO_BANANA_2` và `IMAGEN_4`. Combo "AI image" chứa cả `flow/banana-2` lẫn
     `flow/imagen-4`, nên hai trong sáu bước Flow của nó đều rơi vào đây.

Đường VIDEO đã có bảo vệ này từ 02/08 (đọc ngược model đang chọn rồi so, lệch
thì dừng trước khi bấm Tạo). Đường ẢNH thì không có gì — nên nó mới là cái hỏng.

Test ở đây chốt cả hai đường, và chốt luôn ràng buộc giữa hai file để lần sau
thêm model mới mà quên nhãn thì đỏ ngay, chứ không phải chờ mất tín dụng.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]

DICH_VU = (GOC / "services/image_providers/flow_google.py").read_text(encoding="utf-8")
BO_LAI = (GOC / "captcha-solver/src/solvers/flow_google.py").read_text(encoding="utf-8")


def _cac_dict(nguon: str, ten: str) -> list[dict]:
    """Mọi dict literal gán cho `ten` trong file, theo thứ tự xuất hiện.

    Dùng `ast` chứ không cắt chuỗi: hai bảng cần đọc đều nằm TRONG thân hàm, và
    cắt theo dấu ngoặc thì gãy ngay khi ai đó thụt lề khác đi.
    """
    ra = []
    for nut in ast.walk(ast.parse(nguon)):
        if isinstance(nut, ast.Assign) and isinstance(nut.value, ast.Dict):
            for dich in nut.targets:
                if isinstance(dich, ast.Name) and dich.id == ten:
                    ra.append((nut.lineno, ast.literal_eval(nut.value)))
    return [d for _, d in sorted(ra)]


ALIAS = _cac_dict(DICH_VU, "_MODEL_ALIASES")[0]
# Có HAI bảng `_MODEL_LABEL`: một trong `generate_image`, một trong hàm video.
NHAN_ANH, NHAN_VIDEO = _cac_dict(BO_LAI, "_MODEL_LABEL")[:2]


class HaiFileNoiCungMotThuTests(unittest.TestCase):
    """Ràng buộc đã bị gãy: tên phía dịch vụ gửi ≠ tên bộ lái biết dịch."""

    def test_MOI_ten_noi_bo_gui_di_deu_co_nhan_tuong_ung(self):
        thieu = sorted({v for v in ALIAS.values()} - set(NHAN_ANH))
        self.assertEqual(thieu, [], f"bộ lái không biết dịch: {thieu} — dropdown "
                                    f"sẽ bấm hụt và Flow dùng model của lượt trước")

    def test_hai_ten_da_gay_ra_su_co_deu_co_mat(self):
        self.assertEqual(NHAN_ANH.get("NARWHAL"), "Nano Banana 2")
        self.assertEqual(NHAN_ANH.get("IMAGEN_3_5"), "Imagen 4")

    def test_FLOW_MODELS_khai_dung_ten_noi_bo_that(self):
        """Trường `internal` ở đây từng ghi IMAGEN_4 trong khi alias gửi
        IMAGEN_3_5 — chính sự bất nhất đó làm bảng nhãn trông như đã đủ."""
        i = DICH_VU.index("FLOW_MODELS = [")
        khoi = DICH_VU[i:DICH_VU.index("\n]", i)]
        for m in re.finditer(r'"id":\s*"flow/([\w.-]+)".*?"internal":\s*"(\w+)"', khoi):
            ten, noi_bo = m.group(1), m.group(2)
            self.assertEqual(ALIAS.get(ten), noi_bo,
                             f"flow/{ten}: FLOW_MODELS nói {noi_bo}, alias gửi {ALIAS.get(ten)}")


class DuongAnhPhaiKiemChungTests(unittest.TestCase):
    def _khoi_anh(self) -> str:
        i = BO_LAI.index("KIỂM CHỨNG MODEL — giống hệt cách đường VIDEO")
        return BO_LAI[i:i + 2600]

    def test_doc_NGUOC_model_dang_chon_chu_khong_chi_tin_cu_bam(self):
        """`_set_dropdown` có nhánh trả `clicked` — nghĩa là 'đã bấm một cái gì
        đó', không phải 'đã chọn đúng mục'."""
        khoi = self._khoi_anh()
        self.assertIn("_model_that", khoi)
        self.assertIn("arrow_drop_down", khoi, "chưa đọc chip model trên giao diện")

    def test_LECH_model_thi_KHONG_bam_Tao(self):
        khoi = self._khoi_anh()
        i = khoi.index("_chuan(model_label) not in _chuan(_model_that)")
        self.assertIn("raise RuntimeError", khoi[i:i + 400])
        self.assertIn("chưa bấm Tạo", khoi[i:i + 700])

    def test_khong_dat_duoc_va_khong_doc_duoc_cung_phai_dung(self):
        """Hai cái cùng trượt là lúc mù hoàn toàn — càng phải dừng."""
        khoi = self._khoi_anh()
        i = khoi.index("if not _dat_ok and not _model_that")
        self.assertIn("raise RuntimeError", khoi[i:i + 400])

    def test_chi_MODEL_moi_dung_lai_chu_khong_phai_moi_dropdown(self):
        """Tỉ lệ khung hình hay số lượng bấm hụt chỉ ra ảnh sai cỡ — dừng cả
        request vì chuyện đó là đổi một phiền toái rẻ lấy một lỗi đắt."""
        i = BO_LAI.index('_set_dropdown(page, aspect_label, "aspect")')
        self.assertNotIn("raise", BO_LAI[i:i + 120])


class DuongVideoGiuNguyenBaoVeTests(unittest.TestCase):
    """Đường video đã đúng từ 02/08 — chốt lại để đừng ai gỡ ra."""

    def test_van_so_model_doc_nguoc_truoc_khi_tao(self):
        i = BO_LAI.index("_dat_model_ok = await _set_dropdown")
        khoi = BO_LAI[i:i + 2000]
        self.assertIn("model_mismatch", khoi)
        self.assertIn("Chưa bấm Tạo", khoi)

    def test_van_chan_ca_truong_hop_khong_doc_duoc(self):
        i = BO_LAI.index("_dat_model_ok = await _set_dropdown")
        self.assertIn("model_unverified", BO_LAI[i:i + 2400])

    def test_nhan_video_du_cho_moi_model_key(self):
        anh_xa = _cac_dict(BO_LAI, "model_name_map")[0]
        thieu = sorted({v for v in anh_xa.values()} - set(NHAN_VIDEO))
        self.assertEqual(thieu, [], f"model video không có nhãn: {thieu}")


class KhongLanLoaiTests(unittest.TestCase):
    def test_bo_giai_model_ANH_tu_choi_ten_model_VIDEO(self):
        """Lớp chặn thứ hai: kể cả khi cấu hình đẩy nhầm tên video vào đường
        ảnh, `_resolve_model` cũng không cho nó đi tiếp."""
        import os
        import sys
        sys.path.insert(0, str(GOC))
        os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")
        from services.image_providers.flow_google import _resolve_model
        with self.assertRaises(ValueError):
            _resolve_model("flow/omni-flash")


if __name__ == "__main__":
    unittest.main()
