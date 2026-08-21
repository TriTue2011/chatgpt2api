import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { writeJsonAtomicSync } from '../utils/atomicFile.js';
import { downloadToTemp } from '../utils/download.js';
import { createVideoThumbnail } from '../utils/videoThumbnail.js';
import { reconnectDelay } from '../services/reconnectPolicy.js';

test('ghi JSON thay the atomic va khong de lai file tam', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-atomic-'));
  const file = path.join(dir, 'state.json');
  fs.writeFileSync(file, '{"old":true}\n');

  writeJsonAtomicSync(file, { id: '2036121378794772276', ok: true });

  assert.deepEqual(JSON.parse(fs.readFileSync(file, 'utf8')), {
    id: '2036121378794772276', ok: true,
  });
  assert.deepEqual(fs.readdirSync(dir), ['state.json']);
  fs.rmSync(dir, { recursive: true, force: true });
});

async function withServer(handler, run) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const address = server.address();
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test('download chan Content-Length vuot tran truoc khi ghi dia', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-download-'));
  await withServer((_req, res) => {
    res.writeHead(200, { 'content-length': '4096' });
    res.end(Buffer.alloc(4096));
  }, async (base) => {
    await assert.rejects(
      downloadToTemp(`${base}/large.bin`, { tempDir: dir, maxBytes: 1024 }),
      /vuot qua gioi han/,
    );
  });
  assert.deepEqual(fs.readdirSync(dir), []);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('download chunked vuot tran cung don tep dang do', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-download-'));
  await withServer((_req, res) => {
    res.writeHead(200);
    res.write(Buffer.alloc(800));
    res.end(Buffer.alloc(800));
  }, async (base) => {
    await assert.rejects(
      downloadToTemp(`${base}/chunked.bin`, { tempDir: dir, maxBytes: 1024 }),
      /vuot qua gioi han/,
    );
  });
  assert.deepEqual(fs.readdirSync(dir), []);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('thumbnail video duoc tao bat dong bo va xac minh tep dau ra', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-video-'));
  const video = path.join(dir, 'clip.mp4');
  fs.writeFileSync(video, Buffer.from('fake-video'));
  const calls = [];

  const thumbnail = await createVideoThumbnail(video, {
    tempDir: dir,
    execFileAsync: async (_binary, args) => {
      calls.push(args);
      fs.writeFileSync(args.at(-1), Buffer.from('jpeg'));
    },
  });

  assert.equal(calls.length, 1);
  assert.match(path.basename(thumbnail), /video-thumb\.jpg$/);
  assert.equal(fs.statSync(thumbnail).size, 4);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('reconnect tang backoff va dung o 5 phut', () => {
  assert.deepEqual(
    Array.from({ length: 8 }, (_, attempt) => reconnectDelay(attempt)),
    [5000, 15000, 30000, 60000, 120000, 300000, 300000, 300000],
  );
});
