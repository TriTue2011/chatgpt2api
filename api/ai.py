from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from api.support import require_identity, resolve_image_base_url
from services import image_guard
from services.content_filter import check_request, request_text
from services.image_guard import ImageRejected
from services.ingress_guard import BodyTooLarge, read_upload_limited
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


# Nhóm hành động vật lý/máy chủ — key vai 'user' KHÔNG được chạm mặc định.
_DANGER_GROUPS = {"homeassistant", "device", "server", "code"}

# Trần cho /v1/images/edits — lấy từ services.image_guard để CÙNG một luật với
# /api/image-tasks/edits. Trước đây hai đường vào tự đặt trần riêng và lệch nhau,
# nên chỉ cần đổi cửa là lách được.
_MAX_IMAGE_BYTES = image_guard.MAX_IMAGE_BYTES
_MAX_EDIT_IMAGES = image_guard.MAX_IMAGES_PER_REQUEST
_MAX_EDIT_TOTAL_BYTES = image_guard.MAX_TOTAL_IMAGE_BYTES


def _effective_allowed_groups(role: str, server_allowed, client_allowed):
    """Trần nhóm chức năng cho MỘT request /v1/chat, giao (thu hẹp) các trần:

    - server_allowed: ha_allowed_groups admin cấu hình (None = chưa cấu hình).
    - role ceiling: vai 'user' → mọi nhóm TRỪ _DANGER_GROUPS; admin → không trần.
    - client_allowed: x_allowed_groups client tự khai (chỉ THU HẸP thêm).

    Trả list sorted để gán vào payload['x_allowed_groups'], hoặc None nếu không
    có trần nào (giữ hành vi cũ: admin + chưa cấu hình gì = full)."""
    role_ceiling = None
    if str(role or "") != "admin":
        try:
            from services.agent import capabilities as _caps_role
            role_ceiling = {g for g in _caps_role.all_groups() if g not in _DANGER_GROUPS}
        except Exception:
            role_ceiling = None
    ceilings = [c for c in (server_allowed, role_ceiling) if c is not None]
    if ceilings:
        final = set.intersection(*ceilings) if len(ceilings) > 1 else set(ceilings[0])
        if client_allowed is not None:
            final = final & client_allowed
        return sorted(final)
    if client_allowed is not None:
        return sorted(client_allowed)
    return None


def _internal_header_ok(request: Request) -> bool:
    """True nếu request mang header nội bộ khớp auth_key — chỉ đường agent
    runtime tự gọi localhost mới đặt được (nó biết auth_key). Dùng để tin cờ
    x_agent_internal mà không cho client ngoài giả mạo. So sánh hằng thời gian."""
    try:
        import hmac
        from services.config import config
        got = request.headers.get("x-agent-internal-key") or ""
        want = str(getattr(config, "auth_key", "") or "")
        return bool(got) and bool(want) and hmac.compare_digest(str(got), want)
    except Exception:
        return False


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
        if len(uploads) > _MAX_EDIT_IMAGES:
            raise HTTPException(
                status_code=400,
                detail={"error": f"too many images (max {_MAX_EDIT_IMAGES})"},
            )
        images: list[tuple[bytes, str, str]] = []
        total_bytes = 0
        for upload in uploads:
            try:
                image_data = await read_upload_limited(upload, _MAX_IMAGE_BYTES)
            except BodyTooLarge:
                raise HTTPException(status_code=413, detail={"error": "image file too large"})
            if not image_data:
                raise HTTPException(status_code=400, detail={"error": "image file is empty"})
            # Trần TỔNG: từng ảnh trong hạn nhưng 8 ảnh cộng lại vẫn đủ nặng.
            total_bytes += len(image_data)
            if total_bytes > _MAX_EDIT_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail={"error": "images too large in total"})
            images.append((image_data, upload.filename or "image.png", upload.content_type or "image/png"))
        # Nội dung: magic bytes + trần điểm ảnh. Trần byte KHÔNG chặn được ảnh
        # bom nén — file 40KB khai báo 50.000×50.000 là ~10GB RAM khi giải nén.
        try:
            image_guard.kiem_bo_anh(images)
        except ImageRejected as exc:
            raise HTTPException(status_code=400, detail={"error": exc.ly_do}) from exc
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
        # x_agent_internal đánh dấu "vòng nội bộ của agent" → BỎ QUA Agent run
        # journal. Model cho phép field lạ nên client NGOÀI gửi được cờ này để
        # né audit. Chỉ tin khi request mang header nội bộ khớp auth_key (đường
        # agent runtime tự gọi localhost đặt header đó). Mọi request ngoài: bóc
        # sạch cờ trước khi dùng.
        payload.pop("x_agent_internal", None)
        if _internal_header_ok(request):
            payload["x_agent_internal"] = True
        # Danh tính ĐÃ XÁC THỰC — nguồn sự thật duy nhất cho phạm vi ký ức dài
        # hạn. Trước đây MemoryService lấy khoá kho thẳng từ field `user` do
        # client gửi, nên một bearer token hợp lệ chỉ cần gửi user="<id người
        # khác>" là đọc được ký ức người đó. Gán ĐÈ vô điều kiện: model cho phép
        # field lạ nên client gửi được `_principal`, tin nó là mở lại đúng lỗ.
        payload["_principal"] = str(identity.get("id") or "")
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
        # Mô hình tin cậy: ha_allowed_groups (Settings → Home Assistant) là
        # TRẦN quyền tối đa cho MỌI request qua endpoint này — áp dụng bất kể
        # User-Agent (chuỗi tự khai, giả mạo được) và bất kể client có tự gửi
        # x_allowed_groups hay không. KHÔNG bao giờ tin x_allowed_groups do
        # client gửi làm nguồn sự thật (kẻo bearer token hợp lệ tự gửi list
        # rộng để vượt cấu hình admin) — chỉ dùng nó để THU HẸP thêm (giao
        # với trần server), không bao giờ MỞ RỘNG vượt trần. Admin chưa cấu
        # hình ha_allowed_groups = không có trần (giữ hành vi cũ).
        try:
            from services.config import config as _cfg
            _hag = _cfg.get().get("ha_allowed_groups")
            _server_allowed = {str(g) for g in _hag} if isinstance(_hag, list) else None
        except Exception:
            _server_allowed = None
        _client_ag = payload.get("x_allowed_groups")
        _client_allowed = {str(g) for g in _client_ag} if isinstance(_client_ag, list) else None
        # TRẦN THEO VAI: key vai 'user' KHÔNG được nhóm hành động vật lý/máy chủ
        # mặc định. Admin (gồm HA dùng auth_key admin) full. Trước đây endpoint
        # chỉ gắn _principal, không xét role → bearer user hợp lệ chạm được
        # HA/SSH/ghi cấu hình khi admin chưa cấu hình ha_allowed_groups.
        _eff = _effective_allowed_groups(
            str(identity.get("role") or ""), _server_allowed, _client_allowed)
        if _eff is not None:
            payload["x_allowed_groups"] = _eff
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
