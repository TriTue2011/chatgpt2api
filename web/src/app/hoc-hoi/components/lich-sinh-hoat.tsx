"use client";

/**
 * Lịch sinh hoạt — THEO TỪNG NGƯỜI trong nhà (chủ máy 30/09/2026: "chia theo từng người trong gia đình, có thể
 * tự thêm, căn cứ vào độ tuổi để có list thời gian phù hợp, có thể tự thêm tay").
 *
 * Backend: api/hoc_hoi.py (/api/hoc-hoi/lich) → services/lich_sinh_hoat.py. Mỗi mục lịch của CẢ NHÀ (không chọn
 * ai) hoặc của vài người. Mọi thiết bị dùng chung: khung giờ của thiết bị đi theo mục lịch, mỗi mục là một điều
 * kiện bot học được, và «cả nhà vắng / ngủ» chỉ tính khi AI CŨNG vắng / ngủ. Lịch là lời khai "thường thường" —
 * không tự bật/tắt gì. Gợi ý theo tuổi là khung giờ thường gặp, bấm thêm rồi sửa.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, Save, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { goiPost, layGet } from "./lib";

export type MucLich = {
  ma: string; ten: string; loai: "ngu" | "vang" | "an" | "khac"; tu: string; den: string; thu: number[]; ai?: string[];
};
type ThanhVien = { ma: string; ten: string; nam_sinh: number | null; theo_doi: string[]; tuoi?: number | null; nhom?: string | null };
type Nhom = { ma: string; ten: string };
export const TEN_LOAI = { ngu: "Ngủ", vang: "Vắng nhà", an: "Bữa ăn", khac: "Khác" } as const;
/** 0 = thứ 2 … 6 = chủ nhật — cùng quy ước với backend (datetime.weekday). */
export const THU = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];

export function docThu(thu: number[]): string {
  if (thu.length === 7) return "mọi ngày";
  if (thu.join() === "0,1,2,3,4") return "T2–T6";
  return thu.map((t) => THU[t]).join(", ");
}

/** Khoá của thành viên trong `ai`: mã nếu đã lưu, tên nếu vừa thêm (backend đổi tên → mã khi lưu). */
const khoa = (t: ThanhVien) => t.ma || t.ten;

