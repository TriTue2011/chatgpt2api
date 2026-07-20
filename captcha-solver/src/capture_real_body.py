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

        # Register request listener BEFORE clicking
        captured = {}
        def on_request(request):
            if 'flowMedia:batchGenerateImages' in request.url:
                captured['url'] = request.url
                captured['body'] = request.post_data
                captured['headers'] = dict(request.headers)
                print(f'\n!!! CAPTURED !!!')
                print(f'URL: {request.url[:150]}')
                print(f'Body: {request.post_data}')
        page.on('request', on_request)

        # Click prompt input via JS focus + mouse event
        await page.evaluate("""
            () => {
                const ce = document.querySelector('[contenteditable=true]');
                if (!ce) return 'no ce';
                ce.focus();
                const r = ce.getBoundingClientRect();
                const x = r.left + r.width/2, y = r.top + r.height/2;
                const opts = {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, view: window};
                ce.dispatchEvent(new PointerEvent('pointerdown', opts));
                ce.dispatchEvent(new MouseEvent('mousedown', opts));
                ce.dispatchEvent(new PointerEvent('pointerup', opts));
                ce.dispatchEvent(new MouseEvent('mouseup', opts));
                ce.dispatchEvent(new MouseEvent('click', opts));
                return 'clicked';
            }
        """)
        await asyncio.sleep(0.5)
        print('Prompt clicked')

        # Inject text via InputEvent (Slate needs this)
        await page.evaluate(
            """(text) => {
                const ce = document.querySelector('[contenteditable=true]');
                ce.focus();
                ce.dispatchEvent(new InputEvent('beforeinput', {
                    inputType: 'insertText', data: text,
                    bubbles: true, cancelable: true,
                }));
                ce.dispatchEvent(new InputEvent('input', {
                    inputType: 'insertText', data: text,
                    bubbles: true, cancelable: true,
                }));
            }""",
            'capture test prompt please work'
        )
        await asyncio.sleep(1)
        print('Text injected')

        # Click submit button
        clicked = await page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button'));
                let btn = buttons.find(b => /arrow_forward[\\s\\n]+(Tạo|Generate|Create|Send|Submit)/i.test(b.innerText || ''));
                if (!btn) btn = buttons.find(b => /arrow_(forward|upward)/i.test(b.innerText || ''));
                if (!btn) {
                    const taoes = buttons.filter(b => /Tạo/.test(b.innerText||'') && !/add_2/.test(b.innerText||''));
                    btn = taoes[taoes.length - 1];
                }
                if (!btn) return {found: false, all_buttons: buttons.map(b => (b.innerText||'').slice(0,60).replace(/\\n/g,'|'))};
                btn.click();
                return {found: true, text: (btn.innerText||'').slice(0,100)};
            }
        """)
        print(f'Submit click result: {json.dumps(clicked, ensure_ascii=False)}')

        await asyncio.sleep(20)
        if captured:
            print(f'\nSaved body: {captured["body"]}')
        else:
            print('\nNo request captured')

asyncio.run(main())
