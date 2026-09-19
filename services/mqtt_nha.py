"""MQTT nhà — đường thứ hai để bot biết nhà, KHÔNG cần Home Assistant.

Vấn đề nó giải: bot hiện chỉ biết thiết bị qua ``ha_client`` (2093 dòng, sổ phòng,
dò tên tiếng Việt). Ai không cài Home Assistant thì bot mù hoàn toàn — dù nhà họ
vẫn đang có MQTT chạy với đầy đủ thiết bị.

Đây là ĐƯỜNG SONG SONG, không thay thế: có Home Assistant thì bot vẫn dùng
``ha_client`` (giàu thông tin hơn); không có thì rơi về đây và vẫn chạy được.
Cùng lối nghĩ với ``camera_nha`` — khai thẳng vào cổng, HA chỉ là tuỳ chọn.

Khám phá PHỔ QUÁT — cắm vào máy chủ nào cũng tự đọc ra có gì
────────────────────────────────────────────────────────────
Không khai báo trước thiết bị nào. Ba bước:

1. Dò nhánh gốc bằng ``+`` ở nhiều độ sâu.
2. Thấy nhánh gốc mới thì tự đăng ký ``<gốc>/#`` cho nhánh đó.
3. Đọc bản TỰ KHAI BÁO ở ``homeassistant/<loại>/<id>/config`` — mỗi thiết bị tự
   nói mình đọc ở chủ đề nào, nhận lệnh ở chủ đề nào, chữ nào là bật/tắt.

⚠️  TUYỆT ĐỐI KHÔNG đăng ký ``#``
    EMQX (và mọi máy chủ đặt ``no_match = deny``) TỪ CHỐI ``#`` và ``$SYS/#``,
    nhưng từ chối IM LẶNG: kết nối vẫn thành công, chỉ là không tin nào về. Đo
    trên EMQX thật 09/09/2026: ``#`` → 0 tin/45 giây, còn ``+``…``+/+/+/+/+/+``
    → 747 tin/40 giây, 5 nhánh gốc, 289 chủ đề. Ai sửa file này mà "gọn lại"
    thành ``#`` sẽ mất sạch dữ liệu và tưởng máy chủ hỏng.

    Cũng đừng rút bớt độ sâu: chỉ ``+/+`` thì ra 2 nhánh thay vì 5 — mất 60%
    thiết bị, vì chủ đề dài ngắn khác nhau.

Bản tự khai báo mang tên "Home Assistant discovery" nhưng KHÔNG cần Home
Assistant: Zigbee2MQTT tự đăng lên MQTT, ai đọc cũng được. Tên gọi chỉ là dấu
vết lịch sử.

Ba bộ nhận dạng, thử lần lượt, dừng ở cái đầu tiên khớp: ``tu_khai_bao`` (chuẩn
chung) → ``frigate`` (nhánh riêng, không theo chuẩn trên) → ``tho`` (không nhận
ra thì hiện chủ đề và giá trị thô, KHÔNG đoán bừa).

Mật khẩu máy chủ nằm trong config; mọi đường liệt kê đều che — model không bao
giờ nhìn thấy mật khẩu MQTT.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Optional

from utils.log import logger

# ── Trạng thái luồng nền ─────────────────────────────────────────────────────

_thread: Optional[threading.Thread] = None
_started_lock = threading.Lock()
_stop = threading.Event()

#: Bộ nhớ trạng thái: chủ đề → (giá trị thô, lúc nhận). Chỉ giữ giá trị MỚI NHẤT,
#: không ghi lịch sử ra đĩa — lịch sử là việc của Home Assistant recorder.
_gia_tri: dict[str, tuple[Any, float]] = {}
#: Bản khai đã đọc: tên thiết bị → {thực thể → mô tả}.
_so_thiet_bi: dict[str, dict[str, dict[str, Any]]] = {}
#: Nhánh gốc đã dò ra, để không đăng ký lại và để báo cho người dùng.
_nhanh_goc: set[str] = set()
_khoa_du_lieu = threading.Lock()

_stats: dict[str, Any] = {
    "connected": False,
    "tin": 0,
    "thiet_bi": 0,
    "nhanh": 0,
    "last_error": "",
    "reconnects": 0,
    "last_tin_ts": 0.0,
}

_BACKOFF_START = 5.0
_BACKOFF_CAP = 120.0
#: Độ sâu quét ``+``. Sáu tầng phủ hết chủ đề thực tế đã gặp; sâu hơn chỉ tốn
#: đăng ký mà không thêm nhánh nào.
_SAU_TOI_DA = 6
#: Giữ tối đa ngần này chủ đề trong RAM. Nhà lớn + Frigate có thể sinh vài nghìn
#: chủ đề; không chặn thì tiến trình phình theo thời gian chạy.
_TRAN_CHU_DE = 5000

#: Tầng cuối của chủ đề là LỆNH GỬI ĐI, không phải quan sát về nhà.
#:
#: Zigbee2MQTT nhận lệnh ở `<thiết bị>/set` và trả trạng thái ở chính chủ đề
#: thiết bị. Ghi cả hai là đếm mỗi lần bật đèn HAI lần — đo thật 10/09/2026,
#: cùng một giây có `zigbee2mqtt/Bếp | state_left = ON` và
#: `zigbee2mqtt/Bếp/left | set = ON`; 211 bản ghi trên 6 thiết bị đều vậy.
#:
#: Nặng hơn chuyện đếm đôi: `set` phần lớn do CHÍNH BOT gửi, mà lại ghi với
#: `do_ai=0` nên trông như người làm. Bot sẽ học từ hành động của mình rồi tự
#: khẳng định vòng quanh — đúng thứ cột `do_ai` sinh ra để chặn.
#:
#: Đây là danh sách tên, và là ngoại lệ có lý do: "lệnh" hay "trạng thái" là
#: quy ước GIAO THỨC của Zigbee2MQTT, không suy ra được từ dữ liệu. Không có
#: nguyên tắc đo được nào thay thế; nhịp đổi của `set` giống hệt `state`.
_CHU_DE_LENH = frozenset({"set", "get"})

#: Quá bao lâu không nhận tin thì coi số liệu là CŨ, không dám khẳng định nữa.
#: Frigate publish liên tục (đo: 208 tin/40 giây), nên im quá 3 phút là gương
#: đã rớt chứ không phải nhà yên tĩnh.
_HAN_TUOI = 180.0

#: Rớt quá bao lâu mà paho chưa tự nối lại thì tự dựng phiên mới.
_HAN_ROI = 60.0
#: Đang "nối" nhưng câm quá lâu cũng là chết — máy chủ thật phát liên tục.
_HAN_IM = 600.0


class LoiMqtt(RuntimeError):
    """Hỏng ở phía MQTT — thông điệp đã sẵn sàng đọc cho người dùng."""


def stats() -> dict[str, Any]:
    return dict(_stats)


# ── Cấu hình ─────────────────────────────────────────────────────────────────

def _cau_hinh() -> dict[str, Any]:
    """Cấu hình máy chủ hiện tại (bản thật, còn mật khẩu)."""
    try:
        from services.config import config
        c = config.data.get("mqtt")
        return dict(c) if isinstance(c, dict) else {}
    except Exception:
        return {}


def che_mat_khau(c: dict[str, Any]) -> dict[str, Any]:
    """Bỏ mật khẩu khỏi một bản ghi cấu hình trước khi cho ai đó nhìn thấy."""
    m = dict(c)
    if m.get("password"):
        m["password"] = "***"
    return m


def doc_cau_hinh() -> dict[str, Any]:
    """Cấu hình máy chủ, mật khẩu đã che. Đây là bản cho web và cho model."""
    return che_mat_khau(_cau_hinh())


def luu_cau_hinh(host: str, port: int = 1883, username: str = "",
                 password: str = "", enabled: bool = True,
                 ghi_chu: str = "", uu_tien: bool | None = None) -> dict[str, Any]:
    """Khai hoặc sửa máy chủ MQTT. Trả bản ghi đã che mật khẩu.

    Mật khẩu để trống thì GIỮ mật khẩu cũ — web hiển thị ``***`` nên nếu không
    giữ, mỗi lần người dùng sửa cổng là mật khẩu bị xoá mất.
    """
    host = (host or "").strip()
    if not host:
        raise LoiMqtt("Chưa nhập địa chỉ máy chủ MQTT.")
    try:
        port = int(port or 1883)
    except (TypeError, ValueError):
        raise LoiMqtt("Cổng phải là một con số.")
    if not (1 <= port <= 65535):
        raise LoiMqtt("Cổng phải nằm trong khoảng 1–65535.")

    cu = _cau_hinh()
    mk = password if password and password != "***" else str(cu.get("password") or "")

    ban_ghi = {
        # GIỮ MỌI KHOÁ HÀM NÀY KHÔNG SỞ HỮU. Hàm gán đè CẢ khối "mqtt", mà bản
        # trước dựng bản ghi từ số không rồi cứu tay đúng hai khoá (`uu_tien`,
        # `lich_su`) — nên mọi nhánh khác bị xoá IM LẶNG mỗi lần ai đó lưu lại
        # cấu hình MQTT. Đo trên máy thật 19/09/2026: khối "mqtt" còn giữ
        # `bai_hoc`, `canh_bao`, `du_doan`, `hieu_thiet_bi` — bốn nhánh cấu hình
        # của tầng học và tầng cảnh báo, KHÔNG nhánh nào nằm trong danh sách cứu.
        # Danh sách cứu tay luôn thiếu; bắt đầu từ bản cũ rồi chỉ ghi đè phần của
        # mình thì không bao giờ sót, kể cả nhánh mai này mới thêm.
        **cu,
        "host": host,
        "port": port,
        "username": (username or "").strip(),
        "password": mk,
        "enabled": bool(enabled),
        "note": (ghi_chu or "").strip(),
        "uu_tien": bool(cu.get("uu_tien", False)) if uu_tien is None else bool(uu_tien),
    }

    from services.config import config

    def _ghi(data: dict) -> None:
        data["mqtt"] = ban_ghi

    config.mutate(_ghi)
    logger.info({"event": "mqtt_config_saved", "host": host, "port": port})
    return che_mat_khau(ban_ghi)


def uu_tien_mqtt() -> bool:
    """Có ưu tiên đi đường MQTT khi thiết bị có ở CẢ MQTT lẫn Home Assistant?

    Mặc định TẮT. Bật lên thì lệnh điều khiển thử MQTT trước; khớp không được
    thì vẫn rơi về HA như cũ — nguyên tắc của ha_live: "Tệ nhất bằng hiện
    trạng, không bao giờ tệ hơn."
    """
    return bool(_cau_hinh().get("uu_tien", False))


def _enabled() -> bool:
    """Có đủ điều kiện chạy không: phải khai host, và không tắt cờ."""
    try:
        c = _cau_hinh()
        if not str(c.get("host") or "").strip():
            return False
        return bool(c.get("enabled", True))
    except Exception:
        return False


# ── Bộ lọc đăng ký ───────────────────────────────────────────────────────────

def bo_loc_do_sau() -> list[str]:
    """Các bộ lọc ``+`` dùng để DÒ nhánh gốc.

    Tách thành hàm riêng để test khẳng định được: không bao giờ sinh ra ``#``.
    """
    return ["/".join(["+"] * n) for n in range(1, _SAU_TOI_DA + 1)]


def bo_loc_khai_bao() -> list[str]:
    """Bộ lọc đọc bản tự khai báo. Hai độ sâu vì có loại lồng thêm một tầng."""
    return ["homeassistant/+/+/config", "homeassistant/+/+/+/config"]


# ── Đọc bản tự khai báo ──────────────────────────────────────────────────────

def doc_ban_khai(chu_de: str, payload: bytes) -> tuple[str, str, dict[str, Any]] | None:
    """Đọc một bản tự khai báo thành ``(tên thiết bị, tên thực thể, mô tả)``.

    Trả ``None`` khi không phải bản khai hợp lệ — payload rỗng là chuyện BÌNH
    THƯỜNG, đó là cách gỡ một thiết bị khỏi hệ thống chứ không phải lỗi.
    """
    if not payload:
        return None
    try:
        d = json.loads(payload)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None

    dev = d.get("device")
    ten_tb = ""
    if isinstance(dev, dict):
        ten_tb = str(dev.get("name") or "").strip()
    if not ten_tb:
        # Không khai thiết bị cha thì lấy tên thực thể làm tên thiết bị — vẫn
        # điều khiển được, chỉ là mỗi thực thể đứng riêng một dòng.
        ten_tb = str(d.get("name") or "").strip()
    if not ten_tb:
        return None

    phan = chu_de.split("/")
    loai = phan[1] if len(phan) > 1 else "?"
    ten_tt = str(d.get("name") or d.get("object_id") or phan[-2] if len(phan) > 1 else "?")

    mo_ta = {
        "loai": loai,
        "doc": d.get("state_topic") or "",
        "dieu_khien": d.get("command_topic") or "",
        "bat": d.get("payload_on"),
        "tat": d.get("payload_off"),
        "mau": d.get("value_template") or "",
        "don_vi": d.get("unit_of_measurement") or "",
    }
    return ten_tb, str(ten_tt), mo_ta


def nhan_dang_frigate(chu_de: str) -> dict[str, Any] | None:
    """Nhận ra chủ đề của Frigate. Frigate KHÔNG dùng chuẩn tự khai báo.

    Frigate đăng theo lối riêng: ``frigate/<camera>/<vật thể>`` là số đếm,
    ``frigate/events`` là sự kiện, ``frigate/stats`` là tình trạng máy. Bộ này
    chuẩn bị sẵn đường cho phần cảnh báo cháy/ngã sau này.
    """
    phan = chu_de.split("/")
    if not phan or phan[0] != "frigate":
        return None
    if len(phan) == 2 and phan[1] in ("events", "stats", "available", "reviews"):
        return {"camera": "", "muc": phan[1], "loai": "he_thong"}
    if len(phan) >= 3:
        return {"camera": phan[1], "muc": "/".join(phan[2:]), "loai": "camera"}
    return None


# ── Luồng nền ────────────────────────────────────────────────────────────────

def _nap_tin(chu_de: str, payload: bytes, dang_ky) -> None:
    """Xử lý một tin đến. ``dang_ky`` là hàm đăng ký thêm chủ đề (có thể None).

    Tách khỏi callback của paho để test gọi thẳng được, không cần máy chủ thật.
    """
    goc = chu_de.split("/")[0]

    with _khoa_du_lieu:
        moi = goc and goc not in _nhanh_goc
        if moi:
            _nhanh_goc.add(goc)
        # Vượt trần thì thôi không nhớ thêm chủ đề mới, nhưng vẫn cập nhật chủ
        # đề đã biết — mất chủ đề lạ còn hơn phình bộ nhớ vô hạn.
        if chu_de in _gia_tri or len(_gia_tri) < _TRAN_CHU_DE:
            try:
                _gia_tri[chu_de] = (payload.decode("utf-8", "replace"), time.time())
            except Exception:
                _gia_tri[chu_de] = (repr(payload[:80]), time.time())
        _stats["tin"] += 1
        _stats["last_tin_ts"] = time.time()
        _stats["nhanh"] = len(_nhanh_goc)

    # Nhánh gốc mới → mở rộng ra cả nhánh đó. Đây là bước biến "+" thành phủ đủ.
    if moi and dang_ky is not None:
        try:
            dang_ky(f"{goc}/#", 0)
            logger.info({"event": "mqtt_nhanh_moi", "nhanh": goc})
        except Exception as exc:
            logger.warning({"event": "mqtt_dang_ky_loi", "nhanh": goc,
                            "error": str(exc)[:120]})

    # Ghi vào lịch sử để quản gia học sau này. Bọc kín: ghi hỏng thì mất bản
    # ghi đó, TUYỆT ĐỐI không được làm chết gương MQTT.
    try:
        from services import lich_su_nha
        # Sự kiện Frigate: ghi_frigate() đã viết và đã test từ lâu nhưng CHƯA
        # AI GỌI — đây là chỗ nối. Nó chỉ giữ lúc bắt đầu/kết thúc, bỏ 'update'
        # (Frigate phát 208 tin/40 giây, phần lớn là update của cùng sự kiện).
        if chu_de == "frigate/events":
            try:
                _su_kien = json.loads(payload.decode("utf-8", "replace"))
            except (ValueError, TypeError):
                _su_kien = None
            if _su_kien is not None:
                lich_su_nha.ghi_frigate(_su_kien)
                # Canh camera: Frigate thấy người → nhận mặt (xếp hàng, không chặn).
                from services import canh_camera_nha
                canh_camera_nha.su_kien_frigate(_su_kien)

        phan = chu_de.split("/")
        # KHÔNG `return` sau nhánh Frigate: `return` ở đây thoát khỏi cả hàm
        # nên bỏ luôn phần dựng sổ thiết bị phía dưới.
        if chu_de != "frigate/events" and len(phan) >= 2 and goc != "homeassistant":
            thiet_bi = "/".join(phan[:-1])
            truong = phan[-1]
            gt = payload.decode("utf-8", "replace").strip()
            # Payload JSON (Zigbee2MQTT gửi cả cụm) → tách từng trường. Tên
            # thiết bị là CẢ chủ đề: `zigbee2mqtt/Bếp` gửi {"state_left": ...}.
            if gt.startswith("{"):
                try:
                    for k, v in (json.loads(gt) or {}).items():
                        if not isinstance(v, (dict, list)):
                            lich_su_nha.ghi("mqtt", chu_de, str(k), v)
                except (ValueError, TypeError):
                    pass
            elif gt and truong not in _CHU_DE_LENH:
                lich_su_nha.ghi("mqtt", thiet_bi, truong, gt)
    except Exception:
        pass

    # Bản tự khai báo → dựng sổ thiết bị.
    if goc == "homeassistant" and chu_de.endswith("/config"):
        kq = doc_ban_khai(chu_de, payload)
        if kq:
            ten_tb, ten_tt, mo_ta = kq
            with _khoa_du_lieu:
                _so_thiet_bi.setdefault(ten_tb, {})[ten_tt] = mo_ta
                _stats["thiet_bi"] = len(_so_thiet_bi)


def _tao_client(cid: str = "c2a-mqtt"):
    """Dựng một client paho đã cấu hình. Ném ``LoiMqtt`` nếu chưa khai máy chủ."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        raise LoiMqtt("Chưa cài thư viện paho-mqtt trong image này.")

    c = _cau_hinh()
    host = str(c.get("host") or "").strip()
    if not host:
        raise LoiMqtt("Chưa khai máy chủ MQTT trong Cài đặt.")

    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
    if c.get("username"):
        cl.username_pw_set(str(c["username"]), str(c.get("password") or ""))
    return cl, host, int(c.get("port") or 1883)


