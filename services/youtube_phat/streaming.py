# Chuyển nguyên từ add-on TriTue YouTube Player
# (github.com/TriTue2011/youtube, youtube_player/app/streaming.py, bản 0.6.2) — chủ máy
# 14/09/2026: "tích hợp trực tiếp trên dự án, và ha có thể kết nối đến". Giữ
# nguyên tên hàm và mã lỗi để tích hợp HA của repo nói chuyện được với c2a như
# với add-on; chỉ đổi đúng chỗ ghi "c2a:".
"""Short-lived, signed streaming support for public Zing songs and YouTube audio."""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import io
import json
import re
import time
from http.cookiejar import CookieJar
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    Request,
    build_opener,
)


STREAM_SOURCES = ("zing", "youtube")
YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"
STREAM_CACHE_DEFAULT_SECONDS = 120
STREAM_CACHE_MAX_SECONDS = 5 * 3600
STREAM_EXPIRY_MARGIN_SECONDS = 600
YOUTUBE_STREAM_HOSTS = ("googlevideo.com",)
ZING_ID = re.compile(r"^[A-Za-z0-9]{8,16}$")
ZING_API_BASE = "https://zingmp3.vn"
ZING_API_PATH = "/api/v2/song/get/streaming"
# c2a: apiKey/secret ký yêu cầu của web zingmp3.vn KHÔNG nằm trong mã — gitleaks
# chặn commit. Khoá là của chính trang web Zing, công khai trong mã JavaScript
# của trang: `fetch_zing_web_keys` lấy về lúc chạy (ai cài cũng dùng được, Zing đổi
# khoá thì tự theo); lõi (`dich_vu.PlayerCore.zing_keys`) lưu đệm và truyền vào.
ZING_HOME_URL = "https://zingmp3.vn/"
ZING_WEB_BUNDLE = re.compile(r'src="(https://[a-z0-9.-]+\.zmdcdn\.me/[^"]+/main\.min\.js)"')
# Đo 14/09/2026 trong main.min.js bản 1.20.4: `var r="<apiKey>",i="<secret>",a={…}`.
ZING_WEB_KEY_PAIR = re.compile(r'="([A-Za-z0-9]{32})",[A-Za-z_$][\w$]{0,3}="([A-Za-z0-9]{32})"')
ZING_WEB_HOSTS = ("zingmp3.vn", "zmdcdn.me")
ZING_WEB_VERSION = "1.20.4"
ZING_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
CONTENT_TYPES = {
    "aac": "audio/aac",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "wav": "audio/wav",
    "webm": "audio/webm",
}
ZING_CDN_HOSTS = ("zmdcdn.me", "zadn.vn", "zing.vn", "zingmp3.vn")


class InvalidStreamTokenError(ValueError):
    """The public stream token is invalid, tampered with, or expired."""


class StreamUnavailableError(RuntimeError):
    """The upstream public stream could not be resolved."""


