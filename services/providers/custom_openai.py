"""
Custom OpenAI-compatible Provider — generic proxy for any OpenAI-compatible API.

Users can add custom APIs via UI (Settings → Custom Providers) without writing code.
Each provider gets a unique prefix. Models are auto-fetched from {base_url}/v1/models.

Config stored in config.data["custom_providers"]:
{
  "deepseek": {
    "name": "DeepSeek",
    "base_url": "https://api.deepseek.com",
    "api_key": "sk-...",
    "prefix": "deepseek",
    "enabled": true
  }
}
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Iterator

from curl_cffi import requests

from services.config import config
from utils.log import logger


# Provider khai bằng BIẾN MÔI TRƯỜNG — dành cho máy chạy model tại nhà.
#
# Vì sao cần: khai tay qua API thì mỗi lần dựng lại máy (đổi IP máy GPU, cài lại
# từ đầu, dựng bản sao để thử) đều phải nhớ gọi lại POST /api/v1/custom-providers,
# và quên là model local biến mất khỏi danh sách mà không báo gì. Đặt biến trong
# compose thì hạ tầng tự khai lấy.
#
# {tên biến: (prefix model, tên hiển thị)}. Khoá API lấy ở "<TÊN BIẾN>_KEY",
# không khai thì dùng "local" — llama.cpp không kiểm khoá.
_PROVIDER_TU_ENV: dict[str, tuple[str, str]] = {
    "VISION_URL_GPU": ("lv", "Vision GPU (máy tại nhà)"),
    # Ollama phục vụ luôn giao diện OpenAI ở /v1, nên khai như một provider
    # bình thường là đủ — model của nó (vd model điều khiển nhà) hiện chung
    # danh sách với mọi model khác. Khai gọn "http://ip:11434" cũng được.
    "OLLAMA_URL": ("ol", "Ollama (máy tại nhà)"),
}


# Prefix của provider khai bằng env — đều là model chạy tại nhà.
_PREFIX_MAY_NHA = {prefix for prefix, _ in _PROVIDER_TU_ENV.values()}


# Module ở máy khác khai bằng NGUYÊN TẮC thay vì thêm tên vào dict trên:
# mọi `C2A_PROVIDER_<ID>_URL` là một provider, tiền tố = ID viết thường, tên
# hiển thị ở `C2A_PROVIDER_<ID>_NAME`, khoá ở `C2A_PROVIDER_<ID>_KEY`.
# Vì sao: dict gõ tay chỉ có hai mục — thêm máy thứ ba (TTS trên .220, một
# domain ngoài) là phải sửa code, quên sửa thì module mới bị bỏ ở ngoài mà
# không ai báo. Các provider này KHÔNG vào `_PREFIX_MAY_NHA`: chưa chắc là
# máy tại nhà, nên không được tự nhận cách chèn chữ giữa các ảnh của llama.cpp.
_BIEN_PROVIDER_RE = re.compile(r"^C2A_PROVIDER_(.+)_URL$")
_ID_PROVIDER_RE = re.compile(r"^[A-Z0-9_]+$")

# `_providers_tu_env` chạy trong MỖI lần định tuyến model, nên một biến khai
# sai mà cảnh báo mỗi lượt là ngập log — mỗi (sự kiện, biến) chỉ báo một lần.
_da_canh_bao: set[tuple[str, str]] = set()


def _canh_bao_mot_lan(su_kien: str, bien: str, **chi_tiet: Any) -> None:
    if (su_kien, bien) in _da_canh_bao:
        return
    _da_canh_bao.add((su_kien, bien))
    logger.warning({"event": su_kien, "bien": bien, **chi_tiet})


def _provider_co_san_che(prefix: str) -> str:
    """Tên provider có sẵn sẽ nhận `<prefix>/…` TRƯỚC custom provider, "" nếu không.

    `BackendRouter.resolve_model` duyệt bảng tiền tố có sẵn trước rồi mới tới
    custom provider, nên tiền tố trùng (vd `oc` → opencode) làm module mới bị
    che mất. Tra thẳng hai bảng thay vì gọi `resolve_model`, vì `resolve_model`
    lại gọi `get_custom_providers` → về đây: gọi nó là vòng lặp vô tận.
    Nhập muộn để `backend_router` không phải nạp khi nạp mô-đun này.
    """
    from services.backend_router import IMAGE_PROVIDER_PREFIXES, PROVIDER_PREFIXES

    mau = f"{prefix}/x"
    for bang in (IMAGE_PROVIDER_PREFIXES, PROVIDER_PREFIXES):
        for tien_to, provider in bang.items():
            if mau.startswith(tien_to):
                return provider
    return ""


def _chuan_hoa_url(gia_tri: str | None) -> str:
    url = str(gia_tri or "").strip().rstrip("/")
    # Cho khai gọn "http://192.168.1.10:5003" — tự thêm /v1 cho đỡ một lỗi
    # đánh máy khiến model im lặng không hiện ra.
    if url and not url.endswith("/v1"):
        url = url + "/v1"
    return url


def _tach_khung_anh(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chèn một dòng chữ trước mỗi ảnh khi một lượt gửi nhiều ảnh.

    Vì sao cần: Qwen3-VL nhận được cả video, nên llama.cpp thấy nhiều ảnh nằm
    sát nhau là coi đó là các khung của một đoạn phim và gộp từng cặp khung
    liền kề lại. Đo trên fw-vision 19/08: gửi 2 ảnh tốn đúng bằng 1 ảnh (302
    token), 4 ảnh bằng 2 ảnh; chen chữ vào giữa thì mỗi ảnh về lại 306 token.
    Hai khoảnh khắc bị chồng lên nhau khiến một người đi ngang phòng bị tả
    thành hai người mặc đồ giống hệt nhau — sửa prompt không cứu được vì
    thông tin đã mất trước khi model kịp đọc. Home Assistant gửi ảnh qua
    `ai_task` dưới dạng danh sách đính kèm thuần nên không tự chèn được, đây
    là chỗ duy nhất chèn được hộ nó.
    """
    ra: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            ra.append(msg)
            continue
        so_anh = sum(
            1 for p in content if isinstance(p, dict) and p.get("type") == "image_url"
        )
        if so_anh < 2:
            ra.append(msg)
            continue
        moi: list[Any] = []
        thu_tu = 0
        for p in content:
            if isinstance(p, dict) and p.get("type") == "image_url":
                thu_tu += 1
                moi.append({"type": "text", "text": f"Frame {thu_tu} of {so_anh}:"})
            moi.append(p)
        ra.append({**msg, "content": moi})
    return ra


