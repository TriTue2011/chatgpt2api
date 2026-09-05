/**
 * Sổ tra tính năng — MỘT nguồn cho ba mặt tiền.
 *
 * Cùng dữ liệu này nuôi:
 *   1. Checklist "Bắt đầu ở đây"  → lọc mục chưa xong, sắp theo `thuTu`
 *   2. Tooltip giải thích          → `mucDich` + `canGi`
 *   3. Ô tìm nhanh Cmd+K           → `ten` + `tuKhoa` + `duong`
 *
 * Ba nơi đó trước đây sẽ là ba danh sách chép tay lệch nhau. Ở đây sửa mô tả
 * một chỗ là cả ba đổi theo.
 *
 * **`daXong` cố ý KHÔNG bắt buộc.** Trong 41 thẻ cài đặt, chỉ một phần có thể
 * kiểm chắc chắn từ API hiện có. Mục không kiểm được thì vẫn tra cứu và giải
 * thích được, nhưng KHÔNG xuất hiện trong danh sách "còn thiếu" — thà im lặng
 * còn hơn báo "chưa cấu hình" cho thứ người dùng đã cấu hình xong.
 */
import type { SettingsConfig } from "@/lib/api";

export type MucDo = "bat-buoc" | "nen-co" | "tuy-chon";

/** Trạng thái thật của hệ thống, gom từ ba API đã có sẵn. */
export type TrangThaiHeThong = {
  config: SettingsConfig | null;
  soTaiKhoan: number;
  soTaiKhoanSong: number;
  /** Đã gọi xong API chưa — chưa xong thì đừng kết luận "còn thiếu". */
  daTai: boolean;
};

export type MucTinhNang = {
  id: string;
  ten: string;
  /** Dùng để làm gì — câu đầu trong tooltip. Viết cho người chưa biết gì. */
  mucDich: string;
  /** Cần có sẵn cái gì mới dùng được. Bỏ trống nghĩa là không cần gì thêm. */
  canGi?: string;
  mucDo: MucDo;
  /** Thứ tự cài. Số nhỏ làm trước. */
  thuTu: number;
  duong: string;
  nhom: string;
  tuKhoa: string[];
  /** Bỏ trống = không kiểm được trạng thái, sẽ không vào checklist. */
  daXong?: (tt: TrangThaiHeThong) => boolean;
};

// ── Trợ giúp đọc config an toàn ─────────────────────────────────────────────

function lay(cfg: SettingsConfig | null, khoa: string): unknown {
  if (!cfg) return undefined;
  return (cfg as Record<string, unknown>)[khoa];
}

/** Chuỗi có nội dung thật (không rỗng, không toàn khoảng trắng). */
function coChu(v: unknown): boolean {
  return typeof v === "string" && v.trim().length > 0;
}

/** Object/array có ít nhất một phần tử. */
function coPhanTu(v: unknown): boolean {
  if (Array.isArray(v)) return v.length > 0;
  if (v && typeof v === "object") return Object.keys(v).length > 0;
  return false;
}

// ── Sổ tra ──────────────────────────────────────────────────────────────────

