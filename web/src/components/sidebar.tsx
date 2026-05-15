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
import { useLangStore } from "@/store/lang";
import { translations, TranslationKey } from "@/lib/i18n";
import { clearStoredAuthSession, type StoredAuthSession } from "@/store/auth";

// ── Vietnamese nav items ──
const navItems = [
  { href: "/", labelKey: "nav_overview" as TranslationKey, icon: LayoutDashboard },
  { href: "/accounts", labelKey: "nav_accounts" as TranslationKey, icon: Users },
  { href: "/providers", labelKey: "nav_providers" as TranslationKey, icon: Cpu },
  { href: "/models", labelKey: "nav_models" as TranslationKey, icon: Sparkles },
  { href: "/combos", labelKey: "nav_combos" as TranslationKey, icon: Combine },
  { href: "/image", labelKey: "nav_image" as TranslationKey, icon: ImageIcon },
  { href: "/image-manager", labelKey: "nav_imageLibrary" as TranslationKey, icon: Archive },
  { href: "/search", labelKey: "nav_search" as TranslationKey, icon: Search },
  { href: "/backup", labelKey: "nav_backup" as TranslationKey, icon: Archive },
  { href: "/settings", labelKey: "nav_settings" as TranslationKey, icon: Settings },
];

const adminOnlyPaths = ["/accounts", "/providers", "/models", "/combos", "/image-manager", "/search", "/backup", "/settings"];

export function Sidebar() {
  const { lang } = useLangStore();
  const t = (key: TranslationKey) => translations[lang][key] || key;
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
  const displayName = session.name.trim() || (isAdmin ? t("admin") : t("user"));
  const roleLabel = isAdmin ? t("admin") : t("user");

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
                {t("systemManagement")}
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

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
        {visibleItems.map((item) => {
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] font-medium transition-all duration-200",
                active
                  ? "bg-gradient-to-r from-indigo-500/20 to-violet-500/10 text-indigo-300 shadow-[inset_0_0_0_1px_rgba(99,102,241,0.2)]"
                  : "text-[#8b949e] hover:bg-white/5 hover:text-[#f0f6fc] hover:translate-x-0.5"
              )}
              title={collapsed ? t(item.labelKey) : undefined}
            >
              {active && (
                <div className="absolute left-0 top-1/2 h-[55%] w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-indigo-400 to-violet-500" />
              )}
              <div className={cn(
                "flex size-[30px] shrink-0 items-center justify-center rounded-[10px] transition-all duration-200",
                active ? "bg-indigo-500/20" : "group-hover:bg-white/5"
              )}>
                <Icon className={cn("size-[17px] shrink-0", active ? "text-indigo-400" : "text-[#8b949e]")} />
              </div>
              {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
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
          title={t("logout")}
        >
          <LogOut className="size-[18px]" />
          {!collapsed && t("logout")}
        </button>
      </div>
    </aside>
  );
}
