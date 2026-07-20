"""web_agent — giao cho AI tự điều khiển trình duyệt làm tác vụ web nhiều bước.

Bọc browser-use: LLM trỏ về chính chatgpt2api (127.0.0.1:80/v1) nên không cần
API key ngoài. Dùng cho tác vụ động (điền form, lướt nhiều trang, thao tác UI)
mà web_reader (chỉ đọc) không làm được.

Lưu ý: browser-use's __init__ cố import mọi provider (kể cả OCI) → import lazy
chỉ Agent + ChatOpenAI để tránh ModuleNotFoundError('oci').

Tool:
- run_web_task(task, max_steps): chạy agent, trả về kết quả cuối.
"""

from __future__ import annotations

import logging
import os

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("web_agent")


def _make_llm():
    try:
        from browser_use import ChatOpenAI  # lazy
    except Exception:
        from browser_use.llm import ChatOpenAI  # type: ignore
    key = os.getenv("CHATGPT2API_AUTH_KEY") or os.getenv("CAPTCHA_SOLVER_API_KEY") or "sk-none"
    base = os.getenv("WEB_AGENT_API_BASE", "http://127.0.0.1:80/v1")
    model = os.getenv("WEB_AGENT_MODEL", "cx/auto")
    return ChatOpenAI(model=model, base_url=base, api_key=key, temperature=0.2)


@mcp.tool()
async def run_web_task(task: str, max_steps: int = 12) -> str:
    """Để AI tự mở trình duyệt và hoàn thành một tác vụ web nhiều bước.

    Ví dụ: "tìm giá iPhone 16 trên thegioididong rồi đọc 3 đánh giá đầu",
    "vào trang X điền form Y". Chậm (mỗi bước 1 lượt LLM) nên giới hạn max_steps.
    Với việc chỉ ĐỌC một trang, dùng web_reader.read_url cho nhanh.

    Args:
        task: Mô tả tác vụ bằng ngôn ngữ tự nhiên.
        max_steps: Số bước tối đa agent được thực hiện (1-30, mặc định 12).

    Returns:
        Kết quả cuối agent thu được.
    """
    try:
        try:
            from browser_use import Agent  # lazy
        except Exception:
            from browser_use.beta import Agent  # type: ignore
        llm = _make_llm()
        agent = Agent(task=task, llm=llm)
        try:
            history = await agent.run(max_steps=max(1, min(30, max_steps)))
        except TypeError:
            history = await agent.run()  # older signature
        try:
            result = history.final_result()
        except Exception:
            result = str(history)
        return result or "Hoàn tất nhưng không có kết quả văn bản."
    except Exception as exc:
        logger.warning("web_agent failed: %s", exc)
        return f"web_agent lỗi: {exc}"
