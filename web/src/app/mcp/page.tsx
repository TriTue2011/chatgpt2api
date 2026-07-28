"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { RefreshCw, Trash2, Plug2, Search, CheckCircle2 } from "lucide-react";

// vn-mcp-hub now runs in-process; its admin/studio API is proxied here.
const HUB = "/api/mcp/hub";
const STUDIO = `${HUB}/api/studio`;
const RAG = `${HUB}/api/rag`;

const INPUT =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]";

type Toast = { msg: string; ok: boolean } | null;

// ── Preset groups (built-in vn-mcp-hub servers) ────────────────────────────
type McpGroup = {
  name: string; icon: string; description: string;
  mcps: { id: string; name: string; url: string }[];
  installedCount: number; totalCount: number;
};

const GROUPS: McpGroup[] = [
  { name: "Tìm kiếm", icon: "🔍", description: "Search web, đọc URL, Wikipedia, paper, luật, federated",
    mcps: [{id:"vn_search",name:"Tìm kiếm Web",url:""},{id:"web_reader",name:"Đọc Web",url:""},{id:"wikipedia",name:"Wikipedia",url:""},{id:"arxiv",name:"arXiv Paper",url:""},{id:"federated_search",name:"Federated Search",url:""},{id:"vn_law",name:"Tra cứu Luật",url:""}], installedCount:0, totalCount:6 },
  { name: "Thời tiết", icon: "🌤️", description: "Thời tiết 4 nguồn quốc tế",
    mcps: [{id:"vn_weather",name:"Thời tiết VN",url:""}], installedCount:0, totalCount:1 },
  { name: "Tin tức", icon: "📰", description: "Tin VN + BBC + Google News",
    mcps: [{id:"vn_news",name:"Tin tức VN",url:""}], installedCount:0, totalCount:1 },
  { name: "Tài chính", icon: "💵", description: "Tỷ giá, vàng, cổ phiếu VN",
    mcps: [{id:"vn_currency",name:"Tỷ giá & Vàng",url:""},{id:"vn_stock",name:"Cổ phiếu VN",url:""}], installedCount:0, totalCount:2 },
  { name: "Knowledge Base", icon: "📚", description: "7 kho tri thức RAG (điện nước, y tế, giáo dục, ngoại ngữ, khoa học, tự nhiên, xã hội)",
    mcps: [{id:"kb_dien_nuoc",name:"Kho Điện Nước",url:""},{id:"kb_y_te",name:"Kho Y Tế",url:""},{id:"kb_giao_duc",name:"Kho Giáo Dục",url:""},{id:"kb_ngoai_ngu",name:"Kho Ngoại Ngữ",url:""},{id:"kb_khoa_hoc",name:"Kho Khoa Học",url:""},{id:"kb_tu_nhien",name:"Kho Tự Nhiên",url:""},{id:"kb_xa_hoi",name:"Kho Xã Hội",url:""}], installedCount:0, totalCount:7 },
  { name: "VN Khác", icon: "🏛️", description: "Lịch âm",
    mcps: [{id:"vn_lunar",name:"Lịch Âm",url:""}], installedCount:0, totalCount:1 },
  { name: "Khác", icon: "📦", description: "Web Agent, YouTube Transcript, HA Helper",
    mcps: [{id:"web_agent",name:"Web Agent",url:""},{id:"youtube",name:"YouTube Transcript",url:""},{id:"ha_helper",name:"HA Helper",url:""}], installedCount:0, totalCount:3 },
];

type TabId = "servers" | "kb" | "settings" | "r2" | "external" | "ingest" | "devices";
const TABS: { id: TabId; label: string }[] = [
  { id: "servers", label: "MCP Servers" },
  { id: "kb", label: "Knowledge Base" },
  { id: "settings", label: "Cài đặt RAG" },
  { id: "r2", label: "R2 Storage" },
  { id: "external", label: "External MCP" },
  { id: "ingest", label: "Nạp RAG" },
  { id: "devices", label: "Thiết bị của tôi" },
];

export default function McpPage() {
  const { isCheckingAuth } = useAuthGuard(["admin"]);
  const [tab, setTab] = useState<TabId>("servers");
  const [toast, setToast] = useState<Toast>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((msg: string, ok = true) => {
    setToast({ msg, ok });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  if (isCheckingAuth) return null;

  return (
    <div className="space-y-6">
      <div className="animate-in">
        <h1 className="text-xl font-bold">MCP Servers & Studio</h1>
        <p className="text-sm text-[var(--muted-foreground)] mt-0.5">
          Quản lý MCP, Knowledge Base, RAG, R2 — tất cả chạy nội bộ trong cùng container.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--card)] p-1">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`shrink-0 rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${
              tab === t.id ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "servers" && <ServersTab showToast={showToast} />}
      {tab === "kb" && <KbTab showToast={showToast} />}
      {tab === "settings" && <SettingsTab showToast={showToast} />}
      {tab === "r2" && <R2Tab showToast={showToast} />}
      {tab === "external" && <ExternalTab showToast={showToast} />}
      {tab === "ingest" && <IngestTab showToast={showToast} />}
      {tab === "devices" && <DevicesTab showToast={showToast} />}

      {toast && (
        <div className={`fixed top-5 right-5 z-50 rounded-lg px-4 py-2.5 text-sm font-semibold shadow-lg ${
          toast.ok ? "bg-emerald-500 text-white" : "bg-red-500 text-white"
        }`}>
          {toast.msg}
        </div>
      )}
    </div>
  );
}

type TabProps = { showToast: (msg: string, ok?: boolean) => void };

