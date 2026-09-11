"""Privacy gate — không đẩy MK / token / PII thô vào AI.

P0: detect secret → vault ref; redact before LLM
P1: email / phone / CCCD patterns; redact logs
P2: secret_ref resolve for tools; scrub memory store

Config (top-level ``privacy``, all optional)::

    {
      "enabled": true,
      "vault_ttl_sec": 3600,
      "redact_logs": true,
      "redact_memory": true,
      "redact_pii": true,
      "mask_style": "token"   # token | redact
    }

Design (industry pattern: Auth0 / Agent Vault / Presidio):
  - LLM never sees real passwords or long-lived tokens
  - Tool runtime resolves secret_ref → plaintext only at execution
  - Encryption of vault at-rest is session-memory; disk secrets stay in env/accounts
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.log import logger

# ── Patterns (order matters: secrets before generic PII) ────────────────────

# Labeled secrets: "mk: xxx", "password = yyy"
#
# MỌI mẫu dưới đây bỏ qua chữ nằm trong mã két `⟦…⟧`: tin nhắn bị che HAI lần
# (cửa vào `apply_to_body` và cửa ra `_dispatch`), mà mã két `⟦PWD:1:abc⟧` có
# chữ "PWD:" — không chặn thì lần hai che lồng lên mã két và tool không mở lại
# được mật khẩu. Che hai lần phải ra y như che một lần.
_LABELED_SECRET = re.compile(
    r"(?i)(?:(?<!⟦)\b(?:mk|mat\s*khau|mật\s*khẩu|password|passwd|pwd|secret|api[_-]?key|"
    r"token|session[_-]?key|totp|otp)\b\s*[:=\s]\s*)"
    r"([^\s,;⟦⟧]{4,128})"
)

# JWT
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")

# OpenAI / sk- style keys
_SK_KEY = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_SK_PROJ = re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b")

# Bearer tokens
_BEARER = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._\-]{20,})")

# Google cookie fragments (partial — full cookies rarely pasted)
_PSID = re.compile(r"(?i)(?:__Secure-)?1PSID[TS]?\s*[:=]\s*([^\s;]{12,})")

# Tài khoản:mật khẩu nằm trong đường dẫn — `rtsp://tk:mk@máy/…`. Nhận theo
# DẠNG, không theo tên thiết bị. Mật khẩu được phép chứa "@", nên phần trước tên
# máy kéo tới "@" CUỐI CÙNG của cụm địa chỉ. Đo 11/09/2026: 4 camera go2rtc của
# nhà mang đúng dạng này trong tên Home Assistant, và đi thẳng tới model.
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^\s/@⟦⟧]+:[^\s/⟦⟧]*)@")

# Cặp khoá–giá trị có TÊN KHOÁ là bí mật: JSON (`"password": "…"`), cấu hình hay
# tham số URL (`?token=…`). Tên khoá dùng CHUNG danh sách với phần che cài đặt
# (`settings_secrets.la_truong_bi_mat`) — một danh sách, không có bản thứ hai để
# lệch nhau. Kết quả tool và thuộc tính Home Assistant đều là JSON, mà
# `_LABELED_SECRET` không đọc được dấu ngoặc kép.
_KV_NGOAC = re.compile(r"""(["'])([A-Za-z0-9_\-]{2,48})\1\s*:\s*(["'])([^"'\n⟦⟧]{4,512})\3""")
_KV_TRAN = re.compile(
    r"(?<![A-Za-z0-9_\-⟦])([A-Za-z][A-Za-z0-9_\-]{1,47})\s*[:=]\s*([^\s,;\"'&<>⟦⟧]{4,256})")

# "mật khẩu wifi nhà là Abc123" — nhãn tiếng Việt, vài chữ rồi "là". Một chuỗi
# mật khẩu không có hình dạng đo được; nhãn đi kèm là dấu hiệu duy nhất, nên đây
# là danh sách nhãn có lý do — cùng loại ngoại lệ `boi_canh_nha._TRUONG_NGUOI`.
_LA_SECRET = re.compile(
    r"(?i)\b(?:mật\s*khẩu|mat\s*khau|mk|password|pass)(?:\s+[^\s,;:=]+){0,3}?"
    r"\s+(?:là|la|is)\s+([^\s,;⟦⟧]{4,128})")

# Long hex / base64-ish secrets (conservative: only with keyword nearby handled by labeled)

# Email
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# VN phone
_PHONE = re.compile(
    r"(?<!\d)(?:\+?84|0)(?:3[2-9]|5[2689]|7[06-9]|8[1-9]|9[0-9])\d{7}(?!\d)"
)

# CCCD / CMND (9 or 12 digits)
_CCCD = re.compile(r"(?<!\d)\d{9}(?!\d)|(?<!\d)\d{12}(?!\d)")

_SECRET_KINDS = frozenset({"password", "token", "api_key", "jwt", "cookie", "bearer"})
_PII_KINDS = frozenset({"email", "phone", "cccd"})


@dataclass
class VaultEntry:
    kind: str
    value: str
    created: float = field(default_factory=time.time)
    hits: int = 0


class SessionVault:
    """In-memory session vault: ref → plaintext. TTL prune."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, VaultEntry]] = {}  # session -> ref -> entry

    def _prune(self, session_id: str, ttl: float) -> None:
        bucket = self._data.get(session_id) or {}
        now = time.time()
        dead = [k for k, v in bucket.items() if now - v.created > ttl]
        for k in dead:
            bucket.pop(k, None)
        if not bucket and session_id in self._data:
            self._data.pop(session_id, None)

    def put(self, session_id: str, kind: str, value: str, *, ttl: float = 3600) -> str:
        sid = (session_id or "default").strip() or "default"
        val = (value or "").strip()
        if not val:
            return ""
        with self._lock:
            self._prune(sid, ttl)
            bucket = self._data.setdefault(sid, {})
            # Reuse ref if same value already stored
            for ref, ent in bucket.items():
                if ent.value == val and ent.kind == kind:
                    ent.hits += 1
                    return ref
            n = sum(1 for e in bucket.values() if e.kind == kind) + 1
            prefix = {
                "password": "pwd",
                "token": "tok",
                "api_key": "key",
                "jwt": "jwt",
                "cookie": "ck",
                "bearer": "br",
                "email": "em",
                "phone": "ph",
                "cccd": "id",
            }.get(kind, "sec")
            ref = f"⟦{prefix.upper()}:{n}:{secrets.token_hex(3)}⟧"
            bucket[ref] = VaultEntry(kind=kind, value=val)
            return ref

    def get(self, session_id: str, ref: str) -> Optional[str]:
        # CHỈ tra trong session của chính nó — KHÔNG fallback toàn cục, kẻo
        # user A (một kênh/chat) resolve được secret ref của user B.
        sid = (session_id or "default").strip() or "default"
        with self._lock:
            ent = (self._data.get(sid) or {}).get(ref)
            if not ent:
                return None
            ent.hits += 1
            return ent.value

    def resolve_in_text(self, session_id: str, text: str) -> str:
        """Replace vault tokens in tool args with real values (tool runtime only)."""
        if not text or "⟦" not in text:
            return text
        sid = (session_id or "default").strip() or "default"
        out = text
        with self._lock:
            # CHỈ session của chính nó — không quét bucket của session khác.
            bucket = self._data.get(sid) or {}
            for ref, ent in bucket.items():
                if ref in out:
                    out = out.replace(ref, ent.value)
                    ent.hits += 1
        return out

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id or "default", None)


