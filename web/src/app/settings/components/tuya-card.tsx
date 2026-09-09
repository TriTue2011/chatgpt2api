"use client";

/**
 * Thẻ cài đặt Tuya / Smart Life.
 *
 * Thiết bị Tuya (khoá cửa, ổ cắm…) chỉ nói chuyện với máy chủ của Tuya, không
 * phát gì ra mạng nội bộ — đã đo: nghe quảng bá UDP 6666/6667 trên đúng mạng
 * nhà 30 giây, không thiết bị nào. Nên phải đi qua OpenAPI của Tuya.
 *
 * BÍ MẬT: Access ID và Secret cộng lại là điều khiển được thiết bị từ xa (nhà
 * này có khoá cửa). Máy chủ trả về nhãn che thay vì giá trị thật, nên ô nhập
 * hiện trống khi đã lưu — gõ mới thì mới ghi đè, để trống thì giữ nguyên.
 */

import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

type Tuya = {
  bat?: boolean;
  access_id?: string;
  access_secret?: string;
  endpoint?: string;
};

type ThietBi = {
  id: string;
  ten: string;
  loai: string;
  model?: string;
  online?: boolean | null;
};

const VUNG = [
  { ma: "america", ten: "America (openapi.tuyaus.com)" },
  { ma: "china", ten: "China (openapi.tuyacn.com)" },
  { ma: "europe", ten: "Europe (openapi.tuyaeu.com)" },
  { ma: "india", ten: "India (openapi.tuyain.com)" },
];

const RONG: Tuya = { bat: true, access_id: "", access_secret: "", endpoint: "america" };

