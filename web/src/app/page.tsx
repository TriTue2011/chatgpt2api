"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users, Cpu, Combine, ImageIcon,
  Search, Archive, Settings, RefreshCw, Pencil, Check, X,
  Video, ArrowRight, Activity, DollarSign,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getValidatedAuthSession } from "@/lib/auth-session";
import { request } from "@/lib/request";
import { StatsCard } from "@/components/stats-card";
import { EmptyState } from "@/components/empty-state";

import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

function fmt(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n || 0);
}
function fmtCost(n: number) { return `$${(n || 0).toFixed(2)}`; }
function fmtTokens(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n || 0);
}
function timeAgo(iso: string) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  return `${Math.floor(mins / 1440)}d ago`;
}

const PERIODS = [
  { value: "today", label: "Today" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "60d", label: "60D" },
];

// Gold-first palette for provider series (brand đen–xanh + vàng kim)
const NEON_COLORS = [
  "#D4AF37", "#38bdf8", "#34d399", "#f87171",
  "#a78bfa", "#fbbf24", "#60a5fa", "#e8eef7",
];

// Granularity modes for the Provider Usage chart
const USAGE_GRANULARITIES = [
  { value: "day", label: "Ngày" },
  { value: "week", label: "Tuần" },
  { value: "month", label: "Tháng" },
];

// Friendly labels for account provider groups (account_group() in the backend)
// Tooltip biểu đồ theo phong cách cv (nền tối, chấm màu + giá trị đậm), theme-aware.
function ChartTooltip({ active, payload, label, format }: {
  active?: boolean; payload?: any[]; label?: string; format?: (v: any) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "var(--popover)",
      border: "1px solid color-mix(in srgb, var(--primary) 25%, var(--border))",
      borderRadius: 12, padding: "10px 14px",
      boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
    }}>
      <p style={{ fontWeight: 700, fontSize: 12, color: "var(--foreground)", marginBottom: 6 }}>{label}</p>
      {payload.map((e: any) => (
        <div key={e.name} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: e.color }} />
          <span style={{ fontSize: 11, color: "var(--muted-foreground)" }}>{e.name}:</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--foreground)" }}>
            {format ? format(e.value) : e.value}
          </span>
        </div>
      ))}
    </div>
  );
}

const ACCOUNT_GROUP_LABELS: Record<string, string> = {
  free: "ChatGPT Free",
  codex: "Codex",
  openai: "OpenAI API",
  claude: "Claude",
  antigravity: "Antigravity",
  chatgpt_web: "ChatGPT Web",
  gemini_web: "Gemini Web",
  gemini_web_api: "Gemini Web API",
};

