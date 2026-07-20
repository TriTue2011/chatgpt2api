"""
Veo Video Generation endpoint — OpenAI-compatible /v1/video/generations.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict

from services.config import config
from services.image_providers.veo_video import veo_adapter
from utils.log import logger


class VideoGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "veo/veo-3.1-generate-preview"
    prompt: str
    n: int = 1
    aspect_ratio: str = "16:9"
    duration: str | None = None
    resolution: str | None = None
    image: str | None = None  # base64 image for image→video
    last_frame: str | None = None


async def handle_video_generation(
    body: dict[str, Any],
    authorization: str | None = None,
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Handle POST /v1/video/generations."""
    prompt = str(body.get("prompt") or "")
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": "prompt is required"})

    n = max(1, min(1, int(body.get("n") or 1)))  # Veo only supports 1 per request
    aspect_ratio = str(body.get("aspect_ratio") or "16:9")
    duration = body.get("duration")
    resolution = body.get("resolution")
    image = body.get("image")
    last_frame = body.get("last_frame")
    model = str(body.get("model") or "veo/veo-3.1-generate-preview")

    if model.startswith("flow/"):
        import httpx
        from services.image_providers.flow_google import _pool_config, _next_account
        flow_cfg = _pool_config()
        from services.captcha import captcha_base
        solver_url = captcha_base(flow_cfg.get("captcha_solver_url"))
        
        acc = _next_account()
        if not acc:
            raise HTTPException(status_code=429, detail={"error": "All Flow accounts are exhausted/in cooldown."})
            
        async with httpx.AsyncClient(timeout=300) as client:
            try:
                resp = await client.post(
                    f"{solver_url}/v1/google/flow/generate-video",
                    json={
                        "project_id": acc.get("project_id", ""),
                        "profile": acc.get("profile", "google-fx"),
                        "prompt": prompt,
                        "model": model,
                        "aspect_ratio": aspect_ratio,
                        "duration": duration,
                        "count": n,
                        "image": image,
                        "last_frame": last_frame,
                        "headless": False
                    },
                    headers={"authorization": authorization or ""}
                )
                resp.raise_for_status()
                data = resp.json()
                
                try:
                    meta = data.get("data", [{}])[0].get("metadata", {})
                    credits = meta.get("remainingCredits")
                    if credits is not None:
                        from services.config import config
                        providers = config.data.get("providers") or {}
                        flow = providers.get("flow") or {}
                        accounts = flow.get("accounts") or []
                        for a in accounts:
                            if a.get("profile") == acc.get("profile") and a.get("project_id") == acc.get("project_id"):
                                a["remainingCredits"] = credits
                                config.save()
                                break
                except Exception:
                    pass
                    
                return data
            except Exception as exc:
                import logging
                logger = logging.getLogger(__name__)
                logger.error({"event": "flow_video_error", "error": str(exc)})
                raise HTTPException(status_code=502, detail={"error": f"Flow Video generation failed: {exc}"}) from exc

    # Get credentials from gemini_free config
    providers_cfg = config.data.get("providers") or {}
    provider_config = providers_cfg.get("gemini_free") or {}

    credentials = {
        "apiKey": str(provider_config.get("api_key") or ""),
        "apiKeys": provider_config.get("api_keys") or [],
    }

    all_data = []
    for idx in range(n):
        try:
            result = veo_adapter.generate(
                body={
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "duration": duration,
                    "resolution": resolution,
                    "image": image,
                    "last_frame": last_frame,
                },
                credentials=credentials,
            )
            all_data.extend(result.get("data") or [])
        except Exception as exc:
            logger.error({"event": "veo_generation_error", "error": str(exc)})
            raise HTTPException(
                status_code=500,
                detail={"error": f"Video generation failed: {exc}"},
            ) from exc

    return {
        "created": result.get("created", 0) if all_data else 0,
        "data": all_data,
    }
