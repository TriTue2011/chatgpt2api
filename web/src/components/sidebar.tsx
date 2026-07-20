"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  LayoutDashboard, Users, Cpu, Combine, ImageIcon, Search, Archive, Settings,
  LogOut, ChevronRight, Sparkles, PanelLeftClose,
  Video, Film, Plug, MessageSquare, MessageCircle, Activity,
} from "lucide-react";
import webConfig from "@/constants/common-env";
import { getValidatedAuthSession } from "@/lib/auth-session";
import { cn } from "@/lib/utils";
import { useLangStore } from "@/store/lang";
import { translations, TranslationKey } from "@/lib/i18n";
import { clearStoredAuthSession, type StoredAuthSession } from "@/store/auth";

type NavItem = { href: string; labelKey: TranslationKey; icon: typeof LayoutDashboard };
type NavGroup = { id: string; label: string; items: NavItem[] };

// Nav nhóm 5 mục: Tổng quan · AI Core · Studio · Kênh · Hệ thống (export cho
// mobile bottom-nav dùng chung data).
export const navGroups: NavGroup[] = [
  {
    id: "overview",
    label: "Tổng quan",
    items: [{ href: "/", labelKey: "nav_overview" as TranslationKey, icon: LayoutDashboard }],
  },
  {
    id: "core",
    label: "AI Core",
    items: [
      { href: "/accounts", labelKey: "nav_accounts" as TranslationKey, icon: Users },
      { href: "/providers", labelKey: "nav_providers" as TranslationKey, icon: Cpu },
      { href: "/models", labelKey: "nav_models" as TranslationKey, icon: Sparkles },
      { href: "/combos", labelKey: "nav_combos" as TranslationKey, icon: Combine },
      { href: "/mcp", labelKey: "nav_mcp" as TranslationKey, icon: Plug },
    ],
  },
  {
    id: "studio",
    label: "Studio",
    items: [
      { href: "/chat", labelKey: "nav_chat" as TranslationKey, icon: MessageSquare },
      { href: "/image", labelKey: "nav_image" as TranslationKey, icon: ImageIcon },
      { href: "/image-manager", labelKey: "nav_imageLibrary" as TranslationKey, icon: Archive },
      { href: "/video", labelKey: "nav_video" as TranslationKey, icon: Video },
      { href: "/video-manager", labelKey: "nav_videoLibrary" as TranslationKey, icon: Film },
    ],
  },
  {
    id: "channels",
    label: "Kênh",
    items: [
      { href: "/search", labelKey: "nav_search" as TranslationKey, icon: Search },
    ],
  },
  {
    id: "system",
    label: "Hệ thống",
    items: [
      { href: "/agent-runs", labelKey: "nav_agentRuns" as TranslationKey, icon: Activity },
      { href: "/backup", labelKey: "nav_backup" as TranslationKey, icon: Archive },
      { href: "/settings", labelKey: "nav_settings" as TranslationKey, icon: Settings },
    ],
  },
];

export const adminOnlyPaths = ["/accounts","/providers","/models","/combos","/mcp","/image-manager","/video-manager","/search","/backup","/settings","/agent-runs"];

type SidebarProps = {
  collapsed: boolean;
  onToggle: () => void;
  /** Mobile (<lg): true = drawer đang mở; đóng bằng onMobileClose (backdrop ở app-shell). */
  mobileOpen?: boolean;
  onMobileClose?: () => void;
};

