// auth.js - Quản lý xác thực người dùng
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// PBKDF2: bản ghi CŨ dùng 1000 vòng (yếu). Bản ghi MỚI dùng 600000 (OWASP
// khuyến nghị ≥210k cho PBKDF2-SHA512). Lưu số vòng THEO TỪNG bản ghi để bản
// cũ vẫn đăng nhập được (xác minh bằng đúng số vòng của nó), bản mới mạnh hơn.
const PBKDF2_ITERS = 600000;
const PBKDF2_LEGACY = 1000;

function _hash(password, salt, iters) {
  return crypto.pbkdf2Sync(password, salt, iters, 64, 'sha512').toString('hex');
}

// Mật khẩu admin ban đầu: ưu tiên env. KHÔNG có env → sinh NGẪU NHIÊN và cảnh
// báo (không còn 'admin' cứng đoán được). Trả {password, fromEnv}.
function _initialAdminSecret() {
  const env = String(process.env.ZALO_SERVER_ADMIN_PASSWORD || '').trim();
  if (env) return { password: env, fromEnv: true };
  return { password: crypto.randomBytes(18).toString('base64url'), fromEnv: false };
}

function _adminUsername() {
  return String(process.env.ZALO_SERVER_ADMIN_USERNAME || 'admin').trim() || 'admin';
}

// Đường dẫn đến file lưu thông tin đăng nhập
const userFilePath = path.join(process.cwd(), 'data', 'cookies', 'users.json');

// Tạo file users.json nếu chưa tồn tại
const initUserFile = () => {
  try {
    console.log("Khởi tạo file người dùng...");

    // Kiểm tra và tạo thư mục cookies nếu chưa tồn tại
    const cookiesDir = path.join(process.cwd(), 'data', 'cookies');
    if (!fs.existsSync(cookiesDir)) {
      console.log("Thư mục cookies không tồn tại, đang tạo...");
      fs.mkdirSync(cookiesDir, { recursive: true });
      console.log("Đã tạo thư mục cookies thành công");
    } else {
      console.log("Thư mục cookies đã tồn tại");
    }

    // Đường dẫn đầy đủ đến file users.json
    console.log("Đường dẫn file users.json:", userFilePath);

    // Kiểm tra file users.json
    if (!fs.existsSync(userFilePath)) {
      console.log("File users.json không tồn tại, đang tạo...");

      // Mật khẩu admin ban đầu: env ZALO_SERVER_ADMIN_PASSWORD, hoặc NGẪU NHIÊN.
      // KHÔNG còn mặc định 'admin' đoán được.
      const uname = _adminUsername();
      const { password, fromEnv } = _initialAdminSecret();
      const salt = crypto.randomBytes(16).toString('hex');
      const users = [{
        username: uname,
        salt,
        hash: _hash(password, salt, PBKDF2_ITERS),
        iterations: PBKDF2_ITERS,
        role: 'admin',
      }];
      fs.writeFileSync(userFilePath, JSON.stringify(users, null, 2));
      if (fromEnv) {
        console.log(`Đã tạo users.json với admin '${uname}' (mật khẩu từ ZALO_SERVER_ADMIN_PASSWORD)`);
      } else {
        // In MỘT LẦN để chủ máy đăng nhập rồi đổi — không có env thì đây là
        // đường duy nhất biết mật khẩu (không còn admin/admin).
        console.warn(`[BẢO MẬT] Chưa đặt ZALO_SERVER_ADMIN_PASSWORD. Đã sinh mật khẩu admin NGẪU NHIÊN cho '${uname}':`);
        console.warn(`[BẢO MẬT]   ${password}`);
        console.warn('[BẢO MẬT] Hãy đăng nhập, ĐỔI mật khẩu, rồi đặt ZALO_SERVER_ADMIN_PASSWORD để lần sau không sinh ngẫu nhiên.');
      }
    } else {
      // Kiểm tra file hợp lệ — KHÔNG log nội dung (chứa salt/hash).
      try {
        const content = fs.readFileSync(userFilePath, 'utf8');
        JSON.parse(content); // Kiểm tra xem có phải JSON hợp lệ
      } catch (readError) {
        console.error("Lỗi khi đọc/phân tích file users.json:", readError);
        // File hỏng → tạo lại, KHÔNG dùng admin/admin (env hoặc ngẫu nhiên).
        const uname = _adminUsername();
        const { password, fromEnv } = _initialAdminSecret();
        const salt = crypto.randomBytes(16).toString('hex');
        const users = [{
          username: uname,
          salt,
          hash: _hash(password, salt, PBKDF2_ITERS),
          iterations: PBKDF2_ITERS,
          role: 'admin',
        }];
        fs.writeFileSync(userFilePath, JSON.stringify(users, null, 2));
        if (!fromEnv) {
          console.warn(`[BẢO MẬT] users.json hỏng, đã tạo lại admin '${uname}' với mật khẩu NGẪU NHIÊN:`);
          console.warn(`[BẢO MẬT]   ${password}`);
        }
      }
    }
  } catch (error) {
    console.error("Lỗi trong quá trình khởi tạo file người dùng:", error);
  }
};

