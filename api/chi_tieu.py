"""API tab Chi tiêu (`web/src/app/chi-tieu`) — `services/chi_tieu`.

Chủ máy 02/10/2026: "mỗi account chỉ xem được chi tiêu của họ, kể cả admin cũng thế" — mọi đường dưới
``/api/chi-tieu`` lấy sổ từ CHÍNH danh tính đăng nhập (``require_identity``), không bao giờ nhận ``so_id`` từ ngoài.
"Nhưng admin nhìn thấy tên sổ chi tiêu, để gán theo zalo tương ứng" — nhánh ``/api/chi-tieu/quan-tri`` chỉ trả TÊN
sổ và liên kết, không có số tiền; gán thì bot báo cho chính người được gán.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Header

from api.support import require_admin, require_identity
from services.chi_tieu import kho, ngan_sach as ns, nghiep_vu as nv


def _ok(f, *a, **k) -> dict[str, Any]:
    try:
        return {"ok": True, **(f(*a, **k) or {})}
    except nv.LoiChiTieu as exc:
        return {"ok": False, "error": str(exc)}


def _so(authorization: str | None) -> dict[str, Any]:
    return nv.so_cua_tai_khoan(require_identity(authorization))  # type: ignore[return-value]


_BANG = {"thu-nhap": "thu_nhap_them", "dac-biet": "chi_phi_dac_biet"}
_NEN = {"zalop": "zalop_", "zalo": "zalo_", "tg": ""}


def create_router() -> APIRouter:
    r = APIRouter()

    @r.get("/api/chi-tieu")
    async def tong_quan(thang: str = "", authorization: str | None = Header(default=None)):
        ident = require_identity(authorization)
        s = nv.so_cua_tai_khoan(ident)

        def lam():
            return {"so": s, "ngan_sach": nv.xem_ngan_sach(s["id"], thang), "hu": kho.ds_hu(s["id"]),
                    "tong_ty_le": nv.tong_ty_le(s["id"]),
                    "lien_ket": [{k: x[k] for k in ("kenh_user", "ten", "gan_boi", "luc")}
                                 for x in kho.kenh_cua_so(s["id"])],
                    "la_admin": ident.get("role") == "admin"}
        return await asyncio.to_thread(_ok, lam)

    @r.get("/api/chi-tieu/lich-su")
    async def lich_su(thang: str = "", authorization: str | None = Header(default=None)):
        s = _so(authorization)
        return _ok(nv.xem_lich_su, s["id"], thang)

    @r.get("/api/chi-tieu/thong-ke")
    async def thong_ke(so_ky: int = 6, authorization: str | None = Header(default=None)):
        s = _so(authorization)
        so_ky = max(1, min(int(so_ky or 6), 12))
        hien = ns.ky_hien_tai(s)
        ky = []
        for lui in range(so_ky - 1, -1, -1):
            t = ns.lui_ky(hien, lui)
            theo = kho.tong_chi_theo_hu(s["id"], t)
            ky.append({"thang": t, "tong_chi": sum(theo.values()), "theo_hu": {str(k): v for k, v in theo.items()}})
        ngay: dict[str, int] = {}
        for x in kho.ds_chi(s["id"], hien):
            ngay[x["thoi_gian"][:10]] = ngay.get(x["thoi_gian"][:10], 0) + int(x["so_tien"])
        return {"ok": True, "ky": ky, "theo_ngay": [{"ngay": k, "tong": v} for k, v in sorted(ngay.items())]}

    @r.get("/api/chi-tieu/de-xuat")
    async def de_xuat(authorization: str | None = Header(default=None)):
        s = _so(authorization)
        return await asyncio.to_thread(_ok, nv.de_xuat, s["id"])

    # ── Khoản chi ──
    @r.post("/api/chi-tieu/chi")
    async def them_chi(body: dict, authorization: str | None = Header(default=None)):
        s = _so(authorization)
        return _ok(nv.ghi_chi, s["id"], body.get("hu_id"), body.get("so_tien"), body.get("ghi_chu") or "",
                   bool(body.get("xac_nhan_vuot_tong")), nguon="web")

    @r.post("/api/chi-tieu/chi/{id_}")
    async def sua_chi(id_: int, body: dict, authorization: str | None = Header(default=None)):
        s = _so(authorization)
        return _ok(nv.sua_chi, s["id"], id_, hu=body.get("hu_id"), so_tien=body.get("so_tien"),
                   ghi_chu=body.get("ghi_chu"), xac_nhan_vuot_tong=bool(body.get("xac_nhan_vuot_tong")))

    @r.delete("/api/chi-tieu/chi/{id_}")
    async def xoa_chi(id_: int, authorization: str | None = Header(default=None)):
        return _ok(nv.xoa_chi, _so(authorization)["id"], id_)

    @r.post("/api/chi-tieu/chi/{id_}/tach")
    async def tach(id_: int, body: dict, authorization: str | None = Header(default=None)):
        return _ok(nv.tach_chi, _so(authorization)["id"], id_, body.get("danh_sach") or [])

    # ── Thu nhập thêm / chi phí đặc biệt ──
    @r.post("/api/chi-tieu/ky/{loai}")
    async def them_ky(loai: str, body: dict, authorization: str | None = Header(default=None)):
        if loai not in _BANG:
            return {"ok": False, "error": "loai là thu-nhap | dac-biet"}
        return _ok(nv.ghi_ky, _BANG[loai], _so(authorization)["id"], body.get("mo_ta"), body.get("so_tien"))

    @r.post("/api/chi-tieu/ky/{loai}/{id_}")
    async def sua_ky(loai: str, id_: int, body: dict, authorization: str | None = Header(default=None)):
        if loai not in _BANG:
            return {"ok": False, "error": "loai là thu-nhap | dac-biet"}
        return _ok(nv.sua_ky, _BANG[loai], _so(authorization)["id"], id_, body.get("mo_ta"), body.get("so_tien"))

    @r.delete("/api/chi-tieu/ky/{loai}/{id_}")
    async def xoa_ky(loai: str, id_: int, authorization: str | None = Header(default=None)):
        if loai not in _BANG:
            return {"ok": False, "error": "loai là thu-nhap | dac-biet"}
        return _ok(nv.xoa_ky, _BANG[loai], _so(authorization)["id"], id_)

    # ── Cấu hình sổ & hũ ──
    @r.post("/api/chi-tieu/cau-hinh")
    async def cau_hinh(body: dict, authorization: str | None = Header(default=None)):
        return _ok(nv.luu_cau_hinh, _so(authorization)["id"], ten=body.get("ten"), luong=body.get("luong"),
                   ngay_bat_dau=body.get("ngay_bat_dau"), nguong=body.get("nguong"))

    @r.post("/api/chi-tieu/hu")
    async def them_hu(body: dict, authorization: str | None = Header(default=None)):
        return _ok(nv.them_hu, _so(authorization)["id"], body.get("ten"), body.get("ty_le", 0),
                   body.get("thu_tu_bu", 50), body.get("thu_tu_dac_biet", 0))

    @r.post("/api/chi-tieu/hu/{hu_id}")
    async def sua_hu(hu_id: int, body: dict, authorization: str | None = Header(default=None)):
        truong = {k: body[k] for k in ("ten", "ty_le", "thu_tu", "thu_tu_bu", "thu_tu_dac_biet") if k in body}
        return _ok(nv.sua_hu, _so(authorization)["id"], hu_id, **truong)

    @r.delete("/api/chi-tieu/hu/{hu_id}")
    async def xoa_hu(hu_id: int, authorization: str | None = Header(default=None)):
        return _ok(nv.xoa_hu, _so(authorization)["id"], hu_id)

    # ── Tạm ứng công ty ──
    @r.get("/api/chi-tieu/cong-ty")
    async def cong_ty(authorization: str | None = Header(default=None)):
        return _ok(nv.xem_cong_ty, _so(authorization)["id"])

    @r.post("/api/chi-tieu/cong-ty")
    async def them_cong_ty(body: dict, authorization: str | None = Header(default=None)):
        return _ok(nv.ghi_cong_ty, _so(authorization)["id"], str(body.get("loai") or ""), body.get("so_tien"),
                   body.get("mo_ta"))

    # Khai báo TRƯỚC `/cong-ty/{id_}`: sau nó thì "giai-chi" bị đường kia bắt rồi trả 422 (id phải là số).
    @r.post("/api/chi-tieu/cong-ty/giai-chi")
    async def giai_chi(authorization: str | None = Header(default=None)):
        return _ok(nv.giai_chi, _so(authorization)["id"])

    @r.post("/api/chi-tieu/cong-ty/{id_}")
    async def sua_cong_ty(id_: int, body: dict, authorization: str | None = Header(default=None)):
        s = _so(authorization)

        def lam():
            truong: dict[str, Any] = {}
            if body.get("loai") is not None:
                if body["loai"] not in ("tam_ung", "chi"):
                    raise nv.LoiChiTieu("loai là tam_ung hoặc chi")
                truong["loai"] = body["loai"]
            if body.get("so_tien") is not None:
                truong["so_tien"] = nv._tien(body["so_tien"])
            if body.get("mo_ta") is not None:
                truong["mo_ta"] = nv._chu(body["mo_ta"], "mo_ta")
            if not truong or not kho.sua_cong_ty(s["id"], id_, **truong):
                raise nv.LoiChiTieu("Không có giao dịch đang mở này (đã giải chi thì không sửa được).")
            return {"da_sua": True}
        return _ok(lam)

    @r.delete("/api/chi-tieu/cong-ty/{id_}")
    async def xoa_cong_ty(id_: int, authorization: str | None = Header(default=None)):
        s = _so(authorization)

        def lam():
            if not kho.xoa_cong_ty(s["id"], id_):
                raise nv.LoiChiTieu("Không có giao dịch đang mở này (đã giải chi thì không xoá được).")
            return {"da_xoa": True}
        return _ok(lam)

    @r.get("/api/chi-tieu/giai-chi/{gid}")
    async def xem_giai_chi(gid: int, authorization: str | None = Header(default=None)):
        s = _so(authorization)
        g = kho.giai_chi(s["id"], gid)
        if g is None:
            return {"ok": False, "error": "Không có lần giải chi này."}
        return {"ok": True, "giai_chi": g, "giao_dich": kho.ds_cong_ty(s["id"], gid), "ten_so": s["ten"]}

    # ── Liên kết Zalo / Telegram ──
    @r.post("/api/chi-tieu/lien-ket/ma")
    async def tao_ma(authorization: str | None = Header(default=None)):
        return _ok(nv.tao_ma_lien_ket, _so(authorization)["id"])

    @r.post("/api/chi-tieu/lien-ket/bo")
    async def bo_lien_ket(body: dict, authorization: str | None = Header(default=None)):
        s = _so(authorization)

        def lam():
            if not kho.bo_kenh(str(body.get("kenh_user") or ""), s["id"]):
                raise nv.LoiChiTieu("Liên kết này không thuộc sổ của bạn.")
            return {"da_bo": True}
        return _ok(lam)

    # ── Quản trị: CHỈ tên sổ + liên kết, không số tiền ──
    @r.get("/api/chi-tieu/quan-tri")
    async def quan_tri(authorization: str | None = Header(default=None)):
        require_admin(authorization)

        def lam():
            from services import channel_contacts as cc
            nguoi = []
            for nen, tien_to in _NEN.items():
                try:
                    for x in cc.list_directory(nen, limit=300):
                        if x.get("kind") == "user" and x.get("thread_id"):
                            nguoi.append({"kenh_user": f"{tien_to}{x['thread_id']}", "ten": x.get("name") or "",
                                          "kenh": nen, "bot": x.get("bot_label") or "",
                                          "bot_id": str(x.get("bot_id") or "")})
                except Exception:
                    continue
            return {"so": kho.moi_so(), "nguoi": nguoi}
        return await asyncio.to_thread(_ok, lam)

    @r.post("/api/chi-tieu/quan-tri/gan")
    async def gan(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)

        def lam():
            kenh_user = str(body.get("kenh_user") or "").strip()
            so_id = int(body.get("so_id") or 0)
            s = kho.so(so_id)
            if not kenh_user or s is None:
                raise nv.LoiChiTieu("Cần kenh_user và so_id hợp lệ.")
            nen = "zalop" if kenh_user.startswith("zalop_") else "zalo" if kenh_user.startswith("zalo_") else "tg"
            bot_id = str(body.get("bot_id") or "")
            meta = ({"account": bot_id, "thread_type": 0} if nen == "zalop" else {"bot_id": bot_id}) if bot_id else {}
            kho.gan_kenh(kenh_user, so_id, str(body.get("ten") or ""), meta, "admin")
            # Minh bạch: người được gán biết ngay mình vừa được gắn vào sổ nào — admin không gán lén được.
            gui = 0
            try:
                from services.agent import reminders
                from services.chi_tieu.canh_bao import co_the_nhan_tin
                if co_the_nhan_tin(kenh_user):
                    k, chat = reminders.channel_of(kenh_user)
                    reminders._send(k, chat, f"💰 Zalo/Telegram này vừa được quản trị gắn vào sổ chi tiêu «{s['ten']}». "
                                             "Từ giờ khoản chi bạn nhắn sẽ ghi vào sổ đó. Không đúng thì nhắn lại "
                                             "quản trị.", meta)
                    gui = 1
            except Exception:
                gui = 0
            return {"da_gan": True, "da_bao": bool(gui)}
        return await asyncio.to_thread(_ok, lam)

    @r.post("/api/chi-tieu/quan-tri/bo")
    async def bo(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"ok": kho.bo_kenh(str(body.get("kenh_user") or ""))}

    @r.post("/api/chi-tieu/quan-tri/tao-so")
    async def tao_so(body: dict, authorization: str | None = Header(default=None)):
        """Sổ cho người CHỈ dùng qua chat (không có tài khoản web) — không chủ web nào xem được nội dung."""
        require_admin(authorization)
        return _ok(lambda: {"so": {k: v for k, v in kho.tao_so(nv._chu(body.get("ten"), "tên sổ", 80), None).items()
                                   if k in ("id", "ten")}})

    return r
