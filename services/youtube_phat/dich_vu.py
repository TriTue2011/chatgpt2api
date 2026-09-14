"""Lõi trình phát — phần `PlayerServer` của add-on, bỏ lớp HTTP.

Chuyển từ `youtube_player/app/server.py` (add-on 0.6.2). Lớp HTTP nằm ở
`api/youtube_phat.py`; ở đây giữ nguyên hành vi: lịch sử, phiên phát, tìm kiếm
một lượt một tiến trình, chỉ nhận link Zing vừa tìm công khai, đệm luồng 120 s.

Khác add-on (ghi "c2a:"):
- dữ liệu ở `DATA_DIR/youtube_phat/` (token, lịch sử);
- URL gốc cho loa tính theo request HA gửi tới (`public_base_url` truyền vào),
  vì c2a không biết IP LAN của máy chủ; địa chỉ LAN chủ máy đặt ở tab YouTube
  (`cai_dat.json`) thắng nếu có.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from services.config import DATA_DIR
from utils.log import logger

from .search import search_youtube, search_zing
from .session import PlaybackSession
from .streaming import (
    StreamUnavailableError,
    build_signed_stream_url,
    fetch_zing_web_keys,
    resolve_youtube_audio,
    resolve_zing_stream,
    validate_stream_target,
    validate_zing_target,
)

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{10,80}$")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
APP_VERSION = "0.6.2-c2a"
API_VERSION = "1"
MAX_HISTORY = 20

_THU_MUC = Path(DATA_DIR) / "youtube_phat"


def normalize_target(raw_target):
    target = str(raw_target or "").strip()
    video_id = target if VIDEO_ID.fullmatch(target) else None
    playlist_id = None

    if video_id is None:
        parsed = urlsplit(target)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
            raise ValueError("invalid_youtube_target")
        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/", 1)[0]
        elif parsed.path == "/watch":
            query = parse_qs(parsed.query)
            video_id = query.get("v", [""])[0]
            playlist_id = query.get("list", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/")):
            video_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        elif parsed.path == "/playlist":
            playlist_id = parse_qs(parsed.query).get("list", [""])[0]

    if VIDEO_ID.fullmatch(video_id or ""):
        target = {
            "kind": "video",
            "id": video_id,
            "embed_url": (
                f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1"
            ),
        }
        if PLAYLIST_ID.fullmatch(playlist_id or ""):
            target["playlist_id"] = playlist_id
            target["embed_url"] = (
                f"https://www.youtube-nocookie.com/embed/{video_id}"
                f"?list={playlist_id}&autoplay=1"
            )
        return target

    if PLAYLIST_ID.fullmatch(playlist_id or ""):
        return {
            "kind": "playlist",
            "id": playlist_id,
            "embed_url": (
                "https://www.youtube-nocookie.com/embed/videoseries"
                f"?list={playlist_id}&autoplay=1"
            ),
        }

    raise ValueError("invalid_youtube_target")


def resolve_integration_token(data_dir: Path) -> str:
    """Token Integration API: đọc file, chưa có thì sinh và lưu (quyền 600)."""
    token_path = Path(data_dir) / "integration_token"
    try:
        stored_token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        stored_token = ""
    if stored_token:
        return stored_token
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    temporary_path = token_path.with_suffix(".tmp")
    temporary_path.write_text(token, encoding="utf-8")
    temporary_path.chmod(0o600)
    temporary_path.replace(token_path)
    return token


class PlayerCore:
    def __init__(self, data_dir: Path, *, max_history: int = MAX_HISTORY):
        self.data_dir = Path(data_dir)
        self.max_history = max_history
        self.integration_token = resolve_integration_token(self.data_dir)
        self.history_lock = threading.Lock()
        self.player_lock = threading.Lock()
        self.search_lock = threading.Lock()
        self.zing_result_lock = threading.Lock()
        self.stream_lock = threading.Lock()
        self.zing_result_cache: dict[str, float] = {}
        self.stream_cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self.playback_session = PlaybackSession()

    @property
    def history_path(self):
        return self.data_dir / "history.json"

    def load_history(self):
        with self.history_lock:
            if not self.history_path.exists():
                return []
            try:
                value = json.loads(self.history_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            return value if isinstance(value, list) else []

    def add_history(self, target):
        with self.history_lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            history = []
            if self.history_path.exists():
                try:
                    value = json.loads(self.history_path.read_text(encoding="utf-8"))
                    history = value if isinstance(value, list) else []
                except (OSError, json.JSONDecodeError):
                    history = []
            history = [target] + [item for item in history if item != target]
            history = history[: self.max_history]
            temporary_path = self.history_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary_path.replace(self.history_path)

    def get_session(self):
        with self.player_lock:
            return self.playback_session.snapshot()

    def play(self, target, *, raw_target=""):
        with self.player_lock:
            session = self.playback_session.start(
                "youtube", raw_target or target.get("id"), fallback_item=target
            )
        self.add_history(session["item"])
        return session

    def record_session(
        self,
        source,
        target,
        *,
        output_entity_ids,
        media_content_type="",
        volume_level=None,
    ):
        if source == "youtube":
            fallback = normalize_target(target)
        elif source == "zing":
            target = self.require_public_zing_result(target)
            fallback = {"source": "zing", "kind": "song", "id": target, "url": target}
        elif source == "http":
            fallback = None
        else:
            raise ValueError("unsupported_session_source")
        with self.player_lock:
            session = self.playback_session.start(
                source,
                target,
                fallback_item=fallback,
                output_entity_ids=output_entity_ids,
                media_content_type=media_content_type,
                volume_level=volume_level,
            )
        self.add_history(session["item"])
        return session

    def stop(self, expected_revision=None):
        with self.player_lock:
            return self.playback_session.stop(expected_revision)

    def search(self, source, query, limit):
        """Run one metadata search at a time to bound child processes."""
        with self.search_lock:
            if source == "youtube":
                results = search_youtube(query, limit=limit)
                with self.player_lock:
                    self.playback_session.remember_search(source, results)
                return results
            if source == "zing":
                results = search_zing(query, limit=limit)
                self.remember_public_zing_results(results)
                with self.player_lock:
                    self.playback_session.remember_search(source, results)
                return results
            raise ValueError("invalid_search_source")

    def remember_public_zing_results(self, results, *, ttl=3600):
        """Temporarily authorize Zing URLs that passed public search filters."""
        now = time.monotonic()
        with self.zing_result_lock:
            self.zing_result_cache = {
                url: expiry
                for url, expiry in self.zing_result_cache.items()
                if expiry > now
            }
            for item in results:
                if (
                    not isinstance(item, dict)
                    or item.get("source") != "zing"
                    or item.get("kind") != "song"
                ):
                    continue
                try:
                    target_url = validate_zing_target(item.get("url"))
                except ValueError:
                    continue
                self.zing_result_cache[target_url] = now + int(ttl)

    def require_public_zing_result(self, target_url):
        """Accept only a Zing URL recently returned by public search."""
        target_url = validate_zing_target(target_url)
        now = time.monotonic()
        with self.zing_result_lock:
            expiry = self.zing_result_cache.get(target_url, 0)
            if expiry <= now:
                self.zing_result_cache.pop(target_url, None)
                raise ValueError("unverified_zing_target")
        return target_url

    def create_stream_url(self, source, target, public_base_url):
        """Create a signed LAN URL a speaker can fetch without HA credentials."""
        if not public_base_url:
            raise ValueError("public_base_url_required")
        return build_signed_stream_url(
            public_base_url,
            target,
            self.integration_token,
            source=source,
            ttl=3600,
        )

    def prepare_stream(self, source, target):
        """Authorize, resolve and briefly cache one stream before a speaker uses it."""
        if source == "zing":
            target = self.require_public_zing_result(target)
        elif source == "youtube":
            normalized = normalize_target(target)
            if normalized.get("kind") != "video" or not normalized.get("id"):
                raise ValueError("youtube_audio_requires_video")
            target = normalized["id"]
        else:
            raise ValueError("unsupported_stream_source")
        return target, self._resolve_stream(source, target)

    ZING_KEYS_TTL = 24 * 3600

    def _doc_khoa(self, ten):
        try:
            value = json.loads((self.data_dir / ten).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or not value.get("api_key") or not value.get("api_secret"):
            return None
        return value

    def zing_keys(self, *, lam_moi=False):
        """apiKey/secret của web zingmp3.vn — công khai trong mã trang, không phải
        khoá riêng, nhưng không để trong git (gitleaks chặn).

        Thứ tự: `zing_keys.json` do chủ máy đặt tay (nếu có) → bản tự lấy lưu đệm
        24 giờ (`zing_keys_web.json`) → tải lại từ zingmp3.vn. Tải hỏng thì dùng
        bản đệm cũ nếu còn; không có gì thì chỉ Zing không phát được."""
        tay = self._doc_khoa("zing_keys.json")
        if tay:
            return {"api_key": str(tay["api_key"]), "api_secret": str(tay["api_secret"])}
        dem = self._doc_khoa("zing_keys_web.json")
        if dem and not lam_moi and time.time() - float(dem.get("luc") or 0) < self.ZING_KEYS_TTL:
            return {"api_key": str(dem["api_key"]), "api_secret": str(dem["api_secret"])}
        try:
            keys = fetch_zing_web_keys()
        except StreamUnavailableError as error:
            logger.warning({"event": "youtube_phat_khong_lay_duoc_khoa_zing", "loi": str(error),
                            "dung_ban_dem_cu": bool(dem)})
            if dem:
                return {"api_key": str(dem["api_key"]), "api_secret": str(dem["api_secret"])}
            raise
        path = self.data_dir / "zing_keys_web.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tam = path.with_suffix(".json.tmp")
        tam.write_text(json.dumps({**keys, "luc": time.time()}), encoding="utf-8")
        tam.replace(path)
        return keys

    def _resolve_stream(self, source, target):
        """Resolve and briefly cache one already validated audio stream."""
        key = (source, target)
        with self.stream_lock:
            cached = self.stream_cache.get(key)
            if cached and cached[0] >= time.monotonic():
                return dict(cached[1])
        if source == "youtube":
            resolved = resolve_youtube_audio(target)
        else:
            try:
                resolved = resolve_zing_stream(target, **self.zing_keys())
            except StreamUnavailableError as error:
                if str(error) != "stream_provider_failed":
                    raise
                # Zing có thể đã đổi khoá trong mã web: lấy lại một lần rồi thử lại.
                resolved = resolve_zing_stream(target, **self.zing_keys(lam_moi=True))
        with self.stream_lock:
            now = time.monotonic()
            self.stream_cache = {
                cached_key: value
                for cached_key, value in self.stream_cache.items()
                if value[0] >= now
            }
            self.stream_cache[key] = (now + 120, dict(resolved))
        return dict(resolved)

    def resolve_stream(self, source, target):
        """Return the prepared stream, resolving again after cache expiry."""
        return self._resolve_stream(source, validate_stream_target(source, target))


def chuan_hoa_url_lan(raw) -> str:
    """Địa chỉ c2a trong LAN (`http://IP:3030`), rỗng = xoá. Chỉ nhận
    http(s)://máy[:cổng] — không tài khoản, không đường dẫn — vì loa ghép thêm
    `/yt/api/stream/...` vào sau."""
    url = str(raw or "").strip().rstrip("/")
    if not url:
        return ""
    parsed = urlsplit(url)
    try:
        parsed.port  # noqa: B018 — cổng sai (chữ, quá 65535) ném ValueError tại đây
    except ValueError as error:
        raise ValueError("url_lan_khong_hop_le") from error
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("url_lan_khong_hop_le")
    return f"{parsed.scheme}://{parsed.netloc}"


def _duong_cai_dat() -> Path:
    return core().data_dir / "cai_dat.json"


def doc_url_lan() -> str:
    try:
        value = json.loads(_duong_cai_dat().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(value.get("url_lan") or "") if isinstance(value, dict) else ""


def luu_url_lan(raw) -> str:
    url = chuan_hoa_url_lan(raw)
    path = _duong_cai_dat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tam = path.with_suffix(".json.tmp")
    tam.write_text(json.dumps({"url_lan": url}, ensure_ascii=False), encoding="utf-8")
    tam.replace(path)
    return url


def public_base_url_cau_hinh() -> str:
    """URL gốc cho loa theo địa chỉ LAN chủ máy đặt ở tab YouTube, rỗng = tự tính
    theo request. c2a không tự biết IP LAN của máy chủ (chạy trong container)."""
    url = doc_url_lan()
    return f"{url}/yt" if url else ""


_core: PlayerCore | None = None
_core_lock = threading.Lock()


def core() -> PlayerCore:
    global _core
    with _core_lock:
        if _core is None:
            _core = PlayerCore(_THU_MUC)
        return _core


def _reset_for_tests(data_dir: Path | None = None) -> PlayerCore:
    global _core
    with _core_lock:
        _core = PlayerCore(Path(data_dir) if data_dir else _THU_MUC)
        return _core
