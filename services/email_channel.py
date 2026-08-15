"""Email channel — NHIỀU hộp mail: IMAP poll vào + SMTP trả lời + tóm tắt gửi kênh.

Config ``email_accounts`` (list — mỗi phần tử một hộp mail)::

    id: str                  — khóa ổn định (tự sinh nếu thiếu)
    label: str               — tên hiển thị ("Gmail chính")
    enabled: bool
    imap_host / imap_port    (mặc định 993)
    smtp_host / smtp_port    (mặc định 465; trống thì đoán từ imap_host)
    user: str                — địa chỉ email
    password: str            — GMAIL/OUTLOOK BẮT BUỘC "App Password" (mật khẩu
                               ứng dụng 16 ký tự), KHÔNG dùng mật khẩu đăng nhập:
                               https://myaccount.google.com/apppasswords
    use_ssl: bool (True)
    allowed_senders: list[str]  — rỗng = chặn hết; ["*"] = nhận mọi người
    mark_seen: bool (True)
    max_body_chars: int (6000)
    poll_seconds: int (60, min 20)
    reply_enabled: bool      — AI trả lời thẳng vào email (hành vi cũ)
    summarize_files: bool    — tóm tắt CẢ nội dung tệp đính kèm
    notify_on_new: bool      — có mail mới là tóm tắt gửi kênh ngay
    notify_times: list[str]  — ["07:00", "18:00"] gom lại gửi định kỳ
    notify_targets: list[str]— kênh nhận, khóa 'plat:bot:chat' như «Lọc thread»

Tương thích ngược: ``email_accounts`` rỗng thì đọc ``email_channel`` (cấu hình
một-hộp cũ) thành hộp mail #1 — không ghi đè, không cần migrate.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import logging
import os
import re
import smtplib
import ssl
import tempfile
import threading
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from services.config import config

logger = logging.getLogger(__name__)

_started = False
_stop = threading.Event()
_lock = threading.RLock()
# Trạng thái theo TỪNG hộp: {source_key: {...}}
_status_by_acc: dict[str, dict[str, Any]] = {}
_last_poll_at: dict[str, float] = {}

# Hộp đang có lượt poll CHẠY DỞ — chốt để không bao giờ chồng hai lượt trên
# cùng một hộp (chồng lượt = xử lý trùng thư, gửi thông báo đúp).
_inflight: set[str] = set()
_inflight_lock = threading.Lock()
# Số hộp poll song song. Mỗi thư tốn 1 lượt AI tóm tắt, file đính kèm còn thêm
# AI vision từng trang — trước đây các hộp chạy NỐI TIẾP nên một hộp nhiều thư
# là chặn hết phần còn lại (đo 2026-07-28: cả 2 hộp đứng 9 phút không nhích).
_POLL_WORKERS = 4

#: Gmail/Outlook bật 2FA thì mật khẩu thường bị từ chối — dịch lỗi thô của IMAP
#: thành hướng dẫn làm được ngay (đây là lỗi hay gặp nhất khi cài email).
_APP_PW_HINT = (
    "Cần App Password (mật khẩu ứng dụng), KHÔNG dùng mật khẩu đăng nhập. "
    "Gmail: bật 2FA rồi lấy 16 ký tự tại https://myaccount.google.com/apppasswords "
    "· Outlook: https://account.live.com/proofs/AppPassword"
)


# Các nhà cung cấp lớn bắt buộc App Password; mail công ty/nội bộ thì KHÔNG —
# dùng mật khẩu đăng nhập thường. Hint phải theo host kẻo chỉ dẫn sai đường.
_APP_PW_HOSTS = ("gmail", "google", "outlook", "office365", "hotmail", "live.com", "yahoo")


def _needs_app_pw(host: str) -> bool:
    h = (host or "").lower()
    return any(k in h for k in _APP_PW_HOSTS)


def _friendly_error(exc: Exception | str, host: str = "") -> str:
    """Lỗi IMAP/SMTP → câu tiếng Việt hành động được (hint theo loại mail)."""
    raw = str(exc)
    low = raw.lower()
    if "application-specific password" in low or "app password" in low:
        return f"❌ {_APP_PW_HINT}"
    if ("invalid credentials" in low or "authenticationfailed" in low
            or ("auth" in low and "fail" in low)):
        if _needs_app_pw(host):
            return f"❌ Sai tài khoản hoặc mật khẩu. {_APP_PW_HINT}"
        return ("❌ Sai tài khoản hoặc mật khẩu. Mail công ty/nội bộ dùng mật khẩu "
                "đăng nhập thường (không cần App Password) — kiểm tra lại bằng webmail.")
    if "name or service not known" in low or "getaddrinfo" in low:
        return "❌ Sai IMAP/SMTP host (không phân giải được tên miền)."
    if "timed out" in low or "timeout" in low:
        return "❌ Hết thời gian kết nối — kiểm tra host/port hoặc firewall."
    if "certificate" in low or "ssl" in low:
        return ("❌ Lỗi SSL/chứng chỉ — server nội bộ hay dùng chứng chỉ tự ký: "
                "bật «Chấp nhận mọi chứng chỉ» trong cài đặt hộp mail, "
                "hoặc kiểm tra lại host/port/loại bảo mật.")
    return f"❌ {raw[:200]}"


# ── Danh sách hộp mail ───────────────────────────────────────────────────────
def _legacy() -> dict[str, Any]:
    raw = config.get().get("email_channel")
    return raw if isinstance(raw, dict) else {}


def _norm_account(raw: Any, idx: int) -> dict[str, Any] | None:
    """Chuẩn hóa một hộp mail; None nếu không phải dict."""
    if not isinstance(raw, dict):
        return None
    user = str(raw.get("user") or "").strip()
    acc_id = str(raw.get("id") or "").strip()
    if not acc_id:
        # id ổn định theo user để state 'seen' không mất khi đổi thứ tự danh sách
        acc_id = hashlib.sha256(user.lower().encode()).hexdigest()[:8] if user else f"a{idx + 1}"

    def _int(key: str, default: int, lo: int = 1) -> int:
        try:
            return max(lo, int(raw.get(key) or default))
        except (TypeError, ValueError):
            return default

    imap_host = str(raw.get("imap_host") or "").strip()
    smtp_host = str(raw.get("smtp_host") or "").strip()
    if not smtp_host and imap_host:
        smtp_host = imap_host.replace("imap.", "smtp.")
    senders = raw.get("allowed_senders")
    if isinstance(senders, str):
        senders = [s.strip() for s in senders.split(",") if s.strip()]
    times = raw.get("notify_times")
    if isinstance(times, str):
        times = [s.strip() for s in times.split(",") if s.strip()]
    targets = raw.get("notify_targets")
    if isinstance(targets, str):
        targets = [s.strip() for s in targets.split(",") if s.strip()]
    return {
        "id": acc_id,
        "label": str(raw.get("label") or user or f"Hộp mail {idx + 1}").strip(),
        "enabled": bool(raw.get("enabled")),
        "imap_host": imap_host,
        "imap_port": _int("imap_port", 993),
        "smtp_host": smtp_host,
        "smtp_port": _int("smtp_port", 465),
        "user": user,
        "password": str(raw.get("password") or ""),
        "use_ssl": bool(raw.get("use_ssl", True)),
        # ssl (993/465) | starttls (143/587) | plain — mail công ty đủ kiểu.
        "security": (str(raw.get("security") or "").lower()
                     if str(raw.get("security") or "").lower() in ("ssl", "starttls", "plain")
                     else ("ssl" if raw.get("use_ssl", True) else "plain")),
        # Server nội bộ hay dùng chứng chỉ tự ký → cho phép tắt verify.
        "verify_ssl": bool(raw.get("verify_ssl", True)),
        "allowed_senders": [str(s) for s in (senders or []) if str(s).strip()],
        "mark_seen": bool(raw.get("mark_seen", True)),
        "max_body_chars": _int("max_body_chars", 6000, lo=500),
        "poll_seconds": _int("poll_seconds", 60, lo=20),
        "subject_prefix": str(raw.get("subject_prefix") or "[Tiểu Vy]"),
        "reply_enabled": bool(raw.get("reply_enabled", False)),
        "summarize_files": bool(raw.get("summarize_files", True)),
        "notify_on_new": bool(raw.get("notify_on_new", True)),
        "notify_times": [str(t) for t in (times or []) if str(t).strip()],
        "notify_targets": [str(t) for t in (targets or []) if str(t).strip()],
    }


def accounts() -> list[dict[str, Any]]:
    """Mọi hộp mail đã cấu hình (đã chuẩn hóa). ``email_accounts`` rỗng thì lấy
    ``email_channel`` cũ làm hộp #1 để cấu hình đang chạy không mất."""
    raw = config.get().get("email_accounts")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list) and raw:
        for i, item in enumerate(raw):
            acc = _norm_account(item, i)
            if acc and acc.get("user"):
                out.append(acc)
        if out:
            return out
    legacy = _legacy()
    if str(legacy.get("user") or "").strip():
        acc = _norm_account({**legacy,
                             "label": legacy.get("label") or "Hộp mail chính",
                             # hành vi cũ của email_channel là AI trả lời thư
                             "reply_enabled": legacy.get("reply_enabled", True)}, 0)
        if acc:
            out.append(acc)
    return out


