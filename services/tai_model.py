"""Nút «Tải xuống» trên web: chạy script tải model ở nền, giữ vài dòng tiến độ cuối cho web xem.

Chủ máy 28/09/2026: "chưa có thì hiển thị nút tải xuống bên cạnh, kích vào tự động tải xuống".
Chỉ chạy lệnh có trong danh mục (`danh_muc_model.argv_cua` so NGUYÊN chuỗi) — cùng script mà
hướng dẫn bảo chủ máy tự gõ, nên tải bằng nút hay bằng tay ra cùng một tệp, cùng kiểm SHA-256.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from utils.log import logger

GOC = Path(__file__).resolve().parents[1]
TOI_DA_CUNG_LUC = 2
GIU_VIEC = 20

_khoa = threading.Lock()
_viec: dict[str, dict[str, Any]] = {}


def _cong_khai(v: dict[str, Any]) -> dict[str, Any]:
    return {k: (list(x) if isinstance(x, deque) else x) for k, x in v.items() if k != "_p"}


def ds() -> list[dict[str, Any]]:
    with _khoa:
        return [_cong_khai(v) for v in sorted(_viec.values(), key=lambda x: -x["bat_dau"])]


def _chay(v: dict[str, Any], argv: list[str]) -> None:
    try:
        p = subprocess.Popen(argv, cwd=str(GOC), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        con = b""
        while True:
            khuc = p.stdout.read(512) if p.stdout else b""
            if not khuc:
                break
            con += khuc
            # tiến độ tải in bằng "\r" (ghi đè cùng dòng) — tách cả hai kiểu xuống dòng
            *xong, con = re.split(rb"[\r\n]", con)
            with _khoa:
                v["dong"].extend(x.decode("utf-8", "replace").strip() for x in xong if x.strip())
        if con.strip():
            with _khoa:
                v["dong"].append(con.decode("utf-8", "replace").strip())
        ma = p.wait()
        with _khoa:
            v.update(trang_thai="xong" if ma == 0 else "loi", ma_thoat=ma, ket_thuc=time.time())
    except Exception as exc:  # noqa: BLE001 — việc tải hỏng không được kéo đổ tiến trình web
        with _khoa:
            v.update(trang_thai="loi", ket_thuc=time.time())
            v["dong"].append(f"lỗi chạy: {str(exc)[:160]}")
    logger.info({"event": "tai_model_xong", "lenh": v["lenh"], "trang_thai": v["trang_thai"],
                 "ma_thoat": v.get("ma_thoat")})


def bat_dau(lenh: str) -> dict[str, Any]:
    """Bắt đầu tải; lệnh đó đang chạy thì trả lại việc đang chạy. ``ValueError`` khi không hợp lệ
    hoặc đã đủ `TOI_DA_CUNG_LUC` việc."""
    from services import danh_muc_model
    argv = danh_muc_model.argv_cua(lenh)
    with _khoa:
        dang = [v for v in _viec.values() if v["trang_thai"] == "dang_chay"]
        for v in dang:
            if v["lenh"] == lenh:
                return _cong_khai(v)
        if len(dang) >= TOI_DA_CUNG_LUC:
            raise ValueError(f"đang tải {len(dang)} model — chờ xong rồi bấm tiếp")
        v = {"id": uuid.uuid4().hex[:10], "lenh": lenh, "trang_thai": "dang_chay", "ma_thoat": None,
             "bat_dau": time.time(), "ket_thuc": None, "dong": deque(maxlen=8)}
        _viec[v["id"]] = v
        for cu in sorted((x for x in _viec.values() if x["trang_thai"] != "dang_chay"),
                         key=lambda x: x["bat_dau"])[:-GIU_VIEC or None]:
            _viec.pop(cu["id"], None)
    logger.info({"event": "tai_model_bat_dau", "lenh": lenh})
    threading.Thread(target=_chay, args=(v, argv), name="tai-model", daemon=True).start()
    return _cong_khai(v)


def _reset_for_tests() -> None:
    with _khoa:
        _viec.clear()
