import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-http-'));
process.chdir(directory);
process.env.DATA_DIRECTORY = directory;
process.env.PUBLIC_DIR = path.join(directory, 'public');
process.env.ZALO_SERVER_ADMIN_PASSWORD = 'mat-khau-test-rat-dai';
process.env.JSON_BODY_LIMIT = '2mb';

const { default: app } = await import('../app.js');

async function withApp(run) {
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const address = server.address();
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test('health endpoint nhe, public va co security headers', async () => {
  await withApp(async (base) => {
    const response = await fetch(`${base}/api/health`);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('x-powered-by'), null);
    assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
    assert.equal(response.headers.get('cache-control'), 'no-store');
    const body = await response.json();
    assert.equal(body.status, 'ok');
  });
});

test('JSON body vuot 2 MiB bi chan truoc route', async () => {
  await withApp(async (base) => {
    const response = await fetch(`${base}/api/sendMessageByAccount`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message: 'x'.repeat(2 * 1024 * 1024 + 1) }),
    });
    assert.equal(response.status, 413);
    assert.match(response.headers.get('content-type') || '', /application\/json/);
    assert.equal((await response.json()).code, 'PAYLOAD_TOO_LARGE');
  });
});

test.after(() => fs.rmSync(directory, { recursive: true, force: true }));
