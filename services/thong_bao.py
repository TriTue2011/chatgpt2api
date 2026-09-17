"""Sổ đăng ký THÔNG BÁO — một nơi duy nhất quyết định gửi cái gì đi đâu.

Chủ máy chốt 13/09/2026: *"gom toàn bộ các cài đặt thông báo về 1 chỗ, cài đặt
độc lập mỗi thông báo. Toàn bộ các thông báo theo cài đặt webui, không mặc
định"* và *"cài đặt thông báo ở tab cũ xóa đi tránh xung đột"*.

VÌ SAO PHẢI GOM — đo 13/09/2026, có BỐN đường gửi song song:

1. ``digest.send_targets`` với khoá ``plat:bot:chat`` — cảnh báo nhà, bài học,
   gợi ý, hiểu thiết bị, email (mỗi hộp), lịch (mỗi nguồn).
2. ``canh_bao_nha._nguoi_nhan()`` + ``_gui()`` — thang admin ba tầng. Khoá cửa
   dùng RIÊNG đường này, và tầng 3 của nó chỉ duyệt ``telegram_bots`` +
   ``zalo_bots`` nên KHÔNG BAO GIỜ sinh ra được tiền tố ``zalop_``: tin khoá
   cửa vì thế không tài nào tới Zalo cá nhân, dù chủ máy khai gì đi nữa.
3. ``notifier.notify_admin(category=…)`` — bốn rổ, cờ toàn cục + cờ theo từng
   admin, 19 file gọi tới (riêng ``account_recovery`` 31 lượt).
4. ``telegram_bot`` / ``zalo_bot`` / ``zalo_personal`` mỗi cái có
   ``notify_admin`` riêng, mang thêm một tầng cờ theo từng admin. Đo
   13/09/2026: CHỈ ``notifier`` gọi tới ba hàm đó, không nơi nào gọi thẳng —
   nên gom ở ``notifier`` là đủ, không sót đường nào.

Và xung đột không phải giả định: mọi thẻ Cài đặt đều POST NGUYÊN cả config
(``store.saveConfig`` → ``POST /api/settings``), nên thẻ nạp dữ liệu cũ ghi đè
phần của thẻ khác. Chú thích trong chính ``mqtt-card.tsx`` ghi lại một lần mất
``du_doan.kenh_nhan`` đúng theo kiểu đó.

HỢP ĐỒNG CỦA MODULE NÀY

- ``gui(khoa, tin)`` là đường DUY NHẤT để phát một thông báo.
- Chưa bật hoặc chưa chọn kênh → **KHÔNG gửi**, trả 0, ghi log nói rõ lý do.
  KHÔNG rơi về admin ngầm — đó chính là "không mặc định" chủ máy yêu cầu.
- Cấu hình nằm gọn ở ``config['thong_bao'][<khoa>] = {"bat": bool,
  "kenh": ["plat:bot:chat", …]}``. Một nơi, một chủ sở hữu.

``config.update`` gộp NÔNG (`services/config.py:1355`, deep-merge chỉ dành cho
``providers``/``custom_providers``), nên mục ``thong_bao`` bị thay nguyên khối
mỗi lần lưu. An toàn vì đúng MỘT trang sở hữu nó — và đó là lý do phải xoá ô
cài đặt ở các tab cũ thay vì để hai nơi cùng ghi.
"""
from __future__ import annotations

from typing import Any, Iterable

from services.config import config
# Dùng bộ ghi log CỦA NHÀ, không phải `logging.getLogger(__name__)`.
#
# Đo 13/09/2026 trên máy chủ thật: ứng dụng KHÔNG gọi `basicConfig`/`dictConfig`
# ở đâu cả, nên logger chuẩn propagate lên root — mà root không có handler và
# đang ở mức WARNING. Kết quả: mọi `logger.info` của module này biến mất sạch.
# Đã thử thật: gọi «Gửi thử» vào một mục đang tắt, endpoint trả đúng lý do
# nhưng log ra 0 dòng.
#
# Chuyện đó phá đúng thứ module này được dựng lên để làm: nói RÕ vì sao một
# thông báo không được gửi. `utils.log.logger` có handler riêng, mức DEBUG,
# `propagate=False`, và còn che giúp các khoá kiểu token khi in dict.
from utils.log import logger

