// app.js
import express from 'express';
import session from 'express-session';
import sessionFileStore from 'session-file-store';
import cookieParser from 'cookie-parser';
import { authMiddleware, dashboardRoleMiddleware, isPublicRoute, getServerApiKey } from './services/authService.js';
import { loadWebhookConfig } from './services/webhookService.js';
import routes from './routes/index.js';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import sharp from 'sharp';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { loadHomeAssistantOptions, getDataDirectory } from './config/addon.js';
import { zaloAccounts, loginZaloAccount } from './api/zalo/zalo.js';
import { writeFileAtomicSync } from './utils/atomicFile.js';

// Dành cho ES Module: xác định __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load Home Assistant options if available
const dataDirectory = loadHomeAssistantOptions();
console.log(`Using data directory: ${dataDirectory}`);

// Kiểm tra và đảm bảo thư mục dữ liệu tồn tại và có quyền ghi
if (!fs.existsSync(dataDirectory)) {
  console.log(`Thư mục dữ liệu ${dataDirectory} không tồn tại, đang tạo mới...`);
  try {
    fs.mkdirSync(dataDirectory, { recursive: true });
    console.log(`Đã tạo thư mục dữ liệu ${dataDirectory}`);
  } catch (error) {
    console.error(`Lỗi khi tạo thư mục dữ liệu: ${error.message}`);
  }
}

// Thử ghi file test để kiểm tra quyền
try {
  const testFile = path.join(dataDirectory, '.test_write.txt');
  fs.writeFileSync(testFile, 'test write permission', 'utf8');
  console.log(`Đã ghi thành công file test tại ${testFile}`);
  fs.unlinkSync(testFile);
} catch (error) {
  console.error(`Không thể ghi vào thư mục dữ liệu: ${error.message}`);
}

// Load environment variables from .env file
dotenv.config({ path: path.join(__dirname, 'config', '.env') });

// P0#4: cảnh báo nếu không có API key — route gửi tin có thể public (legacy)
const _zaloApiKey = getServerApiKey();
if (!_zaloApiKey) {
  console.warn(
    '[SECURITY] ZALO_SERVER_API_KEY / CHATGPT2API_AUTH_KEY chưa set — ' +
    'một số API gửi tin vẫn public (legacy). Đặt key + gửi Authorization: Bearer …'
  );
} else {
  console.log('[SECURITY] zalo-server API key auth ENABLED for sensitive routes');
}

const app = express();
app.disable('x-powered-by');
app.use((_req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'same-origin');
  res.setHeader('X-Frame-Options', 'SAMEORIGIN');
  next();
});

// Cấu hình EJS
app.set('view engine', 'ejs');
const viewsPath = path.join(__dirname, 'views');
console.log('Views path:', viewsPath);
app.set('views', viewsPath);

// Kiểm tra thư mục views
if (fs.existsSync(viewsPath)) {
  const files = fs.readdirSync(viewsPath);
  console.log('Views directory exists. Files:', files);
} else {
  console.error('Views directory does not exist at', viewsPath);
  // Nếu không tồn tại, thử tạo thư mục
  try {
    fs.mkdirSync(viewsPath, { recursive: true });
    console.log('Created views directory at', viewsPath);
  } catch (error) {
    console.error('Failed to create views directory:', error);
  }
}

// Tải cấu hình webhook từ file
loadWebhookConfig();
console.log("Đã tải cấu hình webhook");

// Thiết lập middleware
app.use(express.json({ limit: process.env.JSON_BODY_LIMIT || '2mb' }));
app.use(express.urlencoded({
  extended: true,
  limit: process.env.FORM_BODY_LIMIT || '2mb',
}));
app.use(cookieParser());

// Middleware phát hiện HA ingress proxy — tất cả link phải có prefix này
app.use((req, res, next) => {
  const ingressPath = req.headers['x-ingress-path'] || '';
  req.ingressPath = ingressPath;
  res.locals.ingressPath = ingressPath;
  next();
});

