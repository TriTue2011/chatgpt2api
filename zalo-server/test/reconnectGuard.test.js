import assert from 'node:assert/strict';
import test from 'node:test';

import {
  beginReconnectAttempt,
  invalidateReconnectAttempt,
} from '../services/reconnectGuard.js';

test('reconnect timeout lam lan login cu mat quyen commit khi retry bat dau', () => {
  const ownId = '123';
  const states = new Map();
  const state = { generation: 0 };
  states.set(ownId, state);

  const firstIsCurrent = beginReconnectAttempt(states, ownId, state);
  assert.equal(firstIsCurrent(), true);

  invalidateReconnectAttempt(state); // timeout cua lan thu nhat
  const retryIsCurrent = beginReconnectAttempt(states, ownId, state);
  assert.equal(firstIsCurrent(), false);
  assert.equal(retryIsCurrent(), true);
});
