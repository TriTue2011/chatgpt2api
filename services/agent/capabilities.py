"""Capability registry — native tools the agent can call (NO MCP).

Each capability is an OpenAI function the main model may call. Handlers route
directly to concrete provider models via ``runtime.call_model`` and return
``{"text": str, "image_url"?: str}``.

Risk levels drive the human-in-the-loop gate in the orchestrator:
    READ    — answer/lookup; execute immediately.
    CHANGE  — mutates home/data/world; the orchestrator proposes and waits for
              the user's approval unless "always allow" was granted.

(Tool-choice ambiguity — e.g. Flow vs ChatGPT for drawing — is handled
conversationally by the model per the persona rules, not by the risk gate.)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Callable

from services.config import config
from services.agent import state
from services.agent.branches import branch_model


def _channel_of(ctx: dict | None) -> str:
    """Kênh của lượt gọi từ user_id orchestrator ('zalo_…'/'zalop_…'/còn lại =
    Telegram) — để nhánh agent đọc cài đặt RIÊNG từng kênh."""
    uid = str((ctx or {}).get("user_id") or "")
    if uid.startswith("zalop_"):
        return "zalop"
    if uid.startswith("zalo_"):
        return "zalo"
    return "tg" if uid else ""
from services.agent.runtime import (call_model, call_video, content_of,
                                    first_image_url)

logger = logging.getLogger(__name__)

READ = "read"
CHANGE = "change"


@dataclass
class Capability:
    name: str
    description: str                 # for the model / tool schema
    risk: str                       # READ | CHANGE
    handler: Callable[[dict, dict], dict]
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    label: str = ""                 # short human phrase for the persona list
    emoji: str = ""                 # icon for the persona list
    # Procedural note injected into the tool RESULT the first time the tool is
    # used in a turn (tier-2 context: workflows live here, not in the system
    # prompt, so they cost tokens only when the capability is actually used).
    workflow: str = ""

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters}}


# ── Handlers ─────────────────────────────────────────────────────────────────


def _alert_branch(branch_label: str, model: str, err: object) -> None:
    """Lỗi nhánh Agent → báo admin Tele+Zalo để debug (best-effort, theo toggle)."""
    try:
        from services.notifier import notify_admin
        notify_admin(f"⚠️ Nhánh {branch_label} lỗi — model '{model}': {str(err)[:200]}")
    except Exception:
        pass


# Người dùng NÊU RÕ công cụ → override model nhánh; không nêu → nhánh quyết.
_IMAGE_TOOL_OVERRIDE = {
    "chatgpt": "gpt-image-2", "gpt": "gpt-image-2", "dalle": "gpt-image-2",
    "dall-e": "gpt-image-2",
    "flow": "flow/auto",
    "gemini": "gma/image", "gma": "gma/image",
}

# Yêu cầu user 2026-07-26: LUÔN hỏi chọn model TRƯỚC khi vẽ/tạo video (kèm lựa
# chọn "mặc định"). Các token này = chọn nhánh mặc định → làm luôn, KHÔNG hỏi lại.
_IMAGE_DEFAULT_TOKENS = {"mặc định", "mac dinh", "macdinh", "mặcđịnh", "default", "auto"}


def _enabled_models_for(cap: str, limit: int = 6) -> list[str]:
    """ID model ĐÃ BẬT (Quản lý model) có capability `cap` ('image'|'video_gen').

    Dùng CHUNG nguồn với tab Tạo ảnh / Tạo video của web: list_models(apply_filter=
    True) đã lọc enabled_models, rồi classify_model_capability lọc theo năng lực."""
    try:
        from services.protocol.openai_v1_models import list_models
        from utils.helper import classify_model_capability
        data = (list_models(apply_filter=True) or {}).get("data") or []
    except Exception as exc:
        logger.debug("agent: enabled models (%s) lỗi: %s", cap, exc)
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in data:
        mid = str((m or {}).get("id") or "").strip()
        if not mid or mid in seen or mid.endswith(":text"):
            continue
        try:
            caps = classify_model_capability(mid) or []
        except Exception:
            caps = []
        if cap in caps:
            seen.add(mid)
            out.append(mid)
            if len(out) >= limit:
                break
    return out


def _short_model_label(mid: str) -> str:
    """Nhãn cho nút menu: giữ NGUYÊN id nếu vừa (rõ provider), quá dài mới cắt."""
    if len(mid) <= 36:
        return mid
    s = mid.split("/")[-1] if "/" in mid else mid
    return s if len(s) <= 36 else s[:35] + "…"


def _ask_media_provider(prompt: str, cap: str, *, verb: str, emoji: str) -> dict:
    """Menu chọn model TẠO ẢNH/VIDEO — CHỈ liệt kê model ĐÃ BẬT (giống tab web) +
    'Mặc định'. 'send' có TÊN model cụ thể → lượt sau handler nhận model ≠ rỗng nên
    làm luôn (không lặp). deliver_now=True: gửi thẳng menu, không cho LLM tự làm."""
    models = _enabled_models_for(cap)
    short = prompt if len(prompt) <= 60 else prompt[:59] + "…"
    lines = [f'{emoji} Anh/chị muốn {verb} "{short}" bằng model nào ạ?', "<<<ASK>>>",
             f"Mặc định (nhánh đang cài) | {verb} bằng mặc định: {prompt}"]
    for mid in models:  # ask_choices tự cắt tối đa 8 lựa chọn
        lines.append(f"{_short_model_label(mid)} | {verb} bằng model {mid}: {prompt}")
    lines.append("<<<END>>>")
    return {"text": "\n".join(lines), "deliver_now": True}


def _ask_image_provider(prompt: str) -> dict:
    return _ask_media_provider(prompt, "image", verb="vẽ", emoji="🎨")


def _fold_params_into_prompt(prompt: str, chosen: dict, spec: dict) -> str:
    """Ghép tham số đã chọn vào prompt (cho pipeline ảnh chỉ nhận text)."""
    if not chosen:
        return prompt
    labels = {p.get("key"): (p.get("label") or p.get("key")) for p in (spec.get("params") or [])}
    extra = ", ".join(f"{labels.get(k, k)} {v}" for k, v in chosen.items() if v)
    return f"{prompt} ({extra})" if extra else prompt


def _spec_call_kwargs(chosen: dict, spec: dict) -> dict:
    """chosen {key:value} → {arg:value} theo spec.params[].arg (cho call_video)."""
    argmap = {p.get("key"): (p.get("arg") or p.get("key")) for p in (spec.get("params") or [])}
    return {argmap.get(k, k): v for k, v in chosen.items() if v}


def _param_choice_menu(prompt: str, model: str, spec: dict, *, verb: str, emoji: str) -> dict | None:
    """MỘT menu chọn nhanh thông số ĐÃ HỌC: 'Mặc định' + các preset. None = không
    có gì để chọn → làm thẳng. send mang 'params k=v …' → lượt sau handler nhận
    args['params'] rồi gọi có tham số. (Per-field tuần tự = bước sau, cần test live.)"""
    params = spec.get("params") or []
    presets = spec.get("presets") or []
    defaults = {p["key"]: p.get("default") for p in params if p.get("key") and p.get("default")}
    if not presets and not defaults:
        return None
    short = prompt if len(prompt) <= 50 else prompt[:49] + "…"
    lines = [f'{emoji} {verb} "{short}" bằng {model} — chọn thông số ạ:', "<<<ASK>>>"]
    if defaults:
        dv = " ".join(f"{k}={v}" for k, v in defaults.items())
        dlabel = ", ".join(f"{k} {v}" for k, v in defaults.items())
        lines.append(f"Mặc định ({dlabel}) | {verb} '{prompt}' bằng model {model} params {dv}")
    for pr in presets:
        vals = pr.get("values") or {}
        vs = " ".join(f"{k}={v}" for k, v in vals.items())
        vlabel = ", ".join(f"{k} {v}" for k, v in vals.items())
        lines.append(f"{pr.get('label')} ({vlabel}) | {verb} '{prompt}' bằng model {model} params {vs}")
    lines.append("<<<END>>>")
    return {"text": "\n".join(lines), "deliver_now": True}


def _h_generate_image(args: dict, ctx: dict) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    explicit_model = str(args.get("model") or "").strip()
    tool = str(args.get("tool") or args.get("provider") or "").strip().lower()
    if not prompt:
        return {"text": "Anh/chị muốn em vẽ gì ạ? 🎨"}
    # LUÔN hỏi chọn model vẽ (đã bật) trước — trừ khi đã chọn model/công cụ, hoặc
    # đang CHẠY TỰ ĐỘNG (nhắc theo lịch/autonomy) thì dùng mặc định, không hỏi.
    if not explicit_model and not tool:
        if not ctx.get("auto_approve"):
            return _ask_image_provider(prompt)
        model = branch_model("image_gen", _channel_of(ctx))
    # model cụ thể (chọn từ menu) → dùng thẳng; token "mặc định/auto" → nhánh
    # image_gen quyết; tên công cụ (chatgpt/gemini/flow) → override; lạ → nhánh.
    elif explicit_model and explicit_model.lower() not in _IMAGE_DEFAULT_TOKENS:
        model = explicit_model
    elif tool and tool not in _IMAGE_DEFAULT_TOKENS:
        model = _IMAGE_TOOL_OVERRIDE.get(tool) or branch_model("image_gen", _channel_of(ctx))
    else:
        model = branch_model("image_gen", _channel_of(ctx))
    # Bot TỰ HỌC: model có spec tham số → hỏi chọn thông số (1 lần) rồi ghép vào
    # prompt. Chạy tự động (auto_approve) thì bỏ hỏi, dùng luôn.
    chosen = args.get("params") if isinstance(args.get("params"), dict) else {}
    spec = state.get_model_spec(model)
    if spec and (spec.get("params") or spec.get("presets")):
        if not chosen and not ctx.get("auto_approve"):
            menu = _param_choice_menu(prompt, model, spec, verb="vẽ", emoji="🎨")
            if menu:
                return menu
        prompt = _fold_params_into_prompt(prompt, chosen, spec)
    # Câu ngắn ("vẽ con mèo") → prompt chi tiết, như bên video.
    prompt = _mo_rong_prompt_media(prompt, "image", ctx)
    resp = call_model(model, [{"role": "user", "content": f"Vẽ: {prompt}"}],
                      timeout=320, max_tokens=600)
    # deliver_now=True ở các nhánh THẤT BẠI: trả thẳng câu thật cho người dùng,
    # KHÔNG để vòng LLM tự "kể" là đã gửi ảnh trong khi thực ra chưa có ảnh nào.
    if resp.get("error"):
        _alert_branch("Vẽ / tạo ảnh (image_gen)", model, resp["error"])
        return {"deliver_now": True,
                "text": f"Em vẽ bằng {model} bị lỗi 😥 ({resp['error']}). "
                        f"Anh/chị muốn em thử công cụ khác không (Flow/ChatGPT/Gemini)?"}
    txt = content_of(resp)
    url = first_image_url(txt)
    if url:
        return {"text": "Đây ạ 🎨", "image_url": url}
    # CẢI TIẾN: Feedback rõ ràng khi không extract được URL từ response
    if not txt or any(kw in (txt or "").lower() for kw in ("completed", "finished", "generated")):
        return {"deliver_now": True,
                "text": f"Em thử vẽ bằng {model} nhưng chưa lấy được ảnh — model này có thể "
                        f"không tạo được ảnh. Anh/chị chọn công cụ ảnh khác giúp em nhé 🔄"}
    return {"deliver_now": True,
            "text": txt or "Em chưa vẽ được ảnh, anh/chị thử mô tả rõ hơn giúp em nhé."}


def _h_generate_music(args: dict, ctx: dict) -> dict:
    """Tạo nhạc THẬT qua trình duyệt Gemini (Lyria) — trả mp4 (audio + bìa động).

    Lyria KHÔNG gọi được qua HTTP API (model chỉ trả chữ / bịa link — đo thật
    31/07), nên đi đường điều khiển trình duyệt như video Flow. Nhạc lưu dưới
    dạng mp4 vào THƯ VIỆN VIDEO, tên có tiền tố 'nhac_' để 'gửi lại nhạc' tìm
    được và phân biệt với video thường."""
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"text": "Anh/chị muốn em sáng tác bản nhạc thế nào ạ? 🎵"}

    from api.gemini_web import generate_music_via_browser
    kq = generate_music_via_browser(prompt)
    if kq.get("error"):
        loi = str(kq["error"])
        _alert_branch("Tạo nhạc (music_gen)", "gemini-web/Lyria", loi)
        # Thiếu tiện ích YouTube Music là điều kiện tài khoản, không phải bận —
        # nói rõ để chủ máy biết đường bật, đừng bảo "thử lại sau".
        if "youtube music" in loi.lower():
            return {"deliver_now": True,
                    "text": "Em chưa tạo được nhạc vì tài khoản Gemini chưa kết nối "
                            "YouTube Music 🎵. Nhờ chủ máy bật tiện ích YouTube Music "
                            "trên tài khoản Gemini một lần rồi em làm được ngay ạ."}
        return {"deliver_now": True,
                "text": f"Em tạo nhạc chưa được 😥 ({loi[:120]}). Anh/chị thử "
                        "lại sau chút giúp em nhé — Gemini đang bận."}

    # Lưu mp4 vào thư viện video (config.images_dir), tiền tố 'nhac_'.
    import base64 as _b64
    import time as _t
    from pathlib import Path
    from services.config import config as _cfg
    b64 = str(kq.get("video_b64") or "")
    tieu_de = str(kq.get("title") or "Bản nhạc")
    thu_muc = _cfg.images_dir / _t.strftime("%Y") / _t.strftime("%m") / _t.strftime("%d")
    if b64:
        try:
            raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
            data = _b64.b64decode(raw)
            thu_muc.mkdir(parents=True, exist_ok=True)
            ten = f"nhac_{int(_t.time())}.mp4"
            (thu_muc / ten).write_bytes(data)
            rel = f"{_t.strftime('%Y/%m/%d')}/{ten}"
            path = str(thu_muc / ten)
            logger.info({"event": "music_saved", "path": rel, "bytes": len(data)})
            return {"text": f"🎵 {tieu_de} — bản nhạc của anh/chị đây ạ!",
                    "video_path": path,
                    "library_url": f"{_cfg.base_url}/images/{rel}"}
        except Exception as exc:
            logger.warning("music save failed: %s", exc)
    # Không có bytes → dùng URL CDN (có thể hết hạn nhưng còn hơn không).
    url = str(kq.get("url") or "")
    if url:
        return {"text": f"🎵 {tieu_de} đây ạ!", "video_url": url}
    return {"text": "Em tạo xong nhưng không lấy được file nhạc 😥, thử lại giúp em nhé."}


_VIDEO_MODELS = {"nhanh": "flow/veo-3.1-fast", "fast": "flow/veo-3.1-fast",
                 "dep": "flow/veo-3.1-quality", "quality": "flow/veo-3.1-quality",
                 "lite": "flow/veo-3.1-lite"}

#: Câu ngắn hơn ngần này thì đáng mở rộng thành prompt chi tiết.
_NGAN_CAN_MO_RONG = 70


def _mo_rong_prompt_media(prompt: str, loai: str, ctx: dict | None = None) -> str:
    """Biến câu NGẮN của người dùng thành prompt CHI TIẾT cho máy tạo ảnh/video.

    Chủ máy yêu cầu 31/07: "có thể dùng 1 model tạo promt chi tiết từ 1 câu yêu
    cầu của tôi rồi mới đưa vào tạo video". Người dùng gõ "tạo video con mèo" —
    máy tạo video cần mô tả có chủ thể, bối cảnh, ánh sáng, góc máy, phong cách
    thì ảnh/video mới đẹp. Trước đây câu trần đó đi thẳng vào máy tạo.

    Chỉ mở rộng câu NGẮN (< 70 ký tự): câu người dùng đã tả kỹ thì giữ NGUYÊN —
    viết lại là làm sai ý họ. Lỗi/không mở rộng được → trả prompt gốc.
    """
    p = (prompt or "").strip()
    if len(p) >= _NGAN_CAN_MO_RONG:
        return p
    la_video = loai == "video"
    yeu_cau = (
        "Bạn là chuyên gia viết prompt cho máy tạo "
        + ("VIDEO" if la_video else "ẢNH") + ". Hãy mở rộng yêu cầu ngắn của "
        "người dùng thành MỘT prompt chi tiết, sinh động bằng tiếng Việt.\n"
        "- Thêm: chủ thể rõ ràng, bối cảnh, ánh sáng, màu sắc, góc máy, phong cách.\n"
        + ("- Thêm chuyển động của chủ thể và máy quay (video).\n" if la_video else "")
        + "- GIỮ ĐÚNG ý gốc, KHÔNG đổi chủ thể, KHÔNG bịa chi tiết trái ý.\n"
        "- Trả về DUY NHẤT prompt, 1 đoạn, tối đa 80 từ. Không giải thích, không "
        "gạch đầu dòng, không ngoặc kép.\n\n"
        "Yêu cầu gốc: " + p)
    try:
        model = branch_model("default", _channel_of(ctx or {})) or "cx/auto"
        resp = call_model(model, [{"role": "user", "content": yeu_cau}],
                          timeout=60, max_tokens=220)
        if resp.get("error"):
            return p
        ra = (content_of(resp) or "").strip().strip('"').strip()
        # Model đôi khi trả kèm lời dẫn — lấy đoạn dài nhất, bỏ dòng mở đầu ngắn.
        dong = [d.strip() for d in ra.splitlines() if d.strip()]
        if dong:
            ra = max(dong, key=len).strip().strip('"')
        # Combo cạn provider trả CHUỖI LỖI trong content (không phải resp['error'])
        # — đo thật 31/07: "All providers failed. Last error: no usable chatgpt
        # free account" suýt thành prompt vẽ. Nhận diện rồi giữ prompt gốc.
        _thap = ra.lower()
        if any(k in _thap for k in ("all providers failed", "no usable",
                                    "last error", "quota", "rate limit",
                                    "unauthenticated", "error:")):
            logger.warning("mở rộng prompt %s: model trả chuỗi lỗi, giữ prompt gốc", loai)
            return p
        if 15 < len(ra) <= 600:
            logger.info({"event": "media_prompt_mo_rong", "loai": loai,
                         "goc": p[:60], "moi": ra[:80]})
            return ra
    except Exception as exc:
        logger.warning("mở rộng prompt %s lỗi: %s", loai, str(exc)[:120])
    return p

# ── Bảng giá Flow (đọc từ chính giao diện Flow, chủ máy chụp 31/07/2026) ──────
# Dòng "Quá trình tạo sẽ tốn N tín dụng", tính cho MỘT video. Chọn x2/x3/x4 thì
# nhân lên theo số video. Bản TypeScript tương ứng: web/src/lib/video-model-specs.ts
# (hai bảng phải khớp nhau — web và bot cùng báo một giá).
_OMNI_TIN_DUNG = {"4": 7, "6": 10, "8": 12, "10": 15}
_FLOW_TIN_DUNG = {"flow/veo-3.1-lite": 10, "flow/veo-3.1-fast": 20,
                  "flow/veo-3.1-quality": 100}
# Model DUY NHẤT có hàng chọn thời lượng trên giao diện Flow.
_FLOW_THOI_LUONG = {"flow/omni-flash": ["4", "6", "8", "10"]}
_FLOW_SO_LUONG = [1, 2, 3, 4]


def _tin_dung_moi_video(model: str, duration: str | None = None) -> int | None:
    """Tín dụng cho MỘT video, hoặc None nếu model không tính bằng tín dụng Flow
    (Agnes, Veo trực tiếp… tiêu hạn mức tài khoản riêng — đừng bịa ra con số)."""
    m = (model or "").strip().lower()
    if m in _FLOW_THOI_LUONG:
        return _OMNI_TIN_DUNG.get(str(duration or "4"), 7)
    return _FLOW_TIN_DUNG.get(m)


def _mo_ta_chi_phi(model: str, count: int = 1, duration: str | None = None) -> str:
    """Câu THÔNG BÁO chi phí (không phải câu hỏi) để ghép vào menu và lời đáp."""
    moi = _tin_dung_moi_video(model, duration)
    if moi is None:
        return "tính vào hạn mức tài khoản"
    tong = moi * max(1, min(4, count))
    return f"{tong} tín dụng" if count <= 1 else f"{tong} tín dụng ({moi}×{count})"


def _ask_video_thoi_luong(prompt: str, model: str) -> dict:
    """Menu chọn thời lượng — CHỈ cho model thật sự có hàng đó trên Flow."""
    short = prompt if len(prompt) <= 50 else prompt[:49] + "…"
    lines = [f'🎬 Video "{short}" bằng {model} — anh/chị chọn thời lượng ạ:', "<<<ASK>>>"]
    for giay in _FLOW_THOI_LUONG[model.strip().lower()]:
        lines.append(f"{giay} giây — {_mo_ta_chi_phi(model, 1, giay)}/video | "
                     f"tạo video bằng model {model} params duration={giay}: {prompt}")
    lines.append("<<<END>>>")
    return {"text": "\n".join(lines), "deliver_now": True}


def _ask_video_so_luong(prompt: str, model: str, duration: str | None) -> dict:
    """Menu chọn số video. Mỗi dòng THÔNG BÁO tổng tín dụng phải trả."""
    short = prompt if len(prompt) <= 50 else prompt[:49] + "…"
    dur_txt = f" {duration}s" if duration else ""
    lines = [f'🎬 Video "{short}" bằng {model}{dur_txt} — anh/chị muốn mấy video ạ?',
             "<<<ASK>>>"]
    dur_kv = f" duration={duration}" if duration else ""
    for so in _FLOW_SO_LUONG:
        lines.append(f"{so} video — {_mo_ta_chi_phi(model, so, duration)} | "
                     f"tạo video bằng model {model} params count={so}{dur_kv}: {prompt}")
    lines.append("<<<END>>>")
    return {"text": "\n".join(lines), "deliver_now": True}


def _doc_thong_so_video(args: dict) -> tuple[str | None, int | None]:
    """Đọc thời lượng + số lượng từ args, chấp nhận CẢ hai đường mà tầng LLM có
    thể dùng: tham số cấp trên (duration/count/n) và gói 'params' của menu
    ('… params duration=6 count=2'). Đây là biên hệ thống — dữ liệu do LLM sinh
    ra nên phải chịu được cả hai dạng."""
    goi = args.get("params") if isinstance(args.get("params"), dict) else {}
    thoi_luong = args.get("duration") or goi.get("duration")
    so_luong = args.get("count") or args.get("n") or goi.get("count") or goi.get("n")
    try:
        so = max(1, min(4, int(so_luong))) if so_luong is not None else None
    except (TypeError, ValueError):
        so = None
    return (str(thoi_luong) if thoi_luong not in (None, "") else None), so


def _h_generate_video(args: dict, ctx: dict) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"text": "Anh/chị muốn em tạo video gì ạ? 🎬"}
    user_model = str(args.get("model") or "").strip()
    quality = str(args.get("quality") or "").strip().lower()
    # LUÔN hỏi chọn model video (đã bật) trước khi tạo — trừ khi đã chỉ định
    # model/chất lượng, hoặc đang CHẠY TỰ ĐỘNG (nhắc theo lịch) thì dùng mặc định.
    if not user_model and not quality:
        if not ctx.get("auto_approve"):
            return _ask_media_provider(prompt, "video_gen", verb="tạo video", emoji="🎬")
        model = branch_model("video_gen", _channel_of(ctx))
    elif user_model and user_model.lower() not in _IMAGE_DEFAULT_TOKENS:
        model = user_model
    else:
        model = _VIDEO_MODELS.get(quality) or branch_model("video_gen", _channel_of(ctx))

    # ── Hỏi nốt thông số người dùng chưa nêu, kèm THÔNG BÁO tín dụng ──────
    # Chỉ hỏi thứ model thật sự có: ba model Veo không có hàng chọn thời lượng
    # nên không hỏi thời lượng cho chúng. Chạy tự động thì bỏ qua, dùng mặc định.
    thoi_luong, so_luong = _doc_thong_so_video(args)
    m_low = model.strip().lower()
    if not ctx.get("auto_approve"):
        if thoi_luong is None and m_low in _FLOW_THOI_LUONG:
            return _ask_video_thoi_luong(prompt, model)
        if so_luong is None and m_low.startswith("flow/"):
            return _ask_video_so_luong(prompt, model, thoi_luong)

    # Bot TỰ HỌC: model có spec tham số → hỏi chọn (1 lần) rồi map vào kwargs.
    chosen = args.get("params") if isinstance(args.get("params"), dict) else {}
    spec = state.get_model_spec(model)
    if spec and (spec.get("params") or spec.get("presets")) and not chosen \
            and not ctx.get("auto_approve"):
        menu = _param_choice_menu(prompt, model, spec, verb="tạo video", emoji="🎬")
        if menu:
            return menu

    v_kwargs = {}
    if thoi_luong is not None:
        v_kwargs["duration"] = thoi_luong
    if so_luong is not None:
        v_kwargs["n"] = so_luong          # call_video → body["n"] → count của Flow
    for key in ("resolution", "aspect_ratio", "duration", "fps", "frame_rate",
                "num_frames", "negative_prompt", "seed", "image", "last_frame", "mode"):
        if args.get(key) is not None:
            v_kwargs[key] = args[key]
    # Tham số ĐÃ HỌC (chosen) → map theo spec.params[].arg vào kwargs (không đè
    # tham số người dùng nêu trực tiếp).
    if chosen and spec:
        for k, v in _spec_call_kwargs(chosen, spec).items():
            v_kwargs.setdefault(k, v)

    # Câu ngắn ("tạo video con mèo") → mở rộng thành prompt chi tiết trước khi
    # đưa vào máy tạo. Chạy SAU khi đã chốt model/thông số nên không làm chậm
    # phần hỏi đáp. Xem _mo_rong_prompt_media.
    prompt = _mo_rong_prompt_media(prompt, "video", ctx)
    resp = call_video(prompt, model=model, **v_kwargs)
    if resp.get("error"):
        _alert_branch("Tạo video (video_gen)", model, resp["error"])
        return {"text": f"Em tạo video bị lỗi 😥 ({resp['error']}). "
                        f"Anh/chị muốn em thử lại không?"}
    danh_sach = [d for d in (resp.get("data") or []) if isinstance(d, dict)]
    if not danh_sach:
        return {"text": "Em tạo xong nhưng không lấy được video 😥, anh/chị thử lại giúp em nhé."}

    # THÔNG BÁO tín dụng (không hỏi): giá đã trả + số dư Flow báo về.
    meta = danh_sach[0].get("metadata") or {}
    phan_gia = ""
    gia_moi = _tin_dung_moi_video(model, thoi_luong)
    if gia_moi is not None:
        phan_gia = f" — hết {gia_moi * len(danh_sach)} tín dụng"
        con_lai = meta.get("remainingCredits")
        if con_lai is not None:
            phan_gia += f", còn {con_lai}"
    loi = ("Video của anh/chị đây ạ 🎬" if len(danh_sach) == 1
           else f"{len(danh_sach)} video của anh/chị đây ạ 🎬") + phan_gia

    import base64 as _b64
    import time as _t
    from pathlib import Path
    from services.config import DATA_DIR
    vid_dir = Path(DATA_DIR) / "agent" / "media"
    duong_dan: list[str] = []
    for i, item in enumerate(danh_sach):
        b64 = str(item.get("b64_json") or "")
        if not b64:
            continue
        try:
            vid_dir.mkdir(parents=True, exist_ok=True)
            raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
            path = vid_dir / f"video_{int(_t.time())}_{i}.mp4"
            path.write_bytes(_b64.b64decode(raw))
            duong_dan.append(str(path))
        except Exception as exc:
            logger.warning("agent: save video failed: %s", exc)
    if len(duong_dan) > 1:
        return {"text": loi, "video_path": duong_dan[0], "video_paths": duong_dan}
    if duong_dan:
        return {"text": loi, "video_path": duong_dan[0]}

    # Không có bytes → dùng URL. library_url là bản đã lưu trong thư viện của ta
    # (api/veo_video.py::_luu_thu_vien), ưu tiên vì nó không hết hạn như link Flow.
    urls = [str(d.get("library_url") or d.get("url") or "") for d in danh_sach]
    urls = [u for u in urls if u]
    if len(urls) > 1:
        return {"text": loi, "video_url": urls[0], "video_urls": urls}
    if urls:
        return {"text": loi, "video_url": urls[0]}
    return {"text": "Em tạo xong nhưng không lấy được video 😥, anh/chị thử lại giúp em nhé."}


def _h_web_search(args: dict, ctx: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"text": "Anh/chị muốn em tra cứu gì ạ?"}
    # Đi qua nhánh "default" để có DỰ PHÒNG: trước đây dòng này ghim cứng
    # "cx/auto", nên Codex hết lượt là phần tra cứu chết hẳn dù còn 16 model
    # khác trong combo. Nhánh chưa đặt thì vẫn rơi về cx/auto như cũ.
    model = branch_model("default", _channel_of(ctx)) or "cx/auto"
    resp = call_model(model, [{"role": "user", "content": query}], timeout=120)
    if resp.get("error"):
        return {"text": f"Em tra cứu bị lỗi 😥 ({resp['error']})."}
    return {"text": content_of(resp) or "Em chưa tìm được thông tin."}


def _h_write_code(args: dict, ctx: dict) -> dict:
    task = str(args.get("task") or "").strip()
    if not task:
        return {"text": "Anh/chị muốn em viết/sửa code gì ạ?"}
    from services.agent.code_style import PONYTAIL_CAVEMAN_EDITOR
    # Prefix "Viết/sửa code:" để tầng branch routing của gateway nhận diện nhánh
    # code → tự chạy vòng Kiểm duyệt (agent_branches.code_reviewer) nếu bật.
    resp = call_model(branch_model("code", _channel_of(ctx)),
                      [{"role": "system", "content": PONYTAIL_CAVEMAN_EDITOR},
                       {"role": "user", "content": f"Viết/sửa code: {task}"}],
                      timeout=320, max_tokens=1500)
    if resp.get("error"):
        return {"text": f"Em viết code bị lỗi 😥 ({resp['error']})."}
    return {"text": content_of(resp) or "Em chưa viết được, thử lại giúp em nhé."}


def _h_read_webpage(args: dict, ctx: dict) -> dict:
    """Đọc 1 trang web cụ thể → text sạch (markitdown). Bổ sung web_search:
    search tìm nhiều nguồn, còn cái này đọc kỹ 1 URL người dùng đưa."""
    import re as _re
    url = str(args.get("url") or "").strip()
    if not _re.match(r"^https?://", url):
        return {"text": "Cho em xin đường link (http/https) cần đọc ạ."}
    try:
        from services import net_guard
        # URL do user/model đưa → SSRF guard (chặn LAN/metadata + redirect độc).
        raw = net_guard.safe_fetch(url, timeout=25, max_bytes=5 * 1024 * 1024)
        import tempfile, os
        suffix = ".html"
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        try:
            from markitdown import MarkItDown
            text = MarkItDown().convert(path).text_content.strip()
        finally:
            os.unlink(path)
    except Exception as exc:
        return {"text": f"Em không đọc được trang này 😥 ({str(exc)[:120]})."}
    if not text:
        return {"text": "Trang này em không trích được nội dung chữ (có thể toàn ảnh/JS)."}
    # Redact secret/PII trước khi nhét tool result vào context LLM.
    try:
        from services.privacy_gate import redact_text
        text = redact_text(text[:6000], session_id=f"agent:{(ctx or {}).get('user_id') or 'web'}")
    except Exception:
        text = text[:6000]
    return {"text": text[:6000]}


_YT_RE = __import__("re").compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})")


def _h_youtube_transcript(args: dict, ctx: dict) -> dict:
    """Lấy phụ đề/transcript video YouTube (ưu tiên vi, rồi en) để tóm tắt."""
    url = str(args.get("url") or "").strip()
    m = _YT_RE.search(url)
    vid = m.group(1) if m else (url if len(url) == 11 else "")
    if not vid:
        return {"text": "Cho em xin link YouTube ạ."}
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        # API mới (>=1.0): instance .fetch() trả FetchedTranscript (iterable
        # snippet có .text). API cũ: classmethod .get_transcript() → list dict.
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            fetched = api.fetch(vid, languages=["vi", "en"])
            text = " ".join(getattr(s, "text", "") or "" for s in fetched).strip()
        else:
            segs = YouTubeTranscriptApi.get_transcript(vid, languages=["vi", "en"])
            text = " ".join(s.get("text", "") for s in segs).strip()
    except Exception as exc:
        return {"text": f"Video này không lấy được phụ đề 😥 ({str(exc)[:100]})."}
    if not text:
        return {"text": "Video không có phụ đề để em đọc ạ."}
    return {"text": text[:8000]}


def _h_remember(args: dict, ctx: dict) -> dict:
    fact = str(args.get("fact") or "").strip()
    if not fact:
        return {"text": "Anh/chị muốn em ghi nhớ điều gì ạ?"}
    # Phòng hờ (khi auto-approve bỏ qua kiểm tra ở orchestrator): không lưu trùng.
    if state.memory_contains(fact):
        return {"text": "Dạ điều này em ghi nhớ rồi ạ 🧠, không cần lưu lại nữa."}
    state.append_memory(fact, who=str(ctx.get("user_id") or ""))
    return {"text": f"Dạ em nhớ rồi ạ 🧠: {fact}"}


# ── Model specs: bot tự học tham số/form của model tạo ảnh/video ──────────────

def _clean_spec_params(params: list) -> list:
    out = []
    for p in params or []:
        if not isinstance(p, dict):
            continue
        key = str(p.get("key") or p.get("name") or "").strip()
        if not key:
            continue
        opts = [str(o).strip() for o in (p.get("options") or []) if str(o).strip()]
        out.append({
            "key": key,
            "label": str(p.get("label") or key).strip(),
            "options": opts,
            "default": str(p.get("default") or (opts[0] if opts else "")).strip(),
            "arg": str(p.get("arg") or key).strip(),
        })
    return out


def _clean_spec_presets(presets: list) -> list:
    out = []
    for p in presets or []:
        if not isinstance(p, dict):
            continue
        label = str(p.get("label") or "").strip()
        vals = p.get("values") if isinstance(p.get("values"), dict) else {}
        if not label or not vals:
            continue
        out.append({"label": label, "values": {str(k): str(v) for k, v in vals.items()}})
    return out


def _describe_model_spec(model: str, sp: dict | None) -> str:
    if not sp:
        return f"(em chưa có spec cho {model})"
    lines: list[str] = []
    for p in sp.get("params") or []:
        opts = " / ".join(p.get("options") or []) or "(tự do)"
        d = p.get("default")
        lines.append(f"• {p.get('label') or p.get('key')}: {opts}" + (f"  [mặc định {d}]" if d else ""))
    for pr in sp.get("presets") or []:
        vals = ", ".join(f"{k}={v}" for k, v in (pr.get("values") or {}).items())
        lines.append(f"◦ Preset {pr.get('label')}: {vals}")
    if sp.get("notes"):
        lines.append(f"Ghi chú: {sp['notes']}")
    return "\n".join(lines) or "(spec rỗng)"


def _h_model_spec(args: dict, ctx: dict) -> dict:
    """Bot TỰ HỌC tham số/form model tạo ảnh/video. Dạy → lưu → lần sau tự dùng."""
    op = str(args.get("op") or "set").strip().lower()
    model = str(args.get("model") or "").strip()
    who = str(ctx.get("user_id") or "")

    if op == "list":
        specs = state.load_model_specs()
        if not specs:
            return {"text": "Em chưa học spec model nào ạ. Anh/chị dạy em: nêu model + "
                            "các tham số (tên + lựa chọn) là em nhớ 🧠."}
        lines = ["🧬 Spec model em đã học:"]
        for mid, sp in specs.items():
            pnames = ", ".join(p.get("label") or p.get("key") for p in (sp.get("params") or []))
            npre = len(sp.get("presets") or [])
            lines.append(f"• {mid}: {pnames or '—'}" + (f" · {npre} preset" if npre else ""))
        return {"text": "\n".join(lines)}

    if not model:
        return {"text": "Anh/chị cho em xin TÊN model (id) cần dạy/xem ạ."}

    if op == "get":
        sp = state.get_model_spec(model)
        if not sp:
            return {"text": f"Em chưa biết tham số của `{model}`. Anh/chị dạy em nhé "
                            f"(vd: size 1024x1024 / 512x512, số lượng 1,2,4)."}
        return {"text": f"🧬 Spec `{model}`:\n{_describe_model_spec(model, sp)}"}

    if op in ("clear", "delete", "forget"):
        ok = state.delete_model_spec(model)
        return {"text": f"Đã xóa spec `{model}` ạ." if ok else f"Không thấy spec `{model}`."}

    # op == set — dạy tham số / preset (ghép dần với cái đã có)
    spec: dict = {}
    if isinstance(args.get("params"), list):
        spec["params"] = _clean_spec_params(args["params"])
    if isinstance(args.get("presets"), list):
        spec["presets"] = _clean_spec_presets(args["presets"])
    if args.get("notes"):
        spec["notes"] = str(args.get("notes"))
    if not spec:
        return {"text": "Anh/chị mô tả giúp em tham số của model — tên field + các lựa "
                        "chọn (vd size: 1024x1024, 512x512), hoặc preset gói sẵn ạ."}
    state.set_model_spec(model, spec, who=who)
    return {"text": f"Dạ em học rồi ạ 🧠 — spec `{model}`:\n"
                    f"{_describe_model_spec(model, state.get_model_spec(model))}"}


def _h_teach_skill(args: dict, ctx: dict) -> dict:
    """BOT TỰ HỌC MỌI VIỆC: người dùng dạy cách làm 1 việc → lưu thành skill
    (playbook). Skill tự hiện ở danh mục → lần sau gặp việc khớp thì làm theo."""
    from services.agent import skills as sk
    op = str(args.get("op") or "set").strip().lower()

    if op == "list":
        items = sk.list_skills()
        if not items:
            return {"text": "Em chưa học kỹ năng nào ạ. Anh/chị dạy em cách làm một "
                            "việc (các bước) là em nhớ thành skill 🧩."}
        lines = ["🧩 Kỹ năng em đã học:"]
        for s in items:
            lines.append(f"• `{s.slug}` — {s.description or s.name}"
                         + ("" if s.enabled else " (đang tắt)"))
        return {"text": "\n".join(lines)}

    slug = str(args.get("slug") or "").strip()
    if op == "get":
        body = sk.load_body(slug) if slug else None
        return {"text": f"🧩 `{slug}`:\n{body}" if body else f"Không thấy kỹ năng `{slug}`."}
    if op in ("delete", "clear", "forget"):
        if not slug:
            return {"text": "Cho em xin mã kỹ năng (slug) cần xóa ạ (op=list để xem)."}
        return {"text": f"Đã xóa kỹ năng `{slug}` ạ." if sk.delete_skill(slug)
                        else f"Không thấy kỹ năng `{slug}`."}

    # set / append — dạy quy trình
    name = str(args.get("name") or "").strip()
    description = str(args.get("description") or "").strip()
    body = str(args.get("body") or args.get("steps") or "").strip()
    if not body:
        return {"text": "Anh/chị mô tả giúp em CÁC BƯỚC làm việc này (gọi gì, lấy gì, "
                        "gửi đâu…) — em lưu thành kỹ năng để lần sau tự làm ạ."}
    try:
        new_slug = sk.write_skill(name, description, body, slug=slug, append=(op == "append"))
    except Exception as exc:
        return {"text": f"Em lưu kỹ năng chưa được 😥 ({exc})."}
    label = name or description or new_slug
    return {"text": f"Dạ em học rồi ạ 🧩 — kỹ năng `{new_slug}` ({label}). "
                    f"Lần sau gặp việc này em tự làm theo."}


def _h_schedule(args: dict, ctx: dict) -> dict:
    """Create / list / cancel user reminders and recurring agent tasks."""
    from services.agent import reminders as rem

    if not rem.is_enabled():
        return {"text": "Tính năng nhắc hẹn đang tắt trên máy chủ ạ."}

    op = str(args.get("op") or "create").strip().lower()
    user_id = str(ctx.get("user_id") or "")
    if not user_id:
        return {"text": "Em không xác định được người đặt nhắc 😥."}

    if op == "list":
        rows = rem.list_for(user_id)
        if not rows:
            return {"text": "Hiện không có nhắc/việc nào đang chờ ạ."}
        lines = ["Danh sách nhắc & việc định kỳ:"] + [rem.describe(r) for r in rows]
        return {"text": "\n".join(lines)}

    if op == "cancel":
        rid = str(args.get("id") or "").strip()
        if rid in ("*", "all", "tất cả", "tat ca"):
            n = rem.cancel_all(user_id)
            return {"text": f"Dạ em đã huỷ {n} mục ạ." if n else "Không còn mục nào để huỷ ạ."}
        if not rid:
            return {"text": "Cho em xin mã nhắc (id) cần huỷ, hoặc id=all để huỷ hết."}
        ok = rem.cancel(user_id, rid)
        return {"text": f"Đã huỷ `{rid}` ạ." if ok else f"Không thấy nhắc `{rid}` (hoặc đã huỷ)."}

    # create
    text = str(args.get("text") or args.get("message") or "").strip()
    if not text:
        return {"text": "Anh/chị muốn em nhắc / làm việc gì ạ?"}
    mode = str(args.get("mode") or "notify").strip().lower()
    if mode not in ("notify", "task"):
        mode = "notify"
    # ── HỎI-ĐỦ-RỒI-MỚI-LÀM: nếu việc là GỬI TIN cho người/nhóm, resolve danh bạ
    # NGAY lúc tạo (user còn đó) để hỏi lại khi thiếu/mập mờ — KHÔNG đoán lúc bắn.
    # Khớp rõ → nhúng chat_id đã resolve vào `text` để lúc bắn gửi trúng đích.
    send_to = str(args.get("send_to") or "").strip()
    if mode == "task" and send_to:
        _pre = _h_send_to_contact(
            {"to": send_to, "message": text,
             "platform": str(args.get("send_platform") or "").strip(),
             "_resolve_only": True}, ctx)
        if _pre.get("need_clarify"):
            return {"text": _pre.get("text")
                    or "Cho em xin rõ người/nhóm nhận (kênh nào, tên gì) ạ, "
                       "em chưa đặt lịch để tránh gửi nhầm."}
        _rs = _pre.get("resolved") or []
        if _rs:
            _ids = ", ".join(str(x.get("chat_id")) for x in _rs)
            _nm = ", ".join(str(x.get("chat_name") or x.get("alias") or x.get("chat_id"))
                            for x in _rs)
            _pf = _rs[0].get("platform") or ""
            text = (f"Dùng send_to_contact gửi tới chat_id [{_ids}] "
                    f"trên kênh {_pf} (tên: {_nm}) nội dung: {text}")
    # structured time args
    in_minutes = args.get("in_minutes")
    every_minutes = args.get("every_minutes")
    every_day_at = args.get("every_day_at")
    at = args.get("at")
    when = str(args.get("when") or "").strip()
    try:
        if in_minutes is not None:
            in_minutes = int(in_minutes)
        if every_minutes is not None:
            every_minutes = int(every_minutes)
    except (TypeError, ValueError):
        in_minutes = None if not isinstance(in_minutes, int) else in_minutes
        every_minutes = None if not isinstance(every_minutes, int) else every_minutes

    sched = rem.parse_when(
        when,
        in_minutes=in_minutes,
        every_minutes=every_minutes,
        every_day_at=str(every_day_at) if every_day_at else None,
        at=str(at) if at else None,
    )
    if not sched:
        return {
            "text": (
                "Em chưa hiểu thời điểm ạ. Ví dụ: sau 30 phút / lúc 19:30 / "
                "mai 7h sáng / mỗi ngày 7h / mỗi 2 giờ — hoặc truyền in_minutes / "
                "every_day_at / every_minutes."
            )
        }
    try:
        row = rem.create(user_id, text, sched, mode=mode)
    except Exception as exc:
        return {"text": f"Không đặt được nhắc 😥: {str(exc)[:150]}"}
    kind_s = "việc (em sẽ tự làm rồi báo)" if mode == "task" else "nhắc"
    return {
        "text": (
            f"Dạ em đã đặt {kind_s} `{row['id']}` — {rem.describe(row).lstrip('• ').strip()} ⏰"
        )
    }


def _h_search_history(args: dict, ctx: dict) -> dict:
    """Full-text search past conversation turns for this user."""
    from services.agent import session as sess

    q = str(args.get("query") or "").strip()
    if not q:
        return {"text": "Anh/chị muốn tìm lại chuyện gì ạ?"}
    user_id = str(ctx.get("user_id") or "")
    if not user_id:
        return {"text": "Em không xác định được phiên chat 😥."}
    hits = sess.search(user_id, q, limit=8)
    if not hits:
        return {"text": f"Em không thấy đoạn chat nào khớp “{q}” ạ."}
    lines = [f"Em tìm thấy {len(hits)} đoạn liên quan “{q}”:"]
    for h in hits:
        role = "Anh/chị" if h.get("role") == "user" else "Em"
        snippet = str(h.get("content") or "").replace("\n", " ")
        if len(snippet) > 160:
            snippet = snippet[:160] + "…"
        lines.append(f"• {role}: {snippet}")
    return {"text": "\n".join(lines)}


def _h_search_sgk(args: dict, ctx: dict) -> dict:
    """Tìm trong KB SGK mọi cấp — lớp 1–12 (lớp–môn Toán/Văn/Anh)."""
    from services.agent import teacher as teach
    from services.agent import teacher_workspace as tw

    if not teach.is_enabled():
        return {"text": "Chế độ Giáo viên đang tắt trong Settings ạ."}
    if not teach.can_use_teacher(ctx=ctx):
        return {"text": (
            "Khung chat này chưa được cấp «Giáo viên». "
            "Admin tick 📚 trong Settings → Lọc thread."
        )}
    q = str(args.get("query") or args.get("question") or args.get("text") or "").strip()
    grade = args.get("grade")
    try:
        grade_i = int(grade) if grade not in (None, "") else None
    except (TypeError, ValueError):
        grade_i = None
    subject = str(args.get("subject") or args.get("mon") or "").strip()
    ws = str(args.get("workspace") or args.get("workspace_id") or "").strip()
    top_k = args.get("top_k") or 4
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 4
    if not q and not ws:
        return {"text": tw.list_sgk_index() + "\n\nGọi lại với query=… và grade/subject hoặc workspace."}
    if not q:
        w = tw.get_workspace(ws)
        if not w:
            return {"text": "Không thấy workspace. Dùng list_teacher_workspaces."}
        return {"text": (
            f"Workspace **{w.get('name')}** (lớp {w.get('grade')}, "
            f"môn {', '.join(w.get('subjects') or [])}). "
            "Hãy search_sgk với query cụ thể."
        )}
    text = tw.search_sgk(q, grade=grade_i, subject=subject or None,
                         workspace_id=ws, top_k=top_k)
    # Bổ sung best-effort đoạn "kiến thức mở rộng" (kb_nangcao) — TÁCH RÕ khỏi
    # đoạn SGK ở trên để model không lẫn nội dung ngoài chương trình vào như
    # thể đó là SGK. Lỗi/không có gì → im lặng, không ảnh hưởng câu trả lời SGK.
    try:
        from services.agent import sgk_fetch as sf
        extra = sf.nangcao_hits(q, grade=grade_i, subject=subject or None, top_k=2)
        if extra:
            text = text + extra
    except Exception:
        pass
    return {"text": text}


def _h_sgk_fetch(args: dict, ctx: dict) -> dict:
    """Tự tìm & nạp SGK / sách nâng cao vào RAG. op=find|ingest|status."""
    from services.agent import teacher as teach
    from services.agent import sgk_fetch as sf

    if not teach.is_enabled():
        return {"text": "Chế độ Giáo viên đang tắt trong Settings ạ."}
    if not teach.can_use_teacher(ctx=ctx):
        return {"text": (
            "Khung chat này chưa được cấp «Giáo viên». "
            "Admin tick 📚 trong Settings → Lọc thread."
        )}

    op = str(args.get("op") or "find").strip().lower()
    grade = args.get("grade")
    try:
        grade_i = int(grade) if grade not in (None, "") else None
    except (TypeError, ValueError):
        grade_i = None
    subject = str(args.get("subject") or args.get("mon") or "").strip()
    kind = str(args.get("kind") or "sgk").strip().lower()
    year = str(args.get("year") or "").strip()

    if op in {"status", "list"}:
        st = sf.status(grade=grade_i, subject=subject or None)
        if not st["items"]:
            return {"text": "Chưa nạp SGK/nâng cao nào qua tính năng tự tìm (op=find trước)."}
        lines = [f"**Đã nạp {st['total']} nguồn** (tự tìm/tự nạp):", ""]
        for r in st["items"][:20]:
            tag = "SGK" if r.get("kind") == "sgk" else "Nâng cao"
            ok_mark = "✅" if r.get("ok") else "❌"
            mon = sf.SUBJECT_LABEL.get(r.get("subject"), r.get("subject"))
            lines.append(
                f"{ok_mark} Lớp {r.get('grade')} · {mon} · [{tag}] "
                f"{r.get('source_name')} ({r.get('fetched_at')})"
            )
        return {"text": "\n".join(lines)}

    if grade_i is None or not subject:
        return {"text": "Cần grade (1–12) và subject (vd toan, ly, hoa, su…) ạ."}

    if op in {"ingest", "add", "download"}:
        url = str(args.get("url") or "").strip()
        if not url:
            return {"text": "Cần url (lấy từ kết quả op=find, hoặc URL người dùng tự cung cấp)."}
        dry_run = bool(args.get("dry_run") or False)
        curriculum = str(args.get("curriculum") or "").strip()
        r = sf.fetch_and_ingest(
            grade_i, subject, url, year=year, kind=kind,
            curriculum=curriculum, dry_run=dry_run,
        )
        if not r.get("ok"):
            return {"text": f"Không nạp được: {r.get('error') or 'lỗi không rõ'} 😥"}
        if r.get("skipped"):
            return {"text": r.get("reason") or "URL đã nạp trước đó."}
        if r.get("dry_run"):
            return {"text": (
                f"Thử tải OK ({r.get('bytes')} byte, trích được {r.get('preview_chars')} ký tự). "
                "Gọi lại dry_run=false để nạp thật vào RAG."
            )}
        collection = (r.get("provenance") or {}).get("collection", "")
        tag = {
            "kb_giao_duc": "SGK (kb_giao_duc)", "kb_nangcao": "Nâng cao (kb_nangcao)",
        }.get(collection, collection)
        mon = sf.SUBJECT_LABEL.get(subject, subject)
        return {"text": (
            f"Đã nạp xong lớp {grade_i} · {mon} vào {tag}. "
            f"Nguồn: {r.get('source') or url[:80]}."
        )}

    # mặc định: find — CHỈ TÌM, không tự tải
    cands = sf.find_sources(grade_i, subject, year=year, kind=kind)
    mon = sf.SUBJECT_LABEL.get(sf.normalize_subject(subject) or subject, subject)
    if not cands:
        return {"text": (
            f"Không tìm thấy PDF nào đủ tin cậy cho lớp {grade_i} · {mon} "
            f"({'sách nâng cao' if kind == 'nangcao' else 'SGK'}). "
            "Có thể sách này chưa được đăng công khai trên mạng — "
            "đừng đoán bừa, hỏi người dùng cung cấp URL trực tiếp nếu có."
        )}
    lines = [
        f"**Tìm thấy {len(cands)} nguồn khả dĩ** (lớp {grade_i} · {mon}"
        f"{' · ' + year if year else ''}"
        f"{' · nâng cao' if kind == 'nangcao' else ''}):",
        "",
    ]
    for i, c in enumerate(cands, 1):
        lines.append(
            f"{i}. [{c['confidence']:.0%}] {c['title'][:90]} — {c['source']}\n   {c['url']}"
        )
    lines.append("")
    lines.append(
        "⚠️ Đây là PDF đăng công khai trên mạng — KHÔNG đảm bảo đúng bản/năm "
        "phát hành cụ thể. Chọn 1 url rồi gọi lại op=ingest với url=... để nạp; "
        "nếu không chắc bản nào đúng, hỏi người dùng xác nhận trước."
    )
    return {"text": "\n".join(lines)}


def _h_list_teacher_workspaces(args: dict, ctx: dict) -> dict:
    from services.agent import teacher as teach
    from services.agent import teacher_workspace as tw

    if not teach.is_enabled():
        return {"text": "Chế độ Giáo viên đang tắt ạ."}
    if not teach.can_use_teacher(ctx=ctx):
        return {"text": "Thread chưa được cấp quyền Giáo viên ạ."}
    rows = tw.list_workspaces()
    if not rows:
        return {"text": "Chưa có workspace. Seed data/agent/teacher/workspaces.json."}
    lines = [
        f"**Workspace SGK** (Toán · Văn · Anh, lớp 1–12) — {len(rows)} workspace:",
        "",
    ]
    for w in rows:
        lines.append(
            f"- `{w.get('id')}`: {w.get('name')} — lớp {w.get('grade')}, "
            f"môn {', '.join(w.get('subjects') or [])}"
        )
    lines.append("")
    lines.append(
        "Dùng search_sgk / teacher_lesson / teacher_memory với workspace=id."
    )
    return {"text": "\n".join(lines)}


def _h_teacher_memory(args: dict, ctx: dict) -> dict:
    """Memory học sinh theo workspace (điểm yếu/mạnh + ghi chú)."""
    from services.agent import teacher as teach
    from services.agent import teacher_workspace as tw

    if not teach.is_enabled():
        return {"text": "Chế độ Giáo viên đang tắt ạ."}
    if not teach.can_use_teacher(ctx=ctx):
        return {"text": "Thread chưa được cấp quyền Giáo viên ạ."}
    op = str(args.get("op") or "get").strip().lower()
    ws = str(args.get("workspace") or args.get("workspace_id") or "").strip()
    student = str(args.get("student") or args.get("student_key")
                  or ctx.get("user_id") or "default").strip() or "default"
    if op in {"get", "read", "show", ""}:
        if not ws:
            return {"text": "Cần workspace (vd lop2-toan). list_teacher_workspaces để xem id."}
        return {"text": tw.memory_get(ws, student)}
    if op in {"add", "note", "update"}:
        if not ws:
            return {"text": "Cần workspace khi ghi memory."}
        text = tw.memory_add(
            ws, student,
            note=str(args.get("note") or args.get("text") or ""),
            weak_topic=str(args.get("weak_topic") or args.get("weak") or ""),
            strong_topic=str(args.get("strong_topic") or args.get("strong") or ""),
        )
        return {"text": text}
    return {"text": "op=get|add. add cần note và/hoặc weak_topic|strong_topic."}


def _ws_grade_subject(ws: str) -> tuple[int | None, str]:
    """'lop8-toan' → (8, 'toan') — suy LỚP + MÔN từ id workspace.

    Model hay đưa workspace mà quên grade → mọi handler từng rơi về lớp 5
    (sư phạm tiểu học + band CEFR sai cho HS THCS/THPT). Suy từ workspace
    trước khi dùng mặc định."""
    # Mã môn lấy từ danh mục, KHÔNG viết cứng: viết cứng toan|van|anh thì
    # 'lop1-tviet', 'lop4-sudia', 'lop10-ly' đều không khớp → hàm trả (None, "")
    # và handler rơi về mặc định lớp 5 / Toán, tức trả lời sai lớp sai môn mà
    # không báo lỗi gì.
    from services.agent import teacher_workspace as _tw
    m = re.match(
        r"lop(\d{1,2})-(%s)$" % "|".join(_tw.SUBJECTS),
        str(ws or "").strip().lower(),
    )
    if not m:
        return (None, "")
    g = int(m.group(1))
    return (g if 1 <= g <= 12 else None, m.group(2))


def _teacher_grade_subject(args: dict, ws: str = "") -> tuple[int, str]:
    """(grade, subject) cho tool giáo viên: args → workspace → mặc định 5/toan."""
    ws_g, ws_sub = _ws_grade_subject(ws or str(args.get("workspace") or ""))
    grade = args.get("grade")
    try:
        grade = int(grade) if grade not in (None, "") else None
    except (TypeError, ValueError):
        grade = None
    subject = str(args.get("subject") or args.get("mon") or "").strip().lower()
    return (grade or ws_g or 5, subject or ws_sub or "toan")


def _h_teacher_quiz(args: dict, ctx: dict) -> dict:
    """Sinh đề kiểm tra ngắn từ KB SGK (mọi cấp 1–12)."""
    from services.agent import teacher as teach
    from services.agent import teacher_assess as ta

    if not teach.is_enabled() or not teach.can_use_teacher(ctx=ctx):
        return {"text": "Cần quyền Giáo viên (Settings → Lọc thread)."}
    ws = str(args.get("workspace") or "").strip()
    grade, subject = _teacher_grade_subject(args, ws)
    topic = str(args.get("topic") or args.get("query") or "").strip()
    n = args.get("n") or args.get("count") or 5
    quiz = ta.make_quiz(
        grade=grade, subject=subject, topic=topic, n=int(n) if n else 5,
        workspace_id=ws,
    )
    return {"text": ta.format_quiz_for_student(quiz)}


def _h_teacher_bai_tap(args: dict, ctx: dict) -> dict:
    """Ra bài tập BA MỨC dựa trên bài mẫu thật trong kho vở/sách bài tập.

    Khác `teacher_quiz`: cái đó sinh câu bằng `random` theo khoảng lập trình cứng
    nên đúng phép tính mà sai KIỂU ra đề của sách, và chỉ làm được toán/anh/văn.
    Ở đây gốc là bài mẫu trong `kb_giao_duc_vbt`, nên mức "sát" soi đúng dạng hỏi
    của sách và mọi môn đều ra được.
    """
    from services.agent import teacher as teach
    from services.agent import teacher_bai_tap as bt

    if not teach.is_enabled() or not teach.can_use_teacher(ctx=ctx):
        return {"text": "Cần quyền Giáo viên (Settings → Lọc thread)."}
    ws = str(args.get("workspace") or "").strip()
    grade, subject = _teacher_grade_subject(args, ws)
    bai = str(args.get("bai") or args.get("topic") or args.get("query") or "").strip()
    n = args.get("so_moi_muc") or args.get("n") or 2
    xin = args.get("muc") or args.get("levels")
    if isinstance(xin, str):
        xin = [x.strip() for x in xin.replace("|", ",").split(",") if x.strip()]
    r = bt.tao(grade=grade, subject=subject, bai=bai,
               so_moi_muc=int(n) if n else 2,
               muc=tuple(xin) if xin else bt.MUC,
               student_key=str(args.get("student_key") or "").strip())
    if not r.get("ok"):
        return {"text": f"Chưa ra được đề: {r.get('error')}"}
    # Bản GIÁO VIÊN (có đáp án + báo căn cứ): tool này là tool của giáo viên, và
    # cảnh báo "kho chưa có bài mẫu" phải đến được người quyết định giao đề.
    return {"text": bt.format_cho_giao_vien(r["bo_de"])}


def _h_teacher_grade(args: dict, ctx: dict) -> dict:
    """Chấm 1 câu hoặc cả quiz; trả feedback + hướng sửa."""
    from services.agent import teacher as teach
    from services.agent import teacher_assess as ta
    from services.agent import teacher_workspace as tw

    if not teach.is_enabled() or not teach.can_use_teacher(ctx=ctx):
        return {"text": "Cần quyền Giáo viên."}
    quiz_id = str(args.get("quiz_id") or "").strip()
    # Chấm cả đề
    if quiz_id:
        raw = args.get("answers") or args.get("answer") or {}
        if isinstance(raw, str):
            try:
                import json as _json
                raw = _json.loads(raw)
            except Exception:
                raw = {"q1": raw}
        if not isinstance(raw, dict):
            return {"text": "answers phải là object {q1: '...', q2: '...'}."}
        result = ta.grade_quiz(quiz_id, {str(k): str(v) for k, v in raw.items()},
                               use_llm=bool(args.get("use_llm", True)))
        if not result.get("ok"):
            return {"text": result.get("error") or "Chấm lỗi."}
        lines = [
            f"**Kết quả chấm** `{quiz_id}`",
            result.get("summary") or "",
            f"Điểm TB: **{result.get('average_0_10')}/10** ({result.get('percent')}%).",
            "",
        ]
        for d in result.get("details") or []:
            lines.append(
                f"- {d.get('id')}: {d.get('score_0_10')}/10 — {d.get('feedback')}"
            )
            for f in (d.get("fixes") or [])[:2]:
                lines.append(f"  · Sửa: {f}")
        # Ghi memory nếu có workspace
        ws = str(args.get("workspace") or "").strip()
        student = str(args.get("student") or ctx.get("user_id") or "default")
        if ws and result.get("average_0_10", 10) < 7:
            weak = [d["id"] for d in result.get("details") or []
                    if int(d.get("score_0_10") or 0) < 5]
            if weak:
                tw.memory_add(
                    ws, student,
                    weak_topic=f"quiz {quiz_id}: {', '.join(weak)}",
                    note=result.get("summary") or "",
                )
        return {"text": "\n".join(lines)}

    # Chấm 1 câu
    q = str(args.get("question") or args.get("prompt") or "").strip()
    ans = str(args.get("answer") or args.get("student_answer") or args.get("text") or "").strip()
    if not q or not ans:
        return {"text": "Cần question + answer (hoặc quiz_id + answers)."}
    grade, subject = _teacher_grade_subject(args)
    hint = str(args.get("answer_hint") or args.get("hint") or "").strip()
    r = ta.grade_answer(
        question=q, student_answer=ans, answer_hint=hint,
        subject=subject, grade=grade,
        use_llm=bool(args.get("use_llm", True)),
    )
    text = ta.format_grade_for_student(r)
    ws = str(args.get("workspace") or "").strip()
    student = str(args.get("student") or ctx.get("user_id") or "default")
    if ws and int(r.get("score_0_10") or 0) < 5:
        tw.memory_add(
            ws, student,
            weak_topic=(q[:80] if q else "bài yếu"),
            note=f"score {r.get('score_0_10')}/10 · {r.get('feedback') or ''}"[:200],
        )
    return {"text": text}


def _h_teacher_hint(args: dict, ctx: dict) -> dict:
    """Gợi ý bậc thang 1–3 (Socratic scaffold)."""
    from services.agent import teacher as teach
    from services.agent import teacher_assess as ta

    if not teach.is_enabled() or not teach.can_use_teacher(ctx=ctx):
        return {"text": "Cần quyền Giáo viên."}
    q = str(args.get("question") or args.get("prompt") or "").strip()
    if not q:
        return {"text": "Cần question= đề bài đang kẹt."}
    level = args.get("level") or args.get("hint_level") or 1
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 1
    grade, subject = _teacher_grade_subject(args)
    r = ta.progressive_hints(
        question=q,
        student_attempt=str(args.get("attempt") or args.get("answer") or ""),
        answer_hint=str(args.get("answer_hint") or args.get("hint") or ""),
        level=level,
        subject=subject,
        grade=grade,
    )
    return {"text": r.get("text") or "Không tạo được gợi ý."}


def _h_teacher_check(args: dict, ctx: dict) -> dict:
    """1 câu kiểm tra hiểu (exit ticket)."""
    from services.agent import teacher as teach
    from services.agent import teacher_assess as ta

    if not teach.is_enabled() or not teach.can_use_teacher(ctx=ctx):
        return {"text": "Cần quyền Giáo viên."}
    ws = str(args.get("workspace") or "").strip()
    grade, subject = _teacher_grade_subject(args, ws)
    r = ta.make_check(
        grade=grade,
        subject=subject,
        topic=str(args.get("topic") or args.get("query") or ""),
        workspace_id=ws,
    )
    return {"text": r.get("text") or "Không tạo được câu kiểm tra."}


def _h_teacher_lesson(args: dict, ctx: dict) -> dict:
    """Giáo án 6 pha kiểu lớp học + (tuỳ chọn) nạp memory HS."""
    from services.agent import teacher as teach
    from services.agent import teacher_workspace as tw

    if not teach.is_enabled() or not teach.can_use_teacher(ctx=ctx):
        return {"text": "Cần quyền Giáo viên."}
    grade, subject = _teacher_grade_subject(args)
    topic = str(args.get("topic") or args.get("query") or "ôn tập")
    objective = str(args.get("objective") or args.get("muc_tieu") or "")
    ws = str(args.get("workspace") or "").strip()
    student = str(args.get("student") or ctx.get("user_id") or "default")
    weak = str(args.get("weak_topic") or "")
    mem_block = ""
    if ws:
        mem_block = tw.memory_get(ws, student)
        # Lấy weak topics thô nếu chưa truyền
        if not weak:
            m = tw._load_mem(ws, student)
            wlist = m.get("weak_topics") or []
            if wlist:
                weak = "; ".join(str(x) for x in wlist[-3:])
    plan = teach.build_lesson_plan(
        grade=grade,
        subject=subject,
        topic=topic,
        objective=objective,
        student_weak=weak,
        level_note=f"Skill: {teach.skill_for_grade(grade)}",
    )
    parts = [plan]
    if mem_block and "Chưa có ghi nhận" not in mem_block:
        parts.append("")
        parts.append("---")
        parts.append(mem_block)
    parts.append("")
    parts.append(
        f"_Bắt đầu dạy: use_skill `{teach.skill_for_grade(grade)}` · "
        f"search_sgk · teacher_hint / teacher_check / teacher_grade · "
        f"teacher_memory khi kết._"
    )
    return {"text": "\n".join(parts)}


def _h_use_skill(args: dict, ctx: dict) -> dict:
    """Load a markdown skill playbook body for the model to follow."""
    from services.agent import skills as sk
    from services.agent import teacher as teach

    if not sk.is_enabled():
        return {"text": "Playbook/skill đang tắt trên máy chủ ạ."}
    slug = str(args.get("slug") or args.get("name") or "").strip()
    if not slug:
        enabled = sk.list_enabled()
        if not enabled:
            return {"text": "Chưa có skill nào. Thêm SKILL.md vào data/agent/skills/<slug>/."}
        lines = ["Skill đang bật:"] + [s.router_line() for s in enabled]
        return {"text": "\n".join(lines)}
    # Skill giáo viên: cần bật teacher + tick nhóm teacher trên thread (Zalo/Tele).
    if slug in teach.TEACHER_SKILLS:
        if not teach.is_enabled():
            return {"text": "Chế độ Giáo viên đang tắt trong Settings ạ."}
        if not teach.can_use_teacher(ctx=ctx):
            return {"text": (
                "Khung chat này chưa được cấp nhóm «Giáo viên tiểu học». "
                "Admin bật trong Settings → Kênh chat → Lọc thread (tick 📚 Giáo viên)."
            )}
    body = sk.load_body(slug)
    if not body:
        enabled = sk.list_enabled()
        hint = ", ".join(s.slug for s in enabled[:12]) or "(trống)"
        return {"text": f"Không thấy skill `{slug}`. Đang có: {hint}"}
    extra = ""
    if slug in teach.TEACHER_SKILLS:
        vi, en = teach.voice_vi(), teach.voice_en()
        extra = (
            f"\n\n[Cấu hình giọng — Settings Giáo viên: "
            f"VI=`{vi or '(mặc định hệ thống)'}` · EN=`{en or '(mặc định hệ thống)'}` · "
            f"phát loa={'BẬT' if teach.speak_to_speaker_enabled() else 'TẮT'}]"
        )
        if teach.can_teacher_speak(ctx=ctx):
            extra += (
                "\nĐược phép phát loa khi dạy: tóm tắt 2–4 câu rồi gọi "
                "speak_to_speaker (giọng auto theo tiếng Việt/Anh)."
            )
        else:
            extra += "\nKhông phát loa (tắt speak_to_speaker hoặc thread chưa có tts_speaker)."
    return {
        "text": (
            f"[Playbook `{slug}` — làm ĐÚNG các bước dưới, gọi tool cứng khi cần]\n\n"
            f"{body[:6000]}{extra}"
        )
    }


def _h_run_workflow(args: dict, ctx: dict) -> dict:
    """Run a multi-step markdown workflow (optional verify)."""
    from services.agent import workflows as wf
    from services.agent import teacher as teach

    if not wf.is_enabled():
        return {"text": "Workflow đang tắt trên máy chủ ạ."}
    slug = str(args.get("slug") or args.get("name") or "").strip()
    user_input = str(args.get("input") or args.get("text") or args.get("query") or "").strip()
    if not slug:
        items = wf.list_workflows()
        if not items:
            return {"text": "Chưa có workflow. Thêm file .md vào data/agent/workflows/."}
        lines = ["Workflow có sẵn:"] + [w.router_line() for w in items]
        return {"text": "\n".join(lines)}
    if slug in teach.TEACHER_WORKFLOWS:
        if not teach.is_enabled():
            return {"text": "Chế độ Giáo viên đang tắt trong Settings ạ."}
        if not teach.can_use_teacher(ctx=ctx):
            return {"text": (
                "Khung chat này chưa được cấp «Giáo viên tiểu học». "
                "Admin tick trong Settings → Lọc thread."
            )}
    if not user_input:
        return {"text": "Cần `input` (nội dung/yêu cầu chạy pipeline)."}
    out = wf.run(slug, user_input)
    return {"text": out.get("text") or "Workflow xong nhưng không có nội dung."}


def _h_ingest(args: dict, ctx: dict) -> dict:
    """Ingest free text into wiki lite (+ optional MEMORY fact)."""
    from services.agent import wiki as w

    if not w.is_enabled():
        return {"text": "Wiki đang tắt trên máy chủ ạ."}
    content = str(args.get("content") or args.get("text") or args.get("note") or "").strip()
    title = str(args.get("title") or "").strip()
    source = str(args.get("source") or "").strip()
    who = str(ctx.get("user_id") or "")
    out = w.ingest(content, title=title, who=who, source=source)
    return {"text": out.get("text") or "Thu nạp xong."}


def _h_wiki_search(args: dict, ctx: dict) -> dict:
    from services.agent import wiki as w

    if not w.is_enabled():
        return {"text": "Wiki đang tắt trên máy chủ ạ."}
    q = str(args.get("query") or "").strip()
    if not q:
        recent = w.list_recent(10)
        if not recent:
            return {"text": "Wiki còn trống. Dùng ingest để thu nạp ghi chú."}
        lines = ["Ghi chú gần đây:"] + [f"• `{r['slug']}` — {r['title']}" for r in recent]
        return {"text": "\n".join(lines)}
    hits = w.search(q, limit=8)
    if not hits:
        return {"text": f"Không thấy ghi chú khớp “{q}”."}
    lines = [f"Tìm thấy {len(hits)} ghi chú:"]
    for h in hits:
        lines.append(f"• `{h['slug']}` — {h['title']}\n  {h['snippet'][:140]}")
    return {"text": "\n".join(lines)}


def _h_wiki_read(args: dict, ctx: dict) -> dict:
    from services.agent import wiki as w

    if not w.is_enabled():
        return {"text": "Wiki đang tắt trên máy chủ ạ."}
    slug = str(args.get("slug") or "").strip()
    if not slug:
        return {"text": "Cần slug ghi chú (từ wiki_search)."}
    body = w.read(slug)
    if not body:
        return {"text": f"Không có ghi chú `{slug}`."}
    return {"text": body[:4000]}


def _h_expand_tool_result(args: dict, ctx: dict) -> dict:
    """Recover full tool output that was compressed (⟦tc:hash⟧)."""
    from services.agent import tool_compress as tc

    token = str(
        args.get("token") or args.get("hash") or args.get("marker") or ""
    ).strip()
    if not token:
        return {"text": "Cần token (hash trong marker ⟦tc:…⟧) để lấy bản đầy đủ."}
    try:
        max_out = int(args.get("max_chars") or 50000)
    except (TypeError, ValueError):
        max_out = 50000
    max_out = max(500, min(max_out, 100_000))
    full = tc.retrieve(token, max_out=max_out)
    if full is None:
        return {
            "text": (
                f"Không tìm thấy bản đầy đủ cho token `{token[:24]}…`. "
                f"Có thể đã hết hạn cache — gọi lại tool gốc."
            ),
        }
    return {"text": full}


def _h_wiki_digest(args: dict, ctx: dict) -> dict:
    """Build or read daily wiki digest."""
    from services.agent import wiki as w

    if not w.is_enabled():
        return {"text": "Wiki đang tắt trên máy chủ ạ."}
    op = str(args.get("op") or "read").strip().lower()
    day = str(args.get("day") or "").strip() or None
    force = bool(args.get("force") or op in ("build", "create", "run"))
    use_llm = args.get("use_llm")
    if op in ("build", "create", "run", "today") or force:
        out = w.build_daily_digest(
            day,
            force=force or op in ("build", "create", "run"),
            use_llm=bool(use_llm) if use_llm is not None else None,
        )
        if not out.get("ok"):
            return {"text": out.get("text") or "Không tạo được digest."}
        head = (
            f"Digest `{out.get('day')}`"
            + (" (đã có sẵn)" if out.get("skipped") else f" — {out.get('note_count', 0)} ghi chú")
            + ":\n\n"
        )
        body = str(out.get("text") or "")
        if len(body) > 3500:
            body = body[:3500] + "…"
        return {"text": head + body}
    # read
    body = w.read_digest(day)
    if not body:
        d = day or "hôm nay"
        return {
            "text": (
                f"Chưa có digest cho {d}. "
                f"Gọi wiki_digest op=build để tạo."
            ),
        }
    if len(body) > 3500:
        body = body[:3500] + "…"
    return {"text": body}


def _h_goals(args: dict, ctx: dict) -> dict:
    """Thread goals kanban: add / list / done / doing / cancel / update."""
    from services.agent import goals as g

    if not g.is_enabled():
        return {"text": "Goals đang tắt trên máy chủ ạ."}
    user_id = str(ctx.get("user_id") or "")
    if not user_id:
        return {"text": "Em không xác định được phiên chat 😥."}
    op = str(args.get("op") or "list").strip().lower()
    gid = str(args.get("id") or args.get("goal_id") or "").strip()
    title = str(args.get("title") or args.get("text") or args.get("goal") or "").strip()
    notes = str(args.get("notes") or "").strip()
    status = str(args.get("status") or "").strip().lower()

    if op in ("list", "ls", ""):
        st_filter = status if status in ("open", "doing", "done", "cancelled") else None
        rows = g.list_for(user_id, status=st_filter, limit=20)
        if not rows:
            return {"text": "Chưa có goal nào. Thêm bằng goals op=add title=…"}
        lines = ["Mục tiêu thread:"] + [g.describe(r) for r in rows]
        return {"text": "\n".join(lines)}

    if op in ("add", "create", "new"):
        if not title:
            return {"text": "Cần title (nội dung goal)."}
        try:
            pri = int(args.get("priority") or 0)
        except (TypeError, ValueError):
            pri = 0
        try:
            row = g.add(user_id, title, notes=notes, priority=pri,
                        status=status if status in ("open", "doing") else "open")
        except Exception as exc:
            return {"text": f"Không thêm goal: {str(exc)[:150]}"}
        return {"text": f"Đã thêm goal `{row['id']}`: {row['title']} ○"}

    if op in ("done", "complete", "finish"):
        if not gid:
            return {"text": "Cần id goal (từ goals op=list)."}
        row = g.set_status(user_id, gid, "done")
        return {"text": f"Xong goal `{gid}` ●" if row else f"Không thấy goal `{gid}`."}

    if op in ("doing", "start", "progress"):
        if not gid:
            return {"text": "Cần id goal."}
        row = g.set_status(user_id, gid, "doing")
        return {"text": f"Đang làm `{gid}` ◐" if row else f"Không thấy goal `{gid}`."}

    if op in ("cancel", "drop", "delete"):
        if not gid:
            return {"text": "Cần id goal."}
        row = g.set_status(user_id, gid, "cancelled")
        return {"text": f"Đã huỷ `{gid}` ✕" if row else f"Không thấy goal `{gid}`."}

    if op in ("update", "edit"):
        if not gid:
            return {"text": "Cần id goal."}
        pri = args.get("priority")
        try:
            pri_i = int(pri) if pri is not None else None
        except (TypeError, ValueError):
            pri_i = None
        row = g.update(
            user_id, gid,
            title=title or None,
            status=status or None,
            notes=notes if notes else None,
            priority=pri_i,
        )
        return {"text": f"Đã cập nhật `{gid}`." if row else f"Không thấy goal `{gid}`."}

    return {"text": "op goals: list | add | done | doing | cancel | update"}


def _h_contacts(args: dict, ctx: dict) -> dict:
    """Danh bạ kênh: list / rename / recent / resolve for multi-bot admin."""
    from services import channel_contacts as cc
    from services import channel_activity as ca

    op = str(args.get("op") or "list").strip().lower()
    platform = str(args.get("platform") or "").strip().lower()
    if platform in ("telegram", "tele"):
        platform = "tg"
    bot_id = str(args.get("bot_id") or "").strip()
    q = str(args.get("query") or args.get("q") or "").strip()

    if op in ("recent", "who", "ai_vua_nhan", "ai vừa nhắn"):
        plat = platform or ""
        rows = ca.recent(plat, limit=int(args.get("limit") or 15))
        if not rows:
            return {"text": "Chưa có hoạt động gần đây trên kênh."}
        lines = ["📨 Ai vừa nhắn (gần nhất):"]
        for r in rows[:15]:
            bl = cc.bot_label(r.get("platform") or plat, r.get("account") or "")
            lines.append(
                f"• bot **{bl}** (`{r.get('account')}`) "
                f"{'nhóm' if r.get('is_group') else 'chat'} `{r.get('chat_id')}` "
                f"user=`{r.get('user_id') or '—'}` "
                f"{r.get('user_name') or ''}\n"
                f"  {(r.get('text') or '')[:100]}"
            )
        return {"text": "\n".join(lines)}

    if op in ("rename", "alias", "dat_ten"):
        ref = str(args.get("ref") or args.get("key") or args.get("chat_id") or "").strip()
        alias = str(args.get("alias") or args.get("name") or "").strip()
        if not ref or not alias:
            return {"text": "Cần ref (key/chat_id) và alias. VD: ref=... alias=Anh A"}
        rec = cc.find_by_ref(ref)
        if not rec:
            return {"text": f"Không thấy danh bạ `{ref}`. Dùng contacts op=list."}
        out = cc.set_alias(str(rec["key"]), alias, mark_known=True)
        return {"text": f"Đã đặt tên **{alias}** cho `{out and out.get('key')}` — không báo lạ nữa."}

    if op in ("get", "resolve"):
        ref = str(args.get("ref") or args.get("name") or q or "").strip()
        if not ref:
            return {"text": "Cần tên / alias / chat_id."}
        hits = cc.resolve_alias(ref, platform=platform, bot_id=bot_id)
        if not hits:
            one = cc.find_by_ref(ref)
            hits = [one] if one else []
        if not hits:
            return {"text": f"Không khớp `{ref}`."}
        return {"text": "Khớp danh bạ:\n" + "\n".join(cc.describe(h) for h in hits)}

    # list
    rows = cc.list_contacts(platform, bot_id, q=q, limit=20)
    if not rows:
        return {"text": "Danh bạ trống (hoặc không khớp). Người lạ nhắn bot sẽ tự ghi."}
    lines = [f"📒 Danh bạ ({len(rows)}):"] + [cc.describe(r) for r in rows]
    return {"text": "\n".join(lines)}


def _fetch_media_bytes(url: str) -> bytes | None:
    """Tải media về BYTES — Telegram send_photo/send_audio nhận bytes, KHÔNG nhận URL."""
    u = str(url or "").strip()
    if not u:
        return None
    try:
        from pathlib import Path
        p = Path(u)
        if p.is_file():
            return p.read_bytes()
    except Exception:
        pass
    try:
        from services import net_guard
        return net_guard.fetch_media(u, timeout=120)
    except Exception:
        return None


def _send_one_contact(rec: dict, message: str, *, audio_wav: bytes | None = None,
                      audio_path: str = "", image_url: str = "") -> tuple[bool, str]:
    """Gửi 1 tin tới 1 contact đã resolve. Trả (ok, mô tả kết quả).

    Media tuỳ chọn (ưu tiên thoại → ảnh → chữ). Mỗi kênh nhận kiểu khác nhau:
      - Telegram: send_audio/send_photo nhận BYTES (ảnh URL phải tải về trước).
      - Zalo cá nhân: gửi FILE theo path (_media_fetch_candidates map → /images/…).
      - Zalo bot: thoại cần .aac URL và CHỈ gửi được 1-1 (nhóm không hỗ trợ).
    """
    plat = rec.get("platform") or "tg"
    bid = str(rec.get("bot_id") or "")
    chat = str(rec.get("chat_id") or "")
    title = (rec.get("alias") or rec.get("chat_name")
             or rec.get("display_name") or chat)
    if not chat:
        return False, f"«{title}» thiếu chat_id"
    is_group = str(rec.get("kind") or "") == "group"
    cap = (message or "")[:1000]
    try:
        if plat == "tg":
            from services import telegram_bot as tg
            bot = tg._find_bot_by_id(bid)
            if not bot:
                return False, f"bot Telegram `{bid}` không bật"
            prev = tg._cur_bot()
            try:
                tg._current.bot = bot
                if audio_wav:
                    r = tg.send_audio(chat, audio_wav, caption=cap)
                elif image_url:
                    img = _fetch_media_bytes(image_url)
                    if not img:
                        return False, f"«{title}» tải ảnh không được"
                    r = tg.send_photo(chat, img, caption=cap)
                else:
                    r = tg.send_message(chat, message)
            finally:
                tg._current.bot = prev
            return (bool(r.get("ok")), f"«{title}»" if r.get("ok")
                    else f"«{title}» lỗi: {r}")
        if plat == "zalo":
            from services import zalo_bot as zb
            bot = zb._find_bot_by_id(bid) if hasattr(zb, "_find_bot_by_id") else None
            if bot is None:
                for b in zb._bots():
                    if str(b.get("token") or "").split(":")[0] == bid:
                        bot = b
                        break
            if not bot:
                return False, f"bot Zalo `{bid}` không bật"
            prev = zb._cur_bot()
            try:
                zb._current.bot = bot
                if audio_wav:
                    if is_group:
                        return False, (f"«{title}» Zalo bot chỉ gửi thoại 1-1, "
                                       "nhóm thì API không hỗ trợ")
                    aac = zb._wav_to_aac_public_url(audio_wav)
                    r = (zb.send_voice(chat, aac) if aac
                         else {"ok": False, "error": "không tạo được .aac"})
                elif image_url:
                    r = zb.send_photo(chat, image_url, caption=cap)
                else:
                    r = zb.send_message(chat, message)
            finally:
                zb._current.bot = prev
            return (bool(r.get("ok")), f"«{title}»" if r.get("ok")
                    else f"«{title}» lỗi: {r}")
        if plat == "zalop":
            # Zalo Cá nhân: gửi bằng chính account (bot_id=ownId), nhóm→type 1
            from services import zalo_personal as zp
            ttype = 1 if is_group else 0
            if audio_path:
                ok = zp._send_file_robust(chat, audio_path, cap[:200], ttype, account=bid)
                return (ok, f"«{title}»" if ok else f"«{title}» gửi file thoại lỗi")
            if image_url:
                ok = zp._send_photo_robust(chat, image_url, cap[:200], ttype, account=bid)
                return (ok, f"«{title}»" if ok else f"«{title}» gửi ảnh lỗi")
            r = zp.send_message(chat, message, ttype, account=bid)
            return (bool(r.get("ok")), f"«{title}»" if r.get("ok")
                    else f"«{title}» lỗi: {r.get('error') or r}")
    except Exception as exc:
        return False, f"«{title}» lỗi: {str(exc)[:120]}"
    return False, f"«{title}» platform `{plat}` chưa hỗ trợ"


def _admin_recipient(platform: str, ctx: dict) -> dict | None:
    """Contact 'admin' của kênh đang dùng (để gửi 'cho admin'/'cho tôi').

    zalop: Admin #1 của account (zalo_personal_account_admins[acc].admin_thread).
    tg/zalo: admin_entries[0] của bot đang hoạt động.
    """
    try:
        from services.config import config as _cfg
        cfg = _cfg.get() if hasattr(_cfg, "get") else {}
    except Exception:
        cfg = {}
    plat = platform or _channel_of(ctx)
    if plat == "zalop":
        # account gửi lấy Admin #1 đã cấu hình (bất kỳ acc nào có admin_thread)
        amap = (cfg or {}).get("zalo_personal_account_admins") or {}
        if isinstance(amap, dict):
            for own, entry in amap.items():
                if not isinstance(entry, dict):
                    continue
                th = str(entry.get("admin_thread") or "").strip()
                if th:
                    acc = str(own)
                    ttype = str(entry.get("admin_thread_type") or "0")
                    return {"platform": "zalop", "bot_id": acc, "chat_id": th,
                            "kind": "group" if ttype == "1" else "private",
                            "alias": "Admin"}
        return None
    # tg / zalo: lấy admin từ danh sách bot
    try:
        mod = __import__("services.telegram_bot" if plat == "tg"
                         else "services.zalo_bot", fromlist=["_bots"])
        for b in (mod._bots() if hasattr(mod, "_bots") else []):
            ents = b.get("admin_entries") or []
            if ents and str(ents[0].get("chat_id") or "").strip():
                e = ents[0]
                bid = str(b.get("token") or "").split(":")[0]
                return {"platform": plat, "bot_id": bid,
                        "chat_id": str(e.get("chat_id")),
                        "kind": e.get("kind") or "private", "alias": "Admin"}
    except Exception:
        pass
    return None


def _h_send_to_contact(args: dict, ctx: dict) -> dict:
    """Gửi tin tới contact đã lưu — TÁCH nhiều người theo dấu phẩy, LỌC theo
    đúng kênh đang dùng (không quét cả 3 kênh), hỗ trợ tg/zalo/zalop."""
    from services import channel_contacts as cc

    raw_ref = str(args.get("ref") or args.get("name") or args.get("to") or "").strip()
    message = str(args.get("message") or args.get("text") or "").strip()
    # Khử tiền tố KHUNG lệnh lỡ lọt vào nội dung (vd 'nội dung chính là ...',
    # 'với nội dung ...', 'nhắn rằng ...') — giữ nguyên nếu khử ra rỗng.
    _stripped = re.sub(
        r"^\s*(?:với\s+)?(?:nội\s*dung(?:\s+chính)?|nhắn(?:\s+rằng)?|nói\s+rằng|rằng)\s*(?:là\b|:)?\s*",
        "", message, flags=re.I,
    ).strip()
    if _stripped:
        message = _stripped
    bot_id = str(args.get("bot_id") or args.get("via_bot") or "").strip()
    platform = str(args.get("platform") or "").strip().lower()
    if platform in ("telegram", "tele"):
        platform = "tg"
    # KÊNH đang dùng (từ user_id: zalop_/zalo_/tg) — chốt phạm vi danh bạ để
    # không khớp nhầm thread_id của kênh khác, không gửi lộn sang kênh khác.
    if not platform:
        platform = _channel_of(ctx)
    # resolve_only: chỉ TRA + phát hiện mập mờ, KHÔNG gửi. Dùng khi đặt việc
    # hẹn giờ để hỏi lại NGAY lúc tạo (lúc user còn đó) thay vì đoán lúc bắn.
    resolve_only = bool(args.get("_resolve_only"))
    if not raw_ref or not message:
        _no = "Cần `to`/`name` (alias) và `message`."
        return {"need_clarify": True, "text": _no} if resolve_only else {"text": _no}

    # Media kèm theo (thoại TTS / ảnh) — tạo MỘT lần, dùng cho MỌI người nhận.
    want_voice = bool(args.get("voice") or args.get("as_voice") or args.get("send_voice"))
    img_url = str(args.get("image_url") or args.get("image") or "").strip()
    media_kw: dict = {}
    if not resolve_only:
        if want_voice:
            try:
                from services import voice as _voice
                if not _voice.tts_ready():
                    return {"text": "TTS đang tắt nên em chưa tạo được file âm thanh ạ 😢"}
                import uuid
                from pathlib import Path
                from services.config import config as _cfg
                _wav = _voice.speak_reply(message[:1200],
                                          str((ctx or {}).get("user_id") or ""))
                _dir = Path(_cfg.images_dir) / "voice"
                _dir.mkdir(parents=True, exist_ok=True)
                _p = _dir / f"tts_{uuid.uuid4().hex[:10]}.wav"
                _p.write_bytes(_wav)
                media_kw = {"audio_wav": _wav, "audio_path": str(_p)}
            except Exception as exc:
                return {"text": f"Em tạo file âm thanh lỗi: {str(exc)[:140]}"}
        elif img_url:
            media_kw = {"image_url": img_url}

    # "admin"/"tôi"/"mình" → gửi cho chính admin của kênh đang dùng
    if re.fullmatch(r"(admin|quản trị|quan tri|tôi|toi|mình|minh|chính chủ|chinh chu)",
                    raw_ref, re.I):
        rec = _admin_recipient(platform, ctx)
        if not rec:
            _no = "Chưa cấu hình admin cho kênh này (Settings → Admin)."
            return {"need_clarify": True, "text": _no} if resolve_only else {"text": _no}
        if resolve_only:
            return {"resolved": [rec], "need_clarify": False, "text": ""}
        ok, desc = _send_one_contact(rec, message, **media_kw)
        return {"text": (f"✅ Đã gửi admin: {desc}" if ok else f"⚠️ {desc}")}

    # ── Tra danh bạ ĐA KÊNH + phát hiện mập mờ → HỎI LẠI ─────────────────
    # Chỉ gửi khi ra ĐÚNG MỘT thread khớp chính xác. Nếu khớp không dấu /
    # gần giống, tên có ở nhiều kênh, trùng cả nhóm lẫn cá nhân, hoặc nhiều
    # bot → liệt kê ứng viên và hỏi lại, KHÔNG tự gửi.
    import unicodedata

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFD", str(s or ""))
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return " ".join(s.casefold().split())

    _ap = str(args.get("platform") or "").strip().lower()
    if _ap in ("telegram", "tele"):
        _ap = "tg"

    # Kiểm tra xem người dùng có THẬT SỰ nêu kênh trong câu nói không
    # (tránh LLM tự đoán platform="zalop"/"zalo" khi người dùng chưa hề nêu kênh).
    # ctx["user_message"] do orchestrator._execute bơm vào (câu gốc lượt này).
    user_raw = str((ctx or {}).get("user_message") or "").lower()
    # Cụm dài/an toàn khớp trực tiếp; token ngắn khớp theo RANH GIỚI TỪ để tránh
    # dương tính giả ('oa' trong 'hoa/khoản/ngoài', 'bot' trong 'robot', 'tg'…).
    _CH_PHRASES = ("cá nhân", "zalo cá nhân", "zalo bot", "zalo oa")
    _CH_WORDS = ("zalop", "zalo", "telegram", "tele", "tg", "bot", "oa")
    user_mentioned_channel = bool(user_raw) and (
        any(p in user_raw for p in _CH_PHRASES)
        or re.search(r"\b(" + "|".join(_CH_WORDS) + r")\b", user_raw) is not None
    )

    if _ap and user_raw and not user_mentioned_channel:
        explicit_platform = ""
    else:
        explicit_platform = _ap

    search_platforms = [explicit_platform] if explicit_platform else ["tg", "zalo", "zalop"]
    _CH_LABEL = {"tg": "Telegram", "zalo": "Zalo", "zalop": "Zalo cá nhân"}

    def _cands(ref: str) -> list[dict]:
        ref_norm = _norm(ref)
        ref_low = ref.strip().casefold()
        seen: set = set()
        out: list[dict] = []
        for pf in search_platforms:
            if not pf:
                continue
            rows: list[dict] = []
            try:
                for hh in cc.resolve_alias(ref, platform=pf, bot_id=bot_id):
                    rows.append({
                        "platform": pf, "bot_id": str(hh.get("bot_id") or ""),
                        "bot_label": hh.get("bot_label") or "",
                        "chat_id": str(hh.get("chat_id") or ""),
                        "kind": hh.get("kind") or "user",
                        "name": hh.get("alias") or hh.get("chat_name") or hh.get("display_name") or "",
                    })
            except Exception:
                pass
            try:
                for d in cc.list_directory(pf):
                    rows.append({
                        "platform": pf, "bot_id": str(d.get("bot_id") or ""),
                        "bot_label": d.get("bot_label") or "",
                        "chat_id": str(d.get("thread_id") or ""),
                        "kind": d.get("kind") or "user",
                        "name": d.get("name") or "",
                    })
            except Exception:
                pass
            for r in rows:
                if bot_id and r["bot_id"] and r["bot_id"] != bot_id \
                        and str(r["bot_label"]).lower() != bot_id.lower():
                    continue
                nm = r["name"]
                nm_norm = _norm(nm)
                if not nm_norm and not r["chat_id"]:
                    continue
                if nm.strip().casefold() == ref_low or r["chat_id"] == ref.strip():
                    r["quality"] = "exact"
                elif nm_norm and nm_norm == ref_norm:
                    r["quality"] = "noaccent"
                elif ref_norm and (ref_norm in nm_norm or nm_norm in ref_norm):
                    r["quality"] = "partial"
                else:
                    continue
                k = (r["platform"], r["bot_id"], r["chat_id"])
                if k in seen:
                    continue
                seen.add(k)
                out.append(r)
        return out

    # Ưu tiên kiểm tra cả tên gốc trước (phòng trường hợp tên nhóm có chứa dấu phẩy như "Docker, Calendar, Weather")
    whole_cands = _cands(raw_ref)
    if whole_cands:
        refs = [raw_ref]
    else:
        # Nhiều người nhận: tách theo "A, B" / "A; B" / "A và B"
        refs = [x.strip() for x in re.split(r"[,;]|\bvà\b|\band\b", raw_ref) if x.strip()]
        if not refs:
            refs = [raw_ref]

    def _rec_of(c: dict) -> dict:
        return {
            "platform": c["platform"], "bot_id": c["bot_id"],
            "chat_id": c["chat_id"], "kind": c["kind"],
            "chat_name": c["name"], "alias": c["name"],
            "bot_label": c["bot_label"],
        }

    def _label(c: dict) -> str:
        kind = "nhóm" if c["kind"] == "group" else "cá nhân"
        ch = _CH_LABEL.get(c["platform"], c["platform"])
        bl = f" · bot {c['bot_label']}" if c["bot_label"] else ""
        return f"{c['name'] or c['chat_id']} ({kind}, {ch}{bl})"

    sent: list[str] = []
    failed: list[str] = []
    ambiguous: list[str] = []
    resolved: list[dict] = []
    for ref in refs:
        cands = _cands(ref)
        exact = [c for c in cands if c["quality"] == "exact"]
        # Nếu người dùng CHƯA nêu rõ kênh gửi (explicit_platform rỗng),
        # BẮT BUỘC hỏi làm rõ kênh (Zalo cá nhân / Zalo bot / Telegram) chứ KHÔNG tự chọn.
        if not explicit_platform:
            show = exact or cands
            if show:
                opts = "; ".join(_label(c) for c in show[:8])
                ambiguous.append(
                    f"«{ref}» chưa nêu rõ kênh gửi (Zalo cá nhân / Zalo bot / Telegram) — nói rõ giúp em: {opts}"
                )
                continue
        # Chắc chắn: đúng MỘT mục khớp chính xác → gửi (hoặc chỉ ghi nhận khi resolve_only).
        if len(exact) == 1:
            if resolve_only:
                resolved.append(_rec_of(exact[0]))
                continue
            ok, desc = _send_one_contact(_rec_of(exact[0]), message, **media_kw)
            (sent if ok else failed).append(desc)
            continue
        if not cands:
            failed.append(
                f"«{ref}» không thấy trong danh bạ"
                + (f" kênh {explicit_platform}" if explicit_platform else " (đã tra mọi kênh)")
            )
            continue
        # Mập mờ → nêu lý do + liệt kê để người dùng chọn, KHÔNG tự gửi.
        show = exact or cands
        reasons: list[str] = []
        if not exact:
            reasons.append("chỉ khớp gần đúng/không dấu")
        if len({c["platform"] for c in show}) > 1:
            reasons.append("có ở nhiều kênh")
        if len({c["kind"] for c in show}) > 1:
            reasons.append("trùng cả nhóm lẫn cá nhân")
        if exact and len(show) > 1 \
                and len({c["platform"] for c in show}) == 1 \
                and len({c["kind"] for c in show}) == 1:
            reasons.append("nhiều mục cùng tên (nhiều bot)")
        why = " / ".join(reasons) or "chưa đủ chắc chắn"
        opts = "; ".join(_label(c) for c in show[:8])
        ambiguous.append(f"«{ref}» {why} — nói rõ giúp em: {opts}")

    # resolve_only: trả kết quả tra cho caller (vd _h_schedule) tự quyết — hỏi
    # lại khi mập mờ/thiếu, hay đặt lịch khi đã rõ. KHÔNG gửi gì ở đây.
    if resolve_only:
        _bits = ambiguous + failed
        return {
            "resolved": resolved,
            "ambiguous": ambiguous,
            "failed": failed,
            "need_clarify": bool(_bits),
            "text": ("❓ " + "; ".join(_bits)) if _bits else "",
        }

    parts = []
    if sent:
        parts.append(f"✅ Đã gửi: {', '.join(sent)}")
    if ambiguous:
        parts.append("❓ " + "; ".join(ambiguous))
    if failed:
        parts.append("⚠️ " + "; ".join(failed))
    if not parts:
        return {"text": f"Không gửi được `{raw_ref}`. Dùng contacts op=list."}
    return {"text": "\n".join(parts)}


_MEDIA_EXT = {
    "image": (".png", ".jpg", ".jpeg", ".webp", ".gif"),
    "video": (".mp4", ".webm", ".mov"),
    "music": (".mp3", ".m4a", ".wav", ".ogg"),
}
_MEDIA_LABEL = {"image": "🖼️ Ảnh", "video": "🎬 Video", "music": "🎵 Nhạc"}


#: Trần số ảnh một lượt. 50 là giới hạn THẬT đọc được từ phiên Zalo cá nhân
#: (settings.features.sharefile.max_file — đo 30/07 trên tài khoản đang dùng).
#: Kênh nào thấp hơn thì tầng gửi tự chia lô theo giới hạn của kênh đó.
_MAX_ANH_MOT_LUOT = 50


#: Chữ số viết bằng lời — người Việt hay nói "ba ảnh" hơn "3 ảnh".
_SO_CHU = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5, "sáu": 6,
           "bảy": 7, "tám": 8, "chín": 9, "mười": 10, "vài": 3, "mấy": 3}

#: "3 ảnh", "ba tấm", "5 hình", "10 bức" — số ĐỨNG TRƯỚC danh từ chỉ ảnh. Bắt
#: buộc có danh từ đó, nếu không thì "gửi cho tôi 3 bài toán" cũng thành 3 ảnh.
_RE_SO_ANH = re.compile(
    r"(\d{1,2}|một|hai|ba|bốn|tư|năm|sáu|bảy|tám|chín|mười|vài|mấy)\s*"
    r"(?:cái\s+|tấm\s+|bức\s+)?(ảnh|anh|hình|hinh|tấm|tam|bức|buc|photo|image)",
    re.IGNORECASE)


def _so_luong_anh(args: dict, ctx: dict | None = None) -> int:
    """Số ảnh người dùng xin, kẹp trong [1, 50]. Giá trị lạ → 1.

    Đọc THÊM từ câu gốc khi model không truyền tham số — đo thật 30/07: gọi
    handler với `so_luong=3` ra đúng 3 ảnh, nhưng người dùng nhắn "gửi 3 ảnh mới
    nhất" thì chỉ nhận 1 ảnh, vì model bỏ qua tham số dù mô tả tool đã ghi rõ.
    Không thể ép model, nên đọc từ chính câu nói: đó là nguồn sự thật gần nhất
    với ý người dùng.

    Kẹp thay vì báo lỗi: model đôi khi truyền "ba" hoặc 999. Trả 1 tấm còn dùng
    được, còn báo lỗi thì mất luôn lượt trả lời.
    """
    for k in ("so_luong", "count", "n", "so"):
        v = args.get(k)
        if v in (None, ""):
            continue
        try:
            return max(1, min(_MAX_ANH_MOT_LUOT, int(v)))
        except (TypeError, ValueError):
            # Model truyền chữ ("ba") — thử tra bảng trước khi bỏ.
            n = _SO_CHU.get(str(v).strip().lower())
            if n:
                return max(1, min(_MAX_ANH_MOT_LUOT, n))
            continue
    m = _RE_SO_ANH.search(str((ctx or {}).get("user_message") or ""))
    if m:
        raw = m.group(1).lower()
        n = _SO_CHU.get(raw) or (int(raw) if raw.isdigit() else 0)
        if n:
            return max(1, min(_MAX_ANH_MOT_LUOT, n))
    return 1


def _media_cua_nguoi_nay(ctx: dict, so: int, exts: tuple[str, ...],
                         theo_ten: bool = False) -> list[str]:
    """`so` media gần nhất do CHÍNH người đang hỏi tạo, LỌC theo đuôi tệp.

    Sổ `anh_cua_toi` giờ ghi cả video/nhạc (orchestrator ghi mọi media sinh ra),
    nên phải lọc — không thì "3 ảnh của tôi" lẫn cả video.

    `theo_ten=True`: khớp theo TÊN TỆP chứa `exts` (dùng cho nhạc: tên có 'nhac_'
    nhưng đuôi lại là .mp4 nên lọc theo đuôi sẽ trượt).
    """
    uid = str((ctx or {}).get("user_id") or "").strip()
    if not uid:
        return []
    try:
        from services.agent import anh_cua_toi
        tat_ca = anh_cua_toi.gan_nhat(uid, 200)
    except Exception:
        return []
    if theo_ten:
        ra = [u for u in tat_ca
              if any(k in str(u).lower().rsplit("/", 1)[-1] for k in exts)]
    else:
        ra = [u for u in tat_ca
              if any(str(u).lower().split("?")[0].endswith(e) for e in exts)]
    return ra[:so]


def _anh_cua_nguoi_nay(ctx: dict, so: int) -> list[str]:
    """`so` ảnh gần nhất do CHÍNH người đang hỏi tạo. Rỗng nếu chưa có sổ."""
    return _media_cua_nguoi_nay(ctx, so, _MEDIA_EXT["image"])


def _h_library_media(args: dict, ctx: dict) -> dict:
    """Lấy media ĐÃ TẠO (ảnh/video/nhạc) và gửi lại — có PHÂN QUYỀN.

    Đặc tả của chủ máy (31/07/2026):
      • ADMIN: "trong thư viện" = kho CHUNG (media mới nhất của bất kỳ ai);
        "anh tạo / của tôi" = sổ riêng của chính admin.
      • USER THƯỜNG: yêu cầu kiểu gì cũng CHỈ nhận media do chính họ tạo —
        tuyệt đối không rơi về kho chung (kho có media của người khác, ảnh
        camera, ảnh test; lộ là hỏng cả riêng tư lẫn đúng đắn).

    `scope`: "mine" | "all" — đường tắt ở orchestrator suy từ câu nói; model
    gọi tay thì được phép truyền. Không phải admin thì ép "mine" bất kể ai nói gì.
    """
    from services.config import config as _cfg
    kind = str(args.get("kind") or "image").strip().lower()
    if kind in ("photo", "ảnh", "anh", "hình"):
        kind = "image"
    elif kind in ("nhạc", "nhac", "audio", "bài hát", "song"):
        kind = "music"
    elif kind in ("phim", "clip"):
        kind = "video"
    exts = _MEDIA_EXT.get(kind, _MEDIA_EXT["image"])
    # NHẠC lưu dưới dạng .mp4 (audio + bìa động của Lyria) trong THƯ VIỆN VIDEO,
    # tên tiền tố 'nhac_'. Nên kind="music" phải nhận file .mp4 nhac_* — chứ không
    # phải .mp3 (chẳng có). VIDEO thường thì loại các file nhac_ ra để không lẫn.
    def _khop_loai(p) -> bool:
        ten = p.name.lower()
        if kind == "music":
            return ten.startswith("nhac_") or p.suffix.lower() in _MEDIA_EXT["music"]
        if kind == "video":
            return p.suffix.lower() in exts and not ten.startswith("nhac_")
        return p.suffix.lower() in exts
    # Nhãn TRƠN cho giữa câu ("chưa tạo ảnh nào") — _MEDIA_LABEL có emoji + viết
    # hoa ("🖼️ Ảnh"), nhét thẳng vào câu thành "chưa tạo 🖼️ Ảnh nào".
    nhan = {"image": "ảnh", "video": "video", "music": "bản nhạc"}.get(kind, "media")
    so = _so_luong_anh(args, ctx) if kind == "image" else 1

    la_admin = bool((ctx or {}).get("is_admin"))
    scope = str(args.get("scope") or "").strip().lower()
    if not la_admin:
        scope = "mine"
    elif scope not in ("mine", "all"):
        scope = "all"      # admin không nói rõ → kho chung ("thư viện" là của admin)

    # ── SỔ RIÊNG (mine) — không đụng tới kho chung ────────────────────────
    if scope == "mine":
        # Nhạc: khớp theo tiền tố tên 'nhac_' (mp4), không theo đuôi audio.
        loc = (["nhac_"] if kind == "music" else list(exts))
        cua_toi = _media_cua_nguoi_nay(ctx, so, tuple(loc), theo_ten=(kind == "music"))
        if not cua_toi:
            return {"text": (f"Anh/chị chưa tạo {nhan} nào qua em, nên em không có "
                             f"gì để gửi lại ạ. Muốn tạo mới thì anh/chị cứ nói nhé!")}
        if kind == "image":
            if len(cua_toi) == 1:
                return {"text": "Ảnh gần nhất anh/chị tạo ạ.", "image_url": cua_toi[0]}
            thieu_t = ("" if len(cua_toi) >= so
                       else f" (anh/chị mới tạo {len(cua_toi)} ảnh, chưa đủ {so})")
            return {"text": f"{len(cua_toi)} ảnh gần nhất anh/chị tạo ạ{thieu_t}.",
                    "image_urls": cua_toi}
        # video/nhạc: sổ có thể chứa URL hoặc ĐƯỜNG DẪN cục bộ (nhánh bot lưu
        # file) — chọn đúng khoá để kênh gửi được cả hai.
        nguon = cua_toi[0]
        khoa = ("video_path" if kind == "video" else "audio_path") \
            if str(nguon).startswith("/") else \
            ("video_url" if kind == "video" else "audio_url")
        return {"text": f"{nhan.capitalize()} gần nhất anh/chị tạo ạ.", khoa: nguon}

    # ── KHO CHUNG (all — chỉ admin tới được đây) ──────────────────────────
    d = _cfg.images_dir
    try:
        files = [p for p in d.rglob("*") if p.is_file() and _khop_loai(p)
                 and "_thumb" not in p.name]  # bỏ file thumbnail
    except Exception:
        files = []
    if not files:
        return {"text": f"Thư viện chưa có {nhan} nào ạ."}
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    newest = files[0]
    import datetime as _dt
    when = _dt.datetime.fromtimestamp(newest.stat().st_mtime).strftime("%H:%M %d/%m")
    rel = newest.relative_to(d).as_posix()
    url = f"http://127.0.0.1:80/images/{rel}"
    caption = f"{_MEDIA_LABEL.get(kind, 'Media')} mới nhất trong thư viện (tạo lúc {when}) ạ."
    if kind == "image":
        if so <= 1:
            return {"text": caption, "image_url": url}
        # Nhiều ảnh: lấy N tấm mới nhất, LỌC TRÙNG theo nội dung — thư viện có
        # tệp trùng nội dung khác tên (tên = <epoch>_<md5>, trùng nội dung là
        # trùng phần hash; đo thật 30/07).
        chon: list[str] = []
        da_thay: set[str] = set()
        for p in files:
            try:
                van = p.stat().st_size, p.name.split("_", 1)[-1]
            except Exception:
                continue
            if van in da_thay:
                continue
            da_thay.add(van)
            chon.append(f"http://127.0.0.1:80/images/{p.relative_to(d).as_posix()}")
            if len(chon) >= so:
                break
        if len(chon) <= 1:
            return {"text": caption, "image_url": url}
        thieu = ("" if len(chon) >= so
                 else f" (thư viện chỉ có {len(chon)} ảnh KHÁC NHAU, không đủ {so})")
        return {"text": f"{len(chon)} ảnh mới nhất trong thư viện ạ{thieu}.",
                "image_urls": chon}
    # Nhạc cũng là mp4 (Lyria) → gửi như video, KHÔNG phải audio_url.
    if kind in ("video", "music"):
        return {"text": caption, "video_url": url}
    return {"text": caption, "audio_url": url}


def _ha_model() -> str:
    return str(config.get().get("telegram_ai_model") or "").strip() or "cx/auto"


def _h_send_voice(args: dict, ctx: dict) -> dict:
    """Tạo FILE âm thanh TTS từ text rồi GỬI VÀO CHAT hiện tại (Zalo cá nhân /
    Telegram / Zalo bot 1-1) — KHÁC với phát ra loa trong nhà.

    Giọng theo persona của phiên + tông theo tính chất câu (voice.speak_reply).
    Ghi WAV vào images_dir/voice/ để mọi kênh gửi được (Telegram đọc bytes trực
    tiếp; Zalo map path → /images/… served URL).
    """
    from services import voice as _voice
    text = str(args.get("text") or args.get("message") or args.get("content") or "").strip()
    if not text:
        return {"text": "Anh/chị muốn em đọc nội dung gì thành file âm thanh ạ?"}
    if not _voice.tts_ready():
        return {"text": "Hiện TTS đang tắt nên em chưa tạo được file âm thanh ạ 😢"}
    uid = str((ctx or {}).get("user_id") or "")
    try:
        wav = _voice.speak_reply(text[:1200], uid)
    except Exception as exc:
        return {"text": f"Em tạo giọng nói bị lỗi: {str(exc)[:140]}"}
    try:
        import uuid
        from pathlib import Path
        from services.config import config as _cfg
        out_dir = Path(_cfg.images_dir) / "voice"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"tts_{uuid.uuid4().hex[:10]}.wav"
        path.write_bytes(wav)
    except Exception as exc:
        return {"text": f"Em lưu file âm thanh bị lỗi: {str(exc)[:140]}"}
    return {"text": "File âm thanh của anh/chị đây ạ 🎧", "audio_path": str(path)}


def _speaker_scope(ctx: dict) -> tuple[str, str]:
    """(platform, chat_id) suy từ user_id orchestrator để lọc loa theo thread."""
    uid = str((ctx or {}).get("user_id") or "")
    for prefix, plat in (("zalop_", "zalop"), ("zalo_", "zalo"), ("tg_", "tg")):
        if uid.startswith(prefix):
            return plat, uid[len(prefix):]
    return ("tg", uid)


def _h_speak_to_speaker(args: dict, ctx: dict) -> dict:
    """Đọc văn bản rồi phát ra loa trong nhà (Cast / DLNA / qua HA).

    Quyền: capability này thuộc nhóm `tts_speaker` nên chỉ hiện ở thread được
    tick. Trong thread lại còn danh sách loa được phép — không rõ loa nào thì
    HỎI LẠI thay vì đoán (yêu cầu 2026-07-19).

    Giọng: nếu Settings Giáo viên có voice_vi/voice_en → chọn theo ngôn ngữ
    đoạn text; không thì giọng TTS mặc định hệ thống.
    """
    from services import voice
    from services.agent import teacher as teach
    from services.voice import permissions as vperm
    from services.voice import speakers as vspk

    text = str(args.get("text") or args.get("message") or "").strip()
    target = str(args.get("speaker") or args.get("name") or "").strip()
    if not text:
        return {"text": "Anh/chị muốn em đọc nội dung gì ạ?"}
    if not voice.tts_ready():
        return {"text": "Em chưa bật được giọng nói (thiếu model hoặc engine) ạ."}

    plat, chat_id = _speaker_scope(ctx)
    bot_id = str(ctx.get("bot_id") or "").strip()
    user_id = str(ctx.get("user_id") or ctx.get("from_id") or "").strip()
    # Giáo viên: công tắc speak_to_speaker phải bật (khi đang dạy).
    # Lệnh loa thường (không qua teacher) vẫn theo tts_speaker như cũ.
    as_teacher = bool(args.get("as_teacher") or ctx.get("teacher_mode"))
    if as_teacher and not teach.speak_to_speaker_enabled():
        return {"text": "Chế độ Giáo viên đang tắt «phát ra loa» trong Settings ạ."}

    allowed = vperm.visible_speakers(plat, bot_id, chat_id, user_id)
    if not allowed:
        return {"text": "Chưa có loa nào được cấp cho khung chat này ạ."}

    def _menu(rows: list[dict]) -> str:
        lines = [f"{i + 1}. {vspk.describe(r)}" for i, r in enumerate(rows)]
        return ("Anh/chị muốn phát ra loa nào ạ?\n" + "\n".join(lines)
                + f"\n{len(rows) + 1}. Tất cả loa")

    if not target:
        # Ưu tiên loa mặc định giáo viên nếu nằm trong danh sách được phép.
        ds = teach.default_speaker()
        if ds:
            hit = next((r for r in allowed if r.get("id") == ds or r.get("name") == ds), None)
            if hit:
                chosen = [hit]
            elif len(allowed) == 1:
                chosen = allowed
            else:
                return {"text": _menu(allowed)}
        elif len(allowed) == 1:
            chosen = allowed
        else:
            return {"text": _menu(allowed)}
    elif target.lower() in {"tat ca", "tất cả", "all", "moi loa", "mọi loa"}:
        chosen = allowed
    else:
        hits = [r for r in vspk.resolve(target)
                if any(r.get("id") == a.get("id") for a in allowed)]
        if not hits:
            return {"text": f"Em không thấy loa «{target}» trong danh sách được phép.\n"
                            + _menu(allowed)}
        if len(hits) > 1:
            return {"text": _menu(hits)}
        chosen = hits

    voice_name = teach.voice_for_text(text) if (teach.voice_vi() or teach.voice_en()) else ""
    done, failed = [], []
    for spk in chosen:
        try:
            voice.play_text_on(text, spk, voice_name)
            done.append(str(spk.get("name")))
        except Exception as exc:
            failed.append(f"{spk.get('name')} ({str(exc)[:80]})")
    if done and not failed:
        return {"text": f"[đã phát ra loa: {', '.join(done)}]"}
    if done:
        return {"text": f"[phát được: {', '.join(done)}; lỗi: {'; '.join(failed)}]"}
    return {"text": f"Em phát không được ạ 😥: {'; '.join(failed)}"}


def _speaker_menu(rows: list[dict], *, allow_all: bool = False) -> str:
    from services.voice import speakers as vspk
    lines = [f"{i + 1}. {vspk.describe(r)}" for i, r in enumerate(rows)]
    tail = f"\n{len(rows) + 1}. Tất cả loa" if allow_all else ""
    return "Anh/chị muốn loa nào ạ?\n" + "\n".join(lines) + tail


def _h_play_music_on_speaker(args: dict, ctx: dict) -> dict:
    """Mở nhạc theo yêu cầu (YouTube) trên loa R1 — kèm âm lượng nếu có.

    Quyền theo nhóm `tts_speaker` + danh sách loa của thread; nhiều loa R1 mà
    chưa rõ thì HỎI LẠI, không đoán."""
    from services.voice import permissions as vperm
    from services.voice import speakers as vspk

    query = str(args.get("query") or args.get("song") or args.get("text") or "").strip()
    target = str(args.get("speaker") or args.get("name") or "").strip()
    if not query:
        return {"text": "Anh/chị muốn mở bài / thể loại nhạc gì ạ?"}

    plat, chat_id = _speaker_scope(ctx)
    allowed = [r for r in vperm.visible_speakers(plat, "", chat_id) if r.get("kind") == "r1"]
    if not allowed:
        return {"text": "Khung chat này chưa có loa R1 nào để mở nhạc ạ."}
    if not target:
        chosen = allowed[0] if len(allowed) == 1 else None
        if chosen is None:
            return {"text": _speaker_menu(allowed)}
    else:
        hits = [r for r in vspk.resolve(target)
                if r.get("kind") == "r1" and any(r.get("id") == a.get("id") for a in allowed)]
        if not hits:
            return {"text": f"Em không thấy loa R1 «{target}» ạ.\n" + _speaker_menu(allowed)}
        if len(hits) > 1:
            return {"text": _speaker_menu(hits)}
        chosen = hits[0]

    vol = args.get("volume")
    if vol not in (None, ""):
        try:
            vspk.set_volume(chosen, float(vol))    # R1: >1 = chỉ số tuyệt đối (vd 5)
        except Exception:
            pass
    try:
        song = vspk.play_music(chosen, query)
    except Exception as exc:
        return {"text": f"Em mở nhạc không được ạ 😥 ({str(exc)[:120]})."}
    title = str((song or {}).get("title") or query)
    return {"text": f"[đang phát trên {chosen.get('name')}: {title}]"}


def _h_announce_on_speaker(args: dict, ctx: dict) -> dict:
    """Đọc thông báo ra loa NGAY hoặc HẸN GIỜ (sau N phút), kèm âm lượng %.

    Đọc bằng TTS ra loa Cast/DLNA/HA (R1 chưa đọc TTS trực tiếp — dùng mở nhạc)."""
    from services.voice import announce as vann
    from services.voice import permissions as vperm
    from services.voice import speakers as vspk

    text = str(args.get("text") or args.get("message") or "").strip()
    target = str(args.get("speaker") or args.get("name") or "").strip()
    if not text:
        return {"text": "Anh/chị muốn thông báo nội dung gì ạ?"}

    plat, chat_id = _speaker_scope(ctx)
    allowed = vperm.visible_speakers(plat, "", chat_id)
    if not allowed:
        return {"text": "Chưa có loa nào được cấp cho khung chat này ạ."}
    if not target:
        chosen = allowed[0] if len(allowed) == 1 else None
        if chosen is None:
            return {"text": _speaker_menu(allowed)}
    else:
        hits = [r for r in vspk.resolve(target)
                if any(r.get("id") == a.get("id") for a in allowed)]
        if not hits:
            return {"text": f"Em không thấy loa «{target}» ạ.\n" + _speaker_menu(allowed)}
        if len(hits) > 1:
            return {"text": _speaker_menu(hits)}
        chosen = hits[0]

    delay = 0.0
    try:
        if args.get("delay_seconds") not in (None, ""):
            delay = max(0.0, float(args.get("delay_seconds")))
        elif args.get("delay_minutes") not in (None, ""):
            delay = max(0.0, float(args.get("delay_minutes")) * 60)
    except (TypeError, ValueError):
        delay = 0.0
    volume = None
    vol = args.get("volume")
    if vol not in (None, ""):
        try:
            volume = max(0.0, min(100.0, float(vol))) / 100.0
        except (TypeError, ValueError):
            volume = None
    try:
        vann.schedule(str(chosen.get("id")), text, delay_seconds=delay, volume=volume)
    except Exception as exc:
        return {"text": f"Em hẹn thông báo không được ạ 😥 ({str(exc)[:120]})."}
    if delay > 0:
        mins, secs = int(delay // 60), int(delay % 60)
        when = (f"{mins} phút {secs} giây" if mins and secs else
                f"{mins} phút" if mins else f"{secs} giây")
        return {"text": f"[đã hẹn đọc “{text}” ra {chosen.get('name')} sau {when}]"}
    return {"text": f"[đang đọc “{text}” ra {chosen.get('name')}]"}


def _h_describe_device(args: dict, ctx: dict) -> dict:
    """What can this device do? Live service schema + state attributes from HA.

    Nhận entity_id, hoặc tên thiết bị (tự dò trong registry theo friendly_name).
    """
    from services import ha_client

    eid = str(args.get("entity_id") or "").strip()
    name = str(args.get("name") or args.get("device") or "").strip()
    if not eid and not name:
        return {"text": "Anh/chị muốn xem thiết bị nào ạ? (tên hoặc entity_id)"}
    if not eid:
        try:
            states = ha_client.get_states() or []
        except Exception as exc:
            return {"text": f"Em chưa đọc được Home Assistant 😥 ({str(exc)[:120]})."}
        folded = ha_client._fold_diacritics(name).lower()
        best = ""
        for st in states:
            fn = str((st.get("attributes") or {}).get("friendly_name") or "")
            if not fn:
                continue
            if ha_client._fold_diacritics(fn).lower() == folded:
                best = str(st.get("entity_id") or "")
                break
            if not best and folded in ha_client._fold_diacritics(fn).lower():
                best = str(st.get("entity_id") or "")
        if not best:
            return {"text": f"Em không tìm thấy thiết bị «{name}» trong nhà mình ạ."}
        eid = best
    try:
        return {"text": ha_client.describe_entity_actions(eid)}
    except Exception as exc:
        return {"text": f"Em chưa xem được khả năng của `{eid}` 😥 ({str(exc)[:120]})."}


def _h_home_status(args: dict, ctx: dict) -> dict:
    """Read Home Assistant entity states (sensors, lights, cameras, HA-host
    system-monitor…) so the model can answer questions about the home."""
    from services import ha_client
    query = str(args.get("query") or "").strip()
    try:
        states = ha_client.get_states()
    except Exception as exc:
        return {"text": f"Em chưa kết nối được Home Assistant 😥 ({str(exc)[:120]})."}
    if not states:
        return {"text": "Home Assistant chưa cấu hình hoặc không có thiết bị nào ạ."}
    if query:
        ql = query.lower()
        sel = [s for s in states
               if ql in (s.get("entity_id", "") + " " +
                         str((s.get("attributes") or {}).get("friendly_name", ""))).lower()]
        sel = sel or states
    else:
        sel = states
    lines = []
    for s in sel[:40]:
        attrs = s.get("attributes") or {}
        name = attrs.get("friendly_name") or s.get("entity_id", "")
        unit = attrs.get("unit_of_measurement") or ""
        lines.append(f"- {name}: {s.get('state', '')}{(' ' + unit) if unit else ''}")
    more = f"\n(còn {len(sel) - 40} mục nữa)" if len(sel) > 40 else ""
    return {"text": "Trạng thái nhà (Home Assistant):\n" + "\n".join(lines) + more}


def _ha_relevant_entities(request: str, limit: int = 40) -> str:
    """Danh sách entity_id + tên khớp từ khóa trong yêu cầu — để model dùng
    ĐÚNG entity thật khi viết automation."""
    from services import ha_client
    try:
        states = ha_client.get_states()
    except Exception:
        return ""
    ql = request.lower()
    words = [w for w in ql.replace(",", " ").split() if len(w) > 2]
    scored = []
    for s in states:
        eid = s.get("entity_id", "")
        dom = eid.split(".")[0]
        if dom in ("automation", "sensor", "binary_sensor", "device_tracker", "sun", "person"):
            continue
        name = str((s.get("attributes") or {}).get("friendly_name", "")).lower()
        hay = eid.lower() + " " + name
        if any(w in hay for w in words):
            scored.append(f"{eid} = {(s.get('attributes') or {}).get('friendly_name', eid)}")
    return "\n".join(scored[:limit])


def _h_create_automation(args: dict, ctx: dict) -> dict:
    """Tạo automation Home Assistant từ mô tả: model viết YAML → ỦY QUYỀN cho
    ha_client.create_automation_and_verify (vá nháy thời gian + reviewer soi
    trước khi ghi + entity PHẢI tồn tại thật + verify qua error_log HA, tự sửa
    khi lỗi tới 2 lần) — KHÔNG tự POST JSON thẳng vào HA nữa, vì đường cũ chỉ
    soát entity bằng dò chuỗi con (thiếu hẳn 3 tầng kiểm duyệt kể trên)."""
    import time as _t
    request = str(args.get("request") or "").strip()
    if not request:
        return {"text": "Anh/chị muốn tạo automation làm gì ạ?"}
    from services import ha_client
    cfg = ha_client._get_ha_config()
    if not cfg or not cfg.get("url") or not cfg.get("token"):
        return {"text": "Home Assistant chưa cấu hình URL/token nên em chưa tạo được ạ."}
    ents = _ha_relevant_entities(request)
    aid = str(int(_t.time() * 1000))
    prompt = (
        "Bạn viết YAML AUTOMATION Home Assistant hoàn chỉnh (một entry của "
        "automations.yaml). CHỈ xuất YAML (không giải thích, không bọc ```), "
        f"bắt đầu bằng '- id: \"{aid}\"', gồm: id, alias (tên tiếng Việt), "
        "trigger, condition (list, có thể rỗng), action, mode: single. Dùng "
        "ĐÚNG entity_id trong danh sách dưới (nếu có). Không bịa entity.\n"
        + (f"\nEntity khả dụng:\n{ents}\n" if ents else "")
        + f"\nYêu cầu: {request}"
    )
    resp = call_model(branch_model("code", _channel_of(ctx)), [{"role": "user", "content": prompt}],
                      timeout=120, max_tokens=1200)
    yaml_text = str(content_of(resp) or "").strip()
    if yaml_text.startswith("```"):
        yaml_text = re.sub(r"^```[a-zA-Z]*\n?", "", yaml_text)
        yaml_text = re.sub(r"\n?```$", "", yaml_text).strip()
    if not yaml_text:
        return {"text": "Em không tạo được cấu hình automation, anh/chị mô tả rõ hơn giúp em nhé."}
    _status, _text = ha_client.create_automation_and_verify(yaml_text)
    return {"text": _text}


def _h_system_status(args: dict, ctx: dict) -> dict:
    """Report resource usage of THIS server — the container the bot runs in."""
    lines = []
    try:
        with open("/proc/loadavg") as f:
            load = f.read().split()[:3]
        lines.append(f"Tải CPU (1/5/15 phút): {', '.join(load)} — {os.cpu_count()} nhân")
    except Exception:
        pass
    try:
        mem: dict[str, str] = {}
        with open("/proc/meminfo") as f:
            for ln in f:
                k, _, v = ln.partition(":")
                mem[k.strip()] = v.strip()
        total = int(mem.get("MemTotal", "0 kB").split()[0])
        avail = int(mem.get("MemAvailable", "0 kB").split()[0])
        used = total - avail
        pct = (used * 100 // total) if total else 0
        lines.append(f"RAM: {used // 1024} MB / {total // 1024} MB ({pct}%)")
    except Exception:
        pass
    try:
        du = shutil.disk_usage("/app/data")
        lines.append(f"Ổ đĩa: {du.used // (1024**3)} GB / {du.total // (1024**3)} GB "
                     f"({du.used * 100 // du.total}%)")
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        lines.append(f"Uptime: {int(up // 3600)} giờ {int((up % 3600) // 60)} phút")
    except Exception:
        pass
    body = "\n".join(lines) or "Em chưa đọc được thông tin phần cứng."
    return {"text": "Máy chủ em đang chạy (container c2a):\n" + body}


def _h_control_home(args: dict, ctx: dict) -> dict:
    """Control a smart-home device by forwarding the natural-language command
    to the existing Home-Assistant pipeline (intent parsing + confirmation)."""
    command = str(args.get("command") or "").strip()
    if not command:
        return {"text": "Anh/chị muốn em điều khiển thiết bị gì ạ?"}
    resp = call_model(_ha_model(), [{"role": "user", "content": command}],
                      timeout=60, allow_fastpath=True)
    if resp.get("error"):
        return {"text": f"Em điều khiển bị lỗi 😥 ({resp['error']}). Anh/chị muốn thử lại không?"}
    raw = content_of(resp) or ""
    # Return the raw HA result as DATA (not the final reply) so the orchestrator
    # loop lets the model phrase it warmly ("Dạ em bật đèn phòng khách rồi ạ 😊")
    # instead of echoing the pipeline's canned "Đã thực hiện xong lệnh...".
    return {"text": f"[kết quả từ hệ thống nhà cho lệnh '{command}']: {raw or 'đã gửi lệnh'}"}


_REMOTE_CMDS = [
    ("Hệ điều hành", "uname -sr 2>/dev/null"),
    ("Uptime & tải", "uptime 2>/dev/null"),
    ("CPU", "nproc 2>/dev/null; grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2"),
    ("RAM", "free -h 2>/dev/null | head -2"),
    ("Ổ đĩa /", "df -h / 2>/dev/null | tail -1"),
    ("Top tiến trình", "ps -eo pcpu,pmem,comm --sort=-pcpu 2>/dev/null | head -6"),
]


def _h_remote_system_status(args: dict, ctx: dict) -> dict:
    """SSH into a machine the user gives credentials for and read a fixed,
    read-only diagnostic bundle (no arbitrary commands)."""
    host = str(args.get("host") or "").strip()
    user = str(args.get("user") or "").strip()
    password = str(args.get("password") or "")
    try:
        port = int(args.get("port") or 22)
    except Exception:
        port = 22
    if not (host and user and password):
        return {"text": "Cho em xin host, user và mật khẩu SSH của máy cần xem ạ."}
    try:
        import paramiko
    except Exception:
        return {"text": "Máy chủ chưa cài thư viện SSH (paramiko) nên em chưa vào được ạ."}
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507 — may LAN ad-hoc, user tu cap creds, khong pin duoc host key
    try:
        cli.connect(host, port=port, username=user, password=password, timeout=15,
                    allow_agent=False, look_for_keys=False)
    except Exception as exc:
        return {"text": f"Em không đăng nhập được {host} 😥 ({str(exc)[:120]})."}
    out = [f"Thông tin máy {host}:"]
    try:
        for label, cmd in _REMOTE_CMDS:
            try:
                _in, _o, _e = cli.exec_command(cmd, timeout=12)
                res = _o.read().decode("utf-8", "ignore").strip()
                if res:
                    out.append(f"• {label}: {res}")
            except Exception:
                pass
    finally:
        try:
            cli.close()
        except Exception:
            pass
    return {"text": "\n".join(out)}


# ── OfficeCLI (Word/Excel/PowerPoint) — native in-process, KHÔNG qua MCP ────
# Binary trong image (Dockerfile OFFICECLI_VERSION), runner services/officecli.py
# sandbox mọi path dưới DATA_DIR/office. Chỉ office_send trả doc_path (gửi file
# thật) — các tool soạn/sửa trả text để orchestrator không cắt vòng lặp sớm.


def _h_office_files(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    st = oc.status()
    if not st.get("ok"):
        return {"text": "OfficeCLI chưa sẵn sàng trong container (thiếu binary)."}
    files = oc.list_files()
    if not files:
        return {"text": f"Workspace {st['workspace']} chưa có file Office nào."}
    lines = [f"• {f['path']} ({f['bytes']:,} bytes)" for f in files[:50]]
    return {"text": "File Office hiện có:\n" + "\n".join(lines)}


def _h_office_create(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    try:
        res = oc.create(str(args.get("filename") or ""))
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}
    return {"text": res.get("text") or "OK"}


def _h_office_view(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    try:
        return {"text": oc.view(str(args.get("path") or ""),
                                str(args.get("mode") or "outline"))}
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}


def _h_office_query(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    path = str(args.get("path") or "")
    selector = str(args.get("selector") or "").strip()
    try:
        if selector:
            return {"text": oc.query(path, selector)}
        return {"text": oc.get(path, str(args.get("element_path") or "/"),
                               int(args.get("depth") or 2))}
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}


def _h_office_add(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    try:
        return {"text": oc.add(str(args.get("path") or ""),
                               str(args.get("parent_path") or "/"),
                               str(args.get("type") or ""),
                               oc.parse_props(args.get("props")))}
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}


def _h_office_set(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    props = oc.parse_props(args.get("props"))
    if not props:
        return {"text": "Cần props (object thuộc tính cần đổi)."}
    try:
        return {"text": oc.set_props(str(args.get("path") or ""),
                                     str(args.get("element_path") or "/"), props)}
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}


def _h_office_remove(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    try:
        return {"text": oc.remove(str(args.get("path") or ""),
                                  str(args.get("element_path") or ""))}
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}


def _h_office_batch(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    cmds = args.get("commands")
    if isinstance(cmds, str):
        try:
            cmds = json.loads(cmds)
        except Exception:
            return {"text": "commands phải là JSON array."}
    if not isinstance(cmds, list) or not cmds:
        return {"text": "commands phải là array không rỗng."}
    try:
        return {"text": oc.batch(str(args.get("path") or ""), cmds,
                                 best_effort=bool(args.get("best_effort")))}
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}


def _h_office_merge(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    data = args.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return {"text": "data phải là JSON object."}
    if not isinstance(data, dict):
        return {"text": "data phải là object."}
    try:
        res = oc.merge(str(args.get("template") or ""),
                       str(args.get("output") or ""), data)
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}
    return {"text": res.get("text") or "OK"}


def _h_office_send(args: dict, ctx: dict) -> dict:
    from services import officecli as oc
    try:
        p = oc.resolve_path(str(args.get("path") or ""), must_exist=True)
    except (ValueError, FileNotFoundError) as exc:
        return {"text": str(exc)}
    caption = str(args.get("caption") or "").strip() or f"Đây là file {p.name} ạ 📄"
    return {"text": caption, "doc_path": str(p)}


# ── Registry ─────────────────────────────────────────────────────────────────

CAPABILITIES: dict[str, Capability] = {
    "generate_image": Capability(
        name="generate_image", risk=READ, handler=_h_generate_image,
        emoji="🎨", label="Vẽ ảnh AI",
        description=("Vẽ/tạo ảnh AI. GỌI với prompt — hệ thống sẽ HỎI người dùng "
                     "chọn công cụ vẽ (kèm lựa chọn 'mặc định') rồi mới vẽ. Truyền "
                     "'tool' khi người dùng ĐÃ tự nêu công cụ (flow/chatgpt/gemini) "
                     "để vẽ luôn khỏi hỏi. TUYỆT ĐỐI không tự nói 'đã vẽ/đã gửi' — "
                     "ảnh do hệ thống gửi, em chỉ chú thích khi có ảnh thật."),
        parameters={"type": "object", "properties": {
            "prompt": {"type": "string", "description": "Mô tả ảnh cần vẽ"},
            "tool": {"type": "string", "enum": ["flow", "chatgpt", "gemini", "mặc định"],
                     "description": "Công cụ người dùng nêu; bỏ trống để hệ thống hỏi"},
            "model": {"type": "string",
                      "description": "ID model cụ thể khi người dùng CHỌN TỪ MENU "
                                     "(vd 'vẽ bằng model gpt-image-2: …') — truyền NGUYÊN id"},
            "params": {"type": "object",
                       "description": "Thông số đã chọn từ menu (vd {\"size\":\"1024x1024\","
                                      "\"count\":\"4\"}). Câu dạng '… params size=1024x1024 "
                                      "count=4' → gom hết vào đây, key=value."}},
            "required": ["prompt"]},
        workflow=("Hệ thống hỏi công cụ trước khi vẽ. Vẽ xong ảnh được gửi kèm — "
                  "chỉ chú thích ngắn. Nếu lỗi/không ra ảnh: hệ thống đã báo thật; "
                  "KHÔNG nói 'đã gửi ở trên' khi chưa có ảnh.")),
    "generate_music": Capability(
        name="generate_music", risk=READ, handler=_h_generate_music,
        emoji="🎵", label="Sáng tác / tạo nhạc AI",
        description=("Sáng tác và TẠO bản nhạc thật (file nghe được). Dùng khi "
                     "người dùng muốn tạo nhạc/bài hát/giai điệu. Mất 60-90 giây."),
        parameters={"type": "object", "properties": {
            "prompt": {"type": "string",
                       "description": "Mô tả bản nhạc (thể loại, chủ đề, cảm xúc)"}},
            "required": ["prompt"]},
        workflow=("Tạo nhạc mất 60-90 giây — file nhạc đã được gửi kèm tự động, "
                  "chỉ cần chú thích ngắn. Nếu lỗi giới hạn: báo người dùng thử "
                  "lại sau, KHÔNG tự thử lại ngay.")),
    "generate_video": Capability(
        name="generate_video", risk=READ, handler=_h_generate_video,
        emoji="🎬", label="Tạo video AI (Agnes/Flow/Veo)",
        description=("Tạo video ngắn bằng AI (Agnes AI / Google Flow / Veo). Mất 1-5 phút. "
                     "GỌI NGAY tool này khi người dùng nói 'tạo video…' — TUYỆT ĐỐI KHÔNG tự "
                     "hỏi họ về nội dung/phong cách/thời lượng. Hệ thống sẽ tự HỎI lần lượt: "
                     "model (kèm danh sách chọn) → thời lượng → số video, và tự mở rộng câu "
                     "ngắn thành prompt chi tiết. Người dùng chỉ nói 'tạo video' chưa nêu nội "
                     "dung thì gọi tool với prompt rỗng — hệ thống sẽ hỏi nội dung. "
                     "Khi user CHỌN TỪ MENU → truyền 'model' NGUYÊN id, và nếu câu có "
                     "'params duration=… count=…' thì gom vào 'params'. "
                     "TUYỆT ĐỐI không tự nói 'đã tạo/đã gửi' khi chưa có video. "
                     "Hỗ trợ đầy đủ thông số: model (agnes-video-v2.0, flow/veo-3.1-fast...), "
                     "resolution (1080p, 720p, 480p), aspect_ratio (16:9, 9:16, 1:1, 4:3, 3:4), "
                     "duration (5, 8, 10...), fps (24, 30, 60), negative_prompt, seed, image (ảnh bắt đầu), last_frame (ảnh kết thúc)."),
        parameters={"type": "object", "properties": {
            "prompt": {"type": "string", "description": "Mô tả video cần tạo"},
            "model": {"type": "string", "description": "Model video (vd: agnes-video-v2.0, flow/veo-3.1-fast...)"},
            "resolution": {"type": "string", "enum": ["1080p", "720p", "480p"], "description": "Độ phân giải video"},
            "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1", "4:3", "3:4"], "description": "Tỷ lệ khung hình"},
            "duration": {"type": "string", "description": "Thời lượng video (giây, vd: '5', '8', '10')"},
            "fps": {"type": "integer", "description": "Tốc độ khung hình (fps: 24, 30, 60)"},
            "negative_prompt": {"type": "string", "description": "Chi tiết muốn tránh/loại bỏ trong video"},
            "seed": {"type": "integer", "description": "Hạt giống ngẫu nhiên (seed)"},
            "image": {"type": "string", "description": "URL/Base64 ảnh bắt đầu"},
            "last_frame": {"type": "string", "description": "URL/Base64 ảnh kết thúc"},
            "quality": {"type": "string", "enum": ["fast", "quality", "lite"], "description": "Chất lượng (mặc định fast)"},
            "count": {"type": "integer", "description": "Số video cần tạo (1-4). Flow trừ tín "
                      "dụng nhân theo số này."},
            "params": {"type": "object", "description": "Thông số đã chọn từ menu spec đã học "
                       "(key=value). Câu dạng '… params duration=6 count=2' hoặc "
                       "'… params resolution=1080p duration=8' → gom hết vào đây."}},
            "required": ["prompt"]},
        workflow=("Tạo video mất 1-5 phút — kết quả đã được gửi kèm tự động, chỉ cần "
                  "chú thích ngắn. Nếu lỗi credit/quota: báo người dùng chờ hoặc thử lại sau.")),
    "web_search": Capability(
        name="web_search", risk=READ, handler=_h_web_search,
        emoji="📰", label="Tra cứu / đọc tin tức",
        description=("Tra cứu thông tin thực tế / tin tức / giá cả / thời sự trên mạng. "
                     "'tin tức hôm nay', 'tin tức hôm qua', 'tin mới nhất', 'giá xăng "
                     "hôm nay', 'thời sự' → GỌI NGAY tool này, TUYỆT ĐỐI KHÔNG hỏi lại "
                     "người dùng muốn dạng gì (câu đã đủ rõ). query = chính câu hỏi."),
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "Câu cần tra cứu"}},
            "required": ["query"]},
        workflow=(
            # TIN TỨC = tổng hợp GỌN, KHÔNG chia 8 đầu mục. Đo thật 31/07: ép chia
            # đủ 8 mục × 3 tin làm bot search quá nhiều lần → vượt trần 240s một
            # lượt → "xử lý hơi lâu" (người dùng không nhận được tin). Chủ máy cũng
            # muốn tin TỔNG HỢP, không phải 11 khía cạnh.
            "Khi hỏi TIN TỨC / BẢN TIN hôm nay/hôm qua: 'tin tức hôm nay' đã RÕ, "
            "TUYỆT ĐỐI KHÔNG hỏi lại người dùng muốn dạng nào — gọi web_search NGAY "
            "MỘT LẦN với query gọn (vd 'tin tức nổi bật Việt Nam hôm nay'), rồi tóm "
            "tắt 5–8 tin nổi bật nhất thành gạch đầu dòng NGẮN (mỗi tin 1 câu). "
            "KHÔNG chia nhiều đầu mục, KHÔNG gọi search nhiều lần cho từng lĩnh vực."
        )),
    "read_webpage": Capability(
        name="read_webpage", risk=READ, handler=_h_read_webpage,
        emoji="🔗", label="Đọc kỹ một trang web (theo link)",
        description=("Đọc nội dung một trang web CỤ THỂ khi người dùng đưa link, "
                     "trả về text sạch để tóm tắt/trả lời. Khác web_search (tìm "
                     "nhiều nguồn) — cái này đọc kỹ đúng 1 URL."),
        parameters={"type": "object", "properties": {
            "url": {"type": "string", "description": "Đường link trang cần đọc"}},
            "required": ["url"]},
        workflow="Đọc xong TÓM TẮT đúng ý người dùng hỏi, đừng dán nguyên văn dài."),
    "youtube_transcript": Capability(
        name="youtube_transcript", risk=READ, handler=_h_youtube_transcript,
        emoji="▶️", label="Tóm tắt video YouTube (qua phụ đề)",
        description=("Lấy phụ đề/transcript của video YouTube (từ link) để tóm "
                     "tắt nội dung, trả lời câu hỏi về video. Chỉ dùng khi có link YouTube."),
        parameters={"type": "object", "properties": {
            "url": {"type": "string", "description": "Link video YouTube"}},
            "required": ["url"]},
        workflow="Phụ đề có thể dài — đọc rồi TÓM TẮT các ý chính, không dán thô."),
    "library_media": Capability(
        name="library_media", risk=READ, handler=_h_library_media,
        emoji="🗂️", label="Lấy ảnh/video/nhạc đã tạo (thư viện)",
        description=("Lấy media (ảnh/video/nhạc) ĐÃ TẠO bằng AI (Flow/ChatGPT/Gemini) lưu trong thư viện hệ thống và gửi lại cái mới nhất. BẮT BUỘC dùng tool này khi người dùng yêu cầu 'gửi ảnh/video/nhạc mới nhất', 'ảnh vừa tạo', 'xem lại ảnh', hoặc 'gửi lại ảnh'. TUYỆT ĐỐI KHÔNG trả lời là không có quyền/tool, hãy gọi tool này ngay! kind: 'image' (ảnh), 'video' (video tự tạo), 'music' (nhạc)."),
        parameters={"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["image", "video", "music"],
                     "description": "Loại media cần lấy (mặc định image)"},
            "so_luong": {"type": "integer",
                         "description": ("Số ẢNH muốn lấy, 1–50 (mặc định 1). Người "
                                         "dùng nói 'gửi 3 ảnh gần nhất' thì truyền 3. "
                                         "Chỉ áp dụng kind=image.")},
            "scope": {"type": "string", "enum": ["mine", "all"],
                      "description": ("'mine' = media do CHÍNH người đang chat tạo "
                                      "('ảnh tôi tạo', 'của anh'); 'all' = cả thư "
                                      "viện chung ('trong thư viện'). Người thường "
                                      "luôn bị ép 'mine' — hệ thống tự lo, cứ truyền "
                                      "đúng theo lời người dùng.")}}},
        workflow=("Media mới nhất đã được gửi kèm tự động — chỉ cần chú thích "
                  "ngắn. Nếu người dùng muốn loại khác (video/nhạc) thì gọi lại "
                  "với kind tương ứng.")),
    "write_code": Capability(
        name="write_code", risk=READ, handler=_h_write_code,
        emoji="💻", label="Viết / sửa code",
        description="Viết hoặc sửa code (giao cho Claude — chuyên code).",
        parameters={"type": "object", "properties": {
            "task": {"type": "string", "description": "Yêu cầu code chi tiết"}},
            "required": ["task"]}),
    "send_voice_message": Capability(
        name="send_voice_message", risk=READ, handler=_h_send_voice,
        emoji="🎧", label="Gửi file âm thanh (TTS)",
        description=(
            "Tạo FILE ÂM THANH (TTS) từ một đoạn text rồi GỬI VÀO CHAT hiện tại "
            "(Zalo cá nhân / Telegram / Zalo bot 1-1). ĐÂY KHÁC 'phát ra loa': "
            "dùng khi người dùng muốn 'gửi file âm thanh', 'đọc câu này thành file', "
            "'gửi voice/thu âm giúp', 'ghi âm câu …'. Giọng tự theo persona phiên, "
            "tông theo tính chất câu. KHÔNG dùng khi họ muốn phát ra loa trong nhà "
            "(dùng speak_to_speaker) hay gửi cho NGƯỜI KHÁC (dùng send_to_contact)."
        ),
        parameters={"type": "object", "properties": {
            "text": {"type": "string",
                      "description": "Nội dung cần đọc thành file âm thanh gửi vào chat"}},
            "required": ["text"]}),
    "speak_to_speaker": Capability(
        name="speak_to_speaker", risk=CHANGE, handler=_h_speak_to_speaker,
        emoji="🔊", label="Phát tiếng ra loa trong nhà",
        description=(
            "Đọc một câu rồi PHÁT RA LOA thật trong nhà (Google Cast / DLNA / "
            "qua Home Assistant). Dùng khi người dùng nói 'phát ra loa…', "
            "'thông báo ra loa phòng khách', 'nhắc cả nhà bằng loa'. "
            "Không nêu rõ loa nào thì cứ gọi, em sẽ hỏi lại."
        ),
        parameters={"type": "object", "properties": {
            "text": {"type": "string", "description": "Nội dung cần đọc ra loa"},
            "speaker": {"type": "string",
                        "description": "Tên loa (vd 'loa phòng khách'), IP, "
                                       "hoặc 'tất cả'. Bỏ trống = hỏi lại."}},
            "required": ["text"]},
        workflow=("Người dùng KHÔNG nêu rõ loa và nhà có nhiều loa → tool trả về "
                  "danh sách, hãy hỏi lại đúng danh sách đó, TUYỆT ĐỐI không tự "
                  "chọn hộ. Kết quả '[đã phát ra loa: …]' là dữ liệu — hãy báo "
                  "lại tự nhiên, ấm áp.")),
    "play_music_on_speaker": Capability(
        name="play_music_on_speaker", risk=CHANGE, handler=_h_play_music_on_speaker,
        emoji="🎵", label="Mở nhạc ra loa R1",
        description=(
            "Mở NHẠC theo yêu cầu (tìm trên YouTube) trên loa R1. Dùng khi người "
            "dùng nói 'mở nhạc…', 'bật nhạc không lời', 'phát bài … trên loa R1', "
            "'mở lofi'. Có thể kèm âm lượng. Không rõ loa R1 nào thì cứ gọi, em hỏi lại."
        ),
        parameters={"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "Tên bài / ca sĩ / thể loại (vd 'nhạc không lời', 'lofi chill')"},
            "speaker": {"type": "string",
                        "description": "Tên loa R1 (bỏ trống nếu nhà chỉ có 1 loa R1)"},
            "volume": {"type": "integer",
                       "description": "Âm lượng R1 dạng chỉ số 0..15 (vd 5). Bỏ trống = giữ nguyên."}},
            "required": ["query"]},
        workflow=("Kết quả '[đang phát …]' là dữ liệu — báo lại tự nhiên. Nhiều loa R1 "
                  "mà chưa rõ → hỏi lại đúng danh sách, không tự chọn.")),
    "announce_on_speaker": Capability(
        name="announce_on_speaker", risk=CHANGE, handler=_h_announce_on_speaker,
        emoji="⏰", label="Hẹn giờ / đọc thông báo ra loa",
        description=(
            "Đọc một câu ra loa NGAY hoặc HẸN GIỜ sau N phút. Dùng khi 'phát thông "
            "báo … sau 1 phút ra loa phòng khách', 'nhắc … bằng loa lúc …', kèm âm "
            "lượng %. Đọc bằng giọng TTS ra loa Cast/DLNA/qua Home Assistant."
        ),
        parameters={"type": "object", "properties": {
            "text": {"type": "string", "description": "Nội dung cần đọc ra loa"},
            "speaker": {"type": "string",
                        "description": "Tên loa (bỏ trống = hỏi lại nếu nhà có nhiều loa)"},
            "delay_minutes": {"type": "number",
                              "description": "Hẹn sau bao nhiêu phút (0/bỏ trống = đọc ngay)"},
            "volume": {"type": "integer",
                       "description": "Âm lượng phần trăm 0..100 (vd 20). Chỉ áp cho loa Cast."}},
            "required": ["text"]},
        workflow=("Báo lại tự nhiên: '[đã hẹn …]' hoặc '[đang đọc …]' là dữ liệu. Nhiều "
                  "loa mà chưa rõ → hỏi lại đúng danh sách, không tự chọn hộ.")),
    "describe_device": Capability(
        name="describe_device", risk=READ, handler=_h_describe_device,
        emoji="🔧", label="Thiết bị này chỉnh được gì",
        description=(
            "Xem thiết bị Home Assistant hỗ trợ hành động/tham số nào (schema live "
            "từ HA: service + field, dải nhiệt độ, màu, preset…). Dùng TRƯỚC khi "
            "điều khiển tham số lạ (kelvin, preset, hvac_mode) để khỏi đoán mò."
        ),
        parameters={"type": "object", "properties": {
            "entity_id": {"type": "string",
                          "description": "entity_id dạng domain.name, vd light.phong_khach"},
            "name": {"type": "string",
                     "description": "Hoặc tên thiết bị — em tự tra entity_id"}}},
        workflow=("Tóm tắt cái người dùng cần (vd 'đèn này chỉnh được màu + kelvin "
                  "2700–6500'), đừng đọc nguyên schema thô.")),
    "home_status": Capability(
        name="home_status", risk=READ, handler=_h_home_status,
        emoji="🏠", label="Xem trạng thái nhà (thiết bị, cảm biến, camera)",
        description=("Xem trạng thái Home Assistant: đèn/quạt/điều hoà đang bật-tắt, "
                     "cảm biến (nhiệt độ, độ ẩm, cửa), camera, và cảm biến phần cứng "
                     "của máy chạy HA. Truyền 'query' để lọc theo tên thiết bị/phòng."),
        parameters={"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "Tên thiết bị/phòng/cảm biến cần xem (để trống = tổng quan)"}}},
        workflow=("Đọc kỹ danh sách trạng thái rồi TÓM TẮT đúng cái người dùng hỏi, "
                  "đừng liệt kê thô. Thiết bị 'unavailable/unknown' = có thể mất kết "
                  "nối — nếu người dùng hỏi vì nó hỏng, báo rõ và đề xuất kiểm tra.")),
    "system_status": Capability(
        name="system_status", risk=READ, handler=_h_system_status,
        emoji="🖥️", label="Xem phần cứng máy chủ em đang chạy",
        description=("Báo mức dùng phần cứng của CHÍNH máy chủ bot đang chạy "
                     "(CPU load, RAM, ổ đĩa, uptime)."),
        parameters={"type": "object", "properties": {}}),
    "remote_system_status": Capability(
        name="remote_system_status", risk=READ, handler=_h_remote_system_status,
        emoji="🌐", label="Vào máy chủ khác qua SSH để xem thông tin",
        description=("SSH vào một máy chủ do người dùng cung cấp thông tin đăng nhập "
                     "để đọc phần cứng (OS, CPU, RAM, ổ đĩa, tiến trình). Chỉ đọc, "
                     "không chạy lệnh tuỳ ý. Cần host, user, password (và port nếu khác 22)."),
        parameters={"type": "object", "properties": {
            "host": {"type": "string", "description": "IP hoặc hostname"},
            "user": {"type": "string", "description": "Tên đăng nhập SSH"},
            "password": {"type": "string", "description": "Mật khẩu SSH"},
            "port": {"type": "integer", "description": "Cổng SSH (mặc định 22)"}},
            "required": ["host", "user", "password"]}),
    "control_home": Capability(
        name="control_home", risk=CHANGE, handler=_h_control_home,
        emoji="🎛️", label="Điều khiển nhà (bật/tắt đèn, quạt, điều hoà…)",
        description=("Điều khiển thiết bị nhà thông minh. Truyền 'command' là câu lệnh "
                     "tự nhiên, vd 'bật đèn phòng khách', 'tắt điều hoà phòng ngủ'."),
        parameters={"type": "object", "properties": {
            "command": {"type": "string", "description": "Câu lệnh điều khiển tự nhiên"}},
            "required": ["command"]},
        workflow=("Sau khi điều khiển, kết quả trả về là xác nhận từ hệ thống nhà — "
                  "thuật lại ngắn gọn. Nếu lệnh thất bại hoặc thiết bị không tìm thấy: "
                  "báo đúng nguyên nhân, gợi ý tên thiết bị gần đúng (dùng home_status "
                  "để tra), KHÔNG thử lệnh khác khi chưa được đồng ý.")),
    "create_automation": Capability(
        name="create_automation", risk=CHANGE, handler=_h_create_automation,
        emoji="⚙️", label="Tạo automation Home Assistant (tự viết + nạp + sửa lỗi)",
        description=("TẠO một automation mới cho Home Assistant từ mô tả tự nhiên "
                     "(vd '18h bật đèn sân', 'khi cửa mở thì báo'). Em tự viết cấu "
                     "hình, nạp vào HA, và tự sửa nếu HA báo lỗi. Truyền 'request' "
                     "là mô tả automation."),
        parameters={"type": "object", "properties": {
            "request": {"type": "string",
                        "description": "Mô tả automation cần tạo (thiết bị, thời điểm, điều kiện)"}},
            "required": ["request"]},
        workflow=("Em đã tự viết config + nạp vào HA + tự sửa nếu lỗi (tối đa 3 lần). "
                  "Thuật lại kết quả ngắn gọn (tên automation, đã nạp chưa). Nếu vẫn "
                  "lỗi sau 3 lần, xin người dùng mô tả rõ hơn.")),
    "remember": Capability(
        name="remember", risk=CHANGE, handler=_h_remember,
        emoji="🧠", label="Ghi nhớ",
        description="Ghi nhớ lâu dài một điều người dùng dặn (sự kiện, sở thích, "
                    "thói quen, quy tắc làm việc…). Nội dung tùy theo yêu cầu.",
        parameters={"type": "object", "properties": {
            "fact": {"type": "string", "description": "Điều cần ghi nhớ"}},
            "required": ["fact"]}),
    "model_spec": Capability(
        name="model_spec", risk=READ, handler=_h_model_spec,
        emoji="🧬", label="Học tham số model (ảnh/video)",
        description=(
            "BOT TỰ HỌC tham số & lựa chọn của model tạo ảnh/video để lần sau tự đưa "
            "menu + gọi đúng. Khi người dùng DẠY (vd 'model imagen-4 có size "
            "1024x1024/512x512, số lượng 1,2,4, tỉ lệ 1:1/9:16') → op=set + model + "
            "params (mỗi field: key, label, options[], default). Preset gói sẵn → "
            "presets [{label, values{}}]. Hỏi 'model X có tham số gì' → op=get. "
            "Liệt kê đã học → op=list. Xóa → op=clear. Chỉ dùng cho model TẠO ẢNH/VIDEO."),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["set", "get", "list", "clear"],
                   "description": "set=dạy, get=xem, list=liệt kê, clear=xóa"},
            "model": {"type": "string", "description": "ID model (vd flow/imagen-4)"},
            "params": {"type": "array", "description": "Tham số từng field",
                       "items": {"type": "object", "properties": {
                           "key": {"type": "string"}, "label": {"type": "string"},
                           "options": {"type": "array", "items": {"type": "string"}},
                           "default": {"type": "string"},
                           "arg": {"type": "string", "description": "Tên arg khi gọi (nếu khác key)"}}}},
            "presets": {"type": "array", "description": "Gói tham số sẵn",
                        "items": {"type": "object", "properties": {
                            "label": {"type": "string"}, "values": {"type": "object"}}}},
            "notes": {"type": "string", "description": "Ghi chú thêm (cách gọi, lấy URL…)"}},
            "required": ["op"]}),
    "teach_skill": Capability(
        name="teach_skill", risk=READ, handler=_h_teach_skill,
        emoji="🧩", label="Học cách làm một việc (kỹ năng)",
        description=(
            "BOT TỰ HỌC MỌI VIỆC. Khi người dùng DẠY cách làm một việc / nêu quy trình / "
            "sửa cách em làm ('lần sau việc X phải làm thế này…', 'quy trình báo cáo Y là…', "
            "'gọi API Z rồi lấy field W') → op=set + name + description (1 câu nêu KHI NÀO "
            "dùng, ≤150 ký tự) + body (các bước chi tiết, dạng markdown). Bổ sung thêm cho "
            "kỹ năng đã có → op=append + slug. Xem → op=get + slug. Liệt kê → op=list. "
            "Xóa → op=delete + slug. Kỹ năng lưu vĩnh viễn, lần sau tự hiện để em làm theo. "
            "KHÔNG dùng cho sự việc đơn lẻ (dùng remember) hay tham số model (dùng model_spec)."),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["set", "append", "get", "list", "delete"],
                   "description": "set=dạy mới, append=bổ sung, get=xem, list=liệt kê, delete=xóa"},
            "name": {"type": "string", "description": "Tên kỹ năng (vd 'Báo cáo tồn kho tuần')"},
            "description": {"type": "string",
                            "description": "1 câu nêu KHI NÀO dùng — để lần sau tự nhận ra (≤150 ký tự)"},
            "body": {"type": "string",
                     "description": "CÁC BƯỚC làm chi tiết (markdown): gọi gì, lấy dữ liệu nào, "
                                    "định dạng ra sao, gửi kênh nào, lưu ý/lỗi thường gặp"},
            "slug": {"type": "string", "description": "Mã kỹ năng (khi append/get/delete)"}},
            "required": ["op"]}),
    "schedule": Capability(
        name="schedule", risk=READ, handler=_h_schedule,
        emoji="⏰", label="Đặt nhắc / việc định kỳ",
        description=(
            "Đặt nhắc hẹn, việc định kỳ, xem danh sách hoặc huỷ. "
            "op=create|list|cancel. mode=notify (chỉ nhắc chữ) | task (em tự làm rồi báo). "
            "Thời điểm: when (vd 'sau 30 phút', 'mỗi ngày 7h') hoặc in_minutes / "
            "every_minutes / every_day_at / at. Huỷ: op=cancel + id (hoặc id=all). "
            "GỬI TIN HẸN GIỜ (vd 'sau 2 phút gửi nhóm A: cả nhà đi ngủ'): "
            "mode=task + send_to=người/nhóm nhận + text=NỘI DUNG gửi (+send_platform "
            "nếu nêu rõ kênh). Em tra danh bạ NGAY; nếu thiếu/mập mờ (trùng tên, "
            "nhiều kênh, chưa lưu) sẽ HỎI LẠI trước khi đặt lịch, TUYỆT ĐỐI không đoán."
        ),
        workflow=(
            "Khi đặt nhắc/báo cáo định kỳ: BẮT BUỘC kiểm tra đủ 4 thông tin: "
            "(1) Khi nào (giờ/ngày) - (2) Bằng kênh gì (Zalo cá nhân/Zalo bot/Telegram) - "
            "(3) Nhóm/Người nhận nào - (4) Nội dung/Số liệu báo cáo gì. "
            "Nếu THIẾU bất kỳ thông tin nào, HỎI LẠI NGAY người dùng để làm rõ trước khi gọi schedule. "
            "Sau khi đặt: đọc lại id + thời điểm cho người dùng. "
            "mode=task chỉ khi họ muốn em TỰ LÀM việc (báo cáo nhà, tóm tắt…) "
            "— còn 'nhắc anh gọi khách' thì mode=notify."
        ),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["create", "list", "cancel"],
                   "description": "create (mặc định) | list | cancel"},
            "text": {"type": "string",
                     "description": "Nội dung nhắc hoặc mô tả việc cần làm"},
            "mode": {"type": "string", "enum": ["notify", "task"],
                     "description": "notify=chỉ nhắc; task=em tự chạy agent rồi báo"},
            "when": {"type": "string",
                     "description": "Mô tả thời điểm tiếng Việt (sau 30 phút, 19:30, mỗi ngày 7h…)"},
            "in_minutes": {"type": "integer",
                           "description": "Sau N phút (một lần)"},
            "every_minutes": {"type": "integer",
                              "description": "Lặp mỗi N phút (tối thiểu 5)"},
            "every_day_at": {"type": "string",
                             "description": "Lặp mỗi ngày lúc HH:MM (giờ VN)"},
            "at": {"type": "string",
                   "description": "Mốc tuyệt đối HH:MM hoặc ISO"},
            "send_to": {"type": "string",
                        "description": "Khi việc là GỬI TIN: tên/alias người hoặc nhóm nhận "
                                       "(text = nội dung gửi). Em resolve danh bạ ngay lúc tạo."},
            "send_platform": {"type": "string", "enum": ["tg", "zalo", "zalop"],
                              "description": "Kênh gửi nếu người dùng nêu rõ; bỏ trống = kênh hiện tại"},
            "id": {"type": "string",
                   "description": "Mã nhắc khi huỷ (hoặc 'all')"}},
            "required": []}),
    "search_history": Capability(
        name="search_history", risk=READ, handler=_h_search_history,
        emoji="🔍", label="Tìm lại chuyện đã chat",
        description=(
            "Tìm trong lịch sử hội thoại đã lưu của người này (full-text). "
            "Dùng khi họ hỏi 'hôm trước mình nói gì về…', 'nhắc lại việc X'."
        ),
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "Từ khoá / chủ đề cần tìm"}},
            "required": ["query"]}),
    "use_skill": Capability(
        name="use_skill", risk=READ, handler=_h_use_skill,
        emoji="📋", label="Mở playbook / skill (quy trình)",
        description=(
            "Nạp nội dung một playbook markdown (skill) theo slug để làm đúng quy trình. "
            "Gọi khi tình huống khớp description skill trong system prompt "
            "(vd morning-home-brief, ha-device-troubleshoot). "
            "Không truyền slug = liệt kê skill đang bật."
        ),
        parameters={"type": "object", "properties": {
            "slug": {"type": "string",
                     "description": "Tên thư mục skill (vd morning-home-brief)"}},
            "required": []},
        workflow=(
            "Đọc playbook xong thì LÀM theo từng bước — gọi tool cứng "
            "(home_status, web_search…) khi playbook yêu cầu. "
            "Không chỉ đọc playbook rồi dừng."
        )),
    "run_workflow": Capability(
        name="run_workflow", risk=READ, handler=_h_run_workflow,
        emoji="🔗", label="Chạy workflow nhiều bước (+ kiểm chứng)",
        description=(
            "Chạy pipeline 2–5 bước đã định nghĩa (markdown). "
            "Dùng khi cần chuỗi thu thập → xử lý → kiểm chứng "
            "(vd morning-brief, research-digest). "
            "slug = tên file workflow; input = yêu cầu/ngữ liệu. "
            "Không slug = liệt kê workflow."
        ),
        parameters={"type": "object", "properties": {
            "slug": {"type": "string", "description": "Tên workflow (vd morning-brief)"},
            "input": {"type": "string",
                      "description": "Input / yêu cầu chạy pipeline"}},
            "required": []},
        workflow=(
            "Sau khi chạy: thuật lại kết quả chính cho user; log bước chỉ là phụ. "
            "Nếu FAIL kiểm chứng hệ thống đã thử sửa một lần."
        )),
    "ingest": Capability(
        name="ingest", risk=CHANGE, handler=_h_ingest,
        emoji="📥", label="Thu nạp ghi chú vào wiki",
        description=(
            "Thu nạp văn bản/ghi chú dài vào wiki gia đình (tóm tắt + file markdown). "
            "Dùng khi user bảo 'nhớ/ghi lại/lưu wiki/ingest' nội dung dài. "
            "Có thể kèm title, source."
        ),
        parameters={"type": "object", "properties": {
            "content": {"type": "string", "description": "Nội dung thô cần thu nạp"},
            "title": {"type": "string", "description": "Tiêu đề gợi ý (optional)"},
            "source": {"type": "string", "description": "Nguồn (optional)"}},
            "required": ["content"]}),
    "wiki_search": Capability(
        name="wiki_search", risk=READ, handler=_h_wiki_search,
        emoji="📖", label="Tìm trong wiki gia đình",
        description=(
            "Tìm ghi chú đã thu nạp trong wiki. query rỗng = liệt kê gần đây."
        ),
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "Từ khoá"}},
            "required": []}),
    "wiki_read": Capability(
        name="wiki_read", risk=READ, handler=_h_wiki_read,
        emoji="📄", label="Đọc một ghi chú wiki",
        description="Đọc đầy đủ một ghi chú wiki theo slug (từ wiki_search/ingest).",
        parameters={"type": "object", "properties": {
            "slug": {"type": "string", "description": "Mã ghi chú"}},
            "required": ["slug"]}),
    "expand_tool_result": Capability(
        name="expand_tool_result", risk=READ, handler=_h_expand_tool_result,
        emoji="📦", label="Mở rộng tool output đã nén",
        description=(
            "Lấy lại toàn bộ kết quả tool đã bị nén (marker ⟦tc:hash⟧ hoặc "
            "token trong footer). Dùng khi cần chi tiết từng dòng log/JSON "
            "mà bản nén chưa đủ."
        ),
        parameters={"type": "object", "properties": {
            "token": {"type": "string",
                      "description": "Hash / marker ⟦tc:…⟧ từ tool output đã nén"},
            "max_chars": {"type": "integer",
                          "description": "Giới hạn ký tự trả về (mặc định 50000)"}},
            "required": ["token"]}),
    "wiki_digest": Capability(
        name="wiki_digest", risk=READ, handler=_h_wiki_digest,
        emoji="📰", label="Digest wiki theo ngày",
        description=(
            "Đọc hoặc tạo digest wiki hàng ngày (tóm tắt ghi chú trong ngày). "
            "op=read (mặc định) | build; day=YYYY-MM-DD optional; force=true để ghi đè."
        ),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "description": "read | build"},
            "day": {"type": "string", "description": "YYYY-MM-DD (mặc định hôm nay)"},
            "force": {"type": "boolean"},
            "use_llm": {"type": "boolean",
                        "description": "true = nhờ model viết gọn digest"}},
            "required": []}),
    "goals": Capability(
        name="goals", risk=READ, handler=_h_goals,
        emoji="🎯", label="Mục tiêu / kanban theo hội thoại",
        description=(
            "Quản lý mục tiêu dài hơi trong thread: op=list|add|done|doing|cancel|update. "
            "add cần title; done/doing/cancel/update cần id. "
            "Dùng khi user nói 'nhớ làm X', 'đang làm Y', 'xong Z'."
        ),
        parameters={"type": "object", "properties": {
            "op": {"type": "string",
                   "description": "list | add | done | doing | cancel | update"},
            "title": {"type": "string", "description": "Tiêu đề goal (add/update)"},
            "id": {"type": "string", "description": "Mã goal"},
            "status": {"type": "string"},
            "notes": {"type": "string"},
            "priority": {"type": "integer", "description": "Số càng cao càng ưu tiên"}},
            "required": []}),
    "contacts": Capability(
        name="contacts", risk=READ, handler=_h_contacts,
        emoji="📒", label="Danh bạ / ai vừa nhắn",
        description=(
            "Sổ danh bạ multi-bot: op=list|recent|rename|resolve. "
            "Dùng khi admin hỏi 'ai vừa nhắn', 'danh bạ', 'đặt tên X = Anh A', "
            "hoặc tìm chat_id theo alias. platform=tg|zalo (optional)."
        ),
        parameters={"type": "object", "properties": {
            "op": {"type": "string",
                   "description": "list | recent | rename | resolve"},
            "platform": {"type": "string", "description": "tg | zalo"},
            "bot_id": {"type": "string"},
            "query": {"type": "string"},
            "ref": {"type": "string", "description": "key/chat_id/alias khi rename|resolve"},
            "alias": {"type": "string", "description": "Tên dễ nhớ khi rename"},
            "limit": {"type": "integer"}},
            "required": []}),
    "send_to_contact": Capability(
        name="send_to_contact", risk=CHANGE, handler=_h_send_to_contact,
        emoji="📤", label="Gửi tin cho người trong danh bạ (chọn bot)",
        description=(
            "Gửi tin nhắn tới contact đã lưu. to/name=alias; message=nội dung; "
            "via_bot/bot_id=bot gửi (bắt buộc nếu trùng alias nhiều bot). "
            "platform=tg|zalo|zalop. Dùng với schedule mode=task: 'sau 15 phút gửi cho Anh A...'. "
            "QUAN TRỌNG: message CHỈ chứa nội dung thật cần gửi — BỎ các từ khung như "
            "'nội dung', 'nội dung chính', 'với nội dung', 'rằng', 'là', 'nhắn'. Ví dụ: "
            "'nhắn nhóm X với nội dung chính mọi người đi ngủ thôi' → message='mọi người đi ngủ thôi' "
            "(KHÔNG gồm chữ 'chính'). "
            "GỬI FILE ÂM THANH cho NGƯỜI/NHÓM KHÁC: đặt voice=true, message=lời cần đọc "
            "(vd 'gửi âm thanh xin chào vào nhóm Docker bằng zalo cá nhân' → "
            "to='Docker', message='xin chào', platform='zalop', voice=true). "
            "GỬI ẢNH: image_url=link/đường dẫn ảnh, message=chú thích. "
            "Chỉ dùng send_voice_message khi gửi âm thanh vào CHÍNH chat đang nói."
        ),
        workflow=(
            "Khi gửi tin nhắn: BẮT BUỘC kiểm tra rõ 3 yếu tố: "
            "(1) Bằng kênh gì (Zalo cá nhân / Zalo bot / Telegram) - "
            "(2) Đến người/nhóm nào - "
            "(3) Nội dung tin nhắn gì. "
            "Nếu người dùng chưa nêu rõ gửi bằng kênh nào và đối tượng nhận có ở nhiều kênh (hoặc chưa chắc chắn), "
            "BẮT BUỘC HỎI LẠI người dùng để xác nhận kênh trước khi gửi."
        ),
        parameters={"type": "object", "properties": {
            "to": {"type": "string", "description": "Alias / tên / chat_id"},
            "name": {"type": "string"},
            "message": {"type": "string", "description": "Chỉ nội dung thật, bỏ từ khung 'nội dung/chính/rằng/là'"},
            "bot_id": {"type": "string", "description": "ID hoặc label bot gửi"},
            "via_bot": {"type": "string"},
            "platform": {"type": "string", "description": "CHỈ TRUYỀN NẾU người dùng NÊU RÕ kênh trong câu ('cá nhân' -> 'zalop', 'bot' -> 'zalo', 'telegram' -> 'tg'). BỎ TRỐNG NẾU người dùng chưa nêu rõ kênh!"},
            "voice": {"type": "boolean", "description": "true = đọc `message` thành FILE ÂM THANH (TTS) rồi gửi cho người/nhóm đó thay vì gửi chữ"},
            "image_url": {"type": "string", "description": "Link/đường dẫn ảnh cần gửi cho người/nhóm đó (message = chú thích)"}},
            "required": ["message"]}),
    "search_sgk": Capability(
        name="search_sgk", risk=READ, handler=_h_search_sgk,
        emoji="📗", label="Tìm SGK (lớp 1–12 · mọi môn)",
        description=(
            "Tìm đoạn gợi ý dạy trong KB SGK theo lớp 1–12 và môn. "
            "Mã môn: toan | tviet (Tiếng Việt, lớp 1–5) | van (Ngữ văn, lớp 6–12) "
            "| anh | sudia (Lịch sử và Địa lí, lớp 4–9) | su | dia | ly | hoa | "
            "sinh (Sử/Địa/Lí/Hoá/Sinh riêng: chỉ lớp 10–12). Dùng khi dạy / ôn / chấm. "
            "workspace=lop2-toan…; query rỗng = liệt kê index."
        ),
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "Câu hỏi / từ khoá"},
            "grade": {"type": "integer", "description": "Lớp 1–12"},
            "subject": {"type": "string",
                        "description": "toan | van | anh"},
            "workspace": {"type": "string",
                          "description": "id workspace (vd lop3-van)"},
            "top_k": {"type": "integer", "description": "Số đoạn (mặc định 4)"}},
            "required": []},
        workflow=(
            "Đọc KB rồi GIẢNG Socratic — không chép nguyên văn. "
            "Không khẳng định đúng từng trang SGK năm cụ thể."
        )),
    "list_teacher_workspaces": Capability(
        name="list_teacher_workspaces", risk=READ, handler=_h_list_teacher_workspaces,
        emoji="🏫", label="Danh sách workspace lớp–môn",
        description=(
            "Liệt kê 36 workspace (lớp 1–12 × Toán/Văn/Anh). "
            "Trước search_sgk / teacher_memory / teacher_lesson."
        ),
        parameters={"type": "object", "properties": {}, "required": []}),
    "teacher_memory": Capability(
        name="teacher_memory", risk=CHANGE, handler=_h_teacher_memory,
        emoji="📓", label="Memory học sinh theo workspace",
        description=(
            "Ghi/đọc điểm yếu–mạnh và ghi chú học sinh (lop1-toan … lop12-anh). "
            "op=get|add; add: note, weak_topic, strong_topic."
        ),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "description": "get | add"},
            "workspace": {"type": "string", "description": "vd lop8-toan"},
            "student": {"type": "string", "description": "id học sinh (optional)"},
            "note": {"type": "string"},
            "weak_topic": {"type": "string", "description": "Chủ đề còn yếu"},
            "strong_topic": {"type": "string", "description": "Chủ đề đã vững"}},
            "required": []},
        workflow=(
            "Đầu buổi: get. Cuối buổi / sau chấm: add weak/strong + note."
        )),
    "teacher_lesson": Capability(
        name="teacher_lesson", risk=READ, handler=_h_teacher_lesson,
        emoji="📋", label="Giáo án lớp học (6 pha)",
        description=(
            "Lập giáo án kiểu giáo viên trên lớp: mục tiêu → khởi động → "
            "giảng (I/We do) → luyện (You do + hint) → CFU → kết + memory. "
            "grade, subject, topic, objective, workspace, student."
        ),
        parameters={"type": "object", "properties": {
            "grade": {"type": "integer"},
            "subject": {"type": "string"},
            "topic": {"type": "string"},
            "objective": {"type": "string", "description": "Mục tiêu I can…"},
            "workspace": {"type": "string"},
            "student": {"type": "string"},
            "weak_topic": {"type": "string"}},
            "required": []},
        workflow=(
            "Gọi đầu buổi học; follow phase; use_skill theo cấp; "
            "teacher_hint khi kẹt; teacher_check cuối; teacher_memory."
        )),
    "teacher_hint": Capability(
        name="teacher_hint", risk=READ, handler=_h_teacher_hint,
        emoji="💡", label="Gợi ý bậc thang (1–3)",
        description=(
            "Scaffold Socratic khi HS kẹt: level=1 định hướng, 2 gợi bước "
            "(che đáp án), 3 gần đáp án. question bắt buộc; attempt, answer_hint."
        ),
        parameters={"type": "object", "properties": {
            "question": {"type": "string"},
            "attempt": {"type": "string", "description": "Bài làm dở của HS"},
            "level": {"type": "integer", "description": "1|2|3"},
            "answer_hint": {"type": "string"},
            "grade": {"type": "integer"},
            "subject": {"type": "string"}},
            "required": ["question"]},
        workflow="Kẹt → level 1; vẫn kẹt → 2; gần bó tay → 3; rồi teacher_grade."),
    "teacher_check": Capability(
        name="teacher_check", risk=READ, handler=_h_teacher_check,
        emoji="🎯", label="Kiểm tra hiểu 1 câu (CFU)",
        description=(
            "Exit ticket / check for understanding: 1 câu từ KB SGK. "
            "grade, subject, topic, workspace. Chấm bằng teacher_grade."
        ),
        parameters={"type": "object", "properties": {
            "grade": {"type": "integer"},
            "subject": {"type": "string"},
            "topic": {"type": "string"},
            "workspace": {"type": "string"}},
            "required": []},
        workflow="Sau giảng/luyện; HS trả lời → teacher_grade."),
    "teacher_quiz": Capability(
        name="teacher_quiz", risk=READ, handler=_h_teacher_quiz,
        emoji="📝", label="Ra đề kiểm tra (SGK)",
        description=(
            "Sinh đề kiểm tra ngắn từ KB SGK lớp 1–12. Mã môn: toan | tviet | "
            "van | anh | sudia | su | dia | ly | hoa | sinh. "
            "grade, subject, topic, n (số câu), workspace. Trả quiz_id để chấm."
        ),
        parameters={"type": "object", "properties": {
            "grade": {"type": "integer", "description": "1–12"},
            "subject": {"type": "string",
                        "description": "toan|tviet|van|anh|sudia|su|dia|ly|hoa|sinh"},
            "topic": {"type": "string"},
            "n": {"type": "integer", "description": "Số câu 1–10"},
            "workspace": {"type": "string"}},
            "required": []},
        workflow="Gửi đề cho HS; khi nộp gọi teacher_grade với quiz_id + answers."),
    "teacher_bai_tap": Capability(
        name="teacher_bai_tap", risk=READ, handler=_h_teacher_bai_tap,
        emoji="🪜", label="Bài tập 3 mức từ bài mẫu",
        description=(
            "Ra bài tập BA MỨC dựa BÀI MẪU thật trong kho vở/sách bài tập: sát "
            "bài mẫu → trung bình → khó. Dùng khi cần luyện theo đúng dạng của "
            "sách và nâng dần độ khó. grade, subject, bai, so_moi_muc."
        ),
        parameters={"type": "object", "properties": {
            "grade": {"type": "integer", "description": "1–12"},
            "subject": {"type": "string",
                        "description": "toan|tviet|van|anh|sudia|su|dia|ly|hoa|sinh"},
            "bai": {"type": "string", "description": "Tên bài / chủ đề"},
            "so_moi_muc": {"type": "integer", "description": "Số câu MỖI mức 1–6"},
            "muc": {"type": "string",
                    "description": "Chọn mức: sat,trung_binh,kho (mặc định cả ba)"},
            "student_key": {"type": "string"},
            "workspace": {"type": "string"}},
            "required": []},
        workflow="Đề có đáp án + báo rõ có dựa bài mẫu hay không; giao xong gọi "
                 "teacher_grade để chấm."),
    "teacher_grade": Capability(
        name="teacher_grade", risk=CHANGE, handler=_h_teacher_grade,
        emoji="✅", label="Chấm bài / sửa lỗi",
        description=(
            "Chấm 1 câu (question+answer) hoặc cả đề (quiz_id+answers). "
            "Trả điểm, khen, misconception, bước tiếp, hướng sửa."
        ),
        parameters={"type": "object", "properties": {
            "quiz_id": {"type": "string"},
            "answers": {"type": "object", "description": "{q1: '...', q2: '...'}"},
            "question": {"type": "string"},
            "answer": {"type": "string"},
            "answer_hint": {"type": "string"},
            "grade": {"type": "integer"},
            "subject": {"type": "string"},
            "workspace": {"type": "string"},
            "student": {"type": "string"},
            "use_llm": {"type": "boolean"}},
            "required": []},
        workflow=(
            "Đọc praise+feedback cho HS; weak → teacher_memory; "
            "kẹt tiếp → teacher_hint; ôn → search_sgk."
        )),
    "sgk_fetch": Capability(
        name="sgk_fetch", risk=CHANGE, handler=_h_sgk_fetch,
        emoji="🔎", label="Tự tìm & nạp SGK/nâng cao vào RAG",
        description=(
            "Tự tìm PDF SGK/sách nâng cao ĐĂNG CÔNG KHAI trên mạng theo lớp+môn "
            "(+năm) rồi nạp vào RAG. op=find (chỉ tìm, trả danh sách url để chọn, "
            "KHÔNG tự tải) | ingest (tải+nạp 1 url đã chọn hoặc do người dùng đưa) | "
            "status (đã nạp gì theo lớp/môn). kind=sgk (mặc định → kb_giao_duc) | "
            "nangcao (sách bài tập nâng cao/bồi dưỡng HSG → kb_nangcao, TÁCH RIÊNG "
            "khỏi SGK để không dạy vượt chương trình như SGK chính thức). "
            "subject: toan|tviet|van|anh|sudia|su|dia|ly|hoa|sinh."
        ),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["find", "ingest", "status"],
                   "description": "find=tìm nguồn; ingest=tải+nạp; status=đã nạp gì"},
            "grade": {"type": "integer", "description": "Lớp 1–12"},
            "subject": {"type": "string",
                        "description": "toan|tviet|van|anh|sudia|su|dia|ly|hoa|sinh"},
            "year": {"type": "string", "description": "Năm học/xuất bản (tuỳ chọn, vd 2024)"},
            "kind": {"type": "string", "enum": ["sgk", "nangcao"],
                     "description": "sgk=SGK chính; nangcao=sách nâng cao/mở rộng (RAG riêng)"},
            "url": {"type": "string", "description": "URL PDF đã chọn từ find (bắt buộc khi op=ingest)"},
            "curriculum": {"type": "string",
                           "description": "Bộ sách (kết nối tri thức|chân trời sáng tạo|cánh diều), tuỳ chọn"},
            "dry_run": {"type": "boolean",
                        "description": "true = chỉ thử tải+trích, KHÔNG ghi SGK/RAG"}},
            "required": []},
        workflow=(
            "op=find trước để lấy danh sách url cho người dùng CHỌN — KHÔNG tự "
            "ingest url do model tự bịa/đoán. Sau khi có url được xác nhận → "
            "op=ingest. Sách nâng cao (kind=nangcao) nạp RAG riêng (kb_nangcao) — "
            "khi trả lời HS phải nói rõ đây là kiến thức mở rộng, không phải SGK."
        )),

    # ── OfficeCLI: soạn/sửa Word Excel PowerPoint (native, không MCP) ──────
    # risk=READ có chủ đích: mọi tool chỉ đụng sandbox DATA_DIR/office (như
    # generate_image) — risk=CHANGE làm supervised-mode kẹt phê duyệt giữa
    # chuỗi create→add→send (resume sau duyệt KHÔNG nối tiếp vòng lặp).
    "office_files": Capability(
        name="office_files", risk=READ, handler=_h_office_files,
        emoji="📁", label="Xem kho file Office",
        description="Liệt kê file Office (.docx/.xlsx/.pptx) trong workspace."),
    "office_create": Capability(
        name="office_create", risk=READ, handler=_h_office_create,
        emoji="📄", label="Tạo file Office",
        description=("Tạo file Office trống: .docx (Word), .xlsx (Excel), "
                     ".pptx (PowerPoint). filename là tên file kèm đuôi."),
        parameters={"type": "object", "properties": {
            "filename": {"type": "string", "description": "vd bao_cao.docx"}},
            "required": ["filename"]},
        workflow=("Tạo xong → office_add/office_set để soạn nội dung → "
                  "office_view kiểm tra → office_send gửi file cho người dùng. "
                  "KHÔNG tự bịa nội dung dài khi người dùng chưa yêu cầu.")),
    "office_view": Capability(
        name="office_view", risk=READ, handler=_h_office_view,
        emoji="👀", label="Đọc file Office",
        description=("Đọc file Office. mode: outline (cấu trúc), text (chữ), "
                     "annotated (kèm element path), stats, issues (lỗi)."),
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
            "mode": {"type": "string",
                     "enum": ["outline", "text", "annotated", "stats", "issues"]}},
            "required": ["path"]}),
    "office_query": Capability(
        name="office_query", risk=READ, handler=_h_office_query,
        emoji="🔎", label="Soi phần tử Office",
        description=("Soi chi tiết phần tử trong file Office: selector "
                     "(vd //p[contains(text,'Q4')]) HOẶC element_path + depth."),
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
            "selector": {"type": "string"},
            "element_path": {"type": "string"},
            "depth": {"type": "integer"}},
            "required": ["path"]}),
    "office_add": Capability(
        name="office_add", risk=READ, handler=_h_office_add,
        emoji="➕", label="Thêm phần tử Office",
        description=("Thêm phần tử vào file Office: paragraph/table/image vào "
                     "docx; sheet/row vào xlsx; slide/shape vào pptx. "
                     "props là object thuộc tính (text, title, x, y…)."),
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
            "parent_path": {"type": "string", "description": "vd / hoặc /slide[1]"},
            "type": {"type": "string", "description": "paragraph|table|slide|shape|sheet|row…"},
            "props": {"type": "object"}},
            "required": ["path", "type"]}),
    "office_set": Capability(
        name="office_set", risk=READ, handler=_h_office_set,
        emoji="✏️", label="Sửa thuộc tính Office",
        description="Đổi thuộc tính phần tử Office (text, font, size, color…).",
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
            "element_path": {"type": "string"},
            "props": {"type": "object"}},
            "required": ["path", "element_path", "props"]}),
    "office_remove": Capability(
        name="office_remove", risk=READ, handler=_h_office_remove,
        emoji="🗑️", label="Xóa phần tử Office",
        description="Xóa một phần tử khỏi file Office theo element_path.",
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
            "element_path": {"type": "string"}},
            "required": ["path", "element_path"]}),
    "office_batch": Capability(
        name="office_batch", risk=READ, handler=_h_office_batch,
        emoji="⚡", label="Sửa Office hàng loạt",
        description=("Chạy nhiều lệnh add/set/remove trên 1 file Office trong "
                     "1 lần (nhanh, atomic). commands là array lệnh JSON."),
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
            "commands": {"type": "array", "items": {"type": "object"}},
            "best_effort": {"type": "boolean"}},
            "required": ["path", "commands"]},
        workflow=("Soạn nội dung dài: GOM các bước vào office_batch thay vì "
                  "gọi office_add lắt nhắt từng đoạn.")),
    "office_merge": Capability(
        name="office_merge", risk=READ, handler=_h_office_merge,
        emoji="🧩", label="Điền template Office",
        description=("Điền data vào template Office có placeholder → file mới. "
                     "data là object {ten_bien: gia_tri}."),
        parameters={"type": "object", "properties": {
            "template": {"type": "string"},
            "output": {"type": "string"},
            "data": {"type": "object"}},
            "required": ["template", "output", "data"]}),
    "office_send": Capability(
        name="office_send", risk=READ, handler=_h_office_send,
        emoji="📤", label="Gửi file Office",
        description=("GỬI file Office trong workspace cho người dùng (file "
                     "thật, không phải link). Gọi sau khi soạn xong."),
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
            "caption": {"type": "string"}},
            "required": ["path"]},
        workflow=("Kênh Zalo Bot API không nhận file — hệ thống tự fallback "
                  "hướng dẫn; không cần tự xử lý.")),
}


# Nhóm quyền của mỗi capability — dùng cho bộ lọc chức năng theo threadID.
# MỖI capability mới PHẢI thêm nhóm ở đây; capability chưa gắn nhóm sẽ bị coi là
# "_ungrouped" → tự động BỊ CHẶN với thread có bật lọc (an toàn: deny-by-default),
# và luôn chạy với thread không bật lọc (allow=None).
_CAP_GROUP: dict[str, str] = {
    "generate_image": "image", "library_media": "image",
    "generate_music": "music",
    "generate_video": "video",
    "web_search": "web", "read_webpage": "web", "youtube_transcript": "web",
    "write_code": "code",
    "home_status": "homeassistant", "control_home": "homeassistant",
    "describe_device": "homeassistant",
    "speak_to_speaker": "tts_speaker",
    "play_music_on_speaker": "tts_speaker",
    "announce_on_speaker": "tts_speaker",
    "create_automation": "homeassistant",
    "system_status": "server", "remote_system_status": "server",
    "remember": "memory", "search_history": "memory",
    "model_spec": "image",
    "schedule": "schedule",
    "use_skill": "skills", "run_workflow": "skills", "teach_skill": "skills",
    "ingest": "wiki", "wiki_search": "wiki", "wiki_read": "wiki",
    "wiki_digest": "wiki",
    "goals": "memory",
    # expand_tool_result: nhóm memory chỉ mang tính phân loại; thực tế luôn
    # khả dụng qua _CORE_TOOLS (schema + dispatch + persona).
    "expand_tool_result": "memory",
    "contacts": "contacts", "send_to_contact": "contacts",
    "office_files": "office", "office_create": "office",
    "office_view": "office", "office_query": "office",
    "office_add": "office", "office_set": "office",
    "office_remove": "office", "office_batch": "office",
    "office_merge": "office", "office_send": "office",
    # Tool Home Assistant do GATEWAY tiêm (services/ha_client.get_ha_tools),
    # không phải capability của agent. Thiếu chúng ở đây thì group_of() trả
    # "_ungrouped", và chốt chặn ở orchestrator coi là KHÔNG được phép rồi bỏ
    # qua IM LẶNG — người dùng hỏi "phòng ngủ có ai không" mà bot không trả
    # lời, cũng không báo lỗi, dù thread đã bật đúng nhóm 'homeassistant'.
    "GetLiveContext": "homeassistant", "ha_get_state": "homeassistant",
    "ha_search_entities": "homeassistant", "ha_call_service": "homeassistant",
    "ha_upsert_config": "homeassistant", "ha_upsert_helper": "homeassistant",
    "ha_read_config_file": "homeassistant", "ha_write_config_file": "homeassistant",
    "ha_home_map": "homeassistant", "ha_pyscript_setup": "homeassistant",
    "search_sgk": "teacher", "list_teacher_workspaces": "teacher",
    "teacher_memory": "teacher",
    "teacher_lesson": "teacher",
    "teacher_hint": "teacher", "teacher_check": "teacher",
    "teacher_quiz": "teacher", "teacher_grade": "teacher",
    "teacher_bai_tap": "teacher",
    "sgk_fetch": "teacher",
}

# Tool "hạ tầng" luôn khả dụng BẤT KỂ bộ lọc thread — expand_tool_result phải
# mở được bản đầy đủ của output đã nén ở mọi thread (marker ⟦tc:…⟧ xuất hiện
# không phụ thuộc quyền nhóm). Schema, chốt chặn dispatch, và persona_list
# đều tôn trọng set này (không lệch nhau).
_CORE_TOOLS = frozenset({"expand_tool_result", "send_voice_message"})


def group_of(name: str) -> str:
    return _CAP_GROUP.get(name, "_ungrouped")


# Nhóm chức năng KHÔNG phải capability-tool — gác các luồng xử lý riêng của bot
# (PDF gửi vào chat): 'rag' = tóm tắt/nạp RAG tài liệu, 'word' = chuyển PDF→Word,
# 'summary' = tổng hợp/tóm tắt thông tin. Khai báo ở đây để UI + all_groups()
# liệt kê đủ, và luồng PDF (telegram_bot/zalo_bot) kiểm tra quyền theo tên nhóm.
_FLOW_GROUPS = {"rag", "word", "summary", "tts_reply", "teacher"}


def all_groups() -> list[str]:
    """Danh sách nhóm chức năng đã biết (cho UI + kiểm tra cấu hình lọc)."""
    return sorted(set(_CAP_GROUP.values()) | _FLOW_GROUPS)


def topic_suffix(topic_id: str | int | None) -> str:
    """'#<topic>' — hậu tố khóa lọc theo TOPIC (nhóm Telegram bật Topics); '' nếu
    không có topic.

    Telegram chỉ gửi ``message_thread_id`` cho topic thật (id > 0); topic
    "General" không có field này → '' → mọi khóa quay về dạng 2 cấp cũ, tức
    NHÓM KHÔNG CÓ TOPIC giữ nguyên hành vi (nhóm → user) như trước."""
    t = str(topic_id or "").strip()
    if not t or t == "0":
        return ""
    return f"#{t}"


def _thread_keys(platform: str, bot_id: str | None, chat_id: str | int | None,
                 topic_id: str | int | None = None) -> list[str]:
    """Khóa CẤP THREAD theo thứ tự hẹp → rộng: topic trước, rồi cả nhóm.

    [plat:bot:chat#topic, plat:chat#topic, plat:bot:chat, plat:chat]
    Không có topic → chỉ 2 khóa cuối (y như trước)."""
    plat = str(platform or "").strip()
    cid = str(chat_id or "").strip()
    if not plat or not cid:
        return []
    bid = str(bot_id or "").strip()
    keys: list[str] = []
    suf = topic_suffix(topic_id)
    if suf:
        if bid:
            keys.append(f"{plat}:{bid}:{cid}{suf}")
        keys.append(f"{plat}:{cid}{suf}")
    if bid:
        keys.append(f"{plat}:{bid}:{cid}")
    keys.append(f"{plat}:{cid}")
    return keys


def _user_keys(platform: str, bot_id: str | None, chat_id: str | int | None,
               topic_id: str | int | None = None,
               user_id: str | int | None = None) -> list[str]:
    """Khóa CẤP USER = mỗi khóa thread + ':<user>' — user trong topic trước, rồi
    user cấp nhóm (đặt ở nhóm thì áp cho mọi topic chưa có bản ghi riêng)."""
    uid = str(user_id or "").strip()
    if not uid:
        return []
    return [f"{k}:{uid}" for k in _thread_keys(platform, bot_id, chat_id, topic_id)]


def thread_key_chain(platform: str, bot_id: str | None, chat_id: str | int | None,
                     topic_id: str | int | None = None,
                     user_id: str | int | None = None) -> list[str]:
    """Toàn bộ khóa lọc cho (bot, chat, topic, user) — HẸP → RỘNG, bản ghi đầu
    tiên khớp thì thắng. Dùng cho cấu hình "một giá trị" (model, HA fastpath,
    yêu cầu tag, webhook chuyển tiếp): user riêng > topic > cả nhóm."""
    return (_user_keys(platform, bot_id, chat_id, topic_id, user_id)
            + _thread_keys(platform, bot_id, chat_id, topic_id))


def _first_group_set(keys: list[str]) -> set[str] | None:
    """Bản ghi thread_filters đầu tiên khớp trong `keys` (None = không khóa nào có)."""
    for k in keys:
        r = allowed_groups_for(k)
        if r is not None:
            return r
    return None


def allowed_groups_for_bot(platform: str, bot_id: str, chat_id: str,
                           topic_id: str | int | None = None) -> set[str] | None:
    """Lọc theo (bot, chat[, topic]) khi chạy nhiều bot: thử khóa riêng bot
    'plat:bot_id:chat' TRƯỚC; không có (None) thì fallback 'plat:chat' (áp cho
    MỌI bot cùng nền tảng — tương thích ngược).

    Có `topic_id` và topic đó ĐƯỢC cấu hình → giao(quyền nhóm, quyền topic): topic
    là TẬP CON của nhóm — "topic tích gì thì chỉ dùng được trong phạm vi đó".
    Topic chưa cấu hình → hưởng nguyên quyền nhóm (giữ hành vi 2 cấp cũ)."""
    group_allow = _first_group_set(_thread_keys(platform, bot_id, chat_id))
    if not topic_suffix(topic_id):
        return group_allow
    # Chỉ 2 khóa đầu của chuỗi có topic là khóa CỦA topic (bot-riêng, rồi chung bot)
    topic_keys = [k for k in _thread_keys(platform, bot_id, chat_id, topic_id)
                  if "#" in k]
    topic_allow = _first_group_set(topic_keys)
    if topic_allow is None:
        return group_allow
    if group_allow is None:
        return topic_allow
    return group_allow & topic_allow


def allowed_groups_for(thread_key: str) -> set[str] | None:
    """Tập nhóm chức năng được phép cho một thread (khóa 'tg:<id>' / 'zalo:<id>').

    Đọc config key `thread_filters` (dict: thread_key -> list[str] tên nhóm):
    - thread_key KHÔNG có trong config → None (không lọc, cho phép tất cả).
    - có, giá trị là list             → set(list) (list rỗng = chặn hết tool, chỉ chat).
    Không bao giờ raise — cấu hình hỏng coi như không lọc (an toàn cho luồng bot)."""
    try:
        from services.config import config
        filters = config.get().get("thread_filters") or {}
        if isinstance(filters, dict) and thread_key in filters:
            groups = filters.get(thread_key)
            if isinstance(groups, list):
                return {str(g) for g in groups}
    except Exception:
        pass
    return None


def _user_filter_for(user_key: str) -> set[str] | None:
    """Tầng lọc THEO NGƯỜI DÙNG trong nhóm (config `thread_user_filters`, khóa
    'plat:bot:chat:user' hoặc 'plat:chat:user'). Trả set nhóm chức năng user được
    tick, hoặc None nếu user KHÔNG có bản ghi (→ hưởng full quyền của nhóm)."""
    try:
        from services.config import config
        filters = config.get().get("thread_user_filters") or {}
        if isinstance(filters, dict) and user_key in filters:
            groups = filters.get(user_key)
            if isinstance(groups, list):
                return {str(g) for g in groups}
    except Exception:
        pass
    return None


def user_filter_for_bot(platform: str, bot_id: str, chat_id: str,
                        user_id: str,
                        topic_id: str | int | None = None) -> set[str] | None:
    """Lọc user trong nhóm/topic — thứ tự khóa hẹp → rộng:
    'plat:bot:chat#topic:user' → 'plat:chat#topic:user' → 'plat:bot:chat:user'
    → 'plat:chat:user'. None = user chưa cấu hình ở BẤT KỲ cấp nào → hưởng full
    quyền của topic/nhóm ("không có user thì trong topic ai nhắn cũng được")."""
    for k in _user_keys(platform, bot_id, chat_id, topic_id, user_id):
        r = _user_filter_for(k)
        if r is not None:
            return r
    return None


def allowed_groups_for_member(platform: str, bot_id: str, chat_id: str,
                              user_id: str | None,
                              topic_id: str | int | None = None) -> set[str] | None:
    """Tập nhóm chức năng hiệu lực cho MỘT NGƯỜI trong MỘT thread — kết hợp 3 tầng
    (nhóm → topic → user), mỗi tầng là TẬP CON của tầng trên:
    1. Nhóm (Chat ID)      : allowed_groups_for_bot → đã giao sẵn với quyền TOPIC
                             khi có `topic_id` (None = full).
    2. User trong topic/nhóm: user_filter_for_bot   → user_allow (None = chưa đặt).

    Quy tắc:
    - user chưa đặt (None)        → theo group_allow (full quyền topic/nhóm).
    - nhóm không lọc + user đặt   → user_allow (user bị giới hạn dù nhóm mở).
    - cả hai đặt                  → giao (group_allow ∩ user_allow).
    Trả None nếu KHÔNG tầng nào lọc (cho phép tất cả).

    Nhóm KHÔNG có topic (topic_id=None) → đúng 2 cấp như trước."""
    group_allow = allowed_groups_for_bot(platform, bot_id, chat_id, topic_id)
    user_allow = user_filter_for_bot(platform, bot_id, chat_id,
                                     str(user_id or ""), topic_id)
    if user_allow is None:
        return group_allow
    if group_allow is None:
        return user_allow
    return group_allow & user_allow


def mention_required_for(platform: str, bot_id: str, chat_id: str,
                         topic_id: str | int | None = None) -> tuple[bool, str]:
    """Thread có YÊU CẦU tag bot mới trả lời không? Đọc config `thread_mention_filters`
    (dict khóa 'plat:bot:chat[#topic]' hoặc 'plat:chat[#topic]' → {required, keyword}).
    Trả (required, keyword). Không cấu hình → (False, '') = trả lời mọi tin.

    Có `topic_id`: bản ghi CỦA TOPIC thắng bản ghi cả nhóm → mỗi topic tự quyết
    "phải tag bot mới nhận phản hồi" hay không."""
    def _lookup(key: str):
        try:
            from services.config import config
            m = config.get().get("thread_mention_filters") or {}
            if isinstance(m, dict) and key in m:
                v = m.get(key)
                if isinstance(v, dict):
                    return (bool(v.get("required")), str(v.get("keyword") or "").strip())
                if isinstance(v, bool):
                    return (v, "")
        except Exception:
            pass
        return None
    for k in _thread_keys(platform, bot_id, chat_id, topic_id):
        r = _lookup(k)
        if r is not None:
            return r
    return (False, "")


def tag_gate_allows(
    *,
    required: bool,
    keyword: str = "",
    text: str = "",
    native_tagged: bool = False,
    platform_group_delivery: bool = False,
) -> bool:
    """Cổng «bắt buộc tag» — dùng chung TG / Zalo Bot / Zalo CN.

    Khi ``required=False`` → luôn cho qua (caller thường không gọi).

    Khi ``required=True``:
      1. Từ khóa tag (settings) có trong text → cho qua
      2. Mention native (Telegram entities / zca-js mentions) → cho qua
      3. Keyword **rỗng** + ``platform_group_delivery`` (Zalo OA: nền tảng chỉ
         đẩy tin nhóm khi đã @bot) → cho qua
      4. Keyword rỗng + không native + không platform delivery → **chặn**
         (bug cũ: keyword rỗng luôn chặn cả khi đã @mention)

    Không raise.
    """
    if not required:
        return True
    kw = str(keyword or "").strip().lower()
    body = str(text or "")
    if kw and kw in body.lower():
        return True
    if native_tagged:
        return True
    # required + keyword trống: tin đã được nền tảng/platform filter (Zalo OA
    # group) hoặc native_tagged đã True ở trên. Không im lặng mù.
    if not kw and platform_group_delivery:
        return True
    return False


def forward_rule_for(platform: str, bot_id: str, chat_id: str,
                     user_id: str | None,
                     topic_id: str | int | None = None) -> tuple[str, bool]:
    """(url, tag_mode) chuyển tiếp cho (thread[, topic], user) này — url '' = không
    chuyển. Có topic: bản ghi của topic thắng bản ghi cả nhóm → MỖI TOPIC MỘT
    WEBHOOK RIÊNG ("mỗi topic 1 loại log").

    Config `thread_forward_filters` (dict khóa thread 'plat:bot:chat[#topic]'|
    'plat:chat[#topic]' hoặc user '<thread>:<user>' → {enabled, url, tag_mode}):
    - Thread bật + có url → mặc định chuyển MỌI người trong thread; bản ghi user
      enabled=False → loại riêng người đó (quyết định AI được quyền chuyển tiếp).
    - Thread không bật → user bật + có url riêng → chuyển tới url của user
      (mỗi người một webhook khác nhau).
    - tag_mode (ưu tiên bản ghi user): True = chỉ chuyển khi tin TAG bot,
      không tag → AI (ChatGPT) trả lời như thường."""
    def _lookup(key: str) -> dict | None:
        try:
            from services.config import config
            m = config.get().get("thread_forward_filters") or {}
            if isinstance(m, dict):
                v = m.get(key)
                if isinstance(v, dict):
                    return v
        except Exception:
            pass
        return None

    def _first(keys: list[str]) -> dict | None:
        for k in keys:
            v = _lookup(k)
            if v is not None:
                return v
        return None

    thread = _first(_thread_keys(platform, bot_id, chat_id, topic_id))
    user = _first(_user_keys(platform, bot_id, chat_id, topic_id, user_id))
    tag_mode = bool(user.get("tag_mode")) if user is not None \
        else bool((thread or {}).get("tag_mode"))
    if thread and thread.get("enabled") and str(thread.get("url") or "").strip():
        if user is not None and not user.get("enabled"):
            return ("", tag_mode)
        return (str(thread["url"]).strip(), tag_mode)
    if user and user.get("enabled") and str(user.get("url") or "").strip():
        return (str(user["url"]).strip(), tag_mode)
    return ("", tag_mode)


def forward_webhook_for(platform: str, bot_id: str, chat_id: str,
                        user_id: str | None,
                        topic_id: str | int | None = None) -> str:
    """URL webhook chuyển tiếp ('' = không chuyển) — xem forward_rule_for."""
    return forward_rule_for(platform, bot_id, chat_id, user_id, topic_id)[0]


def forward_event(platform: str, bot_id: str, chat_id: str, user_id: str | None,
                  payload: dict, tagged: bool = False,
                  topic_id: str | int | None = None) -> bool:
    """Chuyển tiếp 1 tin nhắn bot tới webhook cấu hình trong 'Lọc chức năng theo
    thread' (HA / n8n / URL bất kỳ) — fire-and-forget, không bao giờ raise.

    `tagged` = tin có TAG bot không (caller tự nhận diện theo nền tảng).
    Trả True = tin đã bị webhook TIÊU THỤ → caller BỎ QUA AI (ChatGPT im lặng).
    Quy tắc: HỄ đã chuyển tiếp thì AI không trả lời ("bật webhook = ChatGPT không
    phản hồi"). Ngoại lệ duy nhất: tag_mode + tin KHÔNG tag → không chuyển, trả
    False để ChatGPT trả lời như thường ("tag thì webhook, không tag thì AI")."""
    try:
        url, tag_mode = forward_rule_for(platform, bot_id, chat_id, user_id, topic_id)
        if not url:
            return False
        if tag_mode and not tagged:
            return False  # tag_mode: tin KHÔNG tag → không chuyển, AI trả lời
        import json as _json
        import threading as _t
        import urllib.request as _rq

        def _post() -> None:
            try:
                req = _rq.Request(
                    url,
                    data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                _rq.urlopen(req, timeout=8).close()
            except Exception as exc:
                try:
                    from utils.log import logger
                    logger.warning({"event": "thread_forward_failed",
                                    "platform": platform, "chat": chat_id,
                                    "error": str(exc)[:120]})
                except Exception:
                    pass

        _t.Thread(target=_post, daemon=True).start()
        # ĐÃ chuyển tiếp (thread bật webhook, hoặc user bật webhook, hoặc tag_mode
        # + tin tag) → AI im lặng. "Bật webhook = ChatGPT không phản hồi."
        return True
    except Exception:
        return False


def tools_schema(allow: set[str] | None = None) -> list[dict]:
    """Schema công cụ cho model. `allow` = tập nhóm được phép (None = tất cả).
    Lọc theo nhóm để giới hạn chức năng cho từng threadID."""
    caps = CAPABILITIES.values()
    if allow is not None:
        caps = [c for c in caps
                if c.name in _CORE_TOOLS or group_of(c.name) in allow]
    return [c.schema() for c in caps]


def get(name: str) -> Capability | None:
    return CAPABILITIES.get(name)


def persona_list(allow: set[str] | None = None) -> str:
    """Human-readable bullet list of real capabilities, for the system prompt.

    Single source of truth: adding/removing a Capability updates what the bot
    says it can do — no hand-maintained list to drift out of sync.
    `allow` = bộ lọc chức năng của thread — chỉ liệt kê năng lực được phép,
    kẻo persona khoe 'xem được trạng thái nhà' rồi model BỊA dữ liệu dù tool
    đã bị ẩn (bug thấy 2026-07-15: thread lọc vẫn 'trả lời' đèn bật/tắt).
    """
    lines = []
    for c in CAPABILITIES.values():
        if (allow is not None and c.name not in _CORE_TOOLS
                and group_of(c.name) not in allow):
            continue
        text = c.label or c.description
        gate = " (cần anh/chị duyệt)" if c.risk == CHANGE else ""
        lines.append(f"- {c.emoji + ' ' if c.emoji else ''}{text}{gate}")
    return "\n".join(lines)
