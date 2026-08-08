"""
Gemini AI Studio Provider — Google Gemini API with native function calling.

Free tier: 15 RPM, 1M tokens/day on gemini-2.5-flash via AI Studio.
Paid: unlimited via Google Cloud billing.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterator

from curl_cffi import requests

from services.config import config
from utils.log import logger

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MODEL = "gemini-3-flash-preview"


def _gemini_base_url() -> str:
    """Return per-provider override or the default Google endpoint.

    Set providers.gemini_free.base_url in config.json to your Cloudflare
    Worker proxy (deploy/cloudflare-gemini-proxy.js) to bypass VN
    geo-block on generativelanguage.googleapis.com."""
    cfg = (config.data.get("providers") or {}).get("gemini_free") or {}
    base = str(cfg.get("base_url") or "").rstrip("/")
    if base:
        # Worker proxies the whole upstream — append /v1beta to match
        if not base.endswith("/v1beta"):
            base = base + "/v1beta"
        return base
    return GEMINI_BASE_URL


class GeminiProvider:
    """Google Gemini API provider — free & paid tiers, native tool calling."""

    @property
    def api_key(self) -> str:
        """Get next available API key (round-robin)."""
        keys = self._get_keys()
        if not keys:
            return ""
        key = keys[self._key_index % len(keys)]
        self._key_index += 1
        return key

    def _get_keys(self) -> list[str]:
        cfg = config.data.get("providers") or {}
        gemini_cfg = cfg.get("gemini_free") or {}
        single = str(gemini_cfg.get("api_key") or "").strip()
        multi = gemini_cfg.get("api_keys") or []
        if not isinstance(multi, list):
            multi = []
        keys = [k.strip() for k in multi if k.strip()]
        if single and single not in keys:
            keys.insert(0, single)
        return keys

    def __init__(self):
        self._key_index = 0
        self._rate_limited: dict[str, float] = {}

    @property
    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            resp = requests.get(f"{_gemini_base_url()}/models?key={self.api_key}", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def chat_completions(
        self, messages, model=GEMINI_DEFAULT_MODEL, stream=False,
        temperature=None, max_tokens=None, tools=None, tool_choice=None, **kwargs,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Send chat request to Gemini API with native tool calling support."""
        keys = self._get_keys()
        if not keys:
            raise RuntimeError("Gemini API key not configured")

        tim_web = _muon_tim_web(model, kwargs)
        contents, system_instruction, gemini_tools = _convert_request(
            messages, tools, google_search=tim_web)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {},
        }
        if system_instruction:
            body["systemInstruction"] = system_instruction
        if gemini_tools:
            body["tools"] = gemini_tools
            if any("functionDeclarations" in t for t in gemini_tools):
                body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        if temperature is not None:
            body["generationConfig"]["temperature"] = temperature
        if max_tokens:
            body["generationConfig"]["maxOutputTokens"] = max_tokens

        url = f"{_gemini_base_url()}/models/{model}:streamGenerateContent?alt=sse"

        logger.info({"event": "gemini_request", "model": model,
                     "has_tools": bool(gemini_tools), "google_search": tim_web})

        # ── Xoay key bằng VÒNG LẶP, mỗi key thử đúng MỘT lần ─────────────────
        # Bản cũ retry 429 bằng cách gọi ĐỆ QUY chính chat_completions(), mà
        # đầu hàm lại xoá _attempted_keys → bộ đếm reset về 0 sau mỗi vòng,
        # điều kiện dừng không bao giờ đạt. Tệ hơn, self.api_key là property
        # TỰ XOAY mỗi lần đọc, bị đọc 4 lần trong một nhánh retry: key bị đánh
        # dấu limited không phải key vừa lỗi, key ghi sổ không phải key vừa
        # kiểm tra. Hậu quả đo được: một request nã Google 981 lượt trong ~150s
        # (caller timeout dài dằng dặc) rồi chết bằng "maximum recursion depth
        # exceeded". Ở đây chốt key vào biến cục bộ cho từng lượt — request,
        # đánh dấu limited, ghi sổ đều trên đúng MỘT key.
        now = time.time()
        start = self._key_index
        self._key_index = (self._key_index + 1) % len(keys)
        candidates = [keys[(start + i) % len(keys)] for i in range(len(keys))]
        usable = [k for k in candidates if self._rate_limited.get(k, 0.0) <= now]
        if not usable:
            raise RuntimeError("All Gemini API keys rate limited. Try again later.")

        # Lỗi thuộc về KEY (không phải request) → bỏ qua key đó, thử key kế
        # tiếp; chỉ raise khi hết sạch key. Trước đây bất kỳ mã ≠200/≠429 là
        # raise NGAY, nên MỘT key hỏng lẫn trong pool giết cả lượt vision/chat
        # dù các key khác còn tốt (đo thật 07/08: 2/6 key hỏng — một key sai
        # "API key not valid" 400, một project bị Google cấm 403 — làm ~1/3
        # request rơi xuống chatgpt_free với "Gemini error 400/403").
        #   400 INVALID_ARGUMENT / 401 / 403 PERMISSION_DENIED: key sai hoặc
        #     project bị cấm → không tự hồi, treo key lâu (1 giờ).
        #   429: rate limit tạm thời → treo ngắn (60s).
        # Body phải đọc bằng resp.content: stream=True làm resp.text rỗng nên
        # log cũ ghi "Gemini error 400: " trống, không ai biết key nào hỏng.
        _KEY_ERR = {400, 401, 403, 429}
        last_error = ""
        for key in usable:
            resp = None
            try:
                resp = requests.post(
                    url, headers={"Content-Type": "application/json", "x-goog-api-key": key},
                    json=body, timeout=300, stream=True,
                )
                if resp.status_code != 200:
                    status = resp.status_code
                    # stream=True: resp.content/.text RỖNG — body chỉ đọc được
                    # qua iter_content() (đo thật trong curl_cffi). Đây là lý do
                    # log cũ ghi "Gemini error 400: " trống suốt.
                    try:
                        body_preview = b"".join(resp.iter_content()).decode("utf-8", "replace")[:200]
                    except Exception:
                        try:
                            body_preview = (resp.content or b"").decode("utf-8", "replace")[:200]
                        except Exception:
                            body_preview = ""
                    try:
                        resp.close()
                    except Exception:
                        pass
                    resp = None
                    last_error = f"Gemini error {status}: {body_preview}"
                    if status in _KEY_ERR:
                        # 429 hồi nhanh; 400/401/403 là key/project chết → treo lâu.
                        self._rate_limited[key] = time.time() + (60 if status == 429 else 3600)
                        logger.info({
                            "event": "gemini_key_skip", "status": status,
                            "key_suffix": key[-6:], "detail": body_preview[:120],
                            "remaining": len(usable) - usable.index(key) - 1,
                        })
                        continue
                    # Mã khác (5xx…) có thể do request hoặc Google-side: vẫn thử
                    # key còn lại, giữ last_error để raise nếu hết key.
                    continue
                # Ownership chuyển sang parser (đóng trong finally của _parse_gemini_stream).
                stream = _parse_gemini_stream(resp, model)
                resp = None
                return stream
            except requests.RequestsError as exc:
                if resp is not None:
                    try:
                        resp.close()
                    except Exception:
                        pass
                last_error = f"Gemini connection failed: {exc}"
                continue
            except Exception:
                if resp is not None:
                    try:
                        resp.close()
                    except Exception:
                        pass
                raise
        raise RuntimeError(last_error or "All Gemini API keys rate limited. Try again later.")


