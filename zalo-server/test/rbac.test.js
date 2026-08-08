/**
 * RBAC của zalo-server: phạm vi API key và cổng vai admin.
 *
 * Hai lỗ (báo cáo bảo mật 08/08):
 * 1. API key tích hợp (ZALO_SERVER_API_KEY, cấp cho Home Assistant) đi qua
 *    middleware CHUNG nên mở được cả dashboard, lịch sử chat và trang quản lý
 *    người dùng — rộng hơn mục đích rất nhiều.
 * 2. Route UI/chat chỉ kiểm "đã đăng nhập", không kiểm vai. Tài khoản vai
 *    'user' đọc được toàn bộ hội thoại của mọi tài khoản Zalo và gửi tin thay
 *    chúng — quyền ngang admin.
 *
 * Chạy: cd zalo-server && node --test test/
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

// authService tự tạo data/cookies/users.json ngay lúc NẠP module, theo
// process.cwd(). Đổi cwd sang thư mục tạm TRƯỚC khi import để test không ghi
// vào repo (đường dẫn ESM tính theo URL của file, không theo cwd → vẫn import
// đúng module).
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'zalo-rbac-'));
process.chdir(tmp);
process.env.DATA_DIRECTORY = tmp;
process.env.ZALO_SERVER_API_KEY = 'khoa-tich-hop-cua-home-assistant';

const { authMiddleware, dashboardRoleMiddleware, isApiKeyRoute } =
  await import('../services/authService.js');

/** Giả res của Express, ghi lại kết quả thay vì gửi đi. */
function fakeRes() {
  const res = { statusCode: 0, body: null, redirectedTo: null };
  res.status = (c) => { res.statusCode = c; return res; };
  res.json = (b) => { res.body = b; return res; };
  res.send = (b) => { res.body = b; return res; };
  res.redirect = (u) => { res.redirectedTo = u; return res; };
  return res;
}

function reqVoiApiKey(pathname) {
  return {
    path: pathname,
    headers: { authorization: 'Bearer khoa-tich-hop-cua-home-assistant', accept: 'application/json' },
    query: {},
    session: null,
  };
}

function reqVoiPhien(pathname, role) {
  return {
    path: pathname,
    headers: { accept: 'application/json' },
    query: {},
    session: { authenticated: true, role, username: 'ai-do' },
  };
}

/** Chạy đúng chuỗi middleware mà app.js dùng cho route được bảo vệ. */
function chay(req) {
  const res = fakeRes();
  let daQua = false;
  authMiddleware(req, res, () =>
    dashboardRoleMiddleware(req, res, () => { daQua = true; })
  );
  return { res, daQua };
}

test('API key gửi được mọi loại nội dung, gồm cả biến thể ByAccount', () => {
  // Biến thể ByAccount là thứ docs/ZALO_ANH_VA_HOME_ASSISTANT.md hướng dẫn dùng
  // để gửi album. Khớp theo tiền tố `/api/sendImagesToUser` KHÔNG bắt được tên
  // `/api/sendImagesToUserByAccount`, nên phải liệt kê đủ tên — test này chốt lại.
  for (const p of ['/api/sendmessage', '/api/sendMessageByAccount',
                   '/api/sendImageToUser', '/api/sendImageToUserByAccount',
                   '/api/sendImageToGroup', '/api/sendImageToGroupByAccount',
                   '/api/sendImagesToUser', '/api/sendImagesToUserByAccount',
                   '/api/sendImagesToGroup', '/api/sendImagesToGroupByAccount',
                   '/api/sendFile', '/api/sendFileByAccount',
                   '/api/sendVideoByAccount', '/api/sendVoiceByAccount',
                   '/api/sendStickerByAccount', '/api/sendLinkByAccount']) {
    assert.equal(isApiKeyRoute(p), true, `${p} phải nằm trong phạm vi API key`);
    const { daQua } = chay(reqVoiApiKey(p));
    assert.equal(daQua, true, `tích hợp gửi thông báo bị chặn ở ${p}`);
  }
});

test('API key KHÔNG đọc được lịch sử chat, không tra người dùng, không sửa nhóm', () => {
  // Chính sách chốt 08/08: key này chỉ để GỬI. Đây là danh sách từng nằm trong
  // phạm vi key (kế thừa nhầm từ nhóm "route từng public") và nay phải bị chặn.
  for (const p of ['/api/getGroupChatHistoryByAccount',
                   '/api/findUser', '/api/getUserInfo', '/api/getGroupInfo',
                   '/api/createGroup', '/api/addUserToGroup',
                   '/api/removeUserFromGroup', '/api/sendFriendRequest']) {
    assert.equal(isApiKeyRoute(p), false, `${p} không được nằm trong phạm vi API key`);
    const { res, daQua } = chay(reqVoiApiKey(p));
    assert.equal(daQua, false, `API key vẫn lọt vào ${p}`);
    assert.equal(res.statusCode, 403);
    assert.equal(res.body.code, 'API_KEY_OUT_OF_SCOPE');
  }
});

test('API key KHÔNG mở được dashboard / chat / quản lý người dùng', () => {
  for (const p of ['/api/conversations', '/api/messages', '/api/send',
                   '/accounts', '/messages', '/user-management', '/api/users']) {
    assert.equal(isApiKeyRoute(p), false, `${p} không được nằm trong phạm vi API key`);
    const { res, daQua } = chay(reqVoiApiKey(p));
    assert.equal(daQua, false, `API key vẫn lọt vào ${p}`);
    assert.equal(res.statusCode, 403, `${p} phải trả 403`);
    assert.equal(res.body.code, 'API_KEY_OUT_OF_SCOPE');
  }
});

test('admin đăng nhập vẫn làm được những việc key không được phép', () => {
  for (const p of ['/api/getGroupChatHistoryByAccount', '/api/findUser',
                   '/api/createGroup']) {
    const { daQua } = chay(reqVoiPhien(p, 'admin'));
    assert.equal(daQua, true, `admin phải vào được ${p}`);
  }
});

test('phiên vai admin vào được dashboard', () => {
  for (const p of ['/api/conversations', '/accounts', '/messages']) {
    const { daQua } = chay(reqVoiPhien(p, 'admin'));
    assert.equal(daQua, true, `admin phải vào được ${p}`);
  }
});

test('phiên vai user bị chặn khỏi dashboard và chat', () => {
  for (const p of ['/api/conversations', '/api/messages', '/api/send',
                   '/accounts', '/messages', '/chat']) {
    const { res, daQua } = chay(reqVoiPhien(p, 'user'));
    assert.equal(daQua, false, `vai 'user' vẫn vào được ${p}`);
    assert.equal(res.statusCode, 403);
  }
});

test("vai user vẫn tự đổi được mật khẩu của mình", () => {
  const { daQua } = chay(reqVoiPhien('/api/change-password', 'user'));
  assert.equal(daQua, true, 'chặn cả đổi mật khẩu là khoá người dùng ra ngoài');
});

test('không có phiên và không có key thì 401', () => {
  const req = { path: '/api/conversations', headers: { accept: 'application/json' }, query: {}, session: null };
  const { res, daQua } = chay(req);
  assert.equal(daQua, false);
  assert.equal(res.statusCode, 401);
});
