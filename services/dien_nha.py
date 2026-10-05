"""MẤT ĐIỆN — đọc UPS qua NUT, báo khi mất điện, có điện lại, pin yếu sắp tắt máy chủ.

Chủ máy 05/10/2026: *"mất điện báo qua các kênh cài đặt, có điện báo lại, nếu khi còn 5% pin mà chưa có thì tắt
pve kèm báo cho user"* — sau khi xem số đo thì chốt 15%. Hôm đó mất điện 14:28, UPS cạn 14:48 mà không ai được báo:
NUT chạy trong LXC, driver không mở được USB và ``upsmon`` không có dòng ``MONITOR``.

CHIA VIỆC: việc TẮT/BẬT máy do NUT trên chính máy Proxmox lo (``upsmon`` + ``upssched`` + cổng chờ điện ổn định
trước ``pve-guests``) — để c2a chết giữa chừng vẫn tắt đúng. Module này chỉ ĐỌC và BÁO.

Đọc thẳng ``upsd`` bằng giao thức NUT (cổng 3493, ``LIST VAR``) chứ không qua cảm biến HA: HA hỏi 60 giây một lần,
còn từ 15% pin tới lúc máy chủ tắt chỉ có chừng một phút (đo 05/10/2026: 23% → cạn trong ~2 phút ở tải 28%).

Tin không gửi được thì GIỮ LẠI gửi sau, không bỏ: mất điện thì modem có thể tắt theo, tin «mất điện» chỉ tới được
khi có mạng lại — muộn nhưng giờ ghi trong tin vẫn đúng.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config
from utils.log import logger

_TZ = timezone(timedelta(hours=7))
_FILE = Path(DATA_DIR) / "agent" / "dien_nha.json"
_khoa = threading.RLock()

KHOA = "nha.mat_dien"
KHOA_LOI = "he_thong.loi"
#: Giây giữa hai lần đọc UPS. Máy chủ chờ FINALDELAY 15 s sau khi pin yếu mới tắt — đọc 5 s một lần là kịp báo.
NHIP_GIAY = 5.0
#: Chạy pin liên tục ngần này giây mới báo mất điện — chớp điện vài giây thì im.
XAC_NHAN_MAT = 10.0
#: Không đọc được UPS lâu ngần này thì báo lỗi hệ thống: NUT hỏng là lần mất điện sau lại im như 05/10/2026.
MAT_DOC_GIAY = 180.0
#: Tin chưa gửi được thì thử lại sau ngần này giây; quá hạn giữ thì bỏ.
GUI_LAI_GIAY = 60.0
GIU_TIN_GIAY = 6 * 3600.0
HET_GIO = 5.0


def _cfg() -> dict[str, Any]:
    raw = config.data.get("dien_nha")
    return raw if isinstance(raw, dict) else {}


def dia_chi() -> str:
    """``ups@máy[:cổng]`` của NUT, vd ``prolink@172.16.10.100``. Rỗng = chưa khai, luồng nằm im."""
    return str(_cfg().get("nut") or "").strip()


# ── Đọc UPS ─────────────────────────────────────────────────────────────────
def _tach(dc: str) -> tuple[str, str, int]:
    ups, _, may = dc.partition("@")
    if not ups or not may:
        raise ValueError(f"địa chỉ NUT phải dạng ups@máy[:cổng], nhận «{dc}»")
    host, _, cong = may.partition(":")
    return ups, host, int(cong or 3493)


def doc(dc: str) -> dict[str, str]:
    """Mọi biến của UPS: ``{"ups.status": "OB", "battery.charge": "87", …}``. Lỗi thì ném OSError/ValueError."""
    ups, host, cong = _tach(dc)
    with socket.create_connection((host, cong), timeout=HET_GIO) as s:
        s.sendall(f"LIST VAR {ups}\n".encode())
        buf = b""
        het = f"END LIST VAR {ups}\n".encode()
        while not buf.endswith(het):
            phan = s.recv(4096)
            if not phan:
                raise OSError("upsd đóng kết nối giữa chừng")
            buf += phan
            if buf.startswith(b"ERR "):
                raise ValueError(f"upsd trả lỗi: {buf.decode(errors='replace').strip()}")
    ra: dict[str, str] = {}
    for dong in buf.decode("utf-8", "replace").splitlines():
        if dong.startswith(f"VAR {ups} "):
            ten, _, gt = dong[len(f"VAR {ups} "):].partition(" ")
            ra[ten] = gt.strip().strip('"')
    return ra


_TEN_CO = {"OL": "đang dùng điện lưới", "OB": "ĐANG CHẠY PIN", "LB": "PIN YẾU", "FSD": "ĐANG TẮT MÁY",
           "CHRG": "đang sạc", "RB": "cần thay ắc quy", "OFF": "UPS tắt nguồn ra"}


def tom_tat(d: dict[str, str]) -> str:
    """Một câu cho nút «Kiểm tra kết nối»: máy nào, đang thế nào, ngưỡng tắt."""
    co = [_TEN_CO.get(x, x) for x in d.get("ups.status", "").split()] or ["không rõ trạng thái"]
    ten = " ".join(x for x in (d.get("device.mfr"), d.get("device.model")) if x) or "UPS"
    ra = f"{ten} — {', '.join(co)}, pin {d.get('battery.charge', '?')}%"
    if d.get("battery.charge.low"):
        ra += f" (máy chủ tắt khi dưới {d['battery.charge.low']}%)"
    if d.get("ups.load"):
        ra += f", tải {d['ups.load']}%"
    if d.get("input.voltage"):
        ra += f", điện vào {d['input.voltage']} V"
    return ra


# ── Trạng thái → tin ────────────────────────────────────────────────────────
def _gio(ts: float) -> str:
    return datetime.fromtimestamp(ts, _TZ).strftime("%H:%M %d/%m")


def buoc(so: dict[str, Any], d: dict[str, str] | None, now: float) -> list[tuple[str, str]]:
    """Một lần đọc UPS → các tin cần gửi ``[(khoá thông báo, nội dung)]``. Sửa ``so`` tại chỗ.

    ``d`` là None khi không đọc được UPS."""
    tin: list[tuple[str, str]] = []
    if d is None:
        tu = so.setdefault("mat_doc_tu", now)
        if now - tu >= MAT_DOC_GIAY and not so.get("da_bao_mat_doc"):
            so["da_bao_mat_doc"] = True
            tin.append((KHOA_LOI, f"⚠️ Không đọc được UPS (NUT {dia_chi()}) từ {_gio(tu)} — mất điện sẽ KHÔNG được "
                                  f"báo. Kiểm dịch vụ nut-server trên máy Proxmox."))
        return tin
    so.pop("mat_doc_tu", None)
    if so.pop("da_bao_mat_doc", False):
        tin.append((KHOA_LOI, f"✅ Đọc lại được UPS (NUT {dia_chi()}) lúc {_gio(now)}."))

    st = d.get("ups.status", "").split()
    pin, nguong, tai = d.get("battery.charge", "?"), d.get("battery.charge.low", "?"), d.get("ups.load", "?")
    if "OB" in st:
        tu = so.setdefault("pin_tu", now)
        yeu = "LB" in st or "FSD" in st
        if not so.get("da_bao_mat") and (now - tu >= XAC_NHAN_MAT or yeu):
            so["da_bao_mat"] = True
            tin.append((KHOA, f"⚡ Mất điện từ {_gio(tu)}. UPS đang chạy pin: còn {pin}%, tải {tai}%. Pin dưới "
                              f"{nguong}% thì máy chủ Proxmox tự tắt; có điện ổn định trở lại thì tự bật."))
        if yeu and not so.get("da_bao_tat"):
            so["da_bao_tat"] = True
            tin.append((KHOA, f"🪫 Pin UPS còn {pin}% (ngưỡng {nguong}%) — máy chủ Proxmox đang tắt, mạng và mọi "
                              f"dịch vụ trong nhà tắt theo. Có điện ổn định trở lại thì máy tự bật."))
    elif "OL" in st:
        tu = so.pop("pin_tu", None)
        da_bao = so.pop("da_bao_mat", False)
        da_tat = so.pop("da_bao_tat", False)
        if tu is not None and da_bao:
            tin.append((KHOA, f"🔌 Có điện lại — mất điện từ {_gio(tu)}, đọc lại UPS lúc {_gio(now)} "
                              f"(~{(now - tu) / 60:.0f} phút). Pin UPS còn {pin}%."
                              + (" Máy chủ đã tự khởi động lại." if da_tat else "")))
    return tin


# ── Gửi, giữ tin chưa gửi được ──────────────────────────────────────────────
def _doc_so() -> dict[str, Any]:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ghi_so(d: dict[str, Any]) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_FILE)
    except OSError as exc:
        logger.warning({"event": "dien_nha_ghi_loi", "error": str(exc)[:160]})


def _gui_hang_doi(so: dict[str, Any], now: float) -> int:
    """Gửi lần lượt các tin đang chờ; dừng ở tin đầu tiên chưa gửi được để giữ đúng thứ tự. Trả số tin đã gửi."""
    from services import thong_bao

    hang = [x for x in so.get("hang_doi") or [] if now - float(x.get("luc", now)) < GIU_TIN_GIAY]
    if hang and now - float(so.get("thu_luc", 0)) < GUI_LAI_GIAY and so.get("thu_luc"):
        so["hang_doi"] = hang
        return 0
    da = 0
    while hang:
        if thong_bao.gui(hang[0]["khoa"], hang[0]["tin"]) <= 0:
            so["thu_luc"] = now
            break
        hang.pop(0)
        da += 1
    else:
        so.pop("thu_luc", None)
    so["hang_doi"] = hang
    return da


def chay_mot_lan(now: float | None = None) -> list[str]:
    """Đọc UPS một lần, cập nhật sổ, gửi tin. Trả các tin mới sinh ra lượt này."""
    dc = dia_chi()
    if not dc:
        return []
    now = now or time.time()
    loi = ""
    try:
        d: dict[str, str] | None = doc(dc)
    except (OSError, ValueError) as exc:
        loi, d = str(exc)[:160], None
    with _khoa:
        so = _doc_so()
        if loi and "mat_doc_tu" not in so:           # ghi một lần lúc bắt đầu mất đọc, không mỗi 5 giây
            logger.info({"event": "dien_nha_doc_loi", "nut": dc, "loi": loi})
        moi = buoc(so, d, now)
        so.setdefault("hang_doi", []).extend({"khoa": k, "tin": t, "luc": now} for k, t in moi)
        if moi:
            so.pop("thu_luc", None)          # tin mới thì thử gửi ngay, không chờ hết nhịp gửi lại
        _gui_hang_doi(so, now)
        _ghi_so(so)
    for k, t in moi:
        logger.info({"event": "dien_nha_bao", "khoa": k, "tin": t[:80]})
    return [t for _, t in moi]


def trang_thai() -> dict[str, Any]:
    with _khoa:
        return {"nut": dia_chi(), **_doc_so()}


def _reset_for_tests(path: Path) -> None:
    global _FILE
    _FILE = path


# ── Luồng nền ───────────────────────────────────────────────────────────────
_luong: threading.Thread | None = None
_dung = threading.Event()


def _chay_mai() -> None:
    while not _dung.is_set():
        t0 = time.time()
        try:
            chay_mot_lan()
        except Exception as exc:  # noqa: BLE001 — một lượt hỏng không được dừng việc canh mất điện
            logger.warning({"event": "dien_nha_nhip_loi", "loi": str(exc)[:160]})
        _dung.wait(max(1.0, NHIP_GIAY - (time.time() - t0)))


def start() -> bool:
    """Luôn chạy nền; nằm im khi chưa khai ``dien_nha.nut`` (đọc lại cài đặt mỗi nhịp). Idempotent."""
    global _luong
    with _khoa:
        if _luong is not None and _luong.is_alive():
            return True
        _dung.clear()
        _luong = threading.Thread(target=_chay_mai, daemon=True, name="dien-nha")
        _luong.start()
    logger.info({"event": "dien_nha_started", "nut": dia_chi() or "(chưa khai)"})
    return True


def stop() -> None:
    global _luong
    _dung.set()
    with _khoa:
        _luong = None
