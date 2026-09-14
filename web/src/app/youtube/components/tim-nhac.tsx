"use client";

import { AudioLines, Headphones, Link2, LoaderCircle, MonitorPlay, Music2, Play, Search, Youtube } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { type BaiHat, type Nguon, TEN_NGUON, thoiLuong } from "./lib";

const NUT_NGUON: { khoa: Nguon; Icon: typeof Youtube; goiY: string }[] = [
  { khoa: "youtube", Icon: Youtube, goiY: "Dán link YouTube để ra đúng video · tivi mở ứng dụng YouTube, loa nhận tiếng" },
  { khoa: "zing", Icon: Music2, goiY: "Bài công khai, không VIP" },
  { khoa: "http", Icon: Link2, goiY: "Dán link MP3, AAC, FLAC, OGG hoặc HLS" },
];

type Props = {
  className?: string;
  nguon: Nguon;
  doiNguon: (n: Nguon) => void;
  tuKhoa: string;
  setTuKhoa: (s: string) => void;
  tim: () => void;
  dangTim: boolean;
  ketQua: BaiHat[];
  dangPhatMa: string;
  dangGuiMa: string;
  /** Có chọn loa: ▶ phát ra loa; chưa chọn: ▶ bài YouTube mở video trên trang. */
  coLoa: boolean;
  /** Nghe khi tắt màn hình đang bật: chưa tích loa thì ▶ phát tiếng trên máy này. */
  ngheNen: boolean;
  phat: (bai: BaiHat) => void;
};

export function TimNhac({ className, nguon, doiNguon, tuKhoa, setTuKhoa, tim, dangTim, ketQua, dangPhatMa, dangGuiMa, coLoa, ngheNen, phat }: Props) {
  const goiY = NUT_NGUON.find((n) => n.khoa === nguon)?.goiY;
  return (
    <section className={cn("rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5", className)}>
      <div role="group" aria-label="Nguồn nhạc" className="grid grid-cols-3 gap-1 rounded-xl bg-[var(--muted)] p-1">
        {NUT_NGUON.map(({ khoa, Icon }) => (
          <button
            key={khoa}
            type="button"
            aria-pressed={nguon === khoa}
            onClick={() => doiNguon(khoa)}
            className={cn(
              "flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold transition sm:text-sm",
              nguon === khoa
                ? "bg-[var(--card)] text-[var(--primary)] shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" />
            <span className="truncate">{TEN_NGUON[khoa]}</span>
          </button>
        ))}
      </div>

      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          tim();
        }}
      >
        <Input
          type="search"
          value={tuKhoa}
          onChange={(e) => setTuKhoa(e.target.value)}
          maxLength={nguon === "zing" ? 120 : 2048}
          placeholder={nguon === "http" ? "https://…/bai-hat.mp3" : nguon === "youtube" ? "Tên bài hát, ca sĩ hoặc link YouTube…" : "Tên bài hát, ca sĩ…"}
          aria-label={nguon === "http" ? "Link âm thanh trực tiếp" : "Tìm bài hát"}
          className="h-10 min-w-0 flex-1"
        />
        <Button type="submit" className="h-10 shrink-0" disabled={dangTim || !tuKhoa.trim()}>
          {dangTim ? <LoaderCircle className="animate-spin" /> : nguon === "http" ? <Link2 /> : <Search />}
          <span className="hidden sm:inline">{nguon === "http" ? "Thêm" : "Tìm"}</span>
        </Button>
      </form>
      <p className="mt-2 text-xs text-muted-foreground">
        {goiY}
        {coLoa || nguon === "http"
          ? ""
          : nguon === "youtube" && !ngheNen
            ? " · chưa chọn loa: bấm ▶ để xem ngay trên trang"
            : " · chưa chọn loa: bấm ▶ để nghe trên máy này"}
      </p>

      <div className="mt-4 space-y-1.5">
        {dangTim && !ketQua.length ? (
          Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="flex animate-pulse items-center gap-3 rounded-xl p-2">
              <div className="aspect-video w-24 shrink-0 rounded-lg bg-[var(--muted)]" />
              <div className="flex-1 space-y-2">
                <div className="h-3 w-3/4 rounded bg-[var(--muted)]" />
                <div className="h-3 w-1/3 rounded bg-[var(--muted)]" />
              </div>
            </div>
          ))
        ) : !ketQua.length ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
            <Music2 className="size-8 opacity-40" />
            {nguon === "http" ? "Dán link âm thanh để phát." : "Tìm một bài để bắt đầu."}
          </div>
        ) : (
          ketQua.map((bai) => {
            const ma = bai.url || bai.id;
            const dangPhat = ma === dangPhatMa;
            const dangGui = ma === dangGuiMa;
            return (
              <div
                key={ma}
                className={cn(
                  "group flex items-center gap-3 rounded-xl p-2 transition",
                  dangPhat
                    ? "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--primary)_30%,transparent)]"
                    : "hover:bg-[var(--muted)]",
                )}
              >
                <div
                  className={cn(
                    "relative shrink-0 overflow-hidden rounded-lg bg-[var(--muted)]",
                    bai.source === "youtube" ? "aspect-video w-24 sm:w-28" : "size-14",
                  )}
                >
                  {/^https?:\/\//.test(bai.thumbnail) ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={bai.thumbnail} alt="" loading="lazy" className="size-full object-cover" />
                  ) : (
                    <Music2 className="absolute inset-0 m-auto size-5 text-muted-foreground" />
                  )}
                  {bai.duration ? (
                    <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 text-[10px] font-medium tabular-nums text-white">
                      {thoiLuong(bai.duration)}
                    </span>
                  ) : null}
                </div>
                <div className="min-w-0 flex-1">
                  <div className={cn("line-clamp-2 text-sm font-medium leading-snug", dangPhat && "text-[var(--primary)]")}>
                    {bai.title || bai.id}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                    {dangPhat && <AudioLines className="size-3.5 shrink-0 animate-pulse text-[var(--primary)]" />}
                    <span className="truncate">{bai.channel || bai.artist || TEN_NGUON[bai.source]}</span>
                  </div>
                </div>
                <Button
                  type="button"
                  size="icon"
                  variant={dangPhat ? "default" : "outline"}
                  className="shrink-0 rounded-full"
                  aria-label={`Phát ${bai.title || bai.id}`}
                  title={coLoa || bai.source === "http" ? "Phát ra loa đã chọn" : bai.source === "youtube" && !ngheNen ? "Xem video trên trang" : "Nghe trên máy này"}
                  disabled={!!dangGuiMa}
                  onClick={() => phat(bai)}
                >
                  {dangGui ? (
                    <LoaderCircle className="animate-spin" />
                  ) : !coLoa && bai.source === "youtube" && !ngheNen ? (
                    <MonitorPlay />
                  ) : !coLoa && bai.source !== "http" ? (
                    <Headphones />
                  ) : (
                    <Play className="translate-x-px" />
                  )}
                </Button>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
