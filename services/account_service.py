from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Condition, Lock
from typing import Any
from datetime import datetime, timedelta, timezone

from services.config import config
from services.log_service import (
    LOG_TYPE_ACCOUNT,
    log_service,
)
from services.rate_limit_backoff import rate_limit_backoff
from services.storage.base import StorageBackend
from utils.helper import anonymize_token
from utils.log import logger

# Token audience values for routing
_TOKEN_AUDIENCE_CHATGPT = "chatgpt.com"
_TOKEN_AUDIENCE_OPENAI_API = "api.openai.com"

# Paid ChatGPT plans. Any account whose `plan` (chatgpt_plan_type) is one of
# these belongs to the PAID/Codex group — NOT the free pool — because the
# subscription unlocks Codex. Decided 2026-05-29 with đại ca: "acc plus, go,
# business là 1 vì nó có codex". Note `go` lives here (it used to be wrongly
# merged into free in api/accounts.py).
PAID_PLANS = {"plus", "pro", "go", "business", "team", "enterprise"}

# Canonical account groups. There are exactly four logical pools and every
# account maps to exactly one. Keeping the mapping in ONE place lets the
# free / codex / openai providers stay fully independent instead of each
# re-deriving the group from ad-hoc `type.split(",")` checks.
GROUP_FREE = "free"
GROUP_CODEX = "codex"
GROUP_OPENAI = "openai"
GROUP_ANTIGRAVITY = "antigravity"
GROUP_CLAUDE = "claude"
# Captcha-solver web-session pools (profile name = access_token). Each is a
# separate pool so a quota-exhausted gemini_web_api profile never gets picked
# as a free chatgpt account by get_text_access_token().
GROUP_GEMINI_WEB_API = "gemini_web_api"
GROUP_GEMINI_WEB = "gemini_web"
GROUP_CHATGPT_WEB = "chatgpt_web"
WEB_SESSION_GROUPS = (GROUP_CLAUDE, GROUP_GEMINI_WEB_API, GROUP_GEMINI_WEB, GROUP_CHATGPT_WEB)


def account_group(account: dict | None) -> str:
    """Classify an account into exactly one logical pool.

    Priority order (first match wins):
      1. antigravity  — Google Cloud companion tokens (type contains it)
      2. codex        — explicit `codex` type tag (real Codex OAuth token)
      3. openai       — raw OpenAI API key (sk-…) or `standard`/`openai` type
                        (api.openai.com); stays here even on a paid plan
      4. codex        — paid plan (plus/go/business…) on a chatgpt.com web acct
      5. free         — everything else (chatgpt.com web JWT, plan=free)

    Type tags beat plan: an api.openai.com token tagged `standard` can only hit
    api.openai.com, so a plus/go subscription on it must NOT divert it to the
    Codex/web pool. A paid-plan chatgpt.com WEB account (no api-only tag) lands
    in codex and the route picks transport later — "phân nhóm theo plan, tự đổi
    route".
    """
    if not isinstance(account, dict):
        return GROUP_FREE
    types = {t.strip() for t in str(account.get("type") or "").split(",") if t.strip()}
    plan = str(account.get("plan") or "").strip().lower()
    token = str(account.get("access_token") or "")

    if GROUP_ANTIGRAVITY in types:
        return GROUP_ANTIGRAVITY
    # Claude.ai web session (sessionKey) — completely separate pool.
    if "claude" in types:
        return GROUP_CLAUDE
    # Other captcha-solver web-session pools (gemini.google.com via cookie or
    # DOM scrape, chatgpt.com web). Each keeps its own pool so rotation +
    # quota-failure tracking stay isolated, exactly like Claude.
    if GROUP_GEMINI_WEB_API in types:
        return GROUP_GEMINI_WEB_API
    if GROUP_GEMINI_WEB in types:
        return GROUP_GEMINI_WEB
    if GROUP_CHATGPT_WEB in types:
        return GROUP_CHATGPT_WEB
    # Explicit Codex-token tag wins outright.
    if "codex" in types:
        return GROUP_CODEX
    # Explicit OpenAI-API account (sk- key, or `standard`/`openai` JWT bound to
    # api.openai.com) stays in the openai group REGARDLESS of subscription plan:
    # such a token can ONLY call api.openai.com — never chatgpt.com web nor the
    # Codex responses API — so a plus/go plan on it must not divert it to codex.
    if token.startswith("sk-") or "standard" in types or "openai" in types:
        return GROUP_OPENAI
    # A chatgpt.com web account on a paid subscription → codex/paid pool.
    if plan in PAID_PLANS:
        return GROUP_CODEX
    return GROUP_FREE


def _decode_jwt_payload(access_token: str) -> dict | None:
    """Best-effort base64url decode of the JWT payload segment. Returns
    None on any error so callers can fall back to their existing path."""
    if not access_token or not access_token.startswith("eyJ"):
        return None
    try:
        import base64, json
        parts = access_token.split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def detect_token_audience(access_token: str) -> str:
    """Decode JWT to determine which API the token works with."""
    payload = _decode_jwt_payload(access_token)
    if not payload:
        return "unknown"
    try:
        aud = payload.get("aud", "")
        if isinstance(aud, list):
            aud = aud[0] if aud else ""
        aud_str = str(aud).lower()
        if "api.openai.com" in aud_str:
            return _TOKEN_AUDIENCE_OPENAI_API
        if "chatgpt.com" in aud_str:
            return _TOKEN_AUDIENCE_CHATGPT
    except Exception:
        pass
    return "unknown"

# Status migration: Chinese → English (backward compatible)
_STATUS_MIGRATION = {
    "正常": "active",
    "限流": "limited",
    "异常": "error",
    "禁用": "disabled",
}
_STATUS_REVERSE = {v: k for k, v in _STATUS_MIGRATION.items()}

DISPLAY_STATUS = {
    "active": "Hoạt động",
    "limited": "Giới hạn",
    "error": "Lỗi",
    "disabled": "Vô hiệu",
}


# NoAuth providers — virtual connections (port from 9router FREE_PROVIDERS)
NO_AUTH_PROVIDERS = {"opencode"}


