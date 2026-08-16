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

#: Việc làm được với tệp: mã → (số menu, nhãn, có phải dịch không).
VIEC = {
    "phu-de": ("1", "Tạo phụ đề .srt (dịch sang tiếng khác)", True),
    "chu": ("2", "Dịch ra bản chữ (chỉ lời thoại)", True),
    "chep-loi": ("3", "Chép lời ra .srt, GIỮ nguyên tiếng gốc", False),
    # Ô thứ tư này chính là việc "chuyển âm thanh thành văn bản" mà người dùng
    # hay gọi là STT: không dịch, không mốc thời gian, chỉ chữ. Ba ô trên đều
    # thiếu nó — ô 3 giữ nguyên tiếng nhưng trả .srt đầy số thứ tự và mốc giờ,
    # dán vào tài liệu là phải dọn tay.
    "chu-goc": ("4", "Chép lời ra bản chữ thuần, GIỮ nguyên tiếng gốc", False),
    # Chỉ hiện cho TỆP VIDEO thật: link hiện chưa tải cả hình về gateway, còn
    # tệp phụ đề/âm thanh không có luồng hình để thay track.
    "long-tieng": ("5", "Lồng tiếng video (giữ nhạc và hiệu ứng)", True),
}

_DUOI_VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp")


def _la_tep_video(pend: dict[str, Any]) -> bool:
    # ``path`` có thể là chuỗi rỗng trong adapter/test trước lúc tệp được chốt;
    # điểm phân biệt link là trường ``url``, còn loại tệp lấy theo tên đã nhận.
    return not bool(pend.get("url")) and str(
        pend.get("ten") or "").lower().endswith(_DUOI_VIDEO)


def _viec_hop_le(pend: dict[str, Any]) -> dict[str, tuple[str, str, bool]]:
    """Các việc thật sự làm được với đúng loại đầu vào đang chờ."""
    return {ma: gia_tri for ma, gia_tri in VIEC.items()
            if ma != "long-tieng" or _la_tep_video(pend)}


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
    dong = "\n".join(f"{i}. Tiếng {TEN_TIENG[m]}"
                     for i, m in enumerate(_danh_sach_tieng(nguon), 1))
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
    m = _SO.match(t)
    if not m:
        return None
    so = m.group(1)
    buoc = str(pend.get("buoc") or BUOC_VIEC)
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
        _ghi_buoc(key, viec=chon, buoc=BUOC_NGUON)
        return {"tiep": True}
    if buoc == BUOC_NGUON:
        ds = _danh_sach_tieng()
        if int(so) > len(ds):
            return None
        nguon = ds[int(so) - 1]
        viec = str(pend.get("viec") or "phu-de")
        if not VIEC.get(viec, ("", "", True))[2]:      # chép lời: khỏi hỏi đích
            # "chu-goc" ra BẢN CHỮ, "chep-loi" ra .srt — cùng là không dịch
            # nhưng khác hẳn thứ người dùng nhận được.
            return {"kieu": "chu" if viec == "chu-goc" else "phu-de",
                    "target": "giu-goc", "nguon": nguon}
        _ghi_buoc(key, nguon=nguon, buoc=BUOC_DICH)
        return {"tiep": True}
    ds = _danh_sach_tieng(str(pend.get("nguon") or ""))
    if int(so) > len(ds):
        return None
    viec = str(pend.get("viec") or "phu-de")
    kieu = "chu" if viec == "chu" else (
        "long-tieng" if viec == "long-tieng" else "phu-de")
    # Truyền THẲNG mã đích, không bọc "cap:". "cap:ko" nghĩa là "cặp Việt ↔
    # Hàn", mà giai_ma_target giải nó thành: nguồn tiếng Việt thì sang Hàn,
    # còn lại về Việt. Menu ba bước đã hỏi rõ cả nguồn lẫn đích, nên chọn
    # Nhật → Hàn mà bọc cap: thì máy dịch ra TIẾNG VIỆT, không báo gì.
    return {"kieu": kieu, "target": ds[int(so) - 1],
            "nguon": str(pend.get("nguon") or "")}


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
_SO = re.compile(r"^\s*([1-5])\b(.*)$", re.DOTALL)


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
