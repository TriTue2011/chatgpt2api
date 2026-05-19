"""kb_tu_nhien — kho tri thức tự nhiên (động vật, thực vật, môi trường, khí hậu).

RAG-backed: Chroma collection 'tu_nhien' (data/tu_nhien/*.md).

Tools:
- ask_tu_nhien(question): hỏi tự do
- list_topics(): liệt kê chủ đề
- get_topic_status(): kiểm tra Chroma collection
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.rag.retriever import RAGRetriever, format_results, query

mcp = FastMCP("kb_tu_nhien")

COLLECTION = "tu_nhien"


@mcp.tool()
def ask_tu_nhien(question: str, top_k: int = 4) -> str:
    """Hỏi đáp về tự nhiên: động vật, thực vật, hệ sinh thái, khí hậu, địa lý.

    Args:
        question: Câu hỏi tiếng Việt (vd: "loài voi sống ở đâu",
                  "rừng nhiệt đới VN", "biến đổi khí hậu là gì",
                  "động đất hình thành thế nào").
        top_k: Số đoạn tài liệu liên quan trả về (1-8, mặc định 4).

    Returns:
        Các đoạn tài liệu phù hợp từ kho tri thức tự nhiên.
    """
    top_k = max(1, min(8, top_k))
    results = query(COLLECTION, question, top_k=top_k)
    return format_results(results)


@mcp.tool()
def list_topics() -> str:
    """Liệt kê chủ đề tự nhiên trong kho."""
    from pathlib import Path
    folder = Path("/app/data/tu_nhien")
    if not folder.exists():
        return "Kho tri thức chưa được seed (data/tu_nhien/ trống)."
    files = sorted(folder.glob("*.md"))
    if not files:
        return "Kho tri thức rỗng."
    lines = ["**Chủ đề tự nhiên:**", ""]
    lines.extend(f"- {f.stem}" for f in files)
    return "\n".join(lines)


@mcp.tool()
def get_topic_status() -> str:
    """Kiểm tra Chroma collection tu_nhien."""
    stats = RAGRetriever.get().collection_stats(COLLECTION)
    if not stats.get("available"):
        return "Collection chưa khởi tạo. Chạy: docker exec vn-mcp-hub python -m src.rag.ingest"
    count = stats.get("count", 0)
    if count == 0:
        return "Collection rỗng. Thêm file vào data/tu_nhien/ rồi chạy ingest."
    return f"Collection 'tu_nhien' có {count} chunks."
