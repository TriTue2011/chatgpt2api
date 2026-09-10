"""Sổ tên dùng chung — bot học "cái mã này là ai/là gì" cho MỌI nguồn.

Chủ máy ra quy tắc 10/09/2026: *"từ giờ tôi nói về 1 thiết bị nhưng khi code
phải mở rộng toàn bộ trong học tập thói quen của BOT"*.

Số liệu chứng minh quy tắc đó đúng: nhà có **1.068 thực thể**, trong đó **101
cái tên còn khó hiểu với người** (``EVN VN Device (PM110000486``,
``Homeassistant (-1002793479``…). Không riêng khoá cửa. Viết một sổ tên cho mỗi
loại thiết bị là không khả thi.

Module này là phần TỔNG QUÁT tách ra từ ``khoa_cua_nha`` — vòng «gặp thứ chưa
biết → hỏi một lần → nhớ mãi», áp cho khoá cửa, khuôn mặt camera, thiết bị MQTT
mới, số lạ gọi tới, và bất cứ thứ gì thêm sau.

═══ VÌ SAO KHOÁ PHẢI CÓ NGUỒN ═══

``khoa_cua_nha`` cũ dùng khoá ``fingerprint#11`` — không có nguồn. Thêm khuôn
mặt Frigate là đụng ngay: ``face#17`` của Tuya và ``face#17`` của Frigate đè
nhau, hai người khác nhau thành một. Khoá ở đây là ``nguồn:loại#mã``.

Học từ ``channel_contacts.contact_key`` (services/channel_contacts.py:89) —
sổ danh bạ đã giải đúng bài này cho kênh chat.

═══ VÌ SAO KHÔNG MƯỢN ``pham_vi`` CỦA TRÍ NHỚ ═══

``state.nho_hoac_cap_nhat(..., pham_vi=)`` nhìn qua tưởng dùng được làm không
gian tên. Không: ``pham_vi`` đã bị chiếm để tách theo NGƯỜI DÙNG — mọi chỗ gọi
đều truyền ``_pham_vi(user_id)`` (orchestrator.py:872, distill.py:267). Một
``pham_vi`` không thể vừa là người vừa là loại dữ liệu. Nhét cả hai vào thì
orchestrator không đọc được fact đó nữa.

Nên tên máy-móc lưu ở sổ CÓ CẤU TRÚC này, còn trí nhớ chung chỉ nhận thêm một
câu tiếng Việt cho người đọc.

═══ HAI CỜ, KHÔNG PHẢI MỘT BỘ ĐẾM ═══

``da_biet`` (đã có tên) tách khỏi ``so_lan_hoi`` (đã hỏi mấy lần). Gộp làm một
thì không phân biệt được «đã hỏi mà chưa ai trả lời» với «chủ nhà bảo thôi đừng
hỏi nữa». Học từ cặp ``known``/``notified`` của channel_contacts.
"""

from __future__ import annotations

import json
import logging
import threading
import re
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_FILE = Path(DATA_DIR) / "agent" / "so_ten_nha.json"
_khoa = threading.RLock()

#: Hỏi tối đa ngần này lần cho MỘT thứ. Hỏi mãi mà không ai trả lời thì thôi —
#: nài thêm chỉ làm phiền, và nhà có 101 thứ chưa biết tên.
_HOI_TOI_DA = 3

#: Chỉ hỏi tên thứ HAY DÙNG. Chủ máy chốt 10/09/2026: không hỏi hết 101 cái.
#: Cảm biến kỹ thuật xuất hiện một lần thì bỏ qua.
_TOI_THIEU_LAN = 3

#: Tên do nhà sản xuất đặt sẵn mà vẫn KHÓ HIỂU với người — coi như chưa có tên.
#: Đo trên HA nhà chủ máy: 101/1068 thực thể rơi vào đây.
_TEN_MAY_MOC = ("device", "unknown", "unnamed", "sensor", "entity")


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("so_ten")
    return raw if isinstance(raw, dict) else {}


def _hoi_toi_da() -> int:
    try:
        return max(1, int(_cfg().get("hoi_toi_da") or _HOI_TOI_DA))
    except (TypeError, ValueError):
        return _HOI_TOI_DA


def _toi_thieu_lan() -> int:
    try:
        return max(1, int(_cfg().get("toi_thieu_lan") or _TOI_THIEU_LAN))
    except (TypeError, ValueError):
        return _TOI_THIEU_LAN


