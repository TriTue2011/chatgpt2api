"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Video, LoaderCircle, Play, Download, Settings2, Sparkles, Image as ImageIcon } from "lucide-react";
import { toast } from "sonner";

import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface VideoModel {
  id: string;
  label: string;
  provider?: string;
  baseCost?: number;
}

const DEFAULT_VIDEO_MODELS: VideoModel[] = [
  { id: "agnes/agnes-video-v2.0", label: "✨ Agnes Video v2.0 (Full Async)", baseCost: 15 },
  { id: "flow/veo-3.1-fast", label: "⚡ Veo 3.1 - Fast", baseCost: 20 },
  { id: "flow/veo-3.1-lite", label: "Veo 3.1 - Lite", baseCost: 10 },
  { id: "flow/veo-3.1-quality", label: "Veo 3.1 - Quality", baseCost: 100 },
  { id: "flow/omni-flash", label: "Omni Flash", baseCost: 12 },
];

const getVideoCreditCost = (modelId: string, count: number): number => {
  const mid = String(modelId || "").toLowerCase();
  const c = Math.max(1, Math.min(4, count));
  if (mid.includes("veo-3.1-quality")) {
    return [100, 200, 300, 400][c - 1];
  }
  if (mid.includes("veo-3.1-fast")) {
    return [20, 40, 60, 80][c - 1];
  }
  if (mid.includes("veo-3.1-lite")) {
    return [10, 20, 30, 40][c - 1];
  }
  if (mid.includes("omni")) {
    return [12, 30, 45, 60][c - 1];
  }
  return c * 15;
};

