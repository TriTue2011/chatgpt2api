"use client";

import { AudioLines, Facebook, Headphones, ListEnd, ListMusic, ListPlus, ListVideo, LoaderCircle, MonitorPlay, Music2, Play, Search, SlidersHorizontal, Youtube } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { type BaiHat, type Nguon, TEN_NGUON, thoiLuong } from "./lib";
import { type KhoPlaylist, laLinkPlaylist, ThemVaoPlaylist } from "./playlist";

/** YouTube, Zing, Facebook, rồi Playlist. Không có nguồn dán file âm thanh trực tiếp. */
const NUT_NGUON: { khoa: Exclude<Nguon, "http">; Icon: typeof Youtube; nhan: string; goiY: string; o: string }[] = [
  { khoa: "youtube", Icon: Youtube, nhan: "YouTube", goiY: "Tivi mở ứng dụng YouTube, loa nhận tiếng.", o: "Tìm tên bài hát, ca sĩ hoặc dán link YouTube…" },
  { khoa: "zing", Icon: Music2, nhan: "Zing MP3", goiY: "Bài công khai, không VIP.", o: "Tìm tên bài hát hoặc ca sĩ…" },
  { khoa: "facebook", Icon: Facebook, nhan: "Facebook", goiY: "Chỉ dán link. Reel, watch hoặc link chia sẻ đều được.", o: "Dán link video Facebook (reel, watch hoặc link chia sẻ)…" },
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
  /** `xem` = nút xem video; không thì chỉ nghe. */
  phat: (bai: BaiHat, xem?: boolean) => void;
  kho: KhoPlaylist;
  /** Đang xem playlist thay cho tìm nhạc. */
  xemPlaylist: boolean;
  doiXemPlaylist: (v: boolean) => void;
  /** Ô tìm đang là link playlist: lưu cả playlist. */
  luuCaPlaylist: () => void;
  dangLuuPlaylist: boolean;
  bangPlaylist: ReactNode;
  /** Đang xem Queue (bài phát kế tiếp) thay cho tìm nhạc. */
  xemQueue: boolean;
  doiXemQueue: (v: boolean) => void;
  bangQueue: ReactNode;
  soQueue: number;
  themVaoQueue: (bai: BaiHat) => void;
  /** Mục chủ máy đã ẩn trên máy này: "youtube" | "zing" | "facebook" | "playlist" | "queue". */
  an: Set<string>;
  datAn: (muc: string, an: boolean) => void;
};

/** Tên lớp phải viết sẵn cho Tailwind — số cột theo số mục còn hiện. */
const COT: Record<number, string> = {
  1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-2 sm:grid-cols-4", 5: "grid-cols-3 sm:grid-cols-5",
};
const MUC_AN: { khoa: string; nhan: string }[] = [
  { khoa: "youtube", nhan: "YouTube" }, { khoa: "zing", nhan: "Zing MP3" }, { khoa: "facebook", nhan: "Facebook" },
  { khoa: "playlist", nhan: "Playlist" }, { khoa: "queue", nhan: "Queue" },
];

