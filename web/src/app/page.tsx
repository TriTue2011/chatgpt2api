"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users, Cpu, Sparkles, Combine, ImageIcon,
  Search, Archive, Settings, RefreshCw,
  ShieldCheck, Activity, Server, Video,
  ArrowRight,
} from "lucide-react";

import { getValidatedAuthSession } from "@/lib/auth-session";
import { getDefaultRouteForRole } from "@/store/auth";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

export default function DashboardPage() {
  const router = useRouter();
  const [session, setSession] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [mounted, setMounted] = useState(false);

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
  const geminiStatus = (health as any)?.gemini;
  const geminiInstances: any[] = geminiStatus?.instances || [];
  const customOnline = geminiInstances.filter((i: any) => i.status === "available").length;
  const version = health?.version || "…";

  if (!mounted) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 sm:gap-4">
          {[1,2,3,4].map(i => <div key={i} className="rounded-[14px] bg-white/60 h-20" />)}
        </div>
      </div>
    );
  }

  const refreshBtn = (
    <button type="button" onClick={() => { setRefreshing(true); void loadHealth().finally(() => setTimeout(() => setRefreshing(false), 400)); }} disabled={refreshing}
      className="inline-flex items-center gap-2 rounded-[12px] border border-slate-200 bg-white px-4 py-2.5 text-[13px] font-semibold text-slate-600 shadow-sm transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-60">
      <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
      Làm mới
    </button>
  );

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-[14px] bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/25">
            <Sparkles className="size-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Tổng quan</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Theo dõi tài khoản, providers &amp; API endpoints · v{version}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="hidden sm:flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
            <span className="relative flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
            </span>
            Hoạt động
          </div>
          {refreshBtn}
        </div>
      </div>

      {/* ── Overview Cards ── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 sm:gap-4">
        <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
          <span className="text-[11px] uppercase font-semibold text-slate-400">Tổng tài khoản</span>
          <span className="truncate text-2xl font-bold text-slate-900">{totalAccounts}</span>
          <span className="text-[11px] text-emerald-600">{activeAccounts} hoạt động</span>
        </div>
        <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
          <span className="text-[11px] uppercase font-semibold text-slate-400">Giới hạn / Lỗi</span>
          <span className={cn("truncate text-2xl font-bold", limitedAccounts > 0 ? "text-amber-600" : "text-emerald-600")}>{limitedAccounts}</span>
          <span className="text-[11px] text-slate-400">cần theo dõi</span>
        </div>
        <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
          <span className="text-[11px] uppercase font-semibold text-slate-400">API Endpoints</span>
          <span className="truncate text-2xl font-bold text-violet-600">{customOnline}/{geminiInstances.length}</span>
          <span className="text-[11px] text-slate-400">online / configured</span>
        </div>
        <div className="flex min-w-0 flex-col gap-1 rounded-[14px] card-3d px-4 py-3">
          <span className="text-[11px] uppercase font-semibold text-slate-400">Gemini API</span>
          <span className={cn("truncate text-2xl font-bold", geminiStatus?.gemini_api === "available" ? "text-emerald-600" : geminiStatus?.gemini_api === "partial" ? "text-amber-600" : "text-rose-500")}>
            {geminiStatus?.gemini_api === "available" ? "Online" : geminiStatus?.gemini_api === "partial" ? "Partial" : geminiStatus?.gemini_api ?? "—"}
          </span>
          <span className="text-[11px] text-slate-400">{geminiStatus?.models_count ?? 0} models</span>
        </div>
      </div>

      {/* ── System metrics + Provider Instances ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* System metrics card */}
        <div className="rounded-[14px] card-main p-5">
          <h3 className="text-[13px] font-semibold text-slate-700 mb-4">Hệ thống</h3>
          <div className="space-y-3">
            {[
              { label: "Backoff", locked: health?.backoff?.total_locked_models ?? 0, tracked: health?.backoff?.total_accounts_tracked ?? 0 },
              { label: "Quota Watcher", on: health?.quota_watcher?.running, queued: health?.quota_watcher?.heap_size ?? 0 },
              { label: "Cooldown", cooling: health?.model_cooldown?.cooling ?? 0, tracked: health?.model_cooldown?.total_tracked ?? 0 },
            ].map((m) => (
              <div key={m.label} className="flex items-center justify-between rounded-[10px] border border-slate-100 bg-white/60 px-4 py-2.5">
                <span className="text-[12px] font-medium text-slate-600">{m.label}</span>
                <div className="flex items-center gap-2 text-[12px]">
                  {m.on !== undefined ? (
                    <span className={cn("font-semibold", m.on ? "text-emerald-600" : "text-amber-600")}>{m.on ? "Running" : "Off"}</span>
                  ) : m.cooling !== undefined ? (
                    <><span className="font-semibold text-amber-600">{m.cooling}</span><span className="text-slate-400">/ {m.tracked}</span></>
                  ) : (
                    <><span className="font-semibold text-slate-700">{m.locked}</span><span className="text-slate-400">/ {m.tracked}</span></>
                  )}
                  {m.queued !== undefined && <span className="text-slate-400">· {m.queued} q</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Provider instances summary */}
        <div className="rounded-[14px] card-main p-5">
          <h3 className="text-[13px] font-semibold text-slate-700 mb-4">Provider Instances</h3>
          {geminiInstances.length > 0 ? (
            <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
              {geminiInstances.map((inst: any) => (
                <div key={inst.id} className="flex items-center gap-3 rounded-[10px] border border-slate-100 bg-white/60 px-4 py-2.5">
                  <div className={cn("size-2.5 rounded-full shrink-0", inst.status === "available" ? "bg-emerald-500" : inst.status === "partial" ? "bg-amber-500" : "bg-rose-500")} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-slate-700">{inst.name}</span>
                      {inst.prefix && <code className="text-[10px] text-slate-400">{inst.prefix}/</code>}
                    </div>
                    {inst.base_url && <div className="text-[10px] text-slate-400 truncate">{inst.base_url}</div>}
                  </div>
                  <span className={cn("text-[11px] font-medium", inst.status === "available" ? "text-emerald-600" : inst.status === "partial" ? "text-amber-600" : "text-rose-500")}>{inst.status}</span>
                  {inst.available_keys !== undefined && (
                    <span className="text-[10px] text-slate-400">{inst.available_keys}/{inst.total_keys} keys</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-[100px] text-sm text-slate-400">Chưa có provider instance nào</div>
          )}
        </div>
      </div>

      {/* ── Quick Access ── */}
      <section>
        <h2 className="text-[12px] font-semibold uppercase tracking-[0.15em] text-slate-400 mb-4">Truy cập nhanh</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
      </section>
    </div>
  );
}