#: Khoá cấu hình cấp cao nhất. Đo 13/09/2026: chưa có khoá nào tên `thong_bao`
#: và cũng không có khoá nào bắt đầu bằng `thong`/`notify` — không va chạm.
KHOA_CAU_HINH = "thong_bao"


class SuKien:
    """Một thông báo có thể bật/tắt và chọn kênh độc lập."""

    __slots__ = ("khoa", "nhan", "mo_ta", "nhom")

    def __init__(self, khoa: str, nhan: str, mo_ta: str, nhom: str) -> None:
        self.khoa = khoa
        self.nhan = nhan
        self.mo_ta = mo_ta
        self.nhom = nhom

    def as_dict(self) -> dict[str, str]:
        return {"khoa": self.khoa, "nhan": self.nhan,
                "mo_ta": self.mo_ta, "nhom": self.nhom}


#: Mỗi dòng = một dòng trên trang Cài đặt → Thông báo. Thêm thông báo mới thì
#: thêm ở ĐÂY, không đi khai rải rác từng module như trước.
SU_KIEN: tuple[SuKien, ...] = (
    SuKien("nha.canh_bao", "Thiết bị nhà hỏng",
           "Cảm biến mất tín hiệu, thiết bị không phản hồi.", "Nhà"),
    SuKien("nha.khoa_cua.hoi_ten", "Khoá cửa — hỏi tên người lạ",
           "Có người mở cửa bằng mã chưa đặt tên, bot hỏi đó là ai.", "Nhà"),
    SuKien("nha.khoa_cua.mo_khuya", "Khoá cửa — mở lúc khuya",
           "Cửa mở sau giờ cả nhà thường đi ngủ.", "Nhà"),
    SuKien("nha.khoa_cua.tom_tat", "Khoá cửa — tóm tắt cuối ngày",
           "Hôm nay ai ra vào lúc mấy giờ.", "Nhà"),
    SuKien("camera.nguoi_la", "Camera — người lạ",
           "Camera thấy mặt không khớp ai đã dạy (kèm ảnh mặt).", "Nhà"),
    SuKien("camera.nguoi_quen", "Camera — người quen về",
           "Nhận ra mặt đã dạy ở camera được chọn (vd camera cửa).", "Nhà"),
    SuKien("camera.hoi_ten", "Camera — hỏi tên mặt lạ hay gặp",
           "Một mặt lạ xuất hiện nhiều lần, bot gửi ảnh hỏi đó là ai.", "Nhà"),
    SuKien("camera.thay_vat", "Camera — thấy vật đã tích",
           "Thấy thứ khác người mà bạn đã tích (chó, mèo, xe máy…). "
           "Gộp theo cùng cửa sổ thời gian với lượt người.", "Nhà"),
    SuKien("nha.goi_y", "Gợi ý bật thiết bị",
           "Bot đoán nên bật gì theo nếp nhà, chờ chủ máy chấm đúng/sai.",
           "Nhà"),
    SuKien("hoc_hoi.ban_tin", "Bản tin bài học",
           "Những câu bot từng trả lời sai và đã rút kinh nghiệm.", "Học hỏi"),
    SuKien("hoc_hoi.hieu_thiet_bi", "Bot hiểu thiết bị",
           "Kết luận mới của bot về thiết bị trong nhà, chờ chấm.", "Học hỏi"),
    SuKien("he_thong.loi", "🔔 Lỗi & cảnh báo hệ thống",
           "Lỗi dịch vụ, tiến trình chết, sự cố nền tảng.", "Hệ thống"),
    SuKien("tai_khoan.log", "📋 Log tài khoản",
           "Diễn biến đăng nhập/khôi phục tài khoản provider.", "Hệ thống"),
    SuKien("tai_khoan.cap_nhat", "🔄 Cập nhật tài khoản",
           "Tài khoản được thêm, sửa, hết hạn hoặc bị gỡ.", "Hệ thống"),
    SuKien("chat.moi", "💬 Chat/nhóm mới",
           "Có người hoặc nhóm mới nhắn tới bot lần đầu.", "Hệ thống"),
)

