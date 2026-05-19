"""kb_xa_hoi — kho tri thức xã hội (lịch sử VN, văn hoá, kinh tế, chính trị).

RAG-backed: Chroma collection 'xa_hoi' (data/xa_hoi/*.md).

Tools:
- ask_xa_hoi(question): hỏi tự do
- list_topics(): liệt kê chủ đề
- get_topic_status(): kiểm tra Chroma collection
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.rag.retriever import RAGRetriever, format_results, query

mcp = FastMCP("kb_xa_hoi")

COLLECTION = "xa_hoi"


@mcp.tool()
def ask_xa_hoi(question: str, top_k: int = 4) -> str:
    """Hỏi đáp về xã hội: lịch sử VN, văn hoá, kinh tế, chính trị, dân tộc.

    Args:
        question: Câu hỏi tiếng Việt (vd: "lịch sử triều Lý",
                  "đặc trưng văn hoá Việt Nam", "kinh tế thị trường XHCN",
                  "54 dân tộc Việt Nam").
        top_k: Số đoạn tài liệu liên quan trả về (1-8, mặc định 4).

    Returns:
        Các đoạn tài liệu phù hợp từ kho tri thức xã hội.
    """
    top_k = max(1, min(8, top_k))
    results = query(COLLECTION, question, top_k=top_k)
    return format_results(results)


@mcp.tool()
def list_topics() -> str:
    """Liệt kê chủ đề xã hội trong kho."""
    from pathlib import Path
    folder = Path("/app/data/xa_hoi")
    if not folder.exists():
        return "Kho tri thức chưa được seed (data/xa_hoi/ trống)."
    files = sorted(folder.glob("*.md"))
    if not files:
        return "Kho tri thức rỗng."
    lines = ["**Chủ đề xã hội:**", ""]
    lines.extend(f"- {f.stem}" for f in files)
    return "\n".join(lines)


@mcp.tool()
def get_topic_status() -> str:
    """Kiểm tra Chroma collection xa_hoi."""
    stats = RAGRetriever.get().collection_stats(COLLECTION)
    if not stats.get("available"):
        return "Collection chưa khởi tạo. Chạy: docker exec vn-mcp-hub python -m src.rag.ingest"
    count = stats.get("count", 0)
    if count == 0:
        return "Collection rỗng. Thêm file vào data/xa_hoi/ rồi chạy ingest."
    return f"Collection 'xa_hoi' có {count} chunks."
