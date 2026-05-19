"""kb_dien_nuoc — kho tri thức kỹ thuật điện, nước, điều hòa, chiller.

RAG-backed: query Chroma collection 'dien_nuoc' (ingested from
data/dien_nuoc/*.md). Để cập nhật knowledge: thêm/sửa file .md trong folder
data/dien_nuoc/, rồi chạy `docker exec vn-mcp-hub python -m src.rag.ingest`.

Tools:
- ask_dien_nuoc(question): hỏi tự do, RAG retrieve top-k chunks
- list_topics(): liệt kê chủ đề trong kho (theo tên file)
- get_topic_status(): kiểm tra Chroma collection có sẵn sàng không
"""

from __future__ import annotations

from fastmcp import FastMCP

from src.rag.retriever import RAGRetriever
from src.rag.hybrid import hybrid_query, format_hybrid_results

mcp = FastMCP("kb_dien_nuoc")

COLLECTION = "dien_nuoc"


@mcp.tool()
def ask_dien_nuoc(question: str, top_k: int = 4) -> str:
    """Hỏi đáp về kỹ thuật điện, nước, điều hòa, chiller.

    Args:
        question: Câu hỏi tiếng Việt (vd: "MCB là gì",
                  "cách tính tải điều hòa", "công suất chiller").
        top_k: Số đoạn tài liệu liên quan trả về (1-8, mặc định 4).

    Returns:
        Các đoạn tài liệu phù hợp nhất từ kho tri thức.
    """
    top_k = max(1, min(8, top_k))
    results = hybrid_query(COLLECTION, question, top_k=top_k)
    return format_hybrid_results(results)


@mcp.tool()
def list_topics() -> str:
    """Liệt kê các chủ đề trong kho tri thức điện/nước/điều hòa/chiller.

    Returns:
        Danh sách file markdown nguồn (mỗi file = 1 chủ đề).
    """
    from pathlib import Path
    folder = Path("/app/data/dien_nuoc")
    if not folder.exists():
        return "Kho tri thức chưa được seed (data/dien_nuoc/ trống)."
    files = sorted(folder.glob("*.md"))
    if not files:
        return "Kho tri thức rỗng."
    lines = ["**Chủ đề trong kho điện/nước/điều hòa/chiller:**", ""]
    lines.extend(f"- {f.stem}" for f in files)
    return "\n".join(lines)


@mcp.tool()
def get_topic_status() -> str:
    """Kiểm tra Chroma collection có sẵn dữ liệu hay chưa.

    Returns:
        Số chunks đã được ingest, hoặc gợi ý chạy ingest nếu chưa có.
    """
    stats = RAGRetriever.get().collection_stats(COLLECTION)
    if not stats.get("available"):
        return "Collection chưa khởi tạo. Chạy: docker exec vn-mcp-hub python -m src.rag.ingest"
    count = stats.get("count", 0)
    if count == 0:
        return "Collection rỗng. Thêm file vào data/dien_nuoc/ rồi chạy ingest."
    return f"Collection 'dien_nuoc' có {count} chunks."
