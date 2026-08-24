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

// JPEG 1x1 that. Truoc day cho ay dung Buffer.from('fake-jpeg') — sau khi
// saveImage soi magic bytes thi chuoi do bi tu choi dung nhu mot trang HTML,
// nen fixture phai la anh that moi con kiem duoc dung thu can kiem.
const JPEG_1X1 = Buffer.from(
  '/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof'
  + 'Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB'
  + 'AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==',
  'base64',
);

async function withImageServer(run) {
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'image/jpeg' });
    res.end(JPEG_1X1);
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
        // Zalo that luon tra msgId; hen tu thu hoi dua vao no.
        return { message: { msgId: `msg-${calls.length}` }, attachment: [] };
      },
      undo: async () => ({ status: 0 }),
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
      // ttl van duoc chuyen xuong zca-js (vo hai, phong khi Zalo bat lai),
      // nhung thu THUC SU lam tin bien mat la hen tu thu hoi.
      assert.equal(res.body.messageTtl.requested, 3_600_000);
      assert.equal(res.body.messageTtl.applied, true);
      assert.equal(res.body.messageTtl.scope, 'auto-undo');
      assert.equal(calls.at(-1).content.ttl, 3_600_000);
      assert.equal(calls.at(-1).threadId, '2036121378794772276');
      assert.equal(calls.at(-1).type, expectedType);
    }
  });
});

test('album HACS vuot ngan sach request tra 413 truoc khi tai anh', async () => {
  process.env.IMAGE_BATCH_MAX_ITEMS = '1';
  try {
    const res = fakeResponse();
    await sendImagesToUserByAccount({ body: {
      imagePaths: ['https://example.invalid/one.jpg', 'https://example.invalid/two.jpg'],
      threadId: '2036121378794772276',
      accountSelection: 'account-test',
    } }, res);
    assert.equal(res.statusCode, 413);
    assert.match(res.body.error, /qua nhieu anh/i);
  } finally {
    delete process.env.IMAGE_BATCH_MAX_ITEMS;
  }
});

test.after(() => {
  zaloAccounts.length = 0;
  fs.rmSync(directory, { recursive: true, force: true });
});

// Hoi quy cho su co 24/08/2026: add-on tai chinh trang admin-login cua no ve
// duoi ten .jpg roi day len Zalo nhu mot tam anh. Tin di tron lot, khong loi
// nao o dau, va nguoi nhan thay mot o den 1280x720. saveImage phai chan tu day.
test('trang HTML tra ve kem ma 200 khong duoc coi la anh', async () => {
  const { saveImage } = await import('../utils/helpers.js');
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<!DOCTYPE html><html><body>Admin Login</body></html>');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const url = `http://127.0.0.1:${server.address().port}/anh.jpg`;

    assert.equal(await saveImage(url), null);

    await assert.rejects(
      () => saveImage(url, undefined, { throwOnError: true }),
      /khong tra ve anh/i,
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

// Hoi quy cho su co 24/08/2026: automation Home Assistant gui anh camera bang
// URL /api/image_proxy/image.cua_nha_last_motion_image. path.extname() cua
// duong dan do ra ".cua_nha_last_motion_image", nen downloadToTemp tuong tep da
// co duoi va bo qua Content-Type image/jpeg; zca-js phan loai dinh kem bang duoi
// ten nen anh len Zalo duoi dang share.file (fileExt "cua_nha_last_motion_image")
// chu khong phai anh. Cung anh do Telegram nhan dung vi Telegram soi noi dung.
test('URL kieu image_proxy cua Home Assistant van ra tep .jpg', async () => {
  const { saveImage, removeImage } = await import('../utils/helpers.js');
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'image/jpeg' });
    res.end(JPEG_1X1);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const goc = `http://127.0.0.1:${server.address().port}`;

    const duongDan = await saveImage(
      `${goc}/api/image_proxy/image.cua_nha_last_motion_image?token=abc`,
    );
    try {
      assert.equal(path.extname(duongDan), '.jpg');
      assert.equal(fs.readFileSync(duongDan).length, JPEG_1X1.length);
    } finally {
      removeImage(duongDan);
    }

    // Duoi da dung thi khong doi ten — tranh de ra "anh.jpeg.jpg".
    const giuNguyen = await saveImage(`${goc}/anh.jpeg`);
    try {
      assert.equal(path.extname(giuNguyen), '.jpeg');
    } finally {
      removeImage(giuNguyen);
    }
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
