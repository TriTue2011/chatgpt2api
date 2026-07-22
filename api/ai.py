from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from api.support import require_identity, resolve_image_base_url
from services.content_filter import check_request, request_text
from services.log_service import (
    KIND_IMAGE,
    KIND_VISION,
    LoggedCall,
    detect_vision_messages,
    endpoint_run_kind,
    resolve_source_kind,
)
from services.protocol import (
    anthropic_v1_messages,
    openai_v1_chat_complete,
    openai_v1_image_edit,
    openai_v1_image_generations,
    openai_v1_models,
    openai_v1_response,
)


def _client_host(request: Request) -> str:
    try:
        return str(getattr(request.client, "host", "") or "")
    except Exception:
        return ""


class ImageGenerationRequest(BaseModel):
    # Allow extra fields so adapters (Flow) can read `extra_body` /
    # per-provider overrides without each new field requiring a schema
    # change here. Without this, Pydantic silently strips unknown keys.
    model_config = ConfigDict(extra="allow")
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-2"
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    response_format: str = "b64_json"
    history_disabled: bool = True
    stream: bool | None = None
    # OpenAI-style escape hatch: clients can stuff provider-specific
    # params under `extra_body` and the adapter pulls them out.
    extra_body: dict[str, object] | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    prompt: str | None = None
    n: int | None = None
    stream: bool | None = None
    modalities: list[str] | None = None
    messages: list[dict[str, object]] | None = None


class ResponseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    input: object | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None
    stream: bool | None = None


class AnthropicMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    messages: list[dict[str, object]] | None = None
    system: object | None = None
    stream: bool | None = None


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("Gọi thất bại", status="failed", error=str(exc.detail))
        raise


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v1/models")
    async def list_models(request: Request, authorization: str | None = Header(default=None)):
        require_identity(authorization)
        force_refresh = request.query_params.get("refresh", "").lower() == "true"
        try:
            return await run_in_threadpool(openai_v1_models.list_models, force_refresh, True)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            user_agent: str | None = Header(default=None, alias="user-agent"),
    ):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        payload["base_url"] = resolve_image_base_url(request)
        client_host = _client_host(request)
        source_kind = resolve_source_kind(
            identity=identity, user_agent=user_agent or "",
        )
        call = LoggedCall(
            identity,
            "/v1/images/generations",
            body.model,
            "Tạo ảnh",
            request_text=body.prompt,
            client_host=client_host,
            user_agent=user_agent or "",
            source_kind=source_kind,
            run_kind=KIND_IMAGE,
            extra_meta={"n": body.n, "size": body.size or ""},
        )
        await filter_or_log(call, body.prompt)
        return await call.run(openai_v1_image_generations.handle, payload)

    @router.post("/v1/images/edits")
    async def edit_images(
            request: Request,
            authorization: str | None = Header(default=None),
            user_agent: str | None = Header(default=None, alias="user-agent"),
            image: list[UploadFile] | None = File(default=None),
            image_list: list[UploadFile] | None = File(default=None, alias="image[]"),
            prompt: str = Form(...),
            model: str = Form(default="gpt-image-2"),
            n: int = Form(default=1),
            size: str | None = Form(default=None),
            response_format: str = Form(default="b64_json"),
            stream: bool | None = Form(default=None),
    ):
        identity = require_identity(authorization)
        client_host = _client_host(request)
        source_kind = resolve_source_kind(
            identity=identity, user_agent=user_agent or "",
        )
        call = LoggedCall(
            identity,
            "/v1/images/edits",
            model,
            "Sửa ảnh",
            request_text=prompt,
            client_host=client_host,
            user_agent=user_agent or "",
            source_kind=source_kind,
            run_kind=KIND_IMAGE,
            extra_meta={"n": n, "size": size or "", "edit": True},
        )
        if n < 1 or n > 4:
            raise HTTPException(status_code=400, detail={"error": "n must be between 1 and 4"})
        await filter_or_log(call, prompt)
        uploads = [*(image or []), *(image_list or [])]
        if not uploads:
            raise HTTPException(status_code=400, detail={"error": "image file is required"})
        images: list[tuple[bytes, str, str]] = []
        for upload in uploads:
            image_data = await upload.read()
            if not image_data:
                raise HTTPException(status_code=400, detail={"error": "image file is empty"})
            images.append((image_data, upload.filename or "image.png", upload.content_type or "image/png"))
        payload = {
            "prompt": prompt,
            "images": images,
            "model": model,
            "n": n,
            "size": size,
            "response_format": response_format,
            "stream": stream,
            "base_url": resolve_image_base_url(request),
        }
        call.extra_meta["input_images"] = len(images)
        return await call.run(openai_v1_image_edit.handle, payload)

    @router.post("/v1/chat/completions")
    async def create_chat_completion(
        body: ChatCompletionRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_agent: str | None = Header(default=None, alias="user-agent"),
    ):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        # HA Conversation / voice surfaces can't render markdown — flag the
        # request so the chat handler force-strips the response. User-Agent
        # contains "HomeAssistant" for both REST and websocket integrations.
        ua = (user_agent or "").lower()
        # Home Assistant core UA, or local_openai / AsyncOpenAI from HA host
        is_ha = (
            "homeassistant" in ua
            or "hass.io" in ua
            or "asyncopenai" in ua.replace(" ", "")
            or "openai/python" in ua
        )
        if is_ha:
            payload["_is_ha_request"] = True
        # Inject base_url so gma provider can build persistent local media URLs
        payload["base_url"] = resolve_image_base_url(request)
        client_host = _client_host(request)
        # Agent runtime internal loop — don't double-count in Agent runs UI
        is_internal = bool(payload.get("x_agent_internal"))
        source_kind = resolve_source_kind(
            identity=identity,
            user_agent=user_agent or "",
            is_internal=is_internal,
        )
        if is_ha and source_kind != "agent_internal":
            source_kind = "ha"
        payload["_client_host"] = client_host
        payload["_source_kind"] = source_kind
        # Persona Home Assistant — cài ở Settings → card Persona (kênh Home
        # Assistant, key phiên "ha"); chỉ áp cho request nhận diện là HA.
        try:
            if source_kind == "ha" and isinstance(payload.get("messages"), list):
                from services.agent import persona as _P
                _pb = _P.prompt_for("ha")
                if _pb:
                    payload["messages"] = [{"role": "system", "content": _pb},
                                           *payload["messages"]]
        except Exception:
            pass
        model = str(payload.get("model") or "auto")
        request_preview = request_text(payload.get("prompt"), payload.get("messages"))
        has_vision = detect_vision_messages(payload.get("messages"))
        run_kind = KIND_VISION if has_vision else endpoint_run_kind(
            "/v1/chat/completions", has_vision=False,
        )
        summary = "Phân tích ảnh" if has_vision else "Chat"
        call = LoggedCall(
            identity,
            "/v1/chat/completions",
            model,
            summary,
            request_text=request_preview,
            client_host=client_host,
            user_agent=user_agent or "",
            source_kind=source_kind,
            skip_run_journal=is_internal,
            run_kind=run_kind,
            extra_meta={"has_vision": has_vision},
        )
        await filter_or_log(call, request_preview)
        return await call.run(openai_v1_chat_complete.handle, payload)

    @router.post("/v1/responses")
    async def create_response(
        body: ResponseCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        user_agent: str | None = Header(default=None, alias="user-agent"),
    ):
        identity = require_identity(authorization)
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        request_preview = request_text(payload.get("input"), payload.get("instructions"))
        client_host = _client_host(request)
        source_kind = resolve_source_kind(
            identity=identity, user_agent=user_agent or "",
        )
        call = LoggedCall(
            identity,
            "/v1/responses",
            model,
            "Responses",
            request_text=request_preview,
            client_host=client_host,
            user_agent=user_agent or "",
            source_kind=source_kind,
            run_kind=endpoint_run_kind("/v1/responses"),
        )
        await filter_or_log(call, request_preview)
        return await call.run(openai_v1_response.handle, payload)

    @router.post("/v1/messages")
    async def create_message(
            body: AnthropicMessageRequest,
            request: Request,
            authorization: str | None = Header(default=None),
            user_agent: str | None = Header(default=None, alias="user-agent"),
            x_api_key: str | None = Header(default=None, alias="x-api-key"),
            anthropic_version: str | None = Header(default=None, alias="anthropic-version"),
    ):
        identity = require_identity(authorization or (f"Bearer {x_api_key}" if x_api_key else None))
        payload = body.model_dump(mode="python")
        model = str(payload.get("model") or "auto")
        request_preview = request_text(payload.get("system"), payload.get("messages"), payload.get("tools"))
        client_host = _client_host(request)
        source_kind = resolve_source_kind(
            identity=identity, user_agent=user_agent or "",
        )
        has_vision = detect_vision_messages(payload.get("messages"))
        run_kind = KIND_VISION if has_vision else endpoint_run_kind("/v1/messages")
        call = LoggedCall(
            identity,
            "/v1/messages",
            model,
            "Phân tích ảnh" if has_vision else "Messages",
            request_text=request_preview,
            client_host=client_host,
            user_agent=user_agent or "",
            source_kind=source_kind,
            run_kind=run_kind,
            extra_meta={"has_vision": has_vision},
        )
        await filter_or_log(call, request_preview)
        return await call.run(anthropic_v1_messages.handle, payload, sse="anthropic")

    return router
