"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
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
  PanelLeftClose,
  PanelLeft,
  Video,
  Film,
} from "lucide-react";

import webConfig from "@/constants/common-env";
import { getValidatedAuthSession } from "@/lib/auth-session";
import { cn } from "@/lib/utils";
import { useLangStore } from "@/store/lang";
import { translations, TranslationKey } from "@/lib/i18n";
import { clearStoredAuthSession, type StoredAuthSession } from "@/store/auth";

const navItems = [
  { href: "/",              labelKey: "nav_overview"       as TranslationKey, icon: LayoutDashboard },
  { href: "/accounts",      labelKey: "nav_accounts"       as TranslationKey, icon: Users },
  { href: "/providers",     labelKey: "nav_providers"      as TranslationKey, icon: Cpu },
  { href: "/models",         labelKey: "nav_models"         as TranslationKey, icon: Sparkles },
  { href: "/combos",         labelKey: "nav_combos"         as TranslationKey, icon: Combine },
  { href: "/image",          labelKey: "nav_image"          as TranslationKey, icon: ImageIcon },
  { href: "/image-manager",  labelKey: "nav_imageLibrary"   as TranslationKey, icon: Archive },
  { href: "/video",          labelKey: "nav_video"          as TranslationKey, icon: Video },
  { href: "/video-manager",  labelKey: "nav_videoLibrary"   as TranslationKey, icon: Film },
  { href: "/search",         labelKey: "nav_search"         as TranslationKey, icon: Search },
  { href: "/backup",         labelKey: "nav_backup"         as TranslationKey, icon: Archive },
  { href: "/settings",       labelKey: "nav_settings"       as TranslationKey, icon: Settings },
];

const adminOnlyPaths = ["/accounts", "/providers", "/models", "/combos", "/image-manager", "/video-manager", "/search", "/backup", "/settings"];

type SidebarProps = {
  collapsed: boolean;
  onToggle: () => void;
};

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { lang } = useLangStore();
  const t = (key: TranslationKey) => translations[lang][key] || key;
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<StoredAuthSession | null | undefined>(undefined);

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

  const handleLogout = useCallback(async () => {
    await clearStoredAuthSession();
    router.replace("/login");
  }, [router]);

  if (pathname === "/login" || session === undefined || !session) return null;

  const isAdmin = session.role === "admin";
  const displayName = session.name.trim() || (isAdmin ? t("admin") : t("user"));
  const roleLabel = isAdmin ? t("admin") : t("user");
  const visibleItems = isAdmin
    ? navItems
    : navItems.filter((item) => !adminOnlyPaths.includes(item.href));

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-50 flex h-screen flex-col border-r border-white/[0.06] bg-[#0a0e14]",
        "transition-[width] duration-300 ease-in-out",
        collapsed ? "w-[68px]" : "w-64",
      )}
    >
      {/* ── Logo ── */}
      <div className={cn(
        "flex h-[60px] items-center border-b border-white/[0.06] px-4",
        collapsed ? "justify-center" : "gap-3"
      )}>
        {collapsed ? (
          <Link href="/" className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/30 transition hover:scale-105">
            <LayoutDashboard className="size-[18px] text-white" />
          </Link>
        ) : (
          <Link href="/" className="flex items-center gap-3 no-underline">
            <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/30">
              <LayoutDashboard className="size-[18px] text-white" />
            </div>
            <div className="flex flex-col leading-tight">
              <span className="text-[14px] font-extrabold tracking-tight text-[#f0f6fc]">
                chatgpt2api
              </span>
              <span className="text-[10px] font-medium text-[#6e7681] tracking-wide uppercase">
                {t("systemManagement")}
              </span>
            </div>
          </Link>
        )}
        <button
          type="button"
          onClick={onToggle}
          className={cn(
            "rounded-lg p-1.5 text-[#6e7681] transition-all duration-200 hover:bg-white/[0.06] hover:text-[#f0f6fc]",
            collapsed ? "absolute -right-3 top-4 z-10 bg-[#0a0e14] border border-white/[0.08] rounded-full shadow-md" : "ml-auto"
          )}
        >
          {collapsed
            ? <PanelLeft className="size-[14px]" />
            : <PanelLeftClose className="size-[15px]" />
          }
        </button>
      </div>

      {/* ── Navigation ── */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3 scrollbar-none">
        {visibleItems.map((item) => {
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "relative flex items-center rounded-xl transition-all duration-200",
                collapsed ? "justify-center px-0 py-3" : "gap-3 px-3 py-2.5",
                active
                  ? "bg-gradient-to-r from-indigo-500/[0.12] to-violet-500/[0.06] text-indigo-300 shadow-[inset_0_0_0_1px_rgba(99,102,241,0.15)]"
                  : "text-[#6e7681] hover:bg-white/[0.04] hover:text-[#e6edf3] hover:translate-x-0.5",
                "text-[13.5px] font-medium",
              )}
              title={collapsed ? t(item.labelKey) : undefined}
            >
              {/* Active glow bar */}
              {active && !collapsed && (
                <div className="absolute left-0 top-1/2 h-[55%] w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-indigo-400 to-violet-500 shadow-[0_0_8px_rgba(99,102,241,0.5)]" />
              )}
              <div className={cn(
                "flex size-[30px] shrink-0 items-center justify-center rounded-[10px] transition-all duration-200",
                active ? "bg-indigo-500/[0.15] text-indigo-400" : "",
              )}>
                <Icon className={cn(
                  "size-[17px] shrink-0 transition-colors",
                  active ? "text-indigo-400" : "text-[#6e7681] group-hover:text-[#e6edf3]",
                )} />
              </div>
              {!collapsed && (
                <span className="truncate">{t(item.labelKey)}</span>
              )}
              {/* Active dot indicator when collapsed */}
              {active && collapsed && (
                <span className="absolute right-1.5 top-1/2 size-1.5 -translate-y-1/2 rounded-full bg-indigo-400 shadow-[0_0_6px_rgba(99,102,241,0.6)]" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* ── Footer: user + version + logout ── */}
      <div className="border-t border-white/[0.06] p-3 space-y-2">
        {!collapsed && (
          <div className="flex items-center gap-3 rounded-xl p-2 transition-colors hover:bg-white/[0.04]">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-[14px] font-bold text-white shadow-md shadow-indigo-500/20">
              {displayName.charAt(0).toUpperCase()}
            </div>
            <div className="flex flex-col overflow-hidden">
              <span className="truncate text-[13px] font-semibold text-[#f0f6fc]">
                {displayName}
              </span>
              <span className="truncate text-[11px] text-[#6e7681]">
                {roleLabel} · v{webConfig.appVersion}
              </span>
            </div>
          </div>
        )}
        {collapsed && (
          <div className="flex justify-center">
            <div className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-xs font-bold text-white shadow-md">
              {displayName.charAt(0).toUpperCase()}
            </div>
          </div>
        )}
        <button
          type="button"
          onClick={() => void handleLogout()}
          className={cn(
            "flex items-center rounded-lg text-[13px] font-medium transition-all duration-200",
            collapsed
              ? "justify-center w-full py-2 text-[#6e7681] hover:text-rose-400 hover:bg-white/[0.04]"
              : "w-full gap-2.5 px-3 py-2 text-[#6e7681] hover:text-rose-400 hover:bg-rose-500/[0.06]",
          )}
          title={t("logout")}
        >
          <LogOut className="size-[17px] shrink-0" />
          {!collapsed && t("logout")}
        </button>
      </div>
    </aside>
  );
}
