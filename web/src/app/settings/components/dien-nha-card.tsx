"use client";

/**
 * Thẻ "Điện nhà" — địa chỉ NUT (Network UPS Tools) để c2a đọc UPS 5 giây một lần và báo mất điện / có điện /
 * pin yếu sắp tắt máy chủ (services/dien_nha.py). Chủ máy 05/10/2026: "thêm hướng dẫn … cài nut để kết nối
 * với c2a". Cùng lối với mang-nha-card.tsx: thử địa chỉ VỪA NHẬP trước khi lưu.
 */

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";
import { HuongDan, PHAN_DIEN } from "./huong-dan-dien-mang";

type KetQua = { ok?: boolean; tom_tat?: string; error?: string };
type TrangThai = {
  ok?: boolean; error?: string; ups?: Record<string, string>;
  pin_tu?: number | null; cho_gui?: number; mat_doc_tu?: number | null;
  luc?: number;   // giây, lúc trình duyệt nhận số đọc — tính «chạy pin bao lâu»
};

const gio = (ts: number) => new Date(ts * 1000).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
const so = (v?: string) => (v === undefined || v === "" || Number.isNaN(Number(v)) ? null : Number(v));

/** Thanh ngang 0–100% có vạch ngưỡng (vd ngưỡng tắt máy chủ). */
function Thanh({ phanTram, mau, vach }: { phanTram: number; mau: string; vach?: number | null }) {
  const p = Math.max(0, Math.min(100, phanTram));
  return (
    <div className="relative h-3 w-full overflow-hidden rounded-full bg-muted">
      <div className={`h-full rounded-full transition-all ${mau}`} style={{ width: `${p}%` }} />
      {vach != null ? (
        <div className="absolute inset-y-0 w-0.5 bg-rose-600" style={{ left: `${vach}%` }} title={`Ngưỡng ${vach}%`} />
      ) : null}
    </div>
  );
}

/**
 * Bảng UPS trực quan — chủ máy 05/10/2026: "không hiển thị thông tin ups trực quan được à". Hỏi
 * GET /api/dien-nha/trang-thai 5 giây một lần khi đang mở tab (cùng nhịp c2a đọc UPS).
 */
