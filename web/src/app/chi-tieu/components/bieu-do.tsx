"use client";

/**
 * Biểu đồ ở tab Tổng quan: chi theo ngày trong kỳ (kèm luỹ kế so với ngân sách), cơ cấu theo hũ kỳ này, và
 * 6 kỳ gần nhất chồng theo hũ. Số liệu kỳ này lấy từ `tq` đã có; theo ngày / theo kỳ từ /api/chi-tieu/thong-ke.
 * Kiểu trục, lưới, tooltip theo biểu đồ ở trang chủ (src/app/page.tsx).
 */

import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, Pie, PieChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

import { dong, lay, type TongQuan } from "../lib";

type ThongKe = {
  ky: { thang: string; tong_chi: number; theo_hu: Record<string, number> }[];
  theo_ngay: { ngay: string; tong: number }[];
};

const MAU = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "#be185d", "#0e7490", "#4d7c0f"];
const LUOI = "color-mix(in srgb, var(--foreground) 6%, transparent)";
const TRUC = { fontSize: 10, fill: "currentColor", fillOpacity: 0.5 };
const KHUNG_TOOLTIP = {
  background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 11, color: "var(--foreground)",
};

/** 1.250.000 → "1,3tr"; 50.000 → "50k". */
const gon = (n: number) =>
  Math.abs(n) >= 1e6 ? `${(n / 1e6).toLocaleString("vi-VN", { maximumFractionDigits: 1 })}tr`
    : Math.abs(n) >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n || 0);

const isoNgay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function Khung({ tieuDe, children }: { tieuDe: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 text-sm font-medium">{tieuDe}</div>
      {children}
    </div>
  );
}

