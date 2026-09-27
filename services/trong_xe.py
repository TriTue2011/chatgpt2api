"""Trông xe — CHỈ khi được nhờ: xe đổi chỗ thì báo động (loa + tin nhắn), người nhà lấy xe thì thôi.

Chủ máy 27/09/2026: "trường hợp tôi yêu cầu em trông cho tôi xe ở cửa, báo động khi có trộm …
khi xe thay đổi tọa độ thì báo động bằng âm thanh, tin nhắn. Nhưng nếu nhận diện được người nhà
qua cam thì không báo động và dừng theo dõi, hoặc yêu cầu dừng theo dõi" — "chỉ giám sát khi
được yêu cầu, không giám sát khi yêu cầu dừng hoặc người nhà lấy xe đi".

Vì sao không chỉ nhìn hộp YOLO: đo 27/09/2026 trên vật đứng yên (bếp, phòng khách, 12 khung
~2 giây): hộp giữ IoU trung vị 0,96–0,99, nhưng vật YOLO kém chắc (điểm 0,38–0,45) có lúc MẤT
HẲN 1–2 khung hoặc lệch còn 0,33. Nên "xe bị dời" phải đủ HAI dấu hiệu, LIÊN TIẾP `LAN_XAC_NHAN`
lần kiểm: (1) không còn xe nào ở chỗ cũ (IoU < `IOU_CON`), và (2) ảnh vùng xe khác hẳn lúc bắt
đầu — "khác hẳn" do BOT TỰ ĐO độ nhiễu (trung vị) của chính vùng ấy ở các lượt YÊN (không người
trong khung) đầu tiên; mốc cũng chỉ chụp lúc yên. Cả khung
đổi sáng (bật đèn, camera chuyển hồng ngoại) thì lấy lại mốc, không báo động.

Người nhà: lúc xe đổi chỗ, nhìn mặt trong khung đó, và xem lượt gặp người quen ở camera này hoặc
từ thiết bị nhận mặt ngoài (`mat_ngoai`) trong `NHA_GIAY` giây — có thì dừng, không báo động.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

XE = frozenset({"car", "motorcycle", "bicycle", "truck", "bus"})
CHU_KY = 1.0
#: Báo sớm «có người ở chỗ xe» tối đa một lần trong ngần này giây.
BAO_SOM_CACH = 60.0
IOU_CON = 0.5
LAN_XAC_NHAN = 3
LAN_DO_NHIEU = 5
#: Đủ ngần này lượt YÊN (có mốc) thì bắt đầu phán — không bắt chờ đủ LAN_DO_NHIEU: chủ máy
#: 27/09/2026 "ít nhất phải thông báo ngay chứ".
LAN_PHAN_TOI_THIEU = 3
#: Lúc yên YOLO thấy xe ở ngần này tỉ lệ lượt trở lên thì YOLO "mất xe" đáng tin hơn — hạ ngưỡng
#: "vùng xe khác hẳn" từ 3× xuống 2× nhiễu. KHÔNG bỏ hẳn điều kiện ảnh: ảnh vùng xe không đổi là
#: bằng chứng mạnh xe còn nằm đó, YOLO lỡ thì chỉ là YOLO lỡ.
THAY_ON_DINH = 0.8
#: Sàn của ngưỡng "khác hẳn" (độ lệch trung bình 0–255 của vùng xe, ảnh xám 64×64).
SAN_KHAC = 12.0
NHA_GIAY = 180
_PATH = Path(DATA_DIR) / "agent" / "trong_xe.json"

_khoa = threading.RLock()
#: Luồng trông đang chạy và cờ dừng CỦA RIÊNG nó. Mỗi lần bật là một cờ mới: dùng chung một cờ
#: thì «dừng» rồi «trông xe» ngay sau đó gặp luồng cũ chưa kịp thoát — lượt mới không ai trông.
_luong: tuple[threading.Thread, threading.Event] | None = None
_moc: dict[str, Any] = {}          # vùng xe (ảnh xám) + độ nhiễu tự đo — ghi cả ra đĩa (`_luu_moc`)
_cho_xe = 0                         # số lượt liền không thấy xe khi phải dựng mốc lại từ đầu
KHOA_TB = "camera.trong_xe"


class LoiTrongXe(RuntimeError):
    pass


def _nap() -> dict[str, Any]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8")) if _PATH.is_file() else {}
    except Exception:  # noqa: BLE001 — tệp hỏng coi như không trông
        return {}


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def trang_thai() -> dict[str, Any]:
    return _nap()


LUONG = ("phu", "chinh", "khoa")


def cai_dat() -> dict[str, Any]:
    """``nhin_nha.trong_xe`` — chủ máy chỉnh trên web (thẻ Nhìn nhà), cùng khuôn nhận mặt.

    * ``luong``: luồng camera dùng khi trông — "phu" (mặc định, nhẹ) | "chinh" | "khoa".
    * ``bao_loa``: báo động có hú loa không. Mặc định TẮT — chủ máy 27/09/2026 "Tạm thời cảnh
      báo về zalo, không cảnh báo loa".
    """
    from services.config import config
    c = (config.data.get("nhin_nha") or {}).get("trong_xe")
    c = c if isinstance(c, dict) else {}
    luong = str(c.get("luong") or "phu")
    return {"luong": luong if luong in LUONG else "phu", "bao_loa": bool(c.get("bao_loa"))}


#: Luồng giữ mở suốt lúc trông: khung mới gần như tức thì (chụp ảnh qua go2rtc tốn ~1 giây mỗi
#: lần). Mốc lúc bật và MỌI lượt kiểm cùng lấy từ luồng phụ nên toạ độ hộp xe luôn khớp. Đo
#: 27/09/2026 Cam phòng khách: luồng phụ 640×480 mở ~3 giây rồi ra khung liên tục; luồng khung khoá
#: của camera này 12 giây không ra khung nào — nên không dùng.
_doc: dict[str, Any] = {}


def _khung(cam: str, luong: str = "phu"):
    from services import camera_nha, yolo_nha
    with _khoa:
        d = _doc.get(cam)
        if d is None:
            try:
                d = _doc[cam] = camera_nha.mo_video(cam, luong)
            except Exception as exc:  # noqa: BLE001 — không giữ được luồng thì chụp ảnh luồng phụ
                logger.info({"event": "trong_xe_khong_mo_luong", "loi": str(exc)[:120]})
    if d is not None:
        kq = d.khung_moi(time.time(), cho=4.0)
        if kq is not None:
            return kq[1]
    # Luồng không ra khung (khung khoá của vài camera không đều): chụp ảnh ĐÚNG CỠ luồng ấy.
    return yolo_nha.doc_anh(camera_nha.chup_tho(cam, phu=luong == "phu", timeout=10)[1])


def _dong_luong() -> None:
    with _khoa:
        ds = list(_doc.values())
        _doc.clear()
    for d in ds:
        try:
            d.dong()
        except Exception:  # noqa: BLE001
            pass


def _anh_ro(cam: str):
    """Ảnh luồng CHÍNH để nhìn mặt — mặt trong luồng phụ 640×480 chỉ còn vài chục điểm ảnh."""
    from services import camera_nha, yolo_nha
    return yolo_nha.doc_anh(camera_nha.chup_tho(cam, timeout=10)[1])


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    g = max(0, x2 - x1) * max(0, y2 - y1)
    h = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - g
    return g / h if h > 0 else 0.0


def _vung(anh, hop):
    import cv2
    x1, y1, x2, y2 = (int(v) for v in hop)
    cat = anh[max(0, y1):max(y1 + 1, y2), max(0, x1):max(x1 + 1, x2)]
    return cv2.resize(cv2.cvtColor(cat, cv2.COLOR_BGR2GRAY), (64, 64)).astype("float32")


def _trung_vi(ds) -> float:
    s = sorted(ds)
    return float(s[len(s) // 2]) if s else 0.0


def _lech(a, b) -> float:
    import numpy as np
    return float(np.mean(np.abs(a - b)))


def _toan_canh(anh):
    import cv2
    return cv2.resize(cv2.cvtColor(anh, cv2.COLOR_BGR2GRAY), (96, 54)).astype("float32")


def _tep_moc() -> Path:
    return _PATH.with_suffix(".moc.npz")


def _luu_moc() -> None:
    """Mốc ảnh vùng xe + độ nhiễu đã đo → đĩa (vài KB).

    Chỉ giữ trong RAM thì khởi động lại (mỗi lần đổi ảnh) phải dựng mốc từ khung đầu tiên, và
    muốn biết xe còn đó hay không chỉ còn MỘT khung YOLO để phán. Đo 27/09/2026 trên vật đứng
    yên ở Cam ban công: YOLO thấy nó 1/3 khung — lượt đầu sau khởi động lỡ mất là bot kết luận
    «xe đã đi» và thôi trông. Có mốc trên đĩa thì sau khởi động lại vẫn phán bằng đủ hai dấu
    hiệu và nhiều lượt liên tiếp như lúc chạy thường.
    """
    import numpy as np

    nhieu = np.full((len(_moc["vung"]), LAN_DO_NHIEU), np.nan, np.float32)
    for i, ds in enumerate(_moc["nhieu"]):
        nhieu[i, :len(ds)] = ds
    canh = np.full(LAN_DO_NHIEU, np.nan, np.float32)
    canh[:len(_moc["nhieu_canh"])] = _moc["nhieu_canh"]
    thay = np.full((len(_moc["vung"]), LAN_DO_NHIEU + 1), np.nan, np.float32)
    for i, ds in enumerate(_moc["thay"]):
        thay[i, :len(ds)] = ds
    try:
        with open(_tep_moc(), "wb") as f:
            np.savez(f, canh=_moc["canh"], vung=np.stack(_moc["vung"]), nhieu=nhieu, nhieu_canh=canh,
                     thay=thay, yen=np.array(bool(_moc.get("yen"))))
    except OSError as exc:
        logger.warning({"event": "trong_xe_luu_moc_loi", "loi": str(exc)[:120]})


def _nap_moc(so_xe: int) -> bool:
    import numpy as np

    try:
        with np.load(_tep_moc()) as z:
            vung, nhieu, canh = list(z["vung"]), z["nhieu"], z["nhieu_canh"]
            _moc.update(canh=z["canh"], vung=vung, lech_lien=0,
                        nhieu=[[float(x) for x in hang if x == x] for hang in nhieu],
                        nhieu_canh=[float(x) for x in canh if x == x],
                        thay=[[bool(x) for x in hang if x == x] for hang in z["thay"]],
                        yen=bool(z["yen"]))
    except (OSError, KeyError, ValueError):
        return False
    if len(_moc["vung"]) != so_xe:
        _moc.clear()
        return False
    return True


def _dung_moc(anh, xe: list[dict[str, Any]], *, yen: bool = True) -> None:
    """Mốc ảnh để so. ``yen`` = khung này yên (không người, YOLO thấy đủ xe). Mốc KHÔNG yên chỉ là
    tạm: lượt yên đầu tiên sẽ chụp lại, và chưa có mốc yên thì chưa đo nhiễu, chưa phán."""
    nha = _moc.get("nha")
    _moc.clear()
    _moc.update(canh=_toan_canh(anh), vung=[_vung(anh, x["hop"]) for x in xe],
                nhieu=[[] for _ in xe], nhieu_canh=[], lech_lien=0,
                thay=[[True] for _ in xe] if yen else [[] for _ in xe], yen=yen)
    if nha:
        _moc["nha"] = nha
    _luu_moc()


def _che_xe(xe: list[dict[str, Any]], vat: list) -> bool:
    """Có người đứng chạm vùng xe không.

    Người đứng cạnh / trước xe che mất xe: YOLO mất hộp và ảnh vùng xe đổi y như xe bị dắt đi.
    Mặt lúc người đang cử động thì mờ, nhận không ra (đo 27/09/2026 ở Cam cửa: mặt đi 2,5–3,9
    bề rộng mặt/giây đều nhoè, người nhà bị báo «người lạ») — đếm những lượt ấy là báo động
    nhầm cả nhà mỗi lần có người ra lấy đồ cạnh xe. Nên khi có người chạm vùng xe thì CHƯA
    đếm; kẻ dắt xe đi rồi chỗ ấy trống cả người lẫn xe thì mới đếm, trễ vài giây.
    """
    for v in vat:
        if v.nhan != "person":
            continue
        for x in xe:
            a, b = x["hop"], v.hop
            if min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]):
                return True
    return False


def _ve_xe(anh, xe: list[dict[str, Any]]) -> str:
    """Ảnh có khung xe đang trông → URL /images/ để gửi kèm tin."""
    import cv2

    from services import camera_nha
    from services.config import config
    from services.local_gateway import gateway_base_url

    ve = anh.copy()
    day = max(2, round(max(anh.shape[:2]) / 600))
    for x in xe:
        x1, y1, x2, y2 = (int(v) for v in x["hop"])
        cv2.rectangle(ve, (x1, y1), (x2, y2), (0, 0, 255), day)
    ok, buf = cv2.imencode(".jpg", ve)
    if not ok:
        return ""
    thu_muc = config.images_dir / time.strftime("%Y") / time.strftime("%m") / time.strftime("%d")
    thu_muc.mkdir(parents=True, exist_ok=True)
    tep = f"trong_xe_{int(time.time() * 1000)}.jpg"
    (thu_muc / tep).write_bytes(camera_nha._thu_nho(buf.tobytes(), camera_nha.CANH_GUI))
    return f"{gateway_base_url()}/images/{time.strftime('%Y/%m/%d')}/{tep}"


def _loa_bao_dong() -> list[str]:
    """Loa hú khi báo động: mọi loa đã khai, trừ khi chủ máy tắt (cài đặt ``trong_xe.bao_loa``).

    Chủ máy 27/09/2026 20:5x: "Tạm thời cảnh báo về zalo, không cảnh báo loa" — mặc định TẮT loa,
    chỉ nhắn tin. Bật lại: ô «hú loa» ở mục Trông xe (``nhin_nha.trong_xe.bao_loa``).
    """
    if not cai_dat()["bao_loa"]:
        return []
    from services.voice import speakers
    return [str(r.get("name")) for r in speakers.list_speakers() if r.get("name")]


def bat(camera: str = "", *, loa: list[str] | None = None, dich: str = "") -> dict[str, Any]:
    """Bắt đầu trông xe ở ``camera``. ``loa``: tên loa báo động (None = mọi loa đã khai, [] =
    không loa). ``dich``: kênh chat của người nhờ (tin báo động gửi thẳng về đó). Trả
    ``{"camera", "xe", "anh"}``; không thấy xe / chưa rõ camera → `LoiTrongXe`."""
    from services import camera_nha, nhin_nha

    ten, cam, goi_y = camera_nha.tim(camera) if camera else ("", None, [])
    if not camera:
        ds = [str(c.get("name")) for c in camera_nha.danh_sach() if c.get("name")]
        if len(ds) != 1:
            raise LoiTrongXe("Anh muốn em trông xe ở camera nào ạ? Đang có: " + ", ".join(ds))
        ten = ds[0]
    elif cam is None:
        raise LoiTrongXe("Em chưa rõ camera nào. Đang có: " + ", ".join(goi_y))
    luong = cai_dat()["luong"]
    anh = _khung(ten, luong)
    vat = nhin_nha.vat_the(anh, chi_nhan=set(XE) | {"person"})
    xe = [{"nhan": v.nhan, "diem": round(float(v.diem), 2), "hop": [int(x) for x in v.hop]}
          for v in vat if v.nhan in XE]
    if not xe:
        raise LoiTrongXe(f"Em không thấy xe nào ở {ten} lúc này — anh kiểm lại xe có trong khung camera không ạ.")
    if loa is None:
        loa = _loa_bao_dong()
    d = {"bat": True, "camera": ten, "xe": xe, "tu": time.time(), "loa": list(loa), "dich": dich, "luong": luong}
    with _khoa:
        _luu(d)
        _dung_moc(anh, xe, yen=not any(v.nhan == "person" for v in vat))
    _chay()
    logger.info({"event": "trong_xe_bat", "camera": ten, "so_xe": len(xe)})
    return {"camera": ten, "xe": xe, "loa": list(loa), "anh": _ve_xe(anh, xe)}


def dung(ly_do: str = "chu_may") -> bool:
    with _khoa:
        d = _nap()
        if not d.get("bat"):
            return False
        d.update(bat=False, dung_luc=time.time(), ly_do=ly_do)
        _luu(d)
        _moc.clear()
        _tep_moc().unlink(missing_ok=True)
        _dong_luong()
        if _luong is not None:
            _luong[1].set()
    logger.info({"event": "trong_xe_dung", "ly_do": ly_do})
    return True


def _mat_nha_trong_khung(anh, kq_vat: list) -> str:
    from services import nhin_nha

    if any(v.nhan == "person" for v in kq_vat) and nhin_nha.co_mat():
        try:
            for m in nhin_nha.phan_tich_khung(anh).mat:
                if m.get("nguoi_id") and m.get("loai") == "quen":
                    return str(m["ten"])
        except Exception as exc:  # noqa: BLE001 — không nhìn được mặt thì dựa vào lượt gặp
            logger.info({"event": "trong_xe_nhin_mat_loi", "loi": str(exc)[:120]})
    return ""


def _nguoi_nha(cam: str, anh, kq_vat: list) -> str:
    """Tên người nhà vừa thấy quanh xe, không có → "".

    Ba nguồn: mặt trong khung này; mặt nhận được lúc có người đứng che xe (`_moc["nha"]`,
    ghi trong lúc chờ); lượt gặp người quen của camera canh / thiết bị nhận mặt ngoài.
    """
    from services import so_mat_nha

    ten = _mat_nha_trong_khung(anh, kq_vat)
    if ten:
        return ten
    nha = _moc.get("nha")
    if nha and time.time() - nha[1] <= NHA_GIAY:
        return str(nha[0])
    for s in so_mat_nha.su_kien_gan(NHA_GIAY / 3600, gioi_han=20):
        if s.get("nguoi_id") and s.get("loai") == "quen" and (
                s.get("camera") == cam or str(s.get("nguon") or "").startswith("ngoai:")):
            return str(s.get("ten") or "")
    return ""


def _bao(d: dict[str, Any], tin: str, anh_url: str) -> int:
    """Gửi về kênh người nhờ trông, và các kênh đã chọn cho «Camera — trông xe» — mỗi kênh MỘT lần.

    Không qua `thong_bao.gui`: kênh người nhờ thường cũng nằm trong danh sách ấy, gửi hai
    đường là báo động tới hai lần cùng một chat.
    """
    from services import digest, thong_bao

    c = thong_bao.cai_dat(KHOA_TB)
    kenh = [str(d["dich"])] if d.get("dich") else []
    kenh += [k for k in (c["kenh"] if c["bat"] else []) if k not in kenh]
    if not kenh:
        logger.warning({"event": "trong_xe_khong_kenh", "ghi_chu": "không biết người nhờ và chưa chọn kênh"})
        return 0
    return digest.send_targets(kenh, tin, anh_url)


def _bao_dong(d: dict[str, Any], anh) -> None:
    from services.voice import announce

    tin = f"🚨 BÁO ĐỘNG: xe ở {d['camera']} đang bị di chuyển lúc {time.strftime('%H:%M:%S')} — em không nhận ra người nhà nào."
    _bao(d, tin + "\nEm đã dừng trông; nhắn «trông xe» để trông tiếp.", _ve_xe(anh, d["xe"]))
    cau = f"Cảnh báo! Xe ở {d['camera']} đang bị di chuyển! Cảnh báo! Xe đang bị di chuyển!"
    for ten in d.get("loa") or []:
        threading.Thread(target=_phat, args=(announce, ten, cau), daemon=True).start()


def _phat(announce, ten: str, cau: str) -> None:
    try:
        announce.schedule(ten, cau, delay_seconds=0, volume=0.9)
    except Exception as exc:  # noqa: BLE001 — một loa hỏng không chặn loa khác
        logger.warning({"event": "trong_xe_loa_loi", "loa": ten, "loi": str(exc)[:120]})


def kiem_mot_lan() -> str:
    """Một lượt kiểm. Trả "" | "lech" | "co_nguoi" | "bao_dong" | "nguoi_nha" | "doi_sang"
    | "mat_xe_khi_nghi" (cho test/log)."""
    from services import nhin_nha

    d = _nap()
    if not d.get("bat"):
        return ""
    cam = d["camera"]
    anh = _khung(cam, str(d.get("luong") or "phu"))
    vat = nhin_nha.vat_the(anh, chi_nhan=set(XE) | {"person"})
    hien = [v for v in vat if v.nhan in XE]
    global _cho_xe
    with _khoa:
        ra = ""
        if not _moc and not _nap_moc(len(d["xe"])):
            # Không có mốc trên đĩa: dựng từ khung này — nhưng chỉ khi xe còn ở chỗ cũ. Lấy chỗ
            # trống làm mốc thì từ đó không bao giờ báo được nữa. Một khung YOLO lỡ mất xe chưa
            # đủ để kết luận (vật kém chắc có lúc mất 1–2 khung): đợi LAN_DO_NHIEU lượt liền.
            if all(max([_iou(x["hop"], v.hop) for v in hien] or [0]) >= IOU_CON for x in d["xe"]):
                _cho_xe = 0
                _dung_moc(anh, d["xe"], yen=not any(v.nhan == "person" for v in vat))
                return ""
            _cho_xe += 1
            if _cho_xe < LAN_DO_NHIEU:
                return ""
            _cho_xe = 0
            ra = "mat_xe_khi_nghi"
    if ra:
        dung(ra)
        _bao(d, f"⚠️ Máy vừa khởi động lại, em không còn thấy xe ở chỗ cũ ({cam}). Em dừng trông — "
                "anh kiểm tra xe giúp em.", _ve_xe(anh, d["xe"]))
        return ra
    # YÊN = không ai trong khung. Chỉ lượt yên mới được làm mốc và đo nhiễu. Đo 27/09/2026 ở Cam
    # phòng khách: chủ máy đặt xe đạp rồi đi ra đúng lúc bot đo 5 lượt đầu — cả khung lệch 14–16,
    # vùng xe tới 55,8 → ngưỡng "khác hẳn" 3 × 55,8 = 167; dắt xe đi thật chỉ lệch 32, bot im.
    yen = not any(v.nhan == "person" for v in vat)
    iou = [max([_iou(x["hop"], v.hop) for v in hien] or [0]) for x in d["xe"]]
    with _khoa:
        if not _moc.get("yen"):
            if yen and all(i >= IOU_CON for i in iou):
                _dung_moc(anh, d["xe"])
            return "cho_yen"
        k = [_lech(_vung(anh, x["hop"]), _moc["vung"][i]) for i, x in enumerate(d["xe"])]
        lech_canh = _lech(_toan_canh(anh), _moc["canh"])
        if yen and len(_moc["nhieu_canh"]) < LAN_DO_NHIEU:
            _moc["nhieu_canh"].append(lech_canh)
            for i in range(len(d["xe"])):
                _moc["thay"][i].append(iou[i] >= IOU_CON)
                if iou[i] >= IOU_CON:            # nhiễu chỉ đo lúc xe còn đó
                    _moc["nhieu"][i].append(k[i])
            _luu_moc()
        elif (len(_moc["nhieu_canh"]) >= LAN_DO_NHIEU
              and lech_canh > max(SAN_KHAC, 3 * _trung_vi(_moc["nhieu_canh"]))
              and all(i >= IOU_CON for i in iou)):
            # Cả khung đổi sáng mà xe vẫn nằm đó (YOLO vẫn thấy): lấy lại mốc, không báo động.
            _dung_moc(anh, d["xe"], yen=yen)
            return "doi_sang"
        if min(len(t) for t in _moc["thay"]) < LAN_PHAN_TOI_THIEU:
            return ""
        if (_moc["nhieu_canh"] and lech_canh > max(SAN_KHAC, 3 * _trung_vi(_moc["nhieu_canh"]))
                and not all(i >= IOU_CON for i in iou) and yen):
            # Cả khung đổi hẳn (tắt/bật đèn, camera chuyển hồng ngoại) mà YOLO mất xe: chưa phân
            # biệt được "đèn tắt" với "xe đi" — chưa đếm, chờ cảnh ổn lại (YOLO thấy xe → lấy lại mốc).
            _moc["lech_lien"] = 0
            return "doi_canh"
        lech_ca = False
        for i in range(len(d["xe"])):
            if iou[i] >= IOU_CON:
                continue
            on_dinh = sum(_moc["thay"][i]) / len(_moc["thay"][i]) >= THAY_ON_DINH
            he_so = 2 if on_dinh else 3
            nguong = max(SAN_KHAC, he_so * _trung_vi(_moc["nhieu"][i])) if _moc["nhieu"][i] else SAN_KHAC
            if k[i] > nguong:
                lech_ca = True
        _moc["lech_lien"] = _moc["lech_lien"] + 1 if lech_ca else 0
        lech_lien = _moc["lech_lien"]
    # KHÔNG còn chờ người rời khung mới đếm. Đo 27/09/2026 23:07 Cam phòng khách: người vào khung
    # 23:07:35 (Frigate), dắt xe, rời khung 23:07:58 — bot báo đúng 23:07:58 vì luật "có người
    # đứng che xe thì chưa đếm"; chủ máy: "lấy trộm đi xa rồi mới báo". Nay: lượt lệch đầu tiên có
    # người ở chỗ xe → nhìn mặt (luồng chính); người nhà thì dừng, không thì BÁO SỚM ngay; đủ
    # LAN_XAC_NHAN lượt lệch liền → báo động.
    if lech_ca and _che_xe(d["xe"], vat):
        try:
            ten = _mat_nha_trong_khung(_anh_ro(cam), [v for v in vat if v.nhan == "person"])
        except Exception as exc:  # noqa: BLE001 — không chụp được luồng chính thì thôi nhìn mặt
            logger.info({"event": "trong_xe_anh_ro_loi", "loi": str(exc)[:120]})
            ten = ""
        if ten:
            with _khoa:
                _moc["nha"] = (ten, time.time())
    if lech_ca and lech_lien == 1:
        ten = _nguoi_nha(cam, anh, vat)
        if ten:
            dung("nguoi_nha")
            _bao(d, f"🏠 {ten} vừa lấy xe ở {cam} — em dừng trông xe.", "")
            return "nguoi_nha"
        if time.time() - float(_moc.get("bao_som_luc") or 0) >= BAO_SOM_CACH:
            with _khoa:
                _moc["bao_som_luc"] = time.time()
            _bao(d, f"⚠️ Xe ở {cam} vừa bị động tới lúc {time.strftime('%H:%M:%S')}"
                    + (" — có người ở chỗ xe" if _che_xe(d["xe"], vat) else "")
                    + ", em chưa nhận ra người nhà. Em đang theo dõi tiếp.", _ve_xe(anh, d["xe"]))
    if lech_lien < LAN_XAC_NHAN:
        return "lech" if lech_ca else ""
    ten = _nguoi_nha(cam, anh, vat)
    if ten:
        dung("nguoi_nha")
        _bao(d, f"🏠 {ten} vừa lấy xe ở {cam} — em dừng trông xe.", "")
        return "nguoi_nha"
    dung("bao_dong")
    _bao_dong(d, anh)
    return "bao_dong"


def _vong(dung_ev: threading.Event) -> None:
    while not dung_ev.wait(CHU_KY):
        try:
            if not kiem_mot_lan() and not _nap().get("bat"):
                return
        except Exception as exc:  # noqa: BLE001 — một lượt hỏng (camera chập chờn) không dừng trông
            logger.warning({"event": "trong_xe_loi", "loi": str(exc)[:160]})


def _chay() -> None:
    global _luong
    with _khoa:
        if _luong is not None and _luong[0].is_alive() and not _luong[1].is_set():
            return
        ev = threading.Event()
        t = threading.Thread(target=_vong, args=(ev,), name="trong-xe", daemon=True)
        _luong = (t, ev)
        t.start()


def khoi_phuc() -> bool:
    """Lúc khởi động: đang trông dở thì trông tiếp (mốc dựng lại từ khung đầu tiên)."""
    d = _nap()
    if d.get("bat") and d.get("luong") not in LUONG:
        # Lượt bật trước 27/09/2026: hộp xe theo toạ độ luồng chính, nay khung lấy từ luồng phụ.
        dung("phien_cu")
        return False
    if d.get("bat"):
        _chay()
        return True
    return False


def _reset_for_tests(duong: Path) -> None:
    global _PATH, _luong
    if _luong is not None:
        _luong[1].set()
    _luong = None
    _PATH = duong
    _moc.clear()
    global _cho_xe
    _cho_xe = 0
