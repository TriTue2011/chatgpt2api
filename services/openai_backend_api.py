import base64
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from curl_cffi import requests
from PIL import Image

from services.account_service import account_service
from services.config import config

logger = logging.getLogger(__name__)
from services.proxy_service import proxy_settings
from utils.helper import ensure_ok, iter_sse_payloads, new_uuid
from utils.log import logger
from utils.pow import build_legacy_requirements_token, build_proof_token, parse_pow_resources
from utils.turnstile import solve_turnstile_token


class InvalidAccessTokenError(RuntimeError):
    pass


@dataclass
class ChatRequirements:
    """保存一次对话请求所需的 sentinel token。"""
    token: str
    proof_token: str = ""
    turnstile_token: str = ""
    so_token: str = ""
    raw_finalize: Optional[Dict[str, Any]] = None


DEFAULT_CLIENT_VERSION = "prod-be885abbfcfe7b1f511e88b3003d9ee44757fbad"
DEFAULT_CLIENT_BUILD_NUMBER = "5955942"
DEFAULT_POW_SCRIPT = "https://chatgpt.com/backend-api/sentinel/sdk.js"
CODEX_IMAGE_MODEL = "codex-gpt-image-2"

# Cache the homepage-derived PoW script references across requests. A new
# OpenAIBackendAPI is built per request, so _bootstrap() otherwise GETs
# chatgpt.com's full homepage on EVERY call — a redundant round-trip whose cost
# dominates when those (free) accounts are throttled (vision went 5-8s → 15-36s).
# The refs are global to chatgpt.com and change only on their web deploys.
_BOOTSTRAP_CACHE: Dict[str, Any] = {"sources": None, "build": None, "ts": 0.0}
_BOOTSTRAP_TTL = 600  # 10 minutes


