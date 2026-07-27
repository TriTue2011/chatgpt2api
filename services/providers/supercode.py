"""SuperCode Provider — model miễn phí qua backend của supercode-cli.

Cổng vào: ``POST {base}/api/ai/chat`` với ``Authorization: Bearer <token>``.
Đây KHÔNG phải API tương thích OpenAI nên không dùng được custom_openai:

  Thân request : {"messages": [...], "provider": "...", "model": "...", "tools": {...}}
  Thân trả về  : NDJSON — mỗi dòng một JSON, ``type`` là một trong
                 text | reasoning | tool-call | finish
  Hết hạn mức  : HTTP lỗi, thân chứa "Insufficient Funds" hoặc
                 "Credit usage at configured limit" (reset sau 24h)

Lấy token KHÔNG CẦN cài CLI — dùng OAuth 2.0 Device Flow bằng curl (đã chạy
thật 2026-07-28), hợp cả với máy chủ không màn hình:

  1) POST {base}/api/auth/device/code
     {"client_id": "", "scope": "openid profile email"}
     → device_code, user_code, verification_uri_complete, interval, expires_in
     (client_id ĐỂ RỖNG vẫn được — chỉ ai tự dựng server mới cần OAuth App)
  2) Người dùng mở verification_uri_complete, đăng nhập GitHub, bấm duyệt
  3) POST {base}/api/auth/device/token
     {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
      "device_code": "...", "client_id": ""}
     → access_token (32 ký tự), expires_in ≈ 604800 (7 NGÀY)

KHÔNG có refresh_token — mã CLI có chỗ lưu nó nhưng server không trả về, nên
7 ngày phải đăng nhập lại. Đừng hứa với người dùng là tự gia hạn được.
Hỏi lại quá dày khi chờ duyệt sẽ bị chặn `slow_down`; giãn ≥ 8 giây.

⚠️ TRẠNG THÁI THỰC TẾ (đo 2026-07-28, không phải phỏng đoán): ĐĂNG NHẬP CHẠY,
   NHƯNG KHÔNG CÓ MODEL NÀO DÙNG ĐƯỢC. Thử cả 4 upstream với token thật:
     openrouter    → HTTP 402 "can only afford 322 tokens" (hết credit của
                     tác giả — "model miễn phí" chạy bằng tài khoản OpenRouter
                     của họ, và tài khoản đó đã cạn)
     minimax       → AI_NoOutputGeneratedError: No output generated
     orcarouter    → "OrcaRouter not configured on server"
     concentrateai → "Bring your own API key to use default"
   Provider này vì vậy ĐỂ SẴN chứ chưa dùng được. Kiểm lại bằng một lượt
   curl tới /api/ai/chat trước khi bật cho người dùng.

GIỚI HẠN ĐÃ BIẾT (đọc mã CLI 0.1.90, không phải suy đoán):
  - CLI KHÔNG có đường gửi ảnh; không rõ backend có nhận phần ảnh trong
    ``messages`` hay không. ĐỪNG dùng provider này cho nhánh vision — nếu
    server lặng lẽ bỏ phần ảnh thì model trả lời như chưa từng thấy ảnh,
    kiểu hỏng khó phát hiện nhất.
  - Backend chạy trên Render gói miễn phí: ngủ khi rảnh, request đầu tiên
    có thể mất 30–60 giây để đánh thức. Không hợp cho việc chạy hàng loạt.
  - Token là session của better-auth nên sẽ hết hạn; hết thì đăng nhập lại
    bằng CLI rồi cập nhật cấu hình.

Model id dạng ``sc/<provider>:<model>`` (vd ``sc/openrouter:glm-5.2``).
Bỏ phần provider thì mặc định ``openrouter``.
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator

from curl_cffi import requests

from services.config import config
from utils.log import logger

BASE_URL = "https://supercode-8w7e.onrender.com"
CHAT_PATH = "/api/ai/chat"
ME_PATH = "/api/user/me"

DEFAULT_UPSTREAM = "openrouter"
# Backend trên Render ngủ khi rảnh → request đầu phải chờ đánh thức.
TIMEOUT = 180

_QUOTA_MARKS = ("Insufficient Funds", "Credit usage at configured limit")


def _cfg() -> dict[str, Any]:
    c = (config.data.get("providers") or {}).get("supercode") or {}
    return c if isinstance(c, dict) else {}


def _base_url() -> str:
    return str(_cfg().get("base_url") or BASE_URL).rstrip("/")


def _token() -> str:
    return str(_cfg().get("api_key") or _cfg().get("access_token") or "").strip()


def _split_model(model: str) -> tuple[str, str]:
    """``openrouter:glm-5.2`` → ("openrouter", "glm-5.2"). Không có ':' thì
    dùng provider mặc định."""
    m = str(model or "").strip()
    if ":" in m:
        up, _, name = m.partition(":")
        return (up.strip() or DEFAULT_UPSTREAM), name.strip()
    return DEFAULT_UPSTREAM, m


class SuperCodeProvider:
    """Model miễn phí qua backend supercode-cli (cần token đăng nhập GitHub)."""

    @property
    def is_available(self) -> bool:
        if not _token():
            return False
        try:
            resp = requests.get(
                f"{_base_url()}{ME_PATH}",
                headers={"Authorization": f"Bearer {_token()}"},
                timeout=30,
            )
            ok = resp.status_code < 400
            resp.close()
            return ok
        except Exception:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        """Backend không có endpoint liệt kê model, nên trả danh sách cấu hình
        được. Để trống cấu hình thì dùng các model thấy trong CLI 0.1.90."""
        ids = _cfg().get("models")
        if not isinstance(ids, list) or not ids:
            ids = [
                "openrouter:glm-5.2",
                "openrouter:deepseek-v4-flash",
                "openrouter:minimax-m3",
                "minimax:MiniMax-M2.5",
            ]
        now = int(time.time())
        return [
            {"id": f"sc/{str(i).strip()}", "object": "model",
             "created": now, "owned_by": "supercode"}
            for i in ids if str(i).strip()
        ]

    def chat_completions(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        stream: bool = False,
        tools: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any] | Iterator[str]:
        token = _token()
        if not token:
            raise RuntimeError(
                "supercode: chưa có token. Cài supercode-cli, đăng nhập GitHub, "
                "rồi chép access_token trong ~/.better-auth vào "
                "providers.supercode.api_key"
            )
        upstream, name = _split_model(model)
        body = {
            "messages": messages,
            "provider": upstream,
            "model": name or "default",
            "tools": tools or {},
        }
        resp = requests.post(
            f"{_base_url()}{CHAT_PATH}",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
            json=body, timeout=TIMEOUT, stream=True,
        )
        if resp.status_code >= 400:
            try:
                text = resp.text or ""
            finally:
                resp.close()
            if any(m in text for m in _QUOTA_MARKS):
                raise RuntimeError("supercode: hết hạn mức miễn phí, reset sau 24 giờ")
            raise RuntimeError(f"supercode {resp.status_code}: {text[:200]}")

        if stream:
            return self._iter_stream(resp, model)
        return self._collect(resp, model)

    # ── đọc NDJSON ────────────────────────────────────────────────────────

    def _events(self, resp: Any) -> Iterator[dict[str, Any]]:
        """Tách từng dòng JSON. Dòng lỗi cú pháp thì bỏ, KHÔNG dựng kết quả
        nửa vời từ mảnh vỡ."""
        buf = ""
        try:
            for chunk in resp.iter_content():
                if not chunk:
                    continue
                buf += chunk.decode("utf-8", errors="ignore")
                lines = buf.split("\n")
                buf = lines.pop()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
            if buf.strip():
                try:
                    yield json.loads(buf.strip())
                except json.JSONDecodeError:
                    pass
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def _collect(self, resp: Any, model: str) -> dict[str, Any]:
        text, reason, usage = "", "stop", {}
        for ev in self._events(resp):
            t = ev.get("type")
            if t == "text":
                text += str(ev.get("content") or "")
            elif t == "finish":
                reason = str(ev.get("reason") or "stop")
                usage = ev.get("usage") or {}
        return {
            "id": f"chatcmpl-sc-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"sc/{model}",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": reason,
            }],
            "usage": {
                "prompt_tokens": int(usage.get("inputTokens") or 0),
                "completion_tokens": int(usage.get("outputTokens") or 0),
                "total_tokens": int(usage.get("totalTokens") or 0),
            },
        }

    def _iter_stream(self, resp: Any, model: str) -> Iterator[str]:
        cid = f"chatcmpl-sc-{int(time.time())}"

        def frame(delta: dict[str, Any], finish: str | None = None) -> str:
            return "data: " + json.dumps({
                "id": cid, "object": "chat.completion.chunk",
                "created": int(time.time()), "model": f"sc/{model}",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }, ensure_ascii=False) + "\n\n"

        yield frame({"role": "assistant", "content": ""})
        got = False
        for ev in self._events(resp):
            t = ev.get("type")
            if t == "text":
                c = str(ev.get("content") or "")
                if c:
                    got = True
                    yield frame({"content": c})
            elif t == "finish":
                yield frame({}, str(ev.get("reason") or "stop"))
        if not got:
            logger.warning({"event": "supercode_empty_stream", "model": model})
        yield "data: [DONE]\n\n"


supercode_provider = SuperCodeProvider()

__all__ = ["SuperCodeProvider", "supercode_provider"]
