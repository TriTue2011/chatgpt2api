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

type HealthData = {
  status: string;
  version: string;
  accounts: { total: number; active: number; limited: number; error: number };
  backoff: { total_accounts_tracked: number; total_locked_models: number };
  opencode: { available: boolean };
  quota_watcher?: { heap_size: number; running: boolean };
  model_cooldown?: { total_tracked: number; cooling: number };
};

export default function DashboardPage() {
  const router = useRouter();
  const [session, setSession] = useState<any>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
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

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadHealth();
    setTimeout(() => setRefreshing(false), 400);
  };

  if (!session) return null;

  const totalAccounts     = health?.accounts?.total ?? 0;
  const activeAccounts    = health?.accounts?.active ?? 0;
  const limitedAccounts   = (health?.accounts?.limited ?? 0) + (health?.accounts?.error ?? 0);
  const geminiStatus      = (health as any)?.gemini;
  const geminiInstances   = geminiStatus?.instances || [];
  const customOnline      = geminiInstances.filter((i: any) => i.status === "available").length;
  const version           = health?.version || "…";

  if (!mounted) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <div className="animate-pulse rounded-[14px] bg-white/60 size-12" />
          <div>
            <div className="animate-pulse rounded-[10px] bg-white/60 h-5 w-32 mb-1.5" />
            <div className="animate-pulse rounded-[10px] bg-white/60 h-3 w-48" />
          </div>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1,2,3,4].map(i => (
            <div key={i} className="rounded-[14px] bg-white/60 p-5">
              <div className="animate-pulse rounded-[10px] bg-slate-100 h-3 w-16 mb-3" />
              <div className="animate-pulse rounded-[10px] bg-slate-100 h-8 w-12 mb-2" />
              <div className="animate-pulse rounded-[10px] bg-slate-100 h-3 w-20" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* ── Header — 9router style ── */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-[14px] bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/25">
            <Sparkles className="size-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Tổng quan</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Quản lý tài khoản, theo dõi trạng thái providers &amp; API endpoints
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
          <button type="button" onClick={handleRefresh} disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-[12px] border border-slate-200 bg-white px-4 py-2.5 text-[13px] font-semibold text-slate-600 shadow-sm transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-60">
            <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
            Làm mới
          </button>
        </div>
      </div>

      {/* ── Stat Cards — 4 columns, 9router card style ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Tổng tài khoản", value: totalAccounts, sub: `Đang hoạt động: ${activeAccounts}`, icon: Users, color: "indigo" as const },
          { label: "Tỉ lệ hoạt động", value: totalAccounts > 0 ? Math.round((activeAccounts / totalAccounts) * 100) + "%" : "—", sub: totalAccounts > 0 ? `${limitedAccounts} giới hạn/lỗi` : "—", icon: ShieldCheck, color: limitedAccounts > 0 ? "amber" as const : "emerald" as const },
          { label: "API Endpoints", value: customOnline, sub: `${geminiInstances.length} instance đã cấu hình`, icon: Server, color: "violet" as const },
          { label: "Phiên bản", value: `v${version}`, sub: geminiStatus?.gemini_api === "available" ? `Gemini API · ${geminiStatus?.models_count ?? 0} models` : "Gemini: không khả dụng", icon: Sparkles, color: "sky" as const },
        ].map((card) => {
          const Icon = card.icon;
          const g = card.color === "indigo" ? "from-indigo-500 to-blue-600" :
            card.color === "emerald" ? "from-emerald-500 to-teal-600" :
            card.color === "amber" ? "from-amber-500 to-orange-600" :
            card.color === "violet" ? "from-violet-500 to-purple-600" :
            "from-sky-500 to-cyan-600";
          return (
            <div key={card.label} className={cn(
              "group relative overflow-hidden rounded-[14px] p-5 transition-all duration-300 hover:-translate-y-0.5",
              "card-3d",
              card.color === "indigo" ? "card-tint-indigo" :
              card.color === "emerald" ? "card-tint-emerald" :
              card.color === "amber" ? "card-tint-amber" :
              card.color === "violet" ? "card-tint-violet" :
              "card-tint-sky"
            )}>
              <div className="flex items-start justify-between">
                <div className="space-y-2">
                  <p className="text-[11px] font-semibold tracking-wide text-slate-400 uppercase">{card.label}</p>
                  <p className="text-3xl font-bold tracking-tight text-slate-900">{card.value}</p>
                  <p className="text-[12px] text-slate-500">{card.sub}</p>
                </div>
                <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-md", g)}>
                  <Icon className="size-[18px] text-white" />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── System Status — 9router style card ── */}
      <div className="rounded-[14px] card-main p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex size-9 items-center justify-center rounded-[10px] bg-slate-100">
            <Activity className="size-[18px] text-slate-500" />
          </div>
          <div>
            <h2 className="text-[15px] font-semibold text-slate-900">Trạng thái hệ thống</h2>
            <p className="text-[12px] text-slate-500">Backoff, Quota, Cooldown &amp; Provider instances</p>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          <div className="rounded-[10px] border border-slate-100 bg-slate-50/50 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Backoff</p>
            <p className="text-lg font-bold text-slate-900">{health?.backoff?.total_locked_models ?? 0} <span className="text-[12px] font-normal text-slate-500">locked</span></p>
            <p className="text-[11px] text-slate-400 mt-0.5">{health?.backoff?.total_accounts_tracked ?? 0} tracked</p>
          </div>
          <div className="rounded-[10px] border border-slate-100 bg-slate-50/50 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Quota Watcher</p>
            <p className={cn("text-lg font-bold", health?.quota_watcher?.running ? "text-emerald-600" : "text-amber-600")}>{health?.quota_watcher?.running ? "Running" : "Off"}</p>
            <p className="text-[11px] text-slate-400 mt-0.5">{health?.quota_watcher?.heap_size ?? 0} queued</p>
          </div>
          <div className="rounded-[10px] border border-slate-100 bg-slate-50/50 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Model Cooldown</p>
            <p className="text-lg font-bold text-slate-900">{health?.model_cooldown?.total_tracked ?? 0} <span className="text-[12px] font-normal text-slate-500">tracked</span></p>
            <p className="text-[11px] text-amber-600 mt-0.5">{health?.model_cooldown?.cooling ?? 0} cooling</p>
          </div>
          <div className="rounded-[10px] border border-slate-100 bg-slate-50/50 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Gemini API</p>
            <p className={cn("text-lg font-bold", geminiStatus?.gemini_api === "available" ? "text-emerald-600" : "text-rose-500")}>{geminiStatus?.gemini_api === "available" ? "Online" : geminiStatus?.gemini_api ?? "…"}</p>
            <p className="text-[11px] text-slate-400 mt-0.5">{geminiStatus?.models_count ?? 0} models</p>
          </div>
        </div>

        {/* Instance list */}
        {geminiInstances.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2">Provider Instances</p>
            {geminiInstances.map((inst: any) => (
              <div key={inst.id} className="flex items-center gap-3 rounded-[10px] border border-slate-100 bg-white/60 px-4 py-2.5">
                <div className={cn("size-2 rounded-full shrink-0", inst.status === "available" ? "bg-emerald-500" : inst.status === "offline" ? "bg-rose-500" : "bg-amber-500")} />
                <span className="flex-1 text-[13px] font-medium text-slate-700">{inst.name}</span>
                {inst.prefix && <code className="text-[11px] text-slate-400">{inst.prefix}/</code>}
                <span className="text-[11px] text-slate-400">:{inst.port}</span>
                <span className={cn("text-[12px] font-medium", inst.status === "available" ? "text-emerald-600" : "text-rose-500")}>{inst.status}</span>
                {inst.clients > 0 && <span className="text-[11px] text-slate-400">{inst.clients} clients</span>}
                {inst.entries > 0 && <span className="text-[11px] text-slate-400">{inst.entries} entries</span>}
                {inst.error && <span className="text-[10px] text-rose-400 truncate max-w-[160px]">{inst.error}</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Quick Access — 9router grid style ── */}
      <section>
        <h2 className="text-[12px] font-semibold uppercase tracking-[0.15em] text-slate-400 mb-4">Truy cập nhanh</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Tài khoản", desc: "Quản lý token &amp; pool", href: "/accounts", icon: Users, color: "indigo" as const },
            { label: "Providers", desc: "OpenCode, Gemini, Codex…", href: "/providers", icon: Cpu, color: "violet" as const },
            { label: "Quản lý Model", desc: "Bật/tắt model từng provider", href: "/models", icon: Settings, color: "sky" as const },
            { label: "Mô hình kết hợp", desc: "Combo fallback tự động", href: "/combos", icon: Combine, color: "emerald" as const },
            { label: "Tạo ảnh", desc: "DALL-E, SD, FLUX…", href: "/image", icon: ImageIcon, color: "rose" as const },
            { label: "Tạo video", desc: "Veo 3.1", href: "/video", icon: Video, color: "violet" as const },
            { label: "Tìm kiếm", desc: "Gemini, Serper, SearXNG…", href: "/search", icon: Search, color: "amber" as const },
            { label: "Sao lưu", desc: "Backup &amp; restore", href: "/backup", icon: Archive, color: "slate" as const },
          ].map((link) => {
            const Icon = link.icon;
            const g = link.color === "indigo" ? "from-indigo-500 to-blue-600" :
              link.color === "emerald" ? "from-emerald-500 to-teal-600" :
              link.color === "amber" ? "from-amber-500 to-orange-600" :
              link.color === "violet" ? "from-violet-500 to-purple-600" :
              link.color === "rose" ? "from-rose-500 to-pink-600" :
              link.color === "sky" ? "from-sky-500 to-cyan-600" :
              "from-slate-500 to-slate-600";
            return (
              <a key={link.href} href={link.href} className={cn(
                "group flex items-center gap-4 rounded-[14px] p-4 transition-all duration-300 hover:-translate-y-1",
                "card-3d",
                link.color === "indigo" ? "card-tint-indigo" :
                link.color === "emerald" ? "card-tint-emerald" :
                link.color === "amber" ? "card-tint-amber" :
                link.color === "violet" ? "card-tint-violet" :
                link.color === "rose" ? "card-tint-rose" :
                link.color === "sky" ? "card-tint-sky" :
                "card-tint-slate",
              )}>
                <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-md transition-transform duration-300 group-hover:scale-105", g)}>
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
