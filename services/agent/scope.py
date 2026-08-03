"""Phạm vi dữ liệu của một cuộc hội thoại — NGUỒN SỰ THẬT DUY NHẤT cho việc
"dữ liệu này thuộc về ai".

Vì sao cần: trước module này mỗi adapter tự ghép một chuỗi khoá theo cách riêng
rồi truyền nó xuống dưới cái tên `user_id`. Telegram ghép `chat#topic:u<user>`
nhưng thiếu bot_id; Zalo Bot ghép `zalo_<chat>:u<user>` cũng thiếu bot_id; Zalo
cá nhân không đưa account vào khoá. Nên mọi module phía sau — lịch sử, memory,
goals, nhắc việc, duyệt lệnh — không cách nào biết chuỗi đó là người, là nhóm
hay là topic. Hệ quả đo được trên máy chủ 03/08: 1.162 bản ghi memory nằm chung
đúng MỘT khoá.

QUY TẮC (chủ máy chốt 03/08): mặc định độc lập tuyệt đối; riêng nhóm/topic mà
KHÔNG có filter user thì các thành viên dùng chung dữ liệu của nhóm/topic đó.

    base_scope = (tenant, channel, account, chat, topic)

    chat 1-1                      → thêm actor  (riêng từng người)
    nhóm/topic có filter cho actor → thêm actor  (người đó tách riêng)
    còn lại                        → dùng base   (cả nhóm/topic dùng chung)

KHÔNG có đường lùi: đọc hay ghi mà thiếu scope thì hỏng to tiếng, không được tự
rơi về một khoá chung nào khác. Chính cái "rơi về khoá chung" là thứ đã trộn
1.162 bản ghi vào nhau.

TOPIC LUÔN THẮNG NHÓM: `Group A/Topic 1`, `Group A/Topic 2` và `Group A/General`
là ba phạm vi độc lập.

VAI TRÒ KHÔNG NẰM TRONG KHOÁ. Admin trong nhóm không có filter thì dùng chung
memory nhóm y như mọi người — nên `admin` là thuộc tính QUYỀN tra từ config, đưa
vào khoá lưu trữ sẽ thành nguồn sự thật thứ hai. Admin phải được nhận diện bằng
ID THẬT của họ (`actor_id`), không bao giờ bằng chuỗi chung "admin".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

# Topic quy ước khi kênh/nhóm không có topic. Đặt tên tường minh thay vì để rỗng
# để `Group A/General` không bao giờ trùng khoá với `Group A` (chưa biết topic).
TOPIC_CHUNG = "general"

# Tăng khi đổi CÁCH DỰNG khoá. Khoá cũ còn nguyên trong dữ liệu, nên phải đọc
# được là của thời nào — không thì migration thành đoán mò.
SCOPE_VERSION = 2

# Người gửi trong phạm vi DÙNG CHUNG (cả nhóm/topic xài chung). Ký tự '*' không
# xuất hiện trong id của Telegram/Zalo nên không thể đụng một actor_id thật.
ACTOR_CHUNG = "*"


@dataclass(frozen=True)
class Scope:
    """Một phạm vi dữ liệu. Bất biến — đem làm khoá dict/set thoải mái."""

    channel: str
    account_id: str
    chat_id: str
    topic_id: str = TOPIC_CHUNG
    actor_id: str = ACTOR_CHUNG
    tenant_id: str = "local"

    @property
    def dung_chung(self) -> bool:
        """Phạm vi này cả nhóm/topic dùng chung, hay của riêng một người?"""
        return self.actor_id == ACTOR_CHUNG

    def key(self) -> str:
        """Chuỗi khoá chuẩn để lưu/đánh index.

        Dạng: `v2:tenant:channel:account:chat#topic:actor`

        Từng thành phần được escape nên dấu ':' hay '#' nằm trong id không thể
        đẩy sang ô bên cạnh — id của Zalo cá nhân là chuỗi tự do, không phải số.
        """
        p = [_esc(self.tenant_id), _esc(self.channel), _esc(self.account_id),
             f"{_esc(self.chat_id)}#{_esc(self.topic_id)}", _esc(self.actor_id)]
        return f"v{SCOPE_VERSION}:" + ":".join(p)

    def cua_nhom(self) -> "Scope":
        """Phạm vi DÙNG CHUNG của cùng nhóm/topic này (bỏ phần người gửi).

        Dùng để tra "nhóm này có gì" khi cần, KHÔNG dùng làm đường lùi khi phạm
        vi riêng chưa có dữ liệu — rơi về nhóm là đúng cái lỗi module này sinh
        ra để chặn.
        """
        return Scope(self.channel, self.account_id, self.chat_id, self.topic_id,
                     ACTOR_CHUNG, self.tenant_id)


def _esc(x: object) -> str:
    """Escape một thành phần khoá. `safe=""` nên ':' '#' '%' đều được mã hoá."""
    return quote(str(x if x is not None else "").strip(), safe="")


def chuan_topic(topic_id: object) -> str:
    """topic_id thô → topic dùng trong khoá. Rỗng/0/None = `general`.

    Telegram chỉ gửi `message_thread_id` cho topic thật; topic "General" không
    có field này. Cùng quy ước với `capabilities.topic_suffix`.
    """
    t = str(topic_id if topic_id is not None else "").strip()
    return t if t and t != "0" else TOPIC_CHUNG


def dung_scope(channel: str, account_id: str, chat_id: str, *,
               actor_id: str, topic_id: object = None,
               chat_rieng: bool = False, co_filter_user: bool = False,
               tenant_id: str = "local") -> Scope:
    """Dựng phạm vi dữ liệu theo đúng quy tắc đã chốt.

    `chat_rieng`   : chat 1-1 (không phải nhóm) → luôn riêng từng người.
    `co_filter_user`: nhóm/topic này có khai filter RIÊNG cho chính actor này.

    Ném ValueError nếu thiếu mảnh định danh nào — thiếu scope thì hỏng to tiếng,
    không im lặng ghi vào khoá chung.
    """
    channel = str(channel or "").strip()
    account_id = str(account_id or "").strip()
    chat_id = str(chat_id or "").strip()
    actor_id = str(actor_id or "").strip()
    thieu = [t for t, v in (("channel", channel), ("account_id", account_id),
                            ("chat_id", chat_id), ("actor_id", actor_id)) if not v]
    if thieu:
        raise ValueError(
            "Thiếu %s để dựng phạm vi dữ liệu. Không có đường lùi: ghi bằng khoá "
            "thiếu định danh là trộn dữ liệu của những người khác nhau vào nhau."
            % ", ".join(thieu))
    topic = chuan_topic(topic_id)
    rieng = bool(chat_rieng) or bool(co_filter_user)
    return Scope(channel, account_id, chat_id, topic,
                 actor_id if rieng else ACTOR_CHUNG, tenant_id)


@dataclass(frozen=True)
class ScopeContext:
    """Toàn bộ định danh của MỘT tin nhắn vừa tới. Adapter dựng đúng một lần rồi
    truyền nguyên vật này đi, không ghép chuỗi ở đâu nữa.

    Hai khoá, đừng dùng lẫn:

    `data_scope_id`  — lịch sử, memory, goals, persona. Theo quy tắc đã chốt:
        nhóm/topic không có filter thì CẢ NHÓM DÙNG CHUNG một khoá.
    `principal_id`   — luôn kèm người gửi, kể cả trong nhóm dùng chung. Dành cho
        mọi thứ mang tính "của riêng người này": nút đang chờ, xin duyệt, ảnh/PDF
        họ vừa gửi, quyền xem kho media.

    Vì sao phải có `principal_id` NGAY từ bước này: quy tắc mới chuyển nhóm từ
    "mỗi người một phiên" sang "cả nhóm dùng chung". Nếu nút bấm và cổng duyệt
    cũng dùng `data_scope_id` thì trong nhóm, người B bấm "Ok" là duyệt luôn lệnh
    người A vừa tạo — tắt máy, gửi tin, phát ra loa. Chia sẻ bộ nhớ là ý muốn;
    chia sẻ quyền xác nhận hành động thì không bao giờ.
    """

    channel: str
    account_id: str
    chat_id: str
    topic_id: str
    actor_id: str
    actor_role: str
    is_private: bool
    has_explicit_user_filter: bool
    data_scope_id: str
    principal_id: str

    def khoa_yeu_cau(self, request_id: str) -> str:
        """Khoá cho một yêu cầu đang chờ cụ thể (nút bấm, xin duyệt)."""
        return f"{self.principal_id}|r={_esc(request_id)}"


def context(channel: str, account_id: str, chat_id: str, *, actor_id: str,
            topic_id: object = None, chat_rieng: bool = False,
            actor_role: str = "user", tenant_id: str = "local") -> ScopeContext:
    """Dựng `ScopeContext` cho một tin nhắn — đường DUY NHẤT mà adapter gọi."""
    co_filter = (False if chat_rieng
                 else co_filter_rieng(channel, account_id, chat_id, actor_id, topic_id))
    du_lieu = dung_scope(channel, account_id, chat_id, actor_id=actor_id,
                         topic_id=topic_id, chat_rieng=chat_rieng,
                         co_filter_user=co_filter, tenant_id=tenant_id)
    # principal: LUÔN kèm người gửi, bất kể nhóm có dùng chung hay không.
    nguoi = dung_scope(channel, account_id, chat_id, actor_id=actor_id,
                       topic_id=topic_id, chat_rieng=True, tenant_id=tenant_id)
    return ScopeContext(
        channel=du_lieu.channel, account_id=du_lieu.account_id,
        chat_id=du_lieu.chat_id, topic_id=du_lieu.topic_id,
        actor_id=str(actor_id).strip(), actor_role=str(actor_role or "user"),
        is_private=bool(chat_rieng), has_explicit_user_filter=bool(co_filter),
        data_scope_id=du_lieu.key(), principal_id=nguoi.key())


def tu_khoa_legacy(khoa: str) -> ScopeContext:
    """Bọc một khoá ĐỜI CŨ thành ScopeContext mà KHÔNG bịa ra định danh.

    Dùng cho đường chưa chuyển xong — hiện là nhắc việc chạy nền: bảng
    `reminders` mới chỉ lưu một chuỗi khoá kiểu cũ, chưa có account/topic/actor
    (đó là bước 5). Bọc như thế này giữ NGUYÊN khoá lưu trữ nên lịch đang hẹn
    vẫn bắn đúng chỗ cũ, và `channel='legacy'` nói thẳng đây là đường chưa
    chuyển thay vì giả vờ là scope v2.
    """
    k = str(khoa or "").strip()
    if not k:
        raise ValueError("Khoá legacy rỗng — không dựng được phạm vi dữ liệu.")
    return ScopeContext(channel="legacy", account_id="", chat_id=k,
                        topic_id=TOPIC_CHUNG, actor_id=k, actor_role="user",
                        is_private=True, has_explicit_user_filter=False,
                        data_scope_id=k, principal_id=k)


def co_filter_rieng(channel: str, account_id: str, chat_id: str, actor_id: str,
                    topic_id: object = None) -> bool:
    """Người này có bộ lọc RIÊNG trong nhóm/topic này không?

    Nguồn: `thread_user_filters` — CÙNG công tắc với bộ lọc chức năng (chủ máy
    chốt 03/08: dùng cái đang có, không dựng khai báo thứ hai). Hệ quả đã biết
    và đã chấp nhận: đặt bộ lọc chức năng cho một người cũng tách luôn bộ nhớ
    của họ ra khỏi nhóm, và ngược lại.

    `channel`/`account_id` phải dùng ĐÚNG bộ từ vựng của khoá lọc hiện có
    ('tg', 'zalo', 'zalop' + bot_id/account_id), không được đặt tên mới — hai bộ
    từ vựng song song là cách chắc chắn nhất để tra nhầm rồi trả về "không có
    filter" cho người thật sự có.

    Đọc config hỏng thì coi như CÓ filter (tách riêng). Đoán sai theo hướng tách
    làm dữ liệu phân mảnh — khó chịu nhưng sửa được; đoán sai theo hướng dùng
    chung là đẩy chuyện riêng của một người vào ngăn cả nhóm đọc được.
    """
    from services.agent import capabilities as caps

    try:
        return caps.user_filter_for_bot(str(channel), str(account_id), str(chat_id),
                                        str(actor_id), topic_id) is not None
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "scope: khong doc duoc thread_user_filters — coi nhu co filter (tach rieng)")
        return True


def tu_kenh(channel: str, account_id: str, chat_id: str, *, actor_id: str,
            topic_id: object = None, chat_rieng: bool = False,
            tenant_id: str = "local") -> Scope:
    """Phạm vi dữ liệu cho một tin nhắn vừa tới — đường mà ADAPTER nên gọi.

    Tự tra `thread_user_filters` để biết người này có tách riêng không, nên nơi
    gọi chỉ cần biết những thứ nó vốn đã có trong tay: kênh, bot/account, chat,
    topic, người gửi, và chat này có phải 1-1 hay không.
    """
    co = True if chat_rieng else co_filter_rieng(channel, account_id, chat_id,
                                                 actor_id, topic_id)
    return dung_scope(channel, account_id, chat_id, actor_id=actor_id,
                      topic_id=topic_id, chat_rieng=chat_rieng,
                      co_filter_user=co, tenant_id=tenant_id)


def khoa_yeu_cau(scope: Scope, actor_id: str, request_id: str) -> str:
    """Khoá cho việc ĐANG CHỜ: nút bấm, xin duyệt, chọn ảnh/PDF.

    LUÔN kèm `actor_id` kể cả khi nhóm đang dùng memory chung. Memory nhóm chung
    được, nhưng quyền XÁC NHẬN HÀNH ĐỘNG thì không: nếu không tách, người B bấm
    "Ok" là duyệt luôn lệnh của người A — tắt máy, gửi tin, phát ra loa.
    """
    a = str(actor_id or "").strip()
    if not a:
        raise ValueError("Yêu cầu đang chờ phải có actor_id — không ai được duyệt hộ.")
    return f"{scope.key()}|a={_esc(a)}|r={_esc(request_id)}"


def doc_key(key: str) -> Optional[Scope]:
    """Ngược của `Scope.key()`. Trả None nếu không phải khoá v2 (khoá đời cũ).

    Cần cho migration: phân biệt được khoá mới với đống chuỗi tự ghép đời trước
    thì mới biết bản ghi nào đã chuyển, bản ghi nào còn nằm ở vùng legacy.
    """
    from urllib.parse import unquote

    s = str(key or "")
    if not s.startswith(f"v{SCOPE_VERSION}:"):
        return None
    phan = s[len(f"v{SCOPE_VERSION}:"):].split(":")
    if len(phan) != 5:
        return None
    tenant, channel, account, chat_topic, actor = phan
    if "#" not in chat_topic:
        return None
    chat, _, topic = chat_topic.partition("#")
    return Scope(unquote(channel), unquote(account), unquote(chat),
                 unquote(topic), unquote(actor), unquote(tenant))
