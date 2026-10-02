"""Sự cố của thiết bị bot ĐANG TỰ ĐIỀU KHIỂN — báo kèm NGUYÊN NHÂN cụ thể.

Chủ máy 02/10/2026: "Báo khi thiết bị đã học bị mất kết nối, đến lịch không thấy có, rồi thực hiện không thấy
thay đổi, nhưng phải kèm nguyên nhân cụ thể. Ví dụ mất mạng, mất kết nối, đơ". Ca thật cùng ngày: 09:56 quạt
phòng khách được tạo lại trong HA dưới mã mới; mã cũ `fan.phong_khach` thành thực thể bỏ lại (`restored`,
`unavailable`). 16:17 người về, luật đã học định bật quạt mà chỉ ghi nhật ký «thiết bị đang unavailable sẵn».
Tin cảnh báo chung (`canh_bao_nha`) có gửi lúc 10:58 nhưng chỉ nói «không khả dụng 1 giờ» — không nói vì sao,
không nói bot sẽ không tự bật được.

Ba lúc báo (chủ máy nêu): thiết bị đã học mất kết nối (`quet`, nhịp 5 phút của heartbeat); tới lúc luật định
làm mà thiết bị không có mặt (`kich_hoat_nha`); đã gửi lệnh mà trạng thái không đổi (`kiem_sau_lenh`).

Nguyên nhân suy từ CHÍNH dữ liệu của HA, không danh sách thiết bị: HA không trả lời; thực thể bị bỏ lại (kèm
thực thể mới sinh cùng lúc); nhiều tích hợp cùng mất một lúc (mạng / HA khởi động lại); cả một tích hợp cùng mất
(hub, cầu nối); riêng thiết bị (pin, sóng lần cuối, mất điện / rớt mạng); còn kết nối mà lệnh không ăn (đơ).
Cặp gương `switch_as_x` (đèn bọc công tắc Zigbee): xét thực thể GỐC — tích hợp và cảm biến sóng nằm ở đó.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_TZ = timezone(timedelta(hours=7))
_FILE = Path(DATA_DIR) / "agent" / "su_co_thiet_bi.json"
_khoa = threading.Lock()

#: Mất kết nối ngắn hơn ngần này không báo — HA khởi động lại, Wi-Fi chớp là chuyện thường.
MAT_TOI_THIEU = 300
#: Các thực thể đổi sang `unavailable` trong khoảng ± ngần này giây được coi là MẤT CÙNG LÚC.
CUNG_LUC = 300
#: Sau lệnh chờ ngần này giây rồi đọc lại trạng thái (Zigbee/ESPHome báo về trong vài giây).
KIEM_SAU = 15
#: Cùng một sự cố không báo lại trong ngần này giây (khoá theo thiết bị + loại + mốc mất kết nối).
GIU_KHOA = 7 * 86400
#: Ngưỡng sóng yếu: linkquality Zigbee (0–255), RSSI Wi-Fi/BLE (dBm). Pin yếu (%).
LQI_YEU, RSSI_YEU, PIN_YEU = 40, -80, 15


def _gio(ts: float) -> str:
    return datetime.fromtimestamp(ts, _TZ).strftime("%H:%M")


def _ts(chu: Any) -> float:
    try:
        return datetime.fromisoformat(str(chu)).timestamp()
    except ValueError:
        return 0.0


def _ten(s: dict[str, Any]) -> str:
    return str((s.get("attributes") or {}).get("friendly_name") or s.get("entity_id") or "")


def _goc(tb: str) -> str:
    """Thực thể mang tích hợp thật: với cặp gương là công tắc gốc mà đèn bọc ngoài."""
    from services import ha_client
    try:
        idx = ha_client.get_ha_area_index() or {}
    except Exception:  # noqa: BLE001
        return tb
    if (idx.get("entity_platform") or {}).get(tb) == "switch_as_x":
        return (idx.get("entity_mirror") or {}).get(tb) or tb
    return tb


def _so(gt: Any) -> float | None:
    try:
        return float(gt)
    except (TypeError, ValueError):
        return None


def _gia_tri_cuoi(ma: list[str]) -> dict[str, str]:
    """Giá trị TỐT cuối cùng — sóng/pin ngay trước khi mất. Bảng ``tuoi`` dùng được ở đây (khác bẫy «tuoi cho mốc
    quá khứ» của tầng học): kho c2a không ghi unavailable, nên giá trị mới nhất CHÍNH LÀ giá trị trước lúc mất,
    và câu hỏi là về hiện tại."""
    from services import lich_su_nha
    try:
        return {str(r["thiet_bi"]): str(r.get("gia_tri") or "") for r in lich_su_nha.doc_tuoi()
                if r.get("thiet_bi") in ma and r.get("truong") == "state"}
    except Exception:  # noqa: BLE001
        return {}


def _luc_khoi_dong(ds: dict[str, dict[str, Any]]) -> float | None:
    """Lúc HA khởi động lại: HA đặt lại `last_changed` của MỌI thực thể về lúc khởi động. Đo 02/10/2026: 350/533
    thực thể (66%) cùng mốc 09:56 sau khi khởi động lại; ngoài mốc đó không phút nào quá 9%."""
    import collections
    dem = collections.Counter(int(_ts(x.get("last_changed")) // 60) for x in ds.values())
    if not dem:
        return None
    phut, n = dem.most_common(1)[0]
    return phut * 60.0 if n >= 0.3 * len(ds) else None


def _tu(chu: str) -> set[str]:
    from services.ha_client import _fold_diacritics
    return set(_fold_diacritics(chu).lower().replace("_", " ").split())


def _thay_the(tb: str, s: dict[str, Any], ds: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Thực thể CÙNG MIỀN, không bị bỏ lại, mà tên CÙNG phần tên phòng và CHỨA ĐỦ phần riêng của tên cũ («Quạt phòng
    khách» → «ir quat Phòng khách»). Tên phòng có ở mọi thiết bị trong phòng nên không nhận ra thiết bị: đo 02/10/2026
    «TV phòng khách 2F34» từng bị gợi ý sang «Cam phong khach»; thời gian cũng không (sau khởi động lại mọi thứ «sinh
    cùng lúc» — từng gợi ý «Aptomat tổng Dòng»). Không chắc thì không gợi ý."""
    from services import ha_client
    try:
        khu_tu = {t for a in ((ha_client.get_ha_area_index() or {}).get("area_names") or {}) for t in a.split()}
    except Exception:  # noqa: BLE001
        khu_tu = set()
    cu = _tu(_ten(s))
    cu_khu, cu_rieng = cu & khu_tu, cu - khu_tu
    if not cu_rieng:
        return None
    ung = []
    for m, x in ds.items():
        if m == tb or m.split(".")[0] != tb.split(".")[0] or (x.get("attributes") or {}).get("restored"):
            continue
        t = _tu(_ten(x))
        if t & khu_tu == cu_khu and cu_rieng <= t - khu_tu:
            ung.append((len(t - cu), abs(_ts(x.get("last_changed")) - _ts(s.get("last_changed"))), m))
    return ds[min(ung)[2]] if ung else None


