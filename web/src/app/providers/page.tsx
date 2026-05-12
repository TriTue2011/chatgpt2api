"use client";

import { useEffect, useState } from "react";
import { Cpu, CheckCircle2, XCircle, Wrench, RefreshCw, ExternalLink } from "lucide-react";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

type ProviderInfo = {
  name: string;
  enabled: boolean;
  noAuth: boolean;
  has_api_key: boolean;
  has_base_url: boolean;
};

const PROVIDER_META: Record<string, { label: string; desc: string; icon: string; color: string }> = {
  opencode: { label: "OpenCode", desc: "Miễn phí, không cần API key — qua opencode.ai", icon: "🆓", color: "#E87040" },
  gemini_free: { label: "Gemini AI Studio", desc: "Google Gemini với Google Search — free 15 RPM", icon: "🔮", color: "#8E6CEE" },
  openrouter: { label: "OpenRouter", desc: "27+ model miễn phí, 200 req/ngày", icon: "🔀", color: "#6366F1" },
  sdwebui: { label: "Stable Diffusion WebUI", desc: "Tạo ảnh local qua AUTOMATIC1111 — miễn phí, không giới hạn", icon: "🎨", color: "#10B981" },
  huggingface: { label: "HuggingFace", desc: "Inference API — FLUX, SDXL miễn phí", icon: "🤗", color: "#F59E0B" },
  cloudflare_ai: { label: "Cloudflare AI", desc: "Workers AI — FLUX schnell miễn phí", icon: "☁️", color: "#F6821F" },
  serper: { label: "Serper.dev", desc: "Google Search API — 2.5K req/tháng miễn phí", icon: "🔍", color: "#3B82F6" },
  searxng: { label: "SearXNG", desc: "Tự host — không giới hạn, riêng tư", icon: "🔎", color: "#6B7280" },
  brave: { label: "Brave Search", desc: "Brave Search API — 2K req/tháng miễn phí", icon: "🦁", color: "#FB923C" },
  nvidia_nim: { label: "NVIDIA NIM", desc: "80+ model qua NVIDIA — chat + vision + tạo ảnh FLUX", icon: "🟢", color: "#76B900" },
};

export default function ProvidersPage() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, boolean | null>>({});

  useEffect(() => {
    fetchProviders();
  }, []);

  async function fetchProviders() {
    try {
      const data = await request.get("/api/v1/providers");
      setProviders((data.data as any)?.providers || []);
    } catch (e) {
      console.error("Failed to fetch providers", e);
    } finally {
      setLoading(false);
    }
  }

  async function testProvider(name: string) {
    setTestingProvider(name);
    try {
      const data = await request.post(`/api/v1/providers/${name}/test`);
      setTestResults((prev) => ({ ...prev, [name]: (data.data as any)?.available ?? false }));
    } catch {
      setTestResults((prev) => ({ ...prev, [name]: false }));
    } finally {
      setTestingProvider(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-stone-400">Đang tải...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Nhà cung cấp AI</h1>
        <p className="mt-1 text-sm text-stone-400">
          Quản lý các nhà cung cấp AI bên ngoài — miễn phí và có API key
        </p>
      </div>

      {/* Provider Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {providers.map((provider) => {
          const meta = PROVIDER_META[provider.name] || {
            label: provider.name,
            desc: "",
            icon: "🔧",
            color: "#6B7280",
          };
          const isTesting = testingProvider === provider.name;
          const testResult = testResults[provider.name];

          return (
            <div
              key={provider.name}
              className="rounded-xl border border-stone-800 bg-stone-900/50 p-5 transition hover:border-stone-700"
            >
              <div className="mb-3 flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{meta.icon}</span>
                  <div>
                    <h3 className="font-semibold text-white">{meta.label}</h3>
                    <p className="text-xs text-stone-400">{meta.desc}</p>
                  </div>
                </div>
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
                    provider.enabled
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-stone-800 text-stone-500",
                  )}
                >
                  {provider.enabled ? (
                    <CheckCircle2 className="size-3" />
                  ) : (
                    <XCircle className="size-3" />
                  )}
                  {provider.enabled ? "Đã bật" : "Đã tắt"}
                </span>
              </div>

              {/* Features */}
              <div className="mb-4 flex flex-wrap gap-1.5">
                {provider.noAuth && (
                  <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400">
                    Không cần API key
                  </span>
                )}
                {provider.has_api_key && (
                  <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-400">
                    Đã cấu hình API key
                  </span>
                )}
                {provider.has_base_url && (
                  <span className="rounded-md bg-purple-500/10 px-2 py-0.5 text-[10px] font-medium text-purple-400">
                    Đã cấu hình URL
                  </span>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2">
                {provider.name === "opencode" && (
                  <button
                    type="button"
                    disabled={isTesting}
                    onClick={() => testProvider(provider.name)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-stone-800 px-3 py-1.5 text-xs font-medium text-stone-300 transition hover:bg-stone-700 disabled:opacity-50"
                  >
                    {isTesting ? (
                      <RefreshCw className="size-3 animate-spin" />
                    ) : (
                      <Wrench className="size-3" />
                    )}
                    {isTesting ? "Đang kiểm tra..." : "Kiểm tra kết nối"}
                  </button>
                )}
                {testResult !== undefined && (
                  <span
                    className={cn(
                      "text-xs font-medium",
                      testResult ? "text-emerald-400" : "text-red-400",
                    )}
                  >
                    {testResult ? "Kết nối OK" : "Lỗi kết nối"}
                  </span>
                )}
                {provider.name === "opencode" && (
                  <a
                    href="https://opencode.ai"
                    target="_blank"
                    rel="noreferrer"
                    className="ml-auto text-xs text-stone-500 transition hover:text-stone-300"
                  >
                    <ExternalLink className="size-3" />
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {providers.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-stone-500">
          <Cpu className="size-12 mb-3 opacity-50" />
          <p>Chưa có nhà cung cấp nào được cấu hình</p>
          <p className="text-xs mt-1">Thêm provider vào config.json để bắt đầu</p>
        </div>
      )}
    </div>
  );
}
