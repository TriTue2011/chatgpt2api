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
import { Check, ChevronDown, ChevronRight, Plus, RefreshCw, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { layGet, goiPost } from "./lib";

type DieuKien = {
  ma: string; la?: string; duoi?: number; tren?: number; tu?: string; den?: string;
  lien_giay?: number; trong_giay?: number; vua_chuyen_giay?: number; phu_dinh?: boolean; dung_yen_giay?: number; lech?: number;
  thu?: number[]; tu_ngay?: string; den_ngay?: string; so_voi?: string;
};
type Luat = { chieu: "bat" | "tat"; nen: string; khi: string[]; neu: DieuKien[]; xac_minh: boolean };
type TruongHop = Luat & {
  id: string; loi: string; nguon: "anh" | "bot" | "bot_hoc";
  trang_thai: "chay" | "dung" | "cho" | "sai" | "chua_chuyen" | "de_xuat" | "cho_kich_ban";
  dong: string[]; ly_do?: string; so_kb?: number;
};
type TheoNep = { bat: boolean; nhiet?: string | null; nep: { du: boolean; gio?: string; phut_bat?: number; ly_do?: string } };
type ThietBi = {
  thiet_bi: string; ten: string; bat: boolean; o_lai_giay?: number | null; roi_giay?: number | null;
  cho_vang_them?: Record<string, number>;   // giờ → phút bot chờ LÂU HƠN mức sàn (đo thấy người hay quay lại)
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
  cho_kich_ban: ["Chờ anh duyệt kịch bản", "bg-amber-500/15 text-amber-700 dark:text-amber-400"],
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

/** Điều kiện cảm biến đang tính thời gian theo cách nào (mỗi điều kiện tối đa một — lõi `_KHOANG_GIAY`). */
function kieuGiay(d: DieuKien): "dang" | "lien_giay" | "trong_giay" | "vua_chuyen_giay" {
  if (d.vua_chuyen_giay !== undefined) return "vua_chuyen_giay";
  if (d.trong_giay !== undefined) return "trong_giay";
  return d.lien_giay !== undefined ? "lien_giay" : "dang";
}

/** Chữ cho hai trạng thái theo LOẠI cảm biến (`loai` của /api/hoc-hoi/cam-bien-luat) — chủ máy 06/10/2026: «có người
 *  / mở» cho mọi cảm biến đọc không ổn. Cửa mở/đóng, camera thấy người, radar có người; loại khác giữ bật/tắt. */
function chuTrangThai(c?: CamBien): [string, string] {
  const l = c?.loai || "";
  if (l.startsWith("cửa")) return ["mở", "đóng"];
  if (l.startsWith("camera")) return ["thấy người", "không thấy người"];
  if (l.startsWith("có người")) return ["có người", "không có người"];
  return ["bật", "tắt"];
}

function tom(ds: TruongHop[]): string {
  const chay = ds.filter((x) => x.trang_thai === "chay").length;
  const cho = ds.filter((x) => ["cho", "de_xuat", "sai", "cho_kich_ban"].includes(x.trang_thai)).length;
  return `${chay} đang chạy${cho ? ` · ${cho} chờ anh` : ""}`;
}

/** Chia trường hợp theo CẢM BIẾN CỬA: «cửa chuyển chế độ» (luật bắt đầu từ cửa đổi đóng ↔ mở) và «cửa giữ một chế
 * độ» (mọi luật khác — radar, camera, khoảng cách…). Chủ máy 05/10/2026: "chia theo trường hợp cụ thể. Ví dụ cảm biến
 * cửa chính chuyển chế độ. Cảm biến cửa chính giữ 1 chế độ". Thiết bị không có luật nào theo cửa thì chia theo cảm
 * biến kích hoạt. */
function nhomTruongHop(ds: TruongHop[], camBien: CamBien[]): { ten: string; ds: TruongHop[] }[] {
  const ten = (ma: string) => camBien.find((c) => c.ma === ma)?.ten || ma;
  const cua = new Set(camBien.filter((c) => c.loai.startsWith("cửa")).map((c) => c.ma));
  const kichCua = (x: TruongHop) => (x.khi || []).map((k) => k.split(" ")[0]).find((m) => cua.has(m));
  const theoCua = ds.filter(kichCua);
  if (theoCua.length) {
    const tenCua = ten(kichCua(theoCua[0]) as string);
    const con = ds.filter((x) => !kichCua(x));
    return [{ ten: `${tenCua} chuyển chế độ (đóng ↔ mở)`, ds: theoCua },
      ...(con.length ? [{ ten: `${tenCua} giữ một chế độ`, ds: con }] : [])];
  }
  const nhom = new Map<string, TruongHop[]>();
  for (const x of ds) {
    const k = x.khi?.[0] ? `Khi ${ten(x.khi[0].split(" ")[0])}` : "Bot chưa chuyển được";
    nhom.set(k, [...(nhom.get(k) || []), x]);
  }
  return [...nhom.entries()].map(([k, v]) => ({ ten: k, ds: v }));
}

// ── Sửa / thêm một trường hợp ───────────────────────────────────────────────
type LoaiDk = "trang_thai" | "so_do" | "gio" | "lich" | "ca_nha" | "troi" | "so_sanh";
const THU = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
/** «24:00» (hết ngày — lõi chấp nhận) không có trong bộ chọn giờ của trình duyệt → ô trống (chủ máy 06/10/2026 chụp
 *  màn hình). Hiện 23:59; không chạm ô thì giá trị lưu vẫn là 24:00. */
const gioHien = (v?: string) => (v === "24:00" ? "23:59" : v || "");
/** Số đo: dưới / trên / trong khoảng (có cả hai) / ngoài khoảng (có cả hai + phủ định) — lõi luat_duyet._kiem_dk. */
function kieuSo(d: DieuKien): "duoi" | "tren" | "trong" | "ngoai" {
  if (d.duoi !== undefined && d.tren !== undefined) return d.phu_dinh ? "ngoai" : "trong";
  return d.tren !== undefined ? "tren" : "duoi";
}

/** «KHÔNG» không còn là ô riêng (chủ máy 05/10/2026: "Mục nếu không là gì") — lật thẳng vào lựa chọn: không có người,
 * trên ↔ dưới, sáng ↔ tối. Giờ / lịch / cả nhà giữ cờ phủ định nhưng chọn bằng «ngoài khung», «không ngủ»… */
function boPhuDinh(d: DieuKien): DieuKien {
  if (!d.phu_dinh) return d;
  const { phu_dinh: _bo, ...x } = d;
  void _bo;
  if (x.ma === "troi") return { ...x, la: x.la === "toi" ? "sang" : "toi" };
  if (x.duoi !== undefined) return { ...x, tren: x.duoi, duoi: undefined };
  if (x.tren !== undefined) return { ...x, duoi: x.tren, tren: undefined };
  if (["gio", "lich", "ca_nha"].includes(x.ma)) return d;
  if (x.dung_yen_giay !== undefined) return d;
  return { ...x, la: x.la === "off" ? "on" : "off" };
}

function loaiCua(d: DieuKien): LoaiDk {
  if (d.ma === "gio") return "gio";
  if (d.ma === "lich") return "lich";
  if (d.ma === "ca_nha") return "ca_nha";
  if (d.ma === "troi") return "troi";
  if (d.so_voi !== undefined) return "so_sanh";
  if (d.duoi !== undefined || d.tren !== undefined || d.dung_yen_giay !== undefined) return "so_do";
  return "trang_thai";
}

function SuaTruongHop({ chieu, ban, camBien, lich, onLuu, onHuy, them }: {
  chieu: "bat" | "tat"; ban: TruongHop | null; camBien: CamBien[]; lich: { ma: string; ten: string }[];
  onLuu: (loi: string, l: Luat) => void; onHuy?: () => void; them?: React.ReactNode;
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
  const [neu, setNeu] = useState<DieuKien[]>((ban?.neu || []).map(boPhuDinh));
  const [xm, setXm] = useState(Boolean(ban?.xac_minh));

  const chuKhi = chuTrangThai(nhiPhan.find((c) => c.ma === camKhi));
  const khi = camKhi ? `${camKhi} ${kieuKhi === "o_lai" ? `ở lại ${giayKhi} giây` : kieuKhi === "vang_n" ? `vắng ${giayKhi} giây` : kieuKhi}` : "";
  const sua = (i: number, d: Partial<DieuKien> | null) =>
    setNeu(d === null ? neu.filter((_, j) => j !== i) : neu.map((x, j) => (j === i ? { ...x, ...d } : x)));
  const doiLoai = (i: number, loai: LoaiDk) => {
    const moi: Record<LoaiDk, DieuKien> = {
      trang_thai: { ma: nhiPhan[0]?.ma || "", la: "on" }, so_do: { ma: so[0]?.ma || "", duoi: 3 },
      gio: { ma: "gio", tu: "18:00", den: "22:00" }, lich: { ma: "lich", la: lich[0]?.ma || "" },
      ca_nha: { ma: "ca_nha", la: "ngu" }, troi: { ma: "troi", la: "toi" },
      so_sanh: { ma: camBien[0]?.ma || "", so_voi: camBien[1]?.ma || "" },
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
          <option value="có người vào">chuyển từ {chuKhi[1]} sang {chuKhi[0]}</option>
          <option value="vắng">{chuKhi[1]} 3 phút</option>
          <option value="o_lai">{chuKhi[0]} được … giây</option>
          <option value="vang_n">{chuKhi[1]} được … giây</option>
        </select>
        {kieuKhi === "o_lai" || kieuKhi === "vang_n" ? (
          <><Input className="h-8 w-20" value={giayKhi} onChange={(e) => setGiayKhi(e.target.value.replace(/\D/g, ""))} /><span>giây</span></>
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
            <select className="h-8 rounded border border-border bg-background px-1" value={loai} onChange={(e) => doiLoai(i, e.target.value as LoaiDk)}>
              <option value="trang_thai">cảm biến</option><option value="so_do">số đo</option><option value="so_sanh">so sánh 2 cảm biến</option><option value="gio">thời gian</option>
              <option value="lich">lịch</option><option value="ca_nha">cả nhà</option><option value="troi">trời</option>
            </select>
            {loai === "trang_thai" ? (<>
              {chon(d.ma, nhiPhan, (v) => sua(i, { ma: v }))}
              {(() => {
                // Chủ máy 06/10/2026: cần NHIỀU chế độ cảm biến, câu đọc phải xuôi — «đang» (không cần số giây), «đã … được ít nhất N giây», «vừa chuyển
                // sang» (cửa để mở sẵn không tính), «từng … trong N giây qua». Mỗi điều kiện một chế độ (lõi `_KHOANG_GIAY`).
                const [on, off] = chuTrangThai(nhiPhan.find((c) => c.ma === d.ma));
                const tt = d.la === "off" ? off : on;
                const k = kieuGiay(d);
                return (<>
                  <select className="h-8 rounded border border-border bg-background px-1" value={k}
                    onChange={(e) => {
                      const v = e.target.value;
                      const giay = d.lien_giay ?? d.trong_giay ?? d.vua_chuyen_giay ?? 30;
                      sua(i, { lien_giay: undefined, trong_giay: undefined, vua_chuyen_giay: undefined, ...(v === "dang" ? {} : { [v]: giay }) });
                    }}>
                    <option value="dang">đang</option>
                    <option value="lien_giay">đã</option>
                    <option value="vua_chuyen_giay">vừa chuyển</option>
                    <option value="trong_giay">có lúc</option>
                  </select>
                  <select className="h-8 rounded border border-border bg-background px-1" value={d.la || "on"} onChange={(e) => sua(i, { la: e.target.value })}>
                    {k === "vua_chuyen_giay"
                      ? <><option value="on">từ {off} sang {on}</option><option value="off">từ {on} sang {off}</option></>
                      : <><option value="on">{on}</option><option value="off">{off}</option></>}
                  </select>
                  {k !== "dang" ? (<>
                    <span>{k === "lien_giay" ? "được ít nhất" : "trong"}</span>
                    <Input className="h-8 w-16" value={d[k] ?? ""}
                      onChange={(e) => sua(i, { [k]: e.target.value ? Number(e.target.value.replace(/\D/g, "")) : undefined })} />
                    <span>{k === "lien_giay" ? "giây" : "giây qua"}</span>
                  </>) : null}
                  <span className="w-full pl-6 text-xs text-muted-foreground">
                    {k === "dang" ? `→ Đạt khi đúng lúc đó cảm biến đang ${tt}.`
                      : k === "lien_giay" ? `→ Đạt khi cảm biến ${tt} liên tục, không ngắt quãng, từ ít nhất ${d.lien_giay ?? "…"} giây trước tới giờ.`
                        : k === "vua_chuyen_giay" ? `→ Đạt khi cảm biến vừa đổi từ ${d.la === "off" ? on : off} sang ${tt} trong ${d.vua_chuyen_giay ?? "…"} giây vừa qua. Nếu đã ${tt} từ lâu thì KHÔNG đạt.`
                          : `→ Đạt khi bây giờ cảm biến ${tt}, hoặc có lúc ${tt} trong ${d.trong_giay ?? "…"} giây vừa qua.`}
                  </span>
                </>);
              })()}
            </>) : null}
            {loai === "so_do" ? (<>
              {chon(d.ma, so, (v) => sua(i, { ma: v }))}
              <select className="h-8 rounded border border-border bg-background px-1" value={kieuSo(d)}
                onChange={(e) => {
                  const k = e.target.value, a = d.tren ?? d.duoi ?? 0, b = d.duoi ?? d.tren ?? 0;
                  if (k === "duoi") sua(i, { duoi: b, tren: undefined, phu_dinh: undefined });
                  else if (k === "tren") sua(i, { tren: a, duoi: undefined, phu_dinh: undefined });
                  else sua(i, { tren: Math.min(a, b), duoi: a === b ? a + 1 : Math.max(a, b), phu_dinh: k === "ngoai" || undefined });
                }}>
                <option value="duoi">dưới</option><option value="tren">trên</option>
                <option value="trong">trong khoảng</option><option value="ngoai">ngoài khoảng</option>
              </select>
              {kieuSo(d) === "duoi" || kieuSo(d) === "tren" ? (
                <Input className="h-8 w-20" type="number" step="any" value={d.duoi ?? d.tren ?? ""}
                  onChange={(e) => { const v = Number(e.target.value); sua(i, d.tren !== undefined ? { tren: v } : { duoi: v }); }} />
              ) : (<>
                <Input className="h-8 w-20" type="number" step="any" value={d.tren ?? ""} title="từ"
                  onChange={(e) => sua(i, { tren: Number(e.target.value) })} /><span>–</span>
                <Input className="h-8 w-20" type="number" step="any" value={d.duoi ?? ""} title="tới"
                  onChange={(e) => sua(i, { duoi: Number(e.target.value) })} />
              </>)}
              {/* Đơn vị lấy từ cài đặt cảm biến (HA unit_of_measurement) — đổi cảm biến là đổi theo. */}
              <span className="text-muted-foreground">{so.find((c) => c.ma === d.ma)?.don_vi || ""}</span>
            </>) : null}
            {loai === "gio" ? (() => {
              // Chủ máy 06/10/2026: thời gian có nhiều chế độ — chỉ giờ / chỉ thứ / chỉ ngày, hai trong ba, hoặc cả ba.
              // Bật phần nào thì phần đó mới vào điều kiện; phải còn ít nhất một phần.
              const co = { gio: d.tu !== undefined, thu: d.thu !== undefined, ngay: d.tu_ngay !== undefined || d.den_ngay !== undefined };
              const bat: Record<keyof typeof co, Partial<DieuKien>> = {
                gio: { tu: "18:00", den: "22:00" }, thu: { thu: [0, 1, 2, 3, 4, 5, 6] }, ngay: { tu_ngay: "", den_ngay: "" } };
              const tat: Record<keyof typeof co, Partial<DieuKien>> = {
                gio: { tu: undefined, den: undefined }, thu: { thu: undefined }, ngay: { tu_ngay: undefined, den_ngay: undefined } };
              // Chủ máy 06/10/2026: "thiếu chỉ có ngày hoặc thứ, thiếu thứ + ngày" — ba nút bật/tắt bắt người tự đoán phải
              // TẮT «giờ» mới ra «chỉ thứ». Nay chọn thẳng một trong 7 chế độ; đổi chế độ giữ nguyên giá trị phần còn lại.
              const CHE_DO: [string, string][] = [
                ["gio", "chỉ khung giờ"], ["thu", "chỉ thứ trong tuần"], ["ngay", "chỉ ngày (từ ngày … tới ngày …)"],
                ["gio+thu", "khung giờ + thứ"], ["gio+ngay", "khung giờ + ngày"], ["thu+ngay", "thứ + ngày"],
                ["gio+thu+ngay", "khung giờ + thứ + ngày"]];
              const cheDo = (["gio", "thu", "ngay"] as const).filter((k) => co[k]).join("+") || "gio";
              return (<>
                <select className="h-8 rounded border border-border bg-background px-1" value={cheDo}
                  onChange={(e) => {
                    const moi = e.target.value.split("+");
                    let doi: Partial<DieuKien> = {};
                    for (const k of ["gio", "thu", "ngay"] as const) {
                      if (moi.includes(k) && !co[k]) doi = { ...doi, ...bat[k] };
                      if (!moi.includes(k) && co[k]) doi = { ...doi, ...tat[k] };
                    }
                    sua(i, doi);
                  }}>
                  {CHE_DO.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select>
                <select className="h-8 rounded border border-border bg-background px-1" value={d.phu_dinh ? "ngoai" : "trong"}
                  onChange={(e) => sua(i, { phu_dinh: e.target.value === "ngoai" || undefined })}>
                  <option value="trong">đúng lúc đó</option><option value="ngoai">KHÔNG phải lúc đó</option>
                </select>
                {co.gio ? (
                  <span className="flex w-full flex-wrap items-center gap-1">
                    giờ
                    {/* Chọn bằng bộ chọn giờ — luôn ra đúng HH:MM, khỏi gõ cho khớp định dạng (chủ máy 06/10/2026). */}
                    <Input className="h-8 w-28" type="time" value={gioHien(d.tu)} onChange={(e) => sua(i, { tu: e.target.value })} /><span>–</span>
                    <Input className="h-8 w-28" type="time" value={gioHien(d.den)} onChange={(e) => sua(i, { den: e.target.value })} />
                  </span>) : null}
                {co.thu ? (
                  <span className="flex w-full flex-wrap items-center gap-0.5" title="Khung giờ qua nửa đêm tính theo ngày bắt đầu.">
                    thứ
                    {THU.map((t, j) => {
                      const on = (d.thu || []).includes(j);
                      return (
                        <button key={t} type="button"
                          className={`h-8 rounded border px-1.5 text-xs ${on ? "border-primary bg-primary/15 text-primary" : "border-border"}`}
                          title={on && d.thu?.length === 1 ? "Phải chọn ít nhất một ngày" : undefined}
                          onClick={() => {
                            const moi = on ? (d.thu || []).filter((v) => v !== j) : [...(d.thu || []), j].sort();
                            if (moi.length) sua(i, { thu: moi });
                          }}>{t}</button>
                      );
                    })}
                  </span>) : null}
                {co.ngay ? (
                  <span className="flex w-full flex-wrap items-center gap-1" title="Bỏ trống một đầu = không giới hạn đầu đó">
                    ngày
                    <Input className="h-8 w-[8.75rem] max-w-full" type="date" value={d.tu_ngay || ""} onChange={(e) => sua(i, { tu_ngay: e.target.value })} />
                    <span>→</span>
                    <Input className="h-8 w-[8.75rem] max-w-full" type="date" value={d.den_ngay || ""} onChange={(e) => sua(i, { den_ngay: e.target.value })} />
                  </span>) : null}
                <span className="w-full pl-6 text-xs text-muted-foreground">{(() => {
                  const phan = [
                    co.gio && d.tu && d.den ? `từ ${d.tu} tới ${d.den}` : "",
                    co.thu && d.thu && d.thu.length < 7 ? `vào ${d.thu.map((v) => THU[v]).join(", ")}` : "",
                    co.ngay && (d.tu_ngay || d.den_ngay) ? `${d.tu_ngay ? `từ ngày ${d.tu_ngay.split("-").reverse().join("/")}` : ""}${d.tu_ngay && d.den_ngay ? " " : ""}${d.den_ngay ? `tới hết ngày ${d.den_ngay.split("-").reverse().join("/")}` : ""}` : "",
                  ].filter(Boolean);
                  if (!phan.length) return "→ Chưa giới hạn gì: lúc nào cũng đạt (lưu vẫn được).";
                  return d.phu_dinh ? `→ Đạt khi KHÔNG nằm trong: ${phan.join(", ")}.` : `→ Đạt khi ${phan.join(", ")}.`;
                })()}</span>
              </>);
            })() : null}
            {loai === "so_sanh" ? (<>
              {chon(d.ma, camBien, (v) => sua(i, { ma: v }))}
              <select className="h-8 rounded border border-border bg-background px-1" value={d.phu_dinh ? "khac" : "giong"}
                onChange={(e) => sua(i, { phu_dinh: e.target.value === "khac" || undefined })}>
                <option value="giong">giống</option><option value="khac">khác</option>
              </select>
              {chon(d.so_voi || "", camBien, (v) => sua(i, { so_voi: v }))}
            </>) : null}
            {loai === "lich" ? (<>
              <select className="h-8 rounded border border-border bg-background px-1" value={d.phu_dinh ? "ngoai" : "trong"}
                onChange={(e) => sua(i, { phu_dinh: e.target.value === "ngoai" || undefined })}>
                <option value="trong">đang trong lịch</option><option value="ngoai">ngoài lịch</option>
              </select>
              <select className="h-8 rounded border border-border bg-background px-1" value={d.la || ""} onChange={(e) => sua(i, { la: e.target.value })}>
                {lich.map((x) => <option key={x.ma} value={x.ma}>{x.ten}</option>)}
              </select>
            </>) : null}
            {loai === "ca_nha" ? (
              <select className="h-8 rounded border border-border bg-background px-1" value={`${d.phu_dinh ? "khong_" : ""}${d.la || "ngu"}`}
                onChange={(e) => { const v = e.target.value; sua(i, { la: v.replace("khong_", ""), phu_dinh: v.startsWith("khong_") || undefined }); }}>
                <option value="ngu">cả nhà đang ngủ</option><option value="vang">cả nhà đi vắng</option>
                <option value="khong_ngu">KHÔNG phải giờ cả nhà ngủ</option><option value="khong_vang">có người ở nhà</option>
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
          {them}
          {onHuy ? <Button size="sm" variant="ghost" onClick={onHuy}>Huỷ</Button> : null}
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
  // Kịch bản bot soạn (chưa duyệt) — trước 05/10/2026 chỉ duyệt được qua Zalo; danh sách gửi đi không ai trả lời là
  // cả hàng thiết bị đứng im. Duyệt xong cả hai chiều thì máy chủ tự cho bot chuyển thành luật (`sua_duyet`).
  const choKb = ds.filter((x) => x.trang_thai === "cho_kich_ban");
  const duyetKb = async (viec: "duyet" | "bo", so?: number) => {
    if (viec === "bo" && !window.confirm("Bỏ trường hợp này khỏi kịch bản?")) return;
    if (await goiPost("/api/hoc-hoi/kich-ban/duyet", { tb: tb.thiet_bi, huong: chieu, viec, so })) tai();
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
      {choKb.length ? (
        <div className="flex flex-wrap items-center gap-2 rounded border border-amber-500/40 bg-amber-500/10 p-2">
          <span className="text-sm">
            {choKb.length} trường hợp {chieu === "bat" ? "bật" : "tắt"} bot soạn đang <b>chờ anh duyệt</b> — mở từng cái
            xem, bỏ cái sai, rồi duyệt. Duyệt xong cả Bật lẫn Tắt thì bot chuyển thành luật chạy được.
          </span>
          <Button size="sm" className="ml-auto" onClick={() => void duyetKb("duyet")}>
            <Check className="size-4" /> Duyệt phần {chieu === "bat" ? "Bật" : "Tắt"}
          </Button>
        </div>
      ) : null}
      {nhomTruongHop(ds, camBien).map((g) => (
        <Gap key={g.ten} tieuDe={g.ten} phu={tom(g.ds)}>
          {g.ds.map((x) => (
            <Gap key={x.id} tieuDe={
              <span className="flex flex-wrap items-center gap-2 font-normal">
                <span className={`rounded px-1.5 py-0.5 text-[11px] ${TRANG_THAI[x.trang_thai][1]}`}>{TRANG_THAI[x.trang_thai][0]}</span>
                <span className="font-medium">{x.loi || "(chưa đặt tên)"}</span>
              </span>}>
              {x.trang_thai === "cho_kich_ban" ? (<>
                <p className="text-muted-foreground">
                  Bot đề nghị: <b>{NEN[chieu].find(([v]) => v === x.nen)?.[1] || x.nen}</b> · {x.ly_do}
                </p>
                <Button size="sm" variant="outline" onClick={() => void duyetKb("bo", x.so_kb)}>
                  <Trash2 className="size-4 text-rose-600" /> Bỏ trường hợp này</Button>
              </>) : x.trang_thai === "chua_chuyen" ? (<>
                <p className="text-muted-foreground">{x.ly_do} — bấm «Bot học &amp; đề xuất lại» ở thiết bị để bot đưa ra điều kiện.</p>
                <Button size="sm" variant="outline" onClick={() => void quyet("xoa", x.id)}>
                  <Trash2 className="size-4 text-rose-600" /> Xoá trường hợp</Button>
              </>) : (
                // Mở ra là thấy TỪNG điều kiện — sửa / xoá / thêm ngay tại chỗ; «Lưu & chạy» = anh duyệt.
                <SuaTruongHop chieu={chieu} ban={x} camBien={camBien} lich={lich}
                  onLuu={(loi, l) => void quyet(x.trang_thai === "de_xuat" ? "them" : "sua", x.id, l, loi)}
                  them={<>
                    {x.trang_thai !== "chay" ? (
                      <Button size="sm" variant="outline" title="Chạy đúng như bot đề xuất, không sửa" onClick={() => void quyet("duyet", x.id)}>
                        <Check className="size-4 text-emerald-600" /> Chạy như cũ</Button>) : null}
                    {x.trang_thai === "chay" || x.trang_thai === "de_xuat" ? (
                      <Button size="sm" variant="outline" onClick={() => void quyet("dung", x.id)}>
                        <X className="size-4 text-amber-600" /> {x.trang_thai === "de_xuat" ? "Bỏ đề xuất" : "Tạm dừng"}</Button>) : null}
                    {x.trang_thai !== "de_xuat" ? (
                      <Button size="sm" variant="outline" onClick={() => void quyet("xoa", x.id)}>
                        <Trash2 className="size-4 text-rose-600" /> Xoá</Button>) : null}
                  </>} />
              )}
            </Gap>
          ))}
        </Gap>
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
            <span>giây {chieu === "bat" ? "rồi mới bật" : "thì tắt"} {chieu === "tat" ? "(ít nhất — trống = bot tự học)" : "(trống = bot tự học)"}</span>
            <Button size="sm" variant="ghost" onClick={() => void luuGiay()}>Lưu</Button>
          </div>
          {chieu === "tat" && Object.keys(tb.cho_vang_them || {}).length ? (
            <p className="text-amber-700 dark:text-amber-400">
              Bot chờ lâu hơn ở những giờ đo thấy người hay quay lại:{" "}
              {Object.entries(tb.cho_vang_them || {}).map(([h, p]) => `${h}h ${p} phút`).join(" · ")}
            </p>
          ) : null}
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

/** Bước đầu là BOT học rồi đưa ra trường hợp (chủ máy 05/10/2026) — anh bấm khi muốn bot chuyển lại toàn bộ trường
 * hợp của thiết bị thành điều kiện (một lượt gọi model), rồi sửa / duyệt từng cái. */
function BotDeXuat({ tb, tai }: { tb: string; tai: () => void }) {
  const [dang, setDang] = useState(false);
  return (
    <Button size="sm" variant="outline" disabled={dang} onClick={async () => {
      setDang(true);
      if (await goiPost("/api/hoc-hoi/luat-duyet", { viec: "giai", tb })) tai();
      setDang(false);
    }}><RefreshCw className={`size-4 ${dang ? "animate-spin" : ""}`} /> {dang ? "Bot đang học…" : "Bot học & đề xuất lại"}</Button>
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
          <BotDeXuat tb={tb.thiet_bi} tai={tai} />
          <Chieu tb={tb} chieu="bat" camBien={camBien} lich={lich} tai={tai} />
          <Chieu tb={tb} chieu="tat" camBien={camBien} lich={lich} tai={tai} />
        </Gap>
      ))}
      <ThemTheoNep tai={tai} />
    </div>
  );
}
