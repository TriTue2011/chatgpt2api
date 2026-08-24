"""Markdown → Zalo RTF styles (cùng mô hình Smarthome Black / HA zalo_bot).

Zalo personal API ``sendMessageByAccount`` nhận::

    {"msg": "plain", "styles": [{"start": 0, "len": 5, "st": "c_f27806,b"}], "ttl": 0}

- ``start`` / ``len`` tính theo UTF-16 (JS), không phải len Python thuần.
- Màu: red / orange / yellow / green (token ``c_…``) + bold.

CÁCH DỰNG: ĐỌC THEO DÒNG, KHÔNG QUÉT CẢ BÀI

Bản trước quét cả chuỗi bằng một ngăn xếp dấu mở/đóng. Một dấu ``*`` lẻ ở bất
kỳ đâu — mà dấu đầu dòng kiểu ``* mục`` thì luôn lẻ — làm lệch ngăn xếp cho
TOÀN BỘ phần còn lại: hai dòng gạch đầu dòng liền nhau bị ghép thành một vùng
nghiêng, còn ``## Tiêu đề`` và ``**đậm**` nằm giữa thì lọt ra nguyên dấu.
Đo thật trên tin gửi lúc 06:26 ngày 24/08/2026: người dùng nhận nguyên chuỗi
``## Goose là gì?`` và ``**1**. MCP rất mạnh``.

Nay mỗi dòng được đọc riêng: cấu trúc (tiêu đề / trích dẫn / gạch đầu dòng /
đánh số / bảng / đường kẻ) nhận diện trước, phần chữ còn lại mới soi dấu inline
bằng biểu thức chính quy có cặp. Dấu lẻ không khớp cặp thì ở nguyên tại chỗ và
KHÔNG kéo theo phần sau. Vị trí style tính thẳng lúc ghép dòng, nên không còn
bước "dời style sau khi bỏ ký tự" — chính bước đó từng để vùng đậm tràn sang
dòng kế (``**1. mục**`` → vùng đậm dài 15 trong khi dòng chỉ còn 12 ký tự).
"""
from __future__ import annotations

import re
from typing import Any

# Màu Zalo (giống HA integration smarthomeblack/zalo_bot)
ZALO_COLORS: dict[str, str] = {
    "red": "c_db342e",
    "orange": "c_f27806",
    "yellow": "c_f7b503",
    "green": "c_15a85f",
    "gold": "c_f7b503",  # alias gần yellow/gold
}

HEADING_STYLES: dict[int, str] = {
    # f_18 chứ không phải f_20: bảng TextStyle của zca-js chỉ có f_13 (Small) và
    # f_18 (Big). "f_20" là mã Zalo không biết, gửi lên coi như không có — tiêu
    # đề cấp 1 xưa nay chỉ đậm chứ chưa bao giờ to lên.
    1: "f_18,b",
    2: "f_18,b",
    3: "b",
    4: "f_13",
    5: "f_13",
    6: "f_13",
}

#: Zalo không có bảng. Ô của một hàng nối bằng dấu này cho dễ đọc trên chat.
NOI_O_BANG = " · "

#: Đường kẻ ngang markdown (``---``) vẽ bằng ký tự kẻ, vì gửi nguyên "---" thì
#: người đọc thấy đúng ba dấu gạch.
KE_NGANG = "─" * 12


def _js_len(s: str) -> int:
    """Độ dài UTF-16 (JS) — emoji > U+FFFF tính 2."""
    n = 0
    for ch in s:
        n += 2 if ord(ch) >= 0x10000 else 1
    return n


def _py_to_js_pos(text: str, py_pos: int) -> int:
    return _js_len(text[: max(0, py_pos)])


def _resolve_color_token(color: str | None) -> str | None:
    """None/off/none → không ép màu; else token ``c_xxx,b``."""
    if not color:
        return None
    c = str(color).strip().lower()
    if c in ("", "off", "none", "default"):
        return None
    tok = ZALO_COLORS.get(c)
    if tok:
        return f"{tok},b"
    # passthrough raw zalo style
    return c


# ── Nhận dạng cấu trúc DÒNG ───────────────────────────────────────────────────

