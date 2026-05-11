from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from api.support import require_admin, require_identity, resolve_image_base_url
from services.backup_service import BackupError, backup_service
from services.config import config
from services.image_service import delete_images, download_images_zip, get_image_download_response, get_thumbnail_response, list_images
from services.image_tags_service import delete_tag, get_all_tags, set_tags
from services.log_service import log_service
from services.proxy_service import test_proxy
from services.state_backup import state_backup
from services.backend_router import backend_router
from services.providers.opencode import opencode_provider
from services.rate_limit_backoff import rate_limit_backoff


def _create_backup() -> dict:
    """Create local full-state backup."""
    payload = state_backup.export_all()
    filepath = state_backup.save_to_file(payload)
    return {
        "status": "ok",
        "path": str(filepath),
        "size_bytes": filepath.stat().st_size,
        "created_at": payload["created_at"],
    }


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProxyTestRequest(BaseModel):
    url: str = ""


class ImageDeleteRequest(BaseModel):
    paths: list[str] = []
    start_date: str = ""
    end_date: str = ""
    all_matching: bool = False

class ImageDownloadRequest(BaseModel):
    paths: list[str]

class ImageTagsRequest(BaseModel):
    path: str
    tags: list[str]

class LogDeleteRequest(BaseModel):
    ids: list[str] = []
class BackupDeleteRequest(BaseModel):
    key: str = ""


