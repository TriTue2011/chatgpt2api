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
};

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

  useEffect(() => {
    const c = ((config as any)?.cameras as Record<string, Cam>) || {};
    setCams(c);
  }, [(config as any)?.cameras]);

  useEffect(() => {
    setModelAnh(String((config as any)?.agent_branches?.vision || ""));
  }, [(config as any)?.agent_branches]);

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
    const veTinh = { ve_tinh_cong: cong ? cong : ("" as const), cho_nghe: cams[dangSua]?.cho_nghe === true,
                     cho_loa: cams[dangSua]?.cho_loa !== false,
                     mic_tang_db: Number(cams[dangSua]?.mic_tang_db || 0) };
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

  // Bật/tắt nghe hoặc loa của một camera — lưu ngay, c2a áp trong vài giây.
  const doi = async (t: string, khoa: "cho_nghe" | "cho_loa") => {
    const c = cams[t];
    const bat = khoa === "cho_nghe" ? c.cho_nghe !== true : c.cho_loa === false;
    const tiep = { ...cams, [t]: { ...c, [khoa]: bat } };
    setCams(tiep);
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
                <span className="flex flex-wrap items-center gap-1">
                  <span className="text-[11px] rounded bg-muted px-1.5 py-0.5"
                    title="Cổng vệ tinh Assist — thêm vào HA: Wyoming Protocol → IP máy c2a + cổng này">
                    🛰️ {c.ve_tinh_cong}
                  </span>
                  <Button size="sm" variant={c.cho_nghe === true ? "default" : "outline"}
                    title="Cho Home Assistant nghe mic camera này (ra lệnh bằng giọng nói)"
                    onClick={() => void doi(t, "cho_nghe")}>
                    🎙️ Nghe: {c.cho_nghe === true ? "Bật" : "Tắt"}
                  </Button>
                  <Button size="sm" variant={c.cho_loa !== false ? "default" : "outline"}
                    title="Cho phát ra loa camera (trả lời, thông báo, cảnh báo)"
                    onClick={() => void doi(t, "cho_loa")}>
                    🔊 Loa: {c.cho_loa !== false ? "Bật" : "Tắt"}
                  </Button>
                  <select
                    className="h-8 rounded border border-input bg-background px-1 text-xs"
                    title="Khuếch đại mic trước khi gửi Home Assistant — phải nói to thì tăng lên"
                    value={String(c.mic_tang_db || 0)}
                    onChange={(e) => void doiMic(t, Number(e.target.value))}>
                    {[0, 6, 12, 18, 24, 30].map((db) => (
                      <option key={db} value={db}>🎚️ Mic {db ? `+${db}` : "±0"} dB</option>
                    ))}
                  </select>
                </span>
              ) : null}
              <div className="ml-auto flex flex-wrap gap-1">
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
          <p className="text-sm font-medium">🛰️ Nói chuyện với nhà qua camera (Home Assistant)</p>
          <p className="text-xs text-muted-foreground">
            Camera Dahua/Imou có mic và loa thành một <b>vệ tinh Assist</b>: gọi «ok nabu»
            rồi ra lệnh, trả lời phát ra loa camera; thông báo và cảnh báo của HA cũng phát
            ra đó. Cách bật: sửa camera → điền <b>Cổng vệ tinh</b> (vd 10801, mỗi camera
            một cổng, cổng phải được mở ra ngoài container) → trong HA thêm tích hợp{" "}
            <b>Wyoming Protocol</b> với IP máy c2a và cổng đó → chọn pipeline có từ gọi.
          </p>
          <p className="text-xs text-muted-foreground">
            <b>🎙️ Nghe</b> — cho HA nghe mic (mặc định Tắt). <b>🔊 Loa</b> — cho phát ra
            loa (trả lời, thông báo, cảnh báo, «đọc ra camera»). <b>🎚️ Mic</b> — phải nói
            to mới nhận thì tăng lên (+12 dB là mức bắt đầu hợp lý); ô «Mic volume» trong
            trang thiết bị HA không có tác dụng với loại vệ tinh này. Bấm là áp ngay; c2a
            chặn ở phía mình nên HA đòi cũng không được.
          </p>
          <p className="text-xs text-amber-600">
            ⚠️ <b>Đừng bật Nghe ở camera hướng ra ngoài</b> (cổng, cửa, ban công): ai đứng
            ngoài nói «ok nabu, …» là ra lệnh được cho nhà bạn — kể cả mở khoá, tắt báo động
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
