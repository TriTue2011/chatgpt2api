"use client";

/**
 * Khối "Đang phát" — bài của loa đang xem (hoặc video), tiến độ, nút điều khiển, cỡ xem.
 *
 * Chủ máy 14/09/2026: "khi xem video thì mục đang phát cũng là nó thì bỏ đi",
 * "nút điều khiển đang to", "mở mỗi bài 1 loa thì làm sao xem nó phát đến đâu,
 * video đến đâu khi tích vào mỗi loa". Video thay chỗ ảnh bìa; thanh tiến độ theo
 * loa dẫn của phiên đang xem; nhóm loa khác hiện thành nút để chuyển sang xem.
 * Khung iframe luôn nằm cùng một chỗ trong cây React (đổi cỡ chỉ đổi lớp CSS), nên
 * đổi Vừa / Rạp / Thu nhỏ không làm video nạp lại.
 */

import {
  ListMusic, LoaderCircle, MonitorOff, Maximize, Maximize2, Minimize2, MonitorPlay, Music2, Pause, PictureInPicture2, Play,
  RectangleHorizontal, SkipBack, SkipForward, Speaker, Square, Users, Volume2, VolumeX, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { type BaiHat, type Phien, TEN_NGUON, type ThietBi, thoiLuong } from "./lib";
import type { CheDoXem, VideoNhung } from "./video-nhung";

export type VideoMo = { bai: BaiHat; src: string; theoLoa: boolean; ngheTrenMay: boolean; theoMay?: boolean };
export type ViTri = { giay: number; tong: number } | null;

type Props = {
  className?: string;
  phien: Phien | null;
  cacPhienKhac: Phien[];
  ngheCungTen: string[];
  thietBi: ThietBi[];
  video: VideoMo | null;
  /** Bài đang nghe trên máy này bằng thẻ âm thanh (nghe khi tắt màn hình, hoặc Zing). */
  nghe: BaiHat | null;
  hang: { index: number; items: BaiHat[] } | null;
  /** Nghe khi tắt màn hình: tiếng trên máy phát bằng thẻ âm thanh. */
  ngheNen: boolean;
  doiNgheNen: () => void;
  /** Trình duyệt chặn tiếng tự phát: bảo người xem chạm vào khung video. */
  canCham: boolean;
  nhung: VideoNhung;
  cheDo: CheDoXem;
  doiCheDo: (c: CheDoXem) => void;
  dongVideo: () => void;
  dangChay: boolean;
  dangGui: boolean;
  layViTri: () => ViTri;
  truoc: (() => void) | null;
  tiep: (() => void) | null;
  phatTamDung: (() => void) | null;
  dung: (() => void) | null;
  xemTaiDay: (() => void) | null;
  chonNhom: (p: Phien) => void;
  ngheCung: (() => void) | null;
  /** Đang phát ra loa: máy này có nghe cùng không (null = không áp dụng, ẩn nút). */
  tiengTrenMay: boolean | null;
  doiNgheTrenMay: () => void;
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

/** Thanh tiến độ tự nhích mỗi giây, đọc vị trí qua `layViTri`. */
function TienDo({ layViTri }: { layViTri: () => ViTri }) {
  const [vt, setVt] = useState<ViTri>(null);
  const lay = useRef(layViTri);
  useEffect(() => {
    lay.current = layViTri;
  });
  useEffect(() => {
    const cap = () => setVt(lay.current());
    const dau = setTimeout(cap, 0);
    const hen = setInterval(cap, 1000);
    return () => {
      clearTimeout(dau);
      clearInterval(hen);
    };
  }, []);
  if (!vt) return null;
  const giay = vt.tong ? Math.min(vt.giay, vt.tong) : vt.giay;
  return (
    <div className="mt-2 grid grid-cols-[auto_1fr_auto] items-center gap-2 text-[11px] tabular-nums text-muted-foreground" aria-label="Tiến độ">
      <span>{thoiLuong(giay) || "0:00"}</span>
      <div className="h-1 overflow-hidden rounded-full bg-[var(--muted)]">
        <div className="h-full rounded-full bg-[var(--primary)] transition-[width] duration-1000 ease-linear" style={{ width: vt.tong ? `${(giay / vt.tong) * 100}%` : "0%" }} />
      </div>
      <span>{thoiLuong(vt.tong) || "–"}</span>
    </div>
  );
}

export function DangPhat(p: Props) {
  const { video, nhung, cheDo } = p;
  const toanManHinh = useRef<HTMLDivElement>(null);
  const bai = video?.bai ?? p.nghe ?? p.phien?.item ?? null;
  const tenTheoMa = new Map(p.thietBi.map((t) => [t.entity_id, t.ten]));
  const noiPhat = p.nghe ? [] : (p.phien?.output_entity_ids ?? []).map((id) => tenTheoMa.get(id) ?? id);
  const hang = p.hang;
  const anh = bai && /^https?:\/\//.test(bai.thumbnail || "") ? bai.thumbnail : "";
  const nho = !!video && cheDo === "nho";

  const meta = bai
    ? video
      ? [bai.channel || bai.artist, video.theoMay ? "Tiếng từ máy này (nghe cả khi tắt màn hình)" : video.theoLoa && noiPhat.length ? `Tiếng ra ${noiPhat.join(", ")}${p.tiengTrenMay ? " và máy này" : ""}` : "Xem trên trang"]
      : [bai.artist || bai.channel, TEN_NGUON[bai.source], p.nghe ? "Nghe trên máy này (cả khi tắt màn hình)" : noiPhat.length ? `Trên ${noiPhat.join(", ")}${p.tiengTrenMay ? " và máy này" : ""}` : ""]
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
            {p.nghe ? (p.dangChay ? "Đang nghe trên máy này" : "Tạm dừng") : bai ? (p.dangChay ? "Đang phát" : "Đã gửi") : "Chưa phát"}
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
              {p.canCham && (
                <span className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 whitespace-nowrap rounded-full bg-black/75 px-3 py-1 text-xs font-semibold text-white">
                  {nhung.trangThai === 1 ? "🔇 Chạm vào video để bật tiếng" : "▶ Chạm vào video để phát có tiếng"}
                </span>
              )}
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
          {bai
            ? meta.filter(Boolean).join(" · ")
            : "Tích loa rồi phát một bài ra loa, hoặc chưa tích loa thì nghe hay xem video ngay trên máy này."}
        </div>
        {bai && <TienDo key={`${p.nghe ? "nghe" : p.phien?.session_id ?? "video"}:${bai.id}`} layViTri={p.layViTri} />}

        <div className="mt-2 flex flex-wrap items-center justify-between gap-1">
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
            <Button type="button" variant="ghost" size="icon" className="size-9 rounded-full text-red-600 hover:text-red-600 dark:text-red-400" aria-label="Dừng" title="Dừng các loa đang tích" disabled={!p.dung} onClick={() => p.dung?.()}>
              <Square className="size-3.5 fill-current" />
            </Button>
          </div>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-1">
            {p.tiengTrenMay !== null && (
              <button
                type="button"
                onClick={p.doiNgheTrenMay}
                aria-pressed={p.tiengTrenMay}
                aria-label={p.tiengTrenMay ? "Tắt tiếng trên máy này (chỉ nghe loa)" : "Nghe cả trên máy này"}
                title={p.tiengTrenMay ? "Tắt tiếng trên máy này — chỉ nghe loa" : "Nghe cả trên máy này, chạy theo loa"}
                className={cn(
                  "flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition",
                  p.tiengTrenMay
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "border-[var(--border)] text-muted-foreground hover:border-[var(--primary)]",
                )}
              >
                {p.tiengTrenMay ? <Volume2 className="size-3.5" /> : <VolumeX className="size-3.5" />} Nghe trên máy này
              </button>
            )}
            <button
              type="button"
              onClick={p.doiNgheNen}
              aria-pressed={p.ngheNen}
              title={p.ngheNen
                ? "Đang bật: tắt màn hình vẫn nghe tiếp trên máy này. Bấm để tắt."
                : "Đang tắt: tắt màn hình thì tiếng trên máy này dừng. Bấm để nghe tiếp cả khi tắt màn hình."}
              className={cn(
                "flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition",
                p.ngheNen
                  ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "border-[var(--border)] text-muted-foreground hover:border-[var(--primary)]",
              )}
            >
              <MonitorOff className="size-3.5" /> Nghe khi tắt màn hình
            </button>
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

        {(p.ngheCung || p.cacPhienKhac.length > 0) && (
          <div className="mt-2 flex flex-wrap gap-1.5 border-t border-[var(--border)] pt-2">
            {p.ngheCung && (
              <button
                type="button"
                onClick={p.ngheCung}
                className="flex max-w-full items-center gap-1.5 rounded-full border border-dashed border-[var(--primary)] px-2.5 py-1 text-xs font-medium text-[var(--primary)]"
              >
                <Users className="size-3.5 shrink-0" />
                <span className="truncate">Cho {p.ngheCungTen.join(", ")} nghe cùng</span>
              </button>
            )}
            {p.cacPhienKhac.map((khac) => {
              const ten = khac.output_entity_ids.map((id) => tenTheoMa.get(id) ?? id).join(", ");
              const hinh = khac.item && /^https?:\/\//.test(khac.item.thumbnail || "") ? khac.item.thumbnail : "";
              return (
                <button
                  key={khac.session_id}
                  type="button"
                  onClick={() => p.chonNhom(khac)}
                  title={`${ten}: ${khac.item?.title ?? ""}`}
                  className="flex max-w-full items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--muted)] py-0.5 pl-0.5 pr-2.5 text-xs hover:border-[var(--primary)]"
                >
                  {hinh ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={hinh} alt="" className="size-5 shrink-0 rounded-full object-cover" />
                  ) : (
                    <Speaker className="size-4 shrink-0 text-muted-foreground" />
                  )}
                  <span className="truncate">{ten} · {khac.item?.title}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
