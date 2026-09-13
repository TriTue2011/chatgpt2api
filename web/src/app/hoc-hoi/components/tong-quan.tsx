"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { layGet, goiPost } from "./lib";

type Diem = { loai: string; diem: number; con_hoi: boolean; sai_gan_day: number };
type LanGiai = { luc: string; model: string; so_nhom: number; loi: string } | null;
type TongQuanData = {
  ok: boolean;
  tang?: Record<string, boolean>;
  nhan_ten_tang?: Record<string, string>;
  diem?: Diem[];
  du_doan?: Record<string, unknown>;
  lan_giai_gan_nhat?: LanGiai;
  kenh_nhan?: string[];
};

const TEN_LOAI: Record<string, string> = {
  cung_thiet_bi: "Cùng thiết bị",
  nguon_nhanh: "Nguồn nhanh",
  hoc: "Học thói quen",
  dieu_kien: "Điều kiện",
  ngoai_vi: "Ngoại vi theo khu vực",
};

export function TongQuan() {
  const [d, setD] = useState<TongQuanData | null>(null);
  const [dangTai, setDangTai] = useState(false);

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      setD(await layGet<TongQuanData>("/api/hoc-hoi/tong-quan"));
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  const doiTang = async (khoa: string, bat: boolean) => {
    if (await goiPost("/api/hoc-hoi/tang/bat", { khoa, bat })) void tai();
  };

  if (!d) {
    return (
      <div className="flex items-center gap-2 p-3 text-xs text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" /> Đang tải…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      {/* Công tắc từng tầng */}
      <div>
        <p className="mb-1 text-xs font-semibold">Bật / tắt từng tầng học</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {Object.entries(d.nhan_ten_tang || {}).map(([khoa, ten]) => (
            <label key={khoa} className="flex items-center gap-2 rounded border border-border px-2 py-1.5 text-xs">
              <input
                type="checkbox"
                checked={Boolean(d.tang?.[khoa])}
                onChange={(e) => void doiTang(khoa, e.target.checked)}
              />
              <span>{ten}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Điểm từng loại câu hỏi */}
      <div>
        <p className="mb-1 text-xs font-semibold">Độ tin cậy từng loại câu hỏi</p>
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="px-2 py-1 text-left">Loại</th>
                <th className="px-2 py-1 text-right">Điểm</th>
                <th className="px-2 py-1 text-right">Trạng thái</th>
              </tr>
            </thead>
            <tbody>
              {(d.diem || []).map((x) => (
                <tr key={x.loai} className="border-t border-border/60">
                  <td className="px-2 py-1">{TEN_LOAI[x.loai] || x.loai}</td>
                  <td className="px-2 py-1 text-right">{(x.diem * 100).toFixed(0)}%</td>
                  <td className="px-2 py-1 text-right">
                    {x.con_hoi ? (
                      <span className="text-amber-600">còn hỏi</span>
                    ) : (
                      // "Đang tin" chứ không phải "đã tin" — vẫn liên tục theo
                      // dõi, sai 2/10 lượt gần nhất là tụt về hỏi lại.
                      <span className="text-green-600">đang tin — {x.sai_gan_day} sai/10 lượt gần nhất</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-1 text-xs text-muted-foreground">
        <p>
          Lần giải gần nhất:{" "}
          {d.lan_giai_gan_nhat
            ? `${d.lan_giai_gan_nhat.luc} · ${d.lan_giai_gan_nhat.model} · ${d.lan_giai_gan_nhat.so_nhom} nhóm${
                d.lan_giai_gan_nhat.loi ? ` · lỗi: ${d.lan_giai_gan_nhat.loi}` : ""
              }`
            : "chưa có"}
        </p>
        {/* Kênh nhận đã dời hẳn sang Cài đặt → Thông báo (13/09/2026). Để lại
            dòng này là hai nơi cùng nói về một thứ, mà nó còn nói sai: không
            còn "admin mặc định" nào nữa. */}
      </div>
    </div>
  );
}