_THEO_KHOA: dict[str, SuKien] = {s.khoa: s for s in SU_KIEN}


def _su_kien_dong() -> tuple[SuKien, ...]:
    """Dòng ĐỘNG: mỗi hộp mail, mỗi lịch một mục riêng.

    Chủ máy chốt 13/09/2026 chọn "mỗi nguồn một dòng riêng", để giữ được việc
    hộp `visaho` báo vào một nơi khác hộp chính.

    Khoá dựng từ ID BỀN của nguồn, KHÔNG theo thứ tự trong mảng. Đo
    13/09/2026: hai hộp mail ra `7823a0e2` và `af931d7e`, lịch ra `ef257920`;
    và `calendar_connector._norm_cal` ghi rõ id gắn theo URL để "state 'seen'
    không mất khi đổi thứ tự danh sách". Khoá theo thứ tự thì thêm/bớt một
    nguồn là cài đặt lặng lẽ trỏ sang nguồn khác — hỏng mà không ai thấy.

    Đọc hỏng thì trả rỗng: mất một dòng trong bảng còn hơn chết cả trang.
    """
    ra: list[SuKien] = []
    try:
        from services import email_channel
        for a in email_channel.accounts():
            ma = str(a.get("id") or "").strip()
            if ma:
                ten = str(a.get("label") or a.get("user") or ma)
                ra.append(SuKien(f"email.{ma}", f"Email — {ten}",
                                 "Tổng hợp thư mới của hộp này.", "Email & Lịch"))
    except Exception as exc:
        logger.info({"event": "thong_bao_doc_hop_mail_loi", "loi": str(exc)[:120]})
    try:
        from services import calendar_connector
        for c in calendar_connector.calendars():
            ma = str(c.get("id") or "").strip()
            if ma:
                ten = str(c.get("label") or ma)
                ra.append(SuKien(f"lich.{ma}", f"Lịch — {ten}",
                                 "Sự kiện sắp tới và nhắc trước giờ.", "Email & Lịch"))
    except Exception as exc:
        logger.info({"event": "thong_bao_doc_lich_loi", "loi": str(exc)[:120]})
    return tuple(ra)


def _tat_ca() -> tuple[SuKien, ...]:
    """Sự kiện cố định + sự kiện suy từ nguồn đang cấu hình."""
    return SU_KIEN + _su_kien_dong()


def dang_ky() -> list[dict[str, Any]]:
    """Danh sách sự kiện + cài đặt hiện tại — cho trang Cài đặt dựng bảng."""
    ra: list[dict[str, Any]] = []
    for s in _tat_ca():
        c = cai_dat(s.khoa)
        ra.append({**s.as_dict(), "bat": c["bat"], "kenh": list(c["kenh"])})
    return ra


def _muc() -> dict[str, Any]:
    raw = config.data.get(KHOA_CAU_HINH)
    return raw if isinstance(raw, dict) else {}


def cai_dat(khoa: str) -> dict[str, Any]:
    """Cài đặt của một thông báo. Chưa khai → tắt và không có kênh nào.

    Mặc định là TẮT chứ không phải bật-gửi-cho-admin: khoá lạ hoặc khoá chưa
    khai mà tự gửi đi đâu đó thì đúng là "mặc định" — thứ chủ máy vừa bỏ.
    """
    raw = _muc().get(khoa)
    if not isinstance(raw, dict):
        return {"bat": False, "kenh": []}
    kenh = raw.get("kenh")
    ds = [str(x).strip() for x in kenh if str(x).strip()] if isinstance(kenh, list) else []
    return {"bat": bool(raw.get("bat", False)), "kenh": ds}


