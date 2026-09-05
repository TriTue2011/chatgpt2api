"use client";

import * as React from "react";
import { Search, X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Ô lọc cho trang Cài đặt.
 *
 * Vì sao cần: 18 mục gập, mỗi mục vài thẻ con, tổng 41 thẻ. Mục thì gập được
 * nên không phải cuộn dài, nhưng muốn đổi một cài đặt vẫn phải NHỚ nó nằm ở
 * mục nào rồi mở từng cái ra dò.
 *
 * Làm bằng context để không phải sửa 18 chỗ gọi `<SettingsSection>`: mỗi mục tự
 * đọc từ khoá đang lọc, tự ẩn nếu không khớp và tự mở nếu khớp.
 */

type BoLoc = {
  tuKhoa: string;
  /** Có đang lọc không — dùng để quyết định tự mở mục khớp. */
  dangLoc: boolean;
};

const Ctx = React.createContext<BoLoc>({ tuKhoa: "", dangLoc: false });

export function useBoLocCaiDat() {
  return React.useContext(Ctx);
}

/** Bỏ dấu để gõ "gemini" hay "cấu hình" đều tìm được, không cần gõ đúng dấu. */
export function boDau(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d");
}

export function KhopTuKhoa(noiDung: string, tuKhoa: string): boolean {
  if (!tuKhoa.trim()) return true;
  const kho = boDau(noiDung);
  // Mọi từ đều phải xuất hiện, không cần liền nhau: gõ "home token" vẫn ra
  // "Home Assistant · token truy cập".
  return boDau(tuKhoa)
    .split(/\s+/)
    .filter(Boolean)
    .every((tu) => kho.includes(tu));
}

export function BoLocCaiDat({ children }: { children: React.ReactNode }) {
  const [tuKhoa, datTuKhoa] = React.useState("");
  const oNhap = React.useRef<HTMLInputElement>(null);

  // "/" để nhảy vào ô lọc, Esc để xoá — quen thuộc với người dùng bàn phím.
  React.useEffect(() => {
    const nhan = (e: KeyboardEvent) => {
      const dich = e.target as HTMLElement | null;
      const dangGo =
        dich && (dich.tagName === "INPUT" || dich.tagName === "TEXTAREA" || dich.isContentEditable);
      if (e.key === "/" && !dangGo) {
        e.preventDefault();
        oNhap.current?.focus();
      } else if (e.key === "Escape" && dich === oNhap.current) {
        datTuKhoa("");
      }
    };
    document.addEventListener("keydown", nhan);
    return () => document.removeEventListener("keydown", nhan);
  }, []);

  const giaTri = React.useMemo(
    () => ({ tuKhoa, dangLoc: tuKhoa.trim().length > 0 }),
    [tuKhoa],
  );

  return (
    <Ctx.Provider value={giaTri}>
      <div className="sticky top-14 z-20 -mx-1 mb-3 bg-[var(--background)]/95 px-1 py-2 backdrop-blur">
        <div
          className={cn(
            "flex items-center gap-2 rounded-xl border border-[var(--border)]",
            "bg-[var(--card)] px-3 focus-within:border-[var(--primary)]/50",
          )}
        >
          <Search className="size-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden />
          <input
            ref={oNhap}
            value={tuKhoa}
            onChange={(e) => datTuKhoa(e.target.value)}
            placeholder="Lọc cài đặt… (bấm / để nhảy vào đây)"
            aria-label="Lọc cài đặt theo từ khoá"
            className={cn(
              "h-10 w-full bg-transparent text-sm text-[var(--foreground)] outline-none",
              "placeholder:text-[var(--muted-foreground)]",
            )}
          />
          {tuKhoa && (
            <button
              type="button"
              onClick={() => datTuKhoa("")}
              aria-label="Xoá bộ lọc"
              className="shrink-0 rounded-md p-1 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          )}
        </div>
      </div>
      {children}
    </Ctx.Provider>
  );
}
