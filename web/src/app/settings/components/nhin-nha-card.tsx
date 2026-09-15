"use client";

/**
 * NhinNhaCard — «mắt của nhà»: YOLO26 nhận vật thể + nhận khuôn mặt kiểu IRIS,
 * chạy ngay trên máy, không cần Frigate.
 *
 * Cấu hình nằm ở `nhin_nha` trong config nên lưu bằng saveConfig như mọi thẻ
 * khác (thẻ này là chủ DUY NHẤT của khoá đó). Sổ khuôn mặt (người, mặt lạ, sự
 * kiện) đi qua /api/nhin-nha/* — ảnh mặt trả về dạng data URL thu nhỏ, không có
 * đường tĩnh công khai nào cho kho mặt.
 *
 * Báo tin (người lạ / người quen về / hỏi tên) KHÔNG bật ở đây: như mọi thông
 * báo khác, bật và chọn kênh ở Cài đặt → Thông báo.
 */

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

type Canh = {
  bat?: boolean; frigate?: boolean; yolo_quet?: boolean; chu_ky_giay?: number;
  cach_giay?: number; phien_phut?: number; camera?: string[]; camera_ve?: string[];
  hoi_ten_sau?: number;
};
type NhinNha = {
  yolo?: { model?: string; nguong?: number; luong?: number };
  khuon_mat?: { bo?: string; nguong_co_the?: number; nguong_chac?: number; luong?: number };
  canh?: Canh;
};
type ModelTT = { ma: string; mb: number; mo_ta: string; da_tai: boolean };
type TrangThai = {
  model: {
    yolo: { model: string; da_tai: boolean; cac_model: ModelTT[] };
    khuon_mat: { bo: string; da_tai: boolean; cac_bo: ModelTT[] };
    lenh_tai: string;
  };
  canh: { dang_chay: boolean; quet: number; co_nguoi: number; nhan_mat: number;
          su_kien: number; frigate: number; loi: number; loi_cuoi: string };
};
type Nguoi = { id: string; ten: string; so_mat: number; anh: string; lan_cuoi: number | null; so_lan: number };
type MatLa = { id: string; anh: string; so_lan: number; lan_cuoi: number; camera: string; da_hoi: number };
type SuKien = { id: number; ts: number; camera: string; nguon: string; loai: string;
                ten: string | null; mat_la_id: string | null; do_giong: number };

const luc = (ts: number | null) =>
  ts ? new Date(ts * 1000).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit",
                                                     day: "2-digit", month: "2-digit" }) : "—";