export function TimNhac({
  className, nguon, doiNguon, tuKhoa, setTuKhoa, tim, dangTim, ketQua, dangPhatMa, dangGuiMa, coLoa, phat,
  kho, xemPlaylist, doiXemPlaylist, luuCaPlaylist, dangLuuPlaylist, bangPlaylist,
  xemQueue, doiXemQueue, bangQueue, soQueue, themVaoQueue, an, datAn,
}: Props) {
  const [moAn, setMoAn] = useState(false);
  const nguonHien = NUT_NGUON.filter((n) => !an.has(n.khoa));
  const soMuc = nguonHien.length + (an.has("playlist") ? 0 : 1) + (an.has("queue") ? 0 : 1);
  const nut = NUT_NGUON.find((n) => n.khoa === nguon);
  const nutNguon = (dang: boolean, nhan: string, Icon: typeof Search, bam: () => void) => (
    <button
      type="button"
      aria-pressed={dang}
      onClick={bam}
      className={cn(
        "flex min-w-0 items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold transition sm:text-sm",
        dang ? "bg-[var(--card)] text-[var(--primary)] shadow-sm" : "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" />
      <span className="truncate">{nhan}</span>
    </button>
  );
  return (
    <section className={cn("rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5", className)}>
      <div className="flex items-start gap-1">
        <div role="group" aria-label="Nguồn nhạc, playlist và Queue" className={cn("grid min-w-0 flex-1 gap-1 rounded-xl bg-[var(--muted)] p-1", COT[soMuc] ?? COT[2])}>
          {nguonHien.map(({ khoa, Icon, nhan }) => (
            <span key={khoa} className="contents">{nutNguon(!xemPlaylist && !xemQueue && nguon === khoa, nhan, Icon, () => { doiXemPlaylist(false); doiXemQueue(false); doiNguon(khoa); })}</span>
          ))}
          {!an.has("playlist") && nutNguon(xemPlaylist, `Playlist${kho.ds?.length ? ` (${kho.ds.length})` : ""}`, ListMusic, () => { doiXemQueue(false); doiXemPlaylist(true); })}
          {!an.has("queue") && nutNguon(xemQueue, `Queue${soQueue ? ` (${soQueue})` : ""}`, ListVideo, () => { doiXemPlaylist(false); doiXemQueue(true); })}
        </div>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-expanded={moAn}
          aria-label="Ẩn hoặc hiện mục"
          title="Ẩn / hiện mục trên máy này"
          className="size-9 shrink-0 rounded-full text-muted-foreground"
          onClick={() => setMoAn((v) => !v)}
        >
          <SlidersHorizontal />
        </Button>
      </div>
      {moAn && (
        <div className="mt-2 rounded-xl border border-[var(--border)] p-3 text-sm">
          <div className="mb-2 text-xs text-muted-foreground">Mục hiện trên máy này (bỏ chọn để ẩn):</div>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {MUC_AN.map(({ khoa, nhan }) => {
              const hien = !an.has(khoa);
              // Phải còn ít nhất một nguồn tìm nhạc — ẩn hết thì không còn đường tìm bài.
              const khoa_cuoi = hien && NUT_NGUON.some((n) => n.khoa === khoa) && nguonHien.length === 1;
              return (
                <label key={khoa} className={cn("flex items-center gap-1.5", khoa_cuoi && "opacity-50")}>
                  <input type="checkbox" checked={hien} disabled={khoa_cuoi} onChange={(e) => datAn(khoa, !e.target.checked)} />
                  {nhan}
                </label>
              );
            })}
          </div>
        </div>
      )}

      {xemQueue ? bangQueue : xemPlaylist ? bangPlaylist : (<>
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
          placeholder={nut?.o ?? "Tìm tên bài hát hoặc ca sĩ…"}
          aria-label="Tìm bài hát"
          className="h-10 min-w-0 flex-1"
        />
        <Button type="submit" className="h-10 shrink-0" disabled={dangTim || !tuKhoa.trim()}>
          {dangTim ? <LoaderCircle className="animate-spin" /> : <Search />}
          <span className="hidden sm:inline">Tìm</span>
        </Button>
      </form>
      <p className="mt-2 text-xs text-muted-foreground">
        {nut?.goiY}
        {coLoa
          ? ""
          : nguon === "youtube" || nguon === "facebook"
            ? " Chưa chọn loa: nút tai nghe để nghe trên máy này, nút màn hình để xem video."
            : " Chưa chọn loa: bấm nút tai nghe để nghe trên máy này."}
      </p>
      {laLinkPlaylist(tuKhoa) && (
        <Button type="button" variant="outline" className="mt-2 h-9 w-full" disabled={dangLuuPlaylist} onClick={luuCaPlaylist}>
          {dangLuuPlaylist ? <LoaderCircle className="animate-spin" /> : <ListPlus />}
          Lưu cả playlist này vào Playlist
        </Button>
      )}

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
            Tìm một bài để bắt đầu.
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
                    bai.source === "youtube" || bai.source === "facebook" ? "aspect-video w-24 sm:w-28" : "size-14",
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
                {bai.source !== "http" && !an.has("queue") && (
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="shrink-0 rounded-full text-muted-foreground"
                    aria-label={`Thêm ${bai.title || bai.id} vào Queue`}
                    title="Thêm vào Queue — phát sau bài đang nghe"
                    onClick={() => themVaoQueue(bai)}
                  >
                    <ListEnd />
                  </Button>
                )}
                {bai.source !== "http" && <ThemVaoPlaylist bai={bai} kho={kho} />}
                {(bai.source === "youtube" || bai.source === "facebook") && (
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="shrink-0 rounded-full text-muted-foreground"
                    aria-label={`Xem video ${bai.title || bai.id}`}
                    title={coLoa ? "Phát ra loa đã chọn và xem video trên trang" : "Xem video trên trang"}
                    disabled={!!dangGuiMa}
                    onClick={() => phat(bai, true)}
                  >
                    <MonitorPlay />
                  </Button>
                )}
                <Button
                  type="button"
                  size="icon"
                  variant={dangPhat ? "default" : "outline"}
                  className="shrink-0 rounded-full"
                  aria-label={`Phát ${bai.title || bai.id}`}
                  title={coLoa || bai.source === "http" ? "Phát ra loa đã chọn (chỉ tiếng)" : "Nghe trên máy này (chỉ tiếng)"}
                  disabled={!!dangGuiMa}
                  onClick={() => phat(bai)}
                >
                  {dangGui ? (
                    <LoaderCircle className="animate-spin" />
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
      </>)}
    </section>
  );
}
