"""Nạp gói `src` của captcha-solver mà không tranh tên với vn-mcp-hub.

Repo có HAI thư mục tên `src`, cả hai đều là gói Python:
`captcha-solver/src` và `vn-mcp-hub/src`. `sys.modules` chỉ giữ được MỘT mục
tên `src`, nên cái nào nạp trước thì thắng, cái sau nhận:

    ImportError: cannot import name 'accounts_db' from 'src'
                 (…/vn-mcp-hub/src/__init__.py)

Đúng lỗi làm CI đỏ ngày 21/08/2026. Cắm `sys.path` không cứu được: các test
vn-mcp-hub (`test_url_guard_ssrf.py`) nạp `src.url_guard` ngay lúc pytest THU
THẬP module, còn các test captcha-solver mới gọi `from src import accounts_db`
lúc CHẠY — tới lúc đó `sys.modules["src"]` đã thuộc về vn-mcp-hub rồi, và
`sys.path` không còn được hỏi tới nữa.

Ở đây nạp thẳng thư mục đó thành gói mang tên riêng `captcha_src`. Import
tương đối bên trong vẫn chạy (`accounts_db` có `from . import vault`) vì tên
gói gắn liền với module chứ không tra qua `sys.path`.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

TEN_GOI = "captcha_src"
_THU_MUC = Path(__file__).resolve().parents[1] / "captcha-solver" / "src"


def _dam_bao_goi() -> None:
    if TEN_GOI in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        TEN_GOI,
        _THU_MUC / "__init__.py",
        submodule_search_locations=[str(_THU_MUC)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"không nạp được gói captcha-solver ở {_THU_MUC}")
    goi = importlib.util.module_from_spec(spec)
    sys.modules[TEN_GOI] = goi
    spec.loader.exec_module(goi)


def nap(ten_module: str):
    """Trả về module con của `captcha-solver/src`, ví dụ `nap("accounts_db")`."""
    _dam_bao_goi()
    return importlib.import_module(f"{TEN_GOI}.{ten_module}")
