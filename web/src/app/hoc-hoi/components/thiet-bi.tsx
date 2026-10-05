"use client";

/**
 * Thiết bị — MỘT chỗ cho mỗi thiết bị: gập sẵn; mở ra có BẬT và TẮT (cũng gập sẵn). Mỗi chiều là danh sách TRƯỜNG
 * HỢP kèm điều kiện (sự kiện, khoảng cách, trạng thái cảm biến, giờ, lịch…), cuối dòng ✓ chạy · ✗ tạm dừng · ✎ sửa ·
 * 🗑 xoá. Bot chỉ ĐỀ XUẤT (luật học từ lịch sử, luật chuyển từ lời anh); anh duyệt / sửa là chạy ngay.
 *
 * Chủ máy 05/10/2026: "Tab học hỏi đang dài dòng khó hiểu… mỗi thiết bị luôn ẩn, mở ra chia làm bật và tắt cũng luôn
 * ẩn… gom theo từng trường hợp… tích v, x… thùng rác… Tất cả đều có thể chỉnh sửa, thêm, xoá". API:
 * GET /api/hoc-hoi/thiet-bi · POST /api/hoc-hoi/truong-hop · GET /api/hoc-hoi/cam-bien-luat.
 */

import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, Pencil, Plus, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { layGet, goiPost } from "./lib";

type DieuKien = {
  ma: string; la?: string; duoi?: number; tren?: number; tu?: string; den?: string;
  lien_giay?: number; trong_giay?: number; phu_dinh?: boolean; dung_yen_giay?: number; lech?: number;
};
type Luat = { chieu: "bat" | "tat"; nen: string; khi: string[]; neu: DieuKien[]; xac_minh: boolean };
type TruongHop = Luat & {
  id: string; loi: string; nguon: "anh" | "bot" | "bot_hoc";
  trang_thai: "chay" | "dung" | "cho" | "sai" | "chua_chuyen" | "de_xuat";
  dong: string[]; ly_do?: string;
};
type TheoNep = { bat: boolean; nhiet?: string | null; nep: { du: boolean; gio?: string; phut_bat?: number; ly_do?: string } };
type ThietBi = {
  thiet_bi: string; ten: string; bat: boolean; o_lai_giay?: number | null; roi_giay?: number | null;
  tat_khi_vang: { bat: boolean; phut?: number; cam_bien: string[]; nhin: string[] } | null;
  ngoai_vi: { ma: string; ten: string; vai_tro?: string }[];
  truong_hop: { bat: TruongHop[]; tat: TruongHop[] };
  theo_nep: TheoNep | null;
};
type CamBien = { ma: string; ten: string; khu: string; loai: string; don_vi?: string };

const TRANG_THAI: Record<TruongHop["trang_thai"], [string, string]> = {
  chay: ["Đang chạy", "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"],
  dung: ["Tạm dừng", "bg-muted text-muted-foreground"],
  cho: ["Chờ anh duyệt", "bg-amber-500/15 text-amber-700 dark:text-amber-400"],
  sai: ["Anh nói sai — chờ bot sửa", "bg-rose-500/15 text-rose-700 dark:text-rose-400"],
  chua_chuyen: ["Bot chưa chuyển được", "bg-muted text-muted-foreground"],
  de_xuat: ["Bot đề xuất", "bg-sky-500/15 text-sky-700 dark:text-sky-400"],
};
const NEN: Record<"bat" | "tat", [string, string][]> = {
  bat: [["bat", "bật"], ["khong_lam", "KHÔNG bật (chặn)"], ["hoi", "hỏi anh"]],
  tat: [["tat", "tắt"], ["giu", "GIỮ, không tắt (chặn)"], ["hoi", "hỏi anh"]],
};

function docThietBi(): Promise<ThietBi[]> {
  return layGet<{ danh_sach?: ThietBi[] }>("/api/hoc-hoi/thiet-bi").then((r) => r.danh_sach || []).catch(() => []);
}