_RE_CHAM = re.compile(r"^([ \t]*)[-*+•][ \t]+(?=\S)")
_RE_SO = re.compile(r"^([ \t]*)\d{1,2}[.)][ \t]+(?=\S)")
_RE_THUT = re.compile(r"^([ \t]+)(?=\S)")
_RE_TIEU_DE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.*)$")
_RE_TRICH = re.compile(r"^[ \t]{0,3}>[ \t]?(.*)$")
#: ``---`` / ``***`` / ``___`` đứng một mình = đường kẻ ngang.
_RE_KE_NGANG = re.compile(r"^[ \t]{0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$")
_RE_HANG_BANG = re.compile(r"^[ \t]*\|(.+)\|[ \t]*$")
#: Hàng ngăn cách của bảng: ``|---|:--:|`` — bỏ hẳn, không có gì để đọc.
_RE_NGAN_BANG = re.compile(r"^[ \t]*\|[\s:|.-]+\|[ \t]*$")
_RE_RAO_CODE = re.compile(r"^[ \t]*(```|~~~)")

_MUC_THUT_TOI_DA = 4


def _muc_thut(khoang: str) -> int:
    """Hai dấu cách (hoặc một tab) = MỘT cấp; Zalo nhận ind_10…ind_40."""
    cot = sum(2 if ch == "\t" else 1 for ch in khoang)
    return min(_MUC_THUT_TOI_DA, cot // 2)


# ── Dấu inline TRONG MỘT DÒNG ────────────────────────────────────────────────

_RE_LIEN_KET = re.compile(r"\[([^\]\n]*)\]\((\S*?)\)")

#: Thứ tự nhánh là thứ tự ưu tiên tại mỗi vị trí: ``***`` trước ``**``, ``__``
#: trước ``_``. Mỗi nhánh đòi ĐỦ CẶP trong cùng một dòng — dấu lẻ không khớp thì
#: nằm nguyên tại chỗ, không nuốt phần sau như ngăn xếp cũ.
_RE_INLINE = re.compile(
    r"(?P<bi>\*\*\*(?P<bi_t>[^\n]+?)\*\*\*)"
    r"|(?P<b>\*\*(?P<b_t>[^\n]+?)\*\*)"
    r"|(?P<s>~~(?P<s_t>[^\n]+?)~~)"
    r"|(?P<u>__(?P<u_t>[^\n]+?)__)"
    r"|(?P<code>`(?P<code_t>[^`\n]+)`)"
    r"|(?P<i>(?<!\*)\*(?P<i_t>[^*\n]+?)\*(?!\*))"
    r"|(?P<i2>(?<![\w_])_(?P<i2_t>[^_\n]+?)_(?![\w_]))"
)

_TOKEN_INLINE = {
    "bi": "b,i", "b": "b", "s": "s", "u": "u",
    # Zalo không có kiểu "code"; nghiêng là thứ gần nhất — giữ như bản cũ.
    "code": "i", "i": "i", "i2": "i",
}
_THU_TU_INLINE = ("bi", "b", "s", "u", "code", "i", "i2")

_SAU_TOI_DA = 2   # **đậm có *nghiêng* bên trong** — sâu hơn nữa thì thôi


def _boc_lien_ket(dong: str) -> str:
    """``[chữ](url)`` → giữ URL trần (Zalo tự bắt link, không hiểu cú pháp md)."""
    return _RE_LIEN_KET.sub(lambda m: m.group(2) or m.group(1), dong)


def _inline(than: str, *, gach_chan: bool, sau: int = 0) -> tuple[str, list[dict]]:
    """Bóc dấu inline của MỘT dòng → (chữ trơn, các vùng style theo dòng)."""
    manh: list[str] = []
    spans: list[dict] = []
    vi_tri = 0      # đã ăn tới đâu trong `than`
    dai = 0         # độ dài chữ trơn đã dựng
    for m in _RE_INLINE.finditer(than):
        if m.start() < vi_tri:
            continue
        ten = next((t for t in _THU_TU_INLINE if m.group(t) is not None), "")
        if not ten or (ten == "u" and not gach_chan):
            continue
        truoc = than[vi_tri:m.start()]
        manh.append(truoc)
        dai += len(truoc)
        noi_dung = m.group(ten + "_t")
        if sau < _SAU_TOI_DA:
            con_txt, con_spans = _inline(noi_dung, gach_chan=gach_chan, sau=sau + 1)
        else:
            con_txt, con_spans = noi_dung, []
        if con_txt:
            spans.append({"start": dai, "len": len(con_txt), "st": _TOKEN_INLINE[ten]})
            for s in con_spans:
                spans.append({"start": dai + s["start"], "len": s["len"], "st": s["st"]})
        manh.append(con_txt)
        dai += len(con_txt)
        vi_tri = m.end()
    manh.append(than[vi_tri:])
    return "".join(manh), spans


def _doc_dong(dong: str, *, gach_chan: bool, danh_sach: bool, thut_le: bool,
              dau_bang: bool) -> tuple[str, list[str], list[dict]] | None:
    """Một dòng markdown → (chữ hiện ra, style cả dòng, style inline).

    Trả None nghĩa là BỎ HẲN dòng — không để lại dòng trống thế chỗ.
    """
    if _RE_KE_NGANG.match(dong):
        return KE_NGANG, [], []

    if _RE_NGAN_BANG.match(dong):
        return None
    m_bang = _RE_HANG_BANG.match(dong)
    if m_bang:
        o = [c.strip() for c in m_bang.group(1).split("|")]
        than, spans = _inline(_boc_lien_ket(NOI_O_BANG.join(c for c in o if c)),
                              gach_chan=gach_chan)
        # Hàng đầu của bảng là tiêu đề cột → đậm CẢ DÒNG (một vùng), chứ không
        # tô từng ô: mỗi ô một vùng là cách nhanh nhất để một bảng 6 hàng ăn hết
        # ngân sách vùng định dạng của cả tin.
        return than, (["b"] if dau_bang and than else []), spans

    m_td = _RE_TIEU_DE.match(dong)
    if m_td:
        cap = len(m_td.group(1))
        than, spans = _inline(_boc_lien_ket(m_td.group(2).strip()), gach_chan=gach_chan)
        return than, ([HEADING_STYLES.get(cap, "b")] if than else []), spans

    m_tr = _RE_TRICH.match(dong)
    if m_tr:
        than, spans = _inline(_boc_lien_ket(m_tr.group(1)), gach_chan=gach_chan)
        return than, (["i"] if than else []), spans

    tok: list[str] = []
    bo_dau = 0
    cap = 0
    m = _RE_CHAM.match(dong) if danh_sach else None
    if m is not None:
        tok.append("lst_1")
    elif danh_sach:
        m = _RE_SO.match(dong)
        if m is not None:
            tok.append("lst_2")
    if m is not None:
        bo_dau = m.end()
        cap = _muc_thut(m.group(1))
    else:
        mt = _RE_THUT.match(dong) if thut_le else None
        cap = _muc_thut(mt.group(1)) if mt else 0
        if mt is not None and cap:
            bo_dau = mt.end()
    if thut_le and cap:
        tok.append(f"ind_{cap}0")

    than, spans = _inline(_boc_lien_ket(dong[bo_dau:]), gach_chan=gach_chan)
    if not than:
        tok = []
    return than, tok, spans


def markdown_to_zalo_message(
    text: str,
    *,
    color: str | None = "orange",
    size: str | None = "normal",
    gach_chan: bool = True,
    danh_sach: bool = True,
    thut_le: bool = True,
) -> dict[str, Any]:
    """Convert markdown-ish LLM text → {msg, styles} cho Zalo personal (zca-js).

    Hỗ trợ: **bold**, *italic*, _italic_, __underline__, ~~strike~~, ``code``,
    # headings, > quote, [t](url), bảng ``| a | b |``, đường kẻ ``---``,
    "- " / "* " / "1. " thành danh sách, khoảng trắng đầu dòng thành thụt lề.
    Khối ``` giữ nguyên chữ bên trong, chỉ bỏ dòng rào.
    size: normal | big → thêm ``f_18`` (TextStyle.Big trong zca-js).

    Ba công tắc `gach_chan` / `danh_sach` / `thut_le` lấy từ cài đặt của tài
    khoản (xem `zalo_bot_format.resolve_zalo_rtf`).
    """
    if not text or not isinstance(text, str):
        return {"msg": str(text or ""), "styles": []}

    dong_ra: list[str] = []
    styles: list[dict[str, Any]] = []
    vi_tri = 0
    trong_code = False
    dang_bang = False

    for dong in text.split("\n"):
        if _RE_RAO_CODE.match(dong):
            # Bỏ cả dòng rào lẫn nhãn ngôn ngữ ("```bash"): để lại thì người đọc
            # thấy một dòng "bash" trơ trọi không hiểu ở đâu ra.
            trong_code = not trong_code
            continue
        if trong_code:
            than, tok, spans = dong, [], []
        else:
            la_bang = bool(_RE_HANG_BANG.match(dong) or _RE_NGAN_BANG.match(dong))
            doc = _doc_dong(
                dong, gach_chan=gach_chan, danh_sach=danh_sach,
                thut_le=thut_le, dau_bang=la_bang and not dang_bang)
            dang_bang = la_bang
            if doc is None:
                continue
            than, tok, spans = doc

        for t in tok:
            styles.append({"start": vi_tri, "len": len(than), "st": t})
        for s in spans:
            styles.append({"start": vi_tri + s["start"], "len": s["len"], "st": s["st"]})
        dong_ra.append(than)
        vi_tri += len(than) + 1

    final_msg = "\n".join(dong_ra)
    # Vùng rỗng là rác: Zalo không có gì để tô, mà mỗi vùng vẫn ăn chỗ trong
    # `textProperties` — chính chỗ đó là thứ làm tin bị từ chối khi quá nhiều.
    styles = [s for s in styles if s["len"] > 0]
    if not styles:
        return {"msg": final_msg, "styles": []}

    # Python pos → JS UTF-16
    for s in styles:
        frag = final_msg[s["start"]: s["start"] + s["len"]]
        s["start"] = _py_to_js_pos(final_msg, s["start"])
        s["len"] = _js_len(frag)

    # color + size override on bold (incl heading bold)
    # zca-js TextStyle: Bold=b, Orange=c_f27806, Big=f_18, Small=f_13
    override = _resolve_color_token(color)
    size_tok = None
    sz = str(size or "normal").strip().lower()
    if sz in {"big", "large", "xlarge", "lg", "xl", "f_18", "f_20"}:
        size_tok = "f_18"
    elif sz in {"small", "sm", "f_13"}:
        size_tok = "f_13"
    if override or size_tok:
        for s in styles:
            tokens = [t for t in (s["st"].split(",") if s["st"] else []) if t]
            is_boldish = "b" in tokens or any(t.startswith("f_") for t in tokens)
            if not is_boldish:
                continue
            new_tokens: list[str] = []
            for t in tokens:
                if t == "b" and override:
                    new_tokens.extend(x for x in override.split(",") if x)
                else:
                    new_tokens.append(t)
            if size_tok and size_tok not in new_tokens:
                new_tokens.append(size_tok)
            seen: set[str] = set()
            cleaned: list[str] = []
            for t in new_tokens:
                if t not in seen:
                    seen.add(t)
                    cleaned.append(t)
            s["st"] = ",".join(cleaned)

    styles = [s for s in styles if s.get("st")]
    return {"msg": final_msg, "styles": styles}


def config_markdown_color() -> str:
    """Màu mặc định từ config (top-level hoặc zalo_personal)."""
    try:
        from services.config import config
        c = config.get()
        zp = c.get("zalo_personal") if isinstance(c.get("zalo_personal"), dict) else {}
        for src in (zp, c):
            if not isinstance(src, dict):
                continue
            for key in ("markdown_color", "zalo_markdown_color"):
                v = str(src.get(key) or "").strip().lower()
                if v:
                    return v
        if c.get("zalo_markdown_enabled") is False:
            return "none"
    except Exception:
        pass
    return "orange"


def config_markdown_enabled() -> bool:
    try:
        from services.config import config
        c = config.get()
        zp = c.get("zalo_personal") if isinstance(c.get("zalo_personal"), dict) else {}
        for src in (zp, c):
            if not isinstance(src, dict):
                continue
            if "markdown_enabled" in src:
                v = src.get("markdown_enabled")
                if isinstance(v, str):
                    return v.strip().lower() in {"1", "true", "yes", "on"}
                return bool(v)
    except Exception:
        pass
    return True