const getModelConfig = (modelId: string) => {
  const mid = String(modelId || "").toLowerCase();
  
  if (mid.startsWith("flow/") || mid.includes("flow/")) {
    if (mid.includes("veo-3.1-quality")) {
      return {
        providerType: "flow",
        badge: "Flow Veo Quality (Google)",
        resolutions: [
          { value: "1080p", label: "1080p (FHD - Chuẩn Veo Quality)" },
        ],
        aspectRatios: [
          { value: "16:9", label: "16:9 (Ngang)" },
          { value: "9:16", label: "9:16 (Dọc Shorts/Reels)" },
        ],
        durations: [
          { value: "5", label: "5s (81 frames)" },
          { value: "8", label: "8s (121 frames)" },
        ],
        fps: [
          { value: "24", label: "24 fps (Tốc độ gốc Veo)" },
        ],
        baseCost: 100,
        supportsEndFrame: true,
        supportsSeed: false,
        supportsNegativePrompt: false,
      };
    }
    
    if (mid.includes("veo-3.1-lite")) {
      return {
        providerType: "flow",
        badge: "Flow Veo Lite (Google)",
        resolutions: [
          { value: "720p", label: "720p (HD - Chuẩn Veo Lite)" },
        ],
        aspectRatios: [
          { value: "16:9", label: "16:9 (Ngang)" },
          { value: "9:16", label: "9:16 (Dọc Shorts/Reels)" },
        ],
        durations: [
          { value: "5", label: "5s (81 frames)" },
        ],
        fps: [
          { value: "24", label: "24 fps (Tốc độ gốc Veo)" },
        ],
        baseCost: 10,
        supportsEndFrame: false,
        supportsSeed: false,
        supportsNegativePrompt: false,
      };
    }

    if (mid.includes("omni")) {
      return {
        providerType: "flow",
        badge: "Flow Omni Flash (Google)",
        resolutions: [
          { value: "720p", label: "720p (HD - Chuẩn Omni)" },
          { value: "1080p", label: "1080p (FHD)" },
        ],
        aspectRatios: [
          { value: "16:9", label: "16:9 (Ngang)" },
          { value: "9:16", label: "9:16 (Dọc Shorts/Reels)" },
        ],
        durations: [
          { value: "4", label: "4s (61 frames)" },
          { value: "6", label: "6s (97 frames)" },
          { value: "8", label: "8s (121 frames)" },
          { value: "10", label: "10s (241 frames)" },
        ],
        fps: [
          { value: "24", label: "24 fps (Tốc độ gốc Omni)" },
        ],
        baseCost: 12,
        supportsEndFrame: true,
        supportsSeed: false,
        supportsNegativePrompt: false,
      };
    }

    // Default Flow Veo Fast / Standard
    return {
      providerType: "flow",
      badge: "Flow Veo Fast (Google)",
      resolutions: [
        { value: "1080p", label: "1080p (FHD - Chuẩn Veo Fast)" },
        { value: "720p", label: "720p (HD)" },
      ],
      aspectRatios: [
        { value: "16:9", label: "16:9 (Ngang)" },
        { value: "9:16", label: "9:16 (Dọc Shorts/Reels)" },
        ],
      durations: [
        { value: "5", label: "5s (81 frames)" },
        { value: "8", label: "8s (121 frames)" },
      ],
      fps: [
        { value: "24", label: "24 fps (Tốc độ gốc Veo)" },
      ],
      baseCost: 20,
      supportsEndFrame: true,
      supportsSeed: false,
      supportsNegativePrompt: false,
    };
  }

  if (mid.includes("agnes")) {
    return {
      providerType: "agnes",
      badge: "Agnes AI Async Engine",
      resolutions: [
        { value: "1080p", label: "1080p (FHD)" },
        { value: "720p", label: "720p (HD)" },
        { value: "480p", label: "480p (SD)" },
      ],
      aspectRatios: [
        { value: "16:9", label: "16:9 (Ngang)" },
        { value: "9:16", label: "9:16 (Dọc Shorts/Reels)" },
        { value: "1:1", label: "1:1 (Vuông)" },
        { value: "4:3", label: "4:3 (Tiêu chuẩn)" },
        { value: "3:4", label: "3:4 (Chân dung)" },
      ],
      durations: [
        { value: "5", label: "5s (81 frames)" },
        { value: "8", label: "8s (121 frames)" },
        { value: "10", label: "10s (241 frames)" },
        { value: "18", label: "18s (441 frames)" },
      ],
      fps: [
        { value: "24", label: "24 fps (Điện ảnh)" },
        { value: "30", label: "30 fps (Mượt mà)" },
        { value: "60", label: "60 fps (Siêu mượt)" },
      ],
      baseCost: 15,
      supportsEndFrame: true,
      supportsSeed: true,
      supportsNegativePrompt: true,
    };
  }

  // Custom Provider Video Models
  return {
    providerType: "custom",
    badge: "Custom Provider Engine",
    resolutions: [
      { value: "1080p", label: "1080p (FHD)" },
      { value: "720p", label: "720p (HD)" },
      { value: "480p", label: "480p (SD)" },
    ],
    aspectRatios: [
      { value: "16:9", label: "16:9 (Ngang)" },
      { value: "9:16", label: "9:16 (Dọc Shorts/Reels)" },
      { value: "1:1", label: "1:1 (Vuông)" },
      { value: "4:3", label: "4:3 (Tiêu chuẩn)" },
      { value: "3:4", label: "3:4 (Chân dung)" },
    ],
    durations: [
      { value: "5", label: "5s (81 frames)" },
      { value: "8", label: "8s (121 frames)" },
      { value: "10", label: "10s (241 frames)" },
    ],
    fps: [
      { value: "24", label: "24 fps (Điện ảnh)" },
      { value: "30", label: "30 fps (Mượt mà)" },
    ],
    baseCost: 15,
    supportsEndFrame: true,
    supportsSeed: true,
    supportsNegativePrompt: true,
  };
};

