"use client";

import { useEffect, useState } from "react";
import { Search, CheckCircle2, Globe, Database } from "lucide-react";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

const SEARCH_BACKENDS = [
  { value: "chatgpt", label: "ChatGPT (có sẵn)", desc: "ChatGPT tự động tìm kiếm web khi cần — không cần API key", icon: Globe },
  { value: "gemini", label: "Gemini Google Search", desc: "Google Search chính xác qua Gemini API — cần API key AI Studio", icon: Search },
  { value: "serper", label: "Serper.dev", desc: "Google Search API nhanh — 2.500 req/tháng miễn phí", icon: Search },
  { value: "searxng", label: "SearXNG (tự cài)", desc: "Tự host, riêng tư, không giới hạn — cần cài Docker", icon: Database },
  { value: "brave", label: "Brave Search", desc: "Brave Search API độc lập — 2.000 req/tháng miễn phí", icon: Search },
];

export default function SearchPage() {
  const [config, setConfig] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchConfig();
  }, []);

  async function fetchConfig() {
    try {
      const data = await request.get("/api/settings");
      const cfg = (data.data as any)?.config || {};
      setConfig(cfg.search || { enabled: true, backend: "chatgpt", auto_detect: true, max_results: 3, inject_as: "user_message" });
    } catch (e) {
      console.error("Failed to fetch config", e);
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    setSaving(true);
    try {
      await request.post("/api/settings", { search: config });
    } catch (e) {
      console.error("Failed to save", e);
    } finally {
      setSaving(false);
    }
  }

  function updateField(field: string, value: any) {
    setConfig((prev: any) => ({ ...prev, [field]: value }));
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
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Cấu hình tìm kiếm</h1>
        <p className="mt-1 text-sm text-stone-400">
          Khi người dùng hỏi câu cần thông tin thực tế (giá cả, thời tiết, tin tức...),
          hệ thống sẽ tự động tìm kiếm trước khi trả lời
        </p>
      </div>

      {/* Enable/Disable */}
      <div className="rounded-xl border border-stone-800 bg-stone-900/50 p-5">
        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={config.enabled !== false}
            onChange={(e) => updateField("enabled", e.target.checked)}
            className="size-4 accent-stone-50"
          />
          <div>
            <span className="text-sm font-medium text-white">Bật tìm kiếm tự động</span>
            <p className="text-xs text-stone-400">Tự động phát hiện câu hỏi cần tìm kiếm và bổ sung kết quả</p>
          </div>
        </label>
      </div>

      {/* Backend selection */}
      <div className="rounded-xl border border-stone-800 bg-stone-900/50 p-5">
        <h3 className="mb-4 text-sm font-semibold text-white">Dịch vụ tìm kiếm</h3>
        <div className="space-y-3">
          {SEARCH_BACKENDS.map((backend) => {
            const active = config.backend === backend.value;
            const Icon = backend.icon;
            return (
              <button
                key={backend.value}
                type="button"
                onClick={() => updateField("backend", backend.value)}
                className={cn(
                  "flex w-full items-start gap-3 rounded-lg border p-4 text-left transition",
                  active
                    ? "border-stone-50/20 bg-stone-50/5"
                    : "border-stone-800 hover:border-stone-700",
                )}
              >
                <Icon className={cn("size-5 mt-0.5", active ? "text-white" : "text-stone-500")} />
                <div className="flex-1">
                  <p className={cn("text-sm font-medium", active ? "text-white" : "text-stone-300")}>
                    {backend.label}
                  </p>
                  <p className="text-xs text-stone-500 mt-0.5">{backend.desc}</p>
                </div>
                {active && <CheckCircle2 className="size-5 text-emerald-400 shrink-0" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* Options */}
      <div className="rounded-xl border border-stone-800 bg-stone-900/50 p-5 space-y-4">
        <h3 className="text-sm font-semibold text-white">Tùy chọn</h3>

        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={config.auto_detect !== false}
            onChange={(e) => updateField("auto_detect", e.target.checked)}
            className="size-4 accent-stone-50"
          />
          <div>
            <span className="text-sm text-white">Tự động phát hiện</span>
            <p className="text-xs text-stone-400">Tự phân tích câu hỏi để biết có cần search không</p>
          </div>
        </label>

        <div className="flex items-center gap-3">
          <label className="text-sm text-stone-300 w-32">Số kết quả tối đa:</label>
          <input
            type="number"
            value={config.max_results || 3}
            onChange={(e) => updateField("max_results", parseInt(e.target.value) || 3)}
            min={1}
            max={10}
            className="w-20 rounded-lg border border-stone-700 bg-stone-800 px-3 py-2 text-sm text-white focus:border-stone-500 focus:outline-none"
          />
        </div>

        <div className="flex items-center gap-3">
          <label className="text-sm text-stone-300 w-32">Cách chèn kết quả:</label>
          <select
            value={config.inject_as || "user_message"}
            onChange={(e) => updateField("inject_as", e.target.value)}
            className="rounded-lg border border-stone-700 bg-stone-800 px-3 py-2 text-sm text-white focus:border-stone-500 focus:outline-none"
          >
            <option value="user_message">Vào tin nhắn người dùng</option>
            <option value="system_message">Vào system message</option>
          </select>
        </div>
      </div>

      {/* Save */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="rounded-lg bg-stone-50 px-6 py-2.5 text-sm font-medium text-stone-950 transition hover:bg-white disabled:opacity-50"
        >
          {saving ? "Đang lưu..." : "Lưu cài đặt"}
        </button>
      </div>
    </div>
  );
}
