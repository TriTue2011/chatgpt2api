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
import unicodedata
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
# 150 chứ không phải 200: bản dịch tiếng Việt NỞ RA so với bản tiếng Anh, nên
# khung gộp sát trần sẽ vượt tốc độ đọc sau khi dịch. (Mức nở thật thì các
# nguồn nói 15–30% nhưng đều là trang tiếp thị, không có phép đo — nên đây là
# ước lượng thận trọng, đo lại rồi chỉnh.)
GOP_TOI_KY_TU = 150

# ── Chuẩn hiển thị phụ đề ───────────────────────────────────────────────────
# Gộp câu để DỊCH cho đúng nghĩa, rồi cắt lại thành khung để ĐỌC cho kịp. Hai
# việc khác nhau: khung 150 ký tự dịch rất tốt nhưng không ai đọc kịp trên màn
# hình. Con số dưới đây lấy từ hướng dẫn nhà phát hành, không tự đặt:
#
#   Netflix (có bản riêng cho tiếng Việt) và TED: 42 ký tự/dòng, tối đa 2 dòng.
#   Netflix: tốc độ đọc 20 ký tự/giây (người lớn), mỗi khung hiện tối đa 7 giây,
#   khoảng hở giữa hai khung tối thiểu 2 khung phim.
#   Subtitle Edit (mặc định của công cụ phụ đề dùng nhiều nhất): tối thiểu
#   1000 ms mỗi khung, hở tối thiểu 24 ms.
#
# BBC quy định RIÊNG cho video DỌC (9:16, dạng TikTok/Shorts): vùng phụ đề rộng
# 90% khung nên chỉ vừa ~25 ký tự/dòng, đổi lại được 3 dòng. Khi làm nhánh
# TikTok thì phải đổi hai hằng số đầu, áp 42 vào video dọc là tràn chữ.
KY_TU_MOI_DONG = 42
SO_DONG_TOI_DA = 2
TOC_DOC = 20.0          # ký tự mỗi giây
GIAY_TOI_THIEU = 1.0
GIAY_TOI_DA = 7.0
KHE_TOI_THIEU = 0.024   # khoảng hở giữa hai khung liền nhau


def _dai(s: str) -> int:
    """Đếm ký tự sau khi CHUẨN HOÁ NFC.

    Tiếng Việt có hai cách lưu hợp lệ trông y hệt nhau trên màn hình: dạng gộp
    (NFC) và dạng tách dấu rời (NFD). Cùng một dòng, NFC đếm 39 ký tự thì NFD
    đếm 54 — đếm trên dạng NFD sẽ cắt oan dòng đang hợp lệ, và lỗi này im lặng
    hoàn toàn.
    """
    return len(unicodedata.normalize("NFC", s))

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


def bo_trung(doan: list[Doan]) -> list[Doan]:
    """Bỏ chữ lặp của phụ đề dạng CUỘN.

    Phụ đề tự sinh YouTube cuộn như bảng chạy chữ: mỗi mảnh mới lặp lại phần
    đuôi của mảnh trước để người xem đọc kịp. Chuyển thẳng sang SRT thì được
    một tệp đầy dòng nhân đôi và mốc đè nhau — lỗi này mở trên yt-dlp từ 2021
    tới nay chưa ai sửa, nên phải tự lọc.

    Hai kiểu lặp đều xử lý: mảnh mới nằm TRỌN trong mảnh trước (bỏ hẳn), và
    mảnh mới CHỒNG một phần đuôi mảnh trước (cắt phần chồng).
    """
    ra: list[Doan] = []
    for d in doan:
        chu = d.chu.strip()
        if not chu:
            continue
        if ra:
            truoc = ra[-1].chu
            if chu in truoc:
                # Lặp trọn: giữ mốc kết thúc muộn hơn để khung không bị ngắt sớm.
                ra[-1] = Doan(ra[-1].bat_dau, max(ra[-1].ket_thuc, d.ket_thuc), truoc)
                continue
            # Đuôi mảnh trước trùng đầu mảnh này → cắt phần trùng. Dò từ chồng
            # NHIỀU nhất xuống, kẻo cắt thiếu và còn lại chữ lặp.
            toi_da = min(len(truoc), len(chu))
            for n in range(toi_da, 3, -1):
                if truoc.endswith(chu[:n]):
                    chu = chu[n:].lstrip()
                    break
            if not chu:
                ra[-1] = Doan(ra[-1].bat_dau, max(ra[-1].ket_thuc, d.ket_thuc), truoc)
                continue
        ra.append(Doan(d.bat_dau, d.ket_thuc, chu))
    return ra


