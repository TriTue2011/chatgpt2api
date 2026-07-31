/**
 * Bảng thông số hỗ trợ theo từng model video — dùng để quyết định control nào
 * hiện/ẩn trong Studio Tạo Video và giá trị nào hợp lệ cho mỗi control.
 *
 * QUAN TRỌNG: các giá trị dưới đây được soi trực tiếp từ code backend thực sự
 * xử lý /v1/video/generations, KHÔNG suy đoán — model nào không thực sự nhận
 * một tham số thì control tương ứng bị ẩn (chứ không hiện disabled) để không
 * đánh lừa người dùng rằng đổi giá trị đó có tác dụng. Nguồn tham chiếu:
 *
 *  - api/veo_video.py (handle_video_generation) — bộ điều phối chính, quyết
 *    định model nào đi nhánh nào và param nào thực sự được forward xuống:
 *      • model bắt đầu "agnes/" (hoặc chứa "agnes") → agnes_provider.generate_video
 *        (forward đủ resolution/aspect_ratio/duration/fps/seed/negative_prompt).
 *      • model bắt đầu "flow/" → payload gửi captcha-solver CHỈ có
 *        prompt/model/aspect_ratio/duration/count/image/last_frame — KHÔNG có
 *        resolution/fps/seed/negative_prompt (bị bỏ hẳn, không forward).
 *      • còn lại → veo_adapter (Google Veo trực tiếp qua key gemini_free); n bị
 *        ép cứng về 1 ("Veo only supports 1 per request").
 *  - services/providers/agnes.py (AgnesProvider.generate_video) — xác nhận
 *    agnes-video-v2.0 nhận resolution/aspect_ratio/duration/frame_rate(fps)/
 *    seed/negative_prompt/keyframes.
 *  - captcha-solver/src/solvers/flow_google.py (flow_generate_video) — xác
 *    nhận phía captcha-solver cũng chỉ set dropdown model/aspect/duration/
 *    count trên UI Flow, không có ô resolution/fps nào được thao tác. Riêng
 *    hàng "Thời lượng" CHỈ tồn tại với Omni Flash: solver gác bằng
 *    `model_key.startswith("abra_")` và ghi log bỏ qua với ba model Veo.
 *  - services/image_providers/veo_video.py (VeoVideoAdapter._build_body) —
 *    nhánh Google Veo trực tiếp forward aspect_ratio/duration/resolution,
 *    KHÔNG có fps/seed/negative_prompt. Model "veo/…" hiện KHÔNG được route
 *    nào thêm vào /v1/models nên bucket này chưa xuất hiện trong dropdown
 *    thực tế, nhưng vẫn khai báo phòng khi được bật sau này.
 */

export type VideoOption = { value: string; label: string };

export type VideoProviderType = "flow" | "agnes" | "veo-direct" | "custom";

export interface VideoModelSpec {
  providerType: VideoProviderType;
  badge: string;
  resolutions: VideoOption[];
  aspectRatios: VideoOption[];
  durations: VideoOption[];
  fps: VideoOption[];
  countOptions: number[];
  baseCost: number;
  supportsEndFrame: boolean;
  supportsSeed: boolean;
  supportsNegativePrompt: boolean;
}

type VideoBucket = "flow-quality" | "flow-lite" | "flow-omni" | "flow-fast" | "agnes" | "veo-direct" | "custom";

/** Model id chứa "flow/" → dùng để đối chiếu với provider "flow" đã cấu hình
 * chưa (models-with-capabilities không tự lọc theo tài khoản Flow — xem
 * video/page.tsx, phần loadModels). */
export function isFlowVideoModel(modelId: string): boolean {
  return String(modelId || "").toLowerCase().includes("flow/");
}

function classifyVideoModel(modelId: string): VideoBucket {
  const mid = String(modelId || "").toLowerCase();
  if (mid.includes("agnes")) return "agnes";
  if (mid.includes("flow/")) {
    if (mid.includes("veo-3.1-quality")) return "flow-quality";
    if (mid.includes("veo-3.1-lite")) return "flow-lite";
    if (mid.includes("omni")) return "flow-omni";
    return "flow-fast";
  }
  if (mid.startsWith("veo/")) return "veo-direct";
  return "custom";
}

const ASPECT_16_9: VideoOption = { value: "16:9", label: "16:9 (Ngang)" };
const ASPECT_9_16: VideoOption = { value: "9:16", label: "9:16 (Dọc Shorts/Reels)" };
const FLOW_ASPECT_RATIOS: VideoOption[] = [ASPECT_16_9, ASPECT_9_16];

