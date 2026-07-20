import asyncio, sys, json
sys.path.insert(0, '/app')
from src.solvers.flow_google import _prime_flow_session
from src.browser_pool import pool

PROJECT_ID = '62e0f686-7172-4ef5-8535-24bd02866f5b'

async def main():
    async with pool.page(profile='google-fx', headless=False) as page:
        # Log ALL requests to aisandbox
        def on_request(request):
            if 'aisandbox-pa' in request.url:
                print(f'\n>>> {request.method} {request.url[:200]}')
                print(f'    Content-Type: {request.headers.get("content-type", "none")}')
                body = request.post_data
                if body:
                    print(f'    Body ({len(body)}b): {body[:500]}')

        page.on('request', on_request)

        await _prime_flow_session(page)
        url = f'https://labs.google/fx/vi/tools/flow/project/{PROJECT_ID}'
        await page.goto(url, wait_until='domcontentloaded', timeout=30_000)

        # Wait for any requests to flow
        print('Waiting for requests...')
        await asyncio.sleep(15)
        print('Done waiting')

asyncio.run(main())
