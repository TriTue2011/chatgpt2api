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
  sendVideoByAccount,
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

// Header ISO BMFF toi thieu: 4 byte kich thuoc box, 'ftyp', roi major brand.
const MP4_HEADER = Buffer.concat([
  Buffer.from([0x00, 0x00, 0x00, 0x18]), Buffer.from('ftypisom', 'latin1'), Buffer.alloc(32),
]);
const MOV_HEADER = Buffer.concat([
  Buffer.from([0x00, 0x00, 0x00, 0x14]), Buffer.from('ftypqt  ', 'latin1'), Buffer.alloc(32),
]);

// Cung mot co che hong nhu anh, o duong video: zca-js chi cho dinh kem di duong
// video khi duoi ten dung "mp4", moi duoi khac roi vao nhanh "others" va bay len
// endpoint asyncfile — toi noi thanh tep dinh kem chu khong phai doan phim bam
// phat duoc. URL khong noi duoc duoi va Content-Type cung khong thi phai soi noi
// dung. Doi lai: .mov khong duoc doi ten thanh .mp4, do la noi doi.
test('video that duoc dat lai duoi .mp4, con .mov thi de nguyen', async () => {
  const { saveVideoFromUrl, removeFile } = await import('../utils/helpers.js');
  let than = MP4_HEADER;
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'application/octet-stream' });
    res.end(than);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const goc = `http://127.0.0.1:${server.address().port}`;

    const duongMp4 = await saveVideoFromUrl(`${goc}/api/camera_proxy_stream/camera.cua_nha`);
    try {
      assert.equal(path.extname(duongMp4), '.mp4');
      assert.equal(fs.readFileSync(duongMp4).length, MP4_HEADER.length);
    } finally {
      removeFile(duongMp4);
    }

    than = MOV_HEADER;
    const duongMov = await saveVideoFromUrl(`${goc}/phim.mov`);
    try {
      assert.equal(path.extname(duongMov), '.mov');
    } finally {
      removeFile(duongMov);
    }
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

// ffmpeg gia ghi vai byte ra doi so cuoi (duong dan anh bia). Du de
// createVideoThumbnail coi la thanh cong, va may dev khong phai co ffmpeg that.
function ffmpegGia() {
  const duongDan = path.join(directory, 'ffmpeg-gia.sh');
  fs.writeFileSync(duongDan, '#!/bin/sh\nfor a in "$@"; do out="$a"; done\nprintf anh > "$out"\n');
  fs.chmodSync(duongDan, 0o755);
  return duongDan;
}

// Hoi quy cho su co 24/08/2026: tich hop Home Assistant mac dinh lay CHINH dia
// chi video lam anh bia khi automation khong khai thumbnail_url. saveImage soi
// magic bytes, thay MP4 nen vut di — bo trong anh bia thi Zalo tra "Tham so
// khong hop le" va tin khong di, tuc moi lan gui video tu tep cuc bo deu hong.
// Phai tu trich mot khung hinh lam bia.
test('anh bia tro vao chinh tep video thi tu trich khung hinh', async () => {
  const ffmpegCu = process.env.FFMPEG_BIN;
  process.env.FFMPEG_BIN = ffmpegGia();
  const daTaiLen = [];
  const daGui = [];
  zaloAccounts.push({
    ownId: 'tk-video-test',
    phoneNumber: '0900000001',
    api: {
      uploadAttachment: async ([duongDan]) => {
        daTaiLen.push(duongDan);
        return path.extname(duongDan) === '.mp4'
          ? [{ fileType: 'video', fileUrl: 'https://zalo.test/video.mp4' }]
          : [{ fileType: 'image', thumbUrl: 'https://zalo.test/bia.jpg' }];
      },
      sendVideo: async (options, threadId, type) => {
        daGui.push({ options, threadId, type });
        return { msgId: 'm1' };
      },
    },
  });

  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'video/mp4' });
    res.end(MP4_HEADER);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const url = `http://127.0.0.1:${server.address().port}/camhd_1.mp4`;
    const res = fakeResponse();
    await sendVideoByAccount({
      body: {
        options: { videoUrl: url, thumbnailUrl: url },
        threadId: '2749165423519409796',
        type: 1,
        accountSelection: 'tk-video-test',
      },
    }, res);

    assert.equal(res.statusCode, 200);
    assert.equal(res.body.success, true);
    // 'auto' = bia do server tu trich, khong phai bia nguoi goi dua vao.
    assert.equal(res.body.thumbnailSource, 'auto');
    assert.equal(daTaiLen.length, 2);
    assert.match(path.basename(daTaiLen[1]), /video-thumb\.jpg$/);
    assert.equal(daGui.length, 1);
    assert.equal(daGui[0].options.videoUrl, 'https://zalo.test/video.mp4');
    assert.equal(daGui[0].options.thumbnailUrl, 'https://zalo.test/bia.jpg');
  } finally {
    await new Promise((resolve) => server.close(resolve));
    if (ffmpegCu === undefined) delete process.env.FFMPEG_BIN;
    else process.env.FFMPEG_BIN = ffmpegCu;
  }
});