// ── Tab: MCP Servers (install/uninstall presets) ───────────────────────────
function ServersTab({ showToast }: TabProps) {
  const [groups, setGroups] = useState<McpGroup[]>(GROUPS);
  const [saving, setSaving] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadStatus = useCallback(async () => {
    try {
      const res = await request.get("/api/mcp/presets");
      const data = res.data?.presets || [];
      const installed: Record<string, { url?: string }> = {};
      data.forEach((p: { id: string; installed?: boolean; url?: string }) => {
        if (p.installed) installed[p.id] = p;
      });
      setGroups((prev) => prev.map((g) => ({
        ...g,
        installedCount: g.mcps.filter((m) => installed[m.id]).length,
        mcps: g.mcps.map((m) => (installed[m.id]?.url ? { ...m, url: installed[m.id].url! } : m)),
      })));
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const installGroup = async (group: McpGroup) => {
    setSaving(group.name);
    const allInstalled = group.installedCount === group.totalCount;
    for (const m of group.mcps) {
      try {
        if (allInstalled) await request.post(`/api/mcp/uninstall/${m.id}`);
        else await request.post("/api/mcp/install", { id: m.id, url_override: m.url });
      } catch { /* ignore */ }
    }
    setGroups((prev) => prev.map((g) => g.name === group.name ? { ...g, installedCount: allInstalled ? 0 : g.totalCount } : g));
    setSaving(null);
    showToast(allInstalled ? `Đã gỡ ${group.name}` : `Đã cài ${group.name}`);
  };

  if (loading) return (
    <div className="grid gap-4 md:grid-cols-2">
      {[...Array(6)].map((_, i) => <div key={i} className="skeleton h-32 rounded-lg" />)}
    </div>
  );

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {groups.map((g, idx) => {
        const allOn = g.installedCount === g.totalCount && g.totalCount > 0;
        const partial = g.installedCount > 0 && !allOn;
        const statusVariant = allOn ? "success" : partial ? "warning" : "muted";
        return (
          <div key={g.name} onClick={() => installGroup(g)}
            className="card cursor-pointer animate-in hover:border-[var(--primary)]/30"
            style={{ animationDelay: `${idx * 0.05}s`, borderLeft: allOn ? "3px solid var(--accent)" : partial ? "3px solid #f6c23e" : undefined }}>
            <div className="card-body">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">{g.icon}</span>
                  <div>
                    <h3 className="font-semibold text-sm">{g.name}</h3>
                    <p className="text-xs text-[var(--muted-foreground)] mt-0.5 max-w-xs">{g.description}</p>
                  </div>
                </div>
                <span className={`badge badge-${statusVariant} shrink-0`}>
                  {saving === g.name ? "..." : `${g.installedCount}/${g.totalCount}`}
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {g.mcps.map((m) => (
                  <span key={m.id} className="text-xs px-2 py-1 rounded-md bg-[var(--secondary)] text-[var(--secondary-foreground)]"
                    style={{ opacity: m.url ? 1 : 0.45 }}>
                    {m.name}{!m.url ? " —" : ""}
                  </span>
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Tab: Knowledge Base (create / list / sources / keys / delete / refresh) ─
type KbRow = { name: string; label?: string; chunks?: number; builtin?: boolean };
type SrcInfo = { enabled?: boolean; help?: string; needsKey?: boolean; hasKey?: boolean };

function KbTab({ showToast }: TabProps) {
  const [rows, setRows] = useState<KbRow[]>([]);
  const [sources, setSources] = useState<Record<string, Record<string, SrcInfo | boolean>>>({});
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [content, setContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [converting, setConverting] = useState(false);
  const [haBusy, setHaBusy] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [mcpR, srcR] = await Promise.all([request.get(`${STUDIO}/mcps`), request.get(`${STUDIO}/sources`)]);
      setRows(mcpR.data?.mcps || []);
      setSources(srcR.data?.sources || {});
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!name.trim() || !content.trim()) { showToast("Tên và nội dung không được trống", false); return; }
    setCreating(true);
    try {
      const r = await request.post(`${STUDIO}/kb`, { name: name.trim(), label: label.trim(), content });
      if (r.data?.ok) {
        showToast(`Đã tạo ${r.data.name} (${r.data.chunks} chunks)`);
        setName(""); setLabel(""); setContent(""); load();
      } else showToast((r.data?.errors || ["Lỗi"]).join(". "), false);
    } catch (e) { showToast(String((e as Error).message), false); }
    setCreating(false);
  };

  const del = async (n: string) => {
    if (!window.confirm(`Xoá KB ${n}?`)) return;
    try {
      const r = await request.delete(`${STUDIO}/kb/${encodeURIComponent(n)}`);
      if (r.data?.ok) { showToast(`Đã xoá ${n}`); load(); } else showToast(r.data?.error || "Lỗi", false);
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  // Chuyển file (PDF/Word/PPT/Excel/HTML/CSV/EPUB) → markdown qua markitdown, chèn vào ô nội dung
  const convertFile = async (f: File | null) => {
    if (!f) return;
    setConverting(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await request.post(`${STUDIO}/convert`, fd);
      if (r.data?.ok) {
        setContent((prev) => (prev ? prev + "\n\n" : "") + (r.data.markdown || ""));
        if (!label.trim()) setLabel(f.name.replace(/\.[^.]+$/, ""));
        showToast(`Đã chuyển ${f.name} sang markdown`);
      } else showToast(r.data?.error || "Lỗi chuyển đổi file", false);
    } catch (e) { showToast(String((e as Error).message), false); }
    setConverting(false);
  };

  // Quét Home Assistant → sinh tài liệu nhà → nạp vào KB ha_docs
  const buildHaDocs = async () => {
    if (!window.confirm("Quét Home Assistant và tạo/cập nhật KB 'ha_docs'?")) return;
    setHaBusy(true);
    try {
      const r = await request.post("/api/mcp/ha-docs/refresh");
      if (r.data?.ok) { showToast(`Đã tạo tài liệu nhà (${r.data.chunks} chunks)`); load(); }
      else showToast(r.data?.error || "Lỗi", false);
    } catch (e) { showToast(String((e as Error).message), false); }
    setHaBusy(false);
  };

  const refresh = async (n: string) => {
    if (!window.confirm(`Chạy tổng hợp AI cho ${n}? (vài phút)`)) return;
    showToast("Đang kích hoạt tổng hợp AI...");
    try {
      const r = await request.post(`${RAG}/refresh/${encodeURIComponent(n)}`);
      showToast(r.data?.message || "Đã gửi yêu cầu", !!r.data?.ok);
    } catch { showToast("Lỗi", false); }
  };

  const toggleSource = async (mcp: string, key: string, enabled: boolean) => {
    try {
      await request.post(`${STUDIO}/sources/${encodeURIComponent(mcp)}`, { [key]: enabled });
      setSources((prev) => ({ ...prev, [mcp]: { ...prev[mcp], [key]: { ...(prev[mcp]?.[key] as SrcInfo), enabled } } }));
      showToast(`${key} ${enabled ? "ON" : "OFF"}`);
    } catch { showToast("Lỗi", false); }
  };

  const saveKey = async (key: string, value: string) => {
    if (!value) return;
    try {
      const r = await request.post(`${STUDIO}/key/${encodeURIComponent(key)}`, { api_key: value });
      if (r.data?.ok) showToast(`Đã lưu API key cho ${key}`);
    } catch { showToast("Lỗi", false); }
  };

  return (
    <div className="space-y-4">
      <div className="card"><div className="card-body space-y-3">
        <h3 className="font-semibold">Tạo Knowledge Base mới</h3>
        <input className={INPUT} placeholder="Tên collection (slug: a-z0-9_)" value={name}
          onChange={(e) => setName(e.target.value)} maxLength={30} />
        <input className={INPUT} placeholder="Nhãn hiển thị" value={label} onChange={(e) => setLabel(e.target.value)} />
        <textarea className={`${INPUT} min-h-32 font-mono`} placeholder="Dán nội dung markdown..." value={content}
          onChange={(e) => setContent(e.target.value)} />
        <div className="flex items-center gap-3 flex-wrap">
          <button className="btn btn-primary" disabled={creating} onClick={create}>{creating ? "Đang tạo..." : "Tạo KB"}</button>
          <label className="btn cursor-pointer">
            {converting ? "Đang chuyển..." : "📎 Nạp từ file"}
            <input type="file" hidden accept=".txt,.md,.pdf,.docx,.pptx,.xlsx,.html,.htm,.csv,.epub"
              onChange={(e) => { convertFile(e.target.files?.[0] || null); e.target.value = ""; }} />
          </label>
          <span className="text-xs text-[var(--muted-foreground)]">PDF/Word/PPT/Excel/HTML/CSV/EPUB → markdown (markitdown), chèn vào ô nội dung.</span>
        </div>
      </div></div>

      <div className="card"><div className="card-body flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="font-semibold">🏠 Tài liệu nhà (Home Assistant)</h3>
          <p className="text-sm text-[var(--muted-foreground)] mt-0.5">
            Quét khu vực, thiết bị, automation, cảm biến... từ HA rồi nạp vào KB <code>ha_docs</code> để AI hiểu cấu trúc nhà.
          </p>
        </div>
        <button className="btn btn-primary" disabled={haBusy} onClick={buildHaDocs}>{haBusy ? "Đang quét HA..." : "Tạo / Cập nhật"}</button>
      </div></div>

      <div className="card"><div className="card-body">
        <h3 className="font-semibold mb-3">Danh sách Knowledge Base</h3>
        <div className="space-y-1.5">
          {rows.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">Chưa có MCP/KB.</p>}
          {rows.map((m) => {
            const srcCfg = sources[m.name] || {};
            const srcKeys = Object.keys(srcCfg);
            const isKb = m.name.startsWith("kb_");
            return (
              <div key={m.name} className="rounded-lg border border-[var(--border)] px-3.5 py-2.5">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className={`badge badge-${m.builtin ? "success" : "warning"}`}>{m.builtin ? "built-in" : "dynamic"}</span>
                  <span className="font-medium text-sm">{m.label || m.name}</span>
                  <span className="text-xs text-[var(--muted-foreground)]">{m.name} · {m.chunks ?? "-"} chunks</span>
                  <div className="ml-auto flex gap-2">
                    {srcKeys.length > 0 && (
                      <button className="text-xs px-2 py-1 rounded-md bg-[var(--secondary)]"
                        onClick={() => setExpanded(expanded === m.name ? null : m.name)}>{srcKeys.length} nguồn</button>
                    )}
                    {isKb && <button className="text-xs px-2 py-1 rounded-md bg-[var(--secondary)] inline-flex items-center gap-1"
                      onClick={() => refresh(m.name)}><RefreshCw className="size-3" />Update</button>}
                    {!m.builtin && <button className="text-xs px-2 py-1 rounded-md bg-red-500/10 text-red-500 inline-flex items-center gap-1"
                      onClick={() => del(m.name)}><Trash2 className="size-3" />Xoá</button>}
                  </div>
                </div>
                {expanded === m.name && srcKeys.length > 0 && (
                  <div className="mt-3 space-y-2 border-t border-[var(--border)] pt-3">
                    {srcKeys.map((k) => {
                      const v = srcCfg[k];
                      const info: SrcInfo = typeof v === "object" ? v : { enabled: v };
                      return (
                        <div key={k} className="space-y-1.5">
                          <div className="flex items-center justify-between gap-3">
                            <div className="flex flex-col min-w-0">
                              <span className="text-sm inline-flex items-center gap-1.5">
                                {k}
                                {info.needsKey && (
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${info.hasKey ? "bg-emerald-500/15 text-emerald-500" : "bg-amber-500/15 text-amber-500"}`}>
                                    {info.hasKey ? "có key" : "cần key"}
                                  </span>
                                )}
                              </span>
                              {info.help && <span className="text-xs text-[var(--muted-foreground)]">{info.help}</span>}
                            </div>
                            <input type="checkbox" className="size-4 shrink-0" checked={!!info.enabled}
                              onChange={(e) => toggleSource(m.name, k, e.target.checked)} />
                          </div>
                          {/* API key field integrated right under the source that needs one */}
                          {info.needsKey && (
                            <input type="password"
                              className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
                              placeholder={info.hasKey ? "✓ Đã lưu key — nhập để thay" : `Nhập API key cho ${k}…`}
                              onBlur={(e) => { if (e.target.value) saveKey(k, e.target.value); }} />
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div></div>
    </div>
  );
}

// ── Tab: RAG settings ──────────────────────────────────────────────────────
type Settings = Record<string, string | number>;
function SettingsTab({ showToast }: TabProps) {
  const [s, setS] = useState<Settings>({});
  const [models, setModels] = useState<string[]>([]);
  const set = (k: string, v: string | number) => setS((prev) => ({ ...prev, [k]: v }));

  const fetchModels = useCallback(async () => {
    try {
      const r = await request.get(`${RAG}/models`);
      if (r.data?.ok && r.data.models) setModels(r.data.models);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    (async () => {
      try { const r = await request.get(`${STUDIO}/settings`); setS(r.data || {}); } catch { /* ignore */ }
      fetchModels();
    })();
  }, [fetchModels]);

  const save = async () => {
    const refreshDays = Number(s.refresh_interval_days) || 90;
    const softDays = Number(s.soft_notify_days) || 60;
    if (softDays >= refreshDays) { showToast('"Gợi ý" phải NHỎ HƠN "Số ngày refresh"', false); return; }
    try {
      const r = await request.post(`${STUDIO}/settings`, {
        sync_interval_minutes: Number(s.sync_interval_minutes) || 360,
        storage_mode: s.storage_mode || "local",
        auto_update_interval_hours: Number(s.auto_update_interval_hours) || 1,
        refresh_interval_days: refreshDays,
        soft_notify_days: softDays,
        refresh_window_start_hour: (Number(s.refresh_window_start_hour) || 0) % 24,
        refresh_window_end_hour: (Number(s.refresh_window_end_hour) || 0) % 24,
        api_base_url: String(s.api_base_url || "http://127.0.0.1:80/v1").trim(),
        ai_model: String(s.ai_model || "cx/auto").trim(),
        api_key: String(s.api_key || "").trim(),
      });
      if (r.data?.ok) showToast("Đã lưu cài đặt");
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  const num = (k: string, def: number) => Number(s[k] ?? def);
  return (
    <div className="card"><div className="card-body space-y-3 max-w-xl">
      <h3 className="font-semibold">RAG Lifecycle</h3>
      <Field label="Đồng bộ R2 (phút)"><input type="number" className={INPUT} value={num("sync_interval_minutes", 360)} onChange={(e) => set("sync_interval_minutes", e.target.value)} /></Field>
      <Field label="Chế độ lưu trữ">
        <select className={INPUT} value={String(s.storage_mode || "local")} onChange={(e) => set("storage_mode", e.target.value)}>
          <option value="local">Local only (ChromaDB)</option>
          <option value="cloud">Cloud only (R2)</option>
          <option value="both">Cả hai (Local + Cloud)</option>
        </select>
      </Field>
      <Field label="Kiểm tra auto-update (giờ)"><input type="number" className={INPUT} value={num("auto_update_interval_hours", 1)} onChange={(e) => set("auto_update_interval_hours", e.target.value)} /></Field>
      <Field label="Số ngày giữa mỗi lần refresh KB"><input type="number" className={INPUT} value={num("refresh_interval_days", 90)} onChange={(e) => set("refresh_interval_days", e.target.value)} /></Field>
      <Field label="Gợi ý refresh khi KB cũ hơn (ngày)"><input type="number" className={INPUT} value={num("soft_notify_days", 60)} onChange={(e) => set("soft_notify_days", e.target.value)} /></Field>
      <div className="flex gap-3">
        <Field label="Khung giờ bắt đầu"><input type="number" min={0} max={23} className={INPUT} value={num("refresh_window_start_hour", 0)} onChange={(e) => set("refresh_window_start_hour", e.target.value)} /></Field>
        <Field label="Khung giờ kết thúc"><input type="number" min={0} max={23} className={INPUT} value={num("refresh_window_end_hour", 0)} onChange={(e) => set("refresh_window_end_hour", e.target.value)} /></Field>
      </div>
      <h3 className="font-semibold pt-2">AI tổng hợp RAG</h3>
      <Field label="API Base URL">
        <input className={INPUT} placeholder="http://127.0.0.1:80/v1" value={String(s.api_base_url || "")} onChange={(e) => set("api_base_url", e.target.value)} />
      </Field>
      <p className="text-xs text-[var(--muted-foreground)] -mt-1">
        Để <code>http://127.0.0.1:80/v1</code>. Hub chạy cùng container với gateway, và gateway nghe cổng <b>80</b> bên trong — 3030 chỉ là cổng publish ra host nên gọi từ trong container sẽ không tới.
      </p>
      <Field label="API Key"><input type="password" className={INPUT} value={String(s.api_key || "")} onChange={(e) => set("api_key", e.target.value)} /></Field>
      <p className="text-xs text-[var(--muted-foreground)] -mt-1">
        Chính khoá admin bạn dùng đăng nhập trang này. Để trống ⇒ gateway trả 401 và mọi lượt tổng hợp trượt, nhưng nạp RAG vẫn ra chunks (văn bản gốc chưa qua AI) nên rất dễ tưởng là bình thường.
      </p>
      <Field label="AI Model">
        <div className="flex gap-2">
          <select className={INPUT} value={String(s.ai_model || "cx/auto")} onChange={(e) => set("ai_model", e.target.value)}>
            {(models.length ? models : [String(s.ai_model || "cx/auto")]).map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <button className="btn" onClick={fetchModels} title="Tải model"><RefreshCw className="size-4" /></button>
        </div>
      </Field>
      <button className="btn btn-primary" onClick={save}>Lưu cài đặt</button>
    </div></div>
  );
}

// ── Tab: R2 Storage ────────────────────────────────────────────────────────
function R2Tab({ showToast }: TabProps) {
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [cols, setCols] = useState<{ name: string; chunks: number; age: string }[]>([]);
  const set = (k: string, v: string) => setCfg((prev) => ({ ...prev, [k]: v }));

  const load = useCallback(async () => {
    try {
      const r = await request.get(`${STUDIO}/r2`);
      if (r.data?.configured) setCfg(r.data.config || {});
    } catch { /* ignore */ }
    try { const l = await request.get(`${RAG}/list`); setCols(l.data?.collections || []); } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      const r = await request.post(`${STUDIO}/r2`, {
        endpoint: (cfg.endpoint || "").trim(), bucket: (cfg.bucket || "").trim(),
        access_key_id: (cfg.access_key_id || "").trim(), secret_access_key: (cfg.secret_access_key || "").trim(),
      });
      if (r.data?.ok) showToast("Đã lưu cấu hình R2");
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  const upload = async (n: string) => {
    try { const r = await request.post(`${RAG}/upload/${encodeURIComponent(n)}`); showToast(r.data?.ok ? "Upload OK" : "Upload fail", !!r.data?.ok); }
    catch { showToast("Lỗi", false); }
  };

  return (
    <div className="space-y-4">
      <div className="card"><div className="card-body space-y-3 max-w-xl">
        <h3 className="font-semibold">Cloudflare R2</h3>
        <Field label="Endpoint (S3 API)"><input className={INPUT} placeholder="https://{id}.r2.cloudflarestorage.com" value={cfg.endpoint || ""} onChange={(e) => set("endpoint", e.target.value)} /></Field>
        <Field label="Bucket"><input className={INPUT} placeholder="vn-mcp-hub-rag" value={cfg.bucket || ""} onChange={(e) => set("bucket", e.target.value)} /></Field>
        <Field label="Access Key ID"><input className={INPUT} value={cfg.access_key_id || ""} onChange={(e) => set("access_key_id", e.target.value)} /></Field>
        <Field label="Secret Access Key"><input type="password" className={INPUT} value={cfg.secret_access_key || ""} onChange={(e) => set("secret_access_key", e.target.value)} /></Field>
        <button className="btn btn-primary" onClick={save}>Lưu cấu hình R2</button>
      </div></div>
      <div className="card"><div className="card-body">
        <h3 className="font-semibold mb-3">RAG Collections</h3>
        <div className="space-y-1.5">
          {cols.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">Chưa có collection.</p>}
          {cols.map((c) => (
            <div key={c.name} className="flex items-center gap-3 rounded-lg border border-[var(--border)] px-3.5 py-2">
              <span className="text-sm font-medium">{c.name}</span>
              <span className="text-xs text-[var(--muted-foreground)]">{c.chunks} chunks · {c.age}</span>
              <button className="ml-auto text-xs px-2 py-1 rounded-md bg-[var(--secondary)]" onClick={() => upload(c.name)}>Upload R2</button>
            </div>
          ))}
        </div>
      </div></div>
    </div>
  );
}

// ── Tab: External MCP ──────────────────────────────────────────────────────
type ExtTool = { name: string; description: string };

// ID trong config.mcp_servers của gateway (phải tính lại được từ tên khi xoá)
const extSlug = (s: string) =>
  "ext_" + (s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "mcp");

function ExternalTab({ showToast }: TabProps) {
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [valid, setValid] = useState<{ name: string; version?: string; tools: ExtTool[] } | null>(null);
  const [extName, setExtName] = useState("");
  const [extDesc, setExtDesc] = useState("");
  const [list, setList] = useState<{ name: string; url: string; description?: string }[]>([]);

  const load = useCallback(async () => {
    try { const r = await request.get(`${STUDIO}/external-mcps`); setList(r.data?.mcps || []); } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const validate = async () => {
    if (!url.trim()) return;
    setValid(null);
    try {
      const r = await request.post(`${STUDIO}/validate-mcp`, { url: url.trim(), api_key: key.trim() });
      if (r.data?.ok) { setValid({ name: r.data.name, version: r.data.version, tools: r.data.tools || [] }); setExtName(r.data.name || ""); }
      else showToast("Lỗi: " + (r.data?.errors || []).join(". "), false);
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  const add = async () => {
    try {
      const r = await request.post(`${STUDIO}/external-mcp`, { name: extName.trim(), url: url.trim(), description: extDesc.trim(), api_key: key.trim() });
      if (r.data?.ok) {
        // Đăng ký vào gateway (config.mcp_servers) — registry của hub chỉ để hiển thị,
        // agent chỉ dùng tool từ danh sách MCP của gateway.
        try {
          await request.post("/api/mcp/install", { id: extSlug(extName), url_override: url.trim(), api_key: key.trim() });
        } catch { /* hub registry vẫn giữ entry; agent sẽ chưa thấy tool */ }
        showToast(`Đã thêm ${r.data.name}`); setValid(null); setUrl(""); setKey(""); setExtDesc(""); load();
      }
      else showToast((r.data?.errors || ["Lỗi"]).join(". "), false);
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  const del = async (n: string) => {
    if (!window.confirm(`Xoá MCP ${n}?`)) return;
    try {
      await request.delete(`${STUDIO}/external-mcp/${encodeURIComponent(n)}`);
      try { await request.post(`/api/mcp/uninstall/${extSlug(n)}`); } catch { /* ignore */ }
      showToast(`Đã xoá ${n}`); load();
    }
    catch { showToast("Lỗi", false); }
  };

  return (
    <div className="space-y-4">
      <div className="card"><div className="card-body space-y-3 max-w-xl">
        <h3 className="font-semibold">Kiểm tra MCP Server</h3>
        <Field label="URL MCP"><input className={INPUT} placeholder="https://example.com/mcp" value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Field label="API Key (nếu cần)"><input type="password" className={INPUT} value={key} onChange={(e) => setKey(e.target.value)} /></Field>
        <button className="btn btn-primary inline-flex items-center gap-1.5" onClick={validate}><Search className="size-4" />Kiểm tra</button>
        {valid && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 space-y-2">
            <p className="text-sm text-emerald-600 inline-flex items-center gap-1.5"><CheckCircle2 className="size-4" />{valid.name} {valid.version} · {valid.tools.length} tools</p>
            <input className={INPUT} placeholder="Tên MCP" value={extName} onChange={(e) => setExtName(e.target.value)} />
            <input className={INPUT} placeholder="Mô tả (để AI biết MCP này làm gì)" value={extDesc} onChange={(e) => setExtDesc(e.target.value)} />
            <button className="btn btn-primary inline-flex items-center gap-1.5" onClick={add}><Plug2 className="size-4" />Thêm MCP</button>
          </div>
        )}
      </div></div>
      <div className="card"><div className="card-body">
        <h3 className="font-semibold mb-3">External MCPs đã thêm</h3>
        <div className="space-y-1.5">
          {list.length === 0 && <p className="text-sm text-[var(--muted-foreground)]">Chưa có.</p>}
          {list.map((m) => (
            <div key={m.name} className="flex items-center gap-3 rounded-lg border border-[var(--border)] px-3.5 py-2 flex-wrap">
              <span className="text-sm font-medium">{m.name}</span>
              <code className="text-xs text-[var(--muted-foreground)]">{m.url}</code>
              {m.description && <span className="text-xs text-[var(--muted-foreground)]">{m.description}</span>}
              <button className="ml-auto text-xs px-2 py-1 rounded-md bg-red-500/10 text-red-500" onClick={() => del(m.name)}>Xoá</button>
            </div>
          ))}
        </div>
      </div></div>
    </div>
  );
}

// ── Tab: Nạp RAG (file/URL → AI analyze → curate into KB) ───────────────────

/** Một mục kiến thức tách từ markdown — đơn vị người dùng tick chọn để nạp. */
type KItem = { id: number; title: string; body: string; on: boolean };

let _kid = 0;
const nextKid = () => ++_kid;

/** Tách markdown thành các mục theo heading `#`/`##`.
 *
 * Chỉ tách ở cấp 1–2; `###` trở xuống để nguyên trong thân mục, nếu không một
 * phụ lục sẽ vỡ thành vài chục mảnh vụn không ai chọn nổi.
 */
function splitItems(md: string): KItem[] {
  const text = (md || "").replace(/\r\n?/g, "\n");
  if (!text.trim()) return [];
  const re = /^(#{1,2})[ \t]+(.+?)[ \t]*$/gm;
  const heads: { at: number; end: number; title: string }[] = [];
  for (let m = re.exec(text); m; m = re.exec(text)) {
    heads.push({ at: m.index, end: m.index + m[0].length, title: m[2].trim() });
  }
  const out: KItem[] = [];
  const pre = (heads.length ? text.slice(0, heads[0].at) : text).trim();
  if (pre) out.push({ id: nextKid(), title: "Mở đầu", body: pre, on: true });
  heads.forEach((h, i) => {
    const body = text.slice(h.end, i + 1 < heads.length ? heads[i + 1].at : undefined).trim();
    // Heading rỗng ruột (chỉ là tiêu đề cha) vẫn giữ — nó là ngữ cảnh cho mục sau.
    out.push({ id: nextKid(), title: h.title, body, on: true });
  });
  return out;
}

function joinItems(items: KItem[], onlySelected = true): string {
  return items
    .filter((i) => (onlySelected ? i.on : true))
    .map((i) => `## ${i.title}\n\n${i.body}`.trim())
    .join("\n\n");
}

type Coverage = {
  pages?: number; chars_extracted?: number; chars_processed?: number;
  batches_total?: number; used_ocr?: boolean; truncated?: boolean;
  batches_failed?: number;
};

/** Hình dạng kết quả analyze_source — khai rõ để không phải nắn `unknown`. */
type AnalyzeResult = Coverage & {
  ok?: boolean; markdown?: string; warning?: string; error?: string;
  pending?: boolean; job_id?: string; batches?: number; raw_fallback?: boolean;
};

type KbRow = { name: string; chunks: number; indexed?: boolean };

const vnNum = (n: number) => n.toLocaleString("vi-VN");

/** Tên collection Chroma: chỉ chữ thường, số, gạch dưới (studio.create_kb ép vậy).
 *
 * Bỏ dấu TRƯỚC khi lọc, nếu không "Phòng cháy" ra "phng_chy" vì mọi nguyên âm
 * có dấu đều bị xoá — người Việt gõ tên kho bằng tiếng Việt là chuyện thường.
 */
const kbSlug = (s: string) =>
  s.normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/đ/gi, "d")
    .toLowerCase().trim()
    .replace(/[^a-z0-9_\s]/g, "")
    .replace(/\s+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 30);

function IngestTab({ showToast }: TabProps) {
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [prog, setProg] = useState("");
  const [items, setItems] = useState<KItem[]>([]);
  const [view, setView] = useState<"list" | "raw">("list");
  const [raw, setRaw] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [cov, setCov] = useState<Coverage | null>(null);
  const [kbs, setKbs] = useState<KbRow[]>([]);
  const [targetKb, setTargetKb] = useState("");
  const [newKb, setNewKb] = useState(false);
  const [kbName, setKbName] = useState("");
  const [kbLabel, setKbLabel] = useState("");
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const loadKbs = useCallback(async () => {
    try {
      const r = await request.get(`${RAG}/list`);
      const list: KbRow[] = r.data?.collections || [];
      setKbs(list);
      setTargetKb((cur) => cur || (list[0]?.name ?? ""));
    } catch { /* ignore */ }
  }, []);

  // Nạp danh sách KB ngay khi mở tab, không chờ phân tích xong: người dùng cần
  // biết TRƯỚC là có kho nào để nạp hay phải tạo mới.
  useEffect(() => { loadKbs(); }, [loadKbs]);

  const apply = useCallback(async (d: AnalyzeResult) => {
    const md = String(d.markdown || "");
    setItems(splitItems(md));
    setRaw(md);
    setView("list");
    setCov({
      pages: Number(d.pages || 0), chars_extracted: Number(d.chars_extracted || 0),
      chars_processed: Number(d.chars_processed || 0), batches_total: Number(d.batches_total || 0),
      used_ocr: Boolean(d.used_ocr), truncated: Boolean(d.truncated),
      batches_failed: Number(d.batches_failed || 0),
    });
    await loadKbs();
    const w = d.warning ? String(d.warning) : "";
    showToast(w || "Phân tích hoàn tất", !w);
  }, [loadKbs, showToast]);

  /** Hỏi thăm job tới khi xong. Tài liệu dài chạy vài phút — vượt xa trần
   *  180s của proxy, nên không thể chờ trong một request. */
  const pollJob = useCallback(async (id: string) => {
    const deadline = Date.now() + 40 * 60 * 1000;
    while (alive.current && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2500));
      if (!alive.current) return;
      const r = await request.get(`${STUDIO}/analyze_job/${encodeURIComponent(id)}`);
      const d = r.data || {};
      if (!d.ok) throw new Error(String(d.error || "job không còn"));
      const tot = Number(d.batches_total || 0);
      const done = Number(d.batches_done || 0);
      setProg(tot > 1 ? `${d.stage || "đang xử lý"} — phần ${done}/${tot}` : String(d.stage || "đang xử lý"));
      if (d.status === "error") throw new Error(String(d.result?.error || "phân tích lỗi"));
      if (d.status === "done") {
        if (!d.result?.ok) throw new Error(String(d.result?.error || "phân tích lỗi"));
        await apply(d.result);
        return;
      }
    }
    throw new Error("job chạy quá lâu — xem log hub");
  }, [apply]);

  const analyze = async () => {
    if (!url.trim() && !file) { showToast("Điền URL hoặc chọn file", false); return; }
    setBusy(true); setItems([]); setCov(null); setProg("đang trích văn bản");
    try {
      const fd = new FormData();
      if (url.trim()) fd.append("url", url.trim());
      if (file) fd.append("file", file);
      const r = await request.post(`${STUDIO}/analyze_source`, fd);
      const d = r.data || {};
      if (!d.ok) { showToast("Lỗi: " + (d.error || "Không phân tích được"), false); }
      else if (d.pending && d.job_id) { await pollJob(String(d.job_id)); }
      else { await apply(d); }
    } catch (e) { showToast(String((e as Error).message), false); }
    if (alive.current) { setBusy(false); setProg(""); }
  };

  const sel = items.filter((i) => i.on);
  const selText = joinItems(items);
  const patch = (id: number, kw: Partial<KItem>) =>
    setItems((xs) => xs.map((i) => (i.id === id ? { ...i, ...kw } : i)));

  const toRaw = () => { setRaw(joinItems(items, false)); setView("raw"); };
  const toList = () => { setItems(splitItems(raw)); setView("list"); };

  const addItem = () => {
    const it: KItem = { id: nextKid(), title: "Mục mới", body: "", on: true };
    setItems((xs) => [...xs, it]);
    setOpenId(it.id);
  };

  const textToSave = () => (view === "raw" ? raw : selText);

  const clearAfterSave = () => {
    setItems([]); setCov(null); setUrl(""); setFile(null);
    setNewKb(false); setKbName(""); setKbLabel("");
  };

  const saveToKb = async () => {
    if (!targetKb) { showToast("Chọn KB", false); return; }
    const text = textToSave();
    if (!text.trim()) { showToast("Chưa chọn mục nào để nạp", false); return; }
    showToast("Đang nạp vào ChromaDB/R2...");
    try {
      const r = await request.post(`${RAG}/curate/${encodeURIComponent(targetKb)}`,
        { title: "Tài liệu AI tổng hợp", text, source: "studio_ingest" });
      if (r.data?.ok) {
        showToast(`Đã nạp ${r.data.chunks_added} chunks vào ${targetKb}`);
        clearAfterSave(); await loadKbs();
      } else showToast("Lỗi nạp: " + r.data?.error, false);
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  /** Tạo kho MỚI từ chính nội dung đang chọn — không kho nào phù hợp thì khỏi
   *  phải sang tab khác tạo rỗng rồi quay lại nạp. */
  const createKbAndSave = async () => {
    const name = kbSlug(kbName);
    if (!name) { showToast("Đặt tên kho (chữ thường, số, gạch dưới)", false); return; }
    if (kbs.some((k) => k.name === name)) {
      showToast(`Đã có kho '${name}' — chọn nó ở danh sách trên`, false); return;
    }
    const text = textToSave();
    if (!text.trim()) { showToast("Chưa chọn mục nào để nạp", false); return; }
    showToast(`Đang tạo kho '${name}' và nạp...`);
    try {
      const r = await request.post(`${STUDIO}/kb`,
        { name, label: kbLabel.trim() || kbName.trim() || name, content: text });
      if (r.data?.ok) {
        showToast(`Đã tạo '${name}' với ${r.data.chunks} chunks. Bật MCP của kho ở tab MCP Servers rồi restart.`);
        clearAfterSave(); await loadKbs();
      } else {
        showToast("Lỗi tạo kho: " + ((r.data?.errors || []).join(". ") || r.data?.error || "?"), false);
      }
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  return (
    <div className="space-y-4">
      <div className="card"><div className="card-body space-y-3 max-w-xl">
        <h3 className="font-semibold">Nạp dữ liệu bằng AI</h3>
        <p className="text-sm text-[var(--muted-foreground)]">Tải file (PDF/Word/PPT/Excel/HTML/CSV/EPUB/TXT/MD) hoặc điền URL để AI đọc, phân tích rồi tổng hợp vào kho RAG. Tài liệu dài được chia nhiều lượt — đọc hết, không cắt.</p>
        <Field label="Từ URL"><input className={INPUT} placeholder="https://..." value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Field label="Từ File"><input type="file" accept=".txt,.md,.pdf,.docx,.pptx,.xlsx,.html,.htm,.csv,.epub" className={INPUT} onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>
        <button className="btn btn-primary" disabled={busy} onClick={analyze}>{busy ? "🤖 " + (prog || "đang xử lý") + "..." : "AI Đọc & Phân Tích"}</button>
        {busy && <p className="text-xs text-[var(--muted-foreground)]">Tài liệu vài chục trang mất vài phút. Cứ để tab này mở.</p>}
      </div></div>

      {cov && (
        <div className="card"><div className="card-body">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            {!!cov.pages && <span>📄 {cov.pages} trang</span>}
            <span>✍️ trích {vnNum(cov.chars_extracted || 0)} ký tự</span>
            <span className={cov.truncated ? "text-amber-600 font-medium" : "text-emerald-600"}>
              {cov.truncated
                ? `⚠️ chỉ xử lý ${vnNum(cov.chars_processed || 0)} ký tự`
                : "✅ xử lý đủ, không cắt"}
            </span>
            {(cov.batches_total || 0) > 1 && <span>🔁 {cov.batches_total} lượt AI</span>}
            {cov.used_ocr && <span>🔍 qua OCR</span>}
            {!!cov.batches_failed && <span className="text-amber-600">{cov.batches_failed} phần giữ văn bản gốc</span>}
          </div>
        </div></div>
      )}

      {items.length > 0 && (
        <div className="card"><div className="card-body space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">Kiến thức trích được</h3>
            <span className="text-sm text-[var(--muted-foreground)]">
              {items.length} mục · chọn {sel.length} · {vnNum(selText.length)} ký tự sẽ nạp
            </span>
            <div className="ml-auto flex flex-wrap gap-1.5">
              <button className="text-xs px-2 py-1 rounded-md border border-[var(--border)]"
                onClick={() => setItems((xs) => xs.map((i) => ({ ...i, on: true })))}>Chọn tất cả</button>
              <button className="text-xs px-2 py-1 rounded-md border border-[var(--border)]"
                onClick={() => setItems((xs) => xs.map((i) => ({ ...i, on: false })))}>Bỏ chọn</button>
              <button className="text-xs px-2 py-1 rounded-md border border-[var(--border)]" onClick={addItem}>＋ Thêm mục</button>
              <button className="text-xs px-2 py-1 rounded-md border border-[var(--border)]"
                onClick={view === "list" ? toRaw : toList}>
                {view === "list" ? "Xem toàn văn" : "Về danh sách"}
              </button>
            </div>
          </div>

          {view === "raw" ? (
            <>
              <textarea className={`${INPUT} min-h-80 font-mono text-xs`} value={raw} onChange={(e) => setRaw(e.target.value)} />
              <p className="text-xs text-[var(--muted-foreground)]">Toàn văn gồm cả mục đang bỏ chọn. Bấm «Về danh sách» sẽ tách lại theo heading và chọn lại tất cả.</p>
            </>
          ) : (
            <div className="max-h-[32rem] overflow-y-auto space-y-1.5 pr-1">
              {items.map((it) => (
                <div key={it.id} className="rounded-lg border border-[var(--border)]">
                  <div className="flex items-center gap-2 px-3 py-2">
                    <input type="checkbox" className="size-4 shrink-0" checked={it.on}
                      onChange={(e) => patch(it.id, { on: e.target.checked })} />
                    <button className="text-sm text-left flex-1 truncate hover:underline"
                      title={it.title}
                      onClick={() => setOpenId(openId === it.id ? null : it.id)}>
                      {it.title || "(chưa có tiêu đề)"}
                    </button>
                    <span className="text-xs text-[var(--muted-foreground)] shrink-0">{vnNum(it.body.length)}</span>
                    <button className="text-xs px-1.5 py-1 rounded-md bg-red-500/10 text-red-500 shrink-0"
                      onClick={() => setItems((xs) => xs.filter((x) => x.id !== it.id))}
                      aria-label="Xoá mục"><Trash2 className="size-3.5" /></button>
                  </div>
                  {openId === it.id && (
                    <div className="border-t border-[var(--border)] p-3 space-y-2">
                      <input className={INPUT} value={it.title} placeholder="Tiêu đề mục"
                        onChange={(e) => patch(it.id, { title: e.target.value })} />
                      <textarea className={`${INPUT} min-h-40 font-mono text-xs`} value={it.body}
                        placeholder="Nội dung Markdown của mục này"
                        onChange={(e) => patch(it.id, { body: e.target.value })} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="border-t border-[var(--border)] pt-3 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Nạp vào đâu</span>
              <span className="text-xs text-[var(--muted-foreground)]">{kbs.length} kho hiện có</span>
              <button className="ml-auto text-xs px-2 py-1 rounded-md border border-[var(--border)]"
                onClick={() => setNewKb((v) => !v)}>
                {newKb ? "← Chọn kho có sẵn" : "＋ Tạo kho mới"}
              </button>
            </div>

            {newKb ? (
              <>
                <Field label="Tên kho (chữ thường, số, gạch dưới — dùng làm tên collection)">
                  <input className={INPUT} placeholder="vd: pccc_bxd" value={kbName}
                    onChange={(e) => setKbName(e.target.value)} />
                </Field>
                {kbName && kbSlug(kbName) !== kbName.trim() && (
                  <p className="text-xs text-amber-600">Sẽ lưu thành: <code>{kbSlug(kbName)}</code></p>
                )}
                <Field label="Tên hiển thị (để AI biết kho này về gì)">
                  <input className={INPUT} placeholder="vd: Giải pháp PCCC — Bộ Xây dựng"
                    value={kbLabel} onChange={(e) => setKbLabel(e.target.value)} />
                </Field>
                <button className="btn btn-primary" disabled={view === "list" && sel.length === 0}
                  onClick={createKbAndSave}>
                  {view === "raw" ? "Tạo kho & nạp toàn văn" : `Tạo kho & nạp ${sel.length} mục`}
                </button>
                <p className="text-xs text-[var(--muted-foreground)]">Kho mới thành một MCP riêng. Sau khi tạo, bật nó ở tab «MCP Servers» rồi restart container để bot dùng được.</p>
              </>
            ) : (
              <>
                <Field label="Chọn kho">
                  <select className={INPUT} value={targetKb} onChange={(e) => setTargetKb(e.target.value)}>
                    {kbs.length === 0 && <option value="">(Chưa có kho — bấm «Tạo kho mới»)</option>}
                    {kbs.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.name} ({vnNum(c.chunks)} chunks{c.indexed ? "" : " · chưa index"})
                      </option>
                    ))}
                  </select>
                </Field>
                <button className="btn btn-primary"
                  disabled={!targetKb || (view === "list" && sel.length === 0)} onClick={saveToKb}>
                  {view === "raw" ? "Nạp toàn văn vào kho này" : `Nạp ${sel.length} mục vào kho này`}
                </button>
              </>
            )}
          </div>
        </div></div>
      )}
    </div>
  );
}

// ── Tab: Thiết bị của tôi (device agent — đọc/sửa file máy tính/điện thoại) ─
type DeviceRow = {
  name: string; label?: string; connected?: boolean; platform?: string;
  hostname?: string; agent_version?: string; paths?: string[];
  can_write?: boolean; can_exec?: boolean; can_power?: boolean; ops?: number; connected_at?: number;
};
type OsId = "win" | "mac" | "linux" | "termux";
const OS_LIST: { id: OsId; label: string; shell: string }[] = [
  { id: "win", label: "🪟 Windows", shell: "PowerShell" },
  { id: "mac", label: "🍎 macOS", shell: "Terminal" },
  { id: "linux", label: "🐧 Linux / VPS", shell: "Terminal (SSH)" },
  { id: "termux", label: "🤖 Android", shell: "Termux" },
];
const RAW_AGENT =
  "https://raw.githubusercontent.com/TriTue2011/chatgpt2api/main/deploy/device_agent/c2a_agent.py";

type Step = { title: string; cmd?: string; note?: string };

/** Các bước cài ĐẦY ĐỦ cho MỘT máy mới — gồm cả việc cài Python. */
function installSteps(
  os: OsId, wsUrl: string, token: string, paths: string[],
  perm: { write: boolean; exec: boolean; power: boolean },
): Step[] {
  if (!token || !wsUrl) return [];
  // Cờ phải khớp ô tích: bật quyền ở dự án mà thiếu cờ khi chạy agent là vẫn bị
  // chặn tại máy — cố ý hai phía, nên lệnh sinh ra phải mang sẵn đúng cờ.
  const w = (perm.write ? " --allow-write" : "")
    + (perm.exec ? " --allow-exec" : "")
    + (perm.power ? " --allow-power" : "");
  const q = (x: string) => `"${x}"`;
  const pArgs = paths.map((x) => `--path ${q(x)}`).join(" ");
  const run = (py: string) =>
    `${py} c2a_agent.py --url ${wsUrl} --token ${q(token)} ${pArgs}${w}`;

  if (os === "win") {
    return [
      { title: "1. Cài Python (bỏ qua nếu `python --version` đã chạy được)",
        cmd: "winget install Python.Python.3.12",
        note: "Cài xong PHẢI đóng rồi mở lại PowerShell để `python` vào PATH." },
      { title: "2. Tải agent về (vào thư mục người dùng)",
        cmd: `cd $HOME; irm ${RAW_AGENT} -OutFile c2a_agent.py` },
      { title: "3. Chạy agent",
        cmd: run("python"),
        note: "Để cửa sổ PowerShell này MỞ. Đóng là agent dừng. Ctrl-C để dừng." },
      { title: "4. (Không bắt buộc) Tự chạy khi mở máy",
        cmd: [
          "# Tạo file c2a.bat rồi mở thư mục Startup",
          '$bat = Join-Path $env:USERPROFILE "c2a.bat"',
          '@("@echo off", "cd /d %USERPROFILE%", ' + JSON.stringify(run("python")) + ') | Set-Content -Encoding OEM $bat',
          "explorer shell:startup",
        ].join("\n"),
        note: "Explorer mở thư mục Startup — kéo file c2a.bat (ở thư mục người dùng) vào đó. Muốn không hiện cửa sổ đen thì sửa 'python' thành 'pythonw' trong file bat." },
    ];
  }
  if (os === "mac") {
    return [
      { title: "1. Kiểm tra Python (macOS có sẵn python3)",
        cmd: "python3 --version",
        note: "Báo lỗi thì cài: brew install python" },
      { title: "2. Tải agent về",
        cmd: `cd ~ && curl -fsSL ${RAW_AGENT} -o c2a_agent.py` },
      { title: "3. Chạy agent",
        cmd: run("python3"),
        note: "Để cửa sổ Terminal này MỞ. Ctrl-C để dừng." },
      { title: "4. (Không bắt buộc) Chạy nền, không cần giữ Terminal",
        cmd: `cd ~ && nohup ${run("python3")} > ~/c2a.log 2>&1 &`,
        note: "Xem log: tail -f ~/c2a.log · Dừng: pkill -f c2a_agent.py" },
    ];
  }
  if (os === "linux") {
    return [
      { title: "1. Cài Python nếu thiếu",
        cmd: "sudo apt update && sudo apt install -y python3 curl",
        note: "Máy RHEL/CentOS: sudo dnf install -y python3 curl" },
      { title: "2. Tải agent về",
        cmd: `cd ~ && curl -fsSL ${RAW_AGENT} -o c2a_agent.py` },
      { title: "3. Chạy thử (xem có kết nối được không)",
        cmd: run("python3"),
        note: "Thấy “đã kết nối” là xong. Ctrl-C rồi làm bước 4 để chạy vĩnh viễn." },
      { title: "4. Chạy vĩnh viễn bằng systemd (khuyến nghị cho VPS)",
        cmd: [
          "sudo tee /etc/systemd/system/c2a-agent.service >/dev/null <<'EOF'",
          "[Unit]",
          "Description=c2a device agent",
          "After=network-online.target",
          "",
          "[Service]",
          `ExecStart=/usr/bin/python3 ${"$"}HOME/c2a_agent.py --url ${wsUrl} ${pArgs}${w}`,
          `Environment=C2A_TOKEN=${token}`,
          "Restart=always",
          "RestartSec=10",
          "",
          "[Install]",
          "WantedBy=multi-user.target",
          "EOF",
          "sudo systemctl daemon-reload && sudo systemctl enable --now c2a-agent",
        ].join("\n"),
        note: "Token đặt qua biến môi trường C2A_TOKEN để không lộ trong `ps aux`. Xem log: journalctl -u c2a-agent -f" },
    ];
  }
  return [
    { title: "1. Cài Python trong Termux",
      cmd: "pkg update -y && pkg install -y python",
      note: "Cài Termux từ F-Droid (bản Play Store đã cũ, hay lỗi)." },
    { title: "2. Giữ máy không ngủ (BẮT BUỘC, nếu không sẽ đứt kết nối)",
      cmd: "termux-wake-lock" },
    { title: "3. Cho Termux xem được bộ nhớ máy",
      cmd: "termux-setup-storage",
      note: "Android sẽ hỏi quyền — bấm Cho phép. Sau đó ~/storage/shared là bộ nhớ trong." },
    { title: "4. Tải agent về",
      cmd: `cd ~ && curl -fsSL ${RAW_AGENT} -o c2a_agent.py` },
    { title: "5. Chạy nền + ghi log",
      cmd: `cd ~ && nohup ${run("python3")} > ~/c2a.log 2>&1 &`,
      note: "Xem log: tail -f ~/c2a.log · Dừng: pkill -f c2a_agent.py" },
  ];
}

function DevicesTab({ showToast }: TabProps) {
  const [rows, setRows] = useState<DeviceRow[]>([]);
  const [wsUrl, setWsUrl] = useState("");
  const [loading, setLoading] = useState(true);
  // Token chỉ tồn tại trong bộ nhớ trang, ngay sau khi tạo/xoay — không bao
  // giờ lưu lại, cũng không đọc ngược từ server (config không phải nơi tra
  // cứu bí mật).
  const [fresh, setFresh] = useState<{
    name: string; token: string; paths: string[];
    perm: { write: boolean; exec: boolean; power: boolean };
  } | null>(null);
  const [os, setOs] = useState<OsId>("win");
  const [mode, setMode] = useState<"domain" | "lan">("domain");
  const [lanUrl, setLanUrl] = useState("");
  const [busy, setBusy] = useState(false);

  // form
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [pathsText, setPathsText] = useState("");
  const [canWrite, setCanWrite] = useState(false);
  const [canExec, setCanExec] = useState(false);
  const [canPower, setCanPower] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await request.get("/api/devices");
      setRows(r.data?.devices || []);
      setWsUrl(r.data?.ws_url || "");
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  // URL cho chế độ LAN: suy từ chính địa chỉ đang mở trang admin. Khi cài
  // trong LAN thì hầu như luôn mở UI bằng IP nội bộ, nên đây là giá trị đúng
  // — vẫn cho sửa tay vì máy chủ có thể có nhiều card mạng.
  useEffect(() => {
    if (lanUrl) return;
    try {
      const o = window.location.origin;
      setLanUrl(o.replace(/^https:/, "wss:").replace(/^http:/, "ws:") + "/api/devices/agent");
    } catch { /* SSR */ }
  }, [lanUrl]);

  // Poll 5s: cần thấy thiết bị bật/tắt gần như tức thì (giống trang tunnel),
  // mà payload rất nhỏ nên rẻ.
  useEffect(() => {
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [load]);

  const parsedPaths = pathsText.split("\n").map((s) => s.trim()).filter(Boolean);

  const create = async () => {
    if (!name.trim()) { showToast("Chưa đặt tên thiết bị", false); return; }
    if (parsedPaths.length === 0) { showToast("Phải khai ít nhất một thư mục", false); return; }
    setBusy(true);
    try {
      const r = await request.post("/api/devices", {
        name: name.trim(), label: label.trim(), paths: parsedPaths,
        can_write: canWrite, can_exec: canExec, can_power: canPower,
      });
      if (r.data?.ok) {
        setFresh({ name: r.data.name, token: r.data.token, paths: r.data.paths || [],
          perm: { write: !!r.data.can_write, exec: !!r.data.can_exec, power: !!r.data.can_power } });
        setName(""); setLabel(""); setPathsText(""); setCanWrite(false);
        showToast(`Đã thêm ${r.data.name} — copy lệnh cài bên dưới`);
        load();
      } else showToast(r.data?.error || "Lỗi", false);
    } catch (e) { showToast(String((e as Error).message), false); }
    setBusy(false);
  };

  const rotate = async (d: DeviceRow) => {
    if (!window.confirm(
      `Lấy lệnh cài mới cho "${d.label || d.name}"?\n\n` +
      "Token cũ sẽ NGỪNG hoạt động ngay (agent đang chạy sẽ bị ngắt) — " +
      "phải chạy lại agent bằng lệnh mới.")) return;
    try {
      const r = await request.post(`/api/devices/${encodeURIComponent(d.name)}/rotate`);
      if (r.data?.ok) {
        setFresh({ name: r.data.name, token: r.data.token, paths: r.data.paths || [],
          perm: { write: !!r.data.can_write, exec: !!r.data.can_exec, power: !!r.data.can_power } });
        showToast("Token mới đã sinh — copy lệnh cài bên dưới");
        load();
      } else showToast(r.data?.error || "Lỗi", false);
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  /** Bật/tắt một quyền của thiết bị ĐÃ CÓ, giữ nguyên token.
   *  Không đi đường xoá-rồi-thêm-lại: xoá là mất token, phải chạy lại agent
   *  trên máy đó — quá đắt chỉ để tích một ô. */
  const togglePerm = async (d: DeviceRow, key: "can_write" | "can_exec" | "can_power") => {
    const next = !d[key];
    const nhan = { can_write: "ghi file", can_exec: "chạy lệnh", can_power: "tắt/khoá máy" }[key];
    const co = { can_write: "--allow-write", can_exec: "--allow-exec", can_power: "--allow-power" }[key];
    if (next && key !== "can_write"
        && !window.confirm(`Bật quyền «${nhan}» cho ${d.label || d.name}?\n\n`
          + (key === "can_exec"
            ? "Lệnh shell đọc/ghi/xoá được MỌI thứ tài khoản chạy agent với tới, kể cả ngoài thư mục đã khai."
            : "Cho phép tắt máy / khởi động lại — người đang dùng máy sẽ mất phiên làm việc.")
          + `\n\nAgent trên máy đó cũng phải chạy kèm ${co}, nếu không vẫn bị chặn.`)) return;
    try {
      const r = await request.patch(`/api/devices/${encodeURIComponent(d.name)}`, { [key]: next });
      if (r.data?.ok) {
        showToast(next
          ? `Đã bật «${nhan}» — nhớ chạy lại agent kèm ${co}`
          : `Đã tắt «${nhan}»`);
        await load();
      } else showToast("Lỗi: " + (r.data?.error || "?"), false);
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  const del = async (d: DeviceRow) => {
    if (!window.confirm(`Xoá thiết bị "${d.label || d.name}"? Token mất hiệu lực ngay.`)) return;
    try {
      const r = await request.delete(`/api/devices/${encodeURIComponent(d.name)}`);
      if (r.data?.ok) {
        if (fresh?.name === d.name) setFresh(null);
        showToast(`Đã xoá ${d.name}`); load();
      } else showToast(r.data?.error || "Lỗi", false);
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  const activeUrl = mode === "domain" ? wsUrl : lanUrl;
  const steps = fresh ? installSteps(os, activeUrl, fresh.token, fresh.paths, fresh.perm) : [];
  const copy = async (text: string, what = "lệnh") => {
    try {
      await navigator.clipboard.writeText(text);
      showToast(`Đã copy ${what}`);
    } catch { showToast("Không copy được — bôi đen rồi Ctrl+C", false); }
  };

  const online = rows.filter((r) => r.connected).length;

  return (
    <div className="space-y-4">
      {/* Trạng thái tổng quan */}
      <div className="card"><div className="card-body flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="font-semibold">Thiết bị của tôi</h3>
          <p className="text-sm text-[var(--muted-foreground)] mt-0.5">
            Cho bot đọc/sửa file trên máy tính, điện thoại Android, VPS — qua Internet,
            không cần mở cổng. Agent tự quay ra nên máy sau NAT/4G vẫn dùng được.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${online > 0 ? "bg-emerald-500" : "bg-[var(--muted-foreground)]"}`} />
          <span className="font-semibold">{online}/{rows.length} online</span>
          <button className="btn" onClick={load} title="Làm mới"><RefreshCw size={15} /></button>
        </div>
      </div></div>

      {!wsUrl && (
        <div className="card"><div className="card-body">
          <p className="text-sm text-amber-500">
            ⚠️ Chưa cấu hình <b>base_url</b> (hoặc telegram_webhook_url) trong Cài đặt —
            không dựng được lệnh cài vì không biết domain công khai của dự án.
          </p>
        </div></div>
      )}

      {/* Lệnh cài — hiện ngay sau khi tạo/xoay token */}
      {fresh && (
        <div className="card border-emerald-500/40"><div className="card-body space-y-4">
          <h3 className="font-semibold">
            <CheckCircle2 size={16} className="inline mr-1.5 text-emerald-500" />
            Hướng dẫn cài cho <code>{fresh.name}</code>
          </h3>

          {/* Chọn 1: cách kết nối */}
          <div>
            <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
              Bước A — Kết nối kiểu nào?
            </span>
            <div className="grid gap-2 sm:grid-cols-2">
              <button onClick={() => setMode("domain")}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  mode === "domain" ? "border-[var(--primary)] bg-[var(--primary)]/10" : "border-[var(--border)] hover:border-[var(--primary)]/50"
                }`}>
                <div className="font-semibold text-sm">🌐 Qua Internet (domain)</div>
                <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                  Máy ở đâu cũng dùng được — 4G, wifi nhà, quán cà phê. Đi qua domain công khai.
                </div>
              </button>
              <button onClick={() => setMode("lan")}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  mode === "lan" ? "border-[var(--primary)] bg-[var(--primary)]/10" : "border-[var(--border)] hover:border-[var(--primary)]/50"
                }`}>
                <div className="font-semibold text-sm">🏠 Trong mạng LAN</div>
                <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                  Chỉ khi thiết bị CÙNG mạng với máy chủ. Nhanh hơn, không qua Internet.
                </div>
              </button>
            </div>
            {mode === "domain" ? (
              wsUrl
                ? <p className="mt-2 text-xs text-[var(--muted-foreground)]">Địa chỉ: <code>{wsUrl}</code></p>
                : <p className="mt-2 text-xs text-amber-500">⚠️ Chưa cấu hình base_url — chọn LAN, hoặc điền base_url trong Cài đặt.</p>
            ) : (
              <div className="mt-2">
                <input className={`${INPUT} font-mono text-xs`} value={lanUrl}
                  onChange={(e) => setLanUrl(e.target.value)} />
                <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                  Tự lấy từ địa chỉ bạn đang mở trang này. Máy chủ có nhiều card mạng thì sửa lại IP cho đúng.
                </p>
              </div>
            )}
          </div>

          {/* Chọn 2: loại thiết bị */}
          <div>
            <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
              Bước B — Thiết bị loại gì?
            </span>
            <div className="grid gap-2 grid-cols-2 sm:grid-cols-4">
              {OS_LIST.map((o) => (
                <button key={o.id} onClick={() => setOs(o.id)}
                  className={`rounded-lg border p-2.5 text-left transition-colors ${
                    os === o.id ? "border-[var(--primary)] bg-[var(--primary)]/10" : "border-[var(--border)] hover:border-[var(--primary)]/50"
                  }`}>
                  <div className="text-sm font-semibold">{o.label}</div>
                  <div className="text-xs text-[var(--muted-foreground)]">{o.shell}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Các bước cụ thể */}
          {steps.length === 0 ? (
            <p className="text-sm text-amber-500">
              Chưa dựng được lệnh — thiếu địa chỉ kết nối ở Bước A.
            </p>
          ) : (
            <div>
              <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                Bước C — Làm lần lượt trên {OS_LIST.find((o) => o.id === os)?.label} (mở {OS_LIST.find((o) => o.id === os)?.shell})
              </span>
              <div className="space-y-2.5">
                {steps.map((s, i) => (
                  <div key={i} className="rounded-lg border border-[var(--border)] p-3">
                    <div className="text-sm font-semibold">{s.title}</div>
                    {s.cmd && (
                      <div className="mt-2 flex items-start gap-2">
                        <pre className="flex-1 overflow-x-auto rounded bg-[var(--background)] p-2.5 font-mono text-[11px] leading-relaxed">{s.cmd}</pre>
                        <button className="btn shrink-0" onClick={() => copy(s.cmd!)}>Copy</button>
                      </div>
                    )}
                    {s.note && (
                      <p className="mt-1.5 text-xs text-[var(--muted-foreground)]">💡 {s.note}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center gap-3 flex-wrap border-t border-[var(--border)] pt-3">
            <button className="btn" onClick={() => setFresh(null)}>Ẩn hướng dẫn</button>
            <span className="text-xs text-amber-500">
              Token chỉ hiện lúc này. Ẩn đi rồi cần lại thì bấm “Lệnh cài mới” ở danh sách (sẽ xoay token khác).
            </span>
          </div>
        </div></div>
      )}

      {/* Danh sách thiết bị */}
      <div className="card"><div className="card-body">
        <h3 className="font-semibold mb-3">Danh sách</h3>
        {loading && <p className="text-sm text-[var(--muted-foreground)]">Đang tải...</p>}
        {!loading && rows.length === 0 && (
          <p className="text-sm text-[var(--muted-foreground)]">
            Chưa có thiết bị nào. Thêm ở khung dưới.
          </p>
        )}
        <div className="space-y-2">
          {rows.map((d) => (
            <div key={d.name} className="rounded-lg border border-[var(--border)] p-3">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`inline-block h-2.5 w-2.5 rounded-full shrink-0 ${
                      d.connected ? "bg-emerald-500 animate-pulse" : "bg-[var(--muted-foreground)]"
                    }`} />
                    <span className="font-semibold">{d.label || d.name}</span>
                    <code className="text-xs text-[var(--muted-foreground)]">{d.name}</code>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    <span className="text-[var(--muted-foreground)]">quyền:</span>
                    {([
                      ["can_write", "thêm/xoá/sửa file"],
                      ["can_exec", "chạy lệnh"],
                      ["can_power", "tắt/khoá máy"],
                    ] as const).map(([k, nhan]) => (
                      <label key={k} className="inline-flex items-center gap-1.5 cursor-pointer">
                        <input type="checkbox" className="size-3.5" checked={!!d[k]}
                          onChange={() => togglePerm(d, k)} />
                        <span className={d[k] ? "font-medium text-amber-600" : "text-[var(--muted-foreground)]"}>{nhan}</span>
                      </label>
                    ))}
                  </div>
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                    {d.connected
                      ? <>🟢 đang kết nối · {d.platform || "?"} · {d.hostname || "?"} · agent v{d.agent_version || "?"} · {d.ops ?? 0} lệnh</>
                      : <>⚪ chưa kết nối — chạy agent trên máy đó (tự nối lại sau 5–120 giây)</>}
                  </p>
                  <p className="mt-0.5 text-xs text-[var(--muted-foreground)] break-all">
                    thư mục: {(d.paths || []).join("  ·  ") || "(chưa khai — không mở gì)"}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button className="btn" onClick={() => rotate(d)}>Lệnh cài mới</button>
                  <button className="btn text-red-500" onClick={() => del(d)} title="Xoá"><Trash2 size={15} /></button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div></div>

      {/* Thêm thiết bị */}
      <div className="card"><div className="card-body space-y-3">
        <h3 className="font-semibold">Thêm thiết bị</h3>
        <div className="flex gap-3 flex-wrap">
          <Field label="Tên (a-z 0-9 _ -)">
            <input className={INPUT} placeholder="laptop-win" value={name}
              onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))} />
          </Field>
          <Field label="Nhãn hiển thị">
            <input className={INPUT} placeholder="Laptop Windows" value={label}
              onChange={(e) => setLabel(e.target.value)} />
          </Field>
        </div>
        <Field label="Thư mục được phép — mỗi dòng một đường dẫn TUYỆT ĐỐI">
          <textarea className={`${INPUT} min-h-20 font-mono text-xs`} value={pathsText}
            onChange={(e) => setPathsText(e.target.value)}
            placeholder={"C:\\Users\\Viet\\Downloads\n/home/me/project"} />
        </Field>
        <div className="space-y-2.5">
          <div className="text-sm font-medium">Quyền cấp cho thiết bị</div>
          <p className="text-xs text-[var(--muted-foreground)] -mt-1">
            Đọc file + tra cứu máy (thông tin, CPU/RAM/ổ đĩa, tiến trình, service, màn hình) <b>luôn có sẵn</b>, không cần tích gì.
            Mỗi ô dưới đây còn phải kèm cờ tương ứng khi chạy agent — <b>hai phía đều phải bật</b>, để sơ suất một chỗ không mở quyền.
          </p>

          <label className="flex items-start gap-2.5 text-sm cursor-pointer">
            <input type="checkbox" className="mt-0.5" checked={canWrite}
              onChange={(e) => setCanWrite(e.target.checked)} />
            <span>
              Cho phép <b>thêm · xoá · sửa file</b>
              <span className="block text-xs text-[var(--muted-foreground)]">
                Chỉ trong các thư mục khai ở trên. Ghi đè luôn tạo bản sao <code>.c2a.bak</code>. Cờ: <code>--allow-write</code>
              </span>
            </span>
          </label>

          <label className="flex items-start gap-2.5 text-sm cursor-pointer">
            <input type="checkbox" className="mt-0.5" checked={canExec}
              onChange={(e) => setCanExec(e.target.checked)} />
            <span>
              Cho phép <b>chạy lệnh</b> — PowerShell · cmd · sh, và tắt ứng dụng
              <span className="block text-xs text-amber-600">
                Bật cái này là <b>allowlist thư mục hết ý nghĩa</b>: một lệnh shell đọc/ghi/xoá được mọi thứ tài khoản chạy agent với tới, kể cả ngoài thư mục đã khai. Đủ để cài phần mềm, xem cấu hình, quản lý service. Cờ: <code>--allow-exec</code>
              </span>
            </span>
          </label>

          <label className="flex items-start gap-2.5 text-sm cursor-pointer">
            <input type="checkbox" className="mt-0.5" checked={canPower}
              onChange={(e) => setCanPower(e.target.checked)} />
            <span>
              Cho phép <b>khoá màn hình · ngủ · đăng xuất · tắt máy · khởi động lại</b>
              <span className="block text-xs text-amber-600">
                Ảnh hưởng trực tiếp người đang dùng máy: tắt/khởi động lại là mất phiên làm việc và agent mất kết nối. Cờ: <code>--allow-power</code>
              </span>
            </span>
          </label>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <button className="btn btn-primary" disabled={busy} onClick={create}>
            {busy ? "Đang thêm..." : "Thêm & lấy lệnh cài"}
          </button>
          <span className="text-xs text-[var(--muted-foreground)]">
            Khai càng hẹp càng an toàn — đừng khai <code>C:\</code> hay <code>/</code>. Mở rộng sau lúc nào cũng được.
          </span>
        </div>
      </div></div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block flex-1">
      <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">{label}</span>
      {children}
    </label>
  );
}
