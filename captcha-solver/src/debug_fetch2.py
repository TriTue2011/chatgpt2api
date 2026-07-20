import asyncio, sys, json
sys.path.insert(0, '/app')
from src.solvers.flow_google import _prime_flow_session, _capture_bearer, _get_recaptcha_token, _MODEL_API_VALUE, API_HOST
from src.browser_pool import pool

PROJECT_ID = "62e0f686-7172-4ef5-8535-24bd02866f5b"

async def main():
    async with pool.page(profile='google-fx', headless=False) as page:
        await _prime_flow_session(page)
        url = f'https://labs.google/fx/vi/tools/flow/project/{PROJECT_ID}'
        await page.goto(url, wait_until='domcontentloaded', timeout=30_000)
        await asyncio.sleep(3)

        try:
            await page.wait_for_function(
                '() => { const ces = Array.from(document.querySelectorAll("[contenteditable=true]")); return ces.some(e => e.offsetWidth > 200); }',
                timeout=30_000)
        except Exception:
            pass

        # CSP bypass via CDP
        cdp = await page.context.new_cdp_session(page)
        await cdp.send('Page.setBypassCSP', {'enabled': True})
        print('CSP bypassed')

        bearer = await _capture_bearer(page, timeout_s=25.0)
        print(f'Bearer len={len(bearer)}')

        recaptcha_token, sitekey = await _get_recaptcha_token(page, action="flow_generate")
        print(f'Recaptcha ok sitekey={sitekey[:20]} token={recaptcha_token[:30]}')

        api_url = f'{API_HOST}/v1/projects/{PROJECT_ID}/flowMedia:batchGenerateImages'
        api_model = _MODEL_API_VALUE.get("NANO_BANANA_PRO", "NANO_BANANA_PRO")
        body = {
            "prompt": "mèo đuổi chuột trong vườn chuối việt nam",
            "imageModelName": api_model,
            "aspectRatio": "IMAGE_ASPECT_RATIO_LANDSCAPE",
            "imageCount": 1,
        }

        # EXACT same pattern as generate_image
        result = await page.evaluate(
            """async (args) => {
                const resp = await fetch(args.apiUrl, {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + args.bearer,
                        'X-Recaptcha-Token': args.recaptchaToken,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(args.body),
                });
                const status = resp.status;
                let data;
                try { data = await resp.json(); }
                catch (e) { data = await resp.text(); }
                return {status, data};
            }""",
            {
                "apiUrl": api_url,
                "body": body,
                "bearer": bearer,
                "recaptchaToken": recaptcha_token,
            },
        )

        status = result.get("status", 0)
        print(f'Status: {status}')
        if status != 200:
            error_body = result.get("data", "")
            if isinstance(error_body, dict):
                error_body = json.dumps(error_body)
            print(f'Error: {str(error_body)[:600]}')
        else:
            data = result.get("data", {})
            media = data.get("media", [])
            print(f'Success! {len(media)} image(s) generated')
            for m in media:
                name = m.get("name", "?")
                img = m.get("image", {}).get("generatedImage", {})
                print(f'  {name}: fifeUrl={img.get("fifeUrl", "")[:80]}')

asyncio.run(main())
