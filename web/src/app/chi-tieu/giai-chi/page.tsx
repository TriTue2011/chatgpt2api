"use client";

/**
 * Trang in giải chi tạm ứng công ty — thay cho PDF của bản gốc (chi-tieu-mcp dùng fpdf2; c2a không có thư viện
 * PDF, nên in thẳng từ trình duyệt: In → Lưu thành PDF). Chỉ đọc lần giải chi của CHÍNH sổ đang đăng nhập.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Printer } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuthGuard } from "@/lib/use-auth-guard";

import { dong, lay } from "../lib";

type Gd = { id: number; loai: string; so_tien: number; mo_ta: string; thoi_gian: string };
type Gc = { id: number; thoi_gian: string; tong_tam_ung: number; tong_chi: number; so_du: number };

function Noi() {
  const id = useSearchParams().get("id") || "";
  const { session } = useAuthGuard(["admin", "user"]);
  const [d, setD] = useState<{ giai_chi: Gc; giao_dich: Gd[]; ten_so: string } | null>(null);
  const [loi, setLoi] = useState("");
  useEffect(() => {
    if (!session || !id) return;
    void lay<{ giai_chi: Gc; giao_dich: Gd[]; ten_so: string }>(`/api/chi-tieu/giai-chi/${encodeURIComponent(id)}`)
      .then((r) => (r.ok ? setD(r) : setLoi(r.error || "Không đọc được.")));
  }, [session, id]);
  if (loi) return <p className="p-6 text-sm text-destructive">{loi}</p>;
  if (!d) return null;
  return (
    <div className="mx-auto max-w-3xl space-y-4 bg-white p-8 text-black print:p-0">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold">GIẢI CHI TẠM ỨNG CÔNG TY</h1>
          <p className="text-sm">{d.ten_so} · lần #{d.giai_chi.id} · {new Date(d.giai_chi.thoi_gian).toLocaleString("vi-VN")}</p>
        </div>
        <Button className="print:hidden" size="sm" onClick={() => window.print()}><Printer className="mr-1 size-4" /> In / lưu PDF</Button>
      </div>
      <table className="w-full border-collapse text-sm">
        <thead><tr className="border-b-2 border-black text-left"><th className="py-1">Ngày</th><th>Loại</th><th>Nội dung</th><th className="text-right">Số tiền</th></tr></thead>
        <tbody>
          {d.giao_dich.map((x) => (
            <tr key={x.id} className="border-b">
              <td className="py-1">{new Date(x.thoi_gian).toLocaleDateString("vi-VN")}</td>
              <td>{x.loai === "tam_ung" ? "Tạm ứng" : "Chi"}</td><td>{x.mo_ta}</td>
              <td className="text-right">{x.loai === "tam_ung" ? "" : "−"}{dong(x.so_tien)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="space-y-1 text-right text-sm">
        <div>Tổng tạm ứng: <b>{dong(d.giai_chi.tong_tam_ung)}</b></div>
        <div>Tổng chi: <b>{dong(d.giai_chi.tong_chi)}</b></div>
        <div className="text-base">
          {d.giai_chi.so_du >= 0 ? "Hoàn lại công ty" : "Công ty trả thêm"}: <b>{dong(Math.abs(d.giai_chi.so_du))}</b>
        </div>
      </div>
    </div>
  );
}

export default function GiaiChiPage() {
  return <Suspense fallback={null}><Noi /></Suspense>;
}
