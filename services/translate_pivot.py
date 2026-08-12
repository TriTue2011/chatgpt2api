"""Trục dịch quanh LLM — gửi tiếng Anh đi, nhận tiếng Việt về.

Việc này làm ĐÚNG MỘT CHỖ: ``_dispatch`` trong
``services/protocol/openai_v1_chat_complete.py`` — cửa duy nhất mà mọi provider
(chatgpt free, codex, gemini, claude, custom…) đi qua để chạm model thật.

**Vì sao không đặt sớm hơn (ở ``handle``).** Trước ``_dispatch`` có cả một tầng
xử lý TIẾNG VIỆT chạy trên chính chữ người dùng gõ: nhận lệnh nhà thông minh
(``_ha_local_intent``), thời tiết, âm lịch, bão, nhánh Agent, định tuyến kỹ
năng. Dịch sang tiếng Anh trước những bước đó là tắt sạch chúng — "bật đèn
phòng khách" thành "turn on the living room light" thì không khớp mẫu nào nữa.
Đặt ở ``_dispatch`` nghĩa là: mọi logic tiếng Việt vẫn chạy trên chữ gốc, chỉ
phần THẬT SỰ bay lên model mới là tiếng Anh.

Ba việc của trục này:

1. Dịch nội dung mọi tin (system / user / assistant) sang tiếng Anh.
2. Chèn một tin ``system`` TIẾNG ANH dặn model luôn trả lời bằng tiếng Việt.
   Tin này chèn SAU khi dịch nên bản thân nó không bị dịch.
3. Phản hồi về: nhận diện ngôn ngữ, không phải tiếng Việt thì dịch về tiếng
   Việt. Model tuân lệnh ở bước 2 thì bước này không tốn gì (đã là ``vi``).

Năm loại request KHÔNG đi qua trục — dịch vào là hỏng, không phải "kém đi":

* có ``tools``: tên hàm và tham số là hợp đồng máy-với-máy; hơn nữa tên thiết
  bị Home Assistant là tiếng Việt, dịch đi thì gọi hàm trượt entity.
* có ``response_format`` / JSON schema: khoá JSON bị dịch là client hết parse.
* có tin ``role="tool"`` hoặc ``tool_calls``: cùng lý do trên.
* có ảnh: đường vision trả JSON cho Home Assistant (xem ``response_format``).
* có cờ :data:`NOI_BO`: lượt gọi NỘI BỘ của pipeline code (architect lập kế
  hoạch, reviewer soi code, editor sửa theo góp ý). Những lời nhắc đó nhúng code
  THÔ — ``_PIPELINE_REVIEWER_PROMPT`` ghép thẳng ``=== CODE ===\\n{code}`` không
  bọc ``` — mà ``translate_service.translate`` chỉ bảo vệ khối mã CÓ dấu huyền.
  Không có cờ này thì bật trục là code bị dịch thành văn xuôi và cả nhánh
  pipeline hỏng lặng lẽ: reviewer vẫn trả lời, chỉ là trả lời về một đoạn rác.

Fail-open tuyệt đối: máy chủ dịch chết, timeout, trả rác → request đi nguyên
văn như khi chưa có tính năng này. Một dịch vụ dịch hỏng không được phép làm
trợ lý câm.

Bật: ``translate_pivot_enabled: true`` + ``translate_url`` (xem
``services/config.py``). Mặc định tắt.
"""
from __future__ import annotations

import logging
from typing import Any, Iterator

from services import translate_service as ts
from services.config import config

logger = logging.getLogger(__name__)

# Dặn model trả lời tiếng Việt. Viết bằng TIẾNG ANH theo yêu cầu: cả gói gửi lên
# model là tiếng Anh, kể cả câu dặn này.
LOI_DAN_TV = (
    "Always respond in Vietnamese (Tiếng Việt). No matter what language this "
    "conversation is written in, your entire reply must be written in "
    "Vietnamese, using natural everyday Vietnamese."
)
#: Đoạn dùng để nhận ra "tin dặn đã chèn rồi" — `_dispatch` bị gọi lại nhiều lần
#: cho cùng một danh sách tin (vòng chạy lại của MCP, fallback provider). Thiếu
#: cái này là mỗi lượt chạy lại dịch đè lên bản đã dịch và chèn thêm một tin dặn.
#:
#: Cố ý dùng CHÍNH câu dặn làm dấu, không dùng token nội bộ kiểu
#: ``[[c2a-vi-out]]``: token đó nằm trong lời nhắc nên model ĐỌC ĐƯỢC, và không
#: có lý do gì để model phải thấy rác nội bộ của gateway (model yếu còn nhại nó
#: ra câu trả lời). Câu dặn là chuỗi tiếng Anh dài, cố định — không nội dung nào
#: của người dùng trùng được.
DAU_NHAN = LOI_DAN_TV[:60]