// Khởi tạo file người dùng
initUserFile();

// Đọc dữ liệu người dùng từ file
const getUsers = () => {
  try {
    // Đảm bảo đọc dữ liệu mới nhất từ file (không sử dụng cache)
    const data = fs.readFileSync(userFilePath, { encoding: 'utf8', flag: 'r' });

    try {
      const users = JSON.parse(data);
      // KHÔNG log username/salt/hash của từng user (rò băm mật khẩu ra log).
      return users;
    } catch (parseError) {
      console.error('Lỗi khi phân tích JSON từ file users.json:', parseError);
      return [];
    }
  } catch (error) {
    console.error('Lỗi khi đọc file users.json:', error);
    return [];
  }
};

// Thêm người dùng mới
export const addUser = (username, password, role = 'user') => {
  const users = getUsers();

  // Kiểm tra nếu username đã tồn tại
  if (users.some(user => user.username === username)) {
    return false;
  }

  const salt = crypto.randomBytes(16).toString('hex');
  users.push({
    username,
    salt,
    hash: _hash(password, salt, PBKDF2_ITERS),
    iterations: PBKDF2_ITERS,
    role,
  });

  fs.writeFileSync(userFilePath, JSON.stringify(users, null, 2));
  return true;
};

const lockFilePath = path.join(process.cwd(), 'data', 'cookies', 'users.lock');

async function withUserLock(fn) {
  const maxWaitMs = 30000;
  const startTime = Date.now();

  while (true) {
    try {
      // 'wx' flag: atomic check-and-create, fails nếu file đã tồn tại
      fs.writeFileSync(lockFilePath, String(Date.now()), { flag: 'wx' });
      break;
    } catch (err) {
      if (err.code !== 'EEXIST') {
        // Lỗi thật sự (permission, disk,...) — throw ra ngoài
        throw new Error(`Không thể tạo lock file: ${err.message}`);
      }

      // Lock đang được giữ bởi process khác, kiểm tra timeout
      if (Date.now() - startTime > maxWaitMs) {
        throw new Error('Không thể acquire lock sau 30s — lock có thể bị orphaned');
      }

      await new Promise(resolve => setTimeout(resolve, 10));
    }
  }

  try {
    return await fn();
  } finally {
    try { fs.unlinkSync(lockFilePath); } catch (e) { /* ignore */ }
  }
}

export const deleteUser = (username) => {
  return withUserLock(() => {
    const users = getUsers();
    const idx = users.findIndex(u => u.username === username);
    if (idx === -1) return { success: false, message: 'Không tìm thấy người dùng' };

    // Không cho xóa admin cuối cùng
    const adminCount = users.filter(u => u.role === 'admin').length;
    if (users[idx].role === 'admin' && adminCount <= 1) {
      return { success: false, message: 'Không thể xóa admin cuối cùng' };
    }

    users.splice(idx, 1);
    fs.writeFileSync(userFilePath, JSON.stringify(users, null, 2));
    return { success: true };
  });
};

// Xác thực người dùng và trả về thông tin user
export const validateUser = (username, password) => {
  // Đọc dữ liệu trực tiếp từ file để đảm bảo dữ liệu mới nhất
  let users = [];
  try {
    const data = fs.readFileSync(userFilePath, { encoding: 'utf8', flag: 'r' });
    users = JSON.parse(data);
  } catch (error) {
    console.error('Error reading users file directly:', error);
    return null;
  }

  const user = users.find(user => user.username === username);
  if (!user) {
    return null;
  }

  // TUYỆT ĐỐI không log password/salt/hash — trước đây in mật khẩu thô + full
  // hash + salt mỗi lượt login, mà bot tự đăng nhập mỗi phút nên credential
  // rò liên tục ra docker logs (báo cáo bảo mật 07/08 xác nhận trên máy chủ).
  // Xác minh bằng ĐÚNG số vòng của bản ghi (bản cũ 1000, bản mới 600000).
  const iters = Number(user.iterations) || PBKDF2_LEGACY;
  const hash = _hash(password, user.salt, iters);
  const stored = Buffer.from(String(user.hash), 'hex');
  const computed = Buffer.from(hash, 'hex');
  const ok = stored.length === computed.length && crypto.timingSafeEqual(stored, computed);
  if (ok) {
    return {
      username: user.username,
      role: user.role || 'user'
    };
  }
  return null;
};