class OpenAIBackendAPI:
    """ChatGPT Web 后端封装。

    说明：
    - 传入 `access_token` 时，聊天和模型列表都会走已登录链路
      例如 `/backend-api/sentinel/chat-requirements`、`/backend-api/conversation`
    - 不传 `access_token` 时，会走未登录链路
      例如 `/backend-anon/sentinel/chat-requirements`、`/backend-anon/conversation`
    - `stream_conversation()` 是底层统一流式入口
    - 协议兼容转换放在 `services.protocol`
    """

    def __init__(self, access_token: str = "") -> None:
        """初始化后端客户端。

        参数：
        - `access_token`：可选。传入后表示使用已登录链路；不传则使用未登录链路。
        """
        self.base_url = "https://chatgpt.com"
        self.client_version = DEFAULT_CLIENT_VERSION
        self.client_build_number = DEFAULT_CLIENT_BUILD_NUMBER
        self.access_token = access_token
        self.fp = self._build_fp()
        self.user_agent = self.fp["user-agent"]
        self.device_id = self.fp["oai-device-id"]
        self.session_id = self.fp["oai-session-id"]
        self.pow_script_sources: list[str] = []
        self.pow_data_build = ""
        self.session = requests.Session(**proxy_settings.build_session_kwargs(
            impersonate=self.fp["impersonate"],
            verify=True,
        ))
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Origin": self.base_url,
            "Referer": self.base_url + "/",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Priority": "u=1, i",
            "Sec-Ch-Ua": self.fp["sec-ch-ua"],
            "Sec-Ch-Ua-Arch": '"x86"',
            "Sec-Ch-Ua-Bitness": '"64"',
            "Sec-Ch-Ua-Full-Version": '"143.0.3650.96"',
            "Sec-Ch-Ua-Full-Version-List": '"Microsoft Edge";v="143.0.3650.96", "Chromium";v="143.0.7499.147", "Not A(Brand";v="24.0.0.0"',
            "Sec-Ch-Ua-Mobile": self.fp["sec-ch-ua-mobile"],
            "Sec-Ch-Ua-Model": '""',
            "Sec-Ch-Ua-Platform": self.fp["sec-ch-ua-platform"],
            "Sec-Ch-Ua-Platform-Version": '"19.0.0"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "OAI-Device-Id": self.device_id,
            "OAI-Session-Id": self.session_id,
            "OAI-Language": "en-US",
            "OAI-Client-Version": self.client_version,
            "OAI-Client-Build-Number": self.client_build_number,
        })
        if self.access_token:
            self.session.headers["Authorization"] = f"Bearer {self.access_token}"

    def _build_fp(self) -> Dict[str, str]:
        account = account_service.get_account(self.access_token) if self.access_token else {}
        account = account if isinstance(account, dict) else {}
        raw_fp = account.get("fp")
        fp = {str(k).lower(): str(v) for k, v in raw_fp.items()} if isinstance(raw_fp, dict) else {}
        for key in (
                "user-agent",
                "impersonate",
                "oai-device-id",
                "oai-session-id",
                "sec-ch-ua",
                "sec-ch-ua-mobile",
                "sec-ch-ua-platform",
        ):
            value = str(account.get(key) or "").strip()
            if value:
                fp[key] = value
        fp.setdefault(
            "user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
        )
        # chrome110, not edge101: the edge101 curl_cffi profile negotiates an
        # HTTP/2 fingerprint that chatgpt.com now RSTs mid-stream on the image
        # endpoint ("HTTP/2 stream not closed cleanly: INTERNAL_ERROR").
        # (upstream basketikun/chatgpt2api 1b423b04)
        fp.setdefault("impersonate", "chrome110")
        fp.setdefault("oai-device-id", new_uuid())
        fp.setdefault("oai-session-id", new_uuid())
        fp.setdefault("sec-ch-ua", '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"')
        fp.setdefault("sec-ch-ua-mobile", "?0")
        fp.setdefault("sec-ch-ua-platform", '"Windows"')
        return fp

    def _headers(self, path: str, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """构造请求头，并补上 web 端要求的 target path/route。"""
        headers = dict(self.session.headers)
        headers["X-OpenAI-Target-Path"] = path
        headers["X-OpenAI-Target-Route"] = path
        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    def _extract_quota_and_restore_at(limits_progress: list[Any]) -> tuple[int, str | None, bool]:
        # For Free tier, we don't want file_upload=0 to globally mark the account as limited
        # because they can still chat. So we will only consider image_gen for the primary 'quota'
        # if available, or just keep it unknown. The individual limits are still preserved in limits_progress.
        quota = 99999
        restore_at = None
        image_quota_unknown = True
        
        for item in limits_progress:
            if not isinstance(item, dict):
                continue
            feature = item.get("feature_name")
            # Only use image_gen to determine the overall numeric "quota" for backward compatibility.
            # file_upload limits are tracked independently in the frontend.
            if feature == "image_gen":
                image_quota_unknown = False
                rem = int(item.get("remaining") or 0)
                reset = str(item.get("reset_after") or "") or None
                if rem < quota:
                    quota = rem
                    restore_at = reset
            elif feature == "file_upload":
                # file_upload is tracked but we don't let it brick the whole account's "quota"
                pass
                    
        if quota == 99999:
            return 0, None, True
        return quota, restore_at, image_quota_unknown

    def _get_me(self) -> Dict[str, Any]:
        path = "/backend-api/me"
        response = self.session.get(self.base_url + path, headers=self._headers(path), timeout=20)
        if response.status_code != 200:
            if response.status_code == 401:
                raise InvalidAccessTokenError(f"{path} failed: HTTP {response.status_code}")
            raise RuntimeError(f"{path} failed: HTTP {response.status_code}")
        return response.json()

    def _get_conversation_init(self) -> Dict[str, Any]:
        path = "/backend-api/conversation/init"
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Content-Type": "application/json"}),
            json={
                "gizmo_id": None,
                "requested_default_model": None,
                "conversation_id": None,
                "timezone_offset_min": -480,
            },
            timeout=20,
        )
        if response.status_code != 200:
            if response.status_code == 401:
                raise InvalidAccessTokenError(f"{path} failed: HTTP {response.status_code}")
            raise RuntimeError(f"{path} failed: HTTP {response.status_code}")
        return response.json()

    def _get_default_account(self) -> Dict[str, Any]:
        route = "/backend-api/accounts/check/v4-2023-04-27"
        response = self.session.get(self.base_url + route + "?timezone_offset_min=-480", headers=self._headers(route),
                                    timeout=20)
        if response.status_code != 200:
            if response.status_code == 401:
                raise InvalidAccessTokenError(f"{route} failed: HTTP {response.status_code}")
            raise RuntimeError(f"/backend-api/accounts/check failed: HTTP {response.status_code}")
        payload = response.json()
        logger.debug({"event": "backend_user_info_account_payload", "account_payload": payload})
        return ((payload.get("accounts") or {}).get("default") or {}).get("account") or {}

    def get_user_info(self) -> Dict[str, Any]:
        """获取当前 token 的账号信息。"""
        if not self.access_token:
            raise RuntimeError("access_token is required")
        logger.debug({"event": "backend_user_info_start"})
        with ThreadPoolExecutor(max_workers=3) as executor:
            me_future = executor.submit(self._get_me)
            init_future = executor.submit(self._get_conversation_init)
            account_future = executor.submit(self._get_default_account)
            me_payload, init_payload, default_account = me_future.result(), init_future.result(), account_future.result()

        plan_type = str(default_account.get("plan_type") or "free")

        limits_progress = init_payload.get("limits_progress")
        limits_progress = limits_progress if isinstance(limits_progress, list) else []
        quota, restore_at, image_quota_unknown = self._extract_quota_and_restore_at(limits_progress)
        result = {
            "email": me_payload.get("email"),
            "user_id": me_payload.get("id"),
            "plan": plan_type,
            "quota": quota,
            "image_quota_unknown": image_quota_unknown,
            "limits_progress": limits_progress,
            "default_model_slug": init_payload.get("default_model_slug"),
            "restore_at": restore_at,
            "status": "active" if plan_type.lower() == "free" else ("limited" if quota == 0 else "active"),
        }
        logger.debug({
            "event": "backend_user_info_result",
            "email": result.get("email"),
            "user_id": result.get("user_id"),
            "type": result.get("type"),
            "quota": result.get("quota"),
            "image_quota_unknown": result.get("image_quota_unknown"),
            "default_model_slug": result.get("default_model_slug"),
            "restore_at": result.get("restore_at"),
            "status": result.get("status"),
        })
        return result

    def _bootstrap_headers(self) -> Dict[str, str]:
        """构造首页预热请求头。"""
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Sec-Ch-Ua": self.session.headers["Sec-Ch-Ua"],
            "Sec-Ch-Ua-Mobile": self.session.headers["Sec-Ch-Ua-Mobile"],
            "Sec-Ch-Ua-Platform": self.session.headers["Sec-Ch-Ua-Platform"],
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

    def _build_requirements(self, data: Dict[str, Any], source_p: str = "") -> ChatRequirements:
        """把 sentinel 响应整理成后续对话需要的 token 集合。"""
        if (data.get("arkose") or {}).get("required"):
            # Arkose gắn theo account/cookie — caller (chatgpt_free) sẽ xoay
            # account khác; combo tự chuyển provider kế tiếp nếu hết account.
            raise RuntimeError(
                "chatgpt.com yêu cầu Arkose token cho account này (chưa hỗ trợ) — "
                "bỏ qua, thử account/provider kế tiếp")

        proof_token = ""
        proof_info = data.get("proofofwork") or {}
        if proof_info.get("required"):
            proof_token = build_proof_token(
                proof_info.get("seed", ""),
                proof_info.get("difficulty", ""),
                self.user_agent,
                script_sources=self.pow_script_sources,
                data_build=self.pow_data_build,
            )

        turnstile_token = ""
        turnstile_info = data.get("turnstile") or {}
        if turnstile_info.get("required") and turnstile_info.get("dx"):
            turnstile_token = solve_turnstile_token(turnstile_info["dx"], source_p) or ""

        return ChatRequirements(
            token=data.get("token", ""),
            proof_token=proof_token,
            turnstile_token=turnstile_token,
            so_token=data.get("so_token", ""),
            raw_finalize=data,
        )

    def _conversation_headers(self, path: str, requirements: ChatRequirements) -> Dict[str, str]:
        """根据当前 requirements 构造对话 SSE 请求头。"""
        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "OpenAI-Sentinel-Chat-Requirements-Token": requirements.token,
        }
        if requirements.proof_token:
            headers["OpenAI-Sentinel-Proof-Token"] = requirements.proof_token
        if requirements.turnstile_token:
            headers["OpenAI-Sentinel-Turnstile-Token"] = requirements.turnstile_token
        if requirements.so_token:
            headers["OpenAI-Sentinel-SO-Token"] = requirements.so_token
        return self._headers(path, headers)

    def _api_messages_to_conversation_messages(self, messages: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """把标准 chat messages 转成 web conversation 所需的 messages。"""
        from services.protocol.conversation import _file_upload_store, _FILE_UPLOAD_MARKER

        conversation_messages = []

        # chatgpt.com native conversation API only supports a SINGLE system message.
        # When multiple system messages are present (e.g. HA instructions + search results),
        # merge them into one combined system message placed first.
        system_parts = [str(item.get("content", "")) for item in messages if item.get("role") == "system"]
        non_system = [item for item in messages if item.get("role") != "system"]
        if system_parts:
            merged_system = "\n\n---\n\n".join(p for p in system_parts if p.strip())
            if merged_system.strip():
                conversation_messages.append({
                    "id": new_uuid(),
                    "author": {"role": "system"},
                    "content": {"content_type": "text", "parts": [merged_system]},
                })
        messages = non_system

        for item in messages:
            role = item.get("role", "user")
            content = item.get("content", "")
            
            if role == "tool":
                role = "user"
                tool_name = item.get("name", "UnknownTool")
                content = f"[KẾT QUẢ TỪ HỆ THỐNG - TOOL {tool_name}]:\n{content}"
            elif role == "assistant":
                tool_calls = item.get("tool_calls") or []
                for tc in tool_calls:
                    if tc.get("type") == "function":
                        name = tc.get("function", {}).get("name", "")
                        args = tc.get("function", {}).get("arguments", "")
                        content = str(content) + f"\n[System Log: You executed tool {name} with args {args}]\n"
                if not str(content).strip():
                    continue

            if isinstance(content, str):
                # Resolve file-upload markers: upload the preserved full text
                # and reference it via asset_pointer (1 msg quota instead of N chunks).
                if content.startswith(_FILE_UPLOAD_MARKER) and self.access_token:
                    try:
                        key = content.split("]", 1)[0].split(":", 1)[1].strip()
                        full_text = _file_upload_store.pop(key, None)
                    except (IndexError, ValueError):
                        full_text = None
                    if full_text:
                        ref = self._upload_text_file(full_text)
                        # Attach the uploaded file as metadata — ChatGPT reads
                        # text files from attachments automatically (same as
                        # uploading a .txt file in the web UI).
                        conversation_messages.append({
                            "id": new_uuid(),
                            "author": {"role": role},
                            "content": {
                                "content_type": "text",
                                "parts": [
                                    content.split("\n...[full content uploaded as file]...", 1)[0]
                                    + "\n\n[Toàn bộ context hệ thống đã được đính kèm file. "
                                    "Hãy đọc file đính kèm để có đầy đủ thông tin.]",
                                ],
                            },
                            "metadata": {
                                "attachments": [{
                                    "id": ref["file_id"],
                                    "mimeType": ref["mime_type"],
                                    "name": ref["file_name"],
                                    "size": ref["file_size"],
                                }],
                            },
                        })
                        continue
                # No marker or no access_token — normal text message
                conversation_messages.append({
                    "id": new_uuid(),
                    "author": {"role": role},
                    "content": {"content_type": "text", "parts": [content]},
                })
                continue
            if not isinstance(content, list):
                raise RuntimeError("only string or list message content is supported")
            text_parts: list[str] = []
            image_inputs: list[tuple[bytes, str]] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "")
                if part_type == "text":
                    text_parts.append(str(part.get("text") or ""))
                elif part_type == "image":
                    data = part.get("data")
                    mime = str(part.get("mime") or "image/png")
                    if isinstance(data, (bytes, bytearray)):
                        image_inputs.append((bytes(data), mime))
                elif part_type in ("image_url", "input_image"):
                    iu = part.get("image_url")
                    url = ""
                    if isinstance(iu, dict):
                        url = str(iu.get("url") or "")
                    elif isinstance(iu, str):
                        url = iu
                    if not url:
                        url = str(part.get("url") or "")
                    if not url:
                        continue
                    img_bytes: Optional[bytes] = None
                    img_mime = "image/png"
                    if url.startswith("data:"):
                        try:
                            head, payload = url.split(",", 1)
                            if head.startswith("data:") and ";" in head:
                                m = head.split(";", 1)[0][5:].strip()
                                if m:
                                    img_mime = m
                            img_bytes = base64.b64decode(payload)
                        except Exception as e:
                            logger.warning({"event": "chatgpt_image_url_decode_failed", "error": str(e)[:120]})
                            continue
                    elif url.startswith(("http://", "https://")):
                        # URL do client cung cấp → SSRF guard (net_guard).
                        try:
                            from services import net_guard
                            img_bytes = net_guard.fetch_media(url, timeout=20, max_bytes=25 * 1024 * 1024)
                            img_mime = "image/png"
                        except Exception as e:
                            logger.warning({"event": "chatgpt_image_url_download_failed", "url": url[:120], "error": str(e)[:120]})
                            continue
                    if img_bytes:
                        image_inputs.append((img_bytes, img_mime))
            if not image_inputs:
                conversation_messages.append({
                    "id": new_uuid(),
                    "author": {"role": role},
                    "content": {"content_type": "text", "parts": ["".join(text_parts)]},
                })
                continue
            if not self.access_token:
                raise RuntimeError("authenticated upstream account required for image input")
            def _prep_upload(idx: int, data: bytes, mime: str) -> tuple[str, str]:
                ext_part = mime.split("/", 1)[1].split("+")[0] if "/" in mime else "png"
                extension = "jpg" if ext_part == "jpeg" else (ext_part or "png")
                b64 = base64.b64encode(data).decode("ascii")
                return f"data:{mime};base64,{b64}", f"image_{idx}.{extension}"

            uploaded: list[Dict[str, Any]] = []
            if len(image_inputs) > 1:
                # Camera automations send a burst of frames; upload them in
                # parallel (each on its own cloned Session — curl_cffi handles
                # are not thread-safe). pool.map preserves frame order.
                def _upload_one(pair: tuple[int, tuple[bytes, str]]) -> Dict[str, Any]:
                    idx, (data, mime) = pair
                    image_b64, fname = _prep_upload(idx, data, mime)
                    sess = self._clone_session()
                    try:
                        return self._upload_image(image_b64, fname, sess=sess)
                    finally:
                        try:
                            sess.close()
                        except Exception:
                            pass
                with ThreadPoolExecutor(max_workers=min(3, len(image_inputs))) as pool:
                    uploaded = list(pool.map(_upload_one, enumerate(image_inputs, start=1)))
            else:
                for idx, (data, mime) in enumerate(image_inputs, start=1):
                    image_b64, fname = _prep_upload(idx, data, mime)
                    uploaded.append(self._upload_image(image_b64, fname))
            parts: list[Any] = []
            for ref in uploaded:
                parts.append({
                    "content_type": "image_asset_pointer",
                    "asset_pointer": f"file-service://{ref['file_id']}",
                    "width": ref["width"],
                    "height": ref["height"],
                    "size_bytes": ref["file_size"],
                })
            text = "".join(text_parts)
            if text:
                parts.append(text)
            conversation_messages.append({
                "id": new_uuid(),
                "author": {"role": role},
                "content": {"content_type": "multimodal_text", "parts": parts},
                "metadata": {
                    "attachments": [{
                        "id": ref["file_id"],
                        "mimeType": ref["mime_type"],
                        "name": ref["file_name"],
                        "size": ref["file_size"],
                        "width": ref["width"],
                        "height": ref["height"],
                    } for ref in uploaded],
                },
            })
        return conversation_messages

    def _conversation_payload(self, messages: list[Dict[str, Any]], model: str, timezone: str, tools: Optional[list[Dict[str, Any]]] = None, tool_choice: Any = None) -> Dict[str, Any]:
        """把标准 messages 构造成 web 对话请求体。"""
        payload: Dict[str, Any] = {
            "action": "next",
            "messages": self._api_messages_to_conversation_messages(messages),
            "model": model,
            "parent_message_id": new_uuid(),
            "conversation_mode": {"kind": "primary_assistant"},
            "conversation_origin": None,
            "force_paragen": False,
            "force_paragen_model_slug": "",
            "force_rate_limit": False,
            "force_use_sse": True,
            "history_and_training_disabled": True,
            "reset_rate_limits": False,
            "suggestions": [],
            "supported_encodings": [],
            "system_hints": [],
            "timezone": timezone,
            "timezone_offset_min": -480,
            "variant_purpose": "comparison_implicit",
            "websocket_request_id": new_uuid(),
            "client_contextual_info": {
                "is_dark_mode": False,
                "time_since_loaded": 120,
                "page_height": 900,
                "page_width": 1400,
                "pixel_ratio": 2,
                "screen_height": 1440,
                "screen_width": 2560,
            },
        }
        if tools:
            from services.protocol.conversation import _slim_tool_schema
            import copy
            slim_tools = []
            for t in tools:
                if "function" in t and "parameters" in t["function"]:
                    t2 = copy.deepcopy(t)
                    t2["function"]["parameters"] = _slim_tool_schema(t2["function"]["parameters"])
                    slim_tools.append(t2)
                else:
                    slim_tools.append(t)
            payload["tools"] = slim_tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

    def _image_model_slug(self, model: str) -> str:
        """把标准图片模型名映射到底层 model slug。"""
        model = str(model or "").strip()
        if not model:
            return "auto"
        if model == "gpt-image-2":
            return "gpt-5-3"
        if model == CODEX_IMAGE_MODEL:
            return model
        return "auto"

    def _image_headers(self, path: str, requirements: ChatRequirements, conduit_token: str = "", accept: str = "*/*") -> \
            Dict[str, str]:
        """构造图片链路请求头。"""
        headers = {
            "Content-Type": "application/json",
            "Accept": accept,
            "OpenAI-Sentinel-Chat-Requirements-Token": requirements.token,
        }
        if requirements.proof_token:
            headers["OpenAI-Sentinel-Proof-Token"] = requirements.proof_token
        if conduit_token:
            headers["X-Conduit-Token"] = conduit_token
        if accept == "text/event-stream":
            headers["X-Oai-Turn-Trace-Id"] = new_uuid()
        return self._headers(path, headers)

    def _prepare_image_conversation(self, prompt: str, requirements: ChatRequirements, model: str) -> str:
        """为图片生成准备 conduit token。"""
        path = "/backend-api/f/conversation/prepare"
        payload = {
            "action": "next",
            "fork_from_shared_post": False,
            "parent_message_id": new_uuid(),
            "model": self._image_model_slug(model),
            "client_prepare_state": "success",
            "timezone_offset_min": -480,
            "timezone": "Asia/Shanghai",
            "conversation_mode": {"kind": "primary_assistant"},
            "system_hints": ["picture_v2"],
            "partial_query": {
                "id": new_uuid(),
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [prompt]},
            },
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": {"app_name": "chatgpt.com"},
        }
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements),
            json=payload,
            timeout=60,
        )
        ensure_ok(response, path)
        return response.json().get("conduit_token", "")

    def _decode_image_base64(self, image: str) -> bytes:
        """把 base64 图片字符串或本地路径解码成二进制。"""
        if (
                image
                and len(image) < 512
                and not image.startswith("data:")
                and "\n" not in image
                and "\r" not in image
        ):
            file_path = Path(os.path.expanduser(image))
            if file_path.exists() and file_path.is_file():
                return file_path.read_bytes()
        payload = image.split(",", 1)[1] if image.startswith("data:") and "," in image else image
        return base64.b64decode(payload)

    def _clone_session(self):
        """New Session with this client's fingerprint/headers/cookies.

        curl_cffi Sessions are NOT safe for concurrent use from multiple
        threads (single curl handle), so parallel uploads each get a clone.
        """
        s = requests.Session(**proxy_settings.build_session_kwargs(
            impersonate=self.fp["impersonate"],
            verify=True,
        ))
        s.headers.update(dict(self.session.headers))
        try:
            for c in self.session.cookies.jar:
                s.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
        except Exception:
            try:
                s.cookies.update(self.session.cookies)
            except Exception:
                pass
        return s

    def _upload_image(self, image: str, file_name: str = "image.png", sess=None) -> Dict[str, Any]:
        """上传一张 base64 图片，返回底层文件元数据。"""
        s = sess or self.session
        data = self._decode_image_base64(image)
        if (
                image
                and len(image) < 512
                and not image.startswith("data:")
                and "\n" not in image
                and "\r" not in image
        ):
            candidate_path = Path(os.path.expanduser(image))
            if candidate_path.exists() and candidate_path.is_file():
                file_name = candidate_path.name
        image = Image.open(BytesIO(data))
        width, height = image.size
        mime_type = Image.MIME.get(image.format, "image/png")
        # Speed: cap the longest side before upload. Camera/phone frames are often
        # 1920–4000px; OpenAI vision processes images in 512px tiles, so shrinking
        # means far fewer tiles → much faster analysis, plus a smaller/faster upload.
        # 1024 is plenty for person-detection / general description; tune via config
        # key "chatgpt_vision_max_dim" (set 0 to disable).
        try:
            max_dim = int(config.data.get("chatgpt_vision_max_dim", 896) or 0)
        except Exception:
            max_dim = 896
        if max_dim and max(width, height) > max_dim:
            scale = max_dim / float(max(width, height))
            new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
            resized = image.convert("RGB") if image.mode not in ("RGB", "L") else image
            resized = resized.resize(new_size, Image.LANCZOS)
            buf = BytesIO()
            resized.save(buf, format="JPEG", quality=85)
            new_data = buf.getvalue()
            logger.info({"event": "chatgpt_image_downscaled", "from": [width, height],
                         "to": list(new_size), "bytes": [len(data), len(new_data)]})
            data, (width, height) = new_data, new_size
            mime_type = "image/jpeg"
            if "." in file_name:
                file_name = file_name.rsplit(".", 1)[0] + ".jpg"
        path = "/backend-api/files"
        response = s.post(
            self.base_url + path,
            headers=self._headers(path, {"Content-Type": "application/json", "Accept": "application/json"}),
            json={"file_name": file_name, "file_size": len(data), "use_case": "multimodal", "width": width,
                  "height": height},
            timeout=60,
        )
        ensure_ok(response, path)
        upload_meta = response.json()
        response = s.put(
            upload_meta["upload_url"],
            headers={
                "Content-Type": mime_type,
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": "2020-04-08",
                "Origin": self.base_url,
                "Referer": self.base_url + "/",
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.8",
            },
            data=data,
            timeout=120,
        )
        ensure_ok(response, "image_upload")
        path = f"/backend-api/files/{upload_meta['file_id']}/uploaded"
        # chatgpt.com occasionally 500s the finalize right after the blob PUT
        # (storage sync race) — retry briefly instead of failing the request.
        for attempt in range(3):
            response = s.post(
                self.base_url + path,
                headers=self._headers(path, {"Content-Type": "application/json", "Accept": "application/json"}),
                data="{}",
                timeout=60,
            )
            if response.status_code < 500 or attempt == 2:
                break
            logger.warning({"event": "chatgpt_file_finalize_retry",
                            "status": response.status_code, "attempt": attempt})
            time.sleep(0.75 * (attempt + 1))
        ensure_ok(response, path)
        return {
            "file_id": upload_meta["file_id"],
            "file_name": file_name,
            "file_size": len(data),
            "mime_type": mime_type,
            "width": width,
            "height": height,
        }

    def _upload_text_file(self, content: str, file_name: str = "context.txt") -> Dict[str, Any]:
        """Upload text content as a .txt file to ChatGPT's file storage.

        Mirrors _upload_image() but for text/plain — same /backend-api/files
        endpoint, same multipart flow, no image parsing needed.
        """
        data = content.encode("utf-8")
        path = "/backend-api/files"
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Content-Type": "application/json", "Accept": "application/json"}),
            json={"file_name": file_name, "file_size": len(data), "use_case": "multimodal"},
            timeout=60,
        )
        ensure_ok(response, path)
        upload_meta = response.json()
        time.sleep(0.5)
        response = self.session.put(
            upload_meta["upload_url"],
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": "2020-04-08",
                "Origin": self.base_url,
                "Referer": self.base_url + "/",
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.8",
            },
            data=data,
            timeout=120,
        )
        ensure_ok(response, "text_upload")
        path = f"/backend-api/files/{upload_meta['file_id']}/uploaded"
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Content-Type": "application/json", "Accept": "application/json"}),
            data="{}",
            timeout=60,
        )
        ensure_ok(response, path)
        return {
            "file_id": upload_meta["file_id"],
            "file_name": file_name,
            "file_size": len(data),
            "mime_type": "text/plain",
        }

    def _start_image_generation(self, prompt: str, requirements: ChatRequirements, conduit_token: str, model: str,
                                references: Optional[list[Dict[str, Any]]] = None) -> requests.Response:
        """启动图片生成或编辑的 SSE 请求。"""
        references = references or []
        # Explicit "@Tạo hình ảnh" ecosystem mention (picture_v2) — free-tier
        # ChatGPT will NOT auto-invoke DALL·E from system_hints alone (turn
        # completes with tool_invoked=false). Prefixing the prompt with the
        # image-tool mention + matching custom_symbol_offsets forces the image
        # tool, exactly like the web UI's "@Tạo hình ảnh" chip does.
        _MENTION = "@Tạo hình ảnh"
        prompt_mention = f"{_MENTION}{prompt}"
        offsets = [{"id": "picture_v2", "symbol": "ecosystemMention",
                    "startIndex": 0, "endIndex": len(_MENTION)}]
        parts = [{
            "content_type": "image_asset_pointer",
            "asset_pointer": f"file-service://{item['file_id']}",
            "width": item["width"],
            "height": item["height"],
            "size_bytes": item["file_size"],
        } for item in references]
        parts.append(prompt_mention)
        content = {"content_type": "multimodal_text", "parts": parts} if references else {"content_type": "text",
                                                                                          "parts": [prompt_mention]}
        metadata = {
            "developer_mode_connector_ids": [],
            "selected_github_repos": [],
            "selected_all_github_repos": False,
            "system_hints": ["picture_v2"],
            "serialization_metadata": {"custom_symbol_offsets": offsets},
        }
        if references:
            metadata["attachments"] = [{
                "id": item["file_id"],
                "mimeType": item["mime_type"],
                "name": item["file_name"],
                "size": item["file_size"],
                "width": item["width"],
                "height": item["height"],
            } for item in references]
        payload = {
            "action": "next",
            "messages": [{
                "id": new_uuid(),
                "author": {"role": "user"},
                "create_time": time.time(),
                "content": content,
                "metadata": metadata,
            }],
            "parent_message_id": new_uuid(),
            "model": self._image_model_slug(model),
            "client_prepare_state": "sent",
            "timezone_offset_min": -480,
            "timezone": "Asia/Shanghai",
            "conversation_mode": {"kind": "primary_assistant"},
            "enable_message_followups": True,
            "system_hints": ["picture_v2"],
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": {
                "is_dark_mode": False,
                "time_since_loaded": 1200,
                "page_height": 1072,
                "page_width": 1724,
                "pixel_ratio": 1.2,
                "screen_height": 1440,
                "screen_width": 2560,
                "app_name": "chatgpt.com",
            },
            "paragen_cot_summary_display_override": "allow",
            "force_parallel_switch": "auto",
        }
        path = "/backend-api/f/conversation"
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements, conduit_token, "text/event-stream"),
            json=payload,
            timeout=300,
            stream=True,
        )
        ensure_ok(response, path)
        return response

    def _get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """获取完整 conversation 详情。"""
        path = f"/backend-api/conversation/{conversation_id}"
        response = self.session.get(self.base_url + path, headers=self._headers(path, {"Accept": "application/json"}),
                                    timeout=60)
        ensure_ok(response, path)
        return response.json()

    def _extract_image_tool_records(self, data: Dict[str, Any]) -> list[Dict[str, Any]]:
        """从 conversation 明细里提取图片工具输出记录。"""
        mapping = data.get("mapping") or {}
        file_pat = re.compile(r"file-service://([A-Za-z0-9_-]+)")
        sed_pat = re.compile(r"sediment://([A-Za-z0-9_-]+)")
        records = []
        for message_id, node in mapping.items():
            message = (node or {}).get("message") or {}
            author = message.get("author") or {}
            metadata = message.get("metadata") or {}
            content = message.get("content") or {}
            if author.get("role") != "tool":
                continue
            if metadata.get("async_task_type") != "image_gen":
                continue
            if content.get("content_type") != "multimodal_text":
                continue
            file_ids, sediment_ids = [], []
            for part in content.get("parts") or []:
                text = (part.get("asset_pointer") or "") if isinstance(part, dict) else (
                    part if isinstance(part, str) else "")
                for hit in file_pat.findall(text):
                    if hit not in file_ids:
                        file_ids.append(hit)
                for hit in sed_pat.findall(text):
                    if hit not in sediment_ids:
                        sediment_ids.append(hit)
            records.append(
                {"message_id": message_id, "create_time": message.get("create_time") or 0, "file_ids": file_ids,
                 "sediment_ids": sediment_ids})
        return sorted(records, key=lambda item: item["create_time"])

    def _poll_image_results(self, conversation_id: str, timeout_secs: float = 120.0) -> tuple[list[str], list[str]]:
        """轮询 conversation，直到拿到图片文件 id 或超时。"""
        start = time.time()
        attempt = 0
        logger.info({"event": "image_poll_start", "conversation_id": conversation_id, "timeout_secs": timeout_secs})
        while time.time() - start < timeout_secs:
            attempt += 1
            conversation = self._get_conversation(conversation_id)
            file_ids, sediment_ids = [], []
            for record in self._extract_image_tool_records(conversation):
                for file_id in record["file_ids"]:
                    if file_id not in file_ids:
                        file_ids.append(file_id)
                for sediment_id in record["sediment_ids"]:
                    if sediment_id not in sediment_ids:
                        sediment_ids.append(sediment_id)
            logger.debug({"event": "image_poll_check", "conversation_id": conversation_id, "attempt": attempt,
                          "file_ids": file_ids, "sediment_ids": sediment_ids})
            if file_ids:
                logger.info({"event": "image_poll_hit", "conversation_id": conversation_id, "file_ids": file_ids,
                             "sediment_ids": sediment_ids})
                return file_ids, sediment_ids
            if sediment_ids:
                logger.info({"event": "image_poll_hit", "conversation_id": conversation_id, "file_ids": [],
                             "sediment_ids": sediment_ids})
                return [], sediment_ids
            logger.debug({"event": "image_poll_wait", "conversation_id": conversation_id,
                          "elapsed_secs": round(time.time() - start, 1)})
            time.sleep(4)
        logger.info({"event": "image_poll_timeout", "conversation_id": conversation_id, "timeout_secs": timeout_secs})
        return [], []

    def _get_file_download_url(self, file_id: str) -> str:
        """获取文件下载地址。"""
        path = f"/backend-api/files/{file_id}/download"
        response = self.session.get(self.base_url + path, headers=self._headers(path, {"Accept": "application/json"}),
                                    timeout=60)
        ensure_ok(response, path)
        data = response.json()
        return data.get("download_url") or data.get("url") or ""

    def _get_attachment_download_url(self, conversation_id: str, attachment_id: str) -> str:
        """通过 conversation 附件接口获取下载地址。"""
        path = f"/backend-api/conversation/{conversation_id}/attachment/{attachment_id}/download"
        response = self.session.get(self.base_url + path, headers=self._headers(path, {"Accept": "application/json"}),
                                    timeout=60)
        ensure_ok(response, path)
        data = response.json()
        return data.get("download_url") or data.get("url") or ""

    def _resolve_image_urls(self, conversation_id: str, file_ids: list[str], sediment_ids: list[str]) -> list[str]:
        """把图片结果 id 解析成可下载 URL。"""
        urls = []
        skip_patterns = {"file_upload"}
        for file_id in file_ids:
            if file_id in skip_patterns:
                logger.debug({
                    "event": "image_file_id_skipped",
                    "source": "file",
                    "conversation_id": conversation_id,
                    "id": file_id,
                })
                continue
            try:
                url = self._get_file_download_url(file_id)
            except Exception as exc:
                logger.debug({
                    "event": "image_download_url_failed",
                    "source": "file",
                    "conversation_id": conversation_id,
                    "id": file_id,
                    "error": repr(exc),
                })
                continue
            if url:
                urls.append(url)
            else:
                logger.debug({
                    "event": "image_download_url_empty",
                    "source": "file",
                    "conversation_id": conversation_id,
                    "id": file_id,
                })
        if urls or not conversation_id:
            logger.debug({
                "event": "image_urls_resolved",
                "conversation_id": conversation_id,
                "file_ids": file_ids,
                "sediment_ids": sediment_ids,
                "urls": urls,
            })
            return urls
        for sediment_id in sediment_ids:
            try:
                url = self._get_attachment_download_url(conversation_id, sediment_id)
            except Exception as exc:
                logger.debug({
                    "event": "image_download_url_failed",
                    "source": "sediment",
                    "conversation_id": conversation_id,
                    "id": sediment_id,
                    "error": repr(exc),
                })
                continue
            if url:
                urls.append(url)
            else:
                logger.debug({
                    "event": "image_download_url_empty",
                    "source": "sediment",
                    "conversation_id": conversation_id,
                    "id": sediment_id,
                })
        logger.debug({
            "event": "image_urls_resolved",
            "conversation_id": conversation_id,
            "file_ids": file_ids,
            "sediment_ids": sediment_ids,
            "urls": urls,
        })
        return urls

    def resolve_conversation_image_urls(
            self,
            conversation_id: str,
            file_ids: list[str],
            sediment_ids: list[str],
            poll: bool = True,
    ) -> list[str]:
        file_ids = [item for item in file_ids if item != "file_upload"]
        sediment_ids = list(sediment_ids)
        if poll and conversation_id and not file_ids and not sediment_ids:
            logger.info({"event": "image_resolve_poll_needed", "conversation_id": conversation_id})
            polled_file_ids, polled_sediment_ids = self._poll_image_results(conversation_id,
                                                                            config.image_poll_timeout_secs)
            file_ids.extend(item for item in polled_file_ids if item and item not in file_ids)
            sediment_ids.extend(item for item in polled_sediment_ids if item and item not in sediment_ids)
        return self._resolve_image_urls(conversation_id, file_ids, sediment_ids)

    def download_image_bytes(self, urls: list[str]) -> list[bytes]:
        images = []
        for url in urls:
            response = self.session.get(url, timeout=120)
            ensure_ok(response, "image_download")
            images.append(response.content)
        return images

    def iter_codex_image_response_events(
        self, prompt: str, images: list | None = None, size: str | None = None, quality: str = "auto"
    ):
        """Tạo/sửa ảnh qua Codex OAuth: chatgpt.com/backend-api/codex/responses + tool
        image_generation (gpt-image-2). Có `images` (base64) → đính kèm input_image để
        edit ảnh tham chiếu. Yield từng SSE event JSON đã parse."""
        path = "/backend-api/codex/responses"
        content: list = [{"type": "input_text", "text": prompt}]
        for _img in (images or []):
            _s = str(_img).strip()
            if not _s:
                continue
            content.append({
                "type": "input_image",
                "image_url": _s if _s.startswith("data:") else f"data:image/png;base64,{_s}",
            })
        payload = {
            "model": "gpt-5.5",
            "instructions": "",
            "store": False,
            "input": [{"role": "user", "content": content}],
            "tools": [{
                "type": "image_generation",
                "model": "gpt-image-2",
                "action": "generate",
                "size": str(size or "1024x1024"),
                "quality": str(quality or "auto"),
                "output_format": "png",
            }],
            "stream": True,
        }
        url = "https://chatgpt.com" + path
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "User-Agent": "codex-cli/1.0.18 (Windows; x64)",
            "originator": "codex-cli",
        }
        response = self.session.post(
            url=url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=120.0,
        )
        if response.status_code >= 400:
            logger.error({"event": "codex_image_400", "body": response.text})
        response.raise_for_status()
        import json
        for line in response.iter_lines():
            line_str = line.decode("utf-8") if isinstance(line, bytes) else str(line)
            line_str = line_str.strip()
            if not line_str or not line_str.startswith("data: "):
                continue
            p = line_str[6:]
            if p == "[DONE]":
                break
            try:
                yield json.loads(p)
            except Exception:
                pass

    def stream_conversation(
            self,
            messages: Optional[list[Dict[str, Any]]] = None,
            model: str = "auto",
            prompt: str = "",
            images: Optional[list[str]] = None,
            system_hints: Optional[list[str]] = None,
            tools: Optional[list[Dict[str, Any]]] = None,
            tool_choice: Any = None,
    ) -> Iterator[str]:
        system_hints = system_hints or []
        if "picture_v2" in system_hints:
            yield from self._stream_picture_conversation(prompt, model, images or [])
            return

        normalized = messages or [{"role": "user", "content": prompt}]
        self._bootstrap()
        requirements = self._get_chat_requirements()
        path, timezone = self._chat_target()
        payload = self._conversation_payload(normalized, model, timezone, tools=tools, tool_choice=tool_choice)
        # Vision safety check: if the inbound messages carried image parts
        # but the outbound payload has no multimodal_text content, the
        # truncation/normalization pipeline silently dropped the image.
        # Surface that as a warning instead of letting the model reply
        # with a generic greeting (regression of conversation.py
        # `_truncate_messages` bytes-size bug — see that function's
        # docstring for context).
        try:
            inbound_has_image = any(
                isinstance(m, dict) and isinstance(m.get("content"), list)
                and any(
                    isinstance(p, dict) and p.get("type") in ("image", "image_url", "input_image")
                    for p in m["content"]
                )
                for m in normalized
            )
            outbound_has_image = any(
                isinstance(m, dict) and isinstance(m.get("content"), dict)
                and m["content"].get("content_type") == "multimodal_text"
                for m in payload.get("messages") or []
            )
            if inbound_has_image and not outbound_has_image:
                logger.warning({
                    "event": "chatgpt_web_vision_image_dropped",
                    "model": payload.get("model"),
                    "inbound_msg_count": len(normalized),
                    "outbound_msg_count": len(payload.get("messages") or []),
                })
        except Exception:
            pass
        response = self.session.post(
            self.base_url + path,
            headers=self._conversation_headers(path, requirements),
            json=payload,
            timeout=300,
            stream=True,
        )
        ensure_ok(response, path)
        try:
            yield from iter_sse_payloads(response)
        finally:
            response.close()

    def _stream_picture_conversation(
            self,
            prompt: str,
            model: str,
            images: list[str],
    ) -> Iterator[str]:
        if not self.access_token:
            raise RuntimeError("access_token is required for image endpoints")
        references = [self._upload_image(image, f"image_{idx}.png") for idx, image in enumerate(images, start=1)]
        self._bootstrap()
        requirements = self._get_chat_requirements()
        conduit_token = self._prepare_image_conversation(prompt, requirements, model)
        response = self._start_image_generation(prompt, requirements, conduit_token, model, references)
        try:
            yield from iter_sse_payloads(response)
        finally:
            response.close()

    def _bootstrap(self) -> None:
        """预热首页，并提取 PoW 相关脚本引用。

        Cached for _BOOTSTRAP_TTL across requests — the homepage GET is otherwise
        repeated on every call (OpenAIBackendAPI is per-request) and is the
        redundant round-trip that slows chatgpt.com free requests, vision in
        particular. PoW refs are global and rarely change.
        """
        now = time.time()
        c = _BOOTSTRAP_CACHE
        if c["sources"] and (now - c["ts"]) < _BOOTSTRAP_TTL:
            self.pow_script_sources = c["sources"]
            self.pow_data_build = c["build"]
            return
        response = self.session.get(
            self.base_url + "/",
            headers=self._bootstrap_headers(),
            timeout=30,
        )
        ensure_ok(response, "bootstrap")
        self.pow_script_sources, self.pow_data_build = parse_pow_resources(response.text)
        if not self.pow_script_sources:
            self.pow_script_sources = [DEFAULT_POW_SCRIPT]
        _BOOTSTRAP_CACHE.update(
            sources=self.pow_script_sources, build=self.pow_data_build, ts=now
        )

    def _get_chat_requirements(self) -> ChatRequirements:
        """获取当前模式对话所需的 sentinel token。"""
        path = "/backend-api/sentinel/chat-requirements" if self.access_token else "/backend-anon/sentinel/chat-requirements"
        context = "auth_chat_requirements" if self.access_token else "noauth_chat_requirements"
        body = {"p": build_legacy_requirements_token(self.user_agent, self.pow_script_sources, self.pow_data_build)}
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Content-Type": "application/json"}),
            json=body,
            timeout=30,
        )
        ensure_ok(response, context)
        requirements = self._build_requirements(response.json(), "" if self.access_token else body["p"])
        if not requirements.token:
            message = "missing auth chat requirements token" if self.access_token else "missing chat requirements token"
            raise RuntimeError(f"{message}: {requirements.raw_finalize}")
        return requirements

    def _chat_target(self) -> tuple[str, str]:
        if self.access_token:
            return "/backend-api/conversation", "Asia/Shanghai"
        return "/backend-anon/conversation", "America/Los_Angeles"

    def list_models(self) -> Dict[str, Any]:
        """返回当前模式下可用模型，格式对齐 OpenAI `/v1/models`。"""
        self._bootstrap()
        path = "/backend-api/models?history_and_training_disabled=false" if self.access_token else (
            "/backend-anon/models?iim=false&is_gizmo=false"
        )
        route = "/backend-api/models" if self.access_token else "/backend-anon/models"
        context = "auth_models" if self.access_token else "anon_models"
        response = self.session.get(
            self.base_url + path,
            headers=self._headers(route),
            timeout=30,
        )
        ensure_ok(response, context)
        data = []
        seen = set()
        for item in response.json().get("models", []):
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug", "")).strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            data.append({
                "id": slug,
                "object": "model",
                "created": int(item.get("created") or 0),
                "owned_by": str(item.get("owned_by") or "chatgpt"),
                "permission": [],
                "root": slug,
                "parent": None,
            })
        data.sort(key=lambda item: item["id"])
        return {"object": "list", "data": data}
