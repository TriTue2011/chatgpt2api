"use client";

/**
 * Tâm hồn của bot — services/agent/tam_hon.py.
 *
 * Chủ máy 02/10/2026: "cần có tích kích hoạt, không để bot tự chủ" — chưa thread nào tích thì bot không cảm, không
 * viết. 05/10/2026: bật THEO TỪNG THREAD ở Lọc thread (Thơ · Văn · Nói chuyện phiếm), bài gửi thẳng vào thread đó.
 * Thẻ này chỉ còn gốc, tâm trạng, ký ức, bài đã viết.
 */

import { useCallback, useEffect, useState } from "react";
import { Feather, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { request } from "@/lib/request";

type Bai = { luc: number; the_loai: string; tieu_de: string; noi_dung: string; cam_xuc: string; gui: number };
type KyUc = { id: number; luc: number; noi_dung: string; cam_xuc: string };
type TrangThai = {
  goc: string; ky_uc: KyUc[]; thread: { khoa: string; kieu: string[] }[];
  tam_trang: { cam_xuc?: string; cuong_do?: number; vi_sao?: string; luc?: number };
  bai: Bai[];
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
  const TEN = { tho: "thơ", van: "văn", phiem: "phiếm" } as Record<string, string>;
  return (
    <Card>
      <CardContent className="space-y-3 pt-4">
        <div className="flex items-center gap-2">
          <Feather className="size-4" />
          <span className="text-sm font-medium">Tâm hồn của bot — gốc, tâm trạng, ký ức</span>
        </div>
        <p className="text-xs text-muted-foreground">
          Bot đọc chuyện THẬT trong ngày (camera thấy ai về lúc nào, lời người nhà nhắn, thời tiết) rồi tự cảm.
          Chưa tích thì bot không làm gì.
        </p>
        <p className="text-sm">
          {tt.thread.length
            ? <>Đang bật ở: {tt.thread.map((t) => `${t.khoa.split(":").pop()} (${t.kieu.map((k) => TEN[k] || k).join(", ")})`).join(" · ")}</>
            : <span className="text-amber-600">Chưa thread nào bật — tích «🖋️ Tâm hồn» ở Lọc thread của từng thread.</span>}
        </p>
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
          <Button size="sm" variant="outline" className="h-7" disabled={busy || !tt.thread.length} onClick={() => void camNgay()}>
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
                  {gio(b.luc)} · {b.the_loai === "tho" ? "thơ" : b.the_loai === "van" ? "văn" : b.the_loai === "tam_su" ? "phiếm" : b.the_loai} · {b.cam_xuc} · {b.gui ? `đã gửi ${b.gui} thread` : "chưa gửi thread nào"}
                </div>
                {b.tieu_de ? <div className="font-medium">{b.tieu_de}</div> : null}
                <p className="whitespace-pre-line">{b.noi_dung}</p>
              </div>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
