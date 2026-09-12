"""Google reCAPTCHA v2/v3 solver via playwright-recaptcha (audio-challenge
fallback) plus a passive token harvester for v3-invisible widgets.

For v3 (invisible) we just open the page, let the JS execute the
"grecaptcha.execute(sitekey, {action})" promise, and read the returned token
from grecaptcha.getResponse(). For v2 (checkbox) we delegate to the audio
challenge solver from playwright-recaptcha — Patchright passes Google's
suspicion checks well enough that the audio path usually succeeds.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..browser_pool import pool
from ..settings import settings

logger = logging.getLogger(__name__)


async def solve_recaptcha_v3(
    url: str,
    sitekey: str,
    action: str = "submit",
    profile: str = "default",
    headless: bool = True,
    timeout: int | None = None,
) -> dict:
    """Trigger grecaptcha.execute on `url` and return the resulting token.

    The page does not need to have a visible reCAPTCHA widget — only the
    grecaptcha runtime must be loaded.
    """
    deadline = time.time() + (timeout or settings.solve_timeout)
    async with pool.page(profile=profile, headless=headless) as page:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Wait for the grecaptcha runtime, then call execute(sitekey, {action})
        await page.wait_for_function(
            "() => window.grecaptcha && grecaptcha.execute",
            timeout=20_000,
        )

        token = await page.evaluate(
            """async ({sitekey, action}) => {
                try {
                    return await grecaptcha.execute(sitekey, { action });
                } catch (e) {
                    return { __error: String(e) };
                }
            }""",
            {"sitekey": sitekey, "action": action},
        )

        if isinstance(token, dict) and token.get("__error"):
            raise RuntimeError(f"grecaptcha.execute failed: {token['__error']}")

        if not token or not isinstance(token, str):
            raise RuntimeError("grecaptcha.execute returned empty token")

        logger.info("recaptcha v3 token obtained len=%d action=%s", len(token), action)
        return {
            "token": token,
            "expires_at": time.time() + 110,
            "action": action,
            "profile": profile,
        }


async def tich_o_recaptcha(page, cho_giay: float = 6.0) -> bool:
    """Bấm thẳng vào ô "Tôi không phải là người máy". True = ô đã tích xong.

    Vì sao KHÔNG để `playwright_recaptcha` lo bước này: nó tìm ô bằng
    `get_by_role("checkbox", name=<tên hiển thị>)` với đúng 9 bản dịch, và
    KHÔNG có tiếng Việt — đo 12/09/2026: tìm chuỗi "không phải là người máy"
    trong cả gói, không ra kết quả nào. Mà trình duyệt của mình cố ý đặt
    `locale="vi-VN"` (browser_pool.py) và ép `?hl=vi` (auto_login.py), nên
    trang LUÔN hiện tiếng Việt. Tên không khớp → thư viện coi như không có ô →
    báo "No unchecked reCAPTCHA boxes were found" dù ô đang hiện rành rành.
    Đó chính là thứ đã xảy ra trong lượt đăng nhập thật đo lúc 20:03.

    Ở đây bám vào VAI TRÒ và MÃ PHẦN TỬ, cả hai không đổi theo ngôn ngữ, và
    `aria-checked` cũng vậy. Khuôn theo `solvers/turnstile.py:43` — nếp
    bấm-trong-iframe sẵn có của nhà, kể cả cách xếp bộ chọn dự phòng.

    KHÔNG hứa giải xong captcha: Google thường bung tiếp thử thách sau cú bấm.
    Hàm này chỉ lo đúng cú tích; phần sau để caller quyết.
    """
    khung = page.frame_locator('iframe[src*="api2/anchor"]')
    bam_duoc = False
    for sel in ("#recaptcha-anchor", '[role="checkbox"]'):
        try:
            await khung.locator(sel).first.click(timeout=3000, force=True)
            bam_duoc = True
            break
        except Exception:
            continue
    if not bam_duoc:
        return False

    het = time.time() + cho_giay
    while time.time() < het:
        try:
            if await khung.locator("#recaptcha-anchor").first.get_attribute(
                    "aria-checked") == "true":
                return True
        except Exception:
            pass
        await page.wait_for_timeout(500)
    return False


async def solve_recaptcha_v2_tren_trang(page) -> str:
    """Giải reCAPTCHA v2 NGAY TRÊN TRANG ĐANG MỞ — trả về token, hoặc raise.

    `solve_recaptcha_v2` bên dưới tự `pool.page()` rồi `goto(url)`. Gọi nó giữa
    một lượt đăng nhập Google là mất sạch ngữ cảnh đang dở (cookie phiên, bước
    Google đã đi tới) — thử thách hiện ra trên ĐÚNG trang đang đăng nhập, nên
    phải giải tại chỗ. `recaptchav2.AsyncSolver` vốn nhận thẳng một `page`.

    Nhập `playwright_recaptcha` BÊN TRONG hàm là cố ý: gói này kéo theo
    `speech_recognition`, mà `speech_recognition` nhập `aifc` và `audioop` —
    hai module đã bị gỡ khỏi thư viện chuẩn từ Python 3.13 (ảnh đang chạy
    3.13.14). Nhập ở cấp module thì một gói thiếu làm hỏng CẢ luồng đăng nhập;
    nhập tại đây thì hỏng nhiều nhất là mất đường tự giải, người vẫn gõ tay
    trên noVNC được như trước.
    """
    from playwright_recaptcha import recaptchav2

    async with recaptchav2.AsyncSolver(page) as solver:
        token = await solver.solve_recaptcha(wait=True)
    if not token:
        raise RuntimeError("recaptcha v2 solver returned empty token")
    return token


async def solve_recaptcha_v2(
    url: str,
    profile: str = "default",
    headless: bool = True,
    timeout: int | None = None,
) -> dict:
    """Solve a v2 checkbox/audio reCAPTCHA on the given page.

    Uses playwright-recaptcha's audio-challenge solver under the hood.
    """
    from playwright_recaptcha import recaptchav2

    deadline = time.time() + (timeout or settings.solve_timeout)
    async with pool.page(profile=profile, headless=headless) as page:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        async with recaptchav2.AsyncSolver(page) as solver:
            token = await solver.solve_recaptcha(wait=True)
        if not token:
            raise RuntimeError("recaptcha v2 solver returned empty token")
        return {
            "token": token,
            "expires_at": time.time() + 110,
            "profile": profile,
        }