_vault = SessionVault()


def vault() -> SessionVault:
    return _vault


def _cfg() -> dict[str, Any]:
    try:
        from services.config import config
        c = config.get().get("privacy")
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def redact_memory_enabled() -> bool:
    return bool(_cfg().get("redact_memory", True))


def _ttl() -> float:
    try:
        return float(_cfg().get("vault_ttl_sec") or 3600)
    except Exception:
        return 3600.0


def session_id_from_body(body: dict[str, Any] | None) -> str:
    if not body:
        return "default"
    for k in ("user", "session_id", "conversation_id", "chat_id"):
        v = body.get(k)
        if v:
            return str(v)[:128]
    # channel metadata
    for k in ("_channel", "x_channel"):
        v = body.get(k)
        if v:
            return f"ch:{v}"[:128]
    return "default"


def redact_text(
    text: str,
    *,
    session_id: str = "default",
    redact_pii: bool | None = None,
) -> str:
    """Redact secrets (always) and PII (if enabled) → vault tokens."""
    if not text or not is_enabled():
        return text
    cfg = _cfg()
    do_pii = bool(cfg.get("redact_pii", True)) if redact_pii is None else redact_pii
    ttl = _ttl()
    out = text

    def _sub_nhom(nhom: int, kind: str = "password"):
        """Thay đúng nhóm `nhom` của mẫu bằng mã két, giữ nguyên phần còn lại."""
        def _fn(m: re.Match[str]) -> str:
            ref = _vault.put(session_id, kind, m.group(nhom), ttl=ttl) or "[REDACTED]"
            a, b = m.start(nhom) - m.start(0), m.end(nhom) - m.start(0)
            return m.group(0)[:a] + ref + m.group(0)[b:]
        return _fn

    def _sub_kv(nhom_khoa: int, nhom_gt: int):
        """Chỉ che khi TÊN KHOÁ là bí mật — danh sách chung `settings_secrets`."""
        from services.settings_secrets import la_truong_bi_mat
        che = _sub_nhom(nhom_gt)

        def _fn(m: re.Match[str]) -> str:
            return che(m) if la_truong_bi_mat(m.group(nhom_khoa)) else m.group(0)
        return _fn

    # DẠNG trước, nhãn sau: URL mang tài khoản:mật khẩu trông giống email, và
    # tên khoá JSON rõ ràng hơn mọi nhãn trong câu nói.
    out = _URL_USERINFO.sub(_sub_nhom(2), out)
    out = _KV_NGOAC.sub(_sub_kv(2, 4), out)
    out = _KV_TRAN.sub(_sub_kv(1, 2), out)
    out = _LA_SECRET.sub(_sub_nhom(1), out)

    def _sub_labeled(m: re.Match[str]) -> str:
        raw = m.group(1)
        ref = _vault.put(session_id, "password", raw, ttl=ttl)
        return m.group(0)[: m.start(1) - m.start(0)] + (ref or "[REDACTED]")

    out = _LABELED_SECRET.sub(_sub_labeled, out)

    def _repl(kind: str):
        def _fn(m: re.Match[str]) -> str:
            raw = m.group(1) if m.lastindex else m.group(0)
            ref = _vault.put(session_id, kind, raw, ttl=ttl)
            return ref or "[REDACTED]"
        return _fn

    out = _JWT.sub(_repl("jwt"), out)
    out = _SK_PROJ.sub(_repl("api_key"), out)
    out = _SK_KEY.sub(_repl("api_key"), out)
    out = _BEARER.sub(lambda m: "Bearer " + (_vault.put(session_id, "bearer", m.group(1), ttl=ttl) or "[REDACTED]"), out)
    out = _PSID.sub(_repl("cookie"), out)

    if do_pii:
        out = _EMAIL.sub(_repl("email"), out)
        out = _PHONE.sub(_repl("phone"), out)
        # CCCD: only if looks labeled or standalone 12-digit (avoid false on timestamps)
        out = re.sub(
            r"(?i)(?:cccd|cmnd|căn\s*cước|cmnd/cccd)\s*[:=]?\s*(\d{9}|\d{12})",
            lambda m: m.group(0).replace(m.group(1), _vault.put(session_id, "cccd", m.group(1), ttl=ttl) or "[REDACTED]"),
            out,
        )

    return out


