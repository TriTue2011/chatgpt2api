"use client";

import { useCallback, useEffect, useState } from "react";
import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

type McpItem = {
  id: string; name: string; description: string; url: string; category: string;
  icon: string; installed: boolean; enabled: boolean;
};

const CAT_NAMES: Record<string, string> = {
  vn: "Việt Nam", general: "Chung", knowledge: "Kho tri thức",
  developer: "Lập trình", search: "Tìm kiếm", finance: "Tài chính",
  travel: "Du lịch", ha: "Home Assistant", hub: "Từ Hub",
};

export default function McpPage() {
  const { isCheckingAuth } = useAuthGuard(["admin"]);
  const [allMcps, setAllMcps] = useState<McpItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [hubUrl, setHubUrl] = useState("http://172.16.10.38:8005");
  const [connecting, setConnecting] = useState(false);
  const [saving, setSaving] = useState(false);

  // Load everything: presets + hub MCPs
  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      // Get presets (includes installed hub MCPs)
      const presets = await request.get("/api/mcp/presets");
      const presetsData: McpItem[] = (presets.data?.presets || presets.presets || []).map((p: any) => ({
        ...p, installed: p.installed, enabled: p.enabled !== false,
        icon: p.icon || (p.category === "hub" ? "🔌" : "📦"),
      }));

      // Try to fetch from saved hub_url or default
      const savedHub = localStorage.getItem("mcp_hub_url") || hubUrl;
      let hubMcps: McpItem[] = [];
      try {
        const hub = await request.post("/api/mcp/discover", { hub_url: savedHub });
        const hubData = hub.data || hub;
        if (hubData.ok) {
          hubMcps = hubData.mcps.map((m: any) => ({
            ...m, installed: false, enabled: true, category: "hub",
            icon: "🔌", description: m.description || "",
          }));
        }
      } catch (e) { /* hub offline — skip */ }

      // Merge: presets first, then hub MCPs not already in presets
      const merged = [...presetsData];
      for (const h of hubMcps) {
        if (!merged.find(p => p.id === h.id)) {
          merged.push(h);
        }
      }
      setAllMcps(merged);
      if (savedHub) setHubUrl(savedHub);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }, [hubUrl]);

  useEffect(() => { loadAll(); }, []);

  const connectHub = async () => {
    setConnecting(true);
    localStorage.setItem("mcp_hub_url", hubUrl);
    await loadAll();
    setConnecting(false);
  };

  const toggleMcp = async (item: McpItem) => {
    if (item.installed) {
      // Toggle enable/disable
      try {
        await request.post(`/api/mcp/toggle/${item.id}`);
        loadAll();
      } catch (e) { console.error(e); }
    } else {
      // Install
      setSaving(true);
      try {
        await request.post("/api/mcp/install", { id: item.id, url_override: item.url });
        loadAll();
      } catch (e) { console.error(e); }
      setSaving(false);
    }
  };

  const cats = [...new Set(allMcps.map(p => p.category))];

  if (loading) return <div className="p-6 text-muted-foreground">Đang tải...</div>;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">MCP Servers</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Kết nối Hub để mở rộng AI. Tích để bật/tắt MCP.
        </p>
      </div>

      <div className="flex gap-2 items-end">
        <div className="flex-1">
          <Input value={hubUrl} onChange={(e) => setHubUrl(e.target.value)} placeholder="http://172.16.10.38:8005" />
        </div>
        <Button onClick={connectHub} disabled={connecting}>{connecting ? "..." : "Kết nối Hub"}</Button>
      </div>

      {allMcps.length === 0 && <p className="text-muted-foreground">Chưa có MCP nào. Nhập Hub URL và bấm "Kết nối Hub".</p>}

      {cats.map((cat: string) => {
        const items = allMcps.filter(p => p.category === cat);
        if (items.length === 0) return null;
        return (
          <div key={cat}>
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-2">
              {CAT_NAMES[cat] || cat} ({items.length})
            </h2>
            <div className="grid gap-2">
              {items.map(p => (
                <div key={p.id}
                  className="flex items-center gap-3 p-3 border-2 rounded-lg cursor-pointer hover:border-primary/50 transition-colors"
                  style={{borderColor: p.installed ? '#3b82f6' : undefined}}
                  onClick={() => toggleMcp(p)}>
                  <div className="w-6 h-6 flex items-center justify-center rounded border-2 flex-shrink-0"
                       style={{backgroundColor: p.installed ? '#3b82f6' : 'transparent', borderColor: p.installed ? '#3b82f6' : '#64748b'}}>
                    {p.installed && <span style={{color:'#fff',fontSize:'14px',lineHeight:1}}>✓</span>}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">{p.icon} {p.name}</span>
                      {p.installed && <Badge variant="outline" className="text-[10px] border-green-500 text-green-500">Đã cài</Badge>}
                      {p.installed && !p.enabled && <Badge variant="outline" className="text-[10px] border-orange-500 text-orange-500">Đã tắt</Badge>}
                    </div>
                    {p.description && <div className="text-xs text-muted-foreground truncate">{p.description}</div>}
                    <code className="text-xs text-muted-foreground">{p.url}</code>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
