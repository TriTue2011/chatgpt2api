"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Save, Cpu, KeyRound, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { request } from "@/lib/request";

export function GeminiCard() {
  const [geminiKey, setGeminiKey]           = useState("");
  const [geminiModel, setGeminiModel]       = useState("gemini-2.5-flash");
  const [geminiEnabled, setGeminiEnabled]   = useState(true);
  const [allModels, setAllModels]           = useState<string[]>([]);  // từ /v1/models (gemini_free)
  const [enabledModels, setEnabledModels]   = useState<string[]>([]);  // đã tick
  const [loading, setLoading]               = useState(true);
  const [saving, setSaving]                 = useState(false);

  useEffect(() => { fetchConfig(); }, []);

  async function fetchConfig() {
    try {
      // Lấy config
      const data = await request.get("/api/settings");
      const cfg  = (data.data as any)?.config || {};
      const p    = (cfg.providers || {}).gemini_free || {};
      const keys = [p.api_key || "", ...(p.api_keys || [])].filter(Boolean);
      setGeminiKey([...new Set(keys)].join("\n"));
      setGeminiModel(p.model || "gemini-2.5-flash");
      setGeminiEnabled(p.enabled !== false);

      // Lấy danh sách model thật từ /v1/models (tab Quản lý Model)
      const mRes = await request.get("/v1/models");
      const mAll: string[] = ((mRes.data as any)?.data || [])
        .filter((m: any) => m.owned_by === "gemini_free" && !String(m.id || "").includes(":"))
        .map((m: any) => String(m.id || ""));
      setAllModels(mAll.sort());

      // extra_models: danh sách đã tick; default = tất cả
      const saved: string[] = Array.isArray(p.extra_models) ? p.extra_models : mAll;
      setEnabledModels(saved.length > 0 ? saved : mAll);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  function toggleModel(model: string) {
    setEnabledModels((prev) =>
      prev.includes(model) ? prev.filter((m) => m !== model) : [...prev, model]
    );
  }

  async function save() {
    setSaving(true);
    try {
      const keyList = geminiKey.split("\n").map((k) => k.trim()).filter(Boolean);
      const cfg     = await request.get("/api/settings");
      const config  = (cfg.data as any)?.config || {};
      const providers = { ...(config.providers || {}) };
      providers.gemini_free = {
        enabled:      geminiEnabled,
        api_key:      keyList[0] || "",
        api_keys:     keyList,
        model:        geminiModel,
        extra_models: enabledModels,
      };
      await request.post("/api/settings", { providers });
      toast.success("Đã lưu!");
    } catch (e: any) { toast.error(e?.message || "Lỗi lưu"); }
    finally { setSaving(false); }
  }

  const keyCount = geminiKey.split("\n").map((k) => k.trim()).filter(Boolean).length;

  if (loading) return (
    <Card className="rounded-2xl card-3d card-tint-violet">
      <CardContent className="flex justify-center p-10">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </CardContent>
    </Card>
  );

  return (
    <Card className="rounded-2xl card-3d card-tint-violet">
      <CardContent className="space-y-5 p-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Cpu className="size-5 text-[var(--foreground)]" />
            <h3 className="text-sm font-semibold text-[var(--foreground)]">Gemini AI Studio</h3>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="flex items-center gap-1 text-xs">
              <KeyRound className="size-3" />
              {keyCount} key{keyCount !== 1 ? "s" : ""}
            </Badge>
            {geminiEnabled
              ? <Badge className="bg-green-500/15 text-green-600 border-green-500/30 text-xs flex items-center gap-1"><CheckCircle2 className="size-3" /> Bật</Badge>
              : <Badge variant="destructive" className="text-xs flex items-center gap-1"><XCircle className="size-3" /> Tắt</Badge>
            }
          </div>
        </div>

        {/* Enable toggle */}
        <label className="flex items-center gap-2 text-sm text-[var(--foreground)] cursor-pointer">
          <input type="checkbox" checked={geminiEnabled} onChange={(e) => setGeminiEnabled(e.target.checked)}
            className="size-4 accent-stone-400" />
          Bật Gemini AI Studio
        </label>

        {/* API Keys */}
        <div className="space-y-2">
          <label className="text-sm text-[var(--foreground)]">
            API Keys (mỗi dòng 1 key)
            <span className="ml-2 text-xs text-[var(--muted-foreground)]">
              — {keyCount} key{keyCount !== 1 ? "s" : ""}, tự round-robin khi hết quota
            </span>
          </label>
          <Textarea
            value={geminiKey}
            onChange={(e) => setGeminiKey(e.target.value)}
            placeholder={"AIzaSyKey1...\nAIzaSyKey2..."}
            className="min-h-28 rounded-xl border-[var(--border)] bg-[var(--secondary)] text-[var(--foreground)] font-mono text-xs placeholder:text-[var(--muted-foreground)]"
          />
          <p className="text-xs text-[var(--muted-foreground)]">
            Lấy key tại <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer"
              className="underline hover:text-[var(--foreground)]">aistudio.google.com/apikey</a>
          </p>
        </div>

        {/* Default model — only picks from ticked models */}
        <div className="flex items-center gap-3">
          <label className="text-sm text-[var(--foreground)] whitespace-nowrap">Model mặc định:</label>
          <select
            value={enabledModels.includes(geminiModel) ? geminiModel : (enabledModels[0] || "")}
            onChange={(e) => setGeminiModel(e.target.value)}
            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--secondary)] px-2 py-1.5 text-sm text-[var(--foreground)]"
          >
            {enabledModels.length === 0 && (
              <option value="">-- Chưa tick model nào --</option>
            )}
            {enabledModels.map((mv) => (
              <option key={mv} value={mv}>{mv}</option>
            ))}
          </select>
        </div>

        {/* Model management – enable/disable per model (like other providers) */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-[var(--foreground)]">🧩 Quản lý Model</label>
            <div className="flex gap-2">
              <button onClick={() => setEnabledModels(allModels)}
                className="text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] underline">
                Chọn tất
              </button>
              <button onClick={() => setEnabledModels([])}
                className="text-[10px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] underline">
                Bỏ tất
              </button>
            </div>
          </div>
          <p className="text-xs text-[var(--muted-foreground)]">
            Tick để bật model trong danh sách /v1/models (dùng gma/&lt;model&gt; vẫn hoạt động dù không tick).
          </p>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--secondary)] divide-y divide-[var(--border)]">
            {allModels.length === 0 && (
              <p className="px-3 py-2 text-xs text-[var(--muted-foreground)]">Đang tải danh sách model...</p>
            )}
            {allModels.map((mv) => (
              <label key={mv}
                className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-[var(--card)] transition-colors">
                <input
                  type="checkbox"
                  checked={enabledModels.includes(mv)}
                  onChange={() => toggleModel(mv)}
                  className="size-4 accent-stone-400 shrink-0"
                />
                <span className="text-xs text-[var(--foreground)] font-mono">{mv}</span>
                {mv === geminiModel && (
                  <Badge variant="secondary" className="ml-auto text-[9px] px-1.5 py-0">mặc định</Badge>
                )}
              </label>
            ))}
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            className="h-10 rounded-xl bg-[var(--secondary)] px-5 text-[var(--foreground)] hover:bg-[var(--card)]"
            onClick={() => void save()}
            disabled={saving}
          >
            {saving ? <LoaderCircle className="size-4 animate-spin mr-1" /> : <Save className="size-4 mr-1" />}
            Lưu
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
