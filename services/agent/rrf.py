"""Trộn hạng RRF + độ giống tam-gram — thuần Python, không dependency.

Bài học lấy từ kiến trúc truy hồi của TencentDB-Agent-Memory (BM25 + vector
+ RRF): dự án không có đường embedding trong gateway, nên thay tín hiệu
vector bằng các tín hiệu từ vựng bổ trợ nhau rồi trộn bằng Reciprocal Rank
Fusion — mỗi bảng xếp hạng đóng góp ``1/(k + hạng)``, kết quả ổn định hơn
mọi cách cộng điểm thô vì không phải chuẩn hoá thang điểm giữa các tín hiệu.

Dùng chung cho ``state.search_memory`` (bm25 + độ mới + tam-gram) và
``wiki.search`` (số từ khớp + độ mới + tam-gram).
"""

from __future__ import annotations

from typing import Hashable, Sequence

# k=60 là hằng số gốc của RRF (Cormack et al.) — đủ phẳng để một bảng xếp
# hạng đơn lẻ không lấn át các bảng còn lại.
_RRF_K = 60

# Ngưỡng bao phủ tam-gram để VỚT ứng viên ngoài đường khớp-từ. Dùng chung cho
# state._tim_trong_index và wiki.search — chỉnh ở đây để hai đường không lệch.
NGUONG_VOT = 0.45


def xep_hang_rrf(cac_bang: Sequence[Sequence[Hashable]], *,
                 k: int = _RRF_K) -> list[Hashable]:
    """Trộn nhiều bảng xếp hạng thành một, tốt nhất đứng đầu.

    Mỗi bảng là một dãy khoá xếp từ TỐT NHẤT tới kém dần; khoá vắng mặt ở một
    bảng thì không được cộng điểm từ bảng đó. Hoà điểm giữ thứ tự xuất hiện
    (ổn định, không phụ thuộc hash).
    """
    diem: dict[Hashable, float] = {}
    thu_tu: dict[Hashable, int] = {}
    stt = 0
    for bang in cac_bang:
        for hang, khoa in enumerate(bang):
            diem[khoa] = diem.get(khoa, 0.0) + 1.0 / (k + hang + 1)
            if khoa not in thu_tu:
                thu_tu[khoa] = stt
                stt += 1
    return sorted(diem, key=lambda kh: (-diem[kh], thu_tu[kh]))


def tam_gram(s: str) -> set[str]:
    """Bộ tam-gram ký tự của một chuỗi (fold sẵn). Public để caller tính bộ
    gram của TRUY VẤN đúng một lần rồi so với nhiều văn bản qua bao_phu_gram —
    đường nóng (mỗi lượt chat) không phải dựng lại bộ gram query mỗi lần so."""
    s = " ".join((s or "").split())
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


_tam_gram = tam_gram  # giữ tên cũ cho nội bộ module


def bao_phu_gram(gq: set[str], van_ban: str) -> float:
    """Như bao_phu_tam_gram nhưng nhận bộ gram truy vấn TÍNH SẴN."""
    if not gq:
        return 0.0
    gv = _tam_gram(van_ban)
    if not gv:
        return 0.0
    return len(gq & gv) / len(gq)


def diem_tam_gram(a: str, b: str) -> float:
    """Độ giống Dice trên tam-gram ký tự, 0..1 — a, b nên fold sẵn
    (``vi_text.fold``) để không phụ thuộc dấu. Bắt được lỗi gõ và biến thể
    dính/tách từ ("tiemphong" ↔ "tiem phong") mà FTS theo từ nguyên vẹn bỏ lỡ.
    """
    ga, gb = _tam_gram(a), _tam_gram(b)
    if not ga or not gb:
        return 0.0
    return 2.0 * len(ga & gb) / (len(ga) + len(gb))


def bao_phu_tam_gram(truy_van: str, van_ban: str) -> float:
    """Tỷ lệ tam-gram của TRUY VẤN có mặt trong VĂN BẢN, 0..1 (bất đối xứng).

    Dice bị loãng khi văn bản dài hơn truy vấn nhiều lần (ghi chú wiki vs câu
    hỏi ngắn); độ bao phủ chỉ hỏi "văn bản có chứa chất liệu của truy vấn
    không" nên vẫn phân biệt tốt. Cả hai chuỗi nên fold sẵn (``vi_text.fold``).
    """
    return bao_phu_gram(_tam_gram(truy_van), van_ban)