def goi_dong(chu: str) -> list[str]:
    """Chữ → danh sách KHUNG, mỗi khung ≤ ``SO_DONG_TOI_DA`` dòng và mỗi dòng
    ≤ ``KY_TU_MOI_DONG`` ký tự.

    Xếp DÒNG trực tiếp chứ không cắt khung rồi mới ngắt dòng: cách sau chỉ ràng
    buộc được dòng trên, dòng dưới vẫn tràn (đo thật 13/08 — 43 dòng dài 43–45
    ký tự lọt qua). Xếp dòng thì mỗi dòng đúng giới hạn ngay lúc dựng.

    Không cân độ dài hai dòng: BBC nói rõ khi chữ, mốc thời gian và ngắt dòng
    xung đột thì chữ và mốc quan trọng hơn ngắt dòng.

    Từ đơn dài hơn cả một dòng (URL, tên hoá chất) thì để nguyên — cắt giữa từ
    tệ hơn tràn dòng.
    """
    khung: list[str] = []
    dong: list[str] = []
    hien = ""
    for t in chu.split():
        thu = f"{hien} {t}".strip()
        if hien and _dai(thu) > KY_TU_MOI_DONG:
            dong.append(hien)
            hien = t
            if len(dong) == SO_DONG_TOI_DA:
                khung.append("\n".join(dong))
                dong = []
        else:
            hien = thu
    if hien:
        dong.append(hien)
    if dong:
        khung.append("\n".join(dong))
    return khung


def cat_khung(doan: list[Doan]) -> list[Doan]:
    """Khung dài → nhiều khung đọc kịp, chia thời gian theo độ dài chữ.

    Vì sao cần: gộp câu để dịch cho đúng nghĩa sinh ra khung 150 ký tự — dịch
    tốt nhưng không ai đọc kịp trên màn hình.

    Thời gian chia theo TỈ LỆ số ký tự và KHÔNG BAO GIỜ vượt ra ngoài khoảng của
    khung gốc: nới ra là đè sang khung sau (đo thật 13/08). Khung gốc quá ngắn
    cho lượng chữ thì đành vượt tốc độ đọc — ``chuan_thoi_gian`` sẽ kéo dài
    trong phần khoảng hở còn trống, hết chỗ thì thôi.
    """
    ra: list[Doan] = []
    for d in doan:
        chu = " ".join(d.chu.split())
        if not chu:
            continue
        phan = goi_dong(chu)
        tong = sum(_dai(p) for p in phan) or 1
        dai_khung = max(d.ket_thuc - d.bat_dau, 0.001)
        moc = d.bat_dau
        for p in phan:
            giay = dai_khung * _dai(p) / tong
            ra.append(Doan(moc, moc + giay, p))
            moc += giay
    return ra


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


