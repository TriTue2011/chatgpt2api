"use client";

/**
 * Chỉnh tay trên thẻ Kích hoạt — chủ máy 01/10/2026: "các trạng thái, thông số kích hoạt tôi muốn chỉnh trên
 * webui được". Bốn nhóm bot tự học mà trước đây chỉ xem được:
 *
 *  - Ngoại vi của thiết bị (sơ đồ bot học luật từ đó)      → /api/hoc-hoi/so-do/sua rồi học lại
 *  - Ngưỡng trong luật bot học (ghim — lần học sau giữ số)   → /api/hoc-hoi/kich-hoat/dat {ghim}
 *  - Bài tự xác minh                                         → /api/hoc-hoi/xac-minh/{lua-chon,sua}
 *  - «Có người thật» + ngưỡng vùng khoảng cách radar         → /api/hoc-hoi/co-nguoi/sua, /vung-khoang-cach/dat
 *
 * Điều chủ máy đặt thắng điều bot học; backend kiểm biên (mã phải có thật).
 */

import { useState } from "react";
import { Pencil, Plus, RotateCcw, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { goiPost, layGet } from "./lib";

export type NgoaiViTb = {
  khoa: string;
  ds: { ma: string; ten: string; vai_tro: string; cua_chu_may: boolean; dung_duoc: boolean }[];
  bo: { ma: string; ten: string }[];
};
export type DieuKien = { key: string; nho_hon: boolean; nguong: number; ghim_duoc: boolean };
export type Ghim = Partial<Record<"on" | "off", Record<string, number>>>;

const VAI_TRO: Record<string, string> = {
  hien_dien: "hiện diện", khoang_cach: "khoảng cách", dem_nguoi: "đếm người", anh_sang: "ánh sáng",
  nhiet_do: "nhiệt độ", do_am: "độ ẩm", thiet_bi: "thiết bị đi kèm", khac: "khác",
};

function Chip({ children, onX, title }: { children: React.ReactNode; onX?: () => void; title?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border bg-muted/50 px-1.5 py-0.5 text-[11px]" title={title}>
      {children}
      {onX ? (
        <button type="button" title="Bỏ" onClick={onX}><X className="size-3 text-destructive" /></button>
      ) : null}
    </span>
  );
}

// ── Ngoại vi ────────────────────────────────────────────────────────────────
export function NgoaiVi({ nv, thietBi, doiMa, xong }: {
  nv: NgoaiViTb; thietBi: string; doiMa: (c: string) => string; xong: () => Promise<void>;
}) {
  const [moi, setMoi] = useState("");
  const [dang, setDang] = useState(false);
  const sua = async (hanh_dong: "them" | "bo" | "bo_lai", ma: string) => {
    setDang(true);
    try {
      if (await goiPost("/api/hoc-hoi/so-do/sua", { khoa: nv.khoa, loai: "nv", hanh_dong, muc: { ma, ten: "" } })) {
        await goiPost("/api/hoc-hoi/kich-hoat/hoc", { thiet_bi: thietBi });
        await xong();
      }
    } finally {
      setDang(false);
    }
  };
  return (
    <div className="space-y-1 border-t pt-2 text-xs">
      <div className="font-medium">Ngoại vi bot học luật từ đó</div>
      <p className="text-muted-foreground">
        Bot chọn theo hướng dẫn; anh thêm/bỏ ở đây là bot học lại luật ngay. Mã MQTT (có «/») bộ học kích hoạt không đọc
        được — nên dùng mã Home Assistant.
      </p>
      <div className="flex flex-wrap items-center gap-1">
        {nv.ds.length ? nv.ds.map((x) => (
          <Chip key={x.ma} onX={dang ? undefined : () => void sua("bo", x.ma)}
            title={`${x.ma}${x.cua_chu_may ? " — anh thêm" : " — bot chọn"}`}>
            <span className={x.dung_duoc ? "" : "text-destructive line-through"}>{x.ten}</span>
            <span className="text-muted-foreground">({VAI_TRO[x.vai_tro] || (x.cua_chu_may ? "anh thêm" : "khác")})</span>
          </Chip>
        )) : <span className="text-muted-foreground">chưa có — bot đang tự dò cả nhà</span>}
        <Input className="h-7 w-56" list="kich-hoat-thuc-the" placeholder="thêm cảm biến (vd khoảng cách radar)"
          value={moi} onChange={(e) => setMoi(e.target.value)} />
        <Button variant="outline" size="sm" className="h-7" disabled={!moi.trim() || dang}
          onClick={() => { void sua("them", doiMa(moi.trim())); setMoi(""); }}>
          <Plus className="size-3.5" />
        </Button>
      </div>
      {nv.bo.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-muted-foreground">Anh đã bỏ:</span>
          {nv.bo.map((x) => (
            <span key={x.ma} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px]">
              {x.ten}
              <button type="button" title="Cho dùng lại" disabled={dang} onClick={() => void sua("bo_lai", x.ma)}>
                <RotateCcw className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Ghim ngưỡng trong luật bot học ─────────────────────────────────────────
const gioChu = (g: number) => {
  const p = Math.round(g * 60);
  return `${String(Math.floor(p / 60) % 24).padStart(2, "0")}:${String(p % 60).padStart(2, "0")}`;
};

/** Hỏi số mới cho một điều kiện; trả undefined khi anh bấm huỷ, NaN khi gõ sai. */
function hoiNguong(dk: DieuKien, ten: string): number | undefined {
  const gio = dk.key === "giờ";
  const r = window.prompt(
    gio ? `Ghim mốc giờ (HH:MM) — đang là ${gioChu(dk.nguong)}` : `Ghim ngưỡng «${ten}» — đang là ${dk.nguong}`,
    gio ? gioChu(dk.nguong) : String(dk.nguong),
  );
  if (r === null) return undefined;
  if (gio) {
    const m = r.trim().match(/^(\d{1,2}):(\d{2})$/);
    return m ? Number(m[1]) + Number(m[2]) / 60 : NaN;
  }
  return Number(r.replace(",", "."));
}

export function DieuKienLuat({ neu, dk, ghim, tenKhoa, luuGhim }: {
  neu: string[]; dk?: DieuKien[]; ghim: Record<string, number>;
  tenKhoa: (k: string) => string; luuGhim: (key: string, nguong: number | null) => Promise<void>;
}) {
  if (!neu.length) return <>mọi lúc</>;
  return (
    <>
      {neu.map((chu, i) => {
        const d = dk?.[i];
        return (
          <span key={i}>
            {i ? " VÀ " : ""}
            {d?.ghim_duoc ? (
              <button type="button" className="underline decoration-dotted underline-offset-2 hover:text-primary"
                title={ghim[d.key] !== undefined ? "Anh đã ghim số này — bấm để đổi" : "Bấm để ghim số khác (lần học sau bot giữ số anh đặt)"}
                onClick={() => {
                  const v = hoiNguong(d, tenKhoa(d.key));
                  if (v === undefined) return;
                  if (!Number.isFinite(v)) { window.alert("Số không hợp lệ."); return; }
                  void luuGhim(d.key, v);
                }}>
                {chu}{ghim[d.key] !== undefined ? " 📌" : ""}<Pencil className="ml-0.5 inline size-2.5" />
              </button>
            ) : chu}
          </span>
        );
      })}
    </>
  );
}

export function DanhSachGhim({ ghim, tenKhoa, luuGhim }: {
  ghim: Record<string, number>; tenKhoa: (k: string) => string; luuGhim: (key: string, nguong: number | null) => Promise<void>;
}) {
  const ds = Object.entries(ghim);
  if (!ds.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1 text-[11px]">
      <span className="text-muted-foreground">Anh ghim:</span>
      {ds.map(([k, v]) => (
        <Chip key={k} onX={() => void luuGhim(k, null)} title="Bỏ ghim — bot tự chọn lại ngưỡng">
          {tenKhoa(k)} = {k === "giờ" ? gioChu(v) : v}
        </Chip>
      ))}
    </div>
  );
}

// ── Bài tự xác minh ─────────────────────────────────────────────────────────
type HuongXm = { hoi: string; xac_minh: string[]; lech_lich: string[]; kiem_lai?: string[]; nha_vang?: string[] };
type BaiXm = { bat: HuongXm; tat: HuongXm; tu_cham: { bat: string[]; tat: string[] } };
type NguonXm = { ma: string; ten: string; loai: string; khu: string };

const TRONG: BaiXm = {
  bat: { hoi: "khi_khong_ro", xac_minh: [], lech_lich: [], kiem_lai: [] },
  tat: { hoi: "khi_khong_ro", xac_minh: [], lech_lich: [], nha_vang: [] },
  tu_cham: { bat: [], tat: [] },
};
const HOI_CHU: Record<string, string> = {
  khong: "không thấy người thì thôi, không hỏi", khi_khong_ro: "không thấy người thì hỏi anh", luon: "luôn hỏi anh",
};
const MUC_XM: { h: "bat" | "tat"; k: keyof HuongXm; chu: string }[] = [
  { h: "bat", k: "xac_minh", chu: "Trước khi bật (lúc luật định hỏi), nhìn" },
  { h: "bat", k: "lech_lich", chu: "…thêm khi lịch nói cả nhà vắng/ngủ" },
  { h: "bat", k: "kiem_lai", chu: "Sau khi bật, kiểm lại mỗi 2 phút bằng" },
  { h: "tat", k: "xac_minh", chu: "Trước khi tắt khi vắng, còn thấy người ở" },
  { h: "tat", k: "lech_lich", chu: "…thêm khi lịch nói cả nhà vắng/ngủ" },
  { h: "tat", k: "nha_vang", chu: "Nhà vắng theo" },
];

function DsNguon({ ds, nguon, doi }: { ds: string[]; nguon: NguonXm[]; doi: (v: string[]) => void }) {
  const ten = (m: string) => nguon.find((x) => x.ma === m)?.ten || m;
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {ds.map((m) => <Chip key={m} onX={() => doi(ds.filter((x) => x !== m))} title={m}>{ten(m)}</Chip>)}
      <select className="rounded border bg-background px-1 py-0.5 text-[11px]" value=""
        onChange={(e) => e.target.value && doi([...ds, e.target.value])}>
        <option value="">+ thêm</option>
        {nguon.filter((x) => !ds.includes(x.ma)).map((x) => (
          <option key={x.ma} value={x.ma}>{x.ten} — {x.loai}{x.khu ? ` (${x.khu})` : ""}</option>
        ))}
      </select>
    </span>
  );
}

export function XacMinh({ thietBi }: { thietBi: string }) {
  const [mo, setMo] = useState(false);
  const [nguon, setNguon] = useState<NguonXm[]>([]);
  const [bai, setBai] = useState<BaiXm | null>(null);
  const [coSan, setCoSan] = useState(false);
  const [nguyHiem, setNguyHiem] = useState(false);
  const tai = async () => {
    const r = await layGet<{ ap?: BaiXm | null; nguon?: NguonXm[]; nguy_hiem?: boolean }>(
      `/api/hoc-hoi/xac-minh/lua-chon?thiet_bi=${encodeURIComponent(thietBi)}`);
    setNguon(r.nguon || []);
    setCoSan(!!r.ap);
    setNguyHiem(!!r.nguy_hiem);
    setBai(r.ap ? { bat: { ...TRONG.bat, ...r.ap.bat }, tat: { ...TRONG.tat, ...r.ap.tat }, tu_cham: { ...TRONG.tu_cham, ...r.ap.tu_cham } } : TRONG);
  };
  const doi = (h: "bat" | "tat", k: keyof HuongXm, v: string | string[]) =>
    setBai((b) => (b ? { ...b, [h]: { ...b[h], [k]: v } } : b));
  const luu = async () => {
    if (!bai) return;
    if (await goiPost("/api/hoc-hoi/xac-minh/sua", {
      thiet_bi: thietBi, gia_tri: { ...bai, chac: 1, vi_sao: "anh sửa trên web" },
    })) await tai();
  };
  return (
    <div className="space-y-1 border-t pt-2 text-xs">
      <button type="button" className="font-medium" onClick={() => { if (!mo) void tai(); setMo(!mo); }}>
        {mo ? "▾" : "▸"} Bài tự xác minh (camera, cảm biến kiểm trước khi bật/tắt)
      </button>
      {mo && bai ? (
        <div className="space-y-1 pl-3">
          {!coSan ? <p className="text-muted-foreground">Chưa có bài đang áp — anh soạn rồi lưu là áp ngay.</p> : null}
          {nguyHiem ? <p className="text-destructive">Thiết bị nguy hiểm: bot không bao giờ tự bật dù xác minh thấy người.</p> : null}
          {MUC_XM.map(({ h, k, chu }) => (
            <div key={`${h}.${k}`} className="flex flex-wrap items-center gap-1">
              <span className="text-muted-foreground">{chu}:</span>
              <DsNguon ds={(bai[h][k] as string[] | undefined) || []} nguon={nguon} doi={(v) => doi(h, k, v)} />
            </div>
          ))}
          {(["bat", "tat"] as const).map((h) => (
            <div key={h} className="flex flex-wrap items-center gap-1">
              <span className="text-muted-foreground">{h === "bat" ? "Bật" : "Tắt"}: </span>
              <select className="rounded border bg-background px-1 py-0.5" value={bai[h].hoi}
                onChange={(e) => doi(h, "hoi", e.target.value)}>
                {Object.entries(HOI_CHU).map(([v, c]) => <option key={v} value={v}>{c}</option>)}
              </select>
            </div>
          ))}
          {(["bat", "tat"] as const).map((h) => (
            <div key={`tc.${h}`} className="flex flex-wrap items-center gap-1">
              <span className="text-muted-foreground">Tự chấm sau khi {h === "bat" ? "bật" : "tắt"} bằng:</span>
              <DsNguon ds={bai.tu_cham[h]} nguon={nguon}
                doi={(v) => setBai((b) => (b ? { ...b, tu_cham: { ...b.tu_cham, [h]: v } } : b))} />
            </div>
          ))}
          <Button variant="outline" size="sm" className="h-7" onClick={() => void luu()}>
            <Save className="mr-1 size-3.5" /> Lưu và áp
          </Button>
        </div>
      ) : null}
    </div>
  );
}

// ── «Có người thật» + vùng khoảng cách ─────────────────────────────────────
type Nut = { ma?: string; la?: string[]; khong?: Nut; khoang_cach?: string; va?: Nut[]; hoac?: Nut[] };
type Nguyen = { kc: true; ma: string } | { kc: false; ma: string; la: string[]; khong: boolean };
type Vung = { radar?: string; dat?: boolean; huong?: string; nguong?: number; nguong_chu?: number; dung?: number; don_vi?: string };

function nguyenTu(x: Nut): Nguyen | null {
  if (x.khoang_cach) return { kc: true, ma: x.khoang_cach };
  if (x.ma) return { kc: false, ma: x.ma, la: x.la || ["on"], khong: false };
  if (x.khong?.ma) return { kc: false, ma: x.khong.ma, la: x.khong.la || ["on"], khong: true };
  return null;
}
/** Biểu thức → các nhóm HOẶC, mỗi nhóm là các điều kiện VÀ. Không vừa khuôn này thì null (sửa bằng JSON). */
function thanhNhom(bt: Nut): Nguyen[][] | null {
  const nhom = (x: Nut) => {
    const ds = (x.va || [x]).map(nguyenTu);
    return ds.every(Boolean) ? (ds as Nguyen[]) : null;
  };
  const ra = (bt.hoac || [bt]).map(nhom);
  return ra.every(Boolean) ? (ra as Nguyen[][]) : null;
}
function veNut(a: Nguyen): Nut {
  if (a.kc) return { khoang_cach: a.ma };
  const goc: Nut = a.la.length === 1 && a.la[0] === "on" ? { ma: a.ma } : { ma: a.ma, la: a.la };
  return a.khong ? { khong: goc } : goc;
}
function thanhBieuThuc(ds: Nguyen[][]): Nut {
  const nhom = (g: Nguyen[]) => (g.length === 1 ? veNut(g[0]) : { va: g.map(veNut) });
  return ds.length === 1 ? nhom(ds[0]) : { hoac: ds.map(nhom) };
}

export function CoNguoiThat({ thietBi, camBien, tenCua, doiMa, xong }: {
  thietBi: string; camBien: string[]; tenCua: (m: string) => string; doiMa: (c: string) => string;
  xong: () => Promise<void>;
}) {
  const [mo, setMo] = useState(false);
  const [nhom, setNhom] = useState<Nguyen[][] | null>(null);
  const [json, setJson] = useState("");
  const [vung, setVung] = useState<Record<string, Vung>>({});
  const [moi, setMoi] = useState<Record<number, { ma: string; khong: boolean }>>({});
  const vang = camBien.find((m) => m.startsWith("binary_sensor.c2a_vang_")) || camBien.find((m) => m.startsWith("binary_sensor.c2a_"));
  const tai = async () => {
    const [g, v] = await Promise.all([
      layGet<{ danh_sach?: { ma: string; bieu_thuc: Nut }[] }>("/api/hoc-hoi/cam-bien-ghep"),
      layGet<{ vung?: Record<string, Vung> }>("/api/hoc-hoi/vung-khoang-cach"),
    ]);
    setVung(v.vung || {});
    const bt = (g.danh_sach || []).find((x) => x.ma === vang)?.bieu_thuc;
    // Chưa có cảm biến ghép: danh sách «tắt khi vắng» nghĩa là MỘT cái báo có người là còn người → mỗi cái một nhóm HOẶC.
    const n = bt ? thanhNhom(bt) : camBien.map((m) => [{ kc: false as const, ma: m, la: ["on"], khong: false }]);
    setNhom(n);
    setJson(JSON.stringify(bt || {}, null, 1));
  };
  const luu = async (bt: Nut) => {
    if (await goiPost("/api/hoc-hoi/co-nguoi/sua", { thiet_bi: thietBi, bieu_thuc: bt })) {
      await xong();
      await tai();
    }
  };
  const datNguong = async (ma: string, chu: string) => {
    const so = chu.trim() ? Number(chu.replace(",", ".")) : null;
    if (so !== null && !Number.isFinite(so)) return;
    if (await goiPost("/api/hoc-hoi/vung-khoang-cach/dat", { ma, nguong: so })) await tai();
  };
  const doiNhom = (i: number, g: Nguyen[]) =>
    setNhom((n) => (n ? (g.length ? n.map((x, j) => (j === i ? g : x)) : n.filter((_, j) => j !== i)) : n));
  const chuNguyen = (a: Nguyen) => (a.kc
    ? `khoảng cách ${tenCua(a.ma)} trong vùng khu`
    : `${a.khong ? "không " : ""}${tenCua(a.ma)}${a.la.join("/") === "on" ? "" : ` là ${a.la.join("/")}`}`);
  const kcDung = Array.from(new Set((nhom || []).flat().filter((a) => a.kc).map((a) => a.ma)));

  return (
    <div className="space-y-1 border-t pt-2 text-xs">
      <button type="button" className="font-medium" onClick={() => { if (!mo) void tai(); setMo(!mo); }}>
        {mo ? "▾" : "▸"} «Có người thật» — điều kiện coi là còn người (tắt khi vắng dựa vào đây)
      </button>
      {mo ? (
        <div className="space-y-1 pl-3">
          {nhom ? (
            <>
              {nhom.map((g, i) => (
                <div key={i} className="flex flex-wrap items-center gap-1">
                  <span className="text-muted-foreground">{i ? "HOẶC" : "Có người khi"}</span>
                  {g.map((a, k) => (
                    <span key={k} className="inline-flex items-center gap-1">
                      {k ? <span className="text-muted-foreground">VÀ</span> : null}
                      <Chip onX={() => doiNhom(i, g.filter((_, j) => j !== k))} title={a.ma}>{chuNguyen(a)}</Chip>
                    </span>
                  ))}
                  <Input className="h-6 w-44" list="kich-hoat-thuc-the" placeholder="+ VÀ cảm biến"
                    value={moi[i]?.ma || ""} onChange={(e) => setMoi({ ...moi, [i]: { ma: e.target.value, khong: !!moi[i]?.khong } })} />
                  <label className="flex items-center gap-0.5" title="Điều kiện là cảm biến này KHÔNG báo có người">
                    <input type="checkbox" checked={!!moi[i]?.khong}
                      onChange={(e) => setMoi({ ...moi, [i]: { ma: moi[i]?.ma || "", khong: e.target.checked } })} /> không
                  </label>
                  <Button variant="outline" size="sm" className="h-6" disabled={!moi[i]?.ma?.trim()}
                    onClick={() => {
                      const ma = doiMa(moi[i].ma.trim());
                      doiNhom(i, [...g, ma.startsWith("sensor.") ? { kc: true, ma } : { kc: false, ma, la: ["on"], khong: moi[i].khong }]);
                      setMoi({ ...moi, [i]: { ma: "", khong: false } });
                    }}>
                    <Plus className="size-3" />
                  </Button>
                </div>
              ))}
              <div className="flex flex-wrap gap-1">
                <Button variant="outline" size="sm" className="h-7"
                  onClick={() => setNhom([...nhom, []])}>
                  <Plus className="mr-1 size-3.5" /> nhóm HOẶC
                </Button>
                <Button variant="outline" size="sm" className="h-7" disabled={!nhom.some((g) => g.length)}
                  onClick={() => void luu(thanhBieuThuc(nhom.filter((g) => g.length)))}>
                  <Save className="mr-1 size-3.5" /> Lưu và áp
                </Button>
              </div>
              <p className="text-muted-foreground">
                Gõ mã <span className="font-mono">sensor.…</span> (khoảng cách radar) là thành điều kiện «trong vùng khu».
                Anh lưu thì bot không tự đè — chỉ bài được chấm đúng sau lần sửa này mới thay.
              </p>
            </>
          ) : (
            <div className="space-y-1">
              <p className="text-muted-foreground">Biểu thức lồng sâu — sửa dạng JSON.</p>
              <textarea className="h-28 w-full rounded border bg-background p-1 font-mono text-[11px]" value={json}
                onChange={(e) => setJson(e.target.value)} />
              <Button variant="outline" size="sm" className="h-7"
                onClick={() => { try { void luu(JSON.parse(json)); } catch { window.alert("JSON không hợp lệ."); } }}>
                <Save className="mr-1 size-3.5" /> Lưu và áp
              </Button>
            </div>
          )}
          {kcDung.map((ma) => {
            const v = vung[ma] || {};
            return (
              <div key={ma} className="flex flex-wrap items-center gap-1">
                <span className="text-muted-foreground">Vùng {tenCua(ma)}:</span>
                {v.dat ? <span>bot học {v.huong === "duoi" ? "dưới" : "từ"} {v.nguong} {v.don_vi || "m"} (đúng {Math.round((v.dung || 0) * 100)}%)</span>
                  : <span className="text-amber-600">bot chưa học được vùng</span>}
                <span>· anh đặt</span>
                <Input className="h-6 w-20" type="number" step="0.1" min={0} defaultValue={v.nguong_chu ?? ""}
                  placeholder="bot học" onBlur={(e) => void datNguong(ma, e.target.value)} />
                <span className="text-muted-foreground">{v.don_vi || "m"} (để trống = theo bot)</span>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