function Gap({ tieuDe, phu, children, mo = false }: { tieuDe: React.ReactNode; phu?: React.ReactNode; children: React.ReactNode; mo?: boolean }) {
  const [m, setM] = useState(mo);
  return (
    <div className="rounded border border-border">
      <button type="button" className="flex w-full items-center gap-2 px-2 py-1.5 text-left" onClick={() => setM(!m)}>
        {m ? <ChevronDown className="size-4 shrink-0" /> : <ChevronRight className="size-4 shrink-0" />}
        <span className="font-medium">{tieuDe}</span>
        {phu ? <span className="ml-auto text-muted-foreground">{phu}</span> : null}
      </button>
      {m ? <div className="space-y-2 border-t border-border p-2">{children}</div> : null}
    </div>
  );
}

function tom(ds: TruongHop[]): string {
  const chay = ds.filter((x) => x.trang_thai === "chay").length;
  const cho = ds.filter((x) => x.trang_thai === "cho" || x.trang_thai === "de_xuat" || x.trang_thai === "sai").length;
  return `${chay} đang chạy${cho ? ` · ${cho} chờ anh` : ""}`;
}

// ── Sửa / thêm một trường hợp ───────────────────────────────────────────────
type LoaiDk = "trang_thai" | "so_do" | "gio" | "lich" | "ca_nha" | "troi";

function loaiCua(d: DieuKien): LoaiDk {
  if (d.ma === "gio") return "gio";
  if (d.ma === "lich") return "lich";
  if (d.ma === "ca_nha") return "ca_nha";
  if (d.ma === "troi") return "troi";
  if (d.duoi !== undefined || d.tren !== undefined || d.dung_yen_giay !== undefined) return "so_do";
  return "trang_thai";
}

