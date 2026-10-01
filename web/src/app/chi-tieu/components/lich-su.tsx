"use client";

import { useCallback, useEffect, useState } from "react";
import { Pencil, Scissors, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { docTien, dong, gui, lay, type KhoanChi, type TongQuan } from "../lib";

type Tach = { hu_id: number; tien: string; ghi_chu: string };

export function LichSu({ tq, thang, taiLai }: { tq: TongQuan; thang: string; taiLai: () => Promise<void> }) {
  const [ds, setDs] = useState<KhoanChi[]>([]);
  const [sua, setSua] = useState<{ id: number; hu_id: number; tien: string; ghi_chu: string } | null>(null);
  const [tach, setTach] = useState<{ id: number; tong: number; muc: Tach[] } | null>(null);

  const tai = useCallback(async () => {
    const r = await lay<{ giao_dich: KhoanChi[] }>(`/api/chi-tieu/lich-su?thang=${encodeURIComponent(thang)}`);
    if (r.ok) setDs(r.giao_dich);
  }, [thang]);
  useEffect(() => { void tai(); }, [tai]);
  const xong = async () => { await tai(); await taiLai(); };

  const luuSua = async () => {
    if (!sua) return;
    const so = docTien(sua.tien);
    if (!Number.isFinite(so) || so <= 0) return void window.alert("Số tiền chưa đúng.");
    if (await gui(`/api/chi-tieu/chi/${sua.id}`, { hu_id: sua.hu_id, so_tien: so, ghi_chu: sua.ghi_chu })) {
      setSua(null);
      await xong();
    }
  };
  const luuTach = async () => {
    if (!tach) return;
    const muc = tach.muc.map((m) => ({ hu_id: m.hu_id, so_tien: docTien(m.tien), ghi_chu: m.ghi_chu }));
    if (muc.some((m) => !Number.isFinite(m.so_tien) || m.so_tien <= 0)) return void window.alert("Số tiền mỗi dòng chưa đúng.");
    if (await gui(`/api/chi-tieu/chi/${tach.id}/tach`, { danh_sach: muc })) {
      setTach(null);
      await xong();
    }
  };
  const tongTach = tach ? tach.muc.reduce((s, m) => s + (docTien(m.tien) || 0), 0) : 0;

  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-muted-foreground">{ds.length} khoản chi trong kỳ {thang}. Lỡ ghi gộp nhiều việc vào một hũ thì bấm ✂ để tách.</p>
      <div className="divide-y rounded-md border">
        {ds.map((x) => (
          <div key={x.id} className="space-y-1 px-3 py-2">
            {sua?.id === x.id ? (
              <div className="flex flex-wrap items-center gap-2">
                <select className="rounded border bg-background px-2 py-1" value={sua.hu_id}
                  onChange={(e) => setSua({ ...sua, hu_id: Number(e.target.value) })}>
                  {tq.hu.map((h) => <option key={h.id} value={h.id}>{h.ten}</option>)}
                </select>
                <Input className="h-8 w-32" value={sua.tien} onChange={(e) => setSua({ ...sua, tien: e.target.value })} />
                <Input className="h-8 w-56" value={sua.ghi_chu} onChange={(e) => setSua({ ...sua, ghi_chu: e.target.value })} />
                <Button size="sm" onClick={() => void luuSua()}>Lưu</Button>
                <Button size="sm" variant="ghost" onClick={() => setSua(null)}>Huỷ</Button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-28 text-xs text-muted-foreground">{new Date(x.thoi_gian).toLocaleString("vi-VN")}</span>
                <span className="w-36 truncate">{x.hu_ten}</span>
                <b className="w-28 text-right">{dong(x.so_tien)}</b>
                <span className="flex-1 truncate text-muted-foreground">{x.ghi_chu}</span>
                <span className="text-[10px] text-muted-foreground">{x.nguon}</span>
                <button type="button" title="Sửa" onClick={() => setSua({ id: x.id, hu_id: x.hu_id, tien: String(x.so_tien), ghi_chu: x.ghi_chu })}>
                  <Pencil className="size-3.5" />
                </button>
                <button type="button" title="Tách thành nhiều hũ" onClick={() => setTach({ id: x.id, tong: x.so_tien, muc: [
                  { hu_id: x.hu_id, tien: String(x.so_tien), ghi_chu: x.ghi_chu }, { hu_id: tq.hu[0]?.id ?? x.hu_id, tien: "0", ghi_chu: "" }] })}>
                  <Scissors className="size-3.5" />
                </button>
                <button type="button" title="Xoá" className="text-destructive" onClick={async () => {
                  if (window.confirm(`Xoá khoản ${dong(x.so_tien)} (${x.ghi_chu || x.hu_ten})?`) && await gui(`/api/chi-tieu/chi/${x.id}`, {}, "DELETE")) await xong();
                }}><Trash2 className="size-3.5" /></button>
              </div>
            )}
            {tach?.id === x.id ? (
              <div className="space-y-1 rounded border p-2">
                {tach.muc.map((m, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <select className="rounded border bg-background px-2 py-1" value={m.hu_id}
                      onChange={(e) => setTach({ ...tach, muc: tach.muc.map((y, j) => j === i ? { ...y, hu_id: Number(e.target.value) } : y) })}>
                      {tq.hu.map((h) => <option key={h.id} value={h.id}>{h.ten}</option>)}
                    </select>
                    <Input className="h-8 w-32" value={m.tien}
                      onChange={(e) => setTach({ ...tach, muc: tach.muc.map((y, j) => j === i ? { ...y, tien: e.target.value } : y) })} />
                    <Input className="h-8 w-48" placeholder="ghi chú" value={m.ghi_chu}
                      onChange={(e) => setTach({ ...tach, muc: tach.muc.map((y, j) => j === i ? { ...y, ghi_chu: e.target.value } : y) })} />
                    {tach.muc.length > 2 ? (
                      <button type="button" onClick={() => setTach({ ...tach, muc: tach.muc.filter((_, j) => j !== i) })}><X className="size-3.5" /></button>
                    ) : null}
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Button size="sm" variant="outline" onClick={() => setTach({ ...tach, muc: [...tach.muc, { hu_id: tq.hu[0]?.id ?? 0, tien: "0", ghi_chu: "" }] })}>+ dòng</Button>
                  <span className={tongTach === tach.tong ? "text-emerald-600" : "text-rose-600"}>
                    Tổng {dong(tongTach)} / phải bằng {dong(tach.tong)}
                  </span>
                  <Button size="sm" disabled={tongTach !== tach.tong} onClick={() => void luuTach()}>Tách</Button>
                  <Button size="sm" variant="ghost" onClick={() => setTach(null)}>Huỷ</Button>
                </div>
              </div>
            ) : null}
          </div>
        ))}
        {!ds.length ? <p className="px-3 py-3 text-xs text-muted-foreground">Chưa có khoản chi nào.</p> : null}
      </div>
    </div>
  );
}
