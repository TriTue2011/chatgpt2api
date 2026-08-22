"""Hai lỗ còn lại của luồng Vision, phát hiện khi soi lại bản vá aa4832b.

1. Model chỉ ĐÍCH DANH mà sai vẫn trả HTTP 200 bằng model KHÁC. Bản trước chỉ
   đổi log từ info sang warning — người dùng tưởng dùng A, thực tế nhận B.
2. Các đường vision chat vẫn `b64decode` data-URL KHÔNG giới hạn, trong khi
   nhánh URL http ngay cạnh đã có `max_bytes`. Client chỉ cần đổi link sang
   data-URL là đi vòng qua hết mọi trần.
"""
import base64
import io
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from fastapi import HTTPException  # noqa: E402

from services import image_guard  # noqa: E402
from services.image_guard import ImageRejected, giai_ma_data_url  # noqa: E402


def _png_data_url(rong: int, cao: int) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (rong, cao), (10, 20, 30)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class DataUrlCoTranTests(unittest.TestCase):
    def test_anh_binh_thuong_giai_ma_duoc(self):
        data, mime = giai_ma_data_url(_png_data_url(64, 48))
        self.assertEqual(mime, "image/png")
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_chuoi_base64_qua_dai_bi_chan_TRUOC_khi_giai_ma(self):
        """`b64decode` cấp phát bản giải mã rồi mới trả về — đo sau là RAM đã mất."""
        goi = []
        that = base64.b64decode

        def _theo_doi(*a, **k):
            goi.append(1)
            return that(*a, **k)

        base64.b64decode = _theo_doi
        try:
            with self.assertRaises(ImageRejected):
                giai_ma_data_url("data:image/png;base64," + "A" * 60_000_000)
        finally:
            base64.b64decode = that
        self.assertEqual(goi, [], "đã giải mã dù biết trước là quá trần")

    def test_bom_nen_qua_data_url_bi_chan(self):
        with self.assertRaises(ImageRejected) as ctx:
            giai_ma_data_url(_png_data_url(12000, 12000))
        self.assertIn("điểm ảnh", str(ctx.exception))

    def test_khong_phai_anh_bi_chan(self):
        gia = "data:image/png;base64," + base64.b64encode(b"%PDF-1.7 khong phai anh").decode()
        with self.assertRaises(ImageRejected):
            giai_ma_data_url(gia)

    def test_data_url_hong_bi_chan(self):
        with self.assertRaises(ImageRejected):
            giai_ma_data_url("data:image/png;base64")   # thiếu dấu phẩy


class MoiDuongVisionDeuQuaHangRaoTests(unittest.TestCase):
    """Ba đường vision chat phải dùng CHUNG helper, không tự b64decode."""

    DUONG = {
        "api/gemini_web.py": "ảnh gửi Gemini",
        "api/claude.py": "ảnh gửi Claude",
        "services/openai_backend_api.py": "ảnh gửi ChatGPT",
    }

    def test_deu_goi_giai_ma_data_url(self):
        for tep in self.DUONG:
            src = (GOC / tep).read_text(encoding="utf-8")
            self.assertIn("giai_ma_data_url", src, f"{tep} chưa dùng hàng rào chung")

    def test_khong_con_b64decode_tran_lan_o_nhanh_anh(self):
        """Không còn `base64.b64decode(b64)` thô ở nhánh data-URL của ảnh."""
        for tep in self.DUONG:
            src = (GOC / tep).read_text(encoding="utf-8")
            self.assertNotIn("base64.b64decode(b64)", src,
                             f"{tep} còn giải mã ảnh không qua trần")

    def test_khong_am_tham_bo_anh(self):
        """Bỏ ảnh im lặng rồi vẫn gọi model = 'phân tích ảnh' mà không có ảnh."""
        for tep in self.DUONG:
            src = (GOC / tep).read_text(encoding="utf-8")
            i = src.index("giai_ma_data_url")
            self.assertIn("HTTPException", src[i:i + 700],
                          f"{tep} phải báo lỗi rõ ràng thay vì bỏ qua ảnh")


class _ModelGia:
    """`Model.from_name` giả — nhận đúng bộ tên mà gemini_webapi thật có."""

    HOP_LE = {"gemini-3-flash", "gemini-3-flash-advanced", "gemini-3-flash-thinking",
              "gemini-3-pro", "gemini-3-pro-advanced"}

    def __init__(self, ten: str) -> None:
        self.ten = ten

    @classmethod
    def from_name(cls, ten: str):
        if ten not in cls.HOP_LE:
            raise ValueError(f"unknown model: {ten}")
        return cls(ten)


class _GeminiClientCu:
    """gemini-webapi CŨ: không có registry động, `_resolve_model` tự quyết."""


