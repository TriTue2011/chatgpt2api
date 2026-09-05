"use client";

import * as React from "react";
import Link from "next/link";
import { Check, ChevronDown, ChevronRight, CircleDashed, ArrowRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { GiaiThich } from "@/components/giai-thich";
import {
  NHAN_MUC_DO,
  mucConThieu,
  mucDaXong,
  tienDo,
  type MucDo,
  type MucTinhNang,
  type TrangThaiHeThong,
} from "@/lib/feature-registry";

/**
 * "Bắt đầu ở đây" — trả lời bốn câu của người vừa cài xong:
 * cài gì trước, cái nào bắt buộc, cái đó để làm gì, đang thiếu gì.
 *
 * Vì sao trang chủ không đủ: nó là bảng KPI (số lượt gọi, token, chi phí). Trên
 * máy vừa dựng thì mọi số đều bằng 0 và không câu nào nói được phải làm gì
 * tiếp. Bảng đó hữu ích cho người đã chạy được, vô dụng cho người chưa bắt đầu.
 *
 * Trạng thái đọc từ cấu hình THẬT, không phải cờ "đã xem hướng dẫn" — nên nó
 * không bao giờ báo xong trong khi hệ thống chưa chạy được.
 */

const MAU_MUC_DO: Record<MucDo, string> = {
  "bat-buoc": "border-[var(--destructive)]/35 text-[var(--destructive)]",
  "nen-co": "border-[var(--primary)]/35 text-[var(--primary)]",
  "tuy-chon": "border-[var(--border)] text-[var(--muted-foreground)]",
};

function HuyHieu({ mucDo }: { mucDo: MucDo }) {
  return (
    <span
      className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        MAU_MUC_DO[mucDo],
      )}
    >
      {NHAN_MUC_DO[mucDo]}
    </span>
  );
}

function Dong({ muc, xong }: { muc: MucTinhNang; xong: boolean }) {
  return (
    <li
      className={cn(
        "flex items-start gap-3 rounded-xl border border-[var(--border)] p-3",
        xong ? "bg-transparent" : "bg-[var(--surface-2)]",
      )}
    >
      {xong ? (
        <Check className="mt-0.5 size-4 shrink-0 text-[var(--tone-ok,var(--primary))]" aria-hidden />
      ) : (
        <CircleDashed className="mt-0.5 size-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden />
      )}

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "text-sm font-medium",
              xong ? "text-[var(--muted-foreground)] line-through" : "text-[var(--foreground)]",
            )}
          >
            {muc.ten}
          </span>
          {!xong && <HuyHieu mucDo={muc.mucDo} />}
          <GiaiThich id={muc.id} />
        </div>

        {!xong && (
          <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
            {muc.mucDich}
            {muc.canGi ? (
              <>
                {" "}
                <span className="text-[var(--foreground)]">Cần:</span> {muc.canGi}
              </>
            ) : null}
          </p>
        )}
      </div>

      {!xong && (
        <Link
          href={muc.duong}
          className={cn(
            "inline-flex shrink-0 items-center gap-1 self-center rounded-lg px-2.5 py-1.5",
            "bg-[var(--primary)] text-xs font-medium text-[var(--primary-foreground)]",
            "transition-[filter] hover:brightness-110 active:scale-[0.98]",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
          )}
        >
          Cấu hình
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      )}
    </li>
  );
}

export function BatDauODay({ tt }: { tt: TrangThaiHeThong }) {
  const [moRong, datMoRong] = React.useState(false);

  const thieu = mucConThieu(tt);
  const { xong, tong } = tienDo(tt);
  const batBuocThieu = thieu.filter((m) => m.mucDo === "bat-buoc");
  const daXong = mucDaXong(tt);

  // Chưa API nào về thì không kết luận gì. Kết luận sớm sẽ chớp một nhịp
  // "thiếu mọi thứ" — đúng cái nhịp làm người mới cài hoảng.
  if (tong === 0) return null;

  const donXong = thieu.length === 0;

  return (
    <section
      className={cn(
        "rounded-2xl border p-4 sm:p-5",
        batBuocThieu.length > 0
          ? "border-[var(--destructive)]/30 bg-[var(--surface-1)]"
          : "border-[var(--border)] bg-[var(--surface-1)]",
      )}
      aria-labelledby="bat-dau-tieu-de"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 id="bat-dau-tieu-de" className="text-base font-semibold text-[var(--foreground)]">
          {donXong ? "Hệ thống đã sẵn sàng" : "Bắt đầu ở đây"}
        </h2>
        <span className="text-xs text-[var(--muted-foreground)]">
          {xong}/{tong} mục đã cấu hình
        </span>
        {batBuocThieu.length > 0 && (
          <span className="rounded-full border border-[var(--destructive)]/35 px-2 py-0.5 text-[10px] font-medium text-[var(--destructive)]">
            Còn {batBuocThieu.length} mục bắt buộc
          </span>
        )}
      </div>

      <p className="mt-1.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {donXong
          ? "Mọi mục kiểm được đều đã cấu hình. Phần còn lại trong Cài đặt là tuỳ chọn, bật khi cần."
          : "Làm từ trên xuống. Mục bắt buộc chưa xong thì hệ thống chưa trả lời được lời gọi nào."}
      </p>

      {thieu.length > 0 && (
        <ul className="mt-4 space-y-2">
          {thieu.map((m) => (
            <Dong key={m.id} muc={m} xong={false} />
          ))}
        </ul>
      )}

      {xong > 0 && (
        <>
          <button
            type="button"
            onClick={() => datMoRong((v) => !v)}
            aria-expanded={moRong}
            className={cn(
              "mt-3 inline-flex items-center gap-1 rounded-lg py-1 text-xs",
              "text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
            )}
          >
            {moRong ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            {moRong ? "Ẩn" : "Xem"} {xong} mục đã xong
          </button>

          {moRong && (
            <ul className="mt-2 space-y-2">
              {daXong.map((m) => (
                <Dong key={m.id} muc={m} xong />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

/** Dải một dòng cho người đã cấu hình xong — không chắn đường lên KPI. */
export function DaiTienDo({ tt }: { tt: TrangThaiHeThong }) {
  const { xong, tong } = tienDo(tt);
  if (tong === 0) return null;
  return (
    <Link
      href="/settings"
      className={cn(
        "flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-1)]",
        "px-3 py-2 text-xs text-[var(--muted-foreground)] transition-colors",
        "hover:border-[var(--primary)]/40 hover:text-[var(--foreground)]",
      )}
    >
      <Check className="size-3.5 shrink-0 text-[var(--primary)]" aria-hidden />
      <span>
        Đã cấu hình {xong}/{tong} mục. Phần còn lại là tuỳ chọn.
      </span>
      <ChevronRight className="ml-auto size-3.5 shrink-0" aria-hidden />
    </Link>
  );
}