def _rieng_thiet_bi(goc: str, ds: dict[str, dict[str, Any]], dv: dict[str, list[str]], t0: float) -> str:
    anh_em = [m for m, ids in dv.items() if ids and ids == dv.get(goc)]
    cung_mat = [m for m in anh_em if (ds.get(m) or {}).get("state") == "unavailable"]
    cuoi = _gia_tri_cuoi(anh_em)
    dau: list[str] = []
    for m in anh_em:
        a = (ds.get(m) or {}).get("attributes") or {}
        v = _so(cuoi.get(m))
        if v is None:
            continue
        if a.get("device_class") == "battery" and v <= PIN_YEU:
            dau.append(f"pin lần cuối còn {v:g}% — nhiều khả năng HẾT PIN")
        elif "linkquality" in m and v < LQI_YEU:
            dau.append(f"sóng Zigbee lần cuối yếu ({v:g}/255) — xa bộ phát/bị chắn")
        elif (a.get("device_class") == "signal_strength" or "rssi" in m) and v < RSSI_YEU:
            dau.append(f"sóng lần cuối yếu ({v:g} dBm)")
    cau = f"riêng thiết bị này mất kết nối từ {_gio(t0)}"
    if len(cung_mat) > 1:
        cau += f" (cả {len(cung_mat)} thực thể của nó)"
    return cau + " — " + ("; ".join(dau) if dau else "mất điện, rớt mạng (Wi-Fi/Zigbee) hoặc dịch vụ đám mây của hãng — kiểm nguồn và sóng")


