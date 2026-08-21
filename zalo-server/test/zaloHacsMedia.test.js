import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-hacs-media-'));
process.env.DATA_DIRECTORY = directory;

const {
  sendImageToGroupByAccount,
  sendImageToUserByAccount,
  sendImagesToGroupByAccount,
  sendImagesToUserByAccount,
  zaloAccounts,
} = await import('../api/zalo/zalo.js');

function fakeResponse() {
  return {
    statusCode: 200,
    body: null,
    status(code) { this.statusCode = code; return this; },
    json(body) { this.body = body; return this; },
  };
}

async function withImageServer(run) {
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'image/jpeg' });
    res.end(Buffer.from('fake-jpeg'));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const address = server.address();
    await run(`http://127.0.0.1:${address.port}/anh.jpg`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test('bon action anh HACS deu giu TTL va dung thread type', async () => {
  const calls = [];
  zaloAccounts.push({
    ownId: 'account-test',
    phoneNumber: '0900000000',
    api: {
      getContext: () => ({
        settings: { features: { sharefile: { max_file: 6 } } },
      }),
      sendMessage: async (content, threadId, type) => {
        calls.push({ content, threadId, type });
        return { ok: true };
      },
    },
  });

  await withImageServer(async (imageUrl) => {
    const cases = [
      [sendImageToUserByAccount, { imagePath: imageUrl }, 0],
      [sendImagesToUserByAccount, { imagePaths: [imageUrl] }, 0],
      [sendImageToGroupByAccount, { imagePath: imageUrl }, 1],
      [sendImagesToGroupByAccount, { imagePaths: [imageUrl] }, 1],
    ];
    for (const [handler, media, expectedType] of cases) {
      const req = {
        body: {
          ...media,
          threadId: '2036121378794772276',
          accountSelection: 'account-test',
          ttl: '1h',
          nghiMs: 1,
        },
      };
      const res = fakeResponse();
      await handler(req, res);
      assert.equal(res.statusCode, 200);
      assert.equal(res.body.messageTtl.ttl, 3_600_000);
      assert.equal(calls.at(-1).content.ttl, 3_600_000);
      assert.equal(calls.at(-1).threadId, '2036121378794772276');
      assert.equal(calls.at(-1).type, expectedType);
    }
  });
});

test.after(() => {
  zaloAccounts.length = 0;
  fs.rmSync(directory, { recursive: true, force: true });
});
