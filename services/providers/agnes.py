"""
Agnes AI Provider — Agnes AI Models (Text 2.5 Flash, Image 2.1 Flash, Video v2.0).

Supports:
- Text & Multimodal chat streaming/non-streaming via standard OpenAI / Gemini compatible endpoints.
- Image generation & editing (agnes-image-2.0-flash, agnes-image-2.1-flash).
- Video generation (agnes-video-v2.0) with async polling.
"""

from __future__ import annotations

import json
import re
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


def _iter_custom_providers() -> list[dict[str, Any]]:
    cps = config.data.get("custom_providers") or {}
    result: list[dict[str, Any]] = []
    if isinstance(cps, dict):
        for pid, cp in cps.items():
            if isinstance(cp, dict):
                d = dict(cp)
                d.setdefault("id", pid)
                result.append(d)
    elif isinstance(cps, list):
        for cp in cps:
            if isinstance(cp, dict):
                result.append(cp)
    return result


def _agnes_base_url() -> str:
    cfg = (config.data.get("providers") or {}).get("agnes") or {}
    base = str(cfg.get("base_url") or "").rstrip("/")
    if not base:
        for cp in _iter_custom_providers():
            cp_id = str(cp.get("id") or "").lower()
            cp_name = str(cp.get("name") or "").lower()
            cp_prefix = str(cp.get("prefix") or "").lower()
            if "agnes" in cp_id or "agnes" in cp_name or "agnes" in cp_prefix:
                base = str(cp.get("base_url") or "").rstrip("/")
                if base:
                    break
    if not base:
        # Check any custom provider base_url if still missing
        for cp in _iter_custom_providers():
            b = str(cp.get("base_url") or "").rstrip("/")
            if "agnes" in b.lower():
                base = b
                break
    if not base:
        base = AGNES_DEFAULT_BASE_URL
    return base


def _strip_agnes_model(model: str) -> str:
    """Strip routing prefixes like 'agnes/' or 'custom:' so bare model id reaches Agnes API."""
    m = str(model or "").strip()
    if m.startswith("agnes/"):
        m = m[len("agnes/"):]
    elif ":" in m:
        m = m.rsplit(":", 1)[-1]
    if m.startswith("agnes/"):
        m = m[len("agnes/"):]
    return m


# ── Hạn mức thuê bao Agnes (tài liệu chính thức, chủ máy đưa 31/07/2026) ─────
# Áp dụng ĐỒNG THỜI với giới hạn RPM. Dòng ảnh và video giống nhau ở mọi gói:
#
#   Gói      agnes-2.5-flash (chat)              image-2.1-flash   video-v2.0
#   Starter  1.500 lượt/5giờ ·  15.000 lượt/tuần  4.000 ảnh/ngày   500 GIÂY/ngày
#   Plus     7.500 lượt/5giờ ·  75.000 lượt/tuần  4.000 ảnh/ngày   500 giây/ngày
#   Pro     30.000 lượt/5giờ · 300.000 lượt/tuần  4.000 ảnh/ngày   500 giây/ngày
#
# Đáng nhớ nhất: video tính bằng GIÂY (500/ngày) — một video 10s ăn 2% quỹ ngày,
# nên khi Agnes trả lỗi hạn mức video thì đó là hết QUỸ GIÂY, đổi gói to hơn
# cũng không tăng (mọi gói đều 500 giây).

# Bậc cỡ và tỉ lệ Agnes công bố cho agnes-image-2.1-flash (tài liệu chính thức,
# chủ máy đưa 31/07/2026).
_AGNES_BAC_CO = ("1K", "2K", "3K", "4K")
_AGNES_TI_LE = ("1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9")
# Cỡ CHÍNH XÁC cho agnes-image-2.0-flash (đời cũ, không có khoá `ratio`).
_AGNES_CO_2_0 = {"1:1": "1024x1024", "4:3": "1024x768", "3:4": "768x1024",
                 "16:9": "1024x768", "9:16": "768x1024", "3:2": "1024x768",
                 "2:3": "768x1024", "21:9": "1024x768"}


def _agnes_co_chinh_xac(size: str, ti_le: str) -> str:
    """Cỡ dạng "RỘNGxCAO" cho agnes-image-2.0-flash.

    Người dùng đưa sẵn "1024x768" thì dùng nguyên; đưa bậc "1K"/"2K" (dạng của
    đời 2.1) thì suy từ tỉ lệ, vì đời 2.0 không hiểu bậc.
    """
    s = (size or "").strip().lower()
    if "x" in s:
        return s
    return _AGNES_CO_2_0.get((ti_le or "").strip(), "1024x1024")