def chuan_thoi_gian(doan: list[Doan]) -> list[Doan]:
    """Ép mốc thời gian về đúng chuẩn hiển thị.

    Bốn luật, theo thứ tự: mỗi khung ít nhất ``GIAY_TOI_THIEU``; kéo dài thêm
    nếu chữ vượt ``TOC_DOC`` để người ta đọc kịp; không quá ``GIAY_TOI_DA``; và
    luôn chừa ``KHE_TOI_THIEU`` trước khung sau.

    Luật cuối là luật hay bị quên nhất: thiếu nó thì khung này kết thúc SAU khi
    khung sau đã bắt đầu, trình phát hiện đè hai dòng lên nhau.
    """
    ra: list[Doan] = []
    for i, d in enumerate(doan):
        # Đẩy mốc BẮT ĐẦU muộn lại nếu khung trước còn đang hiện. Đây là chỗ
        # bảo đảm không đè, và nó phải đứng trên mọi luật khác: trước đó tôi
        # dùng sàn "giữ ít nhất 0,2 giây" ở mốc kết thúc, sàn đó ghi đè luật
        # khoảng hở và sinh ra 8 khung chồng nhau (đo thật 13/08).
        bat_dau = d.bat_dau
        if ra and bat_dau < ra[-1].ket_thuc + KHE_TOI_THIEU:
            bat_dau = ra[-1].ket_thuc + KHE_TOI_THIEU

        can = _dai(d.chu.replace("\n", " ")) / TOC_DOC
        ket = max(d.ket_thuc, bat_dau + max(GIAY_TOI_THIEU, can))
        ket = min(ket, bat_dau + GIAY_TOI_DA)
        if i + 1 < len(doan):
            ket = min(ket, doan[i + 1].bat_dau - KHE_TOI_THIEU)
        # Thà một khung ngắn hơn mức tối thiểu còn hơn để phụ đề TRÔI dần khỏi
        # tiếng nói: BBC chốt rằng chữ và mốc thời gian quan trọng hơn cách
        # trình bày.
        ket = max(ket, bat_dau + 0.001)
        ra.append(Doan(bat_dau, ket, d.chu))
    return ra


def lam_srt(doan: list[Doan]) -> str:
    khoi = []
    for i, d in enumerate(chuan_thoi_gian(doan), 1):
        khoi.append(f"{i}\n{_moc(d.bat_dau)} --> {_moc(d.ket_thuc)}\n{d.chu}\n")
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

    return _dich_va_dong_goi(doan, ma_nguon or nguon, dich, dai)


def _dich_va_dong_goi(doan: list[Doan], nguon: str, dich: str,
                      dai_giay: float) -> dict[str, Any]:
    """Các đoạn chữ có mốc → dịch → khung đạt chuẩn → gói kết quả.

    Phần dùng chung của hai đường vào: phụ đề lấy từ YouTube và chữ máy tự
    nghe từ tệp. ``nguon == dich`` thì bỏ bước dịch — bản chép lời có mốc thời
    gian tự nó đã hữu ích (video tiếng Việt → phụ đề tiếng Việt).
    """
    nhom = gop_doan(bo_trung(doan))
    if nguon == dich:
        ban_dich = [d.chu for d in nhom]
    else:
        chu_goc = [d.chu for d in nhom]
        ban_dich = []
        try:
            for i in range(0, len(chu_goc), LO_MOI_LUOT):
                ban_dich.extend(ts.translate_batch(
                    chu_goc[i:i + LO_MOI_LUOT], dich, nguon or "auto"))
        except ts.LoiDich as exc:
            return {"ok": False, "error": f"máy chủ dịch lỗi: {exc}"}

    # Gộp để DỊCH, cắt lại để ĐỌC: khung 150 ký tự dịch đúng nghĩa nhưng không
    # ai đọc kịp trên màn hình.
    da_dich = cat_khung([Doan(d.bat_dau, d.ket_thuc, b)
                         for d, b in zip(nhom, ban_dich)])
    srt = lam_srt(da_dich)
    return {
        "ok": True,
        "srt": srt.encode("utf-8"),
        "ten": f"phu-de.{dich}.srt",
        "chu": "\n".join(d.chu for d in da_dich),
        "nguon": nguon,
        "dich": dich,
        "so_doan": len(da_dich),
        "phut": int(round(dai_giay / 60)),
    }