#: Khoá cắm vào ``body`` để nói "đây là lượt gọi NỘI BỘ, đừng dịch". Dùng tiền tố
#: ``_`` như mọi khoá meta khác của body (``_request_id``, ``_via_model``,
#: ``_response_format_meta``) — client không bao giờ gửi khoá kiểu này lên.
NOI_BO = "_c2a_noi_bo"

_VAI_DICH = ("system", "user", "assistant")


class Truc:
    """Ngữ cảnh một lượt dịch. ``nguon`` = ngôn ngữ gốc đã nhận diện."""

    __slots__ = ("nguon", "da_dich")

    def __init__(self, nguon: str = "", da_dich: bool = False) -> None:
        self.nguon = nguon
        self.da_dich = da_dich


def dang_bat() -> bool:
    return bool(config.translate_pivot_enabled and ts.is_configured())


def _ly_do_bo_qua(messages: list[dict[str, Any]],
                  tools: list[dict[str, Any]] | None,
                  body: dict[str, Any] | None) -> str:
    if tools:
        return "tools"
    if isinstance(body, dict) and body.get(NOI_BO):
        return "noi_bo"
    try:
        from services.protocol.response_format import wants_structured_output
        if wants_structured_output(body if isinstance(body, dict) else None):
            return "structured_output"
    except Exception:
        pass
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        if str(m.get("role") or "") in ("tool", "function") or m.get("tool_calls"):
            return "tool_messages"
        noi_dung = m.get("content")
        if isinstance(noi_dung, list):
            for p in noi_dung:
                if isinstance(p, dict) and str(p.get("type") or "") in (
                        "image_url", "input_image", "image"):
                    return "images"
    return ""


def _da_chen_loi_dan(messages: list[dict[str, Any]]) -> bool:
    for m in messages or []:
        if isinstance(m, dict) and DAU_NHAN in str(m.get("content") or ""):
            return True
    return False


def _thu_chu(messages: list[dict[str, Any]]) -> list[tuple[int, int | None, str]]:
    """Liệt kê mọi đoạn chữ dịch được: (chỉ số tin, chỉ số phần | None, chữ).

    ``None`` = ``content`` là chuỗi; số = chỉ số phần trong ``content`` dạng
    danh sách (``{"type": "text", "text": ...}``).
    """
    ra: list[tuple[int, int | None, str]] = []
    for i, m in enumerate(messages or []):
        if not isinstance(m, dict) or str(m.get("role") or "") not in _VAI_DICH:
            continue
        noi_dung = m.get("content")
        if isinstance(noi_dung, str):
            if noi_dung.strip():
                ra.append((i, None, noi_dung))
        elif isinstance(noi_dung, list):
            for j, p in enumerate(noi_dung):
                if isinstance(p, dict) and str(p.get("type") or "") == "text":
                    chu = str(p.get("text") or "")
                    if chu.strip():
                        ra.append((i, j, chu))
    return ra


def _dat_chu(messages: list[dict[str, Any]], vi_tri: tuple[int, int | None, str],
             chu_moi: str) -> None:
    i, j, _ = vi_tri
    if j is None:
        messages[i]["content"] = chu_moi
    else:
        messages[i]["content"][j]["text"] = chu_moi


