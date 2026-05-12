"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Plus, Save, Trash2, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { request } from "@/lib/request";

type CustomProvider = {
  name: string;
  base_url: string;
  api_key: string;
  prefix: string;
  enabled: boolean;
};

export function CustomProvidersCard() {
  const [providers, setProviders] = useState<Record<string, CustomProvider>>({});
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [form, setForm] = useState<CustomProvider>({ name: "", base_url: "", api_key: "", prefix: "", enabled: true });

  useEffect(() => { fetchProviders(); }, []);

  async function fetchProviders() {
    setLoading(true);
    try {
      const data = await request.get("/api/v1/custom-providers");
      const raw = (data.data as any)?.custom_providers || {};
      // Combine api_key + api_keys into a multi-line string for display
      const merged: Record<string, CustomProvider> = {};
      for (const [id, p] of Object.entries(raw) as any) {
        const keys = [p.api_key || "", ...(p.api_keys || [])].filter(Boolean);
        merged[id] = { ...p, api_key: [...new Set(keys)].join("\n") };
      }
      setProviders(merged);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  function resetForm() {
    setForm({ name: "", base_url: "", api_key: "", prefix: "", enabled: true });
    setAdding(false);
  }

  function startEdit(id: string) {
    const p = providers[id];
    if (!p) return;
    setForm({ ...p });
    setAdding(true);
  }

  async function saveProvider() {
    if (!form.name.trim() || !form.base_url.trim() || !form.api_key.trim()) {
      toast.error("Tên, Base URL và API Key là bắt buộc");
      return;
    }
    const prefix = form.prefix.trim() || form.name.trim().toLowerCase().replace(/\s+/g, "_");
    const providerId = prefix;

    // Split multi-line keys
    const keyList = form.api_key.split("\n").map(k => k.trim()).filter(Boolean);

    setSaving(providerId);
    try {
      await request.post("/api/v1/custom-providers", {
        provider: {
          ...form,
          prefix,
          api_key: keyList[0] || "",
          api_keys: keyList,
        },
      });
      toast.success(`Đã lưu provider "${form.name}"!`);
      resetForm();
      await fetchProviders();
    } catch (e: any) {
      const msg = e?.response?.data?.detail?.error || e?.message || "Lỗi lưu";
      toast.error(msg);
    }
    finally { setSaving(null); }
  }

  async function deleteProvider(id: string) {
    try {
      await request.delete(`/api/v1/custom-providers/${id}`);
      toast.success(`Đã xóa provider`);
      await fetchProviders();
    } catch (e: any) { toast.error(e?.message || "Lỗi xóa"); }
  }

  async function toggleProvider(id: string, enabled: boolean) {
    const p = providers[id];
    if (!p) return;
    try {
      await request.post("/api/v1/custom-providers", {
        provider: { ...p, prefix: id, enabled },
      });
      await fetchProviders();
    } catch (e: any) { toast.error(e?.message || "Lỗi cập nhật"); }
  }

  if (loading) return <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm"><CardContent className="flex justify-center p-10"><LoaderCircle className="size-5 animate-spin text-stone-400" /></CardContent></Card>;

  const entries = Object.entries(providers);

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-4 p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ExternalLink className="size-5 text-stone-700" />
            <h3 className="text-sm font-semibold text-stone-900">Custom Providers</h3>
            <span className="text-[10px] text-stone-400">{entries.length} provider</span>
          </div>
          {!adding && (
            <Button className="h-8 rounded-lg bg-stone-950 px-3 text-xs text-white hover:bg-stone-800"
              onClick={() => setAdding(true)}>
              <Plus className="size-3.5 mr-1" /> Thêm API
            </Button>
          )}
        </div>

        <p className="text-xs text-stone-500">Thêm bất kỳ OpenAI-compatible API nào (DeepSeek, vLLM, LiteLLM, Gemini Server...). Model được tự động fetch từ /v1/models.</p>

        {/* Add/Edit form */}
        {adding && (
          <div className="space-y-3 rounded-xl border border-stone-200 bg-stone-50 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="text-xs text-stone-600">Tên hiển thị</label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="VD: DeepSeek" className="mt-1 h-9 rounded-lg border-stone-200 text-sm" />
              </div>
              <div>
                <label className="text-xs text-stone-600">Prefix (dùng trong model ID)</label>
                <Input value={form.prefix} onChange={(e) => setForm({ ...form, prefix: e.target.value })}
                  placeholder="VD: deepseek" className="mt-1 h-9 rounded-lg border-stone-200 text-sm font-mono" />
              </div>
              <div className="sm:col-span-2">
                <label className="text-xs text-stone-600">Base URL</label>
                <Input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="VD: https://api.deepseek.com" className="mt-1 h-9 rounded-lg border-stone-200 text-sm font-mono" />
              </div>
              <div className="sm:col-span-2">
                <label className="text-xs text-stone-600">API Keys (mỗi dòng 1 key)</label>
                <Textarea value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder={"sk-...\nsk-..."}
                  className="mt-1 min-h-20 rounded-xl border-stone-200 font-mono text-xs" />
                <p className="text-xs text-stone-400 mt-1">Nhiều key → tự động round-robin khi rate limit</p>
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <Button className="h-8 rounded-lg border border-stone-200 bg-white text-xs text-stone-600 hover:bg-stone-100"
                onClick={resetForm}>Hủy</Button>
              <Button className="h-8 rounded-lg bg-stone-950 px-4 text-xs text-white hover:bg-stone-800"
                onClick={() => void saveProvider()} disabled={saving !== null}>
                {saving ? <LoaderCircle className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                Lưu
              </Button>
            </div>
          </div>
        )}

        {/* Provider list */}
        {entries.length > 0 && (
          <div className="space-y-2">
            {entries.map(([id, p]) => (
              <div key={id} className="flex items-center gap-3 rounded-lg border border-stone-100 px-3 py-2.5">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={p.enabled !== false}
                    onChange={(e) => toggleProvider(id, e.target.checked)}
                    className="size-4 accent-stone-900" />
                </label>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-stone-800">{p.name}</span>
                    <code className="text-[10px] bg-stone-100 px-1.5 py-0.5 rounded text-stone-500">{p.prefix}/model-name</code>
                  </div>
                  <p className="text-[10px] text-stone-400 truncate">{p.base_url}</p>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => startEdit(id)}
                    className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600">
                    <Save className="size-3.5" />
                  </button>
                  <button onClick={() => deleteProvider(id)}
                    className="rounded p-1 text-stone-400 hover:bg-red-50 hover:text-red-500">
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {entries.length === 0 && !adding && (
          <div className="flex flex-col items-center py-6 text-stone-400">
            <ExternalLink className="size-8 mb-2 opacity-40" />
            <p className="text-xs">Chưa có custom provider nào</p>
            <p className="text-[10px]">Thêm DeepSeek, vLLM, LiteLLM hoặc bất kỳ OpenAI-compatible API</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