def _chay_mot_phien() -> None:
    """Một phiên kết nối. Ném ngoại lệ khi đứt để vòng ngoài nối lại."""
    cl, host, port = _tao_client("c2a-mqtt-nha")

    def on_connect(client, userdata, flags, rc, props=None):
        # Đăng ký DÒ bằng '+' nhiều độ sâu. KHÔNG dùng '#' — xem cảnh báo đầu file.
        client.subscribe([(f, 0) for f in bo_loc_do_sau()])
        client.subscribe([(f, 0) for f in bo_loc_khai_bao()])
        # Nhánh đã biết từ phiên trước: đăng ký lại ngay, khỏi chờ dò lại.
        with _khoa_du_lieu:
            da_biet = sorted(_nhanh_goc)
        for g in da_biet:
            client.subscribe(f"{g}/#", 0)
        _stats["connected"] = True
        logger.info({"event": "mqtt_connected", "host": host, "nhanh_cu": len(da_biet)})

    def on_message(client, userdata, m):
        try:
            _nap_tin(m.topic, m.payload, client.subscribe)
        except Exception as exc:
            logger.warning({"event": "mqtt_nap_tin_loi", "error": str(exc)[:120]})

    def on_disconnect(client, userdata, flags, rc, props=None):
        _stats["connected"] = False
        _stats["_roi_tu"] = time.time()
        logger.warning({"event": "mqtt_roi", "rc": str(rc)[:40]})

    cl.on_connect = on_connect
    cl.on_message = on_message
    cl.on_disconnect = on_disconnect

    cl.connect(host, port, 60)
    cl.loop_start()
    try:
        # Luồng nền của paho lo keepalive, NHƯNG nó có thể kẹt ở trạng thái
        # "đã rớt mà không nối lại được" và không báo gì cả. Chỉ canh cờ dừng
        # thì hàm này quay vòng vĩnh viễn, vòng ngoài không bao giờ nối lại →
        # gương chết IM LẶNG. Đo thật 09/09/2026: rớt 150 phút, reconnects=0,
        # không một dòng log, mà bot vẫn trả lời bằng số đã đóng băng.
        #
        # Nên canh THÊM độ tươi: cờ connected tắt quá lâu, hoặc đang nối mà
        # không tin nào về quá lâu → ném để vòng ngoài dựng phiên mới.
        while not _stop.is_set():
            _stop.wait(1.0)
            now = time.time()
            if not _stats.get("connected"):
                if now - _stats.get("_roi_tu", now) > _HAN_ROI:
                    raise RuntimeError(
                        f"rớt quá {_HAN_ROI:.0f}s mà paho không nối lại được")
                _stats.setdefault("_roi_tu", now)
                continue
            _stats.pop("_roi_tu", None)
            cuoi = float(_stats.get("last_tin_ts") or 0)
            if cuoi and now - cuoi > _HAN_IM:
                raise RuntimeError(
                    f"nối nhưng {(now - cuoi) / 60:.0f} phút không tin nào về")
    finally:
        _stats["connected"] = False
        try:
            cl.loop_stop()
            cl.disconnect()
        except Exception:
            pass


