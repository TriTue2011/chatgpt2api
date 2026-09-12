"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Trash2, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { layGet, goiPost } from "./lib";

type Muc = {
  khoa: string;
  nguon: string;
  loai: string;
  ma: string;
  ten: string;
  khu_vuc: string;
  da_biet: boolean;
};

export function SoTen() {
  const [ds, setDs] = useState<Muc[]>([]);
  const [dangTai, setDangTai] = useState(false);
  const [nhap, setNhap] = useState<Record<string, { ten: string; khu_vuc: string }>>({});
  const [them, setThem] = useState({ nguon: "mqtt", loai: "thiet_bi", ma: "", ten: "", khu_vuc: "" });

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const r = await layGet<{ danh_sach?: Muc[] }>("/api/hoc-hoi/ten");
      setDs(r.danh_sach || []);
      setNhap({});
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  const luu = async (m: Muc) => {
    const v = nhap[m.khoa] || { ten: m.ten, khu_vuc: m.khu_vuc };
    if (await goiPost("/api/hoc-hoi/ten/dat", { nguon: m.nguon, loai: m.loai, ma: m.ma, ten: v.ten, khu_vuc: v.khu_vuc })) {
      void tai();
    }
  };
  const xoa = async (khoa: string) => {
    if (await goiPost("/api/hoc-hoi/ten/xoa", { khoa })) void tai();
  };
  const themMoi = async () => {
    if (!them.ma.trim() || !them.ten.trim()) return;
    if (await goiPost("/api/hoc-hoi/ten/dat", them)) {
      setThem({ nguon: "mqtt", loai: "thiet_bi", ma: "", ten: "", khu_vuc: "" });
      void tai();
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Tên và khu vực bot đã biết. Sửa trực tiếp rồi bấm Lưu. Khu vực gõ tay ở
          đợt này (bot tự kết luận khu vực làm sau).
        </p>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      {/* Thêm tay */}
      <div className="rounded border border-border p-2">
        <p className="mb-1 text-xs font-semibold">Thêm tên tay</p>
        <div className="grid gap-2 sm:grid-cols-5">
          <Input placeholder="nguồn (mqtt/ha…)" value={them.nguon}
            onChange={(e) => setThem({ ...them, nguon: e.target.value })} className="h-8 text-xs" />
          <Input placeholder="loại (thiet_bi…)" value={them.loai}
            onChange={(e) => setThem({ ...them, loai: e.target.value })} className="h-8 text-xs" />
          <Input placeholder="mã" value={them.ma}
            onChange={(e) => setThem({ ...them, ma: e.target.value })} className="h-8 text-xs" />
          <Input placeholder="tên" value={them.ten}
            onChange={(e) => setThem({ ...them, ten: e.target.value })} className="h-8 text-xs" />
          <div className="flex gap-1">
            <Input placeholder="khu vực" value={them.khu_vuc}
              onChange={(e) => setThem({ ...them, khu_vuc: e.target.value })} className="h-8 text-xs" />
            <Button size="sm" className="h-8 shrink-0" onClick={() => void themMoi()}>
              <Plus className="size-3.5" />
            </Button>
          </div>
        </div>
      </div>

      {dangTai && !ds.length ? (
        <div className="flex items-center gap-2 p-2 text-xs text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" /> Đang tải…
        </div>
      ) : (
        <div className="max-h-96 overflow-auto rounded border border-border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/60 text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left">Mã</th>
                <th className="px-2 py-1 text-left">Tên</th>
                <th className="px-2 py-1 text-left">Khu vực</th>
                <th className="px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {ds.map((m) => {
                const v = nhap[m.khoa] || { ten: m.ten, khu_vuc: m.khu_vuc };
                return (
                  <tr key={m.khoa} className="border-t border-border/60">
                    <td className="px-2 py-1 align-top text-muted-foreground" title={m.khoa}>
                      {m.nguon}:{m.ma}
                    </td>
                    <td className="px-2 py-1">
                      <Input value={v.ten} className="h-7 text-xs"
                        onChange={(e) => setNhap({ ...nhap, [m.khoa]: { ...v, ten: e.target.value } })} />
                    </td>
                    <td className="px-2 py-1">
                      <Input value={v.khu_vuc} className="h-7 text-xs"
                        onChange={(e) => setNhap({ ...nhap, [m.khoa]: { ...v, khu_vuc: e.target.value } })} />
                    </td>
                    <td className="whitespace-nowrap px-2 py-1 text-right">
                      <Button variant="outline" size="sm" className="h-7" onClick={() => void luu(m)}>Lưu</Button>
                      <Button variant="ghost" size="sm" className="h-7 text-destructive" onClick={() => void xoa(m.khoa)}>
                        <Trash2 className="size-3.5" />
                      </Button>
                    </td>
                  </tr>
                );
              })}
              {!ds.length ? (
                <tr><td colSpan={4} className="px-2 py-3 text-center text-muted-foreground">Chưa có mục nào.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
