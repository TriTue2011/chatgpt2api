"use client";

import { useCallback, useEffect, useState } from "react";
import { Pencil, Plus, Printer, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { docTien, dong, gui, lay } from "../lib";

type Gd = { id: number; loai: "tam_ung" | "chi"; so_tien: number; mo_ta: string; thoi_gian: string };
type Gc = { id: number; thoi_gian: string; tong_tam_ung: number; tong_chi: number; so_du: number };

export function CongTy() {
  const [d, setD] = useState<{ so_du: number; dien_giai: string; giao_dich: Gd[]; giai_chi: Gc[] } | null>(null);
  const [moi, setMoi] = useState({ loai: "chi", mo_ta: "", tien: "" });
  const [sua, setSua] = useState<{ id: number; loai: string; mo_ta: string; tien: string } | null>(null);
  const tai = useCallback(async () => {
    const r = await lay<{ so_du: number; dien_giai: string; giao_dich: Gd[]; giai_chi: Gc[] }>("/api/chi-tieu/cong-ty");
    if (r.ok) setD(r);
  }, []);
  useEffect(() => { void tai(); }, [tai]);
  if (!d) return null;
  return (
    <div className="space-y-3 text-sm">
      <div className="rounded-md border p-3">
        <div className="font-medium">Số dư tạm ứng đang mở: {dong(d.so_du)}</div>
        <div className="text-xs text-muted-foreground">{d.dien_giai} Tách riêng khỏi tiền cá nhân — không vào hũ nào.</div>
      </div>
      <div className="divide-y rounded-md border">
        {d.giao_dich.map((x) => sua?.id === x.id ? (
          <div key={x.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
            <select className="rounded border bg-background px-2 py-1" value={sua.loai} onChange={(e) => setSua({ ...sua, loai: e.target.value })}>
              <option value="tam_ung">Tạm ứng</option><option value="chi">Chi</option>
            </select>
            <Input className="h-8 w-56" value={sua.mo_ta} onChange={(e) => setSua({ ...sua, mo_ta: e.target.value })} />
            <Input className="h-8 w-32" value={sua.tien} onChange={(e) => setSua({ ...sua, tien: e.target.value })} />
            <Button size="sm" onClick={async () => {
              if (await gui(`/api/chi-tieu/cong-ty/${x.id}`, { loai: sua.loai, mo_ta: sua.mo_ta, so_tien: docTien(sua.tien) })) { setSua(null); await tai(); }
            }}>Lưu</Button>
            <Button size="sm" variant="ghost" onClick={() => setSua(null)}>Huỷ</Button>
          </div>
        ) : (
          <div key={x.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
            <span className="w-28 text-xs text-muted-foreground">{new Date(x.thoi_gian).toLocaleString("vi-VN")}</span>
            <span className={`w-20 ${x.loai === "tam_ung" ? "text-emerald-600" : "text-rose-600"}`}>{x.loai === "tam_ung" ? "Tạm ứng" : "Chi"}</span>
            <span className="flex-1">{x.mo_ta}</span><b>{dong(x.so_tien)}</b>
            <button type="button" title="Sửa" onClick={() => setSua({ id: x.id, loai: x.loai, mo_ta: x.mo_ta, tien: String(x.so_tien) })}><Pencil className="size-3.5" /></button>
            <button type="button" title="Xoá" className="text-destructive" onClick={async () => {
              if (window.confirm(`Xoá «${x.mo_ta}»?`) && await gui(`/api/chi-tieu/cong-ty/${x.id}`, {}, "DELETE")) await tai();
            }}><Trash2 className="size-3.5" /></button>
          </div>
        ))}
        {!d.giao_dich.length ? <p className="px-3 py-3 text-xs text-muted-foreground">Kỳ tạm ứng đang trống.</p> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select className="rounded border bg-background px-2 py-1" value={moi.loai} onChange={(e) => setMoi({ ...moi, loai: e.target.value })}>
          <option value="tam_ung">Công ty tạm ứng</option><option value="chi">Chi cho công việc</option>
        </select>
        <Input className="h-8 w-56" placeholder="Mô tả" value={moi.mo_ta} onChange={(e) => setMoi({ ...moi, mo_ta: e.target.value })} />
        <Input className="h-8 w-32" placeholder="Số tiền" value={moi.tien} onChange={(e) => setMoi({ ...moi, tien: e.target.value })} />
        <Button size="sm" variant="outline" disabled={!moi.mo_ta.trim() || !moi.tien.trim()} onClick={async () => {
          if (await gui("/api/chi-tieu/cong-ty", { loai: moi.loai, mo_ta: moi.mo_ta, so_tien: docTien(moi.tien) })) { setMoi({ ...moi, mo_ta: "", tien: "" }); await tai(); }
        }}><Plus className="mr-1 size-4" /> Thêm</Button>
        <Button size="sm" disabled={!d.giao_dich.length} onClick={async () => {
          if (!window.confirm("Giải chi: khoá kỳ tạm ứng đang mở (không sửa được nữa) và mở trang in?")) return;
          const r = await gui("/api/chi-tieu/cong-ty/giai-chi");
          if (r) { await tai(); window.open(`/chi-tieu/giai-chi/?id=${r.id}`, "_blank"); }
        }}>Giải chi</Button>
      </div>
      {d.giai_chi.length ? (
        <div className="rounded-md border p-3">
          <div className="mb-1 font-medium">Các lần giải chi</div>
          {d.giai_chi.map((g) => (
            <div key={g.id} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="w-32">{new Date(g.thoi_gian).toLocaleString("vi-VN")}</span>
              <span>tạm ứng {dong(g.tong_tam_ung)} · chi {dong(g.tong_chi)} · số dư <b>{dong(g.so_du)}</b></span>
              <a className="ml-auto inline-flex items-center gap-1 underline" href={`/chi-tieu/giai-chi/?id=${g.id}`} target="_blank" rel="noreferrer">
                <Printer className="size-3.5" /> In / lưu PDF
              </a>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
