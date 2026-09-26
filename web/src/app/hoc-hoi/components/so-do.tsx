"use client";

/**
 * Sơ đồ kích hoạt — từng thiết bị: ĐIỀU KIỆN (khi nào bật) và NGOẠI VI (cảm biến liên quan),
 * tách riêng, thêm / bỏ / lấy lại được. TÍCH một thiết bị = giao cho bot tự điều khiển nó
 * (chủ máy 26/09/2026); chi tiết bật/tắt nằm ở thẻ "Bật/tắt thiết bị".
 *
 * Backend: api/hoc_hoi.py (/api/hoc-hoi/so-do, /so-do/sua, /thuc-the, /kich-hoat/dat)
 * → services/hieu_thiet_bi_nha.py (sua_so_do) + services/kich_hoat_nha.py.
 */

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, Plus, RefreshCw, RotateCcw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { goiPost, layGet } from "./lib";

type Do = { nhan_hay_gap: string; ty_le: number; mau: number } | null;
type Muc = { khoa: string; ten: string; do: Do; cua_chu_may?: boolean; goc?: Record<string, unknown> };
type Nut = {
  khoa: string;
  nhan_to_chinh: string;
  ngoai_vi: Muc[];
  dieu_kien: Muc[];
  da_bo?: { dk: string[]; nv: { khoa: string; ten: string }[] };
  bot_dieu_khien?: boolean;
  goi_y_them?: { ma: string; ten: string; so_lan: number; ty_le?: number }[];
};
type ThucThe = { ma: string; ten: string; lop: string };
/** {mã thiết bị: {khoá điều kiện: số đo}} — về SAU sơ đồ, xem `/so-do/do`. */
type BangDo = Record<string, Record<string, Exclude<Do, null>>>;

/** Khoá điều kiện đã bỏ ("gio:15:00-24:00", "ngay:thuong", mã thực thể) → điều kiện để lấy lại. */
function mucTuKhoa(k: string): Record<string, unknown> {
  const gio = /^gio:(\d\d:\d\d)-(\d\d:\d\d)$/.exec(k);
  if (gio) return { ma: "gio", tu: gio[1], den: gio[2] };
  const nm = /^(ngay|mua):(.*)$/.exec(k);
  if (nm) return { ma: nm[1], la: nm[2] };
  return { ma: k };
}

