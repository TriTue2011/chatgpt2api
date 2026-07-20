import asyncio, sys, json
sys.path.insert(0, '/app')
from src.solvers.flow_google import _prime_flow_session, _capture_bearer, _get_recaptcha_token, _MODEL_API_VALUE, API_HOST
from src.browser_pool import pool

PROJECT_ID = '62e0f686-7172-4ef5-8535-24bd02866f5b'
API_MODEL = 'NANO_BANANA_PRO'

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
        try:
            err = json.loads(text)
            msg = err.get('error', {}).get('message', text)[:200]
        except:
            msg = text[:200]
        print(f'    -> {msg}')
    else:
        print(f'    SUCCESS! Images: {text[:200]}')
    return resp.status, text

async def main():
    async with pool.page(profile='google-fx', headless=False) as page:
        bf = asyncio.ensure_future(_capture_bearer(page, timeout_s=30.0))
        await _prime_flow_session(page)
        url = f'https://labs.google/fx/vi/tools/flow/project/{PROJECT_ID}'
        await page.goto(url, wait_until='domcontentloaded', timeout=30_000)
        await asyncio.sleep(3)
        bearer = await bf
        print(f'Bearer len={len(bearer)}')
        token, sk = await _get_recaptcha_token(page, action='flow_generate')
        print(f'Token ok\n')

        # Try various message structures - maybe there's a wrapper field
        tests = [
            # Try with 'parent' field (standard Google API pattern)
            ({'parent': f'projects/{PROJECT_ID}'}, 'parent only'),
            ({'parent': f'projects/{PROJECT_ID}', 'prompt': 'test'}, 'parent + prompt'),
            ({'parent': f'projects/{PROJECT_ID}', 'imageModelName': API_MODEL, 'prompt': 'test', 'imageCount': 1}, 'parent + all fields'),

            # Maybe the wrapper is "request"
            ({'request': {'prompt': 'test'}}, 'request.prompt (nested)'),
            ({'request': {'prompt': 'test', 'imageModelName': API_MODEL, 'imageCount': 1}}, 'request.* all fields'),

            # Maybe each image gen request is an item in an array
            ({'requests': [{'prompt': 'test'}]}, 'requests array single'),
            ({'requests': [{'prompt': 'test', 'imageModelName': API_MODEL}]}, 'requests array with model'),

            # Try 'input' wrapper
            ({'input': {'prompt': 'test'}}, 'input.prompt'),

            # Try 'generateImageRequest' or similar
            ({'generateImageRequest': {'prompt': 'test'}}, 'generateImageRequest wrapper'),
            ({'generationRequest': {'prompt': 'test'}}, 'generationRequest wrapper'),

            # Maybe fields are snake_case in proto
            ({'text_prompt': 'test', 'image_model_name': API_MODEL, 'image_count': 1, 'aspect_ratio': 'IMAGE_ASPECT_RATIO_LANDSCAPE'}, 'snake_case all'),
            ({'image_model': API_MODEL, 'text': 'test', 'num_images': 1}, 'snake_case alt'),

            # Try different field for prompt: description, textPrompt, text
            ({'description': 'test', 'imageModelName': API_MODEL, 'imageCount': 1}, 'description not prompt'),
            ({'promptText': 'test', 'model': API_MODEL, 'count': 1}, 'promptText + model + count'),

            # Maybe the fields reference the media type
            ({'mediaType': 'IMAGE', 'prompt': 'test', 'modelName': API_MODEL}, 'mediaType prefix'),
            ({'outputType': 'IMAGE', 'prompt': 'test', 'modelName': API_MODEL}, 'outputType prefix'),

            # Try with 'name' field (Google AIP resource name)
            ({'name': f'projects/{PROJECT_ID}', 'prompt': 'test', 'imageModel': API_MODEL}, 'name field'),

            # Try completely different field names from Google Imagen API
            ({'instances': [{'prompt': 'test'}], 'parameters': {'sampleCount': 1, 'model': API_MODEL}}, 'Imagen-style instances+params'),

            # Try with 'config' or 'params'
            ({'config': {'prompt': 'test', 'modelName': API_MODEL, 'numImages': 1}}, 'config wrapper'),
            ({'params': {'prompt': 'test', 'model': API_MODEL, 'count': 1}}, 'params wrapper'),

            # Try with 'generationConfig'
            ({'prompt': 'test', 'generationConfig': {'modelName': API_MODEL, 'aspectRatio': 'IMAGE_ASPECT_RATIO_LANDSCAPE', 'imageCount': 1}}, 'prompt + generationConfig'),

            # Try JSON with @type for protobuf Any
            ({'@type': 'type.googleapis.com/flowMedia.BatchGenerateImagesRequest', 'prompt': 'test'}, '@type annotated'),

            # Maybe the field is 'content' (like Gemini API)
            ({'contents': [{'parts': [{'text': 'test'}]}], 'generationConfig': {'model': API_MODEL}}, 'Gemini-style contents'),
        ]

        for body, desc in tests:
            await probe(page, bearer, token, body, desc)

        # Also try alternative API paths
        print('\n--- Alternative API paths ---')
        alt_paths = [
            f'/v1/projects/{PROJECT_ID}:batchGenerateImages',
            f'/v1/projects/{PROJECT_ID}/flow:generateImages',
            f'/v1/projects/{PROJECT_ID}/flow:batchGenerateImages',
            f'/v1/projects/{PROJECT_ID}/media:generate',
        ]
        for path in alt_paths:
            api_url2 = f'{API_HOST}{path}'
            resp = await page.context.request.post(api_url2,
                headers={'Authorization': f'Bearer {bearer}', 'X-Recaptcha-Token': token, 'Content-Type': 'application/json'},
                data=json.dumps({'prompt': 'test', 'imageModelName': API_MODEL, 'imageCount': 1}))
            t = await resp.text()
            print(f'  {path}: {resp.status} {t[:200]}')

asyncio.run(main())
