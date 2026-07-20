import asyncio, sys, json
sys.path.insert(0, '/app')
from src.solvers.flow_google import _prime_flow_session, _capture_bearer, _get_recaptcha_token, _MODEL_API_VALUE, API_HOST
from src.browser_pool import pool

PROJECT_ID = '62e0f686-7172-4ef5-8535-24bd02866f5b'

async def probe(page, bearer, token, body, desc):
    api_url = f'{API_HOST}/v1/projects/{PROJECT_ID}/flowMedia:batchGenerateImages'
    headers = {
        'Authorization': f'Bearer {bearer}',
        'X-Recaptcha-Token': token,
        'Content-Type': 'application/json',
    }
    resp = await page.context.request.post(api_url, headers=headers, data=json.dumps(body))
    text = await resp.text()
    print(f'  {desc}: {resp.status}')
    if resp.status != 200:
        # Show just the first error message
        try:
            err = json.loads(text)
            msg = err.get('error', {}).get('message', text)[:200]
        except:
            msg = text[:200]
        print(f'    -> {msg}')
    else:
        print(f'    SUCCESS!')
    return resp.status, text

async def main():
    async with pool.page(profile='google-fx', headless=False) as page:
        # Register bearer listener BEFORE navigation
        bf = asyncio.ensure_future(_capture_bearer(page, timeout_s=30.0))

        await _prime_flow_session(page)
        url = f'https://labs.google/fx/vi/tools/flow/project/{PROJECT_ID}'
        await page.goto(url, wait_until='domcontentloaded', timeout=30_000)
        await asyncio.sleep(3)

        bearer = await bf
        print(f'Bearer len={len(bearer)}')
        token, sk = await _get_recaptcha_token(page, action='flow_generate')
        print(f'Token ok\n')

        # Try various field name formats
        tests = [
            # Empty & minimal
            ({}, 'empty'),
            ({'prompt': 'test'}, 'prompt'),
            # Different casing/styles
            ({'text_prompt': 'test'}, 'text_prompt (snake)'),
            ({'textPrompt': 'test'}, 'textPrompt (camel)'),
            ({'user_prompt': 'test'}, 'user_prompt'),
            ({'input_text': 'test'}, 'input_text'),
            ({'text': 'test'}, 'text'),
            ({'query': 'test'}, 'query'),
            # Maybe nested
            ({'input': {'prompt': 'test'}}, 'nested input.prompt'),
            ({'params': {'prompt': 'test'}}, 'nested params.prompt'),
            # Model fields
            ({'model': 'NANO_BANANA_PRO'}, 'model only'),
            ({'model_name': 'NANO_BANANA_PRO'}, 'model_name'),
            ({'image_model': 'NANO_BANANA_PRO'}, 'image_model'),
            # Try gRPC style (camelCase proto fields)
            ({'imageModelName': 'NANO_BANANA_PRO'}, 'imageModelName only'),
        ]

        for body, desc in tests:
            await probe(page, bearer, token, body, desc)

        # If ALL fields are unknown, maybe the API expects a different endpoint path format
        print('\n--- Checking API path ---')
        # Try without /v1/
        api_url2 = f'{API_HOST}/projects/{PROJECT_ID}/flowMedia:batchGenerateImages'
        resp = await page.context.request.post(api_url2,
            headers={'Authorization': f'Bearer {bearer}', 'X-Recaptcha-Token': token, 'Content-Type': 'application/json'},
            data='{}')
        t = await resp.text()
        print(f'  Without /v1/: {resp.status} {t[:200]}')

asyncio.run(main())
