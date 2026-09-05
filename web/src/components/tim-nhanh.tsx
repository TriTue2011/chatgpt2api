"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { Search, ArrowRight, AlertCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  SO_TRA,
  TRANG,
  NHAN_MUC_DO,
  mucConThieu,
  type MucTinhNang,
} from "@/lib/feature-registry";
import { useTrangThaiHeThong } from "@/lib/use-trang-thai-he-thong";

/**
 * Ô tìm nhanh Cmd+K — tra xuyên 18 trang và toàn bộ tính năng trong sổ tra.
 *
 * Vì sao cần: 18 trang cộng 41 thẻ cài đặt nằm trên một trang cuộn dài. Muốn
 * đổi một cài đặt thì phải nhớ nó nằm ở nhóm nào rồi cuộn tìm. Gõ hai chữ là
 * tới nơi thì không phải nhớ gì cả.
 *
 * Nhóm "Còn thiếu" đưa luôn phần chưa cấu hình lên đầu: người mới cài mở ô tìm
 * ra là thấy việc cần làm, không phải biết trước tên của thứ mình đang thiếu.
 */
export function TimNhanh() {
  const [mo, datMo] = React.useState(false);
  const router = useRouter();
  const tt = useTrangThaiHeThong();

  React.useEffect(() => {
    const nhan = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        datMo((v) => !v);
      }
    };
    document.addEventListener("keydown", nhan);
    return () => document.removeEventListener("keydown", nhan);
  }, []);

  const di = React.useCallback(
    (duong: string) => {
      datMo(false);
      router.push(duong);
    },
    [router],
  );

  const thieu = mucConThieu(tt);
  const thieuId = new Set(thieu.map((m) => m.id));
  const conLai = SO_TRA.filter((m) => !thieuId.has(m.id));

  return (
    <>
      <button
        type="button"
        onClick={() => datMo(true)}
        aria-label="Tìm nhanh chức năng và cài đặt"
        className={cn(
          "group inline-flex h-9 items-center gap-2 rounded-xl border border-[var(--border)]",
          "bg-[var(--surface-2)] px-3 text-sm text-[var(--muted-foreground)] transition-colors",
          "hover:border-[var(--primary)]/40 hover:text-[var(--foreground)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
        )}
      >
        <Search className="size-4" aria-hidden />
        <span className="hidden sm:inline">Tìm chức năng…</span>
        <kbd
          className={cn(
            "ml-1 hidden rounded-md border border-[var(--border)] bg-[var(--card)]",
            "px-1.5 py-0.5 font-mono text-[10px] text-[var(--muted-foreground)] md:inline",
          )}
        >
          ⌘K
        </kbd>
      </button>

      <Command.Dialog
        open={mo}
        onOpenChange={datMo}
        label="Tìm nhanh"
        shouldFilter
        className={cn(
          "fixed left-1/2 top-[12vh] z-[80] w-[min(94vw,36rem)] -translate-x-1/2",
          "overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--popover)]",
          "text-[var(--popover-foreground)] shadow-[0_32px_100px_-40px_rgba(0,0,0,0.6)]",
        )}
        overlayClassName="fixed inset-0 z-[79] bg-black/45 backdrop-blur-[2px]"
      >
        <div className="flex items-center gap-2 border-b border-[var(--border)] px-4">
          <Search className="size-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden />
          <Command.Input
            placeholder="Gõ tên chức năng hoặc cài đặt…"
            className={cn(
              "h-12 w-full bg-transparent text-sm outline-none",
              "placeholder:text-[var(--muted-foreground)]",
            )}
          />
        </div>

        <Command.List className="max-h-[min(60vh,26rem)] overflow-y-auto p-2">
          <Command.Empty className="px-3 py-8 text-center text-sm text-[var(--muted-foreground)]">
            Không có mục nào khớp.
          </Command.Empty>

          {thieu.length > 0 && (
            <Nhom nhan="Còn thiếu">
              {thieu.map((m) => (
                <DongTinhNang key={m.id} muc={m} thieu onChon={() => di(m.duong)} />
              ))}
            </Nhom>
          )}

          <Nhom nhan="Trang">
            {TRANG.map((t) => (
              <Command.Item
                key={t.duong}
                value={`${t.ten} ${t.tuKhoa.join(" ")}`}
                onSelect={() => di(t.duong)}
                className={lopDong}
              >
                <span className="truncate">{t.ten}</span>
                <ArrowRight
                  className="ml-auto size-3.5 shrink-0 opacity-0 data-[selected]:opacity-100"
                  aria-hidden
                />
              </Command.Item>
            ))}
          </Nhom>

          <Nhom nhan="Tính năng và cài đặt">
            {conLai.map((m) => (
              <DongTinhNang key={m.id} muc={m} onChon={() => di(m.duong)} />
            ))}
          </Nhom>
        </Command.List>
      </Command.Dialog>
    </>
  );
}

const lopDong = cn(
  "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none",
  "data-[selected=true]:bg-[var(--sidebar-accent)] data-[selected=true]:text-[var(--foreground)]",
);

function Nhom({ nhan, children }: { nhan: string; children: React.ReactNode }) {
  return (
    <Command.Group
      heading={nhan}
      className={cn(
        "mb-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5",
        "[&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium",
        "[&_[cmdk-group-heading]]:text-[var(--muted-foreground)]",
      )}
    >
      {children}
    </Command.Group>
  );
}

function DongTinhNang({
  muc,
  thieu,
  onChon,
}: {
  muc: MucTinhNang;
  thieu?: boolean;
  onChon: () => void;
}) {
  return (
    <Command.Item
      value={`${muc.ten} ${muc.tuKhoa.join(" ")} ${muc.nhom}`}
      onSelect={onChon}
      className={lopDong}
    >
      {thieu ? (
        <AlertCircle className="size-3.5 shrink-0 text-[var(--primary)]" aria-hidden />
      ) : null}
      <span className="truncate">{muc.ten}</span>
      <span className="ml-auto shrink-0 text-[11px] text-[var(--muted-foreground)]">
        {thieu ? NHAN_MUC_DO[muc.mucDo] : muc.nhom}
      </span>
    </Command.Item>
  );
}
