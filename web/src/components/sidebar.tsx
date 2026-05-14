"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Users,
  Cpu,
  Combine,
  ImageIcon,
  Search,
  Archive,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from "lucide-react";

import webConfig from "@/constants/common-env";
import { getValidatedAuthSession } from "@/lib/auth-session";
import { cn } from "@/lib/utils";
import { clearStoredAuthSession, type StoredAuthSession } from "@/store/auth";

// ── Vietnamese nav items ──
const navItems = [
  { href: "/", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/accounts", label: "Tài khoản", icon: Users },
  { href: "/providers", label: "Nhà cung cấp", icon: Cpu },
  { href: "/models", label: "Quản lý Model", icon: Sparkles },
  { href: "/combos", label: "Mô hình kết hợp", icon: Combine },
  { href: "/image", label: "Vẽ ảnh", icon: ImageIcon },
  { href: "/image-manager", label: "Thư viện ảnh", icon: Archive },
  { href: "/search", label: "Tìm kiếm", icon: Search },
  { href: "/backup", label: "Sao lưu", icon: Archive },
  { href: "/settings", label: "Cài đặt", icon: Settings },
];

const adminOnlyPaths = ["/accounts", "/providers", "/models", "/combos", "/image-manager", "/search", "/backup", "/settings"];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<StoredAuthSession | null | undefined>(undefined);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = async () => {
      if (pathname === "/login") {
        if (!active) return;
        setSession(null);
        return;
      }
      const storedSession = await getValidatedAuthSession();
      if (!active) return;
      setSession(storedSession);
    };
    void load();
    return () => { active = false; };
  }, [pathname]);

  const handleLogout = async () => {
    await clearStoredAuthSession();
    router.replace("/login");
  };

  if (pathname === "/login" || session === undefined || !session) return null;

  const isAdmin = session.role === "admin";
  const displayName = session.name.trim() || (isAdmin ? "Quản trị viên" : "Người dùng");
  const roleLabel = isAdmin ? "Quản trị viên" : "Người dùng";

  const visibleItems = isAdmin
    ? navItems
    : navItems.filter((item) => !adminOnlyPaths.includes(item.href));

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-white/5 bg-[#0d1117] transition-all duration-200",
        collapsed ? "w-16" : "w-64",
      )}
    >
      {/* Logo */}
      <div className="flex h-[60px] items-center gap-3 border-b border-white/5 px-4">
        {!collapsed && (
          <Link href="/" className="flex items-center gap-3 no-underline">
            <div className="flex size-9 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-[0_4px_16px_rgba(99,102,241,0.4)]">
              <LayoutDashboard className="size-5" />
            </div>
            <div className="flex flex-col">
              <span className="text-[14px] font-bold tracking-tight text-[#f0f6fc] leading-tight">
                chatgpt2api
              </span>
              <span className="text-[11px] text-[#8b949e]">
                Quản lý hệ thống
              </span>
            </div>
          </Link>
        )}
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className={cn(
            "rounded-md p-1.5 text-[#8b949e] transition hover:bg-white/5 hover:text-white",
            collapsed ? "mx-auto" : "ml-auto"
          )}
        >
          {collapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
        </button>
      </div>

      {/* Nav Items */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
        {visibleItems.map((item) => {
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "relative flex items-center gap-3 rounded-md px-3 py-2.5 text-[13.5px] font-medium transition-all duration-200",
                active
                  ? "bg-gradient-to-br from-indigo-500/20 to-violet-500/10 text-indigo-300 border border-indigo-500/20"
                  : "text-[#8b949e] hover:bg-white/5 hover:text-[#f0f6fc]"
              )}
              title={collapsed ? item.label : undefined}
            >
              {active && (
                <div className="absolute left-0 top-1/2 h-[60%] w-[3px] -translate-y-1/2 rounded-r-[3px] bg-gradient-to-br from-indigo-500 to-violet-500" />
              )}
              <Icon className={cn("size-[18px] shrink-0", active && "text-indigo-400")} />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Bottom: user + version + logout */}
      <div className="border-t border-white/5 p-3">
        {!collapsed && (
          <div className="mb-3 flex items-center gap-3 rounded-lg p-2 transition hover:bg-white/5 cursor-pointer">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 text-[14px] font-bold text-white">
              {displayName.charAt(0).toUpperCase()}
            </div>
            <div className="flex flex-col overflow-hidden">
              <span className="truncate text-[13px] font-semibold text-[#f0f6fc]">
                {displayName}
              </span>
              <span className="truncate text-[11px] text-[#8b949e]">
                {roleLabel} · v{webConfig.appVersion}
              </span>
            </div>
          </div>
        )}
        <button
          type="button"
          onClick={() => void handleLogout()}
          className={cn(
            "flex items-center gap-2 rounded-md text-[13px] font-medium text-[#8b949e] transition hover:bg-white/5 hover:text-[#f0f6fc]",
            collapsed ? "justify-center w-full py-2.5" : "w-full px-3 py-2"
          )}
          title="Đăng xuất"
        >
          <LogOut className="size-[18px]" />
          {!collapsed && "Đăng xuất"}
        </button>
      </div>
    </aside>
  );
}
