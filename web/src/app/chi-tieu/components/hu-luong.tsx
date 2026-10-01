"use client";

import { useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { docTien, dong, gui, type Hu, type TongQuan } from "../lib";

function DongHu({ h, xong }: { h: Hu; xong: () => Promise<void> }) {
  const [v, setV] = useState({ ten: h.ten, ty_le: String(h.ty_le), thu_tu_bu: String(h.thu_tu_bu), thu_tu_dac_biet: String(h.thu_tu_dac_biet) });
  const doi = v.ten !== h.ten || Number(v.ty_le) !== h.ty_le || Number(v.thu_tu_bu) !== h.thu_tu_bu || Number(v.thu_tu_dac_biet) !== h.thu_tu_dac_biet;
  const luu = async () => {
    if (await gui(`/api/chi-tieu/hu/${h.id}`, { ten: v.ten, ty_le: Number(v.ty_le), thu_tu_bu: Math.round(Number(v.thu_tu_bu)),
      thu_tu_dac_biet: Math.round(Number(v.thu_tu_dac_biet)) })) await xong();
  };
  return (
    <tr className="border-t">
      <td className="p-1"><Input className="h-8" value={v.ten} onChange={(e) => setV({ ...v, ten: e.target.value })} /></td>
      <td className="p-1"><Input className="h-8 w-20" type="number" step="0.5" value={v.ty_le} onChange={(e) => setV({ ...v, ty_le: e.target.value })} /></td>
      <td className="p-1"><Input className="h-8 w-20" type="number" value={v.thu_tu_bu} onChange={(e) => setV({ ...v, thu_tu_bu: e.target.value })} /></td>
      <td className="p-1"><Input className="h-8 w-20" type="number" value={v.thu_tu_dac_biet} onChange={(e) => setV({ ...v, thu_tu_dac_biet: e.target.value })} /></td>
      <td className="whitespace-nowrap p-1">
        <Button size="sm" variant={doi ? "default" : "ghost"} disabled={!doi} onClick={() => void luu()}><Save className="size-3.5" /></Button>
        <Button size="sm" variant="ghost" className="text-destructive" onClick={async () => {
          if (window.confirm(`Xoá hũ «${h.ten}»? Khoản chi cũ của hũ vẫn giữ trong lịch sử.`) && await gui(`/api/chi-tieu/hu/${h.id}`, {}, "DELETE")) await xong();
        }}><Trash2 className="size-3.5" /></Button>
      </td>
    </tr>
  );
}

export function HuLuong({ tq, taiLai }: { tq: TongQuan; taiLai: () => Promise<void> }) {
  const [so, setSo] = useState({ ten: tq.so.ten, luong: String(tq.so.luong), ngay: String(tq.so.ngay_bat_dau),
    nguong: (tq.so.nguong || []).map((x) => Math.round(x * 100)).join(", ") });
  const [moi, setMoi] = useState({ ten: "", ty_le: "0" });

  const luuSo = async () => {
    const luong = docTien(so.luong);
    const nguong = so.nguong.split(/[,\s]+/).filter(Boolean).map((x) => Number(x) / 100);
    if (!Number.isFinite(luong) || luong <= 0) return void window.alert("Lương chưa đúng.");
    if (nguong.some((x) => !Number.isFinite(x) || x <= 0)) return void window.alert("Ngưỡng là các số %, vd 65, 80, 100.");
    if (await gui("/api/chi-tieu/cau-hinh", { ten: so.ten, luong, ngay_bat_dau: Number(so.ngay), nguong })) await taiLai();
  };

  return (
    <div className="space-y-4 text-sm">
      <div className="grid gap-2 rounded-md border p-3 sm:grid-cols-2">
        <label className="space-y-1"><span className="text-xs text-muted-foreground">Tên sổ</span>
          <Input value={so.ten} onChange={(e) => setSo({ ...so, ten: e.target.value })} /></label>
        <label className="space-y-1"><span className="text-xs text-muted-foreground">Lương thực lĩnh mỗi kỳ (vd 15tr)</span>
          <Input value={so.luong} onChange={(e) => setSo({ ...so, luong: e.target.value })} /></label>
        <label className="space-y-1"><span className="text-xs text-muted-foreground">Ngày bắt đầu kỳ lương (1–28)</span>
          <Input type="number" min={1} max={28} value={so.ngay} onChange={(e) => setSo({ ...so, ngay: e.target.value })} /></label>
        <label className="space-y-1"><span className="text-xs text-muted-foreground">Cảnh báo khi hũ / tổng đạt (%)</span>
          <Input value={so.nguong} onChange={(e) => setSo({ ...so, nguong: e.target.value })} /></label>
        <div className="sm:col-span-2"><Button size="sm" onClick={() => void luuSo()}><Save className="mr-1 size-4" /> Lưu</Button>
          <span className="ml-2 text-xs text-muted-foreground">Lương hiện tại {dong(tq.so.luong)}</span></div>
      </div>

      <div className="rounded-md border p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="font-medium">Các hũ</span>
          <span className={`text-xs ${tq.tong_ty_le === 100 ? "text-emerald-600" : "text-amber-600"}`}>
            Tổng tỷ lệ {tq.tong_ty_le}% {tq.tong_ty_le === 100 ? "" : "— nên bằng 100%"}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-muted-foreground">
              <th className="p-1">Tên</th><th className="p-1">Tỷ lệ %</th>
              <th className="p-1" title="Hũ khác vượt thì rút bù từ hũ có số NHỎ trước">Thứ tự bù</th>
              <th className="p-1" title="0 = không; số nhỏ hứng chi phí đặc biệt trước">Hứng chi phí đặc biệt</th><th />
            </tr></thead>
            <tbody>{tq.hu.map((h) => <DongHu key={`${h.id}-${h.ten}-${h.ty_le}-${h.thu_tu_bu}-${h.thu_tu_dac_biet}`} h={h} xong={taiLai} />)}</tbody>
          </table>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Input className="h-8 w-48" placeholder="Tên hũ mới" value={moi.ten} onChange={(e) => setMoi({ ...moi, ten: e.target.value })} />
          <Input className="h-8 w-20" type="number" value={moi.ty_le} onChange={(e) => setMoi({ ...moi, ty_le: e.target.value })} />
          <Button size="sm" variant="outline" disabled={!moi.ten.trim()} onClick={async () => {
            if (await gui("/api/chi-tieu/hu", { ten: moi.ten, ty_le: Number(moi.ty_le) || 0 })) { setMoi({ ten: "", ty_le: "0" }); await taiLai(); }
          }}><Plus className="mr-1 size-4" /> Thêm hũ</Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Thứ tự bù: khi một hũ chi vượt, phần thiếu được rút từ phần dư của các hũ khác — hũ số nhỏ bị rút trước (mặc định
          Hưởng Thụ → Dự Phòng → … → Tự Do Tài Chính sau cùng). Hứng chi phí đặc biệt: khoản lớn biết trước (học phí…) trừ vào
          các hũ có số &gt; 0, số nhỏ trước.
        </p>
      </div>
    </div>
  );
}