const SPECS: Record<VideoBucket, VideoModelSpec> = {
  // ── Ba model Veo: KHÔNG có hàng chọn thời lượng ────────────────────────
  // durations rỗng ⇒ tab Tạo Video ẩn hẳn ô "Thời lượng" cho các model này.
  // Trước đây khai 5s/8s (Quality, Fast) và 5s (Lite) — đều là giá trị TỰ ĐẶT,
  // không có trong giao diện Flow. Người dùng đổi 5s↔8s và tưởng video dài ra,
  // thực tế backend gửi xuống rồi solver không tìm thấy hàng đó nên bỏ qua.
  "flow-quality": {
    providerType: "flow",
    badge: "Flow Veo Quality (Google)",
    resolutions: [],
    aspectRatios: FLOW_ASPECT_RATIOS,
    durations: [],
    fps: [],
    countOptions: [1, 2, 3, 4],
    baseCost: 100,
    supportsEndFrame: true,
    supportsSeed: false,
    supportsNegativePrompt: false,
  },
  "flow-lite": {
    providerType: "flow",
    badge: "Flow Veo Lite (Google)",
    resolutions: [],
    aspectRatios: FLOW_ASPECT_RATIOS,
    durations: [],
    fps: [],
    countOptions: [1, 2, 3, 4],
    baseCost: 10,
    supportsEndFrame: true,
    supportsSeed: false,
    supportsNegativePrompt: false,
  },
  // Model DUY NHẤT có hàng chọn thời lượng, và tín dụng đổi theo thời lượng.
  "flow-omni": {
    providerType: "flow",
    badge: "Flow Omni Flash (Google)",
    resolutions: [],
    aspectRatios: FLOW_ASPECT_RATIOS,
    durations: [
      { value: "4", label: "4s — 7 tín dụng" },
      { value: "6", label: "6s — 10 tín dụng" },
      { value: "8", label: "8s — 12 tín dụng" },
      { value: "10", label: "10s — 15 tín dụng" },
    ],
    fps: [],
    countOptions: [1, 2, 3, 4],
    baseCost: 7,
    supportsEndFrame: true,
    supportsSeed: false,
    supportsNegativePrompt: false,
  },
  "flow-fast": {
    providerType: "flow",
    badge: "Flow Veo Fast (Google)",
    resolutions: [],
    aspectRatios: FLOW_ASPECT_RATIOS,
    durations: [],
    fps: [],
    countOptions: [1, 2, 3, 4],
    baseCost: 20,
    supportsEndFrame: true,
    supportsSeed: false,
    supportsNegativePrompt: false,
  },
  agnes: {
    providerType: "agnes",
    badge: "Agnes AI Async Engine",
    resolutions: [
      { value: "1080p", label: "1080p (FHD)" },
      { value: "720p", label: "720p (HD)" },
      { value: "480p", label: "480p (SD)" },
    ],
    aspectRatios: [
      ASPECT_16_9,
      ASPECT_9_16,
      { value: "1:1", label: "1:1 (Vuông)" },
      { value: "4:3", label: "4:3 (Tiêu chuẩn)" },
      { value: "3:4", label: "3:4 (Chân dung)" },
    ],
    durations: [
      { value: "5", label: "5s" },
      { value: "8", label: "8s" },
      { value: "10", label: "10s" },
      { value: "18", label: "18s" },
    ],
    fps: [
      { value: "24", label: "24 fps (Điện ảnh)" },
      { value: "30", label: "30 fps (Mượt mà)" },
      { value: "60", label: "60 fps (Siêu mượt)" },
    ],
    // Agnes tạo 1 video/lần gọi (engine async single-shot, không có tham số
    // batch) — xem services/providers/agnes.py: generate_video() không nhận n.
    countOptions: [1],
    baseCost: 15,
    supportsEndFrame: true,
    supportsSeed: true,
    supportsNegativePrompt: true,
  },
  "veo-direct": {
    providerType: "veo-direct",
    badge: "Google Veo Direct (Gemini API Key)",
    resolutions: [
      { value: "1080p", label: "1080p (FHD)" },
      { value: "720p", label: "720p (HD)" },
    ],
    aspectRatios: FLOW_ASPECT_RATIOS,
    durations: [
      { value: "4", label: "4s" },
      { value: "6", label: "6s" },
      { value: "8", label: "8s" },
    ],
    fps: [],
    // api/veo_video.py ép n = max(1, min(1, n)) cho nhánh Veo trực tiếp.
    countOptions: [1],
    baseCost: 20,
    supportsEndFrame: true,
    supportsSeed: false,
    supportsNegativePrompt: false,
  },
  custom: {
    providerType: "custom",
    badge: "Custom Provider Engine",
    resolutions: [
      { value: "1080p", label: "1080p (FHD)" },
      { value: "720p", label: "720p (HD)" },
      { value: "480p", label: "480p (SD)" },
    ],
    aspectRatios: [
      ASPECT_16_9,
      ASPECT_9_16,
      { value: "1:1", label: "1:1 (Vuông)" },
      { value: "4:3", label: "4:3 (Tiêu chuẩn)" },
      { value: "3:4", label: "3:4 (Chân dung)" },
    ],
    durations: [
      { value: "5", label: "5s" },
      { value: "8", label: "8s" },
      { value: "10", label: "10s" },
    ],
    fps: [
      { value: "24", label: "24 fps (Điện ảnh)" },
      { value: "30", label: "30 fps (Mượt mà)" },
    ],
    // Chưa rõ khả năng batch của provider tùy biến khác → an toàn 1.
    countOptions: [1],
    baseCost: 15,
    supportsEndFrame: true,
    supportsSeed: true,
    supportsNegativePrompt: true,
  },
};