#: Tệp phải NGHE (không có phụ đề sẵn) dài nhất ngần này. Đo thật 13/08: nghe
#: + dịch mất ~0,6 lần thời lượng video trên máy 4 nhân — 30 phút video là
#: ~18 phút chờ, dài hơn nữa thành bất lịch sự. Đường link YouTube không dính
#: trần này (phụ đề lấy sẵn, gần như miễn phí).
TRAN_GIAY_NGHE = 30 * 60


def dich_tep_video(duong: str, ten: str = "", target: str = "") -> dict[str, Any]:
    """Tệp video/âm thanh trên đĩa → phụ đề .srt. KHÔNG raise, lỗi trong ``error``.

    Khác ``dich_video`` (đường link) đúng một chỗ: chữ đến từ bộ nghe trong máy
    (``video_asr``) thay vì phụ đề YouTube. Video nói tiếng Việt mà đích cũng
    tiếng Việt thì trả bản CHÉP LỜI — vẫn là phụ đề dùng được.
    """
    from services import video_asr as va

    try:
        cau, nguon, _giay_tieng = va.nghe_tep(duong, tran_giay=TRAN_GIAY_NGHE)
    except va.LoiNghe as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("nghe tệp %s lỗi: %s", ten, str(exc)[:200])
        return {"ok": False, "error": f"nghe tệp lỗi: {str(exc)[:200]}"}

    doan = [Doan(c.bat_dau, c.ket_thuc, c.chu) for c in cau]
    dich = str(target or "").lower() or ts.chon_dich_sang(nguon)
    if dich != nguon and not ts.is_configured():
        return {"ok": False, "error": "chưa cấu hình máy chủ dịch (translate_url)"}
    return _dich_va_dong_goi(doan, nguon, dich, doan[-1].ket_thuc)


def soat_srt(srt: str) -> list[str]:
    """Soát một tệp .srt theo chuẩn hiển thị → danh sách lỗi (rỗng = đạt).

    Vòng kiểm chứng chạy được cho khâu cắt khung: không có nó thì "trông có vẻ
    xong" là tín hiệu duy nhất, và mọi lỗi nằm chờ tới lúc người dùng mở tệp.
    """
    loi: list[str] = []
    khoi = [k for k in srt.strip().split("\n\n") if k.strip()]
    truoc_ket = -1.0
    for k in khoi:
        dong = k.split("\n")
        if len(dong) < 3:
            loi.append(f"khung {dong[0] if dong else '?'}: thiếu dòng")
            continue
        so, moc, *chu = dong
        m = re.match(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> "
                     r"(\d\d):(\d\d):(\d\d),(\d\d\d)$", moc)
        if not m:
            loi.append(f"khung {so}: mốc sai khuôn ({moc})")
            continue
        g = [int(x) for x in m.groups()]
        bd = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        kt = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        if len(chu) > SO_DONG_TOI_DA:
            loi.append(f"khung {so}: {len(chu)} dòng (tối đa {SO_DONG_TOI_DA})")
        for d in chu:
            if _dai(d) > KY_TU_MOI_DONG:
                loi.append(f"khung {so}: dòng {_dai(d)} ký tự "
                           f"(tối đa {KY_TU_MOI_DONG})")
        if kt <= bd:
            loi.append(f"khung {so}: mốc kết thúc không sau mốc bắt đầu")
        elif kt - bd > GIAY_TOI_DA + 0.01:
            loi.append(f"khung {so}: hiện {kt - bd:.1f}s (tối đa {GIAY_TOI_DA})")
        if bd < truoc_ket:
            loi.append(f"khung {so}: chồng lên khung trước")
        truoc_ket = kt
    return loi


def bao_cao(r: dict[str, Any]) -> str:
    """Kết quả → câu để bot gửi. Cùng nếp ``translate_service.bao_cao_dich``."""
    if not r.get("ok"):
        return f"🎬 Không dịch được: {r.get('error') or 'lỗi không rõ'}"
    return (f"🎬 Phụ đề {r['nguon']} → {r['dich']} • {r['phut']} phút • "
            f"{r['so_doan']} khung")
