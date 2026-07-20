"use client";

import { cn } from "@/lib/utils";

/**
 * Phần nhỏ thu gọn được TRONG một card settings — "tab nhỏ từng phần, mặc định
 * thu gọn" (khác SettingsSection: cái đó là collapse CẤP CARD, header lớn).
 *
 * Dựa <details> native → không cần state, mặc định đóng (truyền defaultOpen
 * để mở sẵn). Giữ markup đồng bộ với các <details> inline ở
 * telegram-cloudflare-card.
 */
export function CollapsibleSection({
  title,
  defaultOpen = false,
  className,
  children,
}: {
  title: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <details className={cn("group", className)} open={defaultOpen || undefined}>
      <summary className="text-sm font-semibold flex items-center gap-2 cursor-pointer select-none list-none">
        <span className="inline-block text-muted-foreground transition-transform group-open:rotate-90">▸</span>
        {title}
      </summary>
      <div className="space-y-3 mt-3">{children}</div>
    </details>
  );
}
