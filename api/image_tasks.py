from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.support import require_identity, resolve_image_base_url
from services import image_guard
from services.content_filter import check_request
from services.image_guard import ImageRejected
from services.image_task_service import TaskQueueFull, image_task_service
from services.log_service import LoggedCall

# Trần độ dài đầu vào. `client_task_id` là khoá do CLIENT đặt và được ghép vào
# tên thread + khoá sổ tác vụ trên đĩa; prompt đi thẳng sang provider. Không có
# trần thì một request đủ để phình sổ tác vụ và log.
MAX_TASK_ID_LEN = 128
MAX_PROMPT_LEN = 8000


class ImageGenerationTaskRequest(BaseModel):
    client_task_id: str = Field(..., min_length=1, max_length=MAX_TASK_ID_LEN)
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LEN)
    model: str = Field(default="gpt-image-2", max_length=128)
    size: str | None = Field(default=None, max_length=32)


def _parse_task_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def filter_or_log(call: LoggedCall, text: str) -> None:
    try:
        await run_in_threadpool(check_request, text)
    except HTTPException as exc:
        call.log("Gọi thất bại", status="failed", error=str(exc.detail))
        raise


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/image-tasks")
    async def list_image_tasks(
        ids: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        return await run_in_threadpool(image_task_service.list_tasks, identity, _parse_task_ids(ids))

    @router.post("/api/image-tasks/generations")
    async def create_generation_task(
        body: ImageGenerationTaskRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        identity = require_identity(authorization)
        await filter_or_log(LoggedCall(identity, "/api/image-tasks/generations", body.model, "Tác vụ tạo ảnh từ chữ", request_text=body.prompt), body.prompt)
        try:
            return await run_in_threadpool(
                image_task_service.submit_generation,
                identity,
                client_task_id=body.client_task_id,
                prompt=body.prompt,
                model=body.model,
                size=body.size,
                base_url=resolve_image_base_url(request),
            )
        except TaskQueueFull as exc:
            raise HTTPException(status_code=429, detail={"error": exc.ly_do}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/image-tasks/edits")
    async def create_edit_task(
        request: Request,
        authorization: str | None = Header(default=None),
        image: list[UploadFile] | None = File(default=None),
        image_list: list[UploadFile] | None = File(default=None, alias="image[]"),
        client_task_id: str = Form(...),
        prompt: str = Form(...),
        model: str = Form(default="gpt-image-2"),
        size: str | None = Form(default=None),
    ):
        identity = require_identity(authorization)
        # Form không đi qua pydantic nên phải tự chặn độ dài như bản JSON ở trên.
        if len(client_task_id) > MAX_TASK_ID_LEN or len(prompt) > MAX_PROMPT_LEN:
            raise HTTPException(
                status_code=400,
                detail={"error": f"client_task_id ≤ {MAX_TASK_ID_LEN} ký tự, prompt ≤ {MAX_PROMPT_LEN} ký tự"},
            )
        await filter_or_log(LoggedCall(identity, "/api/image-tasks/edits", model, "Tác vụ tạo ảnh từ ảnh", request_text=prompt), prompt)
        uploads = [*(image or []), *(image_list or [])]
        if not uploads:
            raise HTTPException(status_code=400, detail={"error": "image file is required"})
        # Cùng một luật với /v1/images/edits. Trước đây đường này chỉ có trần
        # 50MB mỗi tệp — không giới hạn SỐ ảnh, không giới hạn TỔNG, nên cùng
        # một người dùng chỉ cần đổi sang cửa này là lách sạch cửa kia.
        if len(uploads) > image_guard.MAX_IMAGES_PER_REQUEST:
            raise HTTPException(
                status_code=400,
                detail={"error": f"too many images (max {image_guard.MAX_IMAGES_PER_REQUEST})"},
            )
        from services.ingress_guard import BodyTooLarge, read_upload_limited
        images: list[tuple[bytes, str, str]] = []
        total_bytes = 0
        for upload in uploads:
            try:
                image_data = await read_upload_limited(upload, image_guard.MAX_IMAGE_BYTES)
            except BodyTooLarge:
                raise HTTPException(status_code=413, detail={"error": "image file too large"})
            if not image_data:
                raise HTTPException(status_code=400, detail={"error": "image file is empty"})
            total_bytes += len(image_data)
            if total_bytes > image_guard.MAX_TOTAL_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail={"error": "images too large in total"})
            images.append((image_data, upload.filename or "image.png", upload.content_type or "image/png"))
        try:
            image_guard.kiem_bo_anh(images)
        except ImageRejected as exc:
            raise HTTPException(status_code=400, detail={"error": exc.ly_do}) from exc
        try:
            return await run_in_threadpool(
                image_task_service.submit_edit,
                identity,
                client_task_id=client_task_id,
                prompt=prompt,
                model=model,
                size=size,
                base_url=resolve_image_base_url(request),
                images=images,
            )
        except TaskQueueFull as exc:
            raise HTTPException(status_code=429, detail={"error": exc.ly_do}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    return router
