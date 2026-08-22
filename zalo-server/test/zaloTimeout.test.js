import assert from 'node:assert/strict';
import test from 'node:test';

import {
  OperationTimeoutError,
  cleanupAfterSettled,
  withTimeout,
} from '../utils/timeout.js';

test('timeout bao loi ma van cho phep cleanup sau khi tac vu nen ket thuc', async () => {
  let release;
  let cleaned = false;
  const task = new Promise((resolve) => { release = resolve; });
  await assert.rejects(
    withTimeout(task, 1, 'upload timeout'),
    OperationTimeoutError,
  );
  cleanupAfterSettled(task, () => { cleaned = true; });
  assert.equal(cleaned, false);
  release();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(cleaned, true);
});
