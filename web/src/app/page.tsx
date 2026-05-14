"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LayoutDashboard, Users, ImageIcon, Cpu, Activity } from "lucide-react";

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

  useEffect(() => {
    let active = true;
    const init = async () => {
      const sess = await getValidatedAuthSession();
      if (!active) return;
      if (!sess) {
        router.replace("/login");
        return;
      }
      setSession(sess);
      try {
        const data = await request.get("/api/v1/health");
        if (active) setHealth((data.data as any) || null);
      } catch {
        // Health endpoint may not be available
      }
    };
    void init();
    return () => { active = false; };
  }, [router]);

  if (!session) return null;

  const cards = [
    {
      label: "Tài khoản hoạt động",
      value: health?.accounts?.active ?? "-",
      sub: `/ ${health?.accounts?.total ?? "-"} tổng`,
      icon: Users,
      color: "text-emerald-400",
      bg: "bg-emerald-500/10",
    },
    {
      label: "Tài khoản bị giới hạn",
      value: health?.accounts?.limited ?? "-",
      sub: `${health?.accounts?.error ?? "-"} lỗi`,
      icon: Activity,
      color: "text-amber-400",
      bg: "bg-amber-500/10",
    },
    {
      label: "OpenCode",
      value: health?.opencode?.available ? "Sẵn sàng" : "Không khả dụng",
      sub: "Miễn phí, không giới hạn",
      icon: Cpu,
      color: health?.opencode?.available ? "text-emerald-400" : "text-red-400",
      bg: health?.opencode?.available ? "bg-emerald-500/10" : "bg-red-500/10",
    },
    {
      label: "Model đang khóa",
      value: health?.backoff?.total_locked_models ?? "-",
      sub: `${health?.backoff?.total_accounts_tracked ?? "-"} tài khoản được theo dõi`,
      icon: LayoutDashboard,
      color: "text-blue-400",
      bg: "bg-blue-500/10",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1 border-b border-black/[0.04] pb-5">
        <h1 className="text-[24px] font-bold tracking-tight text-slate-900">Bảng điều khiển</h1>
        <p className="text-[14px] text-slate-500">
          Tổng quan hệ thống chatgpt2api v{health?.version || "..."}
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className={cn(
                "group relative overflow-hidden rounded-[16px] border border-black/[0.04] bg-white p-5 md:p-6",
                "shadow-[0_1px_3px_rgba(0,0,0,0.06),0_4px_16px_rgba(0,0,0,0.04)]",
                "transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_4px_12px_rgba(99,102,241,0.14),0_12px_40px_rgba(0,0,0,0.08)]"
              )}
            >
              {/* Top gradient line */}
              <div className="absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r from-indigo-500 to-violet-500 opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
              
              <div className="mb-4 flex items-center justify-between">
                <span className="text-[13px] font-semibold text-slate-500">{card.label}</span>
                <div className={cn("flex size-10 items-center justify-center rounded-[12px]", card.bg)}>
                  <Icon className={cn("size-[22px]", card.color)} />
                </div>
              </div>
              <p className="text-[28px] font-bold tracking-tight text-slate-900 leading-none">{card.value}</p>
              <p className="mt-2 flex items-center gap-1.5 text-[12px] font-medium text-slate-500">
                {card.sub}
              </p>
            </div>
          );
        })}
      </div>

      {/* Quick Links */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[
          { label: "Vẽ ảnh", desc: "Tạo ảnh với DALL-E hoặc SD WebUI", href: "/image" },
          { label: "Nhà cung cấp", desc: "Quản lý OpenCode, Gemini, SD WebUI...", href: "/providers" },
          { label: "Mô hình kết hợp", desc: "Combo model với fallback tự động", href: "/combos" },
          { label: "Tìm kiếm", desc: "Cấu hình ChatGPT/Gemini/Serper/SearXNG", href: "/search" },
          { label: "Sao lưu", desc: "Sao lưu & phục hồi toàn bộ hệ thống", href: "/backup" },
          { label: "Cài đặt", desc: "Cấu hình proxy, rate limit, token refresh...", href: "/settings" },
        ].map((link) => (
          <a
            key={link.href}
            href={link.href}
            className={cn(
              "group relative overflow-hidden rounded-[16px] border border-black/[0.04] bg-white p-5",
              "shadow-[0_1px_3px_rgba(0,0,0,0.06),0_4px_16px_rgba(0,0,0,0.04)]",
              "transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_4px_12px_rgba(99,102,241,0.14),0_12px_40px_rgba(0,0,0,0.08)]",
              "hover:border-indigo-500/20"
            )}
          >
            <div className="flex flex-col h-full justify-center">
              <p className="text-[15px] font-bold text-slate-900 group-hover:text-indigo-600 transition-colors">
                {link.label}
              </p>
              <p className="mt-1.5 text-[13px] text-slate-500">{link.desc}</p>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
