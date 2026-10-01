"""Cảm biến ghép — bot tự tính một cảm biến nhị phân từ cảm biến gốc bằng biểu thức VÀ / HOẶC / KHÔNG.

Chủ máy 29/09/2026: "có người ở nhà nhưng không có người khu vực phòng khách nhưng cảm biến
phòng khách vẫn báo có người do đứng ở bếp, tôi muốn lúc đó tắt quạt, và khi người ra lại bật
lại". Đo 30 ngày: lúc radar phòng khách báo có người thì 49% thời gian radar bếp cũng báo — nhưng
trong lúc trùng, camera phòng khách vẫn thấy NGƯỜI 62% thời gian (có người ở cả hai phòng). Chủ
máy chọn: "phòng khách có người thật" = radar phòng khách VÀ (bếp vắng HOẶC camera thấy người).

Vì sao bot tự tính chứ không làm cảm biến mẫu trong HA: bot học từ 30 ngày lịch sử, cảm biến
mới trong HA không có lịch sử nào — vài tuần sau bot mới đủ dữ liệu. Cảm biến ghép thì dựng lại
được trọn 30 ngày từ lịch sử cảm biến gốc (``chuoi``), học ngay.

KHÔNG ghi vào kho lịch sử: kho chỉ giữ điều quan sát được; cảm biến ghép luôn dựng lại từ cảm biến
gốc — đổi biểu thức là lịch sử đổi theo, không phải lấp dữ liệu cũ.

Định nghĩa là DỮ LIỆU của từng nhà (``data/agent/cam_bien_ghep.json``), không nằm trong mã:
``{"ma": "binary_sensor.c2a_<tên>", "ten": "...", "loai": "occupancy", "bieu_thuc": …}`` với
biểu thức: ``{"ma": "<thực thể>", "la": ["on", …]}`` (mặc định ``["on"]``), ``{"va": [...]}``,
``{"hoac": [...]}``, ``{"khong": …}``, ``{"khoang_cach": "<cảm biến khoảng cách radar>"}`` — đúng khi radar
không thấy người ở NGOÀI vùng khu của nó (vùng bot tự học, `vung_khoang_cach`; chủ máy 01/10/2026: "tắt thì
cũng dựa vào khoảng cách").
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "cam_bien_ghep.json"
TIEN_TO = "binary_sensor.c2a_"
_khoa = threading.RLock()
_dl: dict[str, Any] | None = None
#: Giá trị cuối đã báo cho bộ kích hoạt (chỉ báo khi ĐỔI).
_cuoi: dict[str, str] = {}


def _nap() -> dict[str, Any]:
    global _dl
    if _dl is None:
        try:
            _dl = json.loads(_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _dl = {}
        _dl.setdefault("cam_bien", {})
    return _dl


def _luu() -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_nap(), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def ds() -> dict[str, dict[str, Any]]:
    with _khoa:
        return {k: dict(v) for k, v in _nap()["cam_bien"].items()}


def la_ghep(ma: str) -> bool:
    return str(ma or "") in _nap()["cam_bien"]


def _kiem(bt: Any, sau: int = 0) -> None:
    if sau > 8 or not isinstance(bt, dict) or len(bt) not in (1, 2):
        raise ValueError("Biểu thức: {ma[, la]} | {va: [...]} | {hoac: [...]} | {khong: …} | {khoang_cach: …}.")
    if set(bt) == {"khoang_cach"}:
        if not re.fullmatch(r"sensor\.[a-z0-9_]+", str(bt["khoang_cach"])):
            raise ValueError(f"«khoang_cach» phải là mã cảm biến khoảng cách, không phải «{bt['khoang_cach']}».")
    elif "ma" in bt:
        if not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", str(bt["ma"])) or str(bt["ma"]).startswith(TIEN_TO):
            raise ValueError(f"Thực thể «{bt['ma']}» không hợp lệ (không ghép cảm biến ghép vào nhau).")
        la = bt.get("la", ["on"])
        if not isinstance(la, list) or not la or not all(isinstance(x, str) for x in la):
            raise ValueError("«la» phải là danh sách trạng thái, vd [\"on\"].")
        if set(bt) - {"ma", "la"}:
            raise ValueError("Nút thực thể chỉ có «ma» và «la».")
    elif set(bt) == {"khong"}:
        _kiem(bt["khong"], sau + 1)
    elif len(bt) == 1 and next(iter(bt)) in ("va", "hoac") and isinstance(next(iter(bt.values())), list) \
            and next(iter(bt.values())):
        for x in next(iter(bt.values())):
            _kiem(x, sau + 1)
    else:
        raise ValueError("Biểu thức: {ma[, la]} | {va: [...]} | {hoac: [...]} | {khong: …} | {khoang_cach: …}.")


def dat(ma: str, ten: str, bieu_thuc: dict[str, Any], loai: str = "occupancy") -> dict[str, Any]:
    """Thêm / sửa một cảm biến ghép. ``ma`` phải bắt đầu bằng ``binary_sensor.c2a_``."""
    ma = str(ma or "").strip()
    if not re.fullmatch(re.escape(TIEN_TO) + r"[a-z0-9_]+", ma):
        raise ValueError(f"Mã cảm biến ghép phải dạng {TIEN_TO}<chữ_thường_số>.")
    if not str(ten or "").strip() or len(str(ten)) > 60:
        raise ValueError("Tên cảm biến ghép 1–60 chữ.")
    if loai not in ("occupancy", "presence", "motion", "power", "running", ""):
        raise ValueError("Loại: occupancy / presence / motion / power / running.")
    _kiem(bieu_thuc)
    with _khoa:
        _nap()["cam_bien"][ma] = {"ten": str(ten).strip(), "loai": loai, "bieu_thuc": bieu_thuc}
        _cuoi[ma] = "on" if tinh(bieu_thuc, _tt_ha()) else "off"
        _luu()
    return ds()[ma]


def xoa(ma: str) -> bool:
    with _khoa:
        co = _nap()["cam_bien"].pop(str(ma), None) is not None
        _cuoi.pop(str(ma), None)
        if co:
            _luu()
    return co


def thanh_phan(bt: Any) -> set[str]:
    if "ma" in bt:
        return {str(bt["ma"])}
    if "khoang_cach" in bt:
        return {str(bt["khoang_cach"])}
    if "khong" in bt:
        return thanh_phan(bt["khong"])
    return set().union(*(thanh_phan(x) for x in next(iter(bt.values()))))


def _khoang_cach_cua(bt: Any) -> set[str]:
    if "khoang_cach" in bt:
        return {str(bt["khoang_cach"])}
    if "ma" in bt:
        return set()
    if "khong" in bt:
        return _khoang_cach_cua(bt["khong"])
    return set().union(*(_khoang_cach_cua(x) for x in next(iter(bt.values()))))


def tinh(bt: Any, tt: dict[str, str]) -> bool:
    """Giá trị biểu thức trên trạng thái ``tt`` (mã → trạng thái chữ thường). Thiếu = không khớp."""
    if "ma" in bt:
        return tt.get(str(bt["ma"]), "") in {str(x).lower() for x in bt.get("la", ["on"])}
    if "khoang_cach" in bt:
        from services import vung_khoang_cach
        return vung_khoang_cach.trong_vung(bt["khoang_cach"], tt.get(str(bt["khoang_cach"])))
    if "khong" in bt:
        return not tinh(bt["khong"], tt)
    if "va" in bt:
        return all(tinh(x, tt) for x in bt["va"])
    return any(tinh(x, tt) for x in bt["hoac"])


def _tt_ha() -> dict[str, str]:
    try:
        from services import ha_client
        return {str(s["entity_id"]): str(s.get("state") or "").lower() for s in ha_client.get_states() or []}
    except Exception:  # noqa: BLE001
        return {}


def hien_tai(tt: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Trạng thái hiện tại của mọi cảm biến ghép, cùng dạng một state HA."""
    tt = _tt_ha() if tt is None else tt
    return [{"entity_id": ma, "state": "on" if tinh(c["bieu_thuc"], tt) else "off",
             "attributes": {"friendly_name": c["ten"], "device_class": c.get("loai") or ""}}
            for ma, c in ds().items()]


