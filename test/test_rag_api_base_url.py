"""URL gateway mặc định của hub — một chỗ khai duy nhất, và phải là loopback.

Bối cảnh: bốn module từng tự hardcode fallback `http://chatgpt2api:3030/v1` và
cả bốn đều sai giống nhau:
  - compose không có service nào tên `chatgpt2api` (tên thật là `c2a`);
  - gateway nghe cổng 80 TRONG container, `"3030:80"` nghĩa là 3030 chỉ là cổng
    publish ra host.
Sai URL thì `_synthesize_with_ai` bắt URLError, trả "" và luồng nạp RAG rơi về
văn bản gốc — vẫn ra chunks nên rất dễ tưởng là bình thường. Bộ test này chốt
để không ai vô tình khai lại tên service / cổng host.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_HUB = _ROOT / "vn-mcp-hub"
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))

from src.rag.settings import DEFAULT_API_BASE_URL, DEFAULTS  # noqa: E402

pytestmark = pytest.mark.pure

# Các module gọi gateway; mỗi module phải LẤY hằng số chứ không tự khai chuỗi.
_CALLERS = [
    _HUB / "src" / "main.py",
    _HUB / "src" / "rag" / "scheduler.py",
    _HUB / "src" / "rag" / "telegram_bot.py",
]


class TestHangSoURL:
    def test_la_loopback(self):
        host = urlparse(DEFAULT_API_BASE_URL).hostname
        assert host in {"127.0.0.1", "localhost", "::1"}, (
            f"{host!r} không phải loopback — hub chạy CÙNG container với gateway, "
            "dùng tên service là phụ thuộc mạng Docker không cần thiết"
        )

    def test_dung_cong_trong_container_khong_phai_cong_host(self):
        port = urlparse(DEFAULT_API_BASE_URL).port
        assert port == 80, f"cổng {port} — gateway nghe 80 trong container"
        assert port != 3030, "3030 là cổng publish ra HOST, không dùng được từ trong container"

    def test_co_duoi_v1(self):
        # `_synthesize_with_ai` nối thẳng "/chat/completions" vào sau.
        assert DEFAULT_API_BASE_URL.rstrip("/").endswith("/v1")

    def test_defaults_dung_chung_hang_so(self):
        assert DEFAULTS["api_base_url"] == DEFAULT_API_BASE_URL


class TestKhongAiHardcodeLai:
    def test_khong_con_ten_service_cu(self):
        for path in _CALLERS + [_HUB / "src" / "rag" / "settings.py"]:
            src = path.read_text(encoding="utf-8")
            # Cho phép nhắc trong chú thích (giải thích vì sao sai), nhưng không
            # được xuất hiện trong CODE.
            code = "\n".join(
                ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
            )
            assert "chatgpt2api:3030" not in code, f"{path.name} còn hardcode URL cũ"

    def test_moi_caller_lay_hang_so_thay_vi_khai_chuoi(self):
        for path in _CALLERS:
            src = path.read_text(encoding="utf-8")
            assert "DEFAULT_API_BASE_URL" in src, (
                f"{path.name} không dùng hằng số — dễ lệch lại như lần trước"
            )

    def test_khong_con_url_gateway_dang_chuoi_trong_caller(self):
        """Chặn mọi biến thể `http://<host>:<port>/v1` viết tay trong caller."""
        pat = re.compile(r'["\']https?://[\w.\-]+:\d+/v1["\']')
        for path in _CALLERS:
            code = "\n".join(
                ln for ln in path.read_text(encoding="utf-8").splitlines()
                if not ln.lstrip().startswith("#")
            )
            found = pat.findall(code)
            assert not found, f"{path.name} còn URL gateway viết tay: {found}"


class TestKhopVoiCompose:
    """Hằng số phải khớp với cổng thật trong docker-compose.yml."""

    def test_cong_trong_container_khop_compose(self):
        compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        # Dòng dạng:  - "3030:80"        # API + web UI
        m = re.search(r'-\s*"(\d+):(\d+)"\s*#\s*API', compose)
        assert m, "không tìm được dòng publish cổng API trong docker-compose.yml"
        host_port, container_port = int(m.group(1)), int(m.group(2))
        assert urlparse(DEFAULT_API_BASE_URL).port == container_port, (
            f"compose map {host_port}->{container_port}; hằng số phải dùng "
            f"{container_port} (cổng trong container)"
        )

    def test_khong_co_service_ten_chatgpt2api(self):
        compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert not re.search(r"^\s{2}chatgpt2api:", compose, re.M), (
            "compose có service tên chatgpt2api — xem lại giả định của bộ test này"
        )