export function getVideoModelSpec(modelId: string): VideoModelSpec {
  return SPECS[classifyVideoModel(modelId)];
}

/**
 * Tín dụng Flow cho MỘT video, đọc từ dòng "Quá trình tạo sẽ tốn N tín dụng"
 * trên chính giao diện Flow (chủ máy chụp qua noVNC 31/07/2026). Chọn x2/x3/x4
 * thì nhân lên theo số video.
 *
 *   Omni Flash          4s → 7    6s → 10    8s → 12    10s → 15
 *   Veo 3.1 - Lite      10   (không có hàng chọn thời lượng)
 *   Veo 3.1 - Fast      20   (không có hàng chọn thời lượng)
 *   Veo 3.1 - Quality   100  (không có hàng chọn thời lượng)
 *
 * Bảng cũ [12, 30, 45, 60] cho Omni Flash là số TỰ ĐẶT: 12 là giá của 8s, còn
 * 30/45/60 không phải bội của bất kỳ mức nào. Nay tính = giá-mỗi-video × số bản.
 */
const OMNI_CREDIT_BY_DURATION: Record<string, number> = {
  "4": 7,
  "6": 10,
  "8": 12,
  "10": 15,
};

const FLOW_CREDIT_PER_VIDEO: Partial<Record<VideoBucket, number>> = {
  "flow-quality": 100,
  "flow-fast": 20,
  "flow-lite": 10,
};

/** Giá mỗi video của model (Omni Flash phụ thuộc thời lượng). */
export function getVideoCreditPerClip(modelId: string, duration?: string): number {
  const bucket = classifyVideoModel(modelId);
  if (bucket === "flow-omni") {
    return OMNI_CREDIT_BY_DURATION[String(duration ?? "4")] ?? 7;
  }
  return FLOW_CREDIT_PER_VIDEO[bucket] ?? 15;
}

export function getVideoCreditCost(modelId: string, count: number, duration?: string): number {
  const c = Math.max(1, Math.min(4, count || 1));
  return getVideoCreditPerClip(modelId, duration) * c;
}

/** Model có tính bằng "tín dụng" Flow không. Agnes/Veo-direct/custom KHÔNG —
 * chúng tiêu hạn mức của tài khoản hoặc khoá API riêng, nên hiện một con số
 * "tín dụng" cho chúng là bịa. */
export function usesFlowCredits(modelId: string): boolean {
  return classifyVideoModel(modelId).startsWith("flow-");
}

/** Câu mô tả chi phí để hiện trên giao diện — không bịa số cho provider
 * không có bảng giá tín dụng. */
export function getVideoCostLabel(modelId: string, count: number, duration?: string): string {
  if (usesFlowCredits(modelId)) {
    return `${getVideoCreditCost(modelId, count, duration)} tín dụng`;
  }
  switch (classifyVideoModel(modelId)) {
    case "agnes":
      return "tính vào hạn mức tài khoản Agnes (không dùng tín dụng Flow)";
    case "veo-direct":
      return "tính vào hạn mức khoá Gemini API";
    default:
      return "tính vào hạn mức của provider";
  }
}

export const NO_VIDEO_PROVIDER_HINT =
  "Chưa có provider video nào được cấu hình — thêm tài khoản Flow hoặc provider Agnes ở tab Providers/Accounts trước.";