def chan_doan(tb: str, *, sau_lenh: str = "") -> dict[str, str]:
    """{"nguyen_nhan": nhãn ngắn, "chi_tiet": câu đầy đủ}. ``sau_lenh`` = "on"/"off": đã gửi lệnh đó mà trạng thái
    không đổi (thiết bị còn kết nối) → xét đơ."""
    from services import ha_client

    try:
        tat_ca = ha_client.get_states(use_cache=False) or []
    except Exception:  # noqa: BLE001
        tat_ca = []
    if not tat_ca:
        return {"nguyen_nhan": "mất kết nối tới Home Assistant",
                "chi_tiet": "Home Assistant không trả lời — máy chủ HA tắt/treo hoặc mạng nội bộ giữa c2a và HA đứt"}
    ds = {str(s.get("entity_id")): s for s in tat_ca}
    s = ds.get(tb)
    if s is None:
        return {"nguyen_nhan": "thực thể không còn",
                "chi_tiet": f"Home Assistant không còn mã {tb} — thiết bị đã bị xoá hoặc đổi mã"}
    tt = str(s.get("state") or "").lower()
    t0 = _ts(s.get("last_changed"))
    if tt == "unavailable":
        if (s.get("attributes") or {}).get("restored"):
            moi = _thay_the(tb, s, ds)
            goi_y = (f"; thực thể thay thế có lẽ là «{_ten(moi)}» ({moi['entity_id']}) — đổi mã của nó về "
                     f"{tb} là em chạy lại với điều kiện đã học") if moi else ""
            return {"nguyen_nhan": "thực thể bị bỏ lại",
                    "chi_tiet": f"từ {_gio(t0)} tích hợp không còn cung cấp mã {tb} (thiết bị được tạo lại hoặc "
                                f"đổi mã){goi_y}"}
        try:
            idx = ha_client.get_ha_area_index() or {}
        except Exception:  # noqa: BLE001
            idx = {}
        pf, dv = idx.get("entity_platform") or {}, idx.get("entity_device_ids") or {}
        goc = _goc(tb)
        t0 = _ts((ds.get(goc) or s).get("last_changed")) or t0
        kd = _luc_khoi_dong(ds)
        if kd is not None and abs(t0 - kd) <= 2 * 60:
            return {"nguyen_nhan": "chưa kết nối lại sau khi HA khởi động lại",
                    "chi_tiet": f"Home Assistant khởi động lại lúc {_gio(kd)} và tích hợp «{pf.get(goc) or '?'}» chưa "
                                "nạp lại được thiết bị — thiết bị đang tắt/mất mạng, hoặc tích hợp lỗi (xem Cài đặt › "
                                "Thiết bị & Dịch vụ)"}
        cung = [m for m, x in ds.items() if x.get("state") == "unavailable"
                and abs(_ts(x.get("last_changed")) - t0) <= CUNG_LUC]
        tich_hop = {pf.get(m) for m in cung} - {None}
        if len(cung) >= 20 and len(tich_hop) >= 3:
            return {"nguyen_nhan": "mất mạng / HA khởi động lại",
                    "chi_tiet": f"{len(cung)} thực thể của {len(tich_hop)} tích hợp cùng mất kết nối lúc {_gio(t0)} — "
                                "mạng nội bộ chập hoặc Home Assistant vừa khởi động lại"}
        p = pf.get(goc)
        cung_th = [m for m in cung if pf.get(m) == p]
        tong_th = [m for m in ds if pf.get(m) == p]
        thiet_bi = {tuple(dv.get(m) or [m]) for m in cung_th}
        if p and len(thiet_bi) >= 2 and len(cung_th) >= 0.8 * len(tong_th):
            return {"nguyen_nhan": f"cả tích hợp {p} mất kết nối",
                    "chi_tiet": f"{len(thiet_bi)} thiết bị của tích hợp «{p}» cùng mất lúc {_gio(t0)} "
                                f"({len(cung_th)}/{len(tong_th)} thực thể) — cầu nối/hub của tích hợp hỏng "
                                "(bộ điều phối Zigbee, MQTT, dịch vụ đám mây…), không phải riêng thiết bị"}
        return {"nguyen_nhan": "thiết bị mất kết nối", "chi_tiet": _rieng_thiet_bi(goc, ds, dv, t0)}
    if sau_lenh:
        a = s.get("attributes") or {}
        if a.get("assumed_state"):
            return {"nguyen_nhan": "điều khiển một chiều",
                    "chi_tiet": "thiết bị hồng ngoại/RF không báo trạng thái thật — lệnh có thể không tới (bị chắn, "
                                "bộ phát IR hỏng)"}
        cap_nhat = max(_ts(x.get("last_updated")) for m, x in ds.items()
                       if m == _goc(tb) or m == tb)
        if cap_nhat and time.time() - cap_nhat > 6 * 3600:
            return {"nguyen_nhan": "thiết bị đơ",
                    "chi_tiet": f"còn kết nối nhưng không gửi gì từ {_gio(cap_nhat)} và không theo lệnh — treo; "
                                "ngắt nguồn rồi cấp lại"}
        return {"nguyen_nhan": "thiết bị không theo lệnh",
                "chi_tiet": f"nhận lệnh {'bật' if sau_lenh == 'on' else 'tắt'} mà vẫn «{tt}» — treo (đơ), kẹt rơ-le "
                            "hoặc bị khoá trẻ em/công tắc cứng"}
    return {"nguyen_nhan": "", "chi_tiet": ""}