export function TuyaCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);

  const [t, setT] = useState<Tuya>({ ...RONG });
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [ds, setDs] = useState<ThietBi[]>([]);

  // false = thu. Prerender và client render đầu tiên phải giống nhau → không
  // đọc localStorage trong initializer.
  const [mo, setMo] = useState(false);
  useEffect(() => {
    try { setMo(localStorage.getItem("tuya.ds") === "1"); } catch { /* bị chặn */ }
  }, []);
  const doiMo = () =>
    setMo((v) => {
      try { localStorage.setItem("tuya.ds", v ? "0" : "1"); } catch { /* bỏ qua */ }
      return !v;
    });

  useEffect(() => {
    const c = ((config as any)?.tuya as Tuya) || {};
    setT({
      ...RONG,
      bat: c.bat !== false,
      endpoint: String(c.endpoint || "america"),
      // Máy chủ trả nhãn che (object) chứ không phải chuỗi → để trống ô nhập.
      access_id: typeof c.access_id === "string" ? c.access_id : "",
      access_secret: typeof c.access_secret === "string" ? c.access_secret : "",
    });
  }, [(config as any)?.tuya]);

  const daCo = (k: "access_id" | "access_secret") => {
    const v = ((config as any)?.tuya || {})[k];
    return typeof v === "object" && v !== null && (v as any).is_set === true;
  };

  const luu = async () => {
    const goi: Record<string, unknown> = { bat: t.bat !== false, endpoint: t.endpoint };
    // Chỉ gửi khi người dùng GÕ MỚI — để trống nghĩa là giữ nguyên cái đã lưu.
    if ((t.access_id || "").trim()) goi.access_id = (t.access_id || "").trim();
    if ((t.access_secret || "").trim()) goi.access_secret = (t.access_secret || "").trim();
    await saveConfig({ ...config, tuya: { ...((config as any)?.tuya || {}), ...goi } } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const thu = async () => {
    setBusy("thu"); setMsg("");
    try {
      const r = await request.post("/api/tuya/test", {
        access_id: (t.access_id || "").trim(),
        access_secret: (t.access_secret || "").trim(),
        endpoint: t.endpoint,
      });
      const d = r.data as { ok?: boolean; error?: string; so_thiet_bi?: number; thiet_bi?: string[] };
      setMsg(d.ok
        ? `✅ Nối được — thấy ${d.so_thiet_bi} thiết bị: ${(d.thiet_bi || []).join(", ")}`
        : `❌ ${d.error || "Nối không được"}`);
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Nối không được"}`);
    } finally { setBusy(""); }
  };

  const napDs = async () => {
    setBusy("nap"); setMsg("");
    try {
      const r = await request.get("/api/tuya/thiet-bi");
      const d = r.data as { ok?: boolean; error?: string; thiet_bi?: ThietBi[] };
      if (!d.ok) { setMsg(`❌ ${d.error || "Không lấy được"}`); return; }
      setDs(d.thiet_bi || []);
      setMo(true);
      try { localStorage.setItem("tuya.ds", "1"); } catch { /* bỏ qua */ }
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Không lấy được"}`);
    } finally { setBusy(""); }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">🔗 Thiết bị Tuya / Smart Life</CardTitle>
        <CardDescription>
          Đường thứ ba, sau Home Assistant và MQTT. Dùng cho thiết bị chỉ nói chuyện
          với máy chủ Tuya — như khoá cửa thông minh, ổ cắm Tuya. Lấy Access ID và
          Secret ở <b>iot.tuya.com</b> → Cloud → dự án của anh/chị.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              Access ID {daCo("access_id") ? <span className="text-green-600">· đã lưu</span> : null}
            </p>
            <Input
              placeholder={daCo("access_id") ? "để trống nếu không đổi" : "cft3qwr8am94..."}
              value={t.access_id || ""}
              onChange={(e) => setT({ ...t, access_id: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              Access Secret {daCo("access_secret") ? <span className="text-green-600">· đã lưu</span> : null}
            </p>
            <Input
              type="password"
              placeholder={daCo("access_secret") ? "để trống nếu không đổi" : "…"}
              value={t.access_secret || ""}
              onChange={(e) => setT({ ...t, access_secret: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Vùng máy chủ</p>
            <select
              className="h-9 w-full rounded-md border border-border bg-transparent px-2 text-sm"
              value={t.endpoint || "america"}
              onChange={(e) => setT({ ...t, endpoint: e.target.value })}
            >
              {VUNG.map((v) => <option key={v.ma} value={v.ma}>{v.ten}</option>)}
            </select>
            <p className="text-xs text-muted-foreground">
              Chọn đúng vùng lúc <b>đăng ký tài khoản</b>, không phải nơi ở. Sai vùng
              là mọi lời gọi bị từ chối.
            </p>
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={t.bat !== false}
            onChange={(e) => setT({ ...t, bat: e.target.checked })}
          />
          Bật lớp Tuya
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void luu()}>{saved ? "Đã lưu!" : "Lưu"}</Button>
          <Button variant="outline" onClick={() => void thu()} disabled={busy === "thu"}>
            {busy === "thu" ? "Đang thử…" : "Kiểm tra kết nối"}
          </Button>
          <Button variant="outline" onClick={() => void napDs()} disabled={busy === "nap"}>
            {busy === "nap" ? "Đang lấy…" : "Lấy danh sách thiết bị"}
          </Button>
        </div>

        {msg ? <p className="text-xs text-muted-foreground">{msg}</p> : null}

        <div className="rounded-md border border-border">
          <button
            type="button"
            onClick={doiMo}
            aria-expanded={mo}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-semibold hover:bg-muted/40"
          >
            <span>🔗 Thiết bị Tuya ({ds.length})</span>
            {mo ? <ChevronUp className="size-3.5 shrink-0 text-muted-foreground" />
                : <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />}
          </button>
          {mo ? (
            <div className="border-t border-border">
              {ds.length ? ds.map((d) => (
                <div key={d.id} className="border-b border-border/60 px-3 py-2 text-xs last:border-0">
                  <span className="font-medium">{d.ten}</span>
                  <span className="text-muted-foreground"> · {d.loai}</span>
                  {d.model ? <span className="text-muted-foreground"> · {d.model}</span> : null}
                </div>
              )) : (
                <p className="px-3 py-2 text-xs text-muted-foreground">
                  Chưa có gì — bấm «Lấy danh sách thiết bị».
                </p>
              )}
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
