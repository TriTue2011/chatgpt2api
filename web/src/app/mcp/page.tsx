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

type TabId = "servers" | "kb" | "settings" | "r2" | "external" | "ingest";
const TABS: { id: TabId; label: string }[] = [
  { id: "servers", label: "MCP Servers" },
  { id: "kb", label: "Knowledge Base" },
  { id: "settings", label: "Cài đặt RAG" },
  { id: "r2", label: "R2 Storage" },
  { id: "external", label: "External MCP" },
  { id: "ingest", label: "Nạp RAG" },
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
      <Field label="API Base URL"><input className={INPUT} placeholder="http://127.0.0.1:80/v1" value={String(s.api_base_url || "")} onChange={(e) => set("api_base_url", e.target.value)} /></Field>
      <Field label="API Key"><input type="password" className={INPUT} value={String(s.api_key || "")} onChange={(e) => set("api_key", e.target.value)} /></Field>
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
function IngestTab({ showToast }: TabProps) {
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [markdown, setMarkdown] = useState("");
  const [showResult, setShowResult] = useState(false);
  const [kbs, setKbs] = useState<{ name: string; chunks: number }[]>([]);
  const [targetKb, setTargetKb] = useState("");

  const loadKbs = useCallback(async () => {
    try {
      const r = await request.get(`${RAG}/list`);
      const list = r.data?.collections || [];
      setKbs(list);
      if (list[0]) setTargetKb(list[0].name);
    } catch { /* ignore */ }
  }, []);

  const analyze = async () => {
    if (!url.trim() && !file) { showToast("Điền URL hoặc chọn file", false); return; }
    setBusy(true); setShowResult(false);
    try {
      const fd = new FormData();
      if (url.trim()) fd.append("url", url.trim());
      if (file) fd.append("file", file);
      const r = await request.post(`${STUDIO}/analyze_source`, fd);
      if (r.data?.ok) {
        setMarkdown(r.data.markdown || ""); setShowResult(true); await loadKbs();
        showToast(r.data.raw_fallback ? (r.data.warning || "AI fallback văn bản gốc") : "Phân tích hoàn tất");
      } else showToast("Lỗi: " + (r.data?.error || "Không phân tích được"), false);
    } catch (e) { showToast(String((e as Error).message), false); }
    setBusy(false);
  };

  const saveToKb = async () => {
    if (!targetKb) { showToast("Chọn KB", false); return; }
    showToast("Đang nạp vào ChromaDB/R2...");
    try {
      const r = await request.post(`${RAG}/curate/${encodeURIComponent(targetKb)}`, { title: "Tài liệu AI tổng hợp", text: markdown, source: "studio_ingest" });
      if (r.data?.ok) { showToast(`Đã nạp ${r.data.chunks_added} chunks vào ${targetKb}`); setShowResult(false); setUrl(""); setFile(null); }
      else showToast("Lỗi nạp: " + r.data?.error, false);
    } catch (e) { showToast(String((e as Error).message), false); }
  };

  return (
    <div className="space-y-4">
      <div className="card"><div className="card-body space-y-3 max-w-xl">
        <h3 className="font-semibold">Nạp dữ liệu bằng AI</h3>
        <p className="text-sm text-[var(--muted-foreground)]">Tải file (PDF/Word/PPT/Excel/HTML/CSV/EPUB/TXT/MD) hoặc điền URL để AI đọc, phân tích rồi tổng hợp vào kho RAG.</p>
        <Field label="Từ URL"><input className={INPUT} placeholder="https://..." value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Field label="Từ File"><input type="file" accept=".txt,.md,.pdf,.docx,.pptx,.xlsx,.html,.htm,.csv,.epub" className={INPUT} onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>
        <button className="btn btn-primary" disabled={busy} onClick={analyze}>{busy ? "🤖 AI đang đọc (1-2 phút)..." : "AI Đọc & Phân Tích"}</button>
      </div></div>
      {showResult && (
        <div className="card"><div className="card-body space-y-3">
          <h3 className="font-semibold">Kết quả AI tổng hợp</h3>
          <textarea className={`${INPUT} min-h-60 font-mono`} value={markdown} onChange={(e) => setMarkdown(e.target.value)} />
          <Field label="Chọn KB để nạp vào">
            <select className={INPUT} value={targetKb} onChange={(e) => setTargetKb(e.target.value)}>
              {kbs.length === 0 && <option value="">(Chưa có KB)</option>}
              {kbs.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.chunks} chunks)</option>)}
            </select>
          </Field>
          <button className="btn btn-primary" onClick={saveToKb}>Nạp vào KB này</button>
        </div></div>
      )}
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
