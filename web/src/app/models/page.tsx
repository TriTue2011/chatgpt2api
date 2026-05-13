"use client";

import { useEffect, useState } from "react";
import { Check, RefreshCw, Save, Sparkles } from "lucide-react";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

type ModelSettings = {
  enabled_models: Record<string, string[]>;
  default_models: Record<string, string>;
};

const PROVIDER_LABELS: Record<string, { label: string; color: string }> = {
  chatgpt: { label: "ChatGPT", color: "#10A37F" },
  opencode: { label: "OpenCode", color: "#E87040" },
  gemini_free: { label: "Gemini", color: "#8E6CEE" },
  openrouter: { label: "OpenRouter", color: "#6366F1" },
  openai_oauth: { label: "Codex OAuth", color: "#00A67E" },
  chatgpt2api: { label: "Hệ thống (combo)", color: "#F59E0B" },
};

const CORE_MODELS = ["ha-agent", "chatgpt/auto", "oc/auto", "gemini_free/auto", "cx/auto"];

export default function ModelsPage() {
  const [available, setAvailable] = useState<Record<string, string[]>>({});
  const [settings, setSettings] = useState<ModelSettings>({ enabled_models: {}, default_models: {} });
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData(forceRefresh = false) {
    if (forceRefresh) setRefreshing(true); else setLoading(true);
    try {
      const params = forceRefresh ? "?refresh=true" : "";
      const [availRes, settingsRes] = await Promise.all([
        request.get(`/api/v1/available-models${params}`),
        request.get("/api/v1/model-settings"),
      ]);
      setAvailable((availRes.data as any)?.providers || {});
      setSettings((settingsRes.data as any)?.model_settings || { enabled_models: {}, default_models: {} });
    } catch (e) {
      console.error("Failed to load model data", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  function isEnabled(provider: string, modelId: string): boolean {
    const enabled = settings.enabled_models[provider];
    if (!enabled) return true; // no config = all enabled
    return enabled.includes(modelId);
  }

  function toggleModel(provider: string, modelId: string) {
    setDirty(true);
    setSaved(false);
    setSettings((prev) => {
      const enabled = { ...prev.enabled_models };
      if (!enabled[provider]) {
        // First toggle: disable all then enable only this one
        enabled[provider] = (available[provider] || []).filter((m) => m !== modelId);
      }
      const list = [...(enabled[provider] || [])];
      const idx = list.indexOf(modelId);
      if (idx >= 0) {
        list.splice(idx, 1);
      } else {
        list.push(modelId);
      }
      enabled[provider] = list;
      return { ...prev, enabled_models: enabled };
    });
  }

  function setDefault(provider: string, modelId: string) {
    setDirty(true);
    setSaved(false);
    setSettings((prev) => ({
      ...prev,
      default_models: { ...prev.default_models, [provider]: modelId },
    }));
  }

  async function save() {
    setSaving(true);
    try {
      await request.post("/api/v1/model-settings", { model_settings: settings });
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error("Failed to save", e);
    } finally {
      setSaving(false);
    }
  }

  const providers = Object.keys(available);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-stone-500">Đang tải danh sách model từ API...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-stone-900">Quản lý Model</h1>
          <p className="mt-1 text-sm text-stone-500">
            Chọn model hiển thị cho Home Assistant. Model không được chọn sẽ bị ẩn khỏi /v1/models.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs text-stone-600 hover:bg-stone-100 transition disabled:opacity-50"
          >
            <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
            {refreshing ? "Đang tải..." : "Làm mới"}
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!dirty || saving}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition",
              saved
                ? "bg-emerald-600 text-white"
                : dirty
                  ? "bg-stone-900 text-white hover:bg-stone-800"
                : "bg-stone-100 text-stone-500 cursor-not-allowed",
          )}
        >
          {saved ? <Check className="size-4" /> : <Save className="size-4" />}
          {saved ? "Đã lưu" : saving ? "Đang lưu..." : "Lưu thay đổi"}
        </button>
      </div>

      {/* Info banner */}
      <div className="rounded-lg border border-stone-200 bg-white/80 p-3">
        <p className="text-xs text-stone-500">
          <Sparkles className="inline size-3 mr-1" />
          Model <strong>auto</strong> tự động chọn model tốt nhất dựa trên cài đặt mặc định bên dưới.
          Các model chính (<code>ha-agent</code>, <code>chatgpt/auto</code>, <code>oc/auto</code>, <code>cx/auto</code>) luôn được hiển thị.
        </p>
      </div>

      {providers.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-stone-500">
          <Sparkles className="size-12 mb-3 opacity-50" />
          <p>Chưa có model nào</p>
          <p className="text-xs mt-1">Thêm tài khoản hoặc API key để lấy danh sách model</p>
        </div>
      )}

      {/* Providers */}
      <div className="space-y-4">
        {providers.map((provider) => {
          const models = available[provider] || [];
          const meta = PROVIDER_LABELS[provider] || { label: provider, color: "#6B7280" };
          const defaultModel = settings.default_models[provider] || "";
          const providerEnabled = settings.enabled_models[provider];
          const hasFilter = !!providerEnabled;

          // Separate core models from regular models for display
          const coreModels = models.filter((m) => CORE_MODELS.includes(m));
          const regularModels = models.filter((m) => !CORE_MODELS.includes(m));

          return (
            <div
              key={provider}
              className="rounded-xl border border-stone-200 bg-white/80 overflow-hidden"
            >
              {/* Provider header */}
              <div className="flex items-center gap-3 px-5 py-3 border-b border-stone-200 bg-stone-900/80">
                <span
                  className="size-3 rounded-full shrink-0"
                  style={{ backgroundColor: meta.color }}
                />
                <h3 className="font-semibold text-white text-sm">{meta.label}</h3>
                <span className="text-xs text-stone-500">{models.length} model</span>
                {defaultModel && (
                  <span className="ml-auto text-[10px] text-stone-500">
                    Mặc định: <span className="text-stone-700 font-mono">{defaultModel.replace(provider + "/", "")}</span>
                  </span>
                )}
              </div>

              {/* Model list */}
              <div className="p-3">
                {/* Core models first */}
                {coreModels.length > 0 && (
                  <div className="mb-3">
                    <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-stone-500">
                      Model chính (luôn hiện)
                    </p>
                    <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                      {coreModels.map((modelId) => (
                        <div
                          key={modelId}
                          className="flex items-center gap-2 rounded-lg px-3 py-1.5 bg-white/50"
                        >
                          <span className="flex-1 text-xs font-mono text-stone-700 truncate">
                            {modelId}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Regular models — toggleable */}
                {regularModels.length > 0 && (
                  <div>
                    <div className="mb-2 flex items-center justify-between">
                      <p className="text-[10px] font-medium uppercase tracking-wider text-stone-500">
                        {hasFilter ? "Chọn model để hiển thị" : "Tất cả model đang hiển thị (bấm để ẩn)"}
                      </p>
                      {hasFilter && (
                        <button
                          type="button"
                          onClick={() => {
                            setDirty(true);
                            setSettings((prev) => {
                              const e = { ...prev.enabled_models };
                              delete e[provider];
                              return { ...prev, enabled_models: e };
                            });
                          }}
                          className="text-[10px] text-stone-500 hover:text-stone-700 transition"
                        >
                          Bật tất cả
                        </button>
                      )}
                    </div>
                    <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                      {regularModels.map((modelId) => {
                        const enabled = isEnabled(provider, modelId);
                        const isDefault = defaultModel === modelId;
                        const shortName = modelId
                          .replace("oc/", "")
                          .replace("gemini_free/", "")
                          .replace("openrouter/", "");

                        return (
                          <div key={modelId} className="group flex items-center gap-2">
                            {/* Toggle checkbox */}
                            <button
                              type="button"
                              onClick={() => toggleModel(provider, modelId)}
                              className={cn(
                                "size-5 rounded border-2 flex items-center justify-center shrink-0 transition",
                                enabled
                                  ? "border-emerald-500 bg-emerald-500/20"
                                  : "border-stone-200 bg-stone-100/50",
                              )}
                            >
                              {enabled && <Check className="size-3 text-emerald-400" />}
                            </button>

                            {/* Model name */}
                            <span
                              className={cn(
                                "flex-1 text-xs font-mono truncate transition",
                                enabled ? "text-stone-800" : "text-stone-600",
                              )}
                            >
                              {shortName}
                            </span>

                            {/* Default radio */}
                            <button
                              type="button"
                              onClick={() => setDefault(provider, modelId)}
                              className={cn(
                                "text-[10px] px-2 py-0.5 rounded border transition opacity-0 group-hover:opacity-100",
                                isDefault
                                  ? "border-amber-500/50 text-amber-400 bg-amber-500/10 opacity-100"
                                  : "border-stone-200 text-stone-600 hover:border-stone-200 hover:text-stone-500",
                              )}
                              title="Đặt làm mặc định"
                            >
                              {isDefault ? "Mặc định" : "Đặt mặc định"}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
