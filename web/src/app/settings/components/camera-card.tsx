"use client";

/**
 * CameraCard — camera nhà, KHÔNG đi qua Home Assistant.
 *
 * Nhiều người dùng bot không cài Home Assistant, nên camera khai thẳng vào cổng
 * theo hai đường: go2rtc (đã có sẵn máy chủ go2rtc thì chỉ trỏ tới và nêu tên
 * luồng) hoặc RTSP (trỏ thẳng vào camera, ffmpeg bóc một khung).
 *
 * Sổ camera lưu trong config (`cameras`) nên card này dùng saveConfig như mọi
 * card khác; việc duy nhất phải hỏi máy chủ là chụp thử.
 *
 * AI ĐƯỢC XEM thì KHÔNG khai ở đây. Quyền camera là ô tích «📷 Camera nhà» trong
 * bộ lọc chức năng của từng kênh (Telegram / Zalo Bot / Zalo Cá Nhân) — một chỗ
 * duy nhất, cùng chỗ với mọi quyền khác của thread đó. Trước 28/08/2026 card này
 * có thêm danh sách tích riêng (`camera_quyen`), nên phải bật ĐÚNG HAI nơi mới
 * xem được camera và tắt một nơi thì nơi kia im lặng không báo gì.
 */

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";
import { BoDamCamera } from "./bo-dam-camera";

type Cam = {
  kind: "go2rtc" | "rtsp";
  base?: string; src?: string; url?: string;
  // Luồng phụ cho AI đọc — không bắt buộc. Không khai thì AI đọc luồng chính.
  src_ai?: string; url_ai?: string;
  username?: string; password?: string; note?: string;
  // Vệ tinh Assist cho Home Assistant (mic + loa camera Dahua/Imou qua cổng 37777).
  // Cổng trống = camera không làm vệ tinh. Nghe mặc định TẮT: camera hướng ra
  // ngoài mà nghe thì người ngoài ra lệnh được cho nhà.
  ve_tinh_cong?: number | ""; cho_nghe?: boolean; cho_loa?: boolean;
  // Khuếch đại mic trước khi gửi HA (dB). Mic camera nhỏ; ô "Mic volume" của
  // thiết bị Wyoming trong HA 2026.9 không áp vào tiếng nên tăng ở đây.
  mic_tang_db?: number;
  // AI NGHE MIC camera — đúng một đường (services/ve_tinh_camera.py). Bản ghi cũ
  // chưa có trường này: cho_nghe=true coi là "ha".
  tro_ly_che_do?: CheDo;
  tu_goi?: string;                 // "" = để HA bắt từ gọi (chỉ ở chế độ "ha")
  do_nhay?: "thap" | "vua" | "cao";
};

type CheDo = "tat" | "ha" | "c2a";
type TroLy = {
  co_thu_vien: boolean;
  tu_goi: { id: string; ten: string }[];
  ha_khac: { entity_id: string; tich_hop: string }[];
  tai: Record<string, { che_do: CheDo; mic: boolean; ha_noi: boolean;
                        lan_goi: number | null; nghe_duoc: string }>;
};

const CHE_DO: { id: CheDo; nhan: string; giai: string }[] = [
  { id: "tat", nhan: "Tắt", giai: "c2a không nghe mic camera này" },
  { id: "ha", nhan: "Qua Home Assistant",
    giai: "gửi mic cho HA qua vệ tinh Wyoming (HA thêm IP c2a + cổng vệ tinh)" },
  { id: "c2a", nhan: "c2a tự nghe, tự trả lời",
    giai: "không cần HA: gọi từ gọi → ting → nói lệnh → c2a trả lời ra loa camera" },
];

const cheDo = (c: Cam): CheDo =>
  c.tro_ly_che_do === "tat" || c.tro_ly_che_do === "ha" || c.tro_ly_che_do === "c2a"
    ? c.tro_ly_che_do : (c.cho_nghe === true ? "ha" : "tat");

const RONG: Cam = { kind: "go2rtc", base: "", src: "", url: "", src_ai: "", url_ai: "",
                    username: "", password: "", note: "", ve_tinh_cong: "" };

