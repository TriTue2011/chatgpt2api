"use client";

import { useState } from "react";
import { Lightbulb, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { docTien, dong, gui, lay, type TongQuan } from "../lib";

function Thanh({ phan_tram }: { phan_tram: number }) {
  const mau = phan_tram >= 100 ? "bg-rose-500" : phan_tram >= 80 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="h-2 w-full overflow-hidden rounded bg-muted">
      <div className={`h-full ${mau}`} style={{ width: `${Math.min(100, Math.max(0, phan_tram))}%` }} />
    </div>
  );
}

export function TongQuanTab({ tq, taiLai }: { tq: TongQuan; taiLai: () => Promise<void> }) {
  const n = tq.ngan_sach;
  const [hu, setHu] = useState(String(tq.hu[0]?.id ?? ""));
  const [tien, setTien] = useState("");
  const [ghiChu, setGhiChu] = useState("");
  const [deXuat, setDeXuat] = useState<string[] | null>(null);

  const them = async () => {
    const so = docTien(tien);
    if (!Number.isFinite(so) || so <= 0) return void window.alert("Số tiền chưa đúng (vd 50k, 1,2tr, 150000).");
    if (await gui("/api/chi-tieu/chi", { hu_id: Number(hu), so_tien: so, ghi_chu: ghiChu })) {
      setTien("");
      setGhiChu("");
      await taiLai();
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-4">
        {[["Ngân sách kỳ", dong(n.tong_ngan_sach)], ["Đã chi", `${dong(n.tong_da_chi)} (${n.ty_le_tong_da_dung_phan_tram}%)`],
          ["Còn lại", dong(n.tong_con_lai)],
          ["Tới kỳ lương", `${n.so_ngay_con_lai} ngày · ~${dong(n.trung_binh_moi_ngay_con_lai)}/ngày`]].map(([k, v]) => (
          <div key={k} className="rounded-md border p-3">
            <div className="text-xs text-muted-foreground">{k}</div>
            <div className={`text-sm font-semibold ${k === "Còn lại" && n.tong_con_lai < 0 ? "text-rose-600" : ""}`}>{v}</div>
          </div>
        ))}
      </div>
      {n.canh_bao_tong ? <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">{n.canh_bao_tong}</p> : null}
      {n.canh_bao_chi_phi_dac_biet ? <p className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">{n.canh_bao_chi_phi_dac_biet}</p> : null}

      <div className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm">
        <span className="font-medium">Thêm khoản chi (kỳ hiện tại):</span>
        <select className="rounded border bg-background px-2 py-1" value={hu} onChange={(e) => setHu(e.target.value)}>
          {tq.hu.map((h) => <option key={h.id} value={h.id}>{h.ten}</option>)}
        </select>
        <Input className="h-8 w-32" placeholder="50k, 1,2tr…" value={tien} onChange={(e) => setTien(e.target.value)} />
        <Input className="h-8 w-56" placeholder="Ghi chú (vd ăn trưa)" value={ghiChu} onChange={(e) => setGhiChu(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void them()} />
        <Button size="sm" onClick={() => void them()}><Plus className="mr-1 size-4" /> Ghi</Button>
      </div>

      <div className="space-y-2">
        {n.hu.map((h) => (
          <div key={h.id} className="space-y-1 rounded-md border p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{h.ten} <span className="text-xs text-muted-foreground">({h.ty_le}%)</span></span>
              <span className="text-xs">
                đã chi <b>{dong(h.da_chi)}</b> / {dong(h.han_muc_hieu_luc)} — còn{" "}
                <b className={h.con_lai < 0 ? "text-rose-600" : ""}>{dong(h.con_lai)}</b>
              </span>
            </div>
            <Thanh phan_tram={h.ty_le_da_dung_phan_tram} />
            {h.duoc_bu > 0 ? (
              <div className="text-xs text-amber-700">
                Vượt hạn mức riêng {dong(h.han_muc_truoc_bu)}, đang được bù {dong(h.duoc_bu)} từ{" "}
                {h.bu_tu.map((b) => `${b.ten} ${dong(b.so_tien)}`).join(", ")}
              </div>
            ) : null}
            {h.da_nhuong > 0 ? <div className="text-xs text-muted-foreground">Đã nhường {dong(h.da_nhuong)} bù cho hũ khác</div> : null}
          </div>
        ))}
      </div>

      <div className="space-y-2 rounded-md border p-3 text-sm">
        <Button variant="outline" size="sm" onClick={async () => {
          const r = await lay<{ de_xuat: string[] }>("/api/chi-tieu/de-xuat");
          if (r.ok) setDeXuat(r.de_xuat);
        }}><Lightbulb className="mr-1 size-4" /> Đề xuất điều chỉnh</Button>
        {deXuat ? <ul className="ml-4 list-disc text-sm">{deXuat.map((x, i) => <li key={i}>{x}</li>)}</ul> : null}
        <p className="text-xs text-muted-foreground">
          Thu nhập kỳ {n.thang}: lương {dong(n.luong)} + thu nhập thêm = {dong(n.thu_nhap_hieu_qua)}. Hạn mức từng hũ = thu
          nhập × tỷ lệ; chi phí đặc biệt trừ vào các hũ hứng; hũ vượt được tự bù từ hũ khác theo thứ tự bù (sửa ở tab Hũ &amp; lương).
        </p>
      </div>
    </div>
  );
}
