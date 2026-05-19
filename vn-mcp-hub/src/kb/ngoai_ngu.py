"""kb_ngoai_ngu — kho tri thức học ngoại ngữ.

RAG-backed: Chroma collection 'ngoai_ngu' (data/ngoai_ngu/*.md).
Phục vụ tra cứu ngữ pháp, từ vựng, mẹo học tiếng Anh / Trung / Nhật / Hàn.
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.rag.retriever import RAGRetriever, format_results, query

mcp = FastMCP("kb_ngoai_ngu")

COLLECTION = "ngoai_ngu"


@mcp.tool()
def ask_ngoai_ngu(question: str, top_k: int = 4) -> str:
    """Hỏi đáp về học ngoại ngữ: ngữ pháp, từ vựng, mẹo học.

    Args:
        question: Câu hỏi tiếng Việt (vd: "thì hiện tại hoàn thành dùng khi nào",
                  "phân biệt 是 và 在 trong tiếng Trung", "から và ので").
        top_k: Số đoạn tài liệu liên quan trả về (1-8, mặc định 4).

    Returns:
        Các đoạn tài liệu phù hợp nhất từ kho tri thức.
    """
    top_k = max(1, min(8, top_k))
    results = query(COLLECTION, question, top_k=top_k)
    return format_results(results)


@mcp.tool()
def list_topics() -> str:
    """Liệt kê chủ đề ngoại ngữ trong kho."""
    from pathlib import Path
    folder = Path("/app/data/ngoai_ngu")
    if not folder.exists():
        return "Kho tri thức chưa được seed (data/ngoai_ngu/ trống)."
    files = sorted(folder.glob("*.md"))
    if not files:
        return "Kho tri thức rỗng."
    lines = ["**Chủ đề ngoại ngữ:**", ""]
    lines.extend(f"- {f.stem}" for f in files)
    return "\n".join(lines)


@mcp.tool()
def get_topic_status() -> str:
    """Kiểm tra Chroma collection ngoai_ngu."""
    stats = RAGRetriever.get().collection_stats(COLLECTION)
    if not stats.get("available"):
        return "Collection chưa khởi tạo. Chạy: docker exec vn-mcp-hub python -m src.rag.ingest"
    count = stats.get("count", 0)
    if count == 0:
        return "Collection rỗng. Thêm file vào data/ngoai_ngu/ rồi chạy ingest."
    return f"Collection 'ngoai_ngu' có {count} chunks."
