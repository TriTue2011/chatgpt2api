"""Cho bot giải BỘ ĐỀ LUYỆN của một hướng dẫn học rồi chấm — sửa hướng dẫn xong chạy lại cả bộ.

    docker exec -w /app c2a /app/.venv/bin/python scripts/luyen_huong_dan.py chon_co_nguoi --lan 2
    … --huong /tmp/ban_thu.md      # thử bản hướng dẫn chưa đưa lên
    … --de nha_tam_khong_camera    # chỉ một đề

Không ghi sổ nào, chỉ gọi model. Xem `services/de_luyen/__init__.py` cho khuôn đáp án.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    ten = argv[0]
    lan = int(argv[argv.index("--lan") + 1]) if "--lan" in argv else 1
    chi = [argv[i + 1] for i, a in enumerate(argv) if a == "--de"]
    from services import de_luyen, hieu_thiet_bi_nha as ht
    huong = (Path(argv[argv.index("--huong") + 1]).read_text(encoding="utf-8") if "--huong" in argv
             else ht.huong_dan(ten)[0])
    ra = de_luyen.luyen(ten, huong, lan=lan, chi=chi or None)
    dung = sum(1 for x in ra if not x["loi"])
    for x in ra:
        print(("✓" if not x["loi"] else "✗"), x["de"], f"#{x['lan']}", "; ".join(x["loi"]))
        if x["loi"] and x["vi_sao"]:
            print("    bot nói:", x["vi_sao"][:300])
    print(f"ĐÚNG {dung}/{len(ra)}")
    return 0 if dung == len(ra) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
