"""Telegram Bot API service layer for chatgpt2api.

Full-ish client + format/webhook/rich helpers so channel code does not re-
implement Bot API details. Prefer:

    from services.telegram import TelegramClient, get_client
    from services import telegram as tg

    cli = tg.get_client(token)
    cli.send_message_safe(chat_id, reply)

Legacy entrypoint remains ``services.telegram_bot`` (webhook + agent wiring).
"""

from __future__ import annotations

from services.telegram import format as fmt
from services.telegram import rich
from services.telegram import updates
from services.telegram.auto_format import FormatChoice, analyze, choose_format, strip_for_plain
from services.telegram.client import TelegramClient, clear_client_cache, get_client
from services.telegram.emphasis import (
    emphasize_text,
    emphasis_settings,
    resolve_emphasis_settings,
    bot_emphasis_defaults,
)
from services.telegram.constants import (
    CHAT_ACTIONS,
    DEFAULT_ALLOWED_UPDATES,
    DEFAULT_API_BASE,
    MAX_CAPTION_LENGTH,
    MAX_DOWNLOAD_BYTES,
    MAX_MESSAGE_LENGTH,
    MAX_UPLOAD_FILE_BYTES,
    MAX_UPLOAD_PHOTO_BYTES,
    PARSE_MODE_HTML,
    PARSE_MODE_MARKDOWN,
    PARSE_MODE_MARKDOWN_V2,
    SAFE_CAPTION_LENGTH,
    SAFE_MESSAGE_LENGTH,
    UPDATE_KINDS,
)
from services.telegram.format import (
    clip,
    clip_caption,
    escape_html,
    escape_markdown_legacy,
    escape_markdown_v2,
    llm_to_html,
    llm_to_legacy_markdown,
    split_message,
)
from services.telegram.rich import (
    draft_stream_id,
    input_rich_message,
    markdown_to_blocks,
)
from services.telegram.updates import (
    UpdateDedupe,
    default_webhook_payload,
    detect_bot_mention,
    extract_message,
    is_duplicate_update,
    match_bot_by_secret,
    message_context,
    update_kind,
    webhook_secret_for,
)

__all__ = [
    # client
    "TelegramClient",
    "get_client",
    "clear_client_cache",
    # constants
    "DEFAULT_API_BASE",
    "DEFAULT_ALLOWED_UPDATES",
    "MAX_MESSAGE_LENGTH",
    "MAX_CAPTION_LENGTH",
    "SAFE_MESSAGE_LENGTH",
    "SAFE_CAPTION_LENGTH",
    "MAX_DOWNLOAD_BYTES",
    "MAX_UPLOAD_PHOTO_BYTES",
    "MAX_UPLOAD_FILE_BYTES",
    "PARSE_MODE_MARKDOWN",
    "PARSE_MODE_MARKDOWN_V2",
    "PARSE_MODE_HTML",
    "CHAT_ACTIONS",
    "UPDATE_KINDS",
    # format
    "fmt",
    "clip",
    "clip_caption",
    "escape_html",
    "escape_markdown_legacy",
    "escape_markdown_v2",
    "llm_to_html",
    "llm_to_legacy_markdown",
    "split_message",
    # auto format
    "choose_format",
    "analyze",
    "strip_for_plain",
    "FormatChoice",
    "emphasize_text",
    "emphasis_settings",
    "resolve_emphasis_settings",
    "bot_emphasis_defaults",
    # updates
    "updates",
    "webhook_secret_for",
    "match_bot_by_secret",
    "UpdateDedupe",
    "is_duplicate_update",
    "update_kind",
    "extract_message",
    "message_context",
    "detect_bot_mention",
    "default_webhook_payload",
    # rich
    "rich",
    "input_rich_message",
    "markdown_to_blocks",
    "draft_stream_id",
]
