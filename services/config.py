from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from pathlib import Path
import time

from services.storage.base import StorageBackend

BASE_DIR = Path(__file__).resolve().parents[1]

# Auto-detect HA addon persistent storage
# /data/options.json is the definitive signal we're in an HA addon
_IS_ADDON = Path("/data/options.json").exists()
_ADDON_DATA = Path("/config/chatgpt2api")
_LEGACY_ADDON_DATA = Path("/data/chatgpt2api")

# Migrate from old /data/ location if needed
if _IS_ADDON and _LEGACY_ADDON_DATA.exists() and not _ADDON_DATA.exists():
    import shutil as _shutil
    _ADDON_DATA.parent.mkdir(parents=True, exist_ok=True)
    try:
        _LEGACY_ADDON_DATA.rename(_ADDON_DATA)
    except OSError:
        _shutil.copytree(_LEGACY_ADDON_DATA, _ADDON_DATA)

if _IS_ADDON:
    DATA_DIR = _ADDON_DATA
elif _ADDON_DATA.exists():
    DATA_DIR = _ADDON_DATA
else:
    DATA_DIR = BASE_DIR / "data"

CONFIG_FILE = DATA_DIR / "config.json"

# On first run in addon, copy default config if not present
if _IS_ADDON and not CONFIG_FILE.exists():
    _default_config = BASE_DIR / "config.json"
    if _default_config.exists():
        import shutil
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_default_config, CONFIG_FILE)
CONFIG_DATA_FILE = DATA_DIR / "config.json"
VERSION_FILE = BASE_DIR / "VERSION"
BACKUP_STATE_FILE = DATA_DIR / "backup_state.json"

DEFAULT_BACKUP_INCLUDE = {
    "config": True,
    "register": True,
    "cpa": True,
    "sub2api": True,
    "logs": True,
    "image_tasks": True,
    "accounts_snapshot": True,
    "auth_keys_snapshot": True,
    "images": False,
}


