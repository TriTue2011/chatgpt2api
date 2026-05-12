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
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Bảng điều khiển</h1>
        <p className="mt-1 text-sm text-stone-400">
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
              className="rounded-xl border border-stone-800 bg-stone-900/50 p-5"
            >
              <div className="mb-3 flex items-center gap-2">
                <div className={cn("rounded-lg p-2", card.bg)}>
                  <Icon className={cn("size-4", card.color)} />
                </div>
                <span className="text-xs text-stone-400">{card.label}</span>
              </div>
              <p className={cn("text-2xl font-bold", card.color)}>{card.value}</p>
              <p className="mt-1 text-xs text-stone-400">{card.sub}</p>
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
            className="rounded-xl border border-stone-800 bg-stone-900/50 p-4 transition hover:border-stone-600 hover:bg-stone-900"
          >
            <p className="text-sm font-medium text-white">{link.label}</p>
            <p className="mt-1 text-xs text-stone-400">{link.desc}</p>
          </a>
        ))}
      </div>
    </div>
  );
}
