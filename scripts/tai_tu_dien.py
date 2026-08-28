#!/usr/bin/env python3
"""Tải từ điển Anh–Việt về ``data/tudien/en-vi.db`` cho ô tra cứu ở tab Dịch.

Tệp ~44 MB nên KHÔNG commit vào git (``.gitignore`` đã loại ``*.db``) và cũng
không nằm trong image (``.dockerignore`` loại ``/data``). Chạy script này một
lần trên máy chủ, ghi thẳng vào volume dữ liệu là xong — không phải dựng lại
image, không phải khởi động lại gì.

Trên máy chủ .38 volume thật của container ``c2a`` là ``/opt/c2a/data``::

    python scripts/tai_tu_dien.py --dich /opt/c2a/data/tudien

Nguồn: skypediacode/english-vietnamese-dictionary — dữ liệu CC BY-SA 4.0, xem
``docs/TU_DIEN.md`` để biết phải ghi nguồn thế nào. Kiểm tệp tải về bằng chính
SQLite (đếm số mục) chứ không tin mỗi mã HTTP 200: proxy chặn giữa đường vẫn
trả 200 kèm trang HTML, ghi đè lên từ điển cũ thì mất mà không ai biết.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

NGUON = ("https://raw.githubusercontent.com/skypediacode/"
         "english-vietnamese-dictionary/main/dictionary_en_vi.db")

#: Kho công bố 104.829 mục. Đặt sàn thấp hơn hẳn để bản cập nhật của họ không
#: làm script báo hỏng, nhưng vẫn bắt được tệp cụt hoặc trang HTML lạc vào.
TOI_THIEU_MUC = 50_000


def _dem_muc(tep: Path) -> int:
    """Số mục trong tệp SQLite. ĐÓNG hẳn kết nối rồi dọn tệp bạn (-wal/-shm).

    ``with sqlite3.connect(...)`` KHÔNG đóng kết nối — nó chỉ kết thúc
    transaction. Bỏ qua chuyện này thì tệp tạm để lại ``tmpXXXX.db-wal`` và
    ``-shm`` nằm lại trong thư mục dữ liệu của máy chủ (đã xảy ra thật 28/08).
    """
    db = sqlite3.connect(f"file:{tep}?mode=ro", uri=True)
    try:
        return db.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    finally:
        db.close()
        for phu in (".db-wal", ".db-shm", "-wal", "-shm"):
            Path(str(tep) + phu).unlink(missing_ok=True)


def _tai(url: str, dich: Path) -> None:
    tam = Path(tempfile.mkstemp(suffix=".db", dir=str(dich.parent))[1])
    try:
        print(f"tải {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=300) as resp, tam.open("wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
        n = _dem_muc(tam)
        if n < TOI_THIEU_MUC:
            raise SystemExit(f"tệp tải về chỉ có {n} mục — nghi tải cụt, KHÔNG ghi đè")
        # mkstemp cho 0600; các tệp dữ liệu khác trong volume là 0644 và tiến
        # trình có thể hạ quyền sau này — để nguyên 0600 là gài bẫy cho tương lai.
        tam.chmod(0o644)
        tam.replace(dich)
        print(f"xong: {dich} ({dich.stat().st_size / 1e6:.0f} MB, {n} mục)",
              file=sys.stderr)
    except sqlite3.DatabaseError as exc:
        raise SystemExit(f"tệp tải về không phải SQLite ({exc}) — KHÔNG ghi đè")
    finally:
        tam.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dich", default="data/tudien",
                    help="thư mục đích (mặc định data/tudien)")
    ap.add_argument("--url", default=NGUON, help="nguồn tải, để thay bản khác")
    args = ap.parse_args()
    thu_muc = Path(args.dich)
    thu_muc.mkdir(parents=True, exist_ok=True)
    _tai(args.url, thu_muc / "en-vi.db")


if __name__ == "__main__":
    main()
