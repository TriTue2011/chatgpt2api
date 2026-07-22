from __future__ import annotations

import hashlib
import json
import itertools
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from services.config import DATA_DIR
from utils.helper import anthropic_sse_stream, sse_json_stream

LOG_TYPE_CALL = "call"
LOG_TYPE_ACCOUNT = "account"
# Per-surface call logs so the Logs UI can filter chat vs image-gen
# without grepping the generic LOG_TYPE_CALL bucket. Each entry carries
# {provider, profile, op, duration_ms, prompt_len, ok, error}.
LOG_TYPE_WEB_CHAT = "web_chat"          # gmw/cgw chat + vision
LOG_TYPE_WEB_IMAGE = "web_image"        # gmw imagen / cgw dall-e / flow

# Nhãn provider cho tin nhắn bot admin — detail có thể mang provider/group/type
# ("free", "codex", "gemini_web_api", "flow"…); không khớp thì hiện nguyên văn.
_PROVIDER_LABELS = {
    "free": "ChatGPT free",
    "chatgpt_free": "ChatGPT free",
    "chatgpt_web": "ChatGPT web",
    "codex": "Codex",
    "codex_oauth": "Codex",
    "openai": "OpenAI",
    "gemini_web_api": "Gemini web",
    "gemini_web": "Gemini web",
    "gma": "Gemini web",
    "flow": "Flow",
    "claude": "Claude",
    "antigravity": "Antigravity",
}


def _provider_label(detail: dict) -> str:
    for key in ("provider", "group", "type", "source"):
        raw = str(detail.get(key) or "").strip()
        if raw:
            return _PROVIDER_LABELS.get(raw.lower(), raw)
    return "Log tài khoản"


class LogService:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _legacy_id(raw_line: str, line_number: int) -> str:
        payload = f"{line_number}:{raw_line}".encode("utf-8", errors="ignore")
        return hashlib.sha1(payload).hexdigest()[:24]

    def _parse_line(self, raw_line: str, line_number: int) -> dict[str, Any] | None:
        try:
            item = json.loads(raw_line)
        except Exception:
            return None
        if not isinstance(item, dict):
            return None
        parsed = dict(item)
        parsed["id"] = str(parsed.get("id") or self._legacy_id(raw_line, line_number))
        return parsed

    @staticmethod
    def _serialize_item(item: dict[str, Any]) -> str:
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _matches_filters(item: dict[str, Any], *, type: str = "", start_date: str = "", end_date: str = "") -> bool:
        t = str(item.get("time") or "")
        day = t[:10]
        if type and item.get("type") != type:
            return False
        if start_date and day < start_date:
            return False
        if end_date and day > end_date:
            return False
        return True

    def add(self, type: str, summary: str = "", detail: dict[str, Any] | None = None, **data: Any) -> None:
        item = {
            "id": uuid4().hex,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": type,
            "summary": summary,
            "detail": detail or data,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(self._serialize_item(item) + "\n")
        # Optional fan-out: account logs → admin bot. Per-channel gating
        # (account_log_notify_telegram/zalo/zalo_personal, fallback key cũ)
        # nằm trong notifier qua category="account_log".
        # Skip if writer already notified bots (e.g. account_recovery._notify).
        if type == LOG_TYPE_ACCOUNT:
            try:
                det0 = item.get("detail") or {}
                if isinstance(det0, dict) and det0.get("notify_bots") is False:
                    return
                if (summary or "").strip():
                    from services.notifier import notify_admin
                    # Keep short — Telegram 4096 limit; detail only if small
                    det = det0 if isinstance(det0, dict) else {}
                    extra = ""
                    if det:
                        bits = []
                        for k in ("provider", "email", "profile", "token", "status",
                                  "step", "source", "reason", "error"):
                            if det.get(k) is not None:
                                bits.append(f"{k}={det.get(k)}")
                        if bits:
                            extra = "\n" + ", ".join(bits)[:500]
                    label = _provider_label(det)
                    notify_admin(f"📋 {label}: {summary}{extra}",
                                 category="account_log")
            except Exception:
                pass

    def list(self, type: str = "", start_date: str = "", end_date: str = "", limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: list[dict[str, Any]] = []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for line_number in range(len(lines) - 1, -1, -1):
            item = self._parse_line(lines[line_number], line_number)
            if item is None:
                continue
            if not self._matches_filters(item, type=type, start_date=start_date, end_date=end_date):
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def delete(self, ids: list[str]) -> dict[str, int]:
        target_ids = {str(item or "").strip() for item in ids if str(item or "").strip()}
        if not self.path.exists() or not target_ids:
            return {"removed": 0}
        lines = self.path.read_text(encoding="utf-8").splitlines()
        kept_lines: list[str] = []
        removed = 0
        for line_number, raw_line in enumerate(lines):
            item = self._parse_line(raw_line, line_number)
            if item is None:
                kept_lines.append(raw_line)
                continue
            if str(item.get("id") or "") in target_ids:
                removed += 1
                continue
            kept_lines.append(self._serialize_item(item))
        content = "\n".join(kept_lines)
        if content:
            content += "\n"
        self.path.write_text(content, encoding="utf-8")
        return {"removed": removed}


log_service = LogService(DATA_DIR / "logs.jsonl")


def _collect_urls(value: object) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str):
                urls.append(item)
            elif key == "urls" and isinstance(item, list):
                urls.extend(str(url) for url in item if isinstance(url, str))
            else:
                urls.extend(_collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_collect_urls(item))
    return urls


def _request_excerpt(text: object, limit: int = 1000) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _image_error_response(exc: Exception) -> JSONResponse:
    message = str(exc)
    if "no available image quota" in message.lower():
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": "no available image quota",
                    "type": "insufficient_quota",
                    "param": None,
                    "code": "insufficient_quota",
                }
            },
        )
    if hasattr(exc, "to_openai_error") and hasattr(exc, "status_code"):
        return JSONResponse(status_code=int(exc.status_code), content=exc.to_openai_error())
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": message,
                "type": "server_error",
                "param": None,
                "code": "upstream_error",
            }
        },
    )


