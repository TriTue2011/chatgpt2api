"""Nhịp thơ cho TTS: nhận ra thể thơ bằng số chữ mỗi dòng rồi chèn dấu phẩy ở chỗ ngắt nhịp.

Chủ máy 29/09/2026: "nếu đưa cho một bài thơ, nó có đọc TTS đúng nhịp điệu được không, ngắt
dòng" → "thu thập các loại thơ để TTS tốt nhất" → "làm cả hai".

Vì sao dấu phẩy: đo 29/09/2026 giọng mặc định (Piper «manhdung»), hai dòng lục bát đầu Truyện
Kiều — không phẩy thì trong dòng không nghỉ chỗ nào; phẩy ở chỗ ngắt nhịp thì giọng tự nghỉ
260–420 ms mà ngữ điệu vẫn liền một câu. Cắt dòng thành nhiều lượt đọc riêng thì mỗi mẩu tự lên
xuống giọng như một câu — nghe rời rạc.

Nhận ra thể CHỈ bằng số chữ (âm tiết) mỗi dòng, không danh sách bài: đo trên bộ mẫu
``test/data/tho_mau.json`` (111 bài Wikisource), đúng 76/78 bài người soạn đã ghi thể.

Luật nhịp (sách giáo khoa): lục bát câu 6 2/2/2, câu 8 2/2/2/2 hoặc 4/4; song thất lục bát câu
bảy 3/4; thất ngôn Đường luật và thơ mới bảy chữ 4/3; ngũ ngôn 2/3; bốn chữ 2/2. Thơ tám chữ
(3/5, 4/4, 3/3/2 tuỳ bài) và thơ tự do không có nhịp cố định — chỉ ngắt dòng.

Hết khổ: dòng trống giữa hai khổ đổi thành HAI dòng trống — ``engines._loai_ranh`` coi đó là
hết khổ (nghỉ gấp đôi hết dòng). Chỉ làm khi đã nhận ra là thơ (kể cả thơ tám chữ); một dòng
trống trong văn xuôi là tách đoạn thường, giữ nguyên.

Mức: ``"day_du"`` (mặc định — chủ máy nghe mẫu hai giọng 29/09/2026 rồi chọn) đủ nhịp sách giáo
khoa (câu 6: 2/2/2, câu 8: 2/2/2/2); ``"chinh"`` một chỗ ngắt mỗi dòng (câu 6: 2/4, câu 8: 4/4);
``"tat"`` không chèn.
"""

from __future__ import annotations

import collections
import re

MUC = ("chinh", "day_du", "tat")

#: Chữ = một âm tiết tiếng Việt (chuỗi chữ cái liền nhau).
_CHU = re.compile(r"[^\W\d_]+")
#: Dấu câu nằm GIỮA dòng thì dòng ấy đã có chỗ ngắt của tác giả — không chèn thêm.
_DAU_GIUA = re.compile(r"[,;:.!?…—–]")

#: (thể, số chữ của dòng) → vị trí ngắt (sau chữ thứ mấy) theo mức.
_NHIP: dict[str, dict[int, tuple[tuple[int, ...], tuple[int, ...]]]] = {
    #            số chữ: (chính,  đầy đủ)
    "luc_bat": {6: ((2,), (2, 4)), 8: ((4,), (2, 4, 6))},
    "song_that_luc_bat": {7: ((3,), (3,)), 6: ((2,), (2, 4)), 8: ((4,), (2, 4, 6))},
    "bay_chu": {7: ((4,), (4,))},
    "ngu_ngon": {5: ((2,), (2,))},
    "bon_chu": {4: ((2,), (2,))},
}


def so_chu(dong: str) -> int:
    return len(_CHU.findall(dong))


def the_tho(dong: list[str]) -> str | None:
    """Thể thơ đoán từ số chữ mỗi dòng (dòng trống bỏ qua), hoặc None nếu không giống thơ có
    khuôn. Cần ít nhất 4 dòng và ít nhất 80% số dòng đúng khuôn."""
    co = [x for x in dong if x.strip()]
    if len(co) < 4:
        return None
    d = collections.Counter(so_chu(x) for x in co)
    ty = lambda *n: sum(d[k] for k in n) / len(co)  # noqa: E731
    # Lục bát: câu 6 và câu 8 xen nhau — mỗi loại khoảng một nửa.
    if ty(6, 8) >= 0.8 and 0.3 <= ty(6) <= 0.6:
        return "luc_bat"
    if ty(8) >= 0.8:
        return "tam_chu"
    # Khổ 7-7-6-8: câu bảy chiếm khoảng một nửa.
    if ty(7, 6, 8) >= 0.8 and 0.35 <= ty(7) <= 0.65 and d[6] and d[8]:
        return "song_that_luc_bat"
    if ty(7) >= 0.8:
        return "bay_chu"
    if ty(5) >= 0.8:
        return "ngu_ngon"
    if ty(4) >= 0.8:
        return "bon_chu"
    return None


def _ngat_dong(dong: str, sau: tuple[int, ...]) -> str:
    """Chèn "," sau chữ thứ ``sau[i]`` của dòng (giữ nguyên mọi ký tự khác)."""
    chu = list(_CHU.finditer(dong))
    ra, pos = [], 0
    for k in sau:
        if k >= len(chu):
            break
        cuoi = chu[k - 1].end()
        ra.append(dong[pos:cuoi] + ",")
        pos = cuoi
    ra.append(dong[pos:])
    return "".join(ra)


def danh_nhip(text: str, muc: str = "day_du") -> str:
    """Văn bản là thơ có khuôn → chèn dấu phẩy ở chỗ ngắt nhịp mỗi dòng; không thì trả nguyên."""
    if muc not in ("chinh", "day_du") or "\n" not in (text or ""):
        return text
    dong = text.split("\n")
    the = the_tho(dong)
    if the is None:
        return text
    nhip = _NHIP.get(the, {})
    i = 0 if muc == "chinh" else 1
    ra = []
    for x in dong:
        than = x.rstrip()
        # Dấu câu ở giữa dòng (không tính dấu cuối dòng): tác giả đã tự ngắt.
        giua = than.rstrip(",;:.!?…").strip()
        k = nhip.get(so_chu(x))
        ra.append(_ngat_dong(x, k[i]) if k and not _DAU_GIUA.search(giua) else x)
    # Dòng trống giữa hai khổ → hai dòng trống: dấu hết khổ cho ``engines._loai_ranh``.
    return re.sub(r"\n(?:[ \t]*\n)+", "\n\n\n", "\n".join(ra))
