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
 *    count trên UI Flow, không có ô resolution/fps nào được thao tác.
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
  "flow-quality": {
    providerType: "flow",
    badge: "Flow Veo Quality (Google)",
    resolutions: [],
    aspectRatios: FLOW_ASPECT_RATIOS,
    durations: [
      { value: "5", label: "5s" },
      { value: "8", label: "8s" },
    ],
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
    durations: [{ value: "5", label: "5s" }],
    fps: [],
    countOptions: [1, 2, 3, 4],
    baseCost: 10,
    supportsEndFrame: false,
    supportsSeed: false,
    supportsNegativePrompt: false,
  },
  "flow-omni": {
    providerType: "flow",
    badge: "Flow Omni Flash (Google)",
    resolutions: [],
    aspectRatios: FLOW_ASPECT_RATIOS,
    durations: [
      { value: "4", label: "4s" },
      { value: "6", label: "6s" },
      { value: "8", label: "8s" },
      { value: "10", label: "10s" },
    ],
    fps: [],
    countOptions: [1, 2, 3, 4],
    baseCost: 12,
    supportsEndFrame: true,
    supportsSeed: false,
    supportsNegativePrompt: false,
  },
  "flow-fast": {
    providerType: "flow",
    badge: "Flow Veo Fast (Google)",
    resolutions: [],
    aspectRatios: FLOW_ASPECT_RATIOS,
    durations: [
      { value: "5", label: "5s" },
      { value: "8", label: "8s" },
    ],
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

const FLOW_CREDIT_TABLE: Partial<Record<VideoBucket, number[]>> = {
  "flow-quality": [100, 200, 300, 400],
  "flow-fast": [20, 40, 60, 80],
  "flow-lite": [10, 20, 30, 40],
  "flow-omni": [12, 30, 45, 60],
};

export function getVideoCreditCost(modelId: string, count: number): number {
  const bucket = classifyVideoModel(modelId);
  const c = Math.max(1, Math.min(4, count || 1));
  const table = FLOW_CREDIT_TABLE[bucket];
  return table ? table[c - 1] : c * 15;
}

export const NO_VIDEO_PROVIDER_HINT =
  "Chưa có provider video nào được cấu hình — thêm tài khoản Flow hoặc provider Agnes ở tab Providers/Accounts trước.";
