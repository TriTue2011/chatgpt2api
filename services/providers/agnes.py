"""
Agnes AI Provider — Agnes AI Models (Text 2.5 Flash, Image 2.1 Flash, Video v2.0).

Supports:
- Text & Multimodal chat streaming/non-streaming via standard OpenAI / Gemini compatible endpoints.
- Image generation & editing (agnes-image-2.0-flash, agnes-image-2.1-flash).
- Video generation (agnes-video-v2.0) with async polling.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator

from curl_cffi import requests

from services.config import config
from utils.log import logger

AGNES_DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"
AGNES_DEFAULT_MODEL = "agnes-2.5-flash"

AGNES_MODELS = [
    {"id": "agnes-2.5-flash", "owned_by": "agnes", "capability": "chat"},
    {"id": "agnes-2.0-flash", "owned_by": "agnes", "capability": "chat"},
    {"id": "agnes-image-2.1-flash", "owned_by": "agnes", "capability": "image"},
    {"id": "agnes-image-2.0-flash", "owned_by": "agnes", "capability": "image"},
    {"id": "agnes-video-v2.0", "owned_by": "agnes", "capability": "video_gen"},
]


def _agnes_base_url() -> str:
    cfg = (config.data.get("providers") or {}).get("agnes") or {}
    base = str(cfg.get("base_url") or "").rstrip("/")
    if not base:
        base = AGNES_DEFAULT_BASE_URL
    return base


def _strip_agnes_model(model: str) -> str:
    """Strip the internal 'agnes/' routing prefix so the bare model id reaches the API.

    The registry exposes ids like 'agnes/agnes-video-v2.0'; the Agnes API expects
    the bare 'agnes-video-v2.0'. Safe to call on already-bare ids (no-op).
    """
    m = str(model or "").strip()
    if m.startswith("agnes/"):
        m = m[len("agnes/"):]
    return m


class AgnesProvider:
    """Agnes AI provider supporting round-robin API keys and full multimodal capabilities."""

    def __init__(self):
        self._key_index = 0
        self._rate_limited: dict[str, float] = {}
        self._key_status: dict[str, str] = {}  # key -> "limited" (429) | "exhausted" (402)
        self._account_cache: dict[str, tuple[float, dict[str, Any]]] = {}  # key -> (ts, info)
        self._account_cache_ttl = 45.0  # seconds — avoid re-probing quota on every tab load

    def _get_keys(self) -> list[str]:
        cfg = config.data.get("providers") or {}
        agnes_cfg = cfg.get("agnes") or {}
        single = str(agnes_cfg.get("api_key") or "").strip()
        multi = agnes_cfg.get("api_keys") or []
        if not isinstance(multi, list):
            multi = []
        keys = [k.strip() for k in multi if k.strip()]
        if single and single not in keys:
            keys.insert(0, single)
        return keys

    def is_key_rate_limited(self, key: str) -> bool:
        until = self._rate_limited.get(key, 0)
        if time.time() < until:
            return True
        if key in self._rate_limited:
            del self._rate_limited[key]
        self._key_status.pop(key, None)
        return False

    def mark_key_rate_limited(self, key: str, cooldown_seconds: float = 300.0, status: str = "limited"):
        self._rate_limited[key] = time.time() + cooldown_seconds
        self._key_status[key] = status

    def _post_with_failover(
        self, urls, payload: dict[str, Any], *, stream: bool = False, timeout: float = 120,
    ) -> tuple[str, Any]:
        """POST with automatic API-key failover on HTTP 429 / 402.

        Tries each configured key in FIFO order (skipping keys in cooldown). On 429
        (rate limit) the key gets a short cooldown; on 402 (quota exhausted) a long
        cooldown — then the next key is tried. `urls` may be a single URL or a list
        of fallback URLs tried (in order) with the SAME key. Other non-200 statuses
        surface immediately. Returns (used_key, response); raises if no key succeeds.
        """
        if isinstance(urls, str):
            urls = [urls]
        keys = self._get_keys()
        if not keys:
            raise RuntimeError("Agnes AI key not configured")
        last_detail = ""
        for _ in range(len(keys)):
            key = self.api_key
            if not key:
                break
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            resp = None
            for u in urls:
                try:
                    resp = requests.post(u, headers=headers, json=payload, stream=stream, timeout=timeout)
                except Exception as exc:
                    last_detail = f"request error: {exc}"
                    resp = None
                    continue
                if resp.status_code == 200 or resp.status_code in (429, 402):
                    break  # decisive: success or account-level throttle
                last_detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp is None:
                self.mark_key_rate_limited(key, 60.0)
                continue
            if resp.status_code == 200:
                return key, resp
            if resp.status_code in (429, 402):
                if resp.status_code == 402:
                    self.mark_key_rate_limited(key, 1800.0, status="exhausted")
                else:
                    self.mark_key_rate_limited(key, 60.0, status="limited")
                last_detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue
            raise RuntimeError(f"Agnes AI error HTTP {resp.status_code}: {resp.text}")
        raise RuntimeError(f"Agnes AI: tất cả API key đều hết quota/bị giới hạn. {last_detail}")

    @property
    def api_key(self) -> str:
        keys = self._get_keys()
        if not keys:
            return ""
        # Find first non-rate-limited key
        for _ in range(len(keys)):
            key = keys[self._key_index % len(keys)]
            self._key_index += 1
            if not self.is_key_rate_limited(key):
                return key
        # Fallback to current key if all are temporarily limited
        key = keys[self._key_index % len(keys)]
        self._key_index += 1
        return key

    @property
    def is_available(self) -> bool:
        key = self.api_key
        if not key:
            return False
        try:
            headers = {"Authorization": f"Bearer {key}"}
            resp = requests.get(f"{_agnes_base_url()}/models", headers=headers, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        return AGNES_MODELS

    def get_account_info(self, api_key: str | None = None) -> dict[str, Any]:
        """Check Agnes AI account plan, remaining credits, and subscription status."""
        key = api_key or self.api_key
        if not key:
            return {"error": "Agnes AI key not configured"}

        headers = {"Authorization": f"Bearer {key}"}
        base_url = _agnes_base_url()
        result: dict[str, Any] = {"api_key": f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "***"}

        # Check rate limited status (reflect the real reason: 429=limited / 402=exhausted)
        if self.is_key_rate_limited(key):
            until = int(self._rate_limited.get(key, 0) - time.time())
            result["status"] = self._key_status.get(key, "limited")
            result["active"] = False
            result["error"] = f"Cooldown ({until}s remaining)"
            return result

        # Serve from short-lived cache to avoid 3 sequential HTTP probes per key
        # on every account-tab refresh.
        cached = self._account_cache.get(key)
        if cached and (time.time() - cached[0]) < self._account_cache_ttl:
            return dict(cached[1])

        # 1. Query Subscription / Plan Info
        try:
            sub_url = f"{base_url}/dashboard/billing/subscription"
            resp = requests.get(sub_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                sdata = resp.json()
                result["plan"] = sdata.get("plan", {}).get("title") or sdata.get("plan_name") or sdata.get("plan") or "Standard"
                result["hard_limit_usd"] = sdata.get("hard_limit_usd")
                result["access_until"] = sdata.get("access_until")
                result["has_payment_method"] = sdata.get("has_payment_method")
            elif resp.status_code in (429, 402):
                result["status"] = "limited" if resp.status_code == 429 else "exhausted"
        except Exception as exc:
            logger.warning("agnes: get subscription error: %s", exc)

        # 2. Query User Profile / Self info
        try:
            user_url = f"{base_url}/user/self"
            resp = requests.get(user_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                udata = resp.json()
                if isinstance(udata, dict) and "data" in udata:
                    udata = udata["data"]
                result["username"] = udata.get("username") or udata.get("email") or udata.get("name")
                result["role"] = udata.get("role")
                if not result.get("plan"):
                    result["plan"] = udata.get("group") or udata.get("plan") or "Standard"
                result["quota"] = udata.get("quota")
                result["used_quota"] = udata.get("used_quota")
        except Exception as exc:
            logger.warning("agnes: get user self error: %s", exc)

        # 3. Fallback check models endpoint to confirm active status
        try:
            m_resp = requests.get(f"{base_url}/models", headers=headers, timeout=10)
            result["active"] = (m_resp.status_code == 200)
            if not result.get("status"):
                result["status"] = "active" if m_resp.status_code == 200 else "error"
        except Exception:
            result["active"] = False
            if not result.get("status"):
                result["status"] = "error"

        self._account_cache[key] = (time.time(), dict(result))
        return result

    def chat_completions(
        self, messages, model=AGNES_DEFAULT_MODEL, stream=False,
        temperature=None, max_tokens=None, tools=None, tool_choice=None, **kwargs,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Send chat/completion request to Agnes AI."""
        model = _strip_agnes_model(model)
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        url = f"{_agnes_base_url()}/chat/completions"

        if stream:
            _, resp = self._post_with_failover(url, body, stream=True)
            return self._iter_stream(resp)

        _, resp = self._post_with_failover(url, body)
        return resp.json()

    def _iter_stream(self, resp: Any) -> Iterator[dict[str, Any]]:
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            if line.startswith("data: "):
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    yield json.loads(data_str)
                except Exception:
                    continue

    def generate_image(
        self, prompt: str, model: str = "agnes-image-2.1-flash",
        size: str = "1K", aspect_ratio: str = "16:9", image: str | None = None, n: int = 1,
    ) -> dict[str, Any]:
        """Generate or edit image using Agnes AI (Default: 1K resolution, 16:9 aspect ratio)."""
        model = _strip_agnes_model(model)
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "quality": size or "1K",
            "aspect_ratio": aspect_ratio or "16:9",
        }
        if image:
            body["image"] = image

        url = f"{_agnes_base_url()}/images/generations"
        _, resp = self._post_with_failover(url, body)
        return resp.json()

    def generate_video(
        self,
        prompt: str,
        model: str = "agnes-video-v2.0",
        resolution: str = "1080p",
        aspect_ratio: str = "16:9",
        duration: str | int = "5",
        num_frames: int | None = None,
        frame_rate: int | None = None,
        fps: int | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        mode: str | None = None,
        image: str | None = None,
        last_frame: str | None = None,
        keyframes: list[str] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Generate video asynchronously using Agnes AI with full parameter support."""
        model = _strip_agnes_model(model)
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "resolution": resolution or "1080p",
            "aspect_ratio": aspect_ratio or "16:9",
            "duration": str(duration) if duration else "5",
        }
        if num_frames is not None:
            body["num_frames"] = num_frames
        effective_fps = frame_rate or fps
        if effective_fps is not None:
            body["frame_rate"] = effective_fps
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        if seed is not None:
            body["seed"] = seed

        # Keyframe animation vs Image-to-video mode handling
        if keyframes or (image and last_frame):
            imgs = keyframes if keyframes else [image, last_frame]
            body["extra_body"] = {
                "image": imgs,
                "mode": mode or "keyframes",
            }
            body["mode"] = mode or "keyframes"
        elif image:
            body["image"] = image
            if mode:
                body["mode"] = mode

        # Submit with key failover: try /video/generations then /videos per key.
        base_url = _agnes_base_url()
        used_key, resp = self._post_with_failover(
            [f"{base_url}/video/generations", f"{base_url}/videos"], body, timeout=60,
        )
        # Reuse the winning key for the async polling requests below.
        headers = {"Authorization": f"Bearer {used_key}", "Content-Type": "application/json"}

        data = resp.json()
        task_id = data.get("task_id") or data.get("id") or data.get("video_id")
        video_id = data.get("video_id") or data.get("id") or task_id

        # If immediate result returned
        video_url = data.get("video_url") or (data.get("metadata") or {}).get("url")
        if video_url:
            return {"created": int(time.time()), "data": [{"url": video_url}]}
        if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
            return data

        if not task_id and not video_id:
            return data

        # Async Polling loop up to 5 minutes (300 seconds)
        start_time = time.time()
        while time.time() - start_time < 300:
            time.sleep(5)
            # Try endpoints for polling status
            endpoints = []
            if task_id:
                endpoints.append(f"{base_url}/video/tasks/{task_id}")
                endpoints.append(f"{base_url}/videos/{task_id}")
            if video_id:
                endpoints.append(f"{base_url.replace('/v1', '')}/agnesapi?video_id={video_id}")
                endpoints.append(f"{base_url}/agnesapi?video_id={video_id}")

            for poll_url in endpoints:
                try:
                    poll_resp = requests.get(poll_url, headers=headers, timeout=20)
                    if poll_resp.status_code == 200:
                        pdata = poll_resp.json()
                        status = str(pdata.get("status") or "").lower()
                        if status in ("completed", "succeeded", "success"):
                            res_url = (
                                pdata.get("video_url")
                                or (pdata.get("metadata") or {}).get("url")
                                or pdata.get("url")
                            )
                            if not res_url and "data" in pdata:
                                return pdata
                            return {
                                "created": int(time.time()),
                                "data": [{"url": res_url or "", "task_id": task_id}],
                            }
                        if status in ("failed", "error"):
                            raise RuntimeError(f"Agnes AI Video Task failed: {pdata.get('error')}")
                except Exception as exc:
                    if "Video Task failed" in str(exc):
                        raise
                    continue

        raise RuntimeError("Agnes AI Video generation timed out after 5 minutes")


agnes_provider = AgnesProvider()
