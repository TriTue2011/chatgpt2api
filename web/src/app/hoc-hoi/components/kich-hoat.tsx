"use client";

/**
 * Kích hoạt — "KHI cảm biến … NẾU giờ / độ sáng … THÌ bật/tắt", từng thiết bị.
 *
 * Backend: api/hoc_hoi.py (/api/hoc-hoi/kich-hoat*) → services/kich_hoat_nha.py.
 * Bot tự chọn nguồn (cảm biến đứng trước lần người bật/tắt) và tự học luật; chủ máy
 * sửa ở đây: bỏ nguồn, đặt khung giờ ngoại lệ, bật/tắt từng thiết bị. Điều chủ máy
 * đặt luôn thắng điều máy học.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, RotateCcw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { goiPost, layGet } from "./lib";

type Luat = { neu: string[]; p: number; k: number; n: number };
type Nguon = { ma: string; ten: string; so_lan?: number };
type Huong = {
  nguon: Nguon[];
  luat: Luat[];
  kiem: { doan?: number; trung?: number; ngay?: number; dat?: boolean };
  so_lan: number;
  cap: number;
  diem: number;
  so_luot: number;
  sai_gan_day: number;
  theo_gio: { gio: number; k: number; n: number; cach: "tu_lam" | "hoi" | "im" }[];
};
type NgoaiLe = { hanh_dong: "on" | "off"; tu: string; den: string; cach: "hoi" | "khong"; ten: string };
const TEN_CACH = { hoi: "luôn hỏi anh", khong: "không làm" } as const;
const MAU_GIO = { tu_lam: "bg-emerald-500/70", hoi: "bg-amber-400/70", im: "bg-muted" } as const;

/** Mỗi giờ luật nói "làm" thì người thật sự làm bao nhiêu — xanh: tự làm, vàng: hỏi, xám: im. */
function TheoGio({ ds }: { ds: Huong["theo_gio"] }) {
  if (!ds.length) return null;
  const theo = new Map(ds.map((x) => [x.gio, x]));
  return (
    <div className="flex flex-wrap items-center gap-0.5 text-[10px]">
      <span className="mr-1 text-muted-foreground">Theo giờ:</span>
      {Array.from({ length: 24 }, (_, h) => {
        const x = theo.get(h);
        return (
          <span key={h} className={`w-6 rounded px-0.5 text-center ${x ? MAU_GIO[x.cach] : "opacity-40"}`}
            title={x ? `${h}h: luật nói làm ${x.n} lần, người làm ${x.k} — ${x.cach === "tu_lam" ? "tự làm" : x.cach === "hoi" ? "hỏi" : "im"} (xét ±1 giờ)` : `${h}h: luật không nói gì`}>
            {h}
          </span>
        );
      })}
    </div>
  );
}
type ThietBi = {
  thiet_bi: string;
  ten: string;
  bat: boolean;
  tu_lam: boolean;
  bo_nguon: Nguon[];
  ngoai_le: NgoaiLe[];
  hoc_luc?: number;
  huong: Record<"on" | "off", Huong>;
  nguong: { so_luot: number; ty_le: number };
};

const TEN_HD = { on: "Bật", off: "Tắt" } as const;
/** Cùng ngưỡng mở miệng `P_HOI` của backend — luật dưới ngưỡng này bot không hỏi. */
const P_HOI = 0.75;

function CapDo({ h, nguong }: { h: Huong; nguong: ThietBi["nguong"] }) {
  if (!h.kiem.dat) {
    return (
      <span className="text-amber-600">
        Chưa đủ tin — thử {h.kiem.ngay ?? 7} ngày cuối: đoán {h.kiem.doan ?? 0}, đúng {h.kiem.trung ?? 0}
        {" "}(cần ≥ 5 lần và ≥ 60%). Bot im.
      </span>
    );
  }
  const thu = `thử ${h.kiem.ngay ?? 7} ngày cuối: đúng ${h.kiem.trung}/${h.kiem.doan}`;
  if (h.cap >= 2) return <span className="text-emerald-600">Tự làm ({thu}; anh chấm {h.so_luot} lượt).</span>;
  return (
    <span>
      Hỏi trước ({thu}). Anh đã chấm {h.so_luot}/{nguong.so_luot} lượt, đúng {Math.round(h.diem * 100)}%
      {h.sai_gan_day ? ` — sai ${h.sai_gan_day} trong 10 lượt gần nhất` : ""}; đủ {nguong.so_luot} lượt
      và ≥ {Math.round(nguong.ty_le * 100)}% thì bot tự làm.
    </span>
  );
}

