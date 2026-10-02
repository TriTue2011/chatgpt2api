"use client";

import { useCallback, useEffect, useState } from "react";
import { Mail, Pencil, Plug, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { gui, lay } from "../lib";

type HopThu = {
  id: number; ten: string; imap_host: string; imap_port: number; dia_chi: string; nguoi_gui: string[]; bat: number;
  tu_ngay: string; luc_quet: string; loi: string; so_da_ghi: number;
};
type Form = { id?: number; ten: string; imap_host: string; imap_port: string; dia_chi: string; mat_khau: string; nguoi_gui: string };
const TRONG: Form = { ten: "", imap_host: "imap.gmail.com", imap_port: "993", dia_chi: "", mat_khau: "", nguoi_gui: "" };

/** Hộp thư CỦA SỔ: bot đọc thư báo biến động của các người gửi đã khai rồi tự ghi (services/chi_tieu/email_chi.py). */
export function HopThuTab({ taiLai }: { taiLai: () => Promise<void> }) {
  const [ds, setDs] = useState<HopThu[] | null>(null);
  const [f, setF] = useState<Form | null>(null);
  const [dang, setDang] = useState<number | null>(null);

  const tai = useCallback(async () => {
    const r = await lay<{ hop_thu: HopThu[] }>("/api/chi-tieu/hop-thu");
    if (r.ok) setDs(r.hop_thu);
  }, []);
  useEffect(() => { void tai(); }, [tai]);

  const luu = async () => {
    if (!f) return;
    const r = await gui("/api/chi-tieu/hop-thu", {
      id: f.id, ten: f.ten, imap_host: f.imap_host, imap_port: Number(f.imap_port), dia_chi: f.dia_chi,
      mat_khau: f.mat_khau, nguoi_gui: f.nguoi_gui.split(/[\n,]/).map((x) => x.trim()).filter(Boolean),
    });
    if (r) { toast.success("Đã lưu hộp thư."); setF(null); await tai(); }
  };

  const viec = async (id: number, duong: "thu" | "quet") => {
    setDang(id);
    try {
      const r = await gui(`/api/chi-tieu/hop-thu/${id}/${duong}`);
      if (r && duong === "thu") toast.success(`Kết nối được — có ${r.so_thu_tu_dau_ky as number} thư của người gửi đã khai từ đầu kỳ.`);
      if (r && duong === "quet") {
        if (r.loi) toast.error(String(r.loi));
        else toast.success(`Đã ghi ${r.da_ghi as number} giao dịch mới.`);
        await taiLai();
      }
      await tai();
    } finally {
      setDang(null);
    }
  };

  if (!ds) return null;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">
        Nối hộp thư nhận thư báo biến động số dư của ngân hàng / ví. Bot chỉ đọc thư của các địa chỉ người gửi anh khai,
        mở hộp thư ở chế độ chỉ đọc (không đánh dấu đã đọc, không xoá), tự ghi CHI vào hũ hợp nhất và THU vào thu nhập thêm,
        rồi nhắn các kênh chat đã liên kết để anh sửa nếu sai. Thư từ đầu kỳ lương hiện tại trở đi.
      </p>
      <div className="divide-y rounded-md border">
        {ds.map((h) => (
          <div key={h.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
            <Mail className="size-4 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="font-medium">{h.ten || h.dia_chi} <span className="text-xs text-muted-foreground">{h.dia_chi}</span></div>
              <div className="text-xs text-muted-foreground">
                Người gửi: {h.nguoi_gui.join(", ")} · đã ghi {h.so_da_ghi} giao dịch
                {h.luc_quet ? ` · quét ${new Date(h.luc_quet).toLocaleString("vi-VN")}` : " · chưa quét"}
              </div>
              {h.loi ? <div className="text-xs text-rose-600">{h.loi}</div> : null}
            </div>
            <Button size="sm" variant="outline" className="h-7" disabled={dang === h.id} onClick={() => void viec(h.id, "thu")}>
              <Plug className="mr-1 size-3.5" /> Thử kết nối
            </Button>
            <Button size="sm" variant="outline" className="h-7" disabled={dang === h.id} onClick={() => void viec(h.id, "quet")}>
              <RefreshCw className={`mr-1 size-3.5 ${dang === h.id ? "animate-spin" : ""}`} /> Quét ngay
            </Button>
            <button type="button" title="Sửa" onClick={() => setF({
              id: h.id, ten: h.ten, imap_host: h.imap_host, imap_port: String(h.imap_port), dia_chi: h.dia_chi, mat_khau: "",
              nguoi_gui: h.nguoi_gui.join("\n"),
            })}><Pencil className="size-3.5" /></button>
            <button type="button" title="Xoá" className="text-destructive" onClick={async () => {
              if (window.confirm(`Bỏ nối hộp thư ${h.dia_chi}? Các khoản đã ghi vẫn giữ.`)
                && await gui(`/api/chi-tieu/hop-thu/${h.id}`, {}, "DELETE")) await tai();
            }}><Trash2 className="size-3.5" /></button>
          </div>
        ))}
        {!ds.length ? <p className="px-3 py-3 text-xs text-muted-foreground">Chưa nối hộp thư nào.</p> : null}
      </div>

      {f ? (
        <div className="space-y-2 rounded-md border p-3">
          <div className="font-medium">{f.id ? "Sửa hộp thư" : "Thêm hộp thư"}</div>
          <div className="grid gap-2 sm:grid-cols-2">
            <Input placeholder="Tên gợi nhớ (vd Gmail chính)" value={f.ten} onChange={(e) => setF({ ...f, ten: e.target.value })} />
            <Input placeholder="Địa chỉ email" value={f.dia_chi} onChange={(e) => setF({ ...f, dia_chi: e.target.value })} />
            <Input placeholder="Máy chủ IMAP" value={f.imap_host} onChange={(e) => setF({ ...f, imap_host: e.target.value })} />
            <Input placeholder="Cổng" value={f.imap_port} onChange={(e) => setF({ ...f, imap_port: e.target.value })} />
            <Input type="password" autoComplete="new-password"
              placeholder={f.id ? "Mật khẩu ứng dụng (để trống = giữ như cũ)" : "Mật khẩu ứng dụng 16 ký tự"}
              value={f.mat_khau} onChange={(e) => setF({ ...f, mat_khau: e.target.value })} />
          </div>
          <textarea className="min-h-[72px] w-full rounded border bg-background px-2 py-1 text-sm"
            placeholder={"Địa chỉ người gửi, mỗi dòng một địa chỉ — vd\nVCBDigibank@info.vietcombank.com.vn\n@techcombank.com.vn (cả tên miền)"}
            value={f.nguoi_gui} onChange={(e) => setF({ ...f, nguoi_gui: e.target.value })} />
          <p className="text-xs text-muted-foreground">
            Gmail: bật xác minh 2 bước rồi tạo mật khẩu ứng dụng ở{" "}
            <a className="underline" href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">myaccount.google.com/apppasswords</a>.
            Địa chỉ người gửi: mở một thư báo biến động của ngân hàng, chép địa chỉ ở dòng «Từ».
          </p>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => void luu()}>Lưu</Button>
            <Button size="sm" variant="ghost" onClick={() => setF(null)}>Huỷ</Button>
          </div>
        </div>
      ) : (
        <Button size="sm" variant="outline" onClick={() => setF({ ...TRONG })}><Plus className="mr-1 size-4" /> Thêm hộp thư</Button>
      )}
    </div>
  );
}
