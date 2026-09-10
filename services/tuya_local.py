"""Nghe thiết bị Tuya THẲNG trong mạng nhà — không qua đám mây, không cần HA.

VÌ SAO CẦN — đo thật 10/09/2026:

Khoá cửa báo chậm tối đa 5 phút, vì `khoa_cua_nha` hỏi API Tuya mỗi nhịp
heartbeat 300 giây. Đó là cơ chế KÉO và đi vòng qua đám mây Tuya. Chủ máy chốt:
*"tôi cần dự án tôi không có HA vẫn realtime được"*, *"qua đám mây rất bất
tiện"*.

Đường local thì thiết bị tự ĐẨY trạng thái ngay khi đổi, độ trễ mili giây.

HÔM NAY NHÀ CHƯA CÓ THIẾT BỊ NÀO DÙNG ĐƯỢC, và đó là kết quả đo chứ không phải
phỏng đoán: nghe quảng bá UDP 6666/6667 có giải mã đúng 30 giây → 0 thiết bị;
quét cổng 6668 trên 20 máy đang sống → 0 máy mở. Nhà chỉ có hai thiết bị Tuya:
một gateway Zigbee và khoá cửa T5 chạy pin. Khoá pin ngủ đông gần như liên tục
nên không giữ cổng mạng mở — làm vậy là hết pin trong vài ngày. Đây là bản chất
thiết bị, mọi thư viện local đều bó tay với nó.

Nhưng thiết bị điện cắm nguồn (ổ cắm, công tắc, đèn, bình nóng lạnh) thì CÓ mở
cổng 6668. Viết sẵn thì chủ máy cắm cái đầu tiên vào là chạy ngay.

BÀI HỌC LẤY TỪ CODE các dự án local (đọc để hiểu vấn đề, KHÔNG chép code —
localtuya/hass-localtuya/xtend_tuya đều GPL-3.0, chép vào là cả repo này phải mở
mã nguồn, mà repo có token Tuya, mật khẩu MQTT, khoá Zalo):

  · Lỗi giải mã nghĩa là ``local_key`` ĐÃ ĐỔI, không phải mạng hỏng. Tuya đổi
    khoá khi thiết bị được ghép nối lại. Thử lại mãi với khoá cũ là vô ích.
  · Thiết bị chỉ nhớ ~5 client gần nhất → mỗi thiết bị đúng MỘT kết nối.
  · Đẩy có thể bỏ sót, nên đường hỏi vòng của `khoa_cua_nha` vẫn giữ làm lưới.

Thư viện dùng: ``tinytuya`` — giấy phép MIT nên dùng thẳng được. Lớp ``Monitor``
của nó theo dõi nhiều thiết bị trên MỘT luồng bằng ``selectors``, tự nối lại,
heartbeat 12 giây. Chính docstring của nó ghi "experimental" nên ở đây bọc kín:
hỏng thì tắt phần local, phần còn lại của bot chạy như thường.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from services.config import config
from utils.log import logger

_khoa = threading.RLock()
_mon: Any = None                      # tinytuya.Monitor, None khi chưa chạy
_thiet_bi: dict[str, dict[str, Any]] = {}   # id → {ip, version, ten}
_loi_cuoi = ""
_dang_chay = False

#: Thời gian nghe quảng bá UDP khi dò. 8 giây đủ cho một nhà: thiết bị Tuya
#: phát mỗi ~10 giây, nhưng dò lâu quá thì lượt bấm "Dò thiết bị" bị treo.
_GIAY_DO = 8.0

#: Trường trong `dps` KHÔNG đáng ghi lịch sử — đo đếm liên tục, không nói lên
#: hành vi người. Cùng nguyên tắc với `ha_live._GHI_SENSOR`: chỉ giữ tín hiệu
#: nói lên CÓ NGƯỜI hoặc THIẾT BỊ ĐỔI TRẠNG THÁI.
_BO_QUA_DP = frozenset({"cur_power", "cur_voltage", "cur_current",
                        "add_ele", "phase_a", "phase_b", "phase_c"})


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("tuya") or {}).get("local")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    """Mặc định BẬT: chưa có thiết bị nào thì `start()` tự nằm im."""
    return bool(_cfg().get("bat", True))


# ── dò thiết bị ─────────────────────────────────────────────────────────────
def do_thiet_bi(giay: float = _GIAY_DO) -> list[dict[str, Any]]:
    """Thiết bị Tuya nói chuyện local được trong mạng nhà.

    Trả ``[{id, ip, version}]``. **Rỗng là chuyện bình thường** — nhà chưa có
    thiết bị cắm điện nào, đúng như đo được 10/09/2026. Không phải lỗi.

    Không bao giờ ném lỗi: dò hỏng thì trả rỗng và ghi log.
    """
    try:
        from tinytuya import scanner
    except Exception as exc:
        logger.info({"event": "tuya_local_thieu_goi", "loi": str(exc)[:120]})
        return []

    try:
        # `discover=True` nghe quảng bá UDP; `poll=False` để KHÔNG hỏi trạng
        # thái ngay — chưa có local_key thì hỏi cũng không đọc được, mà mỗi lần
        # hỏi là một kết nối tính vào hạn ~5 client thiết bị nhớ được.
        ds = scanner.devices(verbose=False, scantime=float(giay), color=False,
                             poll=False, byID=True, discover=True,
                             assume_yes=True) or {}
    except Exception as exc:
        logger.info({"event": "tuya_local_do_loi", "loi": str(exc)[:150]})
        return []

    ra: list[dict[str, Any]] = []
    for ma, d in (ds.items() if isinstance(ds, dict) else []):
        if not isinstance(d, dict):
            continue
        ip = str(d.get("ip") or "").strip()
        if not ip:
            continue
        ra.append({"id": str(ma), "ip": ip,
                   "version": str(d.get("version") or "3.3")})
    return ra


def _lay_khoa(ma: str) -> str:
    """`local_key` của một thiết bị, hỏi đám mây Tuya.

    BÍ MẬT: khoá này cho phép điều khiển thiết bị trong mạng. Chỉ giữ trong
    RAM, không ghi ra đĩa, không đưa vào log.
    """
    try:
        from services.tuya_nha import goi_api
        r = goi_api(f"/v1.0/devices/{ma}") or {}
        return str((r.get("result") or {}).get("local_key") or "")
    except Exception as exc:
        logger.info({"event": "tuya_local_khoa_loi", "loi": str(exc)[:140]})
        return ""


def _ten(ma: str) -> str:
    """Tên thiết bị cho dễ đọc; không tra được thì dùng mã."""
    with _khoa:
        t = str((_thiet_bi.get(ma) or {}).get("ten") or "")
    return t or f"tuya:{ma[:12]}"


# ── nhận đẩy ────────────────────────────────────────────────────────────────
def _khi_doi(device: Any, ket_qua: Any) -> None:
    """`Monitor` gọi mỗi khi thiết bị báo đổi trạng thái.

    Bọc kín: ghi lịch sử hỏng thì mất bản ghi đó, TUYỆT ĐỐI không được làm chết
    luồng nghe — cùng nguyên tắc với `mqtt_nha._nap_tin`.
    """
    try:
        dps = (ket_qua or {}).get("dps") if isinstance(ket_qua, dict) else None
        if not isinstance(dps, dict) or not dps:
            return
        ma = str(getattr(device, "id", "") or "")
        ten = _ten(ma)
        from services import lich_su_nha
        for dp, gt in dps.items():
            if str(dp) in _BO_QUA_DP or gt is None:
                continue
            lich_su_nha.ghi("tuya_local", ten, str(dp), gt)
    except Exception as exc:
        logger.info({"event": "tuya_local_ghi_loi", "loi": str(exc)[:150]})


def _khi_dut(device: Any, loi: Any = None) -> None:
    """Thiết bị rớt. `Monitor` tự nối lại; ở đây chỉ ghi nhận.

    Lỗi giải mã (`UnicodeDecodeError` / `JSONDecodeError`) nghĩa là `local_key`
    đã đổi chứ không phải mạng hỏng — nối lại với khoá cũ là vô ích, phải đi
    lấy khoá mới. Đánh dấu để vòng sau `start()` lấy lại.
    """
    ma = str(getattr(device, "id", "") or "")
    s = str(loi or "")
    doi_khoa = any(k in s for k in ("UnicodeDecode", "JSONDecode", "decrypt",
                                    "Unexpected Payload"))
    if doi_khoa:
        with _khoa:
            _thiet_bi.pop(ma, None)
    logger.info({"event": "tuya_local_dut", "thiet_bi": _ten(ma),
                 "khoa_doi": doi_khoa, "loi": s[:120]})


# ── vòng đời ────────────────────────────────────────────────────────────────
_luong: threading.Thread | None = None


def start() -> bool:
    """Khởi động ở LUỒNG NỀN. Idempotent. Trả True nếu đã/đang chạy.

    Phải chạy nền vì `do_thiet_bi()` nghe quảng bá UDP 8 giây — làm thẳng trong
    `api/app.py` là bot khởi động chậm thêm 8 giây mỗi lần, với một tính năng
    mà hôm nay nhà chưa dùng tới. Cùng khuôn `mqtt_nha.start` (dòng 450).
    """
    global _luong
    if not is_enabled():
        return False
    with _khoa:
        if _dang_chay and _mon is not None:
            return True
        if _luong is not None and _luong.is_alive():
            return True
        _luong = threading.Thread(target=_noi_that, daemon=True,
                                  name="tuya-local")
        _luong.start()
    return True


def _noi_that() -> bool:
    """Việc thật: dò thiết bị rồi mở kết nối thường trực.

    Trả False khi không có thiết bị local nào — trạng thái thật của nhà hiện
    tại, và là đường đi bình thường chứ không phải lỗi.
    """
    global _mon, _dang_chay, _loi_cuoi

    ds = do_thiet_bi()
    if not ds:
        _loi_cuoi = "chưa có thiết bị Tuya nào nói chuyện local được"
        logger.info({"event": "tuya_local_khong_co_thiet_bi"})
        return False

    try:
        import tinytuya
        mon = tinytuya.Monitor(on_status=_khi_doi, on_disconnect=_khi_dut,
                               auto_reconnect=True, reconnect_backoff=15.0)
    except Exception as exc:
        _loi_cuoi = f"không dựng được Monitor: {exc}"
        logger.warning({"event": "tuya_local_monitor_loi", "loi": str(exc)[:150]})
        return False

    noi = 0
    for d in ds:
        ma = d["id"]
        khoa = _lay_khoa(ma)
        if not khoa:
            continue
        try:
            dev = tinytuya.OutletDevice(ma, d["ip"], khoa,
                                        version=float(d["version"] or 3.3),
                                        persist=True)
            # `Monitor.add` trả CHUỖI LỖI khi hỏng, không ném ngoại lệ — đọc
            # từ chính mã nguồn tinytuya, đừng bọc try/except rồi tưởng là xong.
            kq = mon.add(dev)
            if isinstance(kq, str):
                logger.info({"event": "tuya_local_them_loi", "loi": kq[:120]})
                continue
        except Exception as exc:
            logger.info({"event": "tuya_local_noi_loi", "loi": str(exc)[:140]})
            continue
        with _khoa:
            _thiet_bi[ma] = {"ip": d["ip"], "version": d["version"],
                             "ten": f"tuya:{ma[:12]}"}
        noi += 1

    if not noi:
        _loi_cuoi = "thấy thiết bị nhưng không nối được cái nào"
        try:
            mon.stop()
        except Exception:
            pass
        return False

    try:
        mon.start()
    except Exception as exc:
        _loi_cuoi = f"không khởi động được Monitor: {exc}"
        logger.warning({"event": "tuya_local_start_loi", "loi": str(exc)[:150]})
        return False

    with _khoa:
        _mon, _dang_chay, _loi_cuoi = mon, True, ""
    logger.info({"event": "tuya_local_started", "so_thiet_bi": noi})
    return True


def stop() -> None:
    """Đóng mọi kết nối. Gọi được nhiều lần."""
    global _mon, _dang_chay
    with _khoa:
        mon, _mon, _dang_chay = _mon, None, False
        _thiet_bi.clear()
    if mon is not None:
        try:
            mon.stop()
        except Exception:
            pass


def trang_thai() -> dict[str, Any]:
    """Cho web + health: đang nghe mấy thiết bị, hỏng gì."""
    with _khoa:
        return {
            "bat": is_enabled(),
            "dang_chay": _dang_chay,
            "so_thiet_bi": len(_thiet_bi),
            # KHÔNG trả local_key ra ngoài — đó là bí mật điều khiển được nhà.
            "thiet_bi": [{"id": k, "ip": v.get("ip"),
                          "version": v.get("version")}
                         for k, v in _thiet_bi.items()],
            "loi": _loi_cuoi,
        }


def _reset_for_tests() -> None:
    stop()
    global _loi_cuoi
    _loi_cuoi = ""