def source_key(acc: dict[str, Any]) -> str:
    """Khóa nguồn dùng cho digest state."""
    return f"email:{str(acc.get('id') or '').strip() or 'a1'}"


def account_by_id(account_id: str) -> dict[str, Any] | None:
    aid = str(account_id or "").strip()
    accs = accounts()
    if not aid:
        return accs[0] if accs else None
    for a in accs:
        if a.get("id") == aid or a.get("user") == aid:
            return a
    return None


def is_enabled() -> bool:
    """Có ít nhất một hộp mail đang bật."""
    return any(a.get("enabled") for a in accounts())


def status() -> dict[str, Any]:
    """Trạng thái tổng + theo từng hộp (UI hiện từng dòng)."""
    accs = accounts()
    rows: list[dict[str, Any]] = []
    total_processed = 0
    first_error = ""
    with _lock:
        for a in accs:
            st = dict(_status_by_acc.get(source_key(a)) or {})
            processed = int(st.get("processed") or 0)
            total_processed += processed
            err = str(st.get("last_error") or "")
            if err and not first_error:
                first_error = err
            rows.append({
                "id": a.get("id"),
                "label": a.get("label"),
                "user": a.get("user"),
                "enabled": bool(a.get("enabled")),
                "imap_host": a.get("imap_host"),
                "processed": processed,
                "skipped": int(st.get("skipped") or 0),
                "last_poll_at": float(st.get("last_poll_at") or 0),
                "last_error": err,
                "notify_targets": a.get("notify_targets") or [],
                "notify_times": a.get("notify_times") or [],
                "notify_on_new": bool(a.get("notify_on_new")),
            })
    return {
        "running": _started,
        "enabled": is_enabled(),
        "accounts": rows,
        "count": len(rows),
        "processed": total_processed,
        "last_error": first_error,
        # giữ 2 khóa cũ để UI/log cũ không vỡ
        "user": rows[0]["user"] if rows else "",
        "imap_host": rows[0]["imap_host"] if rows else "",
    }