def _next_item(items):
    try:
        return True, next(items)
    except StopIteration:
        return False, None


# Endpoints that land in the Agent runs journal (chat + vision + image + video).
_JOURNAL_ENDPOINTS = frozenset({
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/messages",
    "/v1/images/generations",
    "/v1/images/edits",
    "/api/image-tasks/generations",
    "/api/image-tasks/edits",
    "/v1/video/generations",
})

# Short kind labels stored in run.hint / meta.kind for the Agent runs UI.
KIND_CHAT = "chat"
KIND_VISION = "vision"
KIND_IMAGE = "image_gen"
KIND_VIDEO = "video_gen"
KIND_AGENT = "agent"

_KIND_LABELS = {
    KIND_CHAT: "Chat",
    KIND_VISION: "Phân tích ảnh",
    KIND_IMAGE: "Tạo ảnh",
    KIND_VIDEO: "Tạo video",
    KIND_AGENT: "Agent",
}


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(str(kind or "").strip(), str(kind or "") or "—")


def detect_vision_messages(messages: object) -> bool:
    """True when OpenAI-style messages include image parts (vision request)."""
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = str(part.get("type") or "").lower()
                if (
                    ptype in {"image_url", "image", "input_image"}
                    or "image" in ptype
                    or part.get("image_url")
                    or part.get("image")
                ):
                    return True
        elif isinstance(content, dict):
            ptype = str(content.get("type") or "").lower()
            if "image" in ptype or content.get("image_url") or content.get("image"):
                return True
    return False


def endpoint_run_kind(endpoint: str, *, has_vision: bool = False) -> str:
    """Map gateway endpoint → journal kind (chat / vision / image_gen / video_gen)."""
    ep = str(endpoint or "")
    if ep in {"/v1/images/generations", "/v1/images/edits",
              "/api/image-tasks/generations", "/api/image-tasks/edits"}:
        return KIND_IMAGE
    if ep in {"/v1/video/generations"}:
        return KIND_VIDEO
    if has_vision:
        return KIND_VISION
    if ep in {"/v1/chat/completions", "/v1/responses", "/v1/messages"}:
        return KIND_CHAT
    return KIND_CHAT


def resolve_source_kind(
    *,
    identity: dict[str, object] | None = None,
    user_agent: str = "",
    source_kind: str = "",
    is_internal: bool = False,
) -> str:
    """ha | openapi | web | agent_internal — shared by chat / image / video routes."""
    if source_kind:
        return str(source_kind)
    if is_internal:
        return "agent_internal"
    ua = (user_agent or "").lower()
    if (
        "homeassistant" in ua
        or "hass.io" in ua
        or "asyncopenai" in ua.replace(" ", "")
        or "openai/python" in ua
    ):
        return "ha"
    ident = identity or {}
    if str(ident.get("id") or "") == "admin":
        return "web"
    return "openapi"