export function CameraCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);

  const [cams, setCams] = useState<Record<string, Cam>>({});

  const [ten, setTen] = useState("");
  const [moi, setMoi] = useState<Cam>({ ...RONG });
  // Tên camera đang sửa; "" = đang thêm mới. Sửa = ghi đè theo tên, nên đổi tên
  // trong lúc sửa sẽ tạo bản ghi mới — xoá bản cũ để không thành hai cái.
  const [dangSua, setDangSua] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [xemTruoc, setXemTruoc] = useState("");
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [modelAnh, setModelAnh] = useState("");
  const [boDam, setBoDam] = useState("");        // camera đang mở bộ đàm
  const [dongHa, setDongHa] = useState<{ ten: string; nguon: string } | null>(null);
  const [troLy, setTroLy] = useState<TroLy | null>(null);

  useEffect(() => {
    const c = ((config as any)?.cameras as Record<string, Cam>) || {};
    setCams(c);
  }, [(config as any)?.cameras]);

  useEffect(() => {
    setModelAnh(String((config as any)?.agent_branches?.vision || ""));
  }, [(config as any)?.agent_branches]);

  // Từ gọi chọn được, trợ lý khác đang có trong HA, tai đang chạy — hỏi lại sau mỗi lần lưu.
  useEffect(() => {
    request.get("/api/camera/tro_ly")
      .then((r) => setTroLy(r.data as TroLy))
      .catch(() => setTroLy(null));
  }, [saved]);

  useEffect(() => {
    request.get("/api/v1/available-models")
      .then((r) => setModels(((r.data as any)?.providers as Record<string, string[]>) || {}))
      .catch(() => setModels({}));
  }, []);

  const luu = async (cam: Record<string, Cam>) => {
    await saveConfig({ ...config, cameras: cam } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  // Model phân tích ảnh = nhánh vision. Lưu cả config (side-effect webhook đã
  // được backend chặn khi giá trị không đổi) nên không đụng tới webhook nào.
  const luuModel = async (m: string) => {
    setModelAnh(m);
    await saveConfig({ ...config,
      agent_branches: { ...((config as any)?.agent_branches || {}), vision: m } } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  // Thêm mới HOẶC ghi đè camera đang sửa. Cùng một hàm vì lưu là ghi theo tên.
  const luuCam = async () => {
    const t = ten.trim();
    if (!t) { setMsg("❌ Chưa đặt tên cho camera."); return; }
    if (moi.kind === "go2rtc" && (!moi.base?.trim() || !moi.src?.trim())) {
      setMsg("❌ Camera go2rtc cần cả địa chỉ máy chủ và tên luồng."); return;
    }
    if (moi.kind === "rtsp" && !moi.url?.trim().toLowerCase().startsWith("rtsp://")) {
      setMsg("❌ Địa chỉ RTSP phải bắt đầu bằng rtsp://"); return;
    }
    if (moi.kind === "rtsp" && moi.url_ai?.trim()
        && !moi.url_ai.trim().toLowerCase().startsWith("rtsp://")) {
      setMsg("❌ Địa chỉ RTSP của luồng phụ phải bắt đầu bằng rtsp://"); return;
    }
    if (!dangSua && cams[t]) { setMsg(`❌ Đã có camera tên "${t}" rồi.`); return; }

    const cong = Number(moi.ve_tinh_cong || 0);
    if (moi.ve_tinh_cong && !(cong > 0 && cong < 65536)) {
      setMsg("❌ Cổng vệ tinh phải là số từ 1 tới 65535 (để trống nếu không dùng)."); return;
    }
    const trung = Object.entries(cams).find(([k, c]) => k !== dangSua && cong
                                            && Number(c.ve_tinh_cong || 0) === cong);
    if (trung) { setMsg(`❌ Cổng ${cong} đang dùng cho camera «${trung[0]}».`); return; }
    // Công tắc nghe/loa bật tắt ở danh sách — sửa địa chỉ không được làm mất chúng.
    const cu = cams[dangSua] || ({} as Cam);
    const veTinh = { ve_tinh_cong: cong ? cong : ("" as const), cho_nghe: cu.cho_nghe === true,
                     cho_loa: cu.cho_loa !== false,
                     mic_tang_db: Number(cu.mic_tang_db || 0),
                     tro_ly_che_do: cheDo(cu), tu_goi: cu.tu_goi || "", do_nhay: cu.do_nhay || "vua" };
    const ban: Cam = moi.kind === "go2rtc"
      ? { kind: "go2rtc", base: moi.base!.trim().replace(/\/+$/, ""), src: moi.src!.trim(),
          src_ai: moi.src_ai?.trim() || "",
          username: moi.username?.trim() || "", password: moi.password || "",
          note: moi.note?.trim() || "", ...veTinh }
      : { kind: "rtsp", url: moi.url!.trim(), url_ai: moi.url_ai?.trim() || "",
          note: moi.note?.trim() || "", ...veTinh };

    const tiep = { ...cams };
    // Đổi tên trong lúc sửa: bỏ bản ghi cũ, nếu không thành hai camera.
    if (dangSua && dangSua !== t) delete tiep[dangSua];
    tiep[t] = ban;
    setCams(tiep); huy(); setMsg("");
    await luu(tiep);
  };

  const sua = (t: string) => {
    setDangSua(t);
    setTen(t);
    setMoi({ ...RONG, ...cams[t] });
    setMsg(""); setXemTruoc("");
  };

  const huy = () => { setDangSua(""); setTen(""); setMoi({ ...RONG }); };

  const doiMic = async (t: string, db: number) => {
    const tiep = { ...cams, [t]: { ...cams[t], mic_tang_db: db } };
    setCams(tiep);
    await luu(tiep);
  };

  // Bật/tắt loa của một camera — lưu ngay, c2a áp trong vài giây.
  const doiLoa = async (t: string) => {
    const tiep = { ...cams, [t]: { ...cams[t], cho_loa: cams[t].cho_loa === false } };
    setCams(tiep);
    await luu(tiep);
  };

  // Đổi trợ lý (ai nghe mic, từ gọi, độ nhạy). Viết luôn `cho_nghe` cho khớp để bản ghi
  // không còn hai công tắc nói hai điều khác nhau.
  const doiTroLy = async (t: string, sua: Partial<Cam>) => {
    const c = { ...cams[t], ...sua };
    const m = cheDo(c);
    if (m === "ha" && !c.ve_tinh_cong) {
      setMsg(`❌ «${t}» chưa có cổng vệ tinh — bấm Sửa, điền Cổng vệ tinh rồi mới chọn Qua Home Assistant.`);
      return;
    }
    if (m === "c2a" && !c.tu_goi) c.tu_goi = "tro_ly";
    const tiep = { ...cams, [t]: { ...c, tro_ly_che_do: m, cho_nghe: m === "ha" } };
    setCams(tiep); setMsg("");
    await luu(tiep);
  };

  const xoa = async (t: string) => {
    if (dangSua === t) huy();
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

  // Dòng go2rtc cho thẻ WebRTC Camera của HA nói ra loa camera. c2a ký sẵn
  // đường POST (go2rtc không gửi được header) — địa chỉ lấy theo trang đang mở.
  const layDongHa = async (t: string) => {
    setMsg("");
    try {
      const r = await request.get(`/api/camera/bo_dam/${encodeURIComponent(t)}/go2rtc`,
                                  { params: { goc: window.location.origin } });
      const d = r.data as { ok?: boolean; nguon?: string; error?: string };
      if (d.ok && d.nguon) setDongHa({ ten: t, nguon: d.nguon });
      else setMsg(`❌ ${d.error || "Không lấy được"}`);
    } catch (e) {
      setMsg(`❌ ${e instanceof Error ? e.message : String(e)}`);
    }
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
              <span className="text-xs text-muted-foreground truncate max-w-[20rem]">
                {c.kind === "go2rtc" ? `${c.base} · luồng ${c.src}` : c.url}
              </span>
              {(c.kind === "go2rtc" ? c.src_ai : c.url_ai)
                ? <span className="text-[11px] rounded bg-emerald-500/15 px-1.5 py-0.5"
                    title="Có luồng phụ riêng cho AI đọc">+ luồng phụ</span>
                : null}
              {c.note ? <span className="text-xs text-muted-foreground">— {c.note}</span> : null}
              {c.ve_tinh_cong ? (
                <span className="text-[11px] rounded bg-muted px-1.5 py-0.5"
                  title="Cổng vệ tinh Assist — thêm vào HA: Wyoming Protocol → IP máy c2a + cổng này">
                  🛰️ {c.ve_tinh_cong}
                </span>
              ) : null}
              <span className="flex w-full flex-wrap items-center gap-1">
                <select
                  className="h-8 rounded border border-input bg-background px-1 text-xs"
                  title="Ai nghe mic camera này — chỉ MỘT đường"
                  value={cheDo(c)}
                  onChange={(e) => void doiTroLy(t, { tro_ly_che_do: e.target.value as CheDo })}>
                  {CHE_DO.map((m) => (
                    <option key={m.id} value={m.id}>🎙️ Trợ lý: {m.nhan}</option>
                  ))}
                </select>
                {cheDo(c) !== "tat" ? (
                  <>
                    <select
                      className="h-8 rounded border border-input bg-background px-1 text-xs"
                      title="Từ gọi. «HA bắt» = dùng từ gọi trong pipeline của HA"
                      value={c.tu_goi || (cheDo(c) === "c2a" ? "tro_ly" : "")}
                      onChange={(e) => void doiTroLy(t, { tu_goi: e.target.value })}>
                      {cheDo(c) === "ha" ? <option value="">🗣️ Từ gọi: HA bắt (theo pipeline)</option> : null}
                      {(troLy?.tu_goi || [{ id: "tro_ly", ten: "Trợ lý" }]).map((w) => (
                        <option key={w.id} value={w.id}>🗣️ Từ gọi: {w.ten} (c2a bắt)</option>
                      ))}
                    </select>
                    {c.tu_goi || cheDo(c) === "c2a" ? (
                      <select
                        className="h-8 rounded border border-input bg-background px-1 text-xs"
                        title="Độ nhạy từ gọi — tự dậy khi không ai gọi thì hạ xuống, gọi mãi không dậy thì nâng lên"
                        value={c.do_nhay || "vua"}
                        onChange={(e) => void doiTroLy(t, { do_nhay: e.target.value as Cam["do_nhay"] })}>
                        <option value="thap">Độ nhạy: Thấp (ít dậy nhầm)</option>
                        <option value="vua">Độ nhạy: Vừa</option>
                        <option value="cao">Độ nhạy: Cao (gọi xa)</option>
                      </select>
                    ) : null}
                  </>
                ) : null}
                <Button size="sm" variant={c.cho_loa !== false ? "default" : "outline"}
                  title="Cho phát ra loa camera (trả lời, thông báo, cảnh báo)"
                  onClick={() => void doiLoa(t)}>
                  🔊 Loa: {c.cho_loa !== false ? "Bật" : "Tắt"}
                </Button>
                <select
                  className="h-8 rounded border border-input bg-background px-1 text-xs"
                  title="Khuếch đại mic camera — phải nói to mới nhận thì tăng lên"
                  value={String(c.mic_tang_db || 0)}
                  onChange={(e) => void doiMic(t, Number(e.target.value))}>
                  {[0, 6, 12, 18, 24, 30].map((db) => (
                    <option key={db} value={db}>🎚️ Mic {db ? `+${db}` : "±0"} dB</option>
                  ))}
                </select>
                {troLy?.tai?.[t] ? (
                  <span className="text-[11px] text-muted-foreground">
                    {troLy.tai[t].mic ? "mic đang nghe" : "mic chưa mở"}
                    {cheDo(c) === "ha" ? (troLy.tai[t].ha_noi ? " · HA đã nối" : " · HA chưa nối") : ""}
                    {troLy.tai[t].lan_goi
                      ? ` · gọi lúc ${new Date(troLy.tai[t].lan_goi! * 1000).toLocaleTimeString("vi-VN")}` : ""}
                    {troLy.tai[t].nghe_duoc ? ` · nghe: «${troLy.tai[t].nghe_duoc}»` : ""}
                  </span>
                ) : null}
              </span>
              <div className="ml-auto flex flex-wrap gap-1">
                {c.ve_tinh_cong ? (
                  <>
                    <Button size="sm" variant={boDam === t ? "default" : "outline"}
                      title="Nghe camera và giữ nút để nói ra loa camera"
                      onClick={() => setBoDam(boDam === t ? "" : t)}>
                      📞 Bộ đàm
                    </Button>
                    <Button size="sm" variant="outline"
                      title="Dòng dán vào go2rtc.yaml để thẻ WebRTC Camera của HA nói ra loa camera này"
                      onClick={() => void layDongHa(t)}>
                      📋 Dòng go2rtc
                    </Button>
                  </>
                ) : null}
                <Button size="sm" variant="outline" disabled={busy === t} onClick={() => thu(t)}>
                  {busy === t ? "…" : "Chụp thử"}
                </Button>
                <Button size="sm" variant={dangSua === t ? "default" : "outline"}
                  onClick={() => (dangSua === t ? huy() : sua(t))}>
                  {dangSua === t ? "Đang sửa" : "Sửa"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => xoa(t)}>Xoá</Button>
              </div>
            </div>
          ))}
        </div>

        {boDam && cams[boDam] ? (
          <BoDamCamera key={boDam} ten={boDam} onClose={() => setBoDam("")} />
        ) : null}

        {dongHa ? (
          <div className="rounded border border-border/70 p-3 space-y-2">
            <p className="text-sm font-medium">📋 Bộ đàm trong Home Assistant — «{dongHa.ten}»</p>
            <p className="text-xs text-muted-foreground">
              1. Mở <code>go2rtc.yaml</code> của HA, thêm dòng dưới vào <b>cuối danh sách nguồn</b>{" "}
              của luồng camera này (luồng mà thẻ WebRTC Camera đang xem), rồi khởi động lại go2rtc.
              Địa chỉ trong dòng phải là địa chỉ máy go2rtc gọi tới được c2a — mở trang này bằng
              IP nội bộ thì đúng sẵn.
            </p>
            <textarea readOnly rows={4} value={`      - "${dongHa.nguon}"`}
              className="w-full rounded border border-input bg-muted/40 p-2 font-mono text-[11px]"
              onFocus={(e) => e.currentTarget.select()} />
            <p className="text-xs text-muted-foreground">
              2. Trong thẻ <code>custom:webrtc-camera</code> thêm{" "}
              <code>media: video,audio,microphone</code>, mở HA bằng <b>https</b> (mic trình
              duyệt chỉ chạy trên https), bấm nút mic trên thẻ rồi nói.
            </p>
            <p className="text-xs text-amber-600">
              ⚠️ Dòng này chứa chữ ký riêng của camera này: ai có nó thì phát được tiếng ra loa
              camera (không làm được gì khác). Đừng dán ra ngoài go2rtc.yaml.
            </p>
            <Button size="sm" variant="outline" onClick={() => setDongHa(null)}>Đóng</Button>
          </div>
        ) : null}

        {xemTruoc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={xemTruoc} alt="Ảnh chụp thử" className="max-h-64 rounded border border-border/70" />
        ) : null}

        {/* ── Thêm camera ──────────────────────────────────────────────── */}
        <div className="rounded border border-dashed border-border/70 p-3 space-y-2">
          <p className="text-sm font-medium">
            {dangSua ? `Sửa camera «${dangSua}»` : "Thêm camera"}
          </p>
          <div className="flex flex-wrap gap-2">
            <Input className="w-48" value={ten} onChange={(e) => setTen(e.target.value)}
              placeholder="Tên gọi, vd: Sân trước" />
            <select className="h-9 rounded border border-input bg-background px-2 text-base sm:text-sm"
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
                <Input className="w-52" value={moi.src_ai || ""}
                  onChange={(e) => setMoi({ ...moi, src_ai: e.target.value })}
                  placeholder="luồng phụ cho AI (không bắt buộc)" />
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
                vì go2rtc giữ sẵn kết nối tới camera — và cũng vì thế, khai thêm luồng phụ
                ở đây là an toàn: hai lời gọi cùng lúc không phiền tới camera.
              </p>
            </>
          ) : (
            <>
              <Input value={moi.url || ""}
                onChange={(e) => setMoi({ ...moi, url: e.target.value })}
                placeholder="rtsp://admin:matkhau@192.168.1.20/cam/realmonitor?channel=1&subtype=0" />
              <Input value={moi.url_ai || ""}
                onChange={(e) => setMoi({ ...moi, url_ai: e.target.value })}
                placeholder="Luồng phụ cho AI (không bắt buộc) — cùng URL nhưng subtype=1" />
              <p className="text-xs text-muted-foreground">
                <b>Dán nguyên URL vào</b>, cả phần đường dẫn và phần <code>?channel=1&amp;subtype=0</code>
                {" "}phía sau — không phải cắt bớt hay mã hoá gì. Mật khẩu có ký tự lạ như{" "}
                <code>@</code> cũng gõ thẳng được.
              </p>
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer select-none">
                  Không biết URL camera mình là gì?
                </summary>
                <div className="pt-1 space-y-0.5">
                  <p>Dahua · Amcrest · Lorex · KBVision:{" "}
                    <code>/cam/realmonitor?channel=1&amp;subtype=0</code> — luồng phụ đổi{" "}
                    <code>subtype=1</code></p>
                  <p>Hikvision · Ezviz:{" "}
                    <code>/Streaming/Channels/101</code> — luồng phụ là{" "}
                    <code>/102</code></p>
                  <p>Reolink: <code>/h264Preview_01_main</code> — luồng phụ là{" "}
                    <code>/h264Preview_01_sub</code></p>
                  <p>TP-Link Tapo: <code>/stream1</code> — luồng phụ là{" "}
                    <code>/stream2</code></p>
                  <p className="pt-1">Không chắc thì cứ điền luồng chính rồi bấm{" "}
                    <b>Chụp thử</b>: sai URL nó báo ngay chứ không im lặng.</p>
                </div>
              </details>
              <p className="text-xs text-muted-foreground">
                Xin ảnh thì lấy <b>luồng chính</b> cho nét. Hỏi về cảnh thì AI đọc{" "}
                <b>luồng phụ</b>, còn bạn vẫn nhận tấm luồng chính kèm câu trả lời.
                Bỏ trống luồng phụ cũng chạy bình thường: AI đọc luôn luồng chính.
              </p>
              <p className="text-xs text-amber-600">
                ⚠️ Với RTSP thẳng, khai luồng phụ khiến mỗi lần hỏi phải bấm camera{" "}
                <b>hai lần nối đuôi</b> — nhiều camera không chịu nổi hai phiên RTSP cùng
                lúc (đo trên Dahua thật: song song hỏng cả hai). Hai tấm vì thế cách nhau
                vài giây. Mà ảnh đưa model đằng nào cũng được thu về 768px, nên luồng phụ
                thường <b>không tiết kiệm được bao nhiêu</b>. Chỉ khai khi camera của bạn
                chịu được, hoặc khi đi qua go2rtc.
              </p>
            </>
          )}

          <Input value={moi.note || ""} onChange={(e) => setMoi({ ...moi, note: e.target.value })}
            placeholder="Ghi chú — cũng dùng để nhận tên, vd: cổng ngoài, chỗ để xe" />
          <div className="flex flex-wrap items-center gap-2">
            <Input className="w-40" inputMode="numeric" value={String(moi.ve_tinh_cong ?? "")}
              onChange={(e) => setMoi({ ...moi, ve_tinh_cong: e.target.value.replace(/\D/g, "") as any })}
              placeholder="Cổng vệ tinh, vd 10801" />
            <span className="text-xs text-muted-foreground">
              🛰️ Vệ tinh Assist (camera Dahua/Imou): để trống nếu không dùng.
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={luuCam}>
              {dangSua ? "Lưu thay đổi" : "Thêm camera"}
            </Button>
            {dangSua ? (
              <Button size="sm" variant="outline" onClick={huy}>Huỷ</Button>
            ) : null}
          </div>
        </div>

        {/* ── Vệ tinh Assist ───────────────────────────────────────────── */}
        <div className="rounded border border-dashed border-border/70 p-3 space-y-1">
          <p className="text-sm font-medium">🎙️ Nói chuyện với nhà qua camera</p>
          <p className="text-xs text-muted-foreground">
            Ô <b>🎙️ Trợ lý</b> ở từng camera quyết định <b>ai nghe mic</b> — chỉ một đường:{" "}
            <b>Tắt</b> · <b>Qua Home Assistant</b> (c2a làm vệ tinh Wyoming, HA hiểu lệnh) ·{" "}
            <b>c2a tự nghe, tự trả lời</b> (không cần HA). Từ gọi «c2a bắt» nghe ngay trên máy
            c2a như loa R1; độ nhạy chỉnh ngay cạnh đó.
          </p>
          <p className="text-xs text-amber-600">
            ⚠️ Nếu camera đã được thêm vào HA bằng tích hợp khác có trợ lý (vd <b>dahua_talk</b>)
            thì chỉ bật MỘT bên: bật ở đây thì tắt vệ tinh bên kia (xoá hoặc vô hiệu thực thể
            assist_satellite của nó), không thì một câu gọi được trả lời hai lần.
          </p>
          {troLy && troLy.ha_khac.length > 0 ? (
            <p className="text-xs text-amber-600">
              Trong HA đang có trợ lý khác:{" "}
              {troLy.ha_khac.map((x) => `${x.entity_id} (${x.tich_hop})`).join(", ")}.
            </p>
          ) : null}
          {troLy && !troLy.co_thu_vien ? (
            <p className="text-xs text-destructive">
              Máy chủ chưa có thư viện nghe từ gọi (pyopen-wakeword) — cập nhật ảnh c2a mới.
            </p>
          ) : null}
          <p className="text-sm font-medium pt-1">🛰️ Qua Home Assistant</p>
          <p className="text-xs text-muted-foreground">
            Camera Dahua/Imou có mic và loa thành một <b>vệ tinh Assist</b>: gọi «ok nabu»
            rồi ra lệnh, trả lời phát ra loa camera; thông báo và cảnh báo của HA cũng phát
            ra đó. Cách bật: sửa camera → điền <b>Cổng vệ tinh</b> (vd 10801, mỗi camera
            một cổng, cổng phải được mở ra ngoài container) → trong HA thêm tích hợp{" "}
            <b>Wyoming Protocol</b> với IP máy c2a và cổng đó → chọn pipeline có từ gọi.
          </p>
          <p className="text-xs text-muted-foreground">
            <b>🔊 Loa</b> — cho phát ra
            loa (trả lời, thông báo, cảnh báo, «đọc ra camera»). <b>🎚️ Mic</b> — phải nói
            to mới nhận thì tăng lên (+12 dB là mức bắt đầu hợp lý); ô «Mic volume» trong
            trang thiết bị HA không có tác dụng với loại vệ tinh này. Bấm là áp ngay; c2a
            chặn ở phía mình nên HA đòi cũng không được.
          </p>
          <p className="text-xs text-amber-600">
            ⚠️ <b>Đừng bật Trợ lý ở camera hướng ra ngoài</b> (cổng, cửa, ban công): ai đứng
            ngoài gọi từ gọi là ra lệnh được cho nhà bạn — kể cả mở khoá, tắt báo động
            nếu trợ lý được phép. Camera ngoài chỉ nên bật Loa.
          </p>
        </div>

        {/* ── Ai được xem ──────────────────────────────────────────────── */}
        <div className="rounded border border-dashed border-border/70 p-3 space-y-1">
          <p className="text-sm font-medium">🔐 Ai được xem camera</p>
          <p className="text-xs text-muted-foreground">
            Cài ở <b>Kênh chat</b>, không phải ở đây: chọn kênh (📨 Telegram ·
            💬 Zalo Bot · 👤 Zalo Cá Nhân) → tab <b>🎚️ Lọc thread</b> → tìm hội
            thoại cần mở → tích ô <b>📷 Camera nhà (go2rtc · RTSP)</b>. Đó cũng là
            chỗ đang quyết định mọi quyền khác của hội thoại đó.
          </p>
          <p className="text-xs text-amber-600">
            ⚠️ Camera phải <b>tích mới có</b>: hội thoại chưa đặt bộ lọc thì không
            xem được, kể cả khi các chức năng khác đang mở hết. Bật nhầm là người
            đó xin được ảnh trong nhà bất cứ lúc nào, nên tích xong hãy đọc lại.
          </p>
        </div>

        {/* ── Model phân tích ảnh ──────────────────────────────────────── */}
        <div className="space-y-1">
          <p className="text-sm font-medium">🔎 Model phân tích ảnh</p>
          <p className="text-xs text-muted-foreground">
            Chỉ chạy khi có câu hỏi về ảnh (vd «ngoài cổng có ai không»); chỉ xin
            ảnh thì bỏ qua, không tốn model. Để «Mặc định» nếu không chắc.
          </p>
          <select
            className="w-full rounded-lg border border-border bg-background p-2 text-base sm:text-sm"
            value={modelAnh}
            onChange={(e) => void luuModel(e.target.value)}
          >
            <option value="">Mặc định (gma/auto)</option>
            {Object.entries(models).map(([owner, ids]) => (
              <optgroup key={owner} label={owner}>
                {ids.map((id) => (
                  <option key={id} value={id}>{id}</option>
                ))}
              </optgroup>
            ))}
          </select>
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
