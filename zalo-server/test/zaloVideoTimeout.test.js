import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-video-timeout-'));
process.env.DATA_DIRECTORY = directory;
process.env.VIDEO_UPLOAD_TIMEOUT_MS = '1';

const { sendVideoByAccount, zaloAccounts } = await import('../api/zalo/zalo.js');

function response() {
  return {
    statusCode: 200,
    body: null,
    status(code) { this.statusCode = code; return this; },
    json(body) { this.body = body; return this; },
  };
}

test('video timeout giu tep tam den khi upload nen ket thuc', async () => {
  let resolveUpload;
  let uploadedPath = '';
  zaloAccounts.push({
    ownId: 'video-account', phoneNumber: '0900000001',
    api: {
      uploadAttachment: ([file]) => {
        uploadedPath = file;
        return new Promise((resolve) => { resolveUpload = resolve; });
      },
    },
  });
  const server = http.createServer((_req, res) => res.end('video'));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const { port } = server.address();
    const res = response();
    await sendVideoByAccount({ body: {
      options: { videoUrl: `http://127.0.0.1:${port}/clip.mp4` },
      threadId: 'thread', type: 'user', accountSelection: 'video-account',
    } }, res);
    assert.equal(res.statusCode, 504);
    assert.equal(fs.existsSync(uploadedPath), true);
    resolveUpload([{ fileUrl: 'https://zalo.example/video' }]);
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(fs.existsSync(uploadedPath), false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    zaloAccounts.length = 0;
  }
});

test.after(() => {
  delete process.env.VIDEO_UPLOAD_TIMEOUT_MS;
  fs.rmSync(directory, { recursive: true, force: true });
});
