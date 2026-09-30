"""Bộ đề LUYỆN cho các hướng dẫn học của bot nhà (`services/huong_dan_hoc/*.md`).

Mỗi mô-đun con (trùng tên hướng dẫn) có `DE`: danh sách đề giả lập cho MỘT tình huống thực tế,
kèm `dap_an`. `cham` so bài giải với đáp án; `luyen` cho bot giải và chấm cả bộ. Chủ máy
29/09/2026: "train mọi tình huống trong thực tế chứ không phải bó hẹp trong nhà tôi".

Đáp án (mọi khoá đều tuỳ chọn):
  <bieu_thuc>: None                 — bài phải để null (bieu_thuc: co_nguoi | giu | nhin | roi_di)
  <khoa>: <số / chữ>                — bài phải đúng giá trị đó (vd roi_khi_o_duoi: 3)
  <khoa>_mot_trong: [giá trị]       — bài phải là một trong các giá trị đó
  <bieu_thuc>_phai_co: [mã] | {mã: [trạng thái]}  — phải có (kèm đúng trạng thái)
  <bieu_thuc>_phai_co_mot: [mã]     — phải có ít nhất một trong các mã
  <bieu_thuc>_khong_co: [mã]        — không được có
  co_nguoi_phu_dinh: [mã]           — phải nằm trong một nhánh `khong` (loại lây)
  co_nguoi_phu_dinh_khong: [mã]     — không được nằm trong nhánh `khong`
"""

from __future__ import annotations

import importlib
from typing import Any


def _ma(bt: Any, trong_khong: bool = False) -> dict[str, tuple[set[str], bool]]:
    """{mã: (trạng thái, có nằm dưới `khong` không)} của một biểu thức (hoặc danh sách camera)."""
    ra: dict[str, tuple[set[str], bool]] = {}
    if isinstance(bt, list):
        return {str(x): (set(), False) for x in bt}
    if not isinstance(bt, dict):
        return ra
    if "ma" in bt:
        return {str(bt["ma"]): ({str(x).lower() for x in bt.get("la", ["on"])}, trong_khong)}
    if "khong" in bt:
        return _ma(bt["khong"], True)
    for x in next(iter(bt.values()), []) or []:
        for m, (la, k) in _ma(x, trong_khong).items():
            cu = ra.get(m, (set(), False))
            ra[m] = (cu[0] | la, cu[1] or k)
    return ra


def cham(bai: dict[str, Any] | str, dap_an: dict[str, Any]) -> list[str]:
    """Danh sách LỖI của bài so với đáp án (rỗng = đúng). Bài bị kiểm biên loại (chuỗi) là một lỗi."""
    if isinstance(bai, str):
        return [f"bài bị loại: {bai}"]
    loi: list[str] = []
    for k, v in dap_an.items():
        goc = k.split("_phai_co")[0].split("_khong_co")[0]
        if k.endswith("_mot_trong"):
            goc = k[:-len("_mot_trong")]
            if bai.get(goc) not in v:
                loi.append(f"{goc} phải là một trong {v}, bài viết {bai.get(goc)!r}")
        elif k.endswith("_phai_co_mot"):
            co = _ma(bai.get(goc))
            if not any(m in co for m in v):
                loi.append(f"{goc} phải có ít nhất một trong {v}")
        elif k.endswith("_phai_co"):
            co = _ma(bai.get(goc))
            ds = v.items() if isinstance(v, dict) else ((m, None) for m in v)
            for m, la in ds:
                if m not in co:
                    loi.append(f"{goc} thiếu {m}")
                elif la and not set(la) <= co[m][0]:
                    loi.append(f"{goc}: {m} phải là {la}, bài viết {sorted(co[m][0])}")
        elif k.endswith("_khong_co"):
            co = _ma(bai.get(goc))
            loi += [f"{goc} không được có {m}" for m in v if m in co]
        elif k == "co_nguoi_phu_dinh":
            co = _ma(bai.get("co_nguoi"))
            loi += [f"co_nguoi phải loại lây bằng KHÔNG {m}" for m in v if not co.get(m, (set(), False))[1]]
        elif k == "co_nguoi_phu_dinh_khong":
            co = _ma(bai.get("co_nguoi"))
            loi += [f"co_nguoi không được loại lây {m}" for m in v if co.get(m, (set(), False))[1]]
        elif v is None and bai.get(k) not in (None, [], {}):
            loi.append(f"{k} phải là null")
        elif v is not None and not isinstance(v, (list, dict)) and bai.get(k) != v:
            loi.append(f"{k} phải là {v!r}, bài viết {bai.get(k)!r}")
    return loi


def luyen(ten: str, huong: str, *, lan: int = 1, chi: list[str] | None = None) -> list[dict[str, Any]]:
    """Cho bot giải từng đề của bộ ``ten`` với hướng dẫn ``huong``, chấm. Gọi model thật."""
    from services import hieu_thiet_bi_nha as ht
    from services.thoi_quen_nha import _hoi_bot

    bo = importlib.import_module(f"services.de_luyen.{ten}")
    tang = importlib.import_module(bo.TANG)
    model = ht._model()
    ra = []
    for d in bo.DE:
        if chi and d["ten"] not in chi:
            continue
        # Bộ nào có khuôn đề / cách chấm riêng thì tự khai `de_cho` / `cham_cho`.
        de = ("" if hasattr(bo, "giai_de") else bo.de_cho(d) if hasattr(bo, "de_cho")
              else tang.de(d["uv"], d["ten_tb"], d["dan"]))
        chm = getattr(bo, "cham_cho", cham)
        for i in range(lan):
            if hasattr(bo, "giai_de"):
                # Bộ nào giải nhiều lượt (vd dựng tình huống: từng thiết bị + lượt bổ sung mã bỏ sót) thì tự
                # giải, đúng như lúc chạy thật; hướng dẫn tự ghép theo loại nơi của đề.
                k = bo.giai_de(d, model)
                chm = getattr(bo, "cham_cho", cham)
                ra.append({"de": d["ten"], "lan": i, "loi": chm(k, d["dap_an"]), "vi_sao": ""})
                continue
            b = _hoi_bot(ht, model, huong, de)
            k = tang.kiem(b, d["uv"]) if not isinstance(b, str) else b
            ra.append({"de": d["ten"], "lan": i, "loi": chm(k, d["dap_an"]),
                       "vi_sao": k.get("vi_sao") if isinstance(k, dict) else ""})
    return ra
