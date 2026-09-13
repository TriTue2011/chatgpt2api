"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { layGet } from "./lib";

type Do = { nhan_hay_gap: string; ty_le: number; mau: number } | null;
type Muc = { khoa: string; ten: string; do: Do };
type Nut = {
  khoa: string;
  nhan_to_chinh: string;
  ngoai_vi: Muc[];
  dieu_kien: Muc[];
};
/** {mã thiết bị: {khoá điều kiện: số đo}} — về SAU sơ đồ, xem `/so-do/do`. */
type BangDo = Record<string, Record<string, Exclude<Do, null>>>;

function Chip({ m, khoaNut, bangDo, dangDo }: {
  m: Muc; khoaNut: string; bangDo: BangDo; dangDo: boolean;
}) {
  const so = m.khoa ? bangDo[khoaNut]?.[m.khoa] : undefined;
  return (
    <span className="rounded border border-border bg-muted/50 px-1.5 py-0.5 text-[11px]" title={m.khoa}>
      {m.ten}
      {so && so.mau > 0 ? (
        <span className="ml-1 text-muted-foreground">
          — {so.nhan_hay_gap ? `${so.nhan_hay_gap} ` : ""}{Math.round(so.ty_le * 100)}% ({so.mau} lần bật)
        </span>
      ) : dangDo ? (
        <span className="ml-1 text-muted-foreground">— đang đo…</span>
      ) : m.khoa ? (
        <span className="ml-1 text-amber-600">— chưa đo được</span>
      ) : null}
    </span>
  );
}

export function SoDo() {
  const [ds, setDs] = useState<Nut[]>([]);
  const [bangDo, setBangDo] = useState<BangDo>({});
  const [dangTai, setDangTai] = useState(false);
  const [dangDo, setDangDo] = useState(false);

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const r = await layGet<{ danh_sach?: Nut[] }>("/api/hoc-hoi/so-do");
      setDs(r.danh_sach || []);
    } finally {
      setDangTai(false);
    }
    // Đo TÁCH RIÊNG sau khi sơ đồ đã hiện: phần đo phải dựng lại bối cảnh
    // từng ô 30 phút nên tốn vài giây. Gộp chung một lượt thì cả sơ đồ mất 47
    // giây và trình duyệt bỏ cuộc trước (đo thật 12/09/2026).
    setDangDo(true);
    try {
      const d = await layGet<{ do?: BangDo }>("/api/hoc-hoi/so-do/do");
      setBangDo(d.do || {});
    } finally {
      setDangDo(false);
    }
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Chỉ áp dụng cho <b>thiết bị</b> bot đã học: nhân tố chính (thiết bị được
          bật) ← điều kiện bật trong thói quen bot đọc được + ngoại vi bot chọn theo
          khu vực. Số % là đo THẬT từ lịch sử: trong các lần có người bật, mấy lần
          khớp điều kiện. Điều kiện sai thì chấm «hh N sai vì …» để bot đọc lại.
        </p>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      {dangTai && !ds.length ? (
        <div className="flex items-center gap-2 p-2 text-xs text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" /> Đang tải…
        </div>
      ) : (
        <div className="space-y-2">
          {ds.map((n) => (
            <div key={n.khoa} className="rounded border border-border p-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-primary/10 px-2 py-0.5 font-medium text-primary">
                  {n.nhan_to_chinh}
                </span>
                <ArrowLeft className="size-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">điều kiện + ngoại vi:</span>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {n.dieu_kien.map((d) => (
                  <Chip key={d.khoa} m={d} khoaNut={n.khoa} bangDo={bangDo} dangDo={dangDo} />
                ))}
                {n.ngoai_vi.map((v, i) => (
                  <Chip key={v.khoa || `nv-${i}`} m={v} khoaNut={n.khoa} bangDo={bangDo} dangDo={dangDo} />
                ))}
                {!n.dieu_kien.length ? (
                  <span className="text-muted-foreground">chưa có thói quen nào — bot im với thiết bị này</span>
                ) : null}
              </div>
            </div>
          ))}
          {!ds.length ? (
            <p className="px-2 py-3 text-center text-muted-foreground">Chưa có thiết bị nào được học.</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
