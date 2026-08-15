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
from pathlib import Path
from typing import Any

from services import translate_service as ts

logger = logging.getLogger(__name__)

#: Video dài hơn ngần này thì từ chối: phụ đề vài nghìn đoạn dịch xong vừa lâu
#: vừa cho ra tệp không ai đọc trong chat. 2 giờ đã phủ hết phim/hội thảo.
TRAN_GIAY = 7200

#: Số khung phụ đề gửi mỗi lượt gọi máy dịch. Hai ràng buộc kéo hai hướng:
#: gửi cả video một cục thì vượt hạn 120 giây ("timed out" — đo thật 13/08);
#: gửi lô bé thì máy dịch GPU không bõ chuyến (định tuyến theo lô ở
#: translate_service — đo 14/08: lô 16 GPU chỉ hơn CPU 1,66×, lô to mới bung).
#: 100 khung ≈ 30 giây trên CPU (nửa hạn mức) và đủ to cho GPU.
LO_MOI_LUOT = 100

#: Gộp các đoạn phụ đề ngắn liền nhau lại trước khi dịch. Phụ đề tự sinh của
#: YouTube cắt ~1–2 giây một mảnh, giữa câu — dịch từng mảnh đó thì máy dịch mất
#: hết ngữ cảnh và cho ra chuỗi mảnh vụn. Gộp tới ranh giới CÂU rồi mới dịch.
# Trần gộp là mức CỨNG chống phụ đề không dấu câu chạy dài vô tận, KHÔNG phải
# cỡ mong muốn: luật gộp duy nhất là "dừng khi HẾT CÂU". Bản đầu đặt trần mềm
# 150 ký tự/12 giây cắt được ngang câu — mảnh lơ lửng ("trying to cut a bone.")
# rơi sang đơn vị dịch sau và bị máy dịch nuốt (đo thật 13/08 trên video dạy
# nấu ăn). Câu 350 ký tự vẫn nằm gọn trong sức T5 (~512 token), còn hiển thị
# đã có cat_khung lo, không phải việc của bước gộp.
GOP_TOI_GIAY = 25.0
GOP_TOI_KY_TU = 350

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
    """Gộp mảnh vụn thành CÂU TRỌN VẸN để máy dịch có ngữ cảnh.

    Luật duy nhất: dừng khi hết câu (gặp . ? ! …). Hai trần ``GOP_TOI_GIAY`` /
    ``GOP_TOI_KY_TU`` chỉ là chốt an toàn cho phụ đề KHÔNG có dấu câu — chạm
    trần nghĩa là buộc phải cắt ngang câu, và mảnh sau sẽ dịch kém. Mốc thời
    gian lấy từ mảnh đầu tới mảnh cuối của nhóm.
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
    """Giây → "HH:MM:SS,mmm" đúng khuôn SRT.

    Quy hết ra mili-giây TRƯỚC rồi mới tách giờ-phút-giây: làm tròn phần lẻ
    riêng thì 455.9996 ra ",1000" — bốn chữ số, không nhảy giây (đo thật
    13/08: 5/429 khung video Zootopia dính, soat_srt bắt được).
    """
    tong_ms = max(0, int(round(float(giay) * 1000)))
    giay_nguyen, ms = divmod(tong_ms, 1000)
    gio, con = divmod(giay_nguyen, 3600)
    phut, giay_le = divmod(con, 60)
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
        # trình bày. Đệm 2ms chứ không phải 1ms: SRT ghi tới mili-giây, đệm
        # 1ms có thể bị LÀM TRÒN về trùng mốc (soát bắt được ở khung 338,
        # đo thật 13/08).
        ket = max(ket, bat_dau + 0.002)
        ra.append(Doan(bat_dau, ket, d.chu))
    return ra


def lam_srt(doan: list[Doan]) -> str:
    khoi = []
    for i, d in enumerate(chuan_thoi_gian(doan), 1):
        khoi.append(f"{i}\n{_moc(d.bat_dau)} --> {_moc(d.ket_thuc)}\n{d.chu}\n")
    return "\n".join(khoi)


def srt_chu_tren(srt: str) -> str:
    """Bản phụ đề hiện Ở MÉP TRÊN màn hình — thẻ ``{\\an8}`` đầu mỗi khung.

    Cho video ĐÃ CÓ chữ in cứng ở đáy hình (video dạy tiếng hay gặp): phụ đề
    dịch đè lên chữ gốc thành hai lớp không đọc nổi (ảnh chủ máy gửi 13/08).
    VLC / MX Player / mpv đều hiểu thẻ này; trình phát không hiểu sẽ hiện
    nguyên chữ ``{\\an8}`` — nên đây là BẢN KÈM THÊM, không thay bản thường.
    """
    ra = []
    for k in srt.strip().split("\n\n"):
        dong = k.split("\n")
        if len(dong) >= 3:
            dong[2] = "{\\an8}" + dong[2]
        ra.append("\n".join(dong))
    return "\n\n".join(ra) + "\n"


# ── Từ khoá giảng dạy (video dạy ngoại ngữ) ─────────────────────────────────
# Video dạy tiếng Anh giảng khác biệt "cut" vs "chop" — dịch cả hai thành "cắt"
# là bài học biến mất (đo thật 13/08). Che từ bằng token lạ để model giữ nguyên
# thì cộng đồng đã thử và báo hỏng với NLLB/Marian (CTranslate2 #1798 "none of
# them worked"). Cách có tiền lệ chạy được: XỬ LÝ PHÍA ĐÍCH — dịch bình thường
# rồi đính từ gốc vào khung nào đang giảng từ đó, kiểu "…đang cắt [chopping]".
# Người xem thấy từ gốc ngay tại chỗ, không phụ thuộc model có nghe lời không.

_TU_THUONG = {"the", "a", "an", "to", "it", "this", "that", "you", "we", "i",
              "is", "are", "was", "be", "do", "so", "and", "or", "but", "word",
              "verb", "noun", "yes", "no", "okay", "right", "like", "just",
              "kind", "of", "not", "very", "them", "him", "her", "i'm", "it's",
              "that's", "don't", "you're", "what", "when", "how", "why"}
_TRICH_DAN = re.compile(r"[\"“”‘’']([A-Za-z][A-Za-z' -]{1,24})[\"“”‘’']")
_MAU_GIANG = (
    re.compile(r"\bthe (?:word|verb|noun|phrase|term) [\"']?([A-Za-z-]{3,})", re.I),
    re.compile(r"\b([A-Za-z-]{3,}) means\b", re.I),
    re.compile(r"\b([A-Za-z-]{3,}) (?:vs\.?|versus) ([A-Za-z-]{3,})", re.I),
)
#: Tiếng ồn phụ đề: nhãn âm thanh "[snorts]"/"[music]" và ký hiệu đổi người
#: nói ">>" — không lọc thì "[snorts]" thành ứng viên từ khoá (đo thật 13/08).
_ON_PHU_DE = re.compile(r"\[[^\]]*\]|>+")


def _goc_tu(w: str) -> str:
    """Quy dạng biến hình đơn giản về gốc: cutting/cuts/chopped → cut/chop.

    Cào bằng đuôi -ing/-ed/-s và phụ âm đôi — đủ cho việc ĐẾM các dạng của
    cùng một từ được giảng, không phải bộ phân tích hình thái.
    """
    w = w.lower()
    for duoi in ("ing", "ed", "es", "s"):
        if w.endswith(duoi) and len(w) - len(duoi) >= 3:
            w = w[: len(w) - len(duoi)]
            break
    if len(w) >= 4 and w[-1] == w[-2]:
        w = w[:-1]
    return w


def tu_khoa_giang_day(nhom: list[Doan]) -> set[str]:
    """Dò các từ đang ĐƯỢC GIẢNG trong video dạy ngoại ngữ → tập GỐC từ.

    Ba điều kiện, phải đủ CẢ BA (đo trên video dạy nấu ăn 33 phút thật):

    1. Có tín hiệu giảng: đứng sau "say/says/said" trong cùng vế câu ("we could
       say that I'm kind of CHOPPING"), trong ngoặc kép, hoặc khớp mẫu
       "the word X" / "X means" / "X vs Y".
    2. Xuất hiện ≥ 5 lần trong cả video — từ được dạy bị nhắc đi nhắc lại.
    3. Xuất hiện ở ≥ 2 DẠNG biến hình (cut×19 + cutting×10; chopping×3 +
       chop×2) — người dạy chia động từ quanh bài giảng. Đây là cái lọc tách
       từ được DẠY khỏi từ chỉ hay được DÙNG: "beautiful"×5 chỉ có một dạng.

    Bản đầu còn tín hiệu "khung 1–2 từ" — đo thật ra 21 từ khoá giả ("Oh.",
    "Trust me.", "Beautiful.") nên bỏ. Không có tiền lệ đo sẵn cho bộ tín hiệu
    này (đã tra); ngưỡng đặt chặt: thà bỏ sót còn hơn chú thích bậy.
    """
    diem: dict[str, int] = {}
    xuat_hien: dict[str, int] = {}
    dang: dict[str, set[str]] = {}

    def _cong(tu: str, d: int) -> None:
        goc = _goc_tu(tu)
        if goc and len(goc) >= 3 and goc not in _TU_THUONG:
            diem[goc] = diem.get(goc, 0) + d

    for d in nhom:
        chu = _ON_PHU_DE.sub(" ", d.chu)
        tu_trong = re.findall(r"[A-Za-z][A-Za-z'-]*", chu)
        for t in tu_trong:
            goc = _goc_tu(t)
            if goc not in _TU_THUONG:
                xuat_hien[goc] = xuat_hien.get(goc, 0) + 1
                dang.setdefault(goc, set()).add(t.lower())
        # Từ nội dung đầu tiên ngay sau "say" trong cùng vế câu.
        thap = [t.lower() for t in tu_trong]
        for i, t in enumerate(thap):
            if t in ("say", "says", "said"):
                for u in thap[i + 1:i + 7]:
                    if len(u) >= 3 and u not in _TU_THUONG:
                        _cong(u, 2)
                        break
        for m in _TRICH_DAN.finditer(chu):
            for t in m.group(1).split():
                _cong(t, 2)
        for mau in _MAU_GIANG:
            for m in mau.finditer(chu):
                for t in m.groups():
                    if t:
                        _cong(t, 2)
    return {g for g, v in diem.items()
            if v >= 2 and xuat_hien.get(g, 0) >= 5 and len(dang.get(g, ())) >= 2}


def dinh_tu_goc(nguon: str, ban_dich: str, khoa: set[str]) -> str:
    """Khung nguồn có từ đang giảng → đính dạng GỐC của từ vào cuối bản dịch.

    Đính đúng DẠNG xuất hiện ("[chopping]" chứ không phải "[chop]") — người
    học cần thấy đúng chữ người nói vừa dùng.
    """
    if not khoa:
        return ban_dich
    thay = []
    for t in re.findall(r"[A-Za-z][A-Za-z'-]*", nguon):
        if _goc_tu(t) in khoa and t.lower() not in (x.lower() for x in thay):
            thay.append(t.lower())
    return f"{ban_dich} [{', '.join(thay)}]" if thay else ban_dich


def dich_video(text: str, target: str = "", *,
               chep_loi: bool = False) -> dict[str, Any]:
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

    # Đích cuối chỉ chốt được SAU khi biết tiếng của phụ đề (dạng "cap:xx"
    # phụ thuộc nguồn); ở bước xếp thứ tự track chỉ cần một gợi ý — lấy vi.
    goi_y = str(target or "").lower()
    if not goi_y or goi_y.startswith("cap:"):
        goi_y = "vi"
    try:
        doan, nguon = lay_phu_de(url, goi_y)
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
    # chep_loi: người dùng chọn GIỮ nguyên tiếng gốc — đích = chính tiếng nguồn,
    # _dich_va_dong_goi thấy nguon == dich thì bỏ hẳn bước dịch.
    dich = ma_nguon if chep_loi else ts.giai_ma_target(ma_nguon, target)
    if ma_nguon == dich and not chep_loi:
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
        # Video dạy tiếng Anh: đính từ gốc đang được giảng vào khung tương ứng
        # ("…đang cắt [chopping]") — mẫu dò chỉ viết cho tiếng Anh nên chỉ chạy
        # khi nguồn là en. Video thường không có tín hiệu giảng dạy → tập rỗng,
        # không đổi gì.
        if nguon.startswith("en"):
            khoa = tu_khoa_giang_day(nhom)
            if khoa:
                ban_dich = [dinh_tu_goc(d.chu, b, khoa)
                            for d, b in zip(nhom, ban_dich)]

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
        # Cặp (câu gốc, câu dịch) để đóng bản SONG NGỮ. Ghép ở mức `nhom` chứ
        # không ở `da_dich`: da_dich đã bị cắt lại cho vừa màn hình nên một câu
        # gốc có thể thành hai ba khung, ghép ở đó là lệch cặp.
        "song_ngu": [(d.chu, b) for d, b in zip(nhom, ban_dich)],
        "nguon": nguon,
        "dich": dich,
        "so_doan": len(da_dich),
        "phut": int(round(dai_giay / 60)),
    }


#: Tệp phải NGHE (không có phụ đề sẵn) dài nhất ngần này. Đo thật 13/08: nghe
#: + dịch mất ~0,6 lần thời lượng video trên máy 4 nhân. 150 phút đủ một bộ
#: PHIM ~2 tiếng — chủ máy chốt mức này 13/08, chấp nhận chờ ~1,5 tiếng/phim;
#: tab web có báo tiến độ nên chờ lâu vẫn nhìn thấy máy đang làm. RAM đo được:
#: 2,5 giờ tiếng ≈ 0,9GB lúc đỉnh, máy còn 8GB — lọt. Đường link YouTube
#: không dính trần này (phụ đề lấy sẵn, gần như miễn phí).
TRAN_GIAY_NGHE = 150 * 60


#: Đuôi tệp phụ đề đọc được. .ass chưa nhận (định dạng styling phức tạp).
DUOI_PHU_DE = (".srt", ".vtt")

#: Mốc thời gian SRT ("00:01:02,345") lẫn VTT ("00:01:02.345"; giờ có thể vắng).
_MOC_PHU_DE = re.compile(
    r"(?:(\d+):)?(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(?:(\d+):)?(\d\d):(\d\d)[,.](\d{1,3})")
#: Thẻ trong lời phụ đề: <i>…</i> của SRT/VTT, {\an8}/{\pos(...)} của ASS-style.
_THE_PHU_DE = re.compile(r"<[^>\n]+>|\{\\[^}]*\}")


def _giay_moc(gio: str | None, phut: str, giay: str, ms: str) -> float:
    return (int(gio or 0) * 3600 + int(phut) * 60 + int(giay)
            + int(ms.ljust(3, "0")) / 1000.0)


def doc_phu_de(raw: str) -> list[Doan]:
    """Nội dung tệp .srt / .vtt → các đoạn có mốc. Khối hỏng thì bỏ qua khối
    đó chứ không bỏ cả tệp — phụ đề trôi nổi trên mạng bẩn đủ kiểu."""
    raw = raw.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    ra: list[Doan] = []
    for khoi in raw.split("\n\n"):
        dong = [d for d in khoi.split("\n") if d.strip()]
        vi_tri = next((i for i, d in enumerate(dong) if _MOC_PHU_DE.search(d)), None)
        if vi_tri is None:
            continue
        m = _MOC_PHU_DE.search(dong[vi_tri])
        chu = " ".join(d.strip() for d in dong[vi_tri + 1:])
        chu = _THE_PHU_DE.sub("", chu).strip()
        if not chu:
            continue
        bat = _giay_moc(m.group(1), m.group(2), m.group(3), m.group(4))
        ket = _giay_moc(m.group(5), m.group(6), m.group(7), m.group(8))
        if ket > bat:
            ra.append(Doan(bat, ket, chu))
    ra.sort(key=lambda d: d.bat_dau)
    return ra


def la_tep_phu_de(ten: str) -> bool:
    return str(ten or "").lower().endswith(DUOI_PHU_DE)


def dich_tep_phu_de(duong: str, ten: str = "", target: str = "", *,
                    chep_loi: bool = False) -> dict[str, Any]:
    """Tệp phụ đề có sẵn (.srt/.vtt) → phụ đề đã dịch. KHÔNG raise.

    Đường NHANH + CHUẨN nhất cho phim: chữ gốc do người làm, không dính lỗi
    nghe nhạc ồn, và chỉ tốn bước dịch (~vài chục giây) thay vì nghe cả
    tiếng. Đi chung dây chuyền với phụ đề YouTube: gộp trọn câu rồi mới
    dịch, cắt lại khung đạt chuẩn đọc.
    """
    if not ts.is_configured():
        return {"ok": False, "error": "chưa cấu hình máy chủ dịch (translate_url)"}
    try:
        raw = Path(duong).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": f"không đọc được tệp: {exc}"}
    doan = doc_phu_de(raw)
    if not doan:
        return {"ok": False,
                "error": f"không đọc được khung phụ đề nào trong "
                         f"{ten or 'tệp'} (nhận .srt và .vtt)"}
    mau = " ".join(d.chu for d in doan[:60])
    try:
        nguon, _ = ts.detect(mau[:5000])
    except ts.LoiDich as exc:
        return {"ok": False, "error": str(exc)}
    dich = (nguon or "auto") if chep_loi else ts.giai_ma_target(nguon, target)
    if nguon and nguon == dich and not chep_loi:
        return {"ok": False, "error": f"phụ đề đã là tiếng `{dich}` rồi ạ"}
    return _dich_va_dong_goi(doan, nguon or "auto", dich, doan[-1].ket_thuc)


def _ung_vien_nghe(target: str, session_id: str = "") -> tuple[str, ...]:
    """Nhóm model NGHE đem dò cho một lượt dịch video.

    Thứ tự quyết định (chốt 14/08 — "mỗi loại phải có cài đặt riêng"):

    1. Người dùng chọn CẶP ("cap:zh") → so đúng vi với zh. Họ đã nói rõ video
       thuộc cặp nào thì không có lý gì đi dò cả 5 tiếng.
    2. Không nêu cặp → nhóm tiếng của TÍNH NĂNG phụ đề, có đè theo thread
       (``voice.dung_cho.phu_de.stt_tieng`` / ``voice_sessions.json``).
    3. Cuối cùng mới về ``("vi", "en")``.
    """
    t = str(target or "").lower()
    if t.startswith("cap:") and t[4:] in ("zh", "ja", "ko", "en"):
        return ("vi", t[4:])
    try:
        from services.voice import config as vcfg
        # Mặc định của RIÊNG phụ đề: cặp vi/en — phép so đã đo chắc và là
        # hành vi đang chạy. Không mượn ô của tin nhắn thoại.
        nhom = vcfg.stt_nhom_tieng("phu_de", session_id, ["vi", "en"])
        if nhom:
            return tuple(nhom)
    except Exception as exc:
        logger.info("lấy nhóm tiếng nghe lỗi: %s", str(exc)[:120])
    return ("vi", "en")


def dich_tep_video(duong: str, ten: str = "", target: str = "", *,
                   chep_loi: bool = False, session_id: str = "",
                   nguon_biet: str = "") -> dict[str, Any]:
    """Tệp video/âm thanh trên đĩa → phụ đề .srt. KHÔNG raise, lỗi trong ``error``.

    Khác ``dich_video`` (đường link) đúng một chỗ: chữ đến từ bộ nghe trong máy
    (``video_asr``) thay vì phụ đề YouTube. Video nói tiếng Việt mà đích cũng
    tiếng Việt thì trả bản CHÉP LỜI — vẫn là phụ đề dùng được.

    ``nguon_biet``: người dùng đã NÓI RÕ tệp nói tiếng gì (menu ba bước của
    ``dich_cho``). Có nó thì khoá cứng một tiếng, khỏi dò: dò là nghe thử cả
    cửa sổ mẫu bằng từng model rồi so độ tự tin, nên mỗi tiếng ứng viên là một
    lượt nghe — biết trước vừa nhanh hơn vừa không có cửa đoán sai.
    """
    from services import video_asr as va

    try:
        cau, nguon, _giay_tieng = va.nghe_tep(
            duong, tran_giay=TRAN_GIAY_NGHE,
            ung_vien=((nguon_biet,) if nguon_biet
                      else _ung_vien_nghe(target, session_id)))
    except va.LoiNghe as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("nghe tệp %s lỗi: %s", ten, str(exc)[:200])
        return {"ok": False, "error": f"nghe tệp lỗi: {str(exc)[:200]}"}

    doan = [Doan(c.bat_dau, c.ket_thuc, c.chu) for c in cau]
    dich = nguon if chep_loi else ts.giai_ma_target(nguon, target)
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
