from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from threading import Event

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import accounts, ai, captcha_proxy, channels, claude, image_tasks, mcp, mcp_admin, oauth, register, system, voice, zalo_personal
from api.support import resolve_web_asset, start_limited_account_watcher, require_admin
from api.veo_video import handle_video_generation
from services.backup_service import backup_service
from services.config import config
from services.karpathy_guidelines import refresh_guidelines
from services.quota_watcher import quota_watcher
from utils.log import logger


def _log_startup_failure(step: str, exc: Exception) -> None:
    """Bước khởi động phụ lỗi thì ghi warning thay vì nuốt im lặng —
    scheduler/tunnel/webhook fail âm thầm rất khó debug trên prod."""
    logger.warning({"event": "startup_step_failed", "step": step, "error": str(exc)[:200]})


def create_app() -> FastAPI:
    app_version = config.app_version

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event = Event()
        thread = start_limited_account_watcher(stop_event)
        backup_service.start()
        config.cleanup_old_images()
        # Fetch latest Karpathy guidelines + start quota watcher (fire-and-forget)
        refresh_guidelines()
        watcher_task = asyncio.create_task(quota_watcher.start())
        # Start JWT auto-refresh scheduler (ChatGPT free 28-day expiry)
        try:
            from services.jwt_refresh_scheduler import start as start_jwt_refresh
            start_jwt_refresh()
        except Exception as exc:
            _log_startup_failure("jwt_refresh_scheduler", exc)
        # Start Codex OAuth auto-refresh scheduler (8h access_token expiry)
        try:
            from services.codex_refresh_scheduler import start as start_codex_refresh
            start_codex_refresh()
        except Exception as exc:
            _log_startup_failure("codex_refresh_scheduler", exc)
        # Listen on :1455 for OpenAI Codex CLI OAuth redirects (auto-exchange)
        try:
            from services.codex_callback_listener import start as start_codex_callback
            start_codex_callback()
        except Exception as exc:
            _log_startup_failure("codex_callback_listener", exc)
        # Start models-catalogue auto-refresh (every 6h ± 30 min).
        # Keeps the dynamic gmw/* + cgw/* + codex live lists warm even
        # when nothing hits /v1/models — so the dropdown the user opens
        # tomorrow already reflects upstream's renames/additions today.
        try:
            from services.models_refresh_scheduler import start as start_models_refresh
            start_models_refresh()
        except Exception as exc:
            _log_startup_failure("models_refresh_scheduler", exc)
        # Agent reminders / recurring tasks (user-defined via chat tool `schedule`)
        try:
            from services.agent.reminders import start as start_agent_reminders
            start_agent_reminders()
        except Exception as exc:
            _log_startup_failure("agent_reminders", exc)
        # Agent heartbeat (wiki daily digest, goal nudges, HEARTBEAT.md tasks)
        try:
            from services.agent.heartbeat import start as start_agent_heartbeat
            start_agent_heartbeat()
        except Exception as exc:
            _log_startup_failure("agent_heartbeat", exc)
        # Email channel (IMAP poll → agent → SMTP reply)
        try:
            from services.email_channel import start as start_email_channel
            start_email_channel()
        except Exception as exc:
            _log_startup_failure("email_channel", exc)
        # Pre-load HA client to start background scheduler
        try:
            from services.ha_client import format_states_context
            format_states_context()  # Triggers initial device registry fetch
        except Exception as exc:
            _log_startup_failure("ha_preload", exc)
        # Prewarm MCP tools cache in background so the first chat request
        # doesn't pay the cold-start probe (e.g. a dead remote MCP that
        # times out at 5s adds latency to whoever asks first).
        try:
            from services.mcp_client import prewarm_tools_cache
            prewarm_tools_cache()
        except Exception as exc:
            _log_startup_failure("mcp_prewarm", exc)
        # Prewarm web browser contexts (ChatGPT, Gemini, Flow)
        try:
            from services.web_prewarmer import start as start_web_prewarm
            start_web_prewarm()
        except Exception as exc:
            _log_startup_failure("web_prewarmer", exc)
        # Start Cloudflare Tunnel if token configured
        try:
            from services.cloudflare_tunnel import start_tunnel, start_monitor
            start_tunnel()
            start_monitor()
        except Exception as exc:
            _log_startup_failure("cloudflare_tunnel", exc)
        # Register Telegram webhook if token configured
        try:
            from services.telegram_bot import register_webhook
            register_webhook()
        except Exception as exc:
            _log_startup_failure("telegram_webhook", exc)
        # Register Zalo webhook (chung cloudflare base với Telegram)
        try:
            from services.zalo_bot import register_webhook as _zalo_reg
            _zalo_reg()
        except Exception as exc:
            _log_startup_failure("zalo_webhook", exc)
        # Zalo Cá Nhân (bot server zca-js) — login + tự đăng ký webhook ở nền
        try:
            from services.zalo_personal import startup as _zalo_personal_start
            _zalo_personal_start()
        except Exception as exc:
            _log_startup_failure("zalo_personal", exc)
        # Start Codex-inspired usage snapshot poller (15s proactive rate-limit polling)
        try:
            from services.usage_snapshot_poller import usage_snapshot_poller
            poller_task = asyncio.create_task(usage_snapshot_poller.start())
        except Exception as exc:
            _log_startup_failure("usage_snapshot_poller", exc)
            poller_task = None
        # Initialize project docs watcher (AGENTS.md / CLAUDE.md auto-reload)
        try:
            from services.project_docs_watcher import project_docs_watcher
            project_docs_watcher.force_reload()
        except Exception as exc:
            _log_startup_failure("project_docs_watcher", exc)
        # Wyoming server nhúng — HA trỏ thẳng gateway làm TTS/STT (port 10600)
        try:
            from services.voice import wyoming_server as voice_wyoming
            voice_wyoming.start()
        except Exception as exc:
            _log_startup_failure("voice_wyoming", exc)
        # Prewarm TTS (VieNeu/Kokoro) nền — lần đọc đầu không trả cold-start 1–2s.
        try:
            from services.voice import config as _vconf
            if _vconf.tts_warmup() and _vconf.is_tts_enabled():
                import threading as _thr
                from services.voice.engines import warmup_tts as _warmup_tts

                def _bg_tts_warm() -> None:
                    try:
                        _warmup_tts()
                    except Exception as exc:
                        _log_startup_failure("tts_warmup", exc)

                _thr.Thread(target=_bg_tts_warm, name="tts-warmup",
                            daemon=True).start()
        except Exception as exc:
            _log_startup_failure("tts_warmup_start", exc)
        try:
            yield
        finally:
            try:
                from services.voice import wyoming_server as voice_wyoming
                voice_wyoming.stop()
            except Exception:
                pass
            await quota_watcher.stop()
            if poller_task is not None:
                await usage_snapshot_poller.stop()
            stop_event.set()
            thread.join(timeout=1)
            backup_service.stop()
            try:
                from services.cloudflare_tunnel import stop_tunnel
                stop_tunnel()
            except Exception as exc:
                _log_startup_failure("stop_tunnel", exc)

    from fastapi.responses import ORJSONResponse
    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan,
                  default_response_class=ORJSONResponse)
    app.add_middleware(
        CORSMiddleware,
        # Mặc định ["*"] (self-host); production sau tunnel đặt config
        # `cors_allow_origins` = danh sách domain để whitelist.
        allow_origins=config.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(ai.create_router())
    app.include_router(claude.create_router())  # standalone, OpenAI-compatible /v1/claude/*
    app.include_router(accounts.create_router())
    app.include_router(oauth.create_router())
    app.include_router(image_tasks.create_router())
    app.include_router(mcp.create_router())
    app.include_router(mcp_admin.create_router())  # proxy to internal vn-mcp-hub (127.0.0.1:8005)
    app.include_router(captcha_proxy.create_router())  # proxy to internal captcha-solver (127.0.0.1:8010)
    app.include_router(register.create_router())
    app.include_router(zalo_personal.create_router())  # kênh Zalo Cá Nhân (bot server zca-js)
    app.include_router(channels.create_router())  # hoạt động gần đây + blacklist đa kênh
    app.include_router(system.create_router(app_version))
    app.include_router(voice.create_router())
    try:
        from api import teacher as teacher_api
        app.include_router(teacher_api.create_router())
    except Exception as exc:
        _log_startup_failure("teacher_api", exc)
    if config.images_dir.exists():
        app.mount("/images", StaticFiles(directory=str(config.images_dir)), name="images")

    # Veo video generation
    @app.post("/v1/video/generations")
    async def create_video(body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await handle_video_generation(body, authorization)

    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            return FileResponse(asset)
        if full_path.strip("/").startswith("_next/"):
            raise HTTPException(status_code=404, detail="Not Found")
        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback)

    app.add_api_route("/{full_path:path}", serve_web, methods=["GET", "HEAD"], include_in_schema=False)

    return app
