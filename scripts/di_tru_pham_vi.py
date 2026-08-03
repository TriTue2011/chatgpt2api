#!/usr/bin/env python3
"""Di trú dữ liệu CŨ (toàn cục) sang PHẠM VI — wiki notes + MEMORY.md.

Vì sao cần: từ 26010fb, trí nhớ và wiki tách theo phạm vi (kênh / chat / topic /
người — xem services/agent/scope.py). Dữ liệu tạo TRƯỚC đó không có phạm vi, nên
nó vẫn hiện ở MỌI phạm vi. Đó là lối tương thích cố ý, không phải quên: ẩn chúng
đi là im lặng làm mất wiki và trí nhớ đang dùng. Script này gán phạm vi cho
chúng, để chốt tách được áp cho cả dữ liệu cũ.

PHẠM VI SUY TỪ ĐÂU
Cả hai kho đều đã ghi sẵn NGUỒN của từng bản ghi:
  * wiki note   — frontmatter `who` chính là khoá phiên orchestrator (và
                  `platform` + `chat_id` là đường lùi khi thiếu `who`);
  * MEMORY.md   — mỗi dòng có dạng `- [thời gian] (who) nội dung`.
Đưa `who` qua `scope.khoa_du_lieu()` là ra đúng phạm vi mà lượt đó thuộc về —
không đoán, không hỏi.

Bản ghi KHÔNG có nguồn thì GIỮ NGUYÊN ở kho chung. Đoán bừa một phạm vi cho nó
là hai kiểu hỏng: gán nhầm cho người này thì người kia mất dữ liệu.

CHẠY
    python scripts/di_tru_pham_vi.py            # xem trước, KHÔNG ghi gì
    python scripts/di_tru_pham_vi.py --thuc-hien

Trong container:
    docker exec -it <ten-container> python scripts/di_tru_pham_vi.py
    docker exec -it <ten-container> python scripts/di_tru_pham_vi.py --thuc-hien

An toàn: xem trước là mặc định; `--thuc-hien` sao lưu trước khi ghi; chạy lại
nhiều lần không nhân bản (bản ghi đã có phạm vi thì bỏ qua).

KHÔNG đụng tới `memory.sqlite` (kho của MemoryService): các bản ghi ở đó nằm
dưới `user_id='chatgpt2api'` — chính là kho mặc định mà admin và đường nội bộ
vẫn dùng sau khi sửa, nên chúng không mất đường về, không cần di trú.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agent import scope as _scope           # noqa: E402
from services.agent.skills import split_frontmatter  # noqa: E402

# `- [2026-08-04 07:00] (zalo_123:u456) nội dung…`
_DONG_TRI_NHO = re.compile(r"^\s*-\s*\[[^\]]*\]\s*\((?P<who>[^)]+)\)")


def khoa_phien_cua_note(fm: dict[str, str]) -> str:
    """Khoá phiên của một note wiki, từ frontmatter.

    `who` là khoá phiên nguyên bản (wiki.ingest ghi thẳng ctx['user_id']). Thiếu
    nó thì dựng lại từ `platform` + `chat_id` theo đúng quy ước các adapter dùng.
    """
    who = str(fm.get("who") or "").strip()
    if who:
        return who
    plat = str(fm.get("platform") or "").strip().lower()
    cid = str(fm.get("chat_id") or "").strip()
    if not cid:
        return ""
    if plat == "zalop":
        return f"zalop_{cid}"
    if plat == "zalo":
        return f"zalo_{cid}"
    if plat == "tg":
        return cid
    return ""


def _chen_scope(raw: str, pham_vi: str) -> str:
    """Chèn `scope: …` vào frontmatter sẵn có, giữ nguyên phần còn lại.

    Ghi lại cả file bằng _build_frontmatter sẽ làm mất mọi khoá lạ mà bản cũ có
    — chèn một dòng thì không đụng tới thứ mình không hiểu.
    """
    dong = raw.splitlines(keepends=True)
    if not dong or not dong[0].startswith("---"):
        return raw
    for i in range(1, len(dong)):
        if dong[i].startswith("---"):
            return "".join(dong[:i]) + f"scope: {pham_vi}\n" + "".join(dong[i:])
    return raw


def quet_wiki(goc: Path) -> list[dict[str, Any]]:
    """Các note chưa có phạm vi → [{path, who, pham_vi, ly_do}]."""
    thu_muc = goc / "agent" / "wiki" / "notes"
    ra: list[dict[str, Any]] = []
    if not thu_muc.is_dir():
        return ra
    for p in sorted(thu_muc.glob("*.md")):
        try:
            raw = p.read_text("utf-8", errors="replace")
        except OSError as exc:
            ra.append({"path": p, "ly_do": f"đọc lỗi: {exc}"})
            continue
        fm, _ = split_frontmatter(raw)
        if str(fm.get("scope") or "").strip():
            continue                       # đã di trú rồi
        who = khoa_phien_cua_note(fm)
        if not who:
            ra.append({"path": p, "who": "", "ly_do": "không rõ nguồn"})
            continue
        ra.append({"path": p, "who": who, "pham_vi": _scope.khoa_du_lieu(who),
                   "raw": raw})
    return ra


def quet_tri_nho(goc: Path) -> dict[str, Any]:
    """MEMORY.md chung → dòng nào về phạm vi nào."""
    tep = goc / "agent" / "MEMORY.md"
    ket: dict[str, Any] = {"tep": tep, "theo_pham_vi": {}, "giu_lai": [],
                           "tong": 0}
    if not tep.is_file():
        return ket
    for dong in tep.read_text("utf-8", errors="replace").splitlines():
        if not dong.strip():
            continue
        ket["tong"] += 1
        m = _DONG_TRI_NHO.match(dong)
        who = (m.group("who").strip() if m else "")
        # `who` của wiki là 'wiki' chứ không phải khoá phiên — không suy ra được
        # phạm vi, giữ ở kho chung.
        if not who or who == "wiki":
            ket["giu_lai"].append(dong)
            continue
        pv = _scope.khoa_du_lieu(who)
        ket["theo_pham_vi"].setdefault(pv, []).append(dong)
    return ket


def gan_duong_state(goc: Path) -> None:
    """Trỏ `state` vào ĐÚNG thư mục dữ liệu đang di trú.

    `state` giữ đường dẫn ở hằng số cấp module, tính từ DATA_DIR lúc import. Nếu
    không gán lại, `--data-dir` chỉ đổi chỗ ĐỌC còn chỗ GHI vẫn là thư mục dữ
    liệu thật — đã xảy ra thật lúc thử: quét thư mục tạm nhưng dòng trí nhớ bay
    thẳng vào data/agent/memory của app.
    """
    from services.agent import state
    state._MEMORY_FILE = goc / "agent" / "MEMORY.md"
    state._MEMORY_DB_PATH = goc / "agent" / "memory_fts.sqlite"
    state._MEMORY_SCOPE_DIR = goc / "agent" / "memory"
    state._MEMORY_SCOPE_DIR.mkdir(parents=True, exist_ok=True)
    state._mem_conn = {}


def _sao_luu(duong: Path, dau: str) -> Path:
    bansao = duong.with_name(f"{duong.name}.truoc-di-tru-{dau}")
    shutil.copy2(duong, bansao)
    return bansao


def chay(goc: Path, thuc_hien: bool) -> int:
    dau = time.strftime("%Y%m%d-%H%M%S")
    gan_duong_state(goc)
    print(f"Thư mục dữ liệu: {goc}")
    print(f"Chế độ: {'THỰC HIỆN (có ghi)' if thuc_hien else 'XEM TRƯỚC (không ghi gì)'}\n")

    # ── wiki ────────────────────────────────────────────────────────────────
    notes = quet_wiki(goc)
    can_sua = [n for n in notes if n.get("pham_vi")]
    bo_qua = [n for n in notes if not n.get("pham_vi")]
    print(f"WIKI — {len(can_sua)} ghi chú gán được phạm vi, "
          f"{len(bo_qua)} giữ ở kho chung (không rõ nguồn)")
    theo_pv: dict[str, int] = {}
    for n in can_sua:
        theo_pv[n["pham_vi"]] = theo_pv.get(n["pham_vi"], 0) + 1
    for pv, n in sorted(theo_pv.items(), key=lambda x: -x[1]):
        print(f"    {n:4d} ghi chú → {pv}")
    for n in bo_qua[:5]:
        print(f"    giữ lại: {n['path'].name} ({n.get('ly_do')})")

    if thuc_hien:
        for n in can_sua:
            _sao_luu(n["path"], dau)
            n["path"].write_text(_chen_scope(n["raw"], n["pham_vi"]), "utf-8")
        print(f"    → đã ghi {len(can_sua)} ghi chú (bản sao .truoc-di-tru-{dau})")

    # ── trí nhớ ─────────────────────────────────────────────────────────────
    tn = quet_tri_nho(goc)
    so_chuyen = sum(len(v) for v in tn["theo_pham_vi"].values())
    print(f"\nTRÍ NHỚ — {tn['tong']} dòng trong MEMORY.md chung: "
          f"{so_chuyen} dòng chuyển đi, {len(tn['giu_lai'])} dòng giữ lại")
    for pv, ds in sorted(tn["theo_pham_vi"].items(), key=lambda x: -len(x[1])):
        print(f"    {len(ds):4d} dòng → {pv}")

    if thuc_hien and so_chuyen:
        from services.agent import state
        _sao_luu(tn["tep"], dau)
        for pv, ds in tn["theo_pham_vi"].items():
            dich = state._memory_file(pv)
            dich.parent.mkdir(parents=True, exist_ok=True)
            with dich.open("a", encoding="utf-8") as f:
                for d in ds:
                    f.write(d + "\n")
            state._rebuild_memory_index(pv)
        con = tn["giu_lai"]
        tn["tep"].write_text("\n".join(con) + ("\n" if con else ""), "utf-8")
        state._rebuild_memory_index("")
        print(f"    → đã chuyển {so_chuyen} dòng, dựng lại index FTS "
              f"(bản sao .truoc-di-tru-{dau})")

    if not thuc_hien:
        print("\nChưa ghi gì. Chạy lại với --thuc-hien để áp dụng.")
    return 0


def main() -> int:
    from services.config import DATA_DIR
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--thuc-hien", action="store_true",
                    help="ghi thật (mặc định chỉ xem trước)")
    ap.add_argument("--data-dir", default=str(DATA_DIR),
                    help="thư mục dữ liệu (mặc định: DATA_DIR của app)")
    a = ap.parse_args()
    return chay(Path(a.data_dir), a.thuc_hien)


if __name__ == "__main__":
    raise SystemExit(main())