def _chay_mai() -> None:
    backoff = _BACKOFF_START
    while not _stop.is_set():
        try:
            _chay_mot_phien()
            backoff = _BACKOFF_START      # phiên sống tử tế rồi mới đứt → reset
        except Exception as exc:
            _stats["last_error"] = str(exc)[:160]
            logger.warning({"event": "mqtt_disconnected", "error": str(exc)[:160],
                            "retry_in_s": round(backoff)})
        if _stop.is_set():
            return
        _stats["reconnects"] += 1
        _stop.wait(backoff)
        backoff = min(backoff * 2, _BACKOFF_CAP)


def start() -> bool:
    """Khởi động lớp MQTT (idempotent). Trả True nếu đang/đã chạy."""
    global _thread
    if not _enabled():
        return False
    with _started_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _stop.clear()
        _thread = threading.Thread(target=_chay_mai, daemon=True, name="mqtt-nha")
        _thread.start()
        logger.info({"event": "mqtt_started"})
        return True


def stop() -> None:
    _stop.set()


# ── Đọc ra cho người dùng ────────────────────────────────────────────────────

def _tu(s: str) -> set[str]:
    from services.agent.vi_text import fold
    return {t for t in re.split(r"[^0-9a-z]+", fold(s)) if t}


def danh_sach_thiet_bi() -> list[dict[str, Any]]:
    """Thiết bị đã tìm thấy. Ba nguồn, không nguồn nào lộ mật khẩu.

    ``tu_khai_bao`` là thiết bị tự nói mình là gì (Zigbee2MQTT, Tasmota…);
    ``frigate`` là camera; ``tho`` là nhánh chưa nhận ra — hiện nguyên chủ đề
    chứ không đoán bừa nó là thiết bị gì.
    """
    ra: list[dict[str, Any]] = []
    with _khoa_du_lieu:
        so = {k: dict(v) for k, v in _so_thiet_bi.items()}
        gt = dict(_gia_tri)
        nhanh = set(_nhanh_goc)

    for ten, ents in sorted(so.items()):
        doc, dk = [], []
        for ten_tt, m in sorted(ents.items()):
            muc = {"ten": ten_tt, "loai": m.get("loai") or "",
                   "don_vi": m.get("don_vi") or ""}
            if m.get("dieu_khien"):
                muc["chu_de"] = m["dieu_khien"]
                muc["bat"] = m.get("bat")
                muc["tat"] = m.get("tat")
                dk.append(muc)
            else:
                ct = m.get("doc") or ""
                muc["chu_de"] = ct
                v = gt.get(ct)
                muc["gia_tri"] = v[0][:120] if v else None
                doc.append(muc)
        ra.append({"ten": ten, "nguon": "tu_khai_bao", "nhanh": "homeassistant",
                   "doc": doc, "dieu_khien": dk})

    # Frigate: gom theo camera.
    cam: dict[str, list[dict[str, Any]]] = {}
    for ct, (v, _ts) in sorted(gt.items()):
        f = nhan_dang_frigate(ct)
        if f and f["loai"] == "camera":
            cam.setdefault(f["camera"], []).append(
                {"ten": f["muc"], "chu_de": ct, "gia_tri": str(v)[:120]})
    for c, ds in sorted(cam.items()):
        ra.append({"ten": f"Camera {c}", "nguon": "frigate", "nhanh": "frigate",
                   "doc": ds, "dieu_khien": []})

    # Nhánh thô: có tin nhưng chưa bộ nào nhận ra.
    da_biet = {"homeassistant", "frigate"}
    for g in sorted(nhanh - da_biet):
        ds = [{"ten": ct, "chu_de": ct, "gia_tri": str(v)[:120]}
              for ct, (v, _ts) in sorted(gt.items()) if ct.split("/")[0] == g][:40]
        if ds:
            ra.append({"ten": g, "nguon": "tho", "nhanh": g,
                       "doc": ds, "dieu_khien": []})
    # Chủ máy «Bỏ khỏi c2a» — bỏ ở ĐÂY thì `_khop_ten` (điều khiển theo tên) và
    # mọi chỗ liệt kê cùng không thấy thiết bị đó.
    from services import thiet_bi_bo

    return [d for d in ra if not thiet_bi_bo.la_bo("mqtt", d["ten"])]