def kenh_hoac(khoa: str, cu: Any) -> list[str]:
    """Kênh của `khoa` trong sổ đăng ký; chưa có thì trả về `cu`.

    Dùng cho email và lịch — hai chỗ mà nơi-nhận vốn nằm trong chính cấu hình
    của từng nguồn (`notify_targets`). Sau 13/09/2026 nơi-nhận thuộc về sổ đăng
    ký, nhưng vẫn phải rơi về giá trị cũ khi sổ chưa có gì, vì hai lý do:

    * Lượt chạy TRƯỚC khi `chuyen_du_lieu_mot_lan()` kịp chạy vẫn phải gửi được
      — không thì hộp mail im tiếng đúng một lần khởi động.
    * Chính bản chuyển dữ liệu đọc qua `accounts()`/`calendars()` để lấy giá
      trị cũ. Nếu hàm này trả rỗng khi sổ trống thì bản chuyển sẽ chép rỗng, tức
      tự xoá đúng thứ nó cần giữ. Rơi về `cu` làm cả hai chiều tự khớp: lúc
      chuyển thì đọc ra giá trị cũ, chuyển xong thì sổ thắng.
    """
    goc = [str(x).strip() for x in (cu or []) if str(x).strip()]
    try:
        moi = cai_dat(khoa)["kenh"]
    except Exception:
        return goc
    return list(moi) if moi else goc


def gui(khoa: str, tin: str, anh_url: str = "") -> int:
    """Phát một thông báo. Trả số kênh gửi được (0 = không gửi đi đâu cả).

    ``anh_url``: gửi kèm ảnh (vd mặt người lạ). Kênh gửi ảnh hỏng thì vẫn gửi chữ.

    Đây là đường DUY NHẤT. Không có nhánh dự phòng nào về admin: chưa chọn kênh
    thì im, và nói rõ trong log vì sao im — im lặng không lý do chính là thứ đã
    làm cảnh báo bị nuốt mất trước đây.
    """
    noi_dung = str(tin or "").strip()
    if not noi_dung:
        return 0
    # Chốt chặn khoá lạ vẫn giữ nguyên: chỉ nới cho các khoá SUY RA ĐƯỢC từ
    # nguồn đang cấu hình (`email.<id>`, `lich.<id>`), không phải nới cho mọi
    # chuỗi. Gõ sai một khoá thì vẫn không gửi đi đâu cả.
    if khoa not in _THEO_KHOA and khoa not in {s.khoa for s in _su_kien_dong()}:
        logger.warning({"event": "thong_bao_khoa_la", "khoa": khoa,
                        "ghi_chu": "khoá không có trong sổ đăng ký — không gửi"})
        return 0

    c = cai_dat(khoa)
    if not c["bat"]:
        logger.info({"event": "thong_bao_dang_tat", "khoa": khoa})
        return 0
    if not c["kenh"]:
        logger.info({"event": "thong_bao_chua_chon_kenh", "khoa": khoa,
                     "ghi_chu": "vào Cài đặt → Thông báo chọn kênh nhận"})
        return 0

    try:
        from services import digest
        n = digest.send_targets(c["kenh"], noi_dung, anh_url)
    except Exception as exc:
        logger.warning({"event": "thong_bao_gui_loi", "khoa": khoa,
                        "loi": str(exc)[:160]})
        return 0
    if n == 0:
        logger.warning({"event": "thong_bao_khong_kenh_nao_nhan", "khoa": khoa,
                        "so_kenh": len(c["kenh"])})
    return n