export default function VideoPage() {
  const { session } = useAuthGuard(["admin", "user"]);
  const router = useRouter();

  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [aspectRatio, setAspectRatio] = useState("16:9");
  const [duration, setDuration] = useState("5");
  const [resolution, setResolution] = useState("1080p");
  const [fps, setFps] = useState("24");
  const [seed, setSeed] = useState("");
  const [model, setModel] = useState("agnes/agnes-video-v2.0");
  const [count, setCount] = useState("1");
  const [startImage, setStartImage] = useState<string | null>(null);
  const [endImage, setEndImage] = useState<string | null>(null);
  
  const [videoModels, setVideoModels] = useState<VideoModel[]>(DEFAULT_VIDEO_MODELS);
  const [generating, setGenerating] = useState(false);
  const [resultVideoUrl, setResultVideoUrl] = useState<string | null>(null);
  const [resultB64, setResultB64] = useState<string | null>(null);
  const [error, setError] = useState("");

  const isAgnesModel = model.toLowerCase().includes("agnes");
  const modelConfig = useMemo(() => getModelConfig(model), [model]);

  // Sync duration, resolution, fps when model changes if current selection is not available
  useEffect(() => {
    if (!modelConfig.durations.some((d) => d.value === duration)) {
      setDuration(modelConfig.durations[0]?.value || "5");
    }
    if (!modelConfig.resolutions.some((r) => r.value === resolution)) {
      setResolution(modelConfig.resolutions[0]?.value || "1080p");
    }
    if (!modelConfig.fps.some((f) => f.value === fps)) {
      setFps(modelConfig.fps[0]?.value || "24");
    }
  }, [model, modelConfig]);

  useEffect(() => {
    async function loadModels() {
      try {
        const resp = await request.get("/api/v1/models-with-capabilities");
        const models = ((resp.data as any)?.models || []) as any[];
        const vModels = models
          .filter((m: any) => 
            (m.capabilities || []).includes("video_gen") &&
            m.enabled !== false && !String(m.id).includes(":")
          )
          .map((m: any) => {
            const cfg = getModelConfig(m.id);
            let labelName = m.id;
            if (m.id.includes("agnes")) labelName = `✨ ${m.id} (Agnes Async Video)`;
            else if (m.owned_by && String(m.owned_by).includes("custom")) labelName = `🎬 ${m.id} (${String(m.owned_by).replace("custom:", "")})`;
            return {
              id: m.id,
              label: labelName,
              baseCost: cfg.baseCost,
            };
          });

        if (vModels.length > 0) {
          vModels.sort((a: any, b: any) => {
            const aAgnes = a.id.includes("agnes") ? 0 : 1;
            const bAgnes = b.id.includes("agnes") ? 0 : 1;
            if (aAgnes !== bAgnes) return aAgnes - bAgnes;
            return a.label.localeCompare(b.label);
          });
          setVideoModels(vModels);
          if (!vModels.find((m: any) => m.id === model)) {
            setModel(vModels[0].id);
          }
        }
      } catch (err) {
        /* non-critical fallback */
      }
    }
    loadModels();
  }, []);

  const calculateCredits = () => {
    return getVideoCreditCost(model, parseInt(count || "1", 10));
  };

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>, isStart: boolean) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      if (isStart) setStartImage(ev.target?.result as string);
      else setEndImage(ev.target?.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      toast.error("Vui lòng nhập mô tả video");
      return;
    }
    setGenerating(true);
    setError("");
    setResultB64(null);
    setResultVideoUrl(null);

    try {
      const payload: Record<string, any> = {
        model: model,
        prompt: prompt.trim(),
        n: parseInt(count, 10),
        aspect_ratio: aspectRatio,
        duration: duration,
        resolution: resolution,
        fps: parseInt(fps, 10),
      };

      if (negativePrompt.trim()) {
        payload.negative_prompt = negativePrompt.trim();
      }
      if (seed.trim()) {
        payload.seed = parseInt(seed.trim(), 10);
      }

      if (startImage && endImage) {
        payload.image = startImage;
        payload.last_frame = endImage;
        payload.mode = "keyframes";
      } else if (startImage) {
        payload.image = startImage;
        payload.mode = "ti2vid";
      }

      const resp = await request.post("/v1/video/generations", payload);
      const data = resp.data as any;
      
      const firstItem = data?.data?.[0];
      if (firstItem?.b64_json) {
        setResultB64(firstItem.b64_json);
        toast.success("Đã tạo video thành công!");
      } else if (firstItem?.url) {
        setResultVideoUrl(firstItem.url);
        toast.success("Đã tạo video thành công!");
      } else if (data?.detail?.error || data?.error) {
        const errStr = data?.detail?.error || data?.error;
        setError(errStr);
        toast.error(errStr);
      } else {
        toast.success("Yêu cầu đã gửi thành công!");
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail?.error || e?.message || "Lỗi tạo video";
      setError(msg);
      toast.error(msg);
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = () => {
    const src = resultVideoUrl || (resultB64 ? `data:video/mp4;base64,${resultB64}` : null);
    if (!src) return;
    const a = document.createElement("a");
    a.href = src;
    a.download = `video-${Date.now()}.mp4`;
    a.target = "_blank";
    a.click();
  };

  if (!session) return null;

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-black/[0.04] dark:border-white/[0.06] pb-6">
        <div className="flex size-12 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 via-purple-600 to-indigo-700 shadow-xl shadow-violet-500/20">
          <Video className="size-6 text-white" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold tracking-widest text-violet-500 uppercase">Tạo Video AI Multi-modal</span>
            <span className="inline-flex items-center rounded-full bg-violet-500/10 px-2 py-0.5 text-[10px] font-semibold text-violet-600 dark:text-violet-400 border border-violet-500/20">
              Agnes AI & Veo 3.1
            </span>
          </div>
          <h1 className="text-[26px] font-bold tracking-tight text-[var(--foreground)]">Studio Tạo Video AI</h1>
          <p className="text-[14px] text-[var(--muted-foreground)] mt-0.5">
            Tạo video chất lượng cao từ văn bản (Text-to-Video), hình ảnh (Image-to-Video), hoặc chuyển cảnh (Keyframe Animation)
          </p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Settings Form Column */}
        <Card className="lg:col-span-7 rounded-2xl card-3d card-tint-indigo border border-[var(--border)] shadow-xl">
          <CardContent className="space-y-5 p-6">
            {/* Model Selector */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-semibold text-[var(--foreground)] flex items-center gap-2">
                  <Sparkles className="size-4 text-violet-500" />
                  Mô hình (Model Video)
                </label>
                <span className="text-[11px] font-semibold text-violet-600 dark:text-violet-400 bg-violet-500/10 px-2.5 py-0.5 rounded-full border border-violet-500/20">
                  {modelConfig.badge}
                </span>
              </div>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm font-medium text-[var(--foreground)] focus:ring-2 focus:ring-violet-500/30 outline-none transition"
              >
                {videoModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Prompt Textarea */}
            <div className="space-y-2">
              <label className="text-sm font-semibold text-[var(--foreground)]">Mô tả video (Prompt)</label>
              <Textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Ví dụ: Cảnh quay điện ảnh từ góc máy drone, con rồng vàng bay qua thung lũng sương mù lúc hoàng hôn, hiệu ứng ánh sáng rực rỡ..."
                className="min-h-[110px] rounded-xl border-[var(--border)] bg-[var(--card)] focus:ring-2 focus:ring-violet-500/30 text-sm leading-relaxed"
              />
              <p className="text-xs text-[var(--muted-foreground)]">
                💡 Mô tả càng chi tiết về chủ thể, góc máy, hiệu ứng ánh sáng và phong cách điện ảnh sẽ cho kết quả càng đẹp.
              </p>
            </div>

            {/* Negative Prompt */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[var(--muted-foreground)] flex justify-between">
                <span>Chi tiết muốn tránh (Negative Prompt)</span>
                {!modelConfig.supportsNegativePrompt && (
                  <span className="text-[10px] text-amber-500 font-normal">Engine Flow tự động tối ưu</span>
                )}
              </label>
              <Input
                value={negativePrompt}
                onChange={(e) => setNegativePrompt(e.target.value)}
                disabled={!modelConfig.supportsNegativePrompt}
                placeholder={modelConfig.supportsNegativePrompt ? "VD: mờ, giật lag, biến dạng, chất lượng thấp, logo, watermark..." : "Engine Flow tự động tối ưu chi tiết hình ảnh..."}
                className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)] text-sm disabled:opacity-60"
              />
            </div>

            {/* General Parameters Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Độ phân giải</label>
                <select
                  value={resolution}
                  onChange={(e) => setResolution(e.target.value)}
                  className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm"
                >
                  {modelConfig.resolutions.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Tỷ lệ khung hình</label>
                <select
                  value={aspectRatio}
                  onChange={(e) => setAspectRatio(e.target.value)}
                  className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm"
                >
                  {modelConfig.aspectRatios.map((a) => (
                    <option key={a.value} value={a.value}>{a.label}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Thời lượng</label>
                <select
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm"
                >
                  {modelConfig.durations.map((d) => (
                    <option key={d.value} value={d.value}>{d.label}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Tốc độ khung hình</label>
                <select
                  value={fps}
                  onChange={(e) => setFps(e.target.value)}
                  className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm"
                >
                  {modelConfig.fps.map((f) => (
                    <option key={f.value} value={f.value}>{f.label}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Advanced Extra Configs */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)] flex justify-between">
                  <span>Seed ngẫu nhiên (Tùy chọn)</span>
                  {!modelConfig.supportsSeed && (
                    <span className="text-[10px] text-amber-500 font-normal">Tự động (Flow)</span>
                  )}
                </label>
                <Input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value)}
                  disabled={!modelConfig.supportsSeed}
                  placeholder={modelConfig.supportsSeed ? "Ví dụ: 12345" : "Tự động ngẫu nhiên"}
                  className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)] text-sm disabled:opacity-60"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[var(--muted-foreground)]">Số bản ghi (Count / Multiplier)</label>
                <select
                  value={count}
                  onChange={(e) => setCount(e.target.value)}
                  className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm font-medium"
                >
                  <option value="1">1x (1 video - {getVideoCreditCost(model, 1)} CR)</option>
                  <option value="2">x2 (2 video - {getVideoCreditCost(model, 2)} CR)</option>
                  <option value="3">x3 (3 video - {getVideoCreditCost(model, 3)} CR)</option>
                  <option value="4">x4 (4 video - {getVideoCreditCost(model, 4)} CR)</option>
                </select>
              </div>
            </div>

            {/* Keyframe & Start Image Upload */}
            <div className="space-y-2 pt-2 border-t border-[var(--border)]">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-[var(--foreground)] flex items-center gap-1.5">
                  <ImageIcon className="size-3.5 text-violet-500" />
                  Đính kèm Ảnh (Image-to-Video & Keyframes)
                </label>
                <span className="text-[11px] text-[var(--muted-foreground)] font-medium">
                  {startImage && endImage && modelConfig.supportsEndFrame
                    ? "Chế độ Keyframe Animation"
                    : startImage
                    ? "Chế độ Image-to-Video"
                    : "Chế độ Text-to-Video"}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs font-medium text-[var(--muted-foreground)]">
                    <span>Ảnh đầu (Start frame)</span>
                    {startImage && (
                      <button type="button" onClick={() => setStartImage(null)} className="text-rose-500 hover:text-rose-600">
                        Xóa
                      </button>
                    )}
                  </div>
                  {startImage ? (
                    <img src={startImage} alt="Start frame" className="h-28 w-full object-cover rounded-xl border border-[var(--border)] shadow-sm" />
                  ) : (
                    <label className="flex h-28 w-full cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-[var(--border)] bg-[var(--muted)]/50 hover:bg-[var(--secondary)] transition">
                      <span className="text-xs font-medium text-[var(--muted-foreground)]">+ Tải ảnh bắt đầu</span>
                      <input type="file" accept="image/*" className="hidden" onChange={(e) => handleImageUpload(e, true)} />
                    </label>
                  )}
                </div>

                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs font-medium text-[var(--muted-foreground)]">
                    <span>Ảnh cuối (End frame)</span>
                    {endImage && (
                      <button type="button" onClick={() => setEndImage(null)} className="text-rose-500 hover:text-rose-600">
                        Xóa
                      </button>
                    )}
                  </div>
                  {modelConfig.supportsEndFrame ? (
                    endImage ? (
                      <img src={endImage} alt="End frame" className="h-28 w-full object-cover rounded-xl border border-[var(--border)] shadow-sm" />
                    ) : (
                      <label className="flex h-28 w-full cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-[var(--border)] bg-[var(--muted)]/50 hover:bg-[var(--secondary)] transition">
                        <span className="text-xs font-medium text-[var(--muted-foreground)]">+ Tải ảnh kết thúc</span>
                        <input type="file" accept="image/*" className="hidden" onChange={(e) => handleImageUpload(e, false)} />
                      </label>
                    )
                  ) : (
                    <div className="flex h-28 w-full flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] bg-[var(--muted)]/20 text-[var(--muted-foreground)] px-3 text-center">
                      <span className="text-xs">Model này không hỗ trợ ảnh kết thúc</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Credit info */}
            <div className="text-center py-2.5 text-xs text-[var(--muted-foreground)] bg-[var(--muted)]/60 rounded-xl border border-[var(--border)]">
              Chi phí dự kiến: <span className="font-bold text-[var(--foreground)] underline">{calculateCredits()} tín dụng</span>
            </div>

            {/* Generate Button */}
            <Button
              className="w-full h-12 rounded-xl bg-gradient-to-r from-violet-500 via-purple-600 to-indigo-600 text-white font-semibold hover:from-violet-600 hover:to-indigo-700 shadow-lg shadow-violet-500/25 transition-all"
              onClick={handleGenerate}
              disabled={generating || !prompt.trim()}
            >
              {generating ? (
                <>
                  <LoaderCircle className="size-5 animate-spin" /> Đang khởi tạo & tạo video... (vui lòng chờ 1-5 phút)
                </>
              ) : (
                <>
                  <Play className="size-5 fill-current" /> Bắt đầu tạo video
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        {/* Video Result Column */}
        <Card className="lg:col-span-5 rounded-2xl card-3d card-tint-indigo border border-[var(--border)] shadow-xl flex flex-col justify-between">
          <CardContent className="flex min-h-[420px] flex-col items-center justify-center p-6 my-auto">
            {generating ? (
              <div className="flex flex-col items-center gap-4 text-center">
                <div className="relative flex items-center justify-center">
                  <div className="size-16 rounded-full bg-violet-500/10 animate-ping absolute" />
                  <LoaderCircle className="size-12 animate-spin text-violet-500 relative" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-[var(--foreground)]">Đang xử lý Video AI trên Server Agnes / Veo...</p>
                  <p className="text-xs text-[var(--muted-foreground)] max-w-xs">
                    Quá trình tạo đang diễn ra bất đồng bộ và kiểm tra trạng thái tự động. Vui lòng giữ tab này mở.
                  </p>
                </div>
              </div>
            ) : resultVideoUrl || resultB64 ? (
              <div className="flex w-full flex-col items-center gap-4">
                <div className="w-full overflow-hidden rounded-xl border border-[var(--border)] bg-black shadow-2xl">
                  <video
                    src={resultVideoUrl || `data:video/mp4;base64,${resultB64}`}
                    controls
                    autoPlay
                    loop
                    className="w-full max-h-[460px] object-contain mx-auto"
                  />
                </div>
                <Button
                  className="w-full h-11 rounded-xl bg-violet-600 text-white font-medium hover:bg-violet-700 shadow-md"
                  onClick={handleDownload}
                >
                  <Download className="size-4 mr-2" /> Tải Video MP4
                </Button>
              </div>
            ) : error ? (
              <div className="text-center space-y-3 p-4">
                <div className="size-12 rounded-full bg-rose-500/10 text-rose-500 flex items-center justify-center mx-auto">
                  <Video className="size-6" />
                </div>
                <p className="text-rose-500 font-semibold text-sm">Lỗi tạo video</p>
                <p className="text-xs text-[var(--muted-foreground)] max-w-sm bg-[var(--muted)] p-3 rounded-xl border border-[var(--border)]">
                  {error}
                </p>
              </div>
            ) : (
              <div className="text-center space-y-3 text-[var(--muted-foreground)] py-8">
                <div className="size-16 rounded-2xl bg-violet-500/10 text-violet-500 flex items-center justify-center mx-auto">
                  <Video className="size-8 opacity-60" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-medium text-[var(--foreground)]">Xem trước video kết quả</p>
                  <p className="text-xs text-[var(--muted-foreground)] max-w-xs mx-auto">
                    Cấu hình thông số ở bảng bên trái và bấm "Bắt đầu tạo video" để xem kết quả tại đây.
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