@dataclass
class LoggedCall:
    identity: dict[str, object]
    endpoint: str
    model: str
    summary: str
    started: float = field(default_factory=time.time)
    request_text: str = ""
    # Source context for agent run journal (HA / OpenAPI / web)
    client_host: str = ""
    user_agent: str = ""
    source_kind: str = ""  # ha | openapi | web | agent_internal | ""
    skip_run_journal: bool = False
    request_id: str = ""
    # chat | vision | image_gen | video_gen — empty = auto-detect from endpoint
    run_kind: str = ""
    extra_meta: dict[str, Any] = field(default_factory=dict)

    async def run(self, handler, *args, sse: str = "openai"):
        from services.protocol.conversation import ImageGenerationError

        # Cross-thread request bag (threadpool handlers can write dest account)
        try:
            from services import request_context as rc
            self.request_id = rc.begin(self.request_id or "")
            if self.source_kind or self.client_host or self.identity:
                rc.set_source(
                    request_id=self.request_id,
                    kind=self.source_kind or "",
                    account=str(self.identity.get("name") or self.identity.get("id") or ""),
                    peer=self.client_host or "",
                    user_id=str(self.identity.get("id") or ""),
                    user_agent=(self.user_agent or "")[:160],
                )
            # Inject into first dict payload arg so worker thread re-binds
            for a in args:
                if isinstance(a, dict):
                    a["_request_id"] = self.request_id
                    break
        except Exception:
            pass

        try:
            result = await run_in_threadpool(handler, *args)
        except ImageGenerationError as exc:
            self.log("Gọi thất bại", status="failed", error=str(exc))
            return _image_error_response(exc)
        except HTTPException as exc:
            self.log("Gọi thất bại", status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            self.log("Gọi thất bại", status="failed", error=str(exc))
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": str(exc),
                        "type": "server_error",
                        "param": None,
                        "code": "upstream_error",
                    }
                },
            )

        if isinstance(result, dict):
            self.log("Gọi thành công", result)
            return result

        sender = anthropic_sse_stream if sse == "anthropic" else sse_json_stream
        try:
            has_first, first = await run_in_threadpool(_next_item, result)
        except ImageGenerationError as exc:
            self.log("Gọi thất bại", status="failed", error=str(exc))
            return _image_error_response(exc)
        except HTTPException as exc:
            self.log("Gọi thất bại", status="failed", error=str(exc.detail))
            raise
        except Exception as exc:
            self.log("Gọi thất bại", status="failed", error=str(exc))
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": str(exc),
                        "type": "server_error",
                        "param": None,
                        "code": "upstream_error",
                    }
                },
            )
        if not has_first:
            self.log("Kết thúc stream")
            return StreamingResponse(sender(()), media_type="text/event-stream")
        return StreamingResponse(sender(self.stream(itertools.chain([first], result))), media_type="text/event-stream")

    def stream(self, items):
        urls: list[str] = []
        failed = False
        self._stream_content_len = 0
        self._stream_text_parts: list[str] = []
        try:
            for item in items:
                urls.extend(_collect_urls(item))
                # Collect streaming content length for token estimation
                if isinstance(item, dict):
                    choices = item.get("choices") or []
                    for c in choices:
                        delta = c.get("delta") or {}
                        content = delta.get("content") or ""
                        if content:
                            self._stream_content_len += len(content)
                            # Cap collected reply for journal (~2k)
                            if sum(len(p) for p in self._stream_text_parts) < 2000:
                                self._stream_text_parts.append(content)
                yield item
        except Exception as exc:
            failed = True
            self.log("流式Gọi thất bại", status="failed", error=str(exc), urls=urls)
            raise
        finally:
            if not failed:
                self.log("Kết thúc stream", urls=urls)

    def log(self, suffix: str, result: object = None, status: str = "success", error: str = "",
            urls: list[str] | None = None) -> None:
        detail = {
            "key_id": self.identity.get("id"),
            "key_name": self.identity.get("name"),
            "role": self.identity.get("role"),
            "endpoint": self.endpoint,
            "model": self.model,
            "started_at": datetime.fromtimestamp(self.started).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_ms": int((time.time() - self.started) * 1000),
            "status": status,
        }
        request_excerpt = _request_excerpt(self.request_text)
        if request_excerpt:
            detail["request_text"] = request_excerpt
        if error:
            detail["error"] = error
        collected_urls = [*(urls or []), *_collect_urls(result)]
        if collected_urls:
            detail["urls"] = list(dict.fromkeys(collected_urls))
        if self.client_host:
            detail["client_host"] = self.client_host
        if self.source_kind:
            detail["source_kind"] = self.source_kind
        try:
            from services import request_context as rc
            dest = rc.get_dest(self.request_id)
            if dest:
                detail["dest_provider"] = dest.get("provider")
                detail["dest_account"] = dest.get("account")
                detail["dest_model"] = dest.get("model")
        except Exception:
            pass
        log_service.add(LOG_TYPE_CALL, f"{self.summary}{suffix}", detail)

        # Also log to usage tracker for dashboard stats
        try:
            from services.usage_tracker import log_usage
            prompt_tokens = 0
            completion_tokens = 0
            if isinstance(result, dict):
                usage = result.get("usage") or {}
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
            # Fallback: use tiktoken for accurate prompt token counting
            if prompt_tokens == 0 and self.request_text:
                try:
                    from services.protocol.conversation import encoding_for_model
                    enc = encoding_for_model(self.model)
                    prompt_tokens = max(1, len(enc.encode(self.request_text)))
                except Exception:
                    prompt_tokens = max(1, len(self.request_text) // 4)
            # Completion: estimate from streamed content length
            if completion_tokens == 0:
                stream_len = getattr(self, "_stream_content_len", 0)
                if stream_len > 0:
                    completion_tokens = max(1, stream_len // 4)
            log_usage(
                model=self.model,
                endpoint=self.endpoint,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=int((time.time() - self.started) * 1000),
                status=status,
                error=error,
                started_at=datetime.fromtimestamp(self.started, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        except Exception:
            pass

        # Agent / API run journal (HA + OpenAPI + web) — skip internal agent loops
        try:
            self._journal_run(result=result, status=status, error=error, detail=detail)
        except Exception:
            pass

    def _journal_run(
        self,
        *,
        result: object = None,
        status: str = "success",
        error: str = "",
        detail: dict | None = None,
    ) -> None:
        if self.skip_run_journal:
            return
        # Chat + vision + image gen + video gen (+ agent tools via orchestrator)
        ep = str(self.endpoint or "")
        if ep not in _JOURNAL_ENDPOINTS:
            return
        try:
            from services.agent import run_journal as rj
        except Exception:
            return
        if not rj.is_enabled() or not rj.log_api_enabled():
            return

        kind = str(self.source_kind or "").strip()
        if kind in {"agent_internal", "internal"}:
            return
        if not kind:
            kind = resolve_source_kind(
                identity=self.identity if isinstance(self.identity, dict) else {},
                user_agent=self.user_agent or "",
            )

        run_kind = str(self.run_kind or "").strip() or endpoint_run_kind(ep)
        reply = _journal_reply_text(result, self)
        tools = _journal_tools_for_kind(run_kind, ep)

        journal_status = "ok" if status == "success" else ("error" if status == "failed" else status)
        dest_provider = ""
        dest_account = ""
        dest_model = ""
        dest_trail: list = []
        try:
            from services import request_context as rc
            d = rc.get_dest(self.request_id)
            dest_provider = str(d.get("provider") or "")
            dest_account = str(d.get("account") or "")
            dest_model = str(d.get("model") or "")
            dest_trail = rc.get_dest_trail(self.request_id)
        except Exception:
            pass

        media = _journal_media_summary(result, detail)
        groups = _groups_for_tools(tools)
        meta: dict[str, Any] = {
            "endpoint": ep,
            "kind": run_kind,
            "kind_label": kind_label(run_kind),
            "key_id": self.identity.get("id"),
            "key_name": self.identity.get("name"),
            "user_agent": (self.user_agent or "")[:160],
            "client_host": self.client_host or "",
            "request_id": self.request_id or "",
            "groups": groups,
            "summary": self.summary or "",
        }
        if dest_trail:
            meta["dest_trail"] = dest_trail
        if media.get("urls"):
            meta["urls"] = media["urls"]
        if media.get("media_count"):
            meta["media_count"] = media["media_count"]
        if self.extra_meta:
            try:
                meta.update({k: v for k, v in self.extra_meta.items() if v is not None})
            except Exception:
                pass

        user_id = f"{kind}_{self.identity.get('id') or 'anon'}"
        if kind == "ha" and self.client_host:
            user_id = f"ha_{self.client_host}"

        # hint = run kind so UI can filter Chat / Vision / Image / Video
        rj.log_run(
            user_id=user_id,
            user_text=self.request_text or "",
            reply_text=reply,
            model=str(self.model or ""),
            hint=run_kind,
            tools=tools,
            steps=0,
            duration_ms=int((time.time() - self.started) * 1000),
            status=journal_status,
            error=error or "",
            meta=meta,
            source_kind=kind,
            source_account=str(self.identity.get("name") or self.identity.get("id") or ""),
            source_peer=self.client_host or "",
            dest_provider=dest_provider,
            dest_account=dest_account,
            dest_model=dest_model or str(self.model or ""),
            request_id=self.request_id or "",
            channel=kind if kind in {"ha", "openapi", "web"} else "",
        )
        # drop bag so store stays small
        try:
            from services import request_context as rc
            rc.end(self.request_id)
        except Exception:
            pass


def _journal_reply_text(result: object, call: "LoggedCall") -> str:
    """Extract human-readable reply for journal (text chat or media summary)."""
    reply = ""
    if isinstance(result, dict):
        try:
            choices = result.get("choices") or []
            if choices:
                msg = (choices[0] or {}).get("message") or {}
                content = msg.get("content")
                if isinstance(content, str):
                    reply = content
                elif content is not None:
                    reply = str(content)[:2000]
        except Exception:
            reply = ""
        if not reply:
            # image/video OpenAI-style: data[].url or b64
            data = result.get("data")
            if isinstance(data, list) and data:
                urls = [str(i.get("url") or "") for i in data if isinstance(i, dict) and i.get("url")]
                b64_n = sum(
                    1 for i in data
                    if isinstance(i, dict) and (i.get("b64_json") or i.get("b64"))
                )
                parts = []
                if urls:
                    parts.append(f"{len(urls)} URL: " + "; ".join(urls[:4]))
                if b64_n:
                    parts.append(f"{b64_n} ảnh (b64)")
                if parts:
                    reply = " · ".join(parts)
            # some video adapters return video_url / url at top level
            for key in ("video_url", "url", "output_url"):
                if result.get(key) and not reply:
                    reply = str(result.get(key))
    if not reply:
        parts = getattr(call, "_stream_text_parts", None) or []
        reply = "".join(parts)
    return reply


def _journal_tools_for_kind(run_kind: str, endpoint: str) -> list[str]:
    """Synthetic tool tags so Agent runs shows what kind of work happened."""
    if run_kind == KIND_IMAGE:
        if "edit" in endpoint:
            return ["image_edit"]
        return ["image_generations"]
    if run_kind == KIND_VIDEO:
        return ["video_generations"]
    if run_kind == KIND_VISION:
        return ["vision"]
    if run_kind == KIND_CHAT:
        return ["chat"]
    return []


def _journal_media_summary(result: object, detail: dict | None) -> dict[str, Any]:
    urls: list[str] = []
    if detail and detail.get("urls"):
        raw = detail.get("urls") or []
        if isinstance(raw, list):
            urls.extend(str(u) for u in raw if u)
    urls.extend(_collect_urls(result))
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    media_count = len(uniq)
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, list) and len(data) > media_count:
            media_count = len(data)
    return {"urls": uniq[:20], "media_count": media_count}


def _groups_for_tools(tools: list[str]) -> list[str]:
    """Map tool names → permission groups (🏠 Ảnh / Video / …) for UI chips."""
    if not tools:
        return []
    # Lightweight map for API synthetic tools (no full capability registry needed)
    synthetic = {
        "chat": "chat",
        "vision": "image",  # vision analysis shares the Ảnh family in HA filters
        "image_generations": "image",
        "image_edit": "image",
        "video_generations": "video",
        "generate_image": "image",
        "generate_video": "video",
        "generate_music": "music",
        "library_media": "image",
        "web_search": "web",
        "read_webpage": "web",
        "write_code": "code",
        "home_status": "homeassistant",
        "control_home": "homeassistant",
        "remember": "memory",
        "schedule": "schedule",
        "use_skill": "skills",
        "run_workflow": "skills",
        "contacts": "contacts",
        "speak_to_speaker": "tts_speaker",
    }
    groups: list[str] = []
    try:
        from services.agent.capabilities import group_of
        for t in tools:
            g = group_of(t)
            if g == "_ungrouped":
                g = synthetic.get(t, "")
            if g and g not in groups:
                groups.append(g)
    except Exception:
        for t in tools:
            g = synthetic.get(t, "")
            if g and g not in groups:
                groups.append(g)
    return groups