# ── Sổ trên đĩa ─────────────────────────────────────────────────────────────
def _doc() -> dict[str, Any]:
    try:
        with open(_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ghi(d: dict[str, Any]) -> None:
    """Ghi nguyên tử: .tmp rồi replace. Khuôn của channel_contacts."""
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        tmp.replace(_FILE)
    except OSError as exc:
        logger.warning({"event": "so_ten_ghi_loi", "error": str(exc)[:160]})


def khoa(nguon: str, loai: str, ma: str) -> str:
    """Khoá định danh: ``nguồn:loại#mã``.

    Có nguồn nên ``tuya:unlock#17`` khác ``frigate:face#17`` — hai người khác
    nhau không bị đè.
    """
    n = str(nguon or "?").strip().lower()
    l = str(loai or "?").strip().lower()
    return f"{n}:{l}#{str(ma or '').strip()}"


def _tach(k: str) -> tuple[str, str, str]:
    nguon, _, con = k.partition(":")
    loai, _, ma = con.partition("#")
    return nguon, loai, ma


def ten_may_moc(ten: str) -> bool:
    """Tên này có phải chỉ là mã kỹ thuật không?

    Nhà sản xuất đặt sẵn "EVN VN Device (PM110000486" thì với người vẫn là chưa
    có tên. Trả True nghĩa là NÊN hỏi.
    """
    t = str(ten or "").strip()
    if not t:
        return True
    thap = t.lower()
    # Nhiều chữ số liền, hoặc mã hex dài → mã máy.
    so = sum(1 for c in t if c.isdigit())
    if so >= 6:
        return True
    return any(k in thap for k in _TEN_MAY_MOC) and so >= 2


# ── Ba tầng tra tên ─────────────────────────────────────────────────────────
def ten_cua(nguon: str, loai: str, ma: str, ten_goc: str = "",
            *, user_id: str = "") -> str:
    """Tên người đọc hiểu. Rỗng = CHƯA BIẾT, tầng trên sẽ hỏi.

    Ba tầng: tên nhà sản xuất trả về → sổ này → trí nhớ chung.
    """
    if ten_goc.strip() and not ten_may_moc(ten_goc):
        return ten_goc.strip()

    k = khoa(nguon, loai, ma)
    with _khoa:
        t = str(((_doc().get("muc") or {}).get(k) or {}).get("ten") or "").strip()
    if t:
        return t

    # Tầng cuối: chủ máy từng nói trong chat.
    #
    # Hai lỗi thật ở bản trước, đo 10/09/2026 khi chủ máy dạy "mặt số 17 là vợ
    # tôi" lúc 08h33 mà 11h32 bot vẫn hỏi lại:
    #
    #   1. Không truyền `pham_vi` nên chỉ tra kho CHUNG, trong khi bot ghi vào
    #      kho RIÊNG của người dạy (`data/agent/memory/<băm>.md`). Câu đã ghi
    #      đúng, chỉ là không ai đọc tới.
    #   2. Lọc bằng `f"{loai} {ma}"` tức chuỗi "face 17", nhưng câu tiếng Việt
    #      bot ghi là "Khuôn mặt số 17…" — không bao giờ khớp.
    #
    # Nay tra bằng MÔ TẢ TIẾNG VIỆT ("khuôn mặt 17"), và quét cả kho riêng của
    # từng người đã dạy: sổ tên là của CẢ NHÀ, ai dạy cũng phải dùng được.
    mo = mo_ta(k)
    try:
        from services.agent import state
        for pv in _pham_vi_tra(user_id):
            for dong in (state.search_memory(mo, pham_vi=pv) or [])[:5]:
                t = _tach_ten(str(dong), mo, k, ma)
                if t:
                    return t
    except Exception:
        pass
    return ""


def _pham_vi_tra(user_id: str = "") -> list[str]:
    """Các kho trí nhớ cần quét, kho chung trước rồi tới kho của người dạy.

    Rỗng ("") là kho chung. Không có `user_id` thì quét thêm mọi kho riêng đã
    từng ghi tên — sổ tên dùng chung cả nhà nên người này dạy, người kia hỏi
    vẫn phải ra.
    """
    ra: list[str] = [""]
    if user_id:
        try:
            from services.agent import scope
            for pv in [scope.khoa_du_lieu(user_id),
                       *(scope.pham_vi_doc_them(user_id) or [])]:
                if pv and pv not in ra:
                    ra.append(pv)
        except Exception:
            pass
    with _khoa:
        for pv in (_doc().get("pham_vi_da_day") or []):
            if pv and pv not in ra:
                ra.append(pv)
    return ra


def loai_cua(k: str) -> str:
    """Khoá → phần LOẠI ('tuya:face#17' → 'face')."""
    return _tach(k)[1]


def _tach_ten(dong: str, mo: str, k: str, ma: str) -> str:
    """Lấy tên người từ một dòng trí nhớ, hoặc rỗng nếu dòng không nói về nó.

    Khớp theo TỪ chứ không theo chuỗi liền: mô tả sinh ra là "khuôn mặt 17"
    nhưng câu bot ghi là "Khuôn mặt SỐ 17…" — chèn đúng một chữ "số" là chuỗi
    liền trượt, mà đó lại là cách bot viết tự nhiên nhất.
    """
    low = dong.lower()
    if k not in dong:
        # Mọi từ của mô tả phải có mặt, không cần liền nhau. Chấp nhận CẢ hai
        # cách viết: tiếng Việt ("khuôn mặt số 17" — cách bot ghi thật) và mã
        # máy ("face 17" — trí nhớ cũ, hoặc chỗ khác trong bot ghi).
        hop = [mo.lower().split(), [loai_cua(k).lower(), str(ma).lower()]]
        if not any(all(w in low for w in bo) for bo in hop if all(bo)):
            return ""
    # Phải có ĐÚNG con số này, tách bạch: "17" không được khớp "170" hay "1".
    if ma and not re.search(rf"(?<!\d){re.escape(str(ma))}(?!\d)", dong):
        return ""
    phan = dong.split(" là ")
    if len(phan) < 2:
        return ""
    return phan[-1].strip().rstrip(".")[:60]


def dat_ten(nguon: str, loai: str, ma: str, ten: str,
            *, user_id: str = "") -> bool:
    """Chủ nhà xác nhận. Đây là bước TỰ HỌC của cả hệ.

    Lưu vào sổ, thôi hỏi, và phát một câu tiếng Việt vào trí nhớ để chỗ khác
    trong bot cũng dùng được. Có `user_id` thì ghi vào ĐÚNG kho riêng của
    người đó — cùng kho mà bot ghi khi học qua chat — và nhớ phạm vi ấy lại
    để `ten_cua` biết đường quét.
    """
    ten = (ten or "").strip()
    if not ma or not ten:
        return False
    k = khoa(nguon, loai, ma)
    with _khoa:
        so = _doc()
        muc = so.setdefault("muc", {})
        m = muc.setdefault(k, {})
        m.update({"ten": ten, "da_biet": True, "nguon": nguon, "loai": loai,
                  "ma": str(ma), "dat_luc": time.time()})
        m["so_lan_hoi"] = 0          # đặt tên rồi thì bộ đếm hết ý nghĩa
        _ghi(so)

    pv = ""
    if user_id:
        try:
            from services.agent import scope
            pv = scope.khoa_du_lieu(str(user_id))
        except Exception:
            pv = ""
    try:
        from services.agent import state
        state.nho_hoac_cap_nhat(f"{mo_ta(k)} là {ten}", who="so_ten_nha",
                                pham_vi=pv)
    except Exception:
        pass
    if pv:
        with _khoa:
            so = _doc()
            ds = so.setdefault("pham_vi_da_day", [])
            if pv not in ds:
                ds.append(pv)
                _ghi(so)
    logger.info({"event": "so_ten_dat", "khoa": k, "ten": ten})
    return True


def mo_ta(k: str) -> str:
    """Khoá → câu tiếng Việt. Loại lạ thì hiện nguyên, KHÔNG bịa."""
    nguon, loai, ma = _tach(k)
    nhan = _NHAN_LOAI.get(loai, loai)
    return f"{nhan} {ma}" if ma else nhan


#: Nhãn tiếng Việt cho loại đã biết. Thêm loại mới chỉ là thêm một dòng —
#: loại chưa có ở đây vẫn chạy, chỉ hiện nguyên mã.
_NHAN_LOAI = {
    "unlock": "cách mở khoá", "fingerprint": "vân tay", "face": "khuôn mặt",
    "password": "mật khẩu", "card": "thẻ từ", "key": "chìa cơ",
    "khuon_mat": "khuôn mặt", "nguoi": "người", "thiet_bi": "thiết bị",
    "cuoc_goi": "số gọi tới", "camera": "camera", "cam_bien": "cảm biến",
}


# ── Van chống làm phiền ─────────────────────────────────────────────────────
def da_biet(k: str) -> bool:
    with _khoa:
        return bool(((_doc().get("muc") or {}).get(k) or {}).get("da_biet"))


def nen_hoi(k: str) -> bool:
    """Còn được hỏi tên thứ này không?"""
    with _khoa:
        m = (_doc().get("muc") or {}).get(k) or {}
    if m.get("da_biet") or m.get("thoi_hoi"):
        return False
    return int(m.get("so_lan_hoi") or 0) < _hoi_toi_da()


def danh_dau_da_hoi(k: str) -> None:
    with _khoa:
        so = _doc()
        m = so.setdefault("muc", {}).setdefault(k, {})
        m["so_lan_hoi"] = int(m.get("so_lan_hoi") or 0) + 1
        m["hoi_lan_cuoi"] = time.time()
        _ghi(so)


def thoi_hoi(k: str) -> None:
    """Chủ nhà bảo «để sau» — khác với «đã hỏi 3 lần không ai trả lời»."""
    with _khoa:
        so = _doc()
        so.setdefault("muc", {}).setdefault(k, {})["thoi_hoi"] = True
        _ghi(so)


def dang_hoi_duoc(k: str, so_lan_thay: int) -> bool:
    """Thứ này có đáng hỏi không — CHỈ HỎI THỨ HAY DÙNG.

    Chủ máy chốt 10/09/2026: không hỏi hết 101 thứ chưa biết tên. Cảm biến kỹ
    thuật xuất hiện một hai lần thì bỏ qua; thứ vào ra vài lần mỗi tuần mới
    đáng có tên.
    """
    return so_lan_thay >= _toi_thieu_lan() and nen_hoi(k)


# ── Đọc sổ ──────────────────────────────────────────────────────────────────
def danh_sach(nguon: str = "") -> list[dict[str, Any]]:
    with _khoa:
        muc = (_doc().get("muc") or {})
    ra = []
    for k, m in muc.items():
        n, l, ma = _tach(k)
        if nguon and n != nguon.lower():
            continue
        ra.append({"khoa": k, "nguon": n, "loai": l, "ma": ma,
                   "ten": m.get("ten") or "", "da_biet": bool(m.get("da_biet")),
                   "so_lan_hoi": int(m.get("so_lan_hoi") or 0),
                   "thoi_hoi": bool(m.get("thoi_hoi")),
                   # Lộ ra để `soi_loi_ngam` đối chiếu được: bot nói "em nhớ
                   # rồi" lúc nào thì sổ phải có mục đặt đúng lúc đó.
                   "dat_luc": float(m.get("dat_luc") or 0)})
    ra.sort(key=lambda x: (not x["da_biet"], x["nguon"], x["ma"]))
    return ra


def thong_ke() -> dict[str, Any]:
    ds = danh_sach()
    return {
        "tong": len(ds),
        "da_biet": sum(1 for d in ds if d["da_biet"]),
        "chua_biet": sum(1 for d in ds if not d["da_biet"]),
        "thoi_hoi": sum(1 for d in ds if d["thoi_hoi"]),
    }


def _chuyen_doi_so_cu() -> int:
    """Nạp sổ cũ của khoa_cua_nha sang khoá mới có nguồn.

    Sổ cũ dùng khoá ``fingerprint#11`` (không nguồn). Không chuyển thì chủ máy
    phải dạy lại từ đầu những tên đã dạy.
    """
    cu = Path(DATA_DIR) / "agent" / "khoa_cua_nha.json"
    try:
        with open(cu, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return 0
    ten_cu = (d or {}).get("ten") or {}
    n = 0
    with _khoa:
        so = _doc()
        muc = so.setdefault("muc", {})
        for ma_cu, ten in ten_cu.items():
            cach, _, so_hieu = str(ma_cu).partition("#")
            k = khoa("tuya", cach or "unlock", so_hieu or ma_cu)
            if k in muc:
                continue
            muc[k] = {"ten": ten, "da_biet": True, "nguon": "tuya",
                      "loai": cach or "unlock", "ma": so_hieu or ma_cu,
                      "so_lan_hoi": 0, "dat_luc": time.time()}
            n += 1
        if n:
            _ghi(so)
    if n:
        logger.info({"event": "so_ten_chuyen_doi", "so_muc": n})
    return n


def _reset_for_tests() -> None:
    with _khoa:
        try:
            _FILE.unlink()
        except OSError:
            pass
