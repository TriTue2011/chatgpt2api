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

# Bậc gói — gói CAO dùng trước. Chốt với chủ máy 10/08/2026:
# pro > team/enterprise > business > plus > go > free.
#
# Chỉ có tác dụng TRONG CÙNG một pool. Gói đã tách pool sẵn (`account_group`)
# nên bậc này thực tế chỉ phân định bên trong nhóm `codex` — nơi plus/go và các
# token mang thẻ `codex` nằm chung. Pool `free` toàn plan=free nên bậc bằng nhau
# và thứ tự giữ nguyên như trước.
#
# KHÔNG dùng bậc này để chọn pool: pool do thứ tự provider trong `combo_models`
# quyết, không phải do đây.
PLAN_RANK = {"pro": 5, "team": 4, "enterprise": 4, "business": 3, "plus": 2, "go": 1}

# Tài khoản vừa bị đẩy xuống cuối (429/cạn quota) nằm dưới đáy trong bao lâu.
# Cùng tinh thần với `provider_demote_seconds` của `provider_order`: hạ tạm thời
# rồi tự về chỗ cũ, không phải loại vĩnh viễn. Chỉnh bằng
# `smart_pool.account_demote_seconds`.
_HA_TAI_KHOAN_GIAY = 900

# Số lượt ẢNH lỗi LIÊN TIẾP của cùng một tài khoản trước khi hạ nó xuống đáy.
# Lần đầu chỉ đếm — vòng xoay của `_acquire_next_candidate_token` đã tự sang tài
# khoản kế ở lượt sau, nên hạ ngay từ một lượt lỗi lẻ (nội dung bị chặn, 5xx chớp
# nhoáng) là đẩy một tài khoản lành xuống đáy 15 phút.
#
# VÌ SAO PHẢI CÓ MỐC HẠ Ở ĐƯỜNG ẢNH: `_bac_uu_tien` cố ý KHÔNG có thành phần sức
# khoẻ (để giữ vòng xoay dàn tải), nên bộ đếm `fail` một mình không đẩy được tài
# khoản nào xuống. Trước khi có bậc gói thì điều đó vô hại — đường ảnh xoay đều
# trên mọi tài khoản khả dụng nên tài khoản lỗi chỉ ăn 1/N lượt. Từ lúc
# `_loc_bac_cao_nhat` chỉ giữ bậc cao nhất thì một tài khoản gói cao đang lỗi mà
# là tài khoản gói cao DUY NHẤT sẽ nhận 100% lượt ảnh. Đây bịt đúng chỗ đó.
_NGUONG_HA_KHI_LOI = 2


def bac_goi(account: dict | None) -> int:
    """Bậc gói của tài khoản (cao hơn = dùng trước). Không rõ gói → 0 như free."""
    if not isinstance(account, dict):
        return 0
    return PLAN_RANK.get(str(account.get("plan") or "").strip().lower(), 0)


