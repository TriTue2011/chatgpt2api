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
import { CollapsibleSection } from "@/components/collapsible-section";
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
type CanhBao = { bat?: boolean; gio_hang_ngay?: number };
type TrangThaiCB = { dang_hong?: number; dang_im?: number };
type Hong = { thiet_bi: string; truong: string; loai: string; chi_tiet: string };
type TinhHuong = {
  id: number; ten: string; trang_thai: string; gio: string;
  lech_phut: number; so_lan: number; diem: number;
  loi_cot: string[]; kem_theo: string[];
};

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
  // Danh sách kênh THẬT — cùng nguồn với «Gửi tóm tắt tới kênh» của email/lịch
  // (`email-calendar-card.tsx`). Ô chọn "telegram | zalo" là không đủ: nhà có
  // nhiều tài khoản Zalo và nhiều nhóm, chọn mỗi "zalo" thì không biết Zalo nào.
  // `thread_filterS` — SỐ NHIỀU. Gõ số ít thì rỗng và danh sách kênh trống
  // trơn, đúng lỗi chủ máy gặp 10/09/2026. Xem `email-calendar-card.tsx:71`.
  // Danh sách kênh nhận đã dời sang `notifications-card.tsx` — thẻ này không
  // còn chọn nơi nhận cho bất kỳ thông báo nào.
  const saveConfig = useSettingsStore((s) => s.saveConfig);

  const [may, setMay] = useState<MayChu>({ ...RONG });
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [ds, setDs] = useState<ThietBi[]>([]);
  const [tk, setTk] = useState<ThongKe | null>(null);
  const [hong, setHong] = useState<Hong[] | null>(null);
  const [cb, setCb] = useState<CanhBao>({ bat: true, gio_hang_ngay: 8 });
  // Học từ lỗi: bot hỏi lại khi nó KHÔNG CHẮC, sai một lần thì lần sau tự tránh.
  const [bh, setBh] = useState<{
    bat: boolean; du_mau: number; han_ngay: number;
    bao: boolean; bao_moi_ngay: number; dung_ai: boolean;
  }>({ bat: true, du_mau: 4, han_ngay: 180, bao: false,
       bao_moi_ngay: 7, dung_ai: true });
  // Học thói quen theo BỐI CẢNH: không chỉ "mấy giờ hay bật đèn" mà "lúc đó
  // trời tối chưa, có ai ở nhà không, mùa nào".
  const [dd, setDd] = useState<{ bat: boolean; so_ngay: number }>({
    bat: true, so_ngay: 30,
  });
  // Model cho phần học hỏi. Rỗng = theo định tuyến chung của bot.
  const [modelHoc, setModelHoc] = useState("");
  const [dsModel, setDsModel] = useState<string[]>([]);
  const [ttCb, setTtCb] = useState<TrangThaiCB | null>(null);
  const [th, setTh] = useState<TinhHuong[]>([]);

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
    const q = ((config as any)?.mqtt?.canh_bao as any) || {};
    setCb({
      bat: q.bat !== false,
      gio_hang_ngay: typeof q.gio_hang_ngay === "number" ? q.gio_hang_ngay : 8,
    });
    const h = ((config as any)?.mqtt?.bai_hoc as any) || {};
    setBh({
      bat: h.bat !== false,
      du_mau: typeof h.du_mau === "number" ? h.du_mau : 4,
      han_ngay: typeof h.han_ngay === "number" ? h.han_ngay : 180,
      bao: h.bao === true,
      bao_moi_ngay: typeof h.bao_moi_ngay === "number" ? h.bao_moi_ngay : 7,
      dung_ai: h.dung_ai !== false,
    });
    setModelHoc(String(h.model || ""));
    const d = ((config as any)?.mqtt?.du_doan as any) || {};
    setDd({
      bat: d.bat !== false,
      so_ngay: typeof d.so_ngay === "number" ? d.so_ngay : 30,
    });
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

  const napCb = async () => {
    try {
      const r = await request.get("/api/mqtt/canh-bao");
      const d = r.data as { ok?: boolean; trang_thai?: TrangThaiCB };
      if (d.ok) setTtCb(d.trang_thai || null);
    } catch { /* chưa bật thì thôi */ }
  };
  useEffect(() => { void napCb(); }, []);

  const napTh = async () => {
    try {
      const r = await request.get("/api/mqtt/tinh-huong");
      const d = r.data as { ok?: boolean; danh_sach?: TinhHuong[] };
      if (d.ok) setTh(d.danh_sach || []);
    } catch { /* chưa học được gì thì thôi */ }
  };
  useEffect(() => { void napTh(); }, []);

  // Danh sách model THẬT của gateway, cùng nguồn với thẻ Giáo viên
  // (`teacher-settings-card.tsx`): `/v1/models` trả kiểu OpenAI `{data:[{id}]}`.
  // Gõ tay thì sai một ký tự là hỏng lặng lẽ, nên cho chọn trong danh sách.
  useEffect(() => {
    void (async () => {
      try {
        const r = await request.get("/v1/models");
        const raw = (r as { data?: any })?.data;
        let ids: string[] = [];
        if (Array.isArray(raw?.data)) {
          ids = raw.data.map((m: { id?: string }) => String(m?.id || "")).filter(Boolean);
        } else if (Array.isArray(raw)) {
          ids = raw.map((m: unknown) =>
            typeof m === "string" ? m : String((m as { id?: string })?.id || ""),
          ).filter(Boolean);
        }
        setDsModel(Array.from(new Set(ids)).sort((a, b) => a.localeCompare(b)));
      } catch { /* chưa cấu hình provider thì thôi, vẫn gõ tay được */ }
    })();
  }, []);

  const duyetTh = async (id: number, bo = false) => {
    setBusy(`th${id}`);
    try {
      await request.post("/api/mqtt/tinh-huong/duyet", { id, bo });
      await napTh();
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Không lưu được"}`);
    } finally { setBusy(""); }
  };

  const doiTenTh = async (id: number, cu: string) => {
    const ten = window.prompt("Đặt lại tên tình huống:", cu);
    if (!ten || ten === cu) return;
    setBusy(`th${id}`);
    try {
      await request.post("/api/mqtt/tinh-huong/duyet", { id, ten });
      await napTh();
    } catch (e: any) {
      setMsg(`❌ ${e?.message || "Không lưu được"}`);
    } finally { setBusy(""); }
  };

  // Lưu riêng khối cảnh báo — không đụng phần máy chủ ở trên.
  const luuCb = async () => {
    await saveConfig({
      ...config,
      mqtt: {
        ...((config as any)?.mqtt || {}),
        canh_bao: {
          // Giữ nguyên mọi khoá khác của mục này. Thẻ này chỉ còn sở hữu Bật
          // và Giờ báo hằng ngày; phần nơi-nhận thuộc về Cài đặt → Thông báo,
          // dựng lại nguyên khối ở đây là xoá mất phần của trang kia (bẫy #9).
          ...(((config as any)?.mqtt?.canh_bao as any) || {}),
          bat: cb.bat !== false,
          gio_hang_ngay: cb.gio_hang_ngay ?? 8,
        },
        bai_hoc: {
          bat: bh.bat !== false,
          du_mau: bh.du_mau ?? 4,
          han_ngay: bh.han_ngay ?? 180,
          bao: bh.bao === true,
          bao_moi_ngay: bh.bao_moi_ngay ?? 7,
          dung_ai: bh.dung_ai !== false,
          model: (modelHoc || "").trim(),
        },
        du_doan: {
          // Giữ nguyên các khoá khác (vd `kenh_nhan` riêng của tầng này —
          // `du_doan_nha._kenh_nhan()` đọc trước `bai_hoc.kenh_nhan`). Bản cũ
          // dựng lại nguyên khối chỉ với hai khoá này nên lưu công tắc là mất
          // `du_doan.kenh_nhan` nếu tab Học hỏi đã đặt nó.
          ...(((config as any)?.mqtt?.du_doan as any) || {}),
          bat: dd.bat !== false,
          so_ngay: dd.so_ngay ?? 30,
        },
      },
    } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
    await napCb();
  };

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

        {/* ── Lịch sử nhà — THU GỌN, đây là phần dài nhất của thẻ ───────── */}
        <CollapsibleSection title="🗂️ Lịch sử nhà & phần bot tự học"
          className="rounded-md border border-border p-3">
        <div className="space-y-2">
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

          {/* ── Tình huống đã học ─────────────────────────────────────── */}
          {th.length ? (
            <CollapsibleSection title={<span className="text-xs">🕰️ Nếp sinh hoạt bot học được</span>}
              className="mt-2 rounded border border-border p-2">
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Nhận ra bằng <b>cảm biến có người</b>, không phải đèn nào bật — nên
                hôm nào ăn ở phòng khách thay vì bếp thì vẫn nhận ra.
              </p>
              <div className="max-h-64 overflow-y-auto rounded border border-border">
                {th.map((t) => (
                  <div key={t.id} className="border-b border-border/60 px-2 py-1.5 text-xs last:border-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{t.ten}</span>
                      <span className="text-muted-foreground">
                        khoảng {t.gio} ±{t.lech_phut}p · thấy {t.so_lan} lần
                      </span>
                      {t.trang_thai === "da_duyet" ? (
                        <span className="text-green-600">· đã ghi nhớ</span>
                      ) : t.trang_thai === "bo" ? (
                        <span className="text-muted-foreground">· đã bỏ</span>
                      ) : (
                        <span className="text-amber-600">· chờ duyệt</span>
                      )}
                    </div>
                    {t.trang_thai === "cho_duyet" ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Button variant="outline" size="sm"
                          onClick={() => void duyetTh(t.id)} disabled={busy === `th${t.id}`}>
                          Đúng rồi
                        </Button>
                        <Button variant="outline" size="sm"
                          onClick={() => void doiTenTh(t.id, t.ten)} disabled={busy === `th${t.id}`}>
                          Đổi tên
                        </Button>
                        <Button variant="outline" size="sm"
                          onClick={() => void duyetTh(t.id, true)} disabled={busy === `th${t.id}`}>
                          Bỏ qua
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
            </CollapsibleSection>
          ) : null}

          {/* ── Thông báo lỗi ─────────────────────────────────────────── */}
          <CollapsibleSection title={<span className="text-xs">🔔 Báo khi thiết bị hỏng</span>}
            className="mt-2 rounded border border-border p-2">
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs font-semibold">
              <input
                type="checkbox"
                checked={cb.bat !== false}
                onChange={(e) => setCb({ ...cb, bat: e.target.checked })}
              />
              Bật
            </label>
            <p className="text-xs text-muted-foreground">
              Báo lần đầu ngay, rồi thưa dần: sau 5 phút, 30 phút, 1 tiếng, 6 tiếng,
              rồi mỗi ngày một lần. Nhắn «tôi biết rồi» là thôi nhắc lỗi đó — nhưng
              sửa xong mà hỏng lại thì vẫn báo.
            </p>
            {/* Bộ chọn kênh và ô "Gửi cho ai" đã DỜI sang Cài đặt → Thông báo
                (13/09/2026). Chủ máy chốt gom mọi cài đặt thông báo về một chỗ
                và xoá ở tab cũ để khỏi xung đột — mà xung đột ở đây có thật:
                mọi thẻ Cài đặt đều POST nguyên cả config, nên thẻ nạp dữ liệu
                cũ ghi đè phần của thẻ khác (bẫy #9, từng mất
                `du_doan.kenh_nhan`). Giữ lại Bật và Giờ báo hằng ngày vì hai
                thứ đó không phải nơi-nhận. */}
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Giờ báo hằng ngày</p>
                <Input
                  type="number"
                  min={0}
                  max={23}
                  value={cb.gio_hang_ngay ?? 8}
                  onChange={(e) => setCb({ ...cb, gio_hang_ngay: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => void luuCb()}>
                {saved ? "Đã lưu!" : "Lưu cài đặt thông báo"}
              </Button>
              {ttCb ? (
                <span className="text-xs text-muted-foreground">
                  {ttCb.dang_hong ?? 0} lỗi đang theo dõi
                  {ttCb.dang_im ? ` · ${ttCb.dang_im} cái đã tắt nhắc` : ""}
                </span>
              ) : null}
            </div>
          </div>
          </CollapsibleSection>

          {/* ── Học thói quen theo bối cảnh ───────────────────────────── */}
          <CollapsibleSection title={<span className="text-xs">🏠 Học nếp nhà theo hoàn cảnh</span>}
            className="mt-2 rounded border border-border p-2">
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs font-semibold">
              <input
                type="checkbox"
                checked={dd.bat !== false}
                onChange={(e) => setDd({ ...dd, bat: e.target.checked })}
              />
              Bật
            </label>
            <p className="text-xs text-muted-foreground">
              Em không chỉ nhớ «7 giờ tối hay bật đèn bếp», mà nhớ cả hoàn cảnh
              lúc ấy: trời đã tối chưa, trong nhà nóng hay lạnh, có ai ở phòng
              nào, mùa nào trong năm, và anh vừa bật cái gì trước đó. Nhờ vậy em
              phân biệt được hôm mưa sập tối từ 5 giờ chiều với hôm nắng hè 7
              giờ vẫn sáng.
            </p>
            <p className="text-xs text-muted-foreground">
              Ban đầu em chỉ <b>hỏi ý anh</b> kèm hai nút «Ừ, bật đi / Không
              cần». Mỗi lần anh bấm là một lần em học. Thiết bị nào em đoán đúng{" "}
              <b>19 trên 20 lần</b> và đã được anh chấm đủ <b>50 lượt</b> thì em
              mới tự làm, làm xong mới báo. Sai 2 lần trong 10 lượt gần nhất là
              em tự quay về hỏi lại.
            </p>
            <p className="text-xs text-muted-foreground">
              Khoá cửa, bếp và bình nóng lạnh thì em <b>không bao giờ</b> tự
              động, dù đoán đúng bao nhiêu lần — những thứ đó bật nhầm không sửa
              lại được bằng một câu xin lỗi.
            </p>
            <label className="flex items-center gap-2 text-xs">
              Nhìn lại
              <Input
                type="number"
                className="h-7 w-20"
                value={dd.so_ngay}
                onChange={(e) =>
                  setDd({ ...dd, so_ngay: Number(e.target.value) || 30 })
                }
              />
              ngày gần đây để học
            </label>
            <p className="text-[11px] text-muted-foreground">
              Em nhắn gợi ý vào đúng những kênh anh chọn ở mục «Kể cho ai nghe»
              ngay bên dưới — chung một chỗ cài, khỏi phải đặt hai lần. Chưa
              chọn kênh nào thì em nhắn cho admin mặc định.
            </p>
          </div>
          </CollapsibleSection>

          {/* ── Học từ lỗi ────────────────────────────────────────────── */}
          <CollapsibleSection title={<span className="text-xs">🧠 Học từ lỗi</span>}
            className="mt-2 rounded border border-border p-2">
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs font-semibold">
              <input
                type="checkbox"
                checked={bh.bat !== false}
                onChange={(e) => setBh({ ...bh, bat: e.target.checked })}
              />
              Bật
            </label>
            <p className="text-xs text-muted-foreground">
              Có những câu em trả lời nhanh bằng cách đoán ý, không nghĩ kỹ — và
              đó là chỗ em hay sai. Những lúc như vậy em kèm hai nút «Đúng rồi /
              Chưa đúng». Anh bấm «Chưa đúng» một lần thôi, lần sau gặp câu hỏi
              tương tự em sẽ nghĩ kỹ thay vì đoán. Em hỏi đúng loại câu em chưa
              chắc, và loại nào anh xác nhận đúng đủ nhiều lần thì em thôi hỏi.
            </p>
            <label className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={bh.dung_ai !== false}
                onChange={(e) => setBh({ ...bh, dung_ai: e.target.checked })}
              />
              <span>
                🤖 Cho em nhờ AI hiểu ý câu hỏi
                <span className="block text-muted-foreground">
                  Không có AI thì em chỉ so được chữ: anh hỏi «vân tay số 2 mở
                  cửa hồi nào» là em không nhận ra nó cùng ý với câu anh từng
                  bảo em sai. Có AI thì em hiểu được ý, dù anh nói cách nào.
                  Em chỉ hỏi AI khi so chữ không kết luận nổi.
                </span>
              </span>
            </label>

            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                Model cho phần học hỏi
              </p>
              <select
                className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs"
                value={modelHoc}
                onChange={(e) => setModelHoc(e.target.value)}
              >
                <option value="">(theo model chung của bot)</option>
                {Array.from(new Set([...dsModel, ...(modelHoc ? [modelHoc] : [])]))
                  .map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
              </select>
              <p className="text-[11px] text-muted-foreground">
                Việc ở đây rất nhẹ: chỉ đọc hai câu rồi trả lời «cùng ý» hay
                «khác ý». Một model nhỏ và nhanh làm tốt việc này mà rẻ hơn
                nhiều. Chọn sai cũng không hỏng gì — model không trả lời được
                thì em quay về cách so chữ như cũ. Để trống là dùng chung model
                với phần còn lại của bot.
              </p>
              {dsModel.length === 0 ? (
                <p className="text-[11px] text-amber-600">
                  Chưa lấy được danh sách model — kiểm tra lại phần nhà cung cấp
                  AI. Vẫn để trống được, em dùng model chung.
                </p>
              ) : null}
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">
                  Đúng bao nhiêu lần thì thôi hỏi
                </p>
                <Input
                  type="number"
                  min={1}
                  max={20}
                  value={bh.du_mau ?? 4}
                  onChange={(e) => setBh({ ...bh, du_mau: Number(e.target.value) })}
                />
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">
                  Nhớ bài học trong bao nhiêu ngày
                </p>
                <Input
                  type="number"
                  min={1}
                  max={730}
                  value={bh.han_ngay ?? 180}
                  onChange={(e) => setBh({ ...bh, han_ngay: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="space-y-2 rounded border border-border/60 p-2">
              <label className="flex items-center gap-2 text-xs font-semibold">
                <input
                  type="checkbox"
                  checked={bh.bao === true}
                  onChange={(e) => setBh({ ...bh, bao: e.target.checked })}
                />
                📬 Thỉnh thoảng kể cho tôi nghe em học được gì
              </label>
              <p className="text-xs text-muted-foreground">
                Em gộp lại rồi kể một lần: mấy câu anh bảo chưa đúng, loại nào em
                đã chắc tay, loại nào em còn hay sai. Chưa học được gì thì em im,
                không nhắn cho có. Người nhận lấy theo admin anh đã khai ở tab
                Kênh chat.
              </p>
              {/* "Kể cho ai nghe" đã dời sang Cài đặt → Thông báo, dòng
                  «Bản tin bài học» (13/09/2026). */}
              <div className="space-y-1 sm:max-w-[240px]">
                <p className="text-xs text-muted-foreground">Mấy ngày kể một lần</p>
                <Input
                  type="number"
                  min={1}
                  max={90}
                  value={bh.bao_moi_ngay ?? 7}
                  onChange={(e) => setBh({ ...bh, bao_moi_ngay: Number(e.target.value) })}
                />
              </div>
            </div>

            <Button variant="outline" size="sm" onClick={() => void luuCb()}>
              {saved ? "Đã lưu!" : "Lưu cài đặt học tập"}
            </Button>
          </div>
          </CollapsibleSection>

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
        </CollapsibleSection>

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