def trang_thai(ten: str) -> dict[str, Any] | None:
    """Giá trị mới nhất của một thiết bị. Không khớp tên thì trả ``None``."""
    khop = _khop_ten(ten)
    if not khop:
        return None
    with _khoa_du_lieu:
        ents = dict(_so_thiet_bi.get(khop) or {})
        gt = dict(_gia_tri)
    ra: dict[str, Any] = {"ten": khop}
    for ten_tt, m in ents.items():
        ct = m.get("doc") or ""
        if ct and ct in gt:
            ra[ten_tt] = gt[ct][0][:200]
    return ra


def _khop_ten(ten: str) -> str:
    """Khớp câu người dùng nói với một tên thiết bị đã tìm thấy.

    Trả tên khi chốt được, ``""`` khi mập mờ hoặc không dính. Giống
    ``camera_nha._khop``: bật nhầm thiết bị là chuyện không sửa lại được, nên
    mập mờ thì trả rỗng để tầng trên HỎI LẠI chứ không đoán.
    """
    ten = (ten or "").strip()
    if not ten:
        return ""
    # PHẢI gộp cả camera Frigate: chúng không đi qua chuẩn tự khai báo nên
    # không nằm trong `_so_thiet_bi`. Chỉ tra `_so_thiet_bi` thì hỏi "camera
    # phòng khách" là trả rỗng, bot đành chịu — dù danh sách thiết bị có nó.
    so = [d["ten"] for d in danh_sach_thiet_bi()]
    if not so:
        return ""

    q = _tu(ten)
    if not q:
        return ""
    y_het = [k for k in so if _tu(k) == q]
    if len(y_het) == 1:
        return y_het[0]
    if len(y_het) > 1:
        return ""

    diem = [(len(q & _tu(k)), k) for k in so]
    cao = max((d for d, _ in diem), default=0)
    if cao < 1:
        return ""
    dan = [k for d, k in diem if d == cao]
    return dan[0] if len(dan) == 1 else ""


