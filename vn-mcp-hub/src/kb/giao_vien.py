"""kb_giao_vien — tra 5 kho tài liệu dạy học, mỗi kho một mục đích khác nhau.

Vì sao cần MCP này: đường nạp của phần Giáo viên tách tài liệu ra NHIỀU
collection theo LOẠI, cố ý — sách học sinh, sách giáo viên, vở/sách bài tập, tài
liệu tập huấn, slide phân bổ tuần–tiết là năm thứ khác nhau, để chung một kho thì
truy vấn "bài 5 Toán 4" kéo về cả năm và bot trả lời trộn. Nhưng chỉ
``kb_giao_duc`` có MCP, nên bốn kho còn lại có dữ liệu mà KHÔNG có đường hỏi.

Gộp cả năm vào MỘT MCP thay vì năm MCP riêng: người vận hành bật một công tắc,
và bot thấy đủ năm tool cùng lúc nên chọn được đúng kho ngay trong một lượt.

MÔ TẢ TOOL LÀ THỨ DUY NHẤT dạy bot khi nào dùng kho nào — không có bảng định
tuyến nào khác. Nên mỗi docstring dưới đây nêu thẳng CÂU HỎI MẪU, và phân biệt
cặp dễ lẫn nhất: "bài 3 dạy GÌ" (sách học sinh) khác "DẠY bài 3 thế nào" (sách
giáo viên).
"""

from __future__ import annotations

import re

from fastmcp import FastMCP
from src.kb.hybrid_search import kb_ask
from src.rag.retriever import RAGRetriever

mcp = FastMCP("kb_giao_vien")

C_SGK = "kb_giao_duc"
C_SGV = "kb_giao_duc_sgv"
C_VBT = "kb_giao_duc_vbt"
C_TAILIEU = "kb_giao_duc_tailieu"
C_SLIDE = "kb_giao_duc_slide"


def _sgk_collection(bo: str = "") -> str:
    """Kho SGK theo BỘ SÁCH. Bộ chính → kb_giao_duc, bộ N → kb_giao_duc_bo{N}.

    Khớp ``services/agent/sgk_taphuan.COLLECTION_FOR_SET``. Chỉ nhận chữ số để
    tên collection không thể bị nhét ký tự lạ.
    """
    s = re.sub(r"\D", "", str(bo or ""))
    return f"{C_SGK}_bo{s}" if s else C_SGK


_MON_HOP_LE = frozenset(
    ("toan", "tviet", "van", "anh", "sudia", "su", "dia", "ly", "hoa", "sinh")
)


def _loc(lop: int = 0, mon: str = "") -> dict | None:
    """Bộ lọc metadata theo lớp–môn cho các kho gộp cả 12 lớp.

    Vì sao BẮT BUỘC phải lọc thay vì tin vào ngữ nghĩa: kho SGK chứa cả 12 lớp,
    mà embedding không mang thông tin "lớp mấy" — sách các lớp dùng chung từ vựng
    môn học. Đo thật trên kb_giao_duc (585 chunk, 12 lớp) ngày 2026-07-29: câu hỏi
    có ghi rõ tên lớp ("Toán 9 định lí Viète") chỉ ra đúng lớp–môn 4/12 lần; nhồi
    thêm "lop=9 mon=toan" vào câu hỏi còn tệ hơn (0/8) vì chuỗi kĩ thuật làm loãng
    vector. Lọc metadata: 12/12. Không lọc là bài giảng lớp 1 trích sách lớp 7.

    Chỉ nhận mã môn có thật (khớp teacher_workspace.SUBJECTS) — mã lạ thì bỏ, thà
    tra rộng còn hơn lọc bằng khoá không tồn tại rồi trả về rỗng.
    """
    dk: list[dict] = []
    try:
        g = int(lop)
    except (TypeError, ValueError):
        g = 0
    if 1 <= g <= 12:
        dk.append({"grade": {"$eq": g}})
    m = str(mon or "").strip().lower()
    if m in _MON_HOP_LE:
        dk.append({"subject": {"$eq": m}})
    if not dk:
        return None
    return dk[0] if len(dk) == 1 else {"$and": dk}