# ── Chuyển dữ liệu một lần ──────────────────────────────────────────────────
# Chủ máy chốt: tự điền kênh từ admin đang dùng, để KHÔNG có thông báo nào im
# đột ngột sau khi lên bản mới. Nguyên tắc: chép đúng hành vi HÔM NAY sang chỗ
# mới — cái nào đang tắt thì sang bên kia vẫn tắt.

def _khoa_kenh(nen_tang: str, bot_id: str, chat_id: str) -> str:
    """Dựng khoá ``plat:bot:chat`` bằng đúng hàm cả nhà đang dùng."""
    from services.channel_contacts import contact_key
    # `_nguoi_nhan` cũ cắt 'chat:thread' lấy phần chat; giữ nguyên nếp đó.
    return contact_key(nen_tang, bot_id, str(chat_id).split(":")[0])


def _cong_toan_cuc(nen_tang: str) -> dict[str, bool]:
    """Cờ cấp nền tảng — nằm TRÊN cờ của bot và cờ của từng admin.

    `notifier.notify_admin` hỏi `telegram_notify_enabled`/`zalo_notify_enabled`
    trước tiên (dòng 127–147), kể cả nhánh 💬. Bỏ tầng này thì bản chuyển dữ
    liệu bật lại một nền tảng chủ máy đã tắt.
    """
    c = config.data
    chung = c.get("account_log_notify_enabled", True)
    if nen_tang == "tg":
        return {"bat": bool(c.get("telegram_notify_enabled", True)),
                "log": bool(c.get("account_log_notify_telegram", chung))}
    return {"bat": bool(c.get("zalo_notify_enabled", True)),
            "log": bool(c.get("account_log_notify_zalo", chung))}


def _admin_bot(nen_tang: str, khoa_bots: str) -> list[dict[str, Any]]:
    """Mọi admin của bot đang bật, kèm cờ 🔔/📋/🔄/💬 ĐÃ tính đủ ba tầng.

    Luật chép nguyên từ `telegram_bot.notify_admin:457` và
    `zalo_bot.notify_admin:1181` — KHÔNG đoán lại:

    - 🔔 / 📋 / 🔄 : cổng bot là `notify_admin_enabled`, rồi từng dòng phải có
      `notify_enabled`.
    - 💬 : cổng bot là `newchat_alert_enabled`, và từng dòng chỉ bị loại khi
      `newchat_alert_enabled is False` — **không hỏi `notify_enabled`**. Nên
      một admin đã tắt 🔔 vẫn nhận 💬; loại nó ra là tự ý cắt thông báo.
    - 🔄 : cổng bot mở khi cờ bot bật HOẶC có bất kỳ dòng nào bật, nhưng dòng
      vẫn phải tự bật cờ của nó.
    """
    from services import admin_workspace as aw

    g = _cong_toan_cuc(nen_tang)
    ra: list[dict[str, Any]] = []
    for b in (config.data.get(khoa_bots) or []):
        if not isinstance(b, dict) or not b.get("enabled", True):
            continue
        tok = str(b.get("token") or "").strip()
        bot_id = tok.split(":", 1)[0].strip() if tok else ""
        if not bot_id:
            continue
        ds = aw.admin_entries(b)
        bot_notify = b.get("notify_admin_enabled", True) is not False
        bot_chat_moi = b.get("newchat_alert_enabled", True) is not False
        bot_log = b.get("account_log_enabled", True) is not False
        bot_cap_nhat = bool(b.get("account_update_log_enabled", False)) or any(
            e.get("account_update_log_enabled") for e in ds)
        for e in ds:
            co_notify = e.get("notify_enabled", True) is not False
            ra.append({
                "kenh": _khoa_kenh(nen_tang, bot_id, e["chat_id"]),
                "notify": g["bat"] and bot_notify and co_notify,
                "log": (g["bat"] and g["log"] and bot_notify and bot_log
                        and co_notify
                        and e.get("account_log_enabled", True) is not False),
                "cap_nhat": (g["bat"] and bot_notify and bot_cap_nhat
                             and co_notify
                             and bool(e.get("account_update_log_enabled", False))),
                # KHÔNG có `co_notify` ở đây — đúng như hai module bot.
                "chat_moi": (g["bat"] and bot_chat_moi
                             and e.get("newchat_alert_enabled") is not False),
            })
    return ra


