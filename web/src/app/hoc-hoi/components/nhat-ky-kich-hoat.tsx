"use client";

/**
 * Nhật ký kích hoạt — mỗi lần bot BẬT / TẮT / HỎI / KHÔNG LÀM (và lần người tự bật tắt): thời gian, thiết bị,
 * nguồn kích hoạt (cảm biến, ngoại vi, luật), lý do, điều kiện lúc đó (giờ, độ sáng, xác suất…).
 * Chủ máy 30/09/2026: "Thêm lịch sử kích hoạt thiết bị, kèm thêm nguyên nhân (thiết bị, ngoại vi, điều kiện)
 * tắt hay bật, hoặc không thực hiện, thời gian nào".
 *
 * Backend: api/hoc_hoi.py (/api/hoc-hoi/kich-hoat/nhat-ky) → services/nhat_ky_kich_hoat.py.
 */

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { layGet } from "./lib";

type Dong = {
  id: number;
  ts: number;
  thiet_bi: string;
  ten: string;
  hanh_dong: "on" | "off";
  ket_qua: "lam" | "hoi" | "khong" | "nguoi";
  nguon: string;
  ly_do: string;
  dieu_kien: Record<string, number | string>;
};

const KET_QUA: Record<Dong["ket_qua"], { chu: string; mau: string }> = {
  lam: { chu: "Bot đã làm", mau: "text-emerald-600" },
  hoi: { chu: "Bot hỏi", mau: "text-amber-600" },
  khong: { chu: "Không làm", mau: "text-muted-foreground" },
  nguoi: { chu: "Người tự làm", mau: "text-sky-600" },
};

function dieuKien(dk: Dong["dieu_kien"]): string {
  return Object.entries(dk || {})
    .map(([k, v]) => {
      if (k === "p") return `chắc ${Math.round(Number(v) * 100)}%`;
      if (k === "giờ") {
        const g = Number(v);
        return `${Math.floor(g)}h${String(Math.round((g % 1) * 60)).padStart(2, "0")}`;
      }
      return `${k.replace(/^sensor\./, "")}: ${v}`;
    })
    .join(" · ");
}

export function NhatKyKichHoat() {
  const [ds, setDs] = useState<Dong[]>([]);
  const [thietBi, setThietBi] = useState("");
  const [ketQua, setKetQua] = useState("");
  const [gio, setGio] = useState(24);
  const [dangTai, setDangTai] = useState(false);
  const [tatCaThietBi, setTatCaThietBi] = useState<{ ma: string; ten: string }[]>([]);

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const q = new URLSearchParams({ gio: String(gio) });
      if (thietBi) q.set("thiet_bi", thietBi);
      if (ketQua) q.set("ket_qua", ketQua);
      const r = await layGet<{ nhat_ky?: Dong[] }>(`/api/hoc-hoi/kich-hoat/nhat-ky?${q}`);
      const moi = r.nhat_ky || [];
      setDs(moi);
      if (!thietBi) {
        const gap = new Map<string, string>();
        moi.forEach((x) => gap.set(x.thiet_bi, x.ten));
        setTatCaThietBi([...gap].map(([ma, ten]) => ({ ma, ten })));
      }
    } finally {
      setDangTai(false);
    }
  }, [thietBi, ketQua, gio]);

  useEffect(() => {
    void tai();
  }, [tai]);

  return (
    <div className="space-y-2 text-sm">
      <p className="text-xs text-muted-foreground">
        Mỗi lần bot bật, tắt, hỏi hay <b>không làm</b> — kèm cảm biến / ngoại vi đã kích hoạt, lý do và điều kiện
        lúc đó; cả những lần người tự bật tắt để đọc được đủ dòng thời gian. Giữ 14 ngày.
      </p>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <select className="h-8 rounded-md border border-input bg-background px-2" value={thietBi}
          onChange={(e) => setThietBi(e.target.value)}>
          <option value="">Mọi thiết bị</option>
          {tatCaThietBi.map((t) => <option key={t.ma} value={t.ma}>{t.ten}</option>)}
        </select>
        <select className="h-8 rounded-md border border-input bg-background px-2" value={ketQua}
          onChange={(e) => setKetQua(e.target.value)}>
          <option value="">Mọi kết quả</option>
          {Object.entries(KET_QUA).map(([k, v]) => <option key={k} value={k}>{v.chu}</option>)}
        </select>
        <select className="h-8 rounded-md border border-input bg-background px-2" value={gio}
          onChange={(e) => setGio(Number(e.target.value))}>
          <option value={3}>3 giờ qua</option>
          <option value={24}>24 giờ qua</option>
          <option value={72}>3 ngày qua</option>
          <option value={336}>14 ngày qua</option>
        </select>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className={`mr-1 size-3.5 ${dangTai ? "animate-spin" : ""}`} /> Tải lại
        </Button>
      </div>
      <div className="max-h-[480px] space-y-1 overflow-y-auto">
        {ds.map((x) => (
          <div key={x.id} className="rounded border px-2 py-1 text-xs">
            <div className="flex flex-wrap items-center gap-x-2">
              <span className="font-mono text-muted-foreground">
                {new Date(x.ts * 1000).toLocaleString("vi-VN")}
              </span>
              <span className="font-medium">{x.ten}</span>
              <span>{x.hanh_dong === "on" ? "Bật" : "Tắt"}</span>
              <span className={KET_QUA[x.ket_qua]?.mau}>{KET_QUA[x.ket_qua]?.chu ?? x.ket_qua}</span>
            </div>
            {x.nguon ? <div><span className="text-muted-foreground">Nguồn:</span> {x.nguon}</div> : null}
            {x.ly_do ? <div><span className="text-muted-foreground">Lý do:</span> {x.ly_do}</div> : null}
            {Object.keys(x.dieu_kien || {}).length ? (
              <div className="text-muted-foreground">Điều kiện: {dieuKien(x.dieu_kien)}</div>
            ) : null}
          </div>
        ))}
        {!ds.length ? <p className="text-center text-xs text-muted-foreground">Chưa có lần nào trong khoảng này.</p> : null}
      </div>
    </div>
  );
}