function SuaTruongHop({ chieu, ban, camBien, lich, onLuu, onHuy }: {
  chieu: "bat" | "tat"; ban: TruongHop | null; camBien: CamBien[]; lich: { ma: string; ten: string }[];
  onLuu: (loi: string, l: Luat) => void; onHuy: () => void;
}) {
  const nhiPhan = camBien.filter((c) => c.ma.startsWith("binary_sensor."));
  const so = camBien.filter((c) => c.ma.startsWith("sensor."));
  const khiDau = ban?.khi?.[0] || "";
  const m = /^(\S+) (có người vào|vắng|ở lại (\d+) giây|vắng (\d+) giây)$/.exec(khiDau);
  const [loi, setLoi] = useState(ban?.trang_thai === "de_xuat" ? "" : ban?.loi || "");
  const [nen, setNen] = useState(ban?.nen || chieu);
  const [camKhi, setCamKhi] = useState(m?.[1] || "");
  const [kieuKhi, setKieuKhi] = useState(m ? (m[3] ? "o_lai" : m[4] ? "vang_n" : m[2]) : "có người vào");
  const [giayKhi, setGiayKhi] = useState(m?.[3] || m?.[4] || "30");
  const [neu, setNeu] = useState<DieuKien[]>(ban?.neu || []);
  const [xm, setXm] = useState(Boolean(ban?.xac_minh));

  const khi = camKhi ? `${camKhi} ${kieuKhi === "o_lai" ? `ở lại ${giayKhi} giây` : kieuKhi === "vang_n" ? `vắng ${giayKhi} giây` : kieuKhi}` : "";
  const sua = (i: number, d: Partial<DieuKien> | null) =>
    setNeu(d === null ? neu.filter((_, j) => j !== i) : neu.map((x, j) => (j === i ? { ...x, ...d } : x)));
  const doiLoai = (i: number, loai: LoaiDk) => {
    const moi: Record<LoaiDk, DieuKien> = {
      trang_thai: { ma: nhiPhan[0]?.ma || "", la: "on" }, so_do: { ma: so[0]?.ma || "", duoi: 3 },
      gio: { ma: "gio", tu: "18:00", den: "22:00" }, lich: { ma: "lich", la: lich[0]?.ma || "" },
      ca_nha: { ma: "ca_nha", la: "ngu" }, troi: { ma: "troi", la: "toi" },
    };
    setNeu(neu.map((x, j) => (j === i ? moi[loai] : x)));
  };
  const chon = (v: string, ds: CamBien[], f: (v: string) => void) => (
    <select className="h-8 max-w-56 rounded border border-border bg-background px-1" value={v} onChange={(e) => f(e.target.value)}>
      <option value="">— chọn —</option>
      {ds.map((c) => <option key={c.ma} value={c.ma}>{c.ten} ({c.khu})</option>)}
    </select>
  );

  return (
    <div className="space-y-2 rounded border border-primary/40 bg-muted/30 p-2">
      <Input className="h-8" placeholder="Trường hợp (lời anh), vd «Cửa mở, cam phòng khách thấy người»" value={loi}
        onChange={(e) => setLoi(e.target.value)} />
      <div className="flex flex-wrap items-center gap-1">
        <span>Khi</span>
        {chon(camKhi, nhiPhan, setCamKhi)}
        <select className="h-8 rounded border border-border bg-background px-1" value={kieuKhi} onChange={(e) => setKieuKhi(e.target.value)}>
          <option value="có người vào">có người vào / mở</option>
          <option value="vắng">vắng 3 phút</option>
          <option value="o_lai">ở lại … giây</option>
          <option value="vang_n">vắng … giây</option>
        </select>
        {kieuKhi === "o_lai" || kieuKhi === "vang_n" ? (
          <Input className="h-8 w-20" value={giayKhi} onChange={(e) => setGiayKhi(e.target.value.replace(/\D/g, ""))} />
        ) : null}
        <span>thì</span>
        <select className="h-8 rounded border border-border bg-background px-1" value={nen} onChange={(e) => setNen(e.target.value)}>
          {NEN[chieu].map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
      </div>
      {neu.map((d, i) => {
        const loai = loaiCua(d);
        return (
          <div key={i} className="flex flex-wrap items-center gap-1 pl-3">
            <span>nếu</span>
            <label className="flex items-center gap-1"><input type="checkbox" checked={Boolean(d.phu_dinh)}
              onChange={(e) => sua(i, { phu_dinh: e.target.checked || undefined })} />KHÔNG</label>
            <select className="h-8 rounded border border-border bg-background px-1" value={loai} onChange={(e) => doiLoai(i, e.target.value as LoaiDk)}>
              <option value="trang_thai">cảm biến</option><option value="so_do">số đo</option><option value="gio">giờ</option>
              <option value="lich">lịch</option><option value="ca_nha">cả nhà</option><option value="troi">trời</option>
            </select>
            {loai === "trang_thai" ? (<>
              {chon(d.ma, nhiPhan, (v) => sua(i, { ma: v }))}
              <select className="h-8 rounded border border-border bg-background px-1" value={d.la || "on"} onChange={(e) => sua(i, { la: e.target.value })}>
                <option value="on">có người / mở</option><option value="off">không / đóng</option>
              </select>
              <span>liền</span>
              <Input className="h-8 w-16" placeholder="giây" value={d.lien_giay ?? ""}
                onChange={(e) => sua(i, { lien_giay: e.target.value ? Number(e.target.value.replace(/\D/g, "")) : undefined })} />
            </>) : null}
            {loai === "so_do" ? (<>
              {chon(d.ma, so, (v) => sua(i, { ma: v }))}
              <select className="h-8 rounded border border-border bg-background px-1" value={d.tren !== undefined ? "tren" : "duoi"}
                onChange={(e) => { const v = d.duoi ?? d.tren ?? 0; sua(i, e.target.value === "tren" ? { tren: v, duoi: undefined } : { duoi: v, tren: undefined }); }}>
                <option value="duoi">dưới</option><option value="tren">trên</option>
              </select>
              <Input className="h-8 w-20" value={d.duoi ?? d.tren ?? ""}
                onChange={(e) => { const v = Number(e.target.value.replace(",", ".")); sua(i, d.tren !== undefined ? { tren: v } : { duoi: v }); }} />
            </>) : null}
            {loai === "gio" ? (<>
              <Input className="h-8 w-20" value={d.tu || ""} onChange={(e) => sua(i, { tu: e.target.value })} /><span>–</span>
              <Input className="h-8 w-20" value={d.den || ""} onChange={(e) => sua(i, { den: e.target.value })} />
            </>) : null}
            {loai === "lich" ? (
              <select className="h-8 rounded border border-border bg-background px-1" value={d.la || ""} onChange={(e) => sua(i, { la: e.target.value })}>
                {lich.map((x) => <option key={x.ma} value={x.ma}>{x.ten}</option>)}
              </select>
            ) : null}
            {loai === "ca_nha" ? (
              <select className="h-8 rounded border border-border bg-background px-1" value={d.la || "ngu"} onChange={(e) => sua(i, { la: e.target.value })}>
                <option value="ngu">đang ngủ</option><option value="vang">đi vắng</option>
              </select>
            ) : null}
            {loai === "troi" ? (
              <select className="h-8 rounded border border-border bg-background px-1" value={d.la || "toi"} onChange={(e) => sua(i, { la: e.target.value })}>
                <option value="toi">tối</option><option value="sang">sáng</option>
              </select>
            ) : null}
            <Button size="sm" variant="ghost" title="Bỏ điều kiện" onClick={() => sua(i, null)}><X className="size-4" /></Button>
          </div>
        );
      })}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => setNeu([...neu, { ma: nhiPhan[0]?.ma || "", la: "on" }])}>
          <Plus className="size-4" /> điều kiện
        </Button>
        <label className="flex items-center gap-1"><input type="checkbox" checked={xm} onChange={(e) => setXm(e.target.checked)} />
          nhìn lại camera trước khi làm</label>
        <span className="ml-auto flex gap-2">
          <Button size="sm" variant="ghost" onClick={onHuy}>Huỷ</Button>
          <Button size="sm" disabled={!khi} onClick={() => onLuu(loi, { chieu, nen, khi: [khi], neu, xac_minh: xm })}>Lưu &amp; chạy</Button>
        </span>
      </div>
    </div>
  );
}