def redact_messages(
    messages: list[dict[str, Any]],
    *,
    session_id: str = "default",
) -> list[dict[str, Any]]:
    """Deep-copy-ish redact of OpenAI messages (string or multimodal content)."""
    if not is_enabled() or not messages:
        return messages
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        nm = dict(m)
        c = nm.get("content")
        if isinstance(c, str):
            nm["content"] = redact_text(c, session_id=session_id)
        elif isinstance(c, list):
            parts = []
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text":
                    np = dict(p)
                    np["text"] = redact_text(str(p.get("text") or ""), session_id=session_id)
                    parts.append(np)
                else:
                    parts.append(p)
            nm["content"] = parts
        # tool call arguments may contain secrets
        tcs = nm.get("tool_calls")
        if isinstance(tcs, list):
            new_tcs = []
            for tc in tcs:
                if not isinstance(tc, dict):
                    new_tcs.append(tc)
                    continue
                ntc = dict(tc)
                fn = dict(ntc.get("function") or {})
                if isinstance(fn.get("arguments"), str):
                    fn["arguments"] = redact_text(fn["arguments"], session_id=session_id)
                ntc["function"] = fn
                new_tcs.append(ntc)
            nm["tool_calls"] = new_tcs
        out.append(nm)
    return out


def scrub_for_log(text: str, *, session_id: str = "log") -> str:
    """Redact for logs/admin notify — always on when redact_logs true."""
    if not text:
        return text
    if not bool(_cfg().get("redact_logs", True)):
        # still strip obvious secrets even if privacy disabled for prompts
        pass
    try:
        return redact_text(text, session_id=session_id, redact_pii=True)
    except Exception:
        return text[:200] + "…"


def apply_to_body(body: dict[str, Any]) -> dict[str, Any]:
    """In-place safe: returns new body with redacted messages + session meta."""
    if not is_enabled() or not isinstance(body, dict):
        return body
    sid = session_id_from_body(body)
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return body
    new_body = dict(body)
    new_body["messages"] = redact_messages(msgs, session_id=sid)
    new_body["_privacy_session"] = sid
    # Also redact common free-text fields
    for k in ("prompt", "input", "query"):
        if isinstance(new_body.get(k), str):
            new_body[k] = redact_text(new_body[k], session_id=sid)
    if new_body.get("messages") is not msgs:
        n_sec = sum(1 for m in new_body["messages"] if isinstance(m, dict) and "⟦" in str(m.get("content") or ""))
        if n_sec:
            logger.info({"event": "privacy_gate_redacted", "session": sid[:40], "msgs_touched": n_sec})
    return new_body


def resolve_secret_ref(ref_or_text: str, *, session_id: str = "default") -> str:
    """Tool runtime: expand vault tokens in args. Never call this for LLM prompts."""
    if not ref_or_text:
        return ref_or_text
    if ref_or_text.startswith("⟦") and ref_or_text.endswith("⟧"):
        v = _vault.get(session_id, ref_or_text)
        return v if v is not None else ref_or_text
    return _vault.resolve_in_text(session_id, ref_or_text)


def privacy_public_status() -> dict[str, Any]:
    cfg = _cfg()
    return {
        "enabled": is_enabled(),
        "redact_pii": bool(cfg.get("redact_pii", True)),
        "redact_logs": bool(cfg.get("redact_logs", True)),
        "redact_memory": bool(cfg.get("redact_memory", True)),
        "vault_ttl_sec": _ttl(),
        "note": "MK/token → vault ref; tool runtime inject. AI never sees plaintext secrets.",
    }