def _agnes_khung(resolution: Any, ti_le: Any) -> tuple[int, int]:
    """Đổi (độ phân giải, tỉ lệ) → (width, height) cho agnes-video-v2.0.

    Tài liệu chỉ có `width`/`height`, mặc định 1152×768. Tab Tạo Video lại cho
    người dùng chọn "1080p/720p/480p" và tỉ lệ, nên phải quy đổi ở đây — không
    thì hai lựa chọn đó bị bỏ (khoá `resolution`/`aspect_ratio` cũ không có trong
    tài liệu).
    """
    canh = {"1080p": 1080, "720p": 720, "480p": 480}.get(
        str(resolution or "").strip().lower(), 768)
    tl = str(ti_le or "16:9").strip()
    try:
        a, b = tl.split(":")
        ra, rb = float(a), float(b)
    except Exception:
        ra, rb = 16.0, 9.0
    if ra >= rb:                       # ngang: cạnh ngắn = chiều cao
        h = canh
        w = int(round(h * ra / rb))
    else:                              # dọc: cạnh ngắn = chiều rộng
        w = canh
        h = int(round(w * rb / ra))
    # Bội số 8 — chuẩn chung của mô hình sinh video.
    return max(64, w - w % 8), max(64, h - h % 8)


def _agnes_so_khung(num_frames: Any) -> int | None:
    """Số khung hợp lệ cho agnes-video-v2.0.

    Tài liệu: `num_frames` phải ≤ 441 VÀ theo quy tắc 8n+1 (9, 17, 25, …). Trước
    đây code chuyển tiếp nguyên số người dùng đưa, nên một con số "tròn" như 120
    hay 240 là sai quy tắc — Agnes từ chối hoặc tự chuẩn hoá, và người dùng không
    biết vì sao độ dài không đúng ý.
    """
    if num_frames is None:
        return None
    try:
        n = int(num_frames)
    except (TypeError, ValueError):
        return None
    n = max(9, min(441, n))
    # Về mốc 8n+1 gần nhất, KHÔNG vượt trần.
    k = round((n - 1) / 8)
    ra = int(8 * k + 1)
    while ra > 441:
        ra -= 8
    return max(9, ra)