def _normalize_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _normalize_positive_int(value: object, default: int, minimum: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(minimum, normalized)


def _normalize_backup_include(value: object) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    normalized = dict(DEFAULT_BACKUP_INCLUDE)
    for key in normalized:
        normalized[key] = _normalize_bool(source.get(key), normalized[key])
    return normalized


def _normalize_backup_settings(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": _normalize_bool(source.get("enabled"), False),
        "provider": "cloudflare_r2",
        "account_id": str(source.get("account_id") or "").strip(),
        "access_key_id": str(source.get("access_key_id") or "").strip(),
        "secret_access_key": str(source.get("secret_access_key") or "").strip(),
        "bucket": str(source.get("bucket") or "").strip(),
        "prefix": str(source.get("prefix") or "backups").strip().strip("/") or "backups",
        "interval_minutes": _normalize_positive_int(source.get("interval_minutes"), 360, 1),
        "rotation_keep": _normalize_positive_int(source.get("rotation_keep"), 10, 0),
        "encrypt": _normalize_bool(source.get("encrypt"), False),
        "passphrase": str(source.get("passphrase") or "").strip(),
        "include": _normalize_backup_include(source.get("include")),
    }


def _normalize_backup_state(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "last_started_at": str(source.get("last_started_at") or "").strip() or None,
        "last_finished_at": str(source.get("last_finished_at") or "").strip() or None,
        "last_status": str(source.get("last_status") or "idle").strip() or "idle",
        "last_error": str(source.get("last_error") or "").strip() or None,
        "last_object_key": str(source.get("last_object_key") or "").strip() or None,
    }


def _normalize_multi_api_keys(provider: dict) -> dict:
    """Keep api_key + api_keys in sync for Gemini AI Studio / multi-key providers.

    UI stores many keys in api_keys[] (one per line). Some older saves only set
    api_key. Never drop a non-empty api_keys list just because a later partial
    update only touched api_key / enabled / model.
    """
    out = dict(provider)
    keys: list[str] = []
    multi = out.get("api_keys")
    if multi is None:
        multi = out.get("apiKeys")
    if isinstance(multi, list):
        for item in multi:
            k = str(item or "").strip()
            if k and k not in keys:
                keys.append(k)
    single = str(out.get("api_key") or "").strip()
    if single and single not in keys:
        keys.insert(0, single)
    if keys:
        out["api_key"] = keys[0]
        out["api_keys"] = keys
    elif "api_keys" not in out and "apiKeys" not in out:
        # leave empty providers alone (no keys field)
        pass
    else:
        out["api_key"] = ""
        out["api_keys"] = []
    return out


def _merge_provider_config(old: dict, new: dict) -> dict:
    """Deep-merge one provider block. Preserve multi-key lists when the patch
    omits api_keys or sends an empty list while still carrying a single api_key
    that already exists in the previous list (common after image rebuild UI
    reloads with only the primary key filled)."""
    merged = {**old, **new}
    old_keys: list[str] = []
    for src in (old.get("api_keys"), old.get("apiKeys")):
        if isinstance(src, list):
            for item in src:
                k = str(item or "").strip()
                if k and k not in old_keys:
                    old_keys.append(k)
    old_single = str(old.get("api_key") or "").strip()
    if old_single and old_single not in old_keys:
        old_keys.insert(0, old_single)

    new_has_keys_field = "api_keys" in new or "apiKeys" in new
    new_keys_raw = new.get("api_keys") if "api_keys" in new else new.get("apiKeys")
    new_keys: list[str] = []
    if isinstance(new_keys_raw, list):
        for item in new_keys_raw:
            k = str(item or "").strip()
            if k and k not in new_keys:
                new_keys.append(k)
    new_single = str(new.get("api_key") or "").strip()

    if new_has_keys_field and new_keys:
        # Explicit multi-key save from UI — trust it.
        merged["api_keys"] = new_keys
        merged["api_key"] = new_keys[0]
    elif new_has_keys_field and not new_keys and new_single and old_keys:
        # Patch cleared api_keys but left one api_key that is part of the old
        # pool — keep the full pool (accidental wipe).
        if new_single in old_keys:
            merged["api_keys"] = old_keys
            merged["api_key"] = new_single
        else:
            merged["api_keys"] = [new_single]
            merged["api_key"] = new_single
    elif not new_has_keys_field and old_keys:
        # Partial update without api_keys — never drop the pool.
        merged["api_keys"] = old_keys
        if new_single and new_single not in old_keys:
            merged["api_keys"] = [new_single] + old_keys
            merged["api_key"] = new_single
        elif new_single:
            merged["api_key"] = new_single
        else:
            merged["api_key"] = old_keys[0]
    else:
        merged = _normalize_multi_api_keys(merged)

    return _normalize_multi_api_keys(merged)


@dataclass(frozen=True)
class LoadedSettings:
    auth_key: str
    refresh_account_interval_minute: int


def _normalize_auth_key(value: object) -> str:
    return str(value or "").strip()


def _is_invalid_auth_key(value: object) -> bool:
    return _normalize_auth_key(value) == ""


def _read_json_object(path: Path, *, name: str) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_dir():
        print(
            f"Warning: {name} at '{path}' is a directory, ignoring it and falling back to other configuration sources.",
            file=sys.stderr,
        )
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_settings() -> LoadedSettings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_config = _read_json_object(CONFIG_FILE, name="config.json")
    auth_key = _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY") or raw_config.get("auth-key"))

    # HA addon fallback: read from /data/options.json if auth_key still empty
    if _is_invalid_auth_key(auth_key):
        addon_options = _read_json_object(Path("/data/options.json"), name="HA addon options")
        auth_key = _normalize_auth_key(addon_options.get("auth_key") or "")

    if _is_invalid_auth_key(auth_key):
        raise ValueError(
            "❌ auth-key 未设置！\n"
            "请在环境变量 CHATGPT2API_AUTH_KEY 中设置，或者在 config.json 中填写 auth-key。"
        )

    try:
        refresh_interval = int(raw_config.get("refresh_account_interval_minute", 5))
    except (TypeError, ValueError):
        refresh_interval = 5

    return LoadedSettings(
        auth_key=auth_key,
        refresh_account_interval_minute=refresh_interval,
    )


def _normalize_thread_filters(value: object) -> dict[str, list[str]]:
    """Chuẩn hóa `thread_filters`: dict thread_key(str) -> list[str] tên nhóm.

    Bỏ khóa rỗng/không phải chuỗi và các phần tử nhóm không hợp lệ. Không kiểm
    tra tên nhóm theo capabilities (tên lạ sẽ tự bị bỏ qua khi lọc tool), giữ
    module config độc lập với tầng agent."""
    out: dict[str, list[str]] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if isinstance(v, list):
                out[k.strip()] = [g.strip() for g in v if isinstance(g, str) and g.strip()]
    return out


def _normalize_thread_user_filters(value: object) -> dict[str, list[str]]:
    """Chuẩn hóa `thread_user_filters`: dict user_key(str) -> list[str] tên nhóm.
    user_key = 'plat:bot:chat:user' hoặc 'plat:chat:user'. Cùng dạng dữ liệu như
    thread_filters (chỉ khác ngữ nghĩa: giới hạn theo NGƯỜI trong nhóm)."""
    return _normalize_thread_filters(value)


def _normalize_thread_mention_filters(value: object) -> dict[str, dict]:
    """Chuẩn hóa `thread_mention_filters`: dict thread_key -> {required: bool,
    keyword: str}. Bỏ khóa rỗng; chấp nhận cả giá trị bool (cũ) → {required, ''}."""
    out: dict[str, dict] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if isinstance(v, bool):
                out[k.strip()] = {"required": v, "keyword": ""}
            elif isinstance(v, dict):
                out[k.strip()] = {
                    "required": bool(v.get("required")),
                    "keyword": str(v.get("keyword") or "").strip(),
                }
    return out


def _normalize_thread_forward_filters(value: object) -> dict[str, dict]:
    """Chuẩn hóa `thread_forward_filters`: dict key -> {enabled, url, tag_mode}.

    Khóa = thread ('plat:bot:chat' | 'plat:chat') hoặc user ('<thread>:<user>').
    Thread bật + url → chuyển tiếp MỌI tin thread đó (bản ghi user enabled=False
    loại riêng người đó); thread không bật → user bật + url riêng = mỗi người
    một webhook khác nhau. tag_mode=True (đặt ở bản ghi user) → chỉ chuyển khi
    tin TAG bot; không tag thì AI (ChatGPT) trả lời như thường."""
    out: dict[str, dict] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if isinstance(v, dict):
                out[k.strip()] = {
                    "enabled": bool(v.get("enabled")),
                    "url": str(v.get("url") or "").strip(),
                    "tag_mode": bool(v.get("tag_mode")),
                }
    return out


def _normalize_channel_blacklist(value: object) -> dict[str, list[dict]]:
    """Chuẩn hóa `channel_blacklist`: dict platform -> list[{id, kind, name, account}].

    platform = 'zalop'|'zalo'|'tg'.
    account = bot_id / ownId (trống = blacklist CHUNG cả kênh — tương thích cũ).
    Uniqueness = (account, id) — cùng Chat ID có thể chặn riêng từng bot.
    """
    out: dict[str, list[dict]] = {}
    if isinstance(value, dict):
        for plat, items in value.items():
            if not isinstance(plat, str) or not plat.strip():
                continue
            lst: list[dict] = []
            seen: set[str] = set()
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, str):
                        it = {"id": it}
                    if not isinstance(it, dict):
                        continue
                    _id = str(it.get("id") or "").strip()
                    acc = str(it.get("account") or "").strip()
                    key = f"{acc}|{_id}"
                    if not _id or key in seen:
                        continue
                    seen.add(key)
                    lst.append({
                        "id": _id,
                        "kind": str(it.get("kind") or "").strip(),
                        "name": str(it.get("name") or "").strip(),
                        "account": acc,
                    })
            out[plat.strip()] = lst
    return out


