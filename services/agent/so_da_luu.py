"""Sổ MỤC LỤC những thứ NGƯỜI DÙNG chủ động lưu — tìm lại theo MÔ TẢ.

Khác [[anh_cua_toi]] (ảnh AI tự tạo, lấy theo thời gian gần nhất): đây là thứ
người dùng CHỦ ĐỘNG lưu khi bấm «☁️ Lưu lên kho đám mây», kèm MÔ TẢ để sau gõ
"gửi ảnh thuốc" / "gửi tài liệu hợp đồng" tìm ra đúng cái — như mục lục một cuốn
sách: mỗi mục có nhãn để tra.

Sổ JSON theo người: ``{user_id: [ {id, ref, ref_kho, kind, mo_ta, ten, tu_khoa, ts}, … ]}``
(mới nhất trước, chặn `_MOI_NGUOI` mục mỗi người). ``kind`` = anh | tailieu |
thongtin. ``ref`` là thứ GỬI LẠI được: URL ảnh (images_dir, gateway phục vụ) cho
kind=anh; đường dẫn kho cho tài liệu. ``ref_kho`` giữ bản sao mây của ảnh (nếu
có), để vẫn gửi lại bằng URL ảnh nhưng xóa được bản gốc. Mã ``id`` làm mỗi dòng của mục lục ổn định
khi người dùng chọn nhiều dòng hoặc xóa. Mất sổ chỉ mất khả năng TRA, không mất
tệp (tệp vẫn nằm trên kho) — nên không cần bền bằng DB, JSON phẳng là đủ.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from hashlib import sha1
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MOI_NGUOI = 500          # mục lục lâu dài nên giữ nhiều hơn sổ ảnh AI
_lock = threading.RLock()

KIND_ANH = "anh"
KIND_TAILIEU = "tailieu"
KIND_THONGTIN = "thongtin"

_WORD_RE = re.compile(r"[\wÀ-ỹ]{2,}", re.UNICODE)
#: Từ đệm/hỏi bỏ khi tách khoá — giữ lại từ MANG NGHĨA ("thuốc", "hợp đồng").
_BO = {
    "gui", "cho", "toi", "minh", "anh", "chi", "em", "lai", "cai", "cua", "voi",
    "xem", "tim", "lay", "muon", "can", "do", "nay", "kia", "ay", "the", "la",
    "ve", "hinh", "anh", "tam", "tai", "lieu", "file", "tep", "thong", "tin",
    "va", "hay", "giup", "nhe", "nha", "a", "o", "di", "vao", "ra", "khong",
}


def _fold(s: str) -> str:
    b = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    k = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    return (s or "").lower().translate(str.maketrans(b, k))


def _khoa(s: str) -> list[str]:
    """Từ khoá mang nghĩa (đã bỏ dấu, bỏ từ đệm) để tra chồng khớp."""
    ra: list[str] = []
    for w in _WORD_RE.findall(str(s or "")):
        f = _fold(w)
        if f in _BO or f in ra:
            continue
        ra.append(f)
    return ra


def _duong():
    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "so_da_luu.json"


def _doc() -> dict[str, list[dict[str, Any]]]:
    try:
        p = _duong()
        if p.is_file():
            d = json.loads(p.read_text("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
    except Exception as exc:
        logger.warning("so_da_luu: đọc sổ lỗi: %s", exc)
    return {}


def _ghi_file(d: dict) -> bool:
    """Ghi nguyên tử để một lần xóa không làm hỏng cả mục lục khi máy dừng."""
    tmp: Path | None = None
    try:
        p = _duong()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
        return True
    except Exception as exc:
        logger.warning("so_da_luu: ghi sổ lỗi: %s", exc)
        return False
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _id_muc(muc: dict) -> str:
    """Mã ổn định cả cho bản ghi cũ chưa có ``id``."""
    co = str(muc.get("id") or "").strip()
    if co:
        return co
    return sha1(str(muc.get("ref") or "").encode("utf-8")).hexdigest()[:12]


def _ban_sao(muc: dict) -> dict:
    out = dict(muc)
    out["id"] = _id_muc(out)
    return out


def _danh_sach(uid: str) -> list[dict]:
    return [_ban_sao(m) for m in (_doc().get(uid) or []) if isinstance(m, dict)]


def ghi(user_id: str, *, ref: str, kind: str, mo_ta: str = "",
        ten: str = "", tu_khoa: str = "", ref_kho: str = "") -> bool:
    """Ghi một mục vào sổ của người này. Trả True nếu ghi được.

    ``ref`` là thứ gửi lại được (URL ảnh / đường dẫn kho); rỗng thì bỏ qua vì
    không tra ra để làm gì. ``tu_khoa`` là chữ bổ sung để tra (vd tên tệp gốc)."""
    uid = str(user_id or "").strip()
    r = str(ref or "").strip()
    if not uid or not r:
        return False
    muc = {
        "id": uuid.uuid4().hex[:12],
        "ref": r,
        "ref_kho": str(ref_kho or "").strip(),
        "kind": str(kind or KIND_ANH),
        "mo_ta": str(mo_ta or "").strip()[:500],
        "ten": str(ten or "").strip()[:200],
        "tu_khoa": str(tu_khoa or "").strip()[:200],
        "ts": time.time(),
    }
    with _lock:
        d = _doc()
        ds = [m for m in (d.get(uid) or []) if isinstance(m, dict)]
        # Bỏ trùng theo ref (lưu lại đúng ảnh cũ thì cập nhật, không nhân đôi).
        cu = next((m for m in ds if m.get("ref") == r), None)
        if cu:
            muc["id"] = _id_muc(cu)
            if not muc["ref_kho"]:
                muc["ref_kho"] = str(cu.get("ref_kho") or "")
        _sap_xep_muc(muc)
        ds = [m for m in ds if m.get("ref") != r]
        ds.insert(0, muc)
        d[uid] = ds[:_MOI_NGUOI]
        return _ghi_file(d)


def _diem(muc: dict, khoa: list[str]) -> int:
    """Số từ khoá truy vấn khớp trong mô tả/tên/từ-khoá của mục."""
    if not khoa:
        return 0
    kho_muc = set(_khoa(" ".join([
        str(muc.get("mo_ta") or ""), str(muc.get("ten") or ""),
        str(muc.get("tu_khoa") or ""),
    ])))
    return sum(1 for k in khoa if k in kho_muc)


def tim(user_id: str, truy_van: str, *, kind: str = "", so: int = 3) -> list[dict]:
    """Các mục KHỚP mô tả nhất (điểm > 0), mới ưu tiên khi bằng điểm.

    ``kind`` lọc loại (anh/tailieu/thongtin); rỗng = mọi loại. Trả list mục
    (ref, kind, mo_ta, ten, ts). Rỗng nếu không có gì khớp."""
    uid = str(user_id or "").strip()
    khoa = _khoa(truy_van)
    if not uid or not khoa:
        return []
    ds = _danh_sach(uid)
    if kind:
        ds = [m for m in ds if str(m.get("kind")) == kind]
    ghi_diem = [(m, _diem(m, khoa)) for m in ds]
    khop = [(m, d) for m, d in ghi_diem if d > 0]
    # Điểm cao trước; bằng điểm thì mới trước (ds vốn mới-trước nên giữ index).
    khop.sort(key=lambda md: md[1], reverse=True)
    return [m for m, _ in khop[: max(1, so)]]


def liet_ke(user_id: str, *, kind: str = "", so: int = 20) -> list[dict]:
    """Các mục gần nhất (không tra) — cho «đã lưu gì rồi»."""
    uid = str(user_id or "").strip()
    if not uid:
        return []
    ds = _danh_sach(uid)
    if kind:
        ds = [m for m in ds if str(m.get("kind")) == kind]
    return ds[: max(1, so)]


# ── Trạng thái HỎI-KHI-LƯU và CHỌN-KHI-TÌM (trong RAM, ngắn hạn) ────────────
# Chủ máy chốt: lúc lưu thì HỎI mô tả (cho bỏ qua); lúc tìm nhiều thì cho CHỌN,
# không gửi tất cả. Hai trạng thái này sống theo người, TTL ngắn; mất (restart)
# thì chỉ lỡ một lượt hỏi/chọn, không hại dữ liệu.
_CHO_TTL = 600.0
_cho_mo_ta: dict[str, dict] = {}     # user → {ref, ten, kind, ts}
_cho_chon: dict[str, dict] = {}      # user → {items:[{ref,mo_ta,kind,ten}], ts}
_cho_xoa: dict[str, dict] = {}       # user → danh sách đang chọn để xóa
_xac_nhan_xoa: dict[str, dict] = {}  # user → danh sách đã chọn, chờ gật đầu
_TOI_DA_CHON = 100
_TOI_DA_TAI_TEP = 3      # tệp tải lại mỗi lượt (mỗi tệp là một lệnh rclone)


def _tuoi_ok(rec: dict | None) -> bool:
    return bool(rec) and (time.time() - float(rec.get("ts", 0)) <= _CHO_TTL)


def dat_cho_mo_ta(user_id: str, *, ref: str, ten: str = "",
                  kind: str = KIND_ANH, ref_kho: str = "") -> None:
    """Vừa lưu một thứ, đang CHỜ người dùng nhập mô tả để ghi mục lục."""
    uid = str(user_id or "").strip()
    if uid and ref:
        with _lock:
            ghi(uid, ref=ref, ref_kho=ref_kho, ten=ten, kind=kind, tu_khoa=ten)
            _cho_mo_ta[uid] = {"ref": ref, "ref_kho": ref_kho, "ten": ten,
                                "kind": kind, "ts": time.time()}


def cau_hoi_mo_ta(kind: str = KIND_ANH) -> str:
    """Câu hỏi dùng chung sau khi lưu — ảnh và tệp không bị gọi nhầm loại."""
    if str(kind) == KIND_ANH:
        return ("📝 Anh/chị đặt TÊN/MÔ TẢ cho ảnh này để sau tìm lại nhé "
                "(ví dụ «thuốc Concor», «ảnh con trai») — gõ «thôi» nếu không cần ạ.")
    return ("📝 Anh/chị đặt TÊN/MÔ TẢ cho tệp này để sau tìm theo mục lục nhé "
            "(ví dụ «hợp đồng thuê nhà», «báo cáo tháng 9») — gõ «thôi» nếu không cần ạ.")


def gan_ref_kho(user_id: str, *, ref: str, ref_kho: str) -> bool:
    """Gắn đường dẫn kho thật vào mục ảnh đã có URL gửi lại được.

    Upload ảnh chạy nền, nên mô tả có thể được người dùng trả lời trước khi
    Drive trả kết quả. Hàm này chỉ bổ sung ``ref_kho`` và không đụng mô tả đó.
    """
    uid, r, kho = str(user_id or "").strip(), str(ref or "").strip(), str(ref_kho or "").strip()
    if not uid or not r or not _la_ref_kho(kho):
        return False
    with _lock:
        cho = _cho_mo_ta.get(uid)
        if _tuoi_ok(cho) and str(cho.get("ref") or "") == r:
            cho["ref_kho"] = kho
        d = _doc()
        ds = [m for m in (d.get(uid) or []) if isinstance(m, dict)]
        for muc in ds:
            if str(muc.get("ref") or "") == r:
                muc["ref_kho"] = kho
                _sap_xep_muc(muc)
                if _tuoi_ok(cho) and str(cho.get("ref") or "") == r:
                    cho["ref_kho"] = muc["ref_kho"]
                d[uid] = ds
                return _ghi_file(d)
    return False


def dat_cho_chon(user_id: str, items: list[dict]) -> None:
    """Tìm ra NHIỀU mục, đang CHỜ người dùng chọn một/nhiều số để gửi."""
    uid = str(user_id or "").strip()
    if uid and items:
        _cho_xoa.pop(uid, None)
        _xac_nhan_xoa.pop(uid, None)
        _cho_chon[uid] = {"items": [_ban_sao(m) for m in items][:_TOI_DA_CHON],
                           "ts": time.time()}


def dat_cho_xoa(user_id: str, items: list[dict]) -> None:
    """Hiện danh sách đã lưu, chờ người dùng chọn một/nhiều mục để xóa."""
    uid = str(user_id or "").strip()
    if uid and items:
        _cho_chon.pop(uid, None)
        _xac_nhan_xoa.pop(uid, None)
        _cho_xoa[uid] = {"items": [_ban_sao(m) for m in items][:_TOI_DA_CHON],
                          "ts": time.time()}


def _la_bo_qua(text: str) -> bool:
    return _fold(text) in {
        "thoi", "bo", "bo qua", "khong", "khong can", "huy", "thoi khoi",
        "khoi", "skip", "k", "ko",
    }


#: Câu GẬT ĐẦU cho bước xác nhận xóa. Bước này vừa in danh sách và cảnh báo
#: "không khôi phục được", nên một tiếng "đồng ý"/"xác nhận" là ý định rõ ràng —
#: bắt gõ đúng chữ «xóa» thì người dùng trả lời đúng nghĩa lại bị hủy lệnh.
_GAT_DAU_XOA = frozenset({
    "xoa", "dong y xoa", "xac nhan xoa", "ok xoa", "yes xoa",
    "dong y", "xac nhan", "dung roi", "ok", "yes",
})


def _chon_nhieu(text: str, so_muc: int) -> list[int] | None:
    """Đọc ``1,3-5`` hoặc ``tất cả``; None nghĩa là không phải câu chọn hợp lệ."""
    t = _fold(text).strip()
    if t in {"tat ca", "ca", "all"}:
        return list(range(so_muc))
    if not re.fullmatch(r"[\d\s,;\-]+", t):
        return None
    chon: list[int] = []
    for phan in re.split(r"[,;]", t):
        p = phan.strip()
        if not p:
            continue
        if "-" in p:
            a, sep, b = p.partition("-")
            if not sep or not a.strip().isdigit() or not b.strip().isdigit():
                return None
            dau, cuoi = int(a), int(b)
            if dau > cuoi:
                return None
            day = range(dau, cuoi + 1)
        elif p.isdigit():
            day = (int(p),)
        else:
            return None
        for so in day:
            i = so - 1
            if i < 0 or i >= so_muc:
                return None
            if i not in chon:
                chon.append(i)
    return chon or None


def _nhan(muc: dict, *, dai: int = 100) -> str:
    return str(muc.get("mo_ta") or muc.get("ten") or "đã lưu")[:dai]


def _la_ref_kho(ref: str) -> bool:
    """Chỉ ref rclone hợp lệ mới được phép xóa file thật.

    URL ảnh và các bản ghi cũ chỉ có tên tệp cần đối chiếu sổ upload trước.
    """
    r = str(ref or "").strip()
    return "://" not in r and bool(re.match(r"^[A-Za-z0-9_.-]{1,64}:.+", r))


def _sap_xep_muc(muc: dict) -> None:
    """Mô tả đến trước hay sau upload đều đưa bản cloud vào đúng chủ đề."""
    from services.agent import luu_tru_online as lt
    from services import rclone_service as rc

    ref = str(muc.get("ref_kho") or muc.get("ref") or "")
    if not muc.get("mo_ta") or not _la_ref_kho(ref):
        return
    ban = lt.so_da_day().get(ref) or {}
    # Chỉ sắp xếp những tệp bot đã ghi lại gốc lúc upload.
    goc = str(ban.get("thu_muc_goc") or "")
    if not goc:
        return
    cd = {"enabled": True, "kho": ref.split(":", 1)[0], "thu_muc": goc}
    ten = ref.rsplit("/", 1)[-1]
    dich = lt.duong_dan_dich(cd, ten, mo_ta=str(muc["mo_ta"])) + "/" + ten
    if dich == ref:
        return
    try:
        kq = rc.chuyen_tep(ref, dich)
    except Exception as exc:
        kq = {"ok": False, "error": str(exc)}
    if not kq.get("ok"):
        muc["loi_sap_xep"] = str(kq.get("error") or "không chuyển được thư mục")[:200]
        return
    lt.doi_duong_dan(ref, dich)
    if muc.get("ref") == ref:
        muc["ref"] = dich
    muc["ref_kho"] = dich
    muc.pop("loi_sap_xep", None)


def _tim_ref_kho(uid: str, muc: dict) -> str:
    """Bản ghi cũ: đối chiếu đúng tên và phạm vi trong sổ đã upload."""
    from services.agent import luu_tru_online as lt
    from services.agent.scope import tach_khoa_phien

    ref = str(muc.get("ref_kho") or muc.get("ref") or "")
    if _la_ref_kho(ref):
        return ref
    sc = tach_khoa_phien(uid)
    ten = str(muc.get("ten") or "")
    if not sc.chat or not ten:
        return ""
    khop = []
    for dd, ban in lt.so_da_day().items():
        pv = list(ban.get("pham_vi") or [])
        if len(pv) != 4 or pv[:3] != [sc.kenh, sc.chat, sc.topic]:
            continue
        if sc.actor and pv[3] != sc.actor:
            continue
        if dd.rsplit("/", 1)[-1] == ten:
            khop.append(dd)
    return khop[0] if len(khop) == 1 else ""


def _anh_cuc_bo(ref: str) -> str:
    from urllib.parse import unquote, urlparse
    from services.net_guard import is_self_images_url

    if is_self_images_url(ref):
        return unquote(urlparse(ref).path[len("/images/"):])
    return ""


def _don_cuc_bo(muc: dict, ban_cloud: dict, *, xoa_anh: bool = True) -> None:
    from services import rclone_service as rc

    tep = str(ban_cloud.get("tep_cuc_bo") or "")
    if tep:
        # Chỉ dọn bản upload đã ghi nhận bên trong workspace.
        path = Path(tep).resolve()
        if rc.workspace_dir().resolve() in path.parents and path.exists():
            identity = ban_cloud.get("cuc_bo_identity")
            st = path.stat()
            if not identity or identity != [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]:
                raise OSError("bản cục bộ đã thay đổi, giữ lại để tránh xóa nhầm tệp mới")
            path.unlink(missing_ok=True)
    ten = Path(str(muc.get("ten") or "")).name
    if ten and muc.get("id"):
        an_toan = re.sub(r"[^A-Za-z0-9._-]+", "_", ten)[:120] or "file.bin"
        # Cùng đường dẫn cache mà gui_lai tạo khi tải tệp đã lưu về để gửi.
        cache = rc._duong_dan_cuc_bo(f"muc_luc/{_id_muc(muc)}/{an_toan}")
        cache.unlink(missing_ok=True)
    anh = _anh_cuc_bo(str(muc.get("ref") or ""))
    if anh and xoa_anh:
        from services.image_service import delete_images
        delete_images(paths=[anh], dong_bo_cloud=False)


def _xoa_ref_kho(ref: str) -> dict:
    from services import rclone_service
    return rclone_service.xoa(ref)


def xoa_muc(user_id: str, items: list[dict], *, xoa_cuc_bo: bool = True) -> dict:
    """Xóa cloud rồi bản local; chỉ bỏ mục lục khi mọi bước thành công."""
    from services.agent import luu_tru_online as lt
    uid = str(user_id or "").strip()
    if not uid or not items:
        return {"da_xoa": [], "bo_muc_luc": [], "that_bai": []}
    chon_id = {_id_muc(m) for m in items if isinstance(m, dict)}
    da_xoa: list[dict] = []
    bo_muc_luc: list[dict] = []
    that_bai: list[dict] = []
    with _lock:
        d = _doc()
        ds = [m for m in (d.get(uid) or []) if isinstance(m, dict)]
        giu: list[dict] = []
        for muc in ds:
            if _id_muc(muc) not in chon_id:
                giu.append(muc)
                continue
            ban = _ban_sao(muc)
            ref = _tim_ref_kho(uid, ban)
            if _la_ref_kho(ref):
                ban_cloud = lt.so_da_day().get(ref) or {}
                try:
                    kq = {"ok": True} if muc.get("da_xoa_cloud") else _xoa_ref_kho(ref)
                    if kq.get("ok"):
                        muc["da_xoa_cloud"] = True
                        _don_cuc_bo(ban, ban_cloud, xoa_anh=xoa_cuc_bo)
                except Exception as exc:
                    kq = {"ok": False, "error": str(exc)}
                if kq.get("ok"):
                    lt.xoa_khoi_so([ref])
                    da_xoa.append(ban)
                else:
                    ban["loi_xoa"] = str(kq.get("error") or "không rõ")[:120]
                    that_bai.append(ban)
                    giu.append(muc)
            else:
                ban["loi_xoa"] = "chưa xác định được bản cloud; giữ mục để đối chiếu hoặc chờ upload xong"
                that_bai.append(ban)
                giu.append(muc)
        d[uid] = giu
        if not _ghi_file(d):
            # Không nói thành công nếu JSON không cập nhật được. File mây có thể
            # đã xóa thật, nên ghi log để vận hành đối chiếu thay vì thử xóa lại.
            logger.error("so_da_luu: file mây đã xóa nhưng không ghi được mục lục uid=%s", uid)
            return {"da_xoa": [], "bo_muc_luc": [],
                    "that_bai": [_ban_sao(m) for m in items]}
    return {"da_xoa": da_xoa, "bo_muc_luc": bo_muc_luc, "that_bai": that_bai}


def xoa_cloud_cua_anh(relative_path: str) -> bool:
    """Xóa thư viện local cũng phải xóa bản cloud của các mục đã lưu tương ứng."""
    with _lock:
        for uid, items in _doc().items():
            chon = [m for m in items if isinstance(m, dict)
                    and _anh_cuc_bo(str(m.get("ref") or "")) == relative_path]
            if chon and xoa_muc(uid, chon, xoa_cuc_bo=False)["that_bai"]:
                return False
    return True


def _noi_ket_qua_xoa(kq: dict) -> str:
    da_xoa = kq.get("da_xoa") or []
    bo = kq.get("bo_muc_luc") or []
    loi = kq.get("that_bai") or []
    dong: list[str] = []
    if da_xoa:
        dong.append(f"Đã xóa {len(da_xoa)} tệp khỏi kho đám mây, bản cục bộ đã lưu và mục lục ✅")
    if bo:
        dong.append(f"Đã bỏ {len(bo)} mục khỏi mục lục. Các mục này không có đường dẫn kho "
                    "đủ để xóa file gốc, nên em không nói là đã xóa tệp.")
    if loi:
        ten = ", ".join(_nhan(m, dai=40) for m in loi[:3])
        dong.append(f"Chưa xóa được {len(loi)} mục ({ten}). Em giữ nguyên chúng trong mục lục.")
        dong.extend(str(m["loi_xoa"]) for m in loi[:3] if m.get("loi_xoa"))
    return "\n".join(dong) or "Không có mục nào được xóa ạ."


def _ket_qua_gui(items: list[dict], *, tai_tep: bool = True) -> dict:
    """Dựng kết quả gửi lại; nhiều ảnh dùng ``image_urls`` cho adapter gửi loạt."""
    urls: list[str] = []
    tep: list[dict] = []
    for m in items:
        r = str(m.get("ref") or "")
        if m.get("kind") == KIND_ANH and r.startswith(("http://", "https://")):
            urls.append(r)
        else:
            # Ảnh KHÔNG có URL gửi lại được (bản ghi cũ chỉ có đường dẫn kho) đi
            # cùng đường với tài liệu: tải về rồi gửi thành tệp. Bản trước bỏ nó
            # khỏi cả hai danh sách nên mục đó biến mất khỏi câu trả lời.
            tep.append(m)
    if len(items) == 1 and len(urls) == 1:
        return {"text": f"Đây ạ — {_nhan(items[0], dai=120)} 🖼️", "image_url": urls[0]}
    dong: list[str] = []
    if urls:
        dong.append(f"Gửi {len(urls)} ảnh đã chọn ạ 🖼️")
    duong_tep: list[str] = []
    tep_loi: list[str] = []
    if tep and not tai_tep:
        dong.append("Tệp đã chọn vẫn ở kho. Zalo Bot chưa hỗ trợ gửi tệp; anh/chị "
                    "nhận qua Telegram hoặc Zalo Cá nhân giúp em ạ.")
    elif tep:
        # Tài liệu lưu bằng đường dẫn rclone có thể gửi lại thành FILE thật ở
        # Telegram/Zalo cá nhân. Không có đường dẫn kho (bản ghi cũ) thì chỉ
        # nêu đúng giới hạn, không dựng một link giả.
        # Mỗi lần tải là một lệnh rclone copyto (trần 600 giây) chạy NGAY trong
        # luồng đang xử lý tin nhắn, nên chọn "tất cả" tám tệp có thể treo lượt
        # chat rất lâu. Tải tối đa vài tệp một lượt, phần còn lại nói rõ.
        cho_sau = tep[_TOI_DA_TAI_TEP:]
        try:
            from services import rclone_service
            for m in tep[:_TOI_DA_TAI_TEP]:
                ref = str(m.get("ref_kho") or m.get("ref") or "")
                if not _la_ref_kho(ref):
                    tep_loi.append(_nhan(m, dai=50))
                    continue
                ten = Path(str(m.get("ten") or ref.rsplit("/", 1)[-1])).name
                an_toan = re.sub(r"[^A-Za-z0-9._-]+", "_", ten)[:120] or "file.bin"
                ten_luu = f"muc_luc/{_id_muc(m)}/{an_toan}"
                kq = rclone_service.tai_ve(ref, ten_luu=ten_luu)
                if kq.get("ok") and kq.get("duong_dan"):
                    duong_tep.append(str(kq["duong_dan"]))
                else:
                    tep_loi.append(_nhan(m, dai=50))
        except Exception as exc:
            logger.warning("so_da_luu: tải lại tệp lỗi: %s", str(exc)[:150])
            tep_loi.extend(_nhan(m, dai=50) for m in tep[:_TOI_DA_TAI_TEP]
                           if _nhan(m, dai=50) not in tep_loi)
        if duong_tep:
            dong.append(f"Gửi {len(duong_tep)} tệp đã chọn ạ 📄")
        if tep_loi:
            dong.append("Chưa tải lại được: " + "; ".join(tep_loi))
        if cho_sau:
            dong.append(f"Còn {len(cho_sau)} tệp nữa — anh/chị nhắn tiếp để em "
                        "gửi nốt, em gửi từng nhóm nhỏ cho khỏi nghẽn ạ.")
    out: dict[str, Any] = {"text": "\n".join(dong) or "Em chưa gửi lại được mục đã chọn ạ."}
    if urls:
        out["image_urls"] = urls
    if duong_tep:
        out["doc_paths"] = duong_tep
        if len(duong_tep) == 1:
            out["doc_path"] = duong_tep[0]
    return out


def gui_lai(items: list[dict], *, tai_tep: bool = True) -> dict:
    """Chuẩn bị ảnh/tệp đã chọn để kênh gửi lại (API công khai cho capability)."""
    return _ket_qua_gui(items, tai_tep=tai_tep)


def xu_ly_tra_loi(user_id: str, text: str) -> dict | None:
    """Câu này có phải trả lời cho bước HỎI-mô-tả / CHỌN-số của mục lục không?

    Trả None nếu không liên quan (để kênh xử lý bình thường). Ngược lại trả
    ``{"text": ..., ["image_url(s)": ...]}`` để kênh gửi — và đã dọn trạng
    thái. Xóa luôn cần hai lượt: chọn mục rồi gõ ``xóa`` xác nhận."""
    uid = str(user_id or "").strip()
    t = str(text or "").strip()
    if not uid or not t:
        return None

    # (0) Đang chờ XÁC NHẬN xóa. Gõ nhầm một câu không được biến thành xóa
    # thật, nên câu lạ chỉ được NHẮC LẠI — nhưng đúng MỘT lần. Nhắc mãi thì bản
    # chờ (10 phút) nuốt mọi câu ngắn của người dùng: `la_yeu_cau_moi` trả False
    # cho câu dưới ba từ và câu mở đầu bằng số, nên "ok", "sao vậy", "2+2 bằng
    # mấy" đều rơi vào nhánh nhắc và bot không trả lời gì khác suốt 10 phút.
    rec = _xac_nhan_xoa.get(uid)
    if _tuoi_ok(rec):
        ft = _fold(t)
        if _la_bo_qua(t):
            _xac_nhan_xoa.pop(uid, None)
            return {"text": "Đã thôi xóa, các mục vẫn giữ nguyên ạ."}
        if ft in _GAT_DAU_XOA:
            _xac_nhan_xoa.pop(uid, None)
            return {"text": _noi_ket_qua_xoa(xoa_muc(uid, rec.get("items") or []))}
        try:
            from services.yeu_cau_moi import la_yeu_cau_moi
            if la_yeu_cau_moi(t):
                _xac_nhan_xoa.pop(uid, None)
                return None
        except Exception:
            pass
        if rec.get("da_nhac"):
            # Đã nhắc rồi mà vẫn không phải xác nhận: họ đã chuyển việc khác.
            _xac_nhan_xoa.pop(uid, None)
            return None
        rec["da_nhac"] = True
        return {"text": "Để xóa các mục đã chọn, anh/chị gõ đúng «xóa»; hoặc gõ «thôi» để hủy ạ."}
    _xac_nhan_xoa.pop(uid, None)

    # (1) Đang chờ CHỌN mục để xóa.
    rec = _cho_xoa.get(uid)
    if _tuoi_ok(rec):
        if _la_bo_qua(t):
            _cho_xoa.pop(uid, None)
            return {"text": "Đã thôi chọn xóa ạ."}
        items = rec.get("items") or []
        chon = _chon_nhieu(t, len(items))
        if chon is not None:
            _cho_xoa.pop(uid, None)
            ds = [items[i] for i in chon]
            _xac_nhan_xoa[uid] = {"items": ds, "ts": time.time()}
            ten = "; ".join(_nhan(m, dai=55) for m in ds[:5])
            them = f"; … và {len(ds) - 5} mục khác" if len(ds) > 5 else ""
            return {"text": (f"Anh/chị đã chọn {len(ds)} mục: {ten}{them}.\n"
                            "Gõ «xóa» để xác nhận xóa không thể khôi phục, hoặc «thôi» để hủy ạ.")}
        _cho_xoa.pop(uid, None)

    # (2) Đang chờ CHỌN số sau khi tìm ra nhiều mục.
    rec = _cho_chon.get(uid)
    if _tuoi_ok(rec):
        if _la_bo_qua(t):
            _cho_chon.pop(uid, None)
            return {"text": "Đã thôi chọn ạ."}
        items = rec.get("items") or []
        chon = _chon_nhieu(t, len(items))
        if chon is not None:
            _cho_chon.pop(uid, None)
            return gui_lai([items[i] for i in chon], tai_tep=not uid.startswith("zalo_"))
        # Không phải số/dải số hợp lệ → thôi chờ chọn, để câu đi tiếp bình thường.
        _cho_chon.pop(uid, None)

    # (2) Đang chờ MÔ TẢ sau khi vừa lưu.
    rec = _cho_mo_ta.get(uid)
    if _tuoi_ok(rec):
        from services.yeu_cau_moi import la_yeu_cau_moi
        # Câu là yêu cầu MỚI (có động từ ra lệnh) → không phải mô tả: lưu theo tên
        # rồi để câu đi tiếp.
        if la_yeu_cau_moi(t):
            _cho_mo_ta.pop(uid, None)
            ghi(uid, ref=str(rec.get("ref")), ref_kho=str(rec.get("ref_kho") or ""),
                kind=str(rec.get("kind") or KIND_ANH), mo_ta="",
                ten=str(rec.get("ten") or ""), tu_khoa=str(rec.get("ten") or ""))
            return None
        _cho_mo_ta.pop(uid, None)
        if _la_bo_qua(t):
            ghi(uid, ref=str(rec.get("ref")), ref_kho=str(rec.get("ref_kho") or ""),
                kind=str(rec.get("kind") or KIND_ANH), mo_ta="",
                ten=str(rec.get("ten") or ""), tu_khoa=str(rec.get("ten") or ""))
            return {"text": "Vâng, em lưu rồi ạ (tìm lại theo tên tệp cũng được)."}
        ghi(uid, ref=str(rec.get("ref")), ref_kho=str(rec.get("ref_kho") or ""),
            kind=str(rec.get("kind") or KIND_ANH), mo_ta=t,
            ten=str(rec.get("ten") or ""), tu_khoa=str(rec.get("ten") or ""))
        muc = next((m for m in liet_ke(uid, so=_MOI_NGUOI)
                    if m.get("mo_ta") == t and m.get("ten") == rec.get("ten")), {})
        them = (" Chưa chuyển được thư mục trên đám mây; bản đã lưu vẫn ở vị trí cũ."
                if muc.get("loi_sap_xep") else "")
        if not them and muc.get("ref_kho"):
            them = f" Thư mục: {str(muc['ref_kho']).rsplit('/', 1)[0]}."
        goi = t.split()[0] if t.split() else "…"
        loai = "ảnh" if str(rec.get("kind") or KIND_ANH) == KIND_ANH else "tệp"
        return {"text": f"Đã ghi vào mục lục: «{t[:80]}» ✅ Sau anh/chị nhắn "
                        f"«gửi {loai} {goi}» là em tìm ra ạ.{them}"}

    return None
