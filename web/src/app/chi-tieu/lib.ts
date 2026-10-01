import { toast } from "sonner";

import { httpRequest } from "@/lib/request";

/** Mọi đường đều theo CHÍNH tài khoản đăng nhập — backend không nhận so_id từ ngoài (api/chi_tieu.py). */
export type Hu = { id: number; ten: string; ty_le: number; thu_tu: number; thu_tu_bu: number; thu_tu_dac_biet: number };
export type HuNs = Hu & {
  han_muc_truoc_bu: number; da_chi: number; duoc_bu: number; da_nhuong: number; han_muc_hieu_luc: number;
  con_lai: number; ty_le_da_dung_phan_tram: number; bu_tu: { id: number; ten: string; so_tien: number }[];
};
export type MucKy = { id: number; mo_ta: string; so_tien: number; thoi_gian: string; thang: string };
export type NganSach = {
  thang: string; luong: number; thu_nhap_hieu_qua: number; hu: HuNs[]; tong_ngan_sach: number; tong_da_chi: number;
  tong_con_lai: number; ty_le_tong_da_dung_phan_tram: number; so_ngay_con_lai: number; ngay_bat_dau_ky_sau: string;
  trung_binh_moi_ngay_con_lai: number; canh_bao_tong: string | null; canh_bao_chi_phi_dac_biet: string | null;
  chi_phi_dac_biet: MucKy[]; thu_nhap_them: MucKy[]; tong_chi_phi_dac_biet: number;
};
export type So = { id: number; ten: string; luong: number; ngay_bat_dau: number; nguong: number[] };
export type LienKet = { kenh_user: string; ten: string; gan_boi: string; luc: string };
export type TongQuan = { so: So; ngan_sach: NganSach; hu: Hu[]; tong_ty_le: number; lien_ket: LienKet[]; la_admin: boolean };
export type KhoanChi = { id: number; hu_id: number; hu_ten: string; so_tien: number; ghi_chu: string; thoi_gian: string; nguon: string };

type KetQua = { ok?: boolean; error?: string; can_xac_nhan?: boolean; canh_bao?: string; [k: string]: unknown };

export async function lay<T>(path: string): Promise<T & KetQua> {
  return httpRequest<T & KetQua>(path, { method: "GET" });
}

/** POST / DELETE; lỗi thì toast. Khoản làm vượt tổng ngân sách: hỏi lại rồi gửi kèm xac_nhan_vuot_tong. */
export async function gui(path: string, body: Record<string, unknown> = {}, method: "POST" | "DELETE" = "POST"): Promise<KetQua | null> {
  try {
    let r = await httpRequest<KetQua>(path, { method, body: method === "POST" ? body : undefined });
    if (r?.can_xac_nhan) {
      if (!window.confirm(`${r.canh_bao || "Khoản này làm vượt tổng ngân sách kỳ."}\n\nVẫn ghi?`)) return null;
      r = await httpRequest<KetQua>(path, { method, body: { ...body, xac_nhan_vuot_tong: true } });
    }
    if (!r?.ok) {
      toast.error(r?.error || "Không lưu được.");
      return null;
    }
    return r;
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "Lỗi mạng.");
    return null;
  }
}

export const dong = (n: number) => `${Math.round(n || 0).toLocaleString("vi-VN")} đ`;

/** "50k", "1,2tr", "1.500.000" → số đồng; không hiểu thì NaN. */
export function docTien(s: string): number {
  const t = s.trim().toLowerCase().replace(/\s/g, "");
  const m = t.match(/^([\d.,]+)(k|nghìn|ngàn|tr|triệu|m)?$/);
  if (!m) return NaN;
  const heSo = m[2] ? (["k", "nghìn", "ngàn"].includes(m[2]) ? 1e3 : 1e6) : 1;
  const so = heSo === 1 ? Number(m[1].replace(/[.,]/g, "")) : Number(m[1].replace(",", "."));
  return Number.isFinite(so) ? Math.round(so * heSo) : NaN;
}
