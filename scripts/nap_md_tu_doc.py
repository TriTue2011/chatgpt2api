"""Nạp MỘT tài liệu từ markdown ĐÃ ĐỌC SẴN (đọc ở máy ngoài, không OCR trên sv).

Vì sao tồn tại: người vận hành chốt "bạn làm trực tiếp lấy dữ liệu, không dùng
sv của tôi" — phần đọc trang (vision) chạy ở máy ngoài, server chỉ nhận kết quả.
Đường `import_reader` sẵn có luôn OCR bằng model của server nên không dùng được
cho việc này.

GHI ĐÈ theo yêu cầu "taphuan làm chuẩn, ghi đè nếu đang có": xoá hết đoạn cũ của
CHÍNH source này trước khi nạp — chạy lại bao nhiêu lần cũng ra đúng một bản.

Vào: JSON trên stdin {
  md, grade, subject, kind, volume, label, source (reader_url),
  page_urls: [url ảnh từng trang, đúng thứ tự]   # để "giảng tới đâu lật trang tới đó"
}
Ra: JSON {ok, chunks_added, collection, da_xoa, manifest}
"""
import json
import sys

import os
sys.path.insert(0, os.environ.get("C2A_APP_DIR", "/app"))

import chromadb  # noqa: E402

from services.agent import sgk_fetch as sf  # noqa: E402
from services.agent import sgk_taphuan as tp  # noqa: E402
from services.agent import teacher_workspace as tw  # noqa: E402

d = json.load(sys.stdin)
md = str(d["md"])
g = int(d["grade"])
sub = str(d["subject"])
kind = str(d.get("kind") or "sgk")
vol = str(d.get("volume") or "")
label = str(d.get("label") or "")
source = str(d["source"])
page_urls = list(d.get("page_urls") or [])

col_name = sf.KIND_COLLECTION.get(kind, "kb_giao_duc")

# 1) GHI ĐÈ: xoá đoạn cũ của đúng source này (mọi biến thể source chứa URL).
da_xoa = 0
try:
    cl = chromadb.PersistentClient(path="/app/data/chroma_db")
    col = cl.get_collection(col_name)
    dd = col.get(include=["metadatas"], limit=60000)
    # Khớp theo SLUG TÀI LIỆU (đuôi URL, có ID số) chứ không theo URL đầy đủ:
    # các lần nạp khác nhau ghi `source` khác nhau — đường bulk cũ ghi
    # `teacher_sgk/lop1/toan/<slug>`, đường này ghi `teacher_sgk/.../https://...`.
    # So bằng URL đầy đủ thì không xoá được bản cũ → đo thật 30/07: 4 tài liệu
    # lớp 1 bị TRÙNG ĐÔI (bản slug + bản URL) ngay sau lượt "ghi đè" đầu tiên.
    slug_tl = source.rstrip("/").rsplit("/", 1)[-1]
    bo = [i for i, m in zip(dd["ids"], dd["metadatas"])
          if slug_tl and slug_tl in str((m or {}).get("source") or "")]
    for i in range(0, len(bo), 200):
        col.delete(ids=bo[i:i + 200])
    da_xoa = len(bo)
except Exception:
    pass

# 2) Nạp qua ĐÚNG đường đã soát (push_sgk_to_rag → hub curate, metadata đầy đủ).
rag = tw.push_sgk_to_rag(md, title=label, grade=g, subject=sub,
                         source=source, collection=col_name,
                         volume=vol, kind=kind)

# 3) Bản đồ trang → ảnh, để bài giảng lật được trang. Chỉ URL, không tải gì.
mf = {}
if page_urls:
    try:
        tp.save_page_manifest(source, page_urls, grade=g, subject=sub,
                              kind=kind, book_set="", label=label)
        mf = {"pages": len(page_urls)}
    except Exception as exc:
        mf = {"error": str(exc)[:120]}

# 4) Mục lục cho dropdown chọn bài (chỉ sách học sinh; các loại khác không có
#    mục lục dạng đó).
toc_n = 0
if kind == "sgk":
    try:
        from services.agent import teacher_lecture as tl
        rows = tl.toc_tu_markdown(md, tap=vol)
        if rows:
            toc_n = tl.save_toc(g, sub, rows)
    except Exception:
        pass

print(json.dumps({"ok": bool(rag.get("ok")), "chunks_added": rag.get("chunks_added"),
                  "collection": col_name, "da_xoa": da_xoa, "errors": rag.get("errors"),
                  "manifest": mf, "toc": toc_n}, ensure_ascii=False))
