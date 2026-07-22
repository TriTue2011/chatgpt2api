"""Telegram Bot API constants & limits (cloud Bot API).

Refs: https://core.telegram.org/bots/api
"""

from __future__ import annotations

# Official cloud Bot API base (local server may override).
DEFAULT_API_BASE = "https://api.telegram.org"

# Text / caption
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
SAFE_MESSAGE_LENGTH = 4000  # leave room for "…" / markers
SAFE_CAPTION_LENGTH = 1000

# Files (cloud Bot API — local server is higher)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_PHOTO_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024
MAX_URL_PHOTO_BYTES = 5 * 1024 * 1024
MAX_URL_FILE_BYTES = 20 * 1024 * 1024

# Webhook
WEBHOOK_PORTS = (443, 80, 88, 8443)
SECRET_TOKEN_MAX_LEN = 256
# secret_token charset: A-Z a-z 0-9 _ -
DEFAULT_ALLOWED_UPDATES: tuple[str, ...] = (
    "message",
    "edited_message",
    "callback_query",
)

# Rate (FAQ approximate)
RATE_PER_CHAT_MSG_PER_SEC = 1
RATE_GROUP_MSG_PER_MIN = 20
RATE_BROADCAST_MSG_PER_SEC = 30

# Parse modes
PARSE_MODE_MARKDOWN = "Markdown"       # legacy
PARSE_MODE_MARKDOWN_V2 = "MarkdownV2"
PARSE_MODE_HTML = "HTML"

# Chat actions for sendChatAction
CHAT_ACTIONS: tuple[str, ...] = (
    "typing",
    "upload_photo",
    "record_video",
    "upload_video",
    "record_voice",
    "upload_voice",
    "upload_document",
    "choose_sticker",
    "find_location",
    "record_video_note",
    "upload_video_note",
)

# Common update kinds (Update optional fields)
UPDATE_KINDS: tuple[str, ...] = (
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
    "guest_message",
    "message_reaction",
    "message_reaction_count",
    "inline_query",
    "chosen_inline_result",
    "callback_query",
    "shipping_query",
    "pre_checkout_query",
    "purchased_paid_media",
    "poll",
    "poll_answer",
    "my_chat_member",
    "chat_member",
    "chat_join_request",
    "chat_boost",
    "removed_chat_boost",
    "managed_bot",
    "subscription",
)

# MIME helpers
MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".zip": "application/zip",
}