def _admin_zalop() -> list[dict[str, Any]]:
    """Admin của Zalo cá nhân — cổng hai tầng: cờ tài khoản rồi cờ từng dòng."""
    ra: list[dict[str, Any]] = []
    raw = config.data.get("zalo_personal_account_admins")
    if not isinstance(raw, dict):
        return ra
    for own_id, entry in raw.items():
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        muc_tk = {
            "notify": entry.get("notify_admin_enabled") is not False,
            "log": entry.get("account_log_enabled") is not False,
            "cap_nhat": bool(entry.get("account_update_log_enabled")),
            "chat_moi": entry.get("newchat_alert_enabled") is not False,
        }
        dong = entry.get("admin_entries")
        dong = dong if isinstance(dong, list) else []
        if not dong:
            th = str(entry.get("admin_thread") or "").strip()
            if th:
                dong = [{"chat_id": th}]
        for x in dong:
            cid = str((x or {}).get("chat_id") or "").strip() if isinstance(x, dict) else str(x or "").strip()
            if not cid:
                continue
            ra.append({
                "kenh": _khoa_kenh("zalop", str(own_id), cid),
                # Cả HAI tầng phải bật thì hôm nay mới thật sự nhận được.
                "notify": muc_tk["notify"] and (x.get("notify_enabled", True) if isinstance(x, dict) else True),
                "log": muc_tk["log"] and (x.get("account_log_enabled", True) if isinstance(x, dict) else True),
                "cap_nhat": muc_tk["cap_nhat"] or (bool(x.get("account_update_log_enabled")) if isinstance(x, dict) else False),
                "chat_moi": muc_tk["chat_moi"] and (x.get("newchat_alert_enabled", True) if isinstance(x, dict) else True),
            })
    return ra


def _loc(ds: Iterable[dict[str, Any]], co: str) -> list[str]:
    ra: list[str] = []
    for x in ds:
        if x.get(co) and x["kenh"] not in ra:
            ra.append(x["kenh"])
    return ra


def _kenh_cu(*duong: tuple[str, ...]) -> list[str]:
    """Đọc ``kenh_nhan`` cũ theo thứ tự ưu tiên, lấy danh sách đầu tiên có."""
    for dd in duong:
        cur: Any = config.data
        for k in dd:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        if isinstance(cur, list):
            ds = [str(x).strip() for x in cur if str(x).strip()]
            if ds:
                return ds
    return []


