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
  /** Đọc được /api/settings chưa. Người dùng thường không có quyền. */
  coConfig: boolean;
  /** Đọc được /api/v1/health chưa. */
  coHealth: boolean;
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
  /**
   * Phép kiểm cần dữ liệu từ đâu. Thiếu nguồn thì mục bị BỎ QUA chứ không bị
   * coi là "còn thiếu" — /api/v1/health có thể tốn tới 30 giây ở lần gọi nguội
   * (api/system.py:1099 mô tả ~16 lời gọi HTTP tuần tự), và lúc nó chưa về mà
   * đã kết luận thì màn hình báo đỏ "chưa có tài khoản nào" trên một hệ thống
   * đầy tài khoản đang chạy tốt.
   */
  nguon?: "config" | "health";
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
    nguon: "health",
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
    nguon: "health",
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
    duong: "/settings?tim=cấu%20hình%20hệ%20thống",
    nhom: "Nền tảng",
    tuKhoa: ["base url", "địa chỉ", "domain", "tên miền", "webhook", "link"],
    // KHÔNG kiểm được từ đây. `Config.base_url` là property giải theo thứ tự
    // biến môi trường CHATGPT2API_BASE_URL → data["base_url"] → options.json
    // của HA add-on (services/config.py:1168), mà /api/settings chỉ trả `data`
    // thô. Máy khai bằng env sẽ bị báo thiếu vĩnh viễn, nên thà không kiểm.
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
    // Không đếm được bằng "providers có rỗng không": services/config.py:1272 tự
    // chèn providers.flow.captcha_solver_url mặc định, nên nó KHÔNG BAO GIỜ rỗng
    // và phép kiểm cũ luôn báo xong ngay trên máy vừa cài. Chỉ tính nhà cung cấp
    // do người dùng thật sự khai, tức khác `flow`.
    daXong: (tt) => {
      const pv = lay(tt.config, "providers");
      if (!pv || typeof pv !== "object") return false;
      return Object.keys(pv as Record<string, unknown>).some((k) => k !== "flow");
    },
    nguon: "config",
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
    duong: "/settings?tim=sao%20lưu",
    nhom: "Nền tảng",
    tuKhoa: ["backup", "sao lưu", "khôi phục", "r2", "s3", "cloudflare"],
    daXong: (tt) => {
      const b = lay(tt.config, "backup");
      return !!(b && typeof b === "object" && (b as { enabled?: boolean }).enabled);
    },
    nguon: "config",
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
    duong: "/settings?tim=proxy",
    nhom: "Nền tảng",
    tuKhoa: ["proxy", "socks", "mạng", "ip", "vpn"],
    daXong: (tt) => coChu(lay(tt.config, "proxy")),
    nguon: "config",
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
    duong: "/settings?tim=telegram%20%2F%20zalo&tab=tg",
    nhom: "Kênh trò chuyện",
    tuKhoa: ["telegram", "bot", "botfather", "webhook", "chat"],
    daXong: (tt) => coChu(lay(tt.config, "telegram_webhook_url")),
    nguon: "config",
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
    // /zalo chỉ là stub redirect sang /settings (giữ cho link cũ không chết),
    // nên trỏ thẳng đích để người dùng không đi hai chặng.
    duong: "/settings?tim=telegram%20%2F%20zalo&tab=zalop",
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
    duong: "/settings?tim=facebook",
    nhom: "Kênh trò chuyện",
    tuKhoa: ["facebook", "messenger", "fanpage", "trang"],
    daXong: (tt) => coPhanTu(lay(tt.config, "facebook")),
    nguon: "config",
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
    duong: "/settings?tim=home%20assistant",
    nhom: "Nhà thông minh",
    tuKhoa: ["home assistant", "nhà thông minh", "đèn", "thiết bị", "ha", "camera"],
    daXong: (tt) => coPhanTu(lay(tt.config, "home_assistant")),
    nguon: "config",
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
    duong: "/settings?tim=giọng%20nói",
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
    duong: "/settings?tim=kho%20lưu%20trữ",
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
    duong: "/settings?tim=cấu%20hình%20hệ%20thống",
    nhom: "Công cụ",
    tuKhoa: ["kiểm duyệt", "review", "lọc", "an toàn", "moderation"],
    daXong: (tt) => {
      const r = lay(tt.config, "ai_review");
      return !!(r && typeof r === "object" && (r as { enabled?: boolean }).enabled);
    },
    nguon: "config",
  },
  // ═══ Bổ sung: tính năng ĐANG DÙNG THẬT mà sổ tra chưa có ═══
  // Danh sách rút từ config của máy chủ đang chạy (120 khoá), không phải đoán.
  {
    id: "zalo-bot",
    ten: "Zalo Bot (Official Account)",
    mucDich:
      "Bot Zalo chính chủ trả lời trong Official Account. Khác Zalo Cá Nhân ở chỗ " +
      "không cần quét mã QR và không dùng tài khoản riêng của anh.",
    canGi: "Token bot lấy từ Zalo Developers và Chat ID của nhóm.",
    mucDo: "tuy-chon",
    thuTu: 21,
    duong: "/settings?tim=telegram%20%2F%20zalo&tab=zalo",
    nhom: "Kênh trò chuyện",
    tuKhoa: ["zalo bot", "official account", "oa", "token", "kênh"],
    daXong: (tt) => coPhanTu(lay(tt.config, "zalo_bots")),
    nguon: "config",
  },
  {
    id: "email-lich",
    ten: "Email và Lịch",
    mucDich:
      "Đọc hộp thư và lịch để trả lời trong chat: hỏi 'hôm nay có lịch gì', " +
      "'có thư mới không' là bot tra thẳng.",
    canGi: "Tài khoản IMAP/SMTP (Gmail cần mật khẩu ứng dụng) hoặc link lịch ICS.",
    mucDo: "tuy-chon",
    thuTu: 24,
    duong: "/settings?tim=email",
    nhom: "Kênh trò chuyện",
    tuKhoa: ["email", "imap", "smtp", "gmail", "lịch", "calendar", "ics"],
    daXong: (tt) => coPhanTu(lay(tt.config, "email_accounts")) || coPhanTu(lay(tt.config, "calendars")),
    nguon: "config",
  },
  {
    id: "custom-providers",
    ten: "Nhà cung cấp tự thêm",
    mucDich:
      "Nối bất kỳ dịch vụ nào nói chuẩn OpenAI: máy chạy Ollama ở nhà, dịch vụ " +
      "mua ngoài, hay endpoint của chính anh.",
    canGi: "Địa chỉ API và khoá (nếu dịch vụ đó đòi).",
    mucDo: "tuy-chon",
    thuTu: 12,
    duong: "/settings?tim=custom%20providers",
    nhom: "Model và định tuyến",
    tuKhoa: ["custom", "provider", "ollama", "openai compatible", "endpoint", "tự thêm"],
    daXong: (tt) => coPhanTu(lay(tt.config, "custom_providers")),
    nguon: "config",
  },
  {
    id: "tokenrouter",
    ten: "TokenRouter",
    mucDich:
      "Đường gọi riêng có tự thử lại khi mạng lỗi, dùng khi nhà mạng chặn hoặc " +
      "đường thẳng hay rớt.",
    canGi: "Khoá TokenRouter.",
    mucDo: "tuy-chon",
    thuTu: 13,
    duong: "/settings?tim=tokenrouter",
    nhom: "Model và định tuyến",
    tuKhoa: ["tokenrouter", "định tuyến", "retry", "thử lại", "proxy api"],
    daXong: (tt) => coPhanTu(lay(tt.config, "tokenrouter")),
    nguon: "config",
  },
  {
    id: "combo-model",
    ten: "Mô hình kết hợp (combo)",
    mucDich:
      "Gộp nhiều model thành một tên gọi: cái đầu hỏng thì tự rơi sang cái sau, " +
      "người dùng không thấy gián đoạn.",
    canGi: "Ít nhất hai model đang chạy được.",
    mucDo: "nen-co",
    thuTu: 14,
    duong: "/combos",
    nhom: "Model và định tuyến",
    tuKhoa: ["combo", "kết hợp", "fallback", "dự phòng", "chuỗi model"],
    daXong: (tt) => coPhanTu(lay(tt.config, "combo_models")),
    nguon: "config",
  },
  {
    id: "nhanh-agent",
    ten: "Nhánh agent theo kênh",
    mucDich:
      "Mỗi kênh dùng một bộ tính cách và công cụ riêng: nhóm gia đình khác nhóm " +
      "công việc, không lẫn lộn.",
    canGi: "Đã có ít nhất một kênh chat chạy.",
    mucDo: "tuy-chon",
    thuTu: 25,
    duong: "/settings?tim=telegram%20%2F%20zalo&tab=tg",
    nhom: "Model và định tuyến",
    tuKhoa: ["nhánh", "agent", "branch", "tính cách", "persona", "theo kênh"],
    daXong: (tt) => coPhanTu(lay(tt.config, "agent_branches")),
    nguon: "config",
  },
  {
    id: "dich",
    ten: "Dịch thuật",
    mucDich:
      "Dịch chữ, tài liệu, phụ đề YouTube bằng máy dịch trong stack — không tốn " +
      "lượt gọi AI.",
    canGi: "Máy dịch trong stack (đã có sẵn) hoặc bật thêm Google Dịch để đối chiếu.",
    mucDo: "tuy-chon",
    thuTu: 30,
    duong: "/dich",
    nhom: "Tiện ích",
    tuKhoa: ["dịch", "translate", "phụ đề", "youtube", "ngôn ngữ"],
    daXong: (tt) => coPhanTu(lay(tt.config, "dich")) || coPhanTu(lay(tt.config, "dich_llm")),
    nguon: "config",
  },
  {
    id: "tim-kiem",
    ten: "Tìm kiếm web",
    mucDich:
      "Cho bot tra Internet khi câu hỏi vượt ngoài hiểu biết sẵn có: tin mới, giá " +
      "cả, tra cứu chuyên ngành.",
    canGi: "Dịch vụ tìm kiếm (SearXNG có sẵn trong stack).",
    mucDo: "nen-co",
    thuTu: 26,
    duong: "/search",
    nhom: "Tiện ích",
    tuKhoa: ["tìm kiếm", "search", "searxng", "web", "tra cứu"],
    daXong: (tt) => coPhanTu(lay(tt.config, "search")),
    nguon: "config",
  },
  {
    id: "giao-vien",
    ten: "Giáo viên (lớp 1–12)",
    mucDich:
      "Dạy và chấm bài theo sách giáo khoa: ra đề, giải thích, theo dõi tiến bộ " +
      "từng học sinh.",
    canGi: "Chọn bộ sách và lớp trong phần Giáo viên.",
    mucDo: "tuy-chon",
    thuTu: 31,
    duong: "/teacher",
    nhom: "Tiện ích",
    tuKhoa: ["giáo viên", "dạy học", "sgk", "chấm bài", "học sinh", "lớp"],
    daXong: (tt) => coPhanTu(lay(tt.config, "teacher")),
    nguon: "config",
  },
  {
    id: "nhat-ky-chat",
    ten: "Nhật ký hội thoại",
    mucDich:
      "Lưu lại các cuộc chat để xem lại và tra cứu. Tắt đi thì không có gì để đối " +
      "chiếu khi bot trả lời sai.",
    canGi: "Không cần gì thêm.",
    mucDo: "nen-co",
    thuTu: 27,
    duong: "/settings?tim=telegram%20%2F%20zalo&tab=nhatky",
    nhom: "Tiện ích",
    tuKhoa: ["nhật ký", "log", "lịch sử", "hội thoại", "chatlog"],
    daXong: (tt) => coPhanTu(lay(tt.config, "chatlog_settings")),
    nguon: "config",
  },
  {
    id: "camera",
    ten: "Camera",
    mucDich:
      "Cho bot xem hình từ camera trong nhà: hỏi 'ngoài cổng có ai không' là nó " +
      "chụp và mô tả lại.",
    canGi: "Camera đã có trong Home Assistant hoặc địa chỉ RTSP.",
    mucDo: "tuy-chon",
    thuTu: 33,
    duong: "/settings?tim=home%20assistant&tab=camera",
    nhom: "Nhà thông minh",
    tuKhoa: ["camera", "rtsp", "hình ảnh", "giám sát", "quan sát"],
    daXong: (tt) => coPhanTu(lay(tt.config, "cameras")),
    nguon: "config",
  },
  {
    id: "mqtt",
    ten: "Thiết bị qua MQTT",
    mucDich:
      "Bot đọc trạng thái và bật/tắt thiết bị THẲNG qua MQTT — dùng được cả khi " +
      "nhà không cài Home Assistant.",
    canGi: "Một máy chủ MQTT đang chạy (EMQX, Mosquitto…) và địa chỉ của nó.",
    mucDo: "tuy-chon",
    thuTu: 34,
    duong: "/settings?tim=home%20assistant&tab=mqtt",
    nhom: "Nhà thông minh",
    tuKhoa: ["mqtt", "emqx", "mosquitto", "zigbee", "thiết bị", "broker"],
    // lay() chỉ đọc khoá PHẲNG (xem định nghĩa ở trên), nên "mqtt.host" luôn
    // trả undefined. Lấy object rồi đọc host bên trong.
    daXong: (tt) => coChu((lay(tt.config, "mqtt") as { host?: unknown } | undefined)?.host),
    nguon: "config",
  },
  {
    id: "cloudflare",
    ten: "Cloudflare Tunnel",
    mucDich:
      "Mở một địa chỉ HTTPS ra Internet mà không cần mở cổng router — webhook của " +
      "Telegram và Zalo cần địa chỉ này.",
    canGi: "Token tunnel lấy từ trang Cloudflare Zero Trust.",
    mucDo: "nen-co",
    thuTu: 8,
    duong: "/settings?tim=cloudflare",
    nhom: "Nền tảng",
    tuKhoa: ["cloudflare", "tunnel", "https", "webhook", "tên miền", "ngrok"],
    daXong: (tt) => coChu(lay(tt.config, "cloudflare_tunnel_token")),
    nguon: "config",
  },
  {
    id: "khoa-nguoi-dung",
    ten: "Khoá cho người dùng thường",
    mucDich:
      "Cấp khoá riêng cho người khác dùng, chỉ vào được trang vẽ ảnh — không thấy " +
      "tài khoản và cấu hình của anh.",
    canGi: "Không cần gì thêm.",
    mucDo: "tuy-chon",
    thuTu: 9,
    duong: "/settings?tim=khóa%20người%20dùng",
    nhom: "Nền tảng",
    tuKhoa: ["khoá", "api key", "người dùng", "phân quyền", "chia sẻ"],
    daXong: (tt) => coPhanTu(lay(tt.config, "user_keys")),
    nguon: "config",
  },
  {
    id: "workspace-trinh-duyet",
    ten: "Workspace trình duyệt",
    mucDich:
      "Hồ sơ đăng nhập riêng cho từng tài khoản Google, dùng lại được cho Flow, " +
      "ChatGPT, Gemini và Claude — đăng nhập một lần dùng chung.",
    canGi: "Dịch vụ captcha-solver đang chạy (có sẵn trong stack).",
    mucDo: "tuy-chon",
    thuTu: 10,
    duong: "/settings?tim=workspace",
    nhom: "Nền tảng",
    tuKhoa: ["workspace", "profile", "trình duyệt", "google", "đăng nhập", "session"],
  },
  {
    id: "provider-google",
    ten: "Provider qua tài khoản Google",
    mucDich:
      "Đăng nhập Google một lần rồi tái dùng cho Google Labs Flow, ChatGPT, " +
      "Gemini Web API và Claude — không phải khai token từng cái.",
    canGi: "Một tài khoản Google và workspace trình duyệt ở trên.",
    mucDo: "tuy-chon",
    thuTu: 11,
    duong: "/settings?tim=provider%20qua%20tài%20khoản%20google",
    nhom: "Nền tảng",
    tuKhoa: ["google", "oauth", "flow", "gemini", "claude", "tái dùng", "sso"],
  },
  {
    id: "mcp-hub",
    ten: "Bộ công cụ MCP có sẵn",
    mucDich:
      "Hơn 30 công cụ tra cứu dựng sẵn trong stack: PubMed, PubChem, sách " +
      "Gutenberg, tra cứu tiếng Việt — bot gọi khi cần.",
    canGi: "Không cần gì thêm, chạy sẵn cùng hệ thống.",
    mucDo: "tuy-chon",
    thuTu: 29,
    duong: "/mcp",
    nhom: "Công cụ",
    tuKhoa: ["mcp", "công cụ", "tra cứu", "pubmed", "hub", "tool"],
    daXong: (tt) => coChu(lay(tt.config, "mcp_hub_url")),
    nguon: "config",
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

/** Nguồn dữ liệu của mục này đã về chưa. Chưa về thì không kết luận gì. */
function coNguon(m: MucTinhNang, tt: TrangThaiHeThong): boolean {
  if (!m.daXong) return false;
  if (m.nguon === "health") return tt.coHealth;
  if (m.nguon === "config") return tt.coConfig;
  return false;
}

/** Mục kiểm được ngay lúc này (đủ nguồn dữ liệu). */
function mucKiemDuoc(tt: TrangThaiHeThong): MucTinhNang[] {
  return SO_TRA.filter((m) => coNguon(m, tt));
}

/** Mục CHƯA xong và kiểm được — đây là thứ hiện trong checklist. */
export function mucConThieu(tt: TrangThaiHeThong): MucTinhNang[] {
  return mucKiemDuoc(tt)
    .filter((m) => !m.daXong!(tt))
    .sort((a, b) => a.thuTu - b.thuTu);
}

/** Đã cấu hình xong bao nhiêu trên tổng số kiểm được. */
export function tienDo(tt: TrangThaiHeThong): { xong: number; tong: number } {
  const kiemDuoc = mucKiemDuoc(tt);
  return {
    xong: kiemDuoc.filter((m) => m.daXong!(tt)).length,
    tong: kiemDuoc.length,
  };
}

/** Còn thiếu thứ BẮT BUỘC nào không — quyết định trang chủ hiện checklist hay KPI. */
export function conThieuBatBuoc(tt: TrangThaiHeThong): boolean {
  return mucConThieu(tt).some((m) => m.mucDo === "bat-buoc");
}

/** Mục đã cấu hình xong — dùng cho phần "xem mục đã xong". */
export function mucDaXong(tt: TrangThaiHeThong): MucTinhNang[] {
  return mucKiemDuoc(tt).filter((m) => m.daXong!(tt));
}

export const NHAN_MUC_DO: Record<MucDo, string> = {
  "bat-buoc": "Bắt buộc",
  "nen-co": "Nên có",
  "tuy-chon": "Tuỳ chọn",
};
