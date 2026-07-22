"""Low-level Telegram Bot API client.

Covers the methods we need for an AI multi-channel gateway, plus a generic
``call()`` so any future method is one line away without editing this file.

Refs: https://core.telegram.org/bots/api
"""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from services.telegram.constants import (
    DEFAULT_API_BASE,
    DEFAULT_ALLOWED_UPDATES,
    MAX_CAPTION_LENGTH,
    MAX_DOWNLOAD_BYTES,
    MAX_MESSAGE_LENGTH,
    MIME_BY_EXT,
    SAFE_CAPTION_LENGTH,
)
from services.telegram import format as tg_fmt

logger = logging.getLogger(__name__)


def _retry_after_seconds(payload: dict | None, default: float = 1.0) -> float:
    if not isinstance(payload, dict):
        return default
    params = payload.get("parameters") or {}
    try:
        ra = float(params.get("retry_after") or 0)
        if ra > 0:
            return min(ra, 60.0)
    except (TypeError, ValueError):
        pass
    return default


class TelegramClient:
    """Token-scoped Bot API client (one instance per bot token)."""

    def __init__(
        self,
        token: str,
        *,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.token = (token or "").strip()
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))

    # ── Core transport ────────────────────────────────────────────────────────

    @property
    def bot_id(self) -> str:
        return self.token.split(":", 1)[0] if self.token else ""

    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    def _file_url(self, file_path: str) -> str:
        return f"{self.api_base}/file/bot{self.token}/{file_path.lstrip('/')}"

    def call(
        self,
        method: str,
        data: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        """JSON POST/GET to Bot API. Retries on 429 using retry_after."""
        if not self.token:
            return {"ok": False, "description": "empty token"}
        to = self.timeout if timeout is None else float(timeout)
        retries = self.max_retries if max_retries is None else int(max_retries)
        url = self._url(method)
        body = None
        headers = {}
        if data is not None:
            # Drop Nones so optional fields stay optional
            clean = {k: v for k, v in data.items() if v is not None}
            body = json.dumps(clean, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        last: dict[str, Any] = {"ok": False}
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=to) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                last = json.loads(raw) if raw else {"ok": True}
                if last.get("ok"):
                    return last
                # Flood control
                desc = str(last.get("description") or "")
                if attempt < retries and (
                    last.get("error_code") == 429
                    or "retry after" in desc.lower()
                    or "too many requests" in desc.lower()
                ):
                    time.sleep(_retry_after_seconds(last))
                    continue
                return last
            except urllib.error.HTTPError as exc:
                try:
                    raw = exc.read().decode("utf-8", errors="replace")
                    last = json.loads(raw) if raw else {
                        "ok": False, "description": str(exc), "error_code": exc.code,
                    }
                except Exception:
                    last = {"ok": False, "description": str(exc), "error_code": exc.code}
                if attempt < retries and exc.code == 429:
                    time.sleep(_retry_after_seconds(last))
                    continue
                logger.warning("Telegram HTTP %s %s: %s", method, exc.code, last.get("description"))
                return last
            except Exception as exc:
                last = {"ok": False, "description": str(exc)}
                logger.warning("Telegram API %s: %s", method, exc)
                if attempt < retries:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                return last
        return last

    def call_multipart(
        self,
        method: str,
        fields: dict[str, Any],
        files: dict[str, tuple[str, bytes, str]],
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        """multipart/form-data (file uploads).

        ``files``: name → (filename, bytes, content_type)
        """
        if not self.token:
            return {"ok": False, "description": "empty token"}
        to = self.timeout if timeout is None else float(timeout)
        if method in ("sendVideo", "sendDocument", "sendAudio", "sendAnimation"):
            to = max(to, 120.0)
        retries = self.max_retries if max_retries is None else int(max_retries)
        boundary = f"----c2a{uuid.uuid4().hex}"
        buf = io.BytesIO()
        for key, val in fields.items():
            if val is None:
                continue
            if isinstance(val, (dict, list)):
                sval = json.dumps(val, ensure_ascii=False)
            else:
                sval = str(val)
            buf.write(f"--{boundary}\r\n".encode())
            buf.write(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
            )
            buf.write(sval.encode("utf-8"))
            buf.write(b"\r\n")
        for name, (filename, content, ctype) in files.items():
            buf.write(f"--{boundary}\r\n".encode())
            buf.write(
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode()
            )
            buf.write(f"Content-Type: {ctype or 'application/octet-stream'}\r\n\r\n".encode())
            buf.write(content)
            buf.write(b"\r\n")
        buf.write(f"--{boundary}--\r\n".encode())
        payload = buf.getvalue()
        url = self._url(method)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        last: dict[str, Any] = {"ok": False}
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=to) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                last = json.loads(raw) if raw else {"ok": True}
                if last.get("ok"):
                    return last
                if attempt < retries and last.get("error_code") == 429:
                    time.sleep(_retry_after_seconds(last))
                    continue
                return last
            except urllib.error.HTTPError as exc:
                try:
                    raw = exc.read().decode("utf-8", errors="replace")
                    last = json.loads(raw) if raw else {
                        "ok": False, "description": str(exc), "error_code": exc.code,
                    }
                except Exception:
                    last = {"ok": False, "description": str(exc), "error_code": exc.code}
                if attempt < retries and exc.code == 429:
                    time.sleep(_retry_after_seconds(last))
                    continue
                logger.warning("Telegram multipart %s: %s", method, last.get("description"))
                return last
            except Exception as exc:
                last = {"ok": False, "description": str(exc)}
                logger.warning("Telegram multipart %s: %s", method, exc)
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return last
        return last

    # ── Meta ──────────────────────────────────────────────────────────────────

    def get_me(self) -> dict[str, Any]:
        return self.call("getMe", timeout=10)

    def get_webhook_info(self) -> dict[str, Any]:
        return self.call("getWebhookInfo", timeout=10)

    def set_webhook(
        self,
        url: str,
        *,
        secret_token: str | None = None,
        allowed_updates: list[str] | None = None,
        drop_pending_updates: bool | None = None,
        max_connections: int | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        return self.call("setWebhook", {
            "url": url,
            "secret_token": secret_token,
            "allowed_updates": allowed_updates if allowed_updates is not None
            else list(DEFAULT_ALLOWED_UPDATES),
            "drop_pending_updates": drop_pending_updates,
            "max_connections": max_connections,
            "ip_address": ip_address,
        })

    def delete_webhook(self, *, drop_pending_updates: bool | None = None) -> dict[str, Any]:
        return self.call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    def get_updates(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
        timeout: int | None = None,
        allowed_updates: list[str] | None = None,
    ) -> dict[str, Any]:
        # Long poll timeout must exceed HTTP timeout
        http_to = float(timeout or 0) + 10.0 if timeout else self.timeout
        return self.call("getUpdates", {
            "offset": offset,
            "limit": limit,
            "timeout": timeout,
            "allowed_updates": allowed_updates,
        }, timeout=http_to, max_retries=0)

    def log_out(self) -> dict[str, Any]:
        return self.call("logOut")

    def close(self) -> dict[str, Any]:
        return self.call("close")

    # ── Commands / profile ────────────────────────────────────────────────────

    def set_my_commands(
        self,
        commands: list[dict[str, str]],
        *,
        scope: dict | None = None,
        language_code: str | None = None,
    ) -> dict[str, Any]:
        return self.call("setMyCommands", {
            "commands": commands,
            "scope": scope,
            "language_code": language_code,
        })

    def get_my_commands(
        self,
        *,
        scope: dict | None = None,
        language_code: str | None = None,
    ) -> dict[str, Any]:
        return self.call("getMyCommands", {
            "scope": scope, "language_code": language_code,
        })

    def delete_my_commands(
        self,
        *,
        scope: dict | None = None,
        language_code: str | None = None,
    ) -> dict[str, Any]:
        return self.call("deleteMyCommands", {
            "scope": scope, "language_code": language_code,
        })

    def set_my_name(self, name: str, *, language_code: str | None = None) -> dict[str, Any]:
        return self.call("setMyName", {"name": name, "language_code": language_code})

    def get_my_name(self, *, language_code: str | None = None) -> dict[str, Any]:
        return self.call("getMyName", {"language_code": language_code})

    def set_my_description(
        self, description: str, *, language_code: str | None = None
    ) -> dict[str, Any]:
        return self.call("setMyDescription", {
            "description": description, "language_code": language_code,
        })

    def set_my_short_description(
        self, short_description: str, *, language_code: str | None = None
    ) -> dict[str, Any]:
        return self.call("setMyShortDescription", {
            "short_description": short_description, "language_code": language_code,
        })

    # ── Send text ─────────────────────────────────────────────────────────────

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
        reply_parameters: dict | None = None,
        message_thread_id: int | None = None,
        disable_notification: bool | None = None,
        protect_content: bool | None = None,
        link_preview_options: dict | None = None,
        business_connection_id: str | None = None,
        receiver_user_id: int | None = None,
        entities: list | None = None,
        allow_paid_broadcast: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
            "reply_parameters": reply_parameters,
            "message_thread_id": message_thread_id,
            "disable_notification": disable_notification,
            "protect_content": protect_content,
            "link_preview_options": link_preview_options,
            "business_connection_id": business_connection_id,
            "receiver_user_id": receiver_user_id,
            "entities": entities,
            "allow_paid_broadcast": allow_paid_broadcast,
        }
        return self.call("sendMessage", payload)

    def send_message_safe(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = "auto",
        convert_llm_md: bool = True,
        split: bool = True,
        link_preview_disabled: bool = True,
        reply_markup: dict | None = None,
        reply_parameters: dict | None = None,
        message_thread_id: int | None = None,
        plain_fallback: bool = True,
        allow_rich: bool = True,
        bot: dict | None = None,
        **extra: Any,
    ) -> list[dict[str, Any]]:
        """Send with format conversion, length split, and plain fallback.

        ``parse_mode``:
          - ``"auto"`` (default) — pick rich / HTML / plain optimally
          - ``"HTML"`` / ``"Markdown"`` / ``"MarkdownV2"`` — force that mode
          - ``None`` — plain text

        ``bot`` — active bot config (for per-admin emphasis toggles).

        Returns list of API results (one per chunk / attempt).
        """
        if (parse_mode or "").lower() == "auto":
            return self.send_message_auto(
                chat_id, text,
                convert_llm_md=convert_llm_md,
                split=split,
                link_preview_disabled=link_preview_disabled,
                reply_markup=reply_markup,
                reply_parameters=reply_parameters,
                message_thread_id=message_thread_id,
                allow_rich=allow_rich,
                bot=bot,
                **extra,
            )

        raw = text or ""
        if convert_llm_md and parse_mode == "Markdown":
            body = tg_fmt.llm_to_legacy_markdown(raw)
        elif convert_llm_md and parse_mode == "HTML":
            body = tg_fmt.llm_to_html(raw)
        else:
            body = raw

        preview = {"is_disabled": True} if link_preview_disabled else None
        chunks = tg_fmt.split_message(body) if split else [tg_fmt.clip(body)]
        if not chunks:
            chunks = ["…"]

        results: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            markup = reply_markup if i == 0 else None  # keyboard only once
            r = self.send_message(
                chat_id, chunk,
                parse_mode=parse_mode,
                reply_markup=markup,
                reply_parameters=reply_parameters if i == 0 else None,
                message_thread_id=message_thread_id,
                link_preview_options=preview,
                **extra,
            )
            if not r.get("ok") and plain_fallback and parse_mode:
                # Fall back to original raw chunk (no parse)
                plain_chunks = tg_fmt.split_message(raw) if split else [raw]
                plain = plain_chunks[i] if i < len(plain_chunks) else chunk
                r = self.send_message(
                    chat_id, plain,
                    parse_mode=None,
                    reply_markup=markup,
                    reply_parameters=reply_parameters if i == 0 else None,
                    message_thread_id=message_thread_id,
                    link_preview_options=preview,
                    **extra,
                )
            results.append(r)
            if not r.get("ok"):
                break
        return results

    def send_message_auto(
        self,
        chat_id: int | str,
        text: str,
        *,
        convert_llm_md: bool = True,
        split: bool = True,
        link_preview_disabled: bool = True,
        reply_markup: dict | None = None,
        reply_parameters: dict | None = None,
        message_thread_id: int | None = None,
        allow_rich: bool = True,
        bot: dict | None = None,
        **extra: Any,
    ) -> list[dict[str, Any]]:
        """Auto-pick rich → HTML → plain with cascading fallbacks.

        Annotates the last result with ``_c2a_format`` / ``_c2a_format_reason``
        for logs (not sent to Telegram).
        """
        from services.telegram.auto_format import choose_format, strip_for_plain
        from services.telegram.rich import input_rich_message

        raw = text or ""
        # Auto-bold numbers / key info — respect per-admin-thread toggle on bot
        try:
            from services.telegram.emphasis import emphasize_text
            raw = emphasize_text(raw, bot=bot, chat_id=chat_id)
        except Exception:
            pass
        choice = choose_format(raw, allow_rich=allow_rich)
        preview = {"is_disabled": True} if link_preview_disabled else None
        common = {
            "reply_parameters": reply_parameters,
            "message_thread_id": message_thread_id,
            **extra,
        }

        results: list[dict[str, Any]] = []
        used = choice.mode

        # 1) Rich Message (single payload; Telegram handles structure)
        if choice.mode == "rich":
            try:
                rich_msg = input_rich_message(markdown=raw)
                r = self.send_rich_message(
                    chat_id, rich_msg,
                    reply_markup=reply_markup,
                    **{k: v for k, v in common.items() if v is not None},
                )
                results.append(r)
                if r.get("ok"):
                    r["_c2a_format"] = "rich"
                    r["_c2a_format_reason"] = choice.reason
                    return results
                logger.info(
                    "Telegram rich failed → html: %s",
                    str(r.get("description") or "")[:120],
                )
            except Exception as exc:
                logger.info("Telegram rich error → html: %s", exc)
            used = "html"

        # 2) HTML (or forced after rich fail)
        if used in ("html", "rich") or choice.mode == "html":
            body = tg_fmt.llm_to_html(raw) if convert_llm_md else raw
            chunks = tg_fmt.split_message(body) if split else [tg_fmt.clip(body)]
            if not chunks:
                chunks = ["…"]
            html_ok = True
            html_results: list[dict[str, Any]] = []
            for i, chunk in enumerate(chunks):
                markup = reply_markup if i == 0 else None
                r = self.send_message(
                    chat_id, chunk,
                    parse_mode="HTML",
                    reply_markup=markup,
                    link_preview_options=preview,
                    reply_parameters=reply_parameters if i == 0 else None,
                    message_thread_id=message_thread_id,
                    **extra,
                )
                html_results.append(r)
                if not r.get("ok"):
                    html_ok = False
                    logger.info(
                        "Telegram HTML failed → plain: %s",
                        str(r.get("description") or "")[:120],
                    )
                    break
            if html_ok and html_results:
                for r in html_results:
                    r["_c2a_format"] = "html"
                    r["_c2a_format_reason"] = choice.reason
                return html_results
            results.extend(html_results)
            used = "plain"

        # 3) Plain (always last resort)
        plain = strip_for_plain(raw) if convert_llm_md else raw
        chunks = tg_fmt.split_message(plain) if split else [tg_fmt.clip(plain)]
        if not chunks:
            chunks = ["…"]
        plain_results: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            markup = reply_markup if i == 0 else None
            r = self.send_message(
                chat_id, chunk,
                parse_mode=None,
                reply_markup=markup,
                link_preview_options=preview,
                reply_parameters=reply_parameters if i == 0 else None,
                message_thread_id=message_thread_id,
                **extra,
            )
            r["_c2a_format"] = "plain"
            r["_c2a_format_reason"] = choice.reason
            plain_results.append(r)
            if not r.get("ok"):
                break
        return plain_results or results

    def send_message_draft(
        self,
        chat_id: int | str,
        draft_id: int,
        text: str,
        *,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        """Stream partial text (Bot API draft). ``draft_id`` unique per draft stream."""
        return self.call("sendMessageDraft", {
            "chat_id": str(chat_id),
            "draft_id": int(draft_id),
            "text": text or "",
            "message_thread_id": message_thread_id,
        })

    def forward_message(
        self,
        chat_id: int | str,
        from_chat_id: int | str,
        message_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("forwardMessage", {
            "chat_id": str(chat_id),
            "from_chat_id": str(from_chat_id),
            "message_id": message_id,
            **kwargs,
        })

    def copy_message(
        self,
        chat_id: int | str,
        from_chat_id: int | str,
        message_id: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("copyMessage", {
            "chat_id": str(chat_id),
            "from_chat_id": str(from_chat_id),
            "message_id": message_id,
            **kwargs,
        })

    def send_chat_action(
        self,
        chat_id: int | str,
        action: str = "typing",
        *,
        message_thread_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> dict[str, Any]:
        return self.call("sendChatAction", {
            "chat_id": str(chat_id),
            "action": action,
            "message_thread_id": message_thread_id,
            "business_connection_id": business_connection_id,
        }, timeout=10)

    # ── Media send ────────────────────────────────────────────────────────────

    def _cap(self, caption: str | None) -> str | None:
        if not caption:
            return None
        return tg_fmt.clip_caption(caption, SAFE_CAPTION_LENGTH)

    def send_photo(
        self,
        chat_id: int | str,
        photo: bytes | str,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        filename: str = "image.png",
        content_type: str = "image/png",
        reply_markup: dict | None = None,
        reply_parameters: dict | None = None,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        fields = {
            "chat_id": str(chat_id),
            "caption": self._cap(caption),
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
            "reply_parameters": reply_parameters,
            "message_thread_id": message_thread_id,
            **kwargs,
        }
        if isinstance(photo, (bytes, bytearray)):
            return self.call_multipart(
                "sendPhoto", fields,
                {"photo": (filename, bytes(photo), content_type)},
            )
        fields["photo"] = str(photo)  # file_id or URL
        return self.call("sendPhoto", fields)

    def send_document(
        self,
        chat_id: int | str,
        document: bytes | str,
        *,
        filename: str = "file.bin",
        caption: str | None = None,
        parse_mode: str | None = None,
        content_type: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        fields = {
            "chat_id": str(chat_id),
            "caption": self._cap(caption),
            "parse_mode": parse_mode,
            **kwargs,
        }
        if isinstance(document, (bytes, bytearray)):
            ctype = content_type or _guess_mime(filename)
            return self.call_multipart(
                "sendDocument", fields,
                {"document": (filename, bytes(document), ctype)},
                timeout=60,
            )
        fields["document"] = str(document)
        return self.call("sendDocument", fields)

    def send_video(
        self,
        chat_id: int | str,
        video: bytes | str,
        *,
        filename: str = "video.mp4",
        caption: str | None = None,
        content_type: str = "video/mp4",
        **kwargs: Any,
    ) -> dict[str, Any]:
        fields = {
            "chat_id": str(chat_id),
            "caption": self._cap(caption),
            **kwargs,
        }
        if isinstance(video, (bytes, bytearray)):
            return self.call_multipart(
                "sendVideo", fields,
                {"video": (filename, bytes(video), content_type)},
                timeout=120,
            )
        fields["video"] = str(video)
        return self.call("sendVideo", fields, timeout=120)

    def send_audio(
        self,
        chat_id: int | str,
        audio: bytes | str,
        *,
        filename: str = "audio.mp3",
        caption: str | None = None,
        content_type: str = "audio/mpeg",
        **kwargs: Any,
    ) -> dict[str, Any]:
        fields = {
            "chat_id": str(chat_id),
            "caption": self._cap(caption),
            **kwargs,
        }
        if isinstance(audio, (bytes, bytearray)):
            return self.call_multipart(
                "sendAudio", fields,
                {"audio": (filename, bytes(audio), content_type)},
                timeout=120,
            )
        fields["audio"] = str(audio)
        return self.call("sendAudio", fields)

    def send_voice(
        self,
        chat_id: int | str,
        voice: bytes | str,
        *,
        filename: str = "voice.ogg",
        caption: str | None = None,
        content_type: str = "audio/ogg",
        **kwargs: Any,
    ) -> dict[str, Any]:
        fields = {
            "chat_id": str(chat_id),
            "caption": self._cap(caption),
            **kwargs,
        }
        if isinstance(voice, (bytes, bytearray)):
            return self.call_multipart(
                "sendVoice", fields,
                {"voice": (filename, bytes(voice), content_type)},
            )
        fields["voice"] = str(voice)
        return self.call("sendVoice", fields)

    def send_animation(
        self,
        chat_id: int | str,
        animation: bytes | str,
        *,
        filename: str = "anim.mp4",
        caption: str | None = None,
        content_type: str = "video/mp4",
        **kwargs: Any,
    ) -> dict[str, Any]:
        fields = {
            "chat_id": str(chat_id),
            "caption": self._cap(caption),
            **kwargs,
        }
        if isinstance(animation, (bytes, bytearray)):
            return self.call_multipart(
                "sendAnimation", fields,
                {"animation": (filename, bytes(animation), content_type)},
            )
        fields["animation"] = str(animation)
        return self.call("sendAnimation", fields)

    def send_sticker(
        self, chat_id: int | str, sticker: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("sendSticker", {
            "chat_id": str(chat_id), "sticker": sticker, **kwargs,
        })

    def send_location(
        self,
        chat_id: int | str,
        latitude: float,
        longitude: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("sendLocation", {
            "chat_id": str(chat_id),
            "latitude": latitude,
            "longitude": longitude,
            **kwargs,
        })

    def send_venue(
        self,
        chat_id: int | str,
        latitude: float,
        longitude: float,
        title: str,
        address: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("sendVenue", {
            "chat_id": str(chat_id),
            "latitude": latitude,
            "longitude": longitude,
            "title": title,
            "address": address,
            **kwargs,
        })

    def send_contact(
        self,
        chat_id: int | str,
        phone_number: str,
        first_name: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("sendContact", {
            "chat_id": str(chat_id),
            "phone_number": phone_number,
            "first_name": first_name,
            **kwargs,
        })

    def send_poll(
        self,
        chat_id: int | str,
        question: str,
        options: list[str] | list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        # API accepts InputPollOption objects; plain strings still work on older
        opts: list[Any] = []
        for o in options:
            if isinstance(o, str):
                opts.append({"text": o})
            else:
                opts.append(o)
        return self.call("sendPoll", {
            "chat_id": str(chat_id),
            "question": question,
            "options": opts,
            **kwargs,
        })

    def send_dice(self, chat_id: int | str, emoji: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.call("sendDice", {
            "chat_id": str(chat_id), "emoji": emoji, **kwargs,
        })

    def send_media_group(
        self,
        chat_id: int | str,
        media: list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send album. ``media`` items use file_id/URL only (no multipart mix)."""
        return self.call("sendMediaGroup", {
            "chat_id": str(chat_id), "media": media, **kwargs,
        }, timeout=120)

    # ── Rich messages (Bot API 10.1+) ─────────────────────────────────────────

    def send_rich_message(
        self,
        chat_id: int | str,
        rich_message: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("sendRichMessage", {
            "chat_id": str(chat_id),
            "rich_message": rich_message,
            **kwargs,
        })

    def send_rich_message_draft(
        self,
        chat_id: int | str,
        draft_id: int,
        rich_message: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("sendRichMessageDraft", {
            "chat_id": str(chat_id),
            "draft_id": int(draft_id),
            "rich_message": rich_message,
            **kwargs,
        })

    # ── Edit / delete ─────────────────────────────────────────────────────────

    def edit_message_text(
        self,
        text: str,
        *,
        chat_id: int | str | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
        rich_message: dict | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("editMessageText", {
            "text": text,
            "chat_id": str(chat_id) if chat_id is not None else None,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
            "rich_message": rich_message,
            **kwargs,
        })

    def edit_message_caption(
        self,
        *,
        chat_id: int | str | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("editMessageCaption", {
            "chat_id": str(chat_id) if chat_id is not None else None,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
            "caption": self._cap(caption) if caption else caption,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
            **kwargs,
        })

    def edit_message_media(
        self,
        media: dict,
        *,
        chat_id: int | str | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        reply_markup: dict | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("editMessageMedia", {
            "media": media,
            "chat_id": str(chat_id) if chat_id is not None else None,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
            "reply_markup": reply_markup,
            **kwargs,
        })

    def edit_message_reply_markup(
        self,
        *,
        chat_id: int | str | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        reply_markup: dict | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("editMessageReplyMarkup", {
            "chat_id": str(chat_id) if chat_id is not None else None,
            "message_id": message_id,
            "inline_message_id": inline_message_id,
            "reply_markup": reply_markup,
            **kwargs,
        })

    def delete_message(
        self, chat_id: int | str, message_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("deleteMessage", {
            "chat_id": str(chat_id), "message_id": message_id, **kwargs,
        })

    def delete_messages(
        self, chat_id: int | str, message_ids: list[int], **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("deleteMessages", {
            "chat_id": str(chat_id), "message_ids": message_ids, **kwargs,
        })

    def set_message_reaction(
        self,
        chat_id: int | str,
        message_id: int,
        reaction: list[dict] | None = None,
        *,
        is_big: bool | None = None,
    ) -> dict[str, Any]:
        return self.call("setMessageReaction", {
            "chat_id": str(chat_id),
            "message_id": message_id,
            "reaction": reaction,
            "is_big": is_big,
        })

    # ── Callbacks / inline ────────────────────────────────────────────────────

    def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool | None = None,
        url: str | None = None,
        cache_time: int | None = None,
    ) -> dict[str, Any]:
        return self.call("answerCallbackQuery", {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
            "url": url,
            "cache_time": cache_time,
        }, timeout=10)

    def answer_inline_query(
        self,
        inline_query_id: str,
        results: list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.call("answerInlineQuery", {
            "inline_query_id": inline_query_id,
            "results": results,
            **kwargs,
        })

    def answer_guest_query(
        self,
        guest_query_id: str,
        *,
        text: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Bot API 10 guest mode reply."""
        return self.call("answerGuestQuery", {
            "guest_query_id": guest_query_id,
            "text": text,
            **kwargs,
        })

    # ── Files ─────────────────────────────────────────────────────────────────

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self.call("getFile", {"file_id": file_id}, timeout=15)

    def download_file(
        self,
        file_id: str,
        *,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
        timeout: float = 60.0,
    ) -> bytes | None:
        """getFile + download. Returns None on failure / oversize."""
        r = self.get_file(file_id)
        if not r.get("ok"):
            return None
        result = r.get("result") or {}
        path = result.get("file_path")
        size = int(result.get("file_size") or 0)
        if not path:
            return None
        if size and size > max_bytes:
            logger.warning("Telegram file too large: %s > %s", size, max_bytes)
            return None
        url = self._file_url(str(path))
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                logger.warning("Telegram download exceeded max_bytes")
                return None
            return data
        except Exception as exc:
            logger.warning("Telegram download failed: %s", exc)
            return None

    # ── Chat management ───────────────────────────────────────────────────────

    def get_chat(self, chat_id: int | str) -> dict[str, Any]:
        return self.call("getChat", {"chat_id": str(chat_id)})

    def get_chat_member(self, chat_id: int | str, user_id: int) -> dict[str, Any]:
        return self.call("getChatMember", {
            "chat_id": str(chat_id), "user_id": user_id,
        })

    def get_chat_administrators(self, chat_id: int | str, **kwargs: Any) -> dict[str, Any]:
        return self.call("getChatAdministrators", {
            "chat_id": str(chat_id), **kwargs,
        })

    def get_chat_member_count(self, chat_id: int | str) -> dict[str, Any]:
        return self.call("getChatMemberCount", {"chat_id": str(chat_id)})

    def leave_chat(self, chat_id: int | str) -> dict[str, Any]:
        return self.call("leaveChat", {"chat_id": str(chat_id)})

    def ban_chat_member(
        self, chat_id: int | str, user_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("banChatMember", {
            "chat_id": str(chat_id), "user_id": user_id, **kwargs,
        })

    def unban_chat_member(
        self, chat_id: int | str, user_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("unbanChatMember", {
            "chat_id": str(chat_id), "user_id": user_id, **kwargs,
        })

    def restrict_chat_member(
        self, chat_id: int | str, user_id: int, permissions: dict, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("restrictChatMember", {
            "chat_id": str(chat_id),
            "user_id": user_id,
            "permissions": permissions,
            **kwargs,
        })

    def promote_chat_member(
        self, chat_id: int | str, user_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("promoteChatMember", {
            "chat_id": str(chat_id), "user_id": user_id, **kwargs,
        })

    def set_chat_title(self, chat_id: int | str, title: str) -> dict[str, Any]:
        return self.call("setChatTitle", {"chat_id": str(chat_id), "title": title})

    def set_chat_description(
        self, chat_id: int | str, description: str | None = None
    ) -> dict[str, Any]:
        return self.call("setChatDescription", {
            "chat_id": str(chat_id), "description": description,
        })

    def pin_chat_message(
        self, chat_id: int | str, message_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("pinChatMessage", {
            "chat_id": str(chat_id), "message_id": message_id, **kwargs,
        })

    def unpin_chat_message(
        self, chat_id: int | str, message_id: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("unpinChatMessage", {
            "chat_id": str(chat_id), "message_id": message_id, **kwargs,
        })

    def unpin_all_chat_messages(self, chat_id: int | str) -> dict[str, Any]:
        return self.call("unpinAllChatMessages", {"chat_id": str(chat_id)})

    def set_chat_permissions(
        self, chat_id: int | str, permissions: dict, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("setChatPermissions", {
            "chat_id": str(chat_id), "permissions": permissions, **kwargs,
        })

    def export_chat_invite_link(self, chat_id: int | str) -> dict[str, Any]:
        return self.call("exportChatInviteLink", {"chat_id": str(chat_id)})

    def create_chat_invite_link(self, chat_id: int | str, **kwargs: Any) -> dict[str, Any]:
        return self.call("createChatInviteLink", {"chat_id": str(chat_id), **kwargs})

    def revoke_chat_invite_link(
        self, chat_id: int | str, invite_link: str
    ) -> dict[str, Any]:
        return self.call("revokeChatInviteLink", {
            "chat_id": str(chat_id), "invite_link": invite_link,
        })

    def approve_chat_join_request(
        self, chat_id: int | str, user_id: int
    ) -> dict[str, Any]:
        return self.call("approveChatJoinRequest", {
            "chat_id": str(chat_id), "user_id": user_id,
        })

    def decline_chat_join_request(
        self, chat_id: int | str, user_id: int
    ) -> dict[str, Any]:
        return self.call("declineChatJoinRequest", {
            "chat_id": str(chat_id), "user_id": user_id,
        })

    # ── Forum topics ──────────────────────────────────────────────────────────

    def create_forum_topic(
        self, chat_id: int | str, name: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("createForumTopic", {
            "chat_id": str(chat_id), "name": name, **kwargs,
        })

    def edit_forum_topic(
        self, chat_id: int | str, message_thread_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        return self.call("editForumTopic", {
            "chat_id": str(chat_id),
            "message_thread_id": message_thread_id,
            **kwargs,
        })

    def close_forum_topic(
        self, chat_id: int | str, message_thread_id: int
    ) -> dict[str, Any]:
        return self.call("closeForumTopic", {
            "chat_id": str(chat_id), "message_thread_id": message_thread_id,
        })

    def reopen_forum_topic(
        self, chat_id: int | str, message_thread_id: int
    ) -> dict[str, Any]:
        return self.call("reopenForumTopic", {
            "chat_id": str(chat_id), "message_thread_id": message_thread_id,
        })

    def delete_forum_topic(
        self, chat_id: int | str, message_thread_id: int
    ) -> dict[str, Any]:
        return self.call("deleteForumTopic", {
            "chat_id": str(chat_id), "message_thread_id": message_thread_id,
        })

    # ── Keyboards (builders live here so callers don't invent shapes) ─────────

    @staticmethod
    def inline_keyboard(rows: list[list[dict[str, Any]]]) -> dict[str, Any]:
        """Build InlineKeyboardMarkup from rows of button dicts."""
        return {"inline_keyboard": rows}

    @staticmethod
    def inline_button(
        text: str,
        *,
        callback_data: str | None = None,
        url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        btn: dict[str, Any] = {"text": text, **kwargs}
        if callback_data is not None:
            btn["callback_data"] = callback_data
        if url is not None:
            btn["url"] = url
        return btn

    @staticmethod
    def reply_keyboard(
        rows: list[list[str | dict]],
        *,
        resize_keyboard: bool = True,
        one_time_keyboard: bool = False,
        selective: bool | None = None,
        input_field_placeholder: str | None = None,
        is_persistent: bool | None = None,
    ) -> dict[str, Any]:
        keyboard: list[list[dict]] = []
        for row in rows:
            r: list[dict] = []
            for cell in row:
                if isinstance(cell, str):
                    r.append({"text": cell})
                else:
                    r.append(dict(cell))
            keyboard.append(r)
        mk: dict[str, Any] = {
            "keyboard": keyboard,
            "resize_keyboard": resize_keyboard,
            "one_time_keyboard": one_time_keyboard,
        }
        if selective is not None:
            mk["selective"] = selective
        if input_field_placeholder is not None:
            mk["input_field_placeholder"] = input_field_placeholder
        if is_persistent is not None:
            mk["is_persistent"] = is_persistent
        return mk

    @staticmethod
    def remove_keyboard(*, selective: bool | None = None) -> dict[str, Any]:
        mk: dict[str, Any] = {"remove_keyboard": True}
        if selective is not None:
            mk["selective"] = selective
        return mk

    @staticmethod
    def force_reply(
        *,
        input_field_placeholder: str | None = None,
        selective: bool | None = None,
    ) -> dict[str, Any]:
        mk: dict[str, Any] = {"force_reply": True}
        if input_field_placeholder is not None:
            mk["input_field_placeholder"] = input_field_placeholder
        if selective is not None:
            mk["selective"] = selective
        return mk

    @staticmethod
    def reply_to(message_id: int, **kwargs: Any) -> dict[str, Any]:
        """Build ReplyParameters for reply_parameters=…"""
        return {"message_id": int(message_id), **kwargs}


def _guess_mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in MIME_BY_EXT:
        return MIME_BY_EXT[ext]
    guess, _ = mimetypes.guess_type(filename)
    return guess or "application/octet-stream"


# Module-level cache: token → client (bots rarely change tokens at runtime)
_clients: dict[str, TelegramClient] = {}


def get_client(token: str, **kwargs: Any) -> TelegramClient:
    tok = (token or "").strip()
    if not tok:
        return TelegramClient("")
    c = _clients.get(tok)
    if c is None:
        c = TelegramClient(tok, **kwargs)
        _clients[tok] = c
    return c


def clear_client_cache() -> None:
    _clients.clear()
