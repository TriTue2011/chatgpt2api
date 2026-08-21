import assert from 'node:assert/strict';
import test from 'node:test';

import {
  enrichMessageEvent,
  filterReceivedFriendRequests,
  normalizeAutoDeleteTtl,
  normalizeMessageTtl,
  normalizeThreadType,
  normalizeZaloIdsInPlace,
} from '../utils/zaloContract.js';

test('Zalo ID lon duoc giu dang chuoi va ho tro prefix template-safe', () => {
  const body = {
    threadId: 'zalo:2036121378794772276',
    nested: { userId: 12345 },
    memberIds: ['zalo:6683680861034270202', 42],
  };

  normalizeZaloIdsInPlace(body);

  assert.equal(body.threadId, '2036121378794772276');
  assert.equal(body.nested.userId, '12345');
  assert.deepEqual(body.memberIds, ['6683680861034270202', '42']);
});

test('Zalo ID da mat do chinh xac trong JSON number bi tu choi som', () => {
  assert.throws(
    () => normalizeZaloIdsInPlace({ threadId: 2036121378794772276 }),
    /chuoi JSON/,
  );
});

test('TTL tin nhan tach biet voi Auto Delete cua cuoc tro chuyen', () => {
  assert.equal(normalizeMessageTtl('6h'), 6 * 60 * 60 * 1000);
  assert.equal(normalizeMessageTtl('off'), 0);
  assert.equal(normalizeAutoDeleteTtl('7d'), 7 * 24 * 60 * 60 * 1000);
  assert.equal(normalizeAutoDeleteTtl(0), 0);
  assert.throws(() => normalizeAutoDeleteTtl('6h'), /Auto Delete/);
});

test('type chap nhan ca schema HACS va zca-js', () => {
  assert.equal(normalizeThreadType('user'), 0);
  assert.equal(normalizeThreadType('group'), 1);
  assert.equal(normalizeThreadType('0'), 0);
  assert.equal(normalizeThreadType(1), 1);
  assert.throws(() => normalizeThreadType('channel'), /type khong hop le/);
});

test('webhook them thread ref ma khong bien Zalo ID thanh number', () => {
  const enriched = enrichMessageEvent({
    threadId: '2036121378794772276',
    type: 1,
    data: { uidFrom: '6683680861034270202' },
  }, '475796162066271393');

  assert.equal(enriched.threadId, '2036121378794772276');
  assert.equal(enriched._threadRef, 'zalo:2036121378794772276');
  assert.equal(enriched._threadType, 1);
  assert.equal(enriched._accountId, '475796162066271393');
});

test('action HACS received friend requests chi giu recommType 2', () => {
  const filtered = filterReceivedFriendRequests({
    recommItems: [
      { uid: '1', dataInfo: { recommType: 2 } },
      { uid: '2', recommType: '2' },
      { uid: '3', dataInfo: { recommType: 1 } },
    ],
  });
  assert.deepEqual(filtered.recommItems.map((item) => item.uid), ['1', '2']);
  assert.equal(filtered.total, 2);
});
