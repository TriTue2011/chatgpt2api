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
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config

# Bộ ghi log CỦA NHÀ. `logging.getLogger(__name__)` propagate lên root, mà ứng
# dụng này không cấu hình logging ở đâu cả — root không handler, mức WARNING —
# nên mọi `logger.info` ở đây bốc hơi. Đo 13/09/2026: gọi một đường im rồi tìm
# trong log, ra 0 dòng. Cảnh báo thiết bị hỏng mà hỏng lặng thì không ai biết.
from utils.log import logger

#: Mã thực thể Home Assistant: `miền.tên`, chữ thường. Mã MQTT/Frigate có "/".
_MA_HA = re.compile(r"[a-z_]+\.[a-z0-9_]+")

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


def _kenh_nhan() -> list[str]:
    """Kênh nhận ĐÍCH DANH — khoá ``plat:bot:chat`` như «Lọc thread».

    Chủ máy chốt 10/09/2026: muốn tự đặt kênh cho cảnh báo hỏng, tách khỏi
    kênh của phần học tập. Ô chọn "telegram | zalo" cũ không đủ vì nhà có
    nhiều tài khoản Zalo và nhiều nhóm.

    Rỗng = giữ nguyên đường cũ (`_nguoi_nhan` ba tầng), nên bật tính năng này
    không làm hỏng cảnh báo đang chạy.
    """
    raw = _cfg().get("kenh_nhan")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _nguoi_nhan() -> list[str]:
    """Ai nhận cảnh báo. Tìm theo ba tầng, KHÔNG bắt khai lại từ đầu.

    Chủ máy đã khai admin cho từng bot ở tab Kênh chat (`telegram_bots[].
    admin_thread`, `zalo_bots[].admin_thread`). Bản đầu của hàm này chỉ đọc
    `agent_heartbeat.admin_user_ids` — khoá đó trống nên MỌI cảnh báo bị nuốt
    im lặng, kể cả 181 thiết bị đang hỏng. Phải dùng lại đúng chỗ đã khai.
    """
    raw = _cfg().get("nguoi_nhan")
    if isinstance(raw, list) and raw:
        return [str(x).strip() for x in raw if str(x).strip()]

    try:
        from services.agent import heartbeat
        ds = heartbeat.admin_user_ids()
        if ds:
            return ds
    except Exception:
        pass

    # Tầng cuối: admin đã khai cho từng bot. Tiền tố kênh theo quy ước của
    # reminders.channel_of — 'zalo_'/'zalop_' hoặc để trần cho Telegram.
    ra: list[str] = []
    try:
        from services import admin_workspace as aw
        from services.config import config as _c
        for key, tien_to in (("telegram_bots", ""), ("zalo_bots", "zalo_")):
            for b in (_c.data.get(key) or []):
                if not isinstance(b, dict) or not b.get("enabled", True):
                    continue
                for cid in aw.admin_thread_ids(b):
                    # 'chat:thread' → chỉ lấy phần chat, reminders tự lo thread.
                    x = tien_to + str(cid).split(":")[0]
                    if x not in ra:
                        ra.append(x)
    except Exception as exc:
        logger.info({"event": "canh_bao_tim_admin_loi", "error": str(exc)[:120]})
    return ra


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


def _tra_cuu() -> tuple[dict[str, str], dict[str, str]]:
    """(tên theo mã, khu vực theo mã) — dựng MỘT lần cho cả tin, không tra lại
    cho từng lỗi.

    Tên thực thể lấy qua ``ha_client.get_states()`` — đúng nơi đã ẩn sẵn thực
    thể có mật khẩu trong tên (`_an_thuc_the_mang_mat_khau`). Nhờ đi qua đó,
    tin cảnh báo không thể vô tình mang mật khẩu camera ra Zalo.

    Hỏng thì trả về rỗng chứ không ném: mất tên còn đọc được, mất cảnh báo thì
    không.
    """
    ten: dict[str, str] = {}
    khu: dict[str, str] = {}
    try:
        from services import ha_client
        for s in ha_client.get_states():
            eid = str(s.get("entity_id") or "")
            fn = str((s.get("attributes") or {}).get("friendly_name") or "")
            if eid and fn:
                ten[eid] = fn
        khu = dict((ha_client.get_ha_area_index() or {}).get("entity_area") or {})
    except Exception as exc:
        logger.info({"event": "canh_bao_tra_ten_loi", "error": str(exc)[:120]})
    return ten, khu


