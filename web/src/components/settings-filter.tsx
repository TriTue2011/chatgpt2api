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
  /** Mỗi mục báo lên nó có khớp không, để biết khi nào không còn mục nào. */
  bao: (id: string, khop: boolean) => void;
};

const Ctx = React.createContext<BoLoc>({
  tuKhoa: "",
  dangLoc: false,
  bao: () => {},
});

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

  // Nhảy thẳng tới một mục từ nơi khác: /settings?tim=zalo%20cá%20nhân
  //
  // Bơm vào ĐÚNG ô lọc sẵn có thay vì dựng cơ chế "mở thẻ theo id" riêng, vì
  // settings-section.tsx đã tự mở khi lọc trúng. Người dùng cũng thấy ngay vì
  // sao thẻ mở: từ khoá hiện trong ô, xoá đi là về như cũ.
  //
  // Đọc một lần lúc mount: sau đó ô lọc là của người dùng, không để URL cũ
  // ghi đè khi họ đang gõ.
  React.useEffect(() => {
    const tim = new URLSearchParams(window.location.search).get("tim");
    if (tim && tim.trim()) datTuKhoa(tim.trim());
  }, []);

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

  // Các mục tự báo lên có khớp không. Không có cách nào biết "không còn mục nào"
  // bằng CSS thuần, mà lọc ra trắng trang không một lời giải thích thì người
  // dùng tưởng trang hỏng.
  const [soKhop, datSoKhop] = React.useState<Record<string, boolean>>({});
  const bao = React.useCallback((id: string, khop: boolean) => {
    datSoKhop((cu) => (cu[id] === khop ? cu : { ...cu, [id]: khop }));
  }, []);

  const giaTri = React.useMemo(
    () => ({ tuKhoa, dangLoc: tuKhoa.trim().length > 0, bao }),
    [tuKhoa, bao],
  );
  const khongCoGi =
    tuKhoa.trim().length > 0 && Object.values(soKhop).every((v) => !v);

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
      {khongCoGi && (
        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-1)] px-4 py-8 text-center text-sm text-[var(--muted-foreground)]">
          Không có cài đặt nào khớp «{tuKhoa}».
        </p>
      )}
    </Ctx.Provider>
  );
}
