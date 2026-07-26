from __future__ import annotations

from curl_cffi import requests
from fastapi import HTTPException

from services.config import config
from services.proxy_service import proxy_settings

DEFAULT_REVIEW_PROMPT = "Đánh giá yêu cầu của người dùng có được phép không. CHỈ trả lời ALLOW hoặc REJECT."


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(_text(value.get(key)) for key in ("text", "input_text", "content", "input", "instructions", "system", "prompt"))
    return ""


def request_text(*values: object) -> str:
    return "\n".join(part for value in values if (part := _text(value).strip()))


# Ky tu zero-width (u200b/u200c/u200d/ufeff/u2060) - cach ne bo loc pho bien
# bang cach chen ky tu vo hinh xen giua tu nhay cam. Strip truoc khi so khop.
_ZERO_WIDTH_TRANS = str.maketrans("", "", "\u200b\u200c\u200d\ufeff\u2060")


def _fold(value: str) -> str:
    return value.translate(_ZERO_WIDTH_TRANS).casefold()


def check_request(text: str) -> None:
    text = str(text or "")
    if not text:
        return
    # FIX bypass: truoc day so khop case-sensitive ("if word in text") - vi
    # ai_review (LLM) mac dinh tat (services/config.py), list nay la cong chan
    # NOI DUNG DUY NHAT theo mac dinh, chi can viet hoa/thuong khac la lot qua.
    # casefold() ca 2 ve (khong chi .lower() - xu ly dung ca ky tu da ngon ngu).
    folded_text = _fold(text)
    for word in config.sensitive_words:
        if _fold(word) in folded_text:
            raise HTTPException(status_code=400, detail={"error": "Phát hiện từ nhạy cảm — đã từ chối yêu cầu này"})
    review = config.ai_review
    if not review.get("enabled"):
        return
    base_url = str(review.get("base_url") or "").strip().rstrip("/")
    api_key = str(review.get("api_key") or "").strip()
    model = str(review.get("model") or "").strip()
    if not base_url or not api_key or not model:
        raise HTTPException(status_code=400, detail={"error": "ai review config is incomplete"})
    prompt = str(review.get("prompt") or DEFAULT_REVIEW_PROMPT).strip()
    content = f"{prompt}\n\nYêu cầu người dùng:\n{text}\n\nCHỈ trả lời ALLOW hoặc REJECT."
    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0},
            timeout=60,
            **proxy_settings.build_session_kwargs(),
        )
        result = str(response.json()["choices"][0]["message"]["content"]).strip().lower()
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": f"ai review failed: {exc}"}) from exc
    if result.startswith(("allow", "pass", "true", "yes", "通过", "允许", "安全")):
        return
    raise HTTPException(status_code=400, detail={"error": "AI kiểm duyệt không đạt — đã từ chối yêu cầu này"})
