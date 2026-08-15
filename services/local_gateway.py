"""Địa chỉ gateway khi các thành phần gọi lại cùng một container.

Không đóng đinh cổng 80: chế độ ``APP_USER=c2a`` phải dùng cổng không đặc
quyền (thường là 8080). ``C2A_GATEWAY_URL`` vẫn cho phép triển khai tách
dịch vụ chủ động chỉ định một địa chỉ nội bộ khác.
"""
from __future__ import annotations

import os


def _app_port() -> str:
    value = str(os.getenv("APP_PORT") or "80").strip()
    try:
        port = int(value)
    except ValueError:
        return "80"
    return str(port) if 1 <= port <= 65535 else "80"


def loopback_gateway_url() -> str:
    """Gateway cùng container, luôn qua loopback để không đi vòng ra mạng."""
    return f"http://127.0.0.1:{_app_port()}"


def gateway_base_url() -> str:
    """Gateway nội bộ đã cấu hình, hoặc loopback theo ``APP_PORT``."""
    configured = str(os.getenv("C2A_GATEWAY_URL") or "").strip().rstrip("/")
    return configured or loopback_gateway_url()


def gateway_v1_url() -> str:
    return f"{gateway_base_url()}/v1"
