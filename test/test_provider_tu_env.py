"""Khai model chạy tại nhà bằng biến môi trường thay vì gọi API bằng tay.

Khai tay qua `POST /api/v1/custom-providers` có một cái bẫy: mỗi lần dựng lại
máy hay đổi IP máy GPU đều phải nhớ gọi lại, và quên thì model local lặng lẽ
biến mất khỏi danh sách — automation vẫn chạy nhưng rơi sang model khác mà
không báo gì. Đặt `VISION_URL_GPU` trong compose thì hạ tầng tự khai.

Quy tắc quan trọng: trùng khoá thì CONFIG thắng ENV. Người vận hành sửa trên
giao diện là có chủ ý; để một biến môi trường cũ ghi đè lựa chọn đó là kiểu
lỗi rất khó lần ra.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.pure


@pytest.fixture()
def sach(monkeypatch):
    """Config trống + không có biến env nào, để mỗi phép thử tự dựng cảnh."""
    from services.config import config
    monkeypatch.setattr(config, "data", {}, raising=False)
    for b in ("VISION_URL_GPU", "VISION_URL_GPU_KEY", "OLLAMA_URL", "OLLAMA_URL_KEY"):
        monkeypatch.delenv(b, raising=False)
    # Biến C2A_PROVIDER_* của máy chạy test không được lọt vào phép thử.
    for b in list(os.environ):
        if b.startswith("C2A_PROVIDER_"):
            monkeypatch.delenv(b, raising=False)
    from services.providers import custom_openai
    # Cảnh báo chỉ ghi một lần mỗi biến — mỗi phép thử phải bắt đầu với sổ trống.
    monkeypatch.setattr(custom_openai, "_da_canh_bao", set())
    return custom_openai


class TestKhaiBangEnv:
    def test_khong_dat_bien_thi_khong_co_gi(self, sach):
        assert "lv" not in sach.get_custom_providers()

    def test_dat_bien_thi_tu_hien_provider(self, sach, monkeypatch):
        monkeypatch.setenv("VISION_URL_GPU", "http://172.16.10.220:5003/v1")
        p = sach.get_custom_providers().get("lv")
        assert p, "đặt VISION_URL_GPU mà không thấy provider"
        assert p["base_url"] == "http://172.16.10.220:5003/v1"
        assert p["prefix"] == "lv" and p["enabled"] is True

    def test_khai_gon_khong_co_v1_van_dung(self, sach, monkeypatch):
        """Thiếu '/v1' là lỗi đánh máy dễ gặp, và hậu quả là model im lặng
        không hiện ra — nên tự thêm thay vì bắt người dùng tự dò."""
        monkeypatch.setenv("VISION_URL_GPU", "http://192.168.1.10:5003")
        assert sach.get_custom_providers()["lv"]["base_url"] == "http://192.168.1.10:5003/v1"

    def test_bo_dau_gach_thua_cuoi(self, sach, monkeypatch):
        monkeypatch.setenv("VISION_URL_GPU", "http://192.168.1.10:5003/v1/")
        assert sach.get_custom_providers()["lv"]["base_url"] == "http://192.168.1.10:5003/v1"

    def test_khoa_rieng_khi_can(self, sach, monkeypatch):
        monkeypatch.setenv("VISION_URL_GPU", "http://x:5003/v1")
        monkeypatch.setenv("VISION_URL_GPU_KEY", "bi-mat")
        assert sach.get_custom_providers()["lv"]["api_key"] == "bi-mat"

    def test_khong_khai_khoa_thi_dung_local(self, sach, monkeypatch):
        monkeypatch.setenv("VISION_URL_GPU", "http://x:5003/v1")
        assert sach.get_custom_providers()["lv"]["api_key"] == "local"


class TestConfigThangEnv:
    def test_config_de_len_env_khi_trung_khoa(self, sach, monkeypatch):
        from services.config import config
        monkeypatch.setenv("VISION_URL_GPU", "http://cu:5003/v1")
        monkeypatch.setattr(config, "data", {"custom_providers": {"lv": {
            "name": "sửa tay", "prefix": "lv", "base_url": "http://moi:9999/v1", "enabled": True}}},
            raising=False)
        assert sach.get_custom_providers()["lv"]["base_url"] == "http://moi:9999/v1"

    def test_provider_khac_trong_config_van_con(self, sach, monkeypatch):
        from services.config import config
        monkeypatch.setenv("VISION_URL_GPU", "http://x:5003/v1")
        monkeypatch.setattr(config, "data", {"custom_providers": {"agnes": {
            "name": "Agnes", "prefix": "agnes", "base_url": "https://a/v1", "enabled": True}}},
            raising=False)
        ds = sach.get_custom_providers()
        assert set(ds) == {"lv", "agnes"}, "env và config phải cộng nhau, không thay nhau"

    def test_provider_bi_tat_thi_khong_hien(self, sach, monkeypatch):
        from services.config import config
        monkeypatch.setenv("VISION_URL_GPU", "http://x:5003/v1")
        monkeypatch.setattr(config, "data", {"custom_providers": {"lv": {
            "prefix": "lv", "base_url": "http://x/v1", "enabled": False}}}, raising=False)
        assert "lv" not in sach.get_custom_providers()


class TestOllamaCungCoChe:
    def test_ollama_tu_hien_khi_dat_bien(self, sach, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://172.16.10.220:11434")
        p = sach.get_custom_providers().get("ol")
        assert p, "đặt OLLAMA_URL mà không thấy provider"
        assert p["base_url"] == "http://172.16.10.220:11434/v1", "Ollama phục vụ giao diện OpenAI ở /v1"

    def test_hai_may_cung_luc(self, sach, monkeypatch):
        """Máy thị giác và máy Ollama là hai nguồn riêng, phải cùng hiện."""
        monkeypatch.setenv("VISION_URL_GPU", "http://a:5003")
        monkeypatch.setenv("OLLAMA_URL", "http://b:11434")
        ds = sach.get_custom_providers()
        assert set(ds) == {"lv", "ol"}
        assert ds["lv"]["base_url"] == "http://a:5003/v1"
        assert ds["ol"]["base_url"] == "http://b:11434/v1"


class _GhiLog:
    def __init__(self):
        self.canh_bao: list[dict] = []

    def warning(self, msg):
        self.canh_bao.append(msg)

    def info(self, msg):
        pass

    def error(self, msg):
        pass


class TestKhaiTheoNguyenTac:
    """Module mới không cần sửa code: mọi `C2A_PROVIDER_<ID>_URL` là một provider.

    Danh sách gõ tay `_PROVIDER_TU_ENV` chỉ có hai tên; thêm máy thứ ba là phải
    sửa code — đúng lớp lỗi «danh sách gõ tay → module mới bị bỏ ở ngoài».
    """

    def test_bien_moi_tu_thanh_provider(self, sach, monkeypatch):
        monkeypatch.setenv("C2A_PROVIDER_MAY_GPU_URL", "http://172.16.10.220:8000/")
        p = sach.get_custom_providers().get("may_gpu")
        assert p, "đặt C2A_PROVIDER_MAY_GPU_URL mà không thấy provider"
        assert p["prefix"] == "may_gpu" and p["enabled"] is True
        assert p["base_url"] == "http://172.16.10.220:8000/v1", "chuẩn hoá URL y như hai biến cũ"
        assert p["name"] == "may_gpu", "không khai _NAME thì tên = tiền tố"
        assert p["api_key"] == "local"

    def test_ten_va_khoa_rieng(self, sach, monkeypatch):
        monkeypatch.setenv("C2A_PROVIDER_TTS2_URL", "https://tts.vidu.vn/v1")
        monkeypatch.setenv("C2A_PROVIDER_TTS2_NAME", "Giọng nói máy 2")
        monkeypatch.setenv("C2A_PROVIDER_TTS2_KEY", "bi-mat")
        p = sach.get_custom_providers()["tts2"]
        assert p["name"] == "Giọng nói máy 2" and p["api_key"] == "bi-mat"
        assert p["base_url"] == "https://tts.vidu.vn/v1"

    def test_nhieu_bien_cung_luc_cong_voi_bien_cu(self, sach, monkeypatch):
        monkeypatch.setenv("VISION_URL_GPU", "http://a:5003")
        monkeypatch.setenv("C2A_PROVIDER_M1_URL", "http://m1:1")
        monkeypatch.setenv("C2A_PROVIDER_M2_URL", "http://m2:2")
        assert set(sach.get_custom_providers()) == {"lv", "m1", "m2"}

    def test_url_rong_thi_bo_qua(self, sach, monkeypatch):
        monkeypatch.setenv("C2A_PROVIDER_M1_URL", "  ")
        assert "m1" not in sach.get_custom_providers()

    def test_id_khong_hop_le_bi_bo_va_bao(self, sach, monkeypatch):
        log = _GhiLog()
        monkeypatch.setattr(sach, "logger", log)
        monkeypatch.setenv("C2A_PROVIDER_MAY-GPU_URL", "http://a:1")
        monkeypatch.setenv("C2A_PROVIDER_may_URL", "http://b:1")
        ds = sach.get_custom_providers()
        assert not any(k.startswith("may") for k in ds)
        bien = {m.get("bien") for m in log.canh_bao if m.get("event") == "provider_env_id_khong_hop_le"}
        assert bien == {"C2A_PROVIDER_MAY-GPU_URL", "C2A_PROVIDER_may_URL"}

    def test_trung_tien_to_co_san_bi_bo_va_bao(self, sach, monkeypatch):
        """`oc/…` đã là opencode; khai C2A_PROVIDER_OC_URL thì module mới bị che
        im lặng — bỏ hẳn và cảnh báo để người vận hành biết đổi tên."""
        log = _GhiLog()
        monkeypatch.setattr(sach, "logger", log)
        monkeypatch.setenv("C2A_PROVIDER_OC_URL", "http://a:1")
        monkeypatch.setenv("C2A_PROVIDER_GEMINI_URL", "http://b:1")
        monkeypatch.setenv("C2A_PROVIDER_FLOW_URL", "http://c:1")
        ds = sach.get_custom_providers()
        assert not {"oc", "gemini", "flow"} & set(ds)
        trung = {m["bien"]: m.get("provider") for m in log.canh_bao
                 if m.get("event") == "provider_env_trung_tien_to"}
        assert trung == {"C2A_PROVIDER_OC_URL": "opencode",
                         "C2A_PROVIDER_GEMINI_URL": "gemini_free",
                         "C2A_PROVIDER_FLOW_URL": "flow"}

    def test_canh_bao_chi_ghi_mot_lan(self, sach, monkeypatch):
        """`_providers_tu_env` chạy trong MỖI lần định tuyến model — báo mỗi lượt
        là ngập log."""
        log = _GhiLog()
        monkeypatch.setattr(sach, "logger", log)
        monkeypatch.setenv("C2A_PROVIDER_OC_URL", "http://a:1")
        for _ in range(5):
            sach.get_custom_providers()
        assert len(log.canh_bao) == 1

    def test_trung_tien_to_bien_cu_thi_bien_cu_thang(self, sach, monkeypatch):
        log = _GhiLog()
        monkeypatch.setattr(sach, "logger", log)
        monkeypatch.setenv("VISION_URL_GPU", "http://cu:5003")
        monkeypatch.setenv("C2A_PROVIDER_LV_URL", "http://moi:1")
        assert sach.get_custom_providers()["lv"]["base_url"] == "http://cu:5003/v1"
        assert any(m.get("event") == "provider_env_trung_tien_to" for m in log.canh_bao)

    def test_config_thang_bien_moi(self, sach, monkeypatch):
        from services.config import config
        monkeypatch.setenv("C2A_PROVIDER_M1_URL", "http://env:1")
        monkeypatch.setattr(config, "data", {"custom_providers": {"m1": {
            "name": "sửa tay", "prefix": "m1", "base_url": "http://cfg:9/v1", "enabled": True}}},
            raising=False)
        assert sach.get_custom_providers()["m1"]["base_url"] == "http://cfg:9/v1"

    def test_dinh_tuyen_toi_provider_moi(self, sach, monkeypatch):
        from services.backend_router import BackendRouter
        monkeypatch.setenv("C2A_PROVIDER_MAY_GPU_URL", "http://a:1")
        assert BackendRouter.resolve_model("may_gpu/qwen3") == ("custom:may_gpu", "qwen3")

    def test_khong_doi_tap_may_nha(self, sach):
        """Provider env mới chưa chắc chạy tại nhà — không được tự vào tập này."""
        assert sach._PREFIX_MAY_NHA == {"lv", "ol"}