class _GeminiClientMoi:
    """gemini-webapi MỚI: có registry động nên `_resolve_model` hoãn phán xét."""

    def list_models(self):
        return []

    def resolve_model(self, ten):
        raise ValueError(ten)


class _ClientKhongCoModel:
    """Một account cụ thể không có model được hỏi."""

    def resolve_model(self, ten):
        raise ValueError(ten)


class ModelSaiPhaiBaoLoiTests(unittest.TestCase):
    """Dựng `gemini_webapi.constants` giả để test không phụ thuộc thư viện thật.

    Cần vậy vì chính test này đã bắt ra một lỗi suýt ship: khi thư viện KHÔNG
    nạp được, bản đầu gộp chung với "tên model sai" nên MỌI model hợp lệ đều
    trả 400 — hỏng hẳn kênh Gemini vì một lý do chẳng liên quan tới người gọi.
    """

    def setUp(self):
        import types
        from api import gemini_web as _gma
        self._cu = {ten: sys.modules.get(ten)
                    for ten in ("gemini_webapi", "gemini_webapi.constants")}
        # `setdefault` là SAI ở đây: khi thư viện thật đã được nạp, gói giả bị
        # bỏ qua lặng lẽ và `_resolve_model` đi theo nhánh của bản thật. Đó là
        # lý do bộ test này đậu ở máy dev (chưa cài gemini-webapi) mà đỏ trên
        # CI (`uv sync --frozen` cài đủ). Thay hẳn để test tự quyết hình dạng
        # thư viện mà nó đang mô phỏng.
        goi = types.ModuleType("gemini_webapi")
        goi.GeminiClient = _GeminiClientCu
        hang_so = types.ModuleType("gemini_webapi.constants")
        hang_so.Model = _ModelGia
        sys.modules["gemini_webapi"] = goi
        sys.modules["gemini_webapi.constants"] = hang_so
        self._goi = goi
        # Registry rỗng: còn client nào warm thì `_resolve_model` hoãn 400 lại
        # cho vòng account, và kết quả phụ thuộc file test nào chạy trước.
        self._clients_cu = _gma._clients
        _gma._clients = {}
        self._gma = _gma

    def tearDown(self):
        self._gma._clients = self._clients_cu
        for ten, cu in self._cu.items():
            if cu is None:
                sys.modules.pop(ten, None)
            else:
                sys.modules[ten] = cu

    def test_model_chi_dinh_khong_ton_tai_thi_400(self):
        """Thư viện CŨ: `_resolve_model` là chỗ duy nhất biết model có thật không."""
        from api.gemini_web import _resolve_model
        with self.assertRaises(HTTPException) as ctx:
            _resolve_model("gma/3.6-flash")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail.get("code"), "model_not_found")

    def test_thu_vien_moi_hoan_400_lai_cho_vong_account(self):
        """Thư viện MỚI: registry chỉ đầy đủ sau khi từng account init, nên
        `_resolve_model` cho tên đi tiếp — nhưng lời hứa với người gọi KHÔNG
        đổi, chỉ dời xuống `_model_for_client`. Không có ca này thì việc dời
        tầng biến thành âm thầm trả HTTP 200 bằng model khác.
        """
        from api import gemini_web as gma
        self._goi.GeminiClient = _GeminiClientMoi

        self.assertEqual(gma._resolve_model("gma/3.6-flash"), "3.6-flash")

        with self.assertRaises(gma._ModelUnavailable):
            gma._model_for_client(_ClientKhongCoModel(), "3.6-flash")
        loi = gma._model_unavailable_http("3.6-flash")
        self.assertEqual(loi.status_code, 400)
        self.assertEqual(loi.detail.get("code"), "model_not_found")

    def test_auto_van_duoc_roi_ve_mac_dinh(self):
        """Người gọi không khai model nào thì không có gì để mà sai."""
        from api.gemini_web import _resolve_model
        try:
            _resolve_model("gma/auto")
        except HTTPException:
            self.fail("auto không được ném model_not_found")

    def test_alias_cu_van_chay(self):
        from api.gemini_web import _resolve_model
        for m in ("gma/3.5-flash", "gma/flash", "gma/3.1-pro", "gma/3.1-flash",
                  "gma/3.1-flash-thu-nghiem"):
            try:
                _resolve_model(m)
            except HTTPException:
                self.fail(f"{m} là alias hợp lệ, không được từ chối")

    def test_thu_vien_thieu_thi_KHONG_do_loi_cho_nguoi_goi(self):
        """Import hỏng là lỗi bản triển khai — không được biến thành 400."""
        sys.modules["gemini_webapi.constants"] = None   # ép import thất bại
        from api.gemini_web import _resolve_model
        try:
            self.assertIsNone(_resolve_model("gma/3.5-flash"))
        except HTTPException:
            self.fail("thư viện thiếu mà lại trả model_not_found cho model hợp lệ")


if __name__ == "__main__":
    unittest.main()