def _ten_khu(ma: str, ten_map: dict[str, str],
             khu_map: dict[str, str]) -> tuple[str, str]:
    """Tên người đọc được và khu vực của một mã. Rỗng = chưa biết.

    Đo trên 11 lỗi thật 13/09/2026: mã đi vào đây có HAI dạng — 4 mã thực thể
    Home Assistant (`sensor.hien_dien_phong_hoc_illuminance`) và 7 topic MQTT
    (`cmnd/X_SMART_LINK_A44F95/irhvac`, `zigbee2mqtt/Báo khói bếp`). Hai dạng
    tra hai sổ khác nhau.

    KHÔNG suy phòng từ chữ trong mã. `hien_dien_phong_hoc` trông đúng là "phòng
    học", nhưng khớp chuỗi rồi không ai kiểm chứng chính là lớp lỗi kho này đã
    trả giá ba lần trong một buổi sáng. Khu vực chỉ lấy từ chỉ mục HA; không có
    thì thôi, không đoán.
    """
    if "/" in ma:                       # topic MQTT — không có khu vực
        try:
            from services import so_ten_nha
            return so_ten_nha.ten_cua("mqtt", "thiet_bi", ma), ""
        except Exception:
            return "", ""
    return ten_map.get(ma, ""), khu_map.get(ma, "")


def _mo_ta(h: dict[str, Any], ten_map: dict[str, str] | None = None,
           khu_map: dict[str, str] | None = None) -> str:
    """Một dòng cho một lỗi: thiết bị gì, ở đâu, tên gì, mã gì, hỏng ra sao.

    Chủ máy 13/09/2026: *"Không liệt kê rõ ràng thiết bị gì, ở đâu, tên nếu có,
    entity nếu có"*. Bản cũ chỉ in mỗi mã máy (`cmnd/X_SMART_LINK_A44F95/irhvac
    · Power`) nên không ai biết đó là cái gì trong nhà.

    Giữ ĐÚNG MỘT dòng thụt lề cho mỗi lỗi: `_soan_tin` đếm `"\\n   "` để chặn
    dội 156 lỗi một lượt, thêm dòng thụt nữa là phép chặn đó âm thầm sai.
    """
    ma = str(h.get("thiet_bi") or "?")
    tr = str(h.get("truong") or "")
    nhan = {"chet": "🔴 chết hẳn", "do": "🟠 đơ (vẫn báo nhưng số không đổi)",
            "chap_chon": "🟡 chập chờn", "mat_ket_noi": "🔌 mất kết nối"}.get(str(h.get("loai")), str(h.get("loai")))
    ct = str(h.get("chi_tiet") or "")
    ten, khu = _ten_khu(ma, ten_map or {}, khu_map or {})

    dau = ten or ma
    if khu:
        dau += f" ({khu})"
    # Biết tên thì vẫn kèm mã ở dòng dưới — chủ máy cần mã để tra trong HA.
    # Chưa biết tên thì mã đã nằm ở đầu dòng rồi, đừng lặp lại.
    duoi = ct if not ten else (f"{ma} — {ct}" if ct else ma)
    return (f"{nhan} — {dau}"
            + (f" · {tr}" if tr and tr != "state" else "")
            + f"\n   {duoi}")


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