// Thay đổi mật khẩu
export const changePassword = (username, oldPassword, newPassword) => {
  // KHÔNG log password/độ dài/salt/hash (rò băm + độ dài mật khẩu ra log).
  // Đọc dữ liệu trực tiếp từ file để đảm bảo dữ liệu mới nhất
  let users = [];
  try {
    const data = fs.readFileSync(userFilePath, { encoding: 'utf8', flag: 'r' });
    users = JSON.parse(data);
  } catch (error) {
    console.error('Error reading users file directly for password change:', error);
    return false;
  }

  const userIndex = users.findIndex(user => user.username === username);
  if (userIndex === -1) {
    return false;
  }

  const user = users[userIndex];
  const iters = Number(user.iterations) || PBKDF2_LEGACY;
  const hash = _hash(oldPassword, user.salt, iters);
  const stored = Buffer.from(String(user.hash), 'hex');
  const computed = Buffer.from(hash, 'hex');
  const ok = stored.length === computed.length && crypto.timingSafeEqual(stored, computed);
  if (!ok) {
    return false; // Mật khẩu cũ không chính xác
  }

  // Cập nhật mật khẩu mới — nâng lên số vòng MẠNH (600000).
  const salt = crypto.randomBytes(16).toString('hex');
  const newHash = _hash(newPassword, salt, PBKDF2_ITERS);
  users[userIndex].salt = salt;
  users[userIndex].hash = newHash;
  users[userIndex].iterations = PBKDF2_ITERS;

  try {
    // Ghi qua file tạm rồi rename (atomic) — KHÔNG log nội dung.
    const tempFilePath = path.join(process.cwd(), 'data', 'cookies', 'users.json.tmp');
    fs.writeFileSync(tempFilePath, JSON.stringify(users, null, 2), { encoding: 'utf8', flag: 'w' });
    fs.renameSync(tempFilePath, userFilePath);

    // Verify the file was written correctly
    const verifyUsers = getUsers();
    const verifyUser = verifyUsers.find(u => u.username === username);
    if (!verifyUser || verifyUser.salt !== salt || verifyUser.hash !== newHash) {
      console.error('Verification failed after password change');
      return false;
    }
    return true;
  } catch (error) {
    console.error('Error writing password change to file:', error);
    return false;
  }
};

/** API key cho HA / gateway (env ZALO_SERVER_API_KEY hoặc CHATGPT2API_AUTH_KEY). */
export const getServerApiKey = () =>
  String(process.env.ZALO_SERVER_API_KEY || process.env.CHATGPT2API_AUTH_KEY || '').trim();

function timingSafeEqualStr(a, b) {
  try {
    const ba = Buffer.from(String(a), 'utf8');
    const bb = Buffer.from(String(b), 'utf8');
    if (ba.length !== bb.length) return false;
    return crypto.timingSafeEqual(ba, bb);
  } catch {
    return false;
  }
}

function extractApiToken(req) {
  const auth = String(req.headers.authorization || '');
  if (auth.toLowerCase().startsWith('bearer ')) return auth.slice(7).trim();
  const x = req.headers['x-api-key'];
  if (x) return String(x).trim();
  if (req.query && req.query.api_key) return String(req.query.api_key).trim();
  return '';
}

// Middleware xác thực cho các route
export const authMiddleware = (req, res, next) => {
  if (req.session && req.session.authenticated) {
    return next();
  }

  // P0#4: Bearer / X-Api-Key khớp env (HA integration không dùng session cookie)
  const expected = getServerApiKey();
  const token = extractApiToken(req);
  if (expected && token && timingSafeEqualStr(token, expected)) {
    req.apiKeyAuth = true;
    return next();
  }

  // API request: return 401 JSON instead of HTML redirect
  if (req.path.startsWith('/api/') || req.headers.accept?.includes('application/json')) {
    return res.status(401).json({
      success: false,
      message: expected
        ? 'Thiếu hoặc sai API key (Authorization: Bearer … / X-Api-Key)'
        : 'Chưa đăng nhập',
      code: 'UNAUTHORIZED',
    });
  }

  // Browser request: redirect
  const prefix = req.ingressPath || '';
  res.redirect(prefix + '/admin-login');
};

