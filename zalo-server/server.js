// server.js
import http from 'http';
import { WebSocketServer } from 'ws';
import app, { sessionMiddleware } from './app.js';
import { getDataDirectory } from './config/addon.js';

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
const wss = new WebSocketServer({ noServer: true });
const _WS_MAX = 50;

// Lưu trữ kết nối WebSocket
export const webSocketClients = new Set();

function _originOk(req) {
  // Không có Origin (client không phải trình duyệt) → cho qua; có thì phải
  // khớp Host (chống trình duyệt lạ nối cross-site). WS vẫn cần session hợp lệ.
  const origin = req.headers.origin;
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
  if (webSocketClients.size >= _WS_MAX) {
    console.warn('WS upgrade từ chối: quá số kết nối tối đa');
    socket.destroy();
    return;
  }
  // Chạy session middleware để nạp req.session từ cookie, rồi kiểm authenticated.
  // res giả (no-op): middleware chỉ ĐỌC session ở đây; rolling cookie có thể
  // gọi setHeader/end nên phải có stub kẻo ném lỗi.
  const fakeRes = { setHeader() {}, getHeader() {}, removeHeader() {}, end() {}, writeHead() {}, on() {} };
  sessionMiddleware(req, fakeRes, () => {
    if (!req.session || !req.session.authenticated) {
      console.warn('WS upgrade từ chối: chưa đăng nhập');
      socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
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
  webSocketClients.add(ws);
  ws.on('close', () => {
    webSocketClients.delete(ws);
  });
  ws.on('error', () => {
    webSocketClients.delete(ws);
  });
});

// Hàm gửi thông báo đến tất cả client WebSocket
export function broadcastMessage(message) {
  webSocketClients.forEach((client) => {
    if (client.readyState === 1) { // 1 = OPEN
      client.send(message);
    }
  });
}

// Sử dụng HTTP server thay vì app để hỗ trợ WebSocket
server.listen(PORT, () => {
  console.log(`Server đang chạy tại http://localhost:${PORT}`);
});

// Xử lý tín hiệu tắt server một cách an toàn
process.on('SIGTERM', () => {
  console.log('Nhận tín hiệu SIGTERM (container đang dừng). Đang dọn dẹp...');
  
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
  
  server.close(() => {
    console.log('Server HTTP đã đóng.');
    process.exit(0);
  });
});
