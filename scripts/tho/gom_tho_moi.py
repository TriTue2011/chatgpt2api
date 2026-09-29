"""Thơ mới / tự do từ tác giả đã hết bản quyền: phân loại theo số chữ phổ biến mỗi dòng."""
import json, re, sys, time, collections
sys.argv = [sys.argv[0], "x"]
import gom_tho as g
ra = []
for tg in ("Nguyễn Bính", "Hàn Mặc Tử", "Tản Đà"):
    kq = g.goi(action="query", list="search", srsearch=f'"{tg}" insource:"<poem>"', srlimit=80, srnamespace=0)
    ds = [x["title"] for x in kq.get("query", {}).get("search", [])]
    for t in ds:
        w = g.raw(t)
        if f"= {tg}" not in w and f"={tg}" not in w:
            continue
        khoi = [[re.sub(r"\s+", " ", x).strip() for x in g.sach(m).split("\n")] for m in re.findall(r"<poem>(.*?)</poem>", w, re.S)]
        khoi = [k for k in khoi if not any(re.search(r"[㐀-鿿]", x) for x in k)]
        if not khoi:
            continue
        dong = [x for x in khoi[0]]
        co = [x for x in dong if x]
        if len(co) < 4:
            continue
        dem = collections.Counter(g._am(x) for x in co)
        so, n = dem.most_common(1)[0]
        ty = n / len(co)
        if so == 8 and ty >= 0.8: the = "tam_chu"
        elif so == 7 and ty >= 0.8 and not ({6, 8} & set(dem)): the = "bay_chu_tho_moi"
        elif ty < 0.5 and len(dem) >= 4: the = "tu_do"
        else: continue
        gon = []
        for x in dong:
            if x or (gon and gon[-1]): gon.append(x)
        gon = gon[:g.TOI_DA_DONG]
        while gon and not gon[-1]: gon.pop()
        ra.append({"ten": t, "tac_gia": tg, "the": the, "nguon": "https://vi.wikisource.org/wiki/" + g.urllib.parse.quote(t.replace(" ", "_")), "dong": gon})
        time.sleep(0.3)
json.dump(ra, open("tho_moi.json", "w"), ensure_ascii=False, indent=1)
print(collections.Counter(b["the"] for b in ra), file=sys.stderr)
