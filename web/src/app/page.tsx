"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users, Cpu, Sparkles, Combine, ImageIcon,
  Search, Archive, Settings, RefreshCw,
  ShieldCheck, Activity, Server, Video,
  ArrowRight, Circle,
} from "lucide-react";

import { getValidatedAuthSession } from "@/lib/auth-session";
import { getDefaultRouteForRole } from "@/store/auth";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

// ── Donut Chart (pure SVG) ──
function DonutChart({ segments, size = 120, thickness = 22 }: {
  segments: { label: string; value: number; color: string }[];
  size?: number;
  thickness?: number;
}) {
  const total = segments.reduce((s, seg) => s + seg.value, 0) || 1;
  const radius = (size - thickness) / 2;
  const center = size / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="flex flex-col items-center gap-3">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {segments.map((seg, i) => {
          const ratio = seg.value / total;
          const dashLength = ratio * circumference;
          const strokeDasharray = `${dashLength} ${circumference - dashLength}`;
          const strokeDashoffset = -offset;
          offset += dashLength;
          return (
            <circle
              key={i}
              cx={center}
              cy={center}
              r={radius}
              fill="none"
              stroke={seg.color}
              strokeWidth={thickness}
              strokeDasharray={strokeDasharray}
              strokeDashoffset={strokeDashoffset}
              transform={`rotate(-90 ${center} ${center})`}
              className="transition-all duration-700"
            />
          );
        })}
        <circle cx={center} cy={center} r={radius - thickness / 2 - 2} fill="white" />
        <text x={center} y={center - 6} textAnchor="middle" className="text-[22px] font-bold fill-slate-900">{total}</text>
        <text x={center} y={center + 12} textAnchor="middle" className="text-[10px] fill-slate-400">total</text>
      </svg>
      <div className="flex flex-wrap justify-center gap-x-3 gap-y-1">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center gap-1.5 text-[11px]">
            <span className="size-2 rounded-full shrink-0" style={{ backgroundColor: seg.color }} />
            <span className="text-slate-500">{seg.label}</span>
            <span className="font-semibold text-slate-700">{seg.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Mini Bar Chart (pure SVG) ──
function MiniBarChart({ data, height = 80 }: {
  data: { label: string; value: number; color: string }[];
  height?: number;
}) {
  const maxVal = Math.max(...data.map(d => d.value), 1);
  const barW = Math.max(16, Math.min(32, 200 / data.length));
  const chartW = data.length * (barW + 12) + 20;

  return (
    <svg width={chartW} height={height + 30} viewBox={`0 0 ${chartW} ${height + 30}`}>
      {data.map((d, i) => {
        const barH = Math.max(4, (d.value / maxVal) * height);
        const x = 10 + i * (barW + 12);
        const y = height - barH;
        return (
          <g key={i}>
            <rect x={x} y={y} width={barW} height={barH} rx={4} fill={d.color} opacity={0.85} />
            <text x={x + barW / 2} y={height + 16} textAnchor="middle" className="text-[9px] fill-slate-400">{d.label}</text>
            <text x={x + barW / 2} y={y - 4} textAnchor="middle" className="text-[9px] font-semibold fill-slate-600">{d.value}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [session, setSession] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [mounted, setMounted] = useState(false);

  const loadHealth = useCallback(async () => {
    try {
      const data = await request.get("/api/v1/health");
      setHealth((data.data as any) || null);
    } catch { /* health may be unavailable */ }
  }, []);

  useEffect(() => {
    let active = true;
    const init = async () => {
      const sess = await getValidatedAuthSession();
      if (!active) return;
      if (!sess) { router.replace("/login"); return; }
      setSession(sess);
      await loadHealth();
      setMounted(true);
    };
    void init();
    return () => { active = false; };
  }, [router, loadHealth]);

  const accountChart = useMemo(() => [
    { label: "Hoạt động", value: health?.accounts?.active ?? 0, color: "#10B981" },
    { label: "Giới hạn", value: health?.accounts?.limited ?? 0, color: "#F59E0B" },
    { label: "Lỗi", value: health?.accounts?.error ?? 0, color: "#EF4444" },
  ], [health]);

  const geminiInstances: any[] = (health as any)?.gemini?.instances || [];
  const customOnline = geminiInstances.filter((i: any) => i.status === "available").length;
  const instanceChart = useMemo(() => [
    { label: "Online", value: customOnline, color: "#10B981" },
    { label: "Offline/Error", value: geminiInstances.length - customOnline, color: "#F59E0B" },
  ], [customOnline, geminiInstances.length]);

  if (!session) return null;

  const totalAccounts = health?.accounts?.total ?? 0;
  const activeAccounts = health?.accounts?.active ?? 0;
  const limitedAccounts = (health?.accounts?.limited ?? 0) + (health?.accounts?.error ?? 0);
  const geminiStatus = (health as any)?.gemini;
  const version = health?.version || "…";

  if (!mounted) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="flex items-center gap-4">
          <div className="rounded-[14px] bg-white/60 size-12" />
          <div className="space-y-2"><div className="rounded-[10px] bg-white/60 h-5 w-32" /><div className="rounded-[10px] bg-white/60 h-3 w-48" /></div>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[1,2,3,4].map(i => <div key={i} className="rounded-[14px] bg-white/60 h-28" />)}</div>
      </div>
    );
  }

  const refreshBtn = (
    <button type="button" onClick={() => { setRefreshing(true); void loadHealth().finally(() => setTimeout(() => setRefreshing(false), 400)); }} disabled={refreshing}
      className="inline-flex items-center gap-2 rounded-[12px] border border-slate-200 bg-white px-4 py-2.5 text-[13px] font-semibold text-slate-600 shadow-sm transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-60">
      <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
      Làm mới
    </button>
  );

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-[14px] bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/25">
            <Sparkles className="size-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Tổng quan</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Theo dõi tài khoản, providers &amp; API endpoints · v{version}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="hidden sm:flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
            <span className="relative flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
            </span>
            Hoạt động
          </div>
          {refreshBtn}
        </div>
      </div>

      {/* ── Stat Cards Row ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Tổng tài khoản", value: totalAccounts, sub: `${activeAccounts} hoạt động`, color: "indigo" as const, icon: Users },
          { label: "API Endpoints", value: customOnline, sub: `${geminiInstances.length} đã cấu hình`, color: "violet" as const, icon: Server },
          { label: "Model Cooldown", value: health?.model_cooldown?.cooling ?? 0, sub: `${health?.model_cooldown?.total_tracked ?? 0} tracked`, color: "amber" as const, icon: Activity },
          { label: "Gemini API", value: geminiStatus?.gemini_api === "available" ? "Online" : "—", sub: `${geminiStatus?.models_count ?? 0} models`, color: "sky" as const, icon: Sparkles },
        ].map((card) => {
          const Icon = card.icon;
          const g = card.color === "indigo" ? "from-indigo-500 to-blue-600" : card.color === "violet" ? "from-violet-500 to-purple-600" : card.color === "amber" ? "from-amber-500 to-orange-600" : "from-sky-500 to-cyan-600";
          return (
            <div key={card.label} className={cn("group rounded-[14px] p-5 transition-all hover:-translate-y-0.5 card-3d", card.color === "indigo" ? "card-tint-indigo" : card.color === "violet" ? "card-tint-violet" : card.color === "amber" ? "card-tint-amber" : "card-tint-sky")}>
              <div className="flex items-start justify-between">
                <div className="space-y-1.5">
                  <p className="text-[11px] font-semibold tracking-wide text-slate-400 uppercase">{card.label}</p>
                  <p className="text-[28px] font-bold tracking-tight text-slate-900">{card.value}</p>
                  <p className="text-[11px] text-slate-500">{card.sub}</p>
                </div>
                <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-md", g)}>
                  <Icon className="size-[18px] text-white" />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Charts Row ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Account distribution donut */}
        <div className="rounded-[14px] card-main p-6">
          <h3 className="text-[13px] font-semibold text-slate-700 mb-4">Phân bố tài khoản</h3>
          <DonutChart segments={accountChart} size={140} thickness={26} />
        </div>

        {/* Instance status donut */}
        <div className="rounded-[14px] card-main p-6">
          <h3 className="text-[13px] font-semibold text-slate-700 mb-4">Trạng thái API Endpoints</h3>
          {geminiInstances.length > 0 ? (
            <DonutChart segments={instanceChart} size={140} thickness={26} />
          ) : (
            <div className="flex items-center justify-center h-[140px] text-sm text-slate-400">Chưa có instance nào</div>
          )}
        </div>
      </div>

      {/* ── System Status Bars ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-[10px] card-3d card-tint-slate p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3">Backoff</p>
          <div className="flex items-end justify-between">
            <p className="text-2xl font-bold text-slate-900">{health?.backoff?.total_locked_models ?? 0}</p>
            <p className="text-[11px] text-slate-500">locked</p>
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-amber-500 transition-all" style={{ width: `${Math.min(100, ((health?.backoff?.total_locked_models ?? 0) / Math.max(1, health?.backoff?.total_accounts_tracked ?? 1)) * 100)}%` }} />
          </div>
          <p className="text-[10px] text-slate-400 mt-1.5">{health?.backoff?.total_accounts_tracked ?? 0} tracked</p>
        </div>
        <div className="rounded-[10px] card-3d card-tint-slate p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3">Quota Watcher</p>
          <div className="flex items-end justify-between">
            <p className={cn("text-2xl font-bold", health?.quota_watcher?.running ? "text-emerald-600" : "text-amber-600")}>{health?.quota_watcher?.running ? "On" : "Off"}</p>
            <p className="text-[11px] text-slate-500">{health?.quota_watcher?.heap_size ?? 0} queued</p>
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-slate-100">
            <div className={cn("h-full rounded-full transition-all", health?.quota_watcher?.running ? "bg-emerald-500" : "bg-slate-300")} style={{ width: health?.quota_watcher?.running ? "100%" : "30%" }} />
          </div>
          <p className="text-[10px] text-slate-400 mt-1.5">queue size: {health?.quota_watcher?.heap_size ?? 0}</p>
        </div>
        <div className="rounded-[10px] card-3d card-tint-slate p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3">Cooldown</p>
          <div className="flex items-end justify-between">
            <p className="text-2xl font-bold text-slate-900">{health?.model_cooldown?.cooling ?? 0}</p>
            <p className="text-[11px] text-slate-500">cooling</p>
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-amber-500 transition-all" style={{ width: `${Math.min(100, ((health?.model_cooldown?.cooling ?? 0) / Math.max(1, health?.model_cooldown?.total_tracked ?? 1)) * 100)}%` }} />
          </div>
          <p className="text-[10px] text-slate-400 mt-1.5">{health?.model_cooldown?.total_tracked ?? 0} tracked</p>
        </div>
        <div className="rounded-[10px] card-3d card-tint-slate p-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3">Gemini API</p>
          <div className="flex items-end justify-between">
            <p className={cn("text-2xl font-bold", geminiStatus?.gemini_api === "available" ? "text-emerald-600" : "text-rose-500")}>{geminiStatus?.gemini_api === "available" ? "Online" : "—"}</p>
            <p className="text-[11px] text-slate-500">{geminiStatus?.models_count ?? 0} models</p>
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-slate-100">
            <div className={cn("h-full rounded-full transition-all", geminiStatus?.gemini_api === "available" ? "bg-emerald-500" : "bg-slate-300")} style={{ width: geminiStatus?.gemini_api === "available" ? "100%" : "30%" }} />
          </div>
          <p className="text-[10px] text-slate-400 mt-1.5">Google AI Studio</p>
        </div>
      </div>

      {/* ── Provider Instances Table ── */}
      {geminiInstances.length > 0 && (
        <div className="rounded-[14px] card-main overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100">
            <h3 className="text-[13px] font-semibold text-slate-700">Provider Instances</h3>
            <p className="text-[11px] text-slate-400 mt-0.5">Trạng thái các API endpoint đã cấu hình</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/50">
                  <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Trạng thái</th>
                  <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Tên</th>
                  <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Prefix</th>
                  <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Port</th>
                  <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Clients</th>
                  <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Entries</th>
                  <th className="text-left px-6 py-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Lỗi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {geminiInstances.map((inst: any) => (
                  <tr key={inst.id} className="hover:bg-slate-50/60 transition-colors">
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-2">
                        <div className={cn("size-2 rounded-full", inst.status === "available" ? "bg-emerald-500" : inst.status === "offline" ? "bg-rose-500" : "bg-amber-500")} />
                        <span className={cn("text-[12px] font-medium", inst.status === "available" ? "text-emerald-600" : "text-rose-500")}>{inst.status}</span>
                      </div>
                    </td>
                    <td className="px-6 py-3 text-[13px] font-medium text-slate-700">{inst.name}</td>
                    <td className="px-6 py-3"><code className="text-[11px] text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">{inst.prefix || "—"}</code></td>
                    <td className="px-6 py-3 text-[12px] text-slate-500">{inst.port || "—"}</td>
                    <td className="px-6 py-3 text-[12px] text-slate-600">{inst.clients || 0}</td>
                    <td className="px-6 py-3 text-[12px] text-slate-600">{inst.entries || 0}</td>
                    <td className="px-6 py-3 text-[11px] text-rose-500 max-w-[200px] truncate">{inst.error || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Quick Access ── */}
      <section>
        <h2 className="text-[12px] font-semibold uppercase tracking-[0.15em] text-slate-400 mb-4">Truy cập nhanh</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Tài khoản", desc: "Quản lý token & pool", href: "/accounts", icon: Users, color: "indigo" as const },
            { label: "Providers", desc: "OpenCode, Gemini, Codex…", href: "/providers", icon: Cpu, color: "violet" as const },
            { label: "Quản lý Model", desc: "Bật/tắt model", href: "/models", icon: Settings, color: "sky" as const },
            { label: "Mô hình kết hợp", desc: "Combo fallback", href: "/combos", icon: Combine, color: "emerald" as const },
            { label: "Tạo ảnh", desc: "DALL-E, SD, FLUX…", href: "/image", icon: ImageIcon, color: "rose" as const },
            { label: "Tạo video", desc: "Veo 3.1", href: "/video", icon: Video, color: "violet" as const },
            { label: "Tìm kiếm", desc: "Gemini, Serper…", href: "/search", icon: Search, color: "amber" as const },
            { label: "Sao lưu", desc: "Backup & restore", href: "/backup", icon: Archive, color: "slate" as const },
          ].map((link) => {
            const Icon = link.icon;
            return (
              <a key={link.href} href={link.href} className={cn("group flex items-center gap-4 rounded-[14px] p-4 transition-all hover:-translate-y-1 card-3d", link.color === "indigo" ? "card-tint-indigo" : link.color === "violet" ? "card-tint-violet" : link.color === "sky" ? "card-tint-sky" : link.color === "emerald" ? "card-tint-emerald" : link.color === "rose" ? "card-tint-rose" : link.color === "amber" ? "card-tint-amber" : "card-tint-slate")}>
                <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-md transition-transform group-hover:scale-105", link.color === "indigo" ? "from-indigo-500 to-blue-600" : link.color === "violet" ? "from-violet-500 to-purple-600" : link.color === "sky" ? "from-sky-500 to-cyan-600" : link.color === "emerald" ? "from-emerald-500 to-teal-600" : link.color === "rose" ? "from-rose-500 to-pink-600" : link.color === "amber" ? "from-amber-500 to-orange-600" : "from-slate-500 to-slate-600")}>
                  <Icon className="size-[18px] text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[14px] font-semibold text-slate-800 group-hover:text-indigo-600 transition-colors">{link.label}</p>
                  <p className="text-[11px] text-slate-500 truncate mt-0.5">{link.desc}</p>
                </div>
                <ArrowRight className="size-4 text-slate-300 shrink-0 transition-all group-hover:translate-x-1 group-hover:text-indigo-400" />
              </a>
            );
          })}
        </div>
      </section>
    </div>
  );
}
