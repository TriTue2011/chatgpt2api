"use client";

/**
 * Loa & tivi — tích để xem/điều khiển loa (không tự phát hay tắt loa), chỉnh âm
 * lượng từng thiết bị, ẩn thiết bị không dùng.
 *
 * Chủ máy 14/09/2026: "nhiều trường hợp hiển thị quá nhiều thiết bị không cần" →
 * nút ẩn trên từng thiết bị; sổ ẩn nằm ở máy chủ (DATA_DIR) nên khởi động lại hay
 * cập nhật ảnh không mất, và mục "Đã ẩn" khôi phục lại được bất cứ lúc nào.
 */

import { useState } from "react";
import { Check, ChevronDown, EyeOff, LoaderCircle, RefreshCw, Speaker, Tv, Undo2, Volume2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { NHAN_KET_NOI, type ThietBi } from "./lib";

const TRANG_THAI: Record<string, string> = {
  playing: "Đang phát",
  paused: "Tạm dừng",
  buffering: "Đang tải",
  idle: "Sẵn sàng",
  on: "Đang bật",
  off: "Đang tắt",
  standby: "Chờ",
  unavailable: "Mất kết nối",
};

function mauCham(trangThai: string): string {
  if (trangThai === "playing" || trangThai === "buffering") return "bg-emerald-500";
  if (trangThai === "unavailable") return "bg-red-500";
  if (trangThai === "off" || trangThai === "standby") return "bg-zinc-400";
  return "bg-amber-500";
}

type Props = {
  className?: string;
  thietBi: ThietBi[] | null;
  loi: string;
  chon: Set<string>;
  batTat: (tb: ThietBi) => void;
  amLuong: (tb: ThietBi, v: number) => void;
  an: (ids: string[], an: boolean) => Promise<void>;
  taiLai: () => void;
};

function ThanhAmLuong({ tb, amLuong }: { tb: ThietBi; amLuong: Props["amLuong"] }) {
  const [nhap, setNhap] = useState<number | null>(null);
  const v = nhap ?? tb.am_luong ?? 0.3;
  const gui = () => {
    if (nhap !== null) amLuong(tb, nhap);
    setNhap(null);
  };
  return (
    <div className="flex items-center gap-2 px-3 pb-3 pl-[3.25rem]">
      <Volume2 className="size-3.5 shrink-0 text-muted-foreground" />
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={v}
        aria-label={`Âm lượng ${tb.ten}`}
        className="h-1.5 flex-1 cursor-pointer accent-[var(--primary)]"
        onChange={(e) => setNhap(Number(e.target.value))}
        onPointerUp={gui}
        onKeyUp={gui}
      />
      <span className="w-9 text-right text-[11px] tabular-nums text-muted-foreground">{Math.round(v * 100)}%</span>
    </div>
  );
}

export function DanhSachThietBi({ className, thietBi, loi, chon, batTat, amLuong, an, taiLai }: Props) {
  const [moAn, setMoAn] = useState(false);
  const [dangAn, setDangAn] = useState("");
  // Thiết bị mất kết nối không hiện, tự hiện lại khi HA báo kết nối.
  const conKetNoi = (thietBi ?? []).filter((t) => t.trang_thai !== "unavailable");
  const soMatKetNoi = (thietBi?.length ?? 0) - conKetNoi.length;
  const hien = conKetNoi.filter((t) => !t.an);
  const daAn = conKetNoi.filter((t) => t.an);

  const doiAn = async (ids: string[], giaTri: boolean) => {
    setDangAn(ids.join(","));
    await an(ids, giaTri);
    setDangAn("");
    // Mục "Đã ẩn" luôn gập sẵn: khôi phục hết thì gập lại, để lần ẩn sau không bung ra.
    if (!giaTri && daAn.every((t) => ids.includes(t.entity_id))) setMoAn(false);
  };

  return (
    <section className={cn("rounded-2xl border border-[var(--border)] bg-[var(--card)]", className)}>
      <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-4">
        <div>
          <h2 className="text-sm font-semibold">Loa &amp; tivi</h2>
          <p className="text-xs text-muted-foreground">
            {chon.size ? `${chon.size} đang tích` : "Tích loa để xem và phát"}
            {soMatKetNoi > 0 ? ` · ${soMatKetNoi} mất kết nối, tự hiện khi kết nối lại` : ""}
          </p>
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="Tải lại danh sách" onClick={taiLai}>
          <RefreshCw />
        </Button>
      </div>

      {loi && <p className="mx-4 mb-2 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-700 dark:text-red-400">{loi}</p>}

      {thietBi === null ? (
        <div className="flex h-24 items-center justify-center"><LoaderCircle className="size-4 animate-spin text-muted-foreground" /></div>
      ) : !hien.length ? (
        <p className="px-4 pb-4 text-sm text-muted-foreground">
          {daAn.length
            ? "Mọi thiết bị đang ẩn — mở mục Đã ẩn để khôi phục."
            : soMatKetNoi
              ? "Chưa có loa hay tivi nào đang kết nối."
              : "Home Assistant chưa có loa hay tivi nào."}
        </p>
      ) : (
        <ul className="space-y-1 px-2 pb-2">
          {hien.map((tb) => {
            const daChon = chon.has(tb.entity_id);
            const Icon = tb.loai === "tivi" ? Tv : Speaker;
            const matKetNoi = tb.trang_thai === "unavailable";
            return (
              <li
                key={tb.entity_id}
                className={cn(
                  "rounded-xl transition",
                  daChon ? "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)]" : "hover:bg-[var(--muted)]",
                )}
              >
                <div className="flex items-center gap-1 pr-1">
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={daChon}
                    disabled={!tb.phat_duoc}
                    onClick={() => batTat(tb)}
                    title={tb.entity_id}
                    className="flex min-w-0 flex-1 items-center gap-3 rounded-xl p-2.5 text-left disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <span
                      className={cn(
                        "relative flex size-9 shrink-0 items-center justify-center rounded-lg",
                        daChon ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "bg-[var(--muted)] text-muted-foreground",
                      )}
                    >
                      {daChon ? <Check className="size-4" /> : <Icon className="size-4" />}
                    </span>
                    <span className={cn("min-w-0 flex-1", matKetNoi && "opacity-60")}>
                      <span className="block truncate text-sm font-medium">{tb.ten}</span>
                      <span className="flex items-center gap-1.5 truncate text-[11px] text-muted-foreground">
                        <span className={cn("size-1.5 shrink-0 rounded-full", mauCham(tb.trang_thai))} />
                        <span className="truncate">
                          {TRANG_THAI[tb.trang_thai] ?? tb.trang_thai} · {NHAN_KET_NOI[tb.transport] ?? tb.transport}
                          {tb.so_loa ? (tb.qua === "c2a" ? " · Sổ loa c2a" : " · Sổ loa c2a qua HA") : ""}
                          {tb.trang_thai === "playing" && tb.tieu_de ? ` · ${tb.tieu_de}` : ""}
                        </span>
                      </span>
                    </span>
                  </button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8 shrink-0 text-muted-foreground"
                    aria-label={`Ẩn ${tb.ten}`}
                    title="Ẩn thiết bị này (khôi phục ở mục Đã ẩn)"
                    disabled={!!dangAn}
                    onClick={() => void doiAn([tb.entity_id], true)}
                  >
                    {dangAn === tb.entity_id ? <LoaderCircle className="animate-spin" /> : <EyeOff className="size-3.5" />}
                  </Button>
                </div>
                {daChon && tb.chinh_am_luong && !matKetNoi && <ThanhAmLuong tb={tb} amLuong={amLuong} />}
              </li>
            );
          })}
        </ul>
      )}

      {daAn.length > 0 && (
        <div className="border-t border-[var(--border)] px-2 py-2">
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setMoAn((v) => !v)}
              aria-expanded={moAn}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              <ChevronDown className={cn("size-3.5 transition", moAn && "rotate-180")} />
              Đã ẩn ({daAn.length})
            </button>
            {moAn && daAn.length > 1 && (
              <Button type="button" variant="ghost" size="sm" disabled={!!dangAn} onClick={() => void doiAn(daAn.map((t) => t.entity_id), false)}>
                <Undo2 /> Khôi phục tất cả
              </Button>
            )}
          </div>
          {moAn && (
            <ul className="mt-1 space-y-0.5">
              {daAn.map((tb) => (
                <li key={tb.entity_id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-muted-foreground">{tb.ten}</span>
                    <span className="block truncate font-mono text-[10px] text-muted-foreground/70">{tb.entity_id}</span>
                  </span>
                  <Button type="button" variant="outline" size="sm" disabled={!!dangAn} onClick={() => void doiAn([tb.entity_id], false)}>
                    {dangAn === tb.entity_id ? <LoaderCircle className="animate-spin" /> : <Undo2 />} Khôi phục
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