function MotThietBi({ tb, taiLai }: { tb: ThietBi; taiLai: () => Promise<void> }) {
  const [dangHoc, setDangHoc] = useState(false);
  const [nl, setNl] = useState<NgoaiLe>({ hanh_dong: "on", tu: "21:00", den: "23:30", cach: "hoi", ten: "" });

  const dat = async (body: Record<string, unknown>) => {
    if (await goiPost("/api/hoc-hoi/kich-hoat/dat", { thiet_bi: tb.thiet_bi, ...body })) await taiLai();
  };
  const hocLai = async () => {
    setDangHoc(true);
    try {
      await goiPost("/api/hoc-hoi/kich-hoat/hoc", { thiet_bi: tb.thiet_bi });
      await taiLai();
    } finally {
      setDangHoc(false);
    }
  };
  const boMa = tb.bo_nguon.map((x) => x.ma);

  return (
    <div className="space-y-2 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 font-medium">
          <input type="checkbox" checked={tb.bat} onChange={(e) => void dat({ bat: e.target.checked })} />
          {tb.ten}
        </label>
        <span className="font-mono text-xs text-muted-foreground">{tb.thiet_bi}</span>
        <label className="flex items-center gap-1 text-xs"
          title="Không chờ đủ lượt chấm. Vẫn chỉ làm khi luật đủ chắc; anh làm ngược lại 2 lần trong 10 lượt gần nhất là bot quay về hỏi.">
          <input type="checkbox" checked={tb.tu_lam} disabled={!tb.bat}
            onChange={(e) => void dat({ tu_lam: e.target.checked })} />
          Cho bot tự làm ngay
        </label>
        <span className="ml-auto text-xs text-muted-foreground">
          {tb.hoc_luc ? `học lúc ${new Date(tb.hoc_luc * 1000).toLocaleString("vi-VN")}` : "chưa học"}
        </span>
        <Button variant="outline" size="sm" onClick={() => void hocLai()} disabled={dangHoc}>
          <RefreshCw className={`mr-1 size-3.5 ${dangHoc ? "animate-spin" : ""}`} /> Học lại
        </Button>
      </div>

      {(["on", "off"] as const).map((hd) => {
        const h = tb.huong[hd];
        return (
          <div key={hd} className="space-y-1 border-t pt-2">
            <div className="font-medium">{TEN_HD[hd]} — {h.so_lan} lần người {TEN_HD[hd].toLowerCase()} trong phần học</div>
            <div className="text-xs"><CapDo h={h} nguong={tb.nguong} /></div>
            <TheoGio ds={h.theo_gio || []} />
            {h.nguon.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-xs text-muted-foreground">Khi:</span>
                {h.nguon.map((n) => (
                  <span key={n.ma} className="inline-flex items-center gap-1 rounded border bg-muted/50 px-1.5 py-0.5 text-[11px]"
                    title={`${n.ma} — đứng trước ${n.so_lan ?? 0} lần`}>
                    {n.ten} ({n.so_lan ?? 0})
                    <button type="button" title="Bỏ nguồn này (bot học lại không có nó)"
                      onClick={() => void dat({ bo_nguon: [...boMa, n.ma] })}>
                      <X className="size-3 text-destructive" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <ul className="space-y-0.5 text-xs">
              {h.luat.filter((l) => l.n > 0).slice(0, 5).map((l, i) => (
                <li key={i} className={l.p >= P_HOI ? "font-medium" : "text-muted-foreground"}>
                  {l.p >= P_HOI ? "✔ " : "· "}
                  {l.neu.length ? l.neu.join(" VÀ ") : "mọi lúc"} → {TEN_HD[hd].toLowerCase()} {Math.round(l.p * 100)}%
                  {" "}({l.k}/{l.n} lần)
                </li>
              ))}
            </ul>
          </div>
        );
      })}

      <div className="space-y-1 border-t pt-2 text-xs">
        <div className="font-medium">Khung giờ của anh</div>
        <p className="text-muted-foreground">
          Ví dụ «Đọc sách 21:00–23:30 — Bật: luôn hỏi anh» (bot không tự bật, cũng không im, mà hỏi),
          hay «Quá giờ 22:00–00:30 — Tắt: không làm». Ngoài khung, bot tự cân nhắc theo giờ ở trên.
        </p>
        {tb.ngoai_le.map((x, i) => (
          <div key={i} className="flex items-center gap-2">
            {x.ten ? <b>{x.ten}</b> : null} {x.tu}–{x.den} — {TEN_HD[x.hanh_dong]}: {TEN_CACH[x.cach || "khong"]}
            <button type="button" title="Bỏ ngoại lệ"
              onClick={() => void dat({ ngoai_le: tb.ngoai_le.filter((_, j) => j !== i) })}>
              <X className="size-3 text-destructive" />
            </button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2">
          <Input className="h-7 w-32" placeholder="Tên (vd Đọc sách)" value={nl.ten}
            onChange={(e) => setNl({ ...nl, ten: e.target.value })} />
          <select className="rounded border bg-background px-1 py-0.5" value={nl.hanh_dong}
            onChange={(e) => setNl({ ...nl, hanh_dong: e.target.value as "on" | "off" })}>
            <option value="on">Bật</option>
            <option value="off">Tắt</option>
          </select>
          <select className="rounded border bg-background px-1 py-0.5" value={nl.cach}
            onChange={(e) => setNl({ ...nl, cach: e.target.value as "hoi" | "khong" })}>
            <option value="hoi">luôn hỏi anh</option>
            <option value="khong">không làm</option>
          </select>
          từ <Input type="time" className="h-7 w-28" value={nl.tu} onChange={(e) => setNl({ ...nl, tu: e.target.value })} />
          đến <Input type="time" className="h-7 w-28" value={nl.den} onChange={(e) => setNl({ ...nl, den: e.target.value })} />
          <Button variant="outline" size="sm" onClick={() => void dat({ ngoai_le: [...tb.ngoai_le, nl] })}>
            <Plus className="mr-1 size-3.5" /> Thêm
          </Button>
        </div>
        {tb.bo_nguon.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 pt-1">
            <span className="text-muted-foreground">Nguồn anh đã bỏ:</span>
            {tb.bo_nguon.map((n) => (
              <span key={n.ma} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px]">
                {n.ten}
                <button type="button" title="Cho dùng lại"
                  onClick={() => void dat({ bo_nguon: boMa.filter((m) => m !== n.ma) })}>
                  <RotateCcw className="size-3" />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function KichHoat() {
  const [ds, setDs] = useState<ThietBi[]>([]);
  const [ma, setMa] = useState("");

  const tai = useCallback(async () => {
    const r = await layGet<{ danh_sach?: ThietBi[] }>("/api/hoc-hoi/kich-hoat");
    setDs(r.danh_sach || []);
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  const them = async () => {
    const tb = ma.trim();
    if (!tb) return;
    if (await goiPost("/api/hoc-hoi/kich-hoat/dat", { thiet_bi: tb, bat: true })) {
      setMa("");
      await goiPost("/api/hoc-hoi/kich-hoat/hoc", { thiet_bi: tb });
      await tai();
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Bot tự tìm <b>cảm biến</b> hay đứng ngay trước lần anh bật/tắt, rồi học luật theo giờ và độ
        sáng. Luật nào thử trên 7 ngày cuối đủ đúng thì bot <b>hỏi</b> trong nhóm học hỏi — anh
        trả lời «có» hoặc «không». Đủ lượt đúng thì bot <b>tự làm</b>, không cần anh trả lời; anh
        làm ngược lại trong 10 phút là bot ghi sai và tụt về hỏi. Cảm biến báo có người mà 6 giờ
        qua không ai bấm công tắc hay mở cửa thì bot coi là báo ảo và im.
      </p>
      {ds.map((tb) => <MotThietBi key={tb.thiet_bi} tb={tb} taiLai={tai} />)}
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-64" placeholder="switch.phong_ngu_l1" value={ma}
          onChange={(e) => setMa(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void them(); }} />
        <Button variant="outline" size="sm" onClick={() => void them()} disabled={!ma.trim()}>
          <Plus className="mr-1 size-3.5" /> Thêm thiết bị
        </Button>
      </div>
    </div>
  );
}
