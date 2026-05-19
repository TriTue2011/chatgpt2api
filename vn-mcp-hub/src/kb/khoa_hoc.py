"""kb_khoa_hoc — kho tri thức khoa học cơ bản (vật lý, hoá học, sinh học, toán).

RAG-backed: Chroma collection 'khoa_hoc' (data/khoa_hoc/*.md).
Phase 2 sẽ thêm hybrid mode: RAG + search (vn_search/wikipedia/arxiv) song song,
chatgpt2api LLM tự merge kết quả.

Tools:
- ask_khoa_hoc(question): hỏi tự do, RAG retrieve top-k chunks
- list_topics(): liệt kê chủ đề trong kho
- get_topic_status(): kiểm tra Chroma collection
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.rag.retriever import RAGRetriever
from src.rag.hybrid import hybrid_query, format_hybrid_results

mcp = FastMCP("kb_khoa_hoc")

COLLECTION = "khoa_hoc"


@mcp.tool()
def ask_khoa_hoc(question: str, top_k: int = 4) -> str:
    """Hỏi đáp về khoa học cơ bản (vật lý, hoá học, sinh học, toán).

    Args:
        question: Câu hỏi tiếng Việt (vd: "định luật Newton thứ 2",
                  "phản ứng oxy hoá khử", "DNA cấu trúc thế nào",
                  "đạo hàm là gì").
        top_k: Số đoạn tài liệu liên quan trả về (1-8, mặc định 4).

    Returns:
        Các đoạn tài liệu phù hợp nhất từ kho tri thức khoa học.
    """
    top_k = max(1, min(8, top_k))
    results = hybrid_query(COLLECTION, question, top_k=top_k)
    return format_hybrid_results(results)


@mcp.tool()
def list_topics() -> str:
    """Liệt kê chủ đề khoa học trong kho."""
    from pathlib import Path
    folder = Path("/app/data/khoa_hoc")
    if not folder.exists():
        return "Kho tri thức chưa được seed (data/khoa_hoc/ trống)."
    files = sorted(folder.glob("*.md"))
    if not files:
        return "Kho tri thức rỗng."
    lines = ["**Chủ đề khoa học:**", ""]
    lines.extend(f"- {f.stem}" for f in files)
    return "\n".join(lines)


@mcp.tool()
def get_topic_status() -> str:
    """Kiểm tra Chroma collection khoa_hoc."""
    stats = RAGRetriever.get().collection_stats(COLLECTION)
    if not stats.get("available"):
        return "Collection chưa khởi tạo. Chạy: docker exec vn-mcp-hub python -m src.rag.ingest"
    count = stats.get("count", 0)
    if count == 0:
        return "Collection rỗng. Thêm file vào data/khoa_hoc/ rồi chạy ingest."
    return f"Collection 'khoa_hoc' có {count} chunks."
