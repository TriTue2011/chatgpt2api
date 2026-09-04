"""Đánh mã mục cho câu trả lời dạng DANH SÁCH DÀI, để người dùng chọn xem chi tiết.

Vì sao có file này (yêu cầu chủ máy 24/08): bản tin chia 8 mục × 3 tin là 24
dòng gạch đầu dòng giống hệt nhau, muốn xem kỹ một tin thì phải gõ lại nguyên
tiêu đề. Người dùng nói thẳng: "với những thông tin dài và nhiều lựa chọn nên
tạo đánh số kiểu A, I, 1, a để lựa chọn cần xem chi tiết. Không chỉ ở tin tức
mà cả ở phần khác".

Cách làm — CODE, không nhờ model:

  * ``danh_so(text)`` soi bố cục sẵn có của tin nhắn (đầu mục + gạch đầu dòng)
    rồi thay dấu đầu dòng bằng MÃ MỤC phân cấp;
  * mã được lưu theo user (RAM + SQLite, sống qua restart) như ``ask_choices``;
  * người dùng trả đúng một mã ("A1", "a1", "3") → ``resolve_reply`` trả về
    ĐÚNG mục ấy (mã, nội dung, nguồn) cho orchestrator xử lý tiếp.

Mục của BẢN TIN (``nguon="tin"``) được tra THẲNG bằng chính TIÊU ĐỀ, không bọc
lời dặn quanh nó. Đo thật 24/08 16:55 và 16:57: bản cũ bơm nguyên câu «Xem chi
tiết mục này: "…". …» (xem ``_cau_hoi``) vào vòng trợ lý, mà mọi tầng tra cứu
phía sau (searxng, PubMed/CrossRef/Wikipedia, RAG kho tri thức) đều lấy NGUYÊN
VĂN câu đó làm truy vấn — nên chọn một tin giáo dục thì nhận về sách giáo khoa
Tiếng Việt lớp 2, chọn lần nữa thì nhận về điều khoản VTVgo/iQIYI.

Bậc mã theo độ sâu: ``A`` (đầu mục) → ``1`` (tin) → ``a`` → ``i``. Mã của một
dòng là NỐI mã các bậc cha: mục A, tin 2 → ``A2``; tin con → ``A2a``. Chủ máy
nêu thứ tự "A, I, 1, a"; chữ số La Mã bị đẩy xuống bậc 4 vì mã phải GÕ ĐƯỢC —
"A-II" khó gõ và dễ nhầm, còn "A2" thì không.

Vì sao KHÔNG dùng lại ``ask_choices``: khối ``<<<ASK>>>`` là câu hỏi model chủ
động đặt, tối đa 8 lựa chọn, nhãn cắt ở 40 ký tự và Telegram vẽ thành nút. Bản
tin 24 tin không phải câu hỏi, không vẽ nút được, và cắt 40 ký tự là mất tiêu
đề. Hai việc khác nhau nên hai bản chờ khác nhau — ``ask_choices`` được tra
TRƯỚC trong orchestrator, nên khi đang có câu hỏi thật thì số "1" vẫn thuộc về
câu hỏi đó.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Nhận dạng bố cục ─────────────────────────────────────────────────────────
#
# Dấu đầu dòng: gạch/chấm tròn/số. Cùng bộ dấu mà `zalo_markdown` hiểu, để thứ
# ta thay thế đúng bằng thứ Zalo sẽ vẽ thành danh sách native.
_RE_DAU_DONG = re.compile(r"^([ \t]*)(?:[-*+•]|\d{1,2}[.)])[ \t]+(?=\S)")
_RE_DAM = re.compile(r"^\*\*(.+)\*\*$")
_RE_TIEU_DE_MD = re.compile(r"^(#{1,6}[ \t]+)(\S.*)$")
_RE_BANG = re.compile(r"^[ \t]*\|")

#: Danh sách PHẲNG (không đầu mục) phải đủ dài mới đáng đánh số — ba gạch đầu
#: dòng trong một câu trả lời thường là câu văn, không phải bảng chọn.
_TOI_THIEU_PHANG = 5
#: Có từ 2 đầu mục trở lên thì đánh số sớm hơn: đó đã là một bản tin/danh mục.
_TOI_THIEU_CO_MUC = 4
#: Trần số mục ghi nhớ. Dài hơn nữa thì người ta cuộn chứ không chọn.
_TOI_DA = 60
#: Trần độ dài nội dung một mục đem đi hỏi chi tiết.
_NOI_DUNG_MAX = 300

_TTL = 1800.0        # 30 phút: bản tin đọc dở, lát sau quay lại chọn vẫn còn.

_lock = threading.RLock()
_pending: dict[str, dict[str, Any]] = {}
_conn = None


def _db():
    global _conn
    if _conn is not None:
        return _conn
    try:
        import sqlite3
        from services.config import DATA_DIR
        p = Path(DATA_DIR) / "agent" / "muc_luc_pending.sqlite"
        p.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(p), check_same_thread=False)
        c.execute("CREATE TABLE IF NOT EXISTS muc_pending ("
                  " user_id TEXT PRIMARY KEY, muc TEXT NOT NULL, ts REAL)")
        c.commit()
        _conn = c
    except Exception as exc:
        logger.warning("muc_luc: mở SQLite lỗi (chỉ dùng RAM): %s", exc)
        _conn = None
    return _conn


# ── Sinh mã theo bậc ─────────────────────────────────────────────────────────

_LA_MA = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
          "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx"]


def _chu(so: int, hoa: bool) -> str:
    """Chữ cái thứ `so` (0-based), quá Z thì sang AA/AB — như cột bảng tính.

    Không lấy dư 26 quay vòng: mục thứ 27 mà lại mang mã "A" thì hai mục cùng
    mã, người dùng gõ "A1" ra tin của mục khác mà không hiểu vì sao.
    """
    goc = ord("A") if hoa else ord("a")
    ra, n = "", so
    while True:
        ra = chr(goc + n % 26) + ra
        n = n // 26 - 1
        if n < 0:
            return ra


def _ma_bac(bac: int, so: int) -> str:
    """Mã của phần tử thứ `so` (0-based) ở bậc `bac` (0 = đầu mục)."""
    if bac == 0:
        return _chu(so, True)
    if bac == 1:
        return str(so + 1)
    if bac == 2:
        return _chu(so, False)
    return _LA_MA[so] if so < len(_LA_MA) else str(so + 1)


def _lam_sach(s: str) -> str:
    """Nội dung đem đi hỏi chi tiết: bỏ dấu markdown, gom khoảng trắng, cắt."""
    ra = re.sub(r"\*\*|__|`", "", str(s or "")).strip()
    ra = re.sub(r"\s+", " ", ra)
    return ra[:_NOI_DUNG_MAX].strip()


def _ra_dang_dau_muc(dong: str) -> bool:
    """Dòng này trông đã ra dáng đầu mục chưa (đậm / tiêu đề / kết bằng «:»)."""
    t = dong.strip()
    return bool(_RE_DAM.match(t) or _RE_TIEU_DE_MD.match(dong) or t.endswith(":"))


# ── Đánh mã ──────────────────────────────────────────────────────────────────

def danh_so(text: str) -> tuple[str, list[dict[str, str]]]:
    """Gắn mã mục vào danh sách trong `text`.

    Trả ``(text_mới, [{"ma","noi_dung"}…])``. Không phải danh sách đủ dài thì
    trả về NGUYÊN VĂN và danh sách rỗng — mọi câu trả lời đều đi qua đây nên
    phải im lặng khi không có việc.
    """
    raw = text or ""
    if not raw.strip() or "```" in raw:
        return raw, []

    dong = raw.split("\n")
    la_y = [bool(_RE_DAU_DONG.match(d)) for d in dong]
    if any(_RE_BANG.match(d) for d in dong):   # bảng markdown: đừng chạm vào
        return raw, []
    if not any(la_y):
        return raw, []

    # Đầu mục = dòng chữ thường NGAY TRƯỚC một dấu đầu dòng, không thụt lề.
    # Ràng buộc "ngay trước" là thứ giữ cho dòng tóm tắt của bản tin theo chủ đề
    # (thụt lề, nằm sát tin kế tiếp) không bị nhận nhầm thành đầu mục.
    #
    # Nới đúng một dòng trống — và CHỈ cho dòng trông đã ra dáng đầu mục (bọc
    # `**`, tiêu đề `##`, hoặc kết thúc bằng dấu hai chấm). Model hay xuống dòng
    # trống giữa đầu mục và danh sách; không nới thì cả bản tin rơi về đánh số
    # phẳng 1..24, mất luôn chữ cái mục.
    la_muc = [False] * len(dong)
    for i, d in enumerate(dong):
        if la_y[i] or not d.strip() or d[:1].isspace():
            continue
        ke = i + 1
        if ke < len(dong) and not dong[ke].strip() and _ra_dang_dau_muc(d):
            ke += 1
        if ke < len(dong) and la_y[ke]:
            la_muc[i] = True

    so_muc = sum(1 for x in la_muc if x)
    so_y = sum(1 for x in la_y if x)
    if so_y > _TOI_DA:
        return raw, []
    co_muc = so_muc >= 2
    if co_muc:
        if so_y < _TOI_THIEU_CO_MUC:
            return raw, []
    elif so_y < _TOI_THIEU_PHANG:
        return raw, []

    muc: list[dict[str, str]] = []
    dem_muc = 0
    tien_to = ""
    # Mỗi phần tử: {"thut": int, "so": int, "ma": str} — một bậc danh sách con.
    ngan: list[dict[str, Any]] = []

    for i, d in enumerate(dong):
        if la_muc[i] and co_muc:
            ma = _ma_bac(0, dem_muc)
            dem_muc += 1
            tien_to = ma
            ngan = []
            dong[i] = _gan_ma_dau_muc(d, ma)
            continue
        if not la_y[i]:
            continue
        m = _RE_DAU_DONG.match(d)
        thut = len(m.group(1).expandtabs(4))
        while ngan and thut < ngan[-1]["thut"]:
            ngan.pop()
        if ngan and thut == ngan[-1]["thut"]:
            ngan[-1]["so"] += 1
            ngan[-1]["ma"] = _ma_bac(len(ngan), ngan[-1]["so"])
        else:
            ngan.append({"thut": thut, "so": 0, "ma": _ma_bac(len(ngan) + 1, 0)})
        ma = tien_to + "".join(x["ma"] for x in ngan)
        noi_dung = d[m.end():]
        dong[i] = f"{m.group(1)}{ma}. {noi_dung}"
        muc.append({"ma": ma, "noi_dung": _lam_sach(noi_dung)})

    if not muc:
        return raw, []
    vi_du = muc[0]["ma"]
    ra = "\n".join(dong).rstrip()
    ra += (f"\n\n(Muốn xem kỹ mục nào thì nhắn mã mục đó cho em — ví dụ {vi_du}.)")
    return ra, muc


def _gan_ma_dau_muc(dong: str, ma: str) -> str:
    """Chèn mã vào dòng đầu mục, GIỮ NGUYÊN kiểu chữ của nó.

    Mã phải nằm TRONG cặp `**` chứ không đứng trước: `zalo_markdown` dựng vùng
    đậm theo đúng cặp dấu sao, để mã ra ngoài thì đầu mục hết đậm một nửa.
    """
    d = dong.rstrip()
    m = _RE_DAM.match(d.strip())
    if m:
        return f"**{ma}. {m.group(1)}**"
    m2 = _RE_TIEU_DE_MD.match(d)
    if m2:
        return f"{m2.group(1)}{ma}. {m2.group(2)}"
    return f"{ma}. {d}"


# ── Bản chờ ──────────────────────────────────────────────────────────────────

def set_pending(user_id: str, muc: list[dict[str, str]], nguon: str = "") -> None:
    """`nguon` = danh sách này từ đâu ra ("tin" = bản tin). Quyết định cách xem
    chi tiết: mục bản tin thì tra mạng theo tiêu đề, mục thường thì hỏi trợ lý."""
    if not user_id or not muc:
        return
    now = time.time()
    ng = str(nguon or "")
    with _lock:
        _pending[str(user_id)] = {"muc": list(muc), "nguon": ng, "ts": now}
    try:
        import json
        c = _db()
        if c is not None:
            # Gói `nguon` VÀO cột `muc` (JSON) thay vì thêm cột: bảng cũ đã nằm
            # sẵn trên máy chủ, mà CREATE TABLE IF NOT EXISTS không thêm cột.
            c.execute("INSERT OR REPLACE INTO muc_pending(user_id, muc, ts) "
                      "VALUES (?,?,?)",
                      (str(user_id),
                       json.dumps({"muc": list(muc), "nguon": ng},
                                  ensure_ascii=False),
                       now))
            c.commit()
    except Exception as exc:
        logger.warning("muc_luc: lưu pending lỗi: %s", exc)


def get_pending(user_id: str) -> Optional[dict[str, Any]]:
    """Bản chờ còn hiệu lực → ``{"muc": [...], "nguon": "…"}``, hết hạn → None."""
    uid = str(user_id)
    with _lock:
        p = _pending.get(uid)
    if p:
        if time.time() - float(p.get("ts") or 0) > _TTL:
            clear_pending(uid)
            return None
        return {"muc": list(p.get("muc") or []),
                "nguon": str(p.get("nguon") or "")}
    try:
        import json
        c = _db()
        if c is None:
            return None
        row = c.execute("SELECT muc, ts FROM muc_pending WHERE user_id=?",
                        (uid,)).fetchone()
        if not row:
            return None
        if time.time() - float(row[1] or 0) > _TTL:
            clear_pending(uid)
            return None
        data = json.loads(row[0] or "[]")
        # Bản ghi ghi trước bản này là LIST TRẦN (chưa có `nguon`) — vẫn đọc được,
        # để lần nâng cấp không làm người đang đọc dở bản tin gõ mã ra "chưa rõ ý".
        if isinstance(data, list):
            data = {"muc": data, "nguon": ""}
        muc = list(data.get("muc") or [])
        nguon = str(data.get("nguon") or "")
        if not muc:
            return None
        with _lock:
            _pending[uid] = {"muc": muc, "nguon": nguon, "ts": row[1]}
        return {"muc": muc, "nguon": nguon}
    except Exception as exc:
        logger.warning("muc_luc: đọc pending lỗi: %s", exc)
        return None


def clear_pending(user_id: str) -> None:
    uid = str(user_id)
    with _lock:
        _pending.pop(uid, None)
    try:
        c = _db()
        if c is not None:
            c.execute("DELETE FROM muc_pending WHERE user_id=?", (uid,))
            c.commit()
    except Exception:
        pass


# Câu người dùng gõ để CHỌN: chỉ mã mục, không kèm chữ nào khác. Chặt tay là cố
# ý — bản chờ sống 30 phút, nên "3" trong một câu bình thường mà bị nuốt thành
# lệnh chọn thì người dùng không hiểu vì sao bot lạc đề.
_RE_CHON = re.compile(r"^[\s.\-–)(]*([A-Za-z]{0,2}\d{0,2}[A-Za-z]{0,3})[\s.\-–)(]*$")


def _cau_hoi(noi_dung: str) -> str:
    """Câu bơm vào vòng trợ lý khi người dùng chọn một mục.

    KHÔNG ra lệnh "tra cứu thêm". Bản cũ viết cứng câu đó cho MỌI loại danh
    sách, nên chọn một nghĩa từ điển — thứ chính bot vừa đưa ra và đang nằm sẵn
    trong ngữ cảnh — cũng khiến nó đi tra web rồi mới trả lời. Đo thật 29/08
    trên Zalo: người dùng tra "stroke", bấm «1» (nghĩa y khoa: đột quỵ), bot
    chạy searxng tìm "đột quỵ" rồi mới nói, và người dùng thấy "phản hồi hơi
    lâu".

    Giờ để MODEL tự quyết: đủ dữ kiện thì nói luôn, thiếu mới đi tra. Không cấm
    tra cứu — có mục thật sự cần dữ liệu mới (một tin trong bản tin, một chủ đề
    chỉ mới nêu tên), chặn hẳn thì lại hỏng chiều ngược lại.
    """
    return (f'Nói kỹ hơn về mục này: "{noi_dung}". '
            "Nội dung đã có sẵn trong ngữ cảnh thì trả lời thẳng; chỉ khi cần "
            "dữ kiện mới hoặc số liệu cập nhật mới đi tra cứu.")


def resolve_reply(user_id: str, user_text: str) -> Optional[dict[str, str]]:
    """Người dùng vừa gõ một mã mục? → ``{"ma","noi_dung","nguon","cau_hoi"}``.

    ``cau_hoi`` là câu bơm vào vòng trợ lý, dùng cho danh sách THƯỜNG (việc cần
    làm, danh mục…). Mục BẢN TIN (``nguon="tin"``) KHÔNG dùng câu này —
    orchestrator đem thẳng ``noi_dung`` đi tra tin, vì câu bọc lời dặn làm hỏng
    truy vấn của mọi tầng tra cứu phía sau (xem docstring đầu file)."""
    t = (user_text or "").strip()
    if not t or len(t) > 8:
        return None
    m = _RE_CHON.match(t)
    if not m:
        return None
    ma = m.group(1).strip()
    if not ma:
        return None
    ban = get_pending(user_id)
    if not ban:
        return None
    nguon = str(ban.get("nguon") or "")
    for it in ban.get("muc") or []:
        if str(it.get("ma") or "").lower() == ma.lower():
            noi_dung = str(it.get("noi_dung") or "").strip()
            if not noi_dung:
                return None
            clear_pending(user_id)
            logger.info({"event": "muc_luc_chon", "ma": it.get("ma"),
                         "nguon": nguon})
            return {"ma": str(it.get("ma") or ""), "noi_dung": noi_dung,
                    "nguon": nguon, "cau_hoi": _cau_hoi(noi_dung)}
    return None


def _doc_tho(user_id: str) -> Optional[tuple[list, str, float]]:
    """``(muc, nguon, ts)`` của bản chờ, KHÔNG xoá khi hết hạn — để phân biệt
    'hết hạn' với 'chưa từng có'. ``None`` nếu không có bản ghi nào."""
    uid = str(user_id)
    with _lock:
        p = _pending.get(uid)
    if p:
        return (list(p.get("muc") or []), str(p.get("nguon") or ""),
                float(p.get("ts") or 0))
    try:
        import json
        c = _db()
        if c is None:
            return None
        row = c.execute("SELECT muc, ts FROM muc_pending WHERE user_id=?",
                        (uid,)).fetchone()
        if not row:
            return None
        data = json.loads(row[0] or "[]")
        if isinstance(data, list):
            data = {"muc": data, "nguon": ""}
        return (list(data.get("muc") or []), str(data.get("nguon") or ""),
                float(row[1] or 0))
    except Exception:
        return None


def trang_thai_chon(user_id: str, ma: str) -> str:
    """Vì sao một mã trần KHÔNG chọn được — để CODE nói lý do THẬT thay vì để
    model đọc thuộc một lý do có thể sai.

    Trả một trong: ``"khop"`` (mã có trong bản chờ còn sống — đáng lẽ
    ``resolve_reply`` đã ăn), ``"het_han"`` (có bản chờ nhưng quá 30'/TTL),
    ``"khong_co"`` (bản chờ còn sống nhưng KHÔNG có mã này), ``"trong"`` (không
    có bản chờ nào — chưa gửi danh sách, hoặc đã chọn/dọn)."""
    tho = _doc_tho(user_id)
    if not tho:
        return "trong"
    muc, _nguon, ts = tho
    if time.time() - float(ts or 0) > _TTL:
        return "het_han"
    ma_l = str(ma or "").strip().lower()
    for it in muc:
        if str(it.get("ma") or "").lower() == ma_l:
            return "khop"
    return "khong_co"


def _boc_ma_tu_van(van: str, ma: str) -> str:
    """Tìm dòng mang mã ``ma`` trong tin ĐÃ ĐÁNH MÃ (bot in `D1. …` vào chữ),
    trả nội dung dòng đó (đã làm sạch), "" nếu không thấy.

    Tin trích có thể đã bị lột markdown (`**`, `##`) khi gửi qua Zalo, nên bỏ
    qua các dấu bọc / gạch đầu dòng ở đầu trước khi so mã. Mã so KHÔNG phân biệt
    hoa-thường và phải đứng RIÊNG (theo sau là `.` / `)` / khoảng trắng) để 'D1'
    không dính vào 'D12'.
    """
    if not van or not ma:
        return ""
    pat = re.compile(
        r"^[\s>*#.)\-–•(]*" + re.escape(ma) + r"[.)\s*]+(?P<nd>\S.*)$",
        re.IGNORECASE)
    for dong in van.split("\n"):
        m = pat.match(dong)
        if m:
            nd = _lam_sach(m.group("nd"))
            if nd:
                return nd
    return ""


def resolve_tu_trich(user_id: str, user_text: str,
                     trich_dan: str) -> Optional[dict[str, str]]:
    """Người dùng TRÍCH DẪN một tin cũ đã đánh mã rồi gõ một mã → chọn mục đó.

    Bù đúng chỗ bản chờ hết hạn (30') hoặc đã bị dọn sau lần chọn trước: mã đã
    in sẵn trong CHỮ của tin (`D1. …`), mà kênh cá nhân gửi lại nguyên nội dung
    tin trích, nên đọc lại được kể cả khi bản chờ không còn.

    Ưu tiên bản chờ nếu còn sống (giữ đúng ``nguon`` — vd "tin" → orchestrator
    tra thẳng tiêu đề); hết bản chờ thì bóc mã từ chính tin trích và đi nhánh
    CHUNG (``nguon=""`` → để model đọc nội dung đã có, tự tra khi cần). Trả None
    nếu câu không phải một mã trần, hoặc tin trích không chứa mã đó."""
    t = (user_text or "").strip()
    if not t or len(t) > 8:
        return None
    m = _RE_CHON.match(t)
    if not m:
        return None
    ma = (m.group(1) or "").strip()
    if not ma:
        return None
    # 1) Bản chờ còn sống → dùng nó (authoritative; tự dọn pending khi khớp).
    picked = resolve_reply(user_id, user_text)
    if picked:
        return picked
    # 2) Hết bản chờ → bóc mã từ chữ trong tin trích.
    noi_dung = _boc_ma_tu_van(str(trich_dan or ""), ma)
    if not noi_dung:
        return None
    logger.info({"event": "muc_luc_chon_trich", "ma": ma})
    return {"ma": ma, "noi_dung": noi_dung, "nguon": "",
            "cau_hoi": _cau_hoi(noi_dung)}


def apply_to_result(result: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Đánh mã cho danh sách trong `result["text"]` và ghi bản chờ.

    Bỏ qua khi tin nhắn đã là MENU (`choices`): khối đó có đường chọn riêng của
    `ask_choices`, đánh thêm mã nữa là hai hệ số trong cùng một tin.
    """
    if not isinstance(result, dict):
        return result
    # Cờ NỘI BỘ do đường tắt tin tức gắn. Lấy ra rồi BỎ khỏi kết quả để nó không
    # lọt xuống kênh chat cùng câu trả lời.
    nguon = str(result.pop("muc_luc_nguon", "") or "")
    text = str(result.get("text") or "")
    if result.get("silent") or not text or result.get("choices"):
        return result
    moi, muc = danh_so(text)
    if not muc:
        return result
    result["text"] = moi
    result["muc_luc"] = True
    set_pending(user_id, muc, nguon)
    logger.info({"event": "muc_luc_danh_so", "so_muc": len(muc), "nguon": nguon})
    return result


def _reset_for_tests() -> None:
    with _lock:
        _pending.clear()