function TrangThaiUps() {
  const [t, setT] = useState<TrangThai | null>(null);
  useEffect(() => {
    let song = true;
    const lay = async () => {
      try {
        const r = (await request.get("/api/dien-nha/trang-thai")).data as TrangThai;
        if (song) setT({ ...r, luc: Date.now() / 1000 });
      } catch (e: any) {
        if (song) setT({ ok: false, error: e?.message || "Không gọi được máy chủ" });
      }
    };
    void lay();
    const id = window.setInterval(() => void lay(), 5000);
    return () => { song = false; window.clearInterval(id); };
  }, []);

  if (!t) return <p className="text-xs text-muted-foreground">Đang đọc UPS…</p>;
  if (!t.ok) {
    return (
      <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm">
        ⚠️ {t.error}{t.mat_doc_tu ? ` — mất đọc từ ${gio(t.mat_doc_tu)}` : ""}
      </div>
    );
  }
  const u = t.ups || {};
  const co = (u["ups.status"] || "").split(" ");
  const pin = so(u["battery.charge"]);
  const nguong = so(u["battery.charge.low"]);
  const tai = so(u["ups.load"]);
  const yeu = co.includes("FSD") || (co.includes("OB") && co.includes("LB"));
  const [nhan, khung, mauPin] = yeu
    ? ["🔴 Pin yếu — máy chủ đang tắt", "border-rose-500/50 bg-rose-500/10", "bg-rose-500"]
    : co.includes("OB")
      ? ["🟠 Mất điện — đang chạy pin", "border-amber-500/50 bg-amber-500/10", "bg-amber-500"]
      : co.includes("OL")
        ? ["🟢 Đang dùng điện lưới", "border-emerald-500/40 bg-emerald-500/10", "bg-emerald-500"]
        : [`❔ ${u["ups.status"] || "không rõ trạng thái"}`, "border-border bg-muted/30", "bg-slate-400"];
  const phut = t.pin_tu && t.luc ? Math.max(0, Math.round((t.luc - t.pin_tu) / 60)) : null;
  const o = (nhanO: string, gt: string | undefined, dv: string) => (
    <div className="rounded-md border border-border p-2">
      <p className="text-[11px] text-muted-foreground">{nhanO}</p>
      <p className="text-sm font-semibold">{gt ? `${gt} ${dv}` : "—"}</p>
    </div>
  );

  return (
    <div className={`space-y-3 rounded-md border p-3 ${khung}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-base font-semibold">
          {nhan}{co.includes("CHRG") ? " · đang sạc" : ""}
        </p>
        <p className="text-xs text-muted-foreground">
          {[u["device.mfr"], u["device.model"]].filter(Boolean).join(" ") || "UPS"} · tự làm mới 5 giây
        </p>
      </div>
      {co.includes("OB") && t.pin_tu ? (
        <p className="text-sm">Chạy pin từ <b>{gio(t.pin_tu)}</b> — {phut} phút.</p>
      ) : null}
      <div className="space-y-1">
        <div className="flex justify-between text-xs">
          <span>Pin <b>{pin ?? "?"}%</b>{u["battery.voltage"] ? ` · ${u["battery.voltage"]} V` : ""}</span>
          {nguong != null ? <span className="text-rose-600">máy chủ tắt khi dưới {nguong}%</span> : null}
        </div>
        <Thanh phanTram={pin ?? 0} mau={mauPin} vach={nguong} />
      </div>
      <div className="space-y-1">
        <div className="text-xs">Tải <b>{tai ?? "?"}%</b></div>
        <Thanh phanTram={tai ?? 0} mau={tai != null && tai >= 80 ? "bg-rose-500" : "bg-sky-500"} />
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {o("Điện vào", u["input.voltage"], "V")}
        {o("Điện ra", u["output.voltage"], "V")}
        {o("Tần số", u["input.frequency"], "Hz")}
        {o("Ắc quy danh định", u["battery.voltage.nominal"], "V")}
      </div>
      {t.cho_gui ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          📨 {t.cho_gui} tin báo đang chờ gửi (chưa có mạng ra ngoài) — sẽ gửi bù khi có mạng.
        </p>
      ) : null}
      <p className="text-[11px] text-muted-foreground">
        % pin của dòng UPS này là NUT đoán từ điện áp ắc quy — lúc đang sạc có thể báo 100% ngay.
      </p>
    </div>
  );
}

export function DienNhaCard() {
  const config = useSettingsStore((s) => s.config);
  const cu = String(((config as any)?.dien_nha || {}).nut || "");
  return <DienNhaForm key={cu} cu={cu} />;
}

function DienNhaForm({ cu }: { cu: string }) {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const [nut, setNut] = useState(cu);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [kq, setKq] = useState<KetQua | null>(null);

  const luu = async () => {
    await saveConfig({ ...config, dien_nha: { ...((config as any)?.dien_nha || {}), nut: nut.trim() } } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const thu = async () => {
    setBusy(true); setKq(null);
    try {
      setKq((await request.post("/api/dien-nha/thu", { nut: nut.trim() })).data as KetQua);
    } catch (e: any) {
      setKq({ ok: false, error: e?.message || "Không gọi được máy chủ" });
    } finally { setBusy(false); }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">🔋 Điện nhà — UPS (NUT)</CardTitle>
        <CardDescription>
          c2a đọc UPS 5 giây một lần và báo khi <b>mất điện</b>, khi <b>có điện lại</b>, và khi <b>pin yếu sắp tắt
          máy chủ</b>. Tin đi theo dòng «Mất điện / có điện» ở <b>Cài đặt → Thông báo</b> — bật dòng đó và chọn kênh
          nhận. Không đọc được UPS quá 3 phút thì báo vào «Lỗi & cảnh báo hệ thống».
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {cu ? <TrangThaiUps /> : null}
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Địa chỉ NUT — dạng <code>tên-ups@máy</code> (cổng mặc định 3493)</p>
          <Input placeholder="prolink@172.16.10.100" value={nut} onChange={(e) => setNut(e.target.value)} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void luu()}>{saved ? "Đã lưu!" : "Lưu"}</Button>
          <Button variant="outline" onClick={() => void thu()} disabled={busy}>
            {busy ? "Đang thử…" : "Kiểm tra kết nối"}
          </Button>
        </div>
        {kq ? <p className="text-xs">{kq.ok ? "✅" : "❌"} {kq.ok ? kq.tom_tat : kq.error}</p> : null}

        <div className="space-y-2">
          <p className="text-sm font-medium">📖 Hướng dẫn dựng đủ các phần (lệnh chép từ máy chủ đang chạy)</p>
          <HuongDan phan={PHAN_DIEN} />
        </div>
      </CardContent>
    </Card>
  );
}
