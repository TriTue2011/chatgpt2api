"""Email channel — IMAP poll inbound + SMTP reply (self-hosted, no broker).

Config (``email_channel``)::

    enabled: bool (default False)
    imap_host: str
    imap_port: int (default 993)
    smtp_host: str
    smtp_port: int (default 465)
    user: str
    password: str
    use_ssl: bool (default True)
    poll_seconds: int (default 60, min 20)
    allowed_senders: list[str]  — empty = deny-all; ["*"] = allow any
    subject_prefix: str (default "[Tiểu Vy]")
    max_body_chars: int (default 6000)
    mark_seen: bool (default True)

Inbound → agent orchestrate(user_id=email_<hash>) → SMTP reply.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import logging
import re
import smtplib
import ssl
import threading
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr, formataddr
from typing import Any, Optional

from services.config import config

logger = logging.getLogger(__name__)

_started = False
_stop = threading.Event()
_status: dict[str, Any] = {
    "running": False,
    "last_poll_at": 0.0,
    "last_error": "",
    "processed": 0,
    "skipped": 0,
}
_lock = threading.RLock()


def _cfg() -> dict[str, Any]:
    raw = config.get().get("email_channel")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    c = _cfg()
    return bool(c.get("enabled")) and bool(str(c.get("user") or "").strip())


def status() -> dict[str, Any]:
    with _lock:
        s = dict(_status)
    s["enabled"] = is_enabled()
    c = _cfg()
    s["user"] = str(c.get("user") or "")
    s["imap_host"] = str(c.get("imap_host") or "")
    return s


def _poll_seconds() -> float:
    try:
        return max(20.0, float(_cfg().get("poll_seconds") or 60))
    except (TypeError, ValueError):
        return 60.0


def _allowed(sender: str) -> bool:
    raw = _cfg().get("allowed_senders")
    if not isinstance(raw, list) or not raw:
        return False  # fail-closed
    sender_l = (sender or "").strip().lower()
    for item in raw:
        a = str(item or "").strip().lower()
        if not a:
            continue
        if a == "*":
            return True
        if a == sender_l:
            return True
        if a.startswith("@") and sender_l.endswith(a):
            return True
        if a in sender_l:
            return True
    return False


def _user_id_for(addr: str) -> str:
    h = hashlib.sha256(addr.lower().encode()).hexdigest()[:12]
    local = re.sub(r"[^a-z0-9]+", "", addr.split("@")[0].lower())[:16] or "user"
    return f"email_{local}_{h}"


def _decode_hdr(val: Any) -> str:
    if not val:
        return ""
    try:
        return str(make_header(decode_header(str(val))))
    except Exception:
        return str(val)


def _extract_body(msg: email.message.Message) -> str:
    max_c = 6000
    try:
        max_c = max(500, int(_cfg().get("max_body_chars") or 6000))
    except (TypeError, ValueError):
        pass
    text_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/plain":
                text_parts.append(decoded)
            elif ctype == "text/html":
                html_parts.append(decoded)
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if (msg.get_content_type() or "").lower() == "text/html":
                html_parts.append(decoded)
            else:
                text_parts.append(decoded)
        except Exception:
            pass
    body = "\n".join(text_parts).strip()
    if not body and html_parts:
        raw = "\n".join(html_parts)
        body = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
        body = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()
    return body[:max_c]


def send_email(
    to_addr: str,
    subject: str,
    body: str,
    *,
    in_reply_to: str = "",
    references: str = "",
) -> dict[str, Any]:
    c = _cfg()
    user = str(c.get("user") or "").strip()
    password = str(c.get("password") or "")
    host = str(c.get("smtp_host") or "").strip()
    if not host:
        # guess from imap
        imap_h = str(c.get("imap_host") or "")
        host = imap_h.replace("imap.", "smtp.") if imap_h else ""
    try:
        port = int(c.get("smtp_port") or 465)
    except (TypeError, ValueError):
        port = 465
    use_ssl = bool(c.get("use_ssl", True))
    if not user or not host or not to_addr:
        return {"ok": False, "error": "Thiếu smtp_host/user/to"}
    prefix = str(c.get("subject_prefix") or "[Tiểu Vy]").strip()
    subj = subject or "Re:"
    if prefix and prefix not in subj:
        subj = f"{prefix} {subj}"

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subj
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to
    msg.set_content(body or "(trống)")

    try:
        if use_ssl and port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if use_ssl or port == 587:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(msg)
        return {"ok": True}
    except Exception as exc:
        logger.warning("email_channel: smtp failed: %s", exc)
        return {"ok": False, "error": str(exc)[:200]}


def _process_message(raw: bytes) -> str:
    """Returns status: processed | skipped | error."""
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception as exc:
        logger.warning("email_channel: parse failed: %s", exc)
        return "error"

    from_hdr = _decode_hdr(msg.get("From"))
    _, from_addr = parseaddr(from_hdr)
    from_addr = (from_addr or "").strip().lower()
    if not from_addr:
        return "skipped"
    if not _allowed(from_addr):
        logger.info("email_channel: deny sender %s", from_addr)
        return "skipped"

    subject = _decode_hdr(msg.get("Subject"))
    body = _extract_body(msg)
    if not body and not subject:
        return "skipped"

    msg_id = str(msg.get("Message-ID") or "").strip()
    user_text = f"Tiêu đề: {subject}\n\n{body}".strip()
    user_id = _user_id_for(from_addr)

    try:
        from services.agent.orchestrator import orchestrate
        out = orchestrate(user_text, user_id, ha_fastpath=True)
        reply = str(out.get("text") or "").strip()
        if out.get("silent") or not reply:
            reply = "Dạ em đã nhận email nhưng không có nội dung trả lời ạ."
    except Exception as exc:
        logger.warning("email_channel: orchestrate failed: %s", exc)
        reply = f"Xin lỗi, hệ thống tạm lỗi: {str(exc)[:100]}"

    re_subj = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    sent = send_email(
        from_addr, re_subj, reply,
        in_reply_to=msg_id, references=msg_id,
    )
    if not sent.get("ok"):
        logger.warning("email_channel: reply failed: %s", sent.get("error"))
        return "error"
    return "processed"


def poll_once() -> dict[str, Any]:
    """Fetch UNSEEN mail and process. Safe for tests / manual trigger."""
    if not is_enabled():
        return {"ok": False, "error": "email_channel disabled"}
    c = _cfg()
    user = str(c.get("user") or "").strip()
    password = str(c.get("password") or "")
    host = str(c.get("imap_host") or "").strip()
    try:
        port = int(c.get("imap_port") or 993)
    except (TypeError, ValueError):
        port = 993
    use_ssl = bool(c.get("use_ssl", True))
    mark_seen = bool(c.get("mark_seen", True))
    if not host or not user:
        return {"ok": False, "error": "Thiếu imap_host/user"}

    processed = skipped = errors = 0
    try:
        if use_ssl:
            M = imaplib.IMAP4_SSL(host, port, timeout=40)
        else:
            M = imaplib.IMAP4(host, port, timeout=40)
        try:
            M.login(user, password)
            M.select("INBOX")
            typ, data = M.search(None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                ids: list[bytes] = []
            else:
                ids = data[0].split()
            # limit burst
            for num in ids[:10]:
                typ, msg_data = M.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    errors += 1
                    continue
                raw = msg_data[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    errors += 1
                    continue
                result = _process_message(bytes(raw))
                if result == "processed":
                    processed += 1
                    if mark_seen:
                        M.store(num, "+FLAGS", "\\Seen")
                elif result == "skipped":
                    skipped += 1
                    if mark_seen:
                        M.store(num, "+FLAGS", "\\Seen")
                else:
                    errors += 1
        finally:
            try:
                M.logout()
            except Exception:
                pass
    except Exception as exc:
        with _lock:
            _status["last_error"] = str(exc)[:200]
            _status["last_poll_at"] = time.time()
        logger.warning("email_channel: poll failed: %s", exc)
        return {"ok": False, "error": str(exc)[:200], "processed": processed}

    with _lock:
        _status["last_poll_at"] = time.time()
        _status["last_error"] = ""
        _status["processed"] = int(_status.get("processed") or 0) + processed
        _status["skipped"] = int(_status.get("skipped") or 0) + skipped

    return {
        "ok": True,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }


def test_connection() -> dict[str, Any]:
    """Login IMAP only — does not send mail."""
    c = _cfg()
    user = str(c.get("user") or "").strip()
    password = str(c.get("password") or "")
    host = str(c.get("imap_host") or "").strip()
    try:
        port = int(c.get("imap_port") or 993)
    except (TypeError, ValueError):
        port = 993
    use_ssl = bool(c.get("use_ssl", True))
    if not host or not user:
        return {"ok": False, "error": "Thiếu imap_host/user"}
    try:
        if use_ssl:
            M = imaplib.IMAP4_SSL(host, port, timeout=20)
        else:
            M = imaplib.IMAP4(host, port, timeout=20)
        try:
            M.login(user, password)
            typ, _ = M.select("INBOX")
            return {"ok": typ == "OK", "inbox": typ == "OK"}
        finally:
            try:
                M.logout()
            except Exception:
                pass
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _loop() -> None:
    _stop.wait(8)
    while not _stop.is_set():
        try:
            if is_enabled():
                poll_once()
        except Exception as exc:
            logger.warning("email_channel: loop error: %s", exc)
        _stop.wait(_poll_seconds())


def start() -> None:
    global _started
    if _started:
        return
    # LUÔN chạy thread supervisor kể cả khi đang tắt: _loop tự kiểm tra
    # is_enabled() mỗi vòng nên bật email trong Settings là chạy ngay ở tick
    # kế tiếp — KHÔNG cần restart container. Thread ngủ khi disabled, rẻ.
    if not is_enabled():
        logger.info("email_channel: disabled (supervisor chờ tới khi bật)")
    _started = True
    _stop.clear()
    with _lock:
        _status["running"] = True
    t = threading.Thread(target=_loop, name="email-channel", daemon=True)
    t.start()
    logger.info("email_channel: started poll=%ss", _poll_seconds())


def stop() -> None:
    global _started
    _stop.set()
    _started = False
    with _lock:
        _status["running"] = False


def _reset_for_tests() -> None:
    stop()
    with _lock:
        _status.update({
            "running": False,
            "last_poll_at": 0.0,
            "last_error": "",
            "processed": 0,
            "skipped": 0,
        })
