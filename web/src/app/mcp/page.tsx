"use client";

import { useCallback, useEffect, useState } from "react";
import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Preset = {
  id: string; name: string; description: string; url: string; category: string;
  icon: string; homepage: string; requires_api_key: boolean; api_key_help: string;
  tags: string[]; installed: boolean; enabled: boolean; has_api_key: boolean;
};

const CAT_NAMES: Record<string, string> = {
  vn: "Việt Nam", general: "Chung", knowledge: "Kho tri thức",
  developer: "Lập trình", search: "Tìm kiếm", finance: "Tài chính",
  travel: "Du lịch", ha: "Home Assistant", hub: "Từ Hub",
};

export default function McpPage() {
  const { isCheckingAuth } = useAuthGuard(["admin"]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [showKeyDialog, setShowKeyDialog] = useState<string | null>(null);
  const [gitmcpUrl, setGitmcpUrl] = useState("");
  const [hubUrl, setHubUrl] = useState("http://172.16.10.38:8005");
  const [discovered, setDiscovered] = useState<any[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [installing, setInstalling] = useState(false);

  const fetchPresets = useCallback(async () => {
    try {
      const data = await request.get("/api/mcp/presets");
      setPresets(data.presets || []);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchPresets(); }, [fetchPresets]);

  // Auto-connect to hub on load if URL is configured
  useEffect(() => {
    request.get("/api/mcp/presets").then((d: any) => {
      if (d.presets?.some((p: any) => p.category === "hub")) {
        discoverHub(true);
      }
    }).catch(() => {});
  }, []);

  const install = async (id: string, apiKey = "", urlOverride = "") => {
    setActionId(id);
    try { await request.post("/api/mcp/install", { id, api_key: apiKey, url_override: urlOverride }); }
    finally { setActionId(null); }
  };

  const toggle = async (id: string) => {
    setActionId(id);
    try {
      await request.post(`/api/mcp/toggle/${id}`);
      await fetchPresets();
    } finally { setActionId(null); }
  };

  const discoverHub = async (silent = false) => {
    if (!silent) setDiscovering(true);
    try {
      const resp = await request.post("/api/mcp/discover", { hub_url: hubUrl });
      const data = resp.data || resp;
      if (data.ok) {
        const merged = data.mcps.map((m: any) => {
          const existing = presets.find(p => p.id === m.id);
          return { ...m, selected: existing ? existing.installed : false, installed: existing ? existing.installed : false, enabled: existing ? existing.enabled : true, category: "hub", icon: "🔌", tags: ["hub"], requires_api_key: false, api_key_help: "", homepage: "", has_api_key: false, description: m.description || "" };
        });
        setDiscovered(merged);
      } else if (!silent) {
        alert(data.error || "Cannot connect to hub");
      }
    } catch (e: any) {
      if (!silent) alert("Error: " + (e.response?.data?.detail || e.message || "Cannot connect"));
    } finally {
      if (!silent) setDiscovering(false);
    }
  };

  const toggleDiscovered = (id: string) => {
    setDiscovered(prev => prev.map(d => d.id === id ? { ...d, selected: !d.selected } : d));
  };

  const installSelected = async () => {
    const selected = discovered.filter((d: any) => d.selected && !d.installed);
    if (selected.length === 0) { alert("Chưa chọn MCP nào mới."); return; }
    setInstalling(true);
    let ok = 0;
    for (const d of selected) {
      try { await install(d.id, "", d.url); ok++; } catch (e) {}
    }
    setInstalling(false);
    alert(`Đã lưu ${ok}/${selected.length} MCP.`);
    await fetchPresets();
    setDiscovered([]);
  };

  if (isCheckingAuth || loading) {
    return <div className="flex items-center justify-center h-64 text-muted-foreground">Đang tải...</div>;
  }

  const allMcps = [...presets, ...discovered.filter((d: any) => !presets.find(p => p.id === d.id))];
  const cats = [...new Set(allMcps.map((p: any) => p.category))];

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">MCP Servers</h1>
          <p className="text-muted-foreground text-sm mt-1">Kết nối vn-mcp-hub để mở rộng AI.</p>
        </div>
      </div>

      <div className="flex gap-2 items-end">
        <div className="flex-1">
          <label className="text-sm font-medium">Hub URL</label>
          <Input value={hubUrl} onChange={(e) => setHubUrl(e.target.value)} placeholder="http://172.16.10.38:8005" />
        </div>
        <Button onClick={() => discoverHub()} disabled={discovering}>{discovering ? "..." : "Kết nối"}</Button>
        {discovered.filter((d: any) => d.selected && !d.installed).length > 0 && (
          <Button onClick={installSelected} disabled={installing} className="bg-green-600 hover:bg-green-700">
            {installing ? "..." : `Lưu (${discovered.filter((d: any) => d.selected && !d.installed).length})`}
          </Button>
        )}
        {discovered.length > 0 && (
          <Button variant="outline" onClick={() => setDiscovered([])}>Hủy</Button>
        )}
      </div>

      {cats.map((cat: string) => (
        <div key={cat}>
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-2">
            {CAT_NAMES[cat] || cat} ({allMcps.filter((p: any) => p.category === cat).length})
          </h2>
          <div className="grid gap-2">
            {allMcps.filter((p: any) => p.category === cat).map((p: any) => {
              const isSelected = p.installed || discovered.find((d: any) => d.id === p.id && d.selected);
              return (
                <div key={p.id}
                  className="flex items-center gap-3 p-3 border-2 rounded-lg cursor-pointer hover:border-primary/50 transition-colors"
                  style={{borderColor: isSelected ? '#3b82f6' : undefined}}
                  onClick={() => { if (p.installed) toggle(p.id); else toggleDiscovered(p.id); }}>
                  <div className="w-6 h-6 flex items-center justify-center rounded border-2 flex-shrink-0"
                       style={{backgroundColor: isSelected ? '#3b82f6' : 'transparent', borderColor: isSelected ? '#3b82f6' : '#64748b'}}>
                    {isSelected && <span style={{color:'#fff',fontSize:'14px',lineHeight:1}}>✓</span>}
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
              );
            })}
          </div>
        </div>
      ))}

      {/* API Key Dialog */}
      <Dialog open={!!showKeyDialog} onOpenChange={() => setShowKeyDialog(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{showKeyDialog && presets.find((p) => p.id === showKeyDialog)?.name}</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            {showKeyDialog === "gitmcp" ? (
              <div>
                <label className="text-sm font-medium">GitMCP URL</label>
                <Input placeholder="gitmcp.io/owner/repo" value={gitmcpUrl} onChange={(e) => setGitmcpUrl(e.target.value)} />
              </div>
            ) : (
              <div>
                <label className="text-sm font-medium">API Key</label>
                <Input type="password" placeholder="sk-..." value={apiKeys[showKeyDialog || ""] || ""}
                  onChange={(e) => setApiKeys((prev) => ({ ...prev, [showKeyDialog || ""]: e.target.value }))} />
              </div>
            )}
          </div>
          <Button onClick={() => { if (showKeyDialog) { install(showKeyDialog, apiKeys[showKeyDialog] || "", gitmcpUrl); setShowKeyDialog(null); setGitmcpUrl(""); } }}>Cài đặt</Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
