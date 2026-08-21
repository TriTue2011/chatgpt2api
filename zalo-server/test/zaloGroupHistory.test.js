import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-history-'));
process.env.DATA_DIRECTORY = directory;

const {
  getCachedGroupHistory,
  storeGroupMessage,
} = await import('../utils/groupHistoryStore.js');

test('group chua co cache tra lich su rong thay vi loi ENOENT', () => {
  const result = getCachedGroupHistory('account-empty', 'group-empty', 50);
  assert.deepEqual(result.groupMsgs, []);
  assert.equal(result.cachedCount, 0);
});

test('group history song qua restart format va loai message trung', () => {
  const message = {
    threadId: '2036121378794772276',
    type: 1,
    data: {
      msgId: '6683680861034270202',
      uidFrom: '475796162066271393',
      content: 'xin chao',
      ts: '1787284800000',
    },
  };

  assert.equal(storeGroupMessage('1234567890123456789', message), true);
  assert.equal(storeGroupMessage('1234567890123456789', message), true);
  const result = getCachedGroupHistory(
    '1234567890123456789', '2036121378794772276', 50,
  );

  assert.equal(result.source, 'local_persistent_cache');
  assert.equal(result.groupMsgs.length, 1);
  assert.equal(result.groupMsgs[0].threadId, '2036121378794772276');
});

test('group history ton trong gioi han so message khi doc cache', () => {
  process.env.GROUP_HISTORY_MAX_MESSAGES = '2';
  for (let index = 1; index <= 3; index += 1) {
    storeGroupMessage('account-cap', {
      threadId: 'group-cap',
      type: 1,
      data: { msgId: String(index), uidFrom: 'sender', content: String(index) },
    });
  }
  const result = getCachedGroupHistory('account-cap', 'group-cap', 50);
  assert.deepEqual(result.groupMsgs.map((message) => message.data.msgId), ['2', '3']);
  assert.equal(result.cachedCount, 2);
  delete process.env.GROUP_HISTORY_MAX_MESSAGES;
});

test('group history cat theo ca byte budget, uu tien message moi nhat', () => {
  process.env.GROUP_HISTORY_MAX_MESSAGES = '100';
  process.env.GROUP_HISTORY_MAX_FILE_BYTES = '650';
  for (let index = 1; index <= 6; index += 1) {
    storeGroupMessage('account-bytes', {
      threadId: 'group-bytes',
      type: 1,
      data: {
        msgId: String(index),
        uidFrom: 'sender',
        content: `${index}-${'x'.repeat(100)}`,
      },
    });
  }
  const result = getCachedGroupHistory('account-bytes', 'group-bytes', 50);
  const file = path.join(directory, 'history', 'groups', 'account-bytes', 'group-bytes.jsonl');
  assert.ok(fs.statSync(file).size <= 650);
  assert.equal(result.groupMsgs.at(-1)?.data.msgId, '6');
  delete process.env.GROUP_HISTORY_MAX_MESSAGES;
  delete process.env.GROUP_HISTORY_MAX_FILE_BYTES;
});

test('queue history dang cho duoc gioi han va bo record cu nhat', () => {
  process.env.GROUP_HISTORY_PENDING_MAX = '2';
  for (let index = 1; index <= 3; index += 1) {
    storeGroupMessage('account-queue', {
      threadId: 'group-queue',
      type: 1,
      data: { msgId: String(index), uidFrom: 'sender', content: String(index) },
    });
  }
  const result = getCachedGroupHistory('account-queue', 'group-queue', 50);
  assert.deepEqual(result.groupMsgs.map((message) => message.data.msgId), ['2', '3']);
  delete process.env.GROUP_HISTORY_PENDING_MAX;
});

test.after(() => fs.rmSync(directory, { recursive: true, force: true }));
