"""Cảnh báo thiết bị hỏng — báo dồn thưa dần, và người dùng tắt được từng lỗi.

VÌ SAO KHÔNG BÁO NGAY MỖI LẦN: đo trên nhà chủ máy 09/09/2026 có 24 cảm biến
chết, 63 đơ, 69 chập chờn. Báo mỗi cái một tin là 156 tin một lượt, người dùng
tắt thông báo và từ đó không bao giờ thấy cái quan trọng nữa.

NHỊP BÁO LẠI (chủ máy chốt): 5 phút → 30 phút → 60 phút → 6 giờ → rồi mỗi
ngày. Lỗi mới báo nhanh vì có thể chữa ngay; lỗi cũ giãn dần vì đã biết rồi.

TẮT ĐƯỢC TỪNG LỖI: mỗi tin kèm lựa chọn "tôi biết rồi". Bấm là im về ĐÚNG lỗi
đó. Nhưng nếu thiết bị KHỎI rồi HỎNG LẠI thì báo tiếp — vì đó là lỗi mới, không
phải cái đã tắt. Chỗ này là mấu chốt: tắt vĩnh viễn theo tên thiết bị thì sau
khi sửa xong hỏng lại sẽ im luôn, mà đó đúng là lúc cần biết nhất.

Phân biệt bằng ``lan_hong``: mỗi lần thiết bị chuyển từ lành sang hỏng thì số
này tăng. "Tôi biết rồi" chỉ tắt đúng lượt hỏng đang diễn ra.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=7))
_FILE = Path(DATA_DIR) / "agent" / "canh_bao_nha.json"
_khoa = threading.RLock()

# Nhịp báo lại, tính bằng giây. Hết bậc thì lặp bậc cuối (mỗi ngày).
_NHIP = (5 * 60, 30 * 60, 60 * 60, 6 * 3600, 24 * 3600)

_MAC_DINH_GIO_HANG_NGAY = 8  # giờ VN, dùng khi đã lên bậc "mỗi ngày"


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("canh_bao")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", True))


def _kenh() -> str:
    """'telegram' | 'zalo' | '' (rỗng = dùng kênh mặc định của reminders)."""
    return str(_cfg().get("kenh") or "").strip()


def _nguoi_nhan() -> list[str]:
    raw = _cfg().get("nguoi_nhan")
    if isinstance(raw, list) and raw:
        return [str(x).strip() for x in raw if str(x).strip()]
    # Không khai riêng thì dùng admin của heartbeat — đỡ phải cấu hình hai chỗ.
    try:
        from services.agent import heartbeat
        return heartbeat.admin_user_ids()
    except Exception:
        return []


def _gio_hang_ngay() -> int:
    """Đến bậc 'mỗi ngày' thì báo vào giờ nào (giờ VN)."""
    raw = _cfg().get("gio_hang_ngay")
    if raw is None:
        return _MAC_DINH_GIO_HANG_NGAY
    try:
        return max(0, min(23, int(raw)))
    except (TypeError, ValueError):
        return _MAC_DINH_GIO_HANG_NGAY


def _toi_da_moi_lan() -> int:
    try:
        return max(1, int(_cfg().get("toi_da_moi_lan") or 5))
    except (TypeError, ValueError):
        return 5


# ── Trạng thái trên đĩa ─────────────────────────────────────────────────────
def _doc() -> dict[str, Any]:
    try:
        with open(_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ghi(d: dict[str, Any]) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        tmp.replace(_FILE)          # thay nguyên tệp — khuôn của skill_quality
    except OSError as exc:
        logger.warning({"event": "canh_bao_ghi_loi", "error": str(exc)[:200]})


def _khoa_loi(h: dict[str, Any]) -> str:
    """Khoá định danh MỘT lỗi: thiết bị + trường + loại hỏng."""
    return f"{h.get('thiet_bi')}\x00{h.get('truong')}\x00{h.get('loai')}"


def _mo_ta(h: dict[str, Any]) -> str:
    ten = str(h.get("thiet_bi") or "?")
    tr = str(h.get("truong") or "")
    nhan = {"chet": "🔴 chết hẳn", "do": "🟠 đơ (vẫn báo nhưng số không đổi)",
            "chap_chon": "🟡 chập chờn"}.get(str(h.get("loai")), str(h.get("loai")))
    ct = str(h.get("chi_tiet") or "")
    return f"{nhan} — {ten}" + (f" · {tr}" if tr and tr != "state" else "") + f"\n   {ct}"


# ── Nhịp báo lại ────────────────────────────────────────────────────────────
def _den_han(ban_ghi: dict[str, Any], now: float) -> bool:
    """Đã tới lúc báo lại lỗi này chưa?"""
    if ban_ghi.get("im_lan") == ban_ghi.get("lan_hong"):
        return False                       # người dùng đã bấm "tôi biết rồi"

    lan_cuoi = float(ban_ghi.get("bao_cuoi") or 0)
    if not lan_cuoi:
        return True                        # chưa báo lần nào

    bac = int(ban_ghi.get("bac") or 0)
    if bac >= len(_NHIP) - 1:
        # Bậc cuối = mỗi ngày, và phải rơi vào GIỜ người dùng chọn, không phải
        # đúng 24 tiếng sau lần trước (nếu không giờ báo trôi dần mỗi ngày).
        if now - lan_cuoi < 20 * 3600:
            return False
        return datetime.fromtimestamp(now, _TZ).hour == _gio_hang_ngay()
    return now - lan_cuoi >= _NHIP[bac]


def quet(so_ngay: int = 7) -> dict[str, Any]:
    """Soi thiết bị hỏng, cập nhật sổ, trả về những lỗi ĐẾN HẠN báo.

    Trả ``{"can_bao": [...], "tong_hong": n, "dang_im": m}``. Không tự gửi —
    gửi là việc của ``chay_mot_lan`` để test tách được hai phần.
    """
    from services import lich_su_nha

    now = time.time()
    try:
        hong = lich_su_nha.soi_hong(so_ngay)
    except Exception as exc:
        logger.warning({"event": "canh_bao_soi_loi", "error": str(exc)[:200]})
        return {"can_bao": [], "tong_hong": 0, "dang_im": 0, "loi": str(exc)[:200]}

    with _khoa:
        so = _doc()
        muc: dict[str, Any] = so.get("muc") or {}
        dang_hong = {_khoa_loi(h): h for h in hong}

        # Thiết bị đã KHỎI: xoá cờ im lặng để lần hỏng sau còn báo được.
        for k, bg in list(muc.items()):
            if k not in dang_hong:
                if bg.get("dang_hong"):
                    bg["dang_hong"] = False
                    bg["khoi_luc"] = now
                    bg["bac"] = 0
                    bg["bao_cuoi"] = 0

        can_bao = []
        for k, h in dang_hong.items():
            bg = muc.get(k) or {"lan_hong": 0, "bac": 0, "bao_cuoi": 0,
                                "im_lan": None, "dang_hong": False}
            if not bg.get("dang_hong"):
                # Lành → hỏng: đây là LƯỢT HỎNG MỚI. Tăng lan_hong nên cờ im
                # lặng của lượt trước hết hiệu lực — sửa xong hỏng lại VẪN báo.
                bg["lan_hong"] = int(bg.get("lan_hong") or 0) + 1
                bg["dang_hong"] = True
                bg["hong_tu"] = now
                bg["bac"] = 0
                bg["bao_cuoi"] = 0
            bg["chi_tiet"] = h.get("chi_tiet")
            muc[k] = bg
            if _den_han(bg, now):
                can_bao.append((k, h))

        so["muc"] = muc
        so["quet_cuoi"] = now
        _ghi(so)
        im = sum(1 for bg in muc.values()
                 if bg.get("dang_hong") and bg.get("im_lan") == bg.get("lan_hong"))
    return {"can_bao": [h for _k, h in can_bao],
            "khoa": [k for k, _h in can_bao],
            "tong_hong": len(hong), "dang_im": im}


def _len_bac(khoa: list[str], now: float | None = None) -> None:
    """Đã báo xong thì nâng bậc để lần sau thưa hơn."""
    now = now or time.time()
    with _khoa:
        so = _doc()
        muc = so.get("muc") or {}
        for k in khoa:
            bg = muc.get(k)
            if not bg:
                continue
            # Lần báo ĐẦU TIÊN không nâng bậc: nếu nâng thì mốc 5 phút bị
            # tiêu mất và nhịp thành ngay→30p→60p, sai yêu cầu "5p → 30p →
            # 60p → 6h → hằng ngày". Bậc 0 phải được dùng đúng một lần để
            # chờ 5 phút, rồi mới lên bậc.
            da_bao = bool(bg.get("bao_cuoi"))
            bg["bao_cuoi"] = now
            if da_bao:
                bg["bac"] = min(int(bg.get("bac") or 0) + 1, len(_NHIP) - 1)
        so["muc"] = muc
        _ghi(so)


def im_di(thiet_bi: str, truong: str = "", loai: str = "") -> dict[str, Any]:
    """«Tôi biết rồi» — im về LƯỢT HỎNG đang diễn ra của thiết bị này.

    Không truyền ``truong``/``loai`` thì im mọi lỗi đang có của thiết bị đó.
    Sửa xong mà hỏng LẠI vẫn báo, vì lúc đó ``lan_hong`` đã khác.
    """
    n = 0
    with _khoa:
        so = _doc()
        muc = so.get("muc") or {}
        for k, bg in muc.items():
            tb, tr, lo = k.split("\x00")
            if tb != thiet_bi:
                continue
            if truong and tr != truong:
                continue
            if loai and lo != loai:
                continue
            if bg.get("dang_hong"):
                bg["im_lan"] = bg.get("lan_hong")
                n += 1
        so["muc"] = muc
        _ghi(so)
    logger.info({"event": "canh_bao_im", "thiet_bi": thiet_bi, "so_loi": n})
    return {"ok": True, "da_im": n}


def bo_im(thiet_bi: str = "") -> dict[str, Any]:
    """Bật báo lại — cho nút «nhận lại cảnh báo» trên web."""
    n = 0
    with _khoa:
        so = _doc()
        muc = so.get("muc") or {}
        for k, bg in muc.items():
            if thiet_bi and k.split("\x00")[0] != thiet_bi:
                continue
            if bg.get("im_lan") is not None:
                bg["im_lan"] = None
                bg["bac"] = 0
                n += 1
        so["muc"] = muc
        _ghi(so)
    return {"ok": True, "da_bo_im": n}


def _soan_tin(hong: list[dict[str, Any]], tong: int) -> str:
    n = len(hong)
    dau = (f"⚠️ Nhà có {tong} thiết bị đang lỗi" if tong > n
           else f"⚠️ Nhà có {n} thiết bị đang lỗi")
    than = "\n".join(_mo_ta(h) for h in hong[:_toi_da_moi_lan()])
    con = tong - min(n, _toi_da_moi_lan())
    duoi = f"\n\n…và {con} cái nữa." if con > 0 else ""
    return (f"{dau}:\n\n{than}{duoi}\n\n"
            "Nhắn «tôi biết rồi» để em thôi nhắc mấy cái này. "
            "Sửa xong mà hỏng lại thì em vẫn báo.")


def chay_mot_lan(so_ngay: int = 7) -> dict[str, Any]:
    """Quét, gửi tin nếu có gì đến hạn. Heartbeat gọi hàm này mỗi 5 phút."""
    if not is_enabled():
        return {"gui": 0, "ly_do": "tắt trong cấu hình"}

    kq = quet(so_ngay)
    can = kq.get("can_bao") or []
    if not can:
        return {"gui": 0, "tong_hong": kq.get("tong_hong", 0),
                "dang_im": kq.get("dang_im", 0)}

    nguoi = _nguoi_nhan()
    if not nguoi:
        return {"gui": 0, "ly_do": "chưa khai người nhận (canh_bao.nguoi_nhan "
                                   "hoặc agent_heartbeat.admin_user_ids)"}

    tin = _soan_tin(can, int(kq.get("tong_hong") or len(can)))
    gui = 0
    for uid in nguoi:
        try:
            _gui(uid, tin)
            gui += 1
        except Exception as exc:
            logger.info({"event": "canh_bao_gui_loi", "user": uid,
                         "error": str(exc)[:160]})

    if gui:
        _len_bac(kq.get("khoa") or [])
    return {"gui": gui, "so_loi": len(can), "tong_hong": kq.get("tong_hong", 0)}


def _gui(user_id: str, text: str) -> None:
    """Gửi qua đúng kênh người dùng đang dùng.

    Dùng lại đường của reminders (``channel_of`` → ``_send``) — cùng đường mà
    heartbeat._notify_user đi, nên không phải khai kênh/chat_id lần nữa.
    """
    from services.agent import reminders as rem

    kenh = _kenh()
    channel, chat_id = rem.channel_of(user_id)
    rem._send(kenh or channel, chat_id, text, {})


def trang_thai() -> dict[str, Any]:
    """Cho web + health: đang theo dõi bao nhiêu lỗi, bao nhiêu cái đã tắt."""
    with _khoa:
        so = _doc()
    muc = so.get("muc") or {}
    hong = [bg for bg in muc.values() if bg.get("dang_hong")]
    im = [bg for bg in hong if bg.get("im_lan") == bg.get("lan_hong")]
    return {
        "bat": is_enabled(),
        "dang_hong": len(hong),
        "dang_im": len(im),
        "theo_doi": len(muc),
        "quet_cuoi": so.get("quet_cuoi"),
        "gio_hang_ngay": _gio_hang_ngay(),
        "nguoi_nhan": len(_nguoi_nhan()),
    }


def danh_sach() -> list[dict[str, Any]]:
    """Danh sách lỗi đang theo dõi — cho bảng trên web."""
    with _khoa:
        so = _doc()
    ra = []
    for k, bg in (so.get("muc") or {}).items():
        tb, tr, lo = k.split("\x00")
        ra.append({
            "thiet_bi": tb, "truong": tr, "loai": lo,
            "dang_hong": bool(bg.get("dang_hong")),
            "im": bg.get("im_lan") == bg.get("lan_hong"),
            "lan_hong": bg.get("lan_hong"),
            "bac": bg.get("bac"),
            "bao_cuoi": bg.get("bao_cuoi"),
            "chi_tiet": bg.get("chi_tiet"),
        })
    ra.sort(key=lambda x: (not x["dang_hong"], x["im"], x["thiet_bi"]))
    return ra


def _reset_for_tests() -> None:
    with _khoa:
        try:
            _FILE.unlink()
        except OSError:
            pass
