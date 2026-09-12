"use client";

/**
 * Form sửa TRỰC TIẾP điều kiện của một thiết bị — chọn từ đúng thực đơn bot
 * dùng khi tự đề xuất (không cho gõ tay khoá bịa). Dùng chung cho mục "Bot
 * hiểu thiết bị" và sơ đồ kích hoạt (`so-do.tsx`) — sửa một chỗ, cả hai nơi
 * cùng thấy vì cùng gọi `sua_dieu_kien_ket_luan`.
 */

import { useEffect, useState } from "react";
import { LoaderCircle, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { layGet, goiPost } from "./lib";

type MucThucDon = { khoa: string; ten: string; loai: string };
type SoDoNut = { khoa: string; dieu_kien: { khoa: string }[]; ngoai_vi: { khoa: string }[] };

export function SuaDieuKien({ khoa, onXong }: { khoa: string; onXong: () => void }) {
  const [thucDon, setThucDon] = useState<MucThucDon[]>([]);
  const [chon, setChon] = useState<string[]>([]);
  const [dangTai, setDangTai] = useState(true);
  const [dangLuu, setDangLuu] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [td, sd] = await Promise.all([
          layGet<{ danh_sach?: MucThucDon[] }>("/api/hoc-hoi/dieu-kien-menu"),
          layGet<{ danh_sach?: SoDoNut[] }>("/api/hoc-hoi/so-do"),
        ]);
        setThucDon(td.danh_sach || []);
        const nut = (sd.danh_sach || []).find((n) => n.khoa === khoa);
        if (nut) {
          setChon([...nut.dieu_kien.map((d) => d.khoa), ...nut.ngoai_vi.map((n) => n.khoa)].filter(Boolean));
        }
      } finally {
        setDangTai(false);
      }
    })();
  }, [khoa]);

  const bat = (k: string) =>
    setChon((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : cur.length >= 5 ? cur : [...cur, k]));

  const luu = async () => {
    setDangLuu(true);
    try {
      const ok = await goiPost("/api/hoc-hoi/ket-luan/sua-dieu-kien", { khoa, dieu_kien: chon });
      if (ok) onXong();
    } finally {
      setDangLuu(false);
    }
  };

  return (
    <div className="mt-2 rounded border border-dashed border-border bg-muted/30 p-2">
      <div className="mb-1 flex items-center justify-between">
        <p className="text-[11px] font-semibold">Chọn tối đa 5 điều kiện</p>
        <Button variant="ghost" size="sm" className="h-6" onClick={onXong}><X className="size-3.5" /></Button>
      </div>
      {dangTai ? (
        <LoaderCircle className="size-4 animate-spin text-muted-foreground" />
      ) : (
        <div className="flex flex-wrap gap-1">
          {thucDon.map((m) => (
            <label key={m.khoa}
              className={`cursor-pointer rounded border px-1.5 py-0.5 text-[11px] ${
                chon.includes(m.khoa) ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
              }`}>
              <input type="checkbox" className="mr-1 align-middle" checked={chon.includes(m.khoa)}
                onChange={() => bat(m.khoa)} />
              {m.ten}
            </label>
          ))}
          {!thucDon.length ? <p className="text-[11px] text-muted-foreground">Chưa đo được thực đơn điều kiện.</p> : null}
        </div>
      )}
      <div className="mt-2 flex justify-end">
        <Button size="sm" className="h-7" disabled={dangLuu} onClick={() => void luu()}>
          {dangLuu ? <LoaderCircle className="mr-1 size-3.5 animate-spin" /> : <Save className="mr-1 size-3.5" />}
          Lưu điều kiện
        </Button>
      </div>
    </div>
  );
}