def _chen_loi_dan(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chèn tin dặn "trả lời tiếng Việt" SAU các tin system đầu danh sách.

    Cùng nếp với ``response_format.inject_response_format_prompt``: tin dặn của
    Home Assistant / persona phải giữ vị trí đầu.
    """
    tin = {"role": "system", "content": LOI_DAN_TV}
    chen_tai = 0
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "system":
            chen_tai = i + 1
        else:
            break
    ra = list(messages)
    ra.insert(chen_tai, tin)
    return ra


def dich_truoc_khi_gui(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    body: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], Truc | None]:
    """Trả (danh sách tin để gửi, ngữ cảnh trục | None nếu không dùng trục).

    Không bao giờ raise. Danh sách tin gốc không bị sửa tại chỗ khi có dịch:
    hàm dựng bản sao nông (copy từng tin có đổi chữ) để lịch sử hội thoại mà
    tầng trên đang giữ vẫn là TIẾNG VIỆT — người dùng đọc lại lịch sử phải thấy
    chữ mình gõ, không phải bản dịch.
    """
    if not dang_bat():
        return messages, None
    ly_do = _ly_do_bo_qua(messages or [], tools, body)
    if ly_do:
        logger.info({"event": "translate_pivot_skip", "reason": ly_do})
        return messages, None
    if _da_chen_loi_dan(messages or []):
        # Lượt chạy lại: đã dịch + đã chèn ở lần trước, chỉ giữ đường về.
        return messages, Truc(nguon="", da_dich=True)

    cho = _thu_chu(messages or [])
    if not cho:
        return messages, None
    try:
        nguon, _ = ts.detect("\n\n".join(c[2] for c in cho)[:5000])
    except ts.LoiDich as exc:
        logger.warning({"event": "translate_pivot_detect_fail", "error": str(exc)[:200]})
        return messages, None

    ban_sao = [dict(m) if isinstance(m, dict) else m for m in (messages or [])]
    for i, m in enumerate(ban_sao):
        if isinstance(m, dict) and isinstance(m.get("content"), list):
            ban_sao[i]["content"] = [dict(p) if isinstance(p, dict) else p
                                     for p in m["content"]]
    da_dich = False
    if nguon != ts.EN:
        try:
            ket = ts.translate_batch([c[2] for c in cho], ts.EN, nguon or "auto")
        except ts.LoiDich as exc:
            logger.warning({"event": "translate_pivot_req_fail", "error": str(exc)[:200]})
            return messages, None
        for pos, c in enumerate(cho):
            _dat_chu(ban_sao, c, ket[pos])
        da_dich = True

    ra = _chen_loi_dan(ban_sao)
    logger.info({"event": "translate_pivot_request", "source": nguon or "auto",
                 "translated": da_dich, "segments": len(cho)})
    return ra, Truc(nguon=nguon, da_dich=da_dich)


def dich_lai_phan_hoi(result: Any, truc: Truc | None) -> Any:
    """Phản hồi không phải tiếng Việt → dịch về tiếng Việt. Nhận cả dict và stream."""
    if truc is None:
        return result
    if isinstance(result, dict):
        return _dich_dict(result)
    if hasattr(result, "__iter__"):
        return _dich_stream(result)
    return result


def _ve_viet(text: str) -> str | None:
    """Dịch về tiếng Việt. None = không cần dịch (đã là tiếng Việt) hoặc lỗi."""
    if not (text or "").strip():
        return None
    try:
        ma, _ = ts.detect(text[:5000])
        if ma == ts.VI or not ma:
            return None
        ra = ts.translate(text, ts.VI, ma)
    except ts.LoiDich as exc:
        logger.warning({"event": "translate_pivot_resp_fail", "error": str(exc)[:200]})
        return None
    logger.info({"event": "translate_pivot_response", "from": ma})
    return ra or None


def _dich_dict(result: dict[str, Any]) -> dict[str, Any]:
    for ch in (result.get("choices") or []):
        if not isinstance(ch, dict):
            continue
        msg = ch.get("message")
        if not isinstance(msg, dict) or msg.get("tool_calls"):
            continue
        chu = msg.get("content")
        if isinstance(chu, str):
            moi = _ve_viet(chu)
            if moi:
                msg["content"] = moi
    return result


#: Không có ngắt đoạn nào mà đã gom quá ngần này ký tự thì vẫn xả. Một câu trả
#: lời dài liền mạch (không dòng trống) nếu chờ tới hết là bằng gom cả stream —
#: đúng cái đang muốn bỏ.
TRAN_KHOI = 1200


def _dang_mo_fence(s: str) -> bool:
    """Đang ở giữa một khối mã chưa đóng. Cắt ngang khối mã là dịch một nửa khối
    rồi ghép với nửa kia — vỡ cả khối."""
    return (s.count("```") % 2) == 1


def _cat_khoi(buf: str) -> tuple[str | None, str]:
    """Tách phần ĐÃ hoàn chỉnh khỏi phần còn đang tới → (khối | None, phần dư).

    Ranh giới là dòng trống (hết đoạn văn / hết mục / hết bảng): đủ ngữ cảnh cho
    dịch máy, mà vẫn đủ nhỏ để người dùng thấy chữ chạy.
    """
    # Xét TỪNG điểm ngắt, bỏ qua điểm nằm TRONG khối mã. Kiểm `_dang_mo_fence`
    # trên cả `buf` là sai: khối mã ĐÃ ĐÓNG cho số ``` chẵn nên qua cửa, rồi dòng
    # trống bên trong nó vẫn bị cắt — vỡ đúng cái đang muốn giữ.
    tim = 0
    while True:
        vt = buf.find("\n\n", tim)
        if vt < 0:
            break
        if not _dang_mo_fence(buf[:vt]):
            return buf[:vt + 2], buf[vt + 2:]
        tim = vt + 2
    if len(buf) >= TRAN_KHOI and not _dang_mo_fence(buf):
        # Không có dòng trống: cắt ở lần xuống dòng cuối, không có thì cắt ở dấu
        # kết câu cuối. Cắt giữa câu là dịch máy nhận một mảnh vô nghĩa.
        for dau in ("\n", ". ", "! ", "? "):
            vt = buf.rfind(dau)
            if vt > 0 and not _dang_mo_fence(buf[:vt]):
                return buf[:vt + len(dau)], buf[vt + len(dau):]
    return None, buf


def _chunk_chu(mau: dict[str, Any], chu: str) -> dict[str, Any]:
    """Dựng một chunk chỉ mang chữ, giữ nguyên id/model/created của stream gốc."""
    return {**mau, "choices": [{"index": 0, "delta": {"content": chu},
                                "finish_reason": None}]}


def _dich_stream(it: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Dịch theo TỪNG KHỐI đã hoàn chỉnh, phát ngay khi dịch xong.

    Vì sao không dịch từng chunk: một chunk là vài ký tự, dịch máy cần đủ câu mới
    ra nghĩa. Vì sao không gom cả stream rồi dịch một lần (bản đầu tôi làm vậy):
    người dùng ngồi nhìn màn hình trống suốt thời gian model sinh chữ, rồi cả câu
    trả lời đổ ra một lượt. Ranh giới khối là DÒNG TRỐNG, nên chữ vẫn chạy theo
    từng đoạn văn.

    Chunk nào mang thứ khác ngoài chữ (role, tool_calls, finish_reason, usage)
    được phát lại nguyên vẹn — chỉ phần ``delta.content`` bị gom lại để dịch.
    Gặp ``tool_calls`` thì từ đó trở đi cho qua thẳng, không dịch nữa.
    """
    mau: dict[str, Any] = {}
    buf = ""
    cho_qua = False

    def _xa(s: str) -> Iterator[dict[str, Any]]:
        if not s:
            return
        moi = _ve_viet(s)
        yield _chunk_chu(mau, moi if moi is not None else s)

    for chunk in it:
        if not isinstance(chunk, dict):
            yield chunk
            continue
        if not mau:
            mau = {k: v for k, v in chunk.items() if k != "choices"}
        chu = ""
        con_gi_khac = bool(chunk.get("usage"))
        for ch in (chunk.get("choices") or []):
            if not isinstance(ch, dict):
                continue
            if ch.get("finish_reason") or ch.get("message"):
                con_gi_khac = True
            delta = ch.get("delta")
            if isinstance(delta, dict):
                if delta.get("tool_calls") or delta.get("role"):
                    con_gi_khac = True
                if delta.get("tool_calls"):
                    cho_qua = True
                c = delta.get("content")
                if isinstance(c, str):
                    chu += c
                    delta["content"] = ""
        if cho_qua:
            # Đã thấy tool_calls: xả phần đang gom rồi thôi dịch từ đây.
            for x in _xa(buf):
                yield x
            buf = ""
            if chu:
                yield _chunk_chu(mau, chu)
            yield chunk
            continue
        buf += chu
        while True:
            khoi, con = _cat_khoi(buf)
            if khoi is None:
                break
            buf = con
            for x in _xa(khoi):
                yield x
        if con_gi_khac:
            # Chunk kết (finish_reason/usage) phải đi SAU phần chữ cuối.
            for x in _xa(buf):
                yield x
            buf = ""
            yield chunk
    for x in _xa(buf):
        yield x