def con_ton_tai(hong: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bỏ những lỗi của thiết bị KHÔNG CÒN trong nguồn của nó (đã xoá hay đổi tên) — cho cả tin
    cảnh báo lẫn thẻ «soi hỏng» trên web. Chủ máy 29/09/2026: "giảm thiểu tối đa các thiết bị không
    còn mà vẫn theo dõi". Đối chiếu MỖI lần gọi với danh sách hiện tại của HA và bản tự khai báo MQTT
    — không có sổ nào phải dọn tay."""
    # Mã dạng Home Assistant mà HA hiện KHÔNG có thì không báo: thiết bị đã xoá
    # hay đổi tên thì báo "chết" là báo nhầm, mà tin cảnh báo in thẳng mã
    # (`_mo_ta`). Đo 11/09/2026: mã 4 camera go2rtc của nhà mang mật khẩu dạng
    # slug; `ha_client.get_states` đã ẩn chúng, lọc theo đó thì mã không ra tin.
    from services import ha_client

    con_trong_ha = {str(s.get("entity_id") or "") for s in (ha_client.get_states() or [])}
    if con_trong_ha:
        hong = [h for h in hong if not _MA_HA.fullmatch(str(h.get("thiet_bi") or ""))
                or h.get("thiet_bi") in con_trong_ha]
    # Chủ đề MQTT: cùng lẽ ấy với bản TỰ KHAI BÁO — nhánh có khai (Zigbee2MQTT) mà chủ đề không
    # còn ai khai là thiết bị đã đổi tên hoặc bị gỡ. Chưa nhận bản khai nào (MQTT chưa nối) thì
    # giữ nguyên, không đoán.
    from services import mqtt_nha

    con_khai, goc_khai = mqtt_nha.chu_de_con_khai()
    hong = [h for h in hong if "/" not in str(h.get("thiet_bi") or "")
            or str(h.get("thiet_bi")).split("/")[0] not in goc_khai or h.get("thiet_bi") in con_khai]

    return thiet_bi_con_song(hong)


def thiet_bi_con_song(hong: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Xét «chết» theo THIẾT BỊ, không theo từng thực thể; thực thể CÀI ĐẶT thì không bao giờ là hỏng.

    Chủ máy 30/09/2026 với tin «🔴 chết hẳn — Ban-Cong Motion»: "Vẫn chưa phân biệt được đâu là cảm biến
    setting, đâu là cảm biến thay đổi". Đo lúc đó: `binary_sensor.ban_cong_motion` (Frigate) im từ 18:03 29/09,
    nhưng CÙNG camera ấy `…_person_occupancy` và `…_speech_sound` đổi 400+ lần tới 19:57 hôm nay; công tắc
    cài đặt `switch.ban_cong_motion` vẫn bật. Camera sống — tín hiệu im là do cách tích hợp/cài đặt phát nó
    (`bep_motion` cũng chưa bật lần nào suốt 9 ngày dù bếp ngày nào cũng có người), không phải hỏng.

    Nguyên tắc, không danh sách: (1) HA tự khai loại thực thể — `entity_category == "config"` là cài đặt,
    đứng im là bình thường. (2) Lỗi «chết» (im hẳn, không tin nào) của thực thể thuộc một thiết bị mà một
    thực thể CHÍNH khác của cùng thiết bị đó còn ĐỔI giá trị sau lần đổi cuối của nó → thiết bị còn sống,
    không báo. «Đơ» (vẫn gửi mà số đứng yên) giữ nguyên: thiết bị sống mà số đo kẹt vẫn là hỏng thật.
    Không có sổ thiết bị của HA thì để nguyên, không đoán."""
    from services import ha_client, lich_su_nha

    try:
        idx = ha_client.get_ha_area_index() or {}
    except Exception:  # noqa: BLE001
        return hong
    tb_cua = idx.get("entity_device_ids") or {}
    loai_tt = idx.get("entity_category") or {}
    hong = [h for h in hong if loai_tt.get(str(h.get("thiet_bi") or "")) != "config"]
    anh_em: dict[tuple, list[str]] = {}
    for ma, ids in tb_cua.items():
        if ids and ma not in loai_tt:
            anh_em.setdefault(tuple(ids), []).append(ma)

    def cua(h: dict[str, Any]) -> list[str]:
        return [m for m in anh_em.get(tuple(tb_cua.get(h["thiet_bi"]) or ()), []) if m != h["thiet_bi"]]

    chet = [h for h in hong if h.get("loai") == "chet" and cua(h)]
    if not chet:
        return hong
    try:
        cuoi = lich_su_nha.lan_doi_cuoi(sorted({m for h in chet for m in cua(h)}))
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "canh_bao_anh_em_loi", "error": str(exc)[:200]})
        return hong
    bo = set()
    for h in chet:
        song = [m for m in cua(h) if cuoi.get(m, 0.0) > float(h.get("lan_cuoi_tot") or 0.0)]
        if song:
            bo.add(id(h))
            logger.info({"event": "canh_bao_bo_vi_thiet_bi_con_song", "thiet_bi": h["thiet_bi"],
                         "anh_em": song[:3]})
    return [h for h in hong if id(h) not in bo]