def _muon_tim_web(model: str, kwargs: dict) -> bool:
    """Người gọi có THẬT SỰ muốn tìm web không.

    Theo đúng quy ước đã có trong repo (`api/claude.py`): hậu tố `-search` /
    `-websearch` trong tên model. Thêm kwarg tường minh cho nơi gọi trong mã.
    """
    if "google_search" in kwargs:
        return bool(kwargs.get("google_search"))
    m = str(model or "").lower()
    return "-search" in m or "-websearch" in m


def _convert_request(messages, tools, *, google_search: bool = False):
    """Convert OpenAI format → Gemini format with vision + video support."""
    import base64 as b64

    VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".wmv", ".mpeg", ".mpg", ".3gpp", ".flv", ".mkv"}

    def _is_video_url(url: str) -> bool:
        """Check if URL points to a video file."""
        import os
        # Check extension
        for ext in VIDEO_EXTENSIONS:
            if ext in url.lower().split("?")[0]:
                return True
        return False

    def _data_url_part(data_url: str, ptype: str = "image") -> dict | None:
        """Parse data: URL → Gemini inlineData part."""
        if not data_url.startswith("data:"):
            return None
        header, data = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "")
        return {"inlineData": {"mimeType": mime, "data": data}}

    def _fetch_url_part(url: str) -> dict | None:
        """Fetch URL and return Gemini inlineData part."""
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(url, timeout=60, impersonate="chrome110")
            if resp.status_code == 200:
                img_data = b64.b64encode(resp.content).decode()
                ctype = resp.headers.get("content-type", "image/jpeg")
                return {"inlineData": {"mimeType": ctype, "data": img_data}}
        except Exception:
            pass
        return None

    contents = []
    system_parts = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts = []

        if isinstance(content, list):
            text_content = ""
            for p in content:
                if not isinstance(p, dict):
                    continue
                ptype = p.get("type", "")
                if ptype == "text":
                    text_content += p.get("text", "") + " "
                elif ptype in ("image_url", "video_url"):
                    media_url = (p.get("image_url") or p.get("video_url") or {}).get("url", "")
                    if not media_url:
                        continue
                    part = _data_url_part(media_url)
                    if not part:
                        part = _fetch_url_part(media_url)
                    if part:
                        parts.append(part)
                elif ptype == "file_data":
                    fd = p.get("file_data", {})
                    file_uri = fd.get("file_uri", "")
                    if file_uri.startswith("data:"):
                        part = _data_url_part(file_uri)
                    elif file_uri.startswith("http"):
                        part = _fetch_url_part(file_uri)
                    if part:
                        parts.append(part)
            if text_content.strip():
                parts.insert(0, {"text": text_content.strip()})
            content = text_content.strip()
        else:
            content = str(content or "")
            parts = [{"text": content}]

        if role == "system":
            system_parts.append(content)
            continue

        if not parts:
            parts = [{"text": content}]
        contents.append({"role": "user" if role == "user" else "model", "parts": parts})

    si = {"parts": [{"text": "\n".join(system_parts)}]} if system_parts else None

    gtools = []
    if tools:
        decls = [{"name": t.get("function", {}).get("name", ""),
                  "description": t.get("function", {}).get("description", ""),
                  "parameters": t.get("function", {}).get("parameters", {})} for t in tools]
        if decls:
            gtools.append({"functionDeclarations": decls})
            
    # CHỈ thêm khi người gọi thật sự muốn tìm web.
    #
    # Bản cũ chèn `googleSearch` vào MỌI request "để giống hành vi duyệt web
    # sẵn có của ChatGPT". Cái giá không nhìn thấy được: grounding bằng Google
    # Search tính vào một hạn mức RIÊNG, chặt hơn nhiều so với hạn mức sinh
    # nội dung. Cùng một khoá, cùng một model, gọi thẳng thì 200 mà qua đây
    # thì 429 — nên triệu chứng hiện ra là "khoá hết quota", và người ta đi
    # thay khoá thay vì tìm nguyên nhân.
    #
    # Với đường Vision của Home Assistant thì nó vô nghĩa hoàn toàn: phân tích
    # một khung hình camera không cần tra web, mà lại hỏng vì nó.
    if google_search:
        gtools.append({"googleSearch": {}})


    return contents, si, gtools

