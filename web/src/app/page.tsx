"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users, Cpu, Sparkles, Combine, ImageIcon,
  Search, Archive, Settings, RefreshCw,
  ShieldCheck, Activity, Server, Video,
  ArrowRight,
} from "lucide-react";

import { getValidatedAuthSession } from "@/lib/auth-session";
import { getDefaultRouteForRole } from "@/store/auth";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

function fmt(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n || 0);
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

  if (!session) return null;

  const totalAccounts = health?.accounts?.total ?? 0;
  const activeAccounts = health?.accounts?.active ?? 0;
  const limitedAccounts = (health?.accounts?.limited ?? 0) + (health?.accounts?.error ?? 0);
  const geminiStatus = (health as any)?.gemini;
  const geminiInstances: any[] = geminiStatus?.instances || [];
  const customOnline = geminiInstances.filter((i: any) => i.status === "available").length;
  const cooldownCooling = health?.model_cooldown?.cooling ?? 0;
  const cooldownTracked = health?.model_cooldown?.total_tracked ?? 0;
  const backoffLocked = health?.backoff?.total_locked_models ?? 0;
  const quotaRunning = health?.quota_watcher?.running ?? false;
  const quotaHeap = health?.quota_watcher?.heap_size ?? 0;
  const version = health?.version || "…";

  if (!mounted) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 sm:gap-4">
          {[1,2,3,4].map(i => <div key={i} className="rounded-[14px] bg-white/60 h-20" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {/* ── Overview Cards — 9router style ── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 sm:gap-4">
        <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
          <span className="text-[11px] uppercase font-semibold text-slate-400">Tổng tài khoản</span>
          <span className="truncate text-2xl font-bold text-slate-900">{fmt(totalAccounts)}</span>
          <span className="text-[11px] text-emerald-600">{activeAccounts} hoạt động</span>
        </div>
        <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
          <span className="text-[11px] uppercase font-semibold text-slate-400">Giới hạn / Lỗi</span>
          <span className={cn("truncate text-2xl font-bold", limitedAccounts > 0 ? "text-amber-600" : "text-emerald-600")}>{limitedAccounts}</span>
          <span className="text-[11px] text-slate-400">{cooldownCooling > 0 ? `${cooldownCooling} đang cooling` : "Không có lỗi"}</span>
        </div>
        <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
          <span className="text-[11px] uppercase font-semibold text-slate-400">API Endpoints</span>
          <span className="truncate text-2xl font-bold text-violet-600">{customOnline}/{geminiInstances.length}</span>
          <span className="text-[11px] text-slate-400">online / configured</span>
        </div>
        <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
          <span className="text-[11px] uppercase font-semibold text-slate-400">Hệ thống</span>
          <span className={cn("truncate text-2xl font-bold", geminiStatus?.gemini_api === "available" ? "text-emerald-600" : "text-rose-500")}>
            {geminiStatus?.gemini_api === "available" ? "Online" : "—"}
          </span>
          <span className="text-[11px] text-slate-400">v{version} · Gemini {geminiStatus?.models_count ?? 0} models</span>
        </div>
      </div>

      {/* ── Sub-metrics — 9router style mini cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-[12px] card-3d card-tint-slate px-4 py-3 flex items-center justify-between">
          <span className="text-[11px] font-semibold text-slate-400 uppercase">Backoff</span>
          <div className="text-right">
            <span className="text-lg font-bold text-slate-900">{backoffLocked}</span>
            <span className="text-[10px] text-slate-400 ml-1">locked</span>
          </div>
        </div>
        <div className="rounded-[12px] card-3d card-tint-slate px-4 py-3 flex items-center justify-between">
          <span className="text-[11px] font-semibold text-slate-400 uppercase">Quota</span>
          <div className="text-right">
            <span className={cn("text-lg font-bold", quotaRunning ? "text-emerald-600" : "text-amber-600")}>{quotaRunning ? "On" : "Off"}</span>
            <span className="text-[10px] text-slate-400 ml-1">{quotaHeap} q</span>
          </div>
        </div>
        <div className="rounded-[12px] card-3d card-tint-slate px-4 py-3 flex items-center justify-between">
          <span className="text-[11px] font-semibold text-slate-400 uppercase">Cooldown</span>
          <div className="text-right">
            <span className="text-lg font-bold text-slate-900">{cooldownCooling}</span>
            <span className="text-[10px] text-slate-400 ml-1">/ {cooldownTracked}</span>
          </div>
        </div>
        <div className="rounded-[12px] card-3d card-tint-slate px-4 py-3 flex items-center justify-between">
          <span className="text-[11px] font-semibold text-slate-400 uppercase">Refresh</span>
          <button type="button" onClick={() => { setRefreshing(true); void loadHealth().finally(() => setTimeout(() => setRefreshing(false), 400)); }} disabled={refreshing}
            className="inline-flex items-center gap-1.5 text-[12px] font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-50">
            <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
            Làm mới
          </button>
        </div>
      </div>

      {/* ── Provider Instances Table — 9router UsageTable style ── */}
      {geminiInstances.length > 0 && (
        <div className="rounded-[14px] card-main overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/50">
            <h3 className="text-[13px] font-semibold text-slate-700">Provider Instances</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-50/30 text-[10px] uppercase font-semibold text-slate-400">
                <tr>
                  <th className="px-5 py-2.5 w-8"></th>
                  <th className="px-5 py-2.5">Tên</th>
                  <th className="px-5 py-2.5">Prefix</th>
                  <th className="px-5 py-2.5">Port</th>
                  <th className="px-5 py-2.5 text-right">Clients</th>
                  <th className="px-5 py-2.5 text-right">Entries</th>
                  <th className="px-5 py-2.5 text-right">Lỗi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {geminiInstances.map((inst: any) => (
                  <tr key={inst.id} className="hover:bg-slate-50/40 transition-colors">
                    <td className="px-5 py-2.5">
                      <span className={cn("block w-2 h-2 rounded-full", inst.status === "available" ? "bg-emerald-500" : inst.status === "offline" ? "bg-rose-500" : "bg-amber-500")} />
                    </td>
                    <td className="px-5 py-2.5 font-medium text-slate-700 text-[13px]">{inst.name}</td>
                    <td className="px-5 py-2.5"><code className="text-[11px] text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">{inst.prefix || "—"}</code></td>
                    <td className="px-5 py-2.5 text-slate-500 text-[12px]">{inst.port || "—"}</td>
                    <td className="px-5 py-2.5 text-right text-slate-600 text-[12px]">{inst.clients || 0}</td>
                    <td className="px-5 py-2.5 text-right text-slate-600 text-[12px]">{inst.entries || 0}</td>
                    <td className="px-5 py-2.5 text-right text-[11px] max-w-[180px] truncate">
                      {inst.error ? <span className="text-rose-500">{inst.error}</span> : <span className="text-slate-300">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Quick Access — 9router grid style ── */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Tài khoản", desc: "Quản lý token & pool", href: "/accounts", icon: Users, color: "indigo" },
          { label: "Providers", desc: "OpenCode, Gemini, Codex…", href: "/providers", icon: Cpu, color: "violet" },
          { label: "Quản lý Model", desc: "Bật/tắt model", href: "/models", icon: Settings, color: "sky" },
          { label: "Mô hình kết hợp", desc: "Combo fallback", href: "/combos", icon: Combine, color: "emerald" },
          { label: "Tạo ảnh", desc: "DALL-E, SD, FLUX…", href: "/image", icon: ImageIcon, color: "rose" },
          { label: "Tạo video", desc: "Veo 3.1", href: "/video", icon: Video, color: "violet" },
          { label: "Tìm kiếm", desc: "Gemini, Serper…", href: "/search", icon: Search, color: "amber" },
          { label: "Sao lưu", desc: "Backup & restore", href: "/backup", icon: Archive, color: "slate" },
        ].map((link) => {
          const Icon = link.icon;
          return (
            <a key={link.href} href={link.href}
              className={cn("group flex items-center gap-3 rounded-[14px] px-4 py-3 transition-all hover:-translate-y-0.5 card-3d",
                link.color === "indigo" ? "card-tint-indigo" : link.color === "violet" ? "card-tint-violet" :
                link.color === "sky" ? "card-tint-sky" : link.color === "emerald" ? "card-tint-emerald" :
                link.color === "rose" ? "card-tint-rose" : link.color === "amber" ? "card-tint-amber" : "card-tint-slate"
              )}>
              <div className={cn("flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-gradient-to-br shadow-md transition-transform group-hover:scale-105",
                link.color === "indigo" ? "from-indigo-500 to-blue-600" : link.color === "violet" ? "from-violet-500 to-purple-600" :
                link.color === "sky" ? "from-sky-500 to-cyan-600" : link.color === "emerald" ? "from-emerald-500 to-teal-600" :
                link.color === "rose" ? "from-rose-500 to-pink-600" : link.color === "amber" ? "from-amber-500 to-orange-600" : "from-slate-500 to-slate-600"
              )}>
                <Icon className="size-[16px] text-white" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-semibold text-slate-800 group-hover:text-indigo-600 transition-colors">{link.label}</p>
                <p className="text-[11px] text-slate-500 truncate">{link.desc}</p>
              </div>
              <ArrowRight className="size-3.5 text-slate-300 shrink-0 transition-all group-hover:translate-x-1 group-hover:text-indigo-400" />
            </a>
          );
        })}
      </div>
    </div>
  );
}
