"""Lưu trữ online — đẩy tài liệu và nhật ký lên kho đám mây của chủ máy.

Đi cùng nếp với «Nhật ký nhóm» (`services/agent/chatlog.py`), cố ý giống để chủ
máy chỉ phải học một cách nghĩ:

* **Mặc định TẮT.** Không phạm vi nào đẩy gì lên cho tới khi bật riêng. Đây là
  đem tài liệu người khác gửi trong nhóm bỏ vào tài khoản đám mây của chủ máy,
  nên phải chủ động bật.
* Cấu hình đặt ĐỘC LẬP theo phạm vi, kế thừa HẸP thắng RỘNG (người → topic →
  nhóm → kênh) — dùng lại đúng bộ khoá của nhật ký.
* Không raise. Mạng chập hay Drive đầy thì chat vẫn chạy như thường.

KHÁC nhật ký ở ba chỗ, đừng bê nguyên si:

1. Nhật ký ghi xuống đĩa, tính bằng mili giây. Đẩy file 3 MB lên Drive mất vài
   giây — phải chạy nền, không được chặn lượt trả lời.
2. Nhật ký tách phạm vi bằng KHOÁ, đủ khi dữ liệu nằm trên máy chủ vì chỉ phần
   mềm đọc nó. Lên đám mây thì file nằm trần, ai vào được tài khoản là đọc hết.
   Muốn "không thấy của nhau" đúng nghĩa thì khai kho kiểu `crypt` của rclone —
   nó mã hoá cả nội dung lẫn tên file trước khi gửi đi. Xem `canh_bao_ma_hoa`.
3. Hạn giữ có HAI mức: cục bộ (đã có sẵn) và online (thêm ở đây). Online phải
   dài hơn hoặc bằng cục bộ, và đồng bộ là GHI THÊM chứ không ghi đè — cục bộ
   10 ngày mà online 20 ngày thì bản online vẫn phải đủ 20.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config
from utils.log import logger

# Hạn giữ online mặc định: dài hơn hạn cục bộ (30 ngày của images) để đám mây
# thật sự là nơi giữ lâu, chứ không phải bản sao hết hạn cùng lúc.
MAC_DINH_GIU_NGAY = 365
# Giờ đồng bộ CHỈ áp cho nhật ký, chạy hằng ngày. Tệp thì đã hỏi admin ngay lúc
# nhận nên không cần đồng bộ theo giờ — chủ máy chốt 05/08.
MAC_DINH_GIO_DONG_BO = "03:00"   # giờ thấp điểm, không đụng lúc nhà đang dùng

# Mỗi mục một thư mục con, KHÔNG lưu chung — chủ máy nêu rõ "để khi tìm kiếm
# cũng dễ". Hạn giữ online cũng chia theo đúng các mục này.
THU_MUC_THEO_LOAI: dict[str, str] = {
    ".pdf": "PDF",
    ".doc": "Word", ".docx": "Word",
    ".xls": "Excel", ".xlsx": "Excel",
    ".ppt": "PowerPoint", ".pptx": "PowerPoint",
    ".jpg": "Ảnh", ".jpeg": "Ảnh", ".png": "Ảnh", ".gif": "Ảnh",
    ".webp": "Ảnh", ".heic": "Ảnh", ".bmp": "Ảnh", ".tif": "Ảnh", ".tiff": "Ảnh",
}
THU_MUC_NHAT_KY = "Nhật ký"
THU_MUC_KHAC = "Khác"

#: Mọi mục có thể đặt hạn giữ riêng. Giao diện dựng ô nhập từ danh sách này nên
#: thêm mục mới ở đây là giao diện có ngay, không phải sửa hai chỗ.
CAC_MUC: tuple[str, ...] = ("PDF", "Word", "Excel", "PowerPoint",
                            THU_MUC_NHAT_KY, "Ảnh", THU_MUC_KHAC)


def thu_muc_loai(ten_tep: str) -> str:
    """Tên thư mục con theo loại tệp. Không nhận ra thì vào 'Khác'."""
    ten = str(ten_tep or "").strip().lower()
    for duoi, thu_muc in THU_MUC_THEO_LOAI.items():
        if ten.endswith(duoi):
            return thu_muc
    return THU_MUC_KHAC


def _cac_khoa_cai_dat(kenh: str, chat: str, topic: str, user: str) -> list[str]:
    """Khoá cấu hình từ HẸP tới RỘNG — cùng thứ tự với nhật ký nhóm.

    'plat:chat#topic:user' → 'plat:chat#topic' → 'plat:chat:user' →
    'plat:chat' → 'plat'.
    """
    out: list[str] = []
    if user:
        if topic:
            out.append(f"{kenh}:{chat}#{topic}:{user}")
        out.append(f"{kenh}:{chat}:{user}")
    if topic:
        out.append(f"{kenh}:{chat}#{topic}")
    out.append(f"{kenh}:{chat}")
    out.append(kenh)
    seen: set[str] = set()
    return [k for k in out if not (k in seen or seen.add(k))]


def _so_ngay(v: Any, mac_dinh: int) -> int:
    try:
        n = int(v if v is not None else mac_dinh)
    except (TypeError, ValueError):
        return mac_dinh
    return max(0, n)


def _giu_ngay(v: Any) -> dict[str, int]:
    """Hạn giữ online tách RIÊNG theo từng mục — {'PDF': 365, 'Ảnh': 90, …}.

    Nhận cả một SỐ đơn: đó là dạng cũ, hiểu là "mọi mục cùng hạn này". Giữ lại
    để cấu hình viết trước lúc tách mục không im lặng rơi về mặc định.
    """
    if isinstance(v, dict):
        return {m: _so_ngay(v.get(m), MAC_DINH_GIU_NGAY) for m in CAC_MUC}
    chung = _so_ngay(v, MAC_DINH_GIU_NGAY)
    return {m: chung for m in CAC_MUC}


_GIO_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _gio(v: Any) -> str:
    s = str(v or "").strip()
    return s if _GIO_RE.match(s) else MAC_DINH_GIO_DONG_BO


def cai_dat(kenh: str, chat: str = "", topic: str = "", user: str = "") -> dict:
    """Cấu hình lưu trữ online hiệu lực cho một phạm vi. Mặc định TẮT.

    Trả {enabled, kho, thu_muc, hoi_truoc, giu_ngay, gio_dong_bo}.

    `hoi_truoc=True` → mỗi tệp hỏi admin "1. Lưu / 2. Luôn luôn lưu / 3. Xoá".
    Admin chọn "Luôn luôn lưu" thì ghi `hoi_truoc=False` cho phạm vi đó, từ đó
    về sau tự lưu. Chọn "Xoá" thì KHÔNG đẩy lên và bỏ luôn bản cục bộ — chủ máy
    chốt 05/08: "xoá là không đẩy lên online vì không muốn lưu file cục bộ".
    Vì vậy thứ tự bắt buộc là HỎI TRƯỚC, ĐẨY SAU — không có cảnh tệp đã nằm trên
    mây rồi mới nhận được lệnh xoá.
    """
    mac_dinh = {"enabled": False, "kho": "", "thu_muc": "",
                "hoi_truoc": True, "giu_ngay": _giu_ngay(None),
                "gio_dong_bo": MAC_DINH_GIO_DONG_BO}
    try:
        cfg = config.get().get("luu_tru_online")
    except Exception:
        cfg = None
    if not isinstance(cfg, dict) or not cfg:
        return mac_dinh
    for k in _cac_khoa_cai_dat(kenh, chat, topic, user):
        v = cfg.get(k)
        if not isinstance(v, dict):
            continue
        kho = str(v.get("kho") or "").strip()
        return {
            # Bật mà chưa khai kho thì coi như chưa bật: đẩy đi đâu bây giờ.
            "enabled": bool(v.get("enabled", False)) and bool(kho),
            "kho": kho,
            "thu_muc": str(v.get("thu_muc") or "").strip().strip("/"),
            "hoi_truoc": bool(v.get("hoi_truoc", True)),
            "giu_ngay": _giu_ngay(v.get("giu_ngay")),
            "gio_dong_bo": _gio(v.get("gio_dong_bo")),
        }
    return mac_dinh


def han_giu(cd: dict, ten_tep: str = "", *, nhat_ky: bool = False) -> int:
    """Hạn giữ online (ngày) của ĐÚNG mục mà tệp này thuộc về. 0 = giữ mãi."""
    muc = THU_MUC_NHAT_KY if nhat_ky else thu_muc_loai(ten_tep)
    giu = (cd or {}).get("giu_ngay")
    if isinstance(giu, dict):
        return _so_ngay(giu.get(muc), MAC_DINH_GIU_NGAY)
    return _so_ngay(giu, MAC_DINH_GIU_NGAY)


def duong_dan_dich(cd: dict, ten_tep: str, *, nhat_ky: bool = False) -> str:
    """Đường dẫn đầy đủ trên kho: 'kho:thư/mục/gốc/Loại/tên-tệp'.

    Trả chuỗi rỗng nếu phạm vi chưa bật — caller kiểm cái đó trước khi gọi.
    """
    if not (cd or {}).get("enabled"):
        return ""
    kho = str(cd.get("kho") or "").strip()
    if not kho:
        return ""
    loai = THU_MUC_NHAT_KY if nhat_ky else thu_muc_loai(ten_tep)
    phan = [p for p in (str(cd.get("thu_muc") or "").strip("/"), loai) if p]
    return f"{kho}:{'/'.join(phan)}"


def dat_luon_luon_luu(kenh: str, chat: str, topic: str = "", user: str = "") -> bool:
    """Admin chọn "Luôn luôn lưu" → tắt hỏi lại cho ĐÚNG phạm vi đang bật.

    Ghi vào khoá hẹp nhất ĐÃ CÓ bản ghi, không đẻ khoá mới: đẻ khoá mới ở cấp
    người thì lần sau người khác trong cùng nhóm vẫn bị hỏi, trong khi ý admin
    là "chỗ này khỏi hỏi nữa".
    """
    try:
        cfg = config.get().get("luu_tru_online")
        if not isinstance(cfg, dict):
            return False
        for k in _cac_khoa_cai_dat(kenh, chat, topic, user):
            v = cfg.get(k)
            if isinstance(v, dict):
                moi = dict(cfg)
                moi[k] = {**v, "hoi_truoc": False}
                config.update({"luu_tru_online": moi})
                return True
    except Exception as exc:
        logger.warning(f"luu_tru_online: đặt luôn-luôn-lưu lỗi: {str(exc)[:120]}")
    return False


def thread_admin_nhan(kenh: str, chat: str = "", topic: str = "", user: str = "") -> str:
    """Thread admin nhận câu hỏi xác nhận cho phạm vi này. '' = chưa khai.

    Chủ máy chốt 05/08: "nhỡ có nhiều admin thì không biết gửi cho ai". Nên mỗi
    phạm vi chỉ định RIÊNG một thread admin, tra theo đúng chuỗi khoá hẹp→rộng
    của nhật ký. Chưa khai thì trả rỗng — caller tự quyết (bỏ qua hoặc tự lưu),
    KHÔNG đoán bừa một admin: gửi tài liệu của nhóm này sang admin của nhóm khác
    là rò dữ liệu, tệ hơn hẳn so với không hỏi.
    """
    try:
        cfg = config.get().get("luu_tru_online")
    except Exception:
        return ""
    if not isinstance(cfg, dict):
        return ""
    for k in _cac_khoa_cai_dat(kenh, chat, topic, user):
        v = cfg.get(k)
        if isinstance(v, dict):
            t = str(v.get("thread_admin") or "").strip()
            if t:
                return t
    return ""


# ── Phạm vi nào đọc/ghi được kho nào ─────────────────────────────────────────
# Chủ máy chốt 06/08: "tôi muốn nó độc lập như nhật ký — chỉ khi kết nối mới có
# quyền đọc, tải về; tải lên thì vẫn chỉ tải lên đám mây được cài đặt thôi".
#
# Nên hai chiều KHÁC HẲN nhau:
#
#   ĐỌC  — kho của chính phạm vi này, CỘNG kho của các phạm vi đã «Kết nối bộ
#          nhớ» (bình đẳng hai chiều, chính-phụ một chiều — luật nằm ở
#          `scope._pham_vi_lien_ket_raw`, không viết lại ở đây).
#   GHI  — CHỈ kho của chính phạm vi này. Kết nối không mở đường ghi: nối rồi gỡ
#          mà dữ liệu đã chảy sang nhau thì không tách lại được.
#
# Trước bản này, năng lực `kho_dam_may` cho đọc MỌI kho đã khai, bất kể thread
# nào gọi — tức nhóm nào bật năng lực đó là cả nhóm xem được toàn bộ đám mây của
# chủ máy.


def _mot_kho(kenh: str, chat: str, topic: str, user: str) -> dict:
    cd = cai_dat(kenh, chat, topic, user)
    if not cd.get("enabled"):
        return {}
    return {"kho": cd["kho"], "thu_muc": cd.get("thu_muc") or "",
            "pham_vi": [kenh, chat, topic, user]}


def kho_ghi_duoc(user_id: str) -> dict:
    """Kho DUY NHẤT phạm vi này được ghi lên. {} nếu chưa khai."""
    from services.agent.scope import tach_khoa_phien
    sc = tach_khoa_phien(user_id)
    if not sc.chat:
        return {}
    return _mot_kho(sc.kenh, sc.chat, sc.topic, sc.actor)


def cac_kho_doc_duoc(user_id: str) -> list[dict]:
    """Các kho phạm vi này đọc được: của mình trước, rồi của phạm vi đã kết nối.

    Mỗi mục thêm `cua_minh` để giao diện/bot nói rõ đâu là kho của chính mình.
    """
    from services.agent.scope import kho_doc_them
    ra: list[dict] = []
    minh = kho_ghi_duoc(user_id)
    if minh:
        ra.append({**minh, "cua_minh": True})
    for kenh, chat, topic, user in kho_doc_them(user_id):
        k = _mot_kho(kenh, chat, topic, user)
        if not k:
            continue
        if any(x["kho"] == k["kho"] and x["thu_muc"] == k["thu_muc"] for x in ra):
            continue
        ra.append({**k, "cua_minh": False})
    return ra


def _khoa_pham_vi_thanh_khoa_phien(khoa: str) -> str:
    """Khoá cấu hình 'kenh:chat[#topic][:user]' → khoá phiên orchestrator.

    Đi vòng qua `scope.khoa_phien_tu_thanh_vien` chứ không tự ghép chuỗi: luật
    ghép khoá phiên của từng kênh chỉ được nằm ở MỘT chỗ.
    """
    from services.agent.scope import khoa_phien_tu_thanh_vien
    kenh, _, con = str(khoa or "").strip().partition(":")
    if not kenh or not con:
        return ""
    chat_topic, _, user = con.rpartition(":") if con.count(":") else (con, "", "")
    if not chat_topic:
        chat_topic, user = con, ""
    chat, _, topic = chat_topic.partition("#")
    return khoa_phien_tu_thanh_vien(
        {"kenh": kenh, "chat": chat, "topic": topic, "user": user})


def ban_do_doc_duoc() -> dict[str, list[dict]]:
    """Mỗi phạm vi đã khai kho đọc được những kho nào — cho giao diện hiển thị.

    Khai kết nối rồi mà không thấy được "ai đọc được của ai" thì chủ máy phải
    dò trong mã. Trả về đúng thứ `cac_kho_doc_duoc` tính, không tính lại ở giao
    diện: hai nơi cùng quyết định quyền đọc là hai nơi sẽ lệch nhau.
    """
    try:
        cfg = config.get().get("luu_tru_online")
    except Exception:
        return {}
    if not isinstance(cfg, dict):
        return {}
    ra: dict[str, list[dict]] = {}
    for khoa, v in cfg.items():
        if not isinstance(v, dict) or not v.get("enabled"):
            continue
        kp = _khoa_pham_vi_thanh_khoa_phien(khoa)
        if kp:
            ra[str(khoa)] = cac_kho_doc_duoc(kp)
    return ra


def _trong_pham_vi(duong_dan: str, kho: str, thu_muc: str) -> bool:
    """`duong_dan` có nằm trong `kho:thu_muc` không.

    So theo TỪNG ĐOẠN đường dẫn, không so tiền tố chuỗi: 'drive:c2a-rieng' có
    tiền tố 'drive:c2a' nhưng là thư mục KHÁC, cho qua là lộ dữ liệu.
    """
    s = str(duong_dan or "").strip()
    if ":" not in s:
        return False
    ten, _, phan = s.partition(":")
    if ten != kho:
        return False
    goc = str(thu_muc or "").strip("/")
    if not goc:
        return True                     # khai cả kho → mọi thư mục trong đó
    duong = phan.strip("/")
    return duong == goc or duong.startswith(goc + "/")


def duoc_doc(user_id: str, duong_dan: str) -> bool:
    """Phạm vi này được đọc đường dẫn đó không (kho mình + kho đã kết nối)."""
    return any(_trong_pham_vi(duong_dan, k["kho"], k["thu_muc"])
               for k in cac_kho_doc_duoc(user_id))


def duoc_ghi(user_id: str, duong_dan: str) -> bool:
    """Phạm vi này được ghi vào đường dẫn đó không — CHỈ kho của chính nó."""
    k = kho_ghi_duoc(user_id)
    return bool(k) and _trong_pham_vi(duong_dan, k["kho"], k["thu_muc"])


# ── Sổ những tệp ĐÃ ĐẨY LÊN ──────────────────────────────────────────────────
# Vì sao phải có sổ: hạn giữ online nghĩa là XOÁ tệp trên tài khoản đám mây của
# chủ máy. Nếu dọn theo kiểu "liệt kê thư mục rồi xoá tệp cũ hơn N ngày" thì một
# thư mục chủ máy chọn sẵn (đã có tài liệu riêng trong đó) sẽ bị bot xoá mất tài
# liệu cũ — hỏng dữ liệu thật, không phải chỉ mất tính năng.
#
# Nên: chỉ xoá đúng những tệp CHÍNH BOT đã đẩy lên, ghi lại trong sổ này. Mất sổ
# thì không xoá gì cả — hỏng về phía an toàn.

_SO_PATH = Path(DATA_DIR) / "agent" / "luu_tru_da_day.json"
_TRAN_SO = 20000            # van an toàn, đừng để sổ phình vô hạn
_khoa_so = threading.RLock()


def _doc_so() -> dict[str, dict]:
    try:
        v = json.loads(_SO_PATH.read_text("utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _ghi_so_file(so: dict[str, dict]) -> None:
    try:
        _SO_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SO_PATH.write_text(json.dumps(so, ensure_ascii=False), "utf-8")
    except OSError as exc:
        logger.warning(f"luu_tru_online: ghi sổ lỗi: {str(exc)[:120]}")


def ghi_so(duong_dan: str, kenh: str, chat: str, topic: str = "", user: str = "",
           *, nhat_ky: bool = False) -> None:
    """Ghi nhận một tệp đã đẩy lên, kèm phạm vi để sau tra đúng hạn giữ của nó."""
    dd = str(duong_dan or "").strip()
    if not dd:
        return
    with _khoa_so:
        so = _doc_so()
        so[dd] = {"luc": time.time(), "pham_vi": [kenh, chat, topic, user],
                  "nhat_ky": bool(nhat_ky)}
        if len(so) > _TRAN_SO:
            cu = sorted(so.items(), key=lambda kv: float(kv[1].get("luc") or 0))
            so = dict(cu[-_TRAN_SO:])
        _ghi_so_file(so)


def so_da_day() -> dict[str, dict]:
    """Toàn bộ sổ — {đường dẫn trên kho: {luc, pham_vi, nhat_ky}}."""
    with _khoa_so:
        return _doc_so()


def xoa_khoi_so(cac_duong_dan: list[str]) -> None:
    if not cac_duong_dan:
        return
    with _khoa_so:
        so = _doc_so()
        for dd in cac_duong_dan:
            so.pop(str(dd), None)
        _ghi_so_file(so)


def canh_bao_ma_hoa(kho: str) -> str:
    """Nhắc khi kho đích KHÔNG mã hoá. Chuỗi rỗng = đã mã hoá, không cần nhắc.

    Nhật ký nhóm tách phạm vi bằng khoá — đủ khi dữ liệu nằm trên máy chủ vì chỉ
    phần mềm đọc nó. Đưa lên đám mây thì tệp nằm trần: ai vào được tài khoản là
    đọc hết, tách khoá không còn nghĩa lý. Kho kiểu `crypt` của rclone mã hoá cả
    nội dung lẫn tên tệp trước khi gửi đi.
    """
    ten = str(kho or "").strip()
    if not ten:
        return ""
    try:
        from services import rclone_service as rcl
        loai = {r["name"]: r["type"] for r in rcl.remotes()}.get(ten, "")
    except Exception:
        return ""
    if loai == "crypt":
        return ""
    return ("Kho này chưa mã hoá — tệp nằm trần trên đám mây, ai vào được tài "
            "khoản là đọc được hết. Muốn các phạm vi không thấy của nhau như "
            "nhật ký thì khai thêm một kho kiểu 'crypt' bọc ngoài kho này.")
