"""Agent orchestrator — the supervised, capability-aware conversation loop.

Flow per user message:
  1. Resolve a pending approval first (the user is confirming/denying a change
     the agent proposed last turn).
  2. Build the tiered system prompt (persona + memory + user profile + granted
     permissions) — this is what makes the bot "know who it is, what it can do,
     what it's allowed, and what it remembers".
  3. Run the agentic loop: call the main model with the native capability tools.
     - READ capability  → execute, feed the result back, keep going.
     - CHANGE capability → if pre-approved ("always") execute; otherwise PROPOSE
       it and stop, waiting for the user to approve.
     - plain text       → that's the reply.
  4. Errors are reported to the user, never silently retried in a loop.

Returns ``{"text": str, "image_url": Optional[str]}``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Optional

from services.config import config
import re as _re_mod

from services.agent import state
from services.agent import session as sess
from services.agent import compaction as compact
from services.agent import ask_choices
from services.agent import skills as agent_skills
from services.agent import workflows as agent_workflows
from services.agent import capabilities as caps
from services.agent import tool_compress
from services.agent import approval_gate
from services.agent import super_context
from services.agent import goals as agent_goals
from services.agent import model_hints
from services.agent import run_journal
from services.agent.runtime import call_model, content_of

logger = logging.getLogger(__name__)

_MAX_STEPS = 4

# ── Đường tắt "lấy media đã tạo trong thư viện" ──────────────────────────────
#
# Vì sao KHÔNG để model tự gọi tool: đo thật 31/07 trên Zalo cá nhân, "Gửi anh
# video mới nhất trong thư viện video" và "Gửi anh 3 ảnh mới nhất trong thư viện
# ảnh" đều chỉ nhận lại lời hứa. Tool `library_media` CÓ trong danh sách 43 tool
# và nhóm 'image' được phép — model chính của luồng này (combo "AI text", model
# đầu là oc/deepseek-v4-flash-free) đơn giản là không gọi tool. Nhắc thêm một
# lượt cũng chỉ ra lời hứa thứ hai.
#
# Câu này hoàn toàn xác định (lấy gì, mấy cái, ở đâu) nên không cần model quyết.
# Cùng bộ từ vựng với services/search_service (_DAU_HIEU_KHO_NHA / _TU_CHI_MEDIA)
# để hai nơi hiểu câu giống nhau.
_TAT_XIN_MEDIA = re.compile(
    r"(gửi|gưi|lấy|lay|cho|xem|đưa|dua|show)\b", re.I)
_TAT_KHO = ("thư viện", "thu vien", "trong kho", "vừa tạo", "đã tạo", "vừa vẽ",
            "đã vẽ", "gửi lại", "xem lại", "vừa rồi", "gần nhất", "mới nhất",
            "moi nhat", "gan nhat")
_TAT_LOAI = ((("video", "clip", "phim"), "video"),
             (("nhạc", "nhac", "bài hát", "bai hat", "audio"), "music"),
             (("ảnh", "anh", "hình", "hinh", "photo"), "image"))
_TAT_SO = re.compile(r"\b(\d{1,2})\s*(?:tấm|tam|cái|cai|bức|buc|)\s*"
                     r"(?:ảnh|anh|hình|hinh|video|clip)?", re.I)
# PHẠM VI: "của TÔI tạo" ≠ "trong THƯ VIỆN" (cả kho). Chủ máy chốt 31/07:
# admin xin "thư viện" là kho chung; còn "anh tạo / của tôi" là sổ riêng.
# User thường thì kiểu gì cũng chỉ được sổ riêng (ép ở handler, không phải ở đây).
_TAT_CUA_TOI = ("tôi tạo", "toi tao", "anh tạo", "anh tao", "chị tạo", "chi tao",
                "mình tạo", "minh tao", "của tôi", "cua toi", "của anh", "cua anh",
                "của chị", "cua chi", "của mình", "cua minh", "do tôi", "do anh")
_TAT_CA_KHO = ("thư viện", "thu vien", "trong kho", "tất cả", "tat ca",
               "mọi người", "moi nguoi", "bất kỳ", "bat ky")


def _tat_lay_media(text: str) -> dict | None:
    """Nhận câu xin media ĐÃ TẠO trong thư viện → {"kind", "so_luong", "scope"},
    hoặc None.

    Đòi ĐỦ ba dấu hiệu để khỏi bắt oan: động từ xin + dấu hiệu kho nhà + từ chỉ
    loại media. Nhờ vậy "vẽ cho anh con mèo" hay "tìm ảnh Hà Nội trên mạng"
    không lọt vào đây.
    """
    t = (text or "").strip().lower()
    if not t or len(t) > 200:
        return None
    if not _TAT_XIN_MEDIA.search(t):
        return None
    if not any(k in t for k in _TAT_KHO):
        return None
    for tu, kind in _TAT_LOAI:
        if any(x in t for x in tu):
            ra: dict[str, Any] = {"kind": kind}
            m = _TAT_SO.search(t)
            if m and kind == "image":
                try:
                    ra["so_luong"] = max(1, min(50, int(m.group(1))))
                except ValueError:
                    pass
            if any(k in t for k in _TAT_CUA_TOI):
                ra["scope"] = "mine"
            elif any(k in t for k in _TAT_CA_KHO):
                ra["scope"] = "all"
            return ra
    return None


# Câu hỏi TIN TỨC / thời sự — đủ rõ để GỌI THẲNG web_search, không để model
# phân vân rồi hỏi lại. Đo thật 31/07: model (kể cả gpt-oss) cứ hỏi "muốn bản
# tin dạng nào ạ?" cho "tin tức hôm nay" dù đã sửa mô tả + workflow; nudge prompt
# không thắng được. Đường tắt xác định như _tat_lay_media là cách chắc ăn.
_TAT_TIN_TUC = re.compile(
    r"\b(tin tức|tin tuc|bản tin|ban tin|thời sự|thoi su|tin nóng|tin nong|"
    r"tin mới|tin moi)\b", re.I)


# Mốc thời gian trong câu tin tức. MCP vn_news lấy qua RSS nên CHỈ có tin MỚI
# NHẤT — không lọc được theo ngày. Vì vậy:
#   • "tin tức hôm nay / mới nhất / (không nêu ngày)" → MCP get_news (tổng hợp
#     VnExpress, Tuổi Trẻ, Thanh Niên, Dân Trí, BBC, Google News — nhiều báo).
#   • "hôm qua", "ngày 15/3", "tuần trước"… → web_search (MCP không làm được).
_TIN_NGAY_KHAC = re.compile(
    r"(hôm qua|hom qua|hôm kia|hom kia|tuần trước|tuan truoc|tháng trước|"
    r"thang truoc|năm ngoái|nam ngoai|ngày\s*\d{1,2}|\d{1,2}[/-]\d{1,2})", re.I)


def _la_yeu_cau_tin_tuc(text: str) -> str | None:
    """Câu xin TIN TỨC tổng hợp → 'moi' (tin mới, dùng MCP) | 'ngay' (ngày khác,
    dùng web_search) | None (không phải xin bản tin).

    Chỉ bắt câu NGẮN — câu dài (hỏi chi tiết một vụ việc) để model tự lo."""
    t = (text or "").strip()
    if len(t) > 40:            # câu dài = hỏi cụ thể, không phải xin bản tin chung
        return None
    if not _TAT_TIN_TUC.search(t):
        return None
    return "ngay" if _TIN_NGAY_KHAC.search(t) else "moi"


# ── Đường tắt TẠO ẢNH / TẠO VIDEO ────────────────────────────────────────────
#
# Menu chọn model chỉ là GHÉP CHUỖI từ danh sách model đã cache — gần như tức
# thì. Nhưng để tới được nó, mỗi câu phải đi qua một lượt gọi model định tuyến.
# Đo thật 01–02/08 trên máy chủ: bước hiện menu mất 6–14 giây (ảnh 9,2 · 12,0 ·
# 11,8 · 13,5s; video 6 · 7 · 13 · 14s), trong khi một câu "xin chào" KHÔNG dùng
# tool nào cũng mất 11,2s — tức toàn bộ thời gian là độ trễ của model, không phải
# của việc dựng menu. Đường tắt này nhận ý bằng TỪ KHOÁ rồi gọi thẳng capability,
# nên menu ra ngay.
_TAT_TAO_MEDIA = re.compile(
    r"^\s*(?:ơi\s+|em\s+|bot\s+|bạn\s+|ban\s+)?"
    r"(?:hãy\s+|hay\s+|giúp\s+\S+\s+|giup\s+\S+\s+|cho\s+\S+\s+)?"
    r"(?P<verb>tạo|tao|vẽ|ve|sinh|generate|draw|make)\s+"
    r"(?:cho\s+\S+\s+)?"
    r"(?:(?:một|mot|1|vài|vai|\d+)\s+)?"
    r"(?P<loai>video|clip|ảnh|anh|hình\s*ảnh|hinh\s*anh|hình|hinh|image|picture|photo)"
    r"(?![a-zà-ỹ])"
    r"(?P<con_lai>.*)$",
    re.IGNORECASE | re.DOTALL)

# Câu KHÔNG phải "tạo mới" dù có chữ tạo/ảnh/video:
#   · "… bằng model flow/…" / "params duration=6" — chính là nội dung nút bấm của
#     MENU. Để nó đi đường tắt là hiện lại menu → lặp vô tận.
#   · nói về media ĐÃ CÓ ("ảnh vừa tạo", "video vừa rồi", "gửi lại", "tải")
#     — đường tắt thư viện (mục 1.4) lo, đừng giành.
_KHONG_PHAI_TAO_MOI = re.compile(
    r"(bằng\s+model|bang\s+model|params\s|vừa\s+(tạo|rồi|xong)|vua\s+(tao|roi|xong)|"
    r"gửi\s+lại|gui\s+lai|tải\s+(về|lại)|tai\s+(ve|lai)|model\s+gì|model\s+gi|"
    r"xoá|xóa|xoa\b|thùng\s+rác|thung\s+rac)", re.I)


# "vẽ <bất kỳ>" — KHÔNG cần chữ "ảnh". "vẽ một cô gái mặc áo dài" là xin ảnh, rõ
# như "tạo ảnh cô gái". Chỉ nhận `vẽ` có dấu và `draw`: bỏ dấu thành "ve" thì đụng
# từ khác ("ve", "vệ sinh" gõ thiếu dấu), mà dạng không dấu vẫn vào được qua
# _TAT_TAO_MEDIA nếu có chữ loại ("ve anh con meo").
_TAT_VE_ANH = re.compile(
    r"^\s*(?:ơi\s+|em\s+|bot\s+|bạn\s+)?"
    r"(?:hãy\s+|giúp\s+\S+\s+|cho\s+\S+\s+)?"
    r"(?:vẽ|draw)\s+(?P<con_lai>\S.*)$",
    re.IGNORECASE | re.DOTALL)

# Chữ mở đầu phần mô tả cần bỏ ("tạo video VỀ mưa rơi" → "mưa rơi").
_BO_DAU_MO_TA = re.compile(
    r"^\s*(?::|-|–|về|ve\b|là|la\b|với|voi\b|nội\s*dung|noi\s*dung)\s*", re.I)


def _la_yeu_cau_tao_media(text: str) -> tuple[str, str] | None:
    """('video'|'image', prompt) nếu câu là yêu cầu TẠO MỚI ảnh/video, None nếu không.

    `prompt` là phần còn lại sau động từ + loại, đã bỏ dấu hai chấm/"về"/"là" mở
    đầu. Rỗng cũng hợp lệ ("tạo video") — capability tự hỏi lại muốn tạo gì.
    """
    t = (text or "").strip()
    if not t or _KHONG_PHAI_TAO_MOI.search(t):
        return None
    m = _TAT_TAO_MEDIA.match(t)
    if m:
        loai = m.group("loai").lower()
        kind = "video" if loai in {"video", "clip"} else "image"
        return kind, _BO_DAU_MO_TA.sub("", m.group("con_lai").strip()).strip()
    m = _TAT_VE_ANH.match(t)
    if m:
        return "image", _BO_DAU_MO_TA.sub("", m.group("con_lai").strip()).strip()
    return None


# ── Đường tắt cho NỘI DUNG NÚT BẤM của menu ──────────────────────────────────
#
# Chuỗi này do CHÍNH code sinh ra (_ask_video_provider / _ask_video_thoi_luong /
# _ask_video_so_luong / _param_choice_menu) nên phân tích được chắc chắn, không
# phải đoán như câu người gõ. Bắt được nó thì hai bước sau — chọn thời lượng và
# chọn số lượng — cũng ra tức thì, thay vì mỗi bước một lượt gọi model ~10 giây.
#
# Hai khuôn:
#   A) "<việc> bằng model <id>[ params k=v k=v]: <mô tả>"      (menu model/thời
#      lượng/số lượng — mô tả nằm SAU dấu hai chấm)
#   B) "<việc> '<mô tả>' bằng model <id> params k=v k=v"       (_param_choice_menu
#      — mô tả nằm TRONG dấu nháy, params ở cuối, KHÔNG có dấu hai chấm)
#
# "bằng mặc định" CỐ Ý không bắt: `_h_generate_video` chỉ dùng model mặc định của
# nhánh khi ctx có auto_approve, mà bật cờ đó ở đây sẽ bỏ luôn các bước hỏi thời
# lượng/số lượng — đổi hành vi. Để nó đi đường model như cũ, đó là lựa chọn ít gặp.
_NUT_MENU_A = re.compile(
    r"^\s*(?P<viec>tạo\s+video|tạo\s+ảnh|tao\s+anh|vẽ|ve)\s+"
    r"bằng\s+model\s+(?P<model>\S+?)"
    r"(?:\s+params\s+(?P<params>[^:]*?))?\s*:\s*(?P<prompt>.*)$",
    re.IGNORECASE | re.DOTALL)
_NUT_MENU_B = re.compile(
    r"^\s*(?P<viec>tạo\s+video|tạo\s+ảnh|tao\s+anh|vẽ|ve)\s+"
    r"'(?P<prompt>.*)'\s+bằng\s+model\s+(?P<model>\S+)"
    r"(?:\s+params\s+(?P<params>.*))?$",
    re.IGNORECASE | re.DOTALL)


def _doc_nut_menu_media(text: str) -> tuple[str, dict] | None:
    """('video'|'image', args cho capability) nếu câu là nội dung nút bấm của menu.

    `args` gồm prompt, model và (nếu có) params đã tách thành dict — đúng dạng
    `_h_generate_video`/`_h_generate_image` nhận.
    """
    t = (text or "").strip()
    if not t or "bằng model" not in t.lower():
        return None
    m = _NUT_MENU_A.match(t) or _NUT_MENU_B.match(t)
    if not m:
        return None
    viec = re.sub(r"\s+", " ", m.group("viec").strip().lower())
    kind = "video" if viec == "tạo video" else "image"
    args: dict = {"prompt": m.group("prompt").strip().strip("'").strip(),
                  "model": m.group("model").strip().rstrip(":")}
    tho = (m.groupdict().get("params") or "").strip()
    if tho:
        params: dict = {}
        for cap in tho.split():
            if "=" in cap:
                k, _, v = cap.partition("=")
                k, v = k.strip(), v.strip()
                if k and v:
                    params[k] = v
        if params:
            args["params"] = params
    return kind, args


# Nút bấm của menu DUYỆT BẢN SỬA SKILL (`capabilities._ask_duyet_ban_sua`):
#   lưu bản sửa skill «slug» / giữ bản cũ skill «slug» / xoá skill «slug»
# Đọc lại thẳng nên việc «duyệt» đi đúng vào skill đó, không nhờ model đoán lại —
# bấm nhầm slug ở đây là ghi đè thân một skill khác.
_NUT_SUA_SKILL = re.compile(
    r"^\s*(?P<viec>lưu\s+bản\s+sửa|giữ\s+bản\s+cũ|xoá|xóa)\s+skill\s+«(?P<slug>[^»]+)»\s*$",
    re.IGNORECASE,
)
_VIEC_SKILL = {"lưu bản sửa": "apply_fix", "giữ bản cũ": "keep_old",
               "xoá": "delete", "xóa": "delete"}


def _doc_nut_sua_skill(text: str) -> dict | None:
    """args cho `teach_skill` nếu câu là nút bấm của menu duyệt bản sửa."""
    m = _NUT_SUA_SKILL.match((text or "").strip())
    if not m:
        return None
    viec = re.sub(r"\s+", " ", m.group("viec").strip().lower())
    op = _VIEC_SKILL.get(viec)
    return {"op": op, "slug": m.group("slug").strip()} if op else None


# Nút bấm của menu chọn âm lượng loa (`capabilities._ask_am_luong_loa` sinh ra):
#   đọc ra loa «loa phòng khách» âm lượng 60% sau 2 phút: <nội dung>
# Đọc lại được thì cả loa, âm lượng, nội dung và thời điểm đều đi đúng vào
# `announce_on_speaker` — không phụ thuộc model định tuyến đoán lại, vốn là chỗ
# lượt chat 02/08 bị nhảy qua nhảy lại giữa hai capability loa và mất mất cả
# «loa phòng khách» lẫn «60%».
_NUT_LOA = re.compile(
    r"^\s*đọc\s+ra\s+loa\s+«(?P<loa>[^»]+)»\s+âm\s+lượng\s+"
    r"(?P<vol>\d{1,3}\s*%|giữ\s+nguyên)"
    r"(?:\s+sau\s+(?P<phut>\d+(?:[.,]\d+)?)\s*phút)?"
    r"\s*:\s*(?P<noi_dung>.+)$",
    re.IGNORECASE | re.DOTALL,
)


# Nút bấm của menu CHỌN LOA (`capabilities._ask_chon_loa` sinh ra):
#   chọn loa «loa phòng khách» sau 2 phút: <nội dung>
# Bấm nút này thì loa đã rõ nhưng âm lượng CHƯA — handler sẽ hỏi tiếp âm lượng.
_NUT_CHON_LOA = re.compile(
    r"^\s*chọn\s+loa\s+«(?P<loa>[^»]+)»\s+để\s+đọc"
    r"(?:\s+sau\s+(?P<phut>\d+(?:[.,]\d+)?)\s*phút)?"
    r"\s*:\s*(?P<noi_dung>.+)$",
    re.IGNORECASE | re.DOTALL,
)


# Nút «Tuỳ chọn» và nút mang KẾ HOẠCH nhiều loa (capabilities._ask_chon_loa /
# _ask_am_luong_tung_loa sinh ra):
#   tuỳ chọn loa để đọc[ sau N phút]: <nội dung>
#   đọc ra loa nhiều «loa A=50; loa B=?»[ sau N phút]: <nội dung>
# Kế hoạch nằm TRONG nút nên không cần giữ trạng thái tạm nào trên máy chủ: người
# dùng thấy trọn kế hoạch trước khi bấm, và không có gì để mất khi khởi động lại.
_NUT_TUY_CHON_LOA = re.compile(
    r"^\s*tuỳ\s+chọn\s+loa\s+để\s+đọc"
    r"(?:\s+sau\s+(?P<phut>\d+(?:[.,]\d+)?)\s*phút)?"
    r"\s*:\s*(?P<noi_dung>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_NUT_LOA_NHIEU = re.compile(
    r"^\s*đọc\s+ra\s+loa\s+nhiều\s+«(?P<ke>[^»]+)»"
    r"(?:\s+sau\s+(?P<phut>\d+(?:[.,]\d+)?)\s*phút)?"
    r"\s*:\s*(?P<noi_dung>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _doc_nut_menu_loa(text: str) -> dict | None:
    """args cho `announce_on_speaker` nếu câu là nội dung nút bấm menu loa.

    Đọc được HAI loại nút, vì luồng có hai bước hỏi:
      · chọn loa   → loa đã rõ, âm lượng chưa → handler hỏi tiếp âm lượng
      · chọn âm lượng → đủ thông tin → phát
    """
    t = (text or "").strip()
    if not t:
        return None

    def _phut_vao(d: dict, phut) -> dict:
        if phut:
            try:
                d["delay_minutes"] = float(str(phut).replace(",", "."))
            except ValueError:
                pass
        return d

    m3 = _NUT_LOA_NHIEU.match(t)
    if m3:
        return _phut_vao({"text": m3.group("noi_dung").strip(),
                          "ke_hoach": m3.group("ke").strip()},
                         m3.groupdict().get("phut"))
    m4 = _NUT_TUY_CHON_LOA.match(t)
    if m4:
        return _phut_vao({"text": m4.group("noi_dung").strip(), "tuy_chon": True},
                         m4.groupdict().get("phut"))
    m2 = _NUT_CHON_LOA.match(t)
    if m2:
        args2: dict[str, Any] = {"text": m2.group("noi_dung").strip(),
                                 "speaker": m2.group("loa").strip()}
        phut2 = m2.groupdict().get("phut")
        if phut2:
            try:
                args2["delay_minutes"] = float(phut2.replace(",", "."))
            except ValueError:
                pass
        return args2
    if "âm lượng" not in t.lower():
        return None
    m = _NUT_LOA.match(t)
    if not m:
        return None
    # `am_luong_da_chon` = bằng chứng NGƯỜI đã chọn mức, không phải model đoán —
    # `_h_announce_on_speaker` chỉ áp âm lượng khi thấy cờ này.
    args: dict[str, Any] = {"text": m.group("noi_dung").strip(),
                            "speaker": m.group("loa").strip(),
                            "am_luong_da_chon": True}
    vol = re.sub(r"\s+", "", m.group("vol")).lower()
    if vol.endswith("%"):
        try:
            args["volume"] = int(vol[:-1])
        except ValueError:
            args["giu_am_luong"] = True
    else:
        args["giu_am_luong"] = True     # "giữ nguyên" — đừng hỏi lại âm lượng
    phut = m.groupdict().get("phut")
    if phut:
        try:
            args["delay_minutes"] = float(phut.replace(",", "."))
        except ValueError:
            pass
    return args


# In-process cache; durable source of truth is session SQLite when enabled.
# Kept so a failed DB still allows the current process to converse.
_history: dict[str, list[dict[str, Any]]] = {}

# FIX5 (audit 2026-07): khoá RIÊNG từng user_id, bọc toàn bộ một lượt
# orchestrate() (load lịch sử → gọi LLM/tool → ghi lịch sử) — chống mất-cập-
# nhật khi 2 luồng xử lý CÙNG user song song (vd: reminder mode=task bắn tới
# giờ đúng lúc user đang chat qua Telegram/Zalo, mỗi webhook một luồng riêng).
# _history_locks_guard chỉ bảo vệ việc TẠO lock (get-or-create), không giữ
# xuyên suốt lượt chat. KHÔNG có module nào khác giữ lock của nó trong lúc
# gọi orchestrate() (xem reminders._fire/_advance — _lock của reminders.py
# chỉ bọc CRUD bảng reminders, luôn nhả trước khi gọi orchestrate) nên không
# có chiều ngược để tạo deadlock giữa 2 lock khác nhau.
_history_locks: dict[str, threading.Lock] = {}
_history_locks_guard = threading.Lock()

# Trần thời gian một lượt. Rộng tay để lượt agent nhiều bước vẫn chạy xong
# (MCP 30s + tối đa 4 vòng model), nhưng vẫn bắn TRƯỚC timeout 300s của kênh
# nên người dùng nhận lời xin lỗi thay vì im lặng.
_TURN_BUDGET_S = 240.0
# Chờ lượt trước của CÙNG người. Hết chừng này thì báo bận chứ không xếp hàng
# vô hạn — hàng đợi vô hạn là thứ biến một lượt treo thành chết cả hội thoại.
_LOCK_WAIT_S = 45.0


def _ghi_so_anh(user_id: str, urls: list[str]) -> None:
    """Ghi sổ "ảnh của CHÍNH người này" — để lượt sau hỏi "3 ảnh gần nhất tôi tạo"
    không lấy ảnh của người khác.

    Ghi ở đây vì đây là tầng DUY NHẤT biết cả user_id lẫn ảnh vừa sinh ra;
    `save_image_bytes` được gọi từ nhiều nơi không biết người dùng (protocol
    OpenAI, snapshot camera của Home Assistant, test).

    Lỗi ghi sổ KHÔNG được làm hỏng lượt trả lời: ảnh đã tạo xong rồi, mất sổ chỉ
    mất khả năng lọc theo người ở lượt sau.
    """
    try:
        from services.agent import anh_cua_toi
        anh_cua_toi.ghi(str(user_id or ""), list(urls))
    except Exception as exc:
        logger.warning("ghi sổ ảnh theo người lỗi: %s", exc)


# Dấu hiệu một dòng trí nhớ đang nói về CÁCH TRÌNH BÀY câu trả lời, chứ không
# phải một dữ kiện về người dùng.
_TU_KHOA_SO_THICH = (
    "trình bày", "định dạng", "bố cục", "chia mục", "chia thành các mục",
    "gạch đầu dòng", "mỗi mục", "ngắn gọn", "súc tích", "dài dòng",
    "không cần link", "không link", "bỏ link", "không dán link",
    "không ảnh", "không emoji", "đừng dùng emoji",
    # Tóm tắt: phải bắt CẢ hai chiều. Bản đầu chỉ có "có tóm tắt"/"kèm tóm tắt"
    # nên đúng câu người dùng dùng thật — "Bỏ tóm tắt đi" — không được nhận, và
    # cả cơ chế đứng ngoài lượt đó. Bộ test bắt được, không phải suy đoán.
    "có tóm tắt", "kèm tóm tắt", "bỏ tóm tắt", "không tóm tắt", "bớt tóm tắt",
    "chỉ tiêu đề", "chỉ ghi tiêu đề", "tiêu đề thôi", "chỉ cần tiêu đề",
)


def _bo_dau(s: str) -> str:
    """Hạ chữ + bỏ dấu tiếng Việt, để so khớp không phụ thuộc dấu.

    Người dùng gõ không dấu là chuyện thường ("chia cac muc", "tra loi ngan
    gon"), nên bộ dò chỉ khớp chữ CÓ dấu sẽ bỏ sót đúng những lời dặn gõ nhanh.
    """
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", str(s or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).replace("đ", "d")


_TU_KHOA_SO_THICH_KHONG_DAU = tuple(_bo_dau(k) for k in _TU_KHOA_SO_THICH)


def _so_thich_trinh_bay(limit: int = 6) -> list[str]:
    """Các dòng trí nhớ nói về CÁCH TRÌNH BÀY, lấy mấy dòng gần nhất."""
    try:
        mem = state.load_memory()
    except Exception:
        return []
    ra: list[str] = []
    for dong in (mem or "").splitlines():
        d = dong.strip().lstrip("-•* \t")
        if len(d) < 8:
            continue
        low = _bo_dau(d)
        if any(k in low for k in _TU_KHOA_SO_THICH_KHONG_DAU):
            ra.append(d)
    return ra[-limit:]


# Trần độ dài cho việc nhờ model bày lại. Dài hơn thì model không kịp trong hạn
# chờ 20 giây (đo thật 01/08 với bản tin 4819 ký tự: hết giờ 100% số lần).
_TRAN_BAY_LAI = 1500


_DAU_TIENG_VIET = _re_mod.compile(
    "[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]",
    _re_mod.I)
_DONG_TIN = _re_mod.compile(r"^- \*\*(.+?)\*\*", _re_mod.M)


def _dich_tieu_de_tieng_anh(text: str, main_model_fn) -> str:
    """Dịch các tiêu đề tin KHÔNG phải tiếng Việt sang tiếng Việt.

    Người dùng dặn 01/08: "có nguồn tiếng anh nhưng chuyển sang tiếng việt". Bản
    tin lấy từ nhiều báo, trong đó BBC News và World Monitor trả tiêu đề tiếng
    Anh — đo thật: 4 trong 24 tin.

    Chỉ dịch ĐÚNG mấy tiêu đề đó, không đưa cả bản tin cho model. Đó là bài học
    từ lần trước: gửi cả bản tin 4819 ký tự thì model hết giờ 100% số lần và tốn
    20 giây vô ích. Vài tiêu đề ngắn thì nhanh, và trượt cũng chỉ mất phần dịch.
    """
    goc = text or ""
    can_dich = [t for t in _DONG_TIN.findall(goc) if not _DAU_TIENG_VIET.search(t)]
    if not can_dich:
        return goc                      # bản tin đã toàn tiếng Việt — không tốn gì
    try:
        danh_sach = "\n".join(f"{i+1}. {t}" for i, t in enumerate(can_dich))
        resp = call_model(main_model_fn("chat") or main_model_fn("burst"), [
            {"role": "system", "content": (
                "Dịch từng tiêu đề tin sang tiếng Việt tự nhiên, có đủ dấu. "
                "Giữ NGUYÊN số thứ tự và số dòng, mỗi dòng một tiêu đề, không "
                "thêm lời nào khác. Giữ nguyên tên riêng và số liệu.")},
            {"role": "user", "content": danh_sach},
        ], timeout=15, no_smart_home=True)
        if resp.get("error"):
            return goc
        dong = [d.strip() for d in content_of(resp).strip().splitlines() if d.strip()]
        if len(dong) != len(can_dich):
            logger.info({"event": "dich_tieu_de_bo_qua", "ly_do": "lech so dong",
                         "can": len(can_dich), "nhan": len(dong)})
            return goc
        ra = goc
        for cu, moi in zip(can_dich, dong):
            moi = _re_mod.sub(r"^\d+[.)]\s*", "", moi).strip()
            if moi and _DAU_TIENG_VIET.search(moi):
                ra = ra.replace(f"**{cu}**", f"**{moi}**")
        logger.info({"event": "dich_tieu_de", "so_tin": len(can_dich)})
        return ra
    except Exception as exc:
        logger.warning({"event": "dich_tieu_de_loi", "error": str(exc)[:150]})
        return goc


# Dáng bản tin, tách theo TỪNG MẶT. Mỗi mặt có cụm nói CÓ và cụm nói KHÔNG.
_MAT_DANG_TIN = {
    "tom_tat": (("co tom tat", "kem tom tat", "them tom tat"),
                ("bo tom tat", "khong tom tat", "bot tom tat",
                 "chi tieu de", "tieu de thoi", "chi can tieu de")),
    "in_dam": (("in dam", "to dam", "boi dam", "tô đậm"),
               ("khong in dam", "bo in dam", "khong to dam", "khong dam")),
    "emoji": (("co icon", "them icon", "bo sung icon", "co emoji", "them emoji",
               "moi dau muc co icon"),
              ("khong emoji", "bo emoji", "khong dung emoji", "emoji ruom ra",
               "khong icon", "bo icon")),
    # Chỉ tin tiếng Việt. LỌC chứ không dịch — xem `news._la_tieng_viet`.
    "chi_viet": (("tieng viet", "toan tieng viet", "dich sang tieng viet",
                  "hoan toan tieng viet", "khong de lan tieng anh"),
                 ("giu tieng anh", "de nguyen tieng anh")),
}


def _dang_bay_tin() -> dict[str, bool]:
    """Dáng bản tin suy từ lời dặn, ưu tiên dòng MỚI NHẤT.

    Vì sao phải xét theo thứ tự mới→cũ: trí nhớ có thể chứa hai lời dặn NGƯỢC
    NHAU về cùng một mặt (10:13 "không in đậm, không emoji" rồi 10:16 "bổ sung
    icon, in đậm"). Bản đầu tôi dò bằng `any()` trên toàn bộ lời dặn gộp lại, nên
    cụm phủ định của dòng CŨ luôn thắng — người dùng đổi ý mà bản tin không đổi.

    Dòng nào KHÔNG nói gì về một mặt thì bỏ qua mặt đó, xét tiếp dòng cũ hơn.
    Không dòng nào nói tới thì giữ mặc định (giống dáng gốc).
    """
    ra = {"tom_tat": True, "in_dam": True, "emoji": True, "chi_viet": False}
    con_thieu = set(ra)
    # `_so_thich_trinh_bay()` trả theo thứ tự trong file (cũ → mới) nên đảo lại.
    for dong in reversed(_so_thich_trinh_bay()):
        if not con_thieu:
            break
        d = _bo_dau(dong)
        for mat in list(con_thieu):
            co, khong = _MAT_DANG_TIN[mat]
            if any(k in d for k in khong):
                ra[mat] = False
                con_thieu.discard(mat)
            elif any(k in d for k in co):
                ra[mat] = True
                con_thieu.discard(mat)
    return ra


def _neo_noi_dung(s: str, toi_da: int = 40) -> list[str]:
    """Các mẩu NEO dùng để kiểm "bản trình bày lại có mất tin không".

    Ưu tiên tiêu đề in đậm `**…**` — đó là hạt nhân thông tin của bản tin. Không
    có thì lấy từng dòng có nghĩa. Chỉ giữ `toi_da` ký tự đầu mỗi neo: model
    được phép cắt bớt đuôi tiêu đề dài, nhưng không được làm biến mất cả tin.
    """
    import re as _re
    neo = [x.strip() for x in _re.findall(r"\*\*(.{8,}?)\*\*", s, _re.S)]
    if not neo:
        neo = [d.strip().lstrip("-•*0123456789. \t") for d in s.splitlines()]
    return [n[:toi_da] for n in neo if len(n.strip()) >= 8]


def _ap_so_thich(text: str, user_text: str, main_model_fn) -> str:
    """Diễn đạt lại kết quả ĐƯỜNG TẮT theo sở thích trình bày đã ghi nhớ.

    Vì sao cần, và vì sao ở đây: sở thích ghi nhớ được tiêm vào system prompt,
    nên mọi lượt DO MODEL trả lời đều tôn trọng nó. Nhưng các đường tắt
    (tin tức, lấy media, nhà thông minh) trả về TRƯỚC KHI model được gọi, nên
    chúng bỏ qua sạch mọi thứ người dùng đã dặn. Hệ quả không chỉ ở tin tức: bất
    kỳ yêu cầu "đổi cách phản hồi" nào cũng bị đường tắt vô hiệu hoá, và bot vẫn
    "ghi nhớ" rồi hứa — đo thật 01/08, lượt 08:11 lưu đúng yêu cầu chia mục xong
    lượt sau vẫn trả danh sách phẳng.

    Không có sở thích nào thì trả nguyên văn — không tốn thêm một lượt gọi model.

    Chốt an toàn đo MẤT TIN, KHÔNG đo độ dài. Bản đầu tôi chặn theo độ dài
    ("ngắn hơn một nửa thì bỏ") và nó chặn OAN đúng thứ người dùng xin: đo thật
    01/08, bản tin có tóm tắt 4762 ký tự, bỏ tóm tắt còn 1718 — dưới ngưỡng
    2381, nên yêu cầu "bỏ tóm tắt đi" sẽ bị chính chốt này vô hiệu hoá trong im
    lặng. Rút gọn là việc HỢP LỆ; mất tin mới là lỗi. Nên chốt đếm xem các TIÊU
    ĐỀ của bản gốc còn lại bao nhiêu trong bản mới.
    """
    goc = (text or "").strip()
    if not goc:
        return goc
    st = _so_thich_trinh_bay()
    if not st:
        return goc
    # Văn bản DÀI thì đừng nhờ model: đo thật 01/08, bản tin 4819 ký tự không
    # kịp xong trong 20 giây, lần nào cũng hết giờ rồi rơi về bản gốc — tốn 20
    # giây chờ để nhận đúng thứ cũ. Nội dung dài phải định dạng bằng code ở nơi
    # sinh ra nó (như `get_news_sections` làm), không chữa ở khâu cuối.
    if len(goc) > _TRAN_BAY_LAI:
        logger.info({"event": "ap_so_thich_bo_qua", "ly_do": "van ban qua dai",
                     "dai": len(goc), "tran": _TRAN_BAY_LAI})
        return goc
    try:
        model = main_model_fn("chat") or main_model_fn("burst")
        resp = call_model(model, [
            {"role": "system", "content": (
                "Người dùng đã dặn TRƯỚC cách họ muốn xem câu trả lời. Hãy trình "
                "bày lại nội dung dưới đây cho đúng ý họ.\n"
                "TUYỆT ĐỐI KHÔNG thêm, bớt, hay sửa thông tin: không bịa tin mới, "
                "không bỏ tin đang có, không đổi số liệu hay tên riêng. Chỉ đổi "
                "CÁCH BÀY: thứ tự, nhóm mục, độ dài câu, gạch đầu dòng.\n"
                "Trả về ĐÚNG nội dung đã trình bày lại, không nói gì thêm.\n\n"
                "Người dùng đã dặn:\n" + "\n".join(f"- {x}" for x in st)
            )},
            {"role": "user", "content": f"Câu hỏi: {user_text}\n\nNội dung:\n{goc}"},
        # Trần 20s, KHÔNG 45: lượt tin tức trước đó chỉ 4,1 giây, sau khi thêm
        # bước bày lại thành 37 giây (đo thật 01/08) — người dùng ngồi chờ. Bày
        # lại là việc "có thì tốt"; quá 20 giây thì thà gửi bản gốc ngay.
        ], timeout=20, no_smart_home=True)
        if resp.get("error"):
            return goc
        moi = content_of(resp).strip()
        neo = _neo_noi_dung(goc)
        if neo:
            con = sum(1 for n in neo if n in moi)
            if con < (len(neo) * 7) // 10:
                logger.info({"event": "ap_so_thich_bo_qua", "ly_do": "mat noi dung",
                             "neo": len(neo), "con_lai": con})
                return goc
        elif len(moi) < len(goc) // 2:
            # Không rút được neo nào (văn bản một khối) → đành đo độ dài.
            logger.info({"event": "ap_so_thich_bo_qua", "ly_do": "ngan bat thuong",
                         "goc": len(goc), "moi": len(moi)})
            return goc
        logger.info({"event": "ap_so_thich", "so_dan": len(st),
                     "goc": len(goc), "moi": len(moi)})
        return moi
    except Exception as exc:
        logger.warning({"event": "ap_so_thich_loi", "error": str(exc)[:150]})
        return goc


def _nhieu_anh(urls: list[str]) -> dict:
    """`{"image_urls": [...]}` khi có TỪ HAI ảnh, ngược lại `{}`.

    Chỉ thêm khoá khi thật sự nhiều ảnh: một ảnh đã nằm ở `image_url`, gửi kèm
    thêm danh sách một phần tử là mời mọi kênh đi đường chia lô cho đúng một
    tấm — thêm việc, thêm chỗ sai, không được gì.
    """
    return {"image_urls": list(urls)} if len(urls) > 1 else {}


def _user_history_lock(user_id: str) -> threading.Lock:
    key = str(user_id or "")
    with _history_locks_guard:
        lock = _history_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _history_locks[key] = lock
        return lock


_APPROVE_ALWAYS = ("luôn luôn", "luôn khỏi hỏi", "khỏi hỏi", "lúc nào cũng", "từ giờ khỏi hỏi", "always")
_APPROVE_ONCE = ("ok", "oke", "được", "duoc", "đồng ý", "dong y", "làm đi", "lam di", "ừ", "uh", "yes", "có", "co", "đi")
_DENY = ("thôi", "thoi", "không", "khong", "hủy", "huy", "đừng", "dung", "no", "khỏi")


def _main_model(hint: str = "chat") -> str:
    """Resolve agent model via hint routing (chat/burst/reason/code)."""
    try:
        return model_hints.resolve(hint or "chat")
    except Exception:
        return str(config.get().get("telegram_ai_model") or "").strip() or "cx/auto"


_PROVIDER_FRIENDLY = {
    "cx": "Codex", "claude": "Claude (viết code)", "flow": "Flow (vẽ ảnh miễn phí)",
    "gma": "Gemini", "gemini_free": "Gemini", "gemini_web": "Gemini web",
    "gemini_web_api": "Gemini web", "chatgpt_web": "ChatGPT web",
    "cgf": "ChatGPT free", "chatgpt": "ChatGPT",
}


def _provider_summary() -> str:
    """List the AI backends actually available, so the persona only claims tools
    that really exist. Codex (the main brain) is configured outside `providers`,
    so seed it from the main model."""
    names = []
    try:
        main = _main_model().split("/")[0]
        names.append(_PROVIDER_FRIENDLY.get(main, main) + " (agent chính)")
    except Exception:
        pass
    try:
        providers = config.get().get("providers") or {}
        if isinstance(providers, dict):
            for key in providers.keys():
                names.append(_PROVIDER_FRIENDLY.get(str(key), str(key)))
    except Exception:
        pass
    return ", ".join(dict.fromkeys(names)) if names else ""


_WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def _now_line() -> str:
    """Current VIETNAM datetime in Vietnamese, so the model answers date/time
    questions ("mai thứ mấy") naturally and correctly by itself. The container
    runs UTC, so pin Asia/Ho_Chi_Minh explicitly."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    except Exception:
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    return (f"Bây giờ là {now.strftime('%H:%M')}, {_WEEKDAYS_VI[now.weekday()]}, "
            f"ngày {now.day} tháng {now.month} năm {now.year} (giờ Việt Nam).")


def _build_system_prompt(user_id: str, allow: set[str] | None = None) -> str:
    name = config.agent_name
    soul = state.load_soul().replace("{agent_name}", name)
    parts = [soul, _now_line()]
    # Capability list — auto-generated from the registry (single source of truth).
    # Lọc theo `allow` để persona KHÔNG khoe chức năng thread này bị cấm.
    parts.append("## Em làm được gì (năng lực THẬT lúc này)\n" + caps.persona_list(allow))
    if allow is not None:
        # TUYỆT ĐỐI không nêu ví dụ TĨNH về "chức năng bị tắt" ở đây. Bản cũ
        # viết cứng "vd: xem/điều khiển nhà thông minh, xem máy chủ…" cho MỌI
        # thread — thread đã bật homeassistant hẳn hoi mà model đọc câu "nhà
        # thông minh đã bị TẮT" (gắn mác QUAN TRỌNG) rồi tin theo nghĩa đen:
        # hỏi "phòng ngủ có ai không" là trả [BLOCKED] dù tool home_status nằm
        # ngay trong request. Ví dụ giờ sinh ĐỘNG từ đúng các nhóm bị tắt của
        # thread này; không có nhóm nào tắt thì khỏi doạ.
        disabled = sorted(set(caps.all_groups()) - set(allow))
        limit_txt = (
            "## Giới hạn khung chat này (QUAN TRỌNG)\n"
            "Danh sách «Em làm được gì» ở trên là nguồn sự thật DUY NHẤT về "
            "quyền của khung chat này. Nếu người dùng yêu cầu việc KHÔNG nằm "
            "trong danh sách đó: KHÔNG giải thích, KHÔNG xin lỗi, KHÔNG bịa/"
            "đoán dữ liệu — chỉ trả lời DUY NHẤT chuỗi [BLOCKED] (đúng nguyên "
            "văn), hệ thống sẽ tự bỏ qua tin nhắn đó. Trò chuyện thông thường "
            "vẫn trả lời bình thường.\n"
            # Model hay phán nhầm câu hỏi entity CỤ THỂ ("kiểm tra cảm biến
            # sensor.xyz") là việc kỹ thuật ngoài danh sách rồi [BLOCKED] oan,
            # trong khi "phòng khách có ai không" thì trả lời bình thường —
            # cùng một quyền. Nói rõ hai điều: mọi biến thể của một chức năng
            # đã cấp đều thuộc chức năng đó, và khi KHÔNG CHẮC thì thử tool
            # trước, [BLOCKED] chỉ dành cho việc CHẮC CHẮN nằm ngoài.\n
            "Lưu ý: mọi biến thể của một chức năng đã cấp đều được phép — vd "
            "đã có «Xem trạng thái nhà» thì hỏi một cảm biến/entity cụ thể "
            "(sensor.xyz, light.abc…) cũng thuộc quyền đó, cứ gọi tool mà trả "
            "lời. Chỉ dùng [BLOCKED] khi CHẮC CHẮN yêu cầu nằm ngoài danh "
            "sách; còn phân vân thì thử tool tương ứng trước.")
        if disabled:
            limit_txt += ("\nNhóm chức năng đã TẮT cho khung chat này: "
                          + ", ".join(disabled) + ".")
        parts.append(limit_txt)
    prov = _provider_summary()
    if prov:
        parts.append("## Công cụ / nhà cung cấp AI đang có\n" + prov)
    env = state.load_environment()
    if env.strip():
        parts.append("## Môi trường em đang sống (bản đồ hệ thống)\n" + env.strip())
    mem = state.load_memory()
    if mem.strip():
        parts.append("## Trí nhớ (chuyện đã ghi nhớ)\n" + mem.strip())
    # Người dùng xin đổi CÁCH TRÌNH BÀY nội dung vừa gửi → LÀM LẠI NGAY.
    #
    # Đo thật 01/08: sau khi nhận bản tin, người dùng nói "Bỏ tóm tắt đi". Bot
    # ghi nhớ rồi trả về một BẢN MẪU RỖNG ("Thể thao / - Tin 1 / - Tin 2 / - Tin
    # 3 / … và các mục còn lại"). Người dùng không nhận được tin nào, mà lại
    # tưởng bot đã hiểu và làm xong. Lượt trước đó cũng đúng kiểu này ("Trình bày
    # xấu, không có tóm tắt" → bot trả mẫu "Tin 1: tóm tắt 1 câu ngắn").
    parts.append(
        "## Khi người dùng xin đổi cách trình bày\n"
        "Nếu họ vừa nhận một nội dung (bản tin, danh sách, kết quả) rồi xin đổi "
        "cách bày — 'bỏ tóm tắt đi', 'ngắn hơn', 'chia mục', 'không cần link' — "
        "thì LÀM LẠI NGAY nội dung THẬT theo cách mới, trong cùng câu trả lời "
        "này.\n"
        "TUYỆT ĐỐI KHÔNG trả về bản mẫu có chỗ trống ('Tin 1', 'Tin 2', "
        "'tóm tắt 1 câu ngắn', '… và các mục còn lại'), và không hứa 'từ giờ em "
        "sẽ…' rồi để trống. Mẫu rỗng làm người dùng tưởng đã xong trong khi họ "
        "chưa nhận được gì.\n"
        "Không còn nội dung trong tay thì lấy lại bằng công cụ rồi bày theo cách "
        "mới, chứ không mô tả suông.\n"
        "BẮT BUỘC ghi nhớ: lời dặn về cách trả lời là dặn cho LÂU DÀI, nên trong "
        "CHÍNH lượt đó phải gọi công cụ `remember` để lưu lại. Không được nói "
        "'từ giờ em sẽ…' / 'từ lần sau…' mà không gọi `remember` — nói mà không "
        "lưu thì lượt sau quên sạch, còn người dùng thì tin là đã xong.\n"
        "Người dùng dặn thêm/sửa một điều đã dặn trước thì cứ gọi `remember` với "
        "lời dặn ĐẦY ĐỦ sau khi sửa; hệ thống tự thay bản cũ, không sinh trùng."
    )
    # Compacted earlier turns (durable across restarts)
    try:
        summary = sess.load_summary(user_id)
        if summary.strip():
            parts.append(
                "## Tóm tắt hội thoại trước với người này\n" + summary.strip()
            )
    except Exception:
        pass
    prof = state.load_user_profile(user_id)
    if prof.strip():
        parts.append("## Hồ sơ người đang nói chuyện\n" + prof.strip())
    # Skill / playbook index (description only — body loaded via use_skill)
    try:
        sk_block = agent_skills.router_block()
        if sk_block.strip():
            parts.append(sk_block)
    except Exception:
        pass
    try:
        wf_block = agent_workflows.router_block()
        if wf_block.strip():
            parts.append(wf_block)
    except Exception:
        pass
    try:
        goals_block = agent_goals.prompt_block(user_id)
        if goals_block.strip():
            parts.append(goals_block)
    except Exception:
        pass
    parts.append(
        "## Ngôn ngữ trả lời (BẮT BUỘC)\n"
        "Câu trả lời chỉ dùng chữ Việt/Latin. TUYỆT ĐỐI không để lẫn chữ Hán, "
        "Kana hay Hangul vào câu tiếng Việt, kể cả MỘT từ. Lỗi này đã xảy ra "
        "thật: 'chất bán導体' (phải là 'chất bán dẫn'), 'bộ biến đổi để转换为' "
        "(phải là 'để chuyển thành'), 'thắp sáng灯泡' (phải là 'thắp sáng bóng "
        "đèn'), 'đọc từ多個 nguồn' (phải là 'từ nhiều nguồn'). Nếu từ nào chỉ "
        "nghĩ ra được bằng tiếng Trung/Nhật thì phải diễn đạt lại bằng tiếng "
        "Việt. Chỉ được dùng chữ Hán/Kana/Hangul khi người dùng hỏi trực tiếp "
        "về thứ tiếng đó hoặc yêu cầu dịch.")
    parts.append(
        "## Bảo mật secret / placeholder (BẮT BUỘC)\n"
        "Trong hội thoại và tool/RAG có thể xuất hiện placeholder dạng "
        "⟦secret:…⟧ / ⟦password:…⟧ / ⟦tc:…⟧. "
        "Em phải CHÉP NGUYÊN VĂN placeholder khi cần dùng lại — "
        "TUYỆT ĐỐI KHÔNG đoán, khôi phục, hay viết lại mật khẩu/token thật. "
        "Không đưa secret thô vào câu trả lời cho người dùng.")
    parts.append(
        "## Cách dùng công cụ\n"
        "Khi cần làm việc cụ thể, GỌI đúng tool. Với việc THAY ĐỔI chưa được "
        "phép, cứ gọi tool bình thường — hệ thống sẽ tự hỏi xin phép người dùng. "
        "Nếu chỉ trò chuyện/giải thích thì trả lời thẳng, không gọi tool.")
    parts.append(
        "## HỎI-ĐỦ-THÔNG-TIN-MỚI-LÀM (Quy tắc BẮT BUỘC cho gửi tin, nhắc hẹn, phát loa, báo cáo, thực thi)\n"
        "Trước khi gọi bất kỳ tool thực thi nào (schedule, send_to_contact, v.v.), BẮT BUỘC kiểm tra xem đã ĐỦ các yếu tố bắt buộc chưa:\n"
        "- Với Gửi tin chat / Báo cáo dạng Tin nhắn Text / File (Word/Excel): (1) Khi nào - (2) Bằng kênh gì (Zalo cá nhân/Zalo bot/Telegram) - (3) Nhóm/Người nào - (4) Nội dung/Số liệu gì.\n"
        "- Với Phát loa (TTS): (1) Khi nào - (2) Loa gì (Loa phòng nào) - (3) Nội dung phát gì.\n"
        "Nếu THIẾU bất kỳ yếu tố nào → KHÔNG TỰ ĐOÁN hay điền mặc định! HỎI LẠI NGAY người dùng để làm rõ trước khi đặt lịch hoặc thực thi.\n"
        "\n"
        "## QUY TRÌNH PHÁT LOA (TTS) & BÁO CÁO TIN NHẮN CHAT / FILE (WORD/EXCEL/AUDIO)\n"
        "1. SOẠN SẴN NỘI DUNG / TẠO SẴN FILE (Pre-generate):\n"
        "   - Với Tin nhắn Chat (Text): Soạn sẵn nội dung tin nhắn và lưu lại trong bản ghi lịch.\n"
        "   - Với File Báo cáo (Word/Excel) hoặc File Âm thanh (TTS): Ngay khi nhận yêu cầu (sau khi đủ thông tin), tạo sẵn file (Word/Excel/Audio TTS) và lưu trữ tạm.\n"
        "2. HỎI XÁC NHẬN TRƯỚC KHI BẮN GIỜ (Firing Time): Khi sắp đến giờ phát loa hoặc gửi tin nhắn/file báo cáo vào nhóm, BẮT BUỘC hỏi lại người dùng: 'Đã đến giờ phát/gửi rồi ạ, nội dung/số liệu có thay đổi gì không ạ?':\n"
        "   - Nếu KHÔNG thay đổi → Gửi ngay tin nhắn chat hoặc phát/gửi file đã tạo sẵn trước đó.\n"
        "   - Nếu CÓ thay đổi → Cập nhật nội dung tin nhắn hoặc xóa file cũ tạo file mới (TTS/Word/Excel) rồi mới gửi/phát.\n"
        "3. QUẢN LÝ VÀ DỌN DẸP FILE:\n"
        "   - Lần duy nhất (1 lần): Tự động xóa file tạm sau khi phát/gửi xong.\n"
        "   - Định kỳ (Hằng ngày/mỗi tuần): Giữ lại mẫu/lịch cho các lần sau.")
    parts.append(
        "## Hỏi lại có lựa chọn (khi cần user chọn)\n"
        "Khi phải hỏi chọn (công cụ vẽ, phương án…), cuối câu trả lời thêm khối:\n"
        "<<<ASK>>>\n"
        "Nhãn hiện cho user | giá trị gửi lại khi chọn\n"
        "Flow miễn phí | flow\n"
        "ChatGPT\n"
        "<<<END>>>\n"
        "Hệ thống tự vẽ nút (Telegram) hoặc danh sách số (Zalo). "
        "Chỉ dùng khi THẬT SỰ cần chọn; đừng lạm dụng mỗi câu.")
    parts.append(
        "## Bảng chỉ đường (định tuyến việc — LÀM ĐÚNG NHÁNH, KHÔNG HỎI LẠI)\n"
        "- Vẽ/tạo ảnh → generate_image. Tạo nhạc/bài hát → generate_music. "
        "Tạo video → generate_video. Viết/sửa code → write_code. "
        "Tra cứu tin tức/giá cả → web_search. HAI KIỂU tin, xử lý KHÁC nhau:\n"
        "  • Tin CHUNG (không nêu chủ đề): 'tin tức hôm nay', 'bản tin', 'điểm "
        "tin', 'có gì mới' → chia ĐẦY ĐỦ 8 đầu mục (🇻🇳 Thời sự Việt Nam, 🌎 Thế "
        "giới, 💼 Kinh doanh & Kinh tế, 📱 Công nghệ & Khoa học, ⚽ Thể thao, 🎨 "
        "Giải trí & Văn hóa, 🏥 Sức khỏe & Đời sống, ⚖️ Pháp luật & Xã hội), mỗi "
        "mục đúng 3 tiêu đề mới nhất kèm tóm tắt ngắn.\n"
        "  • Tin về MỘT CHỦ ĐỀ cụ thể: 'tin bão', 'tin về <sự kiện/người/nơi>', "
        "'giá vàng', 'kết quả trận …', 'tình hình <chủ đề>' → search ĐÚNG chủ đề "
        "đó, CHỈ trả tin LIÊN QUAN chủ đề (5–8 tin mới nhất, gạch đầu dòng ngắn). "
        "TUYỆT ĐỐI KHÔNG chia 8 mục, KHÔNG chèn tin lạc đề, KHÔNG thay chủ đề "
        "người dùng hỏi bằng bản tin tổng hợp chung.\n"
        "- Nhắc hẹn / việc định kỳ ('nhắc em sau 30 phút', 'mỗi sáng 7h báo "
        "thời tiết') → schedule (mode=notify|task). Tìm chuyện cũ → search_history.\n"
        "- Quy trình / playbook khớp skill → use_skill(slug=…) rồi làm theo.\n"
        "- Chuỗi nhiều bước (thu thập→xử lý→kiểm chứng) → run_workflow(slug, input).\n"
        "- Lưu ghi chú dài vào wiki → ingest; tìm/đọc wiki → wiki_search / wiki_read; "
        "tóm tắt ngày → wiki_digest.\n"
        "- Mục tiêu dài hơi trong chat ('nhớ làm…', 'đang làm…', 'xong…') → goals.\n"
        "- Tool output bị nén (có marker ⟦tc:…⟧) mà cần chi tiết → expand_tool_result.\n"
        "- Admin: 'ai vừa nhắn' / danh bạ / đặt tên → contacts; gửi tin cho alias "
        "(chọn bot) → send_to_contact (duyệt).\n"
        "- Hỏi về media ĐÃ TẠO ('gửi ảnh/video/nhạc mới nhất', 'ảnh vừa tạo', "
        "'trong thư viện có gì') → BẮT BUỘC gọi tool library_media (kind=image/video/music). "
        "LƯU Ý CỰC KỲ QUAN TRỌNG: Khi user nhắc đến 'thư viện', 'ảnh mới nhất', họ ĐANG NÓI TỚI thư viện ảnh do AI tạo ra trên máy chủ, KHÔNG PHẢI thư viện iCloud hay Google Photos trên điện thoại của họ! TUYỆT ĐỐI KHÔNG được trả lời là 'em không truy cập được thư viện ảnh của anh' — hãy gọi ngay tool library_media để lấy ảnh ra!\n"
        "- Mỗi việc đã có công cụ + model mặc định cấu hình sẵn — cứ gọi tool "
        "ngay, KHÔNG hỏi người dùng chọn công cụ/model.\n"
        "- Chỉ làm khác mặc định khi người dùng NÊU RÕ (vd 'vẽ bằng chatgpt', "
        "'video chất lượng đẹp').\n"
        "- Một yêu cầu = một nhánh chính; đừng gọi nhiều tool tạo media cho "
        "cùng một yêu cầu.")
    return "\n\n".join(parts)


def _finalize(user_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Attach ask-choices metadata; strip control blocks; P0#5 filter media URLs."""
    try:
        result = ask_choices.apply_to_result(result, user_id)
    except Exception:
        pass
    # LLM/tool output = untrusted — chặn SSRF trước khi bot channel fetch/gửi.
    try:
        from services import net_guard
        if isinstance(result, dict):
            result = net_guard.filter_agent_output(result)
    except Exception as exc:
        logger.warning("agent: filter_agent_output failed: %s", exc)
    return result if isinstance(result, dict) else {"text": str(result or "")}


def _get_history(user_id: str) -> list[dict[str, Any]]:
    """Load durable session history (fallback to in-process cache)."""
    if sess.is_enabled():
        try:
            loaded = sess.load_history(user_id)
            if loaded:
                _history[user_id] = loaded
                return _history[user_id]
        except Exception as exc:
            logger.warning("agent: load session failed: %s", exc)
    return _history.setdefault(user_id, [])


def _persist_history(user_id: str, hist: list[dict[str, Any]]) -> None:
    """Write history + searchable turns; compact when long."""
    _history[user_id] = list(hist)
    if not sess.is_enabled():
        return
    try:
        # Log the latest exchange into FTS (user then assistant when available)
        if len(hist) >= 2 and hist[-1].get("role") == "assistant" and hist[-2].get("role") == "user":
            sess.append_turn(user_id, "user", str(hist[-2].get("content") or ""))
            sess.append_turn(user_id, "assistant", str(hist[-1].get("content") or ""))
        elif hist:
            last = hist[-1]
            sess.append_turn(user_id, str(last.get("role") or ""), str(last.get("content") or ""))
        new_hist = compact.maybe_compact(user_id, hist)
        if new_hist is not None:
            hist[:] = new_hist
            _history[user_id] = list(hist)
        else:
            sess.save_history(user_id, hist)
    except Exception as exc:
        logger.warning("agent: persist session failed: %s", exc)


def _classify_reply(text: str) -> Optional[str]:
    """Return 'always' | 'once' | 'deny' | None for a short confirmation reply."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if any(k in t for k in _APPROVE_ALWAYS):
        return "always"
    if any(t == k or t.startswith(k + " ") or t.startswith(k + ",") for k in _DENY):
        return "deny"
    if any(t == k or t.startswith(k + " ") or t.startswith(k + ",") or t.endswith(" " + k) for k in _APPROVE_ONCE):
        return "once"
    return None


def _execute(cap: "caps.Capability", args: dict, user_id: str, *, user_text: str = "",
             auto_approve: bool = False, is_admin: bool = False) -> dict:
    # user_text = câu gốc lượt này → handler cần đối chiếu (vd send_to_contact
    # kiểm tra người dùng có thật sự nêu kênh không, không tin platform LLM đoán).
    # auto_approve=True (chạy tự động: nhắc theo lịch, autonomy) → handler BỎ hỏi
    # tương tác (vd menu chọn model vẽ) mà dùng mặc định luôn.
    ctx = {"user_id": user_id, "user_message": user_text,
           "auto_approve": auto_approve, "is_admin": is_admin}
    risk = str(getattr(cap, "risk", "") or "").lower()
    try:
        raw = cap.handler(args, ctx)
    except Exception as exc:  # report, never crash the turn
        logger.exception("agent: capability %s failed", cap.name)
        try:
            if risk == "change":
                approval_gate.log_event(
                    "execute_error", user_id, cap.name,
                    summary=str(exc)[:200],
                )
        except Exception:
            pass
        return {"text": f"Em gặp lỗi khi {cap.name} 😥: {str(exc)[:150]}. Anh/chị muốn em thử lại không?"}
    # P2#12: audit append-only mọi hành động CHANGE (kể cả auto-approve)
    try:
        if risk == "change":
            summary = approval_gate.summarize_action(
                cap.name, args if isinstance(args, dict) else {},
                getattr(cap, "description", "") or "",
            )
            approval_gate.log_event(
                "execute_change", user_id, cap.name, summary=summary,
            )
    except Exception as exc:
        logger.warning("agent: audit log failed: %s", exc)
    # TokenJuice-style: compact large tool text before it hits the model context.
    # expand_tool_result itself is never compressed (would hide the full payload).
    if cap.name == "expand_tool_result":
        out = raw if isinstance(raw, dict) else {"text": str(raw)}
    else:
        try:
            out = tool_compress.maybe_compress_result(
                raw if isinstance(raw, dict) else {"text": str(raw)},
                tool_name=cap.name,
            )
        except Exception as exc:
            logger.warning("agent: tool_compress failed: %s", exc)
            out = raw if isinstance(raw, dict) else {"text": str(raw)}
    # P1#7: redact secret/PII trong tool result trước khi vào context
    try:
        from services.privacy_gate import redact_text
        if isinstance(out, dict) and isinstance(out.get("text"), str) and out["text"]:
            out = dict(out)
            out["text"] = redact_text(out["text"], session_id=f"agent:{user_id}")
    except Exception:
        pass
    return out


def orchestrate(user_text: str, user_id: str,
                allow: set[str] | None = None,
                ha_fastpath: bool = True,
                model: str | None = None,
                auto_approve: bool = False,
                is_admin: bool = False) -> dict[str, Any]:
    """`allow` = tập nhóm chức năng threadID này được phép (None = tất cả). Lọc
    tool schema + chặn dispatch theo nhóm để giới hạn chức năng cho từng người.

    `ha_fastpath` = cài đặt RIÊNG từng bot/tài khoản (Telegram/Zalo): lệnh nhà
    thông minh rõ ràng được thực thi cục bộ ngay — không vòng qua provider.

    `model` = override model (vd. per-admin ai_model); trống → model_hints/default.

    FIX5: cả lượt (load lịch sử → LLM/tool → ghi lịch sử) chạy dưới 1 khoá
    riêng theo user_id — 2 luồng cùng user (vd chat thường + reminder task bắn
    trùng giờ) không còn ghi đè lịch sử của nhau.

    Lượt chạy có TRẦN THỜI GIAN. Kênh chat (Zalo/Telegram/email) gọi thẳng hàm
    này trong tiến trình và không có timeout nào ở trên: một lượt treo là bot
    câm vĩnh viễn — không trả lời, không báo lỗi, và mọi tin sau của cùng người
    còn kẹt luôn vì khoá lịch sử không bao giờ được nhả.
    """
    lock = _user_history_lock(user_id)
    if not lock.acquire(timeout=_LOCK_WAIT_S):
        logger.warning({"event": "orchestrate_lock_timeout",
                        "user_id": str(user_id)[:40], "waited_s": _LOCK_WAIT_S})
        return {"text": "Em còn đang xử lý tin trước của anh/chị, "
                        "chờ em chút rồi nhắn lại giúp em ạ 🙏"}

    def _run() -> dict[str, Any]:
        try:
            return _orchestrate_locked(
                user_text, user_id, allow=allow, ha_fastpath=ha_fastpath,
                model=model, auto_approve=auto_approve, is_admin=is_admin,
            )
        finally:
            # Khoá do CHÍNH thread chạy thân hàm nhả. Nếu hết giờ mà bên ngoài
            # tự nhả thì thread này vẫn đang ghi lịch sử → hỏng đúng thứ FIX5
            # sinh ra để bảo vệ.
            lock.release()

    import concurrent.futures
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_run)
        try:
            return future.result(timeout=_TURN_BUDGET_S)
        except concurrent.futures.TimeoutError:
            logger.warning({"event": "orchestrate_turn_timeout",
                            "user_id": str(user_id)[:40], "budget_s": _TURN_BUDGET_S})
            # Bỏ lượt này lại chạy nền (nó sẽ tự nhả khoá) và trả lời NGAY,
            # để người dùng biết có chuyện thay vì ngồi nhìn màn hình trống.
            return {"text": "Em xử lý lâu quá nên tạm dừng ở đây ạ 😥 "
                            "Anh/chị thử hỏi lại, hoặc hỏi ngắn gọn hơn giúp em."}
    finally:
        pool.shutdown(wait=False)


def _orchestrate_locked(user_text: str, user_id: str,
                        allow: set[str] | None = None,
                        ha_fastpath: bool = True,
                        model: str | None = None,
                        auto_approve: bool = False,
                        is_admin: bool = False) -> dict[str, Any]:
    import time as _time
    t0 = _time.time()
    tools_used: list[str] = []
    steps_done = 0
    run_status = "ok"
    run_error = ""
    _override = str(model or "").strip()
    main_model = _override or _main_model("reason")

    def _journal(reply: str, *, status: str | None = None, error: str = "") -> None:
        try:
            uid = str(user_id or "")
            # Infer channel + source account from user_id prefixes used by bots
            source_kind = ""
            source_account = ""
            source_peer = ""
            if uid.startswith("zalop_"):
                source_kind = "zalop"
                rest = uid[6:]
                # zalop_{account}_{thread} or similar
                parts = rest.split("_", 1)
                source_account = parts[0] if parts else rest
                source_peer = parts[1] if len(parts) > 1 else ""
            elif uid.startswith("zalo_"):
                source_kind = "zalo"
                source_peer = uid[5:]
            elif uid.startswith("email_"):
                source_kind = "email"
                source_peer = uid[6:]
            elif uid.startswith("tg_") or uid.isdigit():
                source_kind = "tg"
                source_peer = uid[3:] if uid.startswith("tg_") else uid
            else:
                source_kind = "tg" if uid else "agent"
                source_peer = uid
            # Infer display kind + permission groups (🏠 Ảnh / Video / …) for UI
            run_kind = "agent"
            tools_set = set(tools_used or [])
            if tools_set & {"generate_image", "library_media"} and not (
                tools_set - {"generate_image", "library_media", "expand_tool_result"}
            ):
                run_kind = "image_gen"
            elif tools_set & {"generate_video"} and not (
                tools_set - {"generate_video", "expand_tool_result"}
            ):
                run_kind = "video_gen"
            groups: list[str] = []
            try:
                from services.agent.capabilities import group_of
                for t in tools_used or []:
                    g = group_of(t)
                    if g and g != "_ungrouped" and g not in groups:
                        groups.append(g)
            except Exception:
                groups = []
            run_journal.log_run(
                user_id=user_id,
                user_text=user_text,
                reply_text=reply,
                model=main_model,
                hint=run_kind,
                tools=tools_used,
                steps=steps_done,
                duration_ms=int((_time.time() - t0) * 1000),
                status=status or run_status,
                error=error or run_error,
                meta={
                    "kind": run_kind,
                    "kind_label": {
                        "image_gen": "Tạo ảnh",
                        "video_gen": "Tạo video",
                        "agent": "Agent",
                    }.get(run_kind, "Agent"),
                    "groups": groups,
                },
                source_kind=source_kind,
                source_account=source_account,
                source_peer=source_peer,
                # dest_* filled from request_context by log_run when providers set it
            )
        except Exception as exc:
            logger.debug("agent: run_journal failed: %s", exc)
        # Chốt kết quả cho skill đã dùng trong lượt này. Đây là điểm DUY NHẤT
        # biết được lượt xong hay hỏng, nên `use_skill` chỉ ghi "đã dùng" rồi để
        # đây quyết xong/hỏng (xem skill_quality.ghi_ket_qua).
        try:
            from services.agent import skill_quality as sq
            sq.ghi_ket_qua(user_id, str(status or ""), str(error or run_error or ""))
        except Exception as exc:
            logger.debug("agent: chốt điểm skill lỗi: %s", exc)

    user_text = (user_text or "").strip()
    if not user_text:
        return {"text": "Dạ anh/chị cần em giúp gì ạ? 😊"}

    # 0) Resolve a pending ask-choice (user tapped button or replied 1/2/…)
    try:
        picked = ask_choices.resolve_reply(user_id, user_text)
        if picked:
            user_text = picked
    except Exception:
        pass

    # 0a) Lệnh admin xử lý Codex account_deactivated: "xóa <email>" / "giữ <email>".
    # Chỉ khớp khi có pending deactivated cho email đó (do refresh nhiều tầng tạo),
    # nên không đụng vào chat thường.
    try:
        from services.codex_deactivated import try_resolve_admin_reply as _codex_deact_reply
        _cx = _codex_deact_reply(user_text)
        if _cx:
            return {"text": _cx}
    except Exception:
        pass

    # 0) Speech Persona wizard — deterministic, ngoài vòng LLM (0 token model).
    # Chỉ can thiệp khi user gõ trigger ('persona'…) hoặc wizard đang mở.
    try:
        from services.agent import persona as _persona
        _p_out = _persona.handle(user_id, user_text)
        if _p_out is not None:
            return _finalize(user_id, _p_out)
    except Exception as _p_exc:
        logger.warning("persona wizard: %s", _p_exc)

    # 1) Resolve a pending approval (confirming a proposed change).
    pending = approval_gate.get_pending(user_id)
    if pending is not None:
        verdict = _classify_reply(user_text)
        if verdict in ("once", "always"):
            cap = caps.get(pending["capability"])
            if verdict == "always" and cap:
                approval_gate.resolve(user_id, "always", capability=cap.name)
            else:
                approval_gate.resolve(user_id, "once", capability=(cap.name if cap else ""))
            if cap:
                tools_used.append(cap.name)
                out = _execute(cap, pending.get("args") or {}, user_id, is_admin=is_admin)
                if verdict == "always":
                    out["text"] = "Dạ, từ giờ việc này em tự làm khỏi hỏi ạ. " + out.get("text", "")
                fin = _finalize(user_id, out)
                _journal(str(fin.get("text") or ""), status="approved")
                return fin
        elif verdict == "deny":
            approval_gate.resolve(
                user_id, "deny",
                capability=str(pending.get("capability") or ""),
            )
            _journal("thôi", status="denied")
            return {"text": "Dạ thôi em không làm ạ 🙆"}
        # Not a clear yes/no → fall through and treat as a new request.
        approval_gate.clear_pending(user_id)

    hist = _get_history(user_id)
    # Snapshot for SuperContext (before this turn becomes "history").
    hist_before = list(hist)
    hist.append({"role": "user", "content": user_text})
    # Soft cap in-process; durable store keeps more until compaction.
    max_h = sess.max_history() if sess.is_enabled() else 16
    if len(hist) > max_h * 2:
        del hist[: len(hist) - max_h * 2]

    # 1.4) Đường tắt LẤY MEDIA ĐÃ TẠO: xem chú thích ở `_tat_lay_media`. Chạy
    # TRƯỚC vòng agent vì việc này xác định hoàn toàn và model nhỏ không gọi
    # được tool. Vẫn tôn trọng phân quyền nhóm như mọi tool khác.
    _tat = _tat_lay_media(user_text)
    if _tat and (allow is None or caps.group_of("library_media") in allow):
        try:
            _cap_lib = caps.get("library_media")
            _kq = (_cap_lib.handler(dict(_tat),
                                    {"user_id": user_id, "user_message": user_text,
                                     "is_admin": is_admin})
                   if _cap_lib else None)
        except Exception as exc:
            logger.warning({"event": "agent_tat_media_loi", "error": str(exc)[:150]})
            _kq = None
        if _kq:
            logger.info({"event": "agent_tat_media", "kind": _tat.get("kind"),
                         "so_luong": _tat.get("so_luong") or 1,
                         "co_media": any(_kq.get(k) for k in
                                         ("image_url", "image_urls", "video_url", "audio_url"))})
            out_t = _finalize(user_id, _kq)
            hist.append({"role": "assistant", "content": out_t.get("text") or ""})
            _persist_history(user_id, hist)
            _journal(str(out_t.get("text") or ""))
            return out_t

    # 1.45) Đường tắt TIN TỨC — không để model hỏi lại "muốn bản tin dạng nào".
    # Tin MỚI dùng MCP vn_news (tổng hợp NHIỀU BÁO); tin ngày khác dùng
    # web_search vì MCP đọc RSS nên không lọc được theo ngày.
    _loai_tin = _la_yeu_cau_tin_tuc(user_text)
    if _loai_tin and (allow is None or "web" in allow):
        _kq_ws = None
        if _loai_tin == "moi":
            # CHIA MỤC (thể thao, kinh tế, xã hội, CNTT, giáo dục, y tế, giải
            # trí, thế giới), 3 tin mỗi mục — đúng yêu cầu người dùng 01/08.
            #
            # Vì sao phải sửa ở ĐÂY: đường tắt này trả NGUYÊN VĂN kết quả MCP,
            # model không chạm vào định dạng. Nên khi người dùng yêu cầu đổi cách
            # trình bày, bot "ghi nhớ" được nhưng KHÔNG thực hiện được — lượt
            # 08:11 bot lưu đúng yêu cầu rồi lượt sau vẫn trả danh sách phẳng.
            # Ghi nhớ một điều mình không làm được thì tệ hơn là không nhớ.
            try:
                from services.mcp_client import call_mcp_tool
                # Bỏ tóm tắt: quyết định BẰNG CODE từ lời dặn, không nhờ model.
                # Đo thật 01/08: nhờ model bày lại bản tin 4819 ký tự thì nó KHÔNG
                # kịp xong trong 20 giây — lần nào cũng hết giờ rồi rơi về bản gốc,
                # nên người dùng chờ thêm 20 giây để nhận đúng thứ cũ.
                _dang = _dang_bay_tin()
                # Truyền NGUYÊN câu người dùng vào chu_de: get_news_sections tự
                # cắt từ chung ('tin tức/hôm nay') — còn lại rỗng thì digest 8
                # mục như cũ, còn lại 'bão'/'giá vàng'… thì tìm ĐÚNG chủ đề. Đo
                # thật 01/08: 'tin tức bão' trước đây rớt chủ đề, trả digest lạc.
                _tin = call_mcp_tool("get_news_sections",
                                     {"per_section": 3,
                                      "kem_tom_tat": _dang["tom_tat"],
                                      "in_dam": _dang["in_dam"],
                                      "dung_emoji": _dang["emoji"],
                                      "chi_tieng_viet": _dang["chi_viet"],
                                      "chu_de": user_text})
                logger.info({"event": "tintuc_dang_bay", **_dang})
                if not (_tin and str(_tin).strip()):
                    _tin = call_mcp_tool("get_news", {"topic": "moi_nhat", "limit": 10})
                if _tin and str(_tin).strip():
                    # KHÔNG dịch bằng model nữa: tin tiếng Anh được LỌC ngay
                    # lúc lấy (chi_tieng_viet). Đường dịch không đáng tin — đo
                    # thật 01/08: một lần xong 7,9 giây, lần sau hết giờ ở 15
                    # giây mà tiêu đề vẫn nguyên tiếng Anh.
                    _kq_ws = {"text": str(_tin).strip()}
                    logger.info({"event": "agent_tat_tintuc_mcp"})
            except Exception as exc:
                logger.warning({"event": "agent_tat_tintuc_mcp_loi", "error": str(exc)[:150]})
        if _kq_ws is None:          # ngày cụ thể, hoặc MCP hỏng → tra mạng
            try:
                _cap_ws = caps.get("web_search")
                _kq_ws = (_cap_ws.handler({"query": user_text}, {"user_id": user_id})
                          if _cap_ws else None)
            except Exception as exc:
                logger.warning({"event": "agent_tat_tintuc_loi", "error": str(exc)[:150]})
                _kq_ws = None
        if _kq_ws and str(_kq_ws.get("text") or "").strip():
            logger.info({"event": "agent_tat_tintuc", "loai": _loai_tin})
            # KHÔNG nhờ model bày lại bản tin nữa: định dạng (chia mục, gạch
            # đầu dòng, bỏ tóm tắt, không link) đã làm trọn bằng code ở trên, mà
            # bản tin lại quá dài để model kịp xử lý trong hạn chờ.
            out_n = _finalize(user_id, _kq_ws)
            hist.append({"role": "assistant", "content": out_n.get("text") or ""})
            _persist_history(user_id, hist)
            _journal(str(out_n.get("text") or ""))
            return out_n

    # 1.47) Đường tắt TẠO ẢNH / TẠO VIDEO — hiện menu chọn model NGAY.
    #
    # Gọi thẳng capability, bỏ lượt model định tuyến. Capability tự lo phần khó
    # (bung combo thành model thật, gắn giá tín dụng, hỏi tiếp thời lượng/số
    # lượng) nên đường tắt KHÔNG nhân bản logic nào — nó chỉ thay việc "nhờ model
    # đoán nên gọi tool gì" bằng một biểu thức chính quy.
    #
    # Vẫn đi qua bộ lọc chức năng theo thread (`allow`) như mọi capability khác:
    # đường tắt rút ngắn đường đi, không mở thêm quyền.
    # Hai nguồn: câu NGƯỜI gõ ("tạo video cảnh biển") và nội dung NÚT BẤM của menu
    # ("tạo video bằng model flow/veo-3.1-lite params count=1: cảnh biển"). Nút bấm
    # do chính code sinh nên phân tích chắc chắn — nhờ vậy CẢ BA bước (chọn model →
    # thời lượng → số lượng) đều ra tức thì, thay vì mỗi bước một lượt model ~10s.
    _nut = _doc_nut_menu_media(user_text)
    _yc_media = None if _nut else _la_yeu_cau_tao_media(user_text)
    if _nut or _yc_media:
        if _nut:
            _kind, _args_media = _nut
        else:
            _kind, _prompt_media = _yc_media  # type: ignore[misc]
            _args_media = {"prompt": _prompt_media}
        _cap_name = "generate_video" if _kind == "video" else "generate_image"
        _nhom = "video" if _kind == "video" else "image"
        if allow is None or _nhom in allow:
            try:
                _cap_m = caps.get(_cap_name)
                _kq_m = (_cap_m.handler(dict(_args_media),
                                        {"user_id": user_id,
                                         "user_message": user_text,
                                         "is_admin": is_admin})
                         if _cap_m else None)
            except Exception as exc:
                logger.warning({"event": "agent_tat_tao_media_loi",
                                "kind": _kind, "error": str(exc)[:150]})
                _kq_m = None
            if _kq_m and str(_kq_m.get("text") or "").strip():
                logger.info({"event": "agent_tat_tao_media", "kind": _kind,
                             "tu_nut_menu": bool(_nut),
                             "model": _args_media.get("model") or "",
                             "params": _args_media.get("params") or {}})
                out_m = _finalize(user_id, _kq_m)
                hist.append({"role": "assistant", "content": out_m.get("text") or ""})
                _persist_history(user_id, hist)
                _journal(str(out_m.get("text") or ""), status="tao_media_fastpath")
                return out_m

    # 1.48) Nút bấm menu ÂM LƯỢNG LOA → gọi thẳng `announce_on_speaker`.
    #
    # Nội dung nút do chính code sinh nên đọc lại chắc chắn. Nhờ vậy loa, âm
    # lượng, nội dung và thời điểm đi trọn vào tool — thay vì nhờ model định
    # tuyến đoán lại, vốn là chỗ lượt 02/08 nhảy qua nhảy lại giữa hai capability
    # loa rồi mất cả «loa phòng khách» lẫn «60%».
    #
    # NÚT BẤM CHÍNH LÀ LỜI DUYỆT — không hỏi duyệt lần thứ hai.
    #
    # Nội dung nút nói trọn việc: «loa nào» + âm lượng bao nhiêu % + thời điểm +
    # nội dung đọc. Người dùng đọc đúng câu đó rồi bấm, nên đây là lời đồng ý CỤ
    # THỂ HƠN câu "Em định Đọc thông báo ra loa: <nội dung>. Duyệt không ạ?".
    # Hỏi duyệt thêm một lần nữa không thêm thông tin nào, chỉ thêm một vòng.
    #
    # Không có đường lách: chuỗi này nằm trong `user_text` — thứ do NGƯỜI gửi
    # (hoặc do `ask_choices.resolve_reply` tra ra từ con số họ bấm). Tầng model
    # không đặt được gì vào đó.
    #
    # Vẫn giữ: chế độ chỉ-đọc chặn cứng, bộ lọc chức năng theo thread, và ghi
    # audit — nên đi qua `_execute` (nó ghi `execute_change`) chứ không gọi thẳng
    # handler.
    # Nút bấm menu DUYỆT BẢN SỬA SKILL → gọi thẳng `teach_skill`. Đọc lại thẳng
    # nên việc duyệt đi đúng vào skill đó; nhờ model đoán lại có thể ghi đè thân
    # một skill khác. Vẫn qua bộ lọc chức năng theo thread như mọi capability.
    _nut_sk = _doc_nut_sua_skill(user_text)
    if _nut_sk and (allow is None or caps.group_of("teach_skill") in allow):
        _cap_sk = caps.get("teach_skill")
        if _cap_sk:
            out_sk = _finalize(user_id, _execute(_cap_sk, dict(_nut_sk), user_id,
                                                 user_text=user_text, is_admin=is_admin))
            hist.append({"role": "assistant", "content": out_sk.get("text") or ""})
            _persist_history(user_id, hist)
            _journal(str(out_sk.get("text") or ""), status="sua_skill")
            return out_sk

    _nut_loa = _doc_nut_menu_loa(user_text)
    if _nut_loa and (allow is None or "tts_speaker" in allow):
        if approval_gate.is_blocked("announce_on_speaker", risk="change"):
            return {"text": "Chế độ chỉ-đọc: em không được phát ra loa ạ."}
        try:
            _cap_loa = caps.get("announce_on_speaker")
            _kq_loa = (_execute(_cap_loa, dict(_nut_loa), user_id,
                                user_text=user_text, is_admin=is_admin)
                       if _cap_loa else None)
        except Exception as exc:
            logger.warning({"event": "agent_tat_loa_loi", "error": str(exc)[:150]})
            _kq_loa = None
        if _kq_loa and str(_kq_loa.get("text") or "").strip():
            logger.info({"event": "agent_tat_loa", "loa": _nut_loa.get("speaker"),
                         "volume": _nut_loa.get("volume"),
                         "delay_minutes": _nut_loa.get("delay_minutes") or 0})
            out_l = _finalize(user_id, _kq_loa)
            hist.append({"role": "assistant", "content": out_l.get("text") or ""})
            _persist_history(user_id, hist)
            _journal(str(out_l.get("text") or ""), status="loa_fastpath")
            return out_l

    # 1.5) HA fast-path (bật/tắt RIÊNG từng bot/tài khoản qua `ha_fastpath`):
    # lệnh điều khiển / câu hỏi nhà RÕ RÀNG → xử lý CỤC BỘ ngay, KHÔNG vòng qua
    # provider — thiết bị phản ứng tức thì và chạy được cả khi không có provider
    # nào. Phần trả lời: thử nhờ model diễn đạt tự nhiên; không có provider /
    # lỗi → dùng luôn văn mẫu của fast-path.
    if ha_fastpath and (allow is None or "homeassistant" in allow):
        fp_text, fp_control = None, False
        try:
            from services.protocol.openai_v1_chat_complete import ha_local_fastpath_answer
            fp_text, fp_control = ha_local_fastpath_answer(user_text)
        except Exception as exc:
            logger.warning("agent: ha fastpath error: %s", exc)
        # Optional: gate HA control through approval (default off — instant lights).
        if (
            fp_text and fp_control
            and approval_gate.gate_ha_fastpath()
            and approval_gate.needs_approval(user_id, "control_home", risk="change")
        ):
            approval_gate.set_pending(
                user_id, "control_home", {"command": user_text}, user_text,
            )
            q = approval_gate.format_proposal(
                "control_home", {"command": user_text},
                description="Điều khiển nhà thông minh",
                label="điều khiển nhà",
            )
            out_q = _finalize(user_id, {"text": q})
            hist.append({"role": "assistant", "content": out_q.get("text") or q})
            _persist_history(user_id, hist)
            return out_q
        if fp_text and fp_control and approval_gate.is_blocked("control_home", risk="change"):
            return {"text": "Chế độ chỉ-đọc: em không được điều khiển nhà ạ."}
        if fp_text:
            logger.info("agent: ha fastpath %s -> %.120s",
                        "control" if fp_control else "answer", fp_text)
            reply = fp_text
            try:
                # Dùng model chat (thường "AI text") — giữ °C/%; burst có thể là
                # model rẻ không :text và verbalize lại.
                _phrase_model = _main_model("chat") or _main_model("burst")
                resp = call_model(_phrase_model, [
                    {"role": "system", "content": (
                        "Hệ thống nhà thông minh ĐÃ xử lý xong tin nhắn của người dùng. "
                        "Diễn đạt lại kết quả bên dưới thành MỘT câu trả lời tiếng Việt "
                        "tự nhiên, ấm áp (xưng 'em') — đúng CHÍNH XÁC nội dung kết quả, "
                        "không bịa thêm thiết bị hay số liệu, không hỏi thêm.\n"
                        "QUAN TRỌNG — GIỮ NGUYÊN ĐƠN VỊ KÝ HIỆU trong kết quả: "
                        "viết đúng °C (không viết 'độ'/'độ C'), viết % (không 'phần trăm'), "
                        "giữ km/h, kWh nếu có. Ví dụ đúng: 'khoảng 30°C, độ ẩm 79%'."
                    )},
                    # Sở thích trình bày người dùng đã dặn — đường tắt trước đây
                    # bỏ qua sạch, nên "trả lời ngắn gọn thôi" chẳng bao giờ có
                    # tác dụng với câu trả lời nhà thông minh.
                    *([{"role": "system", "content":
                        "Người dùng đã dặn cách trình bày:\n"
                        + "\n".join(f"- {x}" for x in _so_thich_trinh_bay())}]
                      if _so_thich_trinh_bay() else []),
                    {"role": "user", "content": (
                        f"Tin nhắn: {user_text}\nKết quả từ hệ thống nhà: {fp_text}")},
                    # no_smart_home: chỉ nhờ diễn đạt LẠI văn bản — tắt tích hợp HA
                    # kẻo pipeline thấy từ khóa lệnh nhà rồi THỰC THI LẦN 2.
                ], timeout=30, no_smart_home=True)
                if not resp.get("error"):
                    phrased = content_of(resp).strip()
                    if phrased:
                        reply = phrased
            except Exception as exc:  # call_model không raise, nhưng phòng hờ
                logger.info("agent: ha fastpath phrasing skipped: %s", exc)
            out = _finalize(user_id, {"text": reply})
            hist.append({"role": "assistant", "content": out.get("text") or reply})
            _persist_history(user_id, hist)
            tools_used.append("ha_fastpath")
            _journal(str(out.get("text") or reply), status="ha_fastpath")
            return out

    # Only feed the recent tail to the model (summary lives in system prompt).
    model_hist = hist[-max_h:]
    sys_prompt = _build_system_prompt(user_id, allow)
    # Speech Persona của phiên (nếu cài) — khối nén ~100 token, lưu sẵn.
    try:
        from services.agent import persona as _persona2
        _pb = _persona2.prompt_for(user_id)
        if _pb:
            sys_prompt += "\n\n" + _pb
    except Exception:
        pass
    sys_prompt = super_context.maybe_attach(
        sys_prompt, user_id, user_text, hist_before, allow=allow,
    )
    messages = [{"role": "system", "content": sys_prompt}] + list(model_hist)

    # 2) Agentic loop.
    seen_workflows: set[str] = set()  # tier-2: inject each workflow note once/turn
    for _step in range(_MAX_STEPS):
        steps_done = _step + 1
        resp = call_model(main_model, messages, tools=caps.tools_schema(allow),
                          no_smart_home=(allow is not None and "homeassistant" not in allow),
                          allowed_groups=allow, channel=caps._channel_of({"user_id": user_id}))
        if resp.get("error"):
            run_status = "error"
            run_error = str(resp.get("error") or "")[:200]
            msg_err = f"Hệ thống đang trục trặc 😥 ({resp['error']}). Anh/chị thử lại giúp em nhé."
            _journal(msg_err, status="error", error=run_error)
            return {"text": msg_err}
        msg = ((resp.get("choices") or [{}])[0].get("message")) or {}
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            reply = content_of(resp).strip() or "Dạ em chưa rõ ý, anh/chị nói lại giúp em nhé 😊"
            # (Đã GỠ bộ "hứa mà chưa làm". Nó bắt nhầm câu dẫn tự nhiên: đo thật
            # 31/07 — "tin tức hôm nay" model mở đầu "Dạ ĐỂ EM tổng hợp tin tức…"
            # rồi trả nội dung thật, nhưng guard tưởng hứa suông → nhắc lại →
            # model hoảng gọi nhầm library_media → "em lấy 3 ảnh". Ca media-fetch
            # thật sự — "gửi ảnh/video/nhạc trong thư viện" — đã được đường tắt
            # xác định `_tat_lay_media` xử lý TRƯỚC vòng model, nên guard này chỉ
            # còn tác dụng phụ. Bỏ.)
            if allow is not None and "[BLOCKED]" in reply:
                # Thread lọc hỏi chức năng bị tắt → BỎ QUA, không phản hồi gì
                # (yêu cầu 2026-07-15). Bot thấy silent=True sẽ không gửi tin.
                # PHẢI log kèm câu hỏi: đường này câm tuyệt đối, và model có
                # lúc phán nhầm ([BLOCKED] oan cho chức năng đang bật) — không
                # log thì không phân biệt được với treo/chết.
                logger.warning({"event": "agent_reply_blocked", "user_id": str(user_id)[:40],
                                "question": str(user_text)[:120]})
                if hist and hist[-1].get("role") == "user":
                    hist.pop()
                _journal("", status="blocked")
                return {"text": "", "silent": True}
            out = _finalize(user_id, {"text": reply})
            hist.append({"role": "assistant", "content": out.get("text") or reply})
            _persist_history(user_id, hist)
            _journal(str(out.get("text") or reply))
            return out

        # Append the assistant tool-call message so results can reference it.
        messages.append({"role": "assistant", "content": msg.get("content"),
                         "tool_calls": tool_calls})
        produced_media: Optional[dict] = None  # {"image_url"|"video_path"|"video_url"|"doc_path": ...}
        # Nhiều ẢNH của CHÍNH lượt này, theo thứ tự sinh ra. Tách khỏi
        # `produced_media` (dict một khoá, bị ghi đè mỗi tool) vì ảnh là món duy
        # nhất người dùng xin nhiều tấm một lúc.
        produced_images: list[str] = []
        produced_caption = "Đây ạ 🎨"
        # Câu trả lời TERMINAL (deliver_now) từ tool: gửi thẳng, không cho vòng LLM
        # kể lại — dùng khi tạo ảnh/video THẤT BẠI để không "khoe" là đã gửi.
        terminal_reply: Optional[str] = None
        # FIX2 (audit 2026-07): câu hỏi xin duyệt khi MỘT call giữa lượt cần
        # duyệt — không return ngay ở chỗ phát sinh (xem dưới) để khỏi bỏ lỡ
        # media/kết quả của các call THÀNH CÔNG trước đó trong cùng lượt.
        pending_approval_q: Optional[str] = None

        for tc in tool_calls:
            fn = (tc.get("function") or {})
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            # P2: tool runtime resolves vault refs (AI never had plaintext)
            try:
                from services.privacy_gate import resolve_secret_ref
                if isinstance(args, dict):
                    resolved = {}
                    for k, v in args.items():
                        if isinstance(v, str) and ("⟦" in v or k.lower() in {
                            "password", "passwd", "pwd", "secret", "token",
                            "api_key", "session_key", "mk", "mat_khau",
                        }):
                            resolved[k] = resolve_secret_ref(v, session_id=f"agent:{user_id}")
                        elif isinstance(v, str) and "⟦" in v:
                            resolved[k] = resolve_secret_ref(v, session_id=f"agent:{user_id}")
                        else:
                            resolved[k] = v
                    args = resolved
            except Exception:
                pass
            if name:
                tools_used.append(str(name))
            cap = caps.get(name)
            if not cap:
                result = {"text": f"(không có công cụ {name})"}
            elif name == "remember" and state.memory_contains(
                    str(args.get("fact") or ""), threshold=0.97):
                # Model đòi ghi nhớ điều ĐÃ có trong bộ nhớ (hay lôi nhầm ngữ cảnh,
                # vd thông tin SSH) → KHÔNG đề xuất/không lưu lại, chỉ xác nhận ngắn.
                result = {"text": "Dạ điều này em ghi nhớ rồi ạ 🧠, không cần lưu lại nữa."}
            elif (allow is not None and name not in caps._CORE_TOOLS
                    and caps.group_of(name) not in allow):
                # Chốt chặn tầng 2 — model KHÔNG nên gọi (đã lọc schema) nhưng nếu
                # cố gọi thì BỎ QUA im lặng theo bộ lọc chức năng của threadID.
                #
                # PHẢI ghi log: im lặng là hành vi có chủ đích, nhưng không log
                # thì nó không phân biệt được với treo/chết. Một tool thiếu
                # trong _CAP_GROUP sẽ rơi vào "_ungrouped" rồi bị chặn ở đây,
                # và triệu chứng nhìn từ ngoài y hệt bot hỏng: hỏi mà không
                # thấy trả lời, cũng chẳng có dòng log nào.
                logger.warning({"event": "agent_tool_blocked_silent", "tool": name,
                                "group": caps.group_of(name), "allow": sorted(allow)})
                if hist and hist[-1].get("role") == "user":
                    hist.pop()
                return {"text": "", "silent": True}
            elif approval_gate.is_blocked(name, risk=cap.risk):
                # FIX1 (security, audit 2026-07): readonly là CHẶN CỨNG — trước
                # đây điều kiện "not auto_approve and ..." khiến việc chạy TỰ
                # ĐỘNG theo lịch (reminders auto_approve=True) vẫn lách qua được
                # cả khi server cố tình đặt agent_approval.level=readonly. Bỏ
                # "not auto_approve" — is_blocked luôn có hiệu lực bất kể nguồn gọi.
                result = {
                    "text": (
                        f"Chế độ chỉ-đọc: em không được chạy `{name}` "
                        f"(thay đổi hệ thống). Anh/chị bật lại autonomy supervised/full nhé."
                    ),
                }
            elif approval_gate.needs_approval(user_id, name, risk=cap.risk) and (
                not auto_approve or name in approval_gate.always_confirm_names()
            ) and not caps.con_thieu_thong_tin(name, args, user_text):
                # `con_thieu_thong_tin`: việc còn thiếu thông tin thì HỎI ĐỦ TRƯỚC,
                # đừng bắt người dùng duyệt một việc họ chưa thấy hết. Lúc thiếu,
                # handler chỉ trả về câu hỏi/menu — không có tác dụng phụ nào. Chế
                # độ chỉ-đọc và bộ lọc chức năng đã chặn ở hai nhánh trên.
                # FIX1 (security, audit 2026-07): auto_approve (chạy tự động theo
                # lịch — reminders mode=task) CHỈ được phép bỏ qua màn hỏi duyệt
                # THÔNG THƯỜNG. Các tool luôn-phải-hỏi (approval_gate._ALWAYS_CONFIRM,
                # vd send_to_contact/create_automation) vẫn phải dừng chờ người
                # thật xác nhận — kể cả khi việc này chạy tự động, kẻo một tác vụ
                # định kỳ tự ý gửi tin/tạo automation mà không ai duyệt.
                # Propose + wait for approval (ASK chips + ok/luôn luôn/thôi).
                # Never put resolved secrets into approval UI — re-redact display
                display_args = dict(args)
                try:
                    from services.privacy_gate import redact_text
                    for k, v in list(display_args.items()):
                        if isinstance(v, str) and k.lower() in {
                            "password", "passwd", "pwd", "secret", "token", "api_key",
                        }:
                            display_args[k] = "⟦HIDDEN⟧"
                except Exception:
                    pass
                summary = approval_gate.summarize_action(
                    name, display_args, cap.description or "",
                )
                approval_gate.set_pending(user_id, name, args, summary)
                pending_approval_q = approval_gate.format_proposal(
                    name, display_args,
                    description=cap.description or "",
                    label=cap.label or cap.name,
                )
                # FIX2 (audit 2026-07): không return ở đây — nếu có call TRƯỚC đó
                # trong cùng lượt đã chạy xong (vd generate_image tốn phí thật),
                # kết quả/media của nó sẽ được gộp cùng câu hỏi xin duyệt này và
                # trả về SAU vòng for (xem khối `if pending_approval_q` bên dưới),
                # thay vì mất trắng vì return sớm ở đây như trước.
                break
            else:
                result = _execute(cap, args, user_id, user_text=user_text, is_admin=is_admin,
                                  auto_approve=auto_approve)

            # NHIỀU ảnh trong MỘT lượt.
            #
            # `produced_media` là dict một khoá và bị GHI ĐÈ mỗi lần gọi tool, nên
            # model vẽ 3 ảnh thì chỉ 1 tấm tới — không phải lỗi câu lệnh, mà là
            # tầng giao tin chỉ mang được một món. Nay ảnh được GOM LẠI theo thứ tự
            # sinh ra trong lượt này.
            #
            # Gom theo LƯỢT chứ không đọc "N ảnh mới nhất trong thư viện": thư viện
            # có ảnh của lượt khác và ảnh trùng nội dung khác tên, nên lấy theo
            # thời gian là gửi lẫn. Ảnh sinh trong lượt thì không có gì để lẫn.
            them = result.get("image_urls")
            if isinstance(them, list) and them:
                for u in them:
                    try:
                        from services import net_guard as _ng
                        if not _ng.is_allowed_egress_url(str(u)):
                            logger.warning("orchestrator drop unsafe image_urls=%s",
                                           str(u)[:120])
                            continue
                    except Exception:
                        continue
                    if str(u) not in produced_images:
                        produced_images.append(str(u))
                if produced_images:
                    produced_caption = result.get("text") or produced_caption
                    _ghi_so_anh(user_id, produced_images)
                    # PHẢI bật `produced_media`, không chỉ gom vào danh sách.
                    #
                    # Cổng giao media ở dưới là `if produced_media:` — mà biến đó
                    # CHỈ được đặt trong vòng lặp khoá `image_url` (SỐ ÍT). Tool
                    # trả riêng `image_urls` (số nhiều) — đúng cái `library_media`
                    # làm khi xin 3 ảnh — thì `produced_media` vẫn None, cổng
                    # không mở, và lượt chạy rơi xuống nhánh "để model tự viết câu
                    # trả lời từ kết quả tool". Model thấy tool đã trả 3 URL nên
                    # viết "Dạ 3 ảnh mới nhất đây anh nha 😊" — câu đó về tới người
                    # dùng KHÔNG kèm ảnh nào.
                    #
                    # Đo thật 2026-07-30 (Zalo cá nhân, "Gửi 3 ảnh mới nhất trong
                    # thư viện"): model gọi đúng `library_media{so_luong:3}`,
                    # handler trả đúng 3 URL, mà `orchestrate` ra `['text']` —
                    # không có image_url lẫn image_urls. Người dùng hỏi "Ảnh đâu"
                    # hai lần, bot khẳng định đã gửi cả hai lần.
                    #
                    # Giữ tấm ĐẦU ở đây cũng để kênh nào chưa đọc `image_urls`
                    # (Zalo Bot cũ) vẫn gửi được một tấm chứ không gửi rỗng.
                    if not produced_media:
                        produced_media = {"image_url": produced_images[0]}

            for media_key in ("image_url", "video_path", "video_url", "audio_url", "audio_path", "doc_path"):
                if not result.get(media_key):
                    continue
                # P0#5: tool/model media — chỉ giữ URL/path được phép egress.
                try:
                    from services import net_guard as _ng
                    val = result[media_key]
                    if media_key.endswith("_url"):
                        if not _ng.is_allowed_egress_url(str(val)):
                            logger.warning("orchestrator drop unsafe %s=%s",
                                           media_key, str(val)[:120])
                            continue
                    elif media_key.endswith("_path"):
                        if not _ng.is_allowed_media_path(str(val)):
                            logger.warning("orchestrator drop unsafe %s=%s",
                                           media_key, str(val)[:120])
                            continue
                except Exception as exc:
                    logger.warning("orchestrator media guard: %s", exc)
                    continue
                if media_key == "image_url":
                    # Vẽ 3 ảnh = 3 lần gọi tool. Bản cũ ghi đè `produced_media`
                    # mỗi lần nên chỉ tấm CUỐI sống sót, còn hai tấm kia đã tốn
                    # phí sinh ra rồi bị bỏ im lặng. Gom lại theo thứ tự vẽ.
                    if str(val) not in produced_images:
                        produced_images.append(str(val))
                        _ghi_so_anh(user_id, [str(val)])
                    # Giữ tấm ĐẦU ở `produced_media` để kênh nào chưa hiểu
                    # `image_urls` vẫn gửi được một ảnh, không thành gửi rỗng.
                    if not produced_media:
                        produced_media = {media_key: produced_images[0]}
                else:
                    produced_media = {media_key: result[media_key]}
                    # Ghi sổ CẢ video/nhạc theo người (cùng sổ với ảnh; người đọc
                    # lọc theo đuôi tệp). Không ghi thì "gửi video ANH tạo" không
                    # bao giờ trả lời được — sổ chỉ có ảnh.
                    if media_key.startswith(("video_", "audio_")):
                        _ghi_so_anh(user_id, [str(result[media_key])])
                produced_caption = result.get("text") or "Đây ạ 🎨"
                break
            # Nhiều video một lượt (Flow x2/x3/x4) — ghi sổ từng cái.
            for _k in ("video_paths", "video_urls"):
                _ds = result.get(_k)
                if isinstance(_ds, list) and _ds:
                    _ghi_so_anh(user_id, [str(x) for x in _ds if x])
            # Tool báo THẤT BẠI (không có media) nhưng muốn trả câu thật ngay:
            # giữ lại để gửi thẳng, chặn vòng LLM bịa "đã gửi ảnh ở trên".
            if not produced_media and result.get("deliver_now"):
                terminal_reply = str(result.get("text") or "").strip() or None
            content = result.get("text", "")
            # Redact secret/PII trong tool result trước khi đưa lại context LLM
            # (OWASP LLM02/LLM07 — tool output có thể chứa token/cookie).
            try:
                from services.privacy_gate import redact_text
                if isinstance(content, str) and content:
                    content = redact_text(content, session_id=f"agent:{user_id}")
            except Exception:
                pass
            # Tier-2 workflow note: procedural guidance costs tokens only when
            # the capability is actually used (first use per turn).
            if cap and cap.workflow and cap.name not in seen_workflows:
                seen_workflows.add(cap.name)
                content += f"\n\n[Quy trình {cap.name}]: {cap.workflow}"
            messages.append({"role": "tool", "tool_call_id": tc.get("id"),
                             "content": content})

        # FIX2 (audit 2026-07): một call giữa lượt cần xin duyệt (break ở trên)
        # → gộp media/câu trả lời của các call THÀNH CÔNG trước đó (đã tốn phí
        # thật, vd generate_image) với câu hỏi xin duyệt, trả về LUÔN — không
        # để mất kết quả đã tạo ra chỉ vì phải dừng hỏi duyệt call sau.
        if pending_approval_q:
            base_text = produced_caption if produced_media else (terminal_reply or "")
            combo_text = (
                f"{base_text}\n\n{pending_approval_q}" if base_text else pending_approval_q
            )
            out_q = _finalize(user_id, {"text": combo_text, **(produced_media or {}),
                                        **_nhieu_anh(produced_images)})
            hist.append({"role": "assistant", "content": out_q.get("text") or combo_text})
            _persist_history(user_id, hist)
            _journal(str(out_q.get("text") or combo_text), status="awaiting_approval")
            return out_q
        # If a capability produced media, deliver it now (the media is the answer).
        #
        # Điều kiện phải xét CẢ `produced_images`: có ảnh mà cổng đóng thì lượt
        # chạy rơi xuống nhánh để model tự kể lại, và ảnh đã tạo ra bị bỏ im lặng
        # (xem chú thích ở chỗ gom `image_urls`). Đây là chốt phòng hai lớp —
        # nhánh trên đã đặt `produced_media`, nhưng bất kỳ đường nào sau này chỉ
        # đổ vào `produced_images` cũng không được rơi vào đúng cái bẫy đó nữa.
        if produced_media or produced_images:
            text = produced_caption
            out_m = _finalize(user_id, {"text": text, **produced_media,
                                        **_nhieu_anh(produced_images)})
            hist.append({"role": "assistant", "content": out_m.get("text") or text})
            _persist_history(user_id, hist)
            _journal(str(out_m.get("text") or text), status="media")
            return out_m
        # Tạo ảnh/video/nhạc THẤT BẠI (deliver_now) → gửi thẳng câu thật, KHÔNG để
        # LLM kể lại là "đã gửi ở trên" khi thực ra chưa tạo được gì.
        if terminal_reply:
            out_t = _finalize(user_id, {"text": terminal_reply})
            hist.append({"role": "assistant", "content": out_t.get("text") or terminal_reply})
            _persist_history(user_id, hist)
            _journal(str(out_t.get("text") or terminal_reply), status="tool_final")
            return out_t
        # else loop: let the model integrate the tool results into a natural reply.

    # Ran out of steps.
    msg_slow = "Em xử lý hơi lâu, anh/chị thử hỏi lại gọn hơn giúp em nhé 😊"
    _journal(msg_slow, status="max_steps")
    return {"text": msg_slow}
