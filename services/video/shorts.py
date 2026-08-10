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
from services.video.assemble import VideoError, concat_clips, extract_last_frame


def _la_model_flow(model: str) -> bool:
    return str(model or "").strip().lower().startswith("flow/")


def _clip_bang_flow(prompt: str, *, model: str, aspect_ratio: str,
                    duration: int, khung_dau: str = "", auth_key: str = "") -> str:
    """Dựng MỘT cảnh bằng Flow, trả base64 của MP4.

    Gọi nội bộ `http://127.0.0.1/v1/video/generations` — đúng khuôn mà
    `_split_scenes` đã dùng để nhờ LLM của gateway. Đi qua endpoint đó thay vì
    gọi solver trực tiếp là để dùng lại nguyên phần xoay tài khoản, thời gian
    nghỉ sau lỗi, ghi nhật ký và lưu thư viện — viết lại ở đây là có hai bộ luật
    cùng tồn tại rồi lệch nhau.

    `khung_dau` (base64 PNG) biến cảnh này thành ảnh→video, tức mắt xích nối
    liền mạch với cảnh trước.
    """
    import httpx

    than: dict = {"model": model, "prompt": prompt,
                  "aspect_ratio": aspect_ratio, "n": 1}
    if duration:
        than["duration"] = str(duration)
    if khung_dau:
        than["image"] = khung_dau
    dau = {"Authorization": f"Bearer {auth_key}"} if auth_key else {}
    r = httpx.post("http://127.0.0.1/v1/video/generations", json=than,
                   headers=dau, timeout=600)
    if r.status_code != 200:
        raise VideoError(f"Flow trả HTTP {r.status_code}: {r.text[:200]}")
    item = ((r.json().get("data") or [{}])[0]) or {}
    b64 = str(item.get("b64_json") or "")
    if b64:
        return b64.split(",", 1)[1] if b64.startswith("data:") else b64
    # Flow trả LINK (đã ký, tải được bằng HTTP thường). Tải về ngay tại đây vì
    # link có hạn, còn ta còn phải ghép ở bước sau.
    url = str(item.get("url") or "")
    if not url.startswith(("http://", "https://")):
        raise VideoError(f"Flow không trả video: {str(item)[:200]}")
    v = httpx.get(url, timeout=300, follow_redirects=True)
    if v.status_code != 200 or not v.content:
        raise VideoError(f"tải video Flow lỗi: HTTP {v.status_code}")
    return base64.b64encode(v.content).decode()


def _khung_cuoi_b64(clip_path: str) -> str:
    """Khung hình cuối của clip → chuỗi base64 PNG, dọn file tạm ngay sau khi đọc.

    Veo nhận khung mở đầu ở dạng base64 (`instance.image.bytesBase64Encoded`),
    nên phải đọc PNG lên chứ không đưa đường dẫn.
    """
    png = extract_last_frame(clip_path)
    try:
        with open(png, "rb") as f:
            return base64.b64encode(f.read()).decode()
    finally:
        try:
            os.unlink(png)
        except OSError:
            pass


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
    chain_frames: bool = True,
    model: str = "",
) -> str:
    """prompt/scenes → dựng từng cảnh → nối thành 1 MP4. Trả path MP4.

    `chain_frames` (mặc định bật): cảnh N+1 bắt đầu từ khung hình CUỐI của cảnh
    N, nên mối nối không nhảy hình — đây là cách duy nhất để ra video 30 giây
    liền mạch từ các clip 6–10 giây. Tắt đi thì mỗi cảnh sinh độc lập, hợp khi
    câu chuyện cố tình cắt sang bối cảnh khác hẳn.

    `model` rỗng hoặc không phải `flow/*` → Veo qua API Gemini (đường cũ). Là
    `flow/*` → đi Flow qua chính endpoint `/v1/video/generations` của gateway, để
    dùng lại phần xoay tài khoản và lưu thư viện thay vì viết bản thứ hai.

    Ném VideoError nếu không cảnh nào ra clip (vd hết quota mọi key).
    """
    scene_prompts = [s for s in (scenes or []) if str(s).strip()] or \
        _split_scenes(prompt, n_scenes, auth_key)
    if not scene_prompts:
        raise VideoError("Không có cảnh nào để dựng (prompt rỗng / LLM tách hỏng).")

    width, height = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
    clip_paths: list[str] = []
    errors: list[str] = []
    khung_noi: str | None = None  # base64 PNG khung cuối của clip vừa dựng xong
    for i, sp in enumerate(scene_prompts):
        try:
            # Cảnh sau bắt đầu từ đúng khung cuối của cảnh trước, nên chỗ nối
            # không nhảy hình. Cảnh đầu không có gì để nối nên vẫn text→video.
            khung_dau = khung_noi if (chain_frames and khung_noi) else ""
            if _la_model_flow(model):
                b64 = _clip_bang_flow(sp, model=model, aspect_ratio=aspect_ratio,
                                      duration=duration, khung_dau=khung_dau,
                                      auth_key=auth_key)
            else:
                than = {"prompt": sp, "aspect_ratio": aspect_ratio,
                        "duration": str(duration)}
                if khung_dau:
                    than["image"] = khung_dau
                res = veo_adapter.generate(than, credentials)
                b64 = (res.get("data") or [{}])[0].get("b64_json")
            if not b64:
                raise VideoError("không nhận được clip")
            fd, p = tempfile.mkstemp(suffix=f"_scene{i}.mp4")
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(b64))
            clip_paths.append(p)
            # Hỏng ở bước này thì `except` dưới ghi nhận rồi đi tiếp: clip đã
            # thêm vào danh sách, `khung_noi` giữ nguyên giá trị cũ nên cảnh sau
            # vẫn nối được, chỉ là nối từ cảnh xa hơn.
            if chain_frames and i + 1 < len(scene_prompts):
                khung_noi = _khung_cuoi_b64(p)
        except Exception as exc:
            errors.append(f"cảnh {i + 1}: {str(exc)[:160]}")

    if not clip_paths:
        raise VideoError("Không sinh được clip nào — " + "; ".join(errors))

    return concat_clips(clip_paths, voiceover_path, out_path, width=width, height=height)