def suy_ra_tu_cai_cu() -> dict[str, dict[str, Any]]:
    """Dựng mục ``thong_bao`` từ cấu hình đang chạy — KHÔNG ghi, chỉ trả về.

    Tách phần suy ra khỏi phần ghi để test đo được kết quả mà không đụng config
    thật, và để trang Cài đặt xem trước được trước khi bấm.
    """
    admin = (_admin_bot("tg", "telegram_bots")
             + _admin_bot("zalo", "zalo_bots")
             + _admin_zalop())
    he_thong = _loc(admin, "notify")
    log_tk = _loc(admin, "log")
    cap_nhat = _loc(admin, "cap_nhat")
    chat_moi = _loc(admin, "chat_moi")

    canh_bao = _kenh_cu(("mqtt", "canh_bao", "kenh_nhan"))
    ban_tin = _kenh_cu(("mqtt", "bai_hoc", "kenh_nhan"))
    goi_y = _kenh_cu(("mqtt", "du_doan", "kenh_nhan"),
                     ("mqtt", "bai_hoc", "kenh_nhan"))

    def _m(kenh: list[str]) -> dict[str, Any]:
        return {"bat": bool(kenh), "kenh": list(kenh)}

    # Email và Lịch: MỖI NGUỒN một dòng, chép thẳng `notify_targets` đang có.
    # Chủ máy chốt 13/09/2026 chọn "mỗi nguồn một dòng riêng" để giữ được việc
    # hộp `visaho` báo vào nơi khác hộp chính — đo cùng ngày, hộp đó đang trỏ
    # vào một kênh Zalo Bot còn hộp chính thì chưa đặt. Không chép sang thì
    # đúng cái hộp ấy im ngay khi đường gửi chuyển sang sổ đăng ký.
    nguon: dict[str, dict[str, Any]] = {}
    try:
        from services import email_channel
        for a in email_channel.accounts():
            ma = str(a.get("id") or "").strip()
            if ma:
                nguon[f"email.{ma}"] = _m(
                    [str(x) for x in (a.get("notify_targets") or []) if str(x).strip()])
    except Exception as exc:
        logger.info({"event": "thong_bao_chuyen_email_loi", "loi": str(exc)[:120]})
    try:
        from services import calendar_connector
        for c in calendar_connector.calendars():
            ma = str(c.get("id") or "").strip()
            if ma:
                nguon[f"lich.{ma}"] = _m(
                    [str(x) for x in (c.get("notify_targets") or []) if str(x).strip()])
    except Exception as exc:
        logger.info({"event": "thong_bao_chuyen_lich_loi", "loi": str(exc)[:120]})

    return {
        **nguon,
        # Đã có kênh đích danh → chép thẳng, không đụng tới.
        "nha.canh_bao": _m(canh_bao or he_thong),
        "hoc_hoi.ban_tin": _m(ban_tin or he_thong),
        "hoc_hoi.hieu_thiet_bi": _m(goi_y or he_thong),
        "nha.goi_y": _m(goi_y or he_thong),
        # Xưa nay đi ngầm qua admin → biến cái ngầm thành cái nhìn thấy được.
        "nha.khoa_cua.hoi_ten": _m(he_thong),
        "nha.khoa_cua.mo_khuya": _m(he_thong),
        "nha.khoa_cua.tom_tat": _m(he_thong),
        "he_thong.loi": _m(he_thong),
        "tai_khoan.log": _m(log_tk),
        "tai_khoan.cap_nhat": _m(cap_nhat),
        "chat.moi": _m(chat_moi),
    }


def chuyen_du_lieu_mot_lan() -> dict[str, Any]:
    """Chạy lúc khởi động. Đã có mục ``thong_bao`` thì KHÔNG đụng vào."""
    if _muc():
        return {"da_co": True, "so_muc": len(_muc())}
    suy = suy_ra_tu_cai_cu()
    config.update({KHOA_CAU_HINH: suy})
    co_kenh = sum(1 for v in suy.values() if v["kenh"])
    logger.info({"event": "thong_bao_chuyen_du_lieu", "so_muc": len(suy),
                 "co_kenh": co_kenh})
    return {"da_co": False, "so_muc": len(suy), "co_kenh": co_kenh}


def luu(muc: dict[str, Any]) -> dict[str, Any]:
    """Ghi cài đặt từ trang Cài đặt. Chỉ nhận khoá có trong sổ đăng ký."""
    sach: dict[str, Any] = {}
    hop_le = set(_THEO_KHOA) | {s.khoa for s in _su_kien_dong()}
    for khoa, v in (muc or {}).items():
        if khoa not in hop_le or not isinstance(v, dict):
            continue
        kenh = v.get("kenh")
        ds = [str(x).strip() for x in kenh if str(x).strip()] if isinstance(kenh, list) else []
        sach[khoa] = {"bat": bool(v.get("bat", False)), "kenh": ds}
    config.update({KHOA_CAU_HINH: sach})
    return {"ok": True, "so_muc": len(sach)}
