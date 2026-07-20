"""Capture Flow API request body by observing a real generate click."""
import asyncio
import json
import logging
import sys

sys.path.insert(0, "src")
from solvers.flow_google import _prime_flow_session, _capture_bearer
from browser_pool import pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

PROJECT_ID = "62e0f686-7172-4ef5-8535-24bd02866f5b"

async def main():
    async with pool.page(profile="google-fx", headless=False) as page:
        await _prime_flow_session(page)
        url = f"https://labs.google/fx/vi/tools/flow/project/{PROJECT_ID}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(5)

        # Listen for requests to the Flow API
        captured = {}

        def on_request(request):
            if "flowMedia:batchGenerateImages" in request.url:
                captured["url"] = request.url
                captured["method"] = request.method
                captured["headers"] = dict(request.headers)
                captured["postData"] = request.post_data
                print(f"\n=== CAPTURED REQUEST ===")
                print(f"URL: {request.url}")
                print(f"Method: {request.method}")
                print(f"Headers: {json.dumps(dict(request.headers), indent=2)}")
                print(f"Body: {request.post_data}")

        page.on("request", on_request)

        # Inject prompt and click generate via JS
        # First, inject text into the contenteditable
        await page.evaluate(
            """(text) => {
                const ce = document.querySelector('[contenteditable=true]');
                if (!ce) return 'no ce';
                ce.focus();
                const e1 = new InputEvent('beforeinput', {
                    inputType: 'insertText', data: text,
                    bubbles: true, cancelable: true,
                });
                ce.dispatchEvent(e1);
                return 'ok';
            }""",
            "test prompt for capture"
        )
        await asyncio.sleep(1)

        # Click the submit button
        clicked = await page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                let btn = buttons.find(b => /arrow_forward/i.test(b.innerText||''));
                if (!btn) return {found: false, buttons: buttons.slice(0,20).map(b => (b.innerText||'').slice(0,40))};
                btn.click();
                return {found: true};
            }
        """)
        print(f"Clicked: {json.dumps(clicked)}")

        # Wait for the request
        await asyncio.sleep(15)

        if not captured:
            # Try again with route interception (minimal)
            print("\n=== Trying route capture ===")
            async def capture_route(route):
                req = route.request
                print(f"Route URL: {req.url}")
                print(f"Route Method: {req.method}")
                print(f"Route Headers: {json.dumps(dict(req.headers), indent=2)}")
                print(f"Route Body: {req.post_data}")
                captured["route_body"] = req.post_data
                await route.continue_()

            try:
                await page.route("**/flowMedia:batchGenerateImages**", capture_route)
                # Click again
                await page.evaluate("""
                    () => {
                        const btn = Array.from(document.querySelectorAll('button'))
                            .find(b => /arrow_forward/i.test(b.innerText||''));
                        if (btn) btn.click();
                    }
                """)
                await asyncio.sleep(10)
            except Exception as e:
                print(f"Route error: {e}")

        print(f"\n=== Final captured: {json.dumps(captured, indent=2, default=str)}")


if __name__ == "__main__":
    asyncio.run(main())