def dem_nguoi(camera: str = "") -> dict[str, Any]:
    """Frigate ĐẾM SẴN người trong khung hình — đọc thẳng, KHÔNG chụp lại ảnh.

    Frigate chạy YOLO 24/7 trên GPU và publish số đếm lên
    ``frigate/<camera>/person``. Hỏi "phòng khách có người không" mà đi dựng
    luồng RTSP rồi gọi model thị giác là làm lại việc máy đã làm xong: chậm vài
    giây, tốn tiền model, mà kết quả không chính xác hơn.

    Chỉ chụp ảnh khi người dùng muốn NHÌN, hoặc hỏi thứ Frigate không đếm
    ("trên bàn có gì", "con mèo đang làm gì").

    Trả ``{camera: {"nguoi": n, "dang_hoat_dong": n, "ts": …}}``.
    """
    ra: dict[str, Any] = {}
    with _khoa_du_lieu:
        gt = dict(_gia_tri)
        tin_cuoi = float(_stats.get("last_tin_ts") or 0)
    # Số đếm CŨ nguy hiểm hơn không có số: MQTT chỉ gửi khi giá trị ĐỔI, nên
    # mất kết nối là giá trị cuối cùng đóng băng vĩnh viễn. Đo thật 09/09/2026:
    # gương rớt 150 phút mà vẫn báo "1 người" trong khi Frigate hiện là 0.
    # Thà nói "em không chắc" còn hơn khẳng định một con số đã chết.
    cu = time.time() - tin_cuoi if tin_cuoi else None
    if cu is None or cu > _HAN_TUOI:
        return {"_cu": True, "_giay": cu, "_han": _HAN_TUOI}
    can = _tu(camera) if camera else set()
    from services import thiet_bi_bo

    for ct, (v, ts) in gt.items():
        f = nhan_dang_frigate(ct)
        if not f or f["loai"] != "camera":
            continue
        # Đọc thẳng `_gia_tri`, không qua `danh_sach_thiet_bi` — nên camera chủ
        # máy đã «Bỏ khỏi c2a» phải chặn riêng ở đây, theo gốc chủ đề đã lưu.
        if thiet_bi_bo.la_bo_lich_su(ct):
            continue
        muc = f["muc"]
        if muc not in ("person", "person/active", "all", "all/active"):
            continue
        cam = f["camera"]
        if can and not (can & _tu(cam)):
            continue
        try:
            n = int(str(v).strip())
        except (TypeError, ValueError):
            continue
        m = ra.setdefault(cam, {"camera": cam, "nguoi": 0, "dang_hoat_dong": 0,
                                "vat_the": 0, "ts": ts})
        if muc == "person":
            m["nguoi"] = n
        elif muc == "person/active":
            m["dang_hoat_dong"] = n
        elif muc == "all":
            m["vat_the"] = n
        m["ts"] = max(m["ts"], ts)
    return ra


