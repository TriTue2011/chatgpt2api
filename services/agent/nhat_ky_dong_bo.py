"""Đồng bộ nhật ký nhóm lên đám mây, và dọn tệp online quá hạn giữ.

Chủ máy chốt 05/08: nhật ký đồng bộ HẰNG NGÀY theo giờ đặt riêng từng phạm vi
(tệp thì hỏi admin ngay lúc nhận, không cần giờ), và đồng bộ là **ghi thêm chứ
không ghi đè** — cục bộ giữ 10 ngày mà online giữ 20 thì bản online phải đủ 20.

Cách bảo đảm điều đó: **mỗi ngày một tệp**, `nhat-ky-<kênh>-<chat>-<ngày>.jsonl`.

* Đẩy lại một ngày chỉ ghi đè ĐÚNG tệp của ngày đó, và bản mới luôn là bản đầy
  hơn (nhật ký chỉ thêm tin, hạn giữ cục bộ xoá theo TRỌN ngày nên một ngày còn
  ở máy thì còn nguyên vẹn).
* Ngày mà cục bộ đã xoá thì không có tệp nào để đẩy, nên bản online của ngày đó
  đứng yên tới khi hết hạn giữ online. Đó chính là "online đủ 20 ngày".
* Nếu gom cả tháng vào một tệp thì mỗi lần đẩy là ghi đè cả tháng bằng phần cục
  bộ còn lại — đúng cái mất dữ liệu mà chủ máy dặn phải tránh.

Phần dọn hạn giữ CHỈ xoá những tệp có trong sổ `luu_tru_online.so_da_day()`, tức
tệp chính bot đã đẩy lên. Không quét-rồi-xoá theo tuổi: thư mục chủ máy chọn có
thể đang chứa tài liệu riêng của họ, và xoá mất tài liệu đó là hỏng dữ liệu thật.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

from services.agent import chatlog
from services.agent import luu_tru_online as lt
from services.config import DATA_DIR
from utils.log import logger

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _TZ = timezone(timedelta(hours=7))

#: Vòng nền tự thức mỗi 5 phút rồi tự xét đã tới giờ của từng phạm vi chưa. Đặt
#: một hẹn giờ đúng mốc thì sửa giờ ở Cài đặt phải khởi động lại mới có hiệu lực.
CHU_KY_QUET_S = 300
BOOT_DELAY_S = 180          # để server lên hẳn rồi mới đụng mạng

_TRANG_PATH = Path(DATA_DIR) / "agent" / "nhat_ky_dong_bo.json"
_khoa = threading.RLock()
_stop = threading.Event()
_da_chay = False


# ── Trạng thái trên đĩa ─────────────────────────────────────────────────────
# {"lan_cuoi": {"<scope>": "YYYY-MM-DD"},
#  "dau_ngay": {"<scope>|<ngày>": "<số tin>:<ts mới nhất>"}}

def _doc_trang() -> dict:
    try:
        v = json.loads(_TRANG_PATH.read_text("utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _ghi_trang(t: dict) -> None:
    try:
        _TRANG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TRANG_PATH.write_text(json.dumps(t, ensure_ascii=False), "utf-8")
    except OSError as exc:
        logger.warning(f"nhat_ky_dong_bo: ghi trạng thái lỗi: {str(exc)[:120]}")


def _dau_ngay(so_tin: int, ts_moi: float) -> str:
    """Dấu nhận biết một ngày có đổi gì không: số tin + tin mới nhất."""
    return f"{int(so_tin)}:{float(ts_moi):.0f}"


# ── Thuần: tách phạm vi, tên tệp, xuất nội dung, xét giờ ────────────────────

def tach_scope(scope_key: str) -> tuple[str, str, str]:
    """Khoá nhật ký 'v1|kênh|chat|topic|' → (kênh, chat, topic).

    Đúng dạng `scope.khoa_nhat_ky` sinh ra: bốn phần, đã quote từng phần.
    """
    s = str(scope_key or "")
    if not s.startswith("v1|"):
        return "", "", ""
    phan = s.split("|")
    if len(phan) < 4:
        return "", "", ""
    return unquote(phan[1]), unquote(phan[2]), unquote(phan[3])


def ten_tep(kenh: str, chat: str, topic: str, day: str) -> str:
    """Tên tệp nhật ký của MỘT ngày.

    Có kênh + chat trong tên vì nhiều phạm vi có thể trỏ vào cùng một thư mục
    trên đám mây (cấu hình khai ở cấp cả kênh) — trùng tên là nhóm này ghi đè
    nhật ký của nhóm kia.
    """
    phan = [p for p in ("nhat-ky", kenh, chat, topic, day) if p]
    ten = re.sub(r"[^\w.\-]+", "_", "-".join(phan))
    # Gom chuỗi dấu chấm lại: id nhóm Zalo là chuỗi tuỳ ý, để '..' trong tên tệp
    # thì có backend hiểu nó là thư mục cha.
    return re.sub(r"\.{2,}", ".", ten) + ".jsonl"


def xuat_jsonl(cac_tin: list[dict]) -> str:
    """Mỗi tin một dòng JSON. Dạng dòng-một-bản-ghi để ghép thêm được về sau và
    đọc lại được bằng công cụ thường."""
    ra = []
    for t in cac_tin:
        ra.append(json.dumps({
            "ts": round(float(t.get("ts") or 0), 3),
            "ngay": t.get("ngay") or "",
            "nguoi": t.get("sender") or "",
            "uid": t.get("sender_id") or "",
            "text": t.get("text") or "",
        }, ensure_ascii=False))
    return "\n".join(ra) + ("\n" if ra else "")


def _phut_trong_ngay(gio: str) -> int:
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", str(gio or "").strip())
    if not m:
        gio = lt.MAC_DINH_GIO_DONG_BO
        m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", gio)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 3 * 60


def can_chay(gio_dong_bo: str, *, now: float, lan_cuoi: str) -> bool:
    """Đã tới giờ đồng bộ của hôm nay, và hôm nay chưa chạy?

    So theo NGÀY chứ không theo khoảng cách 24 giờ: chạy trễ một hôm (máy chủ
    tắt) thì hôm sau tới giờ là chạy, không phải chờ bù cho đủ 24 tiếng.
    """
    t = datetime.fromtimestamp(now, _TZ)
    if str(lan_cuoi or "") == t.strftime("%Y-%m-%d"):
        return False
    return t.hour * 60 + t.minute >= _phut_trong_ngay(gio_dong_bo)


def _thoi_diem(iso: str) -> float:
    """ModTime của rclone (RFC3339, có thể 9 chữ số phần giây) → epoch."""
    s = str(iso or "").strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", s)
    if not m:
        return 0.0
    try:
        d = datetime.strptime(f"{m.group(1)}T{m.group(2)}", "%Y-%m-%dT%H:%M:%S")
        return d.replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def qua_han(luc_day: float, so_ngay: int, *, now: float) -> bool:
    """Tệp đã đẩy lúc `luc_day` có quá hạn giữ chưa. 0 ngày = giữ mãi."""
    n = int(so_ngay or 0)
    if n <= 0:
        return False
    return (now - float(luc_day or 0)) > n * 86400


# ── Một vòng đồng bộ ────────────────────────────────────────────────────────

def dong_bo_mot_ngay(scope_key: str, day: str, cd: dict) -> dict:
    """Xuất nhật ký một ngày rồi đẩy lên kho. Trả {ok, dich, so_tin}."""
    kenh, chat, topic = tach_scope(scope_key)
    if not chat:
        return {"ok": False, "error": "khoá phạm vi không đọc được"}
    tin = chatlog.doc_scope_ngay(scope_key, day)
    if not tin:
        return {"ok": False, "error": "ngày này không có tin"}
    dich_thu_muc = lt.duong_dan_dich(cd, "x.jsonl", nhat_ky=True)
    if not dich_thu_muc:
        return {"ok": False, "error": "phạm vi chưa bật lưu trữ online"}

    from services import rclone_service as rcl
    d = rcl.workspace_dir() / "nhat_ky"
    d.mkdir(parents=True, exist_ok=True)
    p = d / ten_tep(kenh, chat, topic, day)
    p.write_text(xuat_jsonl(tin), "utf-8")
    try:
        kq = rcl.gui_len(str(p), dich_thu_muc)
    finally:
        # Tệp xuất ra là bản tạm — dựng lại từ SQLite lúc nào cũng được, giữ lại
        # chỉ làm thư mục làm việc phình theo mỗi đêm.
        try:
            p.unlink()
        except OSError:
            pass
    if not kq.get("ok"):
        return {"ok": False, "error": str(kq.get("error") or "")[:200]}
    lt.ghi_so(str(kq.get("duong_dan") or ""), kenh, chat, topic, "", nhat_ky=True)
    return {"ok": True, "dich": kq.get("duong_dan"), "so_tin": len(tin)}


def don_qua_han(*, now: float | None = None) -> dict:
    """Xoá trên đám mây những tệp BOT ĐÃ ĐẨY mà quá hạn giữ của mục đó.

    Chỉ đi theo sổ `luu_tru_online.so_da_day()`. Hạn giữ tra lại theo đúng phạm
    vi đã ghi lúc đẩy, nên đổi hạn ở Cài đặt là vòng dọn sau áp ngay.
    """
    now = time.time() if now is None else now
    so = lt.so_da_day()
    if not so:
        return {"xoa": 0, "xet": 0}
    from services import rclone_service as rcl
    da_xoa: list[str] = []
    for dd, v in so.items():
        pv = list(v.get("pham_vi") or [])
        while len(pv) < 4:
            pv.append("")
        cd = lt.cai_dat(pv[0], pv[1], pv[2], pv[3])
        ten = Path(str(dd).split(":", 1)[-1]).name
        han = lt.han_giu(cd, ten, nhat_ky=bool(v.get("nhat_ky")))
        if not qua_han(v.get("luc") or 0, han, now=now):
            continue
        kq = rcl.xoa(str(dd))
        if kq.get("ok"):
            logger.info(f"nhat_ky_dong_bo: hết hạn giữ {han} ngày, đã xoá {dd}")
            da_xoa.append(str(dd))
        else:
            # Tệp có thể đã bị xoá bằng tay trên đám mây — bỏ khỏi sổ để vòng
            # sau không thử lại mãi.
            logger.warning(f"nhat_ky_dong_bo: xoá {dd} hỏng: {str(kq.get('error'))[:120]}")
            da_xoa.append(str(dd))
    lt.xoa_khoi_so(da_xoa)
    return {"xoa": len(da_xoa), "xet": len(so)}


def dong_bo(*, now: float | None = None) -> dict:
    """Một vòng: mọi phạm vi nhật ký có lưu trữ online đang bật và đã tới giờ."""
    now = time.time() if now is None else now
    with _khoa:
        trang = _doc_trang()
    lan_cuoi = dict(trang.get("lan_cuoi") or {})
    dau = dict(trang.get("dau_ngay") or {})
    lan_don = str(trang.get("lan_don") or "")
    hom_nay = datetime.fromtimestamp(now, _TZ).strftime("%Y-%m-%d")
    da_day = 0
    bo_qua = 0
    pham_vi_chay = 0

    for scope in chatlog.cac_scope():
        kenh, chat, topic = tach_scope(scope)
        if not chat:
            continue
        cd = lt.cai_dat(kenh, chat, topic)
        if not cd.get("enabled"):
            continue
        if not can_chay(cd.get("gio_dong_bo") or "", now=now,
                        lan_cuoi=str(lan_cuoi.get(scope) or "")):
            continue
        pham_vi_chay += 1
        for day, (so_tin, ts_moi) in chatlog.ngay_va_dem(scope).items():
            k = f"{scope}|{day}"
            moi = _dau_ngay(so_tin, ts_moi)
            if dau.get(k) == moi:
                bo_qua += 1
                continue
            kq = dong_bo_mot_ngay(scope, day, cd)
            if kq.get("ok"):
                dau[k] = moi
                da_day += 1
            else:
                logger.warning(f"nhat_ky_dong_bo: {scope} ngày {day} hỏng: {kq.get('error')}")
        lan_cuoi[scope] = hom_nay

    # Dọn hạn giữ chạy theo LỊCH RIÊNG, không đi kèm việc đồng bộ nhật ký: một
    # phạm vi có thể bật lưu trữ online mà không bật ghi nhật ký, khi đó vòng
    # trên không chạy lần nào và tệp đã đẩy sẽ nằm mãi trên đám mây.
    da_xoa = 0
    if lan_don != hom_nay and can_chay(lt.MAC_DINH_GIO_DONG_BO, now=now,
                                       lan_cuoi=lan_don):
        da_xoa = don_qua_han(now=now).get("xoa", 0)
        lan_don = hom_nay

    if pham_vi_chay or lan_don != str(trang.get("lan_don") or ""):
        with _khoa:
            _ghi_trang({"lan_cuoi": lan_cuoi, "dau_ngay": dau, "lan_don": lan_don})
    return {"pham_vi": pham_vi_chay, "da_day": da_day, "bo_qua": bo_qua,
            "da_xoa": da_xoa}


# ── Vòng nền ────────────────────────────────────────────────────────────────

def _vong() -> None:
    _stop.wait(BOOT_DELAY_S)
    while not _stop.is_set():
        try:
            kq = dong_bo()
            if kq.get("pham_vi"):
                logger.info(f"nhat_ky_dong_bo: {kq}")
        except Exception as exc:
            logger.warning(f"nhat_ky_dong_bo: vòng lỗi: {str(exc)[:200]}")
        _stop.wait(CHU_KY_QUET_S)


def start() -> None:
    """Bật vòng nền (gọi nhiều lần chỉ chạy một cái)."""
    global _da_chay
    if _da_chay:
        return
    _da_chay = True
    _stop.clear()
    threading.Thread(target=_vong, name="nhat-ky-dong-bo", daemon=True).start()
    logger.info("nhat_ky_dong_bo: đã bật vòng nền, quét mỗi %d giây", CHU_KY_QUET_S)


def stop() -> None:
    _stop.set()


__all__ = ["start", "stop", "dong_bo", "dong_bo_mot_ngay", "don_qua_han",
           "can_chay", "tach_scope", "ten_tep", "xuat_jsonl", "qua_han"]
