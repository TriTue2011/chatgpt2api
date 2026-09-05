"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { KhopTuKhoa, useBoLocCaiDat } from "@/components/settings-filter";

interface SettingsSectionProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  badge?: React.ReactNode;
  /** Từ khoá thêm cho ô lọc — tên gọi khác, tên tiếng Anh, tên hãng. */
  tuKhoa?: string;
  children: React.ReactNode;
}

export function SettingsSection({
  title,
  description,
  icon,
  defaultOpen = false,
  badge,
  tuKhoa,
  children,
}: SettingsSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const boLoc = useBoLocCaiDat();
  const khop = KhopTuKhoa(`${title} ${description ?? ""} ${tuKhoa ?? ""}`, boLoc.tuKhoa);
  // Chỉ mount children khi đã từng mở — tránh 15 card nặng cùng fetch/polling
  // ngầm lúc /settings vừa tải (xem ActivityCollapse trong telegram-cloudflare-card.tsx).
  // Mở rồi thì giữ mounted luôn để đóng lại không mất dữ liệu đang sửa dở.
  const [hasOpened, setHasOpened] = useState(defaultOpen);
  const dangMo = open;
  useEffect(() => {
    if (dangMo) setHasOpened(true);
  }, [dangMo]);

  // Lọc trúng thì mở bằng CHÍNH state `open`, không phải một cờ hiển thị riêng.
  // Nếu ép mở bằng cờ riêng thì nút gập bấm vào không thấy gì đổi — nó lật một
  // state đang bị cờ kia che, và cái lật đó chỉ lòi ra sau khi xoá bộ lọc.
  useEffect(() => {
    if (boLoc.dangLoc && khop) setOpen(true);
  }, [boLoc.dangLoc, khop]);

  // Báo lên bộ lọc để nó biết khi nào không còn mục nào khớp.
  useEffect(() => {
    boLoc.bao(title, khop);
  }, [boLoc, title, khop]);

  // Không khớp thì ẨN, không tháo khỏi cây. Tháo ra là mất trạng thái form đang
  // gõ dở — đúng điều chú thích hasOpened ở trên đang cố tránh.
  const bienMat = boLoc.dangLoc && !khop;

  return (
    <div
      hidden={bienMat}
      className={cn(
        "overflow-hidden rounded-[16px] border border-[var(--border)] bg-[var(--card)]",
        bienMat && "hidden",
        "transition-all duration-300",
        dangMo
          ? "shadow-[0_8px_28px_color-mix(in_srgb,var(--neon-cyan)_10%,transparent),0_2px_8px_rgba(0,0,0,0.08)] border-[color-mix(in_srgb,var(--neon-cyan)_25%,var(--border))]"
          : "shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
      )}
    >
      {/* Clickable header */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-4 px-5 py-4 text-left transition-colors duration-200",
          dangMo
            ? "border-b border-[var(--border)]/60 bg-[color-mix(in_srgb,var(--neon-cyan)_4%,transparent)]"
            : "hover:bg-[var(--secondary)]/40"
        )}
      >
        {/* Icon avatar — vàng kim (chữ đen trên gold, đồng bộ logo/avatar) */}
        {icon && (
          <div
            className="flex size-10 shrink-0 items-center justify-center rounded-[12px] shrink-0"
            style={{
              background: dangMo
                ? "linear-gradient(135deg, var(--gold-bright), var(--gold-main) 55%, var(--gold-dark))"
                : "linear-gradient(135deg, color-mix(in srgb, var(--gold-main) 80%, transparent), color-mix(in srgb, var(--gold-dark) 70%, transparent))",
              color: "var(--sidebar-primary-foreground)",
              boxShadow: dangMo
                ? "0 0 18px var(--gold-glow)"
                : "0 2px 6px rgba(0,0,0,0.1)",
              transition: "box-shadow 0.3s ease, background 0.3s ease",
            }}
          >
            {icon}
          </div>
        )}

        {/* Text */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[14px] font-bold text-[var(--foreground)]">{title}</span>
            {badge}
          </div>
          {description && (
            <p className="mt-0.5 text-[12px] text-[var(--muted-foreground)] truncate">{description}</p>
          )}
        </div>

        {/* Chevron */}
        <ChevronDown
          className={cn(
            "size-5 shrink-0 transition-all duration-200",
            dangMo ? "rotate-180 text-[var(--neon-cyan)] drop-shadow-[0_0_6px_var(--neon-cyan)]" : "text-[var(--muted-foreground)]"
          )}
        />
      </button>

      {/* Collapsible content */}
      <div
        className={cn(
          "grid transition-all duration-300 ease-in-out",
          dangMo ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        )}
      >
        <div className="overflow-hidden">
          <div className="p-5">{hasOpened ? children : null}</div>
        </div>
      </div>
    </div>
  );
}
