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

import pytest

pytestmark = pytest.mark.pure


@pytest.fixture()
def sach(monkeypatch):
    """Config trống + không có biến env nào, để mỗi phép thử tự dựng cảnh."""
    from services.config import config
    monkeypatch.setattr(config, "data", {}, raising=False)
    monkeypatch.delenv("VISION_URL_GPU", raising=False)
    monkeypatch.delenv("VISION_URL_GPU_KEY", raising=False)
    from services.providers import custom_openai
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