export const SO_TRA: MucTinhNang[] = [
  // ═══ Bắt buộc — chưa có thì hệ thống không chạy được ═══
  {
    id: "tai-khoan",
    ten: "Tài khoản AI",
    mucDich:
      "Kho tài khoản mà mọi lời gọi API đều rút từ đây. Chưa có tài khoản nào thì " +
      "không model nào trả lời được.",
    canGi: "Ít nhất một tài khoản ChatGPT, Codex, Gemini hoặc Antigravity.",
    mucDo: "bat-buoc",
    thuTu: 1,
    duong: "/accounts",
    nhom: "Nền tảng",
    tuKhoa: ["tài khoản", "account", "token", "đăng nhập", "chatgpt", "codex", "gemini"],
    daXong: (tt) => tt.soTaiKhoan > 0,
  },
  {
    id: "tai-khoan-song",
    ten: "Tài khoản còn hoạt động",
    mucDich:
      "Có tài khoản nhưng tất cả đều lỗi hoặc hết hạn thì cũng như không. Mục này " +
      "theo dõi số tài khoản thật sự dùng được.",
    canGi: "Tài khoản chưa bị khoá, chưa hết hạn token.",
    mucDo: "bat-buoc",
    thuTu: 2,
    duong: "/accounts",
    nhom: "Nền tảng",
    tuKhoa: ["tài khoản lỗi", "hết hạn", "rate limit", "khoá"],
    daXong: (tt) => tt.soTaiKhoanSong > 0,
  },
  {
    id: "dia-chi-goc",
    ten: "Địa chỉ gốc (base URL)",
    mucDich:
      "Địa chỉ công khai của máy này. Ảnh, tệp và webhook đều dựng link từ đây — " +
      "để trống thì loa trong nhà và bot ngoài mạng không tải được nội dung.",
    canGi: "Tên miền hoặc IP mà thiết bị khác gọi tới được.",
    mucDo: "bat-buoc",
    thuTu: 3,
    duong: "/settings",
    nhom: "Nền tảng",
    tuKhoa: ["base url", "địa chỉ", "domain", "tên miền", "webhook", "link"],
    daXong: (tt) => coChu(lay(tt.config, "base_url")),
  },

  // ═══ Nên có — chạy được nhưng thiếu thì sớm muộn cũng gặp phiền ═══
  {
    id: "nha-cung-cap",
    ten: "Nhà cung cấp AI",
    mucDich:
      "Khai thêm nguồn model ngoài tài khoản ChatGPT: Gemini, NVIDIA NIM, OpenAI " +
      "chính chủ, hoặc máy chủ tự dựng. Nhiều nguồn thì một nguồn chết vẫn còn đường khác.",
    canGi: "API key của nhà cung cấp tương ứng.",
    mucDo: "nen-co",
    thuTu: 4,
    duong: "/providers",
    nhom: "Nền tảng",
    tuKhoa: ["provider", "nhà cung cấp", "api key", "gemini", "nvidia", "openai"],
    daXong: (tt) => coPhanTu(lay(tt.config, "providers")),
  },
  {
    id: "sao-luu",
    ten: "Sao lưu tự động",
    mucDich:
      "Đẩy cấu hình, tài khoản và nhật ký lên kho đám mây theo lịch. Mất máy hoặc " +
      "lỡ tay xoá thì còn đường khôi phục.",
    canGi: "Kho S3 hoặc Cloudflare R2 với khoá truy cập.",
    mucDo: "nen-co",
    thuTu: 5,
    duong: "/backup",
    nhom: "Nền tảng",
    tuKhoa: ["backup", "sao lưu", "khôi phục", "r2", "s3", "cloudflare"],
    daXong: (tt) => {
      const b = lay(tt.config, "backup");
      return !!(b && typeof b === "object" && (b as { enabled?: boolean }).enabled);
    },
  },
  {
    id: "proxy",
    ten: "Proxy",
    mucDich:
      "Định tuyến lời gọi ra ngoài qua proxy. Cần khi mạng nhà bị chặn hoặc muốn " +
      "tách IP cho từng nhóm tài khoản.",
    canGi: "Địa chỉ proxy dạng http:// hoặc socks5://.",
    mucDo: "tuy-chon",
    thuTu: 20,
    duong: "/settings",
    nhom: "Nền tảng",
    tuKhoa: ["proxy", "socks", "mạng", "ip", "vpn"],
    daXong: (tt) => coChu(lay(tt.config, "proxy")),
  },

  // ═══ Kênh trò chuyện ═══
  {
    id: "telegram",
    ten: "Bot Telegram",
    mucDich:
      "Nối bot Telegram để nhắn tin, gửi ảnh, nghe tin nhắn thoại và điều khiển " +
      "nhà ngay trong khung chat.",
    canGi: "Token bot lấy từ @BotFather, và địa chỉ gốc đã khai ở trên.",
    mucDo: "tuy-chon",
    thuTu: 21,
    duong: "/settings",
    nhom: "Kênh trò chuyện",
    tuKhoa: ["telegram", "bot", "botfather", "webhook", "chat"],
    daXong: (tt) => coChu(lay(tt.config, "telegram_webhook_url")),
  },
  {
    id: "zalo",
    ten: "Zalo Cá Nhân",
    mucDich:
      "Điều khiển tài khoản Zalo cá nhân qua bot server, trả lời tự động trong " +
      "khung chat thật của anh.",
    canGi: "Bot server zca-js chạy sẵn, đăng nhập bằng quét mã QR.",
    mucDo: "tuy-chon",
    thuTu: 22,
    duong: "/zalo",
    nhom: "Kênh trò chuyện",
    tuKhoa: ["zalo", "cá nhân", "zca", "qr", "chat"],
  },
  {
    id: "facebook",
    ten: "Facebook",
    mucDich: "Nhận và trả lời tin nhắn trang Facebook.",
    canGi: "App Facebook có quyền nhắn tin trang.",
    mucDo: "tuy-chon",
    thuTu: 23,
    duong: "/settings",
    nhom: "Kênh trò chuyện",
    tuKhoa: ["facebook", "messenger", "fanpage", "trang"],
    daXong: (tt) => coPhanTu(lay(tt.config, "facebook")),
  },

  // ═══ Nhà thông minh và giọng nói ═══
  {
    id: "home-assistant",
    ten: "Home Assistant",
    mucDich:
      "Nối tới hệ nhà thông minh để ra lệnh bằng lời: bật đèn, xem camera, đọc " +
      "cảm biến. Bot đọc lại trạng thái thiết bị sau khi ra lệnh nên biết lệnh có ăn không.",
    canGi: "Địa chỉ Home Assistant và token truy cập dài hạn.",
    mucDo: "tuy-chon",
    thuTu: 24,
    duong: "/settings",
    nhom: "Nhà thông minh",
    tuKhoa: ["home assistant", "nhà thông minh", "đèn", "thiết bị", "ha", "camera"],
    daXong: (tt) => coPhanTu(lay(tt.config, "home_assistant")),
  },
  {
    id: "giong-noi",
    ten: "Giọng nói (đọc và nghe)",
    mucDich:
      "Đọc câu trả lời thành tiếng ra loa trong nhà, và nghe tin nhắn thoại thành " +
      "chữ. Chạy hoàn toàn trên máy này, không gửi tiếng ra ngoài.",
    canGi:
      "Model nằm ngoài image, phải tải về volume bằng script trong scripts/ " +
      "(download_stt_model.py, download_piper_voices.py).",
    mucDo: "tuy-chon",
    thuTu: 25,
    duong: "/settings",
    nhom: "Nhà thông minh",
    tuKhoa: ["giọng nói", "tts", "stt", "loa", "đọc", "nghe", "voice", "piper", "whisper"],
  },

  // ═══ Công cụ ═══
  {
    id: "mcp",
    ten: "MCP Servers",
    mucDich:
      "Cắm thêm công cụ ngoài cho AI dùng: tra tài liệu, tìm kiếm, truy cập cơ sở " +
      "dữ liệu. Mỗi server là một bộ công cụ.",
    canGi: "Lệnh chạy server hoặc địa chỉ HTTP của nó.",
    mucDo: "tuy-chon",
    thuTu: 26,
    duong: "/mcp",
    nhom: "Công cụ",
    tuKhoa: ["mcp", "server", "công cụ", "tool", "context7"],
  },
  {
    id: "kho-dam-may",
    ten: "Kho đám mây (rclone)",
    mucDich:
      "Lưu ảnh và tệp lên Google Drive, OneDrive hoặc S3, rồi gửi lại được từ " +
      "khung chat bất kỳ lúc nào.",
    canGi: "Cấu hình rclone với ít nhất một remote.",
    mucDo: "tuy-chon",
    thuTu: 27,
    duong: "/settings",
    nhom: "Công cụ",
    tuKhoa: ["rclone", "drive", "kho", "đám mây", "lưu trữ", "onedrive", "s3"],
  },
  {
    id: "kiem-duyet",
    ten: "Kiểm duyệt nội dung",
    mucDich:
      "Cho một model đọc lại câu trả lời trước khi gửi, chặn nội dung không mong muốn.",
    canGi: "Một model riêng làm bộ kiểm (có thể dùng model rẻ).",
    mucDo: "tuy-chon",
    thuTu: 28,
    duong: "/settings",
    nhom: "Công cụ",
    tuKhoa: ["kiểm duyệt", "review", "lọc", "an toàn", "moderation"],
    daXong: (tt) => {
      const r = lay(tt.config, "ai_review");
      return !!(r && typeof r === "object" && (r as { enabled?: boolean }).enabled);
    },
  },
];

