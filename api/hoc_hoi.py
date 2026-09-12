"""API cho tab "Học hỏi" — xem / sửa / xoá những gì bot đã học, và tự thêm tay.

Trước đây chỉ có một khối nhỏ lẫn trong thẻ MQTT: xem nếp sinh hoạt + chấm gợi
ý. Phần học sâu nhất (bot hiểu thiết bị, sổ tên, dữ kiện, hướng dẫn) chỉ chấm
được qua chat Zalo, không có màn xem/sửa/xoá. Tab này gom mọi tầng về một chỗ.

Bám khuôn ``api/mqtt.py``: mỗi endpoint ``require_admin``, việc nặng (giải hiểu
thiết bị, quét gợi ý) chạy qua ``asyncio.to_thread`` để không chặn vòng lặp sự
kiện. Mọi thao tác GHI đi qua endpoint HẸP (không POST cả khối config) — sửa một
công tắc không được làm mất khoá khác (bẫy #9: mất ``du_doan.kenh_nhan``).

Bật/tắt từng tầng chỉ nhận đúng năm khoá đã whitelist (``_KHOA_TANG``); không cho
ghi bừa vào config.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header

from api.support import require_admin

logger = logging.getLogger(__name__)

#: Tầng → khoá config ``mqtt.<x>.bat``. Chỉ năm tầng này được bật/tắt qua đây.
_KHOA_TANG = {
    "du_doan": "Gợi ý theo nếp nhà",
    "hieu_thiet_bi": "Bot hiểu thiết bị",
    "tinh_huong": "Nếp sinh hoạt",
    "bai_hoc": "Học từ lỗi",
    "canh_bao": "Báo thiết bị hỏng",
}


def _loi(exc: Exception, viec: str) -> dict:
    logger.warning("hoc-hoi %s lỗi: %s", viec, exc)
    return {"ok": False, "error": str(exc)[:200]}


def create_router() -> APIRouter:
    router = APIRouter()

    # ── Tổng quan ────────────────────────────────────────────────────────────
    @router.get("/api/hoc-hoi/tong-quan")
    async def tong_quan(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import (bai_hoc, canh_bao_nha, du_doan_nha,
                                  hieu_thiet_bi_nha, tinh_huong_nha)
            from services.config import config

            tang = {
                "du_doan": du_doan_nha.is_enabled(),
                "hieu_thiet_bi": hieu_thiet_bi_nha.is_enabled(),
                "tinh_huong": tinh_huong_nha.is_enabled(),
                "bai_hoc": bai_hoc.is_enabled(),
                "canh_bao": canh_bao_nha.is_enabled(),
            }
            diem = [{"loai": l, "diem": round(hieu_thiet_bi_nha.diem(l), 3),
                     "con_hoi": hieu_thiet_bi_nha.can_hoi(l)}
                    for l in hieu_thiet_bi_nha.LOAI_CAU_HOI]
            gan_nhat = (hieu_thiet_bi_nha.lich_su_giai(1) or [None])[0]
            kenh = (((config.data.get("mqtt") or {}).get("du_doan") or {})
                    .get("kenh_nhan") or [])
            return {"ok": True, "tang": tang, "nhan_ten_tang": _KHOA_TANG,
                    "diem": diem, "du_doan": du_doan_nha.thong_ke(),
                    "lan_giai_gan_nhat": gan_nhat, "kenh_nhan": kenh}
        except Exception as exc:
            return _loi(exc, "tổng quan")

    @router.post("/api/hoc-hoi/tang/bat")
    async def tang_bat(body: dict, authorization: str | None = Header(default=None)):
        """Bật/tắt một tầng. body: {khoa: 'du_doan'|…, bat: bool}."""
        require_admin(authorization)
        khoa = str(body.get("khoa") or "")
        if khoa not in _KHOA_TANG:
            return {"ok": False, "error": f"Khoá tầng không hợp lệ: {khoa}"}
        bat = bool(body.get("bat"))
        try:
            from services.config import config

            def _sua(data: dict) -> None:
                mqtt = data.setdefault("mqtt", {})
                muc = mqtt.setdefault(khoa, {})
                muc["bat"] = bat

            config.mutate(_sua)
            logger.info({"event": "hoc_hoi_tang_bat", "khoa": khoa, "bat": bat})
            return {"ok": True, "khoa": khoa, "bat": bat}
        except Exception as exc:
            return _loi(exc, "bật tầng")

    # ── Sổ tên thiết bị ──────────────────────────────────────────────────────
    @router.get("/api/hoc-hoi/ten")
    async def ten(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import so_ten_nha
            return {"ok": True, "danh_sach": so_ten_nha.danh_sach(),
                    "thong_ke": so_ten_nha.thong_ke()}
        except Exception as exc:
            return _loi(exc, "sổ tên")

    @router.post("/api/hoc-hoi/ten/dat")
    async def ten_dat(body: dict, authorization: str | None = Header(default=None)):
        """Thêm/sửa một tên (và khu vực gõ tay). body: {nguon, loai, ma, ten, khu_vuc}."""
        require_admin(authorization)
        try:
            from services import so_ten_nha
            ok = so_ten_nha.dat_ten(
                str(body.get("nguon") or ""), str(body.get("loai") or ""),
                str(body.get("ma") or ""), str(body.get("ten") or ""),
                khu_vuc=str(body.get("khu_vuc") or ""))
            return {"ok": ok} if ok else {"ok": False, "error": "Thiếu mã hoặc tên."}
        except Exception as exc:
            return _loi(exc, "đặt tên")

    @router.post("/api/hoc-hoi/ten/xoa")
    async def ten_xoa(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import so_ten_nha
            ok = so_ten_nha.xoa(str(body.get("khoa") or ""))
            return {"ok": ok} if ok else {"ok": False, "error": "Không có mục đó."}
        except Exception as exc:
            return _loi(exc, "xoá tên")

    # ── Sổ dữ kiện ───────────────────────────────────────────────────────────
    @router.get("/api/hoc-hoi/du-kien")
    async def du_kien(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            return {"ok": True, "danh_sach": hieu_thiet_bi_nha.du_kien_gan_day(200)}
        except Exception as exc:
            return _loi(exc, "dữ kiện")

    @router.post("/api/hoc-hoi/du-kien/ghi")
    async def du_kien_ghi(body: dict, authorization: str | None = Header(default=None)):
        """Thêm (không id) hoặc sửa (có id) một dữ kiện. body: {noi_dung, id?}."""
        require_admin(authorization)
        noi = str(body.get("noi_dung") or "").strip()
        if not noi:
            return {"ok": False, "error": "Thiếu nội dung."}
        try:
            from services import hieu_thiet_bi_nha
            if body.get("id"):
                ok = hieu_thiet_bi_nha.sua_du_kien(int(body["id"]), noi)
                return {"ok": ok} if ok else {"ok": False, "error": "Không có dòng đó."}
            i = hieu_thiet_bi_nha.ghi_du_kien(noi, nguon="tab")
            return {"ok": bool(i), "id": i}
        except Exception as exc:
            return _loi(exc, "ghi dữ kiện")

    @router.post("/api/hoc-hoi/du-kien/xoa")
    async def du_kien_xoa(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            ok = hieu_thiet_bi_nha.xoa_du_kien(int(body.get("id") or 0))
            return {"ok": ok} if ok else {"ok": False, "error": "Không có dòng đó."}
        except Exception as exc:
            return _loi(exc, "xoá dữ kiện")

    # ── Bot hiểu thiết bị: kết luận + sơ đồ + hướng dẫn + lịch sử ─────────────
    @router.get("/api/hoc-hoi/ket-luan")
    async def ket_luan(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha as h

            def _lay():
                ds = h.dang_hieu_luc()
                try:
                    ten = h._ten_ha()
                    for d in ds:
                        try:
                            d["mo_ta"] = h._cau_doc(d, ten)
                        except Exception:
                            d["mo_ta"] = d.get("khoa") or ""
                except Exception:
                    pass
                return ds

            return {"ok": True, "danh_sach": await asyncio.to_thread(_lay)}
        except Exception as exc:
            return _loi(exc, "kết luận")

    @router.post("/api/hoc-hoi/ket-luan/cham")
    async def ket_luan_cham(body: dict, authorization: str | None = Header(default=None)):
        """Chấm lại một kết luận — người chấm là chủ máy. body: {id, dung, ghi_chu}."""
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            ok = hieu_thiet_bi_nha.sua_cham(
                int(body.get("id") or 0), bool(body.get("dung")),
                cham_boi="chu_may", ghi_chu=str(body.get("ghi_chu") or ""))
            return {"ok": ok} if ok else {"ok": False, "error": "Không có kết luận đó."}
        except Exception as exc:
            return _loi(exc, "chấm kết luận")

    @router.post("/api/hoc-hoi/ket-luan/xoa")
    async def ket_luan_xoa(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            ok = hieu_thiet_bi_nha.xoa_ket_luan(int(body.get("id") or 0))
            return {"ok": ok} if ok else {"ok": False, "error": "Không có kết luận đó."}
        except Exception as exc:
            return _loi(exc, "xoá kết luận")

    @router.get("/api/hoc-hoi/so-do")
    async def so_do(authorization: str | None = Header(default=None)):
        """Sơ đồ kích hoạt: nhân tố chính ← điều kiện + ngoại vi, từng thiết bị."""
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            ds = await asyncio.to_thread(hieu_thiet_bi_nha.so_do_kich_hoat)
            return {"ok": True, "danh_sach": ds}
        except Exception as exc:
            return _loi(exc, "sơ đồ")

    @router.get("/api/hoc-hoi/huong-dan")
    async def huong_dan(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            noi, ban = hieu_thiet_bi_nha.huong_dan()
            return {"ok": True, "noi_dung": noi, "phien_ban": ban}
        except Exception as exc:
            return _loi(exc, "hướng dẫn")

    @router.post("/api/hoc-hoi/huong-dan/ghi")
    async def huong_dan_ghi(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            ok = hieu_thiet_bi_nha.ghi_huong_dan(str(body.get("noi_dung") or ""))
            if not ok:
                return {"ok": False, "error": "Nội dung rỗng."}
            _, ban = hieu_thiet_bi_nha.huong_dan()
            return {"ok": True, "phien_ban": ban}
        except Exception as exc:
            return _loi(exc, "ghi hướng dẫn")

    @router.get("/api/hoc-hoi/lich-su-giai")
    async def lich_su_giai(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            return {"ok": True, "danh_sach": hieu_thiet_bi_nha.lich_su_giai(50)}
        except Exception as exc:
            return _loi(exc, "lịch sử giải")

    # ── Gợi ý: đã gửi, còn chờ chấm — id thật, chấm/xoá dùng lại endpoint mqtt ─
    @router.get("/api/hoc-hoi/du-doan/cho-cham")
    async def du_doan_cho_cham(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import du_doan_nha
            return {"ok": True, "danh_sach": du_doan_nha.cho_cham()}
        except Exception as exc:
            return _loi(exc, "gợi ý chờ chấm")

    @router.post("/api/hoc-hoi/du-doan/xoa")
    async def du_doan_xoa(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            from services import du_doan_nha
            ok = du_doan_nha.xoa(int(body.get("id") or 0))
            return {"ok": ok} if ok else {"ok": False, "error": "Không có dòng đó."}
        except Exception as exc:
            return _loi(exc, "xoá gợi ý")

    # ── Nếp sinh hoạt / thói quen: tự thêm tay ───────────────────────────────
    @router.post("/api/hoc-hoi/tinh-huong/them")
    async def tinh_huong_them(body: dict, authorization: str | None = Header(default=None)):
        """Chủ máy tự thêm một nếp sinh hoạt. body: {ten, gio(0-24), phut(±), thu(-1..6)}."""
        require_admin(authorization)
        ten_th = str(body.get("ten") or "").strip()
        if not ten_th:
            return {"ok": False, "error": "Thiếu tên nếp."}
        try:
            gio = float(body.get("gio"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Giờ không hợp lệ (0–24)."}
        try:
            from services import tinh_huong_nha
            i = tinh_huong_nha.them_tay(
                ten_th, gio, lech_phut=int(body.get("phut") or 15),
                thu=int(body.get("thu", -1)))
            return {"ok": bool(i), "id": i} if i else {
                "ok": False, "error": "Giờ ngoài 0–24 hoặc trùng nếp đã có."}
        except Exception as exc:
            return _loi(exc, "thêm nếp")

    return router
