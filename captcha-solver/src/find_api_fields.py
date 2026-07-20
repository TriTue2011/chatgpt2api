import asyncio, sys, json, re
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
        try:
            await page.wait_for_function(
                '() => { const ces = Array.from(document.querySelectorAll("[contenteditable=true]")); return ces.some(e => e.offsetWidth > 200); }',
                timeout=30_000)
        except Exception:
            pass

        await asyncio.sleep(2)

        # Search all inline scripts and external script content for API patterns
        result = await page.evaluate("""async () => {
            const findings = [];

            // 1. Search inline scripts
            const inlineScripts = document.querySelectorAll('script:not([src])');
            for (const s of inlineScripts) {
                if (s.textContent && s.textContent.includes('batchGenerateImages')) {
                    findings.push({source: 'inline', content: s.textContent.substring(0, 5000)});
                }
            }

            // 2. Fetch and search external JS bundles
            const scripts = document.querySelectorAll('script[src]');
            const jsUrls = Array.from(scripts)
                .map(s => s.src)
                .filter(src => src.includes('flow') || src.includes('main') || src.includes('chunk') || src.includes('bundle') || src.includes('app'));

            for (const srcUrl of jsUrls.slice(0, 20)) {
                try {
                    const resp = await fetch(srcUrl);
                    const text = await resp.text();
                    if (text.includes('batchGenerateImages')) {
                        // Find all occurrences and extract context
                        const lines = text.split('\\n');
                        for (let i = 0; i < lines.length; i++) {
                            if (lines[i].includes('batchGenerateImages')) {
                                const start = Math.max(0, i - 5);
                                const end = Math.min(lines.length, i + 10);
                                findings.push({
                                    source: srcUrl.substring(0, 100),
                                    context: lines.slice(start, end).join('\\n')
                                });
                            }
                        }
                    }
                } catch(e) {
                    // CORS may block, skip
                }
            }

            // 3. Search webpack chunks in memory
            const allScripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
            return {findings, scriptCount: allScripts.length, jsUrls: jsUrls.slice(0, 15)};
        }""")

        print(f"Scripts found: {result.get('scriptCount', 0)}")
        print(f"JS URLs checked: {json.dumps(result.get('jsUrls', []), indent=2)}")
        print(f"\nFindings: {len(result.get('findings', []))}")
        for f in result.get('findings', []):
            print(f"\n=== Source: {f['source']} ===")
            print(f['context'][:3000])

asyncio.run(main())
