"use client";

/**
 * Khối "Đang phát" — ảnh bìa hoặc video, tên bài, nút điều khiển, cỡ xem.
 *
 * Chủ máy 14/09/2026: "Khi xem video thì mục đang phát cũng là nó thì bỏ đi",
 * "nút điều khiển đang to", "khi xem video thì nút đó lại không sử dụng được",
 * "gộp các phần giống nhau lại". Video thay chỗ ảnh bìa; một hàng nút điều khiển
 * cả loa lẫn video. Khung iframe luôn nằm cùng một chỗ trong cây React (đổi cỡ
 * chỉ đổi lớp CSS), nên đổi Vừa / Rạp / Thu nhỏ không làm video nạp lại.
 */

import { ListMusic, LoaderCircle, Maximize, Maximize2, Minimize2, MonitorPlay, Music2, Pause, PictureInPicture2, Play, RectangleHorizontal, SkipBack, SkipForward, Square, X } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { type BaiHat, type Phien, TEN_NGUON, type ThietBi, thoiLuong } from "./lib";
import type { CheDoXem, VideoNhung } from "./video-nhung";

export type VideoMo = { bai: BaiHat; src: string; theoLoa: boolean };

type Props = {
  className?: string;
  phien: Phien | null;
  thietBi: ThietBi[];
  video: VideoMo | null;
  nhung: VideoNhung;
  cheDo: CheDoXem;
  doiCheDo: (c: CheDoXem) => void;
  dongVideo: () => void;
  dangChay: boolean;
  dangGui: boolean;
  truoc: (() => void) | null;
  tiep: (() => void) | null;
  phatTamDung: (() => void) | null;
  dung: (() => void) | null;
  xemTaiDay: (() => void) | null;
};

function NutPhu({ nhan, Icon, onClick, chiManHinhRong = false }: { nhan: string; Icon: typeof X; onClick: () => void; chiManHinhRong?: boolean }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className={cn("size-8 text-muted-foreground", chiManHinhRong && "hidden sm:inline-flex")}
      aria-label={nhan}
      title={nhan}
      onClick={onClick}
    >
      <Icon className="size-4" />
    </Button>
  );
}

