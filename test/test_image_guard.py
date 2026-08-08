"""Hàng rào ảnh dùng chung: bom nén, magic bytes, trần số ảnh và tổng dung lượng.

Vì sao cần: trần BYTE không chặn được ảnh bom nén. Một file PNG vài chục KB khai
báo được 50.000×50.000 điểm ảnh; Pillow giải nén ra là hàng GB RAM, mà trần byte
hoàn toàn vô can vì file thật sự nhỏ.

Và trước bản này hai đường upload ảnh có luật LỆCH nhau: `/v1/images/edits` giới
hạn 8 ảnh / 20MB mỗi ảnh / 48MB tổng, còn `/api/image-tasks/edits` chỉ giới hạn
50MB mỗi tệp — không giới hạn số ảnh, không giới hạn tổng. Cùng một người dùng
chỉ cần đổi cửa là lách sạch.
"""
import io
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import image_guard  # noqa: E402
from services.image_guard import ImageRejected, kiem_anh, kiem_bo_anh  # noqa: E402


def _anh_png(rong: int, cao: int) -> bytes:
    """PNG thật, kích thước tuỳ ý. Ảnh một màu nên nén rất mạnh — đúng hình dạng
    của một quả bom nén: file bé, kích thước khai báo lớn."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (rong, cao), (0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class BomNenTests(unittest.TestCase):
    def test_anh_qua_nhieu_diem_anh_bi_chan(self):
        """File NHỎ nhưng khai báo kích thước khổng lồ — trần byte không thấy gì."""
        raw = _anh_png(12000, 12000)   # 144 triệu điểm ảnh, trần 50 triệu
        self.assertLess(len(raw), image_guard.MAX_IMAGE_BYTES,
                        "test phải dùng file DƯỚI trần byte, nếu không là kiểm nhầm thứ")
        with self.assertRaises(ImageRejected) as ctx:
            kiem_anh(raw)
        self.assertIn("điểm ảnh", str(ctx.exception))

    def test_anh_canh_qua_dai_bi_chan(self):
        raw = _anh_png(25000, 10)      # cạnh 25.000 > trần 20.000
        with self.assertRaises(ImageRejected) as ctx:
            kiem_anh(raw)
        self.assertIn("cạnh quá dài", str(ctx.exception))

    def test_anh_binh_thuong_van_qua(self):
        self.assertEqual(kiem_anh(_anh_png(800, 600)), "image/png")


class MagicBytesTests(unittest.TestCase):
    def test_khong_phai_anh_bi_chan(self):
        for raw, ten in (
            (b"%PDF-1.7\n%...", "pdf"),
            (b"<!doctype html><html><body>loi</body></html>", "html"),
            (b'{"error":"khong tim thay"}', "json"),
        ):
            with self.assertRaises(ImageRejected, msg=ten):
                kiem_anh(raw, ten=ten)

    def test_tep_rong_bi_chan(self):
        with self.assertRaises(ImageRejected):
            kiem_anh(b"")

    def test_qua_tran_byte_bi_chan(self):
        with self.assertRaises(ImageRejected) as ctx:
            kiem_anh(b"\xff\xd8\xff" + b"x" * 100, max_bytes=50)
        self.assertIn("quá lớn", str(ctx.exception))


class BoAnhTests(unittest.TestCase):
    def _bo(self, n: int, rong: int = 64, cao: int = 64):
        raw = _anh_png(rong, cao)
        return [(raw, f"a{i}.png", "image/png") for i in range(n)]

    def test_qua_nhieu_anh_bi_chan(self):
        with self.assertRaises(ImageRejected) as ctx:
            kiem_bo_anh(self._bo(image_guard.MAX_IMAGES_PER_REQUEST + 1))
        self.assertIn("Quá nhiều ảnh", str(ctx.exception))

    def test_dung_so_luong_thi_qua(self):
        kiem_bo_anh(self._bo(image_guard.MAX_IMAGES_PER_REQUEST))

    def test_tong_dung_luong_vuot_tran_bi_chan(self):
        raw = _anh_png(64, 64)
        bo = [(raw, "a.png", "image/png")] * 4
        with self.assertRaises(ImageRejected) as ctx:
            kiem_bo_anh(bo, max_total=len(raw) * 2)
        self.assertIn("Tổng dung lượng", str(ctx.exception))

    def test_mot_anh_hong_lam_ca_lo_bi_tu_choi(self):
        bo = self._bo(2) + [(b"%PDF-1.7", "gia.png", "image/png")]
        with self.assertRaises(ImageRejected):
            kiem_bo_anh(bo)


class DungChungTranTests(unittest.TestCase):
    """Hai đường upload ảnh phải dùng CÙNG hằng số — đây là lỗi gốc lần trước.

    Kiểm ở mức mã nguồn thay vì import `api.ai`: import nó kéo theo cả FastAPI và
    toàn bộ tầng provider, biến một test đơn vị thành test tích hợp.
    """

    def _nguon(self, duong_dan: str) -> str:
        return (GOC / duong_dan).read_text(encoding="utf-8")

    def test_images_edits_lay_tran_tu_image_guard(self):
        src = self._nguon("api/ai.py")
        for hang in ("image_guard.MAX_IMAGE_BYTES",
                     "image_guard.MAX_IMAGES_PER_REQUEST",
                     "image_guard.MAX_TOTAL_IMAGE_BYTES"):
            self.assertIn(hang, src, f"/v1/images/edits phải lấy {hang} thay vì tự đặt số")
        self.assertIn("kiem_bo_anh", src, "/v1/images/edits phải kiểm nội dung ảnh")

    def test_image_tasks_dung_cung_tran_va_kiem_noi_dung(self):
        src = self._nguon("api/image_tasks.py")
        for hang in ("image_guard.MAX_IMAGES_PER_REQUEST",
                     "image_guard.MAX_IMAGE_BYTES",
                     "image_guard.MAX_TOTAL_IMAGE_BYTES"):
            self.assertIn(hang, src, f"/api/image-tasks/edits phải dùng {hang}")
        self.assertIn("kiem_bo_anh", src)
        self.assertIn("TaskQueueFull", src, "quá tải phải trả 429, không xếp hàng vô hạn")


if __name__ == "__main__":
    unittest.main()
