#!/usr/bin/env python3
"""Đo chi phí token MỖI LƯỢT CHAT của bot: system prompt, schema tool, kho skill.

Vì sao cần script này (bài học đo thật 29/08/2026): tối ưu prompt bằng cảm tính
là tối ưu nhầm chỗ. Lần đo đầu cho thấy phần chỉ dẫn trong system prompt khoảng
5.300 token, nghe thì to — nhưng **schema tool là 17.300 token**, gấp hơn ba
lần, và trước đó gửi nguyên 74 tool ở MỌI lượt bất kể lượt đó làm gì. Không có
số liệu thì không ai đoán ra điều đó.

Chạy::

    python scripts/do_context.py                  # bảng theo từng loại việc
    python scripts/do_context.py --chi-tiet       # tách từng khối trong prompt
    python scripts/do_context.py --trung-lap      # soi trùng lặp / xung đột
    python scripts/do_context.py --cache          # tiền tố dùng lại được

Chạy `--trung-lap` sau mỗi lần thêm nhóm việc hay đổi từ khoá: chính nó bắt được
"nhắc anh 7h sáng mai" bị nhận nhầm là việc NHẠC (bỏ dấu thì "nhắc" = "nhac").

Con số là ƯỚC LƯỢNG (≈3 ký tự/token cho tiếng Việt có dấu), đủ để so sánh giữa
các phương án và bắt hồi quy; đừng dùng làm hoá đơn.

Không gọi mạng, không đụng dữ liệu thật: script chỉ lắp prompt trong tiến trình
rồi đếm.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
if str(GOC) not in sys.path:
    sys.path.insert(0, str(GOC))

# Cấu hình bắt buộc auth-key mới import được services.config — script chỉ đọc và
# đếm nên đặt khoá giả là đủ, miễn không ghi đè khoá thật của máy đang chạy.
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "do-context-chi-de-doc-0000")

#: Ký tự trên một token — tiếng Việt có dấu tốn hơn tiếng Anh. Chỉ để so sánh.
KY_TU_MOT_TOKEN = 3

#: Các loại việc đại diện, phủ những nhánh người dùng chạm nhiều nhất.
CA_VIEC: list[tuple[str, str]] = [
    ("Tán gẫu / chào hỏi", "chào em, hôm nay khoẻ không"),
    ("Nhà thông minh", "bật đèn phòng khách giúp anh"),
    ("Tin tức", "tin tức hôm nay"),
    ("Vẽ ảnh", "vẽ cho anh con mèo dễ thương"),
    ("Đặt lịch nhắc", "nhắc anh 7h sáng mai uống thuốc"),
    ("Dạy học", "ra bài tập lớp 4 môn toán"),
    ("Tài liệu Office", "tạo báo cáo excel cho anh"),
    ("Phát loa", "phát ra loa phòng khách câu chào"),
]


def tok(s: str) -> int:
    return len(s or "") // KY_TU_MOT_TOKEN


def _nap():
    from services.agent import capabilities as caps
    from services.agent import orchestrator as orch
    return caps, orch


def bang_theo_viec() -> None:
    """Bảng chính: mỗi loại việc tốn bao nhiêu, so với bản không lọc."""
    caps, orch = _nap()

    def do(txt: str) -> tuple[int, int, int, int]:
        nhom = orch._nhom_ngu_canh(txt, [], None)
        p = tok(orch._build_system_prompt("do_context", None, txt))
        sch = caps.tools_schema(None, nhom)
        t = tok(json.dumps(sch, ensure_ascii=False))
        return p, t, len(sch), p + t

    goc_prompt = tok(orch._build_system_prompt("do_context", None, " ".join(
        c for _t, c in CA_VIEC)))
    goc_sch = caps.tools_schema(None)
    goc = goc_prompt + tok(json.dumps(goc_sch, ensure_ascii=False))

    print(f"{'Loại việc':22s} {'prompt':>7s} {'schema':>7s} {'tool':>5s} "
          f"{'TỔNG':>7s}  {'so với không lọc':>17s}")
    print("-" * 76)
    for ten, cau in CA_VIEC:
        p, t, n, tong = do(cau)
        print(f"{ten:22s} {p:7d} {t:7d} {n:5d} {tong:7d}  "
              f"{'-' + str(100 - tong * 100 // goc) + '%':>17s}")
    print("-" * 76)
    print(f"{'KHÔNG LỌC (mọi nhánh)':22s} {goc_prompt:7d} "
          f"{tok(json.dumps(goc_sch, ensure_ascii=False)):7d} "
          f"{len(goc_sch):5d} {goc:7d}")


def chi_tiet_khoi() -> None:
    """Tách từng khối trong system prompt — tìm khối nào đáng gác tiếp."""
    caps, orch = _nap()
    from services.agent import skills as sk
    from services.agent import state
    from services.agent import workflows as wf

    khoi = [
        ("soul (persona gốc)", state.load_soul()),
        ("persona_list (mục lục năng lực)", caps.persona_list(None)),
        ("skills router — nạp hết", sk.router_block(None)),
        ("skills router — lượt tán gẫu", sk.router_block(set())),
        ("workflows router", wf.router_block()),
        ("environment (bản đồ hệ thống)", state.load_environment()),
    ]
    print(f"{'Khối':38s} {'ký tự':>7s} {'~token':>7s}")
    print("-" * 56)
    for ten, txt in khoi:
        print(f"{ten:38s} {len(txt or ''):7d} {tok(txt):7d}")

    print("\nSchema tool nặng nhất (nạp cả gói thì gánh đủ):")
    nang = sorted(
        ((tok(json.dumps(t, ensure_ascii=False)), t["function"]["name"])
         for t in caps.tools_schema(None)), reverse=True)
    for n, ten in nang[:10]:
        print(f"   {ten:26s} {n:6d} token")


def soi_trung_lap() -> None:
    """Trùng lặp / xung đột — thứ âm thầm ăn token mà không ai để ý."""
    caps, orch = _nap()

    print("① Tool CHƯA có dòng chỉ đường nào")
    noi: dict[str, str] = {}
    for g, _rx, text in orch._BANG_CHI_DUONG:
        noi[g] = noi.get(g, "") + " " + text
    duoi = orch._bang_chi_duong(None, "tin tức hôm nay")   # phần đuôi luôn có
    thieu = [f"{g}/{t}" for t, g in caps._CAP_GROUP.items()
             if t not in noi.get(g, "") and t not in duoi]
    print("   " + (", ".join(sorted(thieu)) if thieu else "(không còn — phủ đủ)"))

    print("\n② Nhánh trỏ nhóm không tồn tại")
    ma = {g for g, _, _ in orch._BANG_CHI_DUONG} - set(caps._CAP_GROUP.values())
    print("   " + (", ".join(sorted(ma)) if ma else "(không có)"))

    print("\n③ Một câu chạm NHIỀU nhóm (dò rộng quá thì tốn oan)")
    for ten, cau in CA_VIEC:
        nhom = orch._nhom_viec(cau, None)
        if len(nhom) > 1:
            print(f"   «{cau}» → {sorted(nhom)}")

    print("\n④ Câu KHÔNG chạm nhóm nào (dò hẹp quá thì model thiếu tool)")
    for ten, cau in CA_VIEC:
        if not orch._nhom_viec(cau, None):
            print(f"   «{cau}» → (rỗng — chỉ còn tool lõi + thông dụng)")

    print("\n⑤ Tool lõi luôn gửi kèm mọi lượt")
    luon = sorted(caps._CORE_TOOLS | caps._TOOL_THONG_DUNG)
    gia = tok(json.dumps(
        [t for t in caps.tools_schema(None) if t["function"]["name"] in luon],
        ensure_ascii=False))
    print(f"   {', '.join(luon)}  → {gia} token/lượt")


def do_cache() -> None:
    """Tiền tố dùng lại được — quyết định bộ nhớ đệm prompt ăn được bao nhiêu.

    Cache của nhà cung cấp chỉ khớp phần ĐẦU giống hệt nhau, nên thứ gì đổi
    nhanh mà nằm sớm là cắt cụt toàn bộ phía sau. Đo 29/08: dòng đồng hồ (đổi
    mỗi phút) từng nằm ở vị trí thứ hai và làm tiền tố chỉ còn 30%.
    """
    from unittest import mock
    _caps, orch = _nap()

    def chung(a: str, b: str) -> int:
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        return n

    def voi_gio(phut: str, txt: str) -> str:
        gio = (f"Bây giờ là 08:{phut}, thứ Sáu, ngày 29 tháng 8 năm 2026 "
               f"(giờ Việt Nam).")
        with mock.patch.object(orch, "_now_line", lambda: gio):
            return orch._build_system_prompt("do_context", None, txt)

    print("Tiền tố dùng lại được giữa hai lượt (càng cao càng rẻ):\n")
    a, b = voi_gio("15", "tin tức hôm nay"), voi_gio("16", "tin tức hôm nay")
    n = chung(a, b)
    print(f"  cùng việc, cách nhau 1 phút : {n:6d}/{len(a):6d} ch  {n*100//len(a):3d}%")
    c, d = voi_gio("15", "tin tức hôm nay"), voi_gio("15", "vẽ con mèo")
    m = chung(c, d)
    it = min(len(c), len(d))
    print(f"  khác việc, cùng một phút    : {m:6d}/{it:6d} ch  {m*100//it:3d}%")
    print("\n  (thấp bất thường → có thứ đổi nhanh bị đặt quá sớm trong prompt)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chi-tiet", action="store_true",
                    help="tách từng khối trong system prompt")
    ap.add_argument("--trung-lap", action="store_true",
                    help="soi trùng lặp, tool thiếu chỉ đường, dò quá rộng/hẹp")
    ap.add_argument("--cache", action="store_true",
                    help="đo tiền tố dùng lại được (bộ nhớ đệm prompt)")
    ns = ap.parse_args()

    if ns.chi_tiet:
        chi_tiet_khoi()
    elif ns.trung_lap:
        soi_trung_lap()
    elif ns.cache:
        do_cache()
    else:
        bang_theo_viec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