class _ZingRedirectHandler(HTTPRedirectHandler):
    """Allow page redirects only to another validated public Zing song URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            validate_zing_target(newurl)
        except ValueError as error:
            raise StreamUnavailableError("unsafe_stream_redirect") from error
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


_STREAM_TOKEN = re.compile(r"/api/stream/([A-Za-z0-9_-]+)\.[A-Za-z0-9_-]+")


def stream_target(media_content_id: object) -> str | None:
    """Bài loa đang phát, đọc từ link luồng đã ký mà loa báo lên HA.

    Phần payload của token là base64 JSON thường ({exp, source, target}); chỉ chữ
    ký là bí mật. None = không phải luồng của trình phát (tivi mở ứng dụng
    YouTube gốc, nguồn khác) nên không biết là bài nào."""
    match = _STREAM_TOKEN.search(str(media_content_id or ""))
    if not match:
        return None
    try:
        data = json.loads(_b64decode(match.group(1)))
    except (ValueError, TypeError):
        return None
    target = data.get("target") if isinstance(data, dict) else None
    return str(target) if target else None


def validate_zing_target(target_url: str) -> str:
    """Return a normalized public Zing song URL or raise ``ValueError``."""
    target_url = str(target_url or "").strip()
    parsed = urlsplit(target_url)
    host = (parsed.hostname or "").lower()
    song_id = parsed.path.rsplit("/", 1)[-1].removesuffix(".html")
    if (
        parsed.scheme != "https"
        or not (host == "zingmp3.vn" or host.endswith(".zingmp3.vn"))
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/bai-hat/")
        or not ZING_ID.fullmatch(song_id)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid_zing_target")
    return target_url


def normalize_public_base_url(base_url: str) -> str:
    """Validate the LAN URL speakers use to reach this add-on.

    c2a: trình phát nằm dưới một tiền tố đường dẫn của c2a (vd `/yt`), nên
    nhận đường dẫn gốc bất kỳ — vẫn cấm tài khoản, query và fragment.
    """
    base_url = str(base_url or "").strip()
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid_public_base_url")
    return base_url.rstrip("/")


def validate_stream_target(source: str, target: str) -> str:
    """Return a normalized target for one supported audio source, or raise."""
    if source == "zing":
        return validate_zing_target(target)
    if source == "youtube":
        video_id = str(target or "").strip()
        if not YOUTUBE_VIDEO_ID.fullmatch(video_id):
            raise ValueError("invalid_youtube_target")
        return video_id
    raise ValueError("unsupported_stream_source")


def create_stream_token(
    target: str,
    secret: str,
    *,
    source: str = "zing",
    now: int | None = None,
    ttl: int = 300,
) -> str:
    """Create a signed, URL-safe token for one Zing song or YouTube video."""
    target = validate_stream_target(source, target)
    secret = str(secret or "")
    if not secret:
        raise ValueError("invalid_stream_secret")
    if not 30 <= int(ttl) <= 7200:
        raise ValueError("invalid_stream_ttl")
    issued_at = int(time.time() if now is None else now)
    payload = _b64encode(
        json.dumps(
            {"exp": issued_at + int(ttl), "source": source, "target": target},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )
    signature = _b64encode(
        hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    )
    return f"{payload}.{signature}"


def verify_stream_token(
    token: str, secret: str, *, now: int | None = None
) -> tuple[str, str]:
    """Verify a stream token and return its ``(source, target)`` pair."""
    try:
        payload, provided_signature = str(token).split(".", 1)
        expected_signature = _b64encode(
            hmac.new(str(secret).encode(), payload.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(provided_signature, expected_signature):
            raise InvalidStreamTokenError("invalid_stream_token")
        value = json.loads(_b64decode(payload))
        current_time = int(time.time() if now is None else now)
        source = value.get("source")
        if source not in STREAM_SOURCES or int(value.get("exp", 0)) < current_time:
            raise InvalidStreamTokenError("expired_stream_token")
        return source, validate_stream_target(source, value.get("target"))
    except InvalidStreamTokenError:
        raise
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise InvalidStreamTokenError("invalid_stream_token") from error


def build_signed_stream_url(
    public_base_url: str,
    target: str,
    secret: str,
    *,
    source: str = "zing",
    now: int | None = None,
    ttl: int = 300,
) -> str:
    """Build the short-lived URL passed to a Home Assistant media player."""
    base_url = normalize_public_base_url(public_base_url)
    token = create_stream_token(target, secret, source=source, now=now, ttl=ttl)
    return f"{base_url}/api/stream/{token}"


def _read_limited_response(response, *, limit=1_000_000) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise StreamUnavailableError("stream_response_too_large")
    if str(response.headers.get("Content-Encoding") or "").lower() == "gzip":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                body = compressed.read(limit + 1)
        except (OSError, EOFError) as error:
            raise StreamUnavailableError("invalid_stream_response") from error
        if len(body) > limit:
            raise StreamUnavailableError("stream_response_too_large")
    return body


def extract_zing_web_keys(script: str) -> dict | None:
    """apiKey/secret từ mã JavaScript của web Zing, hoặc None nếu không thấy."""
    match = ZING_WEB_KEY_PAIR.search(str(script or ""))
    if not match:
        return None
    return {"api_key": match.group(1), "api_secret": match.group(2)}


def fetch_zing_web_keys(*, timeout: int = 20) -> dict:
    """Tải trang chủ zingmp3.vn, tìm bó mã main.min.js, trích apiKey/secret."""

    def _get(url: str, limit: int) -> str:
        with build_opener().open(
            Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": ZING_USER_AGENT}),
            timeout=timeout,
        ) as response:
            host = (urlsplit(response.geturl()).hostname or "").lower()
            if not any(host == h or host.endswith(f".{h}") for h in ZING_WEB_HOSTS):
                raise StreamUnavailableError("unsafe_stream_redirect")
            return _read_limited_response(response, limit=limit).decode("utf-8", "replace")

    try:
        bundle = ZING_WEB_BUNDLE.search(_get(ZING_HOME_URL, 1_000_000))
        keys = extract_zing_web_keys(_get(bundle.group(1), 8_000_000)) if bundle else None
    except StreamUnavailableError:
        raise
    except (OSError, ValueError) as error:
        raise StreamUnavailableError("zing_keys_unavailable") from error
    if not keys:
        raise StreamUnavailableError("zing_keys_unavailable")
    return keys


def _cookie_web_version(cookie_jar: CookieJar) -> str:
    for cookie in cookie_jar:
        if cookie.name == "zmp3_app_version.1" and re.fullmatch(
            r"\d+\.\d+\.\d+", str(cookie.value or "")
        ):
            return cookie.value
    return ZING_WEB_VERSION


def _build_zing_api_url(
    song_id: str, version: str, current_time: int, api_key: str, api_secret: str
) -> str:
    params = {
        "id": song_id,
        "ctime": str(current_time),
        "version": version,
    }
    canonical = "".join(f"{key}={params[key]}" for key in sorted(params))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    signature = hmac.new(
        api_secret.encode(),
        f"{ZING_API_PATH}{digest}".encode(),
        hashlib.sha512,
    ).hexdigest()
    query = urlencode({**params, "apiKey": api_key, "sig": signature})
    return f"{ZING_API_BASE}{ZING_API_PATH}?{query}"


ZING_PLAYLIST_PATH = "/api/v2/page/get/playlist"


def zing_playlist_id(text: str) -> str | None:
    """ID album/playlist trong link Zing MP3 (/album/…/ID.html, /playlist/…/ID.html)."""
    parsed = urlsplit(str(text or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (host == "zingmp3.vn" or host.endswith(".zingmp3.vn")):
        return None
    if not parsed.path.startswith(("/album/", "/playlist/")):
        return None
    playlist_id = parsed.path.rsplit("/", 1)[-1].removesuffix(".html")
    return playlist_id if ZING_ID.fullmatch(playlist_id) else None


def fetch_zing_playlist(
    text: str, *, api_key: str, api_secret: str, timeout: int = 20, now: int | None = None
) -> tuple[str, list[dict]]:
    """(tên, các bài công khai) của một album/playlist Zing MP3.

    Cùng cách ký như luồng bài hát, chỉ khác đường dẫn API. Đo 14/09/2026 với album
    n1mqFnz65jGl: 28 bài, mỗi bài có `streamingStatus` (1 nghe được, 2 là VIP — bỏ)."""
    playlist_id = zing_playlist_id(text)
    if playlist_id is None:
        raise ValueError("invalid_playlist_link")
    if not api_key or not api_secret:
        raise StreamUnavailableError("stream_provider_failed")
    cookie_jar = CookieJar()
    opener = build_opener(_ZingRedirectHandler(), HTTPCookieProcessor(cookie_jar))
    try:
        with opener.open(Request(ZING_HOME_URL, headers={"User-Agent": ZING_USER_AGENT}), timeout=timeout) as response:
            response.read(1)
        params = {"id": playlist_id, "ctime": str(int(round(time.time()) if now is None else now)),
                  "version": _cookie_web_version(cookie_jar)}
        digest = hashlib.sha256("".join(f"{k}={params[k]}" for k in sorted(params)).encode()).hexdigest()
        signature = hmac.new(api_secret.encode(), f"{ZING_PLAYLIST_PATH}{digest}".encode(), hashlib.sha512).hexdigest()
        url = f"{ZING_API_BASE}{ZING_PLAYLIST_PATH}?{urlencode({**params, 'apiKey': api_key, 'sig': signature})}"
        with opener.open(Request(url, headers={
            "Accept": "application/json", "Accept-Encoding": "gzip", "Referer": ZING_HOME_URL,
            "User-Agent": ZING_USER_AGENT,
        }), timeout=timeout) as response:
            payload = json.loads(_read_limited_response(response, limit=4_000_000))
    except StreamUnavailableError:
        raise
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise StreamUnavailableError("stream_provider_failed") from error
    data = payload.get("data") if isinstance(payload, dict) and payload.get("err") == 0 else None
    if not isinstance(data, dict):
        raise StreamUnavailableError("stream_provider_failed")
    items = []
    for song in ((data.get("song") or {}).get("items") or []):
        if not isinstance(song, dict) or song.get("streamingStatus") != 1:
            continue
        link = str(song.get("link") or "")
        song_id = str(song.get("encodeId") or "")
        if not link.startswith("/bai-hat/") or not ZING_ID.fullmatch(song_id):
            continue
        items.append({
            "source": "zing", "kind": "song", "id": song_id, "url": f"https://zingmp3.vn{link}",
            "title": str(song.get("title") or song_id), "channel": str(song.get("artistsNames") or ""),
            "duration": song.get("duration"), "thumbnail": str(song.get("thumbnailM") or song.get("thumbnail") or ""),
        })
    return str(data.get("title") or "Album Zing MP3"), items


def resolve_zing_stream(
    target_url: str,
    *,
    api_key: str,
    api_secret: str,
    timeout: int = 30,
    now: int | None = None,
) -> dict:
    """Resolve one browser-playable public Zing song without downloading it."""
    target_url = validate_zing_target(target_url)
    if not api_key or not api_secret:
        raise StreamUnavailableError("zing_keys_missing")
    cookie_jar = CookieJar()
    opener = build_opener(_ZingRedirectHandler(), HTTPCookieProcessor(cookie_jar))
    try:
        with opener.open(
            Request(
                target_url,
                headers={
                    "Accept-Encoding": "identity",
                    "User-Agent": ZING_USER_AGENT,
                },
            ),
            timeout=timeout,
        ) as response:
            redirected_target = validate_zing_target(response.geturl())
            response.read(1)

        song_id = urlsplit(redirected_target).path.rsplit("/", 1)[-1].removesuffix(
            ".html"
        )
        api_url = _build_zing_api_url(
            song_id,
            _cookie_web_version(cookie_jar),
            int(round(time.time()) if now is None else now),
            api_key,
            api_secret,
        )
        with opener.open(
            Request(
                api_url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Encoding": "gzip",
                    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                    "Referer": redirected_target,
                    "User-Agent": ZING_USER_AGENT,
                },
            ),
            timeout=timeout,
        ) as response:
            payload = json.loads(_read_limited_response(response))
    except StreamUnavailableError:
        raise
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise StreamUnavailableError("stream_provider_failed") from error

    if (
        not isinstance(payload, dict)
        or payload.get("err") != 0
        or not isinstance(payload.get("data"), dict)
    ):
        raise StreamUnavailableError("stream_provider_failed")

    streams = payload["data"]
    stream_url = next(
        (
            str(streams.get(quality) or "")
            for quality in ("320", "128")
            if str(streams.get(quality) or "").startswith(("http://", "https://"))
        ),
        "",
    )
    parsed_stream = urlsplit(stream_url)
    stream_host = (parsed_stream.hostname or "").lower()
    if (
        parsed_stream.scheme not in {"http", "https"}
        or not any(
            stream_host == suffix or stream_host.endswith(f".{suffix}")
            for suffix in ZING_CDN_HOSTS
        )
    ):
        raise StreamUnavailableError("unsupported_stream_format")
    extension = parsed_stream.path.rsplit(".", 1)[-1].lower()
    return {
        "url": stream_url,
        "headers": {
            "Referer": redirected_target,
            "User-Agent": ZING_USER_AGENT,
        },
        "content_type": CONTENT_TYPES.get(extension, "audio/mpeg"),
    }


def _youtube_audio_format(info: dict) -> dict:
    """Pick the concrete audio format yt-dlp selected from its JSON output."""
    if info.get("url"):
        return info
    requested = info.get("requested_downloads")
    if isinstance(requested, list) and requested and isinstance(requested[0], dict):
        return requested[0]
    formats = info.get("formats")
    if isinstance(formats, list):
        audio_only = [
            item
            for item in formats
            if isinstance(item, dict)
            and item.get("url")
            and item.get("acodec") not in (None, "none")
            and item.get("vcodec") in (None, "none")
        ]
        if audio_only:
            return audio_only[-1]
    raise StreamUnavailableError("stream_provider_failed")


def extract_with_yt_dlp(watch_url: str, timeout: int) -> dict:
    """Chạy yt-dlp ngay trong tiến trình, trả đúng thứ ``--dump-single-json`` in ra.

    Đo 14/09/2026 trong container c2a: mở tiến trình yt-dlp mới mất 4,8–7,1 giây
    mỗi bài (riêng nạp yt_dlp 2,2 giây); cùng việc đó trong tiến trình sống lâu
    chỉ 1,1–1,8 giây. Khoảng chờ đó là lúc loa chưa kêu và mỗi lần bấm bài kế.
    """
    import yt_dlp  # nạp lần đầu dùng, sau đó Python giữ sẵn

    options = {
        "format": YOUTUBE_AUDIO_FORMAT,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": timeout,
        "extractor_retries": 1,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.sanitize_info(ydl.extract_info(watch_url, download=False))


def stream_cache_seconds(stream_url: str, *, now: float | None = None) -> int:
    """Link luồng đã giải được dùng lại bao lâu.

    Link googlevideo tự mang hạn ``expire`` (khoảng 6 giờ tới); dùng lại tới sát
    hạn đó thì phát lại, tua, loa hỏi từng đoạn không phải giải lại. Link không
    có hạn giữ 2 phút như cũ."""
    try:
        expire = int(parse_qs(urlsplit(str(stream_url)).query).get("expire", [""])[0])
    except ValueError:
        return STREAM_CACHE_DEFAULT_SECONDS
    remaining = expire - int(time.time() if now is None else now) - STREAM_EXPIRY_MARGIN_SECONDS
    return max(0, min(remaining, STREAM_CACHE_MAX_SECONDS))


def resolve_youtube_audio(
    video_id: str, *, timeout: int = 20, extractor=extract_with_yt_dlp
) -> dict:
    """Resolve one browser-free direct audio stream for a public YouTube video.

    yt-dlp extracts a short-lived, IP-bound ``googlevideo.com`` URL; the caller
    relays it through c2a so speakers never fetch YouTube directly.
    """
    video_id = validate_stream_target("youtube", video_id)
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        info = extractor(watch_url, timeout)
    except Exception as error:  # yt-dlp ném nhiều loại lỗi khác nhau cho cùng một hỏng
        raise StreamUnavailableError("stream_provider_failed") from error
    if not isinstance(info, dict):
        raise StreamUnavailableError("invalid_stream_response")

    selected = _youtube_audio_format(info)
    stream_url = str(selected.get("url") or "")
    parsed_stream = urlsplit(stream_url)
    stream_host = (parsed_stream.hostname or "").lower()
    if parsed_stream.scheme not in {"http", "https"} or not any(
        stream_host == suffix or stream_host.endswith(f".{suffix}")
        for suffix in YOUTUBE_STREAM_HOSTS
    ):
        raise StreamUnavailableError("unsupported_stream_format")

    extension = str(selected.get("ext") or "").lower()
    headers = {"User-Agent": ZING_USER_AGENT}
    upstream_headers = selected.get("http_headers") or info.get("http_headers")
    if isinstance(upstream_headers, dict):
        headers = {
            str(key): str(value)
            for key, value in upstream_headers.items()
            if key and value
        } or headers
    return {
        "url": stream_url,
        "headers": headers,
        "content_type": CONTENT_TYPES.get(extension, "audio/mp4"),
    }
