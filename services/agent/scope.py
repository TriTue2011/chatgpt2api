"""Phạm vi dữ liệu — ai được thấy dữ liệu nào.

Quy tắc chốt 03/08 (chủ máy):

* MẶC ĐỊNH ĐỘC LẬP TUYỆT ĐỐI — mỗi kênh / tài khoản bot / chat / topic / người
  dùng là một phạm vi riêng, không thấy dữ liệu của nhau.
* NGOẠI LỆ DUY NHẤT — nhóm (hoặc topic) KHÔNG có bộ lọc user nào thì các thành
  viên DÙNG CHUNG dữ liệu của nhóm/topic đó. "Trong topic ai nhắn cũng được" thì
  cũng phải "ai đọc cũng được", kẻo mỗi thành viên nói với một trợ lý khác nhau.
* TOPIC LUÔN THẮNG NHÓM — có topic thì phạm vi tính theo topic.

Vì sao module này CHỈ ĐỌC khoá phiên chứ không thay nó
-----------------------------------------------------
Lần làm trước (4 commit, đã revert ở `e68ecba`) thay chuỗi `user_id` mà
`orchestrate()` truyền xuống bằng một khoá "v2" mới. Nó gãy vì nhiều nơi phía
dưới PHÂN TÍCH chuỗi đó theo định dạng cũ — `capabilities._channel_of`,
`reminders.channel_of` — nên Zalo bị nhận thành Telegram, nhắc việc mới lưu sai
nơi nhận, và memory tắt hẳn trên đường bot. 37 test lúc đó đều xanh vì chúng chỉ
khoá tầng quy tắc, không chạm chỗ ghép tầng.

Lần này khoá phiên giữ NGUYÊN hình dạng (`zalo_123:u456`, `-100#7:u9`, …) nên mọi
nơi đang phân tích nó vẫn đúng; phạm vi được SUY RA từ khoá đó. Thêm việc, không
đổi việc đang chạy.

Hình dạng khoá phiên các adapter đang sinh (đừng đổi, chỉ đọc):

    Telegram   <chat>[#<topic>][:u<uid>]        telegram_bot.py
    Zalo Bot   zalo_<chat>[:u<uid>]             zalo_bot.py
    Zalo CN    zalop_<thread>[:u<uid>]          zalo_personal.py
    Email      email_<local>_<hash>             email_channel.py
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import quote

_TIEN_TO_KENH = (("zalop_", "zalop"), ("zalo_", "zalo"), ("email_", "mail"))
_UID_RE = re.compile(r":u(?P<uid>[^:]+)$")


@dataclass(frozen=True)
class Scope:
    """Các thành phần của một phạm vi, tách từ khoá phiên."""

    kenh: str = ""       # tg | zalo | zalop | mail | ""
    chat: str = ""       # chat/thread id (Telegram nhóm là id âm)
    topic: str = ""      # chỉ Telegram; topic thắng nhóm
    actor: str = ""      # người gửi, khi khoá phiên có mang

    @property
    def la_nhom(self) -> bool:
        """Chat này là nhóm? Chỉ Telegram phân biệt được từ chính id (âm)."""
        return self.chat.startswith("-")


def tach_khoa_phien(user_id: str) -> Scope:
    """Tách khoá phiên orchestrator thành các thành phần phạm vi.

    KHÔNG suy diễn gì thêm — chỉ đọc đúng những gì adapter đã ghi vào khoá.
    """
    raw = str(user_id or "").strip()
    if not raw:
        return Scope()
    kenh = "tg"
    for tien_to, ten in _TIEN_TO_KENH:
        if raw.startswith(tien_to):
            kenh = ten
            raw = raw[len(tien_to):]
            break
    actor = ""
    m = _UID_RE.search(raw)
    if m:
        actor = m.group("uid")
        raw = raw[: m.start()]
    chat, _, topic = raw.partition("#")
    if kenh == "mail":
        # Email: khoá đã là băm địa chỉ người gửi → chính nó là chủ thể.
        return Scope(kenh="mail", chat=chat, actor=chat)
    return Scope(kenh=kenh, chat=chat, topic=topic, actor=actor)


def _co_loc_user(sc: Scope) -> bool:
    """Nhóm/topic này có BẤT KỲ bộ lọc user nào chưa?

    Đây là công tắc chia sẻ: có lọc user = chủ máy đã phân biệt người trong
    nhóm → dữ liệu tách theo người. Chưa lọc = nhóm dùng chung.

    Khoá `thread_user_filters` theo `capabilities.user_filter_for_bot`:
    'plat:bot:chat[#topic]:user' hoặc 'plat:chat[#topic]:user'. Ở đây chỉ cần
    biết CÓ hay KHÔNG một bản ghi nào, nên nhận cả hai dạng bằng cách đòi khoá
    mở đầu bằng đúng kênh VÀ chứa ':<chat>[#topic]:' — hai dấu hai chấm bao
    quanh là thứ chặn 'tg:-1009:5' bị tính cho chat '-100'.

    Bản ghi của TOPIC không làm nhóm tách, và ngược lại: ':-100:' không khớp
    'tg:-100#7:9'. Đúng quy tắc topic thắng nhóm — hai phạm vi khác nhau.
    """
    if not sc.chat:
        return False
    try:
        from services.config import config
        filters = config.get().get("thread_user_filters")
    except Exception:
        return False
    if not isinstance(filters, dict) or not filters:
        return False
    dich = f":{sc.chat}#{sc.topic}:" if sc.topic else f":{sc.chat}:"
    dau = f"{sc.kenh}:"
    return any(str(k).startswith(dau) and dich in str(k) for k in filters)


def khoa_du_lieu(user_id: str) -> str:
    """Khoá phạm vi dữ liệu (wiki / digest / lịch / ghi chú) cho một lượt.

    Trả chuỗi ổn định, đọc được, mỗi thành phần đã escape để không có thành
    phần nào chứa dấu phân cách và trộn được sang phạm vi khác:

        v1|tg|-100|7|u9      nhóm -100 topic 7, tách theo người (có lọc user)
        v1|tg|-100|7|        nhóm -100 topic 7, thành viên dùng chung
        v1|zalo|123||u456    Zalo 1-1 (chat 1-1 luôn tách theo người)
        v1|||                không rõ nguồn → phạm vi mặc định

    Chat 1-1 luôn tách theo người vì chat id CHÍNH LÀ người đó. Nhóm/topic thì
    theo công tắc `_co_loc_user`.
    """
    sc = tach_khoa_phien(user_id)
    if not sc.chat:
        return "v1|||"
    actor = sc.actor
    if sc.la_nhom and not _co_loc_user(sc):
        actor = ""      # nhóm/topic chưa lọc user → thành viên dùng chung
    phan = [sc.kenh, sc.chat, sc.topic, actor]
    return "v1|" + "|".join(quote(p, safe="") for p in phan)


def bam_pham_vi(khoa: str) -> str:
    """Băm ngắn của MỘT KHOÁ phạm vi — dùng làm tên file / thư mục.

    Phải băm chứ không được "làm sạch" khoá: bản nháp trước bỏ dấu phân cách
    trong tên file nên `a.b@example.com` và `ab@example.com` ra cùng một file —
    đúng nghĩa rò dữ liệu giữa hai người.
    """
    return hashlib.sha256(str(khoa or "").encode("utf-8")).hexdigest()[:16]


def ma_pham_vi(user_id: str) -> str:
    """Băm phạm vi của một khoá phiên (tiện lối gọi một bước)."""
    return bam_pham_vi(khoa_du_lieu(user_id))
