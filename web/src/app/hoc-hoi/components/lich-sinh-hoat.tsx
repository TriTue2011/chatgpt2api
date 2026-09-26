"use client";

/**
 * Lịch sinh hoạt cả nhà — dậy, vắng nhà, ăn tối, ngủ… theo từng thứ trong tuần.
 *
 * Backend: api/hoc_hoi.py (/api/hoc-hoi/lich) → services/lich_sinh_hoat.py. Một lịch
 * dùng chung cho MỌI thiết bị: khung giờ của thiết bị đi theo mục lịch (sửa giờ ngủ ở
 * đây là mọi khung «Ngủ» theo), và mỗi mục là một điều kiện bot học được ("đang giờ
 * Ăn tối"). Lịch là lời khai "thường thường" — không tự bật/tắt gì.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { goiPost, layGet } from "./lib";

export type MucLich = { ma: string; ten: string; loai: "ngu" | "vang" | "an" | "khac"; tu: string; den: string; thu: number[] };
export const TEN_LOAI = { ngu: "Ngủ", vang: "Nhà vắng", an: "Bữa ăn", khac: "Khác" } as const;
/** 0 = thứ 2 … 6 = chủ nhật — cùng quy ước với backend (datetime.weekday). */
export const THU = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];

export function docThu(thu: number[]): string {
  if (thu.length === 7) return "mọi ngày";
  if (thu.join() === "0,1,2,3,4") return "T2–T6";
  return thu.map((t) => THU[t]).join(", ");
}

export function LichSinhHoat() {
  const [ds, setDs] = useState<MucLich[]>([]);
  const [doi, setDoi] = useState(false);

  const tai = useCallback(async () => {
    const r = await layGet<{ muc?: MucLich[] }>("/api/hoc-hoi/lich");
    setDs(r.muc || []);
    setDoi(false);
  }, []);
  useEffect(() => { void tai(); }, [tai]);

  const sua = (i: number, x: Partial<MucLich>) => {
    setDs(ds.map((m, j) => (j === i ? { ...m, ...x } : m)));
    setDoi(true);
  };
  const luu = async () => {
    if (await goiPost("/api/hoc-hoi/lich", { muc: ds })) await tai();
  };

  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-muted-foreground">
        Giờ giấc «thường thường» của cả nhà, chia theo thứ. Mọi thiết bị dùng chung: khung giờ ở «Bật/tắt thiết bị»
        chọn «theo lịch» thì đổi giờ ở đây là thiết bị theo; bot còn học thêm từ lịch (vd thứ 2 ăn tối muộn). Lưu xong
        bot học lại mọi thiết bị.
      </p>
      {ds.map((m, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2 rounded border p-2">
          <Input className="h-7 w-40" value={m.ten} placeholder="Tên (vd Ngủ)" onChange={(e) => sua(i, { ten: e.target.value })} />
          <select className="rounded border bg-background px-1 py-0.5 text-xs" value={m.loai}
            onChange={(e) => sua(i, { loai: e.target.value as MucLich["loai"] })}>
            {Object.entries(TEN_LOAI).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <Input type="time" className="h-7 w-28" value={m.tu} onChange={(e) => sua(i, { tu: e.target.value })} />
          –
          <Input type="time" className="h-7 w-28" value={m.den} onChange={(e) => sua(i, { den: e.target.value })} />
          <span className="flex gap-0.5">
            {THU.map((t, k) => (
              <button key={t} type="button"
                className={`rounded px-1.5 py-0.5 text-[11px] ${m.thu.includes(k) ? "bg-primary text-primary-foreground" : "border text-muted-foreground"}`}
                onClick={() => sua(i, { thu: m.thu.includes(k) ? m.thu.filter((x) => x !== k) : [...m.thu, k].sort() })}>
                {t}
              </button>
            ))}
          </span>
          <button type="button" title="Bỏ mục này" className="ml-auto"
            onClick={() => { setDs(ds.filter((_, j) => j !== i)); setDoi(true); }}>
            <X className="size-3.5 text-destructive" />
          </button>
        </div>
      ))}
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => {
          setDs([...ds, { ma: "", ten: "", loai: "khac", tu: "12:00", den: "13:30", thu: [0, 1, 2, 3, 4, 5, 6] }]);
          setDoi(true);
        }}>
          <Plus className="mr-1 size-3.5" /> Thêm mục
        </Button>
        <Button size="sm" disabled={!doi} onClick={() => void luu()}>
          <Save className="mr-1 size-3.5" /> Lưu lịch
        </Button>
        {doi ? <Button variant="ghost" size="sm" onClick={() => void tai()}>Huỷ sửa</Button> : null}
      </div>
    </div>
  );
}
