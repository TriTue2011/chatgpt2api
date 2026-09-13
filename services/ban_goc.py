"""Bản chạy thật (DATA_DIR) theo bản gốc trong repo — trừ khi đã sửa tay.

Ba nơi chép bản gốc từ ảnh vào DATA_DIR để sửa được mà không dựng lại ảnh:
hướng dẫn học hỏi (`hieu_thiet_bi_nha.huong_dan`), skill mặc định
(`agent/skills._ensure_seeded`), workflow mặc định (`agent/workflows`). Cả ba
từng chép MỘT lần rồi thôi, nên sửa bản gốc không bao giờ tới máy chủ. Đo
13/09/2026: hướng dẫn chọn ngoại vi kẹt bản một bước trong khi code đã hai
bước; skill `giao-vien-tieu-hoc` và 2 workflow bài học kẹt bản 20/07, thiếu
bản sửa 29/07 "bắt buộc truyền lớp và môn" — bài giảng lớp 1 trích sách lớp 7.

Sổ `.goc` cạnh bản chạy thật giữ dấu vân tay bản gốc lúc chép, để phân biệt:

* bản chạy thật vẫn đúng bằng bản đã chép → chỉ CŨ → chép bản gốc mới;
* bản chạy thật khác bản đã chép → ĐÃ SỬA TAY (người dùng dạy skill, giáo viên
  sửa hướng dẫn) → giữ, log `ban_goc_lech` để người gộp;
* chưa có sổ (chép trước khi có file này): khớp bản gốc thì ghi sổ; khác thì
  không phân biệt được cũ với sửa tay → giữ.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from utils.log import logger


def _doc(p: Path) -> dict[str, bytes]:
    """Tệp → {"": nội dung}; thư mục → {đường dẫn tương đối: nội dung}."""
    if p.is_file():
        return {"": p.read_bytes()}
    return {f.relative_to(p).as_posix(): f.read_bytes() for f in sorted(p.rglob("*")) if f.is_file()}


def _van_tay(tep: dict[str, bytes]) -> str:
    """Tệp đơn: sha256 nội dung (khớp sổ `.goc` của hướng dẫn chép trước đó).
    Thư mục: sha256 của từng (tên, sha256 nội dung) theo thứ tự tên."""
    if list(tep) == [""]:
        return hashlib.sha256(tep[""]).hexdigest()
    h = hashlib.sha256()
    for k in sorted(tep):
        h.update(k.encode("utf-8") + b"\0" + hashlib.sha256(tep[k]).digest())
    return h.hexdigest()


def _dich(chay: Path, rel: str) -> Path:
    return chay if rel == "" else chay / rel


def _doc_so(so: Path) -> dict | None:
    if not so.is_file():
        return None
    tho = so.read_text(encoding="utf-8").strip()
    try:
        d = json.loads(tho)
    except ValueError:
        return {"van_tay": tho, "tep": [""]}          # sổ tệp đơn: chỉ dấu vân tay
    return d if isinstance(d, dict) and d.get("van_tay") else None


def _ghi_so(so: Path, tep: dict[str, bytes]) -> None:
    so.write_text(_van_tay(tep) if list(tep) == [""]
                  else json.dumps({"van_tay": _van_tay(tep), "tep": sorted(tep)}), encoding="utf-8")


def dong_bo(goc: Path, chay: Path, so: Path, *, ten: str) -> str:
    """Đưa `chay` theo `goc` (cùng là tệp, hoặc cùng là thư mục).

    Trả việc đã làm: "chep" (chưa có), "theo" (bản gốc đổi, chưa ai sửa tay),
    "ghi_so" (đã khớp, chỉ thiếu sổ), "giu" (đã sửa tay hoặc không rõ gốc),
    "" (không có gì đổi). Tệp người dùng thêm vào thư mục không bị đụng.
    """
    tep_goc = _doc(goc)
    vt_goc = _van_tay(tep_goc)
    cu = _doc_so(so)
    if not chay.exists():
        _chep(tep_goc, chay, bo=[])
        _ghi_so(so, tep_goc)
        return "chep"
    if cu and cu["van_tay"] == vt_goc:
        return ""
    hien: dict[str, bytes] = {}
    for rel in (cu["tep"] if cu else list(tep_goc)):
        f = _dich(chay, rel)
        if not f.is_file():
            hien = {}
            break
        hien[rel] = f.read_bytes()
    vt_hien = _van_tay(hien) if hien else ""
    if vt_hien == vt_goc:
        _ghi_so(so, tep_goc)
        return "ghi_so"
    if cu and vt_hien == cu["van_tay"]:
        _chep(tep_goc, chay, bo=[r for r in cu["tep"] if r not in tep_goc])
        _ghi_so(so, tep_goc)
        logger.info({"event": "ban_goc_theo", "ten": ten, "van_tay": vt_goc[:12]})
        return "theo"
    logger.warning({"event": "ban_goc_lech", "ten": ten,
                    "ghi_chu": "bản chạy thật đã sửa tay (hoặc không rõ gốc) mà bản gốc "
                               "trong ảnh đã đổi — giữ bản chạy thật, cần người gộp"})
    return "giu"


def _chep(tep: dict[str, bytes], chay: Path, *, bo: list[str]) -> None:
    for rel, noi in tep.items():
        f = _dich(chay, rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        tam = f.with_name(f.name + ".moi")
        tam.write_bytes(noi)
        tam.replace(f)
    for rel in bo:
        _dich(chay, rel).unlink(missing_ok=True)
