"use client";

/**
 * Thẻ "Mạng nhà" — tài khoản router MikroTik (API-SSL) và AdGuard Home.
 *
 * Chủ máy 03/10/2026: "Sau này cài đặt trên webui". Router: tài khoản riêng
 * `c2a` nhóm read,write,api, chỉ đăng nhập được từ máy chủ c2a. Cùng lối bí
 * mật với tuya-card.tsx: máy chủ trả nhãn che thay giá trị thật, nên ô mật khẩu
 * trống khi đã lưu — gõ mới mới ghi đè, để trống là giữ nguyên.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

type Router = { host?: string; port?: string | number; username?: string; password?: unknown };
type AdGuard = { url?: string; username?: string; password?: unknown };
type KetQua = { ok?: boolean; tom_tat?: string; error?: string };

const chuoi = (v: unknown) => (typeof v === "string" ? v : "");
const daLuu = (v: unknown) => typeof v === "object" && v !== null && (v as { is_set?: boolean }).is_set === true;

export function MangNhaCard() {
  const config = useSettingsStore((s) => s.config);
  const rCu = (((config as any)?.mang_nha || {}).router || {}) as Router;
  const aCu = ((config as any)?.adguard || {}) as AdGuard;
  // Đổi khoá khi cấu hình đã lưu đổi → dựng lại form với giá trị mới, khỏi đặt state trong effect.
  const khoa = [rCu.host, rCu.port, rCu.username, aCu.url, aCu.username].map(String).join("|");
  return <MangNhaForm key={khoa} rCu={rCu} aCu={aCu} />;
}

function MangNhaForm({ rCu, aCu }: { rCu: Router; aCu: AdGuard }) {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);

  const [r, setR] = useState({
    host: chuoi(rCu.host), port: String(rCu.port || "8729"), username: chuoi(rCu.username), password: "",
  });
  const [a, setA] = useState({ url: chuoi(aCu.url), username: chuoi(aCu.username), password: "" });
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [kq, setKq] = useState<{ router?: KetQua; adguard?: KetQua } | null>(null);

  // Chỉ gửi mật khẩu khi người dùng GÕ MỚI — để trống nghĩa là giữ cái đã lưu.
  const goiRouter = () => ({
    host: r.host.trim(), port: Number(r.port) || 8729, ssl: true, username: r.username.trim(),
    ...(r.password.trim() ? { password: r.password.trim() } : {}),
  });
  const goiAdguard = () => ({
    url: a.url.trim().replace(/\/+$/, ""), username: a.username.trim(),
    ...(a.password.trim() ? { password: a.password.trim() } : {}),
  });

  const luu = async () => {
    const mn = (config as any)?.mang_nha || {};
    await saveConfig({
      ...config,
      mang_nha: { ...mn, router: { ...(mn.router || {}), ...goiRouter() } },
      adguard: { ...((config as any)?.adguard || {}), ...goiAdguard() },
    } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const thu = async () => {
    setBusy(true); setKq(null);
    try {
      const res = await request.post("/api/mang-nha/thu", { router: goiRouter(), adguard: goiAdguard() });
      setKq(res.data as { router?: KetQua; adguard?: KetQua });
    } catch (e: any) {
      setKq({ router: { ok: false, error: e?.message || "Không gọi được máy chủ" } });
    } finally { setBusy(false); }
  };

  const dong = (ten: string, k?: KetQua) =>
    k ? <p className="text-xs">{k.ok ? "✅" : "❌"} {ten}: {k.ok ? k.tom_tat : k.error}</p> : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">🌐 Mạng nhà — router MikroTik & AdGuard</CardTitle>
        <CardDescription>
          Bot dùng tài khoản router để chặn / mở mạng từng máy, giới hạn tốc độ, duyệt máy mới và bật tắt VPN;
          tài khoản AdGuard để chặn trang web theo máy. Router cần mở cổng <b>api-ssl (8729)</b> cho máy chủ c2a.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Router — địa chỉ</p>
            <Input placeholder="172.16.10.1" value={r.host} onChange={(e) => setR({ ...r, host: e.target.value })} />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Cổng API-SSL</p>
            <Input placeholder="8729" value={r.port} onChange={(e) => setR({ ...r, port: e.target.value })} />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Tài khoản router</p>
            <Input placeholder="c2a" value={r.username} onChange={(e) => setR({ ...r, username: e.target.value })} />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              Mật khẩu router {daLuu(rCu.password) ? <span className="text-green-600">· đã lưu</span> : null}
            </p>
            <Input type="password" placeholder={daLuu(rCu.password) ? "để trống nếu không đổi" : "…"}
              value={r.password} onChange={(e) => setR({ ...r, password: e.target.value })} />
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-3">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">AdGuard — URL</p>
            <Input placeholder="http://172.16.10.10:3000" value={a.url}
              onChange={(e) => setA({ ...a, url: e.target.value })} />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Tài khoản AdGuard</p>
            <Input value={a.username} onChange={(e) => setA({ ...a, username: e.target.value })} />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              Mật khẩu AdGuard {daLuu(aCu.password) ? <span className="text-green-600">· đã lưu</span> : null}
            </p>
            <Input type="password" placeholder={daLuu(aCu.password) ? "để trống nếu không đổi" : "…"}
              value={a.password} onChange={(e) => setA({ ...a, password: e.target.value })} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void luu()}>{saved ? "Đã lưu!" : "Lưu"}</Button>
          <Button variant="outline" onClick={() => void thu()} disabled={busy}>
            {busy ? "Đang thử…" : "Kiểm tra kết nối"}
          </Button>
        </div>
        {kq ? <div className="space-y-1">{dong("Router", kq.router)}{dong("AdGuard", kq.adguard)}</div> : null}
      </CardContent>
    </Card>
  );
}