// ── Điều hướng: mọi trang đều tra được bằng Cmd+K ───────────────────────────

export type MucDieuHuong = {
  ten: string;
  duong: string;
  nhom: string;
  tuKhoa: string[];
};

export const TRANG: MucDieuHuong[] = [
  { ten: "Tổng quan", duong: "/", nhom: "Điều hướng", tuKhoa: ["dashboard", "trang chủ", "tổng quan", "thống kê"] },
  { ten: "Quản lý tài khoản", duong: "/accounts", nhom: "Điều hướng", tuKhoa: ["tài khoản", "account", "token"] },
  { ten: "Nhà cung cấp AI", duong: "/providers", nhom: "Điều hướng", tuKhoa: ["provider", "nhà cung cấp"] },
  { ten: "Models", duong: "/models", nhom: "Điều hướng", tuKhoa: ["model", "danh sách model"] },
  { ten: "Combos", duong: "/combos", nhom: "Điều hướng", tuKhoa: ["combo", "gộp model", "dự phòng"] },
  { ten: "MCP Servers", duong: "/mcp", nhom: "Điều hướng", tuKhoa: ["mcp", "công cụ"] },
  { ten: "Chat", duong: "/chat", nhom: "Điều hướng", tuKhoa: ["chat", "trò chuyện", "hỏi đáp"] },
  { ten: "Giáo viên", duong: "/teacher", nhom: "Điều hướng", tuKhoa: ["giáo viên", "dạy học", "chấm bài", "sgk"] },
  { ten: "Vẽ ảnh", duong: "/image", nhom: "Điều hướng", tuKhoa: ["ảnh", "vẽ", "image", "tạo ảnh"] },
  { ten: "Quản lý ảnh", duong: "/image-manager", nhom: "Điều hướng", tuKhoa: ["thư viện ảnh", "ảnh đã tạo"] },
  { ten: "Video", duong: "/video", nhom: "Điều hướng", tuKhoa: ["video", "tạo video"] },
  { ten: "Quản lý video", duong: "/video-manager", nhom: "Điều hướng", tuKhoa: ["thư viện video"] },
  { ten: "Dịch", duong: "/dich", nhom: "Điều hướng", tuKhoa: ["dịch", "translate", "phụ đề", "subtitle"] },
  { ten: "Tìm kiếm", duong: "/search", nhom: "Điều hướng", tuKhoa: ["tìm kiếm", "search", "web"] },
  { ten: "Zalo Cá Nhân", duong: "/zalo", nhom: "Điều hướng", tuKhoa: ["zalo"] },
  { ten: "Agent runs", duong: "/agent-runs", nhom: "Điều hướng", tuKhoa: ["agent", "lượt chạy", "run"] },
  { ten: "Sao lưu", duong: "/backup", nhom: "Điều hướng", tuKhoa: ["backup", "sao lưu", "khôi phục"] },
  { ten: "Cài đặt", duong: "/settings", nhom: "Điều hướng", tuKhoa: ["cài đặt", "settings", "cấu hình"] },
  { ten: "Nhật ký", duong: "/logs", nhom: "Điều hướng", tuKhoa: ["log", "nhật ký", "lỗi"] },
];