def dieu_khien(ten: str, thuc_the: str, gia_tri: Any) -> bool:
    """Gửi một lệnh tới thiết bị. Ném ``LoiMqtt`` với lời giải thích khi không được.

    Chỉ gửi khi tên khớp CHÍNH XÁC một thiết bị và thực thể đó thật sự có chủ đề
    nhận lệnh — không suy đoán chủ đề từ tên, vì gửi nhầm chỗ thì thiết bị khác
    bật lên mà người dùng không biết vì sao.
    """
    khop = _khop_ten(ten)
    if not khop:
        with _khoa_du_lieu:
            co = sorted(_so_thiet_bi)
        if not co:
            raise LoiMqtt("Chưa tìm thấy thiết bị nào trên MQTT. Bấm «Quét thiết bị» trong Cài đặt trước.")
        raise LoiMqtt(f"Không rõ '{ten}' là thiết bị nào. Đang có: {', '.join(co[:12])}.")

    with _khoa_du_lieu:
        ents = dict(_so_thiet_bi.get(khop) or {})

    m = ents.get(thuc_the)
    if m is None:
        # Nới: khớp không phân biệt hoa thường và dấu.
        q = _tu(thuc_the)
        ung = [k for k in ents if _tu(k) == q] if q else []
        if len(ung) == 1:
            thuc_the, m = ung[0], ents[ung[0]]
    if m is None:
        dk = [k for k, v in ents.items() if v.get("dieu_khien")]
        raise LoiMqtt(f"Thiết bị '{khop}' không có '{thuc_the}'. "
                      f"Điều khiển được: {', '.join(dk) if dk else 'không có gì'}.")

    ct = m.get("dieu_khien")
    if not ct:
        raise LoiMqtt(f"'{thuc_the}' của '{khop}' chỉ đọc được, không điều khiển được.")

    # Chữ bật/tắt lấy từ chính bản khai của thiết bị, không tự chế.
    tin = gia_tri
    if isinstance(gia_tri, bool):
        tin = m.get("bat", "ON") if gia_tri else m.get("tat", "OFF")
    elif isinstance(gia_tri, str) and gia_tri.strip().lower() in ("on", "bật", "bat", "mở", "mo"):
        tin = m.get("bat", "ON")
    elif isinstance(gia_tri, str) and gia_tri.strip().lower() in ("off", "tắt", "tat", "đóng", "dong"):
        tin = m.get("tat", "OFF")
    if tin is None:
        tin = "ON"

    cl, host, port = _tao_client("c2a-mqtt-gui")
    try:
        cl.connect(host, port, 20)
        cl.loop_start()
        r = cl.publish(ct, str(tin), qos=1)
        r.wait_for_publish(10)
        ok = r.is_published()
    except Exception as exc:
        raise LoiMqtt(f"Gửi lệnh không được: {str(exc)[:120]}")
    finally:
        try:
            cl.loop_stop()
            cl.disconnect()
        except Exception:
            pass

    logger.info({"event": "mqtt_dieu_khien", "thiet_bi": khop,
                 "thuc_the": thuc_the, "chu_de": ct, "ok": ok})
    if not ok:
        raise LoiMqtt("Máy chủ MQTT không xác nhận đã nhận lệnh.")

    # do_ai=True: đánh dấu ĐÂY LÀ BOT LÀM, không phải người. Không có dấu này
    # thì giai đoạn sau bot học từ chính hành động của mình rồi tự khẳng định
    # vòng quanh, và không đo được "bot đoán đúng bao nhiêu lần".
    try:
        from services import lich_su_nha
        lich_su_nha.ghi("mqtt", khop, thuc_the, tin, do_ai=True)
    except Exception:
        pass
    return True


