"""Fixture dùng chung cho test tầng MCP (gọi app.main.mcp thật)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def mcp_that(tmp_path, monkeypatch):
    """app.main.mcp thật, DB/cấu hình tạm như test_tools.py. Nạp app.main lần
    đầu sẽ khoi_tao_db() (lúc đó DB đã trỏ sang file tạm) và bật scheduler
    cảnh báo -- chặn scheduler để test không có luồng nền gọi C2A gửi Zalo
    thật (tiến trình test có nạp .env thật qua app.config)."""
    db_path = tmp_path / "chi_tieu_test.db"
    jars_path = tmp_path / "jars_config.json"
    jars_path.write_text(json.dumps({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    }), encoding="utf-8")

    import app.config as config
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "JARS_CONFIG_PATH", jars_path)

    import app.storage as storage
    monkeypatch.setattr(storage, "DB_PATH", db_path)
    storage.khoi_tao_db()

    import app.jars as jars
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", jars_path)

    import app.pdf_cong_ty as pdf_cong_ty
    monkeypatch.setattr(pdf_cong_ty, "THU_MUC_PDF", tmp_path / "tam_ung_pdf")

    from apscheduler.schedulers.background import BackgroundScheduler
    monkeypatch.setattr(BackgroundScheduler, "start", lambda self, *a, **k: None)
    from app import main
    return main.mcp, db_path
