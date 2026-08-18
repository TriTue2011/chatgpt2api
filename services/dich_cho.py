"""Bản CHỜ CHỌN cho việc dịch — bot hỏi trước khi làm, không tự đoán.

Chủ máy chốt 14/08: "bot khi dùng đến phải có lựa chọn rõ ràng, ví dụ phụ đề
phải cho chọn ngôn ngữ chuyển là gì và lấy file phụ đề hay chỉ là file văn bản".
Trước đây bot tự quyết cả hai (luôn .srt, luôn dịch sang tiếng Việt/Anh theo
luật `chon_dich_sang`) — nghe một video 2 giờ xong mới biết không phải thứ mình
cần là mất cả tiếng.

Và chốt tiếp: "/dich mà không có đích ngôn ngữ thì phải đưa ra các lựa chọn" —
trước đây `/dich xin chào` tự nhảy sang tiếng Anh theo luật `chon_dich_sang`.

Cùng nếp ``pdf_intent`` / ``photo_intent``: giữ bản chờ theo khoá phiên, gửi menu
đánh số, người dùng nhắn số thì chạy. Ba loại nguồn dùng chung sổ chờ này:
TỆP (đường dẫn tạm), LINK (url), CHỮ (chu) — menu khác nhau theo loại.

**Ba bước cho tệp và link** (chốt 15/08): làm gì → tệp nói tiếng gì → dịch sang
tiếng nào. Bản trước gộp cả ba vào một menu năm dòng và KHÔNG hỏi tiếng nguồn —
để máy tự dò. Hỏi thẳng hơn hẳn ở hai chỗ đo được:

- **Đúng hơn.** Máy dò bằng cách nghe thử bằng từng model rồi so độ tự tin; đo
  15/08 thì model SenseVoice không trả độ tự tin nên nhánh dò phải chấm bằng
  tiếng model tự khai. Người dùng biết chắc tệp nói tiếng gì thì khỏi đoán.
- **Nhanh hơn.** Một tiếng = khoá cứng, không tốn lượt nghe thử nào; hai tiếng
  trở lên là mỗi tiếng thêm một lượt nghe cả cửa sổ mẫu.

Menu CHỮ vẫn một bước (chỉ hỏi tiếng đích): chữ thì máy dò tiếng bằng bộ dò văn
bản, rẻ và chắc, không phải nghe gì cả.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

#: Bản chờ sống ngần này giây rồi tự dọn (kèm xoá tệp tạm). Dài hơn menu PDF
#: (10 phút) vì người dùng gửi video xong hay đi làm việc khác.
_TTL = 30 * 60
_pending: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

#: Tiếng đích chọn được. Khoá = tên gõ trong menu ("4 nhật").
TIENG = {
    "vi": ("việt", "viet", "vn", "vietnamese"),
    "en": ("anh", "en", "english"),
    "ja": ("nhật", "nhat", "ja", "japanese"),
    "zh": ("trung", "zh", "chinese", "hoa"),
    "ko": ("hàn", "han", "ko", "korean"),
}
TEN_TIENG = {"vi": "Việt", "en": "Anh", "ja": "Nhật", "zh": "Trung", "ko": "Hàn"}


def _gc() -> None:
    """Dọn bản chờ hết hạn. Gọi khi ĐÃ giữ ``_lock``."""
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v["ts"] > _TTL]:
        v = _pending.pop(k, None)
        if v and v.get("path"):
            try:
                os.unlink(v["path"])
            except OSError:
                pass


def set_pending(key: str, *, path: str = "", url: str = "", chu: str = "",
                ten: str = "", so_byte: int = 0) -> None:
    """Ghi bản chờ. Đúng MỘT trong ba: ``path`` (tệp tạm) · ``url`` (link) ·
    ``chu`` (đoạn chữ cần dịch)."""
    with _lock:
        cu = _pending.pop(key, None)
        if cu and cu.get("path"):
            try:
                os.unlink(cu["path"])
            except OSError:
                pass
        _pending[key] = {"path": path, "url": url, "chu": chu,
                         "ten": ten or ("đoạn chữ" if chu else "video"),
                         "so_byte": int(so_byte or 0), "ts": time.time()}
        _gc()


def has_pending(key: str) -> bool:
    with _lock:
        _gc()
        return key in _pending


def get_pending(key: str) -> dict[str, Any] | None:
    with _lock:
        # Có đường gọi thẳng `get_pending` (đặc biệt /tts) trước `has_pending`.
        # Nếu chỉ dọn ở has_pending thì một menu đã hết hạn vẫn bị ăn như câu
        # trả lời hợp lệ. Mọi cửa đọc/tiêu thụ phải cùng thực thi luật TTL.
        _gc()
        p = _pending.get(key)
        return dict(p) if p else None


def pop_pending(key: str) -> dict[str, Any] | None:
    """Lấy bản chờ ra khỏi sổ — người gọi có trách nhiệm xoá tệp tạm."""
    with _lock:
        _gc()
        return _pending.pop(key, None)


def don_tep(pend: dict[str, Any] | None) -> None:
    """Xoá tệp tạm của một bản chờ đã lấy ra."""
    if pend and pend.get("path"):
        try:
            os.unlink(pend["path"])
        except OSError:
            pass


def _la_phu_de(ten: str) -> bool:
    return str(ten or "").lower().endswith((".srt", ".vtt"))


def la_chu(pend: dict[str, Any]) -> bool:
    """Bản chờ này là ĐOẠN CHỮ (không phải tệp/link) — menu chỉ hỏi tiếng đích."""
    return bool(pend.get("chu"))


#: Ba bước của tệp/link. Bản chờ giữ ``buoc`` + những gì đã chọn.
BUOC_VIEC, BUOC_NGUON, BUOC_DICH = "viec", "nguon", "dich"
#: Hai bước RIÊNG của ô phụ đề, hỏi sau khi đã biết tiếng đích.
BUOC_VI_TRI, BUOC_DANG_RA = "vi-tri", "dang-ra"
#: Bước RIÊNG của ô "phân tích một đoạn cụ thể" — đoạn nào thì chỉ người dùng
#: biết. Đây là bước duy nhất nhận CHỮ TỰ DO chứ không phải số menu.
BUOC_DOAN = "doan"

#: Việc làm được với tệp: mã → (số menu, nhãn, có phải dịch không).
#: Cờ thứ ba chỉ để ĐỌC cho hiểu — luồng hỏi tiếng nào là do VIEC_QUA_LLM,
#: VIEC_KHONG_DICH và VIEC_GIU_GOC bên dưới quyết định. Bản trước lấy cờ
#: này làm điều kiện rẽ nhánh, và một việc KHÔNG nằm trong bảng thì rơi
#: vào giá trị mặc định — /stt bị hỏi thêm một câu không ai xin.
# Chủ máy chốt 18/08: MỘT menu duy nhất, đủ mục, dùng CHUNG cho link và cho tệp
# gửi lên. Trước đó có hai menu rời nhau và không mục nào giống mục nào — bot tự
# bịa danh sách riêng cho link (tóm tắt / ý chính / phân tích / ghi chú), còn
# bảng này chỉ có phần dịch, lại giấu ô lồng tiếng khỏi link.
#
# Kiến trúc do chủ máy chốt: "chuyển thành phụ đề rồi mới qua llm để làm 12345".
# Nghĩa là MỌI video — link hay tệp — đều đi qua bước tạo phụ đề trước; phụ đề
# đó là đầu vào cho cả năm ô LLM lẫn hai ô video. Nhờ vậy tệp gửi lên cũng làm
# được tóm tắt/ý chính, việc mà trước đây chỉ link mới có (nhờ transcript sẵn).
#
# Hai ô "chép lời" cũ biến mất KHÔNG phải vì mất chức năng: bước tạo phụ đề
# chính là chép lời, và ô 6 cho chọn giữ nguyên tiếng gốc.
VIEC = {
    "tom-tat": ("1", "Tóm tắt nội dung video", False),
    "y-chinh": ("2", "Lấy các ý chính", False),
    "dich-chu": ("3", "Dịch ra bản chữ (chỉ lời thoại)", True),
    "phan-tich": ("4", "Phân tích một đoạn cụ thể", False),
    "ghi-chu": ("5", "Ghi chú học tập / tài liệu", False),
    "phu-de": ("6", "Phụ đề (chọn vị trí chữ, chọn .srt hay ghép vào video)", True),
    "long-tieng": ("7", "Lồng tiếng video (giữ nhạc và hiệu ứng)", True),
}

#: Bốn ô đầu chạy trên PHỤ ĐỀ đã có, do LLM làm — không hỏi tiếng đích.
VIEC_QUA_LLM = ("tom-tat", "y-chinh", "phan-tich", "ghi-chu")

#: Việc KHÔNG dịch, không nằm trong menu ``VIEC``: /stt vào thẳng đây (tên lệnh
#: đã nói rõ ý định) nên bảng menu không có ô nào cho nó. Mã việc → kiểu kết quả.
#: Phải tra riêng: bản trước dò bằng ``VIEC.get(viec, (..., True))[2]``, mà
#: "chu-goc" không còn trong VIEC nên rơi vào mặc định "có dịch" — /stt bị hỏi
#: thêm "dịch sang tiếng nào" rồi trả .srt đã dịch, đúng thứ người dùng không xin.
VIEC_KHONG_DICH = {"chu-goc": "chu"}

#: Việc CHO PHÉP giữ nguyên tiếng gốc (chép lời, không dịch) — lựa chọn thêm ở
#: bước hỏi tiếng đích. Menu cũ có hẳn hai ô riêng ("Phụ đề .srt GIỮ nguyên
#: tiếng gốc" và "Bản chữ giữ nguyên tiếng"); menu bảy ô gộp chúng vào đây, nếu
#: không thì video tiếng Anh muốn phụ đề tiếng Anh là không bấm được nữa.
#: Lồng tiếng không có mặt: thay tiếng bằng chính tiếng đang nói là việc vô nghĩa.
VIEC_GIU_GOC = ("phu-de", "dich-chu")

#: Vị trí chữ khi ghép vào hình — cùng tên với services.video_tai.VI_TRI.
VI_TRI_PHU_DE = {"1": "duoi", "2": "tren"}

#: Dạng trả cho ô phụ đề.
DANG_RA_PHU_DE = {"1": "srt", "2": "ghep"}

_DUOI_VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp")


def _la_tep_video(pend: dict[str, Any]) -> bool:
    # ``path`` có thể là chuỗi rỗng trong adapter/test trước lúc tệp được chốt;
    # điểm phân biệt link là trường ``url``, còn loại tệp lấy theo tên đã nhận.
    return not bool(pend.get("url")) and str(
        pend.get("ten") or "").lower().endswith(_DUOI_VIDEO)


def _viec_hop_le(pend: dict[str, Any]) -> dict[str, tuple[str, str, bool]]:
    """Các việc thật sự làm được với đúng loại đầu vào đang chờ.

    LINK nay cũng lồng tiếng được: ``services.video_tai.tai_video`` tải cả hình
    về nên link và tệp video đi chung một đường. Trước đây ô lồng tiếng bị giấu
    khỏi link vì "link hiện chưa tải cả hình về gateway" — lý do đó hết rồi.

    Vẫn giấu với TỆP PHỤ ĐỀ và TỆP ÂM THANH: chúng không có luồng hình để thay.
    """
    return {ma: gia_tri for ma, gia_tri in VIEC.items()
            if ma != "long-tieng" or _co_luong_hinh(pend)}


def _co_luong_hinh(pend: dict[str, Any]) -> bool:
    """Đầu vào này có hình để ghép chữ / thay tiếng không."""
    if str(pend.get("url") or "").strip():
        return True                      # link → tải hình về được
    return _la_tep_video(pend)


def _danh_sach_tieng(tru: str = "") -> list[str]:
    """Mã tiếng theo thứ tự menu, bỏ tiếng ``tru`` (không ai dịch sang chính nó)."""
    return [m for m in ("vi", "en", "ja", "zh", "ko") if m != tru]


# ── /stt và /tts ────────────────────────────────────────────────────────────
#
# Dùng CHUNG sổ chờ này với /dich, cố ý. Một khoá phiên chỉ được có MỘT menu
# đang mở: hai sổ chờ riêng thì người dùng nhắn "2" mà cả hai bên cùng nhận là
# hỏng, và bên nào thắng phụ thuộc thứ tự if trong bot — thứ không ai đọc ra
# được từ giao diện.
#
# /stt KHÔNG dựng luồng riêng: nó chỉ là lối tắt vào ô "chép lời ra bản chữ
# thuần" của menu tệp, rồi hỏi tiếng như thường. Làm hai đường thì mỗi lần đổi
# phải sửa hai chỗ, và kiểu gì cũng có ngày lệch nhau.
BUOC_CHO_TEP = "cho-tep"          # /stt: đợi gửi tệp âm thanh
BUOC_CHO_CHU = "cho-chu"          # /tts: đợi đoạn chữ cần đọc
BUOC_TIENG_DOC = "tieng-doc"      # /tts: đọc bằng tiếng nào
BUOC_DUYET_DICH = "duyet-dich"    # /tts: dịch xong, đọc bản nào


def mo_stt(key: str) -> str:
    """Mở lệnh /stt — trả lời câu cần gửi cho người dùng."""
    set_pending(key, ten="tệp âm thanh")
    _ghi_buoc(key, viec_chinh="stt", buoc=BUOC_CHO_TEP)
    return ("🎤 Gửi em tệp âm thanh hoặc video cần chuyển thành chữ ạ. "
            "Nhắn «thôi» để bỏ.")


def mo_tts(key: str, chu: str = "") -> str:
    """Mở lệnh /tts. Có sẵn đoạn chữ thì hỏi tiếng luôn, không thì xin nội dung."""
    set_pending(key, chu=chu, ten="đoạn chữ")
    if chu.strip():
        _ghi_buoc(key, viec_chinh="tts", buoc=BUOC_TIENG_DOC)
        return menu_buoc(key)
    _ghi_buoc(key, viec_chinh="tts", buoc=BUOC_CHO_CHU)
    return "🔊 Gửi em đoạn chữ cần đọc thành tiếng ạ. Nhắn «thôi» để bỏ."


def dang_cho_tep(key: str) -> bool:
    """Phiên này đang đợi tệp âm thanh (/stt) hay không."""
    p = get_pending(key) or {}
    return p.get("buoc") == BUOC_CHO_TEP


def dang_cho_chu(key: str) -> bool:
    p = get_pending(key) or {}
    return p.get("buoc") == BUOC_CHO_CHU


def nap_tep(key: str, path: str, ten: str = "", so_byte: int = 0) -> str:
    """/stt: tệp về rồi → hỏi tiếng của tệp. Việc đã chốt sẵn là chép lời ra
    bản chữ, khỏi hỏi lại thứ người dùng đã nói bằng chính tên lệnh."""
    _ghi_buoc(key, path=path, ten=ten or "tệp âm thanh", so_byte=int(so_byte or 0),
              viec="chu-goc", buoc=BUOC_NGUON)
    return menu_buoc(key)


def nap_chu(key: str, chu: str) -> str:
    """/tts: nội dung về rồi → hỏi đọc bằng tiếng nào."""
    _ghi_buoc(key, chu=chu, buoc=BUOC_TIENG_DOC)
    return menu_buoc(key)


def dat_ban_dich(key: str, ban_dich: str, tieng: str) -> str:
    """/tts: dịch xong → hỏi đọc bản nào. Cho người dùng xem bản dịch TRƯỚC khi
    đọc, vì đọc xong mới thấy dịch sai là mất trắng cả lượt tổng hợp giọng."""
    _ghi_buoc(key, ban_dich=ban_dich, tieng=tieng, buoc=BUOC_DUYET_DICH)
    return menu_buoc(key)


def menu_buoc(key: str) -> str:
    """Menu của BƯỚC hiện tại — tệp và link đi ba bước, chữ đi một bước.

    Phiên đã hết hạn (30 phút) thì trả RỖNG: dựng menu cho một bản chờ không
    còn tệp nghĩa là mời người dùng chọn cho thứ đã bị dọn mất.
    """
    pend = get_pending(key)
    if not pend:
        return ""
    buoc = str(pend.get("buoc") or BUOC_VIEC)
    if buoc == BUOC_CHO_TEP:
        return "🎤 Em đang đợi tệp âm thanh ạ."
    if buoc == BUOC_CHO_CHU:
        return "🔊 Em đang đợi đoạn chữ cần đọc ạ."
    if buoc == BUOC_TIENG_DOC:
        dong = "\n".join(f"{i}. Tiếng {TEN_TIENG[m]}"
                         for i, m in enumerate(_danh_sach_tieng(), 1))
        return (f"🔊 Đọc bằng tiếng nào ạ? Nhắn số:\n{dong}\n"
                "Khác tiếng của đoạn chữ thì em dịch trước rồi gửi anh xem, "
                "duyệt xong em mới đọc.")
    if buoc == BUOC_DUYET_DICH:
        return ("🔊 Em đọc bản nào ạ?\n1. Bản dịch vừa gửi\n"
                "2. Bản gốc, giữ nguyên tiếng")
    if buoc == BUOC_DOAN:
        return ("🔍 Anh muốn phân tích đoạn nào ạ? Nhắn mốc thời gian (ví dụ "
                "«từ 10:20 đến 12:00») hoặc nói chủ đề của đoạn đó.")
    if buoc == BUOC_VI_TRI:
        return ("📝 Chữ hiện ở đâu ạ?\n1. Ở DƯỚI khung hình (thường dùng)\n"
                "2. Ở TRÊN khung hình (khi video đã có sẵn chữ ở dưới)")
    if buoc == BUOC_DANG_RA:
        return ("📦 Em trả về dạng nào ạ?\n1. Tệp phụ đề .srt (nhẹ, tự nạp "
                "vào trình phát)\n2. Ghép thẳng vào video rồi gửi lại "
                "(xem là thấy chữ)")
    if la_chu(pend):
        return menu(pend)
    if buoc == BUOC_VIEC:
        ten = str(pend.get("ten") or "video")
        mb = pend.get("so_byte") or 0
        co = f" ({mb / 1024 / 1024:.0f} MB)" if mb else ""
        dau = (f"🎬 Link video: {ten}{co}" if pend.get("url")
               else f"📄 Tệp phụ đề: {ten}{co}" if _la_phu_de(ten)
               else f"🎬 Tệp: {ten}{co}")
        dong = "\n".join(f"{so}. {nhan}"
                         for so, nhan, _ in _viec_hop_le(pend).values())
        return (f"{dau}\nEm làm gì với tệp này ạ? Nhắn số:\n{dong}\n"
                "Nhắn «thôi» để bỏ.")
    if buoc == BUOC_NGUON:
        dong = "\n".join(f"{i}. Tiếng {TEN_TIENG[m]}"
                         for i, m in enumerate(_danh_sach_tieng(), 1))
        return (f"🗣️ Tệp này nói tiếng gì ạ? Nhắn số:\n{dong}\n"
                "Biết trước tiếng thì em nghe chuẩn hơn và nhanh hơn.")
    nguon = str(pend.get("nguon") or "")
    ds = _danh_sach_tieng(nguon)
    dong = "\n".join(f"{i}. Tiếng {TEN_TIENG[m]}" for i, m in enumerate(ds, 1))
    if str(pend.get("viec") or "") in VIEC_GIU_GOC and nguon in TEN_TIENG:
        dong += (f"\n{len(ds) + 1}. Giữ nguyên tiếng {TEN_TIENG[nguon]} — "
                 "chép lời, không dịch")
    return (f"🌐 Dịch từ tiếng {TEN_TIENG.get(nguon, '?')} sang tiếng nào ạ? "
            f"Nhắn số:\n{dong}")


def tra_loi_buoc(key: str, text: str) -> dict[str, Any] | None:
    """Trả lời của người dùng cho bước hiện tại của phiên ``key``.

    Trả ``{"bo": True}`` nếu xin bỏ; ``{"tiep": True}`` khi đã ghi nhận và còn
    bước nữa (tầng gọi gửi ``menu_buoc(key)`` mới); ``{"kieu", "target",
    "nguon"}`` khi đã đủ để chạy; ``None`` khi câu này không phải trả lời menu.

    Tiến độ ghi thẳng vào sổ chờ theo KHOÁ, không theo đối tượng: ``get_pending``
    trả bản sao nên sửa vào bản sao là mất.
    """
    pend = get_pending(key)
    if not pend:
        return None
    t = str(text or "").strip().lower()
    if not t:
        return None
    if t in _BO:
        return {"bo": True}
    buoc = str(pend.get("buoc") or BUOC_VIEC)
    if buoc == BUOC_DOAN:
        # Bước này KHÔNG đi qua bộ giải số: câu trả lời là mốc giờ hay chủ đề
        # ("từ 10:20", "phần nói về lãi kép"), và "10:20" mà đưa vào _SO thì
        # thành lựa chọn số 1. Dùng chữ GỐC để giữ hoa/thường.
        return {"kieu": "llm", "viec": "phan-tich", "doan": str(text).strip()}
    m = _SO.match(t)
    if not m:
        return None
    so = m.group(1)
    if buoc == BUOC_TIENG_DOC:
        ds = _danh_sach_tieng()
        if int(so) > len(ds):
            return None
        return {"tts_tieng": ds[int(so) - 1], "chu": str(pend.get("chu") or "")}
    if buoc == BUOC_DUYET_DICH:
        if so not in ("1", "2"):
            return None
        lay_dich = so == "1"
        return {"tts_doc": (str(pend.get("ban_dich") or "") if lay_dich
                            else str(pend.get("chu") or "")),
                "tieng": (str(pend.get("tieng") or "") if lay_dich else "")}
    if buoc == BUOC_VIEC:
        chon = next((k for k, v in _viec_hop_le(pend).items() if v[0] == so), "")
        if not chon:
            return None
        if chon == "phan-tich":
            # Ô này ghi rõ "một đoạn CỤ THỂ" — đoạn nào thì chỉ người dùng
            # biết. Không hỏi thì LLM chỉ còn cách tóm tắt cả video, tức là
            # trùng ô 1 và ô người dùng chọn coi như không có.
            _ghi_buoc(key, viec=chon, buoc=BUOC_DOAN)
            return {"tiep": True}
        if chon in VIEC_QUA_LLM:
            # Ba ô còn lại chạy trên PHỤ ĐỀ đã có rồi giao cho LLM — không có
            # tiếng nguồn/đích để hỏi, hỏi thêm chỉ làm người dùng bấm thừa.
            return {"kieu": "llm", "viec": chon}
        _ghi_buoc(key, viec=chon, buoc=BUOC_NGUON)
        return {"tiep": True}
    if buoc == BUOC_NGUON:
        ds = _danh_sach_tieng()
        if int(so) > len(ds):
            return None
        nguon = ds[int(so) - 1]
        viec = str(pend.get("viec") or "phu-de")
        if viec in VIEC_KHONG_DICH:                    # chép lời: khỏi hỏi đích
            return {"kieu": VIEC_KHONG_DICH[viec],
                    "target": "giu-goc", "nguon": nguon}
        _ghi_buoc(key, nguon=nguon, buoc=BUOC_DICH)
        return {"tiep": True}
    if buoc == BUOC_VI_TRI:
        vi_tri = VI_TRI_PHU_DE.get(so)
        if not vi_tri:
            return None
        if not _co_luong_hinh(pend):
            # Tệp .srt / tệp âm thanh: không có hình để ghép chữ vào, nên câu
            # "trả .srt hay ghép vào video" chỉ có MỘT đáp án làm được. Hỏi
            # một câu mà đáp án đã biết trước là bắt người dùng bấm thừa.
            return {"kieu": "phu-de", "dang_ra": "srt", "vi_tri": vi_tri,
                    "target": str(pend.get("dich") or ""),
                    "nguon": str(pend.get("nguon") or "")}
        _ghi_buoc(key, vi_tri=vi_tri, buoc=BUOC_DANG_RA)
        return {"tiep": True}
    if buoc == BUOC_DANG_RA:
        dang = DANG_RA_PHU_DE.get(so)
        if not dang:
            return None
        return {"kieu": "phu-de", "dang_ra": dang,
                "vi_tri": str(pend.get("vi_tri") or "duoi"),
                "target": str(pend.get("dich") or ""),
                "nguon": str(pend.get("nguon") or "")}
    nguon = str(pend.get("nguon") or "")
    ds = _danh_sach_tieng(nguon)
    viec = str(pend.get("viec") or "phu-de")
    giu_goc = int(so) == len(ds) + 1 and viec in VIEC_GIU_GOC and nguon in TEN_TIENG
    if int(so) > len(ds) and not giu_goc:
        return None
    if giu_goc and viec == "dich-chu":
        return {"kieu": "chu", "target": "giu-goc", "nguon": nguon}
    # Ô phụ đề còn hai câu hỏi nữa — vị trí chữ, rồi dạng trả. Chủ máy chốt
    # 18/08: "nếu là phụ đề thì phải đưa lựa chọn trên hay dưới, thứ 2 hỏi trả
    # file phụ đề srt hay ghép luôn vào video". Trước đây bot tự đoán rồi gửi
    # CẢ HAI tệp .srt (bản thường và bản chữ-trên) — xem zalo_personal.
    if viec == "phu-de":
        _ghi_buoc(key, dich="giu-goc" if giu_goc else ds[int(so) - 1],
                  buoc=BUOC_VI_TRI)
        return {"tiep": True}
    kieu = "chu" if viec == "dich-chu" else (
        "long-tieng" if viec == "long-tieng" else "phu-de")
    # Truyền THẲNG mã đích, không bọc "cap:". "cap:ko" nghĩa là "cặp Việt ↔
    # Hàn", mà giai_ma_target giải nó thành: nguồn tiếng Việt thì sang Hàn,
    # còn lại về Việt. Menu ba bước đã hỏi rõ cả nguồn lẫn đích, nên chọn
    # Nhật → Hàn mà bọc cap: thì máy dịch ra TIẾNG VIỆT, không báo gì.
    return {"kieu": kieu, "target": ds[int(so) - 1],
            "nguon": str(pend.get("nguon") or "")}


def la_cau_tra_loi(key: str, text: str) -> bool:
    """Câu này CÓ PHẢI câu trả lời cho menu đang mở của phiên ``key`` không.

    Không tiêu thụ gì, không đổi bước — chỉ để cổng bắt-tag của nhóm quyết định
    cho câu này đi tiếp hay loại. Cần vì cửa sổ "vừa tag bot" sống 5 phút còn
    menu sống 30: đúng quãng giữa hai mốc đó, người dùng bấm số mà cổng nuốt
    mất, menu treo tới lúc hết hạn.

    Chỉ mở cho ĐÚNG dạng câu trả lời chứ không mở cho mọi tin trong 30 phút —
    mở rộng thế là tắt luôn yêu cầu tag của nhóm đó (cùng lý lẽ đã ghi ở
    zalo_personal, chỗ dựng ``_dang_cho``).
    """
    pend = get_pending(key)
    if not pend:
        return False
    t = str(text or "").strip().lower()
    if not t:
        return False
    if t in _BO:
        return True
    if str(pend.get("buoc") or "") in (BUOC_DOAN, BUOC_CHO_CHU):
        # Hai bước này nhận CHỮ TỰ DO (đoạn cần phân tích, nội dung cần đọc)
        # nên không soi dạng được. Chúng chỉ mở ra sau khi người dùng vừa chọn,
        # tức cửa sổ hẹp chứ không phải cả 30 phút.
        return True
    return bool(_SO.match(t))


def _ghi_buoc(key: str, **moi: Any) -> None:
    """Ghi tiến độ của phiên vào sổ chờ. Phiên đã hết hạn thì bỏ qua lặng lẽ."""
    with _lock:
        v = _pending.get(key)
        if v is not None:
            v.update(moi)


def menu(pend: dict[str, Any]) -> str:
    """Menu đánh số gửi cho người dùng."""
    if la_chu(pend):
        xem = str(pend.get("chu") or "").strip().replace("\n", " ")
        if len(xem) > 60:
            xem = xem[:60] + "…"
        return (
            f"🌐 «{xem}»\nDịch sang tiếng nào ạ? Nhắn số:\n"
            "1. Tiếng Việt\n2. Tiếng Anh\n3. Tiếng Nhật\n"
            "4. Tiếng Trung\n5. Tiếng Hàn\n"
            "Lần sau nhắn thẳng «/dich tiếng nhật …» thì em làm ngay, khỏi hỏi.\n"
            "Nhắn «thôi» để bỏ."
        )
    ten = str(pend.get("ten") or "video")
    mb = pend.get("so_byte") or 0
    co = f" ({mb / 1024 / 1024:.0f} MB)" if mb else ""
    if pend.get("url"):
        dau = f"🎬 Link video: {ten}{co}"
        cho = "Em lấy phụ đề của video rồi làm gì ạ?"
    elif _la_phu_de(ten):
        dau = f"📄 Tệp phụ đề: {ten}{co}"
        cho = "Em dịch phụ đề này thành gì ạ?"
    else:
        dau = f"🎬 Tệp: {ten}{co}"
        cho = "Em nghe rồi làm gì ạ? (video dài mất vài phút)"
    return (
        f"{dau}\n{cho} Nhắn số:\n"
        "1. Phụ đề .srt — dịch sang tiếng Việt\n"
        "2. Bản chữ (chỉ lời thoại) — dịch sang tiếng Việt\n"
        "3. Phụ đề .srt — GIỮ nguyên tiếng gốc (chép lời, không dịch)\n"
        "4. Phụ đề .srt sang tiếng khác — nhắn «4 anh» / «4 nhật» / «4 trung» / «4 hàn»\n"
        "5. Bản chữ sang tiếng khác — nhắn «5 anh» / «5 nhật» …\n"
        "Nhắn «thôi» để bỏ."
    )


_BO = ("thôi", "thoi", "bỏ", "bo", "huỷ", "huy", "cancel", "khỏi", "khoi")
# Menu video nay co BAY o (chu may chot 18/08), khong con nam nhu ban cu —
# giu [1-5] thi bam 6 (Phu de) hay 7 (Long tieng) deu roi xuong duong LLM
# nhu mot cau noi thuong, va menu hien lai y nguyen.
_SO = re.compile(r"^\s*([1-9])\b(.*)$", re.DOTALL)


#: Số trong menu CHỮ → tiếng đích (khác menu video: ở đó số là kiểu kết quả).
_SO_TIENG_CHU = {"1": "vi", "2": "en", "3": "ja", "4": "zh", "5": "ko"}


def giai_chon(text: str, *, cho_chu: bool = False) -> dict[str, Any] | None:
    """Câu người dùng nhắn → lựa chọn.

    ``cho_chu=True`` giải theo menu CHỮ (số = tiếng đích); mặc định giải theo
    menu video/phụ đề (số = kiểu kết quả + tiếng).

    Trả ``{"bo": True}`` nếu xin bỏ; ``{"kieu": "phu-de"|"chu", "target": …}``
    nếu chọn hợp lệ (``target`` = "giu-goc" nghĩa là không dịch, "cap:xx"
    nghĩa là cặp Việt ↔ xx); ``None`` nếu câu này không phải trả lời menu.
    """
    t = str(text or "").strip().lower()
    if not t:
        return None
    if t in _BO:
        return {"bo": True}
    m = _SO.match(t)
    if not m:
        return None
    so, con = m.group(1), (m.group(2) or "").strip()
    if cho_chu:
        # Cũng truyền thẳng mã: người dùng bấm số nào là muốn ĐÚNG tiếng đó.
        # Bọc "cap:" thì đoạn chữ tiếng Nhật chọn "Tiếng Anh" lại ra tiếng Việt.
        return {"kieu": "chu", "target": _SO_TIENG_CHU[so]}
    # Mã trơ ở mọi nhánh, không trộn hai kiểu hợp đồng trong một hàm: "cap:xx"
    # nghĩa là CẶP với tiếng Việt, còn mã trơ nghĩa là ĐÚNG tiếng đó. Để lẫn
    # thì chỗ gọi phải nhớ nhánh nào ra kiểu nào — đúng loại nhầm đã làm
    # Nhật→Hàn dịch ra tiếng Việt.
    if so == "1":
        return {"kieu": "phu-de", "target": "vi"}
    if so == "2":
        return {"kieu": "chu", "target": "vi"}
    if so == "3":
        return {"kieu": "phu-de", "target": "giu-goc"}
    # 4 / 5 — phải kèm tên tiếng
    kieu = "phu-de" if so == "4" else "chu"
    for ma, ten in TIENG.items():
        if any(x in con for x in ten):
            return {"kieu": kieu, "target": ma}
    return {"thieu_tieng": True, "kieu": kieu}


def target_cho_may(chon: dict[str, Any], nguon_biet: str = "") -> str:
    """Lựa chọn → giá trị ``target`` mà ``video_dich`` hiểu.

    - ``"cap:vi"`` (chọn 1/2) → cặp Việt↔Anh mặc định, tức truyền ``""``:
      máy tự chọn chiều (nguồn Việt thì sang Anh, còn lại về Việt).
    - ``"cap:xx"`` khác → giữ nguyên dạng cặp.
    - ``"giu-goc"`` → dịch sang CHÍNH tiếng nguồn = không dịch (bản chép lời);
      chưa biết nguồn thì trả ``"giu-goc"`` để tầng gọi tự xử.
    """
    tg = str(chon.get("target") or "")
    if tg == "cap:vi":
        return ""
    if tg == "giu-goc":
        return nguon_biet or "giu-goc"
    return tg
