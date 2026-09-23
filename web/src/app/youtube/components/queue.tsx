"use client";

/* QUEUE — bài phát kế tiếp, mỗi máy / mỗi loa một danh sách (chủ máy 23/09/2026).
   Cùng luật với thẻ Home Assistant 0.27.0: tích loa thì Queue của loa tích ĐẦU TIÊN,
   không tích thì Queue của máy này. Danh sách nằm trên máy chủ c2a
   (`/api/youtube-phat/queue`), chỉ mã máy nằm ở trình duyệt. */

import { AudioLines, Headphones, ListOrdered, MonitorPlay, Music2, Shuffle, Trash2, X } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { type BaiHat, goi, TEN_NGUON, thoiLuong } from "./lib";

export type MucQueue = BaiHat & { uid: string };
export type HangCho = {
  items: MucQueue[];
  current: string | null;
  mode: "video" | "audio";
  order: "sequential" | "shuffle";
  played: string[];
};

const KHOA_MA_MAY = "c2a-youtube:queue-may";
let maMayNho = "";

/** Mã của máy này. getRandomValues chứ không randomUUID: mở c2a bằng http://IP thì
 *  không phải ngữ cảnh an toàn, randomUUID không có. */
export function maMay(): string {
  if (maMayNho) return maMayNho;
  let ma = "";
  try {
    ma = localStorage.getItem(KHOA_MA_MAY) || "";
  } catch {
    /* không có kho */
  }
  if (!/^[a-z0-9-]{8,64}$/.test(ma)) {
    const b = new Uint8Array(8);
    crypto.getRandomValues(b);
    ma = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    try {
      localStorage.setItem(KHOA_MA_MAY, ma);
    } catch {
      /* chỉ sống tới khi tải lại */
    }
  }
  maMayNho = ma;
  return ma;
}

export const khoaMay = () => `device:${maMay()}`;

/** Còn bài kế không — CÙNG LUẬT `bai_ke` của `services/youtube_phat/hang_cho.py`. */
export function coBaiKe(q: HangCho | undefined): boolean {
  const items = q?.items ?? [];
  if (!q || !items.length) return false;
  if (q.order === "shuffle") {
    const da = new Set([...q.played, q.current]);
    return items.some((i) => !da.has(i.uid));
  }
  return items.findIndex((i) => i.uid === q.current) + 1 < items.length;
}

type TraQueue = { queue: HangCho; item: MucQueue | null };

/** Queue theo khoá, tải và gửi lệnh qua máy chủ. */
export function useQueue() {
  const [ds, setDs] = useState<Record<string, HangCho>>({});
  const tai = useCallback(async (khoa: string) => {
    const r = await goi<{ queue: HangCho }>(`queue?key=${encodeURIComponent(khoa)}`, undefined, true);
    if (r?.queue) setDs((cu) => ({ ...cu, [khoa]: r.queue }));
  }, []);
  const lenh = useCallback(async (khoa: string, body: Record<string, unknown>) => {
    const r = await goi<TraQueue>("queue", { key: khoa, ...body });
    if (r?.queue) setDs((cu) => ({ ...cu, [khoa]: r.queue }));
    return r;
  }, []);
  return { ds, tai, lenh };
}

type Props = {
  ten: string;
  q: HangCho | undefined;
  phatUid: (uid: string) => void;
  lenh: (body: Record<string, unknown>) => void;
};