@mcp.tool()
def ask_sgk(question: str, bo: str = "", top_k: int = 4, lop: int = 0, mon: str = "") -> str:
    """Tra NỘI DUNG SÁCH HỌC SINH — thứ học sinh phải học.

    Dùng khi hỏi nội dung bài: "bài 3 Tiếng Việt 1 dạy gì", "công thức trong bài
    5 Toán 9", "đoạn văn trang 47", "trong sách có nói gì về...".

    KHÔNG dùng cho câu hỏi về CÁCH DẠY — cái đó gọi ask_sgv.

    LUÔN truyền `lop` và `mon` khi câu hỏi nói rõ lớp nào môn nào. Kho có cả 12
    lớp và tìm theo ngữ nghĩa KHÔNG phân biệt được lớp — bỏ trống hai tham số này
    thì rất dễ lấy sách lớp khác.

    Args:
        question: Câu hỏi tiếng Việt.
        bo: Mã bộ sách khác (vd "3"). Để trống = bộ dùng thống nhất toàn quốc.
        top_k: Số đoạn trả về (1-8, mặc định 4).
        lop: Lớp 1–12. 0 = không lọc.
        mon: Mã môn: toan, tviet, van, anh, sudia, su, dia, ly, hoa, sinh.
    """
    return kb_ask(_sgk_collection(bo), question, top_k=top_k, where=_loc(lop, mon))


@mcp.tool()
def ask_sgv(question: str, top_k: int = 4, lop: int = 0, mon: str = "") -> str:
    """Tra SÁCH GIÁO VIÊN / KẾ HOẠCH BÀI DẠY — gợi ý CÁCH dạy.

    Dùng khi hỏi cách tổ chức dạy: "dạy bài 3 thế nào", "hoạt động mở đầu bài
    này", "mục tiêu cần đạt của bài", "học sinh thường sai ở đâu", "gợi ý cho
    học sinh yếu".

    Đây là tài liệu cho GIÁO VIÊN, không phải nội dung học sinh phải học — đừng
    đọc nó ra như thể là bài trong sách của học sinh.

    Args:
        question: Câu hỏi tiếng Việt.
        top_k: Số đoạn trả về (1-8, mặc định 4).
        lop: Lớp 1–12 (0 = không lọc). Kho gộp cả 12 lớp nên NÊN truyền.
        mon: Mã môn (toan, tviet, van, anh, sudia, su, dia, ly, hoa, sinh).
    """
    return kb_ask(C_SGV, question, top_k=top_k, where=_loc(lop, mon))


@mcp.tool()
def ask_bai_tap(question: str, top_k: int = 4, lop: int = 0, mon: str = "") -> str:
    """Tra VỞ / SÁCH BÀI TẬP — mẫu dạng bài để ra đề.

    Dùng khi cần dạng bài: "cho tôi bài tập dạng điền vào chỗ trống lớp 2",
    "mẫu bài tập tính nhanh", "dạng bài về đồng đẳng".

    ⚠️ Kho này PHẦN LỚN là BÀI MẪU, không phải cả quyển (đo thật: 135/145 quyển
    trên kho là bài mẫu, số còn lại chỉ 4–19 trang). Dùng để học KIỂU ra đề rồi
    tự soạn thêm, và nói rõ với người dùng là mẫu — đừng khẳng định "vở bài tập
    có bài X" khi kho chỉ có vài trang mẫu.

    Args:
        question: Câu hỏi tiếng Việt.
        top_k: Số đoạn trả về (1-8, mặc định 4).
        lop: Lớp 1–12 (0 = không lọc). Kho gộp cả 12 lớp nên NÊN truyền.
        mon: Mã môn (toan, tviet, van, anh, sudia, su, dia, ly, hoa, sinh).
    """
    return kb_ask(C_VBT, question, top_k=top_k, where=_loc(lop, mon))


