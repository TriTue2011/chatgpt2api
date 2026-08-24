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
  * người dùng trả đúng một mã ("A1", "a1", "3") → ``resolve_reply`` đổi câu đó
    thành yêu cầu xem chi tiết ĐÚNG mục ấy, rồi orchestrator chạy tiếp như một
    câu hỏi bình thường.

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

def set_pending(user_id: str, muc: list[dict[str, str]]) -> None:
    if not user_id or not muc:
        return
    now = time.time()
    with _lock:
        _pending[str(user_id)] = {"muc": list(muc), "ts": now}
    try:
        import json
        c = _db()
        if c is not None:
            c.execute("INSERT OR REPLACE INTO muc_pending(user_id, muc, ts) "
                      "VALUES (?,?,?)",
                      (str(user_id), json.dumps(list(muc), ensure_ascii=False), now))
            c.commit()
    except Exception as exc:
        logger.warning("muc_luc: lưu pending lỗi: %s", exc)


def get_pending(user_id: str) -> Optional[list[dict[str, str]]]:
    uid = str(user_id)
    with _lock:
        p = _pending.get(uid)
    if p:
        if time.time() - float(p.get("ts") or 0) > _TTL:
            clear_pending(uid)
            return None
        return list(p.get("muc") or [])
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
        muc = json.loads(row[0] or "[]")
        with _lock:
            _pending[uid] = {"muc": muc, "ts": row[1]}
        return list(muc)
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


def resolve_reply(user_id: str, user_text: str) -> Optional[str]:
    """Người dùng vừa gõ một mã mục? → trả câu hỏi chi tiết cho mục đó."""
    t = (user_text or "").strip()
    if not t or len(t) > 8:
        return None
    m = _RE_CHON.match(t)
    if not m:
        return None
    ma = m.group(1).strip()
    if not ma:
        return None
    muc = get_pending(user_id)
    if not muc:
        return None
    for it in muc:
        if str(it.get("ma") or "").lower() == ma.lower():
            noi_dung = str(it.get("noi_dung") or "").strip()
            if not noi_dung:
                return None
            clear_pending(user_id)
            logger.info({"event": "muc_luc_chon", "ma": it.get("ma")})
            return (f'Xem chi tiết mục này: "{noi_dung}". '
                    "Tra cứu thêm rồi kể đầy đủ.")
    return None


def apply_to_result(result: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Đánh mã cho danh sách trong `result["text"]` và ghi bản chờ.

    Bỏ qua khi tin nhắn đã là MENU (`choices`): khối đó có đường chọn riêng của
    `ask_choices`, đánh thêm mã nữa là hai hệ số trong cùng một tin.
    """
    if not isinstance(result, dict):
        return result
    text = str(result.get("text") or "")
    if result.get("silent") or not text or result.get("choices"):
        return result
    moi, muc = danh_so(text)
    if not muc:
        return result
    result["text"] = moi
    result["muc_luc"] = True
    set_pending(user_id, muc)
    logger.info({"event": "muc_luc_danh_so", "so_muc": len(muc)})
    return result


def _reset_for_tests() -> None:
    with _lock:
        _pending.clear()