// ── Truy vấn ────────────────────────────────────────────────────────────────

export function timMuc(id: string): MucTinhNang | undefined {
  return SO_TRA.find((m) => m.id === id);
}

/** Mục CHƯA xong và kiểm được — đây là thứ hiện trong checklist. */
export function mucConThieu(tt: TrangThaiHeThong): MucTinhNang[] {
  if (!tt.daTai) return [];
  return SO_TRA.filter((m) => m.daXong && !m.daXong(tt)).sort((a, b) => a.thuTu - b.thuTu);
}

/** Đã cấu hình xong bao nhiêu trên tổng số kiểm được. */
export function tienDo(tt: TrangThaiHeThong): { xong: number; tong: number } {
  const kiemDuoc = SO_TRA.filter((m) => m.daXong);
  if (!tt.daTai) return { xong: 0, tong: kiemDuoc.length };
  return {
    xong: kiemDuoc.filter((m) => m.daXong!(tt)).length,
    tong: kiemDuoc.length,
  };
}

/** Còn thiếu thứ BẮT BUỘC nào không — quyết định trang chủ hiện checklist hay KPI. */
export function conThieuBatBuoc(tt: TrangThaiHeThong): boolean {
  return mucConThieu(tt).some((m) => m.mucDo === "bat-buoc");
}

export const NHAN_MUC_DO: Record<MucDo, string> = {
  "bat-buoc": "Bắt buộc",
  "nen-co": "Nên có",
  "tuy-chon": "Tuỳ chọn",
};
