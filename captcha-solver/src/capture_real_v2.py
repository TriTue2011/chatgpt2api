import asyncio, sys, json
sys.path.insert(0, '/app')
from src.solvers.flow_google import _prime_flow_session
from src.browser_pool import pool

PROJECT_ID = '62e0f686-7172-4ef5-8535-24bd02866f5b'

async def main():
    async with pool.page(profile='google-fx', headless=False) as page:
        await _prime_flow_session(page)
        url = f'https://labs.google/fx/vi/tools/flow/project/{PROJECT_ID}'
        await page.goto(url, wait_until='domcontentloaded', timeout=30_000)

        # Wait for app shell
        await page.wait_for_function(
            '() => { const ces = Array.from(document.querySelectorAll("[contenteditable=true]")); return ces.some(e => e.offsetWidth > 200); }',
            timeout=60_000)
        print('Page hydrated')

        # Remove overlay dialogs
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

        # Register request listener BEFORE any interaction
        captured = {}

        def on_request(request):
            url_lower = request.url.lower()
            if 'batchgenerateimages' in url_lower:
                captured['url'] = request.url
                captured['body'] = request.post_data
                captured['headers'] = dict(request.headers)
                print(f'\n!!! CAPTURED batchGenerateImages !!!')
                print(f'URL: {request.url[:200]}')
                print(f'Method: {request.method}')
                print(f'Headers: {json.dumps(dict(request.headers), indent=2)}')
                print(f'Body: {request.post_data}')
            # Also log ALL API requests for reference
            if 'aisandbox-pa' in request.url and request.method == 'POST':
                body = request.post_data
                if body:
                    body_preview = body[:300]
                else:
                    body_preview = '<empty>'
                print(f'\n>>> POST {request.url[:120]}')
                print(f'    Body: {body_preview}')

        page.on('request', on_request)

        # Find the contenteditable and click it using Playwright locator
        ce = page.locator('[contenteditable=true]').first
        await ce.click(timeout=5000)
        await asyncio.sleep(0.5)
        print('Clicked editor')

        # Type text using Playwright's real keyboard
        await ce.press('Control+a')
        await asyncio.sleep(0.1)
        await ce.press('Backspace')
        await asyncio.sleep(0.1)
        await page.keyboard.type('a cat chasing a mouse in a banana garden', delay=30)
        await asyncio.sleep(1)
        print('Text typed via keyboard')

        # Find and click submit button
        btns = page.locator('button')
        btn_count = await btns.count()
        print(f'Found {btn_count} buttons')

        # Try to find the submit/send button
        for i in range(btn_count):
            try:
                btn = btns.nth(i)
                text = await btn.inner_text()
                print(f'  Btn {i}: "{text[:60]}"')
            except:
                pass

        # Click the submit button using Playwright
        submit_btn = page.locator('button:has-text("Tạo"), button:has-text("Generate"), button:has-text("Send"), button:has-text("Submit")').first
        if await submit_btn.count() > 0:
            await submit_btn.click(timeout=5000)
            print('Submit clicked via Playwright')
        else:
            # Fallback: find arrow_forward button
            print('No text-matched submit button, trying arrow button...')
            # Use JS to find and click
            result = await page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const btn = buttons.find(b => {
                        const t = b.innerText || '';
                        return t.includes('arrow_forward') || t.includes('arrow_upward');
                    });
                    if (btn) { btn.click(); return 'clicked'; }
                    return 'not found';
                }
            """)
            print(f'Arrow button: {result}')

        # Wait for API requests
        print('Waiting for API requests...')
        await asyncio.sleep(15)

        if captured:
            print(f'\n=== CAPTURED BODY ===')
            print(captured['body'])
        else:
            print('\nNo batchGenerateImages request captured')
            print('All captured POST requests are shown above')

asyncio.run(main())
