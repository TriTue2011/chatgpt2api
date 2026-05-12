"use client";

import { useEffect, useState } from "react";
import { Search, CheckCircle2, Globe, Database } from "lucide-react";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

const SEARCH_BACKENDS = [
  { value: "chatgpt", label: "ChatGPT (có sẵn)", desc: "ChatGPT tự tìm kiếm web — chỉ hoạt động với model chatgpt/", icon: Globe },
  { value: "gemini", label: "Gemini Google Search", desc: "Google Search chính xác qua Gemini API — cần API key AI Studio", icon: Search },
  { value: "serper", label: "Serper.dev", desc: "Google Search API nhanh — 2.500 req/tháng miễn phí", icon: Search },
  { value: "searxng", label: "SearXNG (tự cài)", desc: "Tự host, riêng tư, không giới hạn", icon: Database },
  { value: "brave", label: "Brave Search", desc: "Brave Search API — 2.000 req/tháng miễn phí", icon: Search },
];

export default function SearchPage() {
  const [config, setConfig] = useState<any>({});
  const [geminiKey, setGeminiKey] = useState("");
  const [geminiModel, setGeminiModel] = useState("gemini-2.5-flash");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetchConfig();
  }, []);

  async function fetchConfig() {
    try {
      const data = await request.get("/api/settings");
      const cfg = (data.data as any)?.config || {};
      setConfig(cfg.search || { enabled: true, backend: "chatgpt", auto_detect: true, max_results: 3, inject_as: "user_message" });
      const providers = cfg.providers || {};
      const geminiCfg = providers.gemini_free || {};
      setGeminiKey(geminiCfg.api_key || "");
      setGeminiModel(geminiCfg.model || "gemini-2.5-flash");
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      // Save search config
      await request.post("/api/settings", {
        search: config,
        providers: {
          ...config.providers || {},
          gemini_free: {
            enabled: true,
            api_key: geminiKey,
            model: geminiModel,
          },
        },
      });
      setMsg("Đã lưu!");
      setTimeout(() => setMsg(""), 2000);
    } catch (e: any) {
      setMsg("Lỗi: " + (e?.message || "unknown"));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center py-20"><p className="text-stone-500">Đang tải...</p></div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Cấu hình tìm kiếm</h1>
        <p className="mt-1 text-sm text-stone-500">
          Khi dùng model cx/auto, oc/auto (không có search built-in), hệ thống sẽ tự tìm kiếm trước khi trả lời
        </p>
      </div>

      {/* Enable */}
      <div className="rounded-2xl border border-stone-200 bg-white p-5">
        <label className="flex items-center gap-3 cursor-pointer">
          <input type="checkbox" checked={config.enabled !== false}
            onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
            className="size-4 accent-stone-400" />
          <div>
            <span className="text-sm font-medium">Bật tìm kiếm tự động</span>
            <p className="text-xs text-stone-500">Tự động phát hiện câu hỏi cần tìm kiếm và bổ sung kết quả</p>
          </div>
        </label>
      </div>

      {/* Gemini API Key */}
      <div className="rounded-2xl border border-stone-200 bg-white p-5">
        <h3 className="text-sm font-semibold mb-3">Gemini API Key</h3>
        <input type="text" value={geminiKey}
          onChange={(e) => setGeminiKey(e.target.value)}
          placeholder="AIzaSy... (lấy tại aistudio.google.com/apikey)"
          className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-500 focus:border-stone-500 focus:outline-none focus:ring-1 focus:ring-stone-300" />
        <div className="flex items-center gap-3 mt-2">
          <label className="text-xs text-stone-500 w-16">Model:</label>
          <select value={geminiModel} onChange={(e) => setGeminiModel(e.target.value)}
            className="rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-xs text-stone-900 focus:border-stone-500 focus:outline-none">
            <option value="gemini-3-flash-preview">gemini-3-flash-preview (Preview)</option>
            <option value="gemini-2.5-flash">gemini-2.5-flash (Stable)</option>
            <option value="gemini-2.5-pro-preview-07-02">gemini-2.5-pro-preview-07-02 (Preview)</option>
            <option value="gemini-2.0-flash">gemini-2.0-flash (Stable)</option>
          </select>
        </div>
        <p className="text-xs text-stone-500 mt-1">Free 15 RPM. Có thể nhập nhiều key cách nhau dấu phẩy</p>
      </div>

      {/* Backend */}
      <div className="rounded-2xl border border-stone-200 bg-white p-5">
        <h3 className="text-sm font-semibold mb-4">Dịch vụ tìm kiếm</h3>
        <div className="space-y-2">
          {SEARCH_BACKENDS.map((b) => {
            const active = config.backend === b.value;
            const Icon = b.icon;
            return (
              <button key={b.value} type="button"
                onClick={() => setConfig({ ...config, backend: b.value })}
                className={cn("flex w-full items-start gap-3 rounded-lg border p-4 text-left transition",
                  active ? "border-stone-400 bg-stone-100" : "border-stone-200 hover:border-stone-300")}>
                <Icon className={cn("size-5 mt-0.5", active ? "text-stone-900" : "text-stone-500")} />
                <div className="flex-1">
                  <p className="text-sm font-medium">{b.label}</p>
                  <p className="text-xs text-stone-500 mt-0.5">{b.desc}</p>
                </div>
                {active && <CheckCircle2 className="size-5 text-emerald-500 shrink-0" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* Save */}
      <div className="flex justify-end gap-3">
        {msg && <span className={cn("text-sm", msg.startsWith("Lỗi") ? "text-red-500" : "text-emerald-600")}>{msg}</span>}
        <button type="button" onClick={save} disabled={saving}
          className="rounded-xl bg-stone-100 px-6 py-2.5 text-sm font-medium text-white hover:bg-stone-100 disabled:opacity-50">
          {saving ? "Đang lưu..." : "Lưu cài đặt"}
        </button>
      </div>
    </div>
  );
}
