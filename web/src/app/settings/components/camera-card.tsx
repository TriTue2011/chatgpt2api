"use client";

/**
 * CameraCard — camera nhà, KHÔNG đi qua Home Assistant.
 *
 * Nhiều người dùng bot không cài Home Assistant, nên camera khai thẳng vào cổng
 * theo hai đường: go2rtc (đã có sẵn máy chủ go2rtc thì chỉ trỏ tới và nêu tên
 * luồng) hoặc RTSP (trỏ thẳng vào camera, ffmpeg bóc một khung).
 *
 * Sổ camera và quyền lưu trong config (`cameras`, `camera_quyen`) nên card này
 * dùng saveConfig như mọi card khác. Chỉ hai việc phải hỏi máy chủ: danh sách
 * người có thể tích, và chụp thử.
 */

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

type Cam = {
  kind: "go2rtc" | "rtsp";
  base?: string; src?: string; url?: string;
  username?: string; password?: string; note?: string;
};
type Nguoi = { key: string; kenh: string; ten: string };

const RONG: Cam = { kind: "go2rtc", base: "", src: "", url: "", username: "", password: "", note: "" };

export function CameraCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);

  const [cams, setCams] = useState<Record<string, Cam>>({});
  const [cheDo, setCheDo] = useState<"admin" | "danh_sach">("admin");
  const [choPhep, setChoPhep] = useState<string[]>([]);
  const [nguoi, setNguoi] = useState<Nguoi[]>([]);

  const [ten, setTen] = useState("");
  const [moi, setMoi] = useState<Cam>({ ...RONG });
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [xemTruoc, setXemTruoc] = useState("");

  useEffect(() => {
    const c = ((config as any)?.cameras as Record<string, Cam>) || {};
    setCams(c);
    const q = ((config as any)?.camera_quyen as any) || {};
    setCheDo(q.che_do === "danh_sach" ? "danh_sach" : "admin");
    setChoPhep(Array.isArray(q.cho_phep) ? q.cho_phep.map(String) : []);
  }, [(config as any)?.cameras, (config as any)?.camera_quyen]);

  useEffect(() => {
    request.get("/api/camera/nguoi-dung")
      .then((r) => setNguoi(((r.data as any)?.rows as Nguoi[]) || []))
      .catch(() => setNguoi([]));
  }, []);

  const luu = async (cam: Record<string, Cam>, che_do = cheDo, cho_phep = choPhep) => {
    await saveConfig({ ...config, cameras: cam, camera_quyen: { che_do, cho_phep } } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const them = async () => {
    const t = ten.trim();
    if (!t) { setMsg("❌ Chưa đặt tên cho camera."); return; }
    if (moi.kind === "go2rtc" && (!moi.base?.trim() || !moi.src?.trim())) {
      setMsg("❌ Camera go2rtc cần cả địa chỉ máy chủ và tên luồng."); return;
    }
    if (moi.kind === "rtsp" && !moi.url?.trim().toLowerCase().startsWith("rtsp://")) {
      setMsg("❌ Địa chỉ RTSP phải bắt đầu bằng rtsp://"); return;
    }
    const ban: Cam = moi.kind === "go2rtc"
      ? { kind: "go2rtc", base: moi.base!.trim().replace(/\/+$/, ""), src: moi.src!.trim(),
          username: moi.username?.trim() || "", password: moi.password || "", note: moi.note?.trim() || "" }
      : { kind: "rtsp", url: moi.url!.trim(), note: moi.note?.trim() || "" };
    const tiep = { ...cams, [t]: ban };
    setCams(tiep); setTen(""); setMoi({ ...RONG }); setMsg("");
    await luu(tiep);
  };

  const xoa = async (t: string) => {
    const tiep = { ...cams };
    delete tiep[t];
    setCams(tiep);
    await luu(tiep);
  };

  const thu = async (t: string) => {
    setBusy(t); setMsg("Đang chụp thử…"); setXemTruoc("");
    try {
      const r = await request.post("/api/camera/test", { ten: t });
      const d = r.data as { ok?: boolean; ten?: string; bytes?: number; anh?: string; error?: string };
      if (d.ok) {
        setMsg(`✅ ${d.ten} — lấy được khung ${Math.round((d.bytes || 0) / 1024)} KB`);
        setXemTruoc(d.anh || "");
      } else setMsg(`❌ ${d.error || "Chụp không được"}`);
    } catch (e) {
      setMsg(`❌ ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(""); }
  };

  const tick = (key: string) => {
    const tiep = choPhep.includes(key) ? choPhep.filter((k) => k !== key) : [...choPhep, key];
    setChoPhep(tiep);
    void luu(cams, cheDo, tiep);
  };

  const doiCheDo = (v: "admin" | "danh_sach") => {
    setCheDo(v);
    void luu(cams, v, choPhep);
  };

  const ds = Object.entries(cams);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Camera nhà</CardTitle>
        <CardDescription>
          Khai camera thẳng vào cổng qua go2rtc hoặc RTSP — không cần Home Assistant.
          Đặt tên tiếng Việt cho từng cái rồi hỏi bằng tên đó: «xem camera sân trước»,
          «ngoài cổng có ai không». Hỏi được từ Zalo, Telegram và trợ lý trong nhà.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* ── Danh sách camera đã khai ─────────────────────────────────── */}
        <div className="space-y-2">
          {ds.length === 0 && (
            <p className="text-xs text-muted-foreground">Chưa khai camera nào.</p>
          )}
          {ds.map(([t, c]) => (
            <div key={t} className="flex flex-wrap items-center gap-2 rounded border border-border/70 p-2">
              <span className="text-sm font-medium">📷 {t}</span>
              <span className="text-[11px] rounded bg-muted px-1.5 py-0.5">
                {c.kind === "go2rtc" ? "go2rtc" : "RTSP"}
              </span>
              <span className="text-xs text-muted-foreground truncate max-w-[22rem]">
                {c.kind === "go2rtc" ? `${c.base} · luồng ${c.src}` : c.url}
              </span>
              {c.note ? <span className="text-xs text-muted-foreground">— {c.note}</span> : null}
              <div className="ml-auto flex gap-1">
                <Button size="sm" variant="outline" disabled={busy === t} onClick={() => thu(t)}>
                  {busy === t ? "…" : "Chụp thử"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => xoa(t)}>Xoá</Button>
              </div>
            </div>
          ))}
        </div>

        {xemTruoc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={xemTruoc} alt="Ảnh chụp thử" className="max-h-64 rounded border border-border/70" />
        ) : null}

        {/* ── Thêm camera ──────────────────────────────────────────────── */}
        <div className="rounded border border-dashed border-border/70 p-3 space-y-2">
          <p className="text-sm font-medium">Thêm camera</p>
          <div className="flex flex-wrap gap-2">
            <Input className="w-48" value={ten} onChange={(e) => setTen(e.target.value)}
              placeholder="Tên gọi, vd: Sân trước" />
            <select className="h-9 rounded border border-input bg-background px-2 text-sm"
              value={moi.kind}
              onChange={(e) => setMoi({ ...moi, kind: e.target.value as Cam["kind"] })}>
              <option value="go2rtc">go2rtc</option>
              <option value="rtsp">RTSP</option>
            </select>
          </div>

          {moi.kind === "go2rtc" ? (
            <>
              <div className="flex flex-wrap gap-2">
                <Input className="w-64" value={moi.base || ""}
                  onChange={(e) => setMoi({ ...moi, base: e.target.value })}
                  placeholder="http://192.168.1.10:1984" />
                <Input className="w-40" value={moi.src || ""}
                  onChange={(e) => setMoi({ ...moi, src: e.target.value })}
                  placeholder="tên luồng (src)" />
              </div>
              <div className="flex flex-wrap gap-2">
                <Input className="w-40" value={moi.username || ""}
                  onChange={(e) => setMoi({ ...moi, username: e.target.value })}
                  placeholder="tài khoản (nếu có)" />
                <Input className="w-40" type="password" value={moi.password || ""}
                  onChange={(e) => setMoi({ ...moi, password: e.target.value })}
                  placeholder="mật khẩu (nếu có)" />
              </div>
              <p className="text-xs text-muted-foreground">
                Cổng mặc định của go2rtc là 1984. Tên luồng là tên bạn đặt trong mục
                <code className="mx-1">streams</code> của go2rtc. Đường này nhanh hơn RTSP
                vì go2rtc giữ sẵn kết nối tới camera.
              </p>
            </>
          ) : (
            <>
              <Input value={moi.url || ""}
                onChange={(e) => setMoi({ ...moi, url: e.target.value })}
                placeholder="rtsp://admin:matkhau@192.168.1.20:554/stream1" />
              <p className="text-xs text-muted-foreground">
                Trỏ thẳng vào luồng RTSP của camera. Nên dùng <b>luồng phụ</b> (thường có
                đuôi <code>-sub</code> hoặc stream2): ảnh nhỏ vừa đủ cho AI đọc, mà rẻ hơn
                luồng chính khoảng hai mươi lần.
              </p>
            </>
          )}

          <Input value={moi.note || ""} onChange={(e) => setMoi({ ...moi, note: e.target.value })}
            placeholder="Ghi chú — cũng dùng để nhận tên, vd: cổng ngoài, chỗ để xe" />
          <Button size="sm" onClick={them}>Thêm camera</Button>
        </div>

        {/* ── Ai được xem ──────────────────────────────────────────────── */}
        <div className="rounded border border-dashed border-border/70 p-3 space-y-2">
          <p className="text-sm font-medium">🔐 Ai được xem camera</p>
          <label className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
            <input type="radio" className="size-3.5" checked={cheDo === "admin"}
              onChange={() => doiCheDo("admin")} />
            Chỉ mình tôi (admin)
          </label>
          <label className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
            <input type="radio" className="size-3.5" checked={cheDo === "danh_sach"}
              onChange={() => doiCheDo("danh_sach")} />
            Admin và những người tôi tích bên dưới
          </label>

          {cheDo === "danh_sach" && (
            <div className="space-y-1 pt-1">
              {nguoi.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  Chưa có ai trong danh bạ. Người nào nhắn cho bot và được bạn duyệt sẽ
                  hiện ở đây.
                </p>
              )}
              {nguoi.map((n) => (
                <label key={n.key}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
                  <input type="checkbox" className="size-3.5"
                    checked={choPhep.includes(n.key)} onChange={() => tick(n.key)} />
                  <span className="rounded bg-muted px-1">{n.kenh}</span>
                  {n.ten}
                </label>
              ))}
              <p className="text-[11px] text-muted-foreground pt-1">
                Chỉ liệt kê hội thoại 1-1. Nhóm chat không mở được camera: mỗi người trong
                nhóm là một phiên riêng, mà mở camera nhà cho cả nhóm cũng không nên.
              </p>
            </div>
          )}
          {cheDo === "danh_sach" && choPhep.length === 0 && (
            <p className="text-xs text-amber-600">
              ⚠️ Chưa tích ai — hiện vẫn chỉ mình bạn xem được.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => luu(cams)}>{saved ? "Đã lưu!" : "Lưu"}</Button>
          <span className="text-xs text-muted-foreground">
            Camera phải Lưu xong mới chụp thử được.
          </span>
        </div>
        {msg ? <p className="text-xs text-muted-foreground">{msg}</p> : null}
      </CardContent>
    </Card>
  );
}