def _providers_tu_env() -> dict[str, dict[str, Any]]:
    ra: dict[str, dict[str, Any]] = {}
    for bien, (prefix, ten) in _PROVIDER_TU_ENV.items():
        url = _chuan_hoa_url(os.getenv(bien))
        if not url:
            continue
        ra[prefix] = {
            "name": ten,
            "prefix": prefix,
            "base_url": url,
            "base_urls": [],
            "api_key": str(os.getenv(bien + "_KEY") or "local"),
            "api_keys": [],
            "enabled": True,
        }

    for bien in sorted(os.environ):
        khop = _BIEN_PROVIDER_RE.match(bien)
        if not khop:
            continue
        ma = khop.group(1)
        if not _ID_PROVIDER_RE.match(ma):
            # Bỏ im lặng thì người khai tưởng module đã vào — báo để sửa tên.
            _canh_bao_mot_lan("provider_env_id_khong_hop_le", bien,
                              ly_do="ID chỉ gồm A–Z, 0–9, _")
            continue
        url = _chuan_hoa_url(os.getenv(bien))
        if not url:
            continue
        prefix = ma.lower()
        che = _provider_co_san_che(prefix)
        if che:
            _canh_bao_mot_lan("provider_env_trung_tien_to", bien,
                              prefix=prefix, provider=che)
            continue
        if prefix in ra:
            # Trùng `lv`/`ol` của hai biến cũ đang đặt: biến cũ giữ nguyên
            # hành vi, biến mới bị bỏ chứ không lặng lẽ thay máy đang chạy.
            _canh_bao_mot_lan("provider_env_trung_tien_to", bien,
                              prefix=prefix, provider=f"custom:{prefix}")
            continue
        ra[prefix] = {
            "name": str(os.getenv(f"C2A_PROVIDER_{ma}_NAME") or "").strip() or prefix,
            "prefix": prefix,
            "base_url": url,
            "base_urls": [],
            "api_key": str(os.getenv(f"C2A_PROVIDER_{ma}_KEY") or "local"),
            "api_keys": [],
            "enabled": True,
        }
    return ra


