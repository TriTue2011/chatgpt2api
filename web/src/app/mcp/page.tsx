"use client";

import { useCallback, useEffect, useState } from "react";
import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

type Preset = {
  id: string;
  name: string;
  description: string;
  url: string;
  category: string;
  icon: string;
  homepage: string;
  requires_api_key: boolean;
  api_key_help: string;
  tags: string[];
  installed: boolean;
  enabled: boolean;
  has_api_key: boolean;
};

const CAT_NAMES: Record<string, string> = {
  vn: "Việt Nam",
  general: "Chung",
  knowledge: "Kho tri thức",
  developer: "Lập trình",
  search: "Tìm kiếm",
  finance: "Tài chính",
  travel: "Du lịch",
  ha: "Home Assistant",
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

  const fetchPresets = useCallback(async () => {
    try {
      const data = await request.get("/api/mcp/presets");
      setPresets(data.presets || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPresets();
  }, [fetchPresets]);

  const install = async (id: string, apiKey = "", urlOverride = "") => {
    setActionId(id);
    try {
      await request.post("/api/mcp/install", { id, api_key: apiKey, url_override: urlOverride });
      await fetchPresets();
    } finally {
      setActionId(null);
    }
  };

  const uninstall = async (id: string) => {
    if (!confirm("Gỡ cài đặt MCP này?")) return;
    setActionId(id);
    try {
      await request.post(`/api/mcp/uninstall/${id}`);
      await fetchPresets();
    } finally {
      setActionId(null);
    }
  };

  const toggle = async (id: string) => {
    setActionId(id);
    try {
      await request.post(`/api/mcp/toggle/${id}`);
      await fetchPresets();
    } finally {
      setActionId(null);
    }
  };

  const discoverHub = async () => {
    setDiscovering(true);
    try {
      const resp = await request.post("/api/mcp/discover", { hub_url: hubUrl });
      const data = resp.data || resp;
      if (data.ok) {
        setDiscovered(data.mcps.map((m: any) => ({ ...m, selected: false })));
      } else {
        alert(data.error || "Cannot connect to hub");
      }
    } catch (e: any) {
      alert("Error: " + (e.response?.data?.detail || e.message || "Cannot connect"));
    } finally {
      setDiscovering(false);
    }
  };

  const toggleDiscovered = (id: string) => {
    setDiscovered(prev => prev.map(d => d.id === id ? { ...d, selected: !d.selected } : d));
  };

  const installSelected = async () => {
    const selected = discovered.filter(d => d.selected && !d.installed);
    for (const d of selected) {
      await install(d.id, "", d.url);
    }
    await fetchPresets();
    setDiscovered([]);
  };

  if (isCheckingAuth || loading) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        Đang tải danh sách MCP...
      </div>
    );
  }

  const cats = [...new Set(presets.map((p) => p.category))];

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">MCP Servers</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Cài đặt MCP server để mở rộng khả năng AI. Bật/tắt từng server tùy nhu cầu.
          </p>
        </div>
      </div>

      {/* Discover from Hub */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Discover from Hub</CardTitle>
          <CardDescription>Nhập URL vn-mcp-hub để tự động lấy danh sách MCP</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2 mb-3">
            <Input
              placeholder="http://172.16.10.38:8005"
              defaultValue="http://172.16.10.38:8005"
              onChange={(e) => setHubUrl(e.target.value)}
            />
            <Button onClick={discoverHub} disabled={discovering}>
              {discovering ? "Đang tìm..." : "Discover"}
            </Button>
          </div>
          {discovered.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Button size="sm" onClick={installSelected}>Cài các mục đã chọn</Button>
                <span className="text-sm text-muted-foreground">{discovered.filter((d: any) => d.selected).length} đã chọn</span>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {discovered.map((d: any) => (
                  <div key={d.id} className="flex items-center gap-2 p-2 border rounded">
                    <Checkbox checked={d.selected} onCheckedChange={() => toggleDiscovered(d.id)} />
                    <div>
                      <div className="text-sm font-medium">{d.name}</div>
                      <code className="text-xs text-muted-foreground">{d.url}</code>
                      {d.installed && <Badge variant="outline" className="text-[10px] border-green-500 text-green-500 ml-1">Đã cài</Badge>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {cats.map((cat) => (
        <div key={cat}>
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-3">
            {CAT_NAMES[cat] || cat}
          </h2>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {presets
              .filter((p) => p.category === cat)
              .map((p) => (
                <Card key={p.id} className={p.enabled && p.installed ? "border-primary/30" : ""}>
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-xl">{p.icon}</span>
                        <CardTitle className="text-base">{p.name}</CardTitle>
                      </div>
                      {p.installed ? (
                        <Checkbox
                          checked={p.enabled}
                          onCheckedChange={() => toggle(p.id)}
                          disabled={actionId === p.id}
                        />
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            if (p.id === "gitmcp") {
                              setShowKeyDialog(p.id);
                            } else if (p.requires_api_key) {
                              setShowKeyDialog(p.id);
                            } else {
                              install(p.id);
                            }
                          }}
                          disabled={actionId === p.id}
                        >
                          {actionId === p.id ? "..." : "Cài"}
                        </Button>
                      )}
                    </div>
                    <CardDescription className="text-xs">{p.description}</CardDescription>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <div className="flex flex-wrap gap-1 items-center">
                      {p.tags.slice(0, 3).map((t) => (
                        <Badge key={t} variant="secondary" className="text-[10px]">
                          {t}
                        </Badge>
                      ))}
                      {p.requires_api_key && (
                        <Badge variant="outline" className="text-[10px] border-orange-500 text-orange-500">
                          Cần API key
                        </Badge>
                      )}
                      {p.installed && (
                        <Badge variant="outline" className="text-[10px] border-green-500 text-green-500">
                          Đã cài
                        </Badge>
                      )}
                    </div>
                    {p.installed && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="mt-2 text-xs text-muted-foreground"
                        onClick={() => uninstall(p.id)}
                        disabled={actionId === p.id}
                      >
                        Gỡ cài
                      </Button>
                    )}
                    {p.id === "gitmcp" && p.installed && (
                      <div className="mt-2 text-xs text-muted-foreground">
                        URL: {p.url}
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
          </div>
        </div>
      ))}

      {/* API Key Dialog */}
      <Dialog open={!!showKeyDialog} onOpenChange={() => setShowKeyDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {showKeyDialog && presets.find((p) => p.id === showKeyDialog)?.name}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {showKeyDialog === "gitmcp" ? (
              <div>
                <label className="text-sm font-medium">GitMCP URL</label>
                <p className="text-xs text-muted-foreground mb-2">
                  Nhập URL GitMCP: gitmcp.io/{"{owner}/{repo}"}
                </p>
                <Input
                  placeholder="gitmcp.io/owner/repo"
                  value={gitmcpUrl}
                  onChange={(e) => setGitmcpUrl(e.target.value)}
                />
              </div>
            ) : (
              <div>
                <label className="text-sm font-medium">API Key</label>
                <p className="text-xs text-muted-foreground mb-2">
                  {presets.find((p) => p.id === showKeyDialog)?.api_key_help || "Nhập API key để dùng dịch vụ này"}
                </p>
                <Input
                  type="password"
                  placeholder="sk-..."
                  value={apiKeys[showKeyDialog || ""] || ""}
                  onChange={(e) =>
                    setApiKeys((prev) => ({ ...prev, [showKeyDialog || ""]: e.target.value }))
                  }
                />
              </div>
            )}
          </div>
          <Button
            onClick={() => {
              if (showKeyDialog) {
                install(showKeyDialog, apiKeys[showKeyDialog] || "", gitmcpUrl);
                setShowKeyDialog(null);
                setGitmcpUrl("");
              }
            }}
          >
            Cài đặt
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
