"use client";

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon, title, description, action, className, compact,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "h-32 gap-1.5 px-4" : "min-h-[200px] gap-3 px-6 py-10",
        className,
      )}
    >
      {Icon && (
        <div
          className="flex size-11 items-center justify-center rounded-2xl"
          style={{
            background: "color-mix(in srgb, var(--primary) 14%, transparent)",
            border: "1px solid color-mix(in srgb, var(--primary) 28%, transparent)",
          }}
        >
          <Icon className="size-5 text-[var(--primary)]" />
        </div>
      )}
      <div className="space-y-1">
        <p className="text-[13px] font-semibold text-[var(--foreground)]">{title}</p>
        {description && (
          <p className="max-w-sm text-[12px] leading-relaxed text-[var(--muted-foreground)]">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
