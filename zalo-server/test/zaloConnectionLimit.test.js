import assert from 'node:assert/strict';
import test from 'node:test';

import { createConnectionLimit } from '../services/connectionLimit.js';

test('reservation chan upgrade dong thoi vuot gioi han WebSocket', () => {
  let active = 0;
  const limit = createConnectionLimit(2, () => active);
  assert.equal(limit.tryReserve(), true);
  assert.equal(limit.tryReserve(), true);
  assert.equal(limit.tryReserve(), false);
  active += 1;
  limit.confirm();
  active += 1;
  limit.confirm();
  assert.equal(limit.pending(), 0);
  assert.equal(limit.tryReserve(), false);
  active -= 1;
  assert.equal(limit.tryReserve(), true);
});
