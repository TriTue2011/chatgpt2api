import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { taiVeVaGuiNhieuAnh } from '../utils/sendImages.js';

test('album vuot tran so anh bi chan truoc khi tai bat ky tep nao', async () => {
  process.env.IMAGE_BATCH_MAX_ITEMS = '1';
  let downloaded = 0;
  try {
    await assert.rejects(
      taiVeVaGuiNhieuAnh(
        { saveImage: async () => { downloaded += 1; return 'not-downloaded.jpg'; }, removeImage() {} },
        {}, ['one.jpg', 'two.jpg'], 'thread', 0,
      ),
      /qua nhieu anh/i,
    );
    assert.equal(downloaded, 0);
  } finally {
    delete process.env.IMAGE_BATCH_MAX_ITEMS;
  }
});

test('album vuot tran tong dung luong duoc don tep tam da tai', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-image-budget-'));
  const image = path.join(directory, 'one.jpg');
  fs.writeFileSync(image, 'xx');
  process.env.IMAGE_BATCH_MAX_BYTES = '1';
  const removed = [];
  try {
    await assert.rejects(
      taiVeVaGuiNhieuAnh(
        { saveImage: async () => image, removeImage: (value) => removed.push(value) },
        {}, ['one.jpg'], 'thread', 0,
      ),
      /Tong dung luong anh/i,
    );
    assert.deepEqual(removed, [image]);
  } finally {
    delete process.env.IMAGE_BATCH_MAX_BYTES;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
