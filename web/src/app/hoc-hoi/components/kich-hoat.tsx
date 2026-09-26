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
type Nguon = { ma: string; ten: string; so_lan?: number; du_chac?: number };
type Huong = {
  nguon: Nguon[];
  da_xet?: Nguon[];
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
  kiem_ao?: {
    ap_cho: string[]; nhin_lai_gio: number; cua: string[]; chan_gan_day: { luc: number; nguon: string }[];
    bang_chung?: { ma: string; ten: string }[];
  };
  tat_khi_vang?: {
    bat: boolean; phut: number; cam_bien: { ma: string; ten: string }[]; goi_y: { ma: string; ten: string }[];
    quay_lai_moi_ngay?: Record<string, Record<string, number>>;
  };
  co_so?: "so_do" | "tu_do";
};
type ThucThe = { ma: string; ten: string; lop: string };
const CONG_TAC = "cong_tac";

/** Kiểm báo ảo — TÁCH khỏi điều khiển. Chủ máy chọn bằng chứng "có người" và số giờ nhìn lại. */
function KiemAo({ k, luu, doiMa }: {
  k: NonNullable<ThietBi["kiem_ao"]>;
  luu: (v: { gio: number; bang_chung: string[] }) => Promise<void>;
  doiMa: (chu: string) => string;
}) {
  const bc = k.bang_chung ?? [];
  const [gio, setGio] = useState(String(k.nhin_lai_gio));
  const [moi, setMoi] = useState("");
  const ma = bc.map((x) => x.ma);
  return (
    <div className="space-y-1 border-t pt-2 text-xs">
      <div className="font-medium">Kiểm báo ảo (trước khi bật)</div>
      {k.ap_cho.length ? (
        <p className="text-muted-foreground">
          Khi bật theo <b>{k.ap_cho.join(", ")}</b>: nếu trong số giờ dưới đây không có bằng chứng nào có người
          thì coi là báo ảo — không bật, không hỏi. Cảm biến hiện diện khác không nên làm bằng chứng — nhà vắng
          chúng vẫn báo.
        </p>
      ) : (
        <p className="text-muted-foreground">Chưa có nguồn điều khiển nào là cảm biến hiện diện — chưa cần kiểm.</p>
      )}
      <div className="flex flex-wrap items-center gap-1">
        Nhìn lại
        <Input type="number" min={1} max={48} className="h-7 w-16" value={gio} onChange={(e) => setGio(e.target.value)}
          onBlur={() => void luu({ gio: Number(gio) || 6, bang_chung: ma })} />
        giờ, bằng chứng:
        {bc.map((x) => (
          <span key={x.ma} className="inline-flex items-center gap-1 rounded border bg-muted/50 px-1.5 py-0.5 text-[11px]">
            {x.ten}
            <button type="button" title="Bỏ" disabled={bc.length <= 1}
              onClick={() => void luu({ gio: Number(gio) || 6, bang_chung: ma.filter((m) => m !== x.ma) })}>
              <X className="size-3 text-destructive" />
            </button>
          </span>
        ))}
        <Input className="h-7 w-48" list="kich-hoat-thuc-the" placeholder="thêm (vd cửa, khoá)" value={moi}
          onChange={(e) => setMoi(e.target.value)} />
        <Button variant="outline" size="sm" className="h-7" disabled={!moi.trim()}
          onClick={() => { void luu({ gio: Number(gio) || 6, bang_chung: [...ma, doiMa(moi.trim())] }); setMoi(""); }}>
          <Plus className="size-3.5" />
        </Button>
        {!ma.includes(CONG_TAC) ? (
          <Button variant="outline" size="sm" className="h-7"
            onClick={() => void luu({ gio: Number(gio) || 6, bang_chung: [...ma, CONG_TAC] })}>
            + công tắc bấm tay
          </Button>
        ) : null}
      </div>
      {k.chan_gan_day.length > 0 && (
        <ul className="text-muted-foreground">
          {k.chan_gan_day.map((x, i) => (
            <li key={i}>Đã chặn {new Date(x.luc * 1000).toLocaleString("vi-VN")} — {x.nguon}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Tắt khi vắng — chủ máy chọn cảm biến và số phút; mặc định tắt. */
function TatKhiVang({ t, luu, doiMa }: {
  t: NonNullable<ThietBi["tat_khi_vang"]>;
  luu: (v: { bat: boolean; cam_bien: string[]; phut: number }) => Promise<void>;
  doiMa: (chu: string) => string;
}) {
  const [phut, setPhut] = useState(String(t.phut));
  const [moi, setMoi] = useState("");
  const ma = t.cam_bien.map((x) => x.ma);
  const ghi = (v: Partial<{ bat: boolean; cam_bien: string[]; phut: number }>) =>
    void luu({ bat: t.bat, cam_bien: ma, phut: Number(phut) || 15, ...v });
  return (
    <div className="space-y-1 border-t pt-2 text-xs">
      <label className="flex items-center gap-2 font-medium">
        <input type="checkbox" checked={t.bat} disabled={!ma.length && !t.goi_y.length}
          onChange={(e) => ghi({ bat: e.target.checked, cam_bien: ma.length ? ma : t.goi_y.map((x) => x.ma) })} />
        Tắt khi vắng
      </label>
      <p className="text-muted-foreground">
        Tắt là ngược của bật: mọi cảm biến dưới đây cùng báo vắng liền số phút này mà thiết bị còn bật thì bot
        tắt (người vừa tự bật trong 5 phút thì chưa tắt; khung giờ «Tắt: không làm» — vd giờ ngủ — thì không
        tắt). Radar hay mất người khi nằm yên — xem bảng dưới để chọn phút.
      </p>
      {Object.entries(t.quay_lai_moi_ngay ?? {}).map(([ten, bang]) => (
        <div key={ten} className="text-muted-foreground">
          {ten}: vắng ≥ N phút rồi lại có người (lần/ngày) —{" "}
          {Object.entries(bang).map(([n, so]) => (
            <span key={n} className={`mr-2 ${Number(n) === t.phut ? "font-medium text-foreground" : ""}`}>{n}′: {so}</span>
          ))}
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-1">
        {t.cam_bien.map((x) => (
          <span key={x.ma} className="inline-flex items-center gap-1 rounded border bg-muted/50 px-1.5 py-0.5 text-[11px]">
            {x.ten}
            <button type="button" title="Bỏ" onClick={() => ghi({ cam_bien: ma.filter((m) => m !== x.ma),
              bat: t.bat && ma.length > 1 })}>
              <X className="size-3 text-destructive" />
            </button>
          </span>
        ))}
        {t.goi_y.filter((g) => !ma.includes(g.ma)).map((g) => (
          <button key={g.ma} type="button" className="inline-flex items-center gap-1 rounded border border-dashed px-1.5 py-0.5 text-[11px]"
            onClick={() => ghi({ cam_bien: [...ma, g.ma] })}>
            <Plus className="size-3" /> {g.ten}
          </button>
        ))}
        <Input className="h-7 w-48" list="kich-hoat-thuc-the" placeholder="thêm cảm biến" value={moi}
          onChange={(e) => setMoi(e.target.value)} />
        <Button variant="outline" size="sm" className="h-7" disabled={!moi.trim()}
          onClick={() => { ghi({ cam_bien: [...ma, doiMa(moi.trim())] }); setMoi(""); }}>
          <Plus className="size-3.5" />
        </Button>
        vắng
        <Input type="number" min={1} max={240} className="h-7 w-16" value={phut} onChange={(e) => setPhut(e.target.value)}
          onBlur={() => ghi({ phut: Number(phut) || 15 })} />
        phút
      </div>
    </div>
  );
}

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

function MotThietBi({ tb, taiLai, doiMa }: { tb: ThietBi; taiLai: () => Promise<void>; doiMa: (c: string) => string }) {
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
        <label className="flex items-center gap-2 font-medium"
          title="Bỏ tích = bot thôi điều khiển thiết bị này (như bỏ tích ở Sơ đồ kích hoạt)">
          <input type="checkbox" checked={tb.bat} onChange={(e) => void dat({ bat: e.target.checked, tu_lam: e.target.checked })} />
          {tb.ten}
        </label>
        <span className="font-mono text-xs text-muted-foreground">{tb.thiet_bi}</span>
        <span className="text-xs text-muted-foreground">
          học theo {tb.co_so === "so_do" ? "sơ đồ kích hoạt" : "tự dò cả nhà (sơ đồ chưa có cảm biến)"}
        </span>
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
            {hd === "off" && tb.tat_khi_vang?.bat ? (
              <div className="text-xs text-emerald-600">
                Tắt khi: {tb.tat_khi_vang.cam_bien.map((x) => x.ten).join(" + ")} vắng liền {tb.tat_khi_vang.phut} phút
                (sửa ở «Tắt khi vắng» bên dưới). Luật học từ lịch sử bên dưới chỉ để tham khảo.
              </div>
            ) : (
              <div className="text-xs"><CapDo h={h} nguong={tb.nguong} /></div>
            )}
            <TheoGio ds={h.theo_gio || []} />
            {h.nguon.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-xs text-muted-foreground">Điều khiển — khi:</span>
                {h.nguon.map((n) => (
                  <span key={n.ma} className="inline-flex items-center gap-1 rounded border bg-muted/50 px-1.5 py-0.5 text-[11px]"
                    title={`${n.ma} — đứng trước ${n.so_lan ?? 0} lần người ${TEN_HD[hd].toLowerCase()}, ${n.du_chac ?? 0} lần rơi vào luật đủ chắc`}>
                    {n.ten} ({n.so_lan ?? 0})
                    <button type="button" title="Bỏ nguồn này (bot học lại không có nó)"
                      onClick={() => void dat({ bo_nguon: [...boMa, n.ma] })}>
                      <X className="size-3 text-destructive" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            {(h.da_xet?.length ?? 0) > 0 && (
              <div className="text-[11px] text-muted-foreground">
                Đã xét, không dùng (có đứng trước lần {TEN_HD[hd].toLowerCase()} nhưng luật không bao giờ đủ chắc theo nó):{" "}
                {h.da_xet!.map((n) => n.ten).join(", ")}
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

      {tb.kiem_ao ? <KiemAo k={tb.kiem_ao} doiMa={doiMa} luu={(v) => dat({ kiem_ao: v })} /> : null}
      {tb.tat_khi_vang ? <TatKhiVang t={tb.tat_khi_vang} doiMa={doiMa} luu={(v) => dat({ tat_khi_vang: v })} /> : null}

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
  const [thucThe, setThucThe] = useState<ThucThe[]>([]);

  const tai = useCallback(async () => {
    const r = await layGet<{ danh_sach?: ThietBi[] }>("/api/hoc-hoi/kich-hoat");
    setDs(r.danh_sach || []);
  }, []);

  useEffect(() => {
    void tai();
    void layGet<{ danh_sach?: ThucThe[] }>("/api/hoc-hoi/thuc-the").then((r) => setThucThe(r.danh_sach || []));
  }, [tai]);

  const doiMa = (chu: string) => thucThe.find((t) => t.ma === chu || t.ten === chu)?.ma ?? chu;
  const dangDieuKhien = ds.filter((tb) => tb.bat);

  return (
    <div className="space-y-3">
      <datalist id="kich-hoat-thuc-the">
        {thucThe.map((t) => <option key={t.ma} value={t.ma}>{t.ten}</option>)}
      </datalist>
      <p className="text-xs text-muted-foreground">
        Thiết bị anh <b>tích ở Sơ đồ kích hoạt</b>. Bot học luật bật/tắt từ điều kiện và ngoại vi trong sơ đồ
        (giờ, cảm biến, độ sáng…), thử trên 7 ngày cuối; giờ nào bot đã đúng ≥ 90% thì tự làm, lưng chừng thì
        hỏi anh trong nhóm học hỏi («có»/«không»), rõ là không thì im. Anh làm ngược lại trong 10 phút là bot ghi
        sai. Dưới mỗi thiết bị: kiểm báo ảo trước khi bật, tắt khi vắng, khung giờ của anh — đều sửa được.
      </p>
      {dangDieuKhien.map((tb) => <MotThietBi key={tb.thiet_bi} tb={tb} taiLai={tai} doiMa={doiMa} />)}
      {!dangDieuKhien.length ? (
        <p className="text-center text-xs text-muted-foreground">Chưa thiết bị nào — tích ở Sơ đồ kích hoạt để giao cho bot.</p>
      ) : null}
    </div>
  );
}
