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
        "fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-stone-200 bg-white/90 backdrop-blur-xl transition-all duration-200",
        collapsed ? "w-16" : "w-56",
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-stone-200 px-3">
        {!collapsed && (
          <Link href="/" className="text-[15px] font-bold tracking-tight text-stone-900">
            chatgpt2api
          </Link>
        )}
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className="ml-auto rounded-md p-1 text-stone-500 hover:bg-stone-200 hover:text-stone-800"
        >
          {collapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
        </button>
      </div>

      {/* Nav Items */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
        {visibleItems.map((item) => {
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-stone-100 text-stone-900"
                  : "text-stone-500 hover:bg-stone-100/50 hover:text-stone-800",
              )}
              title={collapsed ? item.label : undefined}
            >
              <Icon className="size-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Bottom: user + version + logout */}
      <div className="border-t border-stone-200 px-3 py-3">
        {!collapsed && (
          <div className="mb-2 space-y-0.5">
            <p className="text-xs font-medium text-stone-700 truncate">{displayName}</p>
            <p className="text-[10px] text-stone-500">{roleLabel} · v{webConfig.appVersion}</p>
          </div>
        )}
        <button
          type="button"
          onClick={() => void handleLogout()}
          className={cn(
            "flex items-center gap-2 rounded-md text-xs text-stone-500 transition hover:text-stone-700",
            collapsed ? "justify-center w-full py-1" : "w-full",
          )}
          title="Đăng xuất"
        >
          <LogOut className="size-3.5" />
          {!collapsed && "Đăng xuất"}
        </button>
      </div>
    </aside>
  );
}
