"use client";

/**
 * MqttCard — thiết bị nhà qua MQTT, KHÔNG cần Home Assistant.
 *
 * Đường THỨ HAI bên cạnh HACard: nhà có Home Assistant thì bot vẫn dùng đường
 * kia (biết cả phòng và khu vực); nhà không cài HA thì thiết bị vẫn nói chuyện
 * qua MQTT nên bot vẫn đọc và điều khiển được. Hai đường sống độc lập.
 *
 * Cấu hình máy chủ lưu trong config (`mqtt`) nên card dùng saveConfig như mọi
 * card khác. Việc phải hỏi máy chủ chỉ có ba: thử nối, quét thiết bị, gửi lệnh.
 *
 * Danh sách thiết bị MẶC ĐỊNH THU LẠI: nhà đông có thể ra vài chục mục, bung
 * sẵn thì đẩy phần cài đặt của card khác ra khỏi màn hình.
 */

import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

type MayChu = {
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  enabled?: boolean;
  note?: string;
  uu_tien?: boolean;
};

type ThongKe = { su_kien?: number; so_do?: number; tuoi?: number; mb?: number; chay?: boolean };
type Hong = { thiet_bi: string; truong: string; loai: string; chi_tiet: string };

type Muc = { ten: string; chu_de?: string; gia_tri?: string | null; loai?: string; don_vi?: string };
type ThietBi = {
  ten: string;
  nguon: "tu_khai_bao" | "frigate" | "tho";
  nhanh: string;
  doc: Muc[];
  dieu_khien: Muc[];
};

const RONG: MayChu = { host: "", port: 1883, username: "", password: "", enabled: true, note: "", uu_tien: false };

const NHAN_HONG: Record<string, string> = {
  chet: "chết hẳn",
  do: "đơ (vẫn báo nhưng số không đổi)",
  chap_chon: "chập chờn",
};

const NHAN_NGUON: Record<string, string> = {
  tu_khai_bao: "tự khai báo",
  frigate: "Frigate",
  tho: "chưa nhận ra",
};

