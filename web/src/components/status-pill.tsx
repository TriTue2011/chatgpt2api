"use client";

import { cn } from "@/lib/utils";

export type StatusKind = "ok" | "warning" | "error" | "off" | "info";

const COLORS: Record<StatusKind, string> = {
  ok: "var(--neon-lime)",
  warning: "var(--neon-amber)",
  error: "var(--destructive)",
  off: "var(--muted-foreground)",
  info: "var(--accent)",
};

export function StatusPill({
  status, label, className, showDot = true,
}: {
  status: StatusKind;
  label: string;
  className?: string;
  showDot?: boolean;
}) {
  const color = COLORS[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
        className,
      )}
      style={{
        color,
        borderColor: `color-mix(in srgb, ${color} 35%, transparent)`,
        background: `color-mix(in srgb, ${color} 10%, transparent)`,
      }}
    >
      {showDot && (
        <span className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      )}
      {label}
    </span>
  );
}

export function statusColor(status: StatusKind): string {
  return COLORS[status];
}