def _doc() -> dict[str, float]:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8")) if _FILE.is_file() else {}
    except Exception:  # noqa: BLE001
        return {}


def _danh_dau(khoa: str) -> bool:
    """True = khoá mới (chưa báo); ghi lại. Khoá cũ quá ``GIU_KHOA`` thì bỏ."""
    now = time.time()
    with _khoa:
        so = {k: v for k, v in _doc().items() if now - float(v) < GIU_KHOA}
        if khoa in so:
            return False
        so[khoa] = now
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(so, ensure_ascii=False), encoding="utf-8")
        return True


_DAU = {"mat_ket_noi": "🔌", "den_luc": "⏰", "khong_doi": "⚠️", "lenh_hong": "⚠️"}


def bao(tb: str, loai: str, *, ten: str = "", hd: str = "", vi: str = "", moc: float | None = None) -> bool:
    """Gửi một sự cố (kèm chẩn đoán) qua kênh «Thiết bị nhà hỏng». ``moc`` = mốc chống báo trùng (mặc định: lúc
    trạng thái đổi lần cuối — mỗi lần mất kết nối báo một lần)."""
    from services import ha_client, thong_bao

    st = ha_client.get_state(tb) or {}
    cd = chan_doan(tb, sau_lenh=hd if loai == "khong_doi" else "")
    khoa = f"{tb}|{loai}|{int(moc if moc is not None else _ts(st.get('last_changed')))}"
    if not _danh_dau(khoa):
        return False
    ten = ten or _ten(st) or tb
    viec = "bật" if hd == "on" else "tắt"
    dau = {
        "mat_ket_noi": f"{ten} mất kết nối — em sẽ không tự bật/tắt được cho tới khi nó có lại.",
        "den_luc": f"{vi} — đáng lẽ em {viec} {ten} nhưng thiết bị không có mặt.",
        "khong_doi": f"Em đã gửi lệnh {viec} {ten} mà {KIEM_SAU} giây sau vẫn «{st.get('state')}».",
        "lenh_hong": f"Lệnh {viec} {ten} không tới được thiết bị.",
    }[loai]
    tin = f"{_DAU[loai]} {dau}\nNguyên nhân: {cd['nguyen_nhan'] or 'chưa rõ'}" + (
        f" — {cd['chi_tiet']}." if cd["chi_tiet"] else ".")
    logger.info({"event": "su_co_thiet_bi", "thiet_bi": tb, "loai": loai, "nguyen_nhan": cd["nguyen_nhan"]})
    return bool(thong_bao.gui("nha.canh_bao", tin))


def quet() -> int:
    """Heartbeat 5 phút: thiết bị đang học (bật cho tự kích hoạt) mà mất kết nối ≥ ``MAT_TOI_THIEU``."""
    from services import ha_client, kich_hoat_nha

    n = 0
    for tb in kich_hoat_nha.ds_thiet_bi():
        st = ha_client.get_state(tb)
        if st is None or str(st.get("state") or "").lower() != "unavailable":
            continue
        if time.time() - _ts(st.get("last_changed")) >= MAT_TOI_THIEU and bao(tb, "mat_ket_noi"):
            n += 1
    return n


def kiem_sau_lenh(tb: str, hd: str) -> None:
    """Hẹn đọc lại trạng thái ``KIEM_SAU`` giây sau lệnh; không theo lệnh thì báo kèm nguyên nhân."""
    def _kiem() -> None:
        try:
            from services import ha_client
            st = ha_client.get_state(tb) or {}
            if str(st.get("state") or "").lower() != hd:
                bao(tb, "khong_doi", hd=hd, moc=time.time() // 3600)
        except Exception as exc:  # noqa: BLE001
            logger.warning({"event": "su_co_kiem_sau_lenh_loi", "thiet_bi": tb, "error": str(exc)[:160]})

    t = threading.Timer(KIEM_SAU, _kiem)
    t.daemon = True
    t.start()