const loiCua = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function NhinNhaCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);

  const [nn, setNn] = useState<NhinNha>({});
  const [tt, setTt] = useState<TrangThai | null>(null);
  const [nguoi, setNguoi] = useState<Nguoi[]>([]);
  const [matLa, setMatLa] = useState<MatLa[]>([]);
  const [suKien, setSuKien] = useState<SuKien[]>([]);
  const [msg, setMsg] = useState("");
  const [saved, setSaved] = useState(false);
  const [tenDay, setTenDay] = useState("");
  const [tepDay, setTepDay] = useState<File | null>(null);
  const [canEp, setCanEp] = useState(false);
  const [tenLa, setTenLa] = useState<Record<string, string>>({});
  const [suaTen, setSuaTen] = useState<Record<string, string>>({});

  const cams = Object.keys(((config as any)?.cameras as Record<string, unknown>) || {});

  useEffect(() => {
    setNn(((config as any)?.nhin_nha as NhinNha) || {});
  }, [(config as any)?.nhin_nha]);

  const tai = useCallback(async () => {
    try {
      const [a, b, c, d] = await Promise.all([
        request.get("/api/nhin-nha/trang-thai"), request.get("/api/nhin-nha/nguoi"),
        request.get("/api/nhin-nha/mat-la"), request.get("/api/nhin-nha/su-kien?so_gio=24"),
      ]);
      setTt(a.data as TrangThai);
      setNguoi(((b.data as any)?.nguoi as Nguoi[]) || []);
      setMatLa(((c.data as any)?.mat_la as MatLa[]) || []);
      setSuKien(((d.data as any)?.su_kien as SuKien[]) || []);
    } catch (e) {
      setMsg(`❌ ${loiCua(e)}`);
    }
  }, []);

  useEffect(() => { void tai(); }, [tai]);

  const canh: Canh = nn.canh || {};
  const datCanh = (p: Partial<Canh>) => setNn({ ...nn, canh: { ...canh, ...p } });
  const batTat = (ds: string[] | undefined, t: string) =>
    (ds || []).includes(t) ? (ds || []).filter((x) => x !== t) : [...(ds || []), t];

  const luu = async () => {
    await saveConfig({ ...config, nhin_nha: nn } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
    void tai();
  };

  const day = async (ep: boolean) => {
    if (!tenDay.trim() || !tepDay) { setMsg("❌ Cần cả tên và ảnh."); return; }
    setMsg("Đang dạy mặt…");
    const fd = new FormData();
    fd.append("ten", tenDay.trim());
    fd.append("anh", tepDay);
    fd.append("ep", ep ? "true" : "false");
    try {
      const d = (await request.post("/api/nhin-nha/day", fd)).data as any;
      if (d.ok) {
        setMsg(`✅ Đã nhớ mặt «${d.ten}» (${d.so_mat} ảnh mặt).`);
        setTenDay(""); setTepDay(null); setCanEp(false);
        void tai();
      } else {
        setMsg(`❌ ${d.error}`);
        setCanEp(String(d.error || "").includes("chắc chắn"));
      }
    } catch (e) { setMsg(`❌ ${loiCua(e)}`); }
  };

  const goi = async (fn: () => Promise<{ data: any }>, xong: string) => {
    try {
      const d = (await fn()).data;
      setMsg(d.ok ? `✅ ${xong}` : `❌ ${d.error || "Không làm được"}`);
      void tai();
    } catch (e) { setMsg(`❌ ${loiCua(e)}`); }
  };

  const oTich = (nhan: string, co: boolean, doi: (v: boolean) => void) => (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={co} onChange={(e) => doi(e.target.checked)} />
      {nhan}
    </label>
  );
  const oSo = (nhan: string, gt: number | undefined, macDinh: number, doi: (v: number) => void) => (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      {nhan}
      <Input className="w-20" type="number" value={gt ?? macDinh}
        onChange={(e) => doi(Number(e.target.value))} />
    </label>
  );

  const m = tt?.model;
  const chuaTai = m && (!m.yolo.da_tai || !m.khuon_mat.da_tai);

  return (
    <Card>
      <CardHeader>
        <CardTitle>🧑 Khuôn mặt &amp; vật thể (YOLO26 + InsightFace)</CardTitle>
        <CardDescription>
          Chạy ngay trên máy, không gửi ảnh đi đâu, không cần Frigate. Hỏi «bếp có mấy người»,
          «ai đang ở cửa»; gửi ảnh vào chat rồi chọn «Dạy khuôn mặt» hoặc «Đây là ai?».
          Cần tích 📷 Camera nhà cho hội thoại ở Kênh chat → Lọc thread.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">

        {/* ── Model ───────────────────────────────────────────────────── */}
        <div className="space-y-2">
          <p className="text-sm font-medium">Model</p>
          {chuaTai ? (
            <p className="text-xs text-amber-600">
              ⚠️ Chưa tải đủ model. Chạy trên máy chủ:{" "}
              <code className="break-all">{m!.lenh_tai} --yolo {nn.yolo?.model || m!.yolo.model} --mat {nn.khuon_mat?.bo || m!.khuon_mat.bo}</code>
            </p>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <label className="text-xs text-muted-foreground">Nhận vật thể{" "}
              <select className="h-9 rounded border border-input bg-background px-2 text-sm"
                value={nn.yolo?.model || m?.yolo.model || "yolo26n"}
                onChange={(e) => setNn({ ...nn, yolo: { ...nn.yolo, model: e.target.value } })}>
                {(m?.yolo.cac_model || []).map((x) => (
                  <option key={x.ma} value={x.ma}>{x.ma} · {x.mb} MB{x.da_tai ? " ✓" : " (chưa tải)"}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-muted-foreground">Nhận mặt{" "}
              <select className="h-9 rounded border border-input bg-background px-2 text-sm"
                value={nn.khuon_mat?.bo || m?.khuon_mat.bo || "buffalo_s"}
                onChange={(e) => setNn({ ...nn, khuon_mat: { ...nn.khuon_mat, bo: e.target.value } })}>
                {(m?.khuon_mat.cac_bo || []).map((x) => (
                  <option key={x.ma} value={x.ma}>{x.ma}{x.da_tai ? " ✓" : " (chưa tải)"}</option>
                ))}
              </select>
            </label>
            {oSo("Ngưỡng vật thể", nn.yolo?.nguong, 0.35,
                 (v) => setNn({ ...nn, yolo: { ...nn.yolo, nguong: v } }))}
            {oSo("«Có thể là» từ", nn.khuon_mat?.nguong_co_the, 40,
                 (v) => setNn({ ...nn, khuon_mat: { ...nn.khuon_mat, nguong_co_the: v } }))}
            {oSo("Nhận chắc từ", nn.khuon_mat?.nguong_chac, 55,
                 (v) => setNn({ ...nn, khuon_mat: { ...nn.khuon_mat, nguong_chac: v } }))}
          </div>
          <p className="text-xs text-muted-foreground">
            Đổi bộ nhận mặt thì em tự tính lại mặt của mọi người từ ảnh đã lưu, không phải dạy lại.
          </p>
        </div>

        {/* ── Canh camera ─────────────────────────────────────────────── */}
        <div className="rounded border border-border/70 p-3 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            {oTich("Tự canh camera (ghi ai tới, lúc nào)", !!canh.bat, (v) => datCanh({ bat: v }))}
            {tt ? (
              <span className="text-xs text-muted-foreground">
                {tt.canh.dang_chay ? "luồng nền đang chạy" : "luồng nền chưa chạy"} · quét {tt.canh.quet} ·
                thấy người {tt.canh.co_nguoi} · Frigate {tt.canh.frigate} · nhận mặt {tt.canh.nhan_mat} ·
                ghi {tt.canh.su_kien} lượt{tt.canh.loi ? ` · lỗi ${tt.canh.loi}: ${tt.canh.loi_cuoi}` : ""}
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-4">
            {oTich("Nguồn: sự kiện person của Frigate", canh.frigate !== false, (v) => datCanh({ frigate: v }))}
            {oTich("Nguồn: YOLO tự quét luồng phụ", canh.yolo_quet !== false, (v) => datCanh({ yolo_quet: v }))}
          </div>
          <div className="flex flex-wrap gap-3">
            {oSo("Nghỉ giữa hai vòng quét (giây)", canh.chu_ky_giay, 2, (v) => datCanh({ chu_ky_giay: v }))}
            {oSo("Cùng người trong (phút) là một lượt", canh.phien_phut, 10, (v) => datCanh({ phien_phut: v }))}
            {oSo("Hỏi tên mặt lạ sau (lượt)", canh.hoi_ten_sau, 3, (v) => datCanh({ hoi_ten_sau: v }))}
          </div>
          <div className="text-xs text-muted-foreground space-y-1">
            <p>Camera được canh (không tích cái nào = tất cả):</p>
            <div className="flex flex-wrap gap-3">
              {cams.map((t) => (
                <span key={t}>{oTich(t, (canh.camera || []).includes(t),
                                     () => datCanh({ camera: batTat(canh.camera, t) }))}</span>
              ))}
            </div>
            <p>Camera tính là «về nhà» (báo «người quen về»):</p>
            <div className="flex flex-wrap gap-3">
              {cams.map((t) => (
                <span key={t}>{oTich(t, (canh.camera_ve || []).includes(t),
                                     () => datCanh({ camera_ve: batTat(canh.camera_ve, t) }))}</span>
              ))}
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Báo tin người lạ / người quen về / hỏi tên mặt lạ: bật và chọn kênh ở{" "}
            <b>Cài đặt → Thông báo</b> (nhóm «Nhà»). Mặc định tắt cả ba.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={luu}>{saved ? "Đã lưu!" : "Lưu cài đặt"}</Button>
          {msg ? <span className="text-xs text-muted-foreground">{msg}</span> : null}
        </div>

        {/* ── Người đã dạy ────────────────────────────────────────────── */}
        <div className="space-y-2">
          <p className="text-sm font-medium">Người đã dạy mặt ({nguoi.length})</p>
          <div className="flex flex-wrap gap-2">
            {nguoi.map((n) => (
              <div key={n.id} className="w-44 rounded border border-border/70 p-2 space-y-1">
                {n.anh ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={n.anh} alt={n.ten} className="h-24 w-full rounded object-cover" />
                ) : null}
                <Input value={suaTen[n.id] ?? n.ten}
                  onChange={(e) => setSuaTen({ ...suaTen, [n.id]: e.target.value })} />
                <p className="text-[11px] text-muted-foreground">
                  {n.so_mat} ảnh mặt · gặp {n.so_lan} lượt · {luc(n.lan_cuoi)}
                </p>
                <div className="flex gap-1">
                  {suaTen[n.id] !== undefined && suaTen[n.id] !== n.ten ? (
                    <Button size="sm" variant="outline" onClick={() => goi(
                      () => request.post(`/api/nhin-nha/nguoi/${n.id}/doi-ten`, { ten: suaTen[n.id] }),
                      "Đã đổi tên.")}>Lưu tên</Button>
                  ) : null}
                  <Button size="sm" variant="outline" onClick={() => {
                    if (window.confirm(`Xoá mặt của «${n.ten}» và mọi ảnh mặt đã lưu?`)) {
                      void goi(() => request.delete(`/api/nhin-nha/nguoi/${n.id}`), "Đã xoá.");
                    }
                  }}>Xoá</Button>
                </div>
              </div>
            ))}
          </div>
          <div className="rounded border border-dashed border-border/70 p-3 space-y-2">
            <p className="text-sm font-medium">Dạy mặt mới</p>
            <div className="flex flex-wrap items-center gap-2">
              <Input className="w-48" value={tenDay} onChange={(e) => setTenDay(e.target.value)}
                placeholder="Tên, vd: Bà ngoại" />
              <input type="file" accept="image/*" className="text-xs"
                onChange={(e) => setTepDay(e.target.files?.[0] || null)} />
              <Button size="sm" onClick={() => day(false)}>Dạy</Button>
              {canEp ? (
                <Button size="sm" variant="outline" onClick={() => day(true)}>Đúng là người này</Button>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">
              Ảnh chỉ có mặt người đó (hoặc mặt đó to rõ nhất). Dạy 3–4 ảnh khác góc, khác ánh sáng
              để nhận chắc hơn.
            </p>
          </div>
        </div>

        {/* ── Mặt lạ ──────────────────────────────────────────────────── */}
        <div className="space-y-2">
          <p className="text-sm font-medium">Mặt lạ camera gặp ({matLa.length})</p>
          {matLa.length === 0 ? (
            <p className="text-xs text-muted-foreground">Chưa có — bật «Tự canh camera» thì em mới gom.</p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {matLa.map((x) => (
              <div key={x.id} className="w-44 rounded border border-border/70 p-2 space-y-1">
                {x.anh ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={x.anh} alt={`mặt lạ ${x.id}`} className="h-24 w-full rounded object-cover" />
                ) : null}
                <p className="text-[11px] text-muted-foreground">
                  «{x.id}» · {x.so_lan} lượt · {x.camera} · {luc(x.lan_cuoi)}
                </p>
                <Input value={tenLa[x.id] || ""} placeholder="Đây là ai?"
                  onChange={(e) => setTenLa({ ...tenLa, [x.id]: e.target.value })} />
                <div className="flex gap-1">
                  <Button size="sm" variant="outline" disabled={!(tenLa[x.id] || "").trim()}
                    onClick={() => goi(() => request.post(`/api/nhin-nha/mat-la/${x.id}/dat-ten`,
                                                          { ten: tenLa[x.id] }), "Đã nhớ tên.")}>
                    Đặt tên
                  </Button>
                  <Button size="sm" variant="outline"
                    onClick={() => goi(() => request.post(`/api/nhin-nha/mat-la/${x.id}/thoi-hoi`),
                                       "Sẽ không hỏi về mặt này nữa.")}>
                    Đừng hỏi
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Sự kiện ─────────────────────────────────────────────────── */}
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium">24 giờ qua ({suKien.length} lượt)</p>
            <Button size="sm" variant="outline" onClick={() => void tai()}>Làm mới</Button>
          </div>
          <div className="overflow-x-auto">
            <table className="text-xs">
              <tbody>
                {suKien.map((s) => (
                  <tr key={s.id} className="border-b border-border/40">
                    <td className="pr-3 py-1 whitespace-nowrap">{luc(s.ts)}</td>
                    <td className="pr-3">{s.camera}</td>
                    <td className="pr-3">
                      {s.loai === "quen" ? s.ten
                        : s.loai === "co_the" ? `có thể là ${s.ten} (${Math.round(s.do_giong)}/100)`
                        : `người lạ «${s.mat_la_id}»`}
                    </td>
                    <td className="text-muted-foreground">{s.nguon}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
