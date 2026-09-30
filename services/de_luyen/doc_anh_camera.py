"""Bộ đề LUYỆN cho `doc_anh_camera.md` — đọc ảnh camera THẬT của nhà, đáp án là vùng CHỦ NHÀ khoanh.

Chủ máy 30/09/2026 tự khoanh trên ảnh lưới từng khu (khu chơi, bàn ăn, sàn bếp, sàn ban công đi lại được) và
từng món đồ (tủ lạnh, tivi, kệ, tủ giày, máy giặt…), rồi bảo "dựa vào cơ sở tôi đưa, train cho con bot của tôi".
Ảnh và đáp án là của RIÊNG nhà đó nên nằm trong DATA_DIR (`agent/so_do_nha/de_luyen/`), không vào repo:
  <camera>.jpg   khung hình gốc (chưa kẻ lưới) — mỗi lượt giải kẻ lưới + YOLO lại, y như đường chạy thật
  dap_an.json    {"mo_ta": [lời chủ nhà mô tả nhà TRƯỚC khi khoanh],
                  "de": {camera: {"phong": {phòng: [ô]}, "do": [ô đồ đạc], "trung": [ô không chấm]}}}

Bot giải với lời mô tả gốc, KHÔNG thấy vùng khoanh — thấy thì chỉ là chép lại, sang nhà khác vẫn không biết đọc.
Chấm theo ô: ô sàn đúng phòng / ô gán nhầm phòng / ô ĐỒ ĐẠC bị gán thành sàn / ô sàn bỏ sót.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

TANG = "services.so_do_nha"

THU_MUC = Path(DATA_DIR) / "agent" / "so_do_nha" / "de_luyen"
#: Đạt khi lấy được ≥ 70% ô sàn của đáp án VÀ ≥ 85% ô em gán (trong vùng được chấm) là đúng.
DU_SAN = 0.70
DUNG_TOI_THIEU = 0.85


def _nap() -> dict[str, Any]:
    try:
        return json.loads((THU_MUC / "dap_an.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _de() -> list[dict[str, Any]]:
    d = _nap()
    return [{"ten": cam, "mo_ta": list(d.get("mo_ta") or []), "dap_an": da}
            for cam, da in (d.get("de") or {}).items() if (THU_MUC / f"{cam}.jpg").exists()]


DE: list[dict[str, Any]] = _de()


def giai_de(d: dict[str, Any], model: Any = None) -> dict[str, Any] | str:
    """Bot đọc ảnh đề ``d`` đúng như lúc chạy thật: cùng `lenh_doc_anh`, cùng model, cùng `doc_nhieu_lan`
    (đọc nhiều lần, gộp đa số)."""
    from services import so_do_nha as so

    jpeg = (THU_MUC / f"{d['ten']}.jpg").read_bytes()
    lenh, luoi, _dem, _vat, _co, _ban = so.lenh_doc_anh(d["ten"], jpeg, d["mo_ta"])
    k, loi_model = so.doc_nhieu_lan(lenh, luoi, so._ten_phong())
    if k is None:
        return f"model lỗi: {loi_model[:120]}"
    return k


def do(bai: dict[str, Any], dap_an: dict[str, Any]) -> dict[str, Any]:
    """Đếm ô: dung (đúng phòng), nham_phong, nham_do (đồ đạc bị gán thành sàn), thieu (ô sàn bỏ sót)."""
    that = {o: p for p, ds in dap_an["phong"].items() for o in ds}
    do_dac, trung = set(dap_an["do"]), set(dap_an["trung"])
    ra: dict[str, list[str]] = {"dung": [], "nham_phong": [], "nham_do": [], "phong_la": []}
    gan = {o: p for p, ds in (bai.get("thay") or {}).items() for o in ds}
    for o, p in gan.items():
        if o in trung:
            continue
        if p not in dap_an["phong"]:
            ra["phong_la"].append(f"{o}:{p}")
        elif o in do_dac:
            ra["nham_do"].append(o)
        elif o in that:
            ra["dung" if that[o] == p else "nham_phong"].append(o)
    ra["thieu"] = sorted(o for o in that if o not in gan)
    return ra


def cham_cho(bai: dict[str, Any] | str, dap_an: dict[str, Any]) -> list[str]:
    if isinstance(bai, str):
        return [f"bài bị loại: {bai}"]
    r = do(bai, dap_an)
    if not dap_an["phong"]:
        return [f"camera không nhìn vào phòng nào trong nhà mà bài gán {len(r['phong_la'])} ô"] if r["phong_la"] else []
    tong = sum(len(v) for v in dap_an["phong"].values())
    sai = len(r["nham_phong"]) + len(r["nham_do"]) + len(r["phong_la"])
    loi = []
    if len(r["dung"]) < DU_SAN * tong:
        loi.append(f"bỏ sót sàn: chỉ {len(r['dung'])}/{tong} ô sàn đúng phòng")
    if sai > (1 - DUNG_TOI_THIEU) * (len(r["dung"]) + sai):
        loi.append(f"gán sai {sai} ô (nhầm phòng {len(r['nham_phong'])}, đồ đạc thành sàn {len(r['nham_do'])}, "
                   f"phòng không có trong khung {len(r['phong_la'])})")
    return loi