# ── Quét theo yêu cầu ────────────────────────────────────────────────────────

def lam_moi(giay: float = 20) -> dict[str, Any]:
    """Quét lại máy chủ trong ``giây`` giây, trả tóm tắt tìm được.

    Dùng khi người dùng bấm «Quét thiết bị»: mở một kết nối riêng, nghe một lúc
    rồi đóng. Không đụng luồng nền đang chạy — hai kết nối cùng lúc là chuyện
    bình thường với MQTT, và tách ra thì quét hỏng cũng không làm chết gương.
    """
    giay = max(3.0, min(float(giay or 20), 60.0))
    cl, host, port = _tao_client("c2a-mqtt-quet")

    def on_connect(client, userdata, flags, rc, props=None):
        client.subscribe([(f, 0) for f in bo_loc_do_sau()])
        client.subscribe([(f, 0) for f in bo_loc_khai_bao()])

    def on_message(client, userdata, m):
        try:
            _nap_tin(m.topic, m.payload, client.subscribe)
        except Exception:
            pass

    cl.on_connect = on_connect
    cl.on_message = on_message
    try:
        cl.connect(host, port, 30)
    except Exception as exc:
        raise LoiMqtt(f"Không nối được tới {host}:{port} — {str(exc)[:120]}")
    cl.loop_start()
    time.sleep(giay)
    cl.loop_stop()
    try:
        cl.disconnect()
    except Exception:
        pass

    with _khoa_du_lieu:
        kq = {"so_thiet_bi": len(_so_thiet_bi), "so_chu_de": len(_gia_tri),
              "nhanh": sorted(_nhanh_goc)}
    logger.info({"event": "mqtt_quet_xong", **kq})
    return kq


