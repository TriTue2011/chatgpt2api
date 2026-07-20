import asyncio, sys, json, base64
sys.path.insert(0, '/app')
from src.solvers.flow_google import _prime_flow_session, _capture_bearer
from src.browser_pool import pool

PROJECT_ID = '62e0f686-7172-4ef5-8535-24bd02866f5b'

async def main():
    async with pool.page(profile='google-fx', headless=False) as page:
        await _prime_flow_session(page)
        url = f'https://labs.google/fx/vi/tools/flow/project/{PROJECT_ID}'
        await page.goto(url, wait_until='domcontentloaded', timeout=30_000)

        await page.wait_for_function(
            '() => { const ces = Array.from(document.querySelectorAll("[contenteditable=true]")); return ces.some(e => e.offsetWidth > 200); }',
            timeout=60_000)
        print('Page hydrated')

        # Remove overlay
        await page.evaluate("""
            () => {
                document.querySelectorAll('[data-state="open"]').forEach(el => {
                    if (el.getAttribute('role')) return;
                    const r = el.getBoundingClientRect();
                    if (r.width >= window.innerWidth * 0.8 && r.height >= window.innerHeight * 0.8) {
                        el.remove();
                    }
                });
            }
        """)
        await asyncio.sleep(0.5)
        print('Overlay removed')

        # Use page.route to intercept the batchGenerateImages request
        captured = {}

        async def handle_route(route):
            if 'batchGenerateImages' in route.request.url:
                captured['url'] = route.request.url
                captured['method'] = route.request.method
                captured['headers'] = dict(route.request.headers)
                captured['body'] = route.request.post_data
                print(f'\n!!! CAPTURED batchGenerateImages via route !!!')
                print(f'URL: {route.request.url}')
                print(f'Method: {route.request.method}')
                print(f'Headers: {json.dumps(dict(route.request.headers), indent=2)}')
                print(f'Body: {route.request.post_data}')
            await route.continue_()

        await page.route('**/aisandbox-pa.googleapis.com/**', handle_route)
        print('Route handler registered')

        # Click the editor using Playwright locator (real click)
        ce = page.locator('[contenteditable=true]').first
        await ce.click(timeout=5000)
        await asyncio.sleep(0.5)
        print('Editor clicked')

        # Clear and type using real keyboard
        await page.keyboard.press('Control+a')
        await asyncio.sleep(0.1)
        await page.keyboard.press('Backspace')
        await asyncio.sleep(0.2)
        await page.keyboard.type('a cat chasing a mouse', delay=30)
        await asyncio.sleep(1)
        print('Text typed via Playwright keyboard')

        # Find and click submit button
        # Try various button selectors
        submit_clicked = False
        for selector in [
            'button:has-text("Tạo")',
            'button:has-text("Generate")',
            'button:has-text("Create")',
            'button[aria-label*="Generate" i]',
            'button[aria-label*="Submit" i]',
            'button[aria-label*="Send" i]',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    if await btn.is_enabled():
                        await btn.click(timeout=3000)
                        print(f'Clicked: {selector}')
                        submit_clicked = True
                        break
                    else:
                        print(f'Button {selector} found but disabled')
            except Exception as e:
                print(f'{selector}: {e}')

        if not submit_clicked:
            print('Trying JS-based button find...')
            result = await page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button:not([disabled])'));
                    const info = buttons.map((b, i) => ({
                        i, text: (b.innerText || '').slice(0, 80).replace(/\\n/g, '|'),
                        aria: (b.getAttribute('aria-label') || '').slice(0, 80),
                        disabled: b.disabled,
                        ariaDisabled: b.getAttribute('aria-disabled'),
                    }));
                    // Find create/generate button
                    const btn = buttons.find(b => {
                        const t = ((b.innerText || '') + (b.getAttribute('aria-label') || '')).toLowerCase();
                        return /arrow_forward|arrow_upward|tao|generate|create|send|submit/i.test(t);
                    });
                    if (btn) {
                        btn.click();
                        return {clicked: true, text: (btn.innerText || '').slice(0, 80)};
                    }
                    return {clicked: false, buttons: info};
                }
            """)
            print(f'JS click result: {json.dumps(result, ensure_ascii=False)[:500]}')

        print('Waiting for API requests...')
        await asyncio.sleep(20)

        if captured:
            print(f'\n=== SUCCESS: Captured body ===')
            print(f'Body: {captured["body"]}')
            print(f'Headers: {json.dumps(captured.get("headers", {}), indent=2)}')
        else:
            print('\nNo batchGenerateImages request captured')

asyncio.run(main())
