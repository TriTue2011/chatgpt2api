// server.js
import http from 'http';
import { WebSocketServer } from 'ws';
import app, { sessionMiddleware } from './app.js';
import { getDataDirectory } from './config/addon.js';
import { flushAllGroupHistorySync } from './utils/groupHistoryStore.js';
import {
  closeAllWebSocketClients,
  getWebSocketClientCount,
  registerWebSocketClient,
} from './services/websocketHub.js';

const PORT = process.env.PORT || 3000;
const dataDir = getDataDirectory();

console.log(`=========================================`);
console.log(`Khởi động server với thông số:`);
console.log(`- Port: ${PORT}`);
console.log(`- Thư mục dữ liệu: ${dataDir}`);
console.log(`- Webhook URLs: ${process.env.MESSAGE_WEBHOOK_URL || 'không cấu hình'}`);
console.log(`=========================================`);

// Tạo HTTP server
const server = http.createServer(app);

// WebSocket: KHÔNG gắn thẳng vào server (trước đây `new WebSocketServer({server})`
// nhận MỌI kết nối ở mọi path, KHÔNG qua Express auth, rồi broadcast toàn bộ
// tin nhắn Zalo cho bất kỳ ai — báo cáo bảo mật 07/08). Nay dùng noServer +
// tự xử lý 'upgrade': chỉ path /ws, kiểm Origin same-host, XÁC THỰC session
// (cùng middleware với HTTP), giới hạn số kết nối.
const wss = new WebSocketServer({ noServer: true, maxPayload: 1024 * 1024 }); // trần 1MB/khung
const _WS_MAX = 50;

// Origin allowlist: khai ZALO_WS_ALLOWED_ORIGINS (phẩy) = danh sách origin
// HTTPS cụ thể (khuyến nghị khi chạy sau tunnel). Chưa khai → fallback same-host
// (LAN dev). "Không dựa vào so sánh host đơn thuần" khi đã có allowlist.
const _WS_ORIGINS = String(process.env.ZALO_WS_ALLOWED_ORIGINS || '')
  .split(',').map(s => s.trim()).filter(Boolean);

function _originOk(req) {
  const origin = req.headers.origin;
  if (_WS_ORIGINS.length) {
    // Có allowlist → BẮT BUỘC Origin khớp chính xác một origin đã khai.
    return !!origin && _WS_ORIGINS.includes(origin);
  }
  // Chưa khai allowlist: không có Origin (client không phải trình duyệt) cho
  // qua; có thì phải khớp Host (chống cross-site cơ bản). Vẫn cần session admin.
  if (!origin) return true;
  try {
    return new URL(origin).host === req.headers.host;
  } catch {
    return false;
  }
}

server.on('upgrade', (req, socket, head) => {
  const path = (req.url || '').split('?')[0];
  // endsWith thay vì ==: HA addon ingress thêm prefix (<ingress>/ws), client
  // (websocket.js) nối `${INGRESS_PATH}/ws`.
  if (!path.endsWith('/ws')) {
    socket.destroy();
    return;
  }
  if (!_originOk(req)) {
    console.warn('WS upgrade từ chối: Origin lạ');
    socket.destroy();
    return;
  }
  if (getWebSocketClientCount() >= _WS_MAX) {
    console.warn('WS upgrade từ chối: quá số kết nối tối đa');
    socket.destroy();
    return;
  }
  // Chạy session middleware để nạp req.session từ cookie, rồi kiểm authenticated.
  // res giả (no-op): middleware chỉ ĐỌC session ở đây; rolling cookie có thể
  // gọi setHeader/end nên phải có stub kẻo ném lỗi.
  const fakeRes = { setHeader() {}, getHeader() {}, removeHeader() {}, end() {}, writeHead() {}, on() {} };
  sessionMiddleware(req, fakeRes, () => {
    // WS phát TOÀN BỘ tin nhắn Zalo → chỉ ADMIN. User thường (nếu có) không
    // được nghe chung. Muốn cho user xem Zalo phải thiết kế ACL theo
    // tài khoản/thread, không broadcast chung.
    if (!req.session || !req.session.authenticated || req.session.role !== 'admin') {
      console.warn('WS upgrade từ chối: cần đăng nhập admin');
      socket.write('HTTP/1.1 403 Forbidden\r\n\r\n');
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      wss.emit('connection', ws, req);
    });
  });
});

// Xử lý kết nối WebSocket (đã xác thực ở bước upgrade)
wss.on('connection', (ws) => {
  ws.isAlive = true;
  ws.on('pong', () => { ws.isAlive = true; });
  registerWebSocketClient(ws);
});

// Thu hoi ket noi half-open sau khi Wi-Fi/browser bien mat ma khong gui close.
const wsHeartbeat = setInterval(() => {
  for (const ws of wss.clients) {
    if (ws.isAlive === false) {
      ws.terminate();
      continue;
    }
    ws.isAlive = false;
    try { ws.ping(); } catch { ws.terminate(); }
  }
}, 30_000);
wsHeartbeat.unref?.();

// Sử dụng HTTP server thay vì app để hỗ trợ WebSocket
server.listen(PORT, () => {
  console.log(`Server đang chạy tại http://localhost:${PORT}`);
});

// Xử lý tín hiệu tắt server một cách an toàn
process.on('SIGTERM', () => {
  console.log('Nhận tín hiệu SIGTERM (container đang dừng). Đang dọn dẹp...');
  
  flushAllGroupHistorySync();
  clearInterval(wsHeartbeat);
  closeAllWebSocketClients();
  // Đóng server một cách an toàn
  server.close(() => {
    console.log('Server HTTP đã đóng.');
    process.exit(0);
  });
  
  // Đảm bảo tắt sau 10 giây nếu đóng server bị treo
  setTimeout(() => {
    console.error('Tắt server bị buộc do quá thời gian chờ.');
    process.exit(1);
  }, 10000);
});

process.on('SIGINT', () => {
  console.log('Nhận tín hiệu SIGINT (Ctrl+C). Đang dọn dẹp...');
  
  flushAllGroupHistorySync();
  clearInterval(wsHeartbeat);
  closeAllWebSocketClients();
  server.close(() => {
    console.log('Server HTTP đã đóng.');
    process.exit(0);
  });
});
