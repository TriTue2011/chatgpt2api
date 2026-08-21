import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-auth-migration-'));
const target = path.join(root, 'target');
const legacyDir = path.join(root, 'data', 'cookies');
fs.mkdirSync(legacyDir, { recursive: true });
fs.writeFileSync(path.join(legacyDir, 'users.json'), '{json-hong');
process.chdir(root);
process.env.DATA_DIRECTORY = target;
process.env.ZALO_SERVER_ADMIN_PASSWORD = 'mat-khau-khoi-phuc-sau-migration';

const { validateUser } = await import('../services/authService.js');

test('users legacy hong khong chan tao auth database moi', () => {
  assert.equal(
    validateUser('admin', 'mat-khau-khoi-phuc-sau-migration')?.role,
    'admin',
  );
  assert.doesNotThrow(() => JSON.parse(
    fs.readFileSync(path.join(target, 'cookies', 'users.json'), 'utf8'),
  ));
});

test.after(() => fs.rmSync(root, { recursive: true, force: true }));