export function BangQueue({ ten, q, phatUid, lenh }: Props) {
  const [hoiXoaHet, setHoiXoaHet] = useState(false);
  const items = q?.items ?? [];
  const cheDo = q?.mode ?? "video";
  const thuTu = q?.order ?? "sequential";
  const nutChon = (dang: boolean, nhan: string, Icon: typeof Shuffle, bam: () => void) => (
    <button
      type="button"
      aria-pressed={dang}
      onClick={bam}
      className={cn(
        "flex items-center gap-1 px-2.5 py-1 text-xs font-medium transition",
        dang ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="size-3.5" />
      {nhan}
    </button>
  );
  return (
    <div className="mt-3 space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="truncate text-sm font-semibold">Queue · {ten}</div>
        <div className="shrink-0 text-xs text-muted-foreground">{items.length} bài</div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Chế độ phát" className="flex overflow-hidden rounded-full border border-[var(--border)]">
          {nutChon(cheDo === "video", "Xem video", MonitorPlay, () => cheDo !== "video" && lenh({ action: "set", mode: "video" }))}
          {nutChon(cheDo === "audio", "Nghe audio", Headphones, () => cheDo !== "audio" && lenh({ action: "set", mode: "audio" }))}
        </div>
        <div role="group" aria-label="Thứ tự" className="flex overflow-hidden rounded-full border border-[var(--border)]">
          {nutChon(thuTu === "sequential", "Lần lượt", ListOrdered, () => thuTu !== "sequential" && lenh({ action: "set", order: "sequential" }))}
          {nutChon(thuTu === "shuffle", "Trộn bài", Shuffle, () => thuTu !== "shuffle" && lenh({ action: "set", order: "shuffle" }))}
        </div>
        {items.length > 0 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ml-auto h-7 rounded-full text-xs text-[var(--destructive)]"
            onClick={() => {
              // Xoá hết không lùi được: bấm lần đầu chỉ hỏi lại.
              if (!hoiXoaHet) {
                setHoiXoaHet(true);
                setTimeout(() => setHoiXoaHet(false), 4000);
                return;
              }
              setHoiXoaHet(false);
              lenh({ action: "clear" });
            }}
          >
            <Trash2 className="size-3.5" />
            {hoiXoaHet ? "Bấm lần nữa để xoá hết" : "Xoá tất cả"}
          </Button>
        )}
      </div>
      {!items.length ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-[var(--border)] py-8 text-center text-sm text-muted-foreground">
          <Music2 className="size-7 opacity-40" />
          Queue đang trống. Tìm bài rồi bấm nút thêm vào Queue — hết bài đang phát sẽ tự sang bài kế.
        </div>
      ) : (
        <div className="max-h-[460px] space-y-1.5 overflow-auto pr-0.5">
          {items.map((bai, i) => {
            const dangPhat = bai.uid === q?.current;
            return (
              <div
                key={bai.uid}
                role="button"
                tabIndex={0}
                title={`Phát “${bai.title || bai.id}”`}
                onClick={() => phatUid(bai.uid)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    phatUid(bai.uid);
                  }
                }}
                /* BÀI ĐANG PHÁT NỔI HẲN LÊN (chủ máy 23/09/2026). Màu thuần, KHÔNG
                   color-mix(): Safari 15 (iPhone 7, iMac macOS 12 của nhà) không hiểu
                   color-mix nên dòng sẽ mất nền đúng ở máy cần thấy nhất. */
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-xl p-2 transition",
                  dangPhat
                    ? "border-2 border-[var(--primary)] bg-[var(--muted)] shadow-md"
                    : "border border-transparent hover:bg-[var(--muted)]",
                )}
              >
                <div className={cn("w-6 shrink-0 text-center text-xs tabular-nums", dangPhat ? "text-[var(--primary)]" : "text-muted-foreground")}>
                  {dangPhat ? <AudioLines className="mx-auto size-4 animate-pulse" /> : i + 1}
                </div>
                <div className="relative aspect-video w-20 shrink-0 overflow-hidden rounded-lg bg-[var(--muted)]">
                  {/^https?:\/\//.test(bai.thumbnail) ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={bai.thumbnail} alt="" loading="lazy" className="size-full object-cover" />
                  ) : (
                    <Music2 className="absolute inset-0 m-auto size-5 text-muted-foreground" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className={cn("line-clamp-2 text-sm leading-snug", dangPhat ? "font-bold text-[var(--primary)]" : "font-medium")}>
                    {bai.title || bai.id}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                    {dangPhat && (
                      <span className="shrink-0 rounded-full bg-[var(--primary)] px-2 text-[10px] font-bold text-[var(--primary-foreground)]">
                        Đang phát
                      </span>
                    )}
                    <span className="truncate">
                      {[bai.channel || TEN_NGUON[bai.source], bai.duration ? thoiLuong(bai.duration) : ""].filter(Boolean).join(" · ")}
                    </span>
                  </div>
                </div>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="shrink-0 rounded-full text-muted-foreground"
                  aria-label={`Xoá ${bai.title || bai.id} khỏi Queue`}
                  title="Xoá khỏi Queue"
                  onClick={(e) => {
                    e.stopPropagation();
                    lenh({ action: "remove", uid: bai.uid });
                  }}
                >
                  <X />
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
