"""Dịch video từ LINK — YouTube (và TikTok khi có đường âm thanh).

Vì sao đi bằng PHỤ ĐỀ SẴN CÓ thay vì tải video về nghe lại: YouTube đã có phụ
đề (người làm hoặc máy tự sinh) kèm dấu thời gian, lấy qua
``youtube-transcript-api`` chỉ mất vài trăm KB và một giây — trong khi tải video
rồi chạy nhận dạng tiếng nói tốn hàng trăm MB băng thông và vài phút CPU cho
cùng một kết quả kém hơn. Đo trên máy chủ 13/08/2026: video 18 phút trả về 286
đoạn có mốc thời gian trong ~1 giây.

Đường ra: một tệp .srt (nạp được vào mọi trình phát) kèm bản chữ để đọc luôn
trong chat. KHÔNG gọi LLM — dịch bằng máy dịch trong stack (vn-translate).

Chưa làm ở bản này: TikTok và video YouTube KHÔNG có phụ đề nào. Cả hai đều cần
tải âm thanh về rồi tự nghe (yt-dlp + nhận dạng tiếng nói có dấu thời gian),
xem ``LOI_CHUA_CO_TIENG``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from services import translate_service as ts

logger = logging.getLogger(__name__)

#: Video dài hơn ngần này thì từ chối: phụ đề vài nghìn đoạn dịch xong vừa lâu
#: vừa cho ra tệp không ai đọc trong chat. 2 giờ đã phủ hết phim/hội thảo.
TRAN_GIAY = 7200

#: Số khung phụ đề gửi mỗi lượt gọi máy dịch. Gửi cả video một cục thì một
#: video 18 phút (hơn trăm khung) vượt hạn 120 giây và trả về "timed out" —
#: đo thật 13/08. Chia lô để mỗi lượt gọi chỉ vài giây, còn tổng thời gian thì
#: dài bao nhiêu cũng được.
LO_MOI_LUOT = 20

#: Gộp các đoạn phụ đề ngắn liền nhau lại trước khi dịch. Phụ đề tự sinh của
#: YouTube cắt ~1–2 giây một mảnh, giữa câu — dịch từng mảnh đó thì máy dịch mất
#: hết ngữ cảnh và cho ra chuỗi mảnh vụn. Gộp tới ranh giới CÂU rồi mới dịch.
GOP_TOI_GIAY = 12.0
GOP_TOI_KY_TU = 200

_YT = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^\s&]*&)*v=|embed/|v/|shorts/|live/)"
    r"|youtu\.be/)([A-Za-z0-9_-]{11})")
_TIKTOK = re.compile(r"(?:tiktok\.com/[^\s]+|vm\.tiktok\.com/[A-Za-z0-9]+)")
_LINK = re.compile(r"https?://[^\s<>\"')]+")

LOI_CHUA_CO_TIENG = (
    "video này không có phụ đề nào để lấy. Dịch được nó cần tải tiếng về rồi "
    "tự nghe — phần đó chưa làm"
)


@dataclass
class Doan:
    """Một khung phụ đề: mốc bắt đầu, mốc kết thúc (giây), và chữ."""

    bat_dau: float
    ket_thuc: float
    chu: str


def la_link_video(text: str) -> str:
    """Tin nhắn này có link video không → trả LINK, không có thì "".

    Nhận cả link trần lẫn link lẫn trong câu ("dịch giúp em video này <link>").
    """
    s = str(text or "")
    if _YT.search(s):
        m = _LINK.search(s)
        return m.group(0) if m and _YT.search(m.group(0)) else _YT.search(s).group(0)
    m = _TIKTOK.search(s)
    return m.group(0) if m else ""


def _ma_video(url: str) -> str:
    m = _YT.search(url or "")
    return m.group(1) if m else ""


def _thu_tu(ban: list[tuple[str, bool]], dich_sang: str = "vi") -> list[str]:
    """Thứ tự thử các bản phụ đề → danh sách mã ngôn ngữ.

    ``ban`` = [(mã ngôn ngữ, có phải bản máy TỰ SINH)].

    Bản YouTube tự sinh luôn ở đúng tiếng người ta NÓI trong video, nên nó là
    cách tin cậy để biết video nói tiếng gì. Trong tiếng đó thì bản do người làm
    chính xác hơn bản tự sinh nên xếp trước. Sau đó mới tới tiếng Anh, rồi tới
    các tiếng khác.

    Vì sao cần thứ tự này: video có phụ đề cộng đồng thường liệt kê hàng chục
    thứ tiếng theo bảng chữ cái, nên lấy "bản đầu danh sách" là lấy bản dịch
    của người khác — đo thật 13/08: một video giảng bài tiếng Anh bị lấy bản
    tiếng Ả Rập rồi dịch tiếp sang tiếng Việt, tức dịch hai lần qua ba thứ tiếng.

    Bản đã là ``dich_sang`` xếp CUỐI, không loại hẳn: nếu video chỉ có đúng bản
    đó thì vẫn cần lấy ra để báo "đã là tiếng Việt rồi".
    """
    noi = next((ma.split("-")[0] for ma, tu_sinh in ban if tu_sinh), "")

    def diem(x: tuple[str, bool]) -> int:
        ma, tu_sinh = x
        goc = ma.split("-")[0]
        if goc == dich_sang:
            return 9
        if noi and goc == noi:
            return 1 if tu_sinh else 0
        return 2 if goc == "en" else 3

    return [ma for ma, _ in sorted(ban, key=diem)]


def lay_phu_de(url: str, dich_sang: str = "vi") -> tuple[list[Doan], str]:
    """Lấy phụ đề gốc của video → (các đoạn, mã ngôn ngữ). Raise nếu không có."""
    from youtube_transcript_api import YouTubeTranscriptApi

    vid = _ma_video(url)
    if not vid:
        raise ValueError(LOI_CHUA_CO_TIENG)
    api = YouTubeTranscriptApi()
    ban = [(t.language_code, bool(getattr(t, "is_generated", False)))
           for t in api.list(vid)]
    if not ban:
        raise ValueError(LOI_CHUA_CO_TIENG)
    co = [ma for ma, _ in ban]
    loi_cuoi: Exception | None = None
    for ma in _thu_tu(ban, dich_sang):
        try:
            doan = [Doan(float(x.start), float(x.start) + float(x.duration or 0),
                         str(x.text or "").replace("\n", " ").strip())
                    for x in api.fetch(vid, languages=[ma])]
            return [d for d in doan if d.chu], ma
        except Exception as exc:
            loi_cuoi = exc
    raise ValueError(f"không lấy được phụ đề nào (thử {co[:5]}): {loi_cuoi}")


def gop_doan(doan: list[Doan]) -> list[Doan]:
    """Gộp mảnh vụn thành câu trọn vẹn để máy dịch có ngữ cảnh.

    Dừng gộp khi: đã hết câu (gặp . ? !), hoặc quá ``GOP_TOI_GIAY``, hoặc quá
    ``GOP_TOI_KY_TU``. Mốc thời gian lấy từ mảnh đầu tới mảnh cuối của nhóm.
    """
    ra: list[Doan] = []
    for d in doan:
        if ra and (len(ra[-1].chu) + len(d.chu) + 1 <= GOP_TOI_KY_TU
                   and d.ket_thuc - ra[-1].bat_dau <= GOP_TOI_GIAY
                   and not ra[-1].chu.rstrip().endswith((".", "?", "!", "…"))):
            ra[-1] = Doan(ra[-1].bat_dau, d.ket_thuc, f"{ra[-1].chu} {d.chu}")
        else:
            ra.append(Doan(d.bat_dau, d.ket_thuc, d.chu))
    return ra


def _moc(giay: float) -> str:
    """Giây → "HH:MM:SS,mmm" đúng khuôn SRT."""
    giay = max(0.0, float(giay))
    gio, con = divmod(int(giay), 3600)
    phut, giay_le = divmod(con, 60)
    ms = int(round((giay - int(giay)) * 1000))
    return f"{gio:02d}:{phut:02d}:{giay_le:02d},{ms:03d}"


def lam_srt(doan: list[Doan]) -> str:
    khoi = []
    for i, d in enumerate(doan, 1):
        ket = max(d.ket_thuc, d.bat_dau + 0.5)
        khoi.append(f"{i}\n{_moc(d.bat_dau)} --> {_moc(ket)}\n{d.chu}\n")
    return "\n".join(khoi)


def dich_video(text: str, target: str = "") -> dict[str, Any]:
    """Link video → bản dịch. KHÔNG raise: lỗi nằm trong khoá ``error``.

    Trả::

        {"ok": True, "srt": b"...", "ten": "video.vi.srt", "chu": "…",
         "nguon": "en", "dich": "vi", "so_doan": 42, "phut": 18}
        {"ok": False, "error": "…"}
    """
    url = la_link_video(text)
    if not url:
        return {"ok": False, "error": "không thấy link video trong tin nhắn"}
    if not ts.is_configured():
        return {"ok": False, "error": "chưa cấu hình máy chủ dịch (translate_url)"}
    if not _ma_video(url):
        return {"ok": False, "error": LOI_CHUA_CO_TIENG}

    dich = str(target or "").lower() or "vi"
    try:
        doan, nguon = lay_phu_de(url, dich)
    except Exception as exc:
        logger.warning("lấy phụ đề %s lỗi: %s", url, str(exc)[:200])
        return {"ok": False, "error": str(exc)[:300]}
    if not doan:
        return {"ok": False, "error": LOI_CHUA_CO_TIENG}

    dai = doan[-1].ket_thuc
    if dai > TRAN_GIAY:
        return {"ok": False,
                "error": f"video dài {dai / 60:.0f} phút, quá mức "
                         f"{TRAN_GIAY // 60} phút mà em dịch được"}

    ma_nguon = ts._chuan_ma(nguon.split("-")[0], ts.lang_codes()) or nguon.split("-")[0]
    if ma_nguon == dich:
        return {"ok": False, "error": f"phụ đề đã là tiếng `{dich}` rồi ạ"}

    nhom = gop_doan(doan)
    chu_goc = [d.chu for d in nhom]
    ban_dich: list[str] = []
    try:
        for i in range(0, len(chu_goc), LO_MOI_LUOT):
            ban_dich.extend(ts.translate_batch(
                chu_goc[i:i + LO_MOI_LUOT], dich, ma_nguon or "auto"))
    except ts.LoiDich as exc:
        return {"ok": False, "error": f"máy chủ dịch lỗi: {exc}"}

    da_dich = [Doan(d.bat_dau, d.ket_thuc, b) for d, b in zip(nhom, ban_dich)]
    srt = lam_srt(da_dich)
    return {
        "ok": True,
        "srt": srt.encode("utf-8"),
        "ten": f"phu-de.{dich}.srt",
        "chu": "\n".join(d.chu for d in da_dich),
        "nguon": ma_nguon or nguon,
        "dich": dich,
        "so_doan": len(da_dich),
        "phut": int(round(dai / 60)),
    }


def bao_cao(r: dict[str, Any]) -> str:
    """Kết quả → câu để bot gửi. Cùng nếp ``translate_service.bao_cao_dich``."""
    if not r.get("ok"):
        return f"🎬 Không dịch được: {r.get('error') or 'lỗi không rõ'}"
    return (f"🎬 Phụ đề {r['nguon']} → {r['dich']} • {r['phut']} phút • "
            f"{r['so_doan']} khung")