def get_custom_providers() -> dict[str, dict[str, Any]]:
    """Provider tuỳ chỉnh đang bật: khai trong config, cộng thêm khai bằng env.

    Trùng khoá thì CONFIG THẮNG — người vận hành sửa trên giao diện là có ý,
    không để một biến môi trường cũ lặng lẽ ghi đè lựa chọn đó.
    """
    providers = dict(_providers_tu_env())
    tu_config = config.data.get("custom_providers") or {}
    if isinstance(tu_config, dict):
        providers.update(tu_config)
    return {
        k: v for k, v in providers.items()
        if isinstance(v, dict) and v.get("enabled", True)
    }


def resolve_custom_provider(model: str) -> tuple[dict[str, Any] | None, str]:
    """Check if model matches any custom provider prefix.
    Returns (provider_config, stripped_model) or (None, original_model).
    """
    for provider_id, cfg in get_custom_providers().items():
        prefix = str(cfg.get("prefix") or provider_id).strip()
        if not prefix:
            continue
        full_prefix = f"{prefix}/"
        if model.startswith(full_prefix):
            return (cfg, model[len(full_prefix):])
    return (None, model)


class CustomOpenAIProvider:
    """Generic OpenAI-compatible provider — proxies to any OpenAI-compatible endpoint.

    Supports a SINGLE provider definition with MULTIPLE base_urls so users can
    pool 4 Gemini Custom instances (different ports/IPs) under one provider
    instead of 4 separate entries. The first base_url is also exposed as
    `self.base_url` for backwards compatibility.

    Pool config:
        {"base_url": "http://host:8000",            # primary
         "base_urls": ["http://host:8001",          # additional endpoints
                       "http://host:8002",
                       "http://host:8003"]}

    On 429 / connection error from one base_url we mark it cooled-down for
    60s and rotate to the next; FIFO within the ordered list.
    """

    # Per-class registry so independent instantiations of the same provider
    # (which happens — `CustomOpenAIProvider(cfg)` runs per request) share
    # base-url cooldown state. Keyed by provider name.
    _base_url_cooldown: dict[str, dict[str, float]] = {}
    _base_url_index: dict[str, int] = {}
    _BASE_URL_COOLDOWN_S = 60.0

    def __init__(self, provider_config: dict[str, Any]):
        self.cfg = provider_config
        self.name = str(provider_config.get("name") or "Custom")
        # Build ordered base_url list — first is `base_url`, then `base_urls[]`
        # (deduped). `self.base_url` always returns the next healthy one for
        # backwards-compat with callers that read it directly.
        primary = str(provider_config.get("base_url") or "").rstrip("/")
        extras_raw = provider_config.get("base_urls") or []
        if not isinstance(extras_raw, list):
            extras_raw = []
        extras = [str(u or "").rstrip("/") for u in extras_raw if str(u or "").strip()]
        ordered: list[str] = []
        if primary:
            ordered.append(primary)
        for u in extras:
            if u and u not in ordered:
                ordered.append(u)
        self._base_urls = ordered
        self.base_url = self._next_healthy_base_url() if ordered else ""
        self._key_index = 0
        self._rate_limited: dict[str, float] = {}

        # Detect API style: some providers don't use /v1 prefix
        api_style = str(provider_config.get("api_style") or "").strip().lower()
        if not api_style:
            if "deepseek.com" in self.base_url:
                api_style = "deepseek"
            elif "perplexity.ai" in self.base_url:
                api_style = "deepseek"  # Perplexity also uses no /v1
            else:
                api_style = "openai"
        self._api_style = api_style

        # Determine paths: avoid double /v1 when base_url already includes it
        base_has_v1 = self.base_url.rstrip("/").endswith("/v1")

        if api_style == "deepseek":
            self._models_path = "/models"
            self._chat_path = "/chat/completions"
        elif base_has_v1:
            # Base URL already includes /v1 (e.g. https://api.groq.com/openai/v1)
            self._models_path = "/models"
            self._chat_path = "/chat/completions"
        else:
            # Standard OpenAI format: base_url has no /v1 suffix
            self._models_path = "/v1/models"
            self._chat_path = "/v1/chat/completions"

    def _next_healthy_base_url(self) -> str:
        """Pick the next non-cooled-down base_url in FIFO order, skipping any
        currently in cooldown. Returns first URL if all are in cooldown."""
        if not self._base_urls:
            return ""
        if len(self._base_urls) == 1:
            return self._base_urls[0]
        cooldown = CustomOpenAIProvider._base_url_cooldown.setdefault(self.name, {})
        now = time.time()
        # Always start from index 0 — true priority FIFO. Demoted URLs will
        # have been moved to the back via _demote_base_url and stay there.
        for url in self._base_urls:
            if cooldown.get(url, 0) < now:
                return url
        return self._base_urls[0]

    def _demote_base_url(self, url: str) -> None:
        """Move a base_url to the END of the order + cool it down for
        BASE_URL_COOLDOWN_S so the next picker skips past it."""
        if not url or url not in self._base_urls:
            return
        # Cooldown so _next_healthy_base_url skips it.
        cooldown = CustomOpenAIProvider._base_url_cooldown.setdefault(self.name, {})
        cooldown[url] = time.time() + CustomOpenAIProvider._BASE_URL_COOLDOWN_S
        # Reorder in-memory list — pop + append at tail.
        try:
            self._base_urls.remove(url)
            self._base_urls.append(url)
        except ValueError:
            pass
        logger.warning({
            "event": "custom_provider_base_url_demoted",
            "provider": self.name,
            "url": url,
            "cooldown_s": CustomOpenAIProvider._BASE_URL_COOLDOWN_S,
        })

    def _get_keys(self) -> list[str]:
        """Get all configured API keys (supports multi-key).
        Auto-injects JWT token from account pool if API key is a placeholder.
        """
        single = str(self.cfg.get("api_key") or "").strip()
        multi = self.cfg.get("api_keys") or []
        if not isinstance(multi, list):
            multi = []
        keys = [k.strip() for k in multi if k.strip()]
        if single and single not in keys:
            keys.insert(0, single)

        # Auto-use JWT tokens from account pool if only placeholder key is configured
        if keys == ["sk-auto-created"] or keys == ["sk-placeholder"]:
            try:
                from services.account_service import account_service
                jwt_keys = []
                for acc in account_service.list_accounts():
                    token = (acc.get("access_token") or "").strip()
                    if token.startswith("eyJ") and acc.get("status") == "active":
                        jwt_keys.append(token)
                if jwt_keys:
                    from utils.log import logger
                    logger.info({"event": "openai_auto_key", "key_count": len(jwt_keys),
                                  "emails": [a.get("email") for a in account_service.list_accounts()
                                            if a.get("status") == "active" and (a.get("access_token") or "").startswith("eyJ")]})
                    keys = jwt_keys
            except Exception:
                pass

        return keys

    @property
    def api_key(self) -> str:
        keys = self._get_keys()
        if not keys:
            return ""
        now = time.time()
        for _ in range(len(keys)):
            key = keys[self._key_index % len(keys)]
            self._key_index += 1
            if self._rate_limited.get(key, 0) < now:
                return key
        return min(keys, key=lambda k: self._rate_limited.get(k, 0))

    @property
    def is_available(self) -> bool:
        key = self.api_key
        if not self.base_url or not key:
            return False
        try:
            resp = requests.get(
                f"{self.base_url}{self._models_path}",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            try:
                return resp.status_code == 200
            finally:
                resp.close()
        except Exception:
            return False

    _KIEM_TRA_TIMEOUT_S = 5

    def kiem_tra(self) -> dict[str, Any]:
        """Hỏi từng URL của provider: còn sống không, chậm bao nhiêu, mấy model.

        Vì sao cần: `is_available` chỉ trả một bool và chỉ thử URL đầu, còn
        `list_models` nuốt lỗi — một URL chết trong bể nhiều URL, hay một tiền
        tố bị provider có sẵn che mất, đều không ai thấy cho tới khi người
        dùng hỏi vì sao model biến mất.

        CHỈ ĐỌC: không gọi `_demote_base_url`, không chạm `_base_url_cooldown`
        — hạ hạng ở đây là đổi đường đi của request thật chỉ vì có người mở
        trang kiểm tra. Kết quả đi thẳng ra giao diện nên không bao giờ mang
        khoá API hay nội dung lỗi thô (lỗi mạng có thể kèm header).
        """
        ket_qua: list[dict[str, Any]] = []
        key = self.api_key if self._get_keys() else ""
        for url in self._base_urls:
            muc: dict[str, Any] = {"url": url, "ok": False, "do_tre_ms": None,
                                   "so_model": 0, "loi": ""}
            ket_qua.append(muc)
            if not key:
                muc["loi"] = "chưa có khoá API"
                continue
            # Đường /models tính theo TỪNG URL: `_models_path` dựng theo URL đầu,
            # mà bể có thể trộn URL có và không có /v1.
            duong = ("/models" if self._api_style == "deepseek" or url.endswith("/v1")
                     else "/v1/models")
            bat_dau = time.monotonic()
            try:
                resp = requests.get(
                    f"{url}{duong}",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=self._KIEM_TRA_TIMEOUT_S,
                )
            except Exception as exc:
                muc["do_tre_ms"] = int((time.monotonic() - bat_dau) * 1000)
                muc["loi"] = f"lỗi mạng: {type(exc).__name__}"
                continue
            muc["do_tre_ms"] = int((time.monotonic() - bat_dau) * 1000)
            try:
                if resp.status_code != 200:
                    muc["loi"] = f"HTTP {resp.status_code}"
                    continue
                try:
                    data = resp.json().get("data")
                except Exception:
                    data = None
                if not isinstance(data, list):
                    # 200 mà không phải danh sách model chuẩn OpenAI — thường là
                    # trang đăng nhập hay proxy chặn, không phải module thật.
                    muc["loi"] = "trả 200 nhưng không phải danh sách model OpenAI"
                    continue
                muc["ok"] = True
                muc["so_model"] = len(data)
            finally:
                resp.close()

        bi_che_boi = ""
        prefix = str(self.cfg.get("prefix") or "").strip()
        if prefix:
            # Hỏi đúng bộ định tuyến thật thay vì đoán: nó trả gì cho
            # "<prefix>/x" thì request thật đi đường đó. Nhập muộn vì
            # backend_router nhập lại mô-đun này trong resolve_model.
            from services.backend_router import BackendRouter

            provider, _ = BackendRouter.resolve_model(f"{prefix}/x")
            # "chatgpt" là đường rơi mặc định khi không ai nhận — provider này
            # chưa được bật chứ không phải bị che.
            if provider not in (f"custom:{prefix}", "chatgpt"):
                bi_che_boi = provider
        return {"ok": any(m["ok"] for m in ket_qua), "urls": ket_qua,
                "bi_che_boi": bi_che_boi}

    def chat_completions(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        _attempted_keys: set[str] | None = None,
        _attempted_bases: set[str] | None = None,
        **kwargs,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Forward chat request to custom API endpoint."""
        if not self.base_url:
            raise RuntimeError(f"Custom provider '{self.name}' has no base URL configured")
        if not self._get_keys():
            raise RuntimeError(f"Custom provider '{self.name}' has no API key configured")

        if str(self.cfg.get("prefix") or "") in _PREFIX_MAY_NHA:
            messages = _tach_khung_anh(messages)

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        # Pass through common extra params
        for key in ("top_p", "frequency_penalty", "presence_penalty", "seed", "response_format"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]

        # Refresh `self.base_url` each call so multi-endpoint providers
        # rotate as endpoints fail. Single-endpoint providers always return
        # the same URL.
        if len(self._base_urls) > 1:
            self.base_url = self._next_healthy_base_url()

        # api_key là property round-robin: chỉ được đọc MỘT lần trên mỗi lượt
        # HTTP. Đọc lại ở headers rồi ở nhánh 429 sẽ gửi bằng key B nhưng đánh
        # dấu cooldown key A — pool vì vậy xoay sai và vẫn nã key đang bị limit.
        selected_key = self.api_key
        if not selected_key:
            raise RuntimeError(f"Custom provider '{self.name}' has no usable API key configured")
        headers = {
            "Authorization": f"Bearer {selected_key}",
            "Content-Type": "application/json",
        }
        if stream:
            headers["Accept"] = "text/event-stream"

        logger.info({
            "event": "custom_provider_request",
            "provider": self.name,
            "base_url": self.base_url,
            "model": model,
            "stream": stream,
        })

        try:
            resp = requests.post(
                f"{self.base_url}{self._chat_path}",
                headers=headers,
                json=body,
                timeout=300,
                stream=stream,
            )

            if resp.status_code == 429:
                # Rate limited — mark key and retry with next
                try:
                    resp.close()
                except Exception:
                    pass
                self._rate_limited[selected_key] = time.time() + 60
                # Bộ key đã thử phải đi xuyên qua lời gọi retry, không lưu vào
                # instance (instance có thể dùng lại cho request kế tiếp).
                attempted = _attempted_keys if _attempted_keys is not None else set()
                attempted.add(selected_key)
                if len(attempted) < len(self._get_keys()):
                    return self.chat_completions(
                        messages=messages, model=model, stream=stream,
                        temperature=temperature, max_tokens=max_tokens,
                        tools=tools, tool_choice=tool_choice,
                        _attempted_keys=attempted,
                        _attempted_bases=_attempted_bases, **kwargs,
                    )
                # All keys exhausted on this base_url — demote it and retry
                # on the next endpoint in the pool (if any).
                attempted_bases = _attempted_bases if _attempted_bases is not None else set()
                attempted_bases.add(self.base_url)
                if len(self._base_urls) > len(attempted_bases):
                    self._demote_base_url(self.base_url)
                    self.base_url = self._next_healthy_base_url()
                    return self.chat_completions(
                        messages=messages, model=model, stream=stream,
                        temperature=temperature, max_tokens=max_tokens,
                        tools=tools, tool_choice=tool_choice,
                        _attempted_keys=set(),
                        _attempted_bases=attempted_bases, **kwargs,
                    )
                raise RuntimeError(f"[{self.name}] All API keys rate limited")

            if resp.status_code >= 400:
                error_text = ""
                try:
                    # Try to read error body — may fail for streaming responses
                    if not stream:
                        error_text = (resp.text or "")[:500]
                    else:
                        raw = b""
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                raw += chunk if isinstance(chunk, bytes) else chunk.encode()
                                if len(raw) > 5000:
                                    break
                        error_text = raw.decode("utf-8", errors="ignore")[:500] if raw else ""
                except Exception:
                    pass
                logger.error({
                    "event": "custom_provider_error",
                    "provider": self.name,
                    "status": resp.status_code,
                    "error": error_text,
                    "model_sent": body.get("model"),
                    "msg_count": len(body.get("messages", [])),
                })
                try:
                    resp.close()
                except Exception:
                    pass
                raise RuntimeError(f"[{self.name}] Error {resp.status_code}: {error_text[:200]}")

            if stream:
                return self._stream_response(resp, model)
            else:
                return self._non_stream_response(resp, model)

        except requests.RequestsError as exc:
            # Connection error — most common when a Gemini Custom port is
            # down. Demote this base_url and try the next one in the pool.
            if len(self._base_urls) > 1:
                self._demote_base_url(self.base_url)
                self.base_url = self._next_healthy_base_url()
                if self.base_url:
                    logger.warning({
                        "event": "custom_provider_retry_next_url",
                        "provider": self.name,
                        "next_url": self.base_url,
                        "error": str(exc)[:200],
                    })
                    return self.chat_completions(
                        messages=messages, model=model, stream=stream,
                        temperature=temperature, max_tokens=max_tokens,
                        tools=tools, tool_choice=tool_choice, **kwargs,
                    )
            raise RuntimeError(f"[{self.name}] Connection failed: {exc}") from exc

    def _stream_response(self, response, model: str) -> Iterator[dict[str, Any]]:
        """Parse SSE stream → OpenAI chunks (passthrough — already OpenAI format)."""
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        sent_role = False

        try:
            try:
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8", errors="ignore") if isinstance(raw_line, bytes) else str(raw_line)
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    # Pass through OpenAI-format chunks as-is (they're already correct)
                    choices = chunk.get("choices") or []
                    for choice in choices:
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            if not sent_role:
                                sent_role = True
                                yield {
                                    "id": completion_id, "object": "chat.completion.chunk",
                                    "created": created, "model": model,
                                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                                }
                        # Yield the chunk as-is with our IDs
                        yield {
                            "id": completion_id, "object": "chat.completion.chunk",
                            "created": created, "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": delta,
                                "finish_reason": choice.get("finish_reason"),
                            }],
                        }

            except Exception as exc:
                logger.error({"event": "custom_provider_stream_error", "provider": self.name, "error": str(exc)})
                yield {
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                    "error": {"message": f"[{self.name}] stream error: {exc}", "type": "stream_error"},
                }
                return

            yield {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        finally:
            response.close()

    def _non_stream_response(self, response, model: str) -> dict[str, Any]:
        """Handle non-streaming response (passthrough)."""
        try:
            return response.json()  # already OpenAI format
        finally:
            response.close()

    def list_models(self) -> list[dict[str, Any]]:
        """Fetch available models from custom API, prefixed with provider prefix.

        If /v1/models returns empty, falls back to probing /v1/chat/completions
        with a fake model name and parsing the error message for available models.
        """
        key = self.api_key
        if not self.base_url or not key:
            return []

        prefix = str(self.cfg.get("prefix") or "").strip()
        if not prefix:
            return []

        models: list[dict[str, Any]] = []

        # Try standard models endpoint first
        try:
            resp = requests.get(
                f"{self.base_url}{self._models_path}",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
            try:
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    if isinstance(data, list) and data:
                        for item in data:
                            slug = str(item.get("id") or "").strip()
                            if slug:
                                if slug.startswith(f"{prefix}/"):
                                    display_id = slug
                                else:
                                    display_id = f"{prefix}/{slug}"
                                models.append({
                                    "id": display_id,
                                    "object": "model",
                                    "created": item.get("created", 0),
                                    "owned_by": str(item.get("owned_by") or self.name),
                                })
            finally:
                resp.close()
        except Exception:
            pass

        # Fallback: if models list is empty, probe chat endpoint to discover models
        if not models:
            try:
                import re
                resp = requests.post(
                    f"{self.base_url}{self._chat_path}",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "__discover_models__",
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                    timeout=15,
                )
                try:
                    detail = ""
                    try:
                        detail = resp.json().get("detail", "")
                    except Exception:
                        detail = resp.text[:500] if resp.text else ""

                    # Parse: "Available models: model1, model2, model3"
                    if isinstance(detail, str) and "Available models:" in detail:
                        parts = detail.split("Available models:", 1)[1].strip().rstrip(".")
                        found_models = [m.strip() for m in parts.split(",") if m.strip()]
                        for slug in found_models:
                            if slug and slug != "unspecified":
                                display_id = f"{prefix}/{slug}"
                                models.append({
                                    "id": display_id,
                                    "object": "model",
                                    "created": 0,
                                    "owned_by": self.name,
                                })
                        if models:
                            logger.info({
                                "event": "custom_provider_models_fallback",
                                "provider": self.name,
                                "count": len(models),
                            })
                finally:
                    resp.close()
            except Exception:
                pass

        return models
