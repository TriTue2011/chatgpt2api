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

type KetQua = { ok?: boolean; tom_tat?: string; error?: string };

const CAI_NUT = `# Chạy trên MÁY CẮM CÁP USB CỦA UPS (nhà này: Proxmox .100), KHÔNG cài trong LXC:
# LXC không có udev nên sau mỗi lần mất điện cổng USB về root:root, driver không mở được UPS.
apt install -y nut-server nut-client
nut-scanner -U                     # tìm driver cho UPS cắm USB, chép khối in ra

# /etc/nut/nut.conf
MODE=standalone

# /etc/nut/ups.conf — dán khối nut-scanner in ra, đặt tên [prolink]
[prolink]
    driver = blazer_usb
    port = auto
    vendorid = 0665
    productid = 5161
    ignorelb                           # tự báo pin yếu theo ngưỡng dưới đây
    override.battery.charge.low = 15   # pin dưới 15% thì tắt máy chủ
    offdelay = 60                      # tắt xong ngắt nguồn UPS 60 s, có điện thì tự cấp lại

# /etc/nut/upsd.conf — mở cho c2a đọc qua mạng (chỉ đọc, không cần tài khoản)
LISTEN 0.0.0.0 3493

# /etc/nut/upsd.users
[upsmon]
    password = MAT_KHAU_TU_DAT
    upsmon primary

# /etc/nut/upsmon.conf
MONITOR prolink@localhost 1 upsmon MAT_KHAU_TU_DAT primary
SHUTDOWNCMD "/sbin/shutdown -h +0"
FINALDELAY 15                      # chờ 15 s cho c2a kịp gửi tin trước khi tắt

systemctl restart nut-driver.target nut-server nut-monitor   # Ubuntu 22.04: nut-driver thay nut-driver.target
upsc prolink@localhost ups.status  # phải ra OL (đang dùng điện lưới)`;

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

        <details className="rounded-md border p-3 text-sm">
          <summary className="cursor-pointer font-medium">📖 Hướng dẫn cài NUT để nối với c2a</summary>
          <div className="mt-3 space-y-3">
            <ol className="list-decimal space-y-1 pl-5 text-xs">
              <li>Cài NUT trên <b>máy cắm cáp USB của UPS</b> theo các lệnh dưới (máy Debian/Proxmox).</li>
              <li>Chạy <code>upsc prolink@localhost ups.status</code> trên máy đó — phải ra <code>OL</code>.</li>
              <li>Điền <code>prolink@IP-máy-đó</code> vào ô trên → <b>Kiểm tra kết nối</b> → <b>Lưu</b>.</li>
              <li>Vào <b>Cài đặt → Thông báo</b>, bật «Mất điện / có điện» và chọn kênh nhận.</li>
            </ol>
            <pre className="overflow-x-auto rounded bg-muted p-3 text-[11px] leading-relaxed">{CAI_NUT}</pre>
            <div className="space-y-1 text-xs text-muted-foreground">
              <p><b>Đã cài thêm ở nhà này (Proxmox .100), nếu dựng lại thì làm theo:</b></p>
              <ul className="list-disc space-y-1 pl-5">
                <li>Mất điện quá 60 giây thì tắt VM NVR cho đỡ hao pin; điện ổn định 5 phút thì bật lại —
                  <code>/etc/nut/upssched.conf</code> + <code>/usr/local/sbin/ups-may-khach</code>.</li>
                <li>Sau khi có điện, chờ điện lưới ổn định 5 phút liền mới bật máy khách (chống chập chờn) —
                  <code>cho-dien-on-dinh.service</code> chạy trước <code>pve-guests</code>.</li>
                <li>Thứ tự khởi động: router MikroTik (order 1) → AdGuard (order 2) → máy khác; hookscript
                  <code>local:snippets/cho-san-sang.sh</code> chờ router / DNS trả lời thật.</li>
                <li><b>Đừng đặt IP tĩnh</b> cho máy chủ hay AdGuard: router chỉ cho đi qua máy có lease DHCP.</li>
                <li>BIOS phải đặt <b>Restore on AC Power Loss = Power On</b> thì máy mới tự bật khi có điện.</li>
              </ul>
            </div>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}