def _parse_gemini_stream(response, model: str) -> Iterator[dict[str, Any]]:
    """Parse Gemini SSE stream → OpenAI chunks with native tool_calls support."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    sent_role = False
    accumulated_text = ""
    pending_tool_calls: list[dict] = []

    try:
        try:
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="ignore") if isinstance(raw_line, bytes) else str(raw_line)
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                candidates = event.get("candidates") or []
                for c in candidates:
                    content = c.get("content") or {}
                    parts = content.get("parts") or []
                    for part in parts:
                        # Text response
                        text = part.get("text", "")
                        if text:
                            accumulated_text += text
                            if not sent_role:
                                sent_role = True
                                yield {"id": completion_id, "object": "chat.completion.chunk",
                                       "created": created, "model": model,
                                       "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
                            yield {"id": completion_id, "object": "chat.completion.chunk",
                                   "created": created, "model": model,
                                   "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}

                        # Function call response (native!)
                        func_call = part.get("functionCall")
                        if func_call:
                            pending_tool_calls.append({
                                "id": f"call_{uuid.uuid4().hex[:12]}",
                                "type": "function",
                                "function": {
                                    "name": func_call.get("name", ""),
                                    "arguments": json.dumps(func_call.get("args", {}), ensure_ascii=False),
                                },
                            })

            # Yield tool calls if any
            if pending_tool_calls:
                yield {"id": completion_id, "object": "chat.completion.chunk",
                       "created": created, "model": model,
                       "choices": [{"index": 0, "delta": {"tool_calls": pending_tool_calls}, "finish_reason": None}]}

        except Exception as exc:
            logger.error({"event": "gemini_stream_error", "error": str(exc)})
            yield {"id": completion_id, "object": "chat.completion.chunk",
                   "created": created, "model": model,
                   "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                   "error": {"message": "Gemini stream error: %s" % exc, "type": "stream_error"}}
            return

        if not sent_role and not pending_tool_calls:
            yield {"id": completion_id, "object": "chat.completion.chunk",
                   "created": created, "model": model,
                   "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}
        yield {"id": completion_id, "object": "chat.completion.chunk",
               "created": created, "model": model,
               "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    finally:
        response.close()


gemini_provider = GeminiProvider()
