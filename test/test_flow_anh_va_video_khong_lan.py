"""Flow giữ model ảnh và model video chung một tên miền — đừng để chúng lẫn.

Provider `flow` phơi ra tám model trong CÙNG một nhóm: bốn model ảnh
(`flow/auto`, `banana-pro`, `banana-2`, `banana-2-lite`) và bốn model video
(`omni-flash`, `veo-3.1-lite/fast/quality`). Tab Quản lý Model gom chúng thành
một thẻ với MỘT ô "Đặt mặc định".

Nhưng chỉ đường ẢNH đọc ô đó. `services/protocol/openai_v1_image_generations.py`
gọi `backend_router.route()`, còn `api/veo_video.py` nhận tên model nguyên văn và
không đi qua router. Hậu quả lệch hẳn một bên:

    đặt mặc định = model video  →  ĐƯỜNG ẢNH lấy nhầm tên đó
    đặt mặc định = model ảnh    →  video không đổi gì (nó không đọc)

Và khi một tên veo lọt vào đường ảnh thì `flow_google._resolve_model` không biết
alias đó nên trả về chính chuỗi viết hoa — `"VEO-3.1-FAST"` — rồi gửi cho Flow
làm `imageModelName`. Hỏng, mà thông báo lỗi không nói gì về nguyên nhân.

Rủi ro lớn hơn nằm ở các ô TICK chứ không phải ô mặc định: bỏ tick hết model ảnh
và chỉ giữ veo thì `flow/auto` rơi xuống `real_models[0]` — một tên video — mà
không ai chạm vào ô mặc định lần nào.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backend_router import backend_router, la_model_video  # noqa: E402
from services.config import config  # noqa: E402
from services.image_providers.flow_google import _resolve_model  # noqa: E402
from utils.helper import VIDEO_GEN_MODELS  # noqa: E402

ANH = ["flow/banana-pro", "flow/banana-2", "flow/imagen-4"]
VIDEO = ["flow/veo-3.1-fast", "flow/veo-3.1-lite", "flow/veo-3.1-quality",
         "flow/omni-flash"]


class NhanDienLoaiTests(unittest.TestCase):
    def test_bon_model_video_cua_flow_deu_duoc_nhan_ra(self):
        for m in VIDEO:
            self.assertTrue(la_model_video("flow", m), m)

    def test_nhan_ra_ca_khi_khong_co_tien_to(self):
        """Trong `enabled_models` model có thể ghi cả hai dạng."""
        self.assertTrue(la_model_video("flow", "veo-3.1-fast"))

    def test_model_anh_KHONG_bi_nham_la_video(self):
        for m in ANH + ["flow/auto", "auto", ""]:
            self.assertFalse(la_model_video("flow", m), m)


class MacDinhVideo_KhongDuocRoiVaoDuongAnhTests(unittest.TestCase):
    def setUp(self):
        self._cu = config.data
        self.addCleanup(lambda: setattr(config, "data", self._cu))

    def _dat(self, mac_dinh=None, tick=None):
        ms = {}
        if mac_dinh is not None:
            ms["default_models"] = {"flow": mac_dinh}
        if tick is not None:
            ms["enabled_models"] = {"flow": tick}
        config.data = {"model_settings": ms, "providers": {"flow": {}}}

    def test_dat_model_VIDEO_lam_mac_dinh_thi_anh_KHONG_lay_no(self):
        """Đây là đúng điều chủ máy lo: một ô mặc định cho hai loại."""
        self._dat(mac_dinh="flow/veo-3.1-fast")
        ra = backend_router.route("flow/auto")
        self.assertNotIn("veo", ra.model, f"đường ảnh lấy nhầm model video: {ra.model}")

    def test_dat_model_ANH_lam_mac_dinh_thi_van_dung_binh_thuong(self):
        """Chặn model video không được làm hỏng đường đi đúng."""
        self._dat(mac_dinh="flow/imagen-4")
        self.assertEqual(backend_router.route("flow/auto").model, "imagen-4")

    def test_BO_TICK_het_model_anh_thi_anh_van_khong_roi_vao_veo(self):
        """Đường hỏng thứ hai, không cần đụng ô mặc định lần nào."""
        self._dat(tick=VIDEO)
        ra = backend_router.route("flow/auto")
        self.assertNotIn("veo", ra.model)
        self.assertNotIn("omni", ra.model)

    def test_tick_ca_hai_loai_thi_anh_chon_dung_model_ANH_dau_tien(self):
        self._dat(tick=VIDEO + ANH)
        self.assertEqual(backend_router.route("flow/auto").model, "banana-pro")

    def test_van_ve_dung_provider_flow(self):
        self._dat(mac_dinh="flow/veo-3.1-fast")
        ra = backend_router.route("flow/auto")
        self.assertEqual(ra.provider, "flow")
        self.assertTrue(ra.is_image)

    def test_chi_MODEL_video_bi_bo_QUA_chu_khong_bo_ca_bo_loc(self):
        """Bỏ nguyên bộ lọc khi gặp model video sẽ làm tick của người dùng mất
        tác dụng — model đã bỏ tick lại hiện ra."""
        self._dat(tick=["flow/veo-3.1-fast", "flow/banana-2-lite"])
        self.assertEqual(backend_router.route("flow/auto").model, "banana-2-lite")


class ResolveModelTests(unittest.TestCase):
    def test_tra_dung_ten_noi_bo_cho_model_anh(self):
        """Tên nội bộ đã đo thẳng vào API 09/08/2026 — xem chú thích ở
        `_MODEL_ALIASES`. `NANO_BANANA_PRO` (giá trị cũ của auto/banana-pro)
        chưa từng là hằng số có thật: API trả 400 INVALID_ARGUMENT."""
        self.assertEqual(_resolve_model("flow/banana-pro"), "GEM_PIX_2")
        self.assertEqual(_resolve_model("flow/banana-2"), "NARWHAL")
        self.assertEqual(_resolve_model("flow/banana-2-lite"), "HARBOR_SEAL")
        self.assertEqual(_resolve_model("flow/auto"), "GEM_PIX_2")
        self.assertEqual(_resolve_model(""), "GEM_PIX_2")

    def test_ten_model_VIDEO_bi_TU_CHOI_chu_khong_viet_hoa_roi_gui_di(self):
        for m in VIDEO:
            with self.assertRaises(ValueError, msg=m) as ctx:
                _resolve_model(m)
            loi = str(ctx.exception)
            self.assertIn("VIDEO", loi)
            self.assertIn("flow/banana-pro", loi, "lỗi phải chỉ ra model dùng được")

    def test_model_anh_DA_BO_bi_tu_choi_kem_ly_do(self):
        """Cấu hình đang chạy là dữ liệu, không phải mã.

        Gỡ `flow/imagen-4` khỏi bảng bí danh không gỡ nó khỏi Quản lý Model của
        một hệ thống đang chạy. Nếu để nó rơi xuống nhánh "tên lạ" thì ta gửi
        `imageModelName: "IMAGEN-4"` — chuỗi vô nghĩa — và nhận về 400 không nêu
        trường nào sai, đúng kiểu lỗi tốn cả buổi để lần ra.
        """
        for m in ("flow/imagen-4", "flow/imagen", "imagen-3-5"):
            with self.assertRaises(ValueError, msg=m) as ctx:
                _resolve_model(m)
            loi = str(ctx.exception)
            self.assertIn("ĐÃ BỎ", loi)
            self.assertIn("flow/banana-pro", loi, "lỗi phải chỉ ra model dùng được")

    def test_ten_LA_van_di_qua_duoc(self):
        """Chặn hẳn tên lạ sẽ khiến model ảnh mới của Flow phải chờ sửa mã."""
        self.assertEqual(_resolve_model("flow/model-moi-nao-do"), "MODEL-MOI-NAO-DO")


class MotNguonSuThatTests(unittest.TestCase):
    def test_backend_TU_KHAI_dau_la_model_video(self):
        """Giao diện đoán theo tên là sai sớm muộn — `omni-flash` không có chữ
        'video' nào trong tên."""
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        i = src.index('@router.get("/api/v1/available-models")')
        than = src[i:i + 2000]
        self.assertIn('"video_models"', than)
        self.assertIn("classify_model_capability", than)

    def test_giao_dien_LAY_danh_sach_do_chu_khong_tu_doan(self):
        trang = (GOC / "web/src/app/models/page.tsx").read_text(encoding="utf-8")
        self.assertIn("video_models", trang)
        self.assertNotIn('includes("veo")', trang)

    def test_khoi_video_KHONG_co_nut_dat_mac_dinh(self):
        """Nút đó vô tác dụng với video và làm hỏng ảnh — đừng bày ra."""
        trang = (GOC / "web/src/app/models/page.tsx").read_text(encoding="utf-8")
        i = trang.index("Model tạo video")
        khoi = trang[i:trang.index("end collapsed")]
        self.assertNotIn("setDefault", khoi)
        self.assertIn("tab Tạo Video", khoi, "phải nói model video chọn ở đâu")

    def test_danh_sach_video_van_la_bon_model_flow(self):
        """Chốt lại tập nguồn để một lần đổi tên không lặng lẽ mở lại lỗ hổng."""
        self.assertEqual(VIDEO_GEN_MODELS, set(VIDEO))


if __name__ == "__main__":
    unittest.main()
