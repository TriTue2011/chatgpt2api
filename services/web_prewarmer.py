"""Keep Gemini HTTP sessions ready without opening or warming browser tabs."""
import asyncio

from utils.log import logger


async def _warm_pass():
    # GeminiClient rotates cookies through HTTP and persists them in DATA_DIR.
    # Browser warmup endpoints are deliberately not called: a stored profile
    # needs no running Chrome process until a user or browser-only task opens it.
    try:
        from api.gemini_web import prewarm_clients
        await asyncio.to_thread(prewarm_clients)
    except Exception:
        logger.warning("web_prewarmer: Gemini HTTP client warmup failed")


async def _prewarm_loop():
    await asyncio.sleep(10)
    while True:
        await _warm_pass()
        # Discover newly configured accounts; existing clients manage their own
        # 600-second cookie refresh timers and are reused without browser reads.
        await asyncio.sleep(25 * 60)


def start():
    asyncio.create_task(_prewarm_loop())
