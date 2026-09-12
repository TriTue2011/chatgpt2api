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
            # `sai_gan_day` đi kèm để tab hiện rõ "còn đang theo dõi", không
            # phải một nhãn tĩnh "đã tin" đọc như đã đóng băng mãi mãi — sai
            # 2/10 lượt gần nhất là tụt về hỏi lại, xem `can_hoi`.
            diem = [{"loai": l, "diem": round(hieu_thiet_bi_nha.diem(l), 3),
                     "con_hoi": hieu_thiet_bi_nha.can_hoi(l),
                     "sai_gan_day": hieu_thiet_bi_nha.sai_gan_day(l)}
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

    @router.post("/api/hoc-hoi/ket-luan/sua-dieu-kien")
    async def ket_luan_sua_dieu_kien(body: dict, authorization: str | None = Header(default=None)):
        """Sửa TRỰC TIẾP điều kiện của một thiết bị — dùng chung cho mục "Bot
        hiểu thiết bị" và sơ đồ kích hoạt. body: {khoa, dieu_kien: [...]}."""
        require_admin(authorization)
        khoa = str(body.get("khoa") or "")
        ds = [str(x) for x in (body.get("dieu_kien") or [])]
        try:
            from services import hieu_thiet_bi_nha
            ket = await asyncio.to_thread(
                hieu_thiet_bi_nha.sua_dieu_kien_ket_luan, khoa, ds)
            if ket is True:
                return {"ok": True}
            return {"ok": False, "error": str(ket)}
        except Exception as exc:
            return _loi(exc, "sửa điều kiện")

    @router.get("/api/hoc-hoi/dieu-kien-menu")
    async def dieu_kien_menu(authorization: str | None = Header(default=None)):
        """Thực đơn điều kiện có thể chọn — CÙNG nguồn bot dùng khi tự đề
        xuất (`ho_so()["thuc_don_dieu_kien"]`), để web chỉ cho chọn khoá thật."""
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha

            def _lay():
                hs = hieu_thiet_bi_nha.ho_so()
                return hs.get("thuc_don_dieu_kien") or []

            return {"ok": True, "danh_sach": await asyncio.to_thread(_lay)}
        except Exception as exc:
            return _loi(exc, "thực đơn điều kiện")

    @router.post("/api/hoc-hoi/phan-tich-thiet-bi")
    async def phan_tich_thiet_bi(body: dict, authorization: str | None = Header(default=None)):
        """Chủ máy chỉ đích danh một thiết bị bot bỏ sót → giải ngay.
        body: {ma}."""
        require_admin(authorization)
        ma = str(body.get("ma") or "").strip()
        if not ma:
            return {"ok": False, "error": "Thiếu mã thiết bị."}
        try:
            from services import hieu_thiet_bi_nha
            kq = await asyncio.to_thread(hieu_thiet_bi_nha.giai_mot_thiet_bi, ma)
            if kq.get("loi"):
                return {"ok": False, "error": kq["loi"]}
            return {"ok": True, **kq}
        except Exception as exc:
            return _loi(exc, "phân tích thiết bị")

    @router.get("/api/hoc-hoi/thiet-bi-day-du")
    async def thiet_bi_day_du(authorization: str | None = Header(default=None)):
        """Mọi thiết bị/thực thể HA + MQTT + Tuya, kèm tên/khu vực đã biết —
        cho ô chọn thiết bị (mục "Bot hiểu thiết bị") và tab Thiết bị & tên
        trong Settings → Home Assistant."""
        require_admin(authorization)

        def _lay() -> list[dict]:
            from services import so_ten_nha
            da_biet = {d["khoa"]: d for d in so_ten_nha.danh_sach()}
            ra: list[dict] = []

            try:
                from services import ha_client
                trang_thai = ha_client.get_states() or []
                idx = ha_client.get_ha_area_index()
                khu_vuc_ha = idx.get("entity_area") or {}
                for st in trang_thai:
                    eid = str(st.get("entity_id") or "")
                    if not eid:
                        continue
                    k = so_ten_nha.khoa("ha", "thiet_bi", eid)
                    m = da_biet.get(k) or {}
                    ra.append({
                        "khoa": k, "nguon": "ha", "loai": "thiet_bi", "ma": eid,
                        "ten_goc": str((st.get("attributes") or {}).get("friendly_name") or eid),
                        "ten": m.get("ten") or "",
                        "khu_vuc": m.get("khu_vuc") or "",
                        "khu_vuc_goi_y": khu_vuc_ha.get(eid, ""),
                    })
            except Exception as exc:
                logger.warning("hoc-hoi thiet-bi-day-du (ha) lỗi: %s", exc)

            try:
                from services import mqtt_nha
                for d in mqtt_nha.danh_sach_thiet_bi():
                    ma = str(d.get("ten") or "")
                    if not ma:
                        continue
                    k = so_ten_nha.khoa("mqtt", "thiet_bi", ma)
                    m = da_biet.get(k) or {}
                    ra.append({
                        "khoa": k, "nguon": "mqtt", "loai": "thiet_bi", "ma": ma,
                        "ten_goc": ma, "ten": m.get("ten") or "",
                        "khu_vuc": m.get("khu_vuc") or "", "khu_vuc_goi_y": "",
                    })
            except Exception as exc:
                logger.warning("hoc-hoi thiet-bi-day-du (mqtt) lỗi: %s", exc)

            try:
                from services import tuya_nha
                for d in tuya_nha.danh_sach_thiet_bi():
                    ma = str(d.get("id") or "")
                    if not ma:
                        continue
                    k = so_ten_nha.khoa("tuya", "thiet_bi", ma)
                    m = da_biet.get(k) or {}
                    ra.append({
                        "khoa": k, "nguon": "tuya", "loai": "thiet_bi", "ma": ma,
                        "ten_goc": str(d.get("ten") or ma), "ten": m.get("ten") or "",
                        "khu_vuc": m.get("khu_vuc") or "", "khu_vuc_goi_y": "",
                    })
            except Exception as exc:
                logger.warning("hoc-hoi thiet-bi-day-du (tuya) lỗi: %s", exc)

            ra.sort(key=lambda x: (x["nguon"], x["ten_goc"].lower()))
            return ra

        try:
            return {"ok": True, "danh_sach": await asyncio.to_thread(_lay)}
        except Exception as exc:
            return _loi(exc, "danh sách thiết bị đầy đủ")

    @router.get("/api/hoc-hoi/so-do")
    async def so_do(authorization: str | None = Header(default=None)):
        """Sơ đồ kích hoạt: nhân tố chính ← điều kiện + ngoại vi, từng thiết bị.

        KHÔNG đo ở đây — phần đo (`/so-do/do`) tốn vài giây vì phải dựng lại
        bối cảnh từng ô 30 phút. Gộp chung làm cả sơ đồ mất 47 giây, trình
        duyệt bỏ cuộc trước và chủ máy chỉ thấy "chưa có thiết bị nào được
        học" (đo thật 12/09/2026). Sơ đồ hiện ngay, số % điền sau."""
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha
            ds = await asyncio.to_thread(hieu_thiet_bi_nha.so_do_kich_hoat,
                                         kem_so_do=False)
            return {"ok": True, "danh_sach": ds}
        except Exception as exc:
            return _loi(exc, "sơ đồ")

    @router.get("/api/hoc-hoi/so-do/do")
    async def so_do_do(authorization: str | None = Header(default=None)):
        """Số đo thật cho từng điều kiện trên sơ đồ — gọi RIÊNG sau khi sơ đồ
        đã hiện. Trả ``{mã thiết bị: {khoá điều kiện: {nhan_hay_gap, ty_le,
        mau}}}`` để web ghép vào chỗ đang chờ."""
        require_admin(authorization)
        try:
            from services import hieu_thiet_bi_nha

            def _lay():
                ra: dict[str, dict] = {}
                for n in hieu_thiet_bi_nha.so_do_kich_hoat(kem_so_do=True):
                    ra[n["khoa"]] = {
                        m["khoa"]: m["do"]
                        for m in (*n["dieu_kien"], *n["ngoai_vi"])
                        if m.get("khoa") and m.get("do")
                    }
                return ra

            return {"ok": True, "do": await asyncio.to_thread(_lay)}
        except Exception as exc:
            return _loi(exc, "đo sơ đồ")

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

            def _lay():
                ds = du_doan_nha.cho_cham()
                for d in ds:
                    # `giai_thich` đã có sẵn từ trước nhưng tab chưa gọi — chủ
                    # máy chê "giải thích sơ sài" trong khi lý do đã tính rồi.
                    try:
                        d["giai_thich"] = du_doan_nha.giai_thich(d["id"])
                    except Exception:
                        d["giai_thich"] = ""
                return ds

            return {"ok": True, "danh_sach": await asyncio.to_thread(_lay)}
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

    @router.post("/api/hoc-hoi/tinh-huong/sua")
    async def tinh_huong_sua(body: dict, authorization: str | None = Header(default=None)):
        """Sửa đầy đủ một nếp sinh hoạt — không chỉ đổi tên.
        body: {id, ten?, gio?, phut?, thu?}."""
        require_admin(authorization)
        try:
            i = int(body.get("id") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Thiếu id."}
        if not i:
            return {"ok": False, "error": "Thiếu id."}
        kw: dict = {}
        if body.get("ten") is not None:
            kw["ten"] = str(body["ten"])
        if body.get("gio") is not None:
            try:
                kw["gio"] = float(body["gio"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "Giờ không hợp lệ."}
        if body.get("phut") is not None:
            kw["lech_phut"] = int(body["phut"])
        if body.get("thu") is not None:
            kw["thu"] = int(body["thu"])
        try:
            from services import tinh_huong_nha
            ok = tinh_huong_nha.sua(i, **kw)
            return {"ok": ok} if ok else {"ok": False, "error": "Không có dòng đó, hoặc chưa sửa gì."}
        except Exception as exc:
            return _loi(exc, "sửa nếp")

    return router