export function Sidebar({ collapsed, onToggle, mobileOpen = false, onMobileClose }: SidebarProps) {
  const { lang } = useLangStore();
  const t = (key: TranslationKey) => translations[lang][key] || key;
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<StoredAuthSession | null | undefined>(undefined);

  useEffect(() => {
    let active = true;
    (async () => {
      if (pathname === "/login") { setSession(null); return; }
      const s = await getValidatedAuthSession();
      if (active) setSession(s);
    })();
    return () => { active = false; };
  }, [pathname]);

  const handleLogout = useCallback(async () => {
    await clearStoredAuthSession();
    router.replace("/login");
  }, [router]);

  if (pathname === "/login" || session === undefined || !session) return null;

  const isAdmin = session.role === "admin";
  const visibleGroups = navGroups
    .map((g) => ({
      ...g,
      items: isAdmin ? g.items : g.items.filter((i) => !adminOnlyPaths.includes(i.href)),
    }))
    .filter((g) => g.items.length > 0);

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-50 flex h-screen flex-col glass-strong text-[var(--sidebar-foreground)]",
        "transition-[width,transform] duration-200 ease-out !rounded-none border-r border-[var(--sidebar-border)] border-l-0 border-t-0 border-b-0",
        collapsed ? "lg:w-[68px]" : "lg:w-[250px]",
        // Mobile: drawer trượt từ trái, luôn full 250px; đóng = trượt khuất.
        "max-lg:w-[250px]",
        mobileOpen ? "max-lg:translate-x-0" : "max-lg:-translate-x-full",
      )}
      style={{ background: "var(--sidebar)" }}
      onClick={(e) => {
        // Mobile: bấm 1 link điều hướng xong thì tự đóng drawer.
        if (onMobileClose && (e.target as HTMLElement).closest("a")) onMobileClose();
      }}
    >
      {/* Logo */}
      <div className={cn("flex h-14 items-center border-b border-[var(--sidebar-border)] shrink-0", collapsed ? "justify-center px-2" : "px-4 gap-2.5")}>
        <Link href="/" className="flex items-center gap-2.5 no-underline shrink-0">
          <div
            className="flex size-9 items-center justify-center rounded-[12px] relative overflow-hidden"
            style={{
              background: "linear-gradient(135deg, var(--gold-main), var(--gold-dark))",
              boxShadow: "0 0 18px var(--gold-glow)",
              color: "var(--sidebar-primary-foreground)",
            }}
          >
            <Sparkles className="size-4 relative z-10" />
          </div>
          {!collapsed && (
            <span className="text-[14px] font-bold tracking-tight gradient-text">
              chatgpt2api
            </span>
          )}
        </Link>
        <button
          onClick={onToggle}
          className={cn(
            "rounded-md p-1 text-[var(--sidebar-foreground)]/50 hover:text-[var(--neon-cyan)] hover:bg-[var(--sidebar-accent)] transition",
            collapsed
              ? "absolute -right-2.5 top-3.5 bg-[var(--card)] border border-[var(--border)] rounded-full size-5 flex items-center justify-center"
              : "ml-auto",
          )}
        >
          {collapsed ? <ChevronRight className="size-3" /> : <PanelLeftClose className="size-3.5" />}
        </button>
      </div>

      {/* Nav — nhóm 5 mục, active gold */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-3">
        {visibleGroups.map((group) => (
          <div key={group.id} className="space-y-0.5">
            {!collapsed && (
              <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--sidebar-foreground)]/40">
                {group.label}
              </p>
            )}
            {group.items.map((item) => {
              const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "relative flex items-center rounded-[10px] transition-all duration-200 text-[13px]",
                    collapsed ? "justify-center py-2.5" : "gap-2.5 px-3 py-2",
                    active
                      ? "text-[var(--primary)] font-semibold"
                      : "text-[var(--sidebar-foreground)]/75 hover:text-[var(--sidebar-foreground)] font-normal hover:bg-[var(--sidebar-accent)]",
                  )}
                  style={
                    active
                      ? {
                          background:
                            "linear-gradient(90deg, color-mix(in srgb, var(--primary) 18%, transparent), color-mix(in srgb, var(--primary) 4%, transparent))",
                          boxShadow:
                            "inset 0 0 0 1px color-mix(in srgb, var(--primary) 28%, transparent)",
                        }
                      : undefined
                  }
                  title={collapsed ? t(item.labelKey) : undefined}
                >
                  {/* Active indicator bar — vàng kim */}
                  {active && (
                    <span
                      className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full"
                      style={{
                        background: "linear-gradient(180deg, var(--gold-bright), var(--gold-main))",
                        boxShadow: "0 0 12px var(--gold-glow)",
                      }}
                    />
                  )}
                  <Icon className={cn("size-[18px] shrink-0", active && "drop-shadow-[0_0_6px_var(--primary)]")} />
                  {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Footer — user info lives in the top header; keep only version + logout */}
      <div className="border-t border-[var(--sidebar-border)] p-3 shrink-0">
        {!collapsed && (
          <div className="mb-2 px-1 text-[10px] text-[var(--sidebar-foreground)]/45">
            {isAdmin ? "Admin" : "User"} · v{webConfig.appVersion}
          </div>
        )}
        <button
          onClick={handleLogout}
          className={cn(
            "flex items-center rounded-md text-[var(--sidebar-foreground)]/60 hover:text-red-400 hover:bg-red-400/10 transition-colors w-full text-xs",
            collapsed ? "justify-center py-2" : "gap-2 px-2 py-1.5",
          )}
        >
          <LogOut className="size-3.5 shrink-0" />
          {!collapsed && "Đăng xuất"}
        </button>
      </div>
    </aside>
  );
}