export function BieuDoChiTieu({ tq }: { tq: TongQuan }) {
  const n = tq.ngan_sach;
  const [tk, setTk] = useState<ThongKe | null>(null);
  useEffect(() => {
    void lay<ThongKe>("/api/chi-tieu/thong-ke?so_ky=6").then((r) => r.ok && setTk(r));
  }, [tq]);

  const tenHu = new Map(tq.hu.map((h) => [String(h.id), h.ten]));
  const ten = (id: string) => tenHu.get(id) ?? `Hũ #${id} (đã xoá)`;

  // Chi theo ngày: đủ mọi ngày từ đầu kỳ tới hôm nay (ngày không chi = 0), luỹ kế so với nhịp chi đều cả kỳ.
  const sau = new Date(`${n.ngay_bat_dau_ky_sau}T00:00:00`);
  const dau = new Date(sau.getFullYear(), sau.getMonth() - 1, sau.getDate());
  const soNgayKy = Math.round((sau.getTime() - dau.getTime()) / 864e5);
  const chiNgay = new Map((tk?.theo_ngay ?? []).map((x) => [x.ngay, x.tong]));
  const homNay = isoNgay(new Date());
  const ngay: { nhan: string; chi: number; luy_ke: number; nhip_deu: number }[] = [];
  let luyKe = 0;
  for (let i = 0; i < soNgayKy; i++) {
    const d = new Date(dau.getFullYear(), dau.getMonth(), dau.getDate() + i);
    const k = isoNgay(d);
    if (k > homNay) break;
    luyKe += chiNgay.get(k) ?? 0;
    ngay.push({
      nhan: `${d.getDate()}/${d.getMonth() + 1}`, chi: chiNgay.get(k) ?? 0, luy_ke: luyKe,
      nhip_deu: Math.round((n.tong_ngan_sach * (i + 1)) / soNgayKy),
    });
  }

  const coCau = n.hu.filter((h) => h.da_chi > 0).map((h) => ({ ten: h.ten, gia_tri: h.da_chi }));

  const huCoChi = [...new Set((tk?.ky ?? []).flatMap((k) => Object.keys(k.theo_hu)))];
  const theoKy = (tk?.ky ?? []).map((k) => ({
    thang: k.thang, ...Object.fromEntries(huCoChi.map((id) => [ten(id), k.theo_hu[id] ?? 0])),
  }));
  const mauHu = (id: string) => MAU[Math.max(0, tq.hu.findIndex((h) => String(h.id) === id)) % MAU.length];

  if (!tk) return null;
  if (!n.tong_da_chi && !tk.ky.some((k) => k.tong_chi)) {
    return <p className="rounded-md border p-3 text-xs text-muted-foreground">Chưa có khoản chi nào — ghi khoản đầu tiên là biểu đồ hiện ra.</p>;
  }
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="lg:col-span-2">
        <Khung tieuDe={`Chi theo ngày — kỳ ${n.thang}`}>
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={ngay} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={LUOI} vertical={false} />
              <XAxis dataKey="nhan" tick={TRUC} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis yAxisId="ngay" tick={TRUC} tickLine={false} axisLine={false} tickFormatter={gon} width={44} />
              <YAxis yAxisId="luy_ke" orientation="right" tick={TRUC} tickLine={false} axisLine={false} tickFormatter={gon} width={44}
                domain={[0, (max: number) => Math.max(max, n.tong_ngan_sach)]} />
              <Tooltip contentStyle={KHUNG_TOOLTIP} formatter={(v) => dong(Number(v))} />
              <Legend wrapperStyle={{ fontSize: "11px" }} iconType="circle" iconSize={8} />
              <Bar yAxisId="ngay" dataKey="chi" name="Chi trong ngày" fill="var(--chart-2)" radius={[4, 4, 0, 0]} maxBarSize={22} />
              <Line yAxisId="luy_ke" dataKey="luy_ke" name="Luỹ kế" stroke="var(--chart-5)" strokeWidth={2} dot={false} />
              <Line yAxisId="luy_ke" dataKey="nhip_deu" name="Nhịp chi đều" stroke="var(--muted-foreground)" strokeDasharray="4 4" dot={false} />
              <ReferenceLine yAxisId="luy_ke" y={n.tong_ngan_sach} stroke="#e11d48" strokeDasharray="3 3"
                label={{ value: "Ngân sách", position: "insideTopLeft", fontSize: 10, fill: "#e11d48" }} />
            </ComposedChart>
          </ResponsiveContainer>
          <p className="mt-1 text-xs text-muted-foreground">
            Đường luỹ kế nằm trên «nhịp chi đều» nghĩa là đang tiêu nhanh hơn mức chia đều cho cả kỳ.
          </p>
        </Khung>
      </div>

      <Khung tieuDe="Kỳ này chi vào đâu">
        {coCau.length ? (
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie data={coCau} dataKey="gia_tri" nameKey="ten" innerRadius="55%" outerRadius="85%" paddingAngle={2}>
                {coCau.map((x) => (
                  <Cell key={x.ten} fill={MAU[Math.max(0, tq.hu.findIndex((h) => h.ten === x.ten)) % MAU.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={KHUNG_TOOLTIP}
                formatter={(v) => `${dong(Number(v))} (${Math.round((Number(v) / n.tong_da_chi) * 100)}%)`} />
              <Legend wrapperStyle={{ fontSize: "11px" }} iconType="circle" iconSize={8} />
            </PieChart>
          </ResponsiveContainer>
        ) : <p className="text-xs text-muted-foreground">Kỳ này chưa chi khoản nào.</p>}
      </Khung>

      <Khung tieuDe="6 kỳ gần nhất">
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={theoKy} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={LUOI} vertical={false} />
            <XAxis dataKey="thang" tick={TRUC} tickLine={false} axisLine={false} />
            <YAxis tick={TRUC} tickLine={false} axisLine={false} tickFormatter={gon} width={44} />
            <Tooltip contentStyle={KHUNG_TOOLTIP} formatter={(v) => dong(Number(v))} />
            <Legend wrapperStyle={{ fontSize: "11px" }} iconType="circle" iconSize={8} />
            {huCoChi.map((id) => (
              <Bar key={id} dataKey={ten(id)} stackId="ky" fill={mauHu(id)} maxBarSize={36} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </Khung>
    </div>
  );
}
