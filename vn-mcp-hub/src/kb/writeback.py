"""Answer-time write-back: câu hỏi MISS kho → trả lời từ web NGAY, rồi NỀN tự
tổng hợp kiến thức từ chính câu hỏi đó và nạp vào RAG (+ sync R2).

Khác scheduler (chạy theo lịch, query cố định chung chung): đây bám SÁT câu hỏi
thật của người dùng nên nội dung trúng chủ đề hơn. Có:
- dedup: cùng (kho, câu hỏi) không tổng hợp lại trong _DONE_TTL.
- throttle: tối đa 1 synthesis chạy cùng lúc (codex pool nhẹ tải) — bận thì bỏ qua.
- quality gate: chỉ nạp bản đạt chuẩn (xem src.kb.quality).
Mọi thứ chạy nền (daemon thread) nên KHÔNG làm chậm câu trả lời cho user.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DONE_TTL = 6 * 3600          # 6h: không tổng hợp lại cùng câu hỏi
_MIN_WEB = 3                  # cần >= 3 kết quả web mới đủ để tổng hợp
_done: dict[str, float] = {}
_done_lock = threading.Lock()
_sema = threading.BoundedSemaphore(1)   # tối đa 1 synthesis cùng lúc


def _key(collection: str, question: str) -> str:
    h = hashlib.md5(question.strip().lower().encode("utf-8")).hexdigest()[:12]
    return f"{collection}::{h}"


def maybe_writeback(collection: str, question: str, hybrid_result: dict) -> None:
    """Quyết định (nhanh, không chặn) có nên nạp kiến thức mới cho câu hỏi này."""
    try:
        if not collection or not question or len(question.strip()) < 8:
            return
        rag = hybrid_result.get("rag") or []
        web = hybrid_result.get("web") or []
        if rag:
            return                      # đã có trong kho → khỏi nạp lại
        if len(web) < _MIN_WEB:
            return                      # web quá ít → không đủ tổng hợp tin cậy

        k = _key(collection, question)
        now = time.time()
        with _done_lock:
            for kk, ts in list(_done.items()):
                if now - ts > _DONE_TTL:
                    _done.pop(kk, None)
            if k in _done:
                return
            _done[k] = now

        threading.Thread(target=_run, args=(collection, question, web, k),
                         daemon=True, name="kb-writeback").start()
    except Exception as exc:
        logger.debug("writeback skip: %s", exc)


def _run(collection: str, question: str, web: list, k: str) -> None:
    if not _sema.acquire(blocking=False):
        with _done_lock:
            _done.pop(k, None)          # đang bận → cho phép thử lại lần sau
        logger.info("writeback busy, skip '%s'", question[:50])
        return
    try:
        from src.rag.scheduler import _synthesize_with_ai
        from src.kb.quality import is_good_synthesis
        from src.rag.ingest import chunk_text
        from src.rag.retriever import RAGRetriever

        raw = "\n".join(
            f"Title: {r.get('title','')}\nSnippet: {r.get('snippet','')}\nURL: {r.get('url','')}\n---"
            for r in web[:10] if (r.get("title") or r.get("snippet"))
        )
        if not raw.strip():
            return

        text = _synthesize_with_ai(question, raw)
        ok, reason = is_good_synthesis(text, topic=question)
        if not ok:
            logger.info("writeback rejected (%s) for '%s'", reason, question[:50])
            return

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        final = f"# {question} ({date})\n\n{text}"
        chunks = chunk_text(final)
        if not chunks:
            return

        rt = RAGRetriever.get()
        if not rt._ensure_loaded():
            return
        col = rt._client.get_or_create_collection(
            name=collection, embedding_function=rt._embed_fn
        )
        hid = k.split("::")[-1]
        ids = [f"user_qa::{date}_{hid}::{i}" for i in range(len(chunks))]
        metas = [{"source": f"user_qa/{date}", "chunk": i} for i in range(len(chunks))]
        for i in range(0, len(chunks), 100):
            col.upsert(ids=ids[i:i + 100], documents=chunks[i:i + 100], metadatas=metas[i:i + 100])
        logger.info("writeback OK: %s += %d chunks for '%s'", collection, len(chunks), question[:50])

        try:
            from src.rag.cloud import sync_collection_2way
            sync_collection_2way(collection)
        except Exception as exc:
            logger.debug("writeback R2 sync skip: %s", exc)
    except Exception as exc:
        logger.warning("writeback failed: %s", exc)
    finally:
        _sema.release()
