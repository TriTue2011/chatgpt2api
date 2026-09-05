"""Sổ MỤC LỤC những thứ NGƯỜI DÙNG chủ động lưu — tìm lại theo MÔ TẢ.

Khác [[anh_cua_toi]] (ảnh AI tự tạo, lấy theo thời gian gần nhất): đây là thứ
người dùng CHỦ ĐỘNG lưu khi bấm «☁️ Lưu lên kho đám mây», kèm MÔ TẢ để sau gõ
"gửi ảnh thuốc" / "gửi tài liệu hợp đồng" tìm ra đúng cái — như mục lục một cuốn
sách: mỗi mục có nhãn để tra.

Sổ JSON theo người: ``{user_id: [ {ref, kind, mo_ta, ten, tu_khoa, ts}, … ]}``
(mới nhất trước, chặn `_MOI_NGUOI` mục mỗi người). ``kind`` = anh | tailieu |
thongtin. ``ref`` là thứ GỬI LẠI được: URL ảnh (images_dir, gateway phục vụ) cho
kind=anh; đường dẫn kho / link cho tài liệu. Mất sổ chỉ mất khả năng TRA, không
mất tệp (tệp vẫn nằm trên kho) — nên không cần bền bằng DB, JSON phẳng là đủ.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_MOI_NGUOI = 500          # mục lục lâu dài nên giữ nhiều hơn sổ ảnh AI
_lock = threading.Lock()

KIND_ANH = "anh"
KIND_TAILIEU = "tailieu"
KIND_THONGTIN = "thongtin"

_WORD_RE = re.compile(r"[\wÀ-ỹ]{2,}", re.UNICODE)
#: Từ đệm/hỏi bỏ khi tách khoá — giữ lại từ MANG NGHĨA ("thuốc", "hợp đồng").
_BO = {
    "gui", "cho", "toi", "minh", "anh", "chi", "em", "lai", "cai", "cua", "voi",
    "xem", "tim", "lay", "muon", "can", "do", "nay", "kia", "ay", "the", "la",
    "ve", "hinh", "anh", "tam", "tai", "lieu", "file", "tep", "thong", "tin",
    "va", "hay", "giup", "nhe", "nha", "a", "o", "di", "vao", "ra", "khong",
}


def _fold(s: str) -> str:
    b = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    k = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    return (s or "").lower().translate(str.maketrans(b, k))


def _khoa(s: str) -> list[str]:
    """Từ khoá mang nghĩa (đã bỏ dấu, bỏ từ đệm) để tra chồng khớp."""
    ra: list[str] = []
    for w in _WORD_RE.findall(str(s or "")):
        f = _fold(w)
        if f in _BO or f in ra:
            continue
        ra.append(f)
    return ra


def _duong():
    from pathlib import Path

    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "so_da_luu.json"


def _doc() -> dict[str, list[dict[str, Any]]]:
    try:
        p = _duong()
        if p.is_file():
            d = json.loads(p.read_text("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
    except Exception as exc:
        logger.warning("so_da_luu: đọc sổ lỗi: %s", exc)
    return {}


def _ghi_file(d: dict) -> None:
    try:
        p = _duong()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    except Exception as exc:
        logger.warning("so_da_luu: ghi sổ lỗi: %s", exc)


def ghi(user_id: str, *, ref: str, kind: str, mo_ta: str = "",
        ten: str = "", tu_khoa: str = "") -> bool:
    """Ghi một mục vào sổ của người này. Trả True nếu ghi được.

    ``ref`` là thứ gửi lại được (URL ảnh / đường dẫn kho); rỗng thì bỏ qua vì
    không tra ra để làm gì. ``tu_khoa`` là chữ bổ sung để tra (vd tên tệp gốc)."""
    uid = str(user_id or "").strip()
    r = str(ref or "").strip()
    if not uid or not r:
        return False
    muc = {
        "ref": r,
        "kind": str(kind or KIND_ANH),
        "mo_ta": str(mo_ta or "").strip()[:500],
        "ten": str(ten or "").strip()[:200],
        "tu_khoa": str(tu_khoa or "").strip()[:200],
        "ts": time.time(),
    }
    with _lock:
        d = _doc()
        ds = [m for m in (d.get(uid) or []) if isinstance(m, dict)]
        # Bỏ trùng theo ref (lưu lại đúng ảnh cũ thì cập nhật, không nhân đôi).
        ds = [m for m in ds if m.get("ref") != r]
        ds.insert(0, muc)
        d[uid] = ds[:_MOI_NGUOI]
        _ghi_file(d)
    return True


def _diem(muc: dict, khoa: list[str]) -> int:
    """Số từ khoá truy vấn khớp trong mô tả/tên/từ-khoá của mục."""
    if not khoa:
        return 0
    kho_muc = set(_khoa(" ".join([
        str(muc.get("mo_ta") or ""), str(muc.get("ten") or ""),
        str(muc.get("tu_khoa") or ""),
    ])))
    return sum(1 for k in khoa if k in kho_muc)


def tim(user_id: str, truy_van: str, *, kind: str = "", so: int = 3) -> list[dict]:
    """Các mục KHỚP mô tả nhất (điểm > 0), mới ưu tiên khi bằng điểm.

    ``kind`` lọc loại (anh/tailieu/thongtin); rỗng = mọi loại. Trả list mục
    (ref, kind, mo_ta, ten, ts). Rỗng nếu không có gì khớp."""
    uid = str(user_id or "").strip()
    khoa = _khoa(truy_van)
    if not uid or not khoa:
        return []
    ds = [m for m in _doc().get(uid) or [] if isinstance(m, dict)]
    if kind:
        ds = [m for m in ds if str(m.get("kind")) == kind]
    ghi_diem = [(m, _diem(m, khoa)) for m in ds]
    khop = [(m, d) for m, d in ghi_diem if d > 0]
    # Điểm cao trước; bằng điểm thì mới trước (ds vốn mới-trước nên giữ index).
    khop.sort(key=lambda md: md[1], reverse=True)
    return [m for m, _ in khop[: max(1, so)]]


def liet_ke(user_id: str, *, kind: str = "", so: int = 20) -> list[dict]:
    """Các mục gần nhất (không tra) — cho «đã lưu gì rồi»."""
    uid = str(user_id or "").strip()
    if not uid:
        return []
    ds = [m for m in _doc().get(uid) or [] if isinstance(m, dict)]
    if kind:
        ds = [m for m in ds if str(m.get("kind")) == kind]
    return ds[: max(1, so)]


# ── Trạng thái HỎI-KHI-LƯU và CHỌN-KHI-TÌM (trong RAM, ngắn hạn) ────────────
# Chủ máy chốt: lúc lưu thì HỎI mô tả (cho bỏ qua); lúc tìm nhiều thì cho CHỌN,
# không gửi tất cả. Hai trạng thái này sống theo người, TTL ngắn; mất (restart)
# thì chỉ lỡ một lượt hỏi/chọn, không hại dữ liệu.
_CHO_TTL = 600.0
_cho_mo_ta: dict[str, dict] = {}     # user → {ref, ten, kind, ts}
_cho_chon: dict[str, dict] = {}      # user → {items:[{ref,mo_ta,kind,ten}], ts}


def _tuoi_ok(rec: dict | None) -> bool:
    return bool(rec) and (time.time() - float(rec.get("ts", 0)) <= _CHO_TTL)


def dat_cho_mo_ta(user_id: str, *, ref: str, ten: str = "",
                  kind: str = KIND_ANH) -> None:
    """Vừa lưu một thứ, đang CHỜ người dùng nhập mô tả để ghi mục lục."""
    uid = str(user_id or "").strip()
    if uid and ref:
        _cho_mo_ta[uid] = {"ref": ref, "ten": ten, "kind": kind, "ts": time.time()}


def dat_cho_chon(user_id: str, items: list[dict]) -> None:
    """Tìm ra NHIỀU mục, đang CHỜ người dùng chọn số để gửi."""
    uid = str(user_id or "").strip()
    if uid and items:
        _cho_chon[uid] = {"items": list(items)[:9], "ts": time.time()}


def _la_bo_qua(text: str) -> bool:
    return _fold(text) in {
        "thoi", "bo", "bo qua", "khong", "khong can", "huy", "thoi khoi",
        "khoi", "skip", "k", "ko",
    }


def xu_ly_tra_loi(user_id: str, text: str) -> dict | None:
    """Câu này có phải trả lời cho bước HỎI-mô-tả / CHỌN-số của mục lục không?

    Trả None nếu không liên quan (để kênh xử lý bình thường). Ngược lại trả
    ``{"text": ..., ["image_url": ...]}`` để kênh gửi — và đã dọn trạng thái."""
    uid = str(user_id or "").strip()
    t = str(text or "").strip()
    if not uid or not t:
        return None

    # (1) Đang chờ CHỌN số sau khi tìm ra nhiều mục.
    rec = _cho_chon.get(uid)
    if _tuoi_ok(rec):
        import re as _re
        m = _re.match(r"^\s*(\d{1,2})\b", t)
        if m:
            i = int(m.group(1)) - 1
            items = rec.get("items") or []
            if 0 <= i < len(items):
                _cho_chon.pop(uid, None)
                muc = items[i]
                nhan = str(muc.get("mo_ta") or muc.get("ten") or "đã lưu")[:120]
                if muc.get("kind") == KIND_ANH:
                    return {"text": f"Đây ạ — {nhan} 🖼️", "image_url": str(muc.get("ref"))}
                return {"text": f"• {nhan} (đã lưu trên kho đám mây)"}
        # Không phải một con số hợp lệ → thôi chờ chọn, để câu đi tiếp bình thường.
        _cho_chon.pop(uid, None)

    # (2) Đang chờ MÔ TẢ sau khi vừa lưu.
    rec = _cho_mo_ta.get(uid)
    if _tuoi_ok(rec):
        from services.yeu_cau_moi import la_yeu_cau_moi
        # Câu là yêu cầu MỚI (có động từ ra lệnh) → không phải mô tả: lưu theo tên
        # rồi để câu đi tiếp.
        if la_yeu_cau_moi(t):
            _cho_mo_ta.pop(uid, None)
            ghi(uid, ref=str(rec.get("ref")), kind=str(rec.get("kind") or KIND_ANH),
                mo_ta="", ten=str(rec.get("ten") or ""), tu_khoa=str(rec.get("ten") or ""))
            return None
        _cho_mo_ta.pop(uid, None)
        if _la_bo_qua(t):
            ghi(uid, ref=str(rec.get("ref")), kind=str(rec.get("kind") or KIND_ANH),
                mo_ta="", ten=str(rec.get("ten") or ""), tu_khoa=str(rec.get("ten") or ""))
            return {"text": "Vâng, em lưu rồi ạ (tìm lại theo tên tệp cũng được)."}
        ghi(uid, ref=str(rec.get("ref")), kind=str(rec.get("kind") or KIND_ANH),
            mo_ta=t, ten=str(rec.get("ten") or ""), tu_khoa=str(rec.get("ten") or ""))
        goi = t.split()[0] if t.split() else "…"
        return {"text": f"Đã ghi vào mục lục: «{t[:80]}» ✅ Sau anh/chị nhắn "
                        f"«gửi ảnh {goi}» là em tìm ra ạ."}

    return None
