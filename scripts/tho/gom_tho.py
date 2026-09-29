"""Gom bài thơ mẫu theo thể từ Wikisource tiếng Việt (nội dung tự do / hết bản quyền).

Mỗi thể lấy tối đa N bài có thẻ <poem>, bỏ chú thích <ref>, giữ bản chính của {{khác|chính|phụ}}.
Ra JSON: [{ten, tac_gia, the, nguon, dong: [...]}] — dòng trống = hết khổ.
"""
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://vi.wikisource.org/w/api.php"
UA = {"User-Agent": "c2a-tho/1.0 (bo do TTS; lien he chu repo)"}
THE = {"Lục bát": "luc_bat", "Song thất lục bát": "song_that_luc_bat",
       "Thất ngôn bát cú": "that_ngon_bat_cu", "Thất ngôn tứ tuyệt": "that_ngon_tu_tuyet",
       "Ngũ ngôn": "ngu_ngon", "Ngũ ngôn tứ tuyệt": "ngu_ngon_tu_tuyet",
       "Ngũ ngôn bát cú": "ngu_ngon_bat_cu", "Thơ bốn chữ": "bon_chu"}
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
if __name__ != "__main__": N = 0
TOI_DA_DONG = 32


def goi(**q):
    url = API + "?" + urllib.parse.urlencode({**q, "format": "json"})
    for lan in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 + 3 * lan)
    return {}


def raw(tieu_de):
    url = "https://vi.wikisource.org/w/index.php?" + urllib.parse.urlencode({"title": tieu_de, "action": "raw"})
    for lan in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(2 + 3 * lan)
    return ""


def sach(s: str) -> str:
    s = re.sub(r"<ref[^>/]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    for _ in range(3):   # template lồng nhau: {{khác|chính|phụ}}, {{khác 2|chính|ghi chú}}
        s = re.sub(r"\{\{\s*khác(?: 2)?\s*\|([^{}|]*)(?:\|[^{}]*)?\}\}", r"\1", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s


KHUON = {"luc_bat": (6, 8), "song_that_luc_bat": (7, 6, 8), "that_ngon_bat_cu": (7,),
         "that_ngon_tu_tuyet": (7,), "ngu_ngon": (5,), "ngu_ngon_tu_tuyet": (5,),
         "ngu_ngon_bat_cu": (5,), "bon_chu": (4,)}


def _am(x: str) -> int:
    return len(re.findall(r"[^\W\d_]+", x))


def _khop(dong: list[str], the: str) -> float:
    """Tỉ lệ dòng có số chữ đúng khuôn của thể."""
    co = [x for x in dong if x]
    return sum(1 for x in co if _am(x) in KHUON[the]) / len(co) if co else 0.0


def bai(tieu_de: str, the: str):
    w = raw(tieu_de)
    khoi = [[re.sub(r"\s+", " ", x).strip() for x in sach(m).split("\n")]
            for m in re.findall(r"<poem>(.*?)</poem>", w, re.S)]
    # Bỏ khối chữ Hán; chọn khối khớp khuôn nhất (phiên âm / bản dịch đúng thể).
    khoi = [k for k in khoi if not any(re.search(r"[\u3400-\u9fff]", x) for x in k)]
    if not khoi:
        return None
    dong = max(khoi, key=lambda k: _khop(k, the))
    if _khop(dong, the) < 0.8:
        return None
    tg = re.search(r"\|\s*tác giả\s*=\s*([^\n|]*)", w)
    while dong and not dong[0]:
        dong.pop(0)
    # gộp nhiều dòng trống liền; cắt bài dài (Truyện Kiều…) ở ranh giới khổ gần TOI_DA_DONG
    gon = []
    for x in dong:
        if x or (gon and gon[-1]):
            gon.append(x)
    if len(gon) > TOI_DA_DONG:
        gon = gon[:TOI_DA_DONG]
    while gon and not gon[-1]:
        gon.pop()
    if sum(1 for x in gon if x) < 2:
        return None
    return {"ten": tieu_de, "tac_gia": re.sub(r"\[\[|\]\]", "", tg.group(1)).strip() if tg else "",
            "the": the, "nguon": "https://vi.wikisource.org/wiki/" + urllib.parse.quote(tieu_de.replace(" ", "_")),
            "dong": gon}


def chinh():
    ra = []
    random.seed(29092026)
    for ten_the, ma in THE.items():
        tv = goi(action="query", list="categorymembers", cmtitle=f"Thể loại:{ten_the}", cmlimit=500, cmnamespace=0)
        ds = [x["title"] for x in tv.get("query", {}).get("categorymembers", [])]
        random.shuffle(ds)
        lay = 0
        for t in ds:
            if lay >= N:
                break
            b = bai(t, ma)
            if b:
                ra.append(b)
                lay += 1
            time.sleep(0.3)
        print(f"{ten_the}: {lay}/{len(ds)}", file=sys.stderr)
    json.dump(ra, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
    print(len(ra), "bai", file=sys.stderr)


if __name__ == "__main__":
    chinh()
