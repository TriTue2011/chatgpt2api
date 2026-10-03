"use client";

/**
 * Ngưỡng bộ não học hỏi — các số chủ máy chốt (đủ bao nhiêu lượt + đúng bao nhiêu % thì bot TỰ làm; cổng kiểm tiến
 * dần) nay xem và chỉnh được trên web. Trước đây cứng trong du_doan_nha.py. Backend chặn biên nên không đặt được số
 * phá học; để trống ô là về mặc định. API: GET trong /api/hoc-hoi/tong-quan (khoá "nguong"), POST /api/hoc-hoi/nguong.
 */

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { layGet, goiPost } from "./lib";

type O = { gia_tri: number; mac_dinh: number; nho: number; lon: number };
type Nguong = Record<string, O>;

const NHAN: Record<string, { ten: string; ghi: string; phan_tram?: boolean }> = {
  mau_len_cap: { ten: "Số lượt để tự làm", ghi: "Phải được chấm đủ ngần này lượt mới xét cho thiết bị tự làm." },
  ty_le_len_cap: { ten: "Tỉ lệ đúng để tự làm", phan_tram: true, ghi: "Đúng từ mức này trở lên (tính trên các lượt đã chấm) mới tự làm." },
  sai_tut_cap: { ten: "Sai bao nhiêu thì tụt về hỏi", ghi: "Đang tự làm mà sai ngần này lần trong 10 lượt gần nhất thì quay lại hỏi." },
  kiem_ngay: { ten: "Số ngày thử (kiểm tiến dần)", ghi: "Sống lại ngần này ngày cuối để thử luật trước khi cho mở miệng." },
  kiem_toi_thieu: { ten: "Số lần đoán tối thiểu khi thử", ghi: "Trong mấy ngày thử phải có ít nhất ngần này lần đủ chắc để đoán." },
  kiem_ty_le: { ten: "Tỉ lệ trúng khi thử", phan_tram: true, ghi: "Từ mức này số lần đoán phải trúng thì luật mới qua cổng." },
  p_goi_y: { ten: "Độ chắc tối thiểu để mở miệng", phan_tram: true, ghi: "Dưới mức này thì bot im, không gợi ý." },
};
const THU_TU = ["mau_len_cap", "ty_le_len_cap", "sai_tut_cap", "p_goi_y", "kiem_ngay", "kiem_toi_thieu", "kiem_ty_le"];

const hienThi = (k: string, v: number) => (NHAN[k]?.phan_tram ? Math.round(v * 100).toString() : v.toString());

export function Nguong() {
  const [d, setD] = useState<Nguong | null>(null);
  const [nhap, setNhap] = useState<Record<string, string>>({});
  const [dang, setDang] = useState(false);

  const tai = useCallback(() => {
    return layGet<{ nguong?: Nguong }>("/api/hoc-hoi/tong-quan").then((r) => {
      if (r.nguong) { setD(r.nguong); setNhap({}); }
    });
  }, []);
  // Nạp lần đầu: truyền hàm cho .then thay vì gọi setState thẳng trong effect.
  useEffect(() => { let s = true; tai(); return () => { s = false; void s; }; }, [tai]);

  const luu = async (k: string, ve_mac_dinh = false) => {
    setDang(true);
    const o = d![k];
    // Ô nhập theo % (0–100) đổi về tỉ lệ 0–1 trước khi gửi.
    let gt: number | null = null;
    if (!ve_mac_dinh) {
      const raw = parseFloat(nhap[k]);
      if (Number.isNaN(raw)) { setDang(false); return; }
      gt = NHAN[k]?.phan_tram ? raw / 100 : raw;
    }
    if (await goiPost("/api/hoc-hoi/nguong", { khoa: k, gia_tri: gt })) await tai();
    setDang(false);
    void o;
  };

  if (!d) {
    return <div className="flex items-center gap-2 p-3 text-xs text-muted-foreground"><LoaderCircle className="size-4 animate-spin" /> Đang tải…</div>;
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Số chủ máy chốt cho bộ não. Đổi bừa có thể làm bot tự làm khi chưa đủ tin, nên mỗi ô chỉ nhận trong khoảng an
        toàn; để trống rồi bấm «Mặc định» là trả về số gốc.
      </p>
      {THU_TU.filter((k) => d[k]).map((k) => {
        const o = d[k];
        const n = NHAN[k] || { ten: k, ghi: "" };
        const dangDat = o.gia_tri !== o.mac_dinh;
        return (
          <div key={k} className="rounded-md border border-border p-2">
            <div className="flex flex-wrap items-center gap-2">
              <div className="min-w-56 flex-1">
                <div className="text-sm font-medium">{n.ten}{n.phan_tram ? " (%)" : ""}{dangDat ? <span className="ml-1 text-[10px] text-amber-600">· đã đổi</span> : null}</div>
                <div className="text-[11px] text-muted-foreground">{n.ghi}</div>
              </div>
              <Input className="h-8 w-24" inputMode="decimal"
                placeholder={hienThi(k, o.gia_tri)}
                value={nhap[k] ?? ""}
                onChange={(e) => setNhap({ ...nhap, [k]: e.target.value })} />
              <span className="text-[11px] text-muted-foreground">
                {n.phan_tram ? `${Math.round(o.nho * 100)}–${Math.round(o.lon * 100)}` : `${o.nho}–${o.lon}`}
              </span>
              <Button size="sm" disabled={dang || !(nhap[k] ?? "").trim()} onClick={() => void luu(k)}>Lưu</Button>
              <Button size="sm" variant="ghost" disabled={dang || !dangDat} onClick={() => void luu(k, true)}>Mặc định</Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