// ── Một chiều (Bật / Tắt) của một thiết bị ──────────────────────────────────
function Chieu({ tb, chieu, camBien, lich, tai }: {
  tb: ThietBi; chieu: "bat" | "tat"; camBien: CamBien[]; lich: { ma: string; ten: string }[]; tai: () => void;
}) {
  const ds = tb.truong_hop[chieu];
  const [dangSua, setDangSua] = useState<string | null>(null);
  const [giay, setGiay] = useState(String((chieu === "bat" ? tb.o_lai_giay : tb.roi_giay) ?? ""));

  const quyet = async (viec: string, id = "", luat?: Luat, loi?: string) => {
    if (viec === "xoa" && !window.confirm("Xoá trường hợp này?")) return;
    if (await goiPost("/api/hoc-hoi/truong-hop", { thiet_bi: tb.thiet_bi, viec, id, luat, loi })) { setDangSua(null); tai(); }
  };
  const luuGiay = async () => {
    const g = Number(giay || 0);
    const khoa = chieu === "bat" ? "o_lai_giay" : "roi_giay";
    if (await goiPost("/api/hoc-hoi/kich-hoat/dat", { thiet_bi: tb.thiet_bi, [khoa]: g })) tai();
  };
  const tn = tb.theo_nep;

  return (
    <Gap tieuDe={chieu === "bat" ? "Bật" : "Tắt"} phu={tom(ds)}>
      {ds.length === 0 && !tn ? <p className="text-muted-foreground">Chưa có trường hợp nào.</p> : null}
      {ds.map((x) => dangSua === x.id ? (
        <SuaTruongHop key={x.id} chieu={chieu} ban={x} camBien={camBien} lich={lich} onHuy={() => setDangSua(null)}
          onLuu={(loi, l) => void quyet(x.trang_thai === "de_xuat" ? "them" : "sua", x.id, l, loi)} />
      ) : (
        <div key={x.id} className="flex gap-2 rounded border border-border p-2">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-[11px] ${TRANG_THAI[x.trang_thai][1]}`}>{TRANG_THAI[x.trang_thai][0]}</span>
              <span className="font-medium">{x.loi || "(chưa đặt tên)"}</span>
              {x.nguon === "anh" ? <span className="text-muted-foreground">· anh nêu</span> : null}
            </div>
            {x.dong.length ? (
              <ul className="list-disc pl-5 text-muted-foreground">{x.dong.map((d, i) => <li key={i}>{d}</li>)}</ul>
            ) : <p className="text-muted-foreground">{x.ly_do}</p>}
          </div>
          <div className="flex shrink-0 items-start gap-0.5">
            {x.trang_thai !== "chay" && x.trang_thai !== "chua_chuyen" ? (
              <Button size="sm" variant="ghost" title="Chạy theo trường hợp này" onClick={() => void quyet("duyet", x.id)}>
                <Check className="size-4 text-emerald-600" /></Button>) : null}
            {x.trang_thai === "chay" || x.trang_thai === "de_xuat" ? (
              <Button size="sm" variant="ghost" title={x.trang_thai === "de_xuat" ? "Bỏ đề xuất" : "Tạm dừng"}
                onClick={() => void quyet("dung", x.id)}><X className="size-4 text-amber-600" /></Button>) : null}
            <Button size="sm" variant="ghost" title="Sửa (lưu là chạy)" onClick={() => setDangSua(x.id)}><Pencil className="size-4" /></Button>
            {x.trang_thai !== "de_xuat" ? (
              <Button size="sm" variant="ghost" title="Xoá" onClick={() => void quyet("xoa", x.id)}><Trash2 className="size-4 text-rose-600" /></Button>) : null}
          </div>
        </div>
      ))}
      {tn && chieu === "bat" ? (
        <div className="flex items-center gap-2 rounded border border-border p-2">
          <span className="flex-1">
            <b>Tự bật theo nếp</b> — {tn.nep.du ? `~${tn.nep.gio}, bật ${tn.nep.phut_bat} phút (học từ lần anh bật; chỉ khi nhà có người, hôm nay chưa ai bật)` : `chưa đủ nếp: ${tn.nep.ly_do}`}
          </span>
          <label className="flex items-center gap-1"><input type="checkbox" checked={tn.bat}
            onChange={async (e) => { if (await goiPost("/api/hoc-hoi/theo-nep", { thiet_bi: tb.thiet_bi, bat: e.target.checked })) tai(); }} />chạy</label>
        </div>
      ) : null}
      {tn && chieu === "tat" ? (
        <p className="rounded border border-border p-2 text-muted-foreground">
          Tự tắt sau thời lượng theo nếp. <b>Chưa có cảm biến xác nhận đã tắt</b> (dòng điện / nhiệt độ) — gắn công tắc đo
          công suất thì bot kiểm được bình còn đun hay đã ngắt.
        </p>
      ) : null}
      {dangSua === "moi" ? (
        <SuaTruongHop chieu={chieu} ban={null} camBien={camBien} lich={lich} onHuy={() => setDangSua(null)}
          onLuu={(loi, l) => void quyet("them", "", l, loi)} />
      ) : (
        <Button size="sm" variant="outline" onClick={() => setDangSua("moi")}><Plus className="size-4" /> Thêm trường hợp</Button>
      )}
      {tb.tat_khi_vang ? (
        <div className="space-y-1 border-t border-border pt-2 text-muted-foreground">
          <div className="flex flex-wrap items-center gap-2">
            <span>{chieu === "bat" ? "Chờ người ở lại" : "Phòng vắng"}</span>
            <Input className="h-7 w-20" placeholder="bot học" value={giay} onChange={(e) => setGiay(e.target.value.replace(/\D/g, ""))} />
            <span>giây {chieu === "bat" ? "rồi mới bật" : "thì tắt"} (trống = bot tự học)</span>
            <Button size="sm" variant="ghost" onClick={() => void luuGiay()}>Lưu</Button>
          </div>
          {chieu === "tat" ? (
            <p>Kiểm chứng vắng: {tb.tat_khi_vang.cam_bien.join(", ") || "—"}
              {tb.tat_khi_vang.nhin.length ? ` · nhìn lại: ${tb.tat_khi_vang.nhin.join(", ")}` : ""}</p>
          ) : null}
          <p>Ngoại vi: {tb.ngoai_vi.map((n) => n.ten).join(", ") || "—"}</p>
        </div>
      ) : null}
    </Gap>
  );
}

/** Thêm thiết bị dùng theo GIỜ (bình nóng lạnh, máy lọc nước…) — bot học giờ + thời lượng từ lần người bật. */
function ThemTheoNep({ tai }: { tai: () => void }) {
  const [ma, setMa] = useState("");
  const [nhiet, setNhiet] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
      <span>Thêm thiết bị tự bật theo nếp:</span>
      <Input className="h-7 w-52" placeholder="switch.binh_nong_lanh" value={ma} onChange={(e) => setMa(e.target.value)} />
      <Input className="h-7 w-56" placeholder="cảm biến nhiệt ngoài trời (tuỳ chọn)" value={nhiet} onChange={(e) => setNhiet(e.target.value)} />
      <Button size="sm" variant="outline" disabled={!ma.trim()} onClick={async () => {
        if (await goiPost("/api/hoc-hoi/theo-nep", { thiet_bi: ma.trim(), bat: true, nhiet: nhiet.trim() || null })) {
          setMa(""); setNhiet(""); tai();
        }
      }}><Plus className="size-4" /> Thêm</Button>
    </div>
  );
}

export function ThietBiNha() {
  const [ds, setDs] = useState<ThietBi[] | null>(null);
  const [camBien, setCamBien] = useState<CamBien[]>([]);
  const [lich, setLich] = useState<{ ma: string; ten: string }[]>([]);

  const tai = useCallback(() => { void docThietBi().then(setDs); }, []);
  useEffect(() => {
    let song = true;
    void docThietBi().then((x) => { if (song) setDs(x); });
    void layGet<{ cam_bien?: CamBien[]; lich?: { ma: string; ten: string }[] }>("/api/hoc-hoi/cam-bien-luat")
      .then((r) => { if (song) { setCamBien(r.cam_bien || []); setLich(r.lich || []); } }).catch(() => {});
    return () => { song = false; };
  }, []);

  if (ds === null) return <p className="text-xs text-muted-foreground">Đang tải…</p>;
  return (
    <div className="space-y-2 text-xs">
      <p className="text-muted-foreground">
        Mỗi thiết bị có danh sách trường hợp BẬT và TẮT. Bot chỉ đề xuất; trường hợp anh ✓ (hoặc sửa) mới chạy. Chiều nào
        chưa có trường hợp anh duyệt thì bot tạm chạy theo những gì nó học.
      </p>
      {ds.map((tb) => (
        <Gap key={tb.thiet_bi} tieuDe={tb.ten}
          phu={`Bật: ${tom(tb.truong_hop.bat)} — Tắt: ${tom(tb.truong_hop.tat)}`}>
          {tb.tat_khi_vang ? (
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={tb.bat}
                onChange={async (e) => { if (await goiPost("/api/hoc-hoi/kich-hoat/dat", { thiet_bi: tb.thiet_bi, bat: e.target.checked })) tai(); }} />
              Tự động bật / tắt thiết bị này
            </label>
          ) : null}
          <Chieu tb={tb} chieu="bat" camBien={camBien} lich={lich} tai={tai} />
          <Chieu tb={tb} chieu="tat" camBien={camBien} lich={lich} tai={tai} />
        </Gap>
      ))}
      <ThemTheoNep tai={tai} />
    </div>
  );
}
