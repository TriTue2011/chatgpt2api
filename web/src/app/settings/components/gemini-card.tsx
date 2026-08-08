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
  const [geminiEnabled, setGeminiEnabled]   = useState(true);

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
      setGeminiEnabled(p.enabled !== false);

    } catch (e) { console.error(e); }
    finally { setLoading(false); }
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
              : <Badge variant="danger" className="text-xs flex items-center gap-1"><XCircle className="size-3" /> Tắt</Badge>
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

        {/* Model KHÔNG đặt ở đây nữa.

            Chốt phân chia: Cài đặt giữ KHOÁ, tab Quản lý Model chọn model cho
            chat/vision/HA/ảnh, tab Search chọn model tra web. Trước đây card
            này có cả ô "Model mặc định" lẫn phần tick riêng — hai nguồn cho
            cùng một việc, và bước lọc `enabled_models` lặng lẽ đè lên ô ở đây
            khi hai bên lệch nhau. */}
        <div className="rounded-xl border border-[var(--border)] bg-[var(--secondary)] p-3">
          <p className="text-xs text-[var(--muted-foreground)]">
            Chọn model cho chat / vision / HA / ảnh ở tab{" "}
            <a href="/models" className="underline hover:text-[var(--foreground)]">Quản lý Model</a>
            {" "}(gồm cả nút «Đặt mặc định»). Model tra web đặt ở tab{" "}
            <a href="/search" className="underline hover:text-[var(--foreground)]">Search</a>.
          </p>
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
