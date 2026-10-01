"""Đọc cấu hình từ .env — không hardcode secret trong code."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

C2A_BASE_URL = os.getenv("C2A_BASE_URL", "http://127.0.0.1:3030").rstrip("/")
C2A_AUTH_KEY = os.getenv("C2A_AUTH_KEY", "")
C2A_ZALO_PERSONAL_THREAD_ID = os.getenv("C2A_ZALO_PERSONAL_THREAD_ID", "")

MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8801"))
# Gốc URL ghép vào link PDF giải chi gửi qua chat (tools.giai_chi_cong_ty).
# Mặc định localhost cho máy cài mới; máy chủ thật đặt IP LAN/tên miền trong
# .env. `or` (không phải default của getenv): .env chép từ .env.example có
# dòng `SELF_BASE_URL=` rỗng.
SELF_BASE_URL = (os.getenv("SELF_BASE_URL") or f"http://localhost:{MCP_SERVER_PORT}").rstrip("/")

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/chi_tieu.db")
JARS_CONFIG_PATH = BASE_DIR / "data" / "jars_config.json"
# Mẫu 6 hũ chuẩn cho máy cài mới -- nằm trong app/ (có sẵn trong image), vì
# data/ bị bind mount che mất nội dung image.
JARS_CONFIG_MAU_PATH = BASE_DIR / "app" / "jars_config.example.json"

ALERT_CHECK_INTERVAL_SECONDS = int(os.getenv("ALERT_CHECK_INTERVAL_SECONDS", "1800"))