export function MqttCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);

  const [may, setMay] = useState<MayChu>({ ...RONG });
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [ds, setDs] = useState<ThietBi[]>([]);
  const [tk, setTk] = useState<ThongKe | null>(null);
  const [hong, setHong] = useState<Hong[] | null>(null);

  // false = thu. Prerender (static export) và client render đầu tiên phải giống
  // nhau → không đọc localStorage trong initializer, đọc sau khi mount.
  const [mo, setMo] = useState(false);
  useEffect(() => {
    try { setMo(localStorage.getItem("mqtt.ds") === "1"); } catch { /* bị chặn → giữ thu */ }
  }, []);
  const doiMo = () =>
    setMo((v) => {
      try { localStorage.setItem("mqtt.ds", v ? "0" : "1"); } catch { /* bỏ qua */ }
      return !v;
    });

  useEffect(() => {
    const c = ((config as any)?.mqtt as MayChu) || {};
    setMay({ ...RONG, ...c });
  }, [(config as any)?.mqtt]);

  // Nạp danh sách đã có sẵn trong bộ nhớ máy chủ (không mở kết nối mới).
  const napDs = async () => {
    try {
      const r = await request.get("/api/mqtt/thiet-bi");
      const d = r.data as { ok?: boolean; thiet_bi?: ThietBi[] };
      if (d.ok) setDs(d.thiet_bi || []);
    } catch { /* chưa cấu hình thì thôi, không báo lỗi ồn ào */ }
  };
  useEffect(() => { void napDs(); }, []);

  const napTk = async () => {
    try {
      const r = await request.get("/api/mqtt/lich-su");
      const d = r.data as { ok?: boolean; thong_ke?: ThongKe };
      if (d.ok) setTk(d.thong_ke || null);
    } catch { /* chưa bật thì thôi */ }
  };
  useEffect(() => { void napTk(); }, []);

  // Nạp lịch sử HA sẵn có. HA chỉ giữ ~10 ngày rồi trôi mất, nên nạp sớm được
  // nhiều. Bấm lại nhiều lần không sao: máy chủ chặn ghi trùng.
  const napHa = async () => {
    setBusy("napha"); setMsg("Đang lấy lịch sử Home Assistant…");
    try {
      const r = await request.post("/api/mqtt/nap-ha", { so_ngay: 10 });
      const d = r.data as { ok?: boolean; error?: string; nap?: number; thuc_the?: number };
      setMsg(d.ok
        ? `✅ Nạp ${d.nap} bản ghi từ ${d.thuc_the} thực thể. Bấm lại lần nữa cũng không bị nhân đôi.`
        : `❌ ${d.error || "Nạp không được"}`);
      await napTk();
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Nạp không được"}`);
    } finally { setBusy(""); }
  };

  const soiHong = async () => {
    setBusy("soi"); setMsg("");
    try {
      const r = await request.get("/api/mqtt/soi-hong");
      const d = r.data as { ok?: boolean; error?: string; hong?: Hong[] };
      if (!d.ok) { setMsg(`❌ ${d.error || "Soi không được"}`); return; }
      setHong(d.hong || []);
      if (!(d.hong || []).length) setMsg("✅ Không thấy cảm biến nào có dấu hiệu hỏng.");
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Soi không được"}`);
    } finally { setBusy(""); }
  };

  const luu = async () => {
    if (!(may.host || "").trim()) { setMsg("❌ Chưa nhập địa chỉ máy chủ MQTT."); return; }
    await saveConfig({ ...config, mqtt: { ...may, host: (may.host || "").trim() } } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const thu = async () => {
    setBusy("thu"); setMsg("");
    try {
      const r = await request.post("/api/mqtt/test", {
        host: may.host, port: may.port, username: may.username, password: may.password,
      });
      const d = r.data as { ok?: boolean; error?: string; so_nhanh?: number; nhanh?: string[] };
      if (!d.ok) setMsg(`❌ ${d.error || "Nối không được"}`);
      else if (!d.so_nhanh)
        setMsg("⚠️ Nối được nhưng không nhận được tin nào trong 5 giây. Thường là tài khoản bị giới hạn quyền nghe, hoặc máy chủ đang trống.");
      else setMsg(`✅ Nối được — thấy ${d.so_nhanh} nhánh: ${(d.nhanh || []).join(", ")}`);
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Nối không được"}`);
    } finally { setBusy(""); }
  };

  const quet = async () => {
    setBusy("quet"); setMsg("Đang nghe máy chủ 20 giây…");
    try {
      const r = await request.post("/api/mqtt/quet", { giay: 20 });
      const d = r.data as { ok?: boolean; error?: string; so_thiet_bi?: number; so_chu_de?: number; nhanh?: string[] };
      if (!d.ok) { setMsg(`❌ ${d.error || "Quét không được"}`); return; }
      setMsg(`✅ Thấy ${d.so_thiet_bi} thiết bị, ${d.so_chu_de} chủ đề, ${(d.nhanh || []).length} nhánh (${(d.nhanh || []).join(", ")})`);
      await napDs();
      setMo(true);
      try { localStorage.setItem("mqtt.ds", "1"); } catch { /* bỏ qua */ }
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Quét không được"}`);
    } finally { setBusy(""); }
  };

  const batTat = async (ten: string, thuc_the: string, bat: boolean) => {
    setBusy(`${ten}/${thuc_the}`); setMsg("");
    try {
      const r = await request.post("/api/mqtt/dieu-khien", { ten, thuc_the, gia_tri: bat });
      const d = r.data as { ok?: boolean; error?: string };
      setMsg(d.ok ? `✅ Đã gửi lệnh ${bat ? "bật" : "tắt"} tới ${ten}.` : `❌ ${d.error}`);
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Gửi lệnh không được"}`);
    } finally { setBusy(""); }
  };

  const soDk = ds.reduce((n, d) => n + d.dieu_khien.length, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">📟 Thiết bị qua MQTT</CardTitle>
        <CardDescription>
          Đường thứ hai để bot biết nhà — <b>không cần Home Assistant</b>. Khai máy
          chủ MQTT là cổng tự dò ra có những thiết bị gì, đọc trạng thái và điều
          khiển được. Có Home Assistant thì hai đường chạy song song, không đụng nhau.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* ── Máy chủ ──────────────────────────────────────────────────── */}
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Địa chỉ máy chủ</p>
            <Input
              placeholder="172.16.10.200"
              value={may.host || ""}
              onChange={(e) => setMay({ ...may, host: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Cổng (thường là 1883)</p>
            <Input
              type="number"
              placeholder="1883"
              value={may.port ?? 1883}
              onChange={(e) => setMay({ ...may, port: Number(e.target.value) || 1883 })}
            />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Tài khoản (bỏ trống nếu không cần)</p>
            <Input
              value={may.username || ""}
              onChange={(e) => setMay({ ...may, username: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Mật khẩu</p>
            <Input
              type="password"
              placeholder="để nguyên *** nếu không đổi"
              value={may.password || ""}
              onChange={(e) => setMay({ ...may, password: e.target.value })}
            />
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={may.enabled !== false}
            onChange={(e) => setMay({ ...may, enabled: e.target.checked })}
          />
          Bật lớp MQTT (tắt thì cổng không nối tới máy chủ nữa)
        </label>

        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={may.uu_tien === true}
            onChange={(e) => setMay({ ...may, uu_tien: e.target.checked })}
          />
          <span>
            Ưu tiên MQTT khi ra lệnh
            <span className="block text-xs text-muted-foreground">
              Thiết bị có ở cả hai nơi thì đi thẳng MQTT cho nhanh. Tên không khớp
              rõ ràng thì vẫn quay về Home Assistant như cũ, nên bật lên không mất gì.
            </span>
          </span>
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void luu()}>{saved ? "Đã lưu!" : "Lưu"}</Button>
          <Button variant="outline" onClick={() => void thu()} disabled={busy === "thu"}>
            {busy === "thu" ? "Đang thử…" : "Kiểm tra kết nối"}
          </Button>
          <Button variant="outline" onClick={() => void quet()} disabled={busy === "quet"}>
            {busy === "quet" ? "Đang quét…" : "Quét thiết bị"}
          </Button>
          <span className="text-xs text-muted-foreground">Lưu xong mới quét được.</span>
        </div>

        {msg ? <p className="text-xs text-muted-foreground">{msg}</p> : null}

        {/* ── Lịch sử nhà ──────────────────────────────────────────────── */}
        <div className="rounded-md border border-border p-3 space-y-2">
          <p className="text-xs font-semibold">🗂️ Lịch sử nhà (c2a tự lưu)</p>
          <p className="text-xs text-muted-foreground">
            Ghi lại nhà có gì thay đổi để sau này bot học được nếp sinh hoạt. Lưu
            ở đây chứ không phải trên Home Assistant, nên tắt Home Assistant cũng
            không mất.
          </p>
          {tk ? (
            <p className="text-xs text-muted-foreground">
              {tk.su_kien ?? 0} sự kiện · {tk.so_do ?? 0} số đo · {tk.tuoi ?? 0} thiết bị
              {" "}· {tk.mb ?? 0} MB{tk.chay === false ? " · chưa chạy" : ""}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => void napHa()} disabled={busy === "napha"}>
              {busy === "napha" ? "Đang nạp…" : "Nạp lịch sử Home Assistant"}
            </Button>
            <Button variant="outline" size="sm" onClick={() => void soiHong()} disabled={busy === "soi"}>
              {busy === "soi" ? "Đang soi…" : "Soi thiết bị hỏng"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Home Assistant chỉ giữ khoảng 10 ngày rồi xoá dần, nạp sớm thì được nhiều.
          </p>

          {hong && hong.length ? (
            <div className="space-y-1 pt-1">
              <p className="text-xs font-semibold text-amber-600 dark:text-amber-500">
                ⚠️ {hong.length} thiết bị có dấu hiệu hỏng
              </p>
              <div className="max-h-48 overflow-y-auto rounded border border-border">
                {hong.slice(0, 40).map((h, i) => (
                  <div key={`${h.thiet_bi}/${h.truong}/${i}`}
                       className="border-b border-border/60 px-2 py-1 text-xs last:border-0">
                    <span className="font-medium">{h.thiet_bi}</span>
                    <span className="text-muted-foreground"> · {h.truong} · </span>
                    <span className="text-amber-600 dark:text-amber-500">
                      {NHAN_HONG[h.loai] || h.loai}
                    </span>
                    <span className="block text-muted-foreground">{h.chi_tiet}</span>
                  </div>
                ))}
              </div>
              {hong.length > 40 ? (
                <p className="text-xs text-muted-foreground">…và {hong.length - 40} cái nữa.</p>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* ── Danh sách thiết bị — MẶC ĐỊNH THU ────────────────────────── */}
        <div className="rounded-md border border-border">
          <button
            type="button"
            onClick={doiMo}
            aria-expanded={mo}
            title={mo ? "Thu gọn" : "Mở"}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-semibold hover:bg-muted/40"
          >
            <span>
              📋 Thiết bị đã tìm thấy ({ds.length})
              {soDk ? <span className="ml-1 font-normal text-muted-foreground">· {soDk} thứ điều khiển được</span> : null}
            </span>
            {mo ? <ChevronUp className="size-3.5 shrink-0 text-muted-foreground" />
                : <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />}
          </button>

          {mo ? (
            <div className="space-y-2 px-3 pb-3">
              {ds.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Chưa thấy thiết bị nào. Khai máy chủ ở trên rồi bấm <b>Quét thiết bị</b>.
                </p>
              ) : (
                ds.map((d) => (
                  <div key={`${d.nhanh}/${d.ten}`} className="rounded border border-border/70 p-2 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{d.ten}</span>
                      <span className="text-[11px] text-muted-foreground">
                        {NHAN_NGUON[d.nguon] || d.nguon} · {d.nhanh}
                      </span>
                    </div>

                    {d.dieu_khien.length > 0 ? (
                      <div className="flex flex-wrap items-center gap-1">
                        {d.dieu_khien.map((m) => (
                          <span key={m.ten} className="flex items-center gap-1 rounded bg-muted/50 px-1.5 py-0.5">
                            <span className="text-[11px]">{m.ten}</span>
                            <button
                              type="button"
                              className="rounded border border-input px-1 text-[10px] hover:bg-background"
                              disabled={busy === `${d.ten}/${m.ten}`}
                              onClick={() => void batTat(d.ten, m.ten, true)}
                            >bật</button>
                            <button
                              type="button"
                              className="rounded border border-input px-1 text-[10px] hover:bg-background"
                              disabled={busy === `${d.ten}/${m.ten}`}
                              onClick={() => void batTat(d.ten, m.ten, false)}
                            >tắt</button>
                          </span>
                        ))}
                      </div>
                    ) : null}

                    {d.doc.length > 0 ? (
                      <p className="text-[11px] text-muted-foreground">
                        Đọc được: {d.doc.slice(0, 8).map((m) =>
                          `${m.ten}${m.gia_tri != null ? ` = ${m.gia_tri}` : ""}`).join(" · ")}
                        {d.doc.length > 8 ? ` … và ${d.doc.length - 8} nữa` : ""}
                      </p>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          ) : null}
        </div>

        <div className="rounded border border-dashed border-border/70 p-3 space-y-1">
          <p className="text-sm font-medium">🔐 Ai được điều khiển</p>
          <p className="text-xs text-muted-foreground">
            Dùng chung ô tích với Home Assistant: <b>Kênh chat</b> → tab{" "}
            <b>🎚️ Lọc thread</b> → tích nhóm nhà thông minh. Hội thoại nào bật được
            đèn qua Home Assistant thì cũng điều khiển được qua MQTT — không phải
            tích thêm chỗ nào.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
