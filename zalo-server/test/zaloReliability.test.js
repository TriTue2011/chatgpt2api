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

// Hoi quy cho su co 24/08/2026, nhanh thu hai: path.extname() goi MOI THU sau
// dau cham cuoi la phan mo rong, ke ca mot manh ten thuc the dai ngoang. URL
// media cua Home Assistant (/api/image_proxy/image.cua_nha_last_motion_image,
// /api/camera_proxy_stream/camera.cua_nha) vi the "co duoi" roi nhay qua nhanh
// doc Content-Type. Zalo phan loai dinh kem bang duoi ten nen anh thanh tep va
// video thanh tep. Chi tin duoi nao TRONG NHU duoi that.
test('duoi troi oi trong URL bi thay bang duoi theo Content-Type', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-download-'));
  await withServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'video/mp4' });
    res.end(Buffer.alloc(64));
  }, async (base) => {
    const duongDan = await downloadToTemp(
      `${base}/api/camera_proxy_stream/camera.cua_nha`,
      { tempDir: dir, maxBytes: 4096 },
    );
    assert.equal(path.extname(duongDan), '.mp4');
  });
  fs.rmSync(dir, { recursive: true, force: true });
});

test('duoi that trong URL duoc giu nguyen', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-download-'));
  await withServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'video/mp4' });
    res.end(Buffer.alloc(64));
  }, async (base) => {
    const duongDan = await downloadToTemp(`${base}/phim.mkv`, { tempDir: dir, maxBytes: 4096 });
    assert.equal(path.extname(duongDan), '.mkv');
  });
  fs.rmSync(dir, { recursive: true, force: true });
});

// Content-Disposition la ten may chu TU KHAI, khong phai ten minh doan tu URL —
// suy doan cua minh khong duoc de len tren loi khai cua no.
test('ten trong Content-Disposition duoc giu nguyen du duoi la gi', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-download-'));
  await withServer((_req, res) => {
    res.writeHead(200, {
      'content-type': 'application/octet-stream',
      'content-disposition': 'attachment; filename="ban_sao_luu.thang_tam_2026"',
    });
    res.end(Buffer.alloc(64));
  }, async (base) => {
    const duongDan = await downloadToTemp(`${base}/tai-ve`, { tempDir: dir, maxBytes: 4096 });
    assert.ok(duongDan.endsWith('ban_sao_luu.thang_tam_2026'), duongDan);
  });
  fs.rmSync(dir, { recursive: true, force: true });
});

// Duoi troi oi ma Content-Type cung khong noi duoc la gi thi de nguyen ten goc:
// dap them ".bin" chi lam ten nguoi nhan thay xau di ma chang mo duoc hon.
test('khong ro Content-Type thi duoi la thi giu nguyen, khong dap .bin', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-download-'));
  await withServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'application/octet-stream' });
    res.end(Buffer.alloc(64));
  }, async (base) => {
    const laDuoi = await downloadToTemp(`${base}/ban_sao_luu.thang_tam_2026`, {
      tempDir: dir, maxBytes: 4096,
    });
    assert.ok(laDuoi.endsWith('ban_sao_luu.thang_tam_2026'), laDuoi);

    // Con khong co duoi nao ca thi van phai dat mot cai — hanh vi cu, giu nguyen.
    const khongDuoi = await downloadToTemp(`${base}/tai-ve`, { tempDir: dir, maxBytes: 4096 });
    assert.equal(path.extname(khongDuoi), '.bin');
  });
  fs.rmSync(dir, { recursive: true, force: true });
});