export function LichSinhHoat() {
  const [ds, setDs] = useState<MucLich[]>([]);
  const [tv, setTv] = useState<ThanhVien[]>([]);
  const [nhom, setNhom] = useState<Nhom[]>([]);
  const [goiY, setGoiY] = useState<Record<string, Omit<MucLich, "ma">[]>>({});
  const [loc, setLoc] = useState("");          // "" = mọi mục, "*" = cả nhà, khác = khoá thành viên
  const [doi, setDoi] = useState(false);

  const tai = useCallback(async () => {
    const r = await layGet<{ muc?: MucLich[]; thanh_vien?: ThanhVien[]; nhom?: Nhom[]; goi_y?: Record<string, Omit<MucLich, "ma">[]> }>(
      "/api/hoc-hoi/lich");
    setDs(r.muc || []);
    setTv(r.thanh_vien || []);
    setNhom(r.nhom || []);
    setGoiY(r.goi_y || {});
    setDoi(false);
  }, []);
  useEffect(() => { void tai(); }, [tai]);

  const sua = (i: number, x: Partial<MucLich>) => {
    setDs(ds.map((m, j) => (j === i ? { ...m, ...x } : m)));
    setDoi(true);
  };
  const suaTv = (i: number, x: Partial<ThanhVien>) => {
    const cu = tv[i];
    if (!cu.ma && x.ten !== undefined && x.ten !== cu.ten) {
      // Người chưa lưu được gán vào mục theo TÊN — đổi tên thì đổi theo, kẻo mục trỏ vào tên cũ.
      setDs(ds.map((m) => ({ ...m, ai: (m.ai || []).map((a) => (a === cu.ten ? x.ten as string : a)) })));
      if (loc === cu.ten) setLoc(x.ten);
    }
    setTv(tv.map((m, j) => (j === i ? { ...m, ...x } : m)));
    setDoi(true);
  };
  const boTv = (i: number) => {
    const k = khoa(tv[i]);
    setTv(tv.filter((_, j) => j !== i));
    setDs(ds.map((m) => ({ ...m, ai: (m.ai || []).filter((a) => a !== k) })));
    setDoi(true);
  };
  const nhomCua = (t: ThanhVien): string | null => {
    if (!t.nam_sinh) return null;
    const tuoi = new Date().getFullYear() - t.nam_sinh;
    const bang: [string, number][] = [["tre_nho", 6], ["tieu_hoc", 11], ["trung_hoc", 18], ["nguoi_lon", 60], ["nguoi_gia", 200]];
    return bang.find(([, den]) => tuoi < den)?.[0] ?? null;
  };
  const themGoiY = (t: ThanhVien) => {
    const n = nhomCua(t);
    if (!n) return;
    const k = khoa(t);
    const co = new Set(ds.filter((m) => (m.ai || []).includes(k)).map((m) => m.ten));
    const moi = (goiY[n] || []).filter((g) => !co.has(g.ten)).map((g) => ({ ...g, ma: "", ai: [k] }));
    setDs([...ds, ...moi]);
    setLoc(k);
    setDoi(true);
  };
  const luu = async () => {
    if (await goiPost("/api/hoc-hoi/lich", { muc: ds, thanh_vien: tv })) await tai();
  };

  const tenNhom = (m: string | null) => nhom.find((x) => x.ma === m)?.ten || "";
  const hien = ds.map((m, i) => ({ m, i })).filter(({ m }) =>
    !loc || (loc === "*" ? !(m.ai || []).length : (m.ai || []).includes(loc)));

  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">
        Giờ giấc «thường thường» của từng người, chia theo thứ. Mục không chọn ai là của cả nhà. Bot chỉ coi là «cả
        nhà vắng / ngủ» khi AI CŨNG đang vắng / ngủ. Khung giờ ở «Bật/tắt thiết bị» chọn «theo lịch» thì đổi giờ ở
        đây là thiết bị theo. Lưu xong bot học lại mọi thiết bị.
      </p>

      {/* Thành viên */}
      <div className="space-y-1.5 rounded border p-2">
        <div className="text-xs font-medium">Người trong nhà</div>
        {tv.map((t, i) => {
          const n = nhomCua(t);
          return (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <Input className="h-7 w-32" value={t.ten} placeholder="Tên" onChange={(e) => suaTv(i, { ten: e.target.value })} />
              <Input className="h-7 w-24" type="number" value={t.nam_sinh ?? ""} placeholder="Năm sinh"
                onChange={(e) => suaTv(i, { nam_sinh: e.target.value ? Number(e.target.value) : null })} />
              <span className="text-xs text-muted-foreground">
                {t.nam_sinh ? `${new Date().getFullYear() - t.nam_sinh} tuổi · ${tenNhom(n)}` : "chưa có năm sinh"}
              </span>
              <Input className="h-7 w-56" value={(t.theo_doi || []).join(", ")}
                placeholder="person.… / device_tracker.… (tuỳ chọn)"
                onChange={(e) => suaTv(i, { theo_doi: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
              <Button size="sm" variant="outline" disabled={!n} onClick={() => themGoiY(t)}
                title="Thêm khung giờ thường gặp của lứa tuổi này — sửa lại cho đúng nhà mình">
                <Sparkles className="mr-1 size-3.5" />Gợi ý theo tuổi
              </Button>
              <button type="button" title="Bỏ người này" onClick={() => boTv(i)}>
                <X className="size-3.5 text-destructive" />
              </button>
            </div>
          );
        })}
        <Button variant="outline" size="sm" onClick={() => {
          setTv([...tv, { ma: "", ten: "", nam_sinh: null, theo_doi: [] }]);
          setDoi(true);
        }}>
          <Plus className="mr-1 size-3.5" /> Thêm người
        </Button>
      </div>

      {/* Lọc */}
      <div className="flex flex-wrap gap-1 text-xs">
        {[["", "Tất cả"], ["*", "Cả nhà"], ...tv.filter((t) => t.ten).map((t) => [khoa(t), t.ten])].map(([k, ten]) => (
          <button key={k || "_"} type="button" onClick={() => setLoc(k)}
            className={`rounded px-2 py-0.5 ${loc === k ? "bg-primary text-primary-foreground" : "border text-muted-foreground"}`}>
            {ten}
          </button>
        ))}
      </div>

      {hien.map(({ m, i }) => (
        <div key={i} className="space-y-1 rounded border p-2">
          <div className="flex flex-wrap items-center gap-2">
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
          {tv.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 text-[11px]">
              <span className="text-muted-foreground">Của:</span>
              {!(m.ai || []).length && <span className="rounded bg-muted px-1.5 py-0.5">cả nhà</span>}
              {tv.filter((t) => t.ten).map((t) => {
                const k = khoa(t);
                const co = (m.ai || []).includes(k);
                return (
                  <button key={k} type="button"
                    className={`rounded px-1.5 py-0.5 ${co ? "bg-sky-600 text-white" : "border text-muted-foreground"}`}
                    onClick={() => sua(i, { ai: co ? (m.ai || []).filter((a) => a !== k) : [...(m.ai || []), k] })}>
                    {t.ten}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      ))}
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={() => {
          const ai = loc && loc !== "*" ? [loc] : [];
          setDs([...ds, { ma: "", ten: "", loai: "khac", tu: "12:00", den: "13:30", thu: [0, 1, 2, 3, 4, 5, 6], ai }]);
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
