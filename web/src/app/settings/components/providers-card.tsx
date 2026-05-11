"use client";

import { LoaderCircle, Save, Cpu, Sliders, Combine } from "lucide-react";
import { useState, useEffect } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { request } from "@/lib/request";

export function ProvidersCard() {
  const [config, setConfig] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchConfig();
  }, []);

  async function fetchConfig() {
    try {
      const data = await request.get("/api/settings");
      setConfig((data.data as any)?.config || {});
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    setSaving(true);
    try {
      await request.post("/api/settings", config);
      toast.success("Đã lưu cài đặt");
    } catch (e: any) {
      toast.error(e?.message || "Lỗi lưu");
    } finally {
      setSaving(false);
    }
  }

  function updateProvider(name: string, field: string, value: any) {
    setConfig((prev: any) => ({
      ...prev,
      providers: {
        ...(prev.providers || {}),
        [name]: { ...((prev.providers || {})[name] || {}), [field]: value },
      },
    }));
  }

  function updateBackend(field: string, value: any) {
    setConfig((prev: any) => ({
      ...prev,
      backends: { ...(prev.backends || {}), [field]: value },
    }));
  }

  function updateRateLimit(field: string, value: any) {
    setConfig((prev: any) => ({
      ...prev,
      rate_limit: { ...(prev.rate_limit || {}), [field]: value },
    }));
  }

  function updateNinerouter(field: string, value: any) {
    setConfig((prev: any) => ({
      ...prev,
      ninerouter: { ...(prev.ninerouter || {}), [field]: value },
    }));
  }

  function updateCombo(text: string) {
    const combos: any = {};
    text.split("\n").filter(Boolean).forEach((line) => {
      const [name, models] = line.split("=");
      if (name && models) {
        combos[name.trim()] = models.split(",").map((m) => m.trim()).filter(Boolean);
      }
    });
    setConfig((prev: any) => ({ ...prev, combo_models: combos }));
  }

  function getComboText() {
    const combos = config.combo_models || {};
    return Object.entries(combos).map(([k, v]) => `${k}=${(v as string[]).join(",")}`).join("\n");
  }

  if (loading) {
    return (
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="flex items-center justify-center p-10">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </CardContent>
      </Card>
    );
  }

  const providers = config.providers || {};
  const backends = config.backends || {};
  const rateLimit = config.rate_limit || {};
  const ninerouter = config.ninerouter || {};

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-6 p-6">

        {/* ── Providers ── */}
        <div>
          <div className="flex items-center gap-2 mb-4">
            <Cpu className="size-5 text-stone-700" />
            <h3 className="text-sm font-semibold text-stone-900">Nhà cung cấp AI</h3>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries({
              opencode: "OpenCode (free, no auth)",
              gemini_free: "Gemini AI Studio (API key)",
              openrouter: "OpenRouter (API key)",
              sdwebui: "SD WebUI (local)",
              huggingface: "HuggingFace (API key)",
              cloudflare_ai: "Cloudflare AI (Account ID + Token)",
              serper: "Serper.dev Search (API key)",
              searxng: "SearXNG Search (base URL)",
              brave: "Brave Search (API key)",
            }).map(([name, desc]) => {
              const p = providers[name] || {};
              return (
                <div key={name} className="rounded-xl border border-stone-200 bg-stone-50 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-stone-700">{name}</span>
                    <label className="flex items-center gap-1 text-xs">
                      <input type="checkbox" checked={p.enabled !== false}
                        onChange={(e) => updateProvider(name, "enabled", e.target.checked)}
                        className="size-3 accent-stone-900" />
                      Bật
                    </label>
                  </div>
                  <p className="text-[11px] text-stone-400">{desc}</p>
                  {name === "opencode" ? (
                    <p className="text-[10px] text-emerald-600">Miễn phí, không cần cấu hình gì thêm</p>
                  ) : name === "searxng" || name === "sdwebui" ? (
                    <Input value={p.base_url || ""} onChange={(e) => updateProvider(name, "base_url", e.target.value)}
                      placeholder="http://localhost:8080" className="h-8 rounded-lg border-stone-200 text-xs" />
                  ) : name === "cloudflare_ai" ? (
                    <>
                      <Input value={p.account_id || ""} onChange={(e) => updateProvider(name, "account_id", e.target.value)}
                        placeholder="Account ID" className="h-8 rounded-lg border-stone-200 text-xs" />
                      <Input value={p.api_token || ""} onChange={(e) => updateProvider(name, "api_token", e.target.value)}
                        placeholder="API Token" className="h-8 rounded-lg border-stone-200 text-xs" />
                    </>
                  ) : name === "gemini_free" || name === "serper" ? (
                    <div className="space-y-1">
                      <textarea
                        value={[...new Set([p.api_key || "", ...(p.api_keys || [])])].filter(Boolean).join("\n")}
                        onChange={(e) => {
                          const keys = e.target.value.split("\n").map(k => k.trim()).filter(Boolean);
                          updateProvider(name, "api_key", keys[0] || "");
                          updateProvider(name, "api_keys", keys);
                        }}
                        placeholder="Mỗi dòng 1 API key (hỗ trợ nhiều key, tự động round-robin khi hết quota)"
                        className="w-full h-16 rounded-lg border border-stone-200 text-xs p-2 resize-y"
                      />
                      <div className="flex justify-between items-center">
                        <p className="text-[10px] text-stone-400">Nhiều key → tự chuyển khi hết quota (429)</p>
                        <button type="button"
                          onClick={() => {
                            updateProvider(name, "api_key", "");
                            updateProvider(name, "api_keys", []);
                          }}
                          className="text-[10px] text-red-500 hover:text-red-700">
                          Xóa tất cả
                        </button>
                      </div>
                    </div>
                  ) : (
                    <Input value={p.api_key || ""} onChange={(e) => updateProvider(name, "api_key", e.target.value)}
                      placeholder="API key" className="h-8 rounded-lg border-stone-200 text-xs" />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Backends ── */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Sliders className="size-5 text-stone-700" />
            <h3 className="text-sm font-semibold text-stone-900">Backend mặc định</h3>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <div className="space-y-1">
              <label className="text-xs text-stone-500">Default Chat Model</label>
              <Input value={backends.default_chat || "auto"} onChange={(e) => updateBackend("default_chat", e.target.value)}
                className="h-9 rounded-lg border-stone-200 text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-stone-500">Default Image Size</label>
              <select value={backends.default_image || "1792x1024"} onChange={(e) => updateBackend("default_image", e.target.value)}
                className="w-full h-9 rounded-lg border-stone-200 text-sm bg-white">
                <option value="1024x1024">1024x1024 (1:1)</option>
                <option value="1792x1024">1792x1024 (16:9)</option>
                <option value="1024x1792">1024x1792 (9:16)</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-stone-500">9router URL</label>
              <Input value={ninerouter.base_url || "http://localhost:20128"} onChange={(e) => updateNinerouter("base_url", e.target.value)}
                className="h-9 rounded-lg border-stone-200 text-sm" placeholder="http://localhost:20128" />
            </div>
          </div>
        </div>

        {/* ── Rate Limit ── */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Sliders className="size-5 text-stone-700" />
            <h3 className="text-sm font-semibold text-stone-900">Rate Limit Backoff</h3>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <div className="space-y-1">
              <label className="text-xs text-stone-500">Base (ms)</label>
              <Input value={rateLimit.backoff_base_ms || 2000} onChange={(e) => updateRateLimit("backoff_base_ms", parseInt(e.target.value) || 2000)}
                className="h-9 rounded-lg border-stone-200 text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-stone-500">Max (ms)</label>
              <Input value={rateLimit.backoff_max_ms || 300000} onChange={(e) => updateRateLimit("backoff_max_ms", parseInt(e.target.value) || 300000)}
                className="h-9 rounded-lg border-stone-200 text-sm" />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-stone-500">Max Levels</label>
              <Input value={rateLimit.max_levels || 15} onChange={(e) => updateRateLimit("max_levels", parseInt(e.target.value) || 15)}
                className="h-9 rounded-lg border-stone-200 text-sm" />
            </div>
          </div>
        </div>

        {/* ── Combo Models ── */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Combine className="size-5 text-stone-700" />
            <h3 className="text-sm font-semibold text-stone-900">Combo Models</h3>
          </div>
          <Textarea
            value={getComboText()}
            onChange={(e) => updateCombo(e.target.value)}
            placeholder="ha-agent=cx/auto,oc/auto,chatgpt/auto"
            className="min-h-24 rounded-xl border-stone-200 bg-white font-mono text-xs"
          />
          <p className="text-xs text-stone-400 mt-1">Mỗi dòng: tên=model1,model2,model3. Thứ tự là thứ tự fallback.</p>
        </div>

        <div className="flex justify-end">
          <Button className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
            onClick={() => void save()} disabled={saving}>
            {saving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            Lưu tất cả
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