export function DangPhat(p: Props) {
  const { video, nhung, cheDo } = p;
  const toanManHinh = useRef<HTMLDivElement>(null);
  const bai = video?.bai ?? p.phien?.item ?? null;
  const tenTheoMa = new Map(p.thietBi.map((t) => [t.entity_id, t.ten]));
  const noiPhat = (p.phien?.output_entity_ids ?? []).map((id) => tenTheoMa.get(id) ?? id);
  const hang = p.phien?.queue;
  const anh = bai && /^https?:\/\//.test(bai.thumbnail || "") ? bai.thumbnail : "";
  const nho = !!video && cheDo === "nho";

  const meta = bai
    ? video
      ? [bai.channel || bai.artist, thoiLuong(bai.duration), video.theoLoa && noiPhat.length ? `Tiếng ra ${noiPhat.join(", ")}` : "Xem trên trang"]
      : [bai.artist || bai.channel, thoiLuong(bai.duration), TEN_NGUON[bai.source], noiPhat.length ? `Trên ${noiPhat.join(", ")}` : ""]
    : [];

  const moToanManHinh = () => {
    void toanManHinh.current?.requestFullscreen?.();
  };

  return (
    <section id="khoi-dang-phat" className={cn("overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)]", p.className)}>
      <div className="relative aspect-video w-full overflow-hidden bg-[var(--muted)]">
        {anh ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={anh} alt="" className="absolute inset-0 size-full scale-110 object-cover opacity-60 blur-2xl" />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={anh} alt="" className="relative mx-auto h-full object-contain" />
          </>
        ) : (
          <div className="flex size-full items-center justify-center bg-[radial-gradient(circle_at_30%_20%,var(--gold-glow),transparent_60%)]">
            <Music2 className="size-12 text-[var(--primary)] opacity-50" />
          </div>
        )}
        {!video && (
          <span className="absolute left-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur">
            {bai && p.phien?.state === "playing" ? (p.dangChay ? "Đang phát" : "Đã gửi") : "Chưa phát"}
          </span>
        )}
        {!video && hang && hang.items.length > 1 && hang.index >= 0 && (
          <span className="absolute right-3 top-3 flex items-center gap-1 rounded-full bg-black/60 px-2.5 py-1 text-[11px] font-semibold tabular-nums text-white backdrop-blur">
            <ListMusic className="size-3" /> {hang.index + 1}/{hang.items.length}
          </span>
        )}
        {!video && p.xemTaiDay && (
          <button
            type="button"
            onClick={p.xemTaiDay}
            className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-full bg-black/65 px-3 py-1.5 text-xs font-semibold text-white backdrop-blur transition hover:bg-black/80"
          >
            <MonitorPlay className="size-3.5" /> Xem video
          </button>
        )}
        {video && (
          <div
            className={cn(
              nho
                ? "fixed bottom-20 right-4 z-40 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl lg:bottom-4"
                : "absolute inset-0 bg-black",
            )}
          >
            <div ref={toanManHinh} className={nho ? "relative aspect-video bg-black" : "absolute inset-0"}>
              <iframe
                ref={nhung.ganKhung}
                src={video.src}
                onLoad={nhung.khiNap}
                title={video.bai.title || "Video YouTube"}
                className="absolute inset-0 size-full"
                allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                allowFullScreen
                // YouTube báo "Error 153" khi khung nhúng không kèm Referer (trang gửi no-referrer).
                referrerPolicy="strict-origin-when-cross-origin"
              />
            </div>
            {nho && (
              <div className="flex items-center gap-0.5 px-2 py-1">
                <span className="min-w-0 flex-1 truncate px-1 text-xs font-medium">{video.bai.title}</span>
                {p.phatTamDung && <NutPhu nhan={p.dangChay ? "Tạm dừng" : "Phát"} Icon={p.dangChay ? Pause : Play} onClick={p.phatTamDung} />}
                <NutPhu nhan="Phóng to lại" Icon={Maximize2} onClick={() => p.doiCheDo("vua")} />
                <NutPhu nhan="Đóng video" Icon={X} onClick={p.dongVideo} />
              </div>
            )}
          </div>
        )}
        {nho && (
          <span className="absolute inset-x-0 bottom-3 mx-auto w-fit rounded-full bg-black/65 px-3 py-1 text-xs font-semibold text-white">
            Đang xem ở khung nổi
          </span>
        )}
      </div>

      <div className="px-3 pb-2 pt-3">
        <div className="line-clamp-2 text-sm font-semibold leading-snug">{bai?.title || "Chưa có bài nào"}</div>
        <div className="mt-0.5 truncate text-xs text-muted-foreground">
          {bai ? meta.filter(Boolean).join(" · ") : "Chọn loa rồi bấm ▶ một bài, hoặc bấm ▶ khi chưa chọn loa để xem video ngay trên trang."}
        </div>

        <div className="mt-2 flex items-center justify-between gap-1">
          <div className="flex items-center gap-1">
            <Button type="button" variant="ghost" size="icon" className="size-9 rounded-full" aria-label="Bài trước" title="Bài trước" disabled={!p.truoc || p.dangGui} onClick={() => p.truoc?.()}>
              <SkipBack className="size-4" />
            </Button>
            <Button
              type="button"
              size="icon"
              className="size-11 rounded-full shadow-[0_0_18px_var(--gold-glow)]"
              aria-label={p.dangChay ? "Tạm dừng" : "Phát"}
              title={p.dangChay ? "Tạm dừng" : "Phát"}
              disabled={!p.phatTamDung || p.dangGui}
              onClick={() => p.phatTamDung?.()}
            >
              {p.dangGui ? <LoaderCircle className="size-5 animate-spin" /> : p.dangChay ? <Pause className="size-5" /> : <Play className="size-5 translate-x-px" />}
            </Button>
            <Button type="button" variant="ghost" size="icon" className="size-9 rounded-full" aria-label="Bài tiếp" title="Bài tiếp" disabled={!p.tiep || p.dangGui} onClick={() => p.tiep?.()}>
              <SkipForward className="size-4" />
            </Button>
            <Button type="button" variant="ghost" size="icon" className="size-9 rounded-full text-red-600 hover:text-red-600 dark:text-red-400" aria-label="Dừng" title="Dừng" disabled={!p.dung} onClick={() => p.dung?.()}>
              <Square className="size-3.5 fill-current" />
            </Button>
          </div>
          {video && (
            <div className="flex items-center">
              {cheDo !== "nho" && <NutPhu nhan="Thu nhỏ (khung nổi)" Icon={PictureInPicture2} onClick={() => p.doiCheDo("nho")} />}
              {cheDo === "rap" ? (
                <NutPhu nhan="Cỡ vừa" Icon={Minimize2} onClick={() => p.doiCheDo("vua")} chiManHinhRong />
              ) : (
                <NutPhu nhan="Chế độ rạp (hết bề ngang)" Icon={RectangleHorizontal} onClick={() => p.doiCheDo("rap")} chiManHinhRong />
              )}
              <NutPhu nhan="Toàn màn hình" Icon={Maximize} onClick={moToanManHinh} />
              <NutPhu nhan="Đóng video" Icon={X} onClick={p.dongVideo} />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