# ── Mất kết nối (thực thể HA đang `unavailable`) ────────────────────────────
# Chủ máy 29/09/2026: "khi nào thiết bị không khả dụng, mất kết nối mới là đơ" — và "lấy thêm thông
# tin từ homeassistant, mqtt … tìm kiếm cả thông tin cộng đồng". Tài liệu HA: `unavailable` = "HA
# cannot reach the device or service"; `unknown` = có kết nối nhưng chưa có giá trị (không phải lỗi).
# Nhưng `unavailable` cũng không phải lúc nào cũng hỏng: đo 29/09/2026, 110 thực thể cùng
# `unavailable` từ lúc HA khởi động lại — tivi tắt nguồn, app HA trên máy tính bảng không mở. Nên so
# với NẾP của chính thực thể (lịch sử HA giữ cả `unavailable`, kho c2a thì không): báo khi lần mất
# kết nối này dài hơn MỌI lần trước trong cửa sổ, và thực thể từng khả dụng trong cửa sổ đó.
#: Ngắn hơn ngần này không báo — HA khởi động lại, mạng chớp vài phút là chuyện thường.
MAT_KET_NOI_TOI_THIEU = 3600
MAT_KET_NOI_NGAY = 30
#: (mã, lúc bắt đầu mất kết nối) → lỗi hoặc None — mỗi lần mất kết nối chỉ tra lịch sử HA MỘT lần
#: (quét chạy 5 phút một lần; ~100 thực thể `unavailable` cùng lúc sau khi HA khởi động lại).
_mkn_da_xet: dict[tuple[str, float], dict[str, Any] | None] = {}


def _lich_su_ha(ma: list[str], tu: float) -> dict[str, list[tuple[float, str]]]:
    """{mã: [(ts, trạng thái chữ thường)]} từ /api/history của HA (giữ cả `unavailable`)."""
    import urllib.parse
    from services import lich_su_nha

    ra: dict[str, list[tuple[float, str]]] = {}
    bat_dau = datetime.fromtimestamp(tu, timezone.utc).isoformat()
    for i in range(0, len(ma), 40):
        # end_time BẮT BUỘC: thiếu nó HA chỉ trả MỘT ngày tính từ mốc đầu (đo 29/09/2026: 30 ngày → rỗng).
        q = urllib.parse.urlencode({"filter_entity_id": ",".join(ma[i:i + 40]), "minimal_response": "true",
                                    "no_attributes": "true",
                                    "end_time": datetime.now(timezone.utc).isoformat()})
        for chuoi in lich_su_nha._ha_lay("/api/history/period/" + urllib.parse.quote(bat_dau) + "?" + q) or []:
            if not chuoi:
                continue
            eid = str(chuoi[0].get("entity_id") or "")
            ra[eid] = [(datetime.fromisoformat(str(x["last_changed"])).timestamp(), str(x.get("state") or "").lower())
                       for x in chuoi if x.get("last_changed")]
    return ra


