"use client";

/**
 * Tự bật theo nếp — thiết bị chủ nhà dùng theo GIỜ (bình nóng lạnh…): bot học giờ bật + thời lượng từ các lần NGƯỜI
 * bật, tới giờ thì bật (chỉ khi nhà có người, hôm nay chưa ai bật), tự tắt, hỏi đúng/sai. Chỉ chủ nhà bật từng thiết
 * bị. API: GET/POST /api/hoc-hoi/theo-nep (05/10/2026).
 */

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { layGet, goiPost } from "./lib";

type Nep = { du: boolean; gio?: string; phut_bat?: number; so_ngay?: number; chia?: string; ly_do?: string };
type TB = { ma: string; bat: boolean; nhiet?: string | null; nep: Nep };

function docTheoNep(): Promise<TB[]> {
  return layGet<{ thiet_bi?: TB[] }>("/api/hoc-hoi/theo-nep").then((r) => r.thiet_bi || []).catch(() => []);
}

export function TheoNep() {
  const [ds, setDs] = useState<TB[] | null>(null);
  const [ma, setMa] = useState("");
  const [nhiet, setNhiet] = useState("");

  const tai = useCallback(() => docTheoNep().then(setDs), []);
  useEffect(() => { let song = true; docTheoNep().then((x) => { if (song) setDs(x); }); return () => { song = false; }; }, []);

  const dat = async (thiet_bi: string, bat: boolean, nh?: string | null) => {
    if (await goiPost("/api/hoc-hoi/theo-nep", { thiet_bi, bat, ...(nh !== undefined ? { nhiet: nh } : {}) })) void tai();
  };

  return (
    <div className="space-y-3 text-xs">
      <p className="text-muted-foreground">
        Cho thiết bị dùng theo giờ (bình nóng lạnh, máy lọc nước…). Bot học giờ anh hay bật và bật bao lâu — chỉ từ các
        lần <b>người</b> bật — rồi tới giờ tự bật khi nhà có người, tự tắt sau thời lượng đó (tối đa 45 phút), và hỏi
        «đúng/sai». Hôm nay đã có người bật thì bot thôi. Có cảm biến nhiệt độ ngoài trời thì ngày mát bật lâu hơn.
      </p>
      {(ds || []).map((x) => (
        <div key={x.ma} className="flex flex-wrap items-center gap-2 rounded border border-border p-2">
          <label className="flex items-center gap-2 font-medium">
            <input type="checkbox" checked={x.bat} onChange={(e) => void dat(x.ma, e.target.checked)} />
            {x.ma}
          </label>
          <span className="text-muted-foreground">
            {x.nep.du
              ? `nếp: bật ~${x.nep.gio}, ${x.nep.phut_bat} phút${x.nep.chia ? ` (${x.nep.chia})` : ""} · ${x.nep.so_ngay} ngày`
              : `chưa đủ nếp: ${x.nep.ly_do}`}
          </span>
          {x.nhiet ? <span className="text-muted-foreground">· nhiệt: {x.nhiet}</span> : null}
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <Input className="h-8 w-60" placeholder="switch.binh_nong_lanh" value={ma} onChange={(e) => setMa(e.target.value)} />
        <Input className="h-8 w-64" placeholder="cảm biến nhiệt ngoài trời (tuỳ chọn)" value={nhiet}
          onChange={(e) => setNhiet(e.target.value)} />
        <Button size="sm" disabled={!ma.trim()} onClick={() => { void dat(ma.trim(), true, nhiet.trim() || null); setMa(""); setNhiet(""); }}>
          Thêm & bật
        </Button>
      </div>
    </div>
  );
}
