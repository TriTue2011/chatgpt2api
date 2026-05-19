"""kb_y_te — kho tri thức y tế cơ bản.

RAG-backed: query Chroma collection 'y_te' (ingested from data/y_te/*.md).
Đây là kiến thức tham khảo, KHÔNG thay thế chẩn đoán bác sĩ.

Tools:
- ask_y_te(question): hỏi tự do
- list_topics(): liệt kê chủ đề
- get_topic_status(): kiểm tra Chroma collection
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.rag.retriever import RAGRetriever
from src.rag.hybrid import hybrid_query, format_hybrid_results

mcp = FastMCP("kb_y_te")

COLLECTION = "y_te"

DISCLAIMER = (
    "\n\n_⚠️ Thông tin y tế chỉ mang tính tham khảo. Vui lòng tham khảo bác sĩ "
    "khi có triệu chứng bất thường._"
)


@mcp.tool()
def ask_y_te(question: str, top_k: int = 4) -> str:
    """Hỏi đáp y tế cơ bản (kiến thức tham khảo, không chẩn đoán).

    Args:
        question: Câu hỏi tiếng Việt (vd: "huyết áp cao là bao nhiêu",
                  "sốt 39 độ ở trẻ em phải làm sao", "tiểu đường ăn gì").
        top_k: Số đoạn tài liệu liên quan trả về (1-8, mặc định 4).

    Returns:
        Các đoạn tài liệu phù hợp + cảnh báo tham khảo bác sĩ.
    """
    top_k = max(1, min(8, top_k))
    results = hybrid_query(COLLECTION, question, top_k=top_k)
    return format_hybrid_results(results) + DISCLAIMER


@mcp.tool()
def list_topics() -> str:
    """Liệt kê chủ đề y tế trong kho tri thức.

    Returns:
        Danh sách file markdown nguồn.
    """
    from pathlib import Path
    folder = Path("/app/data/y_te")
    if not folder.exists():
        return "Kho tri thức chưa được seed (data/y_te/ trống)."
    files = sorted(folder.glob("*.md"))
    if not files:
        return "Kho tri thức rỗng."
    lines = ["**Chủ đề y tế:**", ""]
    lines.extend(f"- {f.stem}" for f in files)
    return "\n".join(lines)


@mcp.tool()
def get_topic_status() -> str:
    """Kiểm tra Chroma collection y_te có dữ liệu hay chưa."""
    stats = RAGRetriever.get().collection_stats(COLLECTION)
    if not stats.get("available"):
        return "Collection chưa khởi tạo. Chạy: docker exec vn-mcp-hub python -m src.rag.ingest"
    count = stats.get("count", 0)
    if count == 0:
        return "Collection rỗng. Thêm file vào data/y_te/ rồi chạy ingest."
    return f"Collection 'y_te' có {count} chunks."
