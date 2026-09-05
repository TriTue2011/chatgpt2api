"use client";

import * as React from "react";
import { HelpCircle } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { timMuc } from "@/lib/feature-registry";

type Props = {
  /** Mã mục trong sổ tra — lấy sẵn mục đích và yêu cầu. */
  id?: string;
  /** Hoặc tự khai, dùng cho chỗ chưa có trong sổ tra. */
  mucDich?: string;
  canGi?: string;
  /** Bọc quanh phần tử khác thay vì hiện dấu hỏi. */
  children?: React.ReactNode;
  className?: string;
};

/**
 * Máy có rê chuột thật hay không.
 *
 * Tooltip mở khi rê chuột là vô dụng trên màn cảm ứng — ngón tay không có
 * trạng thái "đang rê". Ở đó phải đổi sang bấm-để-mở, nếu không thì phần giải
 * thích chỉ một nửa người dùng đọc được.
 *
 * Mặc định `true` để bản dựng tĩnh và bản trên máy khớp nhau lúc hydrate; giá
 * trị thật cập nhật ngay ở effect đầu tiên.
 */
function useCoReChuot() {
  const [coRe, datCoRe] = React.useState(true);
  React.useEffect(() => {
    const mq = window.matchMedia("(hover: hover) and (pointer: fine)");
    const capNhat = () => datCoRe(mq.matches);
    capNhat();
    mq.addEventListener("change", capNhat);
    return () => mq.removeEventListener("change", capNhat);
  }, []);
  return coRe;
}

function NoiDung({ mucDich, canGi }: { mucDich: string; canGi?: string }) {
  return (
    <div className="space-y-1.5">
      <p className="text-[var(--popover-foreground)]">{mucDich}</p>
      {canGi ? (
        <p className="border-t border-[var(--border)] pt-1.5 text-[var(--muted-foreground)]">
          <span className="font-medium text-[var(--foreground)]">Cần: </span>
          {canGi}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Dấu hỏi giải thích một chức năng: nó dùng để làm gì và cần gì mới dùng được.
 *
 *   <GiaiThich id="tai-khoan" />
 *   <GiaiThich mucDich="..." canGi="..." />
 *   <GiaiThich id="sao-luu">Sao lưu tự động</GiaiThich>
 */
export function GiaiThich({ id, mucDich, canGi, children, className }: Props) {
  const coReChuot = useCoReChuot();
  const muc = id ? timMuc(id) : undefined;
  const noiDungChinh = mucDich ?? muc?.mucDich;
  const yeuCau = canGi ?? muc?.canGi;

  // Không có gì để nói thì đừng thêm một dấu hỏi rỗng vào giao diện.
  if (!noiDungChinh) return children ? <>{children}</> : null;

  const nhan = muc?.ten ? `Giải thích: ${muc.ten}` : "Giải thích";
  const moc = children ?? (
    <HelpCircle
      aria-hidden
      className="size-3.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
    />
  );
  const lopMoc = cn(
    "inline-flex shrink-0 cursor-help items-center rounded-full align-middle",
    "outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-1",
    "focus-visible:ring-offset-[var(--background)]",
    className,
  );

  if (!coReChuot) {
    // Màn cảm ứng: bấm để mở, và phải là <button> thì bàn phím với trình đọc
    // màn hình mới tới được.
    return (
      <Popover>
        <PopoverTrigger aria-label={nhan} className={lopMoc}>
          {moc}
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="max-w-[min(20rem,calc(100vw-2rem))] p-3 text-xs leading-relaxed"
        >
          <NoiDung mucDich={noiDungChinh} canGi={yeuCau} />
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger aria-label={nhan} className={lopMoc}>
        {moc}
      </TooltipTrigger>
      <TooltipContent side="top" align="start">
        <NoiDung mucDich={noiDungChinh} canGi={yeuCau} />
      </TooltipContent>
    </Tooltip>
  );
}
