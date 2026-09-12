"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { httpRequest } from "@/lib/request";
import { layGet, goiPost } from "./lib";

type Nep = {
  id: number;
  ten: string;
  gio: string;
  lech_phut: number;
  so_lan: number;
  trang_thai: "cho_duyet" | "da_duyet" | "bo";
};

const THU_TRONG_TUAN = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];

export function NepSinhHoat() {
  const [ds, setDs] = useState<Nep[]>([]);
  const [dangTai, setDangTai] = useState(false);
  const [them, setThem] = useState({ ten: "", gio: "", phut: "15", thu: "-1" });

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const r = await layGet<{ danh_sach?: Nep[] }>("/api/mqtt/tinh-huong");
      setDs(r.danh_sach || []);
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  const duyet = async (id: number, boQua = false) => {
    const res = await httpRequest<{ ok?: boolean }>("/api/mqtt/tinh-huong/duyet", {
      method: "POST",
      body: boQua ? { id, bo: true } : { id },
    });
    if (res?.ok) void tai();
  };
  const doiTen = async (id: number, tenCu: string) => {
    const ten = window.prompt("Đổi tên nếp:", tenCu);
    if (ten == null || !ten.trim()) return;
    const res = await httpRequest<{ ok?: boolean }>("/api/mqtt/tinh-huong/duyet", {
      method: "POST",
      body: { id, ten },
    });
    if (res?.ok) void tai();
  };
  const themMoi = async () => {
    const gio = Number(them.gio);
    if (!them.ten.trim() || Number.isNaN(gio)) return;
    const ok = await goiPost("/api/hoc-hoi/tinh-huong/them", {
      ten: them.ten, gio, phut: Number(them.phut) || 15, thu: Number(them.thu),
    });
    if (ok) {
      setThem({ ten: "", gio: "", phut: "15", thu: "-1" });
      void tai();
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Nhận ra bằng <b>cảm biến có người</b>, không phải đèn nào bật. Bot tự
          học, và anh tự thêm tay được ở đây.
        </p>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      {/* Thêm tay */}
      <div className="rounded border border-border p-2">
        <p className="mb-1 text-xs font-semibold">Tự thêm một nếp</p>
        <div className="grid gap-2 sm:grid-cols-5">
          <Input placeholder="tên nếp, vd: ăn tối" value={them.ten}
            onChange={(e) => setThem({ ...them, ten: e.target.value })} className="h-8 text-xs sm:col-span-2" />
          <Input placeholder="giờ (vd 19.5)" type="number" step="0.25" min={0} max={23.99} value={them.gio}
            onChange={(e) => setThem({ ...them, gio: e.target.value })} className="h-8 text-xs" />
          <Input placeholder="± phút" type="number" min={1} value={them.phut}
            onChange={(e) => setThem({ ...them, phut: e.target.value })} className="h-8 text-xs" />
          <select className="h-8 rounded-md border border-input bg-background px-2 text-xs" value={them.thu}
            onChange={(e) => setThem({ ...them, thu: e.target.value })}>
            <option value="-1">Mọi ngày</option>
            {THU_TRONG_TUAN.map((t, i) => <option key={t} value={i}>{t}</option>)}
          </select>
        </div>
        <div className="mt-2 flex justify-end">
          <Button size="sm" onClick={() => void themMoi()}><Plus className="mr-1 size-3.5" /> Thêm</Button>
        </div>
      </div>

      {dangTai && !ds.length ? (
        <div className="flex items-center gap-2 p-2 text-xs text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" /> Đang tải…
        </div>
      ) : (
        <div className="max-h-72 overflow-auto rounded border border-border">
          {ds.map((t) => (
            <div key={t.id} className="border-b border-border/60 px-2 py-1.5 text-xs last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{t.ten}</span>
                <span className="text-muted-foreground">khoảng {t.gio} ±{t.lech_phut}p · thấy {t.so_lan} lần</span>
                {t.trang_thai === "da_duyet" ? (
                  <span className="text-green-600">· đã ghi nhớ</span>
                ) : t.trang_thai === "bo" ? (
                  <span className="text-muted-foreground">· đã bỏ</span>
                ) : (
                  <span className="text-amber-600">· chờ duyệt</span>
                )}
              </div>
              {t.trang_thai === "cho_duyet" ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  <Button variant="outline" size="sm" onClick={() => void duyet(t.id)}>Đúng rồi</Button>
                  <Button variant="outline" size="sm" onClick={() => void doiTen(t.id, t.ten)}>Đổi tên</Button>
                  <Button variant="outline" size="sm" onClick={() => void duyet(t.id, true)}>Bỏ qua</Button>
                </div>
              ) : (
                <div className="mt-1">
                  <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => void doiTen(t.id, t.ten)}>Đổi tên</Button>
                </div>
              )}
            </div>
          ))}
          {!ds.length ? <p className="px-2 py-3 text-center text-xs text-muted-foreground">Chưa có nếp nào.</p> : null}
        </div>
      )}
    </div>
  );
}
