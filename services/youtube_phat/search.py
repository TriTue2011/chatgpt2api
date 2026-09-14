# Chuyển nguyên từ add-on TriTue YouTube Player
# (github.com/TriTue2011/youtube, youtube_player/app/search.py, bản 0.6.2) — chủ máy
# 14/09/2026: "tích hợp trực tiếp trên dự án, và ha có thể kết nối đến". Giữ
# nguyên tên hàm và mã lỗi để tích hợp HA của repo nói chuyện được với c2a như
# với add-on; chỉ đổi đúng chỗ ghi "c2a:".
"""Metadata-only search providers used by the player service."""

from __future__ import annotations

import gzip
import json
import re
import subprocess
import sys
from urllib.parse import parse_qs, quote_plus, urlsplit
from urllib.request import Request, urlopen


VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{10,80}$")
YOUTUBE_URL_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
MAX_QUERY_LENGTH = 120
MAX_URL_LENGTH = 2048
ZING_ID = re.compile(r"^[A-Z0-9]{8,12}$")
ZING_SEARCH_URL = "https://ac.zingmp3.vn/v1/web/ac-suggestions"
SEARCH_RESPONSE_LIMIT = 2_000_000


class SearchUnavailableError(RuntimeError):
    """The metadata provider could not complete a search."""


def parse_search_payload(payload, *, limit):
    """Convert yt-dlp flat search output into the stable integration shape."""
    results = []
    entries = payload.get("entries") if isinstance(payload, dict) else []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "")
        if not VIDEO_ID.fullmatch(video_id):
            continue
        thumbnails = entry.get("thumbnails") or []
        thumbnail = next(
            (
                str(candidate.get("url"))
                for candidate in reversed(thumbnails)
                if isinstance(candidate, dict) and candidate.get("url")
            ),
            str(entry.get("thumbnail") or ""),
        )
        if not thumbnail:
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        duration = entry.get("duration")
        try:
            duration = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        results.append(
            {
                "source": "youtube",
                "kind": "video",
                "id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": str(entry.get("title") or video_id),
                "channel": str(entry.get("channel") or entry.get("uploader") or ""),
                "duration": duration,
                "thumbnail": thumbnail,
            }
        )
        if len(results) >= limit:
            break
    return results


