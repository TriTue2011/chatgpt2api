"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Video, LoaderCircle, Play, Download, Settings2, Sparkles, Image as ImageIcon } from "lucide-react";
import { toast } from "sonner";

import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  getVideoCostLabel,
  getVideoCreditPerClip,
  getVideoModelSpec,
  isFlowVideoModel,
  NO_VIDEO_PROVIDER_HINT,
  usesFlowCredits,
} from "@/lib/video-model-specs";

interface VideoModel {
  id: string;
  label: string;
  baseCost?: number;
}

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
  // Không còn model mặc định cứng — chỉ chọn được model do backend xác nhận
  // provider tương ứng ĐÃ cấu hình (xem loadModels bên dưới).
  const [model, setModel] = useState("");
  const [count, setCount] = useState("1");
  const [startImage, setStartImage] = useState<string | null>(null);
  const [endImage, setEndImage] = useState<string | null>(null);

  const [videoModels, setVideoModels] = useState<VideoModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [resultClips, setResultClips] = useState<Array<{ url?: string; b64?: string }>>([]);
  const [error, setError] = useState("");

  const modelConfig = useMemo(() => (model ? getVideoModelSpec(model) : null), [model]);

  // Đồng bộ tham số khi ĐỔI model: lựa chọn không hợp lệ → về mặc định của
  // model. Control nào model không hỗ trợ (mảng rỗng, vd resolution/fps của
  // Flow) thì tự về rỗng — UI ẩn hẳn control đó (xem phần render bên dưới).
  useEffect(() => {
    if (!modelConfig) return;
    if (!modelConfig.durations.some((d) => d.value === duration)) {
      setDuration(modelConfig.durations[0]?.value || "");
    }
    if (!modelConfig.resolutions.some((r) => r.value === resolution)) {
      setResolution(modelConfig.resolutions[0]?.value || "");
    }
    if (!modelConfig.fps.some((f) => f.value === fps)) {
      setFps(modelConfig.fps[0]?.value || "");
    }
    if (!modelConfig.aspectRatios.some((a) => a.value === aspectRatio)) {
      setAspectRatio(modelConfig.aspectRatios[0]?.value || "16:9");
    }
    if (!modelConfig.countOptions.includes(parseInt(count || "1", 10))) {
      setCount(String(modelConfig.countOptions[0] ?? 1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, modelConfig]);

  useEffect(() => {
    async function loadModels() {
      try {
        // /api/v1/models-with-capabilities là nguồn model THẬT (giống
        // image/page.tsx, models/page.tsx) — thay vì danh sách hardcode cũ
        // vốn luôn hiện agnes/flow bất kể provider đã cấu hình hay chưa.
        // Gọi kèm /api/v1/providers (best-effort) để chặn thêm model flow/*:
        // openai_v1_models.list_models() thêm VIDEO_GEN_MODELS (flow/veo-*,
        // flow/omni-flash) vào /v1/models KHÔNG điều kiện — không như các
        // provider khác (custom_providers Agnes, gemini_free key…), flow/*
        // không bị _drop_unavailable() lọc theo tài khoản. Vì vậy tự lọc
        // thêm ở đây theo providers.flow.enabled; nếu không đọc được danh
        // sách provider (403 non-admin, lỗi mạng…) thì bỏ qua bước lọc thêm
        // này — giữ nguyên danh sách gốc, không làm tệ hơn hiện trạng.
        const [capResult, providersResult] = await Promise.allSettled([
          request.get("/api/v1/models-with-capabilities"),
          request.get("/api/v1/providers"),
        ]);

        if (capResult.status !== "fulfilled") {
          return;
        }

        let flowEnabled: boolean | null = null;
        if (providersResult.status === "fulfilled") {
          const providerList = ((providersResult.value.data as any)?.providers || []) as any[];
          const flowEntry = providerList.find((p: any) => p?.name === "flow");
          flowEnabled = Boolean(flowEntry?.enabled);
        }

        const models = ((capResult.value.data as any)?.models || []) as any[];
        const vModels = models
          .filter((m: any) => {
            if (!(m.capabilities || []).includes("video_gen")) return false;
            if (m.enabled === false) return false;
            if (String(m.id).includes(":")) return false;
            if (flowEnabled === false && isFlowVideoModel(String(m.id))) return false;
            return true;
          })
          .map((m: any) => {
            const id = String(m.id);
            const spec = getVideoModelSpec(id);
            let labelName = id;
            if (id.includes("agnes")) labelName = `✨ ${id} (Agnes Async Video)`;
            else if (m.owned_by && String(m.owned_by).includes("custom")) labelName = `🎬 ${id} (${String(m.owned_by).replace("custom:", "")})`;
            // Giá ngay trên tên model để thấy trước khi chọn. Omni Flash đổi giá
            // theo thời lượng nên ghi khoảng, không ghi một con số cứng.
            if (usesFlowCredits(id)) {
              labelName +=
                spec.durations.length > 1
                  ? ` — ${getVideoCreditPerClip(id, spec.durations[0].value)}–${getVideoCreditPerClip(id, spec.durations[spec.durations.length - 1].value)} tín dụng/video`
                  : ` — ${getVideoCreditPerClip(id)} tín dụng/video`;
            } else {
              labelName += " — theo hạn mức tài khoản";
            }
            return { id, label: labelName, baseCost: spec.baseCost };
          });

        vModels.sort((a, b) => {
          const aAgnes = a.id.includes("agnes") ? 0 : 1;
          const bAgnes = b.id.includes("agnes") ? 0 : 1;
          if (aAgnes !== bAgnes) return aAgnes - bAgnes;
          return a.label.localeCompare(b.label);
        });

        setVideoModels(vModels);
        setModel((prev) => (vModels.some((m) => m.id === prev) ? prev : vModels[0]?.id || ""));
      } catch {
        /* videoModels giữ rỗng → UI hiện hint "chưa cấu hình provider" */
      } finally {
        setModelsLoading(false);
      }
    }
    void loadModels();
  }, []);

  const costLabel = model ? getVideoCostLabel(model, parseInt(count || "1", 10), duration) : "";

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
    if (!model || !modelConfig) {
      toast.error("Vui lòng chọn model video (chưa có provider nào được cấu hình)");
      return;
    }
    setGenerating(true);
    setError("");
    setResultClips([]);

    try {
      const payload: Record<string, any> = {
        model,
        prompt: prompt.trim(),
        n: parseInt(count, 10),
        aspect_ratio: aspectRatio,
      };
      // Chỉ gửi duration khi model có hàng chọn thời lượng thật (Omni Flash,
      // Agnes…). Ba model Veo không có hàng đó — gửi xuống chỉ tổ để solver
      // đi tìm một nút không tồn tại.
      if (modelConfig.durations.length) {
        payload.duration = duration;
      }
      // Chỉ gửi resolution/fps khi model thực sự dùng tới (adapter bỏ qua
      // param thì không gửi giá trị người dùng chưa từng thấy trên UI).
      if (modelConfig.resolutions.length) {
        payload.resolution = resolution;
      }
      if (modelConfig.fps.length) {
        payload.fps = parseInt(fps, 10);
      }

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

      const items = Array.isArray(data?.data) ? data.data : [];
      const clips = items
        .filter((it: any) => it?.url || it?.b64_json)
        .map((it: any) => ({ url: it.url as string | undefined, b64: it.b64_json as string | undefined }));
      if (clips.length) {
        setResultClips(clips);
        toast.success(clips.length > 1 ? `Đã tạo ${clips.length} video thành công!` : "Đã tạo video thành công!");
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

  const handleDownload = (src: string) => {
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
                {modelConfig && (
                  <span className="text-[11px] font-semibold text-violet-600 dark:text-violet-400 bg-violet-500/10 px-2.5 py-0.5 rounded-full border border-violet-500/20">
                    {modelConfig.badge}
                  </span>
                )}
              </div>
              {modelsLoading ? (
                <div className="flex h-11 w-full items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm text-[var(--muted-foreground)]">
                  <LoaderCircle className="size-4 animate-spin" /> Đang tải danh sách model...
                </div>
              ) : videoModels.length === 0 ? (
                <div className="rounded-xl border border-dashed border-amber-500/40 bg-amber-500/10 px-3 py-3 text-xs font-medium text-amber-600 dark:text-amber-400">
                  {NO_VIDEO_PROVIDER_HINT}
                </div>
              ) : (
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
              )}
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

            {modelConfig && (
              <>
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

                {/* General Parameters Grid — chỉ hiện control mà model thực sự dùng tới */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
                  {modelConfig.resolutions.length > 0 && (
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
                  )}

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

                  {/* Thời lượng — ẩn hẳn với model không có hàng này trên Flow
                      (ba model Veo). Hiện ra mà không có tác dụng thì người
                      dùng tưởng đã đổi được độ dài video. */}
                  {modelConfig.durations.length > 0 && (
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
                  )}

                  {modelConfig.fps.length > 0 && (
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
                  )}
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
                      disabled={modelConfig.countOptions.length <= 1}
                      className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm font-medium disabled:opacity-60"
                    >
                      {modelConfig.countOptions.map((c) => (
                        <option key={c} value={String(c)}>
                          {c === 1 ? "1x (1 video" : `x${c} (${c} video`}
                          {usesFlowCredits(model) ? ` — ${getVideoCostLabel(model, c, duration)})` : ")"}
                        </option>
                      ))}
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

                {/* Chi phí — chỉ hiện con số tín dụng với model Flow (có bảng
                    giá thật). Model khác ghi rõ tiêu vào hạn mức nào. */}
                <div className="text-center py-2.5 text-xs text-[var(--muted-foreground)] bg-[var(--muted)]/60 rounded-xl border border-[var(--border)]">
                  Chi phí dự kiến: <span className="font-bold text-[var(--foreground)] underline">{costLabel}</span>
                  {usesFlowCredits(model) && (
                    <span className="ml-1 opacity-80">
                      ({getVideoCreditPerClip(model, duration)} tín dụng / video × {count})
                    </span>
                  )}
                </div>
              </>
            )}

            {/* Generate Button */}
            <Button
              className="w-full h-12 rounded-xl bg-gradient-to-r from-violet-500 via-purple-600 to-indigo-600 text-white font-semibold hover:from-violet-600 hover:to-indigo-700 shadow-lg shadow-violet-500/25 transition-all"
              onClick={handleGenerate}
              disabled={generating || !prompt.trim() || !model}
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
            ) : resultClips.length > 0 ? (
              <div className="flex w-full flex-col gap-5">
                {resultClips.map((clip, i) => {
                  const src = clip.url || (clip.b64 ? `data:video/mp4;base64,${clip.b64}` : "");
                  if (!src) return null;
                  return (
                    <div key={i} className="flex w-full flex-col items-center gap-3">
                      <div className="w-full overflow-hidden rounded-xl border border-[var(--border)] bg-black shadow-2xl">
                        <video
                          src={src}
                          controls
                          autoPlay={i === 0}
                          loop
                          className="w-full max-h-[460px] object-contain mx-auto"
                        />
                      </div>
                      <Button
                        className="w-full h-11 rounded-xl bg-violet-600 text-white font-medium hover:bg-violet-700 shadow-md"
                        onClick={() => handleDownload(src)}
                      >
                        <Download className="size-4 mr-2" /> Tải Video MP4
                        {resultClips.length > 1 ? ` #${i + 1}` : ""}
                      </Button>
                    </div>
                  );
                })}
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
