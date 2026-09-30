"use client";

/**
 * Sơ đồ nhà — ảnh camera CHỜ ĐÁP ÁN. Nhà không có model đọc ảnh (vd không có Claude), hoặc chọn «thu_cong» ở
 * thẻ Nhìn nhà: bot xuất ảnh đã kẻ lưới + LỆNH đầy đủ; người dùng chép vào ChatGPT / Gemini / Claude của họ, thấy
 * chia ô đúng thì dán đáp án (JSON) lại đây — bot kiểm khuôn như lúc tự đọc rồi vẽ lại sơ đồ (chủ máy 30/09/2026).
 *
 * Backend: api/hoc_hoi.py (/api/hoc-hoi/so-do-nha/cho-anh, /dap-an-anh, /chup-camera) → services/so_do_nha.py.
 */

import { useCallback, useEffect, useState } from "react";
import { Camera, Copy, Send } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { httpRequest } from "@/lib/request";
import { layGet } from "./lib";

type Cho = { luc: number; anh_url: string; lenh: string; dem?: boolean };

export function SoDoNha() {
  const [cho, setCho] = useState<Record<string, Cho>>({});
  const [dapAn, setDapAn] = useState<Record<string, string>>({});
  const [dangChup, setDangChup] = useState(false);

  const tai = useCallback(async () => {
    try {
      const r = await layGet<{ cho?: Record<string, Cho> }>("/api/hoc-hoi/so-do-nha/cho-anh");
      setCho(r.cho || {});
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

  const ds = Object.entries(cho);
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">
        Bot chụp camera, kẻ lưới rồi chia ô theo phòng. Nhà không có model đọc ảnh (hoặc chọn «thu_cong» ở thẻ Nhìn
        nhà) thì ảnh nằm đây: chép LỆNH, gửi kèm ẢNH vào ChatGPT / Gemini / Claude của anh, thấy chia ô đúng thì dán
        nguyên phần JSON {"{…}"} app trả vào ô rồi gửi. Có thể nhắn cho bot «đáp án ảnh &lt;camera&gt;: {"{…}"}».
      </p>
      <Button size="sm" variant="outline" onClick={() => void chup()} disabled={dangChup}>
        <Camera className="mr-1 h-4 w-4" />{dangChup ? "Đang chụp…" : "Chụp lại camera"}
      </Button>
      {ds.length === 0 && <p className="text-xs text-muted-foreground">Không có ảnh nào chờ đáp án.</p>}
      {ds.map(([cam, x]) => (
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
  );
}
