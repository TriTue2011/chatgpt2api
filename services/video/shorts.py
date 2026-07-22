"""Orchestration video kể chuyện: prompt → nhiều cảnh → Veo text→video mỗi cảnh
→ nối (concat_clips) thành 1 video dài. KHÔNG phụ đề.

Tái dùng: veo_adapter.generate (đã fix schema) + concat_clips (đã test).
Cảnh có thể truyền tường minh (`scenes`) hoặc để LLM tách từ `prompt`.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile

from services.image_providers.veo_video import veo_adapter
from services.video.assemble import VideoError, concat_clips


def _split_scenes(prompt: str, n: int, auth_key: str = "") -> list[str]:
    """Nhờ LLM của gateway tách `prompt` thành `n` prompt cảnh (text→video).

    Gọi nội bộ http://127.0.0.1/v1/chat/completions. Lỗi/parse hỏng → fallback
    naive (lặp prompt). Best-effort — không ném ra ngoài.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return []
    sysmsg = (
        "You split a short video idea into distinct, vivid single-shot scene "
        "prompts for a text-to-video model. Keep continuity (same characters). "
        "Return ONLY a JSON array of exactly N English scene prompts."
    )
    try:
        import httpx
        r = httpx.post(
            "http://127.0.0.1/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [
                    {"role": "system", "content": sysmsg},
                    {"role": "user", "content": f"Idea: {prompt}\nN = {n}. JSON array only."},
                ],
                "temperature": 0.7,
            },
            headers={"Authorization": f"Bearer {auth_key}"} if auth_key else {},
            timeout=120,
        )
        content = r.json()["choices"][0]["message"]["content"]
        start, end = content.find("["), content.rfind("]")
        arr = json.loads(content[start:end + 1]) if start >= 0 < end else []
        scenes = [str(s).strip() for s in arr if str(s).strip()]
        if scenes:
            return scenes[:n]
    except Exception:
        pass
    # Fallback: lặp cùng prompt cho đủ n cảnh (vẫn ra video, kém đa dạng).
    return [prompt] * max(1, n)


def make_story_video(
    credentials: dict,
    *,
    scenes: list[str] | None = None,
    prompt: str = "",
    n_scenes: int = 3,
    auth_key: str = "",
    aspect_ratio: str = "9:16",
    duration: int = 6,
    voiceover_path: str | None = None,
    out_path: str | None = None,
) -> str:
    """prompt/scenes → Veo text→video từng cảnh → nối thành 1 MP4. Trả path MP4.

    Ném VideoError nếu không cảnh nào ra clip (vd Veo 429 hết quota mọi key).
    """
    scene_prompts = [s for s in (scenes or []) if str(s).strip()] or \
        _split_scenes(prompt, n_scenes, auth_key)
    if not scene_prompts:
        raise VideoError("Không có cảnh nào để dựng (prompt rỗng / LLM tách hỏng).")

    width, height = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
    clip_paths: list[str] = []
    errors: list[str] = []
    for i, sp in enumerate(scene_prompts):
        try:
            res = veo_adapter.generate(
                {"prompt": sp, "aspect_ratio": aspect_ratio, "duration": str(duration)},
                credentials,
            )
            b64 = (res.get("data") or [{}])[0].get("b64_json")
            if not b64:
                raise VideoError("Veo không trả clip")
            fd, p = tempfile.mkstemp(suffix=f"_scene{i}.mp4")
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(b64))
            clip_paths.append(p)
        except Exception as exc:
            errors.append(f"cảnh {i + 1}: {str(exc)[:160]}")

    if not clip_paths:
        raise VideoError("Không sinh được clip nào — " + "; ".join(errors))

    return concat_clips(clip_paths, voiceover_path, out_path, width=width, height=height)