def thu_ket_noi(host: str, port: int = 1883, username: str = "",
                password: str = "") -> dict[str, Any]:
    """Thử nối tới một máy chủ (chưa cần lưu). Trả ``{ok, error}``.

    Nghe 5 giây để đếm nhánh — nối được mà không tin nào về thường là quyền bị
    giới hạn, và người dùng cần biết điều đó ngay lúc khai chứ không phải lúc bot
    trả lời sai.
    """
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        return {"ok": False, "error": "Chưa cài thư viện paho-mqtt trong image này."}

    host = (host or "").strip()
    if not host:
        return {"ok": False, "error": "Chưa nhập địa chỉ máy chủ."}
    if password == "***":
        password = str(_cau_hinh().get("password") or "")

    thay: set[str] = set()
    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="c2a-mqtt-thu")
    if username:
        cl.username_pw_set(username, password or "")
    cl.on_connect = lambda c, u, f, rc, props=None: c.subscribe(
        [(x, 0) for x in bo_loc_do_sau()])
    cl.on_message = lambda c, u, m: thay.add(m.topic.split("/")[0])

    try:
        cl.connect(host, int(port or 1883), 20)
    except Exception as exc:
        return {"ok": False, "error": f"Không nối được: {str(exc)[:140]}"}
    cl.loop_start()
    time.sleep(5)
    cl.loop_stop()
    try:
        cl.disconnect()
    except Exception:
        pass

    return {"ok": True, "so_nhanh": len(thay), "nhanh": sorted(thay)}


def _reset_for_tests() -> None:
    """Xoá sạch trạng thái module. Chỉ dùng trong test."""
    with _khoa_du_lieu:
        _gia_tri.clear()
        _so_thiet_bi.clear()
        _nhanh_goc.clear()
    _stats.update({"connected": False, "tin": 0, "thiet_bi": 0, "nhanh": 0,
                   "last_error": "", "reconnects": 0, "last_tin_ts": 0.0})
