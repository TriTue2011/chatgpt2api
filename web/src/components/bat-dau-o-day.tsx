"use client";

import * as React from "react";
import Link from "next/link";
import { Check, ChevronDown, ChevronRight, CircleDashed, ArrowRight, BellOff, Undo2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { GiaiThich } from "@/components/giai-thich";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { MOC_NHAC, boTamAn, conLaiNgay, dangAn, datTamAn, docTamAn } from "@/lib/tam-an-muc";
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

function NutBoQua({ ten, khiChon }: { ten: string; khiChon: (soNgay: number) => void }) {
  const [mo, datMo] = React.useState(false);
  return (
    <Popover open={mo} onOpenChange={datMo}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Tạm ẩn mục ${ten} và hẹn nhắc lại`}
          className={cn(
            // Đo trên màn 390px: nút cao 28px, dưới ngưỡng chạm 44px nên khó
            // bấm bằng ngón cái. Nới trên điện thoại, giữ gọn ở màn lớn.
            "inline-flex min-h-[44px] shrink-0 items-center gap-1 rounded-lg px-3 text-xs",
            "sm:min-h-0 sm:px-2 sm:py-1.5",
            "text-[var(--muted-foreground)] transition-colors",
            "hover:bg-[var(--secondary)] hover:text-[var(--foreground)]",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
          )}
        >
          <BellOff className="size-3.5" aria-hidden />
          Bỏ qua
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-1.5">
        <p className="px-2 py-1.5 text-[11px] leading-snug text-[var(--muted-foreground)]">
          Ẩn mục này và nhắc lại sau:
        </p>
        {MOC_NHAC.map((m) => (
          <button
            key={m.ngay}
            type="button"
            onClick={() => { khiChon(m.ngay); datMo(false); }}
            className={cn(
              "flex w-full items-center rounded-md px-2 py-1.5 text-left text-[13px]",
              "text-[var(--foreground)] transition-colors hover:bg-[var(--secondary)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
            )}
          >
            {m.nhan}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}

function Dong({ muc, xong, khiBoQua }: { muc: MucTinhNang; xong: boolean; khiBoQua?: (soNgay: number) => void }) {
  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-xl border border-[var(--border)] p-3",
        "sm:flex-row sm:items-start sm:gap-3",
        xong ? "bg-transparent" : "bg-[var(--surface-2)]",
      )}
    >
      <div className="flex min-w-0 flex-1 items-start gap-3">
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
          <p className="mt-1 max-w-[78ch] text-[13px] leading-relaxed text-[var(--muted-foreground)]">
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
      </div>

      {!xong && khiBoQua && (
        <div className="flex w-full items-center justify-end sm:w-auto sm:self-center">
          <NutBoQua ten={muc.ten} khiChon={khiBoQua} />
        </div>
      )}

      {!xong && (
        <Link
          href={muc.duong}
          className={cn(
            "inline-flex shrink-0 items-center justify-center gap-1 rounded-lg px-2.5 py-2",
            "w-full sm:w-auto sm:self-center sm:py-1.5",
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
  // localStorage không tồn tại lúc dựng tĩnh, nên đọc SAU khi gắn vào DOM —
  // đọc ngay trong lượt render đầu sẽ lệch giữa HTML dựng sẵn và lần render
  // đầu ở trình duyệt.
  const [tamAn, datTamAnState] = React.useState<Record<string, number>>({});
  React.useEffect(() => { datTamAnState(docTamAn()); }, []);

  const conThieuTatCa = mucConThieu(tt);
  const { xong, tong } = tienDo(tt);
  // Hết hạn ẩn thì `dangAn` trả false, mục tự hiện lại — không cần dọn gì.
  const thieu = conThieuTatCa.filter((m) => !dangAn(tamAn, m.id));
  const dangAnDs = conThieuTatCa.filter((m) => dangAn(tamAn, m.id));
  const batBuocThieu = thieu.filter((m) => m.mucDo === "bat-buoc");
  const daXong = mucDaXong(tt);

  // Chưa API nào về thì không kết luận gì. Kết luận sớm sẽ chớp một nhịp
  // "thiếu mọi thứ" — đúng cái nhịp làm người mới cài hoảng.
  if (tong === 0) return null;

  // Ẩn KHÔNG phải là xong: còn mục đang ẩn thì chưa được nói "đã sẵn sàng".
  const donXong = conThieuTatCa.length === 0;

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

      <p className="mt-1.5 max-w-[78ch] text-[13px] leading-relaxed text-[var(--muted-foreground)]">
        {donXong
          ? "Mọi mục kiểm được đều đã cấu hình. Phần còn lại trong Cài đặt là tuỳ chọn, bật khi cần."
          : "Làm từ trên xuống. Mục bắt buộc chưa xong thì hệ thống chưa trả lời được lời gọi nào."}
      </p>

      {thieu.length > 0 && (
        <ul className="mt-4 space-y-2">
          {thieu.map((m) => (
            <Dong
              key={m.id}
              muc={m}
              xong={false}
              khiBoQua={(soNgay) => datTamAnState(datTamAn(m.id, soNgay))}
            />
          ))}
        </ul>
      )}

      {/* Mục đang tạm ẩn luôn được đếm ra ở đây, kèm nút hiện lại — bỏ qua là
          HOÃN chứ không phải xoá, nên không thứ gì biến mất lặng lẽ. */}
      {dangAnDs.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-[var(--muted-foreground)]">
          <span>
            {dangAnDs.length} mục đang tạm ẩn
            {dangAnDs.length <= 3 && (
              <> ({dangAnDs.map((m) => `${m.ten} — còn ${conLaiNgay(tamAn, m.id)} ngày`).join("; ")})</>
            )}
          </span>
          <button
            type="button"
            onClick={() => datTamAnState(boTamAn())}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg px-2 py-1",
              "text-[var(--foreground)] transition-colors hover:bg-[var(--secondary)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
            )}
          >
            <Undo2 className="size-3.5" aria-hidden />
            Hiện lại
          </button>
        </div>
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
