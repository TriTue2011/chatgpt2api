# Chuyển nguyên từ add-on TriTue YouTube Player
# (github.com/TriTue2011/youtube, youtube_player/app/session.py, bản 0.6.2) — chủ máy
# 14/09/2026: "tích hợp trực tiếp trên dự án, và ha có thể kết nối đến". Giữ
# nguyên tên hàm và mã lỗi để tích hợp HA của repo nói chuyện được với c2a như
# với add-on; chỉ đổi đúng chỗ ghi "c2a:".
"""Clean-room playback-session model shared by the add-on API and Web UI."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit


MEDIA_PLAYER_ENTITY_ID = re.compile(r"^media_player\.[a-z0-9_]+$")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
DIRECT_AUDIO_TYPES = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m3u8": "application/vnd.apple.mpegurl",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
}
ALLOWED_DIRECT_CONTENT_TYPES = {
    *DIRECT_AUDIO_TYPES.values(),
    "application/x-mpegurl",
}
MAX_QUEUE_ITEMS = 30


def _bounded_text(value, maximum):
    text = str(value or "").strip()
    return text[:maximum]


def _safe_url(value):
    url = _bounded_text(value, 4096)
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return url


def normalize_session_item(source, item):
    """Return bounded media metadata safe to expose through Home Assistant."""
    if not isinstance(item, dict):
        item = {}
    normalized = {
        "source": source,
        "kind": _bounded_text(item.get("kind"), 32) or "song",
        "id": _bounded_text(item.get("id"), 4096),
        "url": _safe_url(item.get("url")),
        "title": _bounded_text(item.get("title") or item.get("id"), 512),
        "artist": _bounded_text(
            item.get("artist") or item.get("channel"), 512
        ),
        "album": _bounded_text(item.get("album"), 512),
        "thumbnail": _safe_url(item.get("thumbnail")),
        "duration": 0,
    }
    try:
        normalized["duration"] = max(0, int(float(item.get("duration") or 0)))
    except (TypeError, ValueError, OverflowError):
        pass
    for key in ("embed_url",):
        if value := _safe_url(item.get(key)):
            normalized[key] = value
    for key in ("playlist_id", "media_content_type"):
        if value := _bounded_text(item.get(key), 256):
            normalized[key] = value
    return normalized


def validate_output_entity_ids(value):
    """Validate, deduplicate and bound physical Home Assistant targets."""
    if not isinstance(value, list):
        raise ValueError("invalid_output_entity_ids")
    output = []
    for candidate in value:
        entity_id = str(candidate or "").strip()
        if not MEDIA_PLAYER_ENTITY_ID.fullmatch(entity_id):
            raise ValueError("invalid_output_entity_ids")
        if entity_id not in output:
            output.append(entity_id)
    if len(output) > 16:
        raise ValueError("invalid_output_entity_ids")
    return output


def build_direct_http_item(target, media_content_type=""):
    """Validate one direct HTTP audio URL without fetching the remote resource."""
    target = _safe_url(target)
    if not target or len(target) > 2048:
        raise ValueError("invalid_http_audio_target")
    parsed = urlsplit(target)
    hostname = (parsed.hostname or "").lower()
    if hostname in YOUTUBE_HOSTS or hostname.endswith(".youtube.com"):
        raise ValueError("invalid_http_audio_target")
    suffix = PurePosixPath(parsed.path).suffix.lower()
    inferred_type = DIRECT_AUDIO_TYPES.get(suffix, "audio/mpeg")
    content_type = _bounded_text(media_content_type, 128) or inferred_type
    if content_type not in ALLOWED_DIRECT_CONTENT_TYPES:
        raise ValueError("invalid_http_audio_target")
    filename = unquote(PurePosixPath(parsed.path).name) or parsed.hostname
    return normalize_session_item(
        "http",
        {
            "kind": "audio",
            "id": target,
            "url": target,
            "title": filename,
            "artist": "HTTP Audio",
            "media_content_type": content_type,
        },
    )


class PlaybackSession:
    """In-memory queue and now-playing state for all Home Assistant clients."""

    def __init__(self):
        self._search_queues = {}
        self._revision = 0
        self._session = self._idle_session(self._revision)

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @classmethod
    def _idle_session(cls, revision):
        return {
            "revision": revision,
            "state": "idle",
            "position": 0,
            "duration": 0,
            "updated_at": cls._timestamp(),
            "volume_level": None,
            "item": None,
            "queue": {"index": -1, "items": []},
            "output_entity_ids": [],
            "supported_actions": [],
        }

    def remember_search(self, source, results):
        queue = [
            normalize_session_item(source, item)
            for item in list(results or [])[:MAX_QUEUE_ITEMS]
            if isinstance(item, dict)
        ]
        self._search_queues[source] = queue

    def start(
        self,
        source,
        target,
        *,
        fallback_item=None,
        output_entity_ids=None,
        media_content_type="",
        volume_level=None,
    ):
        outputs = validate_output_entity_ids(output_entity_ids or [])
        if volume_level is not None:
            try:
                volume_level = float(volume_level)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError("invalid_volume_level") from error
            if not 0 <= volume_level <= 1:
                raise ValueError("invalid_volume_level")
        if source == "http":
            item = build_direct_http_item(target, media_content_type)
            queue = [item]
            index = 0
        else:
            fallback = normalize_session_item(source, fallback_item or {})
            target_text = str(target or "").strip()
            queue = self._search_queues.get(source, [])
            index = next(
                (
                    position
                    for position, candidate in enumerate(queue)
                    if target_text in {candidate.get("id"), candidate.get("url")}
                    or (
                        fallback.get("id")
                        and fallback.get("id") == candidate.get("id")
                    )
                ),
                -1,
            )
            if index >= 0:
                item = dict(queue[index])
                for key in ("embed_url", "playlist_id"):
                    if fallback.get(key):
                        item[key] = fallback[key]
            else:
                item = fallback
                queue = [item]
                index = 0
            if media_content_type:
                item["media_content_type"] = _bounded_text(
                    media_content_type, 128
                )
        if not item.get("id"):
            raise ValueError("invalid_session_target")
        self._revision += 1
        self._session = {
            "revision": self._revision,
            "state": "playing",
            "position": 0,
            "duration": item.get("duration", 0),
            "updated_at": self._timestamp(),
            "volume_level": volume_level,
            "item": dict(item),
            "queue": {
                "index": index,
                "items": [dict(candidate) for candidate in queue],
            },
            "output_entity_ids": outputs,
            "supported_actions": ["stop"],
        }
        return self.snapshot()

    def stop(self, expected_revision=None):
        if (
            expected_revision is not None
            and expected_revision != self._session["revision"]
        ):
            return {"stopped": False, "session": self.snapshot()}
        self._revision += 1
        self._session = self._idle_session(self._revision)
        return {"stopped": True, "session": self.snapshot()}

    def snapshot(self):
        session = self._session
        return {
            **session,
            "item": dict(session["item"]) if session["item"] else None,
            "queue": {
                "index": session["queue"]["index"],
                "items": [dict(item) for item in session["queue"]["items"]],
            },
            "output_entity_ids": list(session["output_entity_ids"]),
            "supported_actions": list(session["supported_actions"]),
        }
