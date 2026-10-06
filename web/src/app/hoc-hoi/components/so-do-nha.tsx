"use client";

/**
 * Sơ đồ nhà — thứ bot đang hiểu về nhà: kiểu nhà, phòng nào thông / có vách với phòng nào, cửa chính, và từng
 * camera thấy phòng nào (tô ô lên chính ảnh lưới bot đã nhìn, kèm lời bot tả ảnh và lời chủ nhà khoanh). Chủ
 * máy 30/09/2026: "sơ đồ nhà không thấy hiển thị gì, mô tả của từng bức ảnh" — bản cũ chỉ có mục ảnh chờ đáp án.
 *
 * Ảnh CHỜ ĐÁP ÁN: nhà không có model đọc ảnh (hoặc chọn «thu_cong» ở thẻ Nhìn nhà) thì bot xuất ảnh đã kẻ lưới +
 * LỆNH; người dùng chép vào ChatGPT / Gemini / Claude của họ rồi dán đáp án (JSON) lại đây.
 *
 * Backend: api/hoc_hoi.py (/api/hoc-hoi/so-do-nha, /anh, /cham, /mo-ta, /giai, /cho-anh, /dap-an-anh,
 * /chup-camera) → services/so_do_nha.py.
 */

import { useCallback, useEffect, useState } from "react";
import { Camera, Check, Copy, Pencil, RefreshCw, Send, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { httpRequest, request } from "@/lib/request";
import { goiPost, layGet } from "./lib";

type Cho = { luc: number; anh_url: string; lenh: string; dem?: boolean };
type Phong = { ten: string; loai?: string; thong_voi?: string[]; vach_voi?: string[] };
type CamSo = { ten: string; thay?: Record<string, string[]> };
type SoDo = {
  kieu?: string;
  so_tang?: number | null;
  phong?: Phong[];
  cua_chinh?: { vao?: string };
  camera?: CamSo[];
  hoi_chu_nha?: string[];
  chac?: number;
  vi_sao?: string;
};
type Bai = { id: number; luc: number; gia_tri: SoDo; ket_qua: "cho" | "dung" | "sai"; ghi_chu?: string };
type MoTa = { luc: number; nguon: string; noi_dung: string };
type SoData = { mo_ta?: MoTa[]; bai?: Bai[]; ap?: (SoDo & { id: number }) | null; luoi?: { cot: number; hang: number };
  chu_khoanh?: Record<string, { phong?: Record<string, string[]>; do?: string[]; luc?: number }> };

const TEN_KIEU: Record<string, string> = {
  chung_cu: "Chung cư", nha_pho: "Nhà phố", biet_thu: "Nhà vườn / biệt thự", van_phong: "Văn phòng",
  xuong: "Xưởng", nha_dat: "Nhà đất", khong_ro: "Chưa rõ kiểu nhà",
};
// Màu tô ô theo thứ tự phòng — đủ khác nhau trên ảnh camera sáng lẫn tối.
const MAU = ["#ef4444", "#3b82f6", "#22c55e", "#eab308", "#a855f7", "#f97316", "#06b6d4", "#ec4899"];

const gio = (t: number) => new Date(t * 1000).toLocaleString("vi-VN");

type Khoanh = { phong?: Record<string, string[]>; do?: string[]; luc?: number };
const DO = "__do";

/** Ảnh lưới của một camera (tải kèm xác thực) + ô tô màu theo phòng. Chế độ KHOANH: chọn cọ (phòng / đồ đạc / xoá)
 * rồi bấm hay kéo qua các ô, lưu thành đáp án của chủ nhà (chủ máy 30/09/2026: "sao không tích được trên ảnh"). */
function AnhCamera({ cam, thay, doDac, mauPhong, luoi, phongDs, daKhoanh, xong }: {
  cam: string; thay: Record<string, string[]>; doDac: string[]; mauPhong: Record<string, string>;
  luoi: { cot: number; hang: number }; phongDs: string[]; daKhoanh: boolean; xong: () => Promise<void>;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [khong, setKhong] = useState(false);
  const [to, setTo] = useState(true);
  const [sua, setSua] = useState(false);
  const [nhap, setNhap] = useState<Record<string, string>>({});
  const [co, setCo] = useState<string>("");
  const [dangKeo, setDangKeo] = useState(false);

  useEffect(() => {
    let bo = "";
    request.get(`/api/hoc-hoi/so-do-nha/anh?camera=${encodeURIComponent(cam)}`, { responseType: "blob" })
      .then((r) => { bo = URL.createObjectURL(r.data as Blob); setUrl(bo); })
      .catch(() => setKhong(true));
    return () => { if (bo) URL.revokeObjectURL(bo); };
  }, [cam]);

  const batDauSua = () => {
    const m: Record<string, string> = {};
    Object.entries(thay).forEach(([p, ds]) => ds.forEach((o) => { m[o] = p; }));
    doDac.forEach((o) => { if (!m[o]) m[o] = DO; });
    setNhap(m);
    setCo(phongDs[0] || DO);
    setSua(true);
  };
  const to1 = (o: string) => setNhap((m) => {
    const n = { ...m };
    if (co) n[o] = co; else delete n[o];
    return n;
  });
  const luu = async () => {
    const phong: Record<string, string[]> = {};
    const doMoi: string[] = [];
    Object.entries(nhap).forEach(([o, p]) => { if (p === DO) doMoi.push(o); else (phong[p] ||= []).push(o); });
    if (await goiPost("/api/hoc-hoi/so-do-nha/khoanh", { camera: cam, phong, do: doMoi })) {
      toast.success("Đã lưu vùng anh khoanh — bot dùng vùng này thay bài tự đọc");
      setSua(false);
      await xong();
    }
  };
  const boKhoanh = async () => {
    if (!window.confirm("Bỏ vùng anh đã khoanh cho camera này, quay về bài bot tự đọc?")) return;
    if (await goiPost("/api/hoc-hoi/so-do-nha/khoanh", { camera: cam, phong: {}, do: [] })) {
      toast.success("Đã bỏ khoanh");
      setSua(false);
      await xong();
    }
  };

  if (khong) return <p className="text-xs text-muted-foreground">Chưa có ảnh camera này — bấm «Chụp lại camera».</p>;
  if (!url) return <p className="text-xs text-muted-foreground">Đang tải ảnh…</p>;
  const o: { p: string; ten: string }[] = sua
    ? Object.entries(nhap).map(([ten, p]) => ({ p, ten }))
    : [...Object.entries(thay).flatMap(([p, ds]) => ds.map((ten) => ({ p, ten }))), ...doDac.map((ten) => ({ p: DO, ten }))];
  const mau = (p: string) => (p === DO ? "#6b7280" : mauPhong[p] || "#888");
  const tenO = (c: number, h: number) => `${String.fromCharCode(65 + c)}${h + 1}`;
  return (
    <div className="space-y-1">
      {sua && (
        <div className="flex flex-wrap items-center gap-1 text-xs">
          <span className="text-muted-foreground">Cọ:</span>
          {[...phongDs, DO, ""].map((p) => (
            <button key={p || "_xoa"} type="button" onClick={() => setCo(p)}
              className={`rounded px-2 py-0.5 ${co === p ? "ring-2 ring-primary" : "border"}`}>
              {p && <span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: mau(p) }} />}
              {p === DO ? "Đồ đạc (không ai đứng)" : p || "Xoá"}
            </button>
          ))}
        </div>
      )}
      <div className="relative inline-block max-w-full touch-none select-none"
        onPointerUp={() => setDangKeo(false)} onPointerLeave={() => setDangKeo(false)}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={cam} className="block max-h-80 max-w-full rounded" draggable={false} />
        {(to || sua) && o.map(({ p, ten }) => {
          const m = /^([A-Z])(\d{1,2})$/.exec(ten);
          if (!m) return null;
          const c = m[1].charCodeAt(0) - 65, h = Number(m[2]) - 1;
          return (
            <div key={`${p}-${ten}`} title={`${ten}: ${p === DO ? "đồ đạc" : p}`} className="pointer-events-none absolute"
              style={{ left: `${(c / luoi.cot) * 100}%`, top: `${(h / luoi.hang) * 100}%`,
                width: `${100 / luoi.cot}%`, height: `${100 / luoi.hang}%`, background: mau(p), opacity: 0.4 }} />
          );
        })}
        {sua && Array.from({ length: luoi.cot * luoi.hang }, (_, i) => {
          const c = i % luoi.cot, h = Math.floor(i / luoi.cot), ten = tenO(c, h);
          return (
            <div key={ten} title={ten} className="absolute cursor-crosshair border border-white/10"
              style={{ left: `${(c / luoi.cot) * 100}%`, top: `${(h / luoi.hang) * 100}%`,
                width: `${100 / luoi.cot}%`, height: `${100 / luoi.hang}%` }}
              onPointerDown={(e) => { e.preventDefault(); setDangKeo(true); to1(ten); }}
              onPointerEnter={() => { if (dangKeo) to1(ten); }} />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        {!sua ? (
          <>
            <Button size="sm" variant="outline" onClick={batDauSua}><Pencil className="mr-1 h-4 w-4" />Khoanh / sửa ô</Button>
            {o.length > 0 && (
              <button type="button" className="text-muted-foreground underline" onClick={() => setTo(!to)}>
                {to ? "Ẩn ô tô màu" : "Hiện ô tô màu"}
              </button>
            )}
            {daKhoanh && <button type="button" className="text-destructive underline" onClick={() => void boKhoanh()}>Bỏ vùng đã khoanh</button>}
          </>
        ) : (
          <>
            <Button size="sm" onClick={() => void luu()}><Check className="mr-1 h-4 w-4" />Lưu vùng khoanh</Button>
            <Button size="sm" variant="ghost" onClick={() => setSua(false)}>Huỷ</Button>
          </>
        )}
      </div>
    </div>
  );
}

/** Một dòng mô tả: đọc, SỬA tại chỗ, XOÁ (chủ máy 30/09/2026: "có thêm có xoá, có chỉnh sửa"). */
function DongMoTa({ m, nhan, mau, xong }: { m: MoTa; nhan: string; mau: string; xong: () => Promise<void> }) {
  const [sua, setSua] = useState<string | null>(null);
  const luu = async (xoa: boolean) => {
    if (xoa && !window.confirm("Xoá dòng mô tả này? Lần vẽ sau bot không đọc nó nữa.")) return;
    if (await goiPost("/api/hoc-hoi/so-do-nha/mo-ta/sua", xoa ? { luc: m.luc, xoa: true } : { luc: m.luc, noi_dung: sua })) {
      toast.success(xoa ? "Đã xoá" : "Đã sửa — lần vẽ sau bot đọc bản mới");
      setSua(null);
      await xong();
    }
  };
  if (sua !== null) {
    return (
      <div className="space-y-1">
        <Textarea className="min-h-[60px] text-xs" value={sua} onChange={(e) => setSua(e.target.value)} />
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void luu(false)} disabled={!sua.trim()}><Check className="mr-1 h-4 w-4" />Lưu</Button>
          <Button size="sm" variant="ghost" onClick={() => setSua(null)}>Huỷ</Button>
        </div>
      </div>
    );
  }
  return (
    <p className="group whitespace-pre-wrap text-xs">
      <span className={mau}>{nhan} ({gio(m.luc)}):</span> {m.noi_dung}
      <button type="button" title="Sửa" className="ml-1 align-middle" onClick={() => setSua(m.noi_dung)}>
        <Pencil className="inline size-3 text-muted-foreground" />
      </button>
      <button type="button" title="Xoá" className="ml-1 align-middle" onClick={() => void luu(true)}>
        <Trash2 className="inline size-3 text-destructive" />
      </button>
    </p>
  );
}

export function SoDoNha() {
  const [so, setSo] = useState<SoData>({});
  const [cho, setCho] = useState<Record<string, Cho>>({});
  const [dapAn, setDapAn] = useState<Record<string, string>>({});
  const [dangChup, setDangChup] = useState(false);
  const [dangVe, setDangVe] = useState(false);
  const [ghiChu, setGhiChu] = useState("");
  const [moTaMoi, setMoTaMoi] = useState("");

  const tai = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([
        layGet<SoData>("/api/hoc-hoi/so-do-nha"),
        layGet<{ cho?: Record<string, Cho> }>("/api/hoc-hoi/so-do-nha/cho-anh"),
      ]);
      setSo(s);
      setCho(c.cho || {});
    } catch { /* mất mạng một nhịp — bấm lại */ }
  }, []);
  useEffect(() => { void tai(); }, [tai]);

  const chup = async () => {
    setDangChup(true);
    try {
      await httpRequest("/api/hoc-hoi/so-do-nha/chup-camera", { method: "POST", body: {} });
      toast.success("Đã chụp xong — kết quả gửi vào nhóm học hỏi");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Không chụp được");
    } finally {
      setDangChup(false);
      await tai();
    }
  };

  const veLai = async () => {
    setDangVe(true);
    try {
      const r = await httpRequest<{ ok?: boolean; loi?: string; id?: number }>("/api/hoc-hoi/so-do-nha/giai",
        { method: "POST", body: {} });
      if (r?.ok) toast.success(`Bot đã vẽ lại — bài #${r.id}`);
      else toast.error(r?.loi || "Bot chưa vẽ được");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Không vẽ được");
    } finally {
      setDangVe(false);
      await tai();
    }
  };

  const cham = async (id: number, dung: boolean) => {
    if (!dung && !ghiChu.trim()) {
      toast.error("Ghi vài chữ sai ở đâu để bot vẽ lại cho đúng");
      return;
    }
    if (await goiPost("/api/hoc-hoi/so-do-nha/cham", { id, dung, ghi_chu: ghiChu })) {
      toast.success(dung ? "Đã dùng sơ đồ này" : "Đã ghi — bấm «Vẽ lại» để bot vẽ theo lời chấm");
      setGhiChu("");
      await tai();
    }
  };

  const themMoTa = async () => {
    if (await goiPost("/api/hoc-hoi/so-do-nha/mo-ta", { noi_dung: moTaMoi })) {
      toast.success("Đã ghi — lần vẽ sau bot đọc cả câu này");
      setMoTaMoi("");
      await tai();
    }
  };

  const gui = async (cam: string) => {
    const r = await httpRequest<{ ok?: boolean; loi?: string }>("/api/hoc-hoi/so-do-nha/dap-an-anh", {
      method: "POST", body: { camera: cam, dap_an: dapAn[cam] || "" },
    });
    if (r?.ok) {
      toast.success(`Đã nhận đáp án ${cam} — bot đang vẽ lại sơ đồ`);
      await tai();
    } else {
      toast.error(r?.loi || "Đáp án chưa dùng được");
    }
  };

  const bai = so.bai || [];
  const moi = bai.length ? bai[bai.length - 1] : null;
  // Hiện sơ đồ ĐANG DÙNG; chưa có thì hiện bài mới nhất để chấm.
  const hien: SoDo | null = so.ap || moi?.gia_tri || null;
  const trangThai = so.ap
    ? `Đang dùng (bài #${so.ap.id})`
    : moi ? `Bài #${moi.id} — ${moi.ket_qua === "cho" ? "chờ chấm" : moi.ket_qua === "sai" ? "đã chấm SAI" : "đúng"}`
      : "";
  const chuaCham = moi && moi.ket_qua === "cho" ? moi : null;
  const luoi = so.luoi || { cot: 16, hang: 12 };
  const moTa = so.mo_ta || [];
  const camTen = Array.from(new Set([
    ...(hien?.camera || []).map((c) => c.ten),
    ...Object.keys(so.chu_khoanh || {}),
    ...moTa.filter((m) => m.nguon.startsWith("anh:")).map((m) => m.nguon.slice(4)),
  ]));
  const khoanhDs = so.chu_khoanh || {};
  const phongDs = Array.from(new Set([
    ...(hien?.phong || []).map((p) => p.ten),
    ...Object.values(khoanhDs).flatMap((k) => Object.keys(k.phong || {})),
  ]));
  const mauPhong: Record<string, string> = {};
  phongDs.forEach((p, i) => { mauPhong[p] = MAU[i % MAU.length]; });
  const loiChu = moTa.filter((m) => !m.nguon.startsWith("anh:") && !m.nguon.startsWith("khoanh:"));
  const dsCho = Object.entries(cho);

  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => void chup()} disabled={dangChup}>
          <Camera className="mr-1 h-4 w-4" />{dangChup ? "Đang chụp… (vài phút)" : "Chụp lại camera"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => void veLai()} disabled={dangVe}>
          <RefreshCw className={`mr-1 h-4 w-4 ${dangVe ? "animate-spin" : ""}`} />{dangVe ? "Đang vẽ…" : "Vẽ lại sơ đồ"}
        </Button>
      </div>

      {/* 1. Sơ đồ */}
      {!hien ? (
        <p className="text-xs text-muted-foreground">Bot chưa vẽ sơ đồ nào — bấm «Vẽ lại sơ đồ».</p>
      ) : (
        <div className="space-y-2 rounded border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">
              {TEN_KIEU[hien.kieu || ""] || hien.kieu}{hien.so_tang ? `, ${hien.so_tang} tầng` : ""}
            </span>
            <span className={`text-xs ${so.ap ? "text-emerald-600" : "text-amber-600"}`}>{trangThai}</span>
            {hien.chac != null && <span className="text-xs text-muted-foreground">bot chắc {Math.round(hien.chac * 100)}%</span>}
          </div>
          <ul className="space-y-0.5">
            {(hien.phong || []).map((p) => (
              <li key={p.ten} className="flex flex-wrap items-center gap-x-2">
                <span className="inline-block h-3 w-3 rounded-sm" style={{ background: mauPhong[p.ten] }} />
                <b>{p.ten}</b>
                {p.thong_voi?.length ? <span>— thông {p.thong_voi.join(", ")}</span> : null}
                {p.vach_voi?.length ? <span className="text-muted-foreground">— có vách với {p.vach_voi.join(", ")}</span> : null}
              </li>
            ))}
            {hien.cua_chinh?.vao ? <li>🚪 Cửa chính mở vào <b>{hien.cua_chinh.vao}</b></li> : null}
          </ul>
          {hien.vi_sao ? <p className="text-xs text-muted-foreground">Bot giải thích: {hien.vi_sao}</p> : null}
          {hien.hoi_chu_nha?.length ? (
            <div className="text-xs">
              <div className="text-muted-foreground">Bot cần anh xác nhận:</div>
              <ol className="list-decimal pl-5">{hien.hoi_chu_nha.map((q) => <li key={q}>{q}</li>)}</ol>
            </div>
          ) : null}
          {chuaCham && (
            <div className="space-y-2 border-t pt-2">
              <Textarea className="min-h-[60px] text-xs" value={ghiChu} onChange={(e) => setGhiChu(e.target.value)}
                placeholder="Sai ở đâu? Vd: «Cam bếp: ô E4, F4 là phòng khách», «bếp có cửa ra ban công»" />
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => void cham(chuaCham.id, true)}>
                  <Check className="mr-1 h-4 w-4" />Đúng — dùng sơ đồ này
                </Button>
                <Button size="sm" variant="outline" onClick={() => void cham(chuaCham.id, false)}>
                  <X className="mr-1 h-4 w-4" />Sai
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 2. Từng camera: ảnh + ô theo phòng + lời tả */}
      {camTen.map((cam) => {
        const kh = khoanhDs[cam];
        const thay = (kh?.phong && Object.keys(kh.phong).length ? kh.phong : null)
          || hien?.camera?.find((c) => c.ten === cam)?.thay || {};
        const doc = [...moTa].reverse().find((m) => m.nguon === `anh:${cam}`);
        const khoanh = moTa.filter((m) => !m.nguon.startsWith("anh:") && !m.nguon.startsWith("khoanh:")
          && m.noi_dung.includes(cam));
        return (
          <div key={cam} className="space-y-2 rounded border p-3">
            <div className="font-medium">📷 {cam}
              <span className={`ml-2 text-xs ${kh ? "text-sky-600" : "text-muted-foreground"}`}>
                {kh ? "vùng anh khoanh" : "bot tự đọc"}
              </span>
            </div>
            <AnhCamera cam={cam} thay={thay} doDac={kh?.do || []} mauPhong={mauPhong} luoi={luoi} phongDs={phongDs}
              daKhoanh={!!kh} xong={tai} />
            <div className="text-xs">
              {Object.keys(thay).length ? (
                Object.entries(thay).map(([p, o]) => (
                  <div key={p}>
                    <span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: mauPhong[p] || "#888" }} />
                    <b>{p}</b>: {o.length} ô
                  </div>
                ))
              ) : <div className="text-muted-foreground">Sơ đồ: camera này không thấy phòng nào trong nhà.</div>}
            </div>
            {doc && <DongMoTa m={doc} nhan="Bot tả ảnh" mau="text-muted-foreground" xong={tai} />}
            {khoanh.map((m) => <DongMoTa key={m.luc} m={m} nhan="Chủ nhà" mau="text-sky-600" xong={tai} />)}
          </div>
        );
      })}

      {/* 3. Lời chủ nhà tả nhà */}
      <div className="space-y-2 rounded border p-3">
        <div className="font-medium">Lời chủ nhà mô tả ({loiChu.length})</div>
        <ul className="max-h-64 space-y-1 overflow-y-auto text-xs">
          {loiChu.map((m) => (
            <li key={m.luc}><DongMoTa m={m} nhan={m.nguon === "chat" ? "Qua chat" : "Chủ nhà"} mau="text-muted-foreground" xong={tai} /></li>
          ))}
        </ul>
        <Textarea className="min-h-[60px] text-xs" value={moTaMoi} onChange={(e) => setMoTaMoi(e.target.value)}
          placeholder="Tả thêm, vd «phòng học có cửa ra phòng khách, không thông»" />
        <Button size="sm" variant="outline" onClick={() => void themMoTa()} disabled={!moTaMoi.trim()}>
          <Send className="mr-1 h-4 w-4" />Ghi mô tả
        </Button>
      </div>

      {/* 4. Ảnh chờ đáp án (nhà không có model đọc ảnh) */}
      {dsCho.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Ảnh chờ anh đọc hộ: chép LỆNH, gửi kèm ẢNH vào ChatGPT / Gemini / Claude của anh, thấy chia ô đúng thì
            dán nguyên phần JSON {"{…}"} app trả vào ô rồi gửi. Có thể nhắn bot «đáp án ảnh &lt;camera&gt;: {"{…}"}».
          </p>
          {dsCho.map(([cam, x]) => (
            <div key={cam} className="space-y-2 rounded border p-2">
              <div className="font-medium">{cam}{x.dem ? " — ảnh đêm, đen trắng" : ""}</div>
              {x.anh_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <a href={x.anh_url} target="_blank" rel="noreferrer"><img src={x.anh_url} alt={cam} className="max-h-72 rounded" /></a>
              )}
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline"
                  onClick={() => { void navigator.clipboard.writeText(x.lenh); toast.success("Đã chép lệnh"); }}>
                  <Copy className="mr-1 h-4 w-4" />Chép lệnh
                </Button>
                <span className="text-xs text-muted-foreground">{x.lenh.length} ký tự</span>
              </div>
              <Textarea className="min-h-[80px] font-mono text-xs" placeholder='Dán đáp án: {"thay": {"Bếp": ["C4", …]}, …}'
                value={dapAn[cam] || ""} onChange={(e) => setDapAn({ ...dapAn, [cam]: e.target.value })} />
              <Button size="sm" onClick={() => void gui(cam)} disabled={!(dapAn[cam] || "").trim()}>
                <Send className="mr-1 h-4 w-4" />Gửi đáp án cho bot
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
