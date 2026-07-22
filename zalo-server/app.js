// app.js
import express from 'express';
import session from 'express-session';
import sessionFileStore from 'session-file-store';
import cookieParser from 'cookie-parser';
import { authMiddleware, isPublicRoute, getServerApiKey } from './services/authService.js';
import { loadWebhookConfig } from './services/webhookService.js';
import routes from './routes/index.js';
import fs from 'fs';
import path from 'path';
import sharp from 'sharp';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { loadHomeAssistantOptions, getDataDirectory } from './config/addon.js';
import { zaloAccounts, loginZaloAccount } from './api/zalo/zalo.js';

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
app.use(express.json());
app.use(express.urlencoded({ extended: true })); // Dùng để parse dữ liệu form
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

// Định nghĩa SESSION_SECRET từ biến môi trường hoặc mặc định
const sessionSecret = process.env.SESSION_SECRET || 'zalo-server-secret-key';
console.log("Using session secret:", sessionSecret ? "Configured properly" : "MISSING SESSION SECRET");

const FileStore = sessionFileStore(session);

// Thiết lập session với file store để tồn tại qua restart
app.use(session({
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
    secure: false,
    httpOnly: true,
    maxAge: 30 * 24 * 60 * 60 * 1000, // 30 ngày
    path: '/',
    sameSite: 'lax'
  },
  rolling: true // Gia hạn session mỗi lần request
}));

// Log để debug session
app.use((req, res, next) => {
  console.log(`[${new Date().toISOString()}] ${req.method} ${req.path}`);
  console.log('Session exists:', !!req.session);
  next();
});

// Middleware xác thực cho tất cả các route trừ những route công khai
app.use((req, res, next) => {
  // Bỏ qua xác thực cho các API route và các route công khai
  if (isPublicRoute(req.path)) {
    console.log(`Skipping auth for public route: ${req.path}`);
    return next();
  }

  // Áp dụng middleware xác thực cho các route khác
  console.log(`Applying auth middleware for protected route: ${req.path}`);
  authMiddleware(req, res, next);
});

// Thiết lập route
app.use('/', routes);

// ── Static file middleware — để sau routes ───────────────────────────────
// Phải sau routes để ko bị redirect /chat → /chat/
const publicDir = '/config/www/zalo_bot';
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

// Login từ cookie đã lưu
// Login từ cookie đã lưu
import { getCookiesDir } from './utils/helpers.js';

const cookiesDir = getCookiesDir();
console.log(`Thư mục cookies được cấu hình: ${cookiesDir}`);

if (fs.existsSync(cookiesDir)) {
    try {
        const cookieFiles = fs.readdirSync(cookiesDir);
        console.log(`Tìm thấy ${cookieFiles.length} file cookie trong thư mục ${cookiesDir}`);

        // Sử dụng IIFE để tránh top-level await
        (async function() {
            for (const file of cookieFiles) {
                if (file.startsWith('cred_') && file.endsWith('.json')) {
                    const ownId = file.substring(5, file.length - 5);
                    try {
                        // Bỏ qua nếu tài khoản đã đăng nhập
                        if (zaloAccounts.some(a => a.ownId === ownId)) {
                            console.log(`Tài khoản ${ownId} đã đăng nhập, bỏ qua.`);
                            continue;
                        }

                        const cookiePath = path.join(cookiesDir, file);
                        if (fs.existsSync(cookiePath)) {
                            const cookie = JSON.parse(fs.readFileSync(cookiePath, "utf-8"));
                            try {
                                await loginZaloAccount(null, cookie);
                                // Kiểm tra thực sự account đã vào zaloAccounts chưa
                                if (zaloAccounts.some(a => a.ownId === ownId)) {
                                    console.log(`[Restore] ${ownId} — OK`);
                                } else {
                                    console.log(`[Restore] ${ownId} — cookie hết hạn, đã xóa`);
                                    try { fs.unlinkSync(cookiePath); } catch (e) { /* ignore */ }
                                }
                            } catch (loginError) {
                                console.error(`Lỗi khi đăng nhập lại tài khoản ${ownId}:`, loginError.message);
                                try { fs.unlinkSync(cookiePath); console.log(`Đã xóa cookie lỗi: ${cookiePath}`); } catch (e) { /* ignore */ }
                            }
                        } else {
                            console.log(`Không tìm thấy file cookie: ${cookiePath}`);
                        }
                    } catch (error) {
                        console.error(`Lỗi khi đọc/xử lý cookie cho tài khoản ${ownId}:`, error.message);
                    }
                }
            }
        })().catch(err => {
            console.error('Lỗi khi xử lý đăng nhập từ cookie:', err);
        });
    } catch (dirError) {
        console.error(`Lỗi khi đọc thư mục cookies:`, dirError);
    }
} else {
    console.log(`Thư mục cookies không tồn tại: ${cookiesDir}. Đang tạo mới...`);
    fs.mkdirSync(cookiesDir, { recursive: true });
}

// In ra thông tin về biến môi trường dữ liệu
console.log('DATA_DIRECTORY from process.env:', process.env.DATA_DIRECTORY);

export default app;