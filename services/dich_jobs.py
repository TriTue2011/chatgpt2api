"""Lưu/khôi phục sổ việc của tab Dịch qua lần khởi động lại gateway.

Không cố tiếp tục một thread ASR đã bị kernel dừng giữa chừng: không có
checkpoint model an toàn để làm vậy. Thay vào đó giữ lại việc và báo lỗi rõ
ràng, thay vì UI nhận 404 rồi tưởng video đã biến mất.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def tai_so_viec(duong: Path) -> dict[str, dict[str, Any]]:
    """Đọc sổ việc; file hỏng không được làm gateway không khởi động."""
    try:
        raw = json.loads(duong.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("không đọc được sổ việc Dịch %s: %s", duong, str(exc)[:160])
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def luu_so_viec(duong: Path, viec: dict[str, dict[str, Any]]) -> None:
    """Ghi nguyên tử sổ việc, chỉ admin gateway mới đọc được nội dung."""
    try:
        duong.parent.mkdir(parents=True, exist_ok=True)
        fd, tam = tempfile.mkstemp(prefix=f".{duong.name}.", suffix=".tmp", dir=duong.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(viec, f, ensure_ascii=False, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tam, 0o600)
            os.replace(tam, duong)
        finally:
            Path(tam).unlink(missing_ok=True)
    except Exception as exc:
        # Sổ là lớp quan sát/khôi phục; lỗi ghi không được chặn phụ đề đang chạy.
        logger.warning("không lưu được sổ việc Dịch %s: %s", duong, str(exc)[:160])


def khoi_phuc_sau_restart(viec: dict[str, dict[str, Any]], *,
                          luc: float | None = None) -> dict[str, dict[str, Any]]:
    """Đánh dấu thread đang chạy là gián đoạn; upload dở còn tệp thì giữ lại."""
    now = time.time() if luc is None else float(luc)
    ra = {k: dict(v) for k, v in viec.items()}
    for v in ra.values():
        trang_thai = str(v.get("trang_thai") or "")
        if trang_thai == "dang_chay":
            v.update({
                "trang_thai": "loi",
                "loi": ("Máy chủ đã khởi động lại khi đang xử lý; "
                        "hãy gửi lại tệp để chạy lại từ đầu."),
                "luc": now,
            })
        elif trang_thai == "nhan_tep" and not Path(str(v.get("duong") or "")).is_file():
            v.update({
                "trang_thai": "loi",
                "loi": "Tệp tải dở không còn sau khi máy chủ khởi động lại; hãy gửi lại.",
                "luc": now,
            })
    return ra