def create_router(app_version: str) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login")
    async def login(authorization: str | None = Header(default=None)):
        identity = require_identity(authorization)
        return {
            "ok": True,
            "version": app_version,
            "role": identity.get("role"),
            "subject_id": identity.get("id"),
            "name": identity.get("name"),
        }

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/settings")
    async def get_settings(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.get()}

    @router.post("/api/settings")
    async def save_settings(body: SettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.update(body.model_dump(mode="python"))}

    @router.get("/api/images")
    async def get_images(request: Request, start_date: str = "", end_date: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return list_images(resolve_image_base_url(request), start_date=start_date.strip(), end_date=end_date.strip())

    @router.get("/image-thumbnails/{image_path:path}", include_in_schema=False)
    async def get_image_thumbnail(image_path: str):
        return get_thumbnail_response(image_path)

    @router.post("/api/images/delete")
    async def delete_images_endpoint(body: ImageDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return delete_images(body.paths, start_date=body.start_date.strip(), end_date=body.end_date.strip(), all_matching=body.all_matching)

    @router.post("/api/images/download")
    async def download_images_endpoint(body: ImageDownloadRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        buf = download_images_zip(body.paths)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="images.zip"'},
        )

    @router.get("/api/images/download/{image_path:path}")
    async def download_single_image_endpoint(image_path: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return get_image_download_response(image_path)

    @router.get("/api/logs")
    async def get_logs(type: str = "", start_date: str = "", end_date: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": log_service.list(type=type.strip(), start_date=start_date.strip(), end_date=end_date.strip())}

    @router.post("/api/logs/delete")
    async def delete_logs(body: LogDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return log_service.delete(body.ids)

    @router.post("/api/proxy/test")
    async def test_proxy_endpoint(body: ProxyTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        candidate = (body.url or "").strip() or config.get_proxy_settings()
        if not candidate:
            raise HTTPException(status_code=400, detail={"error": "proxy url is required"})
        return {"result": await run_in_threadpool(test_proxy, candidate)}

    @router.get("/api/storage/info")
    async def get_storage_info(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        storage = config.get_storage_backend()
        return {
            "backend": storage.get_backend_info(),
            "health": storage.health_check(),
        }

    @router.post("/api/backup/test")
    async def test_backup_connection(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.test_connection)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups")
    async def get_backups(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {
                "items": await run_in_threadpool(backup_service.list_backups),
                "state": backup_service.get_status(),
                "settings": backup_service.get_settings(),
            }
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/run")
    async def run_backup_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.run_backup)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/delete")
    async def delete_backup_endpoint(body: BackupDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            await run_in_threadpool(backup_service.delete_backup, body.key)
            return {"ok": True}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/detail")
    async def get_backup_detail(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"item": await run_in_threadpool(backup_service.get_backup_detail, key)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/download")
    async def download_backup_endpoint(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(backup_service.download_backup, key)
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        filename = str(item.get("name") or "backup.bin")
        quoted = quote(filename)
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "Content-Length": str(int(item.get("size") or 0)),
        }
        return Response(
            content=bytes(item.get("payload") or b""),
            media_type=str(item.get("content_type") or "application/octet-stream"),
            headers=headers,
        )


    @router.get("/api/images/tags")
    async def list_image_tags(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"tags": get_all_tags()}

    @router.post("/api/images/tags")
    async def update_image_tags(body: ImageTagsRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rel = body.path.strip().lstrip("/")
        if not rel:
            raise HTTPException(status_code=400, detail={"error": "path is required"})
        tags = set_tags(rel, body.tags)
        return {"ok": True, "tags": tags}

    @router.delete("/api/images/tags/{tag}")
    async def delete_image_tag(tag: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        count = delete_tag(tag)
        return {"ok": True, "removed_from": count}

    # ── Backup / Restore (local full-state) ──

    class RestoreRequest(BaseModel):
        path: str = ""

    @router.post("/api/v1/backup")
    async def create_local_backup(authorization: str | None = Header(default=None)):
        """Export toàn bộ state ra file JSON và lưu local."""
        require_admin(authorization)
        result = await run_in_threadpool(_create_backup)
        return result

    @router.get("/api/v1/backups")
    async def list_local_backups(authorization: str | None = Header(default=None)):
        """Danh sách backup local."""
        require_admin(authorization)
        return {"backups": state_backup.list_backups()}

    @router.post("/api/v1/restore")
    async def restore_from_backup(
        body: RestoreRequest,
        authorization: str | None = Header(default=None),
    ):
        """Phục hồi state từ file backup local."""
        require_admin(authorization)
        path = (body.path or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail={"error": "path is required"})

        def _restore():
            payload = state_backup.load_from_file(path)
            return state_backup.import_all(payload)

        report = await run_in_threadpool(_restore)
        return report.to_dict()

    @router.delete("/api/v1/backups/{filename}")
    async def delete_local_backup(filename: str, authorization: str | None = Header(default=None)):
        """Xóa một file backup local."""
        require_admin(authorization)
        ok = state_backup.delete_backup(filename)
        return {"ok": ok}

    # ── Health / Providers ──

    @router.get("/api/v1/health")
    async def system_health(authorization: str | None = Header(default=None)):
        """Trạng thái hệ thống: backends, providers, accounts."""
        require_admin(authorization)
        from services.account_service import account_service
        accounts = account_service.list_accounts()
        backoff_stats = rate_limit_backoff.get_stats()

        return {
            "status": "ok",
            "version": app_version,
            "accounts": {
                "total": len(accounts),
                "active": sum(1 for a in accounts if a.get("status") == "正常"),
                "limited": sum(1 for a in accounts if a.get("status") == "限流"),
                "error": sum(1 for a in accounts if a.get("status") in ("异常", "禁用")),
            },
            "backoff": backoff_stats,
            "opencode": {
                "available": opencode_provider.is_available,
            },
        }

    @router.get("/api/v1/providers")
    async def list_providers(authorization: str | None = Header(default=None)):
        """Danh sách provider đang active."""
        require_admin(authorization)
        provider_configs = config.data.get("providers") or {}

        providers = []
        for name, cfg in provider_configs.items():
            if isinstance(cfg, dict):
                providers.append({
                    "name": name,
                    "enabled": cfg.get("enabled", False),
                    "noAuth": cfg.get("noAuth", False),
                    "has_api_key": bool(cfg.get("api_key")),
                    "has_base_url": bool(cfg.get("base_url")),
                })

        return {"providers": providers}

    @router.get("/api/v1/providers/{provider_id}/models")
    async def provider_models(provider_id: str, authorization: str | None = Header(default=None)):
        """Lấy danh sách model của một provider."""
        require_admin(authorization)
        if provider_id == "opencode":
            models = opencode_provider.list_models()
            return {"models": models}
        return {"models": []}

    @router.post("/api/v1/providers/{provider_id}/test")
    async def test_provider(provider_id: str, authorization: str | None = Header(default=None)):
        """Test kết nối đến một provider."""
        require_admin(authorization)
        if provider_id == "opencode":
            available = opencode_provider.is_available
            return {"provider": provider_id, "available": available}
        raise HTTPException(status_code=404, detail={"error": f"unknown provider: {provider_id}"})

    return router
