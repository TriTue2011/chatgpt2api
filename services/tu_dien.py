"""Tra từ điển Anh–Việt tại chỗ — cho ô tra cứu bên cạnh bản dịch máy.

Vì sao có module này, khi đã có máy dịch: máy dịch phải CHỌN một nghĩa, còn
người tra một từ thường cần THẤY CẢ CÁC NGHĨA rồi tự chọn. "stroke" có ít nhất
mười nghĩa thông dụng (đột quỵ, cú đánh, nét bút, kiểu bơi, vuốt ve…) — không
ngữ cảnh thì không engine nào đoán đúng được, và đoán sai thì người dùng không
có cách nào biết là nó đã bỏ mất nghĩa nào.

Cặp đôi với ``services/thuat_ngu.py``: tra ra nghĩa đúng rồi bấm "dùng nghĩa
này" là ghi vào ``<src>.sua.json``, từ lượt sau máy dịch luôn ra đúng chữ đó.

Dữ liệu là SQLite đọc-chỉ ở ``<data>/tudien/en-vi.db`` — KHÔNG nằm trong image
(``.dockerignore`` loại ``/data``) và không commit vào git (``*.db``). Cài bằng
``scripts/tai_tu_dien.py``. Thiếu tệp thì tính năng tự tắt, mọi thứ khác chạy
như cũ.

Nguồn: skypediacode/english-vietnamese-dictionary (CC BY-SA 4.0) — ghi nguồn ở
``docs/TU_DIEN.md``. Lược đồ 4 bảng: ``words`` (từ gốc), ``definitions`` (nghĩa
Việt + từ loại), ``word_definitions`` (nối, kèm câu ví dụ), ``pronunciations``
(IPA).
"""
from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

#: Tiếng nguồn có từ điển. Kho hiện tại chỉ có Anh–Việt; thêm tiếng khác là thả
#: thêm tệp ``<src>-vi.db`` cùng lược đồ vào đây.
TIENG_CO_TU_DIEN = ("en",)

#: Trần số nghĩa trả về. Từ như "set" có hàng chục nghĩa — liệt kê hết thì ô tra
#: cứu dài hơn cả bản dịch, mà nghĩa xếp sau gần như không ai dùng.
TOI_DA_NGHIA = 15

#: Mã từ loại của kho → nhãn tiếng Việt. Mã lạ giữ nguyên chứ không đoán bừa.
TU_LOAI: dict[str, str] = {
    "N": "danh từ", "noun": "danh từ", "n": "danh từ",
    "V": "động từ", "verb": "động từ",
    "A": "tính từ", "adj": "tính từ",
    "D": "trạng từ", "adv": "trạng từ",
    "idiom": "thành ngữ",
    "P": "giới từ", "C": "liên từ", "pron": "đại từ",
}


def _duong_dan(src: str) -> Path:
    """Đường tới tệp từ điển. Đọc ``DATA_DIR`` lúc gọi để test chỉnh được."""
    import services.config as _cfg
    return _cfg.DATA_DIR / "tudien" / f"{src}-vi.db"


def co_tu_dien(src: str = "en") -> bool:
    """Có tệp từ điển cho tiếng này không. Không có = ô tra cứu ẩn đi."""
    src = str(src or "").lower().strip()
    return src in TIENG_CO_TU_DIEN and _duong_dan(src).is_file()


def _chuan(s: str) -> str:
    return unicodedata.normalize("NFC", str(s or "")).strip().lower()


def _dang_goc(tu: str) -> list[str]:
    """Các dạng gốc có thể của một từ đã chia, theo thứ tự nên thử.

    Kho tra theo TỪ GỐC nên "strokes"/"stroked" tra thẳng là trượt. Đây là bộ
    quy tắc hình thái tối thiểu cho tiếng Anh, cố ý không dùng thư viện lemmatize
    (kéo theo NLTK/spacy chỉ để cắt vài hậu tố thì không đáng).
    """
    ra: list[str] = []

    def them(x: str) -> None:
        if x and len(x) > 1 and x not in ra:
            ra.append(x)

    if tu.endswith("ies") and len(tu) > 4:
        them(tu[:-3] + "y")
    if tu.endswith("es") and len(tu) > 3:
        them(tu[:-2])
    if tu.endswith("s") and not tu.endswith("ss"):
        them(tu[:-1])
    if tu.endswith("ing"):
        them(tu[:-3])
        them(tu[:-3] + "e")
    if tu.endswith("ed"):
        them(tu[:-2])
        them(tu[:-1])
    if tu.endswith("er") or tu.endswith("est"):
        them(tu[:-2] if tu.endswith("er") else tu[:-3])
    # Phụ âm gấp đôi trước đuôi: "stopped" → "stop", "running" → "run".
    m = re.match(r"^(.*?)([bcdfglmnprst])\2(?:ed|ing)$", tu)
    if m:
        them(m.group(1) + m.group(2))
    return ra


def _tra_dung_tu(cur: sqlite3.Cursor, tu: str) -> list[dict[str, str]]:
    """Nghĩa của ĐÚNG dạng chữ này (không thử dạng gốc). Rỗng nếu không có."""
    hang = cur.execute(
        "SELECT d.definition, d.pos, wd.example "
        "FROM words w "
        "JOIN word_definitions wd ON wd.word_id = w.id "
        "JOIN definitions d ON d.id = wd.definition_id "
        "WHERE w.word = ? LIMIT ?",
        (tu, TOI_DA_NGHIA),
    ).fetchall()
    return [{"vi": str(r[0] or "").strip(),
             "tu_loai": TU_LOAI.get(str(r[1] or ""), str(r[1] or "")),
             "vi_du": str(r[2] or "").strip()}
            for r in hang if str(r[0] or "").strip()]


def tra(tu: str, src: str = "en") -> dict:
    """Tra một từ/cụm → nghĩa tiếng Việt, từ loại, câu ví dụ, IPA.

    Trả::

        {"tu": "stroke",        # dạng THỰC SỰ tra được (có thể là dạng gốc)
         "goc": "strokes",      # chữ người dùng gõ, chỉ có khi khác "tu"
         "ipa": "/strəʊk/",
         "nghia": [{"vi": "Đột quỵ.", "tu_loai": "danh từ", "vi_du": "…"}]}

    Không có từ điển, hoặc không tìm thấy → ``nghia`` rỗng. Không ném lỗi ra
    ngoài: đây là tính năng phụ, hỏng thì ô tra cứu trống chứ không được làm
    đứt lượt dịch.
    """
    goc = _chuan(tu)
    src = str(src or "").lower().strip()
    ra: dict = {"tu": goc, "ipa": "", "nghia": []}
    if not goc or not co_tu_dien(src):
        return ra
    try:
        with sqlite3.connect(f"file:{_duong_dan(src)}?mode=ro", uri=True) as db:
            cur = db.cursor()
            nghia = _tra_dung_tu(cur, goc)
            dung = goc
            if not nghia:
                for ung_vien in _dang_goc(goc):
                    nghia = _tra_dung_tu(cur, ung_vien)
                    if nghia:
                        dung, ra["goc"] = ung_vien, goc
                        break
            if not nghia:
                return ra
            ipa = cur.execute(
                "SELECT p.ipa FROM words w JOIN pronunciations p ON p.word_id = w.id "
                "WHERE w.word = ? LIMIT 1", (dung,)).fetchone()
            ra["tu"], ra["nghia"] = dung, nghia
            ra["ipa"] = str(ipa[0]) if ipa else ""
    except sqlite3.Error as exc:
        logger.warning("tra từ điển '%s' lỗi: %s", goc, str(exc)[:200])
    return ra
