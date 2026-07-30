"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Save, Route } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { request } from "@/lib/request";

const MAC_DINH_BASE = "https://api.tokenrouter.com/v1";

export function TokenRouterCard() {
  const [baseUrl, setBaseUrl] = useState(MAC_DINH_BASE);
  const [apiKey, setApiKey] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => { void fetchConfig(); }, []);

  async function fetchConfig() {
    try {
      const data = await request.get("/api/settings");
      const cfg = (data.data as any)?.config || {};
      // Ưu tiên khoá riêng `tokenrouter`; chưa có thì mượn lại mục cũ trong
      // custom_providers để khỏi bắt nhập key lần nữa (provider cũng đọc y vậy).
      const rieng = cfg.tokenrouter || {};
      const cu = (cfg.custom_providers || {}).tokenrouter || {};
      const nguon = (rieng.api_key || (rieng.api_keys || []).length) ? rieng : cu;
      const keys = [nguon.api_key || "", ...(nguon.api_keys || [])].filter(Boolean);
      setApiKey([...new Set(keys)].join("\n"));
      setBaseUrl(nguon.base_url || MAC_DINH_BASE);
      setEnabled(nguon.enabled !== false);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  async function save() {
    setSaving(true);
    try {
      const keyList = apiKey.split("\n").map(k => k.trim()).filter(Boolean);
      // Chỉ gửi đúng khoá `tokenrouter` — /api/settings merge theo field đã gửi
      // nên không đụng tới cấu hình khác.
      await request.post("/api/settings", {
        tokenrouter: {
          enabled,
          base_url: baseUrl.trim() || MAC_DINH_BASE,
          api_key: keyList[0] || "",
          api_keys: keyList,
        },
      });
      toast.success("Đã lưu TokenRouter!");
    } catch (e: any) { toast.error(e?.message || "Lỗi lưu"); }
    finally { setSaving(false); }
  }

  if (loading) return <Card className="rounded-2xl card-3d card-tint-emerald"><CardContent className="flex justify-center p-10"><LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" /></CardContent></Card>;

  return (
    <Card className="rounded-2xl card-3d card-tint-emerald">
      <CardContent className="space-y-4 p-6">
        <div className="flex items-center gap-2">
          <Route className="size-4 text-cyan-600" />
          <h3 className="text-sm font-semibold text-[var(--foreground)]">TokenRouter</h3>
          <span className="text-[10px] text-[var(--muted-foreground)]">api.tokenrouter.com</span>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="size-4 accent-stone-400" />
          Bật TokenRouter
        </label>

        <div className="space-y-2">
          <label className="text-sm text-[var(--foreground)]">Base URL</label>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={MAC_DINH_BASE}
            className="h-9 rounded-xl border-[var(--border)] bg-[var(--secondary)] font-mono text-xs" />
        </div>

        <div className="space-y-2">
          <label className="text-sm text-[var(--foreground)]">API Keys (mỗi dòng 1 key)</label>
          <Textarea value={apiKey} onChange={(e) => setApiKey(e.target.value)}
            placeholder={"tr-xxx...\ntr-yyy..."}
            className="min-h-20 rounded-xl border-[var(--border)] bg-[var(--secondary)] font-mono text-xs" />
        </div>

        <div className="p-3 rounded-lg bg-[var(--secondary)] text-xs text-[var(--muted-foreground)] space-y-1">
          <p><strong>Chat:</strong> prefix <code className="bg-[var(--secondary)] px-1 rounded">tr/</code> — ví dụ: <code className="bg-[var(--secondary)] px-1 rounded">tr/moonshotai/kimi-k3-free</code></p>
          <p>Đường <code className="bg-[var(--secondary)] px-1 rounded">tr/</code> có <strong>thử lại khi lỗi mạng</strong> và xin <code className="bg-[var(--secondary)] px-1 rounded">usage</code> ở cuối stream.</p>
          <p>Mục cũ <code className="bg-[var(--secondary)] px-1 rounded">tokenrouter/</code> trong Custom Providers vẫn chạy như trước, không bị ảnh hưởng.</p>
          <p className="text-amber-600 dark:text-amber-400">Model suy luận (kimi-k3): đừng đặt <code className="bg-[var(--secondary)] px-1 rounded">max_tokens</code> nhỏ — token bị tiêu hết cho phần suy luận nên trả lời rỗng.</p>
        </div>

        <div className="flex justify-end">
          <Button className="h-10 rounded-xl bg-[var(--primary)] px-5 text-[var(--primary-foreground)] hover:brightness-110"
            onClick={() => void save()} disabled={saving}>
            {saving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            Lưu
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
