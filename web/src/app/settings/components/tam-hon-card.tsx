"use client";

/**
 * Tâm hồn của bot — services/agent/tam_hon.py.
 *
 * Chủ máy 02/10/2026: "cần có tích kích hoạt, không để bot tự chủ" — hai ô dưới
 * đây mặc định TRỐNG; chưa tích thì bot không cảm, không viết, không vẽ gì cả.
 * Bài viết đi qua thông báo «🖋️ Bot viết & vẽ» (Cài đặt › Thông báo chọn kênh).
 */

import { useCallback, useEffect, useState } from "react";
import { Feather, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { request } from "@/lib/request";

type Bai = { luc: number; the_loai: string; tieu_de: string; noi_dung: string; anh: string; cam_xuc: string; gui: number };
type KyUc = { id: number; luc: number; noi_dung: string; cam_xuc: string };
type TrangThai = {
  bat_viet: boolean; bat_cam_xuc: boolean; goc: string; ky_uc: KyUc[];
  tam_trang: { cam_xuc?: string; cuong_do?: number; vi_sao?: string; luc?: number };
  bai: Bai[];
  thong_bao?: { bat: boolean; kenh: string[] };
};

const gio = (ts?: number) => (ts ? new Date(ts * 1000).toLocaleString("vi-VN") : "");

export function TamHonCard() {
  const [tt, setTt] = useState<TrangThai | null>(null);
  const [busy, setBusy] = useState(false);
  const [goc, setGoc] = useState<string | null>(null);

  const tai = useCallback(async () => {
    const r = await request.get("/api/tam-hon");
    if (r.data?.ok) setTt(r.data as TrangThai);
  }, []);
  useEffect(() => {
    let huy = false;
    request.get("/api/tam-hon").then((r) => { if (!huy && r.data?.ok) setTt(r.data as TrangThai); }).catch(() => {});
    return () => { huy = true; };
  }, []);

  const luuGoc = async () => {
    try {
      const r = await request.post("/api/tam-hon", { goc: goc ?? "" });
      if (r.data?.ok) { toast.success("Đã lưu gốc"); setGoc(null); await tai(); }
      else toast.error(r.data?.error || "Lưu thất bại");
    } catch { toast.error("Lưu thất bại"); }
  };

  const xoaKyUc = async (id: number) => {
    try {
      const r = await request.post("/api/tam-hon/ky-uc/xoa", { id });
      if (r.data?.ok) await tai();
      else toast.error(r.data?.error || "Xoá thất bại");
    } catch { toast.error("Xoá thất bại"); }
  };

  const dat = async (khoa: "bat_viet" | "bat_cam_xuc", v: boolean) => {
    try {
      const r = await request.post("/api/tam-hon", { [khoa]: v });
      if (r.data?.ok) await tai();
      else toast.error(r.data?.error || "Lưu thất bại");
    } catch { toast.error("Lưu thất bại"); }
  };

  const camNgay = async () => {
    setBusy(true);
    try {
      const r = await request.post("/api/tam-hon/cam-ngay", {});
      if (r.data?.ok) toast.success(r.data.bai ? "Bot vừa viết một bài" : `Tâm trạng: ${r.data.tam_trang || r.data.ly_do}`);
      else toast.error(r.data?.ly_do || r.data?.error || "Không cảm được");
      await tai();
    } catch { toast.error("Không cảm được"); }
    setBusy(false);
  };

  if (!tt) return null;
  const tb = tt.thong_bao;
  return (
    <Card>
      <CardContent className="space-y-3 pt-4">
        <div className="flex items-center gap-2">
          <Feather className="size-4" />
          <span className="text-sm font-medium">Tâm hồn của bot — cảm xúc, thơ & tranh</span>
        </div>
        <p className="text-xs text-muted-foreground">
          Bot đọc chuyện THẬT trong ngày (camera thấy ai về lúc nào, lời người nhà nhắn, thời tiết) rồi tự cảm.
          Chưa tích thì bot không làm gì.
        </p>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked={tt.bat_viet} onChange={(e) => void dat("bat_viet", e.target.checked)} />
          <span>Tự viết thơ / nhật ký kèm tranh, hoặc tâm sự ngắn, khi có chuyện đáng viết <span className="text-xs text-muted-foreground">(tối đa 2 lần/ngày, 6h–23h)</span></span>
        </label>
        {tt.bat_viet && !(tb?.bat && tb.kenh.length) ? (
          <p className="text-xs text-amber-600">
            Chưa chọn kênh nhận: vào Cài đặt › Thông báo, bật «🖋️ Bot viết &amp; vẽ» và chọn kênh — không thì bài chỉ lưu ở đây.
          </p>
        ) : null}
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked={tt.bat_cam_xuc} onChange={(e) => void dat("bat_cam_xuc", e.target.checked)} />
          <span>Cảm xúc trong lời trò chuyện <span className="text-xs text-muted-foreground">(Zalo/Telegram; không áp cho loa HA)</span></span>
        </label>
        <div className="space-y-1">
          <div className="text-sm font-medium">Gốc của bot <span className="text-xs font-normal text-muted-foreground">(chỉ anh sửa được — bot là ai trong nhà, gọi từng người thế nào, điều gì không bao giờ nói)</span></div>
          <textarea className="min-h-20 w-full rounded-md border bg-background p-2 text-sm" maxLength={1500}
            placeholder="Vd: Em là trợ lý sống cùng nhà. Gọi chủ nhà là bố, vợ chủ nhà là mẹ, các con gọi bằng tên. Không bao giờ nói chuyện tiền bạc…"
            value={goc ?? tt.goc} onChange={(e) => setGoc(e.target.value)} />
          {goc !== null && goc !== tt.goc ? (
            <Button size="sm" className="h-7" onClick={() => void luuGoc()}>Lưu gốc</Button>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>Tâm trạng: <b>{tt.tam_trang.cam_xuc || "—"}</b>{tt.tam_trang.cuong_do ? ` (${tt.tam_trang.cuong_do}/5)` : ""}</span>
          {tt.tam_trang.vi_sao ? <span className="text-xs text-muted-foreground">vì {tt.tam_trang.vi_sao}</span> : null}
          <Button size="sm" variant="outline" className="h-7" disabled={busy || !(tt.bat_viet || tt.bat_cam_xuc)} onClick={() => void camNgay()}>
            <Sparkles className="mr-1 size-3.5" /> {busy ? "Đang cảm…" : "Cảm ngay"}
          </Button>
        </div>
        {tt.ky_uc.length ? (
          <div className="space-y-1">
            <div className="text-sm font-medium">Ký ức bot giữ <span className="text-xs font-normal text-muted-foreground">(bot tự chọn điều đáng nhớ; anh bỏ được)</span></div>
            {tt.ky_uc.map((k) => (
              <div key={k.id} className="flex items-start gap-2 text-xs">
                <span className="shrink-0 text-muted-foreground">{gio(k.luc)}</span>
                <span className="flex-1">{k.noi_dung} <span className="text-muted-foreground">— {k.cam_xuc}</span></span>
                <button type="button" title="Bỏ ký ức này" className="text-destructive" onClick={() => void xoaKyUc(k.id)}>
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))}
          </div>
        ) : null}
        {tt.bai.length ? (
          <div className="space-y-2">
            {[...tt.bai].reverse().map((b) => (
              <div key={b.luc} className="rounded-md border p-2 text-sm">
                <div className="mb-1 text-xs text-muted-foreground">
                  {gio(b.luc)} · {b.the_loai === "tho" ? "thơ" : b.the_loai === "tam_su" ? "tâm sự" : "nhật ký"} · {b.cam_xuc} · {b.gui ? `đã gửi ${b.gui} kênh` : "chưa gửi kênh nào"}
                </div>
                {b.tieu_de ? <div className="font-medium">{b.tieu_de}</div> : null}
                <p className="whitespace-pre-line">{b.noi_dung}</p>
                {b.anh ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={b.anh} alt={b.tieu_de || "tranh"} className="mt-2 max-h-64 rounded" />
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
