"""Tab Dịch trên Web UI — chữ / link video / tệp (ảnh, tài liệu, video, âm thanh).

Không có bộ dịch nào mới ở đây: tab chỉ là cửa thứ tư đấu vào đúng các đường
mà ba kênh chat đang dùng — ``translate_service`` (chữ, ảnh, tài liệu) và
``video_dich`` (link YouTube, tệp video/âm thanh). Máy dịch là vn-translate
trong stack, không LLM, không dịch vụ ngoài.

Upload CẮT KHÚC (client cắt ~25MB/khúc, gửi tuần tự): đường domain đi qua
Cloudflare tunnel bị chặn thân request ~100MB — một video 720p gửi nguyên
khối là chết ở proxy chứ chưa tới máy. Qua LAN thì khúc to nhỏ đều nhanh.

Việc chậm (nghe video ~0,6× thời lượng; OCR ảnh; dịch tài liệu dài) chạy ở
luồng nền — POST trả ``viec_id`` ngay, UI thăm dò ``GET /api/dich/viec/<id>``.
Kết quả dạng tệp ghi vào ``images_dir/docs/<uuid>/`` và trả đường
``/images/docs/…`` — cùng chỗ, cùng kiểu link mà các kênh chat đang dùng.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from api.support import read_upload_limited, require_admin
from services.config import config

logger = logging.getLogger(__name__)

#: Trần cả tệp. Cao hơn đường Zalo (250MB, tải nguyên tệp vào RAM) vì ở đây
#: khúc ghi thẳng xuống đĩa: 4GB đủ PHIM 1080p ~2 tiếng — khớp trần thời
#: lượng nghe 150 phút, đĩa máy chủ còn ~50GB (đo 13/08).
TRAN_TEP = 4 * 1024 * 1024 * 1024
#: Trần MỘT khúc upload. Client cắt 25MB; 32MB là dư an toàn, và dưới hẳn mức
#: ~100MB mà Cloudflare chặn.
TRAN_KHUC = 32 * 1024 * 1024
#: Chữ xem trước trong JSON thăm dò — bản đầy đủ luôn có trong tệp tải về.
TRAN_CHU_XEM = 30_000

_DUOI_ANH = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

#: viec_id → trạng thái. RAM cho truy cập nhanh, snapshot JSON để restart không
#: biến việc đang chạy thành 404 im lặng; thread bị gián đoạn sẽ hiện lỗi rõ.
_viec: dict[str, dict[str, Any]] = {}
_khoa = threading.Lock()
_GIU_TOI_DA = 40
_HAN_KET_QUA_GIAY = 24 * 3600
# Cùng volume dữ liệu với ảnh/tệp kết quả, không dùng /tmp vốn có thể mất lúc
# container restart. Nội dung chỉ đi qua API admin và file được ghi mode 0600.
_DUONG_SO_VIEC = config.images_dir.parent / "dich-jobs.json"


class DichChuRequest(BaseModel):
    noi_dung: str
    target: str = ""
    #: Tiếng NGUỒN người dùng khai. Rỗng = để máy tự nhận như cũ. Khai rõ thì
    #: dịch được giữa hai tiếng bất kỳ (Nhật → Hàn), còn dạng cặp "cap:xx" cũ
    #: luôn quy về tiếng Việt khi nguồn không phải tiếng Việt.
    nguon: str = ""


class DichTepRequest(BaseModel):
    viec_id: str
    target: str = ""
    #: Tiếng NGUỒN người dùng khai — với video/âm thanh còn giúp khoá cứng
    #: model nghe, khỏi tốn lượt nghe thử để dò.
    nguon: str = ""
    #: Riêng video/âm thanh: "phu-de" (mặc định, .srt) hay "chu" (văn bản
    #: dịch thuần — người dùng chỉ cần lời thoại, không cần mốc thời gian).
    kieu_ra: str = "phu-de"
    #: Giọng TTS chỉ dùng khi ``kieu_ra=long-tieng``. Rỗng = backend chọn
    #: giọng đã tải, rõ tiếng và phù hợp tiếng đích nhất.
    voice: str = ""


def _luu_so_viec_da_khoa() -> None:
    """Ghi sổ việc. Caller đang giữ ``_khoa`` để snapshot nhất quán."""
    from services import dich_jobs

    dich_jobs.luu_so_viec(_DUONG_SO_VIEC, _viec)


def _tai_lai_so_viec_sau_restart() -> None:
    from services import dich_jobs

    da_luu = dich_jobs.tai_so_viec(_DUONG_SO_VIEC)
    if not da_luu:
        return
    _viec.update(dich_jobs.khoi_phuc_sau_restart(da_luu))
    _luu_so_viec_da_khoa()


def _xoa_ket_qua_da_luu(viec: dict[str, Any]) -> None:
    from services import dich_jobs

    dich_jobs.xoa_ket_qua_da_luu(viec, config.images_dir / "docs")


def _don_cu() -> None:
    """Giữ sổ việc gọn. Gọi khi đã giữ ``_khoa``.

    - Việc xong/lỗi cũ nhất bị bỏ khi sổ quá trần.
    - Upload bỏ dở quá 6 giờ thì xoá luôn cả tệp ``.part`` — người dùng chọn
      tệp 250MB rồi đóng trình duyệt là rác nằm lại đĩa, không ai dọn hộ.
    - Tệp kết quả hết hạn sau 24 giờ để MP4 lồng tiếng không lấp volume.
    """
    bay_gio = time.time()
    from services import dich_jobs

    dich_jobs.don_thu_muc_ket_qua(
        config.images_dir / "docs", cu_hon=bay_gio - _HAN_KET_QUA_GIAY)
    han = bay_gio - 6 * 3600
    for k in [k for k, v in _viec.items()
              if v["trang_thai"] == "nhan_tep" and v["luc"] < han]:
        Path(_viec[k]["duong"]).unlink(missing_ok=True)
        _viec.pop(k, None)
    # MP4 lồng tiếng có thể hàng trăm MB; giữ vô hạn sẽ lấp đầy volume dù sổ
    # việc bị giới hạn số dòng. Link kết quả có hiệu lực 24 giờ.
    han_ket_qua = bay_gio - _HAN_KET_QUA_GIAY
    for k in [k for k, v in _viec.items()
              if v["trang_thai"] in ("xong", "loi") and v["luc"] < han_ket_qua]:
        _xoa_ket_qua_da_luu(_viec[k])
        _viec.pop(k, None)
    xong = [k for k, v in _viec.items() if v["trang_thai"] in ("xong", "loi")]
    xong.sort(key=lambda k: _viec[k]["luc"])
    while len(_viec) >= _GIU_TOI_DA and xong:
        cu = _viec.pop(xong.pop(0), None)
        if cu:
            _xoa_ket_qua_da_luu(cu)
    _luu_so_viec_da_khoa()


def _cap_nhat(viec_id: str, **thay) -> None:
    from services import dich_jobs

    with _khoa:
        v = _viec.get(viec_id)
        if v is None:
            return
        v.update(thay)
        bay_gio = time.time()
        # Tiến độ lồng tiếng gọi hàm này mỗi câu thoại; ghi cả sổ kèm fsync
        # ngần ấy lần là hàng trăm MB I/O thừa và giữ ``_khoa`` — cùng khoá mà
        # endpoint nhận khúc upload đang cần.
        if dich_jobs.nen_luu_ngay(v, thay, luc=bay_gio):
            v["luu_luc"] = bay_gio
            _luu_so_viec_da_khoa()


with _khoa:
    _tai_lai_so_viec_sau_restart()


def _luu_ket_tep(cac_tep: list[tuple[str, bytes | str | Path]]) -> list[dict[str, str]]:
    """Ghi các tệp kết quả ra thư mục phục vụ HTTP → [{ten, url}].

    Cùng thư mục và cùng phép làm sạch tên với ``_serve_bytes`` của kênh Zalo
    (tên tệp nằm trong URL, chữ có dấu/ký tự lạ phải về ASCII).
    """
    from services.zalo_personal import _ten_tep_phuc_vu

    thu_muc = config.images_dir / "docs" / uuid.uuid4().hex[:12]
    thu_muc.mkdir(parents=True, exist_ok=True)
    try:
        (thu_muc / ".expire-24h").touch()
        ra = []
        for ten, du_lieu in cac_tep:
            duoi = ten[ten.rfind("."):] if "." in ten else ".txt"
            fn = _ten_tep_phuc_vu(ten, duoi)
            dich = thu_muc / fn
            if isinstance(du_lieu, bytes):
                dich.write_bytes(du_lieu)
            else:
                # Video hàng trăm MB phải copy theo luồng, không đọc cả tệp vào RAM.
                with open(Path(du_lieu), "rb") as src, open(dich, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
            ra.append({"ten": fn, "url": f"/images/docs/{thu_muc.name}/{fn}"})
        return ra
    except Exception:
        shutil.rmtree(thu_muc, ignore_errors=True)
        raise


def _chay_nen(viec_id: str, ham) -> None:
    """Bọc job luồng nền: mọi lỗi về ô ``loi``, không bao giờ nổ im lặng."""

    def _lo():
        try:
            ham()
        except Exception as exc:  # biên hệ thống: lỗi gì cũng phải hiện lên UI
            logger.warning("việc dịch %s lỗi: %s", viec_id, exc)
            _cap_nhat(viec_id, trang_thai="loi", loi=str(exc)[:300],
                      luc=time.time())

    threading.Thread(target=_lo, daemon=True, name=f"dich-{viec_id}").start()


def _xong_phu_de(viec_id: str, r: dict[str, Any], kieu_ra: str = "phu-de") -> None:
    """Kết quả ``dich_video`` / ``dich_tep_video`` → sổ việc.

    ``kieu_ra="chu"``: người dùng chỉ cần LỜI THOẠI đã dịch, không cần mốc
    thời gian — trả văn bản + tệp .txt, không trả .srt.
    """
    from services import video_dich as vd

    if not r.get("ok"):
        _cap_nhat(viec_id, trang_thai="loi", loi=vd.bao_cao(r), luc=time.time())
        return
    long_tieng = r.get("long_tieng") if kieu_ra == "long-tieng" else None
    if long_tieng:
        tep = _luu_ket_tep([
            (f"long-tieng.{r['dich']}.mp4", long_tieng["video_path"]),
            (f"prosody.{r['dich']}.json", long_tieng["prosody_path"]),
            (r["ten"], r["srt"]),
        ])
        ket_qua = {"kieu": "long-tieng", "text": r["chu"][:TRAN_CHU_XEM],
                   "nguon": r["nguon"], "dich": r["dich"], "tep": tep,
                   "voice": long_tieng["voice"]}
    elif kieu_ra == "chu":
        tep = _luu_ket_tep([(f"loi-thoai.{r['dich']}.txt",
                             r["chu"].encode("utf-8"))])
        ket_qua = {"kieu": "chu", "text": r["chu"][:TRAN_CHU_XEM],
                   "nguon": r["nguon"], "dich": r["dich"], "tep": tep}
    else:
        srt = r["srt"].decode("utf-8")
        # Kèm bản chữ-trên cho video đã có chữ in cứng ở đáy hình (VLC/MX hiểu).
        ten_tren = f"phu-de-tren.{r['dich']}.srt"
        tep = _luu_ket_tep([(r["ten"], r["srt"]),
                            (ten_tren, vd.srt_chu_tren(srt).encode("utf-8"))])
        ket_qua = {"kieu": "phu-de", "text": r["chu"][:TRAN_CHU_XEM],
                   "nguon": r["nguon"], "dich": r["dich"], "tep": tep}
    bao_cao = vd.bao_cao(r)
    if r.get("canh_bao_long_tieng"):
        bao_cao += "\n⚠️ " + str(r["canh_bao_long_tieng"])
    elif long_tieng:
        bao_cao += (f"\n🔊 Đã lồng tiếng bằng {long_tieng['voice']}; "
                    "track gốc không được dùng; TTS đã trộn với stem nhạc/hiệu ứng."
                    " Source separation có thể còn rò giọng ở cảnh âm thanh chồng lấn.")
        if long_tieng.get("canh_bao"):
            bao_cao += "\n⚠️ " + str(long_tieng["canh_bao"])
    _cap_nhat(viec_id, trang_thai="xong", luc=time.time(), phan_tram=100,
              bao_cao=bao_cao, ket_qua=ket_qua)


def _xong_chu_hoac_tep(viec_id: str, ket: dict[str, Any], ten: str) -> None:
    """Kết quả ``dich_anh`` / ``dich_tep`` (khuôn chung kieu=chu|tep) → sổ việc."""
    from services import translate_service as ts

    if not ket.get("ok"):
        _cap_nhat(viec_id, trang_thai="loi", luc=time.time(),
                  loi=ts.bao_cao_dich(ket, ten))
        return
    ket_qua: dict[str, Any] = {"kieu": ket.get("kieu"),
                               "nguon": ket.get("nguon"),
                               "dich": ket.get("dich"), "tep": []}
    if ket.get("kieu") == "tep":
        ket_qua["tep"] = _luu_ket_tep([(ket["ten"], ket["data"])])
    else:
        ket_qua["text"] = str(ket.get("text") or "")[:TRAN_CHU_XEM]
    if ket.get("goc"):   # dich_anh kèm chữ OCR gốc để đối chiếu
        ket_qua["goc"] = str(ket["goc"])[:TRAN_CHU_XEM]
    _cap_nhat(viec_id, trang_thai="xong", luc=time.time(),
              bao_cao=ts.bao_cao_dich(ket, ten), ket_qua=ket_qua)


def create_router() -> APIRouter:
    router = APIRouter(tags=["dich"])

    @router.get("/api/dich/giong")
    async def giong_long_tieng(lang: str = "vi",
                              authorization: str | None = Header(None)):
        """Giọng lồng tiếng phù hợp tiếng đích, kèm lựa chọn khuyến nghị."""
        require_admin(authorization)
        lang = str(lang or "").lower().split("-", 1)[0]
        if lang not in {"vi", "en", "zh", "ja", "ko"}:
            raise HTTPException(400, detail={"error": "Tiếng lồng không hợp lệ"})
        from services import tach_am_gpu, video_dub
        separator_ready = True
        separator_error = ""
        try:
            tach_am_gpu.xac_nhan_san_sang()
        except tach_am_gpu.LoiTachAm as exc:
            separator_ready = False
            separator_error = str(exc)[:180]
        return {"voices": video_dub.danh_sach_giong(lang),
                "separator_ready": separator_ready,
                "separator_error": separator_error}

    @router.post("/api/dich/chu")
    async def dich_chu(body: DichChuRequest,
                       authorization: str | None = Header(None)):
        """Dán chữ → dịch ngay (đồng bộ). Dán link video → việc nền."""
        require_admin(authorization)
        nd = (body.noi_dung or "").strip()
        if not nd:
            raise HTTPException(400, detail={"error": "Chưa có gì để dịch"})
        from services import translate_service as ts
        from services import video_dich as vd
        if vd.la_link_video(nd):
            with _khoa:
                _don_cu()
                viec_id = uuid.uuid4().hex[:12]
                _viec[viec_id] = {"trang_thai": "dang_chay", "luc": time.time(),
                                  "buoc": "đang lấy phụ đề và dịch…"}
                _luu_so_viec_da_khoa()
            _chay_nen(viec_id, lambda: _xong_phu_de(
                viec_id, vd.dich_video(nd, body.target,
                                       nguon_biet=(body.nguon or "").strip())))
            return {"viec_id": viec_id}

        if not ts.is_configured():
            raise HTTPException(
                503, detail={"error": "Chưa cấu hình máy chủ dịch (translate_url)"})

        try:
            nguon = (body.nguon or "").strip().lower()
            if not nguon:
                nguon, _ = ts.detect(nd[:5000])
            dich = ts.giai_ma_target(nguon, body.target)
            if nguon and nguon == dich:
                raise HTTPException(
                    400, detail={"error": f"Văn bản đã là tiếng `{dich}`"})
            text = ts.translate(nd, dich, nguon or "auto")
        except ts.LoiDich as exc:
            raise HTTPException(502, detail={"error": str(exc)})
        return {"kieu": "chu", "text": text, "nguon": nguon or "auto",
                "dich": dich}

    @router.post("/api/dich/khuc")
    async def nhan_khuc(viec_id: str = Form(""), chi_so: int = Form(...),
                        tong: int = Form(...), ten: str = Form(""),
                        khuc: UploadFile = File(...),
                        authorization: str | None = Header(None)):
        """Nhận MỘT khúc tệp. Khúc 0 bỏ trống ``viec_id`` — máy chủ cấp."""
        require_admin(authorization)
        du_lieu = await read_upload_limited(khuc, TRAN_KHUC)
        with _khoa:
            if not viec_id:
                if chi_so != 0:
                    raise HTTPException(
                        400, detail={"error": "Khúc đầu phải là chi_so=0"})
                if not str(ten or "").strip():
                    raise HTTPException(400, detail={"error": "Thiếu tên tệp"})
                _don_cu()
                viec_id = uuid.uuid4().hex[:12]
                _viec[viec_id] = {
                    "trang_thai": "nhan_tep", "luc": time.time(),
                    "ten": str(ten).strip(), "tong": max(1, int(tong)),
                    "next": 0, "size": 0,
                    "duong": str(Path(tempfile.gettempdir())
                                 / f"updich-{viec_id}.part"),
                }
                _luu_so_viec_da_khoa()
            v = _viec.get(viec_id)
            if v is None or v["trang_thai"] != "nhan_tep":
                raise HTTPException(404, detail={"error": "Không thấy việc upload này"})
            if chi_so != v["next"]:
                raise HTTPException(
                    409, detail={"error": f"Lệch thứ tự khúc: chờ {v['next']}, nhận {chi_so}"})
            if v["size"] + len(du_lieu) > TRAN_TEP:
                Path(v["duong"]).unlink(missing_ok=True)
                _viec.pop(viec_id, None)
                _luu_so_viec_da_khoa()
                raise HTTPException(
                    413, detail={"error": f"Tệp vượt trần {TRAN_TEP // (1024*1024)}MB"})
            with open(v["duong"], "ab") as f:
                f.write(du_lieu)
            v["next"] += 1
            v["size"] += len(du_lieu)
            v["luc"] = time.time()
            _luu_so_viec_da_khoa()
            return {"viec_id": viec_id, "da_nhan": v["next"], "tong": v["tong"]}

    @router.post("/api/dich/tep")
    async def bat_dau_dich_tep(body: DichTepRequest,
                               authorization: str | None = Header(None)):
        """Đủ khúc rồi → chốt tệp, chọn đường dịch theo đuôi, chạy nền."""
        require_admin(authorization)
        with _khoa:
            v = _viec.get(body.viec_id)
            if v is None or v["trang_thai"] != "nhan_tep":
                raise HTTPException(404, detail={"error": "Không thấy việc upload này"})
            if v["next"] < v["tong"]:
                raise HTTPException(
                    400, detail={"error": f"Mới nhận {v['next']}/{v['tong']} khúc"})
            v["trang_thai"] = "dang_chay"
            v["buoc"] = "đang chuẩn bị…"
            v["luc"] = time.time()
            _luu_so_viec_da_khoa()
            ten, duong = v["ten"], v["duong"]
        viec_id, target = body.viec_id, body.target
        nguon_biet = (body.nguon or "").strip().lower()
        kieu_ra = (body.kieu_ra if body.kieu_ra in
                   {"chu", "phu-de", "long-tieng"} else "phu-de")

        from services import video_asr as va
        from services import video_dich as vd
        from services import translate_service as ts

        thap = ten.lower()
        if kieu_ra == "long-tieng" and not thap.endswith(va.DUOI_VIDEO):
            Path(duong).unlink(missing_ok=True)
            _cap_nhat(viec_id, trang_thai="loi", luc=time.time(),
                      loi="Lồng tiếng cần tệp video, không nhận tệp âm thanh/phụ đề.")
            return {"viec_id": viec_id}
        if kieu_ra == "long-tieng":
            from services import tach_am_gpu

            try:
                tach_am_gpu.xac_nhan_san_sang()
            except tach_am_gpu.LoiTachAm as exc:
                Path(duong).unlink(missing_ok=True)
                _cap_nhat(
                    viec_id, trang_thai="loi", luc=time.time(),
                    loi=f"Chưa thể lồng tiếng: {exc}. Hãy bật máy tách lời hoặc "
                        "chọn Phụ đề để không phải chờ xử lý cả video.")
                return {"viec_id": viec_id}
        if va.la_tep_nghe_duoc(thap):
            def _video():
                def _tien_do(buoc: str, phan_tram: int | None, _moc: bool) -> None:
                    # Web hiện MỌI lượt (kể cả từng lô dịch); cờ mốc chỉ dành
                    # cho kênh chat, nơi mỗi lượt là một tin nhắn.
                    if kieu_ra == "long-tieng" and phan_tram is not None:
                        phan_tram = round(phan_tram * 0.8)
                    _cap_nhat(viec_id, buoc=buoc, phan_tram=phan_tram,
                              luc=time.time())

                tep_tam: list[str] = []
                try:
                    r = vd.dich_tep_video(duong, ten, target,
                                          nguon_biet=nguon_biet, tien_do=_tien_do)
                    if (kieu_ra == "long-tieng" and r.get("ok")
                            and not r.get("canh_bao_dich")):
                        from services import video_dub

                        try:
                            giong = video_dub.chon_giong(
                                str(r.get("dich") or target), body.voice.strip())

                            def _tien_do_tts(xong: int, tong: int, buoc: str) -> None:
                                if "tách" in buoc or "soundtrack" in buoc:
                                    pt = 80 + round(5 * xong / max(1, tong))
                                else:
                                    pt = 85 + round(14 * xong / max(1, tong))
                                _cap_nhat(viec_id, buoc=buoc, phan_tram=pt,
                                          luc=time.time())

                            dub = video_dub.long_tieng(
                                duong, r["srt"], str(r["dich"]), voice=giong,
                                progress=_tien_do_tts)
                            tep_tam.extend([dub.video_path, dub.prosody_path])
                            r["long_tieng"] = {
                                "video_path": dub.video_path,
                                "prosody_path": dub.prosody_path,
                                "voice": dub.voice,
                                "canh_bao": dub.canh_bao,
                            }
                        except Exception as exc:
                            logger.warning("lồng tiếng %s lỗi: %s", ten, str(exc)[:200])
                            r["canh_bao_long_tieng"] = (
                                f"Lồng tiếng không hoàn thành: {str(exc)[:220]}; "
                                "đã giữ lại SRT để không mất kết quả nghe/dịch.")
                    elif kieu_ra == "long-tieng" and r.get("canh_bao_dich"):
                        r["canh_bao_long_tieng"] = (
                            "Không lồng tiếng vì máy dịch đã rơi về phụ đề gốc; "
                            "đã giữ lại SRT để tránh đọc sai ngôn ngữ đích.")
                    _xong_phu_de(viec_id, r, kieu_ra)
                finally:
                    Path(duong).unlink(missing_ok=True)
                    for p in tep_tam:
                        Path(p).unlink(missing_ok=True)

            _chay_nen(viec_id, _video)
        elif vd.la_tep_phu_de(thap):
            # Tệp phụ đề sẵn (.srt/.vtt) — đường nhanh + chuẩn nhất cho phim:
            # không phải nghe, chỉ dịch, và đi chung dây chuyền khung phụ đề.
            def _phu_de():
                _cap_nhat(viec_id, buoc="đang dịch phụ đề…")
                try:
                    r = vd.dich_tep_phu_de(duong, ten, target)
                finally:
                    Path(duong).unlink(missing_ok=True)
                _xong_phu_de(viec_id, r, kieu_ra)

            _chay_nen(viec_id, _phu_de)
        elif thap.endswith(_DUOI_ANH):
            def _anh():
                _cap_nhat(viec_id, buoc="đang đọc chữ trong ảnh rồi dịch…")
                du_lieu = Path(duong).read_bytes()
                Path(duong).unlink(missing_ok=True)
                _xong_chu_hoac_tep(
                    viec_id, ts.dich_anh(du_lieu, target, channel="web"), ten)

            _chay_nen(viec_id, _anh)
        else:
            def _tai_lieu():
                _cap_nhat(viec_id, buoc="đang đọc tài liệu rồi dịch…")
                try:
                    ket = ts.dich_tep(duong, ten, target)
                finally:
                    Path(duong).unlink(missing_ok=True)
                _xong_chu_hoac_tep(viec_id, ket, ten)

            _chay_nen(viec_id, _tai_lieu)
        return {"viec_id": viec_id}

    @router.post("/api/dich/noi")
    async def dich_noi(tieng: UploadFile = File(...), lang_noi: str = Form(...),
                       lang_kia: str = Form(...), tts: str = Form("0"),
                       authorization: str | None = Header(None)):
        """Một LƯỢT đàm thoại: nghe tiếng ``lang_noi`` → dịch sang ``lang_kia``.

        Bấm-nói-thả, không streaming: blob mic vài chục giây → nghe bằng model
        offline của ĐÚNG tiếng người bấm (không cần dò — người dùng bấm mic
        bên nào là khai tiếng bên đó) → dịch → tuỳ chọn đọc bản dịch.
        TTS chỉ có giọng vi (NghiTTS/Piper) và en (Kokoro); tiếng khác trả
        chữ thôi.
        """
        require_admin(authorization)
        hop_le = {"vi", "en", "zh", "ja", "ko"}
        lang_noi = str(lang_noi or "").lower()
        lang_kia = str(lang_kia or "").lower()
        if lang_noi not in hop_le or lang_kia not in hop_le or lang_noi == lang_kia:
            raise HTTPException(400, detail={"error": "Cặp tiếng không hợp lệ"})
        from services import translate_service as ts
        if not ts.is_configured():
            raise HTTPException(
                503, detail={"error": "Chưa cấu hình máy chủ dịch (translate_url)"})
        du_lieu = await read_upload_limited(tieng, 16 * 1024 * 1024)

        from services import video_asr as va
        from services.voice import engines as eng

        duoi = Path(str(tieng.filename or "mic.webm")).suffix or ".webm"
        tam = Path(tempfile.gettempdir()) / f"noi-{uuid.uuid4().hex[:8]}{duoi}"
        tam.write_bytes(du_lieu)
        try:
            wav = va._boc_tieng(str(tam))
        except va.LoiNghe as exc:
            raise HTTPException(400, detail={"error": str(exc)})
        finally:
            tam.unlink(missing_ok=True)
        try:
            mau, rate = va._doc_wav(wav)
        finally:
            Path(wav).unlink(missing_ok=True)
        if len(mau) / rate > 90:
            raise HTTPException(400, detail={
                "error": "Một lượt nói tối đa 90 giây — video dài thì dùng ô Dịch tệp"})
        # Đệm 0,24s lặng hai đầu: người dùng nói NGAY khi bấm nên phụ âm đầu
        # hay dính sát mép clip — thiếu ngữ cảnh onset là model nuốt chữ
        # ("mai là thứ mấy" → "ai là thứ mấy", đo thật 14/08).
        import numpy as np
        dem = np.zeros(int(0.24 * rate), dtype=mau.dtype)
        mau = np.concatenate([dem, mau, dem])
        # Lượt nói ngắn (≤28s — đại đa số) nghe NGUYÊN CLIP, không qua bộ cắt
        # đoạn-có-tiếng: bộ đó sinh ra cho video dài, ngưỡng năng lượng tương
        # đối có thể xén mất âm đầu nói nhỏ. Dài hơn mới phải cắt.
        if len(mau) / rate <= va.DOAN_TOI_DA:
            doan = [(0.0, len(mau) / rate)]
        else:
            doan = va.cat_doan_tieng(mau, rate) or [(0.0, len(mau) / rate)]
        try:
            rec = eng._get_recognizer(lang_noi)
        except Exception as exc:
            raise HTTPException(503, detail={"error": str(exc)[:200]})
        manh: list[str] = []
        for b, k in doan:
            with eng._stt_lock:
                tokens, _ = va._nghe_mot_doan(
                    rec, mau[int(b * rate):int(k * rate)], rate)
            manh.append("".join(tokens).strip())
        chu_goc = eng._normalize_stt(" ".join(m for m in manh if m))
        if not chu_goc:
            return {"goc": "", "dich": "", "tieng": None}
        try:
            ban_dich = ts.translate(chu_goc, lang_kia, lang_noi)
        except ts.LoiDich as exc:
            raise HTTPException(502, detail={"error": str(exc)})

        tieng_b64 = None
        if str(tts) == "1":
            try:
                import base64
                if lang_kia in ("vi", "en"):
                    # Giọng lấy theo Cài đặt → Loa & giọng nói (vi mặc định
                    # của máy; en theo voice.wyoming_server.en_voice).
                    from services.voice import config as vc
                    giong = "" if lang_kia == "vi" else vc.wyoming_en_voice()
                    wav = eng.synthesize(ban_dich, giong)
                else:   # zh/ja/ko — giọng riêng của phiên dịch đàm thoại
                    wav = eng.synthesize_da_ngu(ban_dich, lang_kia)
                tieng_b64 = base64.b64encode(wav).decode("ascii")
            except Exception as exc:   # thiếu model giọng → vẫn trả chữ
                logger.info("đàm thoại TTS lỗi: %s", str(exc)[:120])
        return {"goc": chu_goc, "dich": ban_dich, "tieng": tieng_b64}

    @router.get("/api/dich/viec/{viec_id}")
    async def xem_viec(viec_id: str, authorization: str | None = Header(None)):
        require_admin(authorization)
        with _khoa:
            v = _viec.get(viec_id)
            if v is None:
                raise HTTPException(
                    404, detail={"error": "Không thấy việc này (máy chủ có thể "
                                 "vừa khởi động lại) — gửi lại giúp nhé"})
            # ``phan_tram`` vắng mặt = giai đoạn không đo được (Whisper GPU gửi
            # cả tệp một lần) → giao diện chạy thanh vô định, không tự điền 0.
            ra: dict[str, Any] = {"trang_thai": v["trang_thai"],
                                  "buoc": v.get("buoc", ""),
                                  "phan_tram": v.get("phan_tram")}
            if v["trang_thai"] == "xong":
                ra["ket_qua"] = v.get("ket_qua")
                ra["bao_cao"] = v.get("bao_cao", "")
            elif v["trang_thai"] == "loi":
                ra["loi"] = v.get("loi", "lỗi không rõ")
        return ra

    return router
