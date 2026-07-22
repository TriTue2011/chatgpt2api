"""Ráp video local bằng ffmpeg — nối nhiều clip (vd clip Veo) thành video dài.

Không phụ đề (theo yêu cầu). Không gọi API ngoài — chỉ dùng ffmpeg có sẵn trong
image (giống services/voice dùng ffmpeg cho audio). Clip do Veo sinh
(image→video) rồi nối lại + ghép voiceover.
"""

from services.video.assemble import VideoError, assemble_slideshow, concat_clips

__all__ = ["concat_clips", "assemble_slideshow", "VideoError"]
