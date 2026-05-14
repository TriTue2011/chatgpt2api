"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  LayoutDashboard, Users, Cpu, Activity,
  ArrowRight, Sparkles, Combine, ImageIcon,
  Search, Archive, Settings, RefreshCw,
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
};

export default function DashboardPage() {
  const router = useRouter();
  const [session, setSession] = useState<any>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadHealth = async () => {
    try {
      const data = await request.get("/api/v1/health");
      setHealth((data.data as any) || null);
    } catch {
      // Health endpoint may not be available
    }
  };

  useEffect(() => {
    let active = true;
    const init = async () => {
      const sess = await getValidatedAuthSession();
      if (!active) return;
      if (!sess) { router.replace("/login"); return; }
      setSession(sess);
      await loadHealth();
    };
    void init();
    return () => { active = false; };
  }, [router]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadHealth();
    setRefreshing(false);
  };

  if (!session) return null;

  const statCards = [
    {
      label: "Tổng tài khoản",
      value: health?.accounts?.total ?? "—",
      sub: "trong pool",
      icon: Users,
      gradient: "from-indigo-500 to-blue-600",
      shadow: "shadow-indigo-200",
      bg: "from-indigo-50/80 to-blue-50/80",
      textColor: "text-indigo-900",
      labelColor: "text-indigo-600",
    },
    {
      label: "Hoạt động",
      value: health?.accounts?.active ?? "—",
      sub: "đang dùng được",
      icon: Activity,
      gradient: "from-emerald-500 to-teal-600",
      shadow: "shadow-emerald-200",
      bg: "from-emerald-50/80 to-teal-50/80",
      textColor: "text-emerald-900",
      labelColor: "text-emerald-600",
    },
    {
      label: "Bị giới hạn",
      value: health?.accounts?.limited ?? "—",
      sub: `${health?.accounts?.error ?? "—"} lỗi`,
      icon: LayoutDashboard,
      gradient: "from-amber-500 to-orange-500",
      shadow: "shadow-amber-200",
      bg: "from-amber-50/80 to-orange-50/80",
      textColor: "text-amber-900",
      labelColor: "text-amber-600",
    },
    {
      label: "OpenCode",
      value: health?.opencode?.available ? "Sẵn sàng" : "Tắt",
      sub: "miễn phí · không giới hạn",
      icon: Cpu,
      gradient: health?.opencode?.available ? "from-violet-500 to-purple-600" : "from-slate-400 to-slate-500",
      shadow: health?.opencode?.available ? "shadow-violet-200" : "shadow-slate-200",
      bg: health?.opencode?.available ? "from-violet-50/80 to-purple-50/80" : "from-slate-50/80 to-slate-100/80",
      textColor: health?.opencode?.available ? "text-violet-900" : "text-slate-700",
      labelColor: health?.opencode?.available ? "text-violet-600" : "text-slate-500",
    },
  ];

  const quickLinks = [
    { label: "Tài khoản", desc: "Quản lý token & pool ChatGPT", href: "/accounts", icon: Users, color: "from-indigo-500 to-blue-600", shadow: "shadow-indigo-200" },
    { label: "Nhà cung cấp", desc: "OpenCode, Gemini, OpenRouter...", href: "/providers", icon: Cpu, color: "from-violet-500 to-purple-600", shadow: "shadow-violet-200" },
    { label: "Quản lý Model", desc: "Bật/tắt model cho từng provider", href: "/models", icon: Sparkles, color: "from-sky-500 to-cyan-600", shadow: "shadow-sky-200" },
    { label: "Mô hình kết hợp", desc: "Combo fallback tự động", href: "/combos", icon: Combine, color: "from-emerald-500 to-teal-600", shadow: "shadow-emerald-200" },
    { label: "Vẽ ảnh", desc: "DALL-E, SD WebUI, FLUX...", href: "/image", icon: ImageIcon, color: "from-rose-500 to-pink-600", shadow: "shadow-rose-200" },
    { label: "Tìm kiếm", desc: "Gemini, Serper, SearXNG...", href: "/search", icon: Search, color: "from-amber-500 to-orange-500", shadow: "shadow-amber-200" },
    { label: "Sao lưu", desc: "Backup & restore hệ thống", href: "/backup", icon: Archive, color: "from-slate-600 to-slate-700", shadow: "shadow-slate-200" },
    { label: "Cài đặt", desc: "Proxy, rate limit, system prompt...", href: "/settings", icon: Settings, color: "from-slate-500 to-slate-600", shadow: "shadow-slate-200" },
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between border-b border-black/[0.04] pb-6">
        <div>
          <p className="text-[11px] font-bold tracking-widest text-indigo-500 uppercase mb-1">Tổng quan</p>
          <h1 className="text-[26px] font-bold tracking-tight text-slate-900">Bảng điều khiển</h1>
          <p className="text-[14px] text-slate-500 mt-0.5">
            chatgpt2api v{health?.version || "..."} · Hệ thống quản lý AI tập trung
          </p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-[12px] border border-black/[0.06] bg-white px-4 py-2.5 text-[13px] font-medium text-slate-600 shadow-sm transition hover:bg-slate-50 hover:shadow disabled:opacity-50"
        >
          <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
          Làm mới
        </button>
      </div>

      {/* Stat Cards — ql_tro style */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {statCards.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className={cn(
                "rounded-xl border-0 p-4 md:p-5",
                `bg-gradient-to-br ${card.bg}`,
                `shadow-lg ${card.shadow}`
              )}
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className={cn("text-[11px] md:text-xs font-semibold mb-1", card.labelColor)}>
                    {card.label}
                  </p>
                  <p className={cn("text-2xl md:text-3xl font-bold leading-none", card.textColor)}>
                    {card.value}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-1.5">{card.sub}</p>
                </div>
                <div className={cn(
                  "size-10 rounded-full flex items-center justify-center shrink-0",
                  `bg-gradient-to-br ${card.gradient}`,
                  `shadow-md ${card.shadow}`
                )}>
                  <Icon className="size-5 text-white" />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Quick Navigation */}
      <div>
        <h2 className="text-[13px] font-bold tracking-widest text-slate-400 uppercase mb-4">Truy cập nhanh</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {quickLinks.map((link) => {
            const Icon = link.icon;
            return (
              <a
                key={link.href}
                href={link.href}
                className={cn(
                  "group flex items-center gap-4 rounded-[16px] border border-black/[0.04] bg-white p-4",
                  "shadow-[0_1px_3px_rgba(0,0,0,0.06),0_4px_16px_rgba(0,0,0,0.04)]",
                  "transition-all duration-200 hover:-translate-y-0.5",
                  "hover:shadow-[0_4px_16px_rgba(99,102,241,0.12),0_12px_40px_rgba(0,0,0,0.08)]"
                )}
              >
                <div className={cn(
                  "size-10 shrink-0 rounded-full flex items-center justify-center",
                  `bg-gradient-to-br ${link.color}`,
                  `shadow-md ${link.shadow}`
                )}>
                  <Icon className="size-4 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[14px] font-bold text-slate-900 group-hover:text-indigo-600 transition-colors">
                    {link.label}
                  </p>
                  <p className="text-[12px] text-slate-500 truncate">{link.desc}</p>
                </div>
                <ArrowRight className="size-4 text-slate-300 shrink-0 transition-transform group-hover:translate-x-0.5 group-hover:text-indigo-400" />
              </a>
            );
          })}
        </div>
      </div>
    </div>
  );
}
