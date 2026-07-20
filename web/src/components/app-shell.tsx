"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Sidebar, navGroups, adminOnlyPaths } from "@/components/sidebar";
import { StatusPill, type StatusKind } from "@/components/status-pill";
import { Sun, Moon, Sparkles, Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import { getValidatedAuthSession } from "@/lib/auth-session";
import { clearStoredAuthSession, type StoredAuthSession } from "@/store/auth";
import { useRouter } from "next/navigation";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

const pageTitles: Record<string, string> = {
  "/": "Dashboard",
  "/accounts": "Quản lý tài khoản",
  "/providers": "Nhà cung cấp AI",
  "/models": "Models",
  "/combos": "Combos",
  "/mcp": "MCP Servers",
  "/chat": "Chat",
  "/image": "Vẽ ảnh",
  "/image-manager": "Quản lý ảnh",
  "/video": "Video",
  "/video-manager": "Quản lý video",
  "/search": "Tìm kiếm",
  "/zalo": "Zalo Cá Nhân",
  "/backup": "Sao lưu",
  "/settings": "Cài đặt",
  "/logs": "Nhật ký",
  "/agent-runs": "Agent runs",
};

// 5 mục "hot" cho bottom-nav mobile (lấy từ navGroups để icon/label nhất quán).
const MOBILE_NAV_HREFS = ["/", "/chat", "/image", "/zalo", "/settings"];

type HealthShape = {
  accounts?: { total?: number; active?: number; limited?: number; error?: number };
  provider_circuits?: { open_count?: number };
  quota_watcher?: { enabled?: boolean };
};

// Quy trạng thái /api/v1/health về 1 pill: scan 1 giây là biết hệ khỏe hay không.
function healthToPill(h: HealthShape | null): { status: StatusKind; label: string } | null {
  if (!h) return null;
  const acc = h.accounts || {};
  const errors = acc.error ?? 0;
  const limited = acc.limited ?? 0;
  const circuitsOpen = h.provider_circuits?.open_count ?? 0;
  if (errors > 0) return { status: "error", label: `${errors} account lỗi` };
  if ((acc.total ?? 0) > 0 && (acc.active ?? 0) === 0)
    return { status: "error", label: "Không còn account hoạt động" };
  if (circuitsOpen > 0) return { status: "warning", label: `${circuitsOpen} provider đang ngắt mạch` };
  if (limited > 0) return { status: "warning", label: `Đang bị rate-limit (${limited})` };
  if (h.quota_watcher && h.quota_watcher.enabled === false)
    return { status: "warning", label: "Quota watcher tắt" };
  return { status: "ok", label: "Hệ thống OK" };
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(true);
  const [brand, setBrand] = useState("obsidian");
  const [session, setSession] = useState<StoredAuthSession | null | undefined>(undefined);
  const [health, setHealth] = useState<HealthShape | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    // 2026 default: dark unless explicitly light
    const useDark = stored !== "light";
    setDarkMode(useDark);
    document.documentElement.classList.toggle("dark", useDark);
    // Theme thương hiệu (độc lập sáng/tối): obsidian (mặc định) | linear | supabase.
    const storedBrand = localStorage.getItem("brand") || "obsidian";
    setBrand(storedBrand);
    if (storedBrand !== "obsidian")
      document.documentElement.setAttribute("data-brand", storedBrand);
    getValidatedAuthSession().then(s => setSession(s));
  }, []);

  // Đổi trang trên mobile → đóng drawer.
  useEffect(() => { setMobileNavOpen(false); }, [pathname]);

  // Health pill (admin): nạp 1 lần + refresh 60s; lỗi fetch → ẩn pill.
  useEffect(() => {
    if (!session || session.role !== "admin" || pathname === "/login") return;
    let active = true;
    const load = () =>
      request.get("/api/v1/health")
        .then((r) => { if (active) setHealth(r.data as HealthShape); })
        .catch(() => { if (active) setHealth(null); });
    void load();
    const iv = setInterval(load, 60_000);
    return () => { active = false; clearInterval(iv); };
  }, [session, pathname]);

  const toggleDarkMode = () => {
    setDarkMode(prev => {
      const next = !prev;
      document.documentElement.classList.toggle("dark", next);
      localStorage.setItem("theme", next ? "dark" : "light");
      return next;
    });
  };

  const changeBrand = (next: string) => {
    setBrand(next);
    localStorage.setItem("brand", next);
    if (next === "obsidian") document.documentElement.removeAttribute("data-brand");
    else document.documentElement.setAttribute("data-brand", next);
  };

  const handleLogout = async () => {
    await clearStoredAuthSession();
    router.replace("/login");
  };

  const pageTitle = pageTitles[pathname] || "chatgpt2api";
  const displayName = session?.name?.trim() || "Admin";
  const pill = healthToPill(health);

  if (pathname === "/login") return <>{children}</>;

  const isAdmin = session?.role === "admin";
  const mobileItems = navGroups
    .flatMap((g) => g.items)
    .filter((i) => MOBILE_NAV_HREFS.includes(i.href))
    .filter((i) => isAdmin || !adminOnlyPaths.includes(i.href));

  return (
    <div className="flex min-h-screen bg-[var(--background)] overflow-x-hidden">
      {/* Sidebar (desktop cố định; mobile = drawer) */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        mobileOpen={mobileNavOpen}
        onMobileClose={() => setMobileNavOpen(false)}
      />
      {/* Backdrop cho drawer mobile */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      {/* Main area */}
      <div
        className={cn(
          "flex-1 flex flex-col min-h-screen min-w-0 transition-[margin-left] duration-200 ease-out",
          sidebarCollapsed ? "lg:ml-[68px]" : "lg:ml-[250px]",
        )}
      >
        {/* Glass top header — viền dưới gold */}
        <header
          className="glass-strong sticky top-0 z-30 h-14 flex items-center justify-between px-4 sm:px-6 !rounded-none"
          style={{ borderBottom: "1px solid color-mix(in srgb, var(--primary) 18%, transparent)" }}
        >
          <div className="flex items-center gap-3 min-w-0">
            {/* Hamburger — chỉ mobile */}
            <button
              onClick={() => setMobileNavOpen(true)}
              className="lg:hidden size-9 inline-flex items-center justify-center rounded-[10px] hover:bg-[var(--secondary)] transition-colors"
              title="Menu"
            >
              <Menu className="size-4" />
            </button>
            <Sparkles
              className="size-4 text-[var(--primary)] shrink-0"
              style={{ filter: "drop-shadow(0 0 6px var(--gold-glow))" }}
            />
            <h1 className="text-[15px] font-semibold tracking-tight gradient-text truncate">
              {pageTitle}
            </h1>
            {pill && <StatusPill status={pill.status} label={pill.label} className="hidden sm:inline-flex" />}
          </div>
          <div className="flex items-center gap-2">
            {/* Bộ chọn THEME thương hiệu (độc lập với sáng/tối) */}
            <select
              value={brand}
              onChange={(e) => changeBrand(e.target.value)}
              title="Chọn theme"
              className="h-9 rounded-[10px] border border-[var(--border)] bg-transparent px-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--secondary)] transition-colors cursor-pointer outline-none"
            >
              <option value="obsidian">🏆 Obsidian Gold</option>
              <option value="linear">🔮 Linear Violet</option>
              <option value="supabase">🌿 Supabase Emerald</option>
            </select>
            <button
              onClick={toggleDarkMode}
              className="size-9 inline-flex items-center justify-center rounded-[10px] hover:bg-[var(--secondary)] transition-colors"
              title="Toggle theme"
            >
              {darkMode ? (
                <Sun className="size-4 text-[var(--neon-amber)]" />
              ) : (
                <Moon className="size-4 text-[var(--muted-foreground)]" />
              )}
            </button>
            <div className="flex items-center gap-2 pl-2 ml-1 border-l border-[var(--border)]/50">
              <div
                className="size-8 rounded-full flex items-center justify-center text-[11px] font-bold"
                style={{
                  background: "linear-gradient(135deg, var(--gold-main), var(--gold-dark))",
                  color: "var(--sidebar-primary-foreground)",
                  boxShadow: "0 0 12px var(--gold-glow)",
                }}
              >
                {displayName.charAt(0).toUpperCase()}
              </div>
              <div className="hidden sm:block">
                <div className="text-[13px] font-medium text-[var(--foreground)] leading-tight">
                  {displayName}
                </div>
              </div>
              <button
                onClick={handleLogout}
                className="text-[11px] text-[var(--muted-foreground)] hover:text-[var(--destructive)] ml-1 transition-colors"
              >
                Logout
              </button>
            </div>
          </div>
        </header>

        {/* Page content — chừa chỗ cho bottom-nav trên mobile */}
        <main className="flex-1 min-w-0 p-4 sm:p-6 pb-20 lg:pb-6">{children}</main>
      </div>

      {/* Bottom nav — mobile only, 5 mục hot, active gold */}
      {session && (
        <nav
          className="fixed bottom-0 inset-x-0 z-40 flex items-stretch justify-around lg:hidden glass-strong !rounded-none"
          style={{ borderTop: "1px solid color-mix(in srgb, var(--primary) 18%, transparent)" }}
        >
          {mobileItems.map((item) => {
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition-colors",
                  active ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]",
                )}
              >
                <Icon className={cn("size-5", active && "drop-shadow-[0_0_6px_var(--primary)]")} />
                {pageTitles[item.href] || item.href}
              </Link>
            );
          })}
        </nav>
      )}
    </div>
  );
}
