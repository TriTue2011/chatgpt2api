"use client";

/**
 * Thẻ "Điện nhà" — địa chỉ NUT (Network UPS Tools) để c2a đọc UPS 5 giây một lần và báo mất điện / có điện /
 * pin yếu sắp tắt máy chủ (services/dien_nha.py). Chủ máy 05/10/2026: "thêm hướng dẫn … cài nut để kết nối
 * với c2a". Cùng lối với mang-nha-card.tsx: thử địa chỉ VỪA NHẬP trước khi lưu.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";
import { HuongDan, PHAN_DIEN } from "./huong-dan-dien-mang";

type KetQua = { ok?: boolean; tom_tat?: string; error?: string };

export function DienNhaCard() {
  const config = useSettingsStore((s) => s.config);
  const cu = String(((config as any)?.dien_nha || {}).nut || "");
  return <DienNhaForm key={cu} cu={cu} />;
}

function DienNhaForm({ cu }: { cu: string }) {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const [nut, setNut] = useState(cu);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [kq, setKq] = useState<KetQua | null>(null);

  const luu = async () => {
    await saveConfig({ ...config, dien_nha: { ...((config as any)?.dien_nha || {}), nut: nut.trim() } } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const thu = async () => {
    setBusy(true); setKq(null);
    try {
      setKq((await request.post("/api/dien-nha/thu", { nut: nut.trim() })).data as KetQua);
    } catch (e: any) {
      setKq({ ok: false, error: e?.message || "Không gọi được máy chủ" });
    } finally { setBusy(false); }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">🔋 Điện nhà — UPS (NUT)</CardTitle>
        <CardDescription>
          c2a đọc UPS 5 giây một lần và báo khi <b>mất điện</b>, khi <b>có điện lại</b>, và khi <b>pin yếu sắp tắt
          máy chủ</b>. Tin đi theo dòng «Mất điện / có điện» ở <b>Cài đặt → Thông báo</b> — bật dòng đó và chọn kênh
          nhận. Không đọc được UPS quá 3 phút thì báo vào «Lỗi & cảnh báo hệ thống».
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">Địa chỉ NUT — dạng <code>tên-ups@máy</code> (cổng mặc định 3493)</p>
          <Input placeholder="prolink@172.16.10.100" value={nut} onChange={(e) => setNut(e.target.value)} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void luu()}>{saved ? "Đã lưu!" : "Lưu"}</Button>
          <Button variant="outline" onClick={() => void thu()} disabled={busy}>
            {busy ? "Đang thử…" : "Kiểm tra kết nối"}
          </Button>
        </div>
        {kq ? <p className="text-xs">{kq.ok ? "✅" : "❌"} {kq.ok ? kq.tom_tat : kq.error}</p> : null}

        <div className="space-y-2">
          <p className="text-sm font-medium">📖 Hướng dẫn dựng đủ các phần (lệnh chép từ máy chủ đang chạy)</p>
          <HuongDan phan={PHAN_DIEN} />
        </div>
      </CardContent>
    </Card>
  );
}
