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

#: viec_id → trạng thái. Sống trong RAM: mất khi restart là chấp nhận được
#: (UI báo "không thấy việc", người dùng gửi lại), đổi lấy việc không phải
#: kéo thêm hàng đợi/DB cho một tab công cụ.
_viec: dict[str, dict[str, Any]] = {}
_khoa = threading.Lock()
_GIU_TOI_DA = 40


class DichChuRequest(BaseModel):
    noi_dung: str
    target: str = ""


class DichTepRequest(BaseModel):
    viec_id: str
    target: str = ""
    #: Riêng video/âm thanh: "phu-de" (mặc định, .srt) hay "chu" (văn bản
    #: dịch thuần — người dùng chỉ cần lời thoại, không cần mốc thời gian).
    kieu_ra: str = "phu-de"


def _don_cu() -> None:
    """Giữ sổ việc gọn. Gọi khi đã giữ ``_khoa``.

    - Việc xong/lỗi cũ nhất bị bỏ khi sổ quá trần.
    - Upload bỏ dở quá 6 giờ thì xoá luôn cả tệp ``.part`` — người dùng chọn
      tệp 250MB rồi đóng trình duyệt là rác nằm lại đĩa, không ai dọn hộ.
    """
    han = time.time() - 6 * 3600
    for k in [k for k, v in _viec.items()
              if v["trang_thai"] == "nhan_tep" and v["luc"] < han]:
        Path(_viec[k]["duong"]).unlink(missing_ok=True)
        _viec.pop(k, None)
    xong = [k for k, v in _viec.items() if v["trang_thai"] in ("xong", "loi")]
    xong.sort(key=lambda k: _viec[k]["luc"])
    while len(_viec) >= _GIU_TOI_DA and xong:
        _viec.pop(xong.pop(0), None)


def _cap_nhat(viec_id: str, **thay) -> None:
    with _khoa:
        v = _viec.get(viec_id)
        if v is not None:
            v.update(thay)


def _luu_ket_tep(cac_tep: list[tuple[str, bytes]]) -> list[dict[str, str]]:
    """Ghi các tệp kết quả ra thư mục phục vụ HTTP → [{ten, url}].

    Cùng thư mục và cùng phép làm sạch tên với ``_serve_bytes`` của kênh Zalo
    (tên tệp nằm trong URL, chữ có dấu/ký tự lạ phải về ASCII).
    """
    from services.zalo_personal import _ten_tep_phuc_vu

    thu_muc = config.images_dir / "docs" / uuid.uuid4().hex[:12]
    thu_muc.mkdir(parents=True, exist_ok=True)
    ra = []
    for ten, du_lieu in cac_tep:
        duoi = ten[ten.rfind("."):] if "." in ten else ".txt"
        fn = _ten_tep_phuc_vu(ten, duoi)
        (thu_muc / fn).write_bytes(du_lieu)
        ra.append({"ten": fn, "url": f"/images/docs/{thu_muc.name}/{fn}"})
    return ra


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
    if kieu_ra == "chu":
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
    _cap_nhat(viec_id, trang_thai="xong", luc=time.time(), bao_cao=vd.bao_cao(r),
              ket_qua=ket_qua)


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

    @router.post("/api/dich/chu")
    async def dich_chu(body: DichChuRequest,
                       authorization: str | None = Header(None)):
        """Dán chữ → dịch ngay (đồng bộ). Dán link video → việc nền."""
        require_admin(authorization)
        nd = (body.noi_dung or "").strip()
        if not nd:
            raise HTTPException(400, detail={"error": "Chưa có gì để dịch"})
        from services import translate_service as ts
        if not ts.is_configured():
            raise HTTPException(
                503, detail={"error": "Chưa cấu hình máy chủ dịch (translate_url)"})

        from services import video_dich as vd
        if vd.la_link_video(nd):
            with _khoa:
                _don_cu()
                viec_id = uuid.uuid4().hex[:12]
                _viec[viec_id] = {"trang_thai": "dang_chay", "luc": time.time(),
                                  "buoc": "đang lấy phụ đề và dịch…"}
            _chay_nen(viec_id, lambda: _xong_phu_de(
                viec_id, vd.dich_video(nd, body.target)))
            return {"viec_id": viec_id}

        try:
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
            v = _viec.get(viec_id)
            if v is None or v["trang_thai"] != "nhan_tep":
                raise HTTPException(404, detail={"error": "Không thấy việc upload này"})
            if chi_so != v["next"]:
                raise HTTPException(
                    409, detail={"error": f"Lệch thứ tự khúc: chờ {v['next']}, nhận {chi_so}"})
            if v["size"] + len(du_lieu) > TRAN_TEP:
                Path(v["duong"]).unlink(missing_ok=True)
                _viec.pop(viec_id, None)
                raise HTTPException(
                    413, detail={"error": f"Tệp vượt trần {TRAN_TEP // (1024*1024)}MB"})
            with open(v["duong"], "ab") as f:
                f.write(du_lieu)
            v["next"] += 1
            v["size"] += len(du_lieu)
            return {"viec_id": viec_id, "da_nhan": v["next"], "tong": v["tong"]}

    @router.post("/api/dich/tep")
    async def bat_dau_dich_tep(body: DichTepRequest,
                               authorization: str | None = Header(None)):
        """Đủ khúc rồi → chốt tệp, chọn đường dịch theo đuôi, chạy nền."""
        require_admin(authorization)
        from services import translate_service as ts
        if not ts.is_configured():
            raise HTTPException(
                503, detail={"error": "Chưa cấu hình máy chủ dịch (translate_url)"})
        with _khoa:
            v = _viec.get(body.viec_id)
            if v is None or v["trang_thai"] != "nhan_tep":
                raise HTTPException(404, detail={"error": "Không thấy việc upload này"})
            if v["next"] < v["tong"]:
                raise HTTPException(
                    400, detail={"error": f"Mới nhận {v['next']}/{v['tong']} khúc"})
            v["trang_thai"] = "dang_chay"
            v["buoc"] = "đang chuẩn bị…"
            ten, duong = v["ten"], v["duong"]
        viec_id, target = body.viec_id, body.target
        kieu_ra = "chu" if body.kieu_ra == "chu" else "phu-de"

        from services import video_asr as va
        from services import video_dich as vd

        thap = ten.lower()
        if va.la_tep_nghe_duoc(thap):
            def _video():
                _cap_nhat(viec_id, buoc="đang nghe tiếng trong tệp — "
                          "video dài chờ cỡ 2/3 thời lượng…")
                try:
                    r = vd.dich_tep_video(duong, ten, target)
                finally:
                    Path(duong).unlink(missing_ok=True)
                _xong_phu_de(viec_id, r, kieu_ra)

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
                    giong = "" if lang_kia == "vi" else "kokoro:"
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
            ra: dict[str, Any] = {"trang_thai": v["trang_thai"],
                                  "buoc": v.get("buoc", "")}
            if v["trang_thai"] == "xong":
                ra["ket_qua"] = v.get("ket_qua")
                ra["bao_cao"] = v.get("bao_cao", "")
            elif v["trang_thai"] == "loi":
                ra["loi"] = v.get("loi", "lỗi không rõ")
        return ra

    return router