def dang_bi_ha(account: dict | None) -> bool:
    """Tài khoản có đang trong thời gian bị đẩy xuống cuối hàng không?

    `demote_account()` đẩy tài khoản vừa dính 429 xuống cuối pool, nhưng thứ tự
    pool chỉ còn tác dụng khi mọi tiêu chí khác BẰNG NHAU. Khi đã xếp theo bậc
    gói thì một tài khoản Plus vừa cạn sẽ lại thắng ngay ở lượt sau — đúng thứ
    chủ máy dặn tránh 10/08/2026: "ưu tiên nhưng khi hết quota thì cũng sắp xếp
    xuống cuối chứ không phải lúc nào cũng số #1". Nên việc bị hạ phải thành một
    tiêu chí ĐỨNG TRÊN bậc gói, và muốn vậy thì phải có mốc thời gian.
    """
    if not isinstance(account, dict):
        return False
    moc = account.get("demoted_at")
    if not moc:
        return False
    try:
        from datetime import datetime
        dt = datetime.strptime(str(moc), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False
    han = _HA_TAI_KHOAN_GIAY
    sp = config.data.get("smart_pool")
    if isinstance(sp, dict):
        try:
            han = max(30, int(sp.get("account_demote_seconds", _HA_TAI_KHOAN_GIAY)))
        except Exception:
            han = _HA_TAI_KHOAN_GIAY
    return (datetime.now() - dt).total_seconds() < han

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
    # Nhãn `free` cũng là nhãn RÕ RÀNG nên phải thắng plan, đúng nguyên tắc
    # "type tags beat plan" ghi ở đầu hàm — trước đây chỉ áp cho standard/openai.
    #
    # Đo 18/08 trên máy chủ thật: bios.disused99+…@icloud.com mang type=free
    # nhưng plan=plus, nên rơi xuống luật dưới và bị xếp vào pool Codex, trong
    # khi nó được thêm vào để dùng như tài khoản free qua chatgpt.com.
    if GROUP_FREE in types:
        return GROUP_FREE
    # A chatgpt.com web account on a paid subscription → codex/paid pool.
    if plan in PAID_PLANS:
        return GROUP_CODEX
    return GROUP_FREE


def han_nghi_chua_toi(account: dict | None) -> bool:
    """True khi tài khoản đang `limited` và `restore_at` VẪN ở tương lai.

    `restore_at` là hạn nghỉ do chính upstream báo (Codex trả header
    `x-codex-primary-reset-at` khi 429 usage_limit). Trước hạn đó thì tài khoản
    chắc chắn còn cạn — mọi request tới nó chỉ đổi lấy một cú 429 nữa.
    """
    if not isinstance(account, dict) or str(account.get("status") or "") != "limited":
        return False
    raw = account.get("restore_at")
    if not raw:
        return False   # không có hạn → để tầng khác quyết (revive_stuck_limited)
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except Exception:
        return False   # hạn không đọc được → coi như không có hạn
    return datetime.now(timezone.utc) < t


def giu_han_nghi(current: dict | None, result: dict) -> dict:
    """Bỏ `status`/`restore_at` khỏi kết quả refresh khi hạn nghỉ CHƯA tới.

    Vì sao cần: `OpenAIBackendAPI.get_user_info()` tính `status` từ hạn mức
    **ảnh** của chatgpt.com (`_extract_quota_and_restore_at` chỉ đọc
    `feature_name == "image_gen"`), rồi trả `status="active"` khi còn lượt tạo
    ảnh. Nhưng cú 429 khiến tài khoản thành `limited` lại là quota **text** của
    Codex — hai đồng hồ khác nhau.

    Đo thật 02/08 trên máy chủ: cả 7 tài khoản Codex đều `status=active` trong
    khi `restore_at` còn ở tương lai (03/08 06:00 → 11:01). Bộ đếm 5 phút ở
    `api/support.py` refresh mọi tài khoản `limited`, đồng hồ ảnh nói "còn lượt"
    ⇒ bật lại `active` ⇒ lượt chat sau lấy ra dùng ⇒ 429. Mà
    `_handle_openai_oauth_chat` thử tới 8 tài khoản một lượt, nên mỗi câu chat
    đốt cả một loạt 429 thật trước khi rơi xuống provider kế tiếp.

    Sau hàm này, đồng hồ ảnh vẫn cập nhật `quota` / `limits_progress` / email
    như cũ — nó chỉ không còn quyền xoá hạn nghỉ do upstream đặt ra.
    """
    if not isinstance(result, dict) or not han_nghi_chua_toi(current):
        return result if isinstance(result, dict) else {}
    giu = {k: v for k, v in result.items() if k not in ("status", "restore_at")}
    logger.info({
        "event": "refresh_khong_xoa_han_nghi",
        "email": str((current or {}).get("email") or "")[:80],
        "restore_at": str((current or {}).get("restore_at") or "")[:25],
        "status_bi_bo": str(result.get("status") or ""),
    })
    return giu


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
    "异常": "error",   # KHÓA ĐẦU VÀO (nhãn dữ liệu cũ) — không phải chuỗi hiển thị, đừng dịch
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

    @staticmethod
    def _giu_danh_tinh_codex(acc: dict | None) -> bool:
        """Dòng này mang danh tính Codex/OAuth — đường free KHÔNG được đụng vào.

        Vì sao cần: nhóm được suy từ `plan`, nên một tài khoản Codex vừa hết gói
        trả phí TẠM THỜI trông như free. Nếu đúng lúc đó đường free nhận nó là
        "dòng free cũ của email này" rồi đóng đinh `type="free"` (bên dưới), việc
        tụt hạng thành vĩnh viễn. Đo thật trên máy chủ 15/08/2026: 18 email từng
        nằm nhóm codex, chỉ còn 3; phần lớn số biến mất nay là dòng free mang
        `type=free`, và 27 lần một dòng đổi nhóm được ghi lại trong nhật ký.

        `refresh_token` là dấu hiệu chắc nhất: chỉ luồng OAuth Codex mới có, còn
        tài khoản free là JWT web nên không bao giờ có.
        """
        if not isinstance(acc, dict):
            return False
        if str(acc.get("refresh_token") or "").strip():
            return True
        types = {t.strip() for t in str(acc.get("type") or "").split(",") if t.strip()}
        return bool(types & {"codex", "antigravity"})

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
            # Cùng access_token mà dòng đang giữ là Codex thì DỪNG hẳn: ghi tiếp
            # là thay dòng đó bằng một dòng free ở cùng khoá, tức xoá mất
            # credential OAuth. Thà bỏ lượt ghi còn hơn mất tài khoản.
            dang_giu = self._accounts.get(access_token)
            if self._giu_danh_tinh_codex(dang_giu):
                logger.info({"event": "bo_qua_ghi_free_len_dong_codex",
                             "email": email or "", "token": anonymize_token(access_token)})
                return {"added": 0, "updated": 0, "skipped": 1}
            existing_token = None
            existing = None
            if email:
                for t, acc in list(self._accounts.items()):
                    if account_group(acc) != GROUP_FREE or self._giu_danh_tinh_codex(acc):
                        continue
                    if self._email_from_token_or_account(t, acc) == email:
                        existing_token, existing = t, acc
                        break
            # Không tra được email (JWT thiếu email) → tránh phantom "Thêm 1 free"
            # mỗi lần đồng bộ/khôi phục: nếu ĐÚNG access_token này đã có sẵn thì coi
            # là cập nhật, không phải thêm mới.
            if existing is None:
                cur = self._accounts.get(access_token)
                if cur is not None and account_group(cur) == GROUP_FREE:
                    existing_token, existing = access_token, cur
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
        if not existing:
            log_service.add(LOG_TYPE_ACCOUNT, "Thêm ChatGPT free",
                            {"provider": "free", "email": email})
        elif replaced:
            log_service.add(
                LOG_TYPE_ACCOUNT,
                "Cập nhật ChatGPT free (theo email, không trùng)",
                {"provider": "free", "email": email, "replaced": True},
            )
        # else: cùng access_token, chỉ làm mới field → KHÔNG log (tránh spam mỗi
        # lần đồng bộ/khôi phục khi không có thay đổi thực sự).
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

    def _bac_uu_tien(self, token: str) -> tuple[int, int]:
        """(chưa bị hạ, bậc gói) của một token — khoá ưu tiên của ĐƯỜNG ẢNH.

        Không có thành phần sức khoẻ như `_selection_key`: đường ảnh cố tình xoay
        vòng để dàn tải và đếm slot đang chạy, nên trong cùng một bậc phải giữ
        nguyên vòng xoay đó."""
        return (0 if dang_bi_ha(self._accounts.get(token) or {}) else 1,
                bac_goi(self._accounts.get(token) or {}))

    def _loc_bac_cao_nhat(self, tokens: list[str]) -> list[str]:
        """Giữ lại các token ở bậc ưu tiên cao nhất, bỏ phần còn lại.

        Lọc chứ không sắp xếp: xoay vòng trên danh sách đã sắp vẫn rơi xuống bậc
        thấp sau mỗi lượt. Bậc cao bận hết (hoặc `limited`) thì chúng đã rụng
        khỏi danh sách ứng viên từ trước, nên bậc dưới tự lên thay — ưu tiên chứ
        không phải chặn đường."""
        if len(tokens) < 2:
            return tokens
        cao_nhat = max(self._bac_uu_tien(t) for t in tokens)
        return [t for t in tokens if self._bac_uu_tien(t) == cao_nhat]

    def _acquire_next_candidate_token(self, excluded_tokens: set[str] | None = None) -> str:
        with self._image_slot_condition:
            while True:
                if not self._list_ready_candidate_tokens(excluded_tokens):
                    raise RuntimeError("no available image quota")
                tokens = self._loc_bac_cao_nhat(
                    self._list_available_candidate_tokens(excluded_tokens))
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
            if len(candidates) > 1:
                # max() ổn định → khoá bằng nhau giữ nguyên thứ tự FIFO.
                return max(candidates, key=lambda c: self._selection_key(c[1]))[0]
            return candidates[0][0]

    @staticmethod
    def _weighted_enabled() -> bool:
        sp = config.data.get("smart_pool")
        if isinstance(sp, dict):
            return bool(sp.get("enabled", True)) and bool(sp.get("weighted", True))
        return True

    @classmethod
    def _selection_key(cls, account: dict) -> tuple[int, int, float]:
        """Khoá chọn account, so sánh theo BẬC — trên trước, dưới chỉ để phá hoà.

            1. chưa bị hạ  (vừa cạn quota → xuống đáy, thắng cả bậc gói)
            2. bậc gói     (pro > team/enterprise > business > plus > go > free)
            3. sức khoẻ    (success-rate + né account vừa dùng — `_selection_weight`)

        Dùng bộ ba thay cho một con số vì mỗi luật cần một THỨ BẬC rõ ràng: gộp
        vào một số thì phải cân hằng số cho luật nọ khỏi nuốt luật kia, và lần
        chỉnh sau sẽ không ai biết vì sao con số đó là 0.1 chứ không phải 0.3.
        `max()` so sánh tuple theo thứ tự từ trái, và ổn định — bằng nhau cả ba
        thì giữ nguyên thứ tự pool (FIFO) y như trước.

        Tắt `smart_pool` chỉ bỏ tiêu chí 3 (heuristic), KHÔNG bỏ hai tiêu chí
        đầu: đó là chính sách chủ máy chọn, không phải phỏng đoán của máy.
        """
        suc_khoe = cls._selection_weight(account) if cls._weighted_enabled() else 0.0
        return (0 if dang_bi_ha(account) else 1, bac_goi(account), suc_khoe)

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
        # 'deactivated' = OpenAI đã xóa tài khoản, đang chờ admin trả lời xóa/giữ.
        # Không hạ về 'error' nữa: hạ xong là lượt quét định kỳ lại coi nó "chết
        # tạm" và thử khôi phục tiếp, vô tận. Đo thật 02/08 (benbap2011@gmail.com):
        # vừa đánh dấu deactivated lúc 12:08 thì job refresh_accounts gọi vào đây
        # ghi đè ngược về 'error' và spawn luôn một lượt khôi phục mới.
        if str((snapshot or {}).get("status") or "") == "deactivated":
            logger.info({
                "event": "skip_invalid_deactivated",
                "email": str((snapshot or {}).get("email") or "")[:80],
                "source": event,
            })
            return False
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
            # Ghi mốc bị hạ, KHÔNG chỉ đổi vị trí. Vị trí trong pool chỉ còn tác
            # dụng khi mọi tiêu chí khác bằng nhau, nên từ lúc xếp theo bậc gói
            # (10/08/2026) thì một tài khoản gói cao vừa cạn vẫn thắng ngay lượt
            # sau nếu không có mốc này. Xem `dang_bi_ha`.
            current = dict(current)
            current["demoted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

    def list_limited_tokens(self, *, due_only: bool = False) -> list[str]:
        """Token của các tài khoản đang `limited`.

        `due_only=True` → chỉ những cái ĐÃ tới hạn hồi (`restore_at` đã qua hoặc
        không có). Bộ đếm 5 phút ở `api/support.py` dùng cờ này để thôi gọi
        upstream cho tài khoản còn đang nghỉ — vừa tốn request, vừa là chỗ đồng
        hồ ảnh bật `active` sớm (xem `giu_han_nghi`).
        """
        with self._lock:
            return [
                token
                for item in self._accounts.values()
                if item.get("status") == "limited"
                   and not (due_only and han_nghi_chua_toi(item))
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
        # Chỉ báo khi CÓ thay đổi thật (thêm/cập nhật). Không thì im — tránh
        # "Thêm 0 free…" / phantom lúc đồng bộ định kỳ khi chẳng có tài khoản mới.
        if added or updated:
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
            # Ghi lại XOÁ AI, không chỉ xoá mấy cái: nhật ký cũ chỉ có
            # `{"removed": 1}` nên khi tài khoản biến mất dần thì không truy
            # được cái nào đã đi và đi lúc nào.
            da_xoa: list[str] = []
            for token in target_set:
                acc = self._accounts.pop(token, None)
                if acc is None:
                    continue
                da_xoa.append(str(acc.get("email") or "").strip()[:80]
                              or anonymize_token(token))
            removed = len(da_xoa)
            for token in target_set:
                self._image_inflight.pop(token, None)
            if removed:
                if self._accounts:
                    self._index %= len(self._accounts)
                else:
                    self._index = 0
                self._save_accounts()
                log_service.add(LOG_TYPE_ACCOUNT, f"Đã xóa {removed} tài khoản",
                                {"removed": removed, "emails": da_xoa})
            items = [dict(item) for item in self._accounts.values()]
        return {"removed": removed, "items": items}

    def _bao_dong_bi_nuot(self, bi_nuot: dict, giu_lai: dict, token: str) -> None:
        """Một dòng tài khoản bị đè mất chỗ vì trùng access_token — phải báo.

        Trùng token là chuyện có thật: thêm "ChatGPT free" lấy token từ đúng
        profile trình duyệt đang đăng nhập sẵn một tài khoản có tên, nên hai
        dòng cùng token. Pool đánh khoá bằng token nên buộc phải bỏ một dòng.

        Bỏ thì bỏ, nhưng KHÔNG được lặng lẽ: đo 18/08 trên máy chủ thật có 21
        token từng bị dùng chung, mà nhật ký không có nổi một dòng nào ghi lại,
        nên tài khoản Codex cứ vơi dần và không ai truy được cái nào đã đi.

        Cùng danh tính (cùng email) thì chỉ là gộp dòng trùng — ghi nhật ký cho
        đủ vết. KHÁC danh tính là mất dữ liệu thật — báo thẳng cho admin.
        """
        em_mat = str(bi_nuot.get("email") or "").strip()
        em_giu = str(giu_lai.get("email") or "").strip()
        cung_danh_tinh = em_mat.lower() == em_giu.lower()
        chi_tiet = {
            "token": anonymize_token(token),
            "mat_email": em_mat[:80] or "(không có email)",
            "mat_provider": account_group(bi_nuot) or "?",
            "mat_status": str(bi_nuot.get("status") or ""),
            "giu_email": em_giu[:80] or "(không có email)",
            "giu_provider": account_group(giu_lai) or "?",
            "cung_danh_tinh": cung_danh_tinh,
        }
        log_service.add(
            LOG_TYPE_ACCOUNT,
            ("Gộp dòng trùng token" if cung_danh_tinh
             else "Mất một dòng tài khoản do trùng access_token"),
            chi_tiet,
        )
        if cung_danh_tinh:
            return
        logger.warning({"event": "account_row_overwritten", **chi_tiet})
        try:
            from services.notifier import notify_admin
            notify_admin(
                "⚠️ Mất một dòng tài khoản (trùng access_token)\n"
                f"Bị đè mất: {chi_tiet['mat_email']} · {chi_tiet['mat_provider']}"
                f" · {chi_tiet['mat_status'] or 'không rõ trạng thái'}\n"
                f"Giữ lại  : {chi_tiet['giu_email']} · {chi_tiet['giu_provider']}\n"
                "Hai dòng nhận cùng một access_token nên pool chỉ giữ được một. "
                "Nếu dòng bị mất còn cần thì thêm lại.",
                category="account_log",
            )
        except Exception as exc:
            logger.warning({"event": "account_row_overwritten_notify_failed",
                            "error": str(exc)[:120]})

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
            bi_nuot: dict | None = None
            if new_token != access_token:
                self._accounts.pop(access_token, None)
                # Pool đánh khoá bằng access_token, nên hai dòng trùng token thì
                # chỉ một dòng sống. Bản cũ pop thẳng, KHÔNG ghi gì: đo 18/08 có
                # 21 token từng bị một dòng "free" vô danh và một tài khoản có
                # tên dùng chung, tức đã có chừng ấy dòng biến mất lặng lẽ —
                # đúng cái người vận hành báo "tài khoản tự xoá không thấy báo".
                bi_nuot = self._accounts.pop(new_token, None)
            self._accounts[new_token] = account
            self._save_accounts()
            if bi_nuot is not None:
                self._bao_dong_bi_nuot(bi_nuot, account, new_token)
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
                # Dùng lại được rồi thì hết bị hạ — về đúng chỗ cũ ngay, không
                # phải chờ hết cửa sổ. Cùng cách `provider_order` đối xử với
                # provider hồi phục.
                next_item.pop("demoted_at", None)
                next_item.pop("fail_streak", None)
                if not image_quota_unknown:
                    next_item["quota"] = max(0, int(next_item.get("quota") or 0) - 1)
                if not image_quota_unknown and next_item["quota"] == 0:
                    next_item["status"] = "limited"
                    next_item["restore_at"] = next_item.get("restore_at") or None
                elif next_item.get("status") == "limited":
                    next_item["status"] = "active"
            else:
                next_item["fail"] = int(next_item.get("fail") or 0) + 1
                # Lỗi LIÊN TIẾP lần thứ `_NGUONG_HA_KHI_LOI` mới hạ; lần đầu chỉ
                # đếm rồi để vòng xoay tự sang tài khoản kế. Đóng dấu `demoted_at`
                # y như đường 429 nên nó rơi vào ĐÚNG tiêu chí 1 của
                # `_selection_key` / `_bac_uu_tien` — đứng trên bậc gói, tức tài
                # khoản gói cao đang lỗi cũng phải nhường. Không thêm cơ chế mới.
                lien_tiep = int(next_item.get("fail_streak") or 0) + 1
                next_item["fail_streak"] = lien_tiep
                if lien_tiep >= _NGUONG_HA_KHI_LOI:
                    next_item["demoted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        # Đồng hồ ảnh của chatgpt.com KHÔNG được xoá hạn nghỉ của quota text.
        return self.update_account(
            access_token, giu_han_nghi(self.get_account(access_token), result)
        )

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
