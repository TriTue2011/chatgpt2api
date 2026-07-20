import asyncio, sys, json
sys.path.insert(0, '/app')
from src.solvers.flow_google import _prime_flow_session
from src.browser_pool import pool

async def main():
    async with pool.page(profile='google-fx', headless=False) as page:
        await _prime_flow_session(page)
        url = 'https://labs.google/fx/vi/tools/flow/project/62e0f686-7172-4ef5-8535-24bd02866f5b'
        await page.goto(url, wait_until='domcontentloaded', timeout=30_000)
        await asyncio.sleep(3)

        cdp = await page.context.new_cdp_session(page)
        await cdp.send('Page.setBypassCSP', {'enabled': True})
        print('CDP CSP bypass sent')

        js = """
        (async () => {
            const results = {};
            try {
                const r = await fetch("https://httpbin.org/get");
                results.httpbin = {ok: r.ok, status: r.status};
            } catch(e) { results.httpbin = {err: e.message}; }
            try {
                const r = await fetch("https://aisandbox-pa.googleapis.com/");
                results.aisandbox = {ok: r.ok, status: r.status};
            } catch(e) { results.aisandbox = {err: e.message}; }
            try {
                const r = await fetch("https://aisandbox-pa.googleapis.com/v1/projects/test/flowMedia:batchGenerateImages", {
                    method: "POST",
                    headers: {
                        "Authorization": "Bearer test",
                        "Content-Type": "application/json"
                    },
                    body: "{}"
                });
                results.aisandbox_post = {ok: r.ok, status: r.status};
            } catch(e) { results.aisandbox_post = {err: e.message}; }
            return results;
        })()
        """
        r = await page.evaluate(js)
        print(json.dumps(r, indent=2))

asyncio.run(main())