def _giay_video(duration: str | int | None, mac_dinh: int = 5) -> int:
    """Số giây video, luôn trả SỐ NGUYÊN cho API Agnes.

    Người gọi có thể truyền 5, "5", "5s", hay None (endpoint /v1/video/generations
    khai `duration: str | None`). Agnes lại yêu cầu int, gửi chuỗi là HTTP 400.
    """
    if duration is None or duration == "":
        return mac_dinh
    if isinstance(duration, int):
        return duration if duration > 0 else mac_dinh
    so = re.search(r"\d+", str(duration))
    return int(so.group()) if so else mac_dinh


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

        # Fallback/Merge from custom_providers if any custom provider entry matches 'agnes'
        for cp in _iter_custom_providers():
            cp_id = str(cp.get("id") or "").lower()
            cp_name = str(cp.get("name") or "").lower()
            cp_prefix = str(cp.get("prefix") or "").lower()
            if "agnes" in cp_id or "agnes" in cp_name or "agnes" in cp_prefix:
                if cp.get("enabled") is False:
                    continue
                cp_single = str(cp.get("api_key") or "").strip()
                cp_multi = cp.get("api_keys") or []
                if not isinstance(cp_multi, list):
                    cp_multi = []
                for k in cp_multi:
                    k_str = str(k).strip()
                    if k_str and k_str not in keys:
                        keys.append(k_str)
                if cp_single and cp_single not in keys:
                    keys.insert(0, cp_single)

        # Ultimate fallback: chỉ gom key từ custom provider THỰC SỰ là Agnes
        # (base_url chứa 'agnes'). KHÔNG dựa vào tiền tố 'sk-' vì rất nhiều
        # provider khác (OpenAI, DeepSeek…) cũng dùng key 'sk-' → tránh gửi
        # nhầm key provider khác lên apihub.agnes-ai.com.
        if not keys:
            for cp in _iter_custom_providers():
                if cp.get("enabled") is False:
                    continue
                b_url = str(cp.get("base_url") or "").lower()
                cp_single = str(cp.get("api_key") or "").strip()
                cp_multi = cp.get("api_keys") or []
                if not isinstance(cp_multi, list):
                    cp_multi = []
                if "agnes" in b_url:
                    for k in cp_multi:
                        k_str = str(k).strip()
                        if k_str and k_str not in keys:
                            keys.append(k_str)
                    if cp_single and cp_single not in keys:
                        keys.insert(0, cp_single)

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
        """POST with automatic API-key failover & transient retry on HTTP 429 / 402 / 503.

        Tries each configured key in FIFO order (skipping keys in cooldown). On 429
        (rate limit) the key gets a short cooldown; on 402 (quota exhausted) a long
        cooldown; on 503 (service busy) a brief retry pause — then the next key/retry is tried.
        Returns (used_key, response); raises if no key succeeds.
        """
        if isinstance(urls, str):
            urls = [urls]
        keys = self._get_keys()
        if not keys:
            raise RuntimeError("Agnes AI key not configured")
        last_detail = ""
        max_attempts = max(len(keys) * 2, 4)

        for attempt in range(max_attempts):
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
                if resp.status_code == 200:
                    break
                if resp.status_code in (429, 402, 500, 502, 503, 504):
                    break  # transient/retryable status
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
            if resp.status_code in (500, 502, 503, 504):
                # Service busy / transient server error: sleep briefly and retry
                time.sleep(1.5)
                last_detail = f"Máy chủ Agnes AI đang bận (HTTP {resp.status_code})"
                continue

            # Clean up error JSON if present
            err_msg = resp.text
            try:
                err_data = resp.json()
                if isinstance(err_data, dict) and "error" in err_data:
                    err_sub = err_data["error"]
                    if isinstance(err_sub, dict):
                        err_msg = err_sub.get("message") or err_msg
                    elif isinstance(err_sub, str):
                        err_msg = err_sub
            except Exception:
                pass
            raise RuntimeError(f"Agnes AI error (HTTP {resp.status_code}): {err_msg}")

        raise RuntimeError(f"Agnes AI: Máy chủ đang bận (Service Busy) hoặc API Key bị giới hạn. ({last_detail})")

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
        size: str = "1K", aspect_ratio: str = "16:9", image: Any = None, n: int = 1,
        return_base64: bool | None = None,
    ) -> dict[str, Any]:
        """Tạo hoặc SỬA ảnh bằng Agnes AI.

        Tên khoá theo TÀI LIỆU CHÍNH THỨC của Agnes (chủ máy đưa 31/07/2026).
        Trước đây hàm này gửi `quality` và `aspect_ratio` — hai khoá KHÔNG có
        trong tài liệu; tài liệu ghi là `size` và `ratio`. Nên kích thước và tỉ lệ
        người dùng chọn chưa bao giờ tới được Agnes: ảnh vẫn ra nhưng luôn ở cỡ
        mặc định, y như hôm nay tìm ra ở phần video.

        Hai đời model nhận `size` KHÁC NHAU:
          • agnes-image-2.0-flash — cỡ CHÍNH XÁC ("1024x768", "1024x1024",
            "768x1024"). Không có khoá `ratio`.
          • agnes-image-2.1-flash — BẬC cỡ ("1K"/"2K"/"3K"/"4K") kèm `ratio`
            ("1:1","3:4","4:3","16:9","9:16","2:3","3:2","21:9").
        """
        model = _strip_agnes_model(model)
        body: dict[str, Any] = {"model": model, "prompt": prompt, "n": n}

        la_2_1 = "2.1" in model or "2-1" in model
        s = str(size or "").strip()
        if la_2_1:
            # Bậc cỡ; nhận cả cỡ chính xác cũ (tài liệu nói vẫn chấp nhận nhưng
            # có thể bị chuẩn hoá) — cứ chuyển tiếp nguyên văn.
            body["size"] = s.upper() if s.upper() in _AGNES_BAC_CO else (s or "1K")
            body["ratio"] = aspect_ratio if aspect_ratio in _AGNES_TI_LE else "1:1"
        else:
            body["size"] = _agnes_co_chinh_xac(s, aspect_ratio)

        # `image` là MẢNG chuỗi (URL công khai hoặc data URI base64) — code cũ gán
        # thẳng một chuỗi nên phần sửa-ảnh-theo-ảnh-gốc gửi sai kiểu.
        if image:
            ds = image if isinstance(image, (list, tuple)) else [image]
            hop_le = [str(x) for x in ds if str(x or "").strip()]
            if hop_le:
                body["image"] = hop_le
        if return_base64 is not None:
            body["return_base64"] = bool(return_base64)

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
            # Agnes nhận `duration` là SỐ NGUYÊN. Gửi chuỗi thì API trả HTTP 400
            # "json: cannot unmarshal string into Go struct field
            # taskSubmitReqAlias.duration of type int" — nghĩa là mọi lượt tạo
            # video qua agnes đều thất bại. Đo thật 31/07 sau khi vá chỗ báo lỗi
            # bị crash (trước đó lỗi này bị che thành HTTP 500 trắng).
            # (`duration` KHÔNG có trong tài liệu nhưng lỗi trên chứng minh nó là
            # trường thật — giữ lại.)
            "duration": _giay_video(duration),
        }
        # KHUNG HÌNH: tài liệu ghi `width`/`height` (mặc định 1152×768), KHÔNG có
        # `resolution` hay `aspect_ratio`. Hai khoá cũ đó không nằm trong tài liệu
        # nên độ phân giải và tỉ lệ người dùng chọn ở tab Tạo Video chưa bao giờ
        # tới được Agnes. Quy đổi sang width/height thật.
        w, h = _agnes_khung(resolution, aspect_ratio)
        body["width"], body["height"] = w, h
        # `num_frames` phải ≤441 và theo 8n+1 — xem _agnes_so_khung.
        khung = _agnes_so_khung(num_frames)
        if khung is not None:
            body["num_frames"] = khung
        effective_fps = frame_rate or fps
        if effective_fps is not None:
            try:                      # tài liệu: 1–60
                body["frame_rate"] = max(1, min(60, int(effective_fps)))
            except (TypeError, ValueError):
                pass
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        if seed is not None:
            body["seed"] = seed
        buoc = kwargs.get("num_inference_steps")
        if buoc is not None:
            try:
                body["num_inference_steps"] = int(buoc)
            except (TypeError, ValueError):
                pass

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