def _normalize_bots(value: object, legacy_token: object,
                    legacy_chat_ids: object, legacy_model: object) -> list[dict]:
    """Danh sách bot đa-token:
    [{token, chat_ids, ai_model, enabled, admin_thread, admin_thread_type}].

    admin_thread / admin_thread_type: Thread ID admin RIÊNG từng bot (báo chat
    mới, /id…). Trống → fallback global telegram_admin_thread / zalo_admin_thread.

    Nếu `value` (list mới) rỗng mà có `legacy_token` → tạo 1 bot từ các field cũ
    (telegram_bot_token / zalo_bot_token …) để tương thích ngược, KHÔNG phá vỡ cấu
    hình 1-bot đang chạy. Bỏ mục thiếu token."""
    bots: list[dict] = []
    if isinstance(value, list):
        for it in value:
            if not isinstance(it, dict):
                continue
            token = str(it.get("token", "")).strip()
            if not token:
                continue
            cids = it.get("chat_ids")
            cids = [str(c).strip() for c in cids if str(c).strip()] if isinstance(cids, list) else []
            atype = str(it.get("admin_thread_type") or "0").strip()
            if atype not in {"0", "1"}:
                atype = "1" if atype.lower() in {"group", "1", "true"} else "0"
            # Multi-admin: admin_threads list; legacy admin_thread gộp vào.
            threads: list[str] = []
            raw_th = it.get("admin_threads")
            if isinstance(raw_th, list):
                for x in raw_th:
                    s = str(x).strip()
                    if s and s not in threads:
                        threads.append(s)
            one = str(it.get("admin_thread") or "").strip()
            if one and one not in threads:
                threads.append(one)
            bots.append({
                "token": token,
                "chat_ids": cids,
                "ai_model": str(it.get("ai_model", "")).strip(),
                "enabled": bool(it.get("enabled", True)),
                "admin_thread": threads[0] if threads else "",
                "admin_threads": threads,
                "admin_thread_type": atype,
                # Cài đặt RIÊNG từng bot: lệnh nhà thông minh rõ ràng chạy
                # fast-path cục bộ (không vòng qua provider AI).
                "ha_fastpath": bool(it.get("ha_fastpath", True)),
                # Toggle thông báo RIÊNG từng bot (độc lập giữa các tài khoản,
                # áp cho cả chat_ids lẫn admin_threads của bot này; toggle
                # global của kênh vẫn là công tắc tổng): cảnh báo hệ thống,
                # log tài khoản provider, báo chat/nhóm mới.
                "notify_admin_enabled": bool(it.get("notify_admin_enabled", True)),
                "account_log_enabled": bool(it.get("account_log_enabled", True)),
                "newchat_alert_enabled": bool(it.get("newchat_alert_enabled", True)),
                # Tên dễ nhớ do admin đặt (khác @username Telegram/Zalo).
                "label": str(it.get("label") or "").strip()[:64],
            })
    if not bots:
        lt = str(legacy_token or "").strip()
        if lt:
            lc = legacy_chat_ids if isinstance(legacy_chat_ids, list) else []
            bots.append({
                "token": lt,
                "chat_ids": [str(c).strip() for c in lc if str(c).strip()],
                "ai_model": str(legacy_model or "").strip(),
                "enabled": True,
                "admin_thread": "",
                "admin_threads": [],
                "admin_thread_type": "0",
                "ha_fastpath": True,
                "notify_admin_enabled": True,
                "account_log_enabled": True,
                "newchat_alert_enabled": True,
                "label": "",
            })
    return bots


