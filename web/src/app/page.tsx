"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users, Cpu, Sparkles, Combine, ImageIcon,
  Search, Archive, Settings, RefreshCw,
  ArrowRight, ShieldCheck, Activity, Bell,
  TrendingUp, Zap, ChevronRight,
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

// ── Premium gradient presets ──
const gradients = {
  indigo:  "from-indigo-500 via-blue-500 to-indigo-600",
  emerald: "from-emerald-400 via-teal-500 to-emerald-600",
  amber:   "from-amber-400 via-orange-500 to-amber-600",
  violet:  "from-violet-500 via-purple-500 to-violet-600",
  rose:    "from-rose-400 via-pink-500 to-rose-600",
  sky:     "from-sky-400 via-cyan-500 to-sky-600",
  slate:   "from-slate-500 via-slate-600 to-slate-700",
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
      const h = (data.data as any) || null;
      setHealth(h);
    } catch {
      // health may be unavailable
    }
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
  const opencodeAvailable = health?.opencode?.available ?? false;
  const version           = health?.version || "…";

  // ── Stat cards ──
  const statCards = [
    {
      label: "Tổng tài khoản",
      value: totalAccounts,
      sub: "trong pool",
      icon: Users,
      color: "indigo" as const,
      trend: null,
    },
    {
      label: "Hoạt động",
      value: activeAccounts,
      sub: "đang dùng được",
      icon: ShieldCheck,
      color: "emerald" as const,
      trend: totalAccounts > 0 ? Math.round((activeAccounts / totalAccounts) * 100) + "%" : "—",
    },
    {
      label: "Bị giới hạn / Lỗi",
      value: limitedAccounts,
      sub: health?.model_cooldown?.cooling ? `${health.model_cooldown.cooling} đang cooling` : "cần chú ý",
      icon: Activity,
      color: limitedAccounts > 0 ? "amber" as const : "slate" as const,
      trend: null,
    },
    {
      label: "OpenCode",
      value: opencodeAvailable ? "Online" : "Offline",
      sub: "miễn phí · không giới hạn",
      icon: Zap,
      color: opencodeAvailable ? "violet" as const : "slate" as const,
      trend: null,
    },
  ];

  // ── Quick access cards ──
  const quickLinks = [
    { label: "Tài khoản",  desc: "Quản lý token & pool",          href: "/accounts",      icon: Users,     color: "indigo"  as const },
    { label: "Providers",  desc: "OpenCode, Gemini, Codex…",       href: "/providers",      icon: Cpu,       color: "violet"  as const },
    { label: "Quản lý Model", desc: "Bật/tắt model từng provider", href: "/models",         icon: Sparkles,  color: "sky"     as const },
    { label: "Mô hình kết hợp", desc: "Combo fallback tự động",    href: "/combos",         icon: Combine,   color: "emerald" as const },
    { label: "Tạo ảnh",     desc: "DALL-E, SD, FLUX…",             href: "/image",          icon: ImageIcon, color: "rose"    as const },
    { label: "Tìm kiếm",    desc: "Gemini, Serper, SearXNG…",      href: "/search",         icon: Search,    color: "amber"   as const },
    { label: "Sao lưu",     desc: "Backup & restore hệ thống",     href: "/backup",         icon: Archive,   color: "slate"   as const },
    { label: "Cài đặt",     desc: "Proxy, rate limit, prompt…",    href: "/settings",       icon: Settings,  color: "slate"   as const },
  ];

  // ── Skeleton for loading ──
  if (!mounted) {
    return (
      <div className="space-y-8 animate-pulse">
        <div className="h-20 bg-white/60 rounded-2xl" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1,2,3,4].map(i => <div key={i} className="h-32 bg-white/60 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* ── Page Header ── */}
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <div className="flex size-8 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/25">
              <TrendingUp className="size-4 text-white" />
            </div>
            <p className="text-[11px] font-bold tracking-[0.2em] text-indigo-500 uppercase">Tổng quan</p>
          </div>
          <h1 className="text-[28px] font-extrabold tracking-tight text-slate-900">
            Bảng điều khiển
          </h1>
          <p className="text-sm text-slate-500">
            chatgpt2api <span className="font-mono text-slate-400">v{version}</span> · Hệ thống quản lý AI tập trung
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Live indicator */}
          <div className="hidden sm:flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
            <span className="relative flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
            </span>
            Hệ thống hoạt động
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-[13px] font-semibold text-slate-600 shadow-sm transition-all duration-200 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 hover:shadow-md disabled:opacity-60"
          >
            <RefreshCw className={cn("size-4 transition-transform", refreshing && "animate-spin")} />
            Làm mới
          </button>
        </div>
      </header>

      {/* ── Stat Cards ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((card) => {
          const Icon = card.icon;
          const g = gradients[card.color];
          return (
            <div
              key={card.label}
              className="group relative overflow-hidden rounded-2xl border border-slate-200/60 bg-white/80 backdrop-blur-sm p-5 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg hover:border-slate-300"
            >
              {/* subtle gradient glow on hover */}
              <div className="absolute inset-0 bg-gradient-to-br from-slate-50 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" />

              <div className="relative flex items-start justify-between">
                <div className="space-y-2">
                  <p className="text-[11px] font-bold tracking-widest text-slate-400 uppercase">
                    {card.label}
                  </p>
                  <p className="text-[32px] font-extrabold leading-none tracking-tight text-slate-900">
                    {card.value}
                  </p>
                  <div className="flex items-center gap-2">
                    <p className="text-xs text-slate-500">{card.sub}</p>
                    {card.trend && (
                      <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                        {card.trend}
                      </span>
                    )}
                  </div>
                </div>
                <div className={cn(
                  "flex size-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br shadow-lg",
                  g,
                  card.color === "indigo"  ? "shadow-indigo-500/20"  :
                  card.color === "emerald" ? "shadow-emerald-500/20" :
                  card.color === "amber"   ? "shadow-amber-500/20"   :
                  card.color === "violet"  ? "shadow-violet-500/20"  :
                                             "shadow-slate-500/15"
                )}>
                  <Icon className="size-5 text-white" />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── System sub-status bar ── */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200/60 bg-white/60 px-4 py-2.5 text-xs text-slate-500">
        <span className="font-semibold text-slate-700">Trạng thái hệ thống</span>
        <span className="text-slate-300">·</span>
        <span>Backoff: <strong className="text-slate-700">{health?.backoff?.total_locked_models ?? 0}</strong> model locked</span>
        <span className="text-slate-300">·</span>
        <span>Quota Watcher: <strong className={cn(health?.quota_watcher?.running ? "text-emerald-600" : "text-amber-600")}>{health?.quota_watcher?.running ? "Đang chạy" : "Tắt"}</strong></span>
        {health?.quota_watcher?.heap_size ? (
          <>
            <span className="text-slate-300">·</span>
            <span><strong className="text-slate-700">{health.quota_watcher.heap_size}</strong> trong hàng đợi</span>
          </>
        ) : null}
        <span className="text-slate-300">·</span>
        <span>Cooldown: <strong className="text-slate-700">{health?.model_cooldown?.total_tracked ?? 0}</strong> tracked, <strong className="text-amber-600">{health?.model_cooldown?.cooling ?? 0}</strong> cooling</span>
      </div>

      {/* ── Quick Access ── */}
      <section>
        <div className="mb-4 flex items-center gap-3">
          <h2 className="text-[13px] font-bold tracking-[0.15em] text-slate-400 uppercase">Truy cập nhanh</h2>
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
                  "group relative flex items-center gap-4 rounded-2xl border border-slate-200/60 bg-white/70 backdrop-blur-sm p-4",
                  "shadow-sm transition-all duration-300",
                  "hover:-translate-y-1 hover:shadow-xl hover:border-indigo-200/60",
                  "active:translate-y-0 active:shadow-sm"
                )}
              >
                <div className={cn(
                  "flex size-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-md transition-transform duration-300 group-hover:scale-105",
                  g,
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
