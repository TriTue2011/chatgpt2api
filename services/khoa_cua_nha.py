"""Ai mở cửa, lúc nào — và bot TỰ HỌC tên từng người.

Khoá Tuya chỉ báo mã: "vân tay số 11", "khuôn mặt số 17". Đo trên khoá nhà chủ
máy 10/09/2026: **5 người, không ai có tên** (trường ``unlock_name`` của Tuya
rỗng vì chưa ai đặt trong app Smart Life).

Chủ máy hỏi đúng chỗ thiếu: *"liên quan đến tự học mà, nếu không xác nhận làm
sao biết đó là ai nhỉ"*. Đúng — không ai xác nhận thì bot mãi chỉ biết con số.

BA NGUỒN TÊN, xét theo thứ tự:

1. ``unlock_name`` do Tuya trả — chủ nhà đặt trong app thì mọi nơi cùng hiện
   đúng tên, khỏi dạy.
2. Trí nhớ bot — chủ máy đã nói "vân tay 11 là con trai" thì nhớ mãi.
3. Chưa có gì → **BOT HỎI**, và chỉ hỏi MỘT LẦN cho mỗi mã.

NHỊP BÁO (chủ máy chốt): báo ngay chuyện bất thường, cộng một bản tóm tắt cuối
ngày. Giờ tóm tắt KHÔNG cố định mà bám nếp ngủ của nhà — đo được nhà này ngủ
quanh 0h22 ±74 phút, nên gửi lúc 22h là quá sớm, còn 23h30 thì vừa.

THẾ NÀO LÀ BẤT THƯỜNG: người chưa biết tên, mở ngoài khung giờ quen của chính
người đó (học từ ``thoi_quen_nha``), hoặc mở lúc cả nhà đã ngủ.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_TZ = timezone(timedelta(hours=7))
_FILE = Path(DATA_DIR) / "agent" / "khoa_cua_nha.json"
_khoa = threading.RLock()

#: Mã lệnh mở khoá của Tuya. `unlock_` + cách mở.
_CACH_MO = {
    "fingerprint": "vân tay", "face": "khuôn mặt", "password": "mật khẩu",
    "card": "thẻ từ", "key": "chìa cơ", "temporary": "mã tạm",
    "dynamic": "mã động", "hand": "vân tay", "finger_vein": "tĩnh mạch ngón",
    "phone": "điện thoại", "app": "điện thoại",
}

#: Hỏi tên tối đa ngần này lần cho MỘT mã. Hỏi mãi mà không ai trả lời thì
#: thôi — nài thêm chỉ làm phiền.
_HOI_TOI_DA = 3
#: Nhà ngủ muộn nhất mấy giờ thì vẫn tính là "hôm nay" (giờ thập phân, >24 là
#: sang hôm sau). Đo nhà chủ máy: tắt đèn cuối quanh 0h22.
_DEM_TOI_DA = 27.0


def _cfg() -> dict[str, Any]:
    raw = (config.data.get("mqtt") or {}).get("khoa_cua")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("bat", True))


# ── Sổ ghi ──────────────────────────────────────────────────────────────────
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
        tmp.replace(_FILE)
    except OSError as exc:
        logger.warning({"event": "khoa_cua_ghi_loi", "error": str(exc)[:160]})


def _ma(code: str, value: Any) -> str:
    """Khoá định danh một người: 'fingerprint#11'."""
    return f"{str(code or '').replace('unlock_', '')}#{value}"


def _mo_ta_ma(ma: str) -> str:
    """'fingerprint#11' → 'vân tay số 11'."""
    cach, _, so = ma.partition("#")
    return f"{_CACH_MO.get(cach, cach)} số {so}"


# ── Tên người: uỷ cho SỔ DÙNG CHUNG ─────────────────────────────────────────
# Trước đây module này giữ sổ tên RIÊNG, và đó là lỗi thật: `thoi_quen_nha`
# không đọc được sổ đó, nên chủ máy dạy "vân tay 11 là con trai" xong mà báo
# cáo thói quen vẫn gọi "vân tay số 11". Giờ mọi nguồn dùng chung một sổ.
_NGUON = "tuya"


def _khoa_so(ma: str) -> str:
    """'fingerprint#11' → khoá sổ chung có nguồn."""
    from services import so_ten_nha
    cach, _, so = ma.partition("#")
    return so_ten_nha.khoa(_NGUON, cach or "unlock", so or ma)


def ten_cua(ma: str, ten_tuya: str = "") -> str:
    """Tên người. Rỗng nghĩa là CHƯA BIẾT — bot sẽ hỏi."""
    from services import so_ten_nha
    cach, _, so = ma.partition("#")
    return so_ten_nha.ten_cua(_NGUON, cach or "unlock", so or ma, ten_tuya)


def dat_ten(ma: str, ten: str, *, user_id: str = "") -> bool:
    """Chủ nhà xác nhận ai là ai — bước TỰ HỌC."""
    from services import so_ten_nha
    if not ma:
        return False
    cach, _, so = ma.partition("#")
    return so_ten_nha.dat_ten(_NGUON, cach or "unlock", so or ma, ten,
                              user_id=user_id)


def _nen_hoi(ma: str) -> bool:
    from services import so_ten_nha
    return so_ten_nha.nen_hoi(_khoa_so(ma))


def _danh_dau_da_hoi(ma: str) -> None:
    from services import so_ten_nha
    so_ten_nha.danh_dau_da_hoi(_khoa_so(ma))


# ── Nếp ngủ của nhà ─────────────────────────────────────────────────────────
#: Nhớ nếp ngủ trong 10 phút. Nó là TRUNG VỊ CỦA 14 NGÀY nên không thể đổi
#: trong vài phút, mà mỗi lần tính lại phải đọc 7.498 dòng lịch sử (đo trên
#: máy chủ 11/09/2026: 0,48 giây mỗi lượt).
#:
#: Vì sao thành vấn đề: vòng khoá cửa chạy mỗi 15 giây, và một lượt
#: `chay_mot_lan()` gọi hàm này BA lần — hai qua `soi_bat_thuong()`, một qua
#: `gio_tom_tat()`. Thành 3 × 0,48 / 15 ≈ 10% một lõi, chạy suốt ngày đêm.
#: Claude trên máy chủ đo bằng py-spy: luồng `khoa-cua-nhip` chiếm 11,9% một
#: lõi, đã tốn 2.688 giây CPU kể từ lúc container khởi động.
#:
#: Đệm ở ĐÂY chứ không sửa từng nơi gọi: nơi gọi thứ tư viết sau này cũng được
#: hưởng, không ai phải nhớ.
_HAN_NHO_NGU = 600.0
_ngu_nho: tuple[float, float | None] | None = None   # (lúc tính, kết quả)


def gio_di_ngu(so_ngay: int = 14) -> float | None:
    """Nhà thường đi ngủ lúc mấy giờ (thập phân, >24 là quá nửa đêm).

    Suy từ lần TẮT đèn cuối cùng mỗi đêm. Đo nhà chủ máy 10/09/2026: trung vị
    0h22 (=24.37) ±74 phút — nên gửi tóm tắt lúc 22h là quá sớm.

    Trả ``None`` khi chưa đủ dữ liệu; tầng trên tự chọn giờ mặc định.

    Kết quả được NHỚ ``_HAN_NHO_NGU`` giây — xem ghi chú ở trên.
    """
    global _ngu_nho
    if so_ngay == 14:                     # chỉ đệm đường mặc định
        with _khoa:
            nho = _ngu_nho
        if nho is not None and time.time() - nho[0] < _HAN_NHO_NGU:
            return nho[1]
    from services import lich_su_nha

    den = time.time()
    try:
        # Lọc ở SQL: hàm này chỉ quan tâm đèn/công tắc tắt đi, mà đó là vài
        # trăm dòng trong khi cả nhà sinh ~55.000 sự kiện/ngày. Kéo hết về rồi
        # bỏ 99% là cách bản cũ chạm trần và mất 94,9% dữ liệu (đo 10/09/2026).
        sk = lich_su_nha.doc_cua_so(
            den - max(1, int(so_ngay)) * 86400, den,
            tien_to=("light.", "switch."))
    except Exception:
        return None

    dem: dict[Any, list[float]] = {}
    for r in sk:
        if str(r.get("gia_tri") or "").lower() != "off":
            continue
        tb = str(r.get("thiet_bi") or "").lower()
        if not tb.startswith(("light.", "switch.")):
            continue
        try:
            t = datetime.fromtimestamp(float(r["ts"]), _TZ)
        except (TypeError, ValueError, KeyError):
            continue
        g = t.hour + t.minute / 60
        if not (g >= 20 or g < 4):
            continue
        # Đêm thuộc về NGÀY HÔM TRƯỚC nếu đã quá nửa đêm.
        ngay = (t - timedelta(hours=4)).date()
        dem.setdefault(ngay, []).append(g + 24 if g < 4 else g)

    mocs = [max(v) for v in dem.values() if v]
    kq = round(statistics.median(mocs), 3) if len(mocs) >= 3 else None
    if so_ngay == 14:
        # Nhớ CẢ `None`: "chưa đủ dữ liệu" cũng tốn đúng ngần ấy công để biết,
        # và nó càng không đổi trong mười phút.
        # (`global _ngu_nho` đã khai ở đầu hàm — khai lại ở đây là SyntaxError.)
        with _khoa:
            _ngu_nho = (time.time(), kq)
    return kq


def gio_tom_tat() -> float:
    """Giờ gửi bản tóm tắt cuối ngày — TRƯỚC lúc nhà đi ngủ 45 phút.

    Chủ máy chốt: *"dựa vào thói quen để biết người trong nhà đi ngủ… để báo
    chứ không cố định giờ"*.
    """
    raw = _cfg().get("gio_tom_tat")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    ngu = gio_di_ngu()
    if ngu is None:
        return 22.0                     # chưa học được thì lấy giờ hợp lý
    return max(20.0, ngu - 0.75)


# ── Đọc nhật ký khoá ────────────────────────────────────────────────────────
def _tu_ha(so_ngay: int) -> list[dict[str, Any]]:
    """Lần mở cửa đọc từ lịch sử Home Assistant — đường ĐẨY, biết NGAY.

    Vì sao có hàm này: bản đầu chỉ hỏi API Tuya, mà heartbeat gọi mỗi 5 phút
    nên cửa mở xong phải đợi gần trọn 5 phút mới báo. Trong khi HA đã có
    `event.smart_lock_unlock_user_face` với `value: 17` ngay lúc cửa mở
    (đo thật 10/09/2026, 08:29:26) — dữ liệu nằm sẵn, chỉ là không ai nối.

    `ha_live` ghi các thực thể `event.` vào `lich_su_nha` ngay khi HA đẩy sang,
    nên đọc từ đó là gần như tức thì.
    """
    from services import lich_su_nha

    tu = time.time() - max(1, int(so_ngay)) * 86400
    try:
        # Chỉ cần thực thể `event.` — 7 ngày còn vài trăm dòng thay vì gần
        # 400.000. Bản cũ đặt tran=3000 rồi lọc sau, nên mọi lần mở cửa của
        # HÔM NAY đều nằm ngoài phần lấy về (đo 10/09/2026).
        ds = lich_su_nha.doc_cua_so(tu, time.time() + 60, tien_to=("event.",))
    except Exception as exc:
        logger.info({"event": "khoa_cua_ha_loi", "error": str(exc)[:140]})
        return []

    # Gom theo mốc thời gian: `event_type` và `value` là hai bản ghi riêng của
    # cùng một lần mở cửa, ha_live ghi liền nhau nên cùng giây.
    theo_luc: dict[int, dict[str, Any]] = {}
    for m in ds:
        e = str(m.get("thiet_bi") or "")
        if not e.lower().startswith("event.") or "unlock" not in e.lower():
            continue
        giay = int(float(m.get("ts") or 0))
        o = theo_luc.setdefault(giay, {"ts": float(m.get("ts") or 0),
                                       "thiet_bi": e})
        truong = str(m.get("truong") or "")
        if truong in ("event_type", "value"):
            o[truong] = str(m.get("gia_tri") or "")

    ra: list[dict[str, Any]] = []
    for o in theo_luc.values():
        cach = str(o.get("event_type") or "").replace("unlock_", "").strip()
        so = str(o.get("value") or "").strip().rstrip("0").rstrip(".")
        if not cach or not so:
            continue
        ma = f"{cach}#{so}"
        ra.append({"ma": ma, "ten": ten_cua(ma), "ts": o["ts"],
                   "thiet_bi": "khoá cửa"})
    return ra


def doc_nhat_ky(so_ngay: int = 2) -> list[dict[str, Any]]:
    """Lần mở cửa gần đây, mới nhất trước.

    Hai nguồn gộp lại: Home Assistant (ĐẨY — biết ngay) và API Tuya (KÉO — đủ
    lịch sử cũ). Trùng thì giữ một, so theo mã và mốc giây.
    """
    from services import tuya_nha

    ha = _tu_ha(so_ngay)

    # Tuya hỏng (mất mạng, hết hạn IoT Core) thì VẪN dùng dữ liệu HA — bản
    # trước `return []` ở đây, tức vứt sạch đường realtime chỉ vì nguồn phụ
    # không gọi được. Test khoá đúng chỗ này.
    try:
        ds = tuya_nha.danh_sach_thiet_bi()
    except Exception as exc:
        logger.info({"event": "khoa_cua_doc_loi", "error": str(exc)[:140]})
        return sorted(ha, key=lambda x: -x["ts"])
    khoa = [d for d in ds if "khoá" in str(d.get("loai") or "")]
    if not khoa:
        return sorted(ha, key=lambda x: -x["ts"])

    now = int(time.time() * 1000)
    tu = now - max(1, int(so_ngay)) * 86400 * 1000
    ra: list[dict[str, Any]] = []
    for k in khoa:
        try:
            r = tuya_nha.goi_api(
                f"/v1.0/devices/{k['id']}/door-lock/open-logs"
                f"?start_time={tu}&end_time={now}&page_no=1&page_size=50")
        except Exception as exc:
            logger.info({"event": "khoa_cua_log_loi", "error": str(exc)[:140]})
            continue
        for l in (r.get("result") or {}).get("logs") or []:
            st = l.get("status") or {}
            ma = _ma(str(st.get("code") or ""), st.get("value"))
            if ma.startswith("#"):
                continue
            ra.append({
                "ma": ma,
                "ten": ten_cua(ma, str(l.get("unlock_name") or l.get("nick_name") or "")),
                "ts": float(l.get("time") or l.get("update_time") or 0) / 1000,
                "thiet_bi": k.get("ten") or "khoá cửa",
            })
    # Gộp: HA trước (mới hơn), Tuya bù phần cũ. Cùng mã trong vòng 5 giây là
    # một lần mở — hai nguồn ghi lệch nhau chút đỉnh.
    gop = list(ha)
    for m in ra:
        trung = any(x["ma"] == m["ma"] and abs(x["ts"] - m["ts"]) < 5
                    for x in gop)
        if not trung:
            gop.append(m)
    gop.sort(key=lambda x: -x["ts"])
    return gop


# ── Bất thường ──────────────────────────────────────────────────────────────
def soi_bat_thuong(so_ngay: int = 1) -> list[dict[str, Any]]:
    """Lần mở cửa nào đáng báo ngay.

    Ba loại: người CHƯA BIẾT TÊN, mở lúc cả nhà đã ngủ, và mở lệch hẳn khung
    giờ quen của chính người đó (nếu đã học được nếp).
    """
    ra = []
    ngu = gio_di_ngu()
    for m in doc_nhat_ky(so_ngay):
        t = datetime.fromtimestamp(m["ts"], _TZ)
        g = t.hour + t.minute / 60
        gio_dem = g + 24 if g < 4 else g

        if not m["ten"]:
            ra.append({**m, "vi_sao": "chưa biết là ai", "muc": "hoi_ten"})
            continue
        if ngu is not None and gio_dem > ngu and gio_dem < _DEM_TOI_DA:
            ra.append({**m, "vi_sao": "mở cửa sau giờ cả nhà đã ngủ",
                       "muc": "khuya"})
    return ra


def _mo_ta_luc(ts: float) -> str:
    t = datetime.fromtimestamp(ts, _TZ)
    return t.strftime("%H:%M")


def soan_hoi_ten(m: dict[str, Any]) -> str:
    """Tin hỏi tên, kèm nút bấm — khuôn ask_choices (<<<ASK>>>…<<<END>>>).

    Chỉ hỏi MỘT LẦN cho mỗi mã, và tối đa _HOI_TOI_DA lần nếu không ai trả lời.
    """
    ma = m["ma"]
    dong = [
        f"🚪 Có người mở cửa lúc {_mo_ta_luc(m['ts'])} bằng {_mo_ta_ma(ma)}.",
        "Em chưa biết đây là ai — anh/chị cho em biết tên với ạ?",
        "<<<ASK>>>",
        f"Đây là tôi | khoá cửa {ma} là tôi",
        f"Người nhà | khoá cửa {ma} là người nhà",
        f"Để sau | thôi đừng hỏi về {ma} nữa",
        "<<<END>>>",
    ]
    return "\n".join(dong)


def soan_tom_tat(so_ngay: int = 1) -> str:
    """Bản tóm tắt cuối ngày: hôm nay ai về lúc mấy giờ."""
    ds = doc_nhat_ky(so_ngay)
    if not ds:
        return ""
    hom_nay = datetime.now(_TZ).date()
    theo_nguoi: dict[str, list[float]] = {}
    chua_biet_ten: set[str] = set()
    for m in ds:
        t = datetime.fromtimestamp(m["ts"], _TZ)
        if (t - timedelta(hours=4)).date() != hom_nay:
            continue
        ten = m["ten"] or _mo_ta_ma(m["ma"])
        if not m["ten"]:
            chua_biet_ten.add(ten)
        theo_nguoi.setdefault(ten, []).append(m["ts"])
    if not theo_nguoi:
        return ""
    dong = ["🚪 Hôm nay ai ra vào:"]
    for ten, ts in sorted(theo_nguoi.items(), key=lambda x: min(x[1])):
        gio = ", ".join(_mo_ta_luc(x) for x in sorted(ts)[:6])
        dong.append(f"  - {ten}: {gio}" + (f" (+{len(ts) - 6} lần nữa)"
                                           if len(ts) > 6 else ""))
    # Nhận diện bằng CỜ, không phải bằng chữ "số" trong tên. Bản cũ dùng
    # `"số" in t` nên tên thật chứa chữ "số" bị đếm nhầm là chưa biết.
    chua = [t for t in theo_nguoi if t in chua_biet_ten]
    if chua:
        dong.append("")
        dong.append(f"({len(chua)} người em chưa biết tên — nhắn «khoá cửa … là …» "
                    "để em nhớ ạ.)")
    return "\n".join(dong)


# ── Chạy định kỳ ────────────────────────────────────────────────────────────
def chay_mot_lan() -> dict[str, Any]:
    """Heartbeat gọi mỗi tick. Báo bất thường ngay, tóm tắt đúng giờ đã học."""
    if not is_enabled():
        return {"gui": 0, "ly_do": "tắt trong cấu hình"}

    # Ba tin của khoá cửa giờ là BA mục cài riêng trong Cài đặt → Thông báo,
    # thay cho thang admin ba tầng cũ. Chủ máy nêu đích danh 13/09/2026: "kể cả
    # thông báo khoá cửa hay tương tự". Đường cũ còn hỏng ngầm: tầng 3 của
    # `_nguoi_nhan` chỉ duyệt `telegram_bots` + `zalo_bots` nên không bao giờ
    # sinh nổi tiền tố `zalop_` — tin khoá cửa không tài nào tới Zalo cá nhân.
    from services import thong_bao

    gui = 0
    # 1. Hỏi tên người lạ — chỉ một mã mỗi lượt, đừng dội một chùm.
    for m in soi_bat_thuong():
        if m["muc"] != "hoi_ten" or not _nen_hoi(m["ma"]):
            continue
        gui += thong_bao.gui("nha.khoa_cua.hoi_ten", soan_hoi_ten(m))
        if gui:
            _danh_dau_da_hoi(m["ma"])
        break

    # 2. Mở cửa lúc khuya — báo ngay, không chờ tóm tắt.
    with _khoa:
        so = _doc()
        da_bao = set(so.get("da_bao_khuya") or [])
    moi_khuya = []
    for m in soi_bat_thuong():
        if m["muc"] != "khuya":
            continue
        khoa_tin = f"{m['ma']}|{int(m['ts'])}"
        if khoa_tin in da_bao:
            continue
        moi_khuya.append((khoa_tin, m))
    for khoa_tin, m in moi_khuya[:3]:
        tin = (f"🌙 {m['ten'] or _mo_ta_ma(m['ma'])} mở cửa lúc "
               f"{_mo_ta_luc(m['ts'])} — sau giờ cả nhà thường đi ngủ.")
        gui += thong_bao.gui("nha.khoa_cua.mo_khuya", tin)
        da_bao.add(khoa_tin)
    if moi_khuya:
        with _khoa:
            so = _doc()
            so["da_bao_khuya"] = sorted(da_bao)[-200:]
            _ghi(so)

    # 3. Tóm tắt cuối ngày, đúng giờ suy từ nếp ngủ.
    now = datetime.now(_TZ)
    g = now.hour + now.minute / 60
    moc = gio_tom_tat() % 24
    hom_nay = now.strftime("%Y-%m-%d")
    with _khoa:
        da_tom_tat = (_doc().get("tom_tat_ngay") or "") == hom_nay
    if not da_tom_tat and moc <= g < moc + 0.5:
        tin = soan_tom_tat()
        if tin:
            gui += thong_bao.gui("nha.khoa_cua.tom_tat", tin)
        with _khoa:
            so = _doc()
            so["tom_tat_ngay"] = hom_nay
            _ghi(so)

    return {"gui": gui, "gio_tom_tat": round(moc, 2)}


def trang_thai() -> dict[str, Any]:
    with _khoa:
        so = _doc()
    ngu = gio_di_ngu()
    return {
        "bat": is_enabled(),
        "da_dat_ten": len(so.get("ten") or {}),
        "gio_di_ngu": (f"{int(ngu % 24)}h{int(ngu % 1 * 60):02d}"
                       if ngu is not None else "chưa học được"),
        "gio_tom_tat": f"{int(gio_tom_tat() % 24)}h{int(gio_tom_tat() % 1 * 60):02d}",
        "ten": so.get("ten") or {},
    }


def _reset_for_tests() -> None:
    global _ngu_nho
    with _khoa:
        _ngu_nho = None          # cache nếp ngủ là biến toàn cục — rò giữa test
        try:
            _FILE.unlink()
        except OSError:
            pass


# ── Vòng nhịp nhanh ─────────────────────────────────────────────────────────
# VÌ SAO CÓ RIÊNG VÒNG NÀY, không dùng heartbeat chung:
#
# Heartbeat chạy mỗi 300 giây và nhịp tối thiểu của nó là 60 giây
# (`heartbeat.tick_seconds`), nên cửa mở xong phải đợi gần trọn 5 phút mới
# báo. Hạ nhịp chung xuống là kéo theo mọi task khác (chưng cất hồ sơ, quét
# nhật ký nhóm, cảnh báo thiết bị hỏng) chạy dày lên vô ích.
#
# Đo thật 10/09/2026: đám mây Tuya nhận sự kiện gần như TỨC THÌ — bản ghi
# `unlock_face = 17` có mốc 08:29:26, trùng khít với thứ Home Assistant thấy.
# Chỗ chậm là nhịp hỏi của bot, không phải Tuya. Một lượt gọi API mất 1,2 giây.
#
# Đường LOCAL đã thử và KHÔNG dùng được với khoá này: lúc thiết bị đang thức và
# trả lời ping, cả 6 cổng đều `Connection refused`, không có quảng bá UDP, và
# `tinytuya` với `local_key` thật thử đủ 4 phiên bản giao thức đều
# "Unable to Connect". Khoá T5 chỉ nói chuyện với đám mây Tuya — lựa chọn của
# hãng, và với khoá cửa thì hợp lý.
_nhip_luong: threading.Thread | None = None
_nhip_dung = threading.Event()

#: Giây giữa hai lần hỏi. Chủ máy chốt 15 giây (10/09/2026): nhanh gấp 20 lần
#: nhịp cũ, mà mỗi ngày chỉ thêm ~5.700 lượt gọi — thấp xa hạn mức Tuya.
_NHIP_GIAY = 15.0


def _nhip() -> float:
    try:
        return max(5.0, float(_cfg().get("nhip_giay") or _NHIP_GIAY))
    except (TypeError, ValueError):
        return _NHIP_GIAY


def _chay_mai() -> None:
    while not _nhip_dung.is_set():
        t0 = time.time()
        try:
            if is_enabled():
                chay_mot_lan()
        except Exception as exc:
            logger.info({"event": "khoa_cua_nhip_loi", "loi": str(exc)[:150]})
        # Trừ thời gian vừa tốn: một lượt gọi Tuya mất ~4 giây (đo thật
        # 10/09/2026), cộng thẳng 15 giây nữa thì nhịp THẬT thành 19 giây chứ
        # không phải 15. Vòng chạy tuần tự nên không bao giờ chồng lượt; chỉ
        # cần bù lại phần đã tốn, và giữ sàn 1 giây phòng khi Tuya chậm hơn cả
        # nhịp.
        _nhip_dung.wait(max(1.0, _nhip() - (time.time() - t0)))


def start() -> bool:
    """Vòng hỏi khoá cửa nhịp nhanh. Idempotent; trả True nếu đang/đã chạy."""
    global _nhip_luong
    if not is_enabled():
        return False
    with _khoa:
        if _nhip_luong is not None and _nhip_luong.is_alive():
            return True
        _nhip_dung.clear()
        _nhip_luong = threading.Thread(target=_chay_mai, daemon=True,
                                       name="khoa-cua-nhip")
        _nhip_luong.start()
    logger.info({"event": "khoa_cua_nhip_started", "giay": _nhip()})
    return True


def stop() -> None:
    """Dừng vòng nhịp nhanh. Gọi được nhiều lần."""
    global _nhip_luong
    _nhip_dung.set()
    with _khoa:
        _nhip_luong = None
