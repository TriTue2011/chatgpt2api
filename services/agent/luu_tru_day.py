"""Đẩy tệp lên kho đám mây — chờ admin xác nhận, rồi chạy nền.

Hai phần:

* **Chờ xác nhận.** Tệp vừa tới thì hỏi admin "1. Lưu / 2. Luôn luôn lưu /
  3. Xoá" rồi mới làm gì. Thứ tự HỎI TRƯỚC ĐẨY SAU là bắt buộc: chủ máy chốt
  "xoá là không đẩy lên online vì không muốn lưu file cục bộ", nên không được
  có cảnh tệp đã nằm trên mây rồi mới nhận lệnh xoá.
* **Đẩy nền.** Đẩy 3 MB lên Drive mất vài giây; làm ngay trong lượt chat là bắt
  người dùng ngồi chờ. Chạy luồng riêng, hỏng thì ghi log rồi thôi — mạng chập
  hay Drive đầy không được làm gãy luồng trả lời.

Bản chờ giữ trong bộ nhớ tiến trình, có hạn: khởi động lại là mất, và mất thì
tệp cục bộ vẫn còn nguyên theo hạn giữ cũ. Không đáng dựng thêm một kho trên đĩa
chỉ để nhớ một câu hỏi đang treo.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from services.agent import luu_tru_online as lt
from utils.log import logger

# Câu hỏi treo quá lâu thì bỏ — admin đã lướt qua, đừng để nó trả lời "1" cho
# một tệp từ hôm kia.
_HAN_CHO_S = 30 * 60
_cho: dict[str, dict] = {}
_khoa = threading.RLock()

LUA_CHON = ("Lưu", "Luôn luôn lưu (khỏi hỏi lại)", "Xoá")
#: Câu lệnh gắn với từng lựa chọn. Tách hằng số vì bên nhận trả lời phải so
#: NGƯỢC lại: `ask_choices.resolve_reply` trả về chuỗi lệnh, không trả về số.
LENH = ("lưu tệp vừa nhận lên kho online",
        "luôn luôn lưu tệp của phạm vi này lên kho online",
        "xoá tệp vừa nhận, không lưu")

#: Sau khi CHUYỂN ĐỔI thì có hai tệp, nên ba lựa chọn khác hẳn lúc mới nhận —
#: chủ máy chốt 05/08: "chuyển đổi → ba lựa chọn: tệp PDF gốc, tệp đã chuyển,
#: hoặc cả hai".
LUA_CHON_CD = ("Bản đã chuyển", "Cả tệp gốc và bản đã chuyển", "Không lưu")
LENH_CD = ("lưu bản đã chuyển lên kho online",
           "lưu cả tệp gốc và bản đã chuyển lên kho online",
           "không lưu gì lên kho online")

#: Tóm tắt không sinh ra tệp thứ hai để chọn, nên chỉ CÓ/KHÔNG — chủ máy chốt
#: 05/08: "tóm tắt → chỉ hỏi có lưu tệp không".
LUA_CHON_TT = ("Lưu bản tóm tắt", "Không lưu")
LENH_TT = ("lưu bản tóm tắt lên kho online", "không lưu bản tóm tắt")

KIEU_NHAN = "nhan"            # vừa nhận tệp
KIEU_CHUYEN_DOI = "chuyen_doi"  # vừa chuyển đổi xong
KIEU_TOM_TAT = "tom_tat"        # vừa tóm tắt xong


def _bang(kieu: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if kieu == KIEU_CHUYEN_DOI:
        return LUA_CHON_CD, LENH_CD
    if kieu == KIEU_TOM_TAT:
        return LUA_CHON_TT, LENH_TT
    return LUA_CHON, LENH


def cau_hoi(ten_tep: str, *, ten_nhom: str = "") -> str:
    """Khối lựa chọn gửi cho admin. Ba lựa chọn, đánh số, bấm chọn được."""
    o = f" từ {ten_nhom}" if ten_nhom else ""
    return (f"📎 Nhận tệp {ten_tep}{o} — lưu lên kho đám mây ạ?\n"
            "<<<ASK>>>\n"
            f"{LUA_CHON[0]} | {LENH[0]}\n"
            f"{LUA_CHON[1]} | {LENH[1]}\n"
            f"{LUA_CHON[2]} | {LENH[2]}\n"
            "<<<END>>>")


def cau_hoi_chuyen_doi(ten_goc: str, ten_moi: str) -> str:
    """Khối lựa chọn sau khi chuyển đổi xong. Ba lựa chọn, đánh số."""
    return (f"📎 Đã chuyển {ten_goc} → {ten_moi}. Lưu lên kho đám mây ạ?\n"
            "<<<ASK>>>\n"
            f"{LUA_CHON_CD[0]} | {LENH_CD[0]}\n"
            f"{LUA_CHON_CD[1]} | {LENH_CD[1]}\n"
            f"{LUA_CHON_CD[2]} | {LENH_CD[2]}\n"
            "<<<END>>>")


def chuan_bi_hoi(ten_tep: str, *, ten_nhom: str = "") -> str:
    """Câu hỏi ĐÃ ĐÁNH SỐ, gửi thẳng vào thread admin được.

    Câu này gửi CHỦ ĐỘNG, không đi qua orchestrator, nên `ask_choices` không tự
    móc vào để bóc khối `<<<ASK>>>` — phải tự bóc rồi tự in danh sách số. Cố ý
    KHÔNG đặt bản chờ chip của `ask_choices`: đường nút bấm của Telegram tra
    theo khoá phiên của TỪNG NGƯỜI (`khoa_phien`), còn câu hỏi này thuộc cả
    thread, nên đặt vào đó cũng không ai đọc. Giải mã trả lời làm tại
    `chon_tu_tra_loi`, không phụ thuộc module nào.
    """
    from services.agent import ask_choices as ac
    sach, lua_chon = ac.extract(cau_hoi(ten_tep, ten_nhom=ten_nhom))
    return ac.format_numbered(sach, lua_chon)


def chuan_bi_hoi_chuyen_doi(ten_goc: str, ten_moi: str) -> str:
    """Câu hỏi sau-chuyển-đổi ĐÃ ĐÁNH SỐ, gửi thẳng vào thread admin được."""
    from services.agent import ask_choices as ac
    sach, lua_chon = ac.extract(cau_hoi_chuyen_doi(ten_goc, ten_moi))
    return ac.format_numbered(sach, lua_chon)


def chuan_bi_hoi_tom_tat(ten_goc: str) -> str:
    """Câu hỏi sau-tóm-tắt ĐÃ ĐÁNH SỐ. Chỉ hai lựa chọn."""
    from services.agent import ask_choices as ac
    khoi = (f"📝 Đã tóm tắt {ten_goc}. Lưu bản tóm tắt lên kho đám mây ạ?\n"
            "<<<ASK>>>\n"
            f"{LUA_CHON_TT[0]} | {LENH_TT[0]}\n"
            f"{LUA_CHON_TT[1]} | {LENH_TT[1]}\n"
            "<<<END>>>")
    sach, lua_chon = ac.extract(khoi)
    return ac.format_numbered(sach, lua_chon)


def chon_tu_tra_loi(khoa_admin: str, text: str) -> int:
    """Câu admin vừa nói là lựa chọn nào (1/2/3)? 0 = không phải lựa chọn.

    KHÔNG tiêu bản chờ — chỉ `tra_loi` mới tiêu. Vì cổng tag của nhóm phải tra
    được điều này TRƯỚC khi quyết định cho tin đi qua, rồi phần xử lý bên dưới
    còn phải tra lại lần nữa; tra một lần là mất thì lần thứ hai trả về 0 và câu
    trả lời của admin rơi vào hư không.

    Đòi PHẢI có tệp đang chờ trước khi xét: không thì mọi câu "1" nói trong nhóm
    admin đều bị hiểu thành lệnh lưu tệp.
    """
    t = str(text or "").strip().lower()
    ban = lay_cho(khoa_admin)
    if not t or not ban:
        return 0
    nhan_ds, lenh_ds = _bang(str(ban.get("kieu") or KIEU_NHAN))
    # Chặn theo SỐ MỤC của đúng bảng đó: lối tóm tắt chỉ có hai mục, nhận "3" là
    # nhận một lựa chọn không tồn tại rồi rơi vào nhánh nào cũng sai.
    if t.isdigit() and 1 <= int(t) <= len(nhan_ds):
        return int(t)
    for i, (nhan, lenh) in enumerate(zip(nhan_ds, lenh_ds), 1):
        if t in (nhan.lower(), lenh.lower()):
            return i
    return 0


def tach_thread_admin(khoa: str) -> tuple[str, str, str]:
    """Khoá phạm vi 'kenh:chat[#topic][:user]' → (kênh, chat, topic).

    Khoá cấp NGƯỜI vẫn trả về thread của người đó: gửi tin thì chỉ gửi được tới
    một thread, không gửi được "tới một người bên trong nhóm". Khoá cấp cả kênh
    ('zalop') không có chat → trả rỗng, caller hiểu là chưa chọn được nơi nhận.
    """
    kenh, _, con = str(khoa or "").strip().partition(":")
    if not kenh or not con:
        return "", "", ""
    chat, _, topic = con.partition("#")
    if topic:
        topic = topic.split(":", 1)[0]
    else:
        chat = chat.split(":", 1)[0]
    return kenh, chat, topic


_DUOI_ANH = ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png"),
             (b"GIF8", ".gif"), (b"RIFF", ".webp"))


def duoi_anh(du_lieu: bytes) -> str:
    """Đuôi tệp theo mấy byte đầu. Ảnh Zalo/Telegram tới không kèm tên tệp, mà
    đặt sai đuôi thì trên đám mây mở ra bằng ứng dụng sai."""
    d = bytes(du_lieu or b"")[:8]
    for dau, duoi in _DUOI_ANH:
        if d.startswith(dau):
            return duoi
    return ".jpg"


def ten_anh(du_lieu: bytes) -> str:
    """Ảnh tới không kèm tên tệp — đặt theo thời điểm nhận cho khỏi trùng."""
    return time.strftime("anh-%Y%m%d-%H%M%S") + duoi_anh(du_lieu)


def luu_vao_thu_muc_lam_viec(ten_tep: str, du_lieu: bytes) -> str:
    """Ghi tệp vừa nhận vào thư mục làm việc — nơi DUY NHẤT rclone đọc được.

    Bản gốc nằm ở /tmp với tên ngẫu nhiên do `pdf_intent` đặt, mà rclone bị khoá
    trong `workspace_dir()` (một trong ba ràng buộc an toàn của `rclone_service`),
    nên phải có bản ở đây mới gửi lên được. Giữ nguyên tên để trên đám mây nhận
    ra đúng tệp; chỉ lọc ký tự lạ và chặn thoát thư mục.
    """
    from services import rclone_service as rcl
    ten = re.sub(r"[^\w.() \-]+", "_", Path(str(ten_tep or "")).name).strip()
    if not ten:
        ten = "tep"
    d = rcl.workspace_dir() / "da_nhan"
    d.mkdir(parents=True, exist_ok=True)
    p = d / ten
    if p.exists():
        # Trùng tên khác nội dung là chuyện thường (mỗi nhóm một "bao-cao.pdf").
        # Ghi đè là mất tệp của người trước, nên thêm số.
        for i in range(1, 1000):
            q = d / f"{p.stem}-{i}{p.suffix}"
            if not q.exists():
                p = q
                break
    p.write_bytes(bytes(du_lieu or b""))
    return str(p)


def dat_cho(khoa_admin: str, *, tep: str, kenh: str, chat: str,
            topic: str = "", user: str = "", tep_2: str = "",
            kieu: str = KIEU_NHAN) -> None:
    """Ghi nhận tệp đang chờ admin trả lời.

    `tep_2` + `kieu=KIEU_CHUYEN_DOI`: lối sau-chuyển-đổi, khi đó `tep` là bản
    GỐC và `tep_2` là bản ĐÃ CHUYỂN — ba lựa chọn khác hẳn (xem `LUA_CHON_CD`).
    """
    with _khoa:
        _don_het_han()
        _cho[str(khoa_admin)] = {"tep": str(tep), "kenh": kenh, "chat": chat,
                                 "topic": topic, "user": user,
                                 "tep_2": str(tep_2 or ""), "kieu": kieu,
                                 "luc": time.time()}


def lay_cho(khoa_admin: str) -> dict:
    with _khoa:
        _don_het_han()
        return dict(_cho.get(str(khoa_admin)) or {})


def bo_cho(khoa_admin: str) -> None:
    with _khoa:
        _cho.pop(str(khoa_admin), None)


def _don_het_han() -> None:
    nay = time.time()
    for k in [k for k, v in _cho.items() if nay - float(v.get("luc") or 0) > _HAN_CHO_S]:
        _cho.pop(k, None)


def tra_loi(khoa_admin: str, chon: int) -> dict:
    """Xử lý lựa chọn của admin. chon: 1=lưu, 2=luôn luôn lưu, 3=xoá.

    Trả {ok, text} — `text` là câu báo lại cho admin.
    """
    ban = lay_cho(khoa_admin)
    if not ban:
        return {"ok": False, "text": "Không còn tệp nào đang chờ ạ."}
    bo_cho(khoa_admin)
    tep = str(ban.get("tep") or "")
    ten = Path(tep).name
    _kieu = str(ban.get("kieu") or KIEU_NHAN)
    if _kieu == KIEU_CHUYEN_DOI:
        return _tra_loi_chuyen_doi(ban, chon)
    if _kieu == KIEU_TOM_TAT:
        if chon != 1:
            _xoa_cuc_bo(tep)
            return {"ok": True, "text": "Vâng, em không lưu bản tóm tắt ạ."}
        pv = (ban["kenh"], ban["chat"], ban.get("topic") or "",
              ban.get("user") or "")
        day_nen(tep, lt.cai_dat(*pv), pham_vi=pv)
        return {"ok": True, "text": f"Đang lưu {ten} lên kho đám mây ạ."}

    if chon == 3:
        _xoa_cuc_bo(tep)
        return {"ok": True, "text": f"Đã bỏ {ten}, không lưu lên đâu cả ạ."}

    if chon == 2:
        lt.dat_luon_luon_luu(ban["kenh"], ban["chat"],
                             ban.get("topic") or "", ban.get("user") or "")

    cd = lt.cai_dat(ban["kenh"], ban["chat"], ban.get("topic") or "",
                    ban.get("user") or "")
    day_nen(tep, cd, pham_vi=(ban["kenh"], ban["chat"],
                              ban.get("topic") or "", ban.get("user") or ""))
    them = " Từ giờ phạm vi này tự lưu, khỏi hỏi lại ạ." if chon == 2 else ""
    return {"ok": True, "text": f"Đang lưu {ten} lên kho đám mây.{them}"}


def _tra_loi_chuyen_doi(ban: dict, chon: int) -> dict:
    """1 = bản đã chuyển, 2 = cả hai, 3 = không lưu gì.

    Tách hàm riêng vì ba lựa chọn ở đây KHÁC HẲN lúc mới nhận tệp: không có mục
    "luôn luôn lưu" (chuyển đổi là việc người dùng chủ động gọi từng lần), và
    "không lưu" chỉ bỏ hai bản tạm chứ không phải quyết định gì về phạm vi.
    """
    goc = str(ban.get("tep") or "")
    moi = str(ban.get("tep_2") or "")
    ten_moi = Path(moi).name
    if chon == 3:
        _xoa_cuc_bo(goc)
        _xoa_cuc_bo(moi)
        return {"ok": True, "text": "Vâng, em không lưu lên kho ạ."}

    pv = (ban["kenh"], ban["chat"], ban.get("topic") or "", ban.get("user") or "")
    cd = lt.cai_dat(*pv)
    day_nen(moi, cd, pham_vi=pv)
    if chon == 2:
        day_nen(goc, cd, pham_vi=pv)
        return {"ok": True,
                "text": f"Đang lưu cả {Path(goc).name} và {ten_moi} lên kho ạ."}
    # Chỉ lưu bản đã chuyển → bản gốc tạm ở đây không còn việc gì.
    _xoa_cuc_bo(goc)
    return {"ok": True, "text": f"Đang lưu {ten_moi} lên kho đám mây ạ."}


def moi_luu_tom_tat(kenh: str, chat: str, *, ten_goc: str, tom_tat: str,
                    topic: str = "", user: str = "", dinh_danh: str = "") -> None:
    """Vừa tóm tắt xong → hỏi admin có lưu BẢN TÓM TẮT lên kho không.

    Vì sao lưu bản tóm tắt mà không phải tệp gốc: tệp gốc đã được hỏi ngay lúc
    nhận (`moi_luu`), hỏi lại là hỏi hai lần về cùng một tệp. Bản tóm tắt mới là
    thứ vừa sinh ra và chưa ai hỏi — cũng là thứ đáng nằm trên kho, để lần sau
    tìm lại khỏi phải đọc lại cả tài liệu.
    """
    try:
        noi_dung = str(tom_tat or "").strip()
        if not noi_dung:
            return
        cd = lt.cai_dat(kenh, chat, topic, user)
        if not cd.get("enabled"):
            return
        khoa_admin = lt.thread_admin_nhan(kenh, chat, topic, user)
        k_admin, chat_admin, _ = tach_thread_admin(khoa_admin)
        if not chat_admin or k_admin != kenh:
            return
        goc = Path(str(ten_goc or "tai-lieu")).stem or "tai-lieu"
        tep = luu_vao_thu_muc_lam_viec(f"{goc}-tom-tat.md",
                                       noi_dung.encode("utf-8"))
        khoa = khoa_cho_thread(kenh, dinh_danh, chat_admin)
        dat_cho(khoa, tep=tep, kieu=KIEU_TOM_TAT,
                kenh=kenh, chat=chat, topic=topic, user=user)
        if not gui_toi_admin(khoa_admin, chuan_bi_hoi_tom_tat(ten_goc),
                             dinh_danh=dinh_danh):
            bo_cho(khoa)
            _xoa_cuc_bo(tep)
            logger.warning(f"luu_tru_online: không gửi được câu hỏi sau tóm tắt "
                           f"tới {khoa_admin} — đã bỏ bản tóm tắt")
    except Exception as exc:
        logger.warning(f"luu_tru_online: hỏi sau tóm tắt lỗi: {str(exc)[:150]}")


def moi_luu_sau_chuyen_doi(kenh: str, chat: str, *, tep_goc: str, ten_goc: str,
                           du_lieu_moi: bytes, ten_moi: str, topic: str = "",
                           user: str = "", dinh_danh: str = "") -> None:
    """Vừa chuyển đổi xong → hỏi admin lưu bản nào lên kho.

    Chủ máy chốt 05/08: "sau khi làm xong ... thì hỏi thêm có lưu online không.
    Chuyển đổi → ba lựa chọn: tệp PDF gốc, tệp đã chuyển, hoặc cả hai."

    Bản đã chuyển bị xoá ngay sau khi gửi cho người dùng, nên phải chép sang thư
    mục làm việc TRƯỚC khi hỏi — hỏi xong mới chép thì lúc admin trả lời không
    còn tệp nào.
    """
    try:
        cd = lt.cai_dat(kenh, chat, topic, user)
        if not cd.get("enabled"):
            return
        khoa_admin = lt.thread_admin_nhan(kenh, chat, topic, user)
        k_admin, chat_admin, _ = tach_thread_admin(khoa_admin)
        if not chat_admin or k_admin != kenh:
            # Cùng luật với lúc nhận tệp: chưa chọn admin (hoặc admin ở kênh
            # khác) thì không hỏi, không lưu.
            return
        moi = luu_vao_thu_muc_lam_viec(ten_moi, du_lieu_moi)
        goc = luu_vao_thu_muc_lam_viec(ten_goc, Path(tep_goc).read_bytes())
        khoa = khoa_cho_thread(kenh, dinh_danh, chat_admin)
        dat_cho(khoa, tep=goc, tep_2=moi, kieu=KIEU_CHUYEN_DOI,
                kenh=kenh, chat=chat, topic=topic, user=user)
        if not gui_toi_admin(khoa_admin,
                             chuan_bi_hoi_chuyen_doi(ten_goc, ten_moi),
                             dinh_danh=dinh_danh):
            bo_cho(khoa)
            _xoa_cuc_bo(moi)
            _xoa_cuc_bo(goc)
            logger.warning(f"luu_tru_online: không gửi được câu hỏi sau chuyển "
                           f"đổi tới {khoa_admin} — đã bỏ {ten_moi}")
    except Exception as exc:
        logger.warning(f"luu_tru_online: hỏi sau chuyển đổi {ten_moi} lỗi: "
                       f"{str(exc)[:150]}")


def _xoa_cuc_bo(tep: str) -> None:
    try:
        os.unlink(tep)
    except OSError:
        pass


def day_nen(tep: str, cd: dict, *, nhat_ky: bool = False,
            pham_vi: tuple[str, str, str, str] | None = None) -> bool:
    """Đẩy một tệp lên kho, chạy ở luồng riêng. Trả False nếu chưa bật.

    Không bao giờ ném lỗi ra ngoài: đây là việc phụ, hỏng thì chat vẫn phải chạy.
    `pham_vi` chỉ để GHI SỔ (xem `luu_tru_online.ghi_so`) — thiếu nó thì tệp vẫn
    lên mây, chỉ là phần dọn theo hạn giữ sẽ không bao giờ chạm tới nó.
    """
    if not (cd or {}).get("enabled"):
        return False
    dich = lt.duong_dan_dich(cd, Path(tep).name, nhat_ky=nhat_ky)
    if not dich:
        return False
    threading.Thread(target=_day, args=(tep, dich),
                     kwargs={"pham_vi": pham_vi, "nhat_ky": nhat_ky},
                     daemon=True).start()
    return True


def _day(tep: str, dich: str, *, pham_vi: tuple[str, str, str, str] | None = None,
         nhat_ky: bool = False) -> None:
    try:
        from services import rclone_service as rcl
        kq = rcl.gui_len(tep, dich)
        if kq.get("ok"):
            logger.info(f"luu_tru_online: đã đẩy {Path(tep).name} → {dich}")
            if pham_vi:
                lt.ghi_so(str(kq.get("duong_dan") or ""), *pham_vi, nhat_ky=nhat_ky)
        else:
            logger.warning(f"luu_tru_online: đẩy {Path(tep).name} hỏng: "
                           f"{str(kq.get('error'))[:150]}")
    except Exception as exc:
        logger.warning(f"luu_tru_online: đẩy {Path(tep).name} lỗi: {str(exc)[:150]}")


# ── Gửi câu hỏi tới thread admin ────────────────────────────────────────────

def gui_toi_admin(khoa_pham_vi: str, text: str, *, dinh_danh: str = "") -> bool:
    """Gửi một tin tới thread admin theo khoá phạm vi. Không raise.

    `dinh_danh` là account (Zalo cá nhân) hoặc bot id của kênh đang xử lý — kênh
    nào tự biết dùng nó thế nào.
    """
    kenh, chat, topic = tach_thread_admin(khoa_pham_vi)
    if not chat:
        return False
    try:
        if kenh == "tg":
            from services import telegram_bot as tg
            return bool(tg.gui_chu_dong(f"{chat}:{topic}" if topic else chat, text))
        if kenh == "zalop":
            from services import zalo_personal as zp
            return bool(zp.gui_chu_dong(chat, text, account=dinh_danh).get("ok"))
        if kenh == "zalo":
            from services import zalo_bot as zb
            return bool(zb.send_message(chat, text, rich=False).get("ok"))
    except Exception as exc:
        logger.warning(f"luu_tru_online: gửi câu hỏi tới {khoa_pham_vi} lỗi: "
                       f"{str(exc)[:150]}")
    return False


def khoa_cho_thread(kenh: str, dinh_danh: str, chat: str) -> str:
    """Khoá bản chờ của một thread. Phải khớp CHÍNH XÁC chuỗi mà kênh dựng lúc
    đọc trả lời — dựng một đằng tra một nẻo thì admin bấm số mãi không ra gì."""
    return f"{kenh}:{dinh_danh}:{chat}"


def luu_ngay(kenh: str, chat: str, *, tep: str, ten_tep: str = "",
             topic: str = "", user: str = "") -> str:
    """Đẩy một tệp lên kho NGAY, không hỏi ai. Trả câu báo lại cho người dùng.

    Dùng cho hai lối: người dùng tự chọn mục «Lưu lên kho đám mây» trong menu ý
    định, và hỏi-sau-khi-chuyển-đổi. Cả hai đều là người dùng VỪA tự quyết, nên
    hỏi admin lần nữa là hỏi lại điều vừa được trả lời.
    """
    try:
        cd = lt.cai_dat(kenh, chat, topic, user)
        if not cd.get("enabled"):
            return "Phạm vi này chưa khai kho đám mây nào ạ."
        ten = str(ten_tep or "").strip() or Path(tep).name
        cuc_bo = luu_vao_thu_muc_lam_viec(ten, Path(tep).read_bytes())
        if not day_nen(cuc_bo, cd, pham_vi=(kenh, chat, topic, user)):
            return "Chưa đẩy được lên kho, em ghi log rồi ạ."
        dich = lt.duong_dan_dich(cd, Path(cuc_bo).name)
        return f"☁️ Đang lưu {Path(cuc_bo).name} vào {dich} ạ."
    except Exception as exc:
        logger.warning(f"luu_tru_online: lưu ngay {ten_tep} lỗi: {str(exc)[:150]}")
        return "Chưa lưu được lên kho, em ghi log rồi ạ."


def moi_luu(kenh: str, chat: str, *, ten_tep: str, du_lieu: bytes,
            topic: str = "", user: str = "", ten_nhom: str = "",
            dinh_danh: str = "") -> None:
    """Tệp vừa nhận: hỏi admin rồi đẩy — hoặc đẩy luôn nếu phạm vi đã chốt.

    Không raise: đây là việc PHỤ đi kèm luồng nhận tệp; hỏng thì menu ý định và
    đường nạp RAG vẫn phải chạy như thường.
    """
    try:
        cd = lt.cai_dat(kenh, chat, topic, user)
        if not cd.get("enabled"):
            return
        khoa_admin = ""
        chat_admin = ""
        if cd.get("hoi_truoc"):
            khoa_admin = lt.thread_admin_nhan(kenh, chat, topic, user)
            k_admin, chat_admin, _ = tach_thread_admin(khoa_admin)
            if not chat_admin:
                logger.info(f"luu_tru_online: {kenh}:{chat} bật lưu nhưng chưa chọn "
                            f"thread admin — không hỏi, không lưu {ten_tep}")
                return
            if k_admin != kenh:
                # Gửi được sang kênh khác, nhưng trả lời thì tra không ra: bản
                # chờ khoá theo kênh+định danh của kênh NHẬN tệp. Nói thẳng ra
                # log còn hơn để admin bấm "1" mà không có gì xảy ra.
                logger.warning(f"luu_tru_online: thread admin {khoa_admin} khác kênh "
                               f"{kenh} — chưa hỗ trợ trả lời chéo kênh, "
                               f"bỏ qua {ten_tep}")
                return
        tep = luu_vao_thu_muc_lam_viec(ten_tep, du_lieu)
        if not cd.get("hoi_truoc"):
            day_nen(tep, cd, pham_vi=(kenh, chat, topic, user))
            return
        khoa = khoa_cho_thread(kenh, dinh_danh, chat_admin)
        dat_cho(khoa, tep=tep, kenh=kenh, chat=chat, topic=topic, user=user)
        if not gui_toi_admin(khoa_admin, chuan_bi_hoi(ten_tep, ten_nhom=ten_nhom),
                             dinh_danh=dinh_danh):
            # Câu hỏi không tới được admin thì không ai trả lời được nó. Dọn
            # luôn: để lại là một bản chờ chết kèm một tệp nằm mãi trong thư mục
            # làm việc, mà không có gì trên màn hình cho thấy điều đó.
            bo_cho(khoa)
            _xoa_cuc_bo(tep)
            logger.warning(f"luu_tru_online: không gửi được câu hỏi tới "
                           f"{khoa_admin} — đã bỏ {ten_tep}, không lưu")
    except Exception as exc:
        logger.warning(f"luu_tru_online: mời lưu {ten_tep} lỗi: {str(exc)[:150]}")