def chuoi(ro: sqlite3.Connection, ma: str, tu: float, den: float) -> list[tuple[float, str]]:
    """Chuỗi (ts, "on"/"off") của cảm biến ghép ``ma`` trong [tu, den), dựng từ lịch sử cảm biến
    gốc: mốc đầu ở ``tu`` là giá trị lúc ấy, sau đó chỉ các lần ĐỔI."""
    c = ds().get(ma)
    if not c:
        return []
    bt = c["bieu_thuc"]
    # Khoảng cách: kho chỉ giữ số gộp 5 phút (còn sót vài bản ghi sự kiện cũ — đọc chúng là mang một số cũ
    # suốt 30 ngày) → ở quá khứ nút khoảng cách là "không đo được" = đúng (`vung_khoang_cach.trong_vung`).
    goc = sorted(thanh_phan(bt) - _khoang_cach_cua(bt))
    tt: dict[str, str] = {}
    for g in goc:
        r = ro.execute("SELECT gia_tri FROM su_kien WHERE thiet_bi=? AND truong='state' AND ts<?"
                       " ORDER BY ts DESC LIMIT 1", (g, tu)).fetchone()
        if r:
            tt[g] = str(r[0]).lower()
    cu = "on" if tinh(bt, tt) else "off"
    ra = [(float(tu), cu)]
    if not goc:
        return ra
    dau = ",".join("?" * len(goc))
    for ts, g, gt in ro.execute(
            f"SELECT ts, thiet_bi, gia_tri FROM su_kien WHERE truong='state' AND ts>=? AND ts<?"
            f" AND thiet_bi IN ({dau}) ORDER BY ts", (tu, den, *goc)):
        tt[str(g)] = str(gt).lower()
        moi = "on" if tinh(bt, tt) else "off"
        if moi != cu:
            ra.append((float(ts), moi))
            cu = moi
    return ra