function Chip({ m, khoaNut, bangDo, dangDo, onBo }: {
  m: Muc; khoaNut: string; bangDo: BangDo; dangDo: boolean; onBo: () => void;
}) {
  const so = m.khoa ? bangDo[khoaNut]?.[m.khoa] : undefined;
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] ${
      m.cua_chu_may ? "border-primary/50 bg-primary/5" : "border-border bg-muted/50"}`} title={m.khoa}>
      {m.ten}
      {m.cua_chu_may ? <span className="text-primary">· anh thêm</span> : null}
      {so && so.mau > 0 ? (
        <span className="text-muted-foreground">
          — {so.nhan_hay_gap ? `${so.nhan_hay_gap} ` : ""}{Math.round(so.ty_le * 100)}% ({so.mau} lần bật)
        </span>
      ) : dangDo ? (
        <span className="text-muted-foreground">— đang đo…</span>
      ) : null}
      <button type="button" title="Bỏ" onClick={onBo}><X className="size-3 text-destructive" /></button>
    </span>
  );
}

function ThemDieuKien({ onThem }: { onThem: (muc: Record<string, unknown>) => void }) {
  const [loai, setLoai] = useState<"gio" | "cam_bien">("gio");
  const [tu, setTu] = useState("18:00");
  const [den, setDen] = useState("22:00");
  const [ma, setMa] = useState("");
  const [kieu, setKieu] = useState<"on" | "off" | "duoi" | "tren">("on");
  const [so, setSo] = useState("50");
  const them = () => {
    if (loai === "gio") onThem({ ma: "gio", tu, den });
    else if (ma.trim()) {
      onThem(kieu === "on" || kieu === "off" ? { ma: ma.trim(), la: kieu } : { ma: ma.trim(), [kieu]: Number(so) });
      setMa("");
    }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <select className="rounded border bg-background px-1 py-0.5" value={loai}
        onChange={(e) => setLoai(e.target.value as "gio" | "cam_bien")}>
        <option value="gio">khung giờ</option>
        <option value="cam_bien">cảm biến</option>
      </select>
      {loai === "gio" ? (
        <>
          <Input type="time" className="h-7 w-24" value={tu} onChange={(e) => setTu(e.target.value)} />–
          <Input type="time" className="h-7 w-24" value={den} onChange={(e) => setDen(e.target.value)} />
        </>
      ) : (
        <>
          <Input className="h-7 w-56" list="hoc-hoi-thuc-the" placeholder="mã hoặc tên cảm biến" value={ma}
            onChange={(e) => setMa(e.target.value)} />
          <select className="rounded border bg-background px-1 py-0.5" value={kieu}
            onChange={(e) => setKieu(e.target.value as typeof kieu)}>
            <option value="on">là bật / có người</option>
            <option value="off">là tắt / vắng</option>
            <option value="duoi">dưới</option>
            <option value="tren">trên</option>
          </select>
          {kieu === "duoi" || kieu === "tren" ? (
            <Input type="number" className="h-7 w-20" value={so} onChange={(e) => setSo(e.target.value)} />
          ) : null}
        </>
      )}
      <Button variant="outline" size="sm" className="h-7" onClick={them}><Plus className="size-3.5" /></Button>
    </span>
  );
}

function ThemNgoaiVi({ onThem }: { onThem: (ma: string) => void }) {
  const [ma, setMa] = useState("");
  return (
    <span className="inline-flex items-center gap-1">
      <Input className="h-7 w-56" list="hoc-hoi-thuc-the" placeholder="thêm cảm biến / thiết bị" value={ma}
        onChange={(e) => setMa(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && ma.trim()) { onThem(ma.trim()); setMa(""); } }} />
      <Button variant="outline" size="sm" className="h-7" disabled={!ma.trim()}
        onClick={() => { onThem(ma.trim()); setMa(""); }}><Plus className="size-3.5" /></Button>
    </span>
  );
}

export function SoDo() {
  const [ds, setDs] = useState<Nut[]>([]);
  const [bangDo, setBangDo] = useState<BangDo>({});
  const [thucThe, setThucThe] = useState<ThucThe[]>([]);
  const [dangTai, setDangTai] = useState(false);
  const [dangDo, setDangDo] = useState(false);

  const taiSoDo = useCallback(async () => {
    const r = await layGet<{ danh_sach?: Nut[] }>("/api/hoc-hoi/so-do");
    setDs(r.danh_sach || []);
  }, []);

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      await taiSoDo();
    } finally {
      setDangTai(false);
    }
    // Đo TÁCH RIÊNG sau khi sơ đồ đã hiện: phần đo phải dựng lại bối cảnh
    // từng ô 30 phút nên tốn vài giây. Gộp chung một lượt thì cả sơ đồ mất 47
    // giây và trình duyệt bỏ cuộc trước (đo thật 12/09/2026).
    setDangDo(true);
    try {
      const d = await layGet<{ do?: BangDo }>("/api/hoc-hoi/so-do/do");
      setBangDo(d.do || {});
    } finally {
      setDangDo(false);
    }
  }, [taiSoDo]);

  useEffect(() => {
    void tai();
    void layGet<{ danh_sach?: ThucThe[] }>("/api/hoc-hoi/thuc-the").then((r) => setThucThe(r.danh_sach || []));
  }, [tai]);

  /** Chủ máy gõ tên hoặc mã — đổi ra mã thực thể. */
  const doiMa = (chu: string) => thucThe.find((t) => t.ma === chu || t.ten === chu)?.ma ?? chu;
  const tenCua = (ma: string) => thucThe.find((t) => t.ma === ma)?.ten ?? "";

  const sua = async (khoa: string, loai: "dk" | "nv", hanh_dong: "them" | "bo" | "bo_lai",
                     muc: Record<string, unknown>) => {
    if (await goiPost("/api/hoc-hoi/so-do/sua", { khoa, loai, hanh_dong, muc })) await taiSoDo();
  };

  const tich = async (n: Nut, bat: boolean) => {
    if (await goiPost("/api/hoc-hoi/kich-hoat/dat", { thiet_bi: n.khoa, bat, tu_lam: bat })) {
      if (bat) await goiPost("/api/hoc-hoi/kich-hoat/hoc", { thiet_bi: n.khoa });
      await taiSoDo();
    }
  };

  return (
    <div className="space-y-3">
      <datalist id="hoc-hoi-thuc-the">
        {thucThe.map((t) => <option key={t.ma} value={t.ma}>{t.ten}</option>)}
      </datalist>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Mỗi thiết bị: <b>điều kiện</b> (khi nào bật) và <b>ngoại vi</b> (cảm biến liên quan) — bot đọc từ
          thói quen, anh <b>thêm / bỏ</b> được, điều anh sửa luôn thắng. <b>Tích</b> một thiết bị là giao cho
          bot tự điều khiển nó theo sơ đồ này (chi tiết ở thẻ «Bật/tắt thiết bị»). Số % là đo THẬT từ lịch
          sử: trong các lần có người bật, mấy lần khớp điều kiện.
        </p>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      {dangTai && !ds.length ? (
        <div className="flex items-center gap-2 p-2 text-xs text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" /> Đang tải…
        </div>
      ) : (
        <div className="space-y-2">
          {ds.map((n) => (
            <div key={n.khoa} className="space-y-1.5 rounded border border-border p-2 text-xs">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={!!n.bot_dieu_khien} onChange={(e) => void tich(n, e.target.checked)} />
                <span className="rounded bg-primary/10 px-2 py-0.5 font-medium text-primary">{n.nhan_to_chinh}</span>
                <span className="text-muted-foreground">{n.bot_dieu_khien ? "bot tự điều khiển" : ""}</span>
              </label>
              <div className="flex flex-wrap items-center gap-1">
                <span className="w-16 shrink-0 text-muted-foreground">Điều kiện:</span>
                {n.dieu_kien.map((d) => (
                  <Chip key={d.khoa} m={d} khoaNut={n.khoa} bangDo={bangDo} dangDo={dangDo}
                    onBo={() => void sua(n.khoa, "dk", "bo", d.goc || mucTuKhoa(d.khoa))} />
                ))}
                {!n.dieu_kien.length ? <span className="text-muted-foreground">chưa có — bot im với thiết bị này</span> : null}
                <ThemDieuKien onThem={(muc) => void sua(n.khoa, "dk", "them",
                  typeof muc.ma === "string" && muc.ma !== "gio" ? { ...muc, ma: doiMa(muc.ma) } : muc)} />
              </div>
              <div className="flex flex-wrap items-center gap-1">
                <span className="w-16 shrink-0 text-muted-foreground">Ngoại vi:</span>
                {n.ngoai_vi.map((v) => (
                  <Chip key={v.khoa} m={v} khoaNut={n.khoa} bangDo={bangDo} dangDo={false}
                    onBo={() => void sua(n.khoa, "nv", "bo", { ma: v.khoa })} />
                ))}
                <ThemNgoaiVi onThem={(chu) => { const ma = doiMa(chu); void sua(n.khoa, "nv", "them", { ma, ten: tenCua(ma) }); }} />
              </div>
              {(n.goi_y_them?.length ?? 0) > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                  <span className="w-16 shrink-0 text-muted-foreground">Gợi ý:</span>
                  {n.goi_y_them!.map((g) => (
                    <button key={g.ma} type="button" title="Báo có người vào rồi anh hay bật thiết bị này — thêm vào ngoại vi"
                      className="inline-flex items-center gap-1 rounded border border-dashed px-1.5 py-0.5 text-[11px]"
                      onClick={() => void sua(n.khoa, "nv", "them", { ma: g.ma, ten: g.ten })}>
                      <Plus className="size-3" /> {g.ten} (báo rồi anh bật {g.so_lan} lần{g.ty_le != null ? ` — ${Math.round(g.ty_le * 100)}%` : ""})
                    </button>
                  ))}
                </div>
              )}
              {((n.da_bo?.dk.length ?? 0) + (n.da_bo?.nv.length ?? 0)) > 0 && (
                <div className="flex flex-wrap items-center gap-1 text-muted-foreground">
                  <span className="w-16 shrink-0">Đã bỏ:</span>
                  {n.da_bo!.dk.map((k) => (
                    <span key={k} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px]">
                      {k.startsWith("gio:") ? `trong ${k.slice(4).replace("-", "–")}` : tenCua(k) || k}
                      <button type="button" title="Lấy lại" onClick={() => void sua(n.khoa, "dk", "bo_lai", mucTuKhoa(k))}>
                        <RotateCcw className="size-3" />
                      </button>
                    </span>
                  ))}
                  {n.da_bo!.nv.map((v) => (
                    <span key={v.khoa} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px]">
                      {v.ten}
                      <button type="button" title="Lấy lại" onClick={() => void sua(n.khoa, "nv", "bo_lai", { ma: v.khoa })}>
                        <RotateCcw className="size-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {!ds.length ? (
            <p className="px-2 py-3 text-center text-muted-foreground">Chưa có thiết bị nào được học.</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