// ── Generate PWA icons & screenshots ────────────────────────────────────
(function generateIcons() {
    const iconsDir = path.join(__dirname, 'public', 'chat', 'icons');
    if (!fs.existsSync(iconsDir)) fs.mkdirSync(iconsDir, { recursive: true });
    const srcIcon = path.join(iconsDir, 'zalo.png');
    if (!fs.existsSync(srcIcon)) return;

    // Icons from zalo.png
    [192, 512].forEach(size => {
        const pngPath = path.join(iconsDir, `icon-${size}.png`);
        // Luôn regenerate để cập nhật icon mới
        sharp(srcIcon).resize(size, size).png().toFile(pngPath)
            .then(() => console.log(`[PWA] Icon ${size}x${size} generated`))
            .catch(e => console.warn(`[PWA] Icon ${size} failed:`, e.message));
    });
    // Screenshots
    const screenshots = [
        { name: 'screenshot-wide', w: 1280, h: 720, text: 'Zalo Chat' },
        { name: 'screenshot-narrow', w: 720, h: 1280, text: 'Zalo Chat' }
    ];
    screenshots.forEach(({ name, w, h, text }) => {
        const pngPath = path.join(iconsDir, `${name}.png`);
        if (fs.existsSync(pngPath)) return;
        const overlay = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">
            <defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:#0068ff"/>
                <stop offset="100%" style="stop-color:#4d9fff"/>
            </linearGradient></defs>
            <rect width="${w}" height="${h}" fill="url(#g)"/>
            <text x="${w/2}" y="${h/2}" font-family="Inter,sans-serif" font-size="36" font-weight="700" fill="#fff" text-anchor="middle" dominant-baseline="middle">${text}</text>
        </svg>`;
        sharp(Buffer.from(overlay)).resize(w, h).png().toFile(pngPath)
            .then(() => console.log(`[PWA] Screenshot ${name} generated`))
            .catch(e => console.warn(`[PWA] Screenshot ${name} failed:`, e.message));
    });
})();

// Uu tien env. Neu thieu, tao mot secret ngau nhien BEN VUNG trong data dir
// (mode 0600, atomic) de restart container khong dang xuat moi dashboard. Day
// van la secret khong doan duoc, khac default cung hoac random moi lan chay.
function getSessionSecret() {
  const fromEnv = String(process.env.SESSION_SECRET || '').trim();
  if (fromEnv) return fromEnv;

  const secretPath = path.join(dataDirectory, 'session-secret');
  try {
    if (fs.existsSync(secretPath)) {
      const existing = fs.readFileSync(secretPath, 'utf8').trim();
      if (existing.length >= 32) return existing;
    }
    const generated = crypto.randomBytes(48).toString('hex');
    writeFileAtomicSync(secretPath, generated);
    try { fs.chmodSync(secretPath, 0o600); } catch { /* platform may not support chmod */ }
    console.log(`[Session] Da tao session secret ben vung tai ${secretPath}`);
    return generated;
  } catch (error) {
    console.warn(`[Session] Khong luu duoc session secret: ${error.message}; dung secret tam thoi.`);
    return crypto.randomBytes(48).toString('hex');
  }
}

const sessionSecret = getSessionSecret();

// ZALO_COOKIE_SECURE chỉ nhận "0" hoặc "1". Mọi giá trị khác ("true", "yes",
// "on"…) rơi vào nhánh false một cách IM LẶNG — người triển khai tưởng đã bật
// cookie Secure trong khi thực tế chưa. Nói to ra thay vì để họ tự đoán.
const cookieSecureRaw = (process.env.ZALO_COOKIE_SECURE ?? '').trim();
if (cookieSecureRaw !== '' && cookieSecureRaw !== '0' && cookieSecureRaw !== '1') {
  console.warn(
    `[BẢO MẬT] ZALO_COOKIE_SECURE="${cookieSecureRaw}" không hợp lệ — chỉ chấp nhận "0" hoặc "1". ` +
    'Đang hiểu là "0" (cookie KHÔNG có cờ Secure). Muốn bật thì đặt đúng ZALO_COOKIE_SECURE=1.'
  );
}
const cookieSecure = cookieSecureRaw === '1';
if (cookieSecure) {
  console.warn(
    '[BẢO MẬT] ZALO_COOKIE_SECURE=1 — cookie session chỉ gửi qua HTTPS. ' +
    'Bot Python gọi http://127.0.0.1:3001 sẽ MẤT phiên; chỉ dùng khi zalo-server đứng sau HTTPS hoàn toàn.'
  );
}

const FileStore = sessionFileStore(session);

// Export session middleware để dùng lại khi xác thực WebSocket upgrade
// (server.js) — WS trước đây nhận MỌI kết nối, broadcast toàn bộ tin nhắn cho
// bất kỳ ai (báo cáo bảo mật 07/08). Cùng một session middleware nên cùng cách
// xác thực với HTTP.
export const sessionMiddleware = session({
  store: new FileStore({
    path: path.join(getDataDirectory(), 'sessions'),
    ttl: 30 * 24 * 60 * 60, // 30 ngày (tính bằng giây)
    retries: 0
  }),
  secret: sessionSecret,
  resave: false,
  saveUninitialized: false,
  name: 'zalo-server.sid',
  cookie: {
    // secure BẬT khi ZALO_COOKIE_SECURE=1 (triển khai chỉ-HTTPS qua tunnel).
    // Mặc định false để không phá đăng nhập LAN qua HTTP (chủ máy dùng cả hai).
    secure: cookieSecure,
    httpOnly: true,
    maxAge: 30 * 24 * 60 * 60 * 1000, // 30 ngày
    path: '/',
    sameSite: 'lax'
  },
  rolling: true // Gia hạn session mỗi lần request
});
app.use(sessionMiddleware);

// Chi log request khi can debug; production khong ghi I/O cho moi webhook/API.
if (process.env.DEBUG_HTTP === 'true') {
  app.use((req, _res, next) => {
    console.log(`[${new Date().toISOString()}] ${req.method} ${req.path}`);
    next();
  });
}

// Middleware xác thực cho tất cả các route trừ những route công khai
app.use((req, res, next) => {
  // Bỏ qua xác thực cho các API route và các route công khai
  if (isPublicRoute(req.path)) {
    console.log(`Skipping auth for public route: ${req.path}`);
    return next();
  }

  // Áp dụng middleware xác thực cho các route khác
  console.log(`Applying auth middleware for protected route: ${req.path}`);
  authMiddleware(req, res, () => dashboardRoleMiddleware(req, res, next));
});

// Thiết lập route
app.use('/', routes);

// ── Static file middleware — để sau routes ───────────────────────────────
// Phải sau routes để ko bị redirect /chat → /chat/
const publicDir = process.env.PUBLIC_DIR || '/config/www/zalo_bot';
if (!fs.existsSync(publicDir)) {
  try { fs.mkdirSync(publicDir, { recursive: true }); } catch (error) { console.error(`Lỗi tạo public dir:`, error.message); }
}
app.use(express.static(publicDir));
app.use(express.static(path.join(__dirname, 'public'), {
    setHeaders(res, filePath) {
        if (filePath.endsWith('.webmanifest')) res.setHeader('Content-Type', 'application/manifest+json');
    }
}));
app.use('/zalo_bot', express.static(publicDir));
console.log('Static files path:', publicDir, 'và', path.join(__dirname, 'public'));

// Body-parser nem loi truoc khi route chay. Tra JSON gon va khong in stack
// trace cho payload co chu dich vuot tran.
app.use((error, req, res, next) => {
  if (error?.type === 'entity.too.large' || Number(error?.status) === 413) {
    return res.status(413).json({
      success: false,
      code: 'PAYLOAD_TOO_LARGE',
      error: 'Request body vuot gioi han cho phep',
    });
  }
  return next(error);
});

// Login từ cookie đã lưu
// Login từ cookie đã lưu
import { getCookiesDir } from './utils/helpers.js';

const cookiesDir = getCookiesDir();
console.log(`Thư mục cookies được cấu hình: ${cookiesDir}`);

async function restoreSavedAccounts() {
  let files;
  try {
    files = fs.readdirSync(cookiesDir)
      .filter((file) => file.startsWith('cred_') && file.endsWith('.json'));
  } catch (error) {
    console.error(`[Restore] Khong doc duoc ${cookiesDir}: ${error.message}`);
    return;
  }
  if (!files.length) return;

  let nextIndex = 0;
  async function worker() {
    while (true) {
      const index = nextIndex++;
      if (index >= files.length) return;
      const file = files[index];
      const ownId = file.slice(5, -5);
      if (zaloAccounts.some((account) => String(account.ownId) === ownId)) continue;

      const credentialPath = path.join(cookiesDir, file);
      try {
        const credential = JSON.parse(fs.readFileSync(credentialPath, 'utf8'));
        const hasSavedProxy = Object.prototype.hasOwnProperty.call(credential, 'proxy');
        const savedProxy = hasSavedProxy ? (credential.proxy || null) : null;
        let lastError;
        for (let attempt = 1; attempt <= 3; attempt += 1) {
          try {
            await loginZaloAccount(savedProxy, credential, {
              allowQrFallback: false,
              autoSelectProxy: !hasSavedProxy,
            });
            lastError = null;
            break;
          } catch (error) {
            lastError = error;
            if (attempt < 3) {
              await new Promise((resolve) => setTimeout(resolve, attempt * 5000));
            }
          }
        }
        if (lastError) {
          // Khong tu xoa credential ke ca khi SDK bao cookie loi: tai khoan co
          // the dang bi rate-limit/mat mang. Xoa phien la hanh dong cua user.
          console.error(`[Restore] ${ownId} chua khoi phuc duoc; GIU credential: ${lastError.message}`);
        } else {
          console.log(`[Restore] ${ownId} — OK`);
        }
      } catch (error) {
        console.error(`[Restore] Khong doc/khoi phuc duoc ${ownId}; giu file: ${error.message}`);
      }
    }
  }

  const concurrency = Math.min(3, files.length);
  await Promise.all(Array.from({ length: concurrency }, () => worker()));
}

void restoreSavedAccounts().catch((error) => {
  console.error('[Restore] Loi ngoai du kien:', error);
});

// In ra thông tin về biến môi trường dữ liệu
console.log('DATA_DIRECTORY from process.env:', process.env.DATA_DIRECTORY);

export default app;
