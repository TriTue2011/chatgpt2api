"use client";

import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { docTien, dong, gui, type MucKy, type TongQuan } from "../lib";

function Bang({ loai, tieuDe, goiY, ds, xong }: {
  loai: "thu-nhap" | "dac-biet"; tieuDe: string; goiY: string; ds: MucKy[]; xong: () => Promise<void>;
}) {
  const [moi, setMoi] = useState({ mo_ta: "", tien: "" });
  const [sua, setSua] = useState<{ id: number; mo_ta: string; tien: string } | null>(null);
  return (
    <div className="space-y-2 rounded-md border p-3 text-sm">
      <div className="font-medium">{tieuDe}</div>
      <p className="text-xs text-muted-foreground">{goiY}</p>
      {ds.map((x) => sua?.id === x.id ? (
        <div key={x.id} className="flex flex-wrap items-center gap-2">
          <Input className="h-8 w-56" value={sua.mo_ta} onChange={(e) => setSua({ ...sua, mo_ta: e.target.value })} />
          <Input className="h-8 w-32" value={sua.tien} onChange={(e) => setSua({ ...sua, tien: e.target.value })} />
          <Button size="sm" onClick={async () => {
            if (await gui(`/api/chi-tieu/ky/${loai}/${x.id}`, { mo_ta: sua.mo_ta, so_tien: docTien(sua.tien) })) { setSua(null); await xong(); }
          }}>Lưu</Button>
          <Button size="sm" variant="ghost" onClick={() => setSua(null)}>Huỷ</Button>
        </div>
      ) : (
        <div key={x.id} className="flex flex-wrap items-center gap-2">
          <span className="flex-1">{x.mo_ta}</span><b>{dong(x.so_tien)}</b>
          <button type="button" title="Sửa" onClick={() => setSua({ id: x.id, mo_ta: x.mo_ta, tien: String(x.so_tien) })}><Pencil className="size-3.5" /></button>
          <button type="button" title="Xoá" className="text-destructive" onClick={async () => {
            if (window.confirm(`Xoá «${x.mo_ta}»?`) && await gui(`/api/chi-tieu/ky/${loai}/${x.id}`, {}, "DELETE")) await xong();
          }}><Trash2 className="size-3.5" /></button>
        </div>
      ))}
      {!ds.length ? <p className="text-xs text-muted-foreground">Chưa có.</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <Input className="h-8 w-56" placeholder="Mô tả" value={moi.mo_ta} onChange={(e) => setMoi({ ...moi, mo_ta: e.target.value })} />
        <Input className="h-8 w-32" placeholder="Số tiền" value={moi.tien} onChange={(e) => setMoi({ ...moi, tien: e.target.value })} />
        <Button size="sm" variant="outline" disabled={!moi.mo_ta.trim() || !moi.tien.trim()} onClick={async () => {
          const so = docTien(moi.tien);
          if (!Number.isFinite(so) || so <= 0) return void window.alert("Số tiền chưa đúng.");
          if (await gui(`/api/chi-tieu/ky/${loai}`, { mo_ta: moi.mo_ta, so_tien: so })) { setMoi({ mo_ta: "", tien: "" }); await xong(); }
        }}><Plus className="mr-1 size-4" /> Thêm</Button>
      </div>
    </div>
  );
}

export function Ky({ tq, taiLai }: { tq: TongQuan; taiLai: () => Promise<void> }) {
  const n = tq.ngan_sach;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">Kỳ {n.thang}. Mục mới luôn ghi vào kỳ HIỆN TẠI.</p>
      <Bang loai="thu-nhap" tieuDe="Thu nhập ngoài lương" ds={n.thu_nhap_them} xong={taiLai}
        goiY="Thưởng, làm thêm… cộng vào thu nhập kỳ này — hạn mức mọi hũ tăng theo tỷ lệ." />
      <Bang loai="dac-biet" tieuDe="Chi phí đặc biệt biết trước" ds={n.chi_phi_dac_biet} xong={taiLai}
        goiY="Khoản lớn biết trước (học phí, sửa xe…) chỉ trong kỳ này — trừ vào các hũ hứng chi phí đặc biệt (tab Hũ & lương)." />
    </div>
  );
}
