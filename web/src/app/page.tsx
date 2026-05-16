"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users, Cpu, Sparkles, Combine, ImageIcon,
  Search, Archive, Settings, RefreshCw,
  ChevronRight, ShieldCheck, Activity,
  Server, Video,
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

const gradients = {
  indigo:  "from-indigo-500 via-blue-500 to-indigo-600",
  emerald: "from-emerald-400 via-teal-500 to-emerald-600",
  amber:   "from-amber-400 via-orange-500 to-amber-600",
  violet:  "from-violet-500 via-purple-500 to-violet-600",
  rose:    "from-rose-400 via-pink-500 to-rose-600",
  sky:     "from-sky-400 via-cyan-500 to-sky-600",
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

  // ── Stat cards ──
  const statCards = [
    { label: "Tổng tài khoản", value: totalAccounts, sub: "tài khoản trong pool", icon: Users, color: "indigo" as const, trend: null },
    { label: "Hoạt động", value: activeAccounts, sub: "đang sẵn sàng", icon: ShieldCheck, color: "emerald" as const, trend: totalAccounts > 0 ? Math.round((activeAccounts / totalAccounts) * 100) + "%" : null },
    { label: "Giới hạn / Lỗi", value: limitedAccounts, sub: health?.model_cooldown?.cooling ? `${health.model_cooldown.cooling} cooling` : "cần theo dõi", icon: Activity, color: limitedAccounts > 0 ? "amber" as const : "slate" as const, trend: null },
    { label: "Custom APIs", value: customOnline, sub: `${geminiInstances.length} instance`, icon: Server, color: "sky" as const, trend: geminiStatus?.gemini_api === "available" ? "Gemini Online" : null },
    { label: "Phiên bản", value: `v${version}`, sub: "chatgpt2api", icon: Sparkles, color: "violet" as const, trend: null },
  ];

  // ── Quick access ──
  const quickLinks = [
    { label: "Tài khoản",  desc: "Quản lý token & pool",          href: "/accounts",      icon: Users,     color: "indigo"  as const },
    { label: "Providers",  desc: "OpenCode, Gemini, Codex…",       href: "/providers",      icon: Cpu,       color: "violet"  as const },
    { label: "Quản lý Model", desc: "Bật/tắt model từng provider", href: "/models",         icon: Settings,  color: "sky"     as const },
    { label: "Mô hình kết hợp", desc: "Combo fallback tự động",    href: "/combos",         icon: Combine,   color: "emerald" as const },
    { label: "Tạo ảnh",     desc: "DALL-E, SD, FLUX…",             href: "/image",          icon: ImageIcon, color: "rose"    as const },
    { label: "Tạo video",   desc: "Veo 3.1…",                      href: "/video",          icon: Video,     color: "violet"  as const },
    { label: "Tìm kiếm",    desc: "Gemini, Serper, SearXNG…",      href: "/search",         icon: Search,    color: "amber"   as const },
    { label: "Sao lưu",     desc: "Backup & restore",              href: "/backup",         icon: Archive,   color: "slate"   as const },
  ];

  if (!mounted) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-16 bg-white/60 rounded-2xl" />
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {[1,2,3,4,5].map(i => <div key={i} className="h-24 bg-white/60 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Header — 9router style ── */}
      <header className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-[14px] bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/25">
            <Sparkles className="size-5 text-white" />
          </div>
          <div className="min-w-0">
            <h1 className="text-[22px] font-bold tracking-tight text-slate-900">Tổng quan</h1>
            <p className="text-[13px] text-slate-500 truncate">
              chatgpt2api v{version} · Hệ thống quản lý AI tập trung
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
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-[12px] border border-slate-200 bg-white px-4 py-2.5 text-[13px] font-semibold text-slate-600 shadow-sm transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-60"
          >
            <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
            Làm mới
          </button>
        </div>
      </header>

      {/* ── Stat Cards — 5 per row ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {statCards.map((card) => {
          const Icon = card.icon;
          const g = gradients[card.color];
          return (
            <div
              key={card.label}
              className={cn(
                "group relative overflow-hidden rounded-2xl p-4 transition-all duration-300 hover:-translate-y-0.5",
                "card-3d",
                card.color === "indigo"  ? "card-tint-indigo"  :
                card.color === "emerald" ? "card-tint-emerald" :
                card.color === "amber"   ? "card-tint-amber"   :
                card.color === "violet"  ? "card-tint-violet"  :
                card.color === "sky"     ? "card-tint-sky"     :
                                           "card-tint-slate"
              )}
            >
              <div className="relative flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[10px] font-bold tracking-widest text-slate-400 uppercase mb-1">
                    {card.label}
                  </p>
                  <p className="text-[28px] font-extrabold leading-none tracking-tight text-slate-900">
                    {card.value}
                  </p>
                  <div className="flex items-center gap-2 mt-1.5">
                    <p className="text-[11px] text-slate-500 truncate">{card.sub}</p>
                    {card.trend && (
                      <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700 whitespace-nowrap">
                        {card.trend}
                      </span>
                    )}
                  </div>
                </div>
                <div className={cn(
                  "flex size-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br shadow-md",
                  g
                )}>
                  <Icon className="size-[18px] text-white" />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── System Status Bar ── */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl card-main px-4 py-3 text-xs text-slate-500">
        <span className="font-semibold text-slate-700 text-[11px] uppercase tracking-wider">Hệ thống</span>
        <span className="text-slate-300">·</span>
        <span>Backoff: <strong className="text-slate-700">{health?.backoff?.total_locked_models ?? 0}</strong> locked</span>
        <span className="text-slate-300">·</span>
        <span>Quota: <strong className={cn(health?.quota_watcher?.running ? "text-emerald-600" : "text-amber-600")}>{health?.quota_watcher?.running ? "Running" : "Off"}</strong>{health?.quota_watcher?.heap_size ? ` · ${health.quota_watcher.heap_size} queued` : ""}</span>
        <span className="text-slate-300">·</span>
        <span>Cooldown: <strong className="text-slate-700">{health?.model_cooldown?.total_tracked ?? 0}</strong> tracked · <strong className="text-amber-600">{health?.model_cooldown?.cooling ?? 0}</strong> cooling</span>
        <span className="text-slate-300">·</span>
        <span>Gemini API: <strong className={geminiStatus?.gemini_api === "available" ? "text-emerald-600" : "text-rose-500"}>{geminiStatus?.gemini_api ?? "…"}</strong> · {geminiStatus?.models_count ?? 0} models</span>
        {geminiInstances.map((inst: any) => (
          <span key={inst.id}>
            <span className="text-slate-300">·</span>
            <span>{inst.name}: <strong className={inst.status === "available" ? "text-emerald-600" : "text-rose-500"}>{inst.status}</strong> port {inst.port}{inst.clients > 0 ? ` · ${inst.clients}c` : ""}{inst.error ? ` · ${inst.error}` : ""}</span>
          </span>
        ))}
      </div>

      {/* ── Quick Access Grid ── */}
      <section>
        <div className="mb-4 flex items-center gap-3">
          <h2 className="text-[12px] font-bold tracking-[0.15em] text-slate-400 uppercase">Truy cập nhanh</h2>
          <div className="h-px flex-1 bg-slate-100" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {quickLinks.map((link) => {
            const Icon = link.icon;
            const g = gradients[link.color];
            return (
              <a
                key={link.href}
                href={link.href}
                className={cn(
                  "group relative flex items-center gap-4 rounded-2xl p-4",
                  "card-3d",
                  link.color === "indigo"  ? "card-tint-indigo"  :
                  link.color === "emerald" ? "card-tint-emerald" :
                  link.color === "amber"   ? "card-tint-amber"   :
                  link.color === "violet"  ? "card-tint-violet"  :
                  link.color === "rose"    ? "card-tint-rose"    :
                  link.color === "sky"     ? "card-tint-sky"     :
                                             "card-tint-slate",
                  "transition-all duration-300 hover:-translate-y-1 hover:shadow-xl active:translate-y-0"
                )}
              >
                <div className={cn(
                  "flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-md transition-transform duration-300 group-hover:scale-105",
                  g
                )}>
                  <Icon className="size-[18px] text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[14px] font-bold text-slate-800 group-hover:text-indigo-600 transition-colors">
                    {link.label}
                  </p>
                  <p className="text-[12px] text-slate-500 truncate mt-0.5">{link.desc}</p>
                </div>
                <ChevronRight className="size-4 text-slate-300 shrink-0 transition-all duration-300 group-hover:translate-x-1 group-hover:text-indigo-400" />
              </a>
            );
          })}
        </div>
      </section>
    </div>
  );
}
