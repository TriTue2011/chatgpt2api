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
        """Chat này là nhóm?

        Hai dấu hiệu, và dấu hiệu thứ hai mới là dấu hiệu tổng quát:

        * id âm — quy ước của RIÊNG Telegram;
        * khoá phiên CÓ MANG người gửi — mọi adapter chỉ gắn ':u<uid>' khi đang
          ở nhóm (xem telegram_bot.khoa_phien, zalo_bot._skey, zalo_personal).
          Chat 1-1 thì chat_id chính là người nên không adapter nào gắn thêm.

        Vì sao phải có dấu hiệu thứ hai: id nhóm Zalo KHÔNG âm (dữ liệu thật
        trên máy chủ: `zalo_zgr-7c722c7ea91e4040190f`), nên xét mỗi id âm là mọi
        nhóm Zalo bị coi là chat 1-1 và không bao giờ áp được luật chia sẻ —
        thành viên cùng nhóm không thấy dữ liệu của nhau dù chưa lọc user.

        Nhóm mà TẮT `group_user_isolation` thì khoá không mang người gửi và id
        không âm → rơi vào nhánh "không phải nhóm", tức cả nhóm chung một phạm
        vi. Đó cũng chính là điều luật chia sẻ muốn, nên không cần ngoại lệ.
        """
        return self.chat.startswith("-") or bool(self.actor)


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


# ── Kết nối bộ nhớ ───────────────────────────────────────────────────────────
# Config `memory_links`: danh sách các mối nối giữa những phạm vi ĐỘC LẬP.
#
#     [{"id": "ml_1", "kind": "binh_dang", "name": "Nhà mình",
#       "members": [{"kenh": "tg", "chat": "-100", "topic": "", "user": ""}, …]},
#      {"id": "ml_2", "kind": "chinh_phu", "name": "Bố mẹ ↔ các con",
#       "primary": [ …thành viên… ], "secondary": [ …thành viên… ]}]
#
# binh_dang — mọi thành viên đọc được của nhau (hai chiều).
# chinh_phu — CHÍNH đọc được PHỤ; PHỤ không đọc được CHÍNH (một chiều).
#
# Thành viên là bản ghi CÓ CẤU TRÚC chứ không phải chuỗi 'plat:bot:chat:user'
# như tab «Lọc thread». Chuỗi đó nhập nhằng — 'tg:b1:-100' và 'tg:-100:9' cùng
# ba phần mà phần cuối một đằng là chat, một đằng là người; tab Lọc thread gỡ
# được vì nó thử tra cả hai kiểu khoá, ở đây thì không có gì để tra.
#
# KẾT NỐI CHỈ MỞ ĐƯỜNG ĐỌC. Ghi vẫn luôn vào phạm vi của chính lượt đó: nối rồi
# gỡ mà dữ liệu đã chảy sang nhau thì không tách lại được nữa.
_KIEU_BINH_DANG = "binh_dang"
_KIEU_CHINH_PHU = "chinh_phu"


def khoa_phien_tu_thanh_vien(tv: dict) -> str:
    """Dựng lại khoá phiên từ một thành viên kết nối (nghịch của tach_khoa_phien).

    Đi vòng qua khoá phiên thay vì ghép thẳng khoá phạm vi để chỉ có MỘT nơi
    biết luật chia sẻ (`khoa_du_lieu`). Ghép thẳng là có hai nơi cùng quyết định
    "nhóm này tách theo người hay không", và hai nơi đó sẽ lệch nhau.
    """
    kenh = str(tv.get("kenh") or "").strip()
    chat = str(tv.get("chat") or "").strip()
    topic = str(tv.get("topic") or "").strip()
    user = str(tv.get("user") or "").strip()
    if not chat:
        return ""
    if kenh == "mail":
        return f"email_{chat}" if not chat.startswith("email_") else chat
    goc = f"{chat}#{topic}" if topic else chat
    if user:
        goc = f"{goc}:u{user}"
    if kenh == "zalo":
        return f"zalo_{goc}"
    if kenh == "zalop":
        return f"zalop_{goc}"
    return goc


def _khop_thanh_vien(tv: dict, sc: Scope) -> bool:
    """Thành viên này có trỏ vào lượt đang chạy không?

    Ô trống = mọi giá trị: `{kenh, chat}` không nêu topic/user thì khớp mọi
    topic và mọi người trong chat đó. Nhờ vậy nối "cả nhóm" là một dòng, không
    phải liệt kê từng người.
    """
    if str(tv.get("kenh") or "").strip() != sc.kenh:
        return False
    if str(tv.get("chat") or "").strip() != sc.chat:
        return False
    topic = str(tv.get("topic") or "").strip()
    if topic and topic != sc.topic:
        return False
    user = str(tv.get("user") or "").strip()
    return not user or user == sc.actor


def _cac_moi_noi() -> list[dict]:
    try:
        from services.config import config
        ds = config.get().get("memory_links")
    except Exception:
        return []
    return [m for m in ds if isinstance(m, dict)] if isinstance(ds, list) else []


def _thanh_vien(moi: dict, khoa: str) -> list[dict]:
    ds = moi.get(khoa)
    return [t for t in ds if isinstance(t, dict)] if isinstance(ds, list) else []


def pham_vi_doc_them(user_id: str) -> list[str]:
    """Các phạm vi mà lượt này ĐƯỢC ĐỌC THÊM nhờ kết nối bộ nhớ.

    Không gồm phạm vi của chính nó. Trả danh sách đã bỏ trùng, thứ tự ổn định
    (theo thứ tự khai trong cấu hình) để prompt không đổi giữa hai lượt giống
    nhau — prompt nhảy lung tung là hỏng cache và khó dò lỗi.

    chinh_phu MỘT CHIỀU: đứng ở CHÍNH thì đọc được PHỤ; đứng ở PHỤ thì không
    thấy gì thêm. Một lượt vừa là chính ở mối nối này vừa là phụ ở mối nối khác
    là bình thường — mỗi mối nối xét riêng.
    """
    sc = tach_khoa_phien(user_id)
    if not sc.chat:
        return []
    cua_toi = khoa_du_lieu(user_id)
    ra: list[str] = []

    def _them(ds: list[dict]) -> None:
        for tv in ds:
            kp = khoa_phien_tu_thanh_vien(tv)
            if not kp:
                continue
            k = khoa_du_lieu(kp)
            if k != cua_toi and k not in ra:
                ra.append(k)

    for moi in _cac_moi_noi():
        if not bool(moi.get("enabled", True)):
            continue
        kieu = str(moi.get("kind") or "").strip()
        if kieu == _KIEU_BINH_DANG:
            tv_ds = _thanh_vien(moi, "members")
            if any(_khop_thanh_vien(t, sc) for t in tv_ds):
                _them(tv_ds)
        elif kieu == _KIEU_CHINH_PHU:
            if any(_khop_thanh_vien(t, sc) for t in _thanh_vien(moi, "primary")):
                _them(_thanh_vien(moi, "secondary"))
    return ra


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
