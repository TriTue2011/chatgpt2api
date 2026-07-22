"""Nối nhiều clip video (vd clip Veo image→video) thành 1 video dài, bằng ffmpeg.

Chuẩn hoá mỗi clip về cùng WxH/fps rồi concat filter (an toàn khi clip lệch nhẹ),
ghép voiceover nếu có. KHÔNG phụ đề. Self-hosted — chỉ cần ffmpeg trong image.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


class VideoError(RuntimeError):
    """Lỗi ráp video — caller bắt để báo người dùng tử tế."""


def _ffprobe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, timeout=30,
        )
        return float(json.loads(out.stdout or b"{}").get("format", {}).get("duration") or 0.0)
    except Exception:
        return 0.0


def concat_clips(
    clips: list[str],
    audio_path: str | None = None,
    out_path: str | None = None,
    *,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Nối `clips` (đường dẫn video) → 1 MP4 dọc 9:16.

    - Mỗi clip được scale-cover + crop về ``width x height`` và ép ``fps`` (đồng
      nhất để concat không vỡ khi clip lệch codec/kích thước).
    - ``audio_path`` (voiceover): nếu có → THAY toàn bộ tiếng bằng voiceover; nếu
      không → giữ tiếng gốc các clip (Veo 3.1 có audio sẵn).
    - Không phụ đề.

    Trả về đường dẫn MP4. Ném VideoError nếu ffmpeg lỗi.
    """
    valid = [str(c) for c in (clips or []) if c and Path(str(c)).is_file()]
    if not valid:
        raise VideoError("Không có clip hợp lệ để nối.")
    have_audio = bool(audio_path and Path(str(audio_path)).is_file())

    if out_path is None:
        fd, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)

    cmd: list[str] = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for c in valid:
        cmd += ["-i", c]
    if have_audio:
        cmd += ["-i", str(audio_path)]

    n = len(valid)
    parts: list[str] = []
    for i in range(n):
        parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},setsar=1[v{i}]"
        )
    vlabels = "".join(f"[v{i}]" for i in range(n))

    maps: list[str] = []
    if have_audio:
        # Voiceover thay tiếng: chỉ concat video, map audio từ input cuối.
        parts.append(f"{vlabels}concat=n={n}:v=1:a=0[v]")
        maps = ["-map", "[v]", "-map", f"{n}:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        # Giữ tiếng gốc clip: concat cả video lẫn audio (clip Veo có audio).
        albls = "".join(f"[{i}:a]" for i in range(n))
        parts.append(f"{vlabels}{albls}concat=n={n}:v=1:a=1[v][a]")
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]

    cmd += ["-filter_complex", ";".join(parts)]
    cmd += maps
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-movflags", "+faststart", str(out_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=1200)
    except FileNotFoundError as exc:
        raise VideoError("Thiếu ffmpeg trong image — không ráp được video.") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoError("ffmpeg ráp video quá lâu (timeout).") from exc

    if proc.returncode != 0 or not Path(out_path).is_file() or Path(out_path).stat().st_size == 0:
        err = proc.stderr.decode("utf-8", "ignore")[:400] if proc.stderr else ""
        raise VideoError(f"ffmpeg ráp video lỗi: {err}")
    return str(out_path)


def assemble_slideshow(
    image_paths: list[str],
    audio_path: str | None = None,
    out_path: str | None = None,
    *,
    seconds_per_image: float | None = None,
    total_seconds: float | None = None,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    zoom_speed: float = 0.0015,
    zoom_max: float = 1.20,
) -> str:
    """Ảnh tĩnh → video dọc 9:16 có **Ken Burns** (zoom/pan) + voiceover. Không phụ đề.

    Self-hosted hoàn toàn (chỉ ffmpeg) — KHÔNG cần Veo/API ngoài. Thời lượng mỗi
    ảnh: `seconds_per_image`, hoặc chia đều `total_seconds`/số ảnh, hoặc theo độ
    dài voiceover, mặc định 3s/ảnh.
    """
    imgs = [str(p) for p in (image_paths or []) if p and Path(str(p)).is_file()]
    if not imgs:
        raise VideoError("Không có ảnh hợp lệ để dựng video.")
    have_audio = bool(audio_path and Path(str(audio_path)).is_file())

    if seconds_per_image and seconds_per_image > 0:
        durs = [float(seconds_per_image)] * len(imgs)
    else:
        total = float(total_seconds or 0)
        if not total and have_audio:
            total = _ffprobe_duration(str(audio_path))
        if not total:
            total = 3.0 * len(imgs)
        durs = [max(1.0, total / len(imgs))] * len(imgs)

    if out_path is None:
        fd, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)

    cmd: list[str] = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for img, d in zip(imgs, durs):
        cmd += ["-loop", "1", "-t", f"{d:.3f}", "-i", img]
    if have_audio:
        cmd += ["-i", str(audio_path)]

    n = len(imgs)
    parts: list[str] = []
    for i, d in enumerate(durs):
        frames = max(1, round(d * fps))
        # Upscale 2x trước zoompan cho mượt (bớt giật), rồi downsample về WxH.
        parts.append(
            f"[{i}:v]scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
            f"crop={width * 2}:{height * 2},"
            f"zoompan=z='min(zoom+{zoom_speed},{zoom_max})':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps},"
            f"setsar=1[v{i}]"
        )
    vlabels = "".join(f"[v{i}]" for i in range(n))
    parts.append(f"{vlabels}concat=n={n}:v=1:a=0[v]")

    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]"]
    if have_audio:
        cmd += ["-map", f"{n}:a", "-c:a", "aac", "-b:a", "192k"]
    # Độ dài = tổng thời lượng ảnh. KHÔNG dùng -shortest (voiceover ngắn sẽ cắt
    # cụt video); voiceover ngắn hơn → phát xong rồi im tới hết slideshow.
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-t", f"{sum(durs):.3f}", "-movflags", "+faststart", str(out_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=1200)
    except FileNotFoundError as exc:
        raise VideoError("Thiếu ffmpeg trong image — không dựng được video.") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoError("ffmpeg dựng slideshow quá lâu (timeout).") from exc

    if proc.returncode != 0 or not Path(out_path).is_file() or Path(out_path).stat().st_size == 0:
        err = proc.stderr.decode("utf-8", "ignore")[:400] if proc.stderr else ""
        raise VideoError(f"ffmpeg dựng slideshow lỗi: {err}")
    return str(out_path)
