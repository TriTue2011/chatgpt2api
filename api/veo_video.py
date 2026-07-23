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
    negative_prompt = body.get("negative_prompt")
    fps = body.get("fps") or body.get("frame_rate")
    num_frames = body.get("num_frames")
    seed = body.get("seed")
    mode = body.get("mode")
    keyframes = body.get("keyframes")
    model = str(body.get("model") or "veo/veo-3.1-generate-preview")

    if model.startswith("agnes/") or "agnes" in model:
        from services.providers.agnes import agnes_provider
        try:
            return agnes_provider.generate_video(
                prompt=prompt,
                model=model,
                aspect_ratio=aspect_ratio,
                duration=duration,
                resolution=resolution,
                image=image,
                last_frame=last_frame,
                negative_prompt=negative_prompt,
                fps=fps,
                num_frames=num_frames,
                seed=seed,
                mode=mode,
                keyframes=keyframes,
            )
        except Exception as exc:
            logger.error({"event": "agnes_video_error", "error": str(exc)})
            raise HTTPException(status_code=502, detail={"error": f"Agnes Video generation failed: {exc}"}) from exc

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


def _decode_media(b64: str) -> bytes:
    """Nhận b64 hoặc data-URL ('data:video/mp4;base64,...') → bytes."""
    import base64 as _b64
    s = str(b64 or "")
    if "," in s and s.strip().lower().startswith("data:"):
        s = s.split(",", 1)[1]
    return _b64.b64decode(s)


async def handle_video_compose(
    body: dict[str, Any],
    authorization: str | None = None,
) -> dict[str, Any]:
    """POST /v1/video/compose — nối nhiều clip (b64) → 1 video dài + voiceover.

    Body: {"clips":[b64|dataURL,...], "audio": b64?, "aspect_ratio":"9:16"?}
    """
    import base64
    import os
    import tempfile
    import time
    from pathlib import Path

    from fastapi.concurrency import run_in_threadpool
    from services.video import VideoError, concat_clips

    clips_b64 = (body or {}).get("clips") or []
    if not isinstance(clips_b64, list) or not clips_b64:
        raise HTTPException(status_code=400, detail={"error": "clips (list b64) is required"})

    tmp: list[str] = []
    audio_path = None
    try:
        for c in clips_b64:
            fd, p = tempfile.mkstemp(suffix=".mp4"); os.close(fd)
            Path(p).write_bytes(_decode_media(c)); tmp.append(p)
        clip_paths = list(tmp)
        audio_b64 = (body or {}).get("audio")
        if audio_b64:
            fd, ap = tempfile.mkstemp(suffix=".wav"); os.close(fd)
            Path(ap).write_bytes(_decode_media(audio_b64)); tmp.append(ap); audio_path = ap
        try:
            out = await run_in_threadpool(concat_clips, clip_paths, audio_path, None)
        except VideoError as exc:
            raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
        data = base64.b64encode(Path(out).read_bytes()).decode()
        try:
            os.unlink(out)
        except Exception:
            pass
        return {"created": int(time.time()), "data": [{"b64_json": data}]}
    finally:
        for p in tmp:
            try:
                os.unlink(p)
            except Exception:
                pass


async def handle_video_story(
    body: dict[str, Any],
    authorization: str | None = None,
) -> dict[str, Any]:
    """POST /v1/video/story — prompt/scenes → Veo text→video từng cảnh → nối.

    Body: {"prompt": "...", "scenes":[...]?, "n_scenes":3, "duration":6,
           "aspect_ratio":"9:16"}
    """
    import base64
    import os
    import time
    from pathlib import Path

    from fastapi.concurrency import run_in_threadpool
    from services.video import VideoError
    from services.video.shorts import make_story_video

    providers_cfg = config.data.get("providers") or {}
    pc = providers_cfg.get("gemini_free") or {}
    credentials = {"apiKey": str(pc.get("api_key") or ""), "apiKeys": pc.get("api_keys") or []}
    auth_key = str(authorization or "").replace("Bearer ", "").strip()

    scenes = (body or {}).get("scenes") or None
    prompt = str((body or {}).get("prompt") or "")
    if not scenes and not prompt:
        raise HTTPException(status_code=400, detail={"error": "prompt or scenes is required"})
    try:
        n = int((body or {}).get("n_scenes") or 3)
        dur = int((body or {}).get("duration") or 6)
    except (TypeError, ValueError):
        n, dur = 3, 6
    aspect = str((body or {}).get("aspect_ratio") or "9:16")

    try:
        out = await run_in_threadpool(
            lambda: make_story_video(
                credentials, scenes=scenes, prompt=prompt, n_scenes=n,
                auth_key=auth_key, aspect_ratio=aspect, duration=dur,
            )
        )
    except VideoError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
    data = base64.b64encode(Path(out).read_bytes()).decode()
    try:
        os.unlink(out)
    except Exception:
        pass
    return {"created": int(time.time()), "data": [{"b64_json": data}]}
