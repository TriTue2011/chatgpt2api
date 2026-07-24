"""Live Mouse Click Tracker & DOM Extractor for Google Flow.

Connects to Chrome via CDP (port 9222) and listens to every click event in real-time.
Logs clicked element tags, text, aria-labels, classes, and attributes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("live_tracker")

CDP_URL = "http://localhost:9222"

JS_CLICK_LISTENER = """
(() => {
    if (window._flow_tracker_attached) return;
    window._flow_tracker_attached = true;
    console.log('⚡ [Flow Live Tracker] Event listener attached!');
    
    document.addEventListener('click', (event) => {
        let el = event.target;
        let info = {
            timestamp: new Date().toISOString(),
            tagName: el.tagName,
            innerText: (el.innerText || '').slice(0, 100).trim(),
            className: el.className || '',
            id: el.id || '',
            ariaLabel: el.getAttribute('aria-label') || '',
            role: el.getAttribute('role') || '',
            type: el.getAttribute('type') || '',
            x: event.clientX,
            y: event.clientY,
            parentTag: el.parentElement ? el.parentElement.tagName : '',
            parentText: el.parentElement ? (el.parentElement.innerText || '').slice(0, 80).strip() : ''
        };
        console.log('👉 [CLICK EVENT]:', JSON.stringify(info));
    }, true);
})();
"""


async def start_live_tracker(cdp_url: str = CDP_URL):
    """Attach to running Chrome browser and monitor clicks live."""
    async with async_playwright() as p:
        try:
            logger.info("Connecting to Chrome via CDP at %s...", cdp_url)
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            
            pages = context.pages
            target_page = None
            for page in pages:
                if "flow" in page.url or "labs.google" in page.url:
                    target_page = page
                    break
            
            if not target_page:
                target_page = pages[0] if pages else await context.new_page()

            logger.info("Attached to page: %s (%s)", target_page.title, target_page.url)

            # Listen for console log events from browser
            def handle_console(msg):
                text = msg.text
                if "[CLICK EVENT]" in text:
                    logger.info(text)

            target_page.on("console", handle_console)
            
            # Inject JS click listener
            await target_page.evaluate(JS_CLICK_LISTENER)
            logger.info("🟢 LIVE TRACKER IS ACTIVE! Click anywhere on Google Flow, clicks will be captured in real-time.")

            # Keep running to stream clicks
            while True:
                await asyncio.sleep(1)
        except Exception as exc:
            logger.error("Tracker error: %s", exc)


if __name__ == "__main__":
    asyncio.run(start_live_tracker())
