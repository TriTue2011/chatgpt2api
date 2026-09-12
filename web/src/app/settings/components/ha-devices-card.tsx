"use client";

/**
 * Thiết bị & tên — danh sách ĐẦY ĐỦ thiết bị/thực thể (HA + MQTT + Tuya), bấm
 * vào đặt tên/khu vực ngay. Trước đây phần này nằm trong tab "Học hỏi" nhưng
 * chỉ liệt kê thứ ĐÃ TỪNG gặp (sổ tên), không cho duyệt toàn bộ danh sách
 * thiết bị đang có — chủ máy chốt chuyển sang đây, đúng chỗ quản lý thiết bị.
 */

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { httpRequest } from "@/lib/request";

type Muc = {
  khoa: string;
  nguon: "ha" | "mqtt" | "tuya";
  ma: string;
  ten_goc: string;
  ten: string;
  khu_vuc: string;
  khu_vuc_goi_y: string;
};

const NHAN_NGUON: Record<string, string> = { ha: "HA", mqtt: "MQTT", tuya: "Tuya" };

export function HaDevicesCard() {
  const [ds, setDs] = useState<Muc[]>([]);
  const [dangTai, setDangTai] = useState(false);
  const [loc, setLoc] = useState("");
  const [nhap, setNhap] = useState<Record<string, { ten: string; khu_vuc: string }>>({});

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const r = await httpRequest<{ danh_sach?: Muc[] }>("/api/hoc-hoi/thiet-bi-day-du", { method: "GET" });
      setDs(r.danh_sach || []);
      setNhap({});
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => { void tai(); }, [tai]);

  const luu = async (m: Muc) => {
    const v = nhap[m.khoa] || { ten: m.ten, khu_vuc: m.khu_vuc || m.khu_vuc_goi_y };
    const nguon = m.khoa.split(":", 1)[0];
    const res = await httpRequest<{ ok?: boolean }>("/api/hoc-hoi/ten/dat", {
      method: "POST",
      body: { nguon, loai: "thiet_bi", ma: m.ma, ten: v.ten, khu_vuc: v.khu_vuc },
    });
    if (res?.ok) void tai();
  };
  const xoaTen = async (khoa: string) => {
    await httpRequest("/api/hoc-hoi/ten/xoa", { method: "POST", body: { khoa } });
    void tai();
  };

  const locXuong = loc.trim().toLowerCase();
  const hienThi = locXuong
    ? ds.filter((m) => m.ten_goc.toLowerCase().includes(locXuong) || m.ten.toLowerCase().includes(locXuong)
        || m.ma.toLowerCase().includes(locXuong))
    : ds;

  return (
    <div className="space-y-3 rounded-xl border-2 border-slate-200 bg-[var(--card)]/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-xs font-bold text-slate-800">Thiết bị & tên</p>
          <p className="text-[10px] text-[var(--muted-foreground)]">
            Toàn bộ thiết bị/thực thể HA + MQTT + Tuya đang có. Bấm vào đặt tên và khu vực.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      <Input placeholder="Lọc theo tên hoặc mã…" value={loc} onChange={(e) => setLoc(e.target.value)}
        className="h-8 text-xs" />

      {dangTai && !ds.length ? (
        <div className="flex items-center gap-2 p-2 text-xs text-[var(--muted-foreground)]">
          <LoaderCircle className="size-4 animate-spin" /> Đang tải…
        </div>
      ) : (
        <div className="max-h-[32rem] overflow-auto rounded border border-border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/60 text-[var(--muted-foreground)]">
              <tr>
                <th className="px-2 py-1 text-left">Nguồn</th>
                <th className="px-2 py-1 text-left">Mã / tên gốc</th>
                <th className="px-2 py-1 text-left">Tên</th>
                <th className="px-2 py-1 text-left">Khu vực</th>
                <th className="px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {hienThi.map((m) => {
                const v = nhap[m.khoa] || { ten: m.ten, khu_vuc: m.khu_vuc || m.khu_vuc_goi_y };
                return (
                  <tr key={m.khoa} className="border-t border-border/60">
                    <td className="px-2 py-1 align-top text-[var(--muted-foreground)]">{NHAN_NGUON[m.nguon] || m.nguon}</td>
                    <td className="px-2 py-1 align-top">
                      <div>{m.ten_goc}</div>
                      <div className="text-[10px] text-[var(--muted-foreground)]">{m.ma}</div>
                    </td>
                    <td className="px-2 py-1">
                      <Input value={v.ten} placeholder="chưa đặt tên" className="h-7 text-xs"
                        onChange={(e) => setNhap({ ...nhap, [m.khoa]: { ...v, ten: e.target.value } })} />
                    </td>
                    <td className="px-2 py-1">
                      <Input value={v.khu_vuc} placeholder={m.khu_vuc_goi_y ? `gợi ý: ${m.khu_vuc_goi_y}` : "chưa rõ"}
                        className="h-7 text-xs"
                        onChange={(e) => setNhap({ ...nhap, [m.khoa]: { ...v, khu_vuc: e.target.value } })} />
                    </td>
                    <td className="whitespace-nowrap px-2 py-1 text-right align-top">
                      <Button variant="outline" size="sm" className="h-7" onClick={() => void luu(m)}>Lưu</Button>
                      {m.ten ? (
                        <Button variant="ghost" size="sm" className="h-7 text-destructive" onClick={() => void xoaTen(m.khoa)}>
                          <Trash2 className="size-3.5" />
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
              {!hienThi.length ? (
                <tr><td colSpan={5} className="px-2 py-3 text-center text-[var(--muted-foreground)]">Không có thiết bị nào khớp.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
