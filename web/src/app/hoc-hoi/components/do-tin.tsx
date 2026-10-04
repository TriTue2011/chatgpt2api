"use client";

/**
 * Độ tin cảm biến — đo trên lịch sử thật xem cảm biến nào đáng tin cho việc học/điều khiển (04/10/2026).
 * Nhãn: lành (dùng thẳng) · nhiễu (đặt quá nhạy, bot lọc mềm + báo) · kẹt (đứng im bất thường). API GET
 * /api/hoc-hoi/do-tin. Chỉ xem — lọc và báo do backend lo.
 */

import { useState } from "react";
import { LoaderCircle } from "lucide-react";

import { layGet } from "./lib";

type Nhi = { ma: string; ten?: string; khu?: string; nhan: string; doi_ngay?: number; ngan_tl?: number; nhieu_giay?: number; im_gio?: number };
type So = { ma: string; ten?: string; khu?: string; nhan: string; cham0_tl?: number; bien_rong_tl?: number };
type DuLieu = { ok?: boolean; nhi_phan?: Nhi[]; so?: So[]; so_ngay?: number };

const MAU: Record<string, string> = {
  lanh: "border-emerald-500 text-emerald-600", nhieu: "border-amber-500 text-amber-600", ket: "border-red-500 text-red-600",
};
const TEN: Record<string, string> = { lanh: "lành", nhieu: "nhiễu", ket: "kẹt" };

function fetchDoTin(): Promise<DuLieu> {
  return layGet<DuLieu>("/api/hoc-hoi/do-tin").catch(() => ({ ok: false }));
}

export function DoTin() {
  const [d, setD] = useState<DuLieu | null>(null);
  const [dang, setDang] = useState(false);

  const tai = () => { setDang(true); fetchDoTin().then((x) => { setD(x); setDang(false); }); };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Cảm biến đổi quá nhiều lần/ngày và phần lớn chỉ ở vài giây là <b>nhiễu</b> (đặt quá nhạy) — bot lọc mềm rồi
          mới tin, và báo anh chỉnh độ nhạy. Cảm biến từng đổi nhiều mà 24h qua đứng im là <b>kẹt</b>.
        </p>
        <button className="shrink-0 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted/40"
          onClick={tai} disabled={dang}>{dang ? "Đang đo…" : d ? "Đo lại" : "Đo"}</button>
      </div>

      {dang && !d ? <div className="flex items-center gap-2 p-3 text-xs text-muted-foreground"><LoaderCircle className="size-4 animate-spin" /> Đang đo…</div> : null}
      {d && d.ok === false ? <p className="text-xs text-red-600">Chưa đo được (cần dữ liệu lịch sử).</p> : null}

      {d?.nhi_phan?.length ? (
        <div className="space-y-1">
          <div className="text-xs font-semibold">Cảm biến hiện diện / cửa / đếm</div>
          {d.nhi_phan.map((x) => (
            <div key={x.ma} className="flex flex-wrap items-center gap-2 rounded border border-border px-2 py-1 text-xs">
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${MAU[x.nhan] || "border-border"}`}>{TEN[x.nhan] || x.nhan}</span>
              <span className="font-medium">{x.ten || x.ma}</span>
              {x.khu ? <span className="text-muted-foreground">· {x.khu}</span> : null}
              <span className="ml-auto text-muted-foreground">
                {x.nhan === "ket" ? `đứng im ${x.im_gio}h` : `${x.doi_ngay}/ngày · ${Math.round((x.ngan_tl || 0) * 100)}% dưới 10s${x.nhan === "nhieu" ? ` · giữ ≥${x.nhieu_giay}s mới tin` : ""}`}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {d?.so?.length ? (
        <div className="space-y-1">
          <div className="text-xs font-semibold">Cảm biến khoảng cách (radar)</div>
          {d.so.map((x) => (
            <div key={x.ma} className="flex flex-wrap items-center gap-2 rounded border border-border px-2 py-1 text-xs">
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${MAU[x.nhan] || "border-border"}`}>{TEN[x.nhan] || x.nhan}</span>
              <span className="font-medium">{x.ten || x.ma}</span>
              {x.khu ? <span className="text-muted-foreground">· {x.khu}</span> : null}
              <span className="ml-auto text-muted-foreground">chạm 0: {Math.round((x.cham0_tl || 0) * 100)}% ô 5 phút</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