// Middleware kiểm tra quyền admin
export const adminMiddleware = (req, res, next) => {
  if (req.session && req.session.authenticated && req.session.role === 'admin') {
    return next();
  }

  res.status(403).send('Không có quyền truy cập. Chỉ admin mới có thể thực hiện chức năng này.');
};

// Lấy toàn bộ danh sách người dùng (chỉ admin mới có quyền)
export const getAllUsers = () => {
  const users = getUsers();
  return users.map(user => ({
    username: user.username,
    role: user.role || 'user'
  }));
};

// Danh sách các route công khai (không cần xác thực)
export const publicRoutes = [
  '/', // Trang chủ hiển thị nút đăng nhập
  '/admin-login', // Trang đăng nhập
  '/session-test', // Trang kiểm tra session
  '/api/login', // API đăng nhập
  '/api/simple-login', // API đăng nhập đơn giản
  '/api/test-login', // API đăng nhập test
  '/api/logout', // API đăng xuất
  '/api/check-auth', // API kiểm tra trạng thái xác thực
  '/api/session-test', // API kiểm tra session
  '/api/account-webhook/', // API webhook có tham số
  '/reset-password', // Trang reset mật khẩu admin
  '/favicon.ico', // Favicon
  '/ws', // WebSocket
  '/pwa-manifest', // PWA manifest
  '/chat/sw.js', // PWA service worker
  '/chat/icons/*', // PWA icons
  '/chat/css/*', // Chat CSS
  '/chat/js/*', // Chat JS

  // Legacy: các API Zalo từng public. Khi ZALO_SERVER_API_KEY /
  // CHATGPT2API_AUTH_KEY được set, isPublicRoute sẽ KHÔNG coi chúng public
  // (bắt buộc Bearer/session) — xem SENSITIVE_API_PREFIXES bên dưới.
  '/api/findUser',
  '/api/getUserInfo',
  '/api/sendFriendRequest',
  '/api/sendmessage',
  '/api/createGroup',
  '/api/getGroupInfo',
  '/api/addUserToGroup',
  '/api/removeUserFromGroup',
  '/api/sendImageToUser',
  '/api/sendImagesToUser',
  '/api/sendImageToGroup',
  '/api/sendImagesToGroup',
  '/api/getGroupChatHistoryByAccount'
];

/** API gửi tin / điều khiển — không public khi đã cấu hình API key. */
const SENSITIVE_API_PREFIXES = [
  '/api/findUser',
  '/api/getUserInfo',
  '/api/sendFriendRequest',
  '/api/sendmessage',
  '/api/createGroup',
  '/api/getGroupInfo',
  '/api/addUserToGroup',
  '/api/removeUserFromGroup',
  '/api/sendImageToUser',
  '/api/sendImagesToUser',
  '/api/sendImageToGroup',
  '/api/sendImagesToGroup',
  '/api/getGroupChatHistoryByAccount',
];

// Kiểm tra xem route có phải là public hay không
export const isPublicRoute = (path) => {
  console.log('Checking if route is public:', path);

  // Kiểm tra các route API công khai
  if (path.startsWith('/api/')) {
    // Xử lý các route có tham số động
    if (path.startsWith('/api/account-webhook/')) {
      console.log('Is account webhook API with parameters:', true);
      return true;
    }

    // P0#4: khi có API key, các route gửi tin không còn public
    const apiKey = getServerApiKey();
    if (apiKey) {
      for (const pref of SENSITIVE_API_PREFIXES) {
        if (path === pref || path.startsWith(pref + '/') || path.startsWith(pref + '?')) {
          console.log('Sensitive API requires key/session:', path);
          return false;
        }
      }
    }

    // Kiểm tra các route cụ thể trong danh sách publicRoutes
    for (const route of publicRoutes) {
      if (route.startsWith('/api/') && (
        path === route || // Trùng khớp chính xác
        (route.endsWith('/') && path.startsWith(route)) // Route kết thúc bằng / và path bắt đầu bằng route
      )) {
        console.log('Is public API route:', true);
        return true;
      }
    }

    console.log('Is public API route:', false);
    return false;
  }

  // Kiểm tra các route UI công khai
  for (const route of publicRoutes) {
    // Bỏ qua các route API
    if (route.startsWith('/api/')) continue;

    // Kiểm tra exact match
    if (path === route) {
      console.log('Is public UI route (exact match):', true);
      return true;
    }

    // Kiểm tra prefix match cho routes như /route/*
    if (route.endsWith('*') && path.startsWith(route.slice(0, -1))) {
      console.log('Is public UI route (prefix match):', true);
      return true;
    }
  }

  console.log('Is public route:', false);
  return false;
};