"""Giá trị mặc định của app/config.py khi .env không đặt gì (máy cài mới)."""
import importlib
import sys
from pathlib import Path

import dotenv
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.config as config  # noqa: E402


@pytest.fixture
def nap_lai_config(monkeypatch):
    """Nạp lại app.config như trên máy cài mới: KHÔNG đọc .env thật (máy chủ có
    SELF_BASE_URL riêng) và không có biến môi trường của app. Xong test nạp lại
    bình thường để các test khác thấy đúng cấu hình gốc."""
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    def _nap(**bien_moi_truong):
        for ten in ("SELF_BASE_URL", "MCP_SERVER_PORT"):
            monkeypatch.delenv(ten, raising=False)
        for ten, gia_tri in bien_moi_truong.items():
            monkeypatch.setenv(ten, gia_tri)
        return importlib.reload(config)

    yield _nap
    monkeypatch.undo()
    importlib.reload(config)


def test_self_base_url_mac_dinh_la_localhost_khong_phai_ip_may_chu(nap_lai_config):
    assert nap_lai_config().SELF_BASE_URL == "http://localhost:8801"


def test_self_base_url_mac_dinh_theo_cong_mcp(nap_lai_config):
    assert nap_lai_config(MCP_SERVER_PORT="9000").SELF_BASE_URL == "http://localhost:9000"


def test_self_base_url_trong_trong_env_van_dung_mac_dinh(nap_lai_config):
    """.env chép từ .env.example có dòng `SELF_BASE_URL=` (rỗng) -- không được
    thành chuỗi rỗng (link PDF sẽ thành đường dẫn tương đối, bấm không mở được)."""
    assert nap_lai_config(SELF_BASE_URL="").SELF_BASE_URL == "http://localhost:8801"


def test_self_base_url_tu_env_bo_dau_gach_cuoi(nap_lai_config):
    assert nap_lai_config(SELF_BASE_URL="http://10.0.0.5:8801/").SELF_BASE_URL == "http://10.0.0.5:8801"