def _normalize_zalo_personal_account_admins(value: object) -> dict[str, dict]:
    """Map ownId → {admin_thread, admin_thread_type, ha_fastpath} cho Zalo Cá
    Nhân đa-acc (cài đặt RIÊNG từng tài khoản)."""
    out: dict[str, dict] = {}
    if not isinstance(value, dict):
        return out
    for k, v in value.items():
        key = str(k or "").strip()
        if not key or not isinstance(v, dict):
            continue
        th = str(v.get("admin_thread") or "").strip()
        atype = str(v.get("admin_thread_type") or "0").strip()
        if atype not in {"0", "1"}:
            atype = "1" if atype.lower() in {"group", "1", "true"} else "0"
        out[key] = {"admin_thread": th, "admin_thread_type": atype,
                    "ha_fastpath": bool(v.get("ha_fastpath", True))}
    return out


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self._storage_backend: StorageBackend | None = None
        if _is_invalid_auth_key(self.auth_key):
            raise ValueError(
                "❌ auth-key 未设置！\n"
                "请按以下任意一种方式解决：\n"
                "1. 在 Render 的 Environment 变量中添加：\n"
                "   CHATGPT2API_AUTH_KEY = your_real_auth_key\n"
                "2. 或者在 config.json 中填写：\n"
                '   "auth-key": "your_real_auth_key"'
            )

    def _load(self) -> dict[str, object]:
        # Load from data dir first (persists across restarts), fallback to root
        if CONFIG_DATA_FILE.exists():
            return _read_json_object(CONFIG_DATA_FILE, name="data/config.json")
        return _read_json_object(self.path, name="config.json")

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DATA_FILE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Also sync to root if different (backward compat)
        if self.path != CONFIG_DATA_FILE:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @property
    def auth_key(self) -> str:
        # Priority: 1) ENV var  2) HA addon config  3) config.json
        key = _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY"))
        if _is_invalid_auth_key(key):
            addon_options = _read_json_object(Path("/data/options.json"), name="HA addon options")
            key = _normalize_auth_key(addon_options.get("auth_key") or "")
        if _is_invalid_auth_key(key):
            key = _normalize_auth_key(str(self.data.get("auth-key") or ""))
        return key

    @property
    def accounts_file(self) -> Path:
        return DATA_DIR / "accounts.json"

    @property
    def refresh_account_interval_minute(self) -> int:
        try:
            return int(self.data.get("refresh_account_interval_minute", 5))
        except (TypeError, ValueError):
            return 5

    @property
    def image_retention_days(self) -> int:
        try:
            return max(1, int(self.data.get("image_retention_days", 30)))
        except (TypeError, ValueError):
            return 30

    @property
    def image_poll_timeout_secs(self) -> int:
        try:
            return max(1, int(self.data.get("image_poll_timeout_secs", 300)))
        except (TypeError, ValueError):
            return 300

    @property
    def image_account_concurrency(self) -> int:
        try:
            return max(1, int(self.data.get("image_account_concurrency", 3)))
        except (TypeError, ValueError):
            return 3

    @property
    def auto_remove_invalid_accounts(self) -> bool:
        value = self.data.get("auto_remove_invalid_accounts", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def auto_remove_rate_limited_accounts(self) -> bool:
        value = self.data.get("auto_remove_rate_limited_accounts", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def usage_limit_resume_prompt(self) -> str | None:
        """Codex-style auto-resume prompt after usage limit + account switch.

        - None (unset): use built-in default resume prompt
        - "" (empty string): disable auto-resume entirely
        - Any other string: use as custom resume prompt

        Mirrors codext's [tui].usage_limit_resume_prompt config.
        """
        value = self.data.get("usage_limit_resume_prompt")
        if value is None:
            return None  # Use default
        return str(value).strip()

    @property
    def usage_snapshot_polling_enabled(self) -> bool:
        """Enable proactive rate-limit polling (codext-style 15s interval)."""
        value = self.data.get("usage_snapshot_polling_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def auto_switch_on_rate_limit(self) -> bool:
        """Auto-switch to next account when hitting usage limit (codext-style)."""
        value = self.data.get("auto_switch_on_rate_limit", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def project_docs_watch_enabled(self) -> bool:
        """Enable AGENTS.md / CLAUDE.md auto-reload watcher."""
        value = self.data.get("project_docs_watch_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def log_levels(self) -> list[str]:
        levels = self.data.get("log_levels")
        if not isinstance(levels, list):
            return []
        allowed = {"debug", "info", "warning", "error"}
        return [level for item in levels if (level := str(item or "").strip().lower()) in allowed]

    @property
    def rtk_enabled(self) -> bool:
        """RTK message compression for chatgpt. Default: True"""
        val = self.data.get("rtk_enabled", True)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in {"1", "true", "yes", "on"}
        return True

    @property
    def rtk_other_enabled(self) -> bool:
        """RTK message compression for other providers. Default: False"""
        val = self.data.get("rtk_other_enabled", False)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in {"1", "true", "yes", "on"}
        return False

    @property
    def openai_default_model(self) -> str:
        """Default model for web session routed through OpenAI API."""
        return str(self.data.get("openai_default_model") or "gpt-4o").strip()

    @property
    def sensitive_words(self) -> list[str]:
        words = self.data.get("sensitive_words")
        return [word for item in words if (word := str(item or "").strip())] if isinstance(words, list) else []

    @property
    def ai_review(self) -> dict[str, object]:
        value = self.data.get("ai_review")
        return value if isinstance(value, dict) else {}

    @property
    def global_system_prompt(self) -> str:
        return str(self.data.get("global_system_prompt") or "").strip()

    @property
    def agent_name(self) -> str:
        """Display name of the family assistant persona.

        Priority: explicit `agent_name` → the Overview display name
        (`admin_name`, e.g. "Ben Bắp") → "Tiểu Vy". So changing the name in
        the Overview tab renames the bot too, unless an explicit agent_name
        is set to override it."""
        return (str(self.data.get("agent_name") or "").strip()
                or str(self.data.get("admin_name") or "").strip()
                or "Tiểu Vy")

    @property
    def karpathy_mode(self) -> bool:
        return _normalize_bool(self.data.get("karpathy_mode"), False)

    @property
    def auto_refresh_enabled(self) -> bool:
        return _normalize_bool(self.data.get("auto_refresh_enabled"), True)

    @property
    def default_image_size(self) -> str:
        size = str(self.data.get("default_image_size") or "1792x1024").strip()
        # Validate: must be WxH format
        if "x" in size:
            return size
        return "1792x1024"

    @property
    def images_dir(self) -> Path:
        path = DATA_DIR / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def image_thumbnails_dir(self) -> Path:
        path = DATA_DIR / "image_thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_old_images(self) -> int:
        cutoff = time.time() - self.image_retention_days * 86400
        removed = 0
        for path in self.images_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        for path in sorted((p for p in self.images_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        return removed

    @property
    def base_url(self) -> str:
        url = str(
            os.getenv("CHATGPT2API_BASE_URL")
            or self.data.get("base_url")
            or ""
        ).strip().rstrip("/")
        # HA addon fallback
        if not url:
            addon_options = _read_json_object(Path("/data/options.json"), name="HA addon options")
            url = str(addon_options.get("base_url") or "").strip().rstrip("/")
        return url

    @property
    def app_version(self) -> str:
        try:
            value = VERSION_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "0.0.0"
        return value or "0.0.0"

    @property
    def cors_allow_origins(self) -> list[str]:
        """Origin được phép CORS. Config `cors_allow_origins` nhận list hoặc
        chuỗi phẩy; mặc định ["*"] (self-host LAN). Production sau tunnel nên
        whitelist domain cụ thể."""
        val = self.data.get("cors_allow_origins")
        if isinstance(val, list):
            out = [str(x).strip() for x in val if str(x).strip()]
            if out:
                return out
        if isinstance(val, str) and val.strip():
            return [s.strip() for s in val.split(",") if s.strip()]
        return ["*"]

    @property
    def telegram_notify_enabled(self) -> bool:
        value = self.data.get("telegram_notify_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def zalo_notify_enabled(self) -> bool:
        value = self.data.get("zalo_notify_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def telegram_bots(self) -> list[dict]:
        """Danh sách bot Telegram đang cấu hình (đa-token, fallback field 1-bot cũ)."""
        return _normalize_bots(self.data.get("telegram_bots"),
                               self.data.get("telegram_bot_token"),
                               self.data.get("telegram_chat_ids"),
                               self.data.get("telegram_ai_model"))

    def zalo_bots(self) -> list[dict]:
        """Danh sách bot Zalo đang cấu hình (đa-token, fallback field 1-bot cũ)."""
        return _normalize_bots(self.data.get("zalo_bots"),
                               self.data.get("zalo_bot_token"),
                               self.data.get("zalo_chat_ids"),
                               self.data.get("zalo_ai_model"))

    def get(self) -> dict[str, object]:
        data = dict(self.data)
        data["refresh_account_interval_minute"] = self.refresh_account_interval_minute
        data["image_retention_days"] = self.image_retention_days
        data["image_poll_timeout_secs"] = self.image_poll_timeout_secs
        data["image_account_concurrency"] = self.image_account_concurrency
        data["auto_remove_invalid_accounts"] = self.auto_remove_invalid_accounts
        data["auto_remove_rate_limited_accounts"] = self.auto_remove_rate_limited_accounts
        data["usage_limit_resume_prompt"] = self.usage_limit_resume_prompt
        data["usage_snapshot_polling_enabled"] = self.usage_snapshot_polling_enabled
        data["auto_switch_on_rate_limit"] = self.auto_switch_on_rate_limit
        data["project_docs_watch_enabled"] = self.project_docs_watch_enabled
        data["log_levels"] = self.log_levels
        data["sensitive_words"] = self.sensitive_words
        data["ai_review"] = self.ai_review
        data["global_system_prompt"] = self.global_system_prompt
        data["backup"] = self.get_backup_settings()
        # Auto-fill captcha-solver config from env vars so frontend always has them.
        # The solver now runs in-process inside the same container, so default to
        # localhost when nothing is configured.
        cs_url = os.getenv("CAPTCHA_SOLVER_URL", "http://127.0.0.1:8010").strip()
        cs_api_key = os.getenv("CAPTCHA_SOLVER_API_KEY", "").strip()
        if cs_url or cs_api_key:
            providers = dict(data.get("providers") or {})
            flow = dict(providers.get("flow") or {})
            if cs_url and not flow.get("captcha_solver_url"):
                flow["captcha_solver_url"] = cs_url
            if cs_api_key and not flow.get("captcha_solver_api_key"):
                flow["captcha_solver_api_key"] = cs_api_key
            providers["flow"] = flow
            data["providers"] = providers
        data["telegram_notify_enabled"] = self.telegram_notify_enabled
        data["zalo_notify_enabled"] = self.zalo_notify_enabled
        # Account log → admin bot (default on). UI: tab Zalo/Telegram/Cloudflare.
        # Per-channel keys (telegram / zalo / zalo_personal) fallback về key cũ
        # account_log_notify_enabled để giữ tương thích cấu hình đã lưu.
        def _aln_bool(raw: object) -> bool:
            if isinstance(raw, str):
                return raw.strip().lower() in {"1", "true", "yes", "on"}
            return bool(raw)

        legacy_aln = _aln_bool(self.data.get("account_log_notify_enabled", True))
        data["account_log_notify_enabled"] = legacy_aln
        for aln_key in (
            "account_log_notify_telegram",
            "account_log_notify_zalo",
            "account_log_notify_zalo_personal",
        ):
            raw_ch = self.data.get(aln_key)
            data[aln_key] = legacy_aln if raw_ch is None else _aln_bool(raw_ch)
        data["thread_filters"] = _normalize_thread_filters(self.data.get("thread_filters"))
        data["thread_user_filters"] = _normalize_thread_user_filters(self.data.get("thread_user_filters"))
        data["thread_mention_filters"] = _normalize_thread_mention_filters(self.data.get("thread_mention_filters"))
        data["thread_forward_filters"] = _normalize_thread_forward_filters(self.data.get("thread_forward_filters"))
        data["channel_blacklist"] = _normalize_channel_blacklist(self.data.get("channel_blacklist"))
        data["telegram_bots"] = self.telegram_bots()
        data["zalo_bots"] = self.zalo_bots()
        data["zalo_personal_account_admins"] = _normalize_zalo_personal_account_admins(
            self.data.get("zalo_personal_account_admins")
        )
        data.pop("auth-key", None)
        return data

    def get_proxy_settings(self) -> str:
        return str(self.data.get("proxy") or "").strip()

    def update(self, data: dict[str, object]) -> dict[str, object]:
        next_data = dict(self.data)
        incoming = dict(data or {})

        # Deep-merge providers / custom_providers so a partial save (or a UI
        # that only posts api_key) cannot wipe sibling providers or multi-key
        # lists like Gemini AI Studio api_keys[]. Shallow dict.update() used to
        # replace the entire "providers" object and reset keys after rebuilds /
        # settings saves.
        for map_key in ("providers", "custom_providers"):
            if map_key not in incoming:
                continue
            new_map = incoming.get(map_key)
            if not isinstance(new_map, dict):
                continue
            old_map = next_data.get(map_key)
            if not isinstance(old_map, dict):
                old_map = {}
            merged_map: dict[str, object] = dict(old_map)
            for pid, pcfg in new_map.items():
                if isinstance(pcfg, dict) and isinstance(merged_map.get(pid), dict):
                    merged_map[pid] = _merge_provider_config(
                        merged_map[pid],  # type: ignore[arg-type]
                        pcfg,
                    )
                else:
                    merged_map[pid] = (
                        _normalize_multi_api_keys(dict(pcfg))
                        if isinstance(pcfg, dict)
                        else pcfg
                    )
            incoming[map_key] = merged_map

        next_data.update(incoming)
        if "backup" in next_data:
            next_data["backup"] = _normalize_backup_settings(next_data.get("backup"))
        if "thread_filters" in next_data:
            next_data["thread_filters"] = _normalize_thread_filters(next_data.get("thread_filters"))
        if "thread_user_filters" in next_data:
            next_data["thread_user_filters"] = _normalize_thread_user_filters(next_data.get("thread_user_filters"))
        if "thread_mention_filters" in next_data:
            next_data["thread_mention_filters"] = _normalize_thread_mention_filters(next_data.get("thread_mention_filters"))
        if "thread_forward_filters" in next_data:
            next_data["thread_forward_filters"] = _normalize_thread_forward_filters(next_data.get("thread_forward_filters"))
        if "channel_blacklist" in next_data:
            next_data["channel_blacklist"] = _normalize_channel_blacklist(next_data.get("channel_blacklist"))
        if "telegram_bots" in next_data:
            next_data["telegram_bots"] = _normalize_bots(next_data.get("telegram_bots"), None, None, None)
        if "zalo_bots" in next_data:
            next_data["zalo_bots"] = _normalize_bots(next_data.get("zalo_bots"), None, None, None)
        if "zalo_personal_account_admins" in next_data:
            next_data["zalo_personal_account_admins"] = _normalize_zalo_personal_account_admins(
                next_data.get("zalo_personal_account_admins")
            )
        # Keep multi-key lists consistent for known API-key providers
        providers = next_data.get("providers")
        if isinstance(providers, dict):
            for pid, pcfg in list(providers.items()):
                if isinstance(pcfg, dict) and (
                    "api_key" in pcfg or "api_keys" in pcfg or "apiKeys" in pcfg
                ):
                    providers[pid] = _normalize_multi_api_keys(pcfg)
            next_data["providers"] = providers
        custom_providers = next_data.get("custom_providers")
        if isinstance(custom_providers, dict):
            for pid, pcfg in list(custom_providers.items()):
                if isinstance(pcfg, dict) and (
                    "api_key" in pcfg or "api_keys" in pcfg or "apiKeys" in pcfg
                ):
                    custom_providers[pid] = _normalize_multi_api_keys(pcfg)
            next_data["custom_providers"] = custom_providers
        next_data.pop("backup_state", None)
        self.data = next_data
        self._save()
        # Invalidate model cache when settings change (combo_models, providers, etc.)
        try:
            from services.protocol.openai_v1_models import invalidate_models_cache
            invalidate_models_cache()
        except Exception:
            pass
        return self.get()

    def get_backup_settings(self) -> dict[str, object]:
        return _normalize_backup_settings(self.data.get("backup"))

    def get_storage_backend(self) -> StorageBackend:
        """获取存储后端实例（单例）"""
        if self._storage_backend is None:
            from services.storage.factory import create_storage_backend
            self._storage_backend = create_storage_backend(DATA_DIR)
        return self._storage_backend


def load_backup_state() -> dict[str, object]:
    return _normalize_backup_state(_read_json_object(BACKUP_STATE_FILE, name="backup_state.json"))


def save_backup_state(state: dict[str, object]) -> dict[str, object]:
    normalized = _normalize_backup_state(state)
    BACKUP_STATE_FILE.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


config = ConfigStore(CONFIG_FILE)