def _mark_status(acc: dict[str, Any], **patch: Any) -> None:
    key = source_key(acc)
    with _lock:
        st = _status_by_acc.setdefault(key, {})
        for k, v in patch.items():
            if k in {"processed", "skipped"}:
                st[k] = int(st.get(k) or 0) + int(v)
            else:
                st[k] = v


# ── Lọc người gửi ────────────────────────────────────────────────────────────
def _allowed(acc: dict[str, Any], sender: str) -> bool:
    raw = acc.get("allowed_senders")
    if not isinstance(raw, list) or not raw:
        return False  # fail-closed: trống = chặn hết
    sender_l = (sender or "").strip().lower()
    for item in raw:
        a = str(item or "").strip().lower()
        if not a:
            continue
        # `*` = admin CỐ Ý cho tất cả (email agent nay chạy tool read-only +
        # tắt HA fastpath nên rủi ro giới hạn). Khớp CHÍNH XÁC hoặc theo @domain.
        if a == "*" or a == sender_l:
            return True
        if a.startswith("@") and (sender_l.endswith(a) or sender_l == a[1:]):
            return True
        # BỎ khớp chuỗi con `a in sender_l`: nó cho "admin" khớp
        # "admin@evil.com" → giả mạo người gửi lọt allowlist (báo cáo 07/08).
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


