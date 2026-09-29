"""Làm sạch + gộp hai bộ gom thành một bộ mẫu thơ cho TTS (``test/data/tho_mau.json``).

Chủ máy 29/09/2026: "thu thập các loại thơ để khi TTS tốt nhất". Gom lại từ đầu (Wikisource
tiếng Việt — nội dung tự do / hết bản quyền):

    cd scripts/tho
    python3 gom_tho.py tho_mau.json 12     # thể cổ điển theo thể loại Wikisource (nhãn = đáp án)
    python3 gom_tho_moi.py                 # thơ mới Nguyễn Bính / Hàn Mặc Tử / Tản Đà → tho_moi.json
    python3 lam_sach_tho.py tho_mau.json tho_moi.json ../../test/data/tho_mau.json

Đo 29/09/2026: ``the_theo_chu`` (đoán thể chỉ bằng đếm chữ mỗi dòng) đúng 76/78 bài có nhãn.

Nhãn thể: bài cổ điển giữ nhãn Wikisource (người soạn ghi — đáp án thật); bài thơ mới xếp theo
số chữ (``nguon_nhan = "dem_chu"``). Mỗi thể tối đa ``TOI_DA`` bài.
"""
import collections
import json
import random
import re
import sys

TOI_DA = 12
am = lambda x: len(re.findall(r"[^\W\d_]+", x))  # noqa: E731


def sach_dong(dong: list[str]) -> list[str]:
    ra = []
    for x in dong:
        x = re.sub(r"^:+\s*", "", x).strip()
        if re.fullmatch(r"[\dIVXLC.\-–—*·•\s]+", x or "0"):   # "1", "II.", "* * *"
            x = "" if x else x
            if ra and ra[-1]:
                ra.append("")
            continue
        ra.append(x)
    # lời đề tặng / chú trong ngoặc ở ĐẦU bài, trước khổ đầu
    while ra and (not ra[0] or re.match(r"^\(.*\)$|^(Tặng|Gửi|Kính tặng|Viếng)\b", ra[0])):
        ra.pop(0)
    gon = []
    for x in ra:
        if x or (gon and gon[-1]):
            gon.append(x)
    while gon and not gon[-1]:
        gon.pop()
    return gon


def the_theo_chu(dong: list[str]) -> str | None:
    co = [x for x in dong if x]
    if len(co) < 4:
        return None
    d = collections.Counter(am(x) for x in co)
    ty = lambda *n: sum(d[k] for k in n) / len(co)  # noqa: E731
    # Lục bát: câu 6 và câu 8 xen nhau — mỗi loại khoảng một nửa.
    if ty(6, 8) >= 0.8 and 0.3 <= ty(6) <= 0.6:
        return "luc_bat"
    if ty(8) >= 0.8:
        return "tam_chu"
    # Khổ 7-7-6-8: câu bảy chiếm khoảng một nửa.
    if ty(7, 6, 8) >= 0.8 and 0.35 <= ty(7) <= 0.65 and d[6] and d[8]:
        return "song_that_luc_bat"
    if ty(7) >= 0.8:
        return "bay_chu_tho_moi"
    if ty(5) >= 0.8:
        return "ngu_ngon"
    if ty(4) >= 0.8:
        return "bon_chu"
    if max(d.values()) / len(co) < 0.5:
        return "tu_do"
    return None


co_dien = json.load(open(sys.argv[1]))
moi = json.load(open(sys.argv[2]))
ra, da = [], set()
for b in co_dien:
    b = {**b, "dong": sach_dong(b["dong"]), "nguon_nhan": "wikisource"}
    if sum(1 for x in b["dong"] if x) >= 2 and b["ten"] not in da:
        ra.append(b)
        da.add(b["ten"])
random.seed(29092026)
random.shuffle(moi)
dem = collections.Counter(b["the"] for b in ra)
for b in moi:
    dong = sach_dong(b["dong"])
    the = the_theo_chu(dong)
    if not the or b["ten"] in da or dem[the] >= TOI_DA:
        continue
    ra.append({**b, "the": the, "dong": dong, "nguon_nhan": "dem_chu"})
    da.add(b["ten"])
    dem[the] += 1
json.dump(ra, open(sys.argv[3], "w"), ensure_ascii=False, indent=1)
print(sorted(collections.Counter(b["the"] for b in ra).items()), len(ra), "bai")