def youtube_url_query(query):
    """Return ("video", id) or ("playlist", id) when the query is a YouTube link.

    Accepts what people paste from the app or browser: watch links with extra
    parameters (app=desktop, list=RD..., pp=..., si=...), youtu.be, Shorts,
    embed and live links, playlist pages, with or without "https://". A watch
    link inside a mix or playlist still means that one video.
    """
    text = str(query or "").strip()
    if not text or len(text) > MAX_URL_LENGTH or any(char.isspace() for char in text):
        return None
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlsplit(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_URL_HOSTS:
        return None
    values = parse_qs(parsed.query)
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        video_id = values.get("v", [""])[0]
    elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
        video_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    else:
        video_id = ""
    if VIDEO_ID.fullmatch(video_id):
        return ("video", video_id)
    playlist_id = values.get("list", [""])[0]
    if parsed.path == "/playlist" and PLAYLIST_ID.fullmatch(playlist_id):
        return ("playlist", playlist_id)
    return None


def _validated_query_and_limit(query, limit, *, max_length=MAX_QUERY_LENGTH):
    query = str(query or "").strip()
    if not 1 <= len(query) <= max_length:
        raise ValueError("invalid_search_query")
    try:
        limit = int(limit)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid_search_limit") from error
    if not 1 <= limit <= 30:
        raise ValueError("invalid_search_limit")
    return query, limit


def _zing_suggestions(payload):
    """Yield suggestion entries from Zing's nested autocomplete response."""
    data = payload.get("data") if isinstance(payload, dict) else None
    groups = data.get("items") if isinstance(data, dict) else []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        suggestions = group.get("suggestions")
        if isinstance(suggestions, list):
            yield from suggestions


def parse_zing_payload(payload, *, limit):
    """Convert public Zing song suggestions into the stable search shape."""
    results = []
    for entry in _zing_suggestions(payload):
        if not isinstance(entry, dict) or entry.get("type") != 1:
            continue
        song_id = str(entry.get("id") or "")
        song_url = str(entry.get("link") or "")
        parsed_url = urlsplit(song_url)
        song_host = (parsed_url.hostname or "").lower()
        if (
            not ZING_ID.fullmatch(song_id)
            or parsed_url.scheme != "https"
            or not (
                song_host == "zingmp3.vn"
                or song_host.endswith(".zingmp3.vn")
            )
            or not parsed_url.path.startswith("/bai-hat/")
            or entry.get("status") != 1
            or entry.get("privacy") != 1
            or entry.get("playStatus") != 2
        ):
            continue
        artists = entry.get("artists") or []
        artist_names = [
            str(artist.get("name"))
            for artist in artists
            if isinstance(artist, dict) and artist.get("name")
        ]
        duration = entry.get("duration")
        try:
            duration = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        results.append(
            {
                "source": "zing",
                "kind": "song",
                "id": song_id,
                "url": song_url,
                "title": str(entry.get("title") or song_id),
                "channel": ", ".join(artist_names),
                "duration": duration,
                "thumbnail": str(entry.get("thumb") or ""),
            }
        )
        if len(results) >= limit:
            break
    return results


def search_youtube(query, *, limit=20, timeout=30):
    """Search song metadata without downloading or resolving media streams.

    A pasted YouTube link looks up exactly that video (or that playlist's
    videos) instead of searching for the link's text.
    """
    link = youtube_url_query(query)
    if link is not None:
        _, limit = _validated_query_and_limit(query, limit, max_length=MAX_URL_LENGTH)
    else:
        query, limit = _validated_query_and_limit(query, limit)

    # c2a: tìm trên YouTube thường, không phải tab "Bài hát" của YouTube Music.
    # Tab đó chỉ gồm bài có hồ sơ âm nhạc chính thức, nên nhạc AI / cover đăng
    # dạng video bị lọc mất dù phát được — đo 14/09/2026 với "trót tin vào lời
    # hứa": `#songs` không có llPioQNSBLY, `ytsearch` có ở vị trí 3, cùng 3,8 s,
    # và trả thêm tên kênh + thời lượng (tab Bài hát để trống cả hai).
    if link is None:
        search_url = f"ytsearch{limit}:{query}"
    elif link[0] == "video":
        search_url = f"https://www.youtube.com/watch?v={link[1]}"
    else:
        search_url = f"https://www.youtube.com/playlist?list={link[1]}"
    # c2a: container không có lệnh `yt-dlp` trên PATH, chỉ có thư viện trong venv.
    command = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        "--ignore-errors",
        "--playlist-end",
        str(limit),
        search_url,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SearchUnavailableError("search_process_failed") from error
    if completed.returncode != 0:
        raise SearchUnavailableError("search_provider_failed")
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise SearchUnavailableError("invalid_search_response") from error
    if link is not None and link[0] == "video":
        # One video comes back as its own info object, not a list of entries.
        return parse_search_payload({"entries": [payload]}, limit=1)
    return parse_search_payload(payload, limit=limit)


def youtube_playlist_id(text):
    """ID playlist trong một link YouTube (trang /playlist hoặc link xem có `list=`)."""
    raw = str(text or "").strip()
    if not raw or len(raw) > MAX_URL_LENGTH or any(char.isspace() for char in raw):
        return None
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in YOUTUBE_URL_HOSTS:
        return None
    playlist_id = parse_qs(parsed.query).get("list", [""])[0]
    return playlist_id if PLAYLIST_ID.fullmatch(playlist_id) else None


def fetch_youtube_playlist(text, *, limit=500, timeout=120):
    """(tên, các bài) của cả một playlist YouTube công khai — để lưu nguyên playlist."""
    playlist_id = youtube_playlist_id(text)
    if playlist_id is None:
        raise ValueError("invalid_playlist_link")
    command = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist", "--dump-single-json", "--skip-download", "--no-warnings", "--ignore-errors",
        "--playlist-end", str(int(limit)),
        f"https://www.youtube.com/playlist?list={playlist_id}",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SearchUnavailableError("search_process_failed") from error
    if completed.returncode != 0:
        raise SearchUnavailableError("search_provider_failed")
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise SearchUnavailableError("invalid_search_response") from error
    title = str(payload.get("title") or "").strip() if isinstance(payload, dict) else ""
    return title or "Playlist YouTube", parse_search_payload(payload, limit=int(limit))


def search_zing(query, *, limit=20, timeout=10):
    """Search public Zing song metadata through its autocomplete endpoint."""
    query, limit = _validated_query_and_limit(query, limit)
    request = Request(
        f"{ZING_SEARCH_URL}?query={quote_plus(query)}&num={limit}",
        headers={
            "Accept": "application/json",
            "User-Agent": "TriTue-YouTube-Player/0.6",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(SEARCH_RESPONSE_LIMIT + 1)
            if len(body) > SEARCH_RESPONSE_LIMIT:
                raise SearchUnavailableError("search_response_too_large")
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
                if len(body) > SEARCH_RESPONSE_LIMIT:
                    raise SearchUnavailableError("search_response_too_large")
        payload = json.loads(body)
    except SearchUnavailableError:
        raise
    except (OSError, ValueError, gzip.BadGzipFile) as error:
        raise SearchUnavailableError("search_provider_failed") from error
    if not isinstance(payload, dict) or payload.get("err") != 0:
        raise SearchUnavailableError("invalid_search_response")
    return parse_zing_payload(payload, limit=limit)
