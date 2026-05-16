"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users, Cpu, Sparkles, Combine, ImageIcon,
  Search, Archive, Settings, RefreshCw,
  ShieldCheck, Activity, Server, Video,
  ArrowRight, TrendingUp, AlertTriangle,
} from "lucide-react";

import { getValidatedAuthSession } from "@/lib/auth-session";
import { getDefaultRouteForRole } from "@/store/auth";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

function fmt(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n || 0);
}

export default function DashboardPage() {
  const router = useRouter();
  const [session, setSession] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [activeTab, setActiveTab] = useState("overview");

  const loadHealth = useCallback(async () => {
    try {
      const data = await request.get("/api/v1/health");
      setHealth((data.data as any) || null);
    } catch { /* health may be unavailable */ }
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

  if (!session) return null;

  const totalAccounts = health?.accounts?.total ?? 0;
  const activeAccounts = health?.accounts?.active ?? 0;
  const limitedAccounts = (health?.accounts?.limited ?? 0) + (health?.accounts?.error ?? 0);
  const gemini = (health as any)?.gemini || {};
  const geminiInstances: any[] = gemini.instances || [];
  const customOnline = geminiInstances.filter((i: any) => i.status === "available" || i.status === "partial").length;
  const version = health?.version || "…";

  if (!mounted) {
    return (
      <div className="flex min-w-0 flex-col gap-6 animate-pulse px-1 sm:px-0">
        <div className="h-10 bg-white/60 rounded-xl w-48" />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 sm:gap-4">
          {[1,2,3,4].map(i => <div key={i} className="rounded-[14px] bg-white/60 h-20" />)}
        </div>
      </div>
    );
  }

  const TabButton = ({ value, label }: { value: string; label: string }) => (
    <button
      onClick={() => setActiveTab(value)}
      className={cn(
        "px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
        activeTab === value ? "bg-indigo-500 text-white shadow-sm" : "text-slate-500 hover:text-slate-700 hover:bg-slate-100"
      )}
    >
      {label}
    </button>
  );

  return (
    <div className="flex min-w-0 flex-col gap-6 px-1 sm:px-0">
      {/* ── Tabs row — 9router style ── */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1 w-full sm:w-auto">
          <TabButton value="overview" label="Tổng quan" />
          <TabButton value="instances" label="Instances" />
        </div>
        <button type="button" onClick={() => { setRefreshing(true); void loadHealth().finally(() => setTimeout(() => setRefreshing(false), 400)); }} disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60 w-full sm:w-auto justify-center">
          <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
          Làm mới
        </button>
      </div>

      {activeTab === "overview" && (
        <>
          {/* ── Overview Cards — 9router style (4 cards) ── */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 sm:gap-4">
            <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
              <span className="text-[11px] uppercase font-semibold text-slate-400">Tổng tài khoản</span>
              <span className="truncate text-2xl font-bold text-slate-900">{fmt(totalAccounts)}</span>
              <span className="text-[11px] text-emerald-600">{activeAccounts} hoạt động</span>
            </div>
            <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
              <span className="text-[11px] uppercase font-semibold text-slate-400">Giới hạn / Lỗi</span>
              <span className={cn("truncate text-2xl font-bold", limitedAccounts > 0 ? "text-amber-600" : "text-emerald-600")}>{limitedAccounts}</span>
              <span className="text-[11px] text-slate-400">{health?.model_cooldown?.cooling > 0 ? `${health.model_cooldown.cooling} cooling` : "không có"}</span>
            </div>
            <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
              <span className="text-[11px] uppercase font-semibold text-slate-400">API Endpoints</span>
              <span className="truncate text-2xl font-bold text-violet-600">{customOnline}/{geminiInstances.length}</span>
              <span className="text-[11px] text-slate-400">online / configured</span>
            </div>
            <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
              <span className="text-[11px] uppercase font-semibold text-slate-400">Hệ thống</span>
              <span className={cn("truncate text-2xl font-bold", gemini.gemini_api === "available" ? "text-emerald-600" : gemini.gemini_api === "partial" ? "text-amber-600" : "text-rose-500")}>
                {gemini.gemini_api === "available" ? "Online" : gemini.gemini_api === "partial" ? "Partial" : gemini.gemini_api ?? "—"}
              </span>
              <span className="text-[11px] text-slate-400">v{version} · Gemini {gemini.models_count ?? 0} models</span>
            </div>
          </div>

          {/* ── Sub-metrics + Status — 9router 2-col layout ── */}
          <div className="grid grid-cols-1 items-stretch gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
            {/* Provider instances grid */}
            <div className="rounded-[14px] card-main overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/50">
                <h3 className="text-[13px] font-semibold text-slate-700">Provider Instances</h3>
              </div>
              <div className="divide-y divide-slate-50">
                {geminiInstances.length > 0 ? geminiInstances.map((inst: any) => (
                  <div key={inst.id} className="flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50/40 transition-colors">
                    <div className={cn("size-2 rounded-full shrink-0",
                      inst.status === "available" ? "bg-emerald-500" :
                      inst.status === "partial" ? "bg-amber-500" :
                      inst.status === "offline" ? "bg-rose-500" : "bg-amber-400"
                    )} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-medium text-slate-700">{inst.name}</span>
                        {inst.prefix && <code className="text-[10px] text-slate-400">{inst.prefix}/</code>}
                      </div>
                      {inst.base_url && <div className="text-[10px] text-slate-400 truncate">{inst.base_url}</div>}
                    </div>
                    <span className={cn("text-[11px] font-medium",
                      inst.status === "available" ? "text-emerald-600" :
                      inst.status === "partial" ? "text-amber-600" : "text-rose-500"
                    )}>{inst.status}</span>
                    {inst.available_keys !== undefined && (
                      <span className="text-[10px] text-slate-400">{inst.available_keys}/{inst.total_keys}</span>
                    )}
                  </div>
                )) : (
                  <div className="flex items-center justify-center py-8 text-sm text-slate-400">Chưa có provider instance</div>
                )}
              </div>
            </div>

            {/* System status card */}
            <div className="rounded-[14px] card-main overflow-hidden" style={{ height: "fit-content" }}>
              <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/50">
                <h3 className="text-[13px] font-semibold text-slate-700">Trạng thái hệ thống</h3>
              </div>
              <div className="p-4 space-y-2.5">
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-slate-500">Backoff</span>
                  <span className="font-semibold text-slate-700">{health?.backoff?.total_locked_models ?? 0} locked / {health?.backoff?.total_accounts_tracked ?? 0} tracked</span>
                </div>
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-slate-500">Quota Watcher</span>
                  <span className={cn("font-semibold", health?.quota_watcher?.running ? "text-emerald-600" : "text-amber-600")}>{health?.quota_watcher?.running ? "Running" : "Off"} · {health?.quota_watcher?.heap_size ?? 0} q</span>
                </div>
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-slate-500">Cooldown</span>
                  <span className="font-semibold text-amber-600">{health?.model_cooldown?.cooling ?? 0} / {health?.model_cooldown?.total_tracked ?? 0}</span>
                </div>
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-slate-500">Gemini API</span>
                  <span className={cn("font-semibold", gemini.gemini_api === "available" ? "text-emerald-600" : "text-amber-600")}>{gemini.gemini_api ?? "—"} · {gemini.models_count ?? 0} models</span>
                </div>
              </div>
            </div>
          </div>

          {/* ── Account Distribution Table — 9router UsageTable style ── */}
          <div className="rounded-[14px] card-main overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/50">
              <h3 className="text-[13px] font-semibold text-slate-700">Phân bố tài khoản</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-50/30 text-[10px] uppercase font-semibold text-slate-400">
                  <tr>
                    <th className="px-5 py-2.5">Trạng thái</th>
                    <th className="px-5 py-2.5 text-right">Số lượng</th>
                    <th className="px-5 py-2.5 text-right">Tỉ lệ</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {[
                    { label: "Hoạt động", value: health?.accounts?.active ?? 0, color: "bg-emerald-500", total: totalAccounts },
                    { label: "Giới hạn", value: health?.accounts?.limited ?? 0, color: "bg-amber-500", total: totalAccounts },
                    { label: "Lỗi / Vô hiệu", value: health?.accounts?.error ?? 0, color: "bg-rose-500", total: totalAccounts },
                  ].map((row) => (
                    <tr key={row.label} className="hover:bg-slate-50/40 transition-colors">
                      <td className="px-5 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className={cn("size-2 rounded-full", row.color)} />
                          <span className="text-[13px] text-slate-700">{row.label}</span>
                        </div>
                      </td>
                      <td className="px-5 py-2.5 text-right font-semibold text-slate-900">{row.value}</td>
                      <td className="px-5 py-2.5 text-right text-slate-500">
                        {row.total > 0 ? Math.round((row.value / row.total) * 100) + "%" : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {activeTab === "instances" && (
        <div className="rounded-[14px] card-main overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/50">
            <h3 className="text-[13px] font-semibold text-slate-700">Tất cả Provider Instances</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-50/30 text-[10px] uppercase font-semibold text-slate-400">
                <tr>
                  <th className="px-5 py-2.5 w-8"></th>
                  <th className="px-5 py-2.5">Tên</th>
                  <th className="px-5 py-2.5">Prefix</th>
                  <th className="px-5 py-2.5">Port</th>
                  <th className="px-5 py-2.5 text-right">Keys</th>
                  <th className="px-5 py-2.5 text-right">Clients</th>
                  <th className="px-5 py-2.5 text-right">Entries</th>
                  <th className="px-5 py-2.5 text-right">Lỗi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {geminiInstances.map((inst: any) => (
                  <tr key={inst.id} className="hover:bg-slate-50/40 transition-colors">
                    <td className="px-5 py-2.5">
                      <span className={cn("block size-2 rounded-full",
                        inst.status === "available" ? "bg-emerald-500" :
                        inst.status === "partial" ? "bg-amber-500" : "bg-rose-500"
                      )} />
                    </td>
                    <td className="px-5 py-2.5 font-medium text-slate-700 text-[13px]">{inst.name}</td>
                    <td className="px-5 py-2.5"><code className="text-[11px] text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">{inst.prefix || "—"}</code></td>
                    <td className="px-5 py-2.5 text-slate-500 text-[12px]">{inst.port || "—"}</td>
                    <td className="px-5 py-2.5 text-right text-slate-600 text-[12px]">{inst.available_keys !== undefined ? `${inst.available_keys}/${inst.total_keys}` : "—"}</td>
                    <td className="px-5 py-2.5 text-right text-slate-600 text-[12px]">{inst.clients || "—"}</td>
                    <td className="px-5 py-2.5 text-right text-slate-600 text-[12px]">{inst.entries || "—"}</td>
                    <td className="px-5 py-2.5 text-right text-[11px] max-w-[180px] truncate">
                      {inst.error ? <span className="text-rose-500">{inst.error}</span> : <span className="text-slate-300">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Quick Access — always visible ── */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Tài khoản", desc: "Quản lý token & pool", href: "/accounts", icon: Users, color: "from-indigo-500 to-blue-600" },
          { label: "Providers", desc: "OpenCode, Gemini, Codex…", href: "/providers", icon: Cpu, color: "from-violet-500 to-purple-600" },
          { label: "Quản lý Model", desc: "Bật/tắt model", href: "/models", icon: Settings, color: "from-sky-500 to-cyan-600" },
          { label: "Mô hình kết hợp", desc: "Combo fallback", href: "/combos", icon: Combine, color: "from-emerald-500 to-teal-600" },
          { label: "Tạo ảnh", desc: "DALL-E, SD, FLUX…", href: "/image", icon: ImageIcon, color: "from-rose-500 to-pink-600" },
          { label: "Tạo video", desc: "Veo 3.1", href: "/video", icon: Video, color: "from-violet-500 to-purple-600" },
          { label: "Tìm kiếm", desc: "Gemini, Serper…", href: "/search", icon: Search, color: "from-amber-500 to-orange-600" },
          { label: "Sao lưu", desc: "Backup & restore", href: "/backup", icon: Archive, color: "from-slate-500 to-slate-600" },
        ].map((link) => {
          const Icon = link.icon;
          return (
            <a key={link.href} href={link.href} className="group flex items-center gap-3 rounded-[14px] px-4 py-3 transition-all hover:-translate-y-0.5 card-3d">
              <div className={cn("flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-gradient-to-br shadow-md transition-transform group-hover:scale-105", link.color)}>
                <Icon className="size-[16px] text-white" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-semibold text-slate-800 group-hover:text-indigo-600 transition-colors">{link.label}</p>
                <p className="text-[11px] text-slate-500 truncate">{link.desc}</p>
              </div>
              <ArrowRight className="size-3.5 text-slate-300 shrink-0 transition-all group-hover:translate-x-1 group-hover:text-indigo-400" />
            </a>
          );
        })}
      </div>
    </div>
  );
}
