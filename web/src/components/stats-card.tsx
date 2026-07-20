"use client";

import type { LucideIcon } from "lucide-react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

type StatsTone = "gold" | "blue" | "emerald" | "red" | "violet" | "amber";

const toneMap: Record<StatsTone, { iconBg: string; glow: string; accent: string; text: string }> = {
  gold:    { iconBg: "linear-gradient(135deg,var(--gold-main),var(--gold-dark))", glow: "var(--gold-glow)", accent: "color-mix(in srgb, var(--gold-main) 10%, transparent)", text: "var(--gold-main)" },
  blue:    { iconBg: "linear-gradient(135deg,#38bdf8,#0284c7)", glow: "rgba(56,189,248,0.28)", accent: "rgba(56,189,248,0.10)", text: "#38bdf8" },
  emerald: { iconBg: "linear-gradient(135deg,#34d399,#059669)", glow: "rgba(52,211,153,0.28)", accent: "rgba(52,211,153,0.10)", text: "#34d399" },
  red:     { iconBg: "linear-gradient(135deg,#f87171,#dc2626)", glow: "rgba(248,113,113,0.28)", accent: "rgba(248,113,113,0.10)", text: "#f87171" },
  violet:  { iconBg: "linear-gradient(135deg,#a78bfa,#7c3aed)", glow: "rgba(167,139,250,0.28)", accent: "rgba(167,139,250,0.10)", text: "#a78bfa" },
  amber:   { iconBg: "linear-gradient(135deg,#fbbf24,#d97706)", glow: "rgba(251,191,36,0.28)",  accent: "rgba(251,191,36,0.10)",  text: "#fbbf24" },
};

export function StatsCard({
  title, value, icon: Icon, tone = "gold", sub, trend, trendLabel, loading, className,
}: {
  title: string;
  value: string | number;
  icon: LucideIcon;
  tone?: StatsTone;
  sub?: string;
  trend?: number;
  trendLabel?: string;
  loading?: boolean;
  className?: string;
}) {
  const c = toneMap[tone];
  if (loading) {
    return (
      <div className={cn("bento-cell animate-pulse min-h-[108px] p-4", className)}>
        <div className="skeleton h-2.5 w-[55%] mb-3" />
        <div className="skeleton h-8 w-[40%] mb-2" />
        <div className="skeleton h-2 w-[45%]" />
      </div>
    );
  }
  return (
    <div
      className={cn("bento-cell relative overflow-hidden min-h-[108px] p-4", className)}
      onMouseEnter={(e) => { e.currentTarget.style.boxShadow = `0 12px 28px ${c.glow}`; }}
      onMouseLeave={(e) => { e.currentTarget.style.boxShadow = ""; }}
    >
      <div className="pointer-events-none absolute -right-4 -top-4 size-20 rounded-full blur-2xl" style={{ background: c.accent }} />
      <div
        className="absolute right-3.5 top-3.5 flex size-9 items-center justify-center rounded-[11px] text-white"
        style={{ background: c.iconBg, boxShadow: `0 6px 16px ${c.glow}` }}
      >
        <Icon className="size-[18px]" />
      </div>
      <p className="pr-12 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--muted-foreground)]">{title}</p>
      <p className="mt-1.5 text-[28px] font-extrabold leading-none tabular-nums text-[var(--foreground)]">{value}</p>
      {(sub || trend !== undefined) && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          {trend !== undefined && (
            <span
              className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-bold"
              style={{
                background: trend >= 0 ? "rgba(52,211,153,0.12)" : "rgba(248,113,113,0.12)",
                color: trend >= 0 ? "#34d399" : "#f87171",
              }}
            >
              {trend >= 0 ? <TrendingUp className="size-2.5" /> : <TrendingDown className="size-2.5" />}
              {Math.abs(trend)}%
            </span>
          )}
          {(trendLabel || sub) && (
            <span className="text-[10px] text-[var(--muted-foreground)]">{trendLabel || sub}</span>
          )}
        </div>
      )}
      <div className="absolute bottom-0 left-0 right-0 h-0.5" style={{ background: `linear-gradient(90deg, ${c.text}55, transparent)` }} />
    </div>
  );
}
