"use client";

/**
 * Ô chọn MỘT thiết bị từ danh sách đầy đủ (HA + MQTT + Tuya) rồi bấm một nút
 * hành động — dùng chung cho "phân tích thiết bị bot bỏ sót" và bất cứ chỗ
 * nào khác cần chọn thiết bị (sơ đồ kích hoạt thêm nhân tố chính mới…).
 */

import { useEffect, useState, type ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { layGet } from "./lib";

type Muc = { khoa: string; nguon: string; ma: string; ten_goc: string; ten: string };

export function ChonThietBi({
  onChon,
  dangChay,
  nhanNut,
  icon,
}: {
  onChon: (ma: string) => void | Promise<void>;
  dangChay: boolean;
  nhanNut: string;
  icon?: ReactNode;
}) {
  const [ds, setDs] = useState<Muc[]>([]);
  const [dangTai, setDangTai] = useState(true);
  const [chon, setChon] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const r = await layGet<{ danh_sach?: Muc[] }>("/api/hoc-hoi/thiet-bi-day-du");
        setDs(r.danh_sach || []);
      } finally {
        setDangTai(false);
      }
    })();
  }, []);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {dangTai ? (
        <LoaderCircle className="size-4 animate-spin text-muted-foreground" />
      ) : (
        <select className="h-8 max-w-full rounded-md border border-input bg-background px-2 text-xs"
          value={chon} onChange={(e) => setChon(e.target.value)}>
          <option value="">— chọn thiết bị —</option>
          {ds.map((m) => (
            <option key={m.khoa} value={m.ma}>
              [{m.nguon}] {m.ten || m.ten_goc} ({m.ma})
            </option>
          ))}
        </select>
      )}
      <Button size="sm" disabled={!chon || dangChay} onClick={() => void onChon(chon)}>
        {dangChay ? <LoaderCircle className="mr-1 size-3.5 animate-spin" /> : icon}
        {nhanNut}
      </Button>
    </div>
  );
}
