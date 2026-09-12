"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { layGet } from "./lib";

type Nut = {
  khoa: string;
  nhan_to_chinh: string;
  ngoai_vi: string[];
  dieu_kien: string[];
};

export function SoDo() {
  const [ds, setDs] = useState<Nut[]>([]);
  const [dangTai, setDangTai] = useState(false);

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const r = await layGet<{ danh_sach?: Nut[] }>("/api/hoc-hoi/so-do");
      setDs(r.danh_sach || []);
    } finally {
      setDangTai(false);
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
          bật) ← điều kiện + ngoại vi đi kèm.
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
                {n.dieu_kien.map((c, i) => (
                  <span key={`dk-${i}`} className="rounded border border-border bg-muted/50 px-1.5 py-0.5">
                    {c}
                  </span>
                ))}
                {n.ngoai_vi.map((c, i) => (
                  <span key={`nv-${i}`} className="rounded border border-dashed border-border px-1.5 py-0.5 text-muted-foreground">
                    {c}
                  </span>
                ))}
                {!n.dieu_kien.length && !n.ngoai_vi.length ? (
                  <span className="text-muted-foreground">chưa có điều kiện nào</span>
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