def _extract_body(msg: email.message.Message, max_c: int = 6000) -> str:
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


# ── Tệp đính kèm ─────────────────────────────────────────────────────────────
_PLAIN_EXT = {".txt", ".md", ".csv", ".log", ".json", ".yml", ".yaml", ".ini"}
_DOC_EXT = {".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".html", ".htm", ".epub"}
_ATTACH_MAX = 8 * 1024 * 1024   # bỏ qua tệp > 8MB (tránh treo vòng poll)
_ATTACH_CHARS = 4000            # text lấy ra mỗi tệp


def _attachment_text(filename: str, payload: bytes) -> str:
    """Nội dung CHỮ của một tệp đính kèm ('' nếu không đọc được).

    PDF dùng chung đường trích của luồng PDF (OCR nếu là bản scan); tệp Office /
    EPUB qua anydoc rồi markitdown — dùng chung `pdf_intent.markdown_office_so`
    với luồng PDF để chỉ có MỘT đường đọc tài liệu trong dự án; .html/.htm và
    .xls nhị phân cũ anydoc không nhận nên rơi hẳn về markitdown. Tệp text đọc
    trực tiếp. Không raise."""
    name = str(filename or "file")
    ext = os.path.splitext(name)[1].lower()
    if not payload or len(payload) > _ATTACH_MAX:
        return ""
    try:
        if ext in _PLAIN_EXT:
            return payload.decode("utf-8", errors="replace")[:_ATTACH_CHARS]
        if ext == ".pdf":
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(payload)
                path = f.name
            try:
                from services.pdf_intent import extract_markdown
                return (extract_markdown(path, max_pages=10) or "")[:_ATTACH_CHARS]
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if ext in _DOC_EXT:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(payload)
                path = f.name
            try:
                from services.pdf_intent import markdown_office_so
                t = markdown_office_so(path)
                if not t:
                    from markitdown import MarkItDown
                    t = MarkItDown().convert(path).text_content or ""
                return t[:_ATTACH_CHARS]
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except Exception as exc:
        logger.warning("email: đọc tệp %s lỗi: %s", name, str(exc)[:140])
    return ""


def _attachments(msg: email.message.Message, *, read_text: bool) -> list[dict[str, Any]]:
    """[{name, size, text}] — text rỗng nếu không đọc được / tắt tóm tắt tệp."""
    out: list[dict[str, Any]] = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        disp = str(part.get("Content-Disposition") or "").lower()
        fname = _decode_hdr(part.get_filename() or "")
        if "attachment" not in disp and not fname:
            continue
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            payload = b""
        item: dict[str, Any] = {"name": fname or "(không tên)",
                                "size": len(payload), "text": ""}
        if read_text and payload:
            item["text"] = _attachment_text(fname, payload)
        out.append(item)
        if len(out) >= 5:      # 5 tệp/mail là đủ cho bản tóm tắt
            break
    return out


# ── SMTP ─────────────────────────────────────────────────────────────────────
def send_email(
    to_addr: str,
    subject: str,
    body: str,
    *,
    in_reply_to: str = "",
    references: str = "",
    account_id: str = "",
) -> dict[str, Any]:
    """Gửi mail bằng hộp `account_id` (trống = hộp đầu tiên)."""
    acc = account_by_id(account_id)
    if not acc:
        return {"ok": False, "error": "Chưa cấu hình hộp mail nào"}
    user = acc["user"]
    host = acc["smtp_host"]
    port = int(acc["smtp_port"])
    if not user or not host or not to_addr:
        return {"ok": False, "error": "Thiếu smtp_host/user/to"}
    prefix = str(acc.get("subject_prefix") or "").strip()
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

    sec = _sec_mode(acc)
    try:
        if sec == "ssl" and port != 587:
            with smtplib.SMTP_SSL(host, port, context=_ssl_ctx(acc),
                                  timeout=30) as smtp:
                smtp.login(user, acc["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if sec != "plain" or port == 587:
                    smtp.starttls(context=_ssl_ctx(acc))
                    smtp.ehlo()
                smtp.login(user, acc["password"])
                smtp.send_message(msg)
        return {"ok": True}
    except Exception as exc:
        logger.warning("email_channel: smtp %s lỗi: %s", user, exc)
        return {"ok": False, "error": _friendly_error(exc, host)}


# ── Xử lý 1 mail ─────────────────────────────────────────────────────────────
def _summary_text(acc: dict[str, Any], sender: str, subject: str,
                  body: str, atts: list[dict[str, Any]]) -> str:
    """Bản tóm tắt gửi vào kênh chat — gộp CẢ nội dung thư và nội dung tệp."""
    from services import digest
    parts = [f"Người gửi: {sender}",
             f"Tiêu đề: {subject or '(không tiêu đề)'}", "",
             body or "(thư không có nội dung chữ)"]
    for a in atts:
        if a.get("text"):
            parts.append(f"\n--- Tệp: {a['name']} ---\n{a['text']}")
    summary = digest.summarize("\n".join(parts), what="email")
    head = f"📬 {acc.get('label') or acc.get('user')}"
    lines = [f"{head}\n👤 {sender}\n✉️ {subject or '(không tiêu đề)'}", "", summary]
    files = [a for a in atts if a.get("name")]
    if files:
        names = ", ".join(
            f"{a['name']}{'' if a.get('text') else ' (không đọc được)'}" for a in files)
        lines.append(f"\n📎 Tệp: {names}")
    return "\n".join(lines).strip()


def _process_message(acc: dict[str, Any], raw: bytes) -> str:
    """Trả 'processed' | 'skipped' | 'error'."""
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception as exc:
        logger.warning("email_channel: parse lỗi: %s", exc)
        return "error"

    from_hdr = _decode_hdr(msg.get("From"))
    _, from_addr = parseaddr(from_hdr)
    from_addr = (from_addr or "").strip().lower()
    if not from_addr:
        return "skipped"
    if not _allowed(acc, from_addr):
        logger.info("email_channel: chặn người gửi %s", from_addr)
        return "skipped"

    subject = _decode_hdr(msg.get("Subject"))
    body = _extract_body(msg, int(acc.get("max_body_chars") or 6000))
    atts = _attachments(msg, read_text=bool(acc.get("summarize_files", True)))
    if not body and not subject and not atts:
        return "skipped"

    msg_id = str(msg.get("Message-ID") or "").strip()
    src = source_key(acc)
    uid = msg_id or hashlib.sha256(raw[:4096]).hexdigest()[:24]

    # Chống gửi trùng: một mail không bao giờ thông báo 2 lần, kể cả khi
    # mark_seen tắt hoặc IMAP trả lại mail cũ. Chỉ GHI mốc sau khi tác vụ
    # ngoài (thông báo/SMTP) đã xong: ghi ngay tại đây làm một lỗi tạm thời
    # khiến poll sau bỏ thư đó vĩnh viễn dù IMAP vẫn còn UNSEEN.
    from services import digest
    if digest.seen(src, uid):
        return "skipped"

    sent_any = False
    if acc.get("notify_targets"):
        # Mốc RIÊNG cho bước thông báo. Mail giữ trạng thái chưa xử lý khi bước
        # TRẢ LỜI bên dưới hỏng, nên nếu chỉ có một mốc chung thì mỗi lượt poll
        # lại bắn thêm một thông báo trùng cho cùng lá thư — hỏng theo kiểu
        # ngược lại với chuyện mất thư mà bản vá này muốn tránh.
        moc_bao = f"{uid}:notify"
        if digest.seen(src, moc_bao):
            sent_any = True
        else:
            try:
                text = _summary_text(acc, from_hdr or from_addr, subject, body, atts)
                res = digest.notify(src, acc, text)
                sent_any = bool(res.get("sent_now") or res.get("queued"))
            except Exception as exc:
                logger.warning("email_channel: thông báo lỗi: %s", str(exc)[:160])
                return "error"
            if not sent_any:
                # Không gửi ngay và cũng không xếp được lịch — giữ mail chưa xử lý
                # để lần sau thử lại khi kênh nhận/đường mạng hồi phục.
                logger.warning("email_channel: chưa chuyển được thông báo cho %s", from_addr)
                return "error"
            digest.mark_seen(src, moc_bao)

    # Trả lời thẳng vào email bằng AI — CHỈ khi hộp này bật (mặc định TẮT để hộp
    # chỉ-tóm-tắt không tự đi trả lời người ta).
    if acc.get("reply_enabled"):
        att_note = ""
        for a in atts:
            if a.get("text"):
                att_note += f"\n\n--- Tệp {a['name']} ---\n{a['text'][:2000]}"
        user_text = f"Tiêu đề: {subject}\n\n{body}{att_note}".strip()
        try:
            from services.agent.orchestrator import orchestrate
            from services.agent import capabilities as _caps
            # Email đến từ người gửi KHÔNG xác thực được (header From giả được),
            # nên email agent KHÔNG được chạm nhóm hành động vật lý/máy chủ:
            # homeassistant/device/server/code. Tắt luôn HA fast-path. Giữ các
            # nhóm đọc/tra cứu (web, wiki, office, tóm tắt…) để vẫn hữu ích.
            _email_deny = {"homeassistant", "device", "server", "code"}
            _email_allow = {g for g in _caps.all_groups() if g not in _email_deny}
            out = orchestrate(user_text, _user_id_for(from_addr),
                              allow=_email_allow, ha_fastpath=False)
            reply = str(out.get("text") or "").strip()
            if out.get("silent") or not reply:
                reply = "Dạ em đã nhận email nhưng không có nội dung trả lời ạ."
        except Exception as exc:
            logger.warning("email_channel: orchestrate lỗi: %s", exc)
            reply = f"Xin lỗi, hệ thống tạm lỗi: {str(exc)[:100]}"
        re_subj = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        sent = send_email(from_addr, re_subj, reply, in_reply_to=msg_id,
                          references=msg_id, account_id=str(acc.get("id") or ""))
        if not sent.get("ok"):
            logger.warning("email_channel: trả lời lỗi: %s", sent.get("error"))
            return "error"
        digest.mark_seen(src, uid)
        return "processed"
    digest.mark_seen(src, uid)
    return "processed" if sent_any else "skipped"


# ── IMAP ─────────────────────────────────────────────────────────────────────
def _sec_mode(acc: dict[str, Any]) -> str:
    sec = str(acc.get("security") or "").lower()
    if sec in ("ssl", "starttls", "plain"):
        return sec
    return "ssl" if acc.get("use_ssl", True) else "plain"


def _ssl_ctx(acc: dict[str, Any]) -> ssl.SSLContext:
    if bool(acc.get("verify_ssl", True)):
        return ssl.create_default_context()
    # User chủ động chọn «Chấp nhận mọi chứng chỉ» cho server nội bộ tự ký
    # (giống tùy chọn cùng tên trên app mail điện thoại).
    return ssl._create_unverified_context()  # nosec B323


def _imap_connect(acc: dict[str, Any], timeout: int) -> imaplib.IMAP4:
    host, port = acc["imap_host"], int(acc["imap_port"])
    sec = _sec_mode(acc)
    if sec == "ssl":
        return imaplib.IMAP4_SSL(host, port, timeout=timeout, ssl_context=_ssl_ctx(acc))
    M = imaplib.IMAP4(host, port, timeout=timeout)
    if sec == "starttls":
        M.starttls(_ssl_ctx(acc))
    return M


def poll_account(acc: dict[str, Any]) -> dict[str, Any]:
    """Đọc mail CHƯA ĐỌC của một hộp rồi xử lý."""
    if not acc.get("imap_host") or not acc.get("user"):
        return {"ok": False, "error": "Thiếu imap_host/user", "id": acc.get("id")}
    mark_seen = bool(acc.get("mark_seen", True))
    processed = skipped = errors = 0
    try:
        M = _imap_connect(acc, 40)
        try:
            M.login(acc["user"], acc["password"])
            M.select("INBOX")
            typ, data = M.search(None, "UNSEEN")
            ids = data[0].split() if (typ == "OK" and data and data[0]) else []
            for num in ids[:10]:      # giới hạn burst mỗi vòng poll
                typ, msg_data = M.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    errors += 1
                    continue
                raw = msg_data[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    errors += 1
                    continue
                result = _process_message(acc, bytes(raw))
                if result == "processed":
                    processed += 1
                elif result == "skipped":
                    skipped += 1
                else:
                    errors += 1
                if result in {"processed", "skipped"} and mark_seen:
                    M.store(num, "+FLAGS", "\\Seen")
        finally:
            try:
                M.logout()
            except Exception:
                pass
    except Exception as exc:
        msg_err = _friendly_error(exc, str(acc.get("imap_host") or ""))
        _mark_status(acc, last_error=msg_err, last_poll_at=time.time())
        logger.warning("email_channel: poll %s lỗi: %s", acc.get("user"), exc)
        return {"ok": False, "error": msg_err, "id": acc.get("id"),
                "processed": processed}

    _mark_status(acc, last_error="", last_poll_at=time.time(),
                 processed=processed, skipped=skipped)
    return {"ok": True, "id": acc.get("id"), "label": acc.get("label"),
            "processed": processed, "skipped": skipped, "errors": errors}


def poll_once(account_id: str = "") -> dict[str, Any]:
    """Poll một hộp (account_id) hoặc MỌI hộp đang bật. An toàn để gọi tay/test."""
    if account_id:
        acc = account_by_id(account_id)
        if not acc:
            return {"ok": False, "error": f"Không thấy hộp mail {account_id}"}
        accs = [acc]
    else:
        accs = [a for a in accounts() if a.get("enabled")]
    if not accs:
        return {"ok": False, "error": "Chưa bật hộp mail nào"}
    results = [poll_account(a) for a in accs]
    return {
        "ok": any(r.get("ok") for r in results),
        "processed": sum(int(r.get("processed") or 0) for r in results),
        "skipped": sum(int(r.get("skipped") or 0) for r in results),
        "results": results,
    }


def test_connection(account_id: str = "") -> dict[str, Any]:
    """Đăng nhập IMAP (không gửi mail) — báo lỗi bằng câu hành động được."""
    acc = account_by_id(account_id)
    if not acc:
        return {"ok": False, "error": "Chưa cấu hình hộp mail nào"}
    if not acc.get("imap_host") or not acc.get("user"):
        return {"ok": False, "error": "❌ Thiếu IMAP host hoặc địa chỉ email"}
    if not acc.get("password"):
        if _needs_app_pw(str(acc.get("imap_host") or "")):
            return {"ok": False, "error": f"❌ Chưa nhập App Password. {_APP_PW_HINT}"}
        return {"ok": False, "error": "❌ Chưa nhập mật khẩu — mail công ty/nội bộ "
                                      "dùng mật khẩu đăng nhập thường."}
    try:
        M = _imap_connect(acc, 20)
        try:
            M.login(acc["user"], acc["password"])
            typ, _ = M.select("INBOX")
            ok = typ == "OK"
            return {"ok": ok, "inbox": ok, "id": acc.get("id"),
                    "label": acc.get("label"),
                    "message": "✅ IMAP OK — đăng nhập và mở INBOX được"
                    if ok else "❌ Đăng nhập được nhưng không mở được INBOX"}
        finally:
            try:
                M.logout()
            except Exception:
                pass
    except Exception as exc:
        return {"ok": False, "error": _friendly_error(exc, str(acc.get("imap_host") or "")),
                "id": acc.get("id")}


def send_digest_now(account_id: str = "") -> dict[str, Any]:
    """Gửi NGAY bản tổng hợp đang chờ của hộp mail (nút «Gửi thử» trong UI)."""
    acc = account_by_id(account_id)
    if not acc:
        return {"ok": False, "error": "Chưa cấu hình hộp mail nào"}
    from services import digest
    src = source_key(acc)
    if not acc.get("notify_targets"):
        return {"ok": False, "error": "Hộp này chưa chọn kênh nhận"}
    waiting = digest.pending_count(src)
    if not waiting:
        # Không có gì chờ → gửi 1 dòng kiểm tra để user biết kênh nhận đã đúng.
        n = digest.send_targets(
            acc["notify_targets"],
            f"📬 {acc.get('label') or acc.get('user')} — kiểm tra kênh nhận: OK "
            f"(chưa có mail mới nào đang chờ tổng hợp).")
        return {"ok": n > 0, "sent": n, "pending": 0,
                "message": f"Đã gửi tin kiểm tra tới {n} kênh"}
    n = digest.flush(src, acc, title=f"📬 Tổng hợp email · {acc.get('label')}")
    return {"ok": n > 0, "sent": n, "pending": waiting,
            "message": f"Đã gửi tổng hợp {waiting} mục tới {n} kênh"}


# ── Vòng lặp ─────────────────────────────────────────────────────────────────
def _poll_worker(acc: dict[str, Any], key: str) -> None:
    """Poll MỘT hộp trên luồng riêng; luôn nhả chốt inflight khi xong."""
    try:
        poll_account(acc)
    except Exception as exc:
        logger.warning("email_channel: poll %s lỗi: %s", acc.get("user"), exc)
    finally:
        with _inflight_lock:
            _inflight.discard(key)


def _loop() -> None:
    """Supervisor: mỗi 15s xét hộp nào tới hạn rồi GIAO cho luồng riêng.

    Đọc cấu hình mỗi vòng nên thêm/bật hộp trong Settings là chạy ngay ở tick
    kế tiếp, không cần restart. Bản thân supervisor KHÔNG bao giờ tự đi poll —
    trước đây nó poll trực tiếp nên một hộp chậm là treo cả kênh mail.
    """
    from concurrent.futures import ThreadPoolExecutor

    _stop.wait(8)
    pool = ThreadPoolExecutor(max_workers=_POLL_WORKERS,
                              thread_name_prefix="email-poll")
    try:
        while not _stop.is_set():
            try:
                for acc in accounts():
                    if not acc.get("enabled"):
                        continue
                    key = source_key(acc)
                    every = float(acc.get("poll_seconds") or 60)
                    if time.time() - _last_poll_at.get(key, 0.0) < every:
                        continue
                    with _inflight_lock:
                        if key in _inflight:
                            # Lượt trước của CHÍNH hộp này còn chạy (nhiều thư
                            # + AI) → bỏ nhịp, đừng xếp thêm.
                            continue
                        _inflight.add(key)
                    _last_poll_at[key] = time.time()
                    pool.submit(_poll_worker, acc, key)
            except Exception as exc:
                logger.warning("email_channel: loop lỗi: %s", exc)
            # Nhịp chung 15s; mỗi hộp tự tôn trọng poll_seconds riêng ở trên.
            _stop.wait(15)
    finally:
        # wait=False: hộp đang xử lý dở không được giữ luôn tiến trình lúc tắt.
        pool.shutdown(wait=False, cancel_futures=True)


def start() -> None:
    global _started
    if _started:
        return
    # LUÔN chạy supervisor kể cả khi chưa bật hộp nào: _loop tự đọc cấu hình mỗi
    # vòng nên thêm/bật hộp mail trong Settings là chạy ngay ở tick kế tiếp —
    # KHÔNG cần restart container.
    if not is_enabled():
        logger.info("email_channel: chưa bật hộp nào (supervisor chờ)")
    _started = True
    _stop.clear()
    threading.Thread(target=_loop, name="email-channel", daemon=True).start()
    logger.info("email_channel: started (%d hộp)", len(accounts()))


def stop() -> None:
    global _started
    _stop.set()
    _started = False


def _reset_for_tests() -> None:
    stop()
    with _lock:
        _status_by_acc.clear()
        _last_poll_at.clear()
