"""kb_giao_duc — kho tri thức giáo dục Việt Nam.

RAG-backed: Chroma collection 'giao_duc' (data/giao_duc/*.md).
Phục vụ tra cứu chương trình giáo dục, phương pháp học, kỹ năng.
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.rag.retriever import RAGRetriever
from src.rag.hybrid import hybrid_query, format_hybrid_results

mcp = FastMCP("kb_giao_duc")

COLLECTION = "giao_duc"


@mcp.tool()
def ask_giao_duc(question: str, top_k: int = 4) -> str:
    """Hỏi đáp về giáo dục: chương trình, phương pháp, kỹ năng học.

    Args:
        question: Câu hỏi tiếng Việt (vd: "phương pháp Pomodoro",
                  "chương trình giáo dục phổ thông 2018", "thi tốt nghiệp THPT").
        top_k: Số đoạn tài liệu liên quan trả về (1-8, mặc định 4).

    Returns:
        Các đoạn tài liệu phù hợp nhất từ kho tri thức.
    """
    top_k = max(1, min(8, top_k))
    results = hybrid_query(COLLECTION, question, top_k=top_k)
    return format_hybrid_results(results)


@mcp.tool()
def list_topics() -> str:
    """Liệt kê chủ đề giáo dục trong kho."""
    from pathlib import Path
    folder = Path("/app/data/giao_duc")
    if not folder.exists():
        return "Kho tri thức chưa được seed (data/giao_duc/ trống)."
    files = sorted(folder.glob("*.md"))
    if not files:
        return "Kho tri thức rỗng."
    lines = ["**Chủ đề giáo dục:**", ""]
    lines.extend(f"- {f.stem}" for f in files)
    return "\n".join(lines)


@mcp.tool()
def get_topic_status() -> str:
    """Kiểm tra Chroma collection giao_duc."""
    stats = RAGRetriever.get().collection_stats(COLLECTION)
    if not stats.get("available"):
        return "Collection chưa khởi tạo. Chạy: docker exec vn-mcp-hub python -m src.rag.ingest"
    count = stats.get("count", 0)
    if count == 0:
        return "Collection rỗng. Thêm file vào data/giao_duc/ rồi chạy ingest."
    return f"Collection 'giao_duc' có {count} chunks."