@mcp.tool()
def ask_phan_bo(question: str, top_k: int = 4, lop: int = 0, mon: str = "") -> str:
    """Tra PHÂN BỔ TUẦN – TIẾT và cấu trúc chương trình.

    Dùng khi hỏi tiến độ và thời lượng: "bài 3 học tuần mấy", "học vần mấy tiết",
    "tuần 1 đến 6 dạy gì", "cả năm bao nhiêu tiết", "thứ tự các bài trong tập
    một", "điểm mới của sách so với chương trình cũ".

    Nguồn: slide giới thiệu sách + tập huấn giáo viên của nhà xuất bản. Đây là
    kho DUY NHẤT có phân bổ tuần–tiết, nên câu hỏi về tiến độ phải vào đây chứ
    không phải ask_sgk.

    Args:
        question: Câu hỏi tiếng Việt.
        top_k: Số đoạn trả về (1-8, mặc định 4).
        lop: Lớp 1–12 (0 = không lọc). Kho gộp cả 12 lớp nên NÊN truyền.
        mon: Mã môn (toan, tviet, van, anh, sudia, su, dia, ly, hoa, sinh).
    """
    return kb_ask(C_SLIDE, question, top_k=top_k, where=_loc(lop, mon))


@mcp.tool()
def ask_tai_lieu(question: str, top_k: int = 4) -> str:
    """Tra TÀI LIỆU TẬP HUẤN, BỒI DƯỠNG giáo viên.

    Dùng cho câu hỏi về phương pháp và đánh giá ở mức chương trình: "cách đánh
    giá theo thông tư", "dạy học phát triển năng lực là gì", "hướng dẫn sử dụng
    sách giáo khoa mới".

    Args:
        question: Câu hỏi tiếng Việt.
        top_k: Số đoạn trả về (1-8, mặc định 4).
    """
    return kb_ask(C_TAILIEU, question, top_k=top_k)


@mcp.tool()
def trang_thai_kho() -> str:
    """Kho nào đã có dữ liệu, kho nào còn rỗng (số chunks từng kho).

    Gọi cái này TRƯỚC khi kết luận "không có thông tin": kho rỗng nghĩa là CHƯA
    NẠP, khác hẳn với "đã nạp mà không tìm thấy". Nói sai hai thứ đó là người
    dùng đi tìm nội dung không hề tồn tại.
    """
    r = RAGRetriever.get()
    rows = [
        ("SGK (sách học sinh)", C_SGK),
        ("SGV + kế hoạch bài dạy", C_SGV),
        ("Vở & sách bài tập", C_VBT),
        ("Tài liệu tập huấn", C_TAILIEU),
        ("Phân bổ tuần–tiết (slide)", C_SLIDE),
    ]
    out = ["**Kho tài liệu dạy học:**", ""]
    for label, name in rows:
        try:
            st = r.collection_stats(name)
        except Exception as exc:  # noqa: BLE001 — báo trạng thái, không được chết
            out.append(f"- {label} (`{name}`): lỗi đọc — {str(exc)[:80]}")
            continue
        if not st.get("available"):
            out.append(f"- {label} (`{name}`): **chưa khởi tạo** (chưa nạp gì)")
            continue
        n = int(st.get("count") or 0)
        out.append(f"- {label} (`{name}`): "
                   + (f"{n} chunks" if n else "**rỗng** (chưa nạp)"))
    # Bộ sách khác nạp vào kb_giao_duc_bo{N}; dò vài mã hay dùng.
    extra = []
    for bo in ("2", "3", "4", "5"):
        name = _sgk_collection(bo)
        try:
            st = r.collection_stats(name)
        except Exception:
            continue
        n = int(st.get("count") or 0)
        if st.get("available") and n:
            extra.append(f"- SGK bộ {bo} (`{name}`): {n} chunks")
    if extra:
        out += ["", "**Bộ sách khác:**", ""] + extra
    return "\n".join(out)