def mat_ket_noi(trang_thai: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Thực thể HA đang `unavailable` lâu bất thường so với chính nó — cùng dạng lỗi của `soi_hong`."""
    from services import ha_client

    now = time.time()
    dang: dict[str, float] = {}
    st = trang_thai if trang_thai is not None else (ha_client.get_states() or [])
    ten = {str(x.get("entity_id")): str((x.get("attributes") or {}).get("friendly_name") or "") for x in st}
    for x in st:
        if str(x.get("state") or "").lower() != "unavailable":
            continue
        try:
            tu = datetime.fromisoformat(str(x.get("last_changed"))).timestamp()
        except ValueError:
            continue
        if now - tu >= MAT_KET_NOI_TOI_THIEU:
            dang[str(x["entity_id"])] = tu
    if not dang:
        return []
    moi = sorted(m for m, tu in dang.items() if (m, tu) not in _mkn_da_xet)
    lich = _lich_su_ha(moi, now - MAT_KET_NOI_NGAY * 86400) if moi else {}
    for ma in moi:
        _mkn_da_xet[(ma, dang[ma])] = _xet_mat_ket_noi(ma, dang[ma], lich.get(ma) or [])
    for k in [k for k in _mkn_da_xet if dang.get(k[0]) != k[1]]:
        _mkn_da_xet.pop(k)               # đã kết nối lại (hoặc lần mất mới) — bỏ kết quả cũ
    ra = []
    for ma, tu in sorted(dang.items()):
        loi = _mkn_da_xet.get((ma, tu))
        im = now - tu
        if loi and im > loi["nguong"]:
            ra.append({k: v for k, v in loi.items() if k != "nguong"} | {"chi_tiet": loi["chi_tiet"].format(gio=im / 3600)})
    return _gom_theo_thiet_bi(ra, ten)


def _gom_theo_thiet_bi(ra: list[dict[str, Any]], ten: dict[str, str]) -> list[dict[str, Any]]:
    """Một thiết bị mất kết nối kéo theo MỌI thực thể của nó (đo 29/09/2026: 5 camera Imou = 90 thực
    thể) — gom thành MỘT lỗi mỗi thiết bị theo sổ thiết bị của HA, kèm số thực thể và tích hợp."""
    from services import ha_client

    try:
        idx = ha_client.get_ha_area_index() or {}
    except Exception:  # noqa: BLE001 — không có sổ thì để nguyên từng thực thể
        idx = {}
    tb_cua = idx.get("entity_device_ids") or {}
    tich_hop = idx.get("entity_platform") or {}
    nhom: dict[tuple, list[dict[str, Any]]] = {}
    for h in ra:
        nhom.setdefault(tuple(tb_cua.get(h["thiet_bi"]) or [h["thiet_bi"]]), []).append(h)
    gom = []
    for ds in nhom.values():
        dai = sorted(ds, key=lambda h: (len(ten.get(h["thiet_bi"]) or h["thiet_bi"]), h["thiet_bi"]))[0]
        if len(ds) > 1:
            th = tich_hop.get(dai["thiet_bi"])
            dai = {**dai, "chi_tiet": f"{dai['chi_tiet']} · cả thiết bị: {len(ds)} thực thể"
                                      + (f" (tích hợp {th})" if th else "")}
        gom.append(dai)
    return gom


def _xet_mat_ket_noi(ma: str, tu: float, lich: list[tuple[float, str]]) -> dict[str, Any] | None:
    """Ngưỡng của lần mất kết nối từ ``tu`` theo nếp của chính thực thể; None = không có nếp để so."""
    cu: list[float] = []
    a: float | None = None
    tot = 0
    for ts, g in lich:
        if ts >= tu:
            break
        if g == "unavailable":
            a = ts if a is None else a
        else:
            tot += 1
            if a is not None:
                cu.append(ts - a)
                a = None
    if not tot:
        return None         # cả cửa sổ chưa từng khả dụng — không có nếp để so
    # Lỗi hay không phụ thuộc thời gian: lúc này chưa dài hơn lần cũ thì xét lại ở lượt sau — nên
    # chỉ lưu NGƯỠNG, `mat_ket_noi` so với thời gian mất kết nối hiện tại.
    return {"thiet_bi": ma, "truong": "state", "loai": "mat_ket_noi", "nguong": max(cu) if cu else 0.0,
            "chi_tiet": ("không khả dụng {gio:.1f} giờ — lâu hơn mọi lần mất kết nối trước "
                         f"({max(cu) / 3600:.1f} giờ)" if cu else
                         "không khả dụng {gio:.1f} giờ — " + f"{MAT_KET_NOI_NGAY} ngày qua chưa từng mất kết nối"),
            "lan_cuoi_tot": tu, "so_ban_ghi": tot}


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

    try:
        hong += mat_ket_noi()
    except Exception as exc:
        logger.warning({"event": "canh_bao_mat_ket_noi_loi", "error": str(exc)[:200]})
    hong = con_ton_tai(hong)
    with _khoa:
        khong = (_doc().get("khong_phai_loi") or {})
    hong = [h for h in hong if f"{h.get('thiet_bi')}\x00{h.get('truong')}" not in khong
            and f"{h.get('thiet_bi')}\x00" not in khong]

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


def khong_phai_loi(thiet_bi: str, truong: str = "", ly_do: str = "") -> dict[str, Any]:
    """Chủ nhà nói điều bộ soi báo KHÔNG PHẢI LỖI (vd "tôi không tắt chứ không phải đơ") → ghi vào
    sổ, từ nay không báo trường đó nữa (không truyền ``truong`` = cả thiết bị) cho tới khi chủ nhà
    bảo bật lại (`bo_im`). Khác «tôi biết rồi» (`im_di`): cái kia chỉ im LƯỢT hỏng đang có.

    Chủ máy 29/09/2026 hỏi bot "có hiểu và đưa vào học hỏi không" — trước đây bot trả lời «em sẽ
    không coi đó là lỗi nữa» mà không có chỗ nào ghi, lần quét sau vẫn báo y nguyên."""
    thiet_bi = str(thiet_bi or "").strip()
    if not thiet_bi:
        return {"ok": False, "error": "thiếu thiết bị"}
    with _khoa:
        so = _doc()
        ds = so.setdefault("khong_phai_loi", {})
        # Tên người dùng nói có thể là tên hiển thị — khớp với lỗi đang theo dõi theo mã hoặc đúng tên.
        khop = sorted({k.split("\x00")[0] for k in (so.get("muc") or {}) if k.split("\x00")[0] == thiet_bi})
        for tb in khop or [thiet_bi]:
            ds[f"{tb}\x00{truong}"] = {"ly_do": str(ly_do or "")[:300], "luc": time.time()}
        _ghi(so)
    logger.info({"event": "canh_bao_khong_phai_loi", "thiet_bi": thiet_bi, "truong": truong})
    return {"ok": True, "thiet_bi": khop or [thiet_bi]}


def bo_im(thiet_bi: str = "") -> dict[str, Any]:
    """Bật báo lại — cho nút «nhận lại cảnh báo» trên web. Gỡ cả dấu «không phải lỗi»."""
    n = 0
    with _khoa:
        so = _doc()
        kpl = so.get("khong_phai_loi") or {}
        for k in [k for k in kpl if not thiet_bi or k.split("\x00")[0] == thiet_bi]:
            kpl.pop(k)
            n += 1
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
    ten_map, khu_map = _tra_cuu()
    than = "\n".join(_mo_ta(h, ten_map, khu_map)
                     for h in hong[:_toi_da_moi_lan()])
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

    tin = _soan_tin(can, int(kq.get("tong_hong") or len(can)))
    gui = 0

    # MỘT đường duy nhất: sổ đăng ký `services/thong_bao.py`. Chủ máy chốt
    # 13/09/2026 — mọi thông báo theo cài đặt trên web, KHÔNG mặc định — nên
    # nhánh "chưa chọn kênh thì rơi về admin ba tầng" đã bỏ hẳn. Cái thang cũ
    # ấy chỉ duyệt `telegram_bots` + `zalo_bots`, không bao giờ sinh nổi tiền
    # tố `zalop_`, nên nó vừa là mặc định ngầm vừa là mặc định TRẬT.
    from services import thong_bao

    gui = thong_bao.gui("nha.canh_bao", tin)
    if not gui and not thong_bao.cai_dat("nha.canh_bao")["kenh"]:
        return {"gui": 0, "ly_do": "chưa chọn kênh nhận (Cài đặt → Thông báo)"}

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
    # Đếm KÊNH đã chọn cho cảnh báo, không đếm admin nữa. Từ 13/09/2026 cảnh
    # báo đi theo sổ đăng ký `thong_bao`, nên số admin là con số không còn dính
    # dáng gì tới "ai thật sự nhận được tin" — hiện nó lên web là nói sai.
    from services import thong_bao

    return {
        "bat": is_enabled(),
        "dang_hong": len(hong),
        "dang_im": len(im),
        "theo_doi": len(muc),
        "quet_cuoi": so.get("quet_cuoi"),
        "gio_hang_ngay": _gio_hang_ngay(),
        "nguoi_nhan": len(thong_bao.cai_dat("nha.canh_bao")["kenh"]),
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
    _mkn_da_xet.clear()
    with _khoa:
        try:
            _FILE.unlink()
        except OSError:
            pass