def khoi_tao() -> None:
    """Ghi nhớ giá trị hiện tại của mọi cảm biến ghép — gọi khi ``ha_live`` vừa nạp lại toàn bộ
    trạng thái HA. Không có bước này thì lần đổi ĐẦU TIÊN sau khởi động bị nuốt (không biết giá
    trị trước đó)."""
    tt = _tt_ha()
    with _khoa:
        for ma, c in _nap()["cam_bien"].items():
            _cuoi[ma] = "on" if tinh(c["bieu_thuc"], tt) else "off"


def khi_doi(entity_id: str) -> list[tuple[str, str]]:
    """Gọi từ ``ha_live`` SAU khi bộ nhớ trạng thái đã cập nhật: tính lại các cảm biến ghép có
    dùng ``entity_id``, cái nào ĐỔI thì báo bộ kích hoạt như một cảm biến HA. Trả các lần đổi."""
    ghep = [(ma, c) for ma, c in ds().items() if entity_id in thanh_phan(c["bieu_thuc"])]
    if not ghep:
        return []
    tt = _tt_ha()
    doi = []
    with _khoa:
        for ma, c in ghep:
            v = "on" if tinh(c["bieu_thuc"], tt) else "off"
            if _cuoi.get(ma) != v:
                if ma in _cuoi:           # chưa từng ghi nhớ (hiếm — xem khoi_tao): chỉ ghi nhớ
                    doi.append((ma, v))
                _cuoi[ma] = v
    if doi:
        from services import kich_hoat_nha
        for ma, v in doi:
            logger.info({"event": "cam_bien_ghep_doi", "cam_bien": ma, "trang_thai": v})
            kich_hoat_nha.su_kien(ma, v)
    return doi


def _reset_for_tests(duong: Path) -> None:
    global _dl, _PATH
    _dl, _PATH = None, duong
    _cuoi.clear()
