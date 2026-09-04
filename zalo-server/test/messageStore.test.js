// Kho tin 1-1: lưu CẢ HAI CHIỀU và tra lại được theo msgId.
//
// Vì sao bộ test này tồn tại: Zalo GỌT nội dung tin trích. Tin dài (bản tin
// đánh mã A1..E5) chỉ được Zalo kèm một đoạn xem trước ở `quote.msg`, nên mã
// nằm cuối bản tin không chọn lại được. Đường chữa là tra ngược tin GỐC theo
// `quote.globalMsgId` — chỉ chạy được nếu tin gốc THẬT SỰ nằm trong kho.
//
// Bẫy đã có thật: khối lưu trong eventListeners.js từng chặn `!msg.isSelf`, tức
// chỉ lưu tin NHẬN, trong khi chú thích ngay trên nó ghi "cả tin nhận lẫn tin
// tự gửi". Bản tin do BOT gửi (nơi mã mục sống) vì thế không bao giờ vào kho.
// Test `tin bot tu gui cung phai luu duoc` khoá đúng chỗ đó.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-msgstore-'));
process.env.DATA_DIRECTORY = directory;

const {
  saveMessage,
  loadMessages,
  getMessageById,
} = await import('../services/messageStore.js');

const OWN = 'own-1';
const THREAD = 'thread-1';

test('tra duoc tin da luu theo msgId', () => {
  saveMessage(OWN, THREAD, {
    id: '111', from: 'u1', name: 'Ai do', content: 'xin chao', ts: 1, isSelf: false,
  });
  const found = getMessageById(OWN, THREAD, '111');
  assert.equal(found?.content, 'xin chao');
});

test('tin bot tu gui cung phai luu duoc va tra duoc', () => {
  // Đây là ca quan trọng nhất: bản tin đánh mã do BOT gửi.
  const banTin = 'A. The thao\nA1. Tin mot\nD1. Cong ty ban dan\n(Muon xem ky muc nao...)';
  saveMessage(OWN, THREAD, {
    id: '222', from: OWN, name: 'bot', content: banTin, ts: 2, isSelf: true,
  });
  const found = getMessageById(OWN, THREAD, '222');
  assert.equal(found?.isSelf, true);
  assert.match(found?.content ?? '', /D1\. Cong ty ban dan/);
});

test('so khop khong phan biet kieu so hay chuoi', () => {
  // `quote.globalMsgId` của zca-js là NUMBER, còn `msgId` lúc lưu là STRING.
  saveMessage(OWN, THREAD, {
    id: '333', from: 'u1', name: 'Ai do', content: 'tin ba', ts: 3, isSelf: false,
  });
  assert.equal(getMessageById(OWN, THREAD, 333)?.content, 'tin ba');
});

test('id khong co thi tra null, khong nem loi', () => {
  assert.equal(getMessageById(OWN, THREAD, '999999'), null);
  assert.equal(getMessageById(OWN, THREAD, ''), null);
  assert.equal(getMessageById(OWN, 'thread-chua-ton-tai', '111'), null);
});

test('tin trung id khong bi luu hai lan', () => {
  const truoc = loadMessages(OWN, THREAD).length;
  saveMessage(OWN, THREAD, {
    id: '111', from: 'u1', name: 'Ai do', content: 'ban sao', ts: 9, isSelf: false,
  });
  assert.equal(loadMessages(OWN, THREAD).length, truoc);
  // Bản đầu phải được giữ, không bị bản sau đè.
  assert.equal(getMessageById(OWN, THREAD, '111')?.content, 'xin chao');
});

test('ton trong tran 1000 tin va giu tin MOI nhat', () => {
  const t2 = 'thread-tran';
  for (let i = 0; i < 1010; i++) {
    saveMessage(OWN, t2, {
      id: String(i), from: 'u1', name: 'x', content: 'tin ' + i, ts: i, isSelf: false,
    });
  }
  assert.equal(loadMessages(OWN, t2).length, 1000);
  // Tin cũ nhất đã bị cuốn đi, tin mới nhất còn tra được.
  assert.equal(getMessageById(OWN, t2, '0'), null);
  assert.equal(getMessageById(OWN, t2, '1009')?.content, 'tin 1009');
});
