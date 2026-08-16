"""Lưu/khôi phục sổ việc của tab Dịch qua lần khởi động lại gateway.

Không cố tiếp tục một thread ASR đã bị kernel dừng giữa chừng: không có
checkpoint model an toàn để làm vậy. Thay vào đó giữ lại việc và báo lỗi rõ
ràng, thay vì UI nhận 404 rồi tưởng video đã biến mất.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


#: Giãn cách tối thiểu giữa hai lần ghi sổ cho các cập nhật TIẾN ĐỘ.
NHIP_LUU_TIEN_DO = 2.0


def nen_luu_ngay(viec: dict[str, Any], thay: dict[str, Any], *, luc: float,
                 nhip: float = NHIP_LUU_TIEN_DO) -> bool:
    """Lần cập nhật này có phải ghi sổ xuống đĩa ngay không?

    Lồng tiếng báo tiến độ MỖI CÂU — phim dài là cả nghìn lượt, mà mỗi lượt ghi
    lại toàn bộ sổ kèm ``fsync`` và giữ khoá trong lúc đó. Mất dòng "đang tổng
    hợp câu 412" vì cúp điện thì không ai tiếc; mất TRẠNG THÁI mới là thứ khiến
    giao diện báo 404 sau restart, nên đổi trạng thái là ghi ngay, không giãn.
    """
    if "trang_thai" in thay:
        return True
    try:
        lan_cuoi = float(viec.get("luu_luc") or 0.0)
    except (TypeError, ValueError):
        lan_cuoi = 0.0
    return luc - lan_cuoi >= float(nhip)


def xoa_ket_qua_da_luu(viec: dict[str, Any], thu_muc_docs: Path) -> None:
    """Xoá đúng thư mục kết quả UUID do API tạo; bỏ qua mọi URL lạ."""
    for tep in ((viec.get("ket_qua") or {}).get("tep") or []):
        url = str((tep or {}).get("url") or "")
        if "/images/docs/" not in url:
            continue
        ma = url.split("/images/docs/", 1)[1].split("/", 1)[0]
        if re.fullmatch(r"[0-9a-f]{12}", ma):
            shutil.rmtree(thu_muc_docs / ma, ignore_errors=True)


def don_thu_muc_ket_qua(thu_muc_docs: Path, *, cu_hon: float) -> int:
    """Dọn thư mục UUID có dấu TTL, kể cả file Zalo không có job WebUI."""
    da_xoa = 0
    try:
        cac_thu_muc = list(thu_muc_docs.iterdir())
    except FileNotFoundError:
        return 0
    except OSError as exc:
        logger.info("không liệt kê được tệp kết quả Dịch: %s", str(exc)[:120])
        return 0
    for duong in cac_thu_muc:
        if not re.fullmatch(r"[0-9a-f]{12}", duong.name) or duong.is_symlink():
            continue
        try:
            co_ttl = duong / ".expire-24h"
            if (duong.is_dir() and co_ttl.is_file()
                    and duong.stat().st_mtime < float(cu_hon)):
                shutil.rmtree(duong)
                da_xoa += 1
        except OSError as exc:
            logger.info("không dọn được tệp kết quả %s: %s",
                        duong.name, str(exc)[:120])
    return da_xoa


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
