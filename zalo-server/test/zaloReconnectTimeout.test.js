import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-reconnect-timeout-'));
process.env.DATA_DIRECTORY = directory;
process.env.RECONNECT_LOGIN_TIMEOUT_MS = '1';

const {
  configureReconnectDependencies,
  reloginAttempts,
  setupEventListeners,
} = await import('../eventListeners.js');

test('login reconnect treo bi timeout va lan thu sau van chay', async () => {
  const ownId = 'reconnect-account';
  fs.mkdirSync(path.join(directory, 'cookies'), { recursive: true });
  fs.writeFileSync(
    path.join(directory, 'cookies', `cred_${ownId}.json`),
    JSON.stringify({ imei: 'i', cookie: [], userAgent: 'ua' }),
  );

  let onClosed;
  const sourceApi = {
    getOwnId: () => ownId,
    listener: {
      on() {}, onConnected() {}, onError() {},
      onClosed(callback) { onClosed = callback; },
    },
  };
  const accounts = [{ ownId, api: sourceApi }];
  let loginCalls = 0;
  configureReconnectDependencies({
    accounts,
    login: async () => {
      loginCalls += 1;
      if (loginCalls === 1) return new Promise(() => {});
      return true;
    },
  });
  setupEventListeners(sourceApi, () => {});

  const originalSetTimeout = global.setTimeout;
  global.setTimeout = (callback, delay, ...args) => (
    originalSetTimeout(callback, delay >= 5_000 ? 0 : delay, ...args)
  );
  try {
    onClosed();
    await new Promise((resolve, reject) => {
      const deadline = originalSetTimeout(() => reject(new Error('retry did not run')), 250);
      const check = () => {
        if (loginCalls >= 2) {
          clearTimeout(deadline);
          resolve();
          return;
        }
        originalSetTimeout(check, 2);
      };
      check();
    });
    assert.equal(loginCalls, 2);
    assert.equal(reloginAttempts.has(ownId), false);
  } finally {
    global.setTimeout = originalSetTimeout;
    configureReconnectDependencies({ login: async () => true, accounts: [] });
  }
});

test.after(() => {
  delete process.env.RECONNECT_LOGIN_TIMEOUT_MS;
  fs.rmSync(directory, { recursive: true, force: true });
});