export default function DashboardPage() {
  const router = useRouter();
  const [session, setSession] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [usage, setUsage] = useState<any>(null);
  const [recentReqs, setRecentReqs] = useState<any[]>([]);
  const [mounted, setMounted] = useState(false);
  const [period, setPeriod] = useState("7d"); // mặc định 7D (user yêu cầu)
  const [chartMode, setChartMode] = useState<"tokens" | "cost">("tokens");
  const [usageMode, setUsageMode] = useState<"day" | "week" | "month">("day");
  const [usageSeries, setUsageSeries] = useState<any>(null);
  const [dailyUsage, setDailyUsage] = useState<any>(null);
  const [dailyMode, setDailyMode] = useState<"requests" | "tokens">("requests");
  // Inline edit of the current user's display name
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [savingName, setSavingName] = useState(false);

  const loadUsageSeries = useCallback(async (granularity: string) => {
    try {
      const res = await request.get(`/api/v1/usage/timeseries?granularity=${granularity}&period=${period}`);
      setUsageSeries((res.data as any) || null);
    } catch { /* usage series may be unavailable */ }
  }, [period]);

  const loadDailyUsage = useCallback(async () => {
    try {
      const res = await request.get("/api/v1/usage/daily?days=14");
      setDailyUsage((res.data as any) || null);
    } catch { /* optional */ }
  }, []);

  const loadHealth = useCallback(async () => {
    try {
      const [hRes, uRes, rRes] = await Promise.all([
        request.get("/api/v1/health"),
        request.get(`/api/v1/usage/stats?period=${period}`),
        request.get("/api/v1/usage/recent"),
      ]);
      setHealth((hRes.data as any) || null);
      setUsage((uRes.data as any) || null);
      setRecentReqs(((rRes.data as any)?.requests) || []);
    } catch { /* health may be unavailable */ }
  }, [period]);

  // Session init — runs once.
  useEffect(() => {
    let active = true;
    const init = async () => {
      const sess = await getValidatedAuthSession();
      if (!active) return;
      if (!sess) { router.replace("/login"); return; }
      setSession(sess);
      setMounted(true);
    };
    void init();
    return () => { active = false; };
  }, [router]);

  // Data load — refetches whenever the period changes (loadHealth depends on period).
  useEffect(() => {
    if (!session) return;
    void loadHealth();
  }, [session, loadHealth]);

  // Provider usage series — reacts to granularity + period.
  useEffect(() => {
    if (!session) return;
    void loadUsageSeries(usageMode);
  }, [session, usageMode, loadUsageSeries]);

  // Daily bar chart (fixed 14 days) — independent of period selector.
  useEffect(() => {
    if (!session) return;
    void loadDailyUsage();
  }, [session, loadDailyUsage]);

  const gemini = (health as any)?.gemini || {};
  const geminiInstances: any[] = gemini.instances || [];
  const customOnline = geminiInstances.filter((i: any) => i.status === "available" || i.status === "partial").length;
  const usageProviders: string[] = (usageSeries?.providers as string[]) || [];
  const usageHasData = usageProviders.length > 0
    && (usageSeries?.series || []).some((row: any) => usageProviders.some((p) => (row[p] || 0) > 0));
  const startEditName = () => {
    setNameDraft(session?.name || "");
    setEditingName(true);
  };
  const saveName = async () => {
    const next = nameDraft.trim();
    if (!next || next === (session?.name || "")) { setEditingName(false); return; }
    setSavingName(true);
    try {
      await request.post("/api/v1/profile/name", { name: next });
      const sess = await getValidatedAuthSession();
      if (sess) setSession(sess);
      setEditingName(false);
    } catch { /* keep editing open on failure */ }
    finally { setSavingName(false); }
  };

  if (!session) return null;

  if (!mounted) {
    return (
      <div className="bento-grid animate-pulse">
        <div className="bento-hero skeleton h-[240px]" />
        <div className="bento-tall skeleton h-[240px]" />
        <div className="bento-md skeleton h-[280px]" />
        <div className="bento-md skeleton h-[280px]" />
        <div className="bento-md skeleton h-[280px]" />
      </div>
    );
  }

  const SegmentedControl = ({ options, value, onChange }: { options: { value: string; label: string }[]; value: string; onChange: (v: string) => void }) => (
    <div className="inline-flex items-center gap-0.5 p-1 rounded-[10px] glass-subtle">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            "shrink-0 px-3 h-7 rounded-[8px] text-[12px] font-medium transition-all",
            value === opt.value
              ? "bg-[var(--neon-cyan)] text-[var(--primary-foreground)] shadow-[0_0_18px_color-mix(in_srgb,var(--neon-cyan)_40%,transparent)]"
              : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="flex flex-col gap-5">
      {/* ── Page header — period + refresh ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">Overview</p>
          <h2 className="display-text display-3 text-[var(--foreground)] mt-0.5 flex items-center gap-2 flex-wrap">
            <span>Xin chào,</span>
            {editingName ? (
              <span className="inline-flex items-center gap-1.5">
                <input
                  autoFocus
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void saveName();
                    if (e.key === "Escape") setEditingName(false);
                  }}
                  maxLength={40}
                  disabled={savingName}
                  className="px-2 py-0.5 rounded-[8px] bg-[var(--surface-2)] border border-[var(--border)] text-[var(--foreground)] outline-none focus:border-[var(--neon-cyan)] min-w-[140px]"
                  style={{ font: "inherit" }}
                />
                <button
                  onClick={() => void saveName()}
                  disabled={savingName}
                  className="size-7 inline-flex items-center justify-center rounded-[8px] glass-subtle hover:text-[var(--neon-lime)] transition-colors disabled:opacity-50"
                  title="Lưu"
                >
                  <Check className="size-4" />
                </button>
                <button
                  onClick={() => setEditingName(false)}
                  disabled={savingName}
                  className="size-7 inline-flex items-center justify-center rounded-[8px] glass-subtle hover:text-[var(--destructive)] transition-colors disabled:opacity-50"
                  title="Hủy"
                >
                  <X className="size-4" />
                </button>
              </span>
            ) : (
              <span className="inline-flex items-center gap-2 group">
                <span className="gradient-text">{session?.name || "Admin"}</span>
                <button
                  onClick={startEditName}
                  className="size-7 inline-flex items-center justify-center rounded-[8px] glass-subtle text-[var(--muted-foreground)] opacity-0 group-hover:opacity-100 hover:text-[var(--neon-cyan)] transition-all"
                  title="Đổi tên"
                >
                  <Pencil className="size-3.5" />
                </button>
              </span>
            )}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <SegmentedControl options={PERIODS} value={period} onChange={setPeriod} />
          <button
            onClick={() => { void loadHealth(); void loadUsageSeries(usageMode); void loadDailyUsage(); }}
            className="size-9 inline-flex items-center justify-center rounded-[10px] glass-subtle hover:text-[var(--neon-cyan)] transition-colors"
            title="Refresh"
          >
            <RefreshCw className="size-4 text-[var(--muted-foreground)]" />
          </button>
        </div>
      </div>

      {/* ── KPI StatsCards — requests / tokens / cost / accounts ── */}
      {(() => {
        const acc = health?.accounts || {};
        const circuitsOpen = health?.provider_circuits?.open_count ?? 0;
        return (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatsCard title="Requests" value={fmt(usage?.totalRequests ?? 0)} icon={Activity} tone="gold" sub={`Kỳ: ${period}`} />
            <StatsCard
              title="Tokens"
              value={fmt((usage?.totalPromptTokens ?? 0) + (usage?.totalCompletionTokens ?? 0))}
              icon={Cpu}
              tone="blue"
              sub={`In ${fmt(usage?.totalPromptTokens ?? 0)} · Out ${fmt(usage?.totalCompletionTokens ?? 0)}`}
            />
            <StatsCard title="Chi phí ước tính" value={fmtCost(usage?.totalCost ?? 0)} icon={DollarSign} tone="amber" />
            <StatsCard
              title="Accounts"
              value={`${acc.active ?? 0}/${acc.total ?? 0}`}
              icon={Users}
              tone={(acc.active ?? 0) > 0 ? "emerald" : "red"}
              sub={circuitsOpen > 0 ? `${circuitsOpen} provider ngắt mạch` : "Pool sẵn sàng"}
            />
          </div>
        );
      })()}

      {/* ── Bento grid ── */}
      <div className="bento-grid">
        {/* KPI bar — Total Requests + token/cost summary (span full width, slim) */}
        <div className="bento-cell animate-in flex items-center gap-5 flex-wrap" style={{ gridColumn: "span 12" }}>
          <div className="flex items-center gap-3.5 pr-5 sm:border-r border-[var(--border)]/50">
            <div className="size-12 rounded-[14px] flex items-center justify-center shrink-0"
              style={{
                background: "linear-gradient(135deg, color-mix(in srgb, var(--neon-cyan) 20%, transparent), color-mix(in srgb, var(--neon-magenta) 20%, transparent))",
                boxShadow: "0 0 24px color-mix(in srgb, var(--neon-cyan) 35%, transparent)",
              }}
            >
              <Activity className="size-6 text-[var(--neon-cyan)]" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">Total Requests</p>
              <p className="display-text display-3 gradient-text animate-gradient leading-none mt-1">{fmt(usage?.totalRequests ?? 0)}</p>
            </div>
          </div>
          <div className="flex items-center gap-7 sm:gap-10 flex-wrap flex-1">
            {[
              { label: "Input", value: fmt(usage?.totalPromptTokens ?? 0), cls: "neon-cyan-text" },
              { label: "Output", value: fmt(usage?.totalCompletionTokens ?? 0), cls: "neon-lime-text" },
              { label: "Cost", value: `~${fmtCost(usage?.totalCost ?? 0)}`, cls: "neon-amber-text" },
              { label: "Avg / h", value: `+${Math.round((usage?.totalRequests ?? 0) / 24)}`, cls: "neon-lime-text" },
            ].map((s) => (
              <div key={s.label}>
                <p className="text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">{s.label}</p>
                <p className={cn("text-[22px] font-bold leading-none mt-1.5", s.cls)}>{s.value}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Provider Usage — per-provider tokens over time */}
        <div className="bento-cell animate-in flex flex-col" style={{ gridColumn: "span 8", gridRow: "span 2", padding: 0 }}>
          <div className="px-5 py-3 flex items-center justify-between border-b border-[var(--border)]/40 flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <Activity className="size-3.5 text-[var(--neon-cyan)]" />
              <p className="text-[11px] uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">Provider Usage</p>
            </div>
            <SegmentedControl
              options={USAGE_GRANULARITIES}
              value={usageMode}
              onChange={(v) => setUsageMode(v as "day" | "week" | "month")}
            />
          </div>
          <div className="flex-1 p-4">
            {!usageHasData ? (
              <div className="h-[380px] flex items-center justify-center">
                <EmptyState
                  icon={Activity}
                  title="Chưa có dữ liệu sử dụng"
                  description="Gửi thử POST /v1/chat/completions (hoặc chat 1 câu ở tab Chat) để thấy biểu đồ token theo provider."
                />
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={380}>
                <AreaChart data={usageSeries?.series || []} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    {usageProviders.map((p, i) => {
                      const c = NEON_COLORS[i % NEON_COLORS.length];
                      return (
                        <linearGradient key={p} id={`gradUsage${i}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={c} stopOpacity={0.25} />
                          <stop offset="95%" stopColor={c} stopOpacity={0.02} />
                        </linearGradient>
                      );
                    })}
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="color-mix(in srgb, var(--foreground) 6%, transparent)" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: "currentColor", fillOpacity: 0.5 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: "currentColor", fillOpacity: 0.5 }} tickLine={false} axisLine={false} tickFormatter={fmtTokens} width={50} />
                  <Tooltip content={<ChartTooltip format={fmtTokens} />} />
                  <Legend wrapperStyle={{ fontSize: "11px" }} iconType="circle" iconSize={8} />
                  {usageProviders.map((p, i) => {
                    const c = NEON_COLORS[i % NEON_COLORS.length];
                    return (
                      <Area
                        key={p}
                        type="monotone"
                        dataKey={p}
                        stackId="usage"
                        stroke={c}
                        strokeWidth={2}
                        fill={`url(#gradUsage${i})`}
                        dot={false}
                        activeDot={{ r: 4, fill: c, strokeWidth: 0 }}
                      />
                    );
                  })}
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Recent Requests */}
        <div className="bento-cell animate-in flex flex-col" style={{ gridColumn: "span 4", gridRow: "span 2", padding: 0, maxHeight: 472 }}>
          <div className="px-5 py-3 border-b border-[var(--border)]/40 flex items-center justify-between shrink-0">
            <p className="text-[11px] uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">Recent Requests</p>
            <span className="text-[10px] text-[var(--muted-foreground)]">{recentReqs.length}</span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {recentReqs.length === 0 ? (
              <div className="h-32 flex items-center justify-center text-[var(--muted-foreground)] text-sm">No requests yet.</div>
            ) : (
              <table className="w-full text-[12px]">
                <tbody>
                  {recentReqs.map((r: any, i: number) => (
                    <tr key={i} className="hover:bg-[var(--secondary)]/40 transition-colors border-b border-[var(--border)]/30 last:border-0">
                      <td className="py-2 pl-3 w-3">
                        <span
                          className={cn("block size-1.5 rounded-full dot-glow", r.status === "success" ? "bg-[var(--neon-lime)] text-[var(--neon-lime)]" : "bg-[var(--destructive)] text-[var(--destructive)]")}
                        />
                      </td>
                      <td className="py-2 pl-2 font-mono text-[11px] truncate max-w-[120px] text-[var(--foreground)]" title={r.model}>{r.model}</td>
                      <td className="py-2 pr-3 text-right whitespace-nowrap">
                        <span className="neon-cyan-text text-[11px]">{fmt(r.promptTokens)}↑</span>{" "}
                        <span className="neon-lime-text text-[11px]">{fmt(r.completionTokens)}↓</span>
                        <div className="text-[10px] text-[var(--muted-foreground)] mt-0.5">{timeAgo(r.started_at)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* 14-day daily bar chart — requests / tokens */}
        <div className="bento-cell animate-in" style={{ gridColumn: "span 6", padding: "1.25rem" }}>
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <div>
              <p className="text-[11px] uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">14 ngày gần nhất</p>
              <p className="text-[18px] font-bold mt-0.5 display-text">
                {dailyMode === "requests"
                  ? `${fmt(dailyUsage?.totals?.requests ?? 0)} requests`
                  : `${fmtTokens(dailyUsage?.totals?.tokens ?? 0)} tokens`}
              </p>
              <p className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
                Cost ~{fmtCost(dailyUsage?.totals?.cost ?? 0)}
              </p>
            </div>
            <SegmentedControl
              options={[{ value: "requests", label: "Requests" }, { value: "tokens", label: "Tokens" }]}
              value={dailyMode}
              onChange={(v) => setDailyMode(v as "requests" | "tokens")}
            />
          </div>
          {!(dailyUsage?.series || []).some((r: any) => (r.requests || 0) > 0 || (r.tokens || 0) > 0) ? (
            <div className="h-[240px] flex items-center justify-center">
              <EmptyState
                compact
                icon={Activity}
                title="Chưa có dữ liệu 14 ngày"
                description="Gửi vài request API để thấy cột theo ngày."
              />
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={dailyUsage?.series || []} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="color-mix(in srgb, var(--foreground) 6%, transparent)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: "currentColor", fillOpacity: 0.5 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: "currentColor", fillOpacity: 0.5 }} tickLine={false} axisLine={false} tickFormatter={dailyMode === "tokens" ? fmtTokens : fmt} width={50} />
                <Tooltip content={<ChartTooltip format={dailyMode === "tokens" ? fmtTokens : fmt} />} />
                <Bar
                  dataKey={dailyMode === "tokens" ? "tokens" : "requests"}
                  name={dailyMode === "tokens" ? "Tokens" : "Requests"}
                  fill="#D4AF37"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={28}
                />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Usage Trend — total tokens / cost over the selected period (real data) */}
        <div className="bento-cell animate-in" style={{ gridColumn: "span 6", padding: "1.25rem" }}>
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <div>
              <p className="text-[11px] uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">Usage Trend</p>
              <p className="text-[18px] font-bold mt-0.5 display-text">
                {chartMode === "tokens" ? fmtTokens((usage?.totalPromptTokens ?? 0) + (usage?.totalCompletionTokens ?? 0)) + " tokens" : fmtCost(usage?.totalCost ?? 0) + " spent"}
              </p>
            </div>
            <SegmentedControl
              options={[{ value: "tokens", label: "Tokens" }, { value: "cost", label: "Cost" }]}
              value={chartMode}
              onChange={(v) => setChartMode(v as "tokens" | "cost")}
            />
          </div>
          {!usageHasData ? (
            <div className="h-[240px] flex items-center justify-center">
              <EmptyState
                compact
                icon={Activity}
                title="Chưa có dữ liệu cho khoảng này"
                description="Đổi kỳ ở góc phải trên, hoặc gửi 1 request /v1/chat/completions."
              />
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={usageSeries?.series || []} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="gradTokens" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--neon-cyan)" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="var(--neon-cyan)" stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="gradCost" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--neon-amber)" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="var(--neon-amber)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="color-mix(in srgb, var(--foreground) 6%, transparent)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: "currentColor", fillOpacity: 0.5 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: "currentColor", fillOpacity: 0.5 }} tickLine={false} axisLine={false} tickFormatter={chartMode === "tokens" ? fmtTokens : fmtCost} width={50} />
                <Tooltip content={<ChartTooltip format={chartMode === "tokens" ? fmtTokens : fmtCost} />} />
                {chartMode === "tokens" ? (
                  <Area type="monotone" dataKey="__tokens" stroke="var(--neon-cyan)" strokeWidth={2.5} fill="url(#gradTokens)" dot={false} activeDot={{ r: 5, fill: "var(--neon-cyan)", strokeWidth: 0 }} />
                ) : (
                  <Area type="monotone" dataKey="__cost" stroke="var(--neon-amber)" strokeWidth={2.5} fill="url(#gradCost)" dot={false} activeDot={{ r: 5, fill: "var(--neon-amber)", strokeWidth: 0 }} />
                )}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* System Status (half) */}
        <div className="bento-cell animate-in" style={{ gridColumn: "span 6", padding: 0 }}>
          <div className="px-5 py-3 border-b border-[var(--border)]/40">
            <p className="text-[11px] uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">System Status</p>
          </div>
          <div className="divide-y divide-[var(--border)]/40">
            {[
              { label: "Backoff", value: `${health?.backoff?.total_locked_models ?? 0} locked`, status: (health?.backoff?.total_locked_models ?? 0) > 0 ? "warning" : "ok" },
              { label: "Quota Watcher", value: health?.quota_watcher?.running ? "Running" : "Off", status: health?.quota_watcher?.running ? "ok" : "off" },
              { label: "Cooldown", value: `${health?.model_cooldown?.cooling ?? 0} / ${health?.model_cooldown?.total_tracked ?? 0}`, status: (health?.model_cooldown?.cooling ?? 0) > 0 ? "warning" : "ok" },
              { label: "Gemini API", value: gemini.gemini_api ?? "—", status: gemini.gemini_api === "available" ? "ok" : gemini.gemini_api === "partial" ? "warning" : "error" },
              { label: "API Endpoints", value: `${customOnline}/${geminiInstances.length}`, status: customOnline > 0 ? "ok" : "error" },
            ].map((row) => {
              const color = row.status === "ok" ? "var(--neon-lime)" : row.status === "warning" ? "var(--neon-amber)" : row.status === "error" ? "var(--destructive)" : "var(--muted-foreground)";
              return (
                <div key={row.label} className="px-5 py-2.5 flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="size-1.5 rounded-full dot-glow shrink-0" style={{ backgroundColor: color, color }} />
                    <span className="text-[12px] font-medium text-[var(--foreground)]">{row.label}</span>
                  </div>
                  <span className="text-[11px] text-[var(--muted-foreground)] font-mono">{row.value}</span>
                </div>
              );
            })}
            {/* Accounts — total + real per-provider breakdown */}
            {(() => {
              const acc = health?.accounts || {};
              const byGroup = (acc.by_group || {}) as Record<string, { total: number; active: number }>;
              const groupKeys = Object.keys(byGroup).sort((a, b) => byGroup[b].total - byGroup[a].total);
              return (
                <div className="px-5 py-2.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <span className="size-1.5 rounded-full dot-glow shrink-0" style={{ backgroundColor: "var(--neon-lime)", color: "var(--neon-lime)" }} />
                      <span className="text-[12px] font-medium text-[var(--foreground)]">Accounts</span>
                    </div>
                    <span className="text-[11px] text-[var(--muted-foreground)] font-mono">{acc.active ?? 0} active / {acc.total ?? 0} total</span>
                  </div>
                  {groupKeys.length > 0 && (
                    <div className="mt-2 ml-4 flex flex-col gap-1.5">
                      {groupKeys.map((g) => {
                        const b = byGroup[g];
                        const c = b.active === 0 ? "var(--muted-foreground)" : (b.active === b.total ? "var(--neon-lime)" : "var(--neon-amber)");
                        return (
                          <div key={g} className="flex items-center justify-between">
                            <span className="text-[11px] text-[var(--muted-foreground)]">{ACCOUNT_GROUP_LABELS[g] || g}</span>
                            <span className="text-[11px] font-mono" style={{ color: c }}>{b.active}/{b.total}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        </div>

        {/* Quick Access — 8 tiles, each bento-sm */}
        {[
          { label: "Tài khoản", desc: "Quản lý token & pool", href: "/accounts", icon: Users, color: "var(--neon-cyan)" },
          { label: "Providers", desc: "OpenCode, Gemini, Codex…", href: "/providers", icon: Cpu, color: "var(--neon-magenta)" },
          { label: "Quản lý Model", desc: "Bật/tắt model", href: "/models", icon: Settings, color: "var(--neon-lime)" },
          { label: "Mô hình kết hợp", desc: "Combo fallback", href: "/combos", icon: Combine, color: "var(--neon-violet)" },
          { label: "Tạo ảnh", desc: "DALL-E, SD, FLUX…", href: "/image", icon: ImageIcon, color: "var(--neon-magenta)" },
          { label: "Tạo video", desc: "Veo 3.1", href: "/video", icon: Video, color: "var(--neon-violet)" },
          { label: "Tìm kiếm", desc: "Gemini, Serper…", href: "/search", icon: Search, color: "var(--neon-amber)" },
          { label: "Sao lưu", desc: "Backup & restore", href: "/backup", icon: Archive, color: "var(--neon-cyan)" },
        ].map((link) => {
          const Icon = link.icon;
          return (
            <a
              key={link.href}
              href={link.href}
              className="bento-cell bento-sm group flex items-center gap-3 animate-in"
              style={{ padding: "0.9rem 1rem" }}
            >
              <div
                className="size-9 rounded-[10px] shrink-0 flex items-center justify-center transition-all group-hover:scale-105"
                style={{
                  background: `color-mix(in srgb, ${link.color} 16%, transparent)`,
                }}
              >
                <Icon className="size-4" style={{ color: link.color }} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-semibold text-[var(--foreground)] truncate transition-colors group-hover:text-[var(--neon-cyan)]">
                  {link.label}
                </p>
                <p className="text-[10px] text-[var(--muted-foreground)] truncate">{link.desc}</p>
              </div>
              <ArrowRight className="size-3.5 text-[var(--muted-foreground)] shrink-0 transition-all group-hover:translate-x-1 group-hover:text-[var(--neon-cyan)]" />
            </a>
          );
        })}
      </div>
    </div>
  );
}