class AccountService:
    """账号池服务，使用 token -> account 的 dict 保存账号。"""

    def __init__(self, storage_backend: StorageBackend):
        self.storage = storage_backend
        self._lock = Lock()
        self._image_slot_condition = Condition(self._lock)
        self._index = 0
        self._accounts = self._load_accounts()
        self._image_inflight: dict[str, int] = {}

    def _load_accounts(self) -> dict[str, dict]:
        accounts = self.storage.load_accounts()
        loaded = {
            normalized["access_token"]: normalized
            for item in accounts
            if (normalized := self._normalize_account(item)) is not None
        }
        # ChatGPT free: 1 email = 1 account. Merge duplicates created by JWT
        # refresh / recovery that keyed only on access_token.
        deduped, removed = self._dedupe_free_by_email(loaded)
        if removed:
            logger.info({
                "event": "free_accounts_deduped_on_load",
                "removed": removed,
                "remaining_free": sum(
                    1 for a in deduped.values() if account_group(a) == GROUP_FREE
                ),
            })
            # Persist cleaned pool so duplicates don't reappear next boot
            try:
                self.storage.save_accounts(list(deduped.values()))
            except Exception:
                pass
        return deduped

    def _save_accounts(self) -> None:
        self.storage.save_accounts(list(self._accounts.values()))

    @staticmethod
    def _email_from_token_or_account(access_token: str = "", account: dict | None = None) -> str:
        """Best-effort email for free-pool identity (lowercase)."""
        if account:
            e = str(account.get("email") or "").strip().lower()
            if e and "@" in e:
                return e
            access_token = str(account.get("access_token") or access_token or "")
        if access_token.startswith("eyJ"):
            payload = _decode_jwt_payload(access_token)
            if payload:
                claim = payload.get("email")
                if not (isinstance(claim, str) and "@" in claim):
                    profile = payload.get("https://api.openai.com/profile") or {}
                    if isinstance(profile, dict):
                        claim = profile.get("email")
                if isinstance(claim, str) and "@" in claim:
                    return claim.strip().lower()
        return ""

    @classmethod
    def _dedupe_free_by_email(cls, accounts: dict[str, dict]) -> tuple[dict[str, dict], int]:
        """Keep at most one free-pool account per email. Prefer active + newer JWT exp."""
        out: dict[str, dict] = {}
        free_by_email: dict[str, tuple[str, dict]] = {}
        removed = 0

        def _rank(acc: dict) -> tuple:
            st = str(acc.get("status") or "")
            st_score = {"active": 3, "limited": 2, "error": 1, "disabled": 0}.get(st, 1)
            exp = 0
            tok = str(acc.get("access_token") or "")
            payload = _decode_jwt_payload(tok)
            if payload:
                try:
                    exp = int(payload.get("exp") or 0)
                except Exception:
                    exp = 0
            return (st_score, exp)

        for token, acc in accounts.items():
            if account_group(acc) != GROUP_FREE:
                out[token] = acc
                continue
            email = cls._email_from_token_or_account(token, acc)
            if not email:
                # Keep orphan free rows (no email) only if active; drop dead blanks
                if str(acc.get("status") or "") in {"error", "disabled", "limited"}:
                    removed += 1
                    continue
                out[token] = acc
                continue
            # Ensure email field set for UI
            if not acc.get("email"):
                acc = dict(acc)
                acc["email"] = email
            prev = free_by_email.get(email)
            if prev is None or _rank(acc) > _rank(prev[1]):
                if prev is not None:
                    removed += 1
                free_by_email[email] = (token, acc)
            else:
                removed += 1
        for token, acc in free_by_email.values():
            out[token] = acc
        return out, removed

    def find_free_by_email(self, email: str) -> dict | None:
        """Return free-pool account matching email, or None."""
        email = str(email or "").strip().lower()
        if not email:
            return None
        with self._lock:
            for acc in self._accounts.values():
                if account_group(acc) != GROUP_FREE:
                    continue
                if self._email_from_token_or_account(account=acc) == email:
                    return dict(acc)
        return None

    def upsert_free_token(self, access_token: str, extra: dict | None = None) -> dict:
        """Insert or replace free-pool account by email (never create duplicate free rows).

        If a free account with the same email already exists, re-key to the new
        access_token and merge fields. Does NOT invent accounts for unknown
        emails from captcha profiles — caller must intend to add.
        """
        access_token = str(access_token or "").strip()
        if not access_token:
            return {"added": 0, "updated": 0, "skipped": 1}
        email = self._email_from_token_or_account(access_token)
        if extra and extra.get("email"):
            email = str(extra.get("email") or email).strip().lower() or email
        with self._lock:
            existing_token = None
            existing = None
            if email:
                for t, acc in list(self._accounts.items()):
                    if account_group(acc) != GROUP_FREE:
                        continue
                    if self._email_from_token_or_account(t, acc) == email:
                        existing_token, existing = t, acc
                        break
            base = dict(existing) if existing else {}
            base.update(extra or {})
            base["access_token"] = access_token
            base["type"] = "free"
            if email:
                base["email"] = email
            if not existing:
                base.setdefault("status", "active")
            account = self._normalize_account(base)
            if account is None:
                return {"added": 0, "updated": 0, "skipped": 1}
            if existing_token and existing_token != access_token:
                self._accounts.pop(existing_token, None)
            self._accounts[access_token] = account
            self._save_accounts()
            replaced = bool(existing and existing_token and existing_token != access_token)
            result = {
                "added": 0 if existing else 1,
                "updated": 1 if existing else 0,
                "skipped": 0,
            }
        # log + items OUTSIDE lock (list_accounts also takes _lock)
        if result["updated"]:
            log_service.add(
                LOG_TYPE_ACCOUNT,
                "Cập nhật ChatGPT free (theo email, không trùng)",
                {"provider": "free", "email": email, "replaced": replaced},
            )
        else:
            log_service.add(LOG_TYPE_ACCOUNT, "Thêm ChatGPT free",
                            {"provider": "free", "email": email})
        result["items"] = self.list_accounts()
        return result

    @staticmethod
    def _is_image_account_available(account: dict) -> bool:
        if not isinstance(account, dict):
            return False
        if account.get("status") in {"disabled", "limited", "error"}:
            return False
        if "antigravity" in str(account.get("type") or "").split(","):
            return False
        if str(account.get("type") or "chatgpt") not in {"chatgpt", "codex", "free", "plus"}:
            return False
        if bool(account.get("image_quota_unknown")):
            return True
        return int(account.get("quota") or 0) > 0

    def _normalize_account(self, item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        access_token = item.get("access_token") or ""
        if not access_token:
            return None
        normalized = dict(item)
        normalized["access_token"] = access_token
        normalized["type"] = normalized.get("type") or "free"
        normalized["plan"] = normalized.get("plan") or None
        normalized["audience"] = normalized.get("audience") or detect_token_audience(access_token)
        # Stable per-account device_id (UUID) — sent as a header on Codex
        # OAuth refresh so the account looks like a real CLI install with
        # a persistent device, not an impersonator that rotates devices
        # on every refresh. Backfilled lazily for accounts that pre-date
        # this field. Once set, never changes.
        if not normalized.get("device_id"):
            import uuid
            normalized["device_id"] = str(uuid.uuid4())
        # Auto-migrate Chinese status to English
        raw_status = normalized.get("status") or "active"
        normalized["status"] = _STATUS_MIGRATION.get(raw_status, raw_status)
        normalized["quota"] = max(0, int(normalized.get("quota") if normalized.get("quota") is not None else 0))
        normalized["image_quota_unknown"] = bool(normalized.get("image_quota_unknown"))
        # Backfill email/user_id from JWT payload when missing. chatgpt.com
        # access tokens carry the user's email under the `email` claim or
        # under `https://api.openai.com/profile.email`. This lets one-click
        # token-import flows display the correct identity straight away
        # instead of showing "(none)" until a separate refresh step runs.
        if not normalized.get("email") and access_token.startswith("eyJ"):
            payload = _decode_jwt_payload(access_token)
            if payload:
                claim_email = payload.get("email")
                if not (isinstance(claim_email, str) and "@" in claim_email):
                    profile = payload.get("https://api.openai.com/profile") or {}
                    if isinstance(profile, dict):
                        claim_email = profile.get("email")
                if isinstance(claim_email, str) and "@" in claim_email:
                    normalized["email"] = claim_email
                if not normalized.get("user_id"):
                    auth = payload.get("https://api.openai.com/auth") or {}
                    if isinstance(auth, dict) and auth.get("user_id"):
                        normalized["user_id"] = str(auth["user_id"])
                    elif payload.get("sub"):
                        normalized["user_id"] = str(payload["sub"])
        normalized["email"] = normalized.get("email") or None
        normalized["user_id"] = normalized.get("user_id") or None
        # Backfill `plan` from the JWT's chatgpt_plan_type claim at IMPORT time.
        # Both session-token import and captcha-solver Google login produce a
        # chatgpt.com web JWT carrying this claim — without decoding it here, a
        # freshly-imported plus/go/business account would have plan=None and be
        # misclassified as `free` by account_group() until a /backend-api/me
        # refresh ran. Decoding now makes the free/codex split correct on day 1.
        if not normalized.get("plan") and access_token.startswith("eyJ"):
            _plan_payload = _decode_jwt_payload(access_token)
            if _plan_payload:
                _auth = _plan_payload.get("https://api.openai.com/auth") or {}
                if isinstance(_auth, dict) and isinstance(_auth.get("chatgpt_plan_type"), str):
                    normalized["plan"] = _auth.get("chatgpt_plan_type") or None
        normalized["plan"] = normalized.get("plan") or None
        normalized["source_type"] = str(normalized.get("source_type") or "web").strip() or "web"
        limits_progress = normalized.get("limits_progress")
        normalized["limits_progress"] = limits_progress if isinstance(limits_progress, list) else []
        normalized["default_model_slug"] = normalized.get("default_model_slug") or None
        normalized["restore_at"] = normalized.get("restore_at") or None
        normalized["project_id"] = normalized.get("project_id") or None
        normalized["success"] = int(normalized.get("success") or 0)
        normalized["fail"] = int(normalized.get("fail") or 0)
        normalized["last_used_at"] = normalized.get("last_used_at")
        # Free-text user annotation, shown/edited in the Accounts UI. Applies to
        # every account type (chatgpt/claude/gemini-web/...). Defaults to "" and
        # is only changed when an update explicitly carries it.
        normalized["notes"] = str(normalized.get("notes") or "")
        return normalized

    def list_tokens(self) -> list[str]:
        with self._lock:
            return list(self._accounts)

    def _list_ready_candidate_tokens(self, excluded_tokens: set[str] | None = None) -> list[str]:
        excluded = set(excluded_tokens or set())
        return [
            token
            for item in self._accounts.values()
            if self._is_image_account_available(item)
               and (token := item.get("access_token") or "")
               and token not in excluded
        ]

    def _list_available_candidate_tokens(self, excluded_tokens: set[str] | None = None) -> list[str]:
        max_concurrency = max(1, int(config.image_account_concurrency or 1))
        return [
            token
            for token in self._list_ready_candidate_tokens(excluded_tokens)
            if int(self._image_inflight.get(token, 0)) < max_concurrency
        ]

    def _acquire_next_candidate_token(self, excluded_tokens: set[str] | None = None) -> str:
        with self._image_slot_condition:
            while True:
                if not self._list_ready_candidate_tokens(excluded_tokens):
                    raise RuntimeError("no available image quota")
                tokens = self._list_available_candidate_tokens(excluded_tokens)
                if tokens:
                    access_token = tokens[self._index % len(tokens)]
                    self._index += 1
                    self._image_inflight[access_token] = int(self._image_inflight.get(access_token, 0)) + 1
                    return access_token
                self._image_slot_condition.wait(timeout=1.0)

    def release_image_slot(self, access_token: str) -> None:
        if not access_token:
            return
        with self._image_slot_condition:
            current_inflight = int(self._image_inflight.get(access_token, 0))
            if current_inflight <= 1:
                self._image_inflight.pop(access_token, None)
            else:
                self._image_inflight[access_token] = current_inflight - 1
            self._image_slot_condition.notify_all()

    def get_available_access_token(self, excluded_tokens: set[str] | None = None) -> str:
        # `excluded_tokens` lets the image dispatcher rotate PAST accounts it
        # already tried this request (e.g. a free Codex account that can't run
        # the image tool) so it reaches a Plus/image-capable account instead of
        # re-picking the same dead one.
        attempted_tokens: set[str] = set(excluded_tokens or set())
        while True:
            access_token = self._acquire_next_candidate_token(excluded_tokens=attempted_tokens)
            attempted_tokens.add(access_token)
            try:
                account = self.fetch_remote_info(access_token, "get_available_access_token")
            except Exception:
                self.release_image_slot(access_token)
                continue
            if self._is_image_account_available(account or {}):
                return access_token
            self.release_image_slot(access_token)

    def get_text_access_token(
        self,
        excluded_tokens: set[str] | None = None,
        account_type: str | None = None,
        requires_image: bool = False,
    ) -> str:
        """Priority-FIFO selection. Optionally filter to one account type.

        Codex and ChatGPT-free are separate logical pools — each maintains
        its own #1 because demote_account() moves items within the shared
        ordered dict but type-filtered iteration only sees its own type.
        Pass `account_type="free"` for ChatGPT-free only, `"codex"` for
        codex JWT only, or omit (default) to scan any non-antigravity type
        — the chatgpt provider auto-routes by token format after selection.

        smart_pool.weighted bật (mặc định): gom mọi ứng viên hợp lệ rồi chọn
        theo success-rate (Laplace) + né account vừa dùng <60s — tie thì giữ
        thứ tự FIFO cũ. Tắt → trả ứng viên ĐẦU TIÊN y hệt hành vi cũ.
        """
        excluded = set(excluded_tokens or set())
        candidates: list[tuple[str, dict]] = []
        with self._lock:
            for account in self._accounts.values():
                status = account.get("status")
                if status in {"disabled", "error", "limited"}:
                    continue
                group = account_group(account)
                if group == GROUP_ANTIGRAVITY:
                    continue
                # Web-session pools (claude / gemini_web_api / gemini_web /
                # chatgpt_web) store a captcha-solver PROFILE NAME as the
                # access_token — never a usable chatgpt JWT. They have their own
                # selectors (get_claude_session_key / normalize_and_rank_accounts)
                # so they must never be handed to the chatgpt token path, even
                # when account_type is None ("any").
                if group in WEB_SESSION_GROUPS:
                    continue
                # Type-filter via the canonical group classifier. "free" now
                # means group==free (excludes codex tokens AND paid-plan
                # accounts — plus/go/business carry Codex and must never leak
                # into chatgpt/auto / HA / n8n free-tier traffic). "codex"
                # means the paid group (codex token or paid plan).
                if account_type and group != account_type:
                    continue
                token = account.get("access_token") or ""
                if not token or token in excluded:
                    continue
                if requires_image:
                    # Skip if we know file_upload/image_gen is 0
                    limits = account.get("limits_progress")
                    if isinstance(limits, list):
                        has_zero_quota = False
                        for lp in limits:
                            if lp.get("feature_name") in ("file_upload", "image_gen") and int(lp.get("remaining") or 0) <= 0:
                                has_zero_quota = True
                                break
                        if has_zero_quota:
                            continue
                    # Skip if recently failed image upload (e.g. within 6 hours)
                    last_fail = account.get("last_image_failed_at")
                    if last_fail:
                        try:
                            from datetime import datetime
                            fail_dt = datetime.strptime(last_fail, "%Y-%m-%d %H:%M:%S")
                            if (datetime.now() - fail_dt).total_seconds() < 6 * 3600:
                                continue
                        except Exception:
                            pass
                    # Skip if recently failed advanced data analysis (within 6 hours)
                    last_analysis_fail = account.get("last_analysis_failed_at")
                    if last_analysis_fail:
                        try:
                            from datetime import datetime
                            fail_dt = datetime.strptime(last_analysis_fail, "%Y-%m-%d %H:%M:%S")
                            if (datetime.now() - fail_dt).total_seconds() < 6 * 3600:
                                continue
                        except Exception:
                            pass
                candidates.append((token, account))
            if not candidates:
                return ""
            if len(candidates) > 1 and self._weighted_enabled():
                # max() ổn định → điểm bằng nhau giữ nguyên thứ tự FIFO.
                return max(candidates, key=lambda c: self._selection_weight(c[1]))[0]
            return candidates[0][0]

    @staticmethod
    def _weighted_enabled() -> bool:
        sp = config.data.get("smart_pool")
        if isinstance(sp, dict):
            return bool(sp.get("enabled", True)) and bool(sp.get("weighted", True))
        return True

    @staticmethod
    def _selection_weight(account: dict) -> float:
        """Trọng số chọn account: success-rate Laplace-smoothed + né account
        vừa dùng trong 60s (dàn tải đều pool)."""
        success = int(account.get("success") or 0)
        fail = int(account.get("fail") or 0)
        weight = (success + 1) / (success + fail + 2)
        last_used = account.get("last_used_at")
        if last_used:
            try:
                from datetime import datetime
                dt = datetime.strptime(str(last_used), "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - dt).total_seconds() < 60:
                    weight -= 0.1
            except Exception:
                pass
        return weight

    def get_claude_session_key(
        self,
        excluded_tokens: set[str] | None = None,
        requires_image: bool = False,
    ) -> str:
        """Return the next available Claude session key (access_token with type=claude).

        Same priority-FIFO logic as get_text_access_token but scoped to
        GROUP_CLAUDE accounts. When requires_image=True, additionally skip
        accounts that recently failed image upload or advanced data analysis.
        """
        excluded = set(excluded_tokens or set())
        with self._lock:
            for account in self._accounts.values():
                if account.get("status") in {"disabled", "error", "limited"}:
                    continue
                if account_group(account) != GROUP_CLAUDE:
                    continue
                token = account.get("access_token") or ""
                if not token or token in excluded:
                    continue
                if requires_image:
                    # Skip if recently failed image upload (within 6 hours)
                    last_fail = account.get("last_image_failed_at")
                    if last_fail:
                        try:
                            fail_dt = datetime.strptime(last_fail, "%Y-%m-%d %H:%M:%S")
                            if (datetime.now() - fail_dt).total_seconds() < 6 * 3600:
                                continue
                        except Exception:
                            pass
                    # Skip if recently failed advanced data analysis (within 6 hours)
                    last_analysis_fail = account.get("last_analysis_failed_at")
                    if last_analysis_fail:
                        try:
                            fail_dt = datetime.strptime(last_analysis_fail, "%Y-%m-%d %H:%M:%S")
                            if (datetime.now() - fail_dt).total_seconds() < 6 * 3600:
                                continue
                        except Exception:
                            pass
                return token
            return ""

    def normalize_and_rank_accounts(
        self,
        raw_accounts: list[dict],
        account_type: str,
        required_features: list[str] | None = None,
    ) -> list[dict]:
        """Sync captcha-solver profiles into the pool and rank them for rotation.

        Used by web-session providers (gemini_web_api, gemini_web, chatgpt_web)
        whose "access_token" is a profile name. Mirrors get_claude_session_key
        but returns the FULL ranked list (the caller iterates with retry/exclude):

          - Auto-registers any profile not yet in the pool (type=account_type)
            so it gets the right group, survives restarts, and shows in the UI.
          - Drops disabled / error / limited accounts.
          - When required_features needs images, drops profiles that recently
            failed image upload / advanced data analysis (within 6 hours).
          - Returns survivors in pool FIFO order (demoted accounts sink to the
            back), so element #0 is the preferred account — same rotation as
            ChatGPT / Claude.
        """
        required = set(required_features or [])
        wants_image = bool(required & {"file_upload", "image_gen", "vision"})
        profiles: list[str] = []
        for a in raw_accounts or []:
            p = str((a or {}).get("profile") or "").strip()
            if p and p not in profiles:
                profiles.append(p)
        if not profiles:
            return []

        now = datetime.now()

        def _recently_failed(acc: dict) -> bool:
            for fld in ("last_image_failed_at", "last_analysis_failed_at"):
                ts = acc.get(fld)
                if not ts:
                    continue
                try:
                    if (now - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).total_seconds() < 6 * 3600:
                        return True
                except Exception:
                    pass
            return False

        wanted = set(profiles)
        ranked: list[dict] = []
        with self._lock:
            changed = False
            for p in profiles:
                if p not in self._accounts:
                    seed = self._normalize_account({
                        "access_token": p,
                        "type": account_type,
                        "email": p,
                        "status": "active",
                        "quota": 0,
                        "image_quota_unknown": True,
                    })
                    if seed:
                        self._accounts[p] = seed
                        changed = True
            # Pool dict order is the FIFO priority queue (demote sinks to tail).
            for token, account in self._accounts.items():
                if token not in wanted:
                    continue
                if account_group(account) != account_type:
                    continue
                if account.get("status") in {"disabled", "error", "limited"}:
                    continue
                if wants_image and _recently_failed(account):
                    continue
                ranked.append({"profile": token, "status": account.get("status") or "active"})
            if changed:
                self._save_accounts()
        return ranked

    def mark_image_failed(self, access_token: str) -> None:
        """Mark that this account failed an image upload (e.g. reached file limit)
        so we can skip it for future image requests, but keep it at #1 for text requests.
        """
        if not access_token:
            return
        with self._lock:
            current = self._accounts.get(access_token)
            if current is None:
                return
            next_item = dict(current)
            from datetime import datetime
            next_item["last_image_failed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[access_token] = account
            self._save_accounts()

    def mark_analysis_failed(self, access_token: str) -> None:
        """Mark that this account failed advanced data analysis quota
        so we skip it for future vision/image requests, but keep it at #1 for text.
        """
        if not access_token:
            return
        with self._lock:
            current = self._accounts.get(access_token)
            if current is None:
                return
            next_item = dict(current)
            from datetime import datetime
            next_item["last_analysis_failed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            account = self._normalize_account(next_item)
            if account is not None:
                self._accounts[access_token] = account
            self._save_accounts()

    def mark_text_used(self, access_token: str) -> None:
        if not access_token:
            return
        with self._lock:
            current = self._accounts.get(access_token)
            if current is None:
                return
            next_item = dict(current)
            next_item["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            account = self._normalize_account(next_item)
            if account is None:
                return
            self._accounts[access_token] = account
            self._save_accounts()

    def record_profile_quota_failure(
        self,
        profile: str,
        quota_type: str,
        account_type: str = "claude",
        email: str = "",
    ) -> None:
        """Persist a quota failure for a captcha-solver profile.

        Auto-registers the profile in the account pool (using profile name as
        access_token) if it has never been seen before, then writes the
        appropriate failure timestamp so:
          - The failure survives container restarts
          - The UI shows the correct badge (Hết Gửi ảnh / Phân tích DL / Text)
          - get_claude_session_key / get_text_access_token will skip it for 6h

        quota_type: one of "file_upload", "advanced_data_analysis", "text_limit"
        account_type: "claude" | "chatgpt_web" | "gemini_web"
        """
        if not profile:
            return
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            if profile not in self._accounts:
                # First time seeing this profile — auto-register it
                seed: dict = {
                    "access_token": profile,
                    "type": account_type,
                    "email": email or profile,
                    "status": "active",
                    "quota": 0,
                    "image_quota_unknown": True,
                    "success": 0,
                    "fail": 0,
                }
                normalized = self._normalize_account(seed)
                if normalized:
                    self._accounts[profile] = normalized

            current = self._accounts.get(profile)
            if current is None:
                return
            next_item = dict(current)
            next_item["last_quota_exhausted"] = quota_type
            next_item["last_quota_exhausted_at"] = now_str

            if quota_type == "file_upload":
                next_item["last_image_failed_at"] = now_str
            elif quota_type == "advanced_data_analysis":
                next_item["last_analysis_failed_at"] = now_str
            else:
                # text_limit: demote by moving to end of dict (FIFO)
                self._accounts.pop(profile, None)
                next_item["status"] = "limited"
                # GMA/web session: always set restore_at so quota_watcher can
                # auto-revive (avoid stuck limited forever when last_used is null).
                next_item["restore_at"] = (
                    datetime.now(timezone.utc) + timedelta(hours=24)
                ).isoformat()

            account = self._normalize_account(next_item)
            if account:
                self._accounts[profile] = account
            self._save_accounts()

        logger.info({
            "event": "profile_quota_persisted",
            "profile": profile,
            "quota_type": quota_type,
            "account_type": account_type,
            "at": now_str,
            "restore_at": (self._accounts.get(profile) or {}).get("restore_at"),
        })

    def remove_invalid_token(self, access_token: str, event: str) -> bool:
        # Snapshot before mutate/delete so multi-tier recovery still has email/rt.
        snapshot = self.get_account(access_token)
        if not config.auto_remove_invalid_accounts:
            self.update_account(access_token, {"status": "error", "quota": 0})
            self._spawn_dead_recovery(snapshot, access_token, event)
            return False
        # Chụp email/provider TRƯỚC khi xóa để log đủ "tài khoản nào, provider nào"
        removed = bool(self.delete_accounts([access_token])["removed"])
        if removed:
            log_service.add(LOG_TYPE_ACCOUNT, "Tự động xóa tài khoản lỗi",
                            {"provider": account_group(snapshot),
                             "email": str((snapshot or {}).get("email") or "")[:80],
                             "source": event, "token": anonymize_token(access_token)})
        elif access_token:
            self.update_account(access_token, {"status": "error", "quota": 0})
            self._spawn_dead_recovery(snapshot, access_token, event)
        return removed

    def _spawn_dead_recovery(
        self,
        snapshot: dict | None,
        access_token: str,
        event: str,
    ) -> None:
        """Kick multi-tier recovery for accounts just marked error (async)."""
        try:
            from services.codex_error_recovery_scheduler import (
                schedule_dead_account_recovery,
            )

            acc = dict(snapshot) if isinstance(snapshot, dict) else {}
            if access_token and "access_token" not in acc:
                acc["access_token"] = access_token
            if not acc:
                return
            schedule_dead_account_recovery(acc, reason=f"marked_error:{event}")
        except Exception:
            pass

    def get_account(self, access_token: str) -> dict | None:
        if not access_token:
            return None
        with self._lock:
            account = self._accounts.get(access_token)
            return dict(account) if account else None

    def demote_account(self, access_token: str) -> None:
        """Move this account to the END of the ordered pool.

        Used after a 429/quota burn so the next request lands on a fresh
        account at the front of the queue. When the demoted account is
        auto-restored later, it stays at the back until older accounts
        also fail and rotate down — guaranteeing "always prefer #1" with
        FIFO demotion, exactly the rotation the user asked for.

        No-op if the token isn't in the pool.
        """
        if not access_token:
            return
        with self._lock:
            current = self._accounts.pop(access_token, None)
            if current is None:
                return
            self._accounts[access_token] = current  # re-insert at tail
            self._save_accounts()
        # Account bị demote → gỡ mọi phiên sticky đang dính vào nó.
        try:
            from services.session_affinity import session_affinity
            session_affinity.evict_token(access_token)
        except Exception:
            pass

    def promote_account(self, access_token: str) -> None:
        """Move this account to the FRONT of the ordered pool.

        Inverse of demote_account — used after an explicit user action
        ("set this account as primary") or by quota_watcher when an
        account is auto-restored and you want it back at #1.
        """
        if not access_token:
            return
        with self._lock:
            current = self._accounts.pop(access_token, None)
            if current is None:
                return
            new_accounts = {access_token: current}
            new_accounts.update(self._accounts)
            self._accounts = new_accounts
            self._save_accounts()

    def list_accounts(self) -> list[dict]:
        from datetime import datetime
        now = datetime.now()

        def _scrub(item: dict) -> dict:
            out = dict(item)
            for fld in ("last_image_failed_at", "last_analysis_failed_at", "last_quota_exhausted_at"):
                ts = out.get(fld)
                if ts:
                    try:
                        if (now - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).total_seconds() >= 6 * 3600:
                            out[fld] = ""
                            if fld == "last_quota_exhausted_at":
                                out["last_quota_exhausted"] = ""
                    except Exception:
                        pass
            return out

        with self._lock:
            return [_scrub(item) for item in self._accounts.values()]

    def refresh_status_overview(self) -> dict:
        """Per-token refresh ETA + health, grouped by provider — for the dashboard.

        For each account we report: time left until its token is proactively
        refreshed and whether refresh is healthy or the token is dead.

        Refresh rules mirror the schedulers:
          - codex / antigravity (OAuth): refresh ~6h before `expires_at`; needs refresh_token.
          - free / web-session JWTs: refresh ~7d before the JWT `exp`; needs captcha-solver.
          - openai (raw sk- key): static, never expires / refreshes.
        """
        import time as _time
        import base64 as _b64
        import json as _json

        def _jwt_exp(token: str) -> float | None:
            try:
                _, payload_b64, _ = token.split(".", 2)
            except ValueError:
                return None
            pad = "=" * (-len(payload_b64) % 4)
            try:
                payload = _json.loads(_b64.urlsafe_b64decode(payload_b64 + pad))
            except Exception:
                return None
            exp = payload.get("exp")
            try:
                return float(exp) if exp else None
            except (TypeError, ValueError):
                return None

        now = _time.time()
        flow_cfg = (config.data.get("providers") or {}).get("flow") or {}
        captcha_ready = bool(str(flow_cfg.get("captcha_solver_url") or "").strip())

        oauth_groups = {GROUP_CODEX, GROUP_ANTIGRAVITY}
        groups: dict[str, list[dict]] = {}

        for acc in self.list_accounts():
            grp = account_group(acc)
            token = str(acc.get("access_token") or "")
            status = str(acc.get("status") or "active")
            has_refresh_token = bool(str(acc.get("refresh_token") or "").strip())

            expires_at: float | None = None
            raw_exp = acc.get("expires_at")
            if raw_exp:
                try:
                    expires_at = float(raw_exp)
                except (TypeError, ValueError):
                    expires_at = None
            if expires_at is None and token.count(".") == 2:
                expires_at = _jwt_exp(token)

            if grp in oauth_groups:
                threshold = 6 * 3600
                can_refresh = has_refresh_token
            elif grp == GROUP_OPENAI:
                threshold = 0
                can_refresh = False  # raw API key — static
            else:  # free + web-session JWTs, auto-refreshed via captcha-solver
                threshold = 7 * 86400
                can_refresh = captcha_ready

            seconds_until_refresh = (
                int(expires_at - threshold - now) if (expires_at is not None and threshold) else None
            )

            last_refresh_raw = acc.get("codex_refreshed_at") or acc.get("jwt_refreshed_at")
            try:
                last_refresh_at = int(last_refresh_raw) if last_refresh_raw else None
            except (TypeError, ValueError):
                last_refresh_at = None

            if status in {"error", "disabled"}:
                health = "dead"
            elif status == "limited":
                health = "limited"
            elif grp == GROUP_OPENAI:
                health = "static"
            elif not can_refresh:
                health = "dead" if (expires_at is not None and expires_at < now) else "no_refresh"
            elif expires_at is not None and expires_at < now:
                health = "stale"  # expired but should self-heal on next scan
            else:
                health = "ok"

            groups.setdefault(grp, []).append({
                "email": str(acc.get("email") or "") or anonymize_token(token),
                "status": status,
                "canRefresh": can_refresh,
                "expiresAt": expires_at,
                "secondsUntilRefresh": seconds_until_refresh,
                "lastRefreshAt": last_refresh_at,
                "health": health,
            })

        return {
            "groups": [
                {
                    "group": grp,
                    "total": len(accs),
                    "active": sum(1 for a in accs if a["status"] == "active"),
                    "accounts": sorted(
                        accs,
                        key=lambda a: (a["secondsUntilRefresh"] is None, a["secondsUntilRefresh"] or 0),
                    ),
                }
                for grp, accs in sorted(groups.items())
            ],
        }

    def find_by_refresh_token(self, refresh_token: str) -> dict | None:
        """Return the account dict matching a given refresh_token, or None.

        Used by token-refresh code paths that hold a per-token mutex: once a
        thread finishes refreshing, a second thread that was waiting on the
        same mutex can re-read the account here and observe the fresh
        access_token instead of issuing another OAuth call (which would
        trigger refresh-token rotation race and brick the account).
        """
        if not refresh_token:
            return None
        with self._lock:
            for account in self._accounts.values():
                if account.get("refresh_token") == refresh_token:
                    return dict(account)
        return None

    def list_limited_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for item in self._accounts.values()
                if item.get("status") == "limited"
                   and (token := item.get("access_token") or "")
            ]

    def revive_stuck_limited(
        self,
        *,
        max_age_hours: float = 24.0,
        account_types: set[str] | None = None,
    ) -> list[str]:
        """Auto-restore limited accounts that have no restore_at / last_used.

        Used for GMA profiles stuck forever after text_limit without timestamps.
        Returns list of restored profile/token ids.
        """
        now = datetime.now(timezone.utc)
        types = account_types or {"gemini_web_api", "gemini_web", "gma"}
        revived: list[str] = []
        with self._lock:
            for token, acc in list(self._accounts.items()):
                if str(acc.get("status") or "") != "limited":
                    continue
                grp = account_group(acc)
                if types and grp not in types and str(acc.get("type") or "") not in types:
                    continue
                restore_at = acc.get("restore_at")
                if restore_at:
                    try:
                        t = datetime.fromisoformat(str(restore_at).replace("Z", "+00:00"))
                        if t.tzinfo is None:
                            t = t.replace(tzinfo=timezone.utc)
                        if now < t:
                            continue  # still cooling down
                    except Exception:
                        pass
                else:
                    # No restore_at: age out by last_quota_exhausted_at / last_used
                    anchor = (
                        acc.get("last_quota_exhausted_at")
                        or acc.get("last_used_at")
                        or acc.get("updated_at")
                        or ""
                    )
                    age_ok = False
                    if anchor:
                        try:
                            t = datetime.strptime(
                                str(anchor)[:19], "%Y-%m-%d %H:%M:%S"
                            ).replace(tzinfo=timezone.utc)
                            age_ok = (now - t).total_seconds() / 3600.0 >= max_age_hours
                        except Exception:
                            age_ok = True
                    else:
                        age_ok = True
                    if not age_ok:
                        continue
                next_item = dict(acc)
                next_item["status"] = "active"
                next_item["restore_at"] = None
                next_item["quota"] = max(int(next_item.get("quota") or 0), 1)
                norm = self._normalize_account(next_item)
                if norm:
                    self._accounts[token] = norm
                    revived.append(token)
            if revived:
                self._save_accounts()
        if revived:
            logger.info({
                "event": "stuck_limited_revived",
                "n": len(revived),
                "ids": [r[:40] for r in revived],
            })
        return revived

    def add_accounts(self, tokens: list[str]) -> dict:
        """Add free-pool tokens. Dedupes by email so refresh never creates a 2nd row."""
        tokens = list(dict.fromkeys(token for token in tokens if token))
        if not tokens:
            return {"added": 0, "skipped": 0, "items": self.list_accounts()}

        added = 0
        updated = 0
        skipped = 0
        for access_token in tokens:
            r = self.upsert_free_token(access_token)
            added += int(r.get("added") or 0)
            updated += int(r.get("updated") or 0)
            skipped += int(r.get("skipped") or 0)
        log_service.add(
            LOG_TYPE_ACCOUNT,
            f"Thêm {added} free, cập nhật {updated}, bỏ qua {skipped}",
            {"provider": "free", "added": added, "updated": updated, "skipped": skipped},
        )
        return {"added": added, "skipped": skipped, "updated": updated, "items": self.list_accounts()}

    def add_accounts_with_type(self, tokens: list[str], account_type: str = "codex") -> dict:
        """Add accounts with a specific type (e.g. 'codex' for 9router OAuth tokens).

        For type=free, always upsert by email (one free account per email).
        """
        tokens = list(dict.fromkeys(token for token in tokens if token))
        if not tokens:
            return {"added": 0, "skipped": 0, "items": self.list_accounts()}

        # Free pool: never create duplicate rows for the same email
        if str(account_type or "").strip() == "free" or (
            "free" in set(str(account_type or "").split(",")) and "codex" not in set(str(account_type or "").split(","))
        ):
            added = updated = skipped = 0
            for access_token in tokens:
                r = self.upsert_free_token(access_token)
                added += int(r.get("added") or 0)
                updated += int(r.get("updated") or 0)
                skipped += int(r.get("skipped") or 0)
            return {
                "added": added, "skipped": skipped, "updated": updated,
                "items": self.list_accounts(),
            }

        with self._lock:
            added = 0
            skipped = 0
            updated = 0
            for access_token in tokens:
                current = self._accounts.get(access_token)
                if current is not None:
                    # Never merge "free" and "codex" types — chatgpt/auto
                    # hard-pins to the free pool and a "free,codex" hybrid
                    # leaks paid Codex quota into free-tier traffic.
                    existing_types = set(str(current.get("type") or "").split(","))
                    new_types = set(str(account_type).split(","))
                    if ("free" in existing_types and "codex" in new_types) or \
                       ("codex" in existing_types and "free" in new_types):
                        skipped += 1
                        continue
                    merged = ",".join(sorted(existing_types | new_types))
                    if merged != str(current.get("type") or ""):
                        current["type"] = merged
                        updated += 1
                        logger.info({"event": "account_type_merged", "token": anonymize_token(access_token), "new_type": merged})
                    else:
                        skipped += 1
                    continue
                added += 1
                account = self._normalize_account({
                    "access_token": access_token,
                    "type": account_type,
                    "status": "active",
                })
                if account is not None:
                    self._accounts[access_token] = account
            self._save_accounts()
            items = [dict(item) for item in self._accounts.values()]
            log_service.add(LOG_TYPE_ACCOUNT, f"Thêm {added} tài khoản {account_type}, cập nhật {updated}, bỏ qua {skipped}",
                            {"added": added, "skipped": skipped, "updated": updated, "type": account_type})
        return {"added": added, "skipped": skipped, "updated": updated, "items": items}

    def add_accounts_with_credentials(self, creds: list[dict], account_type: str = "codex") -> dict:
        """Add Codex OAuth accounts with full credential payload (access + refresh + expiry).

        Each cred dict accepts: access_token (required), refresh_token, expires_at.
        Existing accounts are merged: refresh_token / expires_at are updated even
        when the access_token already exists, so older imports get refreshable.
        """
        added = 0
        skipped = 0
        updated = 0
        with self._lock:
            for cred in creds or []:
                if not isinstance(cred, dict):
                    continue
                access_token = str(cred.get("access_token") or "").strip()
                if not access_token:
                    continue
                refresh_token = str(cred.get("refresh_token") or "").strip() or None
                expires_at = cred.get("expires_at") or None
                email = str(cred.get("email") or "").strip().lower()

                # Find existing account by token OR by email (to avoid duplicating OAuth logins)
                current = self._accounts.get(access_token)
                if current is None and email:
                    for t, acc in list(self._accounts.items()):
                        # Match email and ensure it's a codex account (so we don't overwrite non-codex accounts)
                        if str(acc.get("email") or "").strip().lower() == email and account_type in set(str(acc.get("type") or "").split(",")):
                            current = self._accounts.pop(t)
                            break

                if current is None:
                    added += 1
                    base = {"access_token": access_token, "type": account_type, "status": "active"}
                else:
                    base = dict(current)
                    base["access_token"] = access_token
                    existing_types = set(str(base.get("type") or "").split(","))
                    new_types = set(str(account_type).split(","))
                    base["type"] = ",".join(sorted(existing_types | new_types))
                    skipped += 1
                if refresh_token:
                    base["refresh_token"] = refresh_token
                    updated += 1
                if expires_at:
                    base["expires_at"] = expires_at
                if cred.get("project_id"):
                    base["project_id"] = cred["project_id"]
                if cred.get("email"):
                    base["email"] = cred["email"]
                account = self._normalize_account(base)
                if account is not None:
                    self._accounts[access_token] = account
            self._save_accounts()
            items = [dict(item) for item in self._accounts.values()]
            log_service.add(
                LOG_TYPE_ACCOUNT,
                f"Thêm {added} tài khoản {account_type} có refresh, cập nhật {updated}, bỏ qua {skipped}",
                {"added": added, "skipped": skipped, "updated": updated, "type": account_type},
            )
        return {"added": added, "skipped": skipped, "updated": updated, "items": items}

    def delete_accounts(self, tokens: list[str]) -> dict:
        target_set = set(token for token in tokens if token)
        if not target_set:
            return {"removed": 0, "items": self.list_accounts()}
        with self._lock:
            removed = sum(self._accounts.pop(token, None) is not None for token in target_set)
            for token in target_set:
                self._image_inflight.pop(token, None)
            if removed:
                if self._accounts:
                    self._index %= len(self._accounts)
                else:
                    self._index = 0
                self._save_accounts()
                log_service.add(LOG_TYPE_ACCOUNT, f"删除 {removed}  tài khoản", {"removed": removed})
            items = [dict(item) for item in self._accounts.values()]
        return {"removed": removed, "items": items}

    def update_account(self, access_token: str, updates: dict) -> dict | None:
        if not access_token:
            return None
        with self._lock:
            current = self._accounts.get(access_token)
            if current is None:
                return None
            # Allow re-key when JWT refresh supplies a new access_token.
            # Previously the old key was forced back, so refresh never stuck
            # and recovery then added a 2nd free row for the same email.
            new_token = str((updates or {}).get("access_token") or access_token).strip() or access_token
            account = self._normalize_account({**current, **(updates or {}), "access_token": new_token})
            if account is None:
                return None
            if account.get("status") == "limited" and config.auto_remove_rate_limited_accounts:
                self._accounts.pop(access_token, None)
                if new_token != access_token:
                    self._accounts.pop(new_token, None)
                self._save_accounts()
                log_service.add(LOG_TYPE_ACCOUNT, "Tự động xóa tài khoản giới hạn",
                                {"provider": account_group(account),
                                 "email": str(account.get("email") or "")[:80],
                                 "token": anonymize_token(access_token)})
                return None
            if new_token != access_token:
                self._accounts.pop(access_token, None)
                # If another row already holds new_token, drop it (same free email case)
                self._accounts.pop(new_token, None)
            self._accounts[new_token] = account
            self._save_accounts()
            log_service.add(LOG_TYPE_ACCOUNT, "Cập nhật tài khoản",
                            {"provider": account_group(account),
                             "email": str(account.get("email") or "")[:80],
                             "token": anonymize_token(new_token), "status": account.get("status"),
                             "rekeyed": new_token != access_token})
            return dict(account)
        return None

    def mark_image_result(self, access_token: str, success: bool) -> dict | None:
        if not access_token:
            return None
        self.release_image_slot(access_token)
        with self._lock:
            current = self._accounts.get(access_token)
            if current is None:
                return None
            next_item = dict(current)
            next_item["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            image_quota_unknown = bool(next_item.get("image_quota_unknown"))
            if success:
                next_item["success"] = int(next_item.get("success") or 0) + 1
                if not image_quota_unknown:
                    next_item["quota"] = max(0, int(next_item.get("quota") or 0) - 1)
                if not image_quota_unknown and next_item["quota"] == 0:
                    next_item["status"] = "limited"
                    next_item["restore_at"] = next_item.get("restore_at") or None
                elif next_item.get("status") == "limited":
                    next_item["status"] = "active"
            else:
                next_item["fail"] = int(next_item.get("fail") or 0) + 1
            account = self._normalize_account(next_item)
            if account is None:
                return None
            if account.get("status") == "limited" and config.auto_remove_rate_limited_accounts:
                self._accounts.pop(access_token, None)
                self._save_accounts()
                log_service.add(LOG_TYPE_ACCOUNT, "Tự động xóa tài khoản giới hạn",
                                {"provider": account_group(account),
                                 "email": str(account.get("email") or "")[:80],
                                 "token": anonymize_token(access_token)})
                return None
            self._accounts[access_token] = account
            self._save_accounts()
            return dict(account)
        return None

    def fetch_remote_info(self, access_token: str, event: str = "fetch_remote_info") -> dict[str, Any] | None:
        if not access_token:
            raise ValueError("access_token is required")

        try:
            from services.openai_backend_api import InvalidAccessTokenError, OpenAIBackendAPI
            result = OpenAIBackendAPI(access_token).get_user_info()
        except InvalidAccessTokenError:
            # Token can't access chatgpt.com
            logger.info({"event": "fetch_remote_401_skip", "token": anonymize_token(access_token)})
            account = self.get_account(access_token)
            if account and account.get("refresh_token") and account_group(account) in ("codex", "antigravity"):
                try:
                    from services.codex_refresh_scheduler import _refresh_one
                    updated = _refresh_one(account)
                    if updated:
                        logger.info({"event": "fetch_remote_401_recovered_via_oauth", "token": anonymize_token(access_token)})
                        return self.update_account(access_token, updated)
                    else:
                        # If oauth refresh also failed or token is revoked, mark disabled
                        logger.info({"event": "fetch_remote_401_oauth_failed_disabling", "token": anonymize_token(access_token)})
                        self.remove_invalid_token(access_token, event)
                        return None
                except Exception as e:
                    logger.warning({"event": "fetch_remote_401_oauth_recovery_failed", "error": str(e)})
            elif account and account_group(account) == "free":
                # For free web JWTs, 401 means the JWT is dead
                self.remove_invalid_token(access_token, event)
                return None
            return account
        except Exception as exc:
            msg = str(exc).lower()
            if any(k in msg for k in ("openssl", "tls", "invalid library", "curl: (35)")):
                logger.warning({"event": "fetch_remote_tls_skip", "token": anonymize_token(access_token), "error": str(exc)[:120]})
                return self.get_account(access_token)
            raise
        return self.update_account(access_token, result)

    def refresh_accounts(self, access_tokens: list[str]) -> dict[str, Any]:
        access_tokens = list(dict.fromkeys(token for token in access_tokens if token))
        if not access_tokens:
            return {"refreshed": 0, "errors": [], "items": self.list_accounts()}

        refreshed = 0
        errors = []
        max_workers = min(10, len(access_tokens))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.fetch_remote_info, token, "refresh_accounts"): token
                for token in access_tokens
            }
            for future in as_completed(futures):
                try:
                    account = future.result()
                except Exception as exc:
                    errors.append({"token": anonymize_token(futures[future]), "error": str(exc)})
                    continue
                if account is not None:
                    refreshed += 1

        return {
            "refreshed": refreshed,
            "errors": errors,
            "items": self.list_accounts(),
        }


    def get_health_score(self, access_token: str) -> float:
        """Calculate health score for an account (0.0-1.0).

        Ported from 9router health scoring pattern:
        - 0.35: rate-limit status
        - 0.20: response latency (placeholder)
        - 0.20: concurrency saturation
        - 0.15: token last used recency
        - 0.10: success/fail ratio
        """
        account = self.get_account(access_token)
        if not account:
            return 0.0

        score = 0.0

        # Rate-limit status (0.35)
        status = str(account.get("status") or "active")
        if status == "active":
            score += 0.35
        elif status == "limited":
            score += 0.0
        else:
            score += 0.1

        # Concurrency saturation (0.20)
        max_conc = max(1, int(config.image_account_concurrency or 1))
        inflight = int(self._image_inflight.get(access_token, 0))
        saturation = inflight / max_conc
        score += (1 - saturation) * 0.20

        # Token recency (0.15)
        last_used = account.get("last_used_at")
        if last_used:
            try:
                from datetime import datetime
                last_dt = datetime.strptime(str(last_used), "%Y-%m-%d %H:%M:%S")
                age_minutes = (datetime.now() - last_dt).total_seconds() / 60
                if age_minutes < 5:
                    score += 0.15
                elif age_minutes < 30:
                    score += 0.10
                else:
                    score += 0.03
            except (ValueError, TypeError):
                score += 0.05
        else:
            score += 0.05

        # Success/fail ratio (0.10)
        success = int(account.get("success") or 0)
        fail = int(account.get("fail") or 0)
        total = success + fail
        if total > 0:
            score += (success / total) * 0.10
        else:
            score += 0.05

        # Latency placeholder (0.20) — default to mid-range
        score += 0.10

        return max(0.0, min(1.0, score))

    def get_provider_credentials(
        self,
        provider_id: str,
        exclude_connection_ids: set[str] | None = None,
        model: str = "",
    ) -> dict[str, Any] | None:
        """Get credentials for a provider, supporting noAuth virtual connections.

        Ported from 9router src/sse/services/auth.js getProviderCredentials().
        Returns None if no credentials available.

        For noAuth providers (opencode): returns a virtual connection with
        id="noauth" and accessToken="public".
        """
        # Check for noAuth provider first (port from 9router FREE_PROVIDERS check)
        if provider_id in NO_AUTH_PROVIDERS:
            return {
                "id": "noauth",
                "connectionName": "Public",
                "isActive": True,
                "accessToken": "public",
                "noAuth": True,
            }

        # For chatgpt provider, use existing token pool
        if provider_id == "chatgpt":
            token = self.get_text_access_token(exclude_connection_ids)
            if not token:
                return None
            return {
                "id": anonymize_token(token),
                "connectionName": "ChatGPT",
                "isActive": True,
                "accessToken": token,
                "noAuth": False,
            }

        return None

    def is_noauth_provider(self, provider_id: str) -> bool:
        """Check if a provider uses noAuth virtual connections."""
        return provider_id in NO_AUTH_PROVIDERS


account_service = AccountService(config.get_storage_backend())
