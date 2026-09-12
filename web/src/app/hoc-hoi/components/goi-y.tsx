"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { httpRequest } from "@/lib/request";
import { layGet, goiPost } from "./lib";

/** Bản xem trước — bot đang nghĩ gì NGAY LÚC NÀY, chưa ghi, chưa có id. */
type XemTruoc = { ten: string; p: number; cach: string; ly_do?: string };
/** Gợi ý ĐÃ GỬI, còn chờ chấm — có id thật, chấm/xoá được. */
type ChoCham = { id: number; ten: string; hanh_dong: string; p: number };
type ThongKeRow = { ten: string; dung: number; sai: number; diem: number; cap: number; con_thieu_luot: number };

export function GoiY() {
  const [xemTruoc, setXemTruoc] = useState<XemTruoc[]>([]);
  const [choCham, setChoCham] = useState<ChoCham[]>([]);
  const [thongKe, setThongKe] = useState<ThongKeRow[]>([]);
  const [dangTai, setDangTai] = useState(false);

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const [xt, cc] = await Promise.all([
        layGet<{ dang_nghi?: XemTruoc[]; thong_ke?: { thanh_tich?: ThongKeRow[] } }>("/api/mqtt/du-doan"),
        layGet<{ danh_sach?: ChoCham[] }>("/api/hoc-hoi/du-doan/cho-cham"),
      ]);
      setXemTruoc(xt.dang_nghi || []);
      setThongKe(xt.thong_ke?.thanh_tich || []);
      setChoCham(cc.danh_sach || []);
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  const cham = async (id: number, dung: boolean) => {
    const res = await httpRequest<{ ok?: boolean }>("/api/mqtt/du-doan/cham", { method: "POST", body: { id, dung } });
    if (res?.ok) void tai();
  };
  const xoa = async (id: number) => {
    if (await goiPost("/api/hoc-hoi/du-doan/xoa", { id })) void tai();
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      <section>
        <p className="mb-1 text-xs font-semibold">Gợi ý đã gửi, còn chờ chấm</p>
        <div className="max-h-64 overflow-auto rounded border border-border">
          {choCham.map((n) => (
            <div key={n.id} className="border-b border-border/60 px-2 py-1.5 text-xs last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{n.ten}</span>
                <span className="text-muted-foreground">{n.hanh_dong} · {(n.p * 100).toFixed(0)}%</span>
              </div>
              <div className="mt-1 flex gap-1">
                <Button variant="outline" size="sm" className="h-7" onClick={() => void cham(n.id, true)}>Đúng</Button>
                <Button variant="outline" size="sm" className="h-7" onClick={() => void cham(n.id, false)}>Sai</Button>
                <Button variant="ghost" size="sm" className="h-7 text-destructive" onClick={() => void xoa(n.id)}>
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </div>
          ))}
          {!choCham.length && !dangTai ? (
            <p className="px-2 py-3 text-center text-xs text-muted-foreground">Chưa có gợi ý nào chờ chấm.</p>
          ) : null}
          {dangTai && !choCham.length ? (
            <div className="flex items-center gap-2 p-2 text-xs text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" /> Đang tải…
            </div>
          ) : null}
        </div>
      </section>

      <section>
        <p className="mb-1 text-xs font-semibold">Bot đang nghĩ gì (xem trước, chưa gửi)</p>
        <div className="max-h-48 overflow-auto rounded border border-border">
          {xemTruoc.map((n, i) => (
            <div key={`${n.ten}-${i}`} className="border-b border-border/60 px-2 py-1.5 text-xs last:border-0">
              <span className="font-medium">{n.ten}</span>
              <span className="text-muted-foreground"> · {(n.p * 100).toFixed(0)}% · {n.cach}</span>
              {n.ly_do ? <p className="text-muted-foreground">{n.ly_do}</p> : null}
            </div>
          ))}
          {!xemTruoc.length ? <p className="px-2 py-3 text-center text-xs text-muted-foreground">Chưa nghĩ gì lúc này.</p> : null}
        </div>
      </section>

      <section>
        <p className="mb-1 text-xs font-semibold">Thành tích từng thiết bị</p>
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left">Thiết bị</th>
                <th className="px-2 py-1 text-right">Đúng/Sai</th>
                <th className="px-2 py-1 text-right">Điểm</th>
                <th className="px-2 py-1 text-right">Cấp</th>
              </tr>
            </thead>
            <tbody>
              {thongKe.map((t) => (
                <tr key={t.ten} className="border-t border-border/60">
                  <td className="px-2 py-1">{t.ten}</td>
                  <td className="px-2 py-1 text-right">{t.dung}/{t.sai}</td>
                  <td className="px-2 py-1 text-right">{(t.diem * 100).toFixed(0)}%</td>
                  <td className="px-2 py-1 text-right">
                    {t.cap >= 2 ? <span className="text-green-600">tự làm</span> : <span className="text-muted-foreground">gợi ý</span>}
                  </td>
                </tr>
              ))}
              {!thongKe.length ? (
                <tr><td colSpan={4} className="px-2 py-3 text-center text-muted-foreground">Chưa có dữ liệu.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
