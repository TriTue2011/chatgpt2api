"use client";

/**
 * Card Giọng nói & Loa — đặt TÊN cho loa rồi ra lệnh bằng tên đó.
 *
 * Backend: api/voice.py (/api/voice/status, /api/voice/speakers…).
 * Loa Cast/DLNA nối THẲNG bằng IP (không qua Home Assistant); loa lạ thì nhập
 * từ HA. Container chạy bridge network nên KHÔNG tự dò được mDNS/SSDP — vì vậy
 * UI luôn cho nhập IP tay.
 */

import { useCallback, useEffect, useState } from "react";
import { Save, Volume2, Trash2, PlayCircle, PlugZap, Download, Radar, Music, Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { useSettingsStore } from "../store";

type Speaker = {
  id: string; name: string; kind: string;
  host?: string; port?: number; entity_id?: string; note?: string;
  ws_port?: number; max_vol?: number;
};

type Found = { host: string; port: number; kind: string; name: string; known?: boolean; control_url?: string };

type VoiceStatus = {
  tts?: { enabled?: boolean; backend?: string; voice?: string; model_ready?: boolean;
          piper_bin?: string; local_voices?: string[]; wyoming_url?: string };
  stt?: { enabled?: boolean; backend?: string; model_ready?: boolean;
          en_model_ready?: boolean; language?: string;
          sherpa_installed?: boolean; wyoming_url?: string };
  public_base_url?: string;
};

type VoiceItem = {
  id: string; language: string; language_label: string;
  downloaded: boolean; default: boolean;
};

const KIND_LABEL: Record<string, string> = {
  cast: "Google Cast", dlna: "DLNA / UPnP", ha: "Qua Home Assistant", r1: "Loa R1 (Phicomm)",
};

export function VoiceSpeakersCard() {
  const config = useSettingsStore((s) => s.config);
  const setField = useSettingsStore((s) => s.setField);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const isSavingConfig = useSettingsStore((s) => s.isSavingConfig);

  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [rows, setRows] = useState<Speaker[]>([]);
  const [catalog, setCatalog] = useState<VoiceItem[]>([]);
  const [draft, setDraft] = useState<Speaker>({ id: "", name: "", kind: "cast", host: "" });
  const [busy, setBusy] = useState(false);
  const [previewing, setPreviewing] = useState("");
  const [found, setFound] = useState<Found[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanKind, setScanKind] = useState("all");
  // Hẹn giờ thông báo ra loa
  const [ann, setAnn] = useState({ speaker: "", text: "", delayMin: 1, volPct: 20 });

  const load = useCallback(async () => {
    try {
      const [st, sp, cat] = await Promise.all([
        request.get("/api/voice/status"),
        request.get("/api/voice/speakers"),
        request.get("/api/voice/catalog"),
      ]);
      setStatus(st.data as VoiceStatus);
      setRows(((sp.data as { rows?: Speaker[] })?.rows) || []);
      setCatalog(((cat.data as { voices?: VoiceItem[] })?.voices) || []);
    } catch {
      /* chưa bật voice thì bỏ qua */
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Nghe thử theo DÒNG CHẢY: chữ tổng hợp tới đâu phát tới đó (stream=1) nên nghe
  // gần như tức thì thay vì chờ ~3-4s tổng hợp trọn câu. Thẻ <audio> không gửi
  // được header nên đính token qua query `key=` (giống tab Chat).
  const preview = async (voiceId: string) => {
    setPreviewing(voiceId);
    try {
      const { getStoredAuthKey } = await import("@/store/auth");
      let key = await getStoredAuthKey();
      if (!key) { try { key = localStorage.getItem("chatgpt2api_auth_key") || ""; } catch { /* noop */ } }
      const url = `/api/voice/preview?stream=1&voice=${encodeURIComponent(voiceId)}`
        + `&key=${encodeURIComponent(key || "")}`;
      const audio = new Audio(url);
      audio.onended = () => setPreviewing("");
      audio.onerror = () => { setPreviewing(""); toast.error("Nghe thử lỗi (giọng chưa tải?)"); };
      await audio.play();
    } catch (e) {
      setPreviewing("");
      toast.error(`Nghe thử lỗi: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const cfg = (config as Record<string, unknown>) || {};
  const voiceCfg = (cfg.voice as Record<string, unknown>) || {};
  const ttsCfg = (voiceCfg.tts as Record<string, unknown>) || {};
  const sttCfg = (voiceCfg.stt as Record<string, unknown>) || {};

  const patchVoice = (section: "tts" | "stt", patch: Record<string, unknown>) => {
    const base = section === "tts" ? ttsCfg : sttCfg;
    setField("voice", { ...voiceCfg, [section]: { ...base, ...patch } });
  };

  const addSpeaker = async () => {
    if (!draft.name.trim()) { toast.error("Đặt tên loa trước (vd 'loa phòng khách')"); return; }
    setBusy(true);
    try {
      await request.post("/api/voice/speakers", draft);
      toast.success(`Đã thêm loa ${draft.name}`);
      setDraft({ id: "", name: "", kind: draft.kind, host: "" });
      void load();
    } catch (e) {
      toast.error(`Thêm loa lỗi: ${e instanceof Error ? e.message : e}`);
    } finally { setBusy(false); }
  };

  const act = async (id: string, what: "test" | "play" | "delete") => {
    setBusy(true);
    try {
      if (what === "delete") {
        await request.delete(`/api/voice/speakers/${id}`);
        toast.success("Đã xoá loa");
        void load();
      } else if (what === "test") {
        const r = await request.post(`/api/voice/speakers/${id}/test`, {});
        const d = r.data as { ok?: boolean; message?: string };
        if (d?.ok) toast.success(d.message || "Kết nối được");
        else toast.error(d?.message || "Không kết nối được");
      } else {
        await request.post(`/api/voice/speakers/${id}/play`,
          { text: "Xin chào, đây là thử nghiệm loa." });
        toast.success("Đã gửi câu thử ra loa");
      }
    } catch (e) {
      toast.error(`Lỗi: ${e instanceof Error ? e.message : e}`);
    } finally { setBusy(false); }
  };

  // Âm lượng loa Cast: đặt ngay + lưu làm mặc định cho các lần phát sau.
  const setVol = async (id: string, level: number) => {
    try {
      await request.post(`/api/voice/speakers/${id}/volume`, { level, save: true });
      toast.success(`Âm lượng ${level}%`);
    } catch (e) {
      toast.error(`Lỗi: ${e instanceof Error ? e.message : e}`);
    }
  };

  // Bật/tắt/dừng như media_player của Home Assistant (on = đánh thức,
  // off = thoát app đang cast, stop = dừng phát).
  const ctl = async (id: string, action: "on" | "off" | "stop") => {
    try {
      await request.post(`/api/voice/speakers/${id}/control`, { action });
      toast.success({ on: "Đã bật loa", off: "Đã tắt (thoát cast)", stop: "Đã dừng phát" }[action]);
    } catch (e) {
      toast.error(`Lỗi: ${e instanceof Error ? e.message : e}`);
    }
  };

  const importHa = async () => {
    setBusy(true);
    try {
      const r = await request.post("/api/voice/speakers/import-ha", {});
      const d = r.data as { count?: number };
      toast.success(`Đã nhập ${d?.count ?? 0} loa từ Home Assistant`);
      void load();
    } catch (e) {
      toast.error(`Nhập lỗi: ${e instanceof Error ? e.message : e}`);
    } finally { setBusy(false); }
  };

  // Dò loa trong LAN (Cast 8009 / R1 8082, DLNA qua SSDP) — không cần nhập IP tay.
  const discover = async () => {
    setScanning(true);
    try {
      const r = await request.post(`/api/voice/discover?kind=${encodeURIComponent(scanKind)}`, {});
      const d = r.data as { found?: Found[] };
      const list = d?.found || [];
      setFound(list);
      toast.success(list.length ? `Tìm thấy ${list.length} loa`
        : (scanKind === "dlna" ? "Không thấy loa DLNA (mạng có thể chặn multicast — thử nhập từ HA)"
          : "Không thấy loa nào"));
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e instanceof Error ? e.message : String(e));
      toast.error(`Dò loa lỗi: ${msg}`);
    } finally { setScanning(false); }
  };

  // Thêm nhanh loa vừa dò được (điền sẵn tên/IP/kiểu).
  const addFound = async (f: Found) => {
    const name = window.prompt(`Đặt tên cho loa ${f.name} (${f.host})`, f.name) || "";
    if (!name.trim()) return;
    setBusy(true);
    try {
      await request.post("/api/voice/speakers",
        { name: name.trim(), kind: f.kind, host: f.host, port: f.port,
          control_url: f.control_url || "" });
      toast.success(`Đã thêm loa ${name.trim()}`);
      setFound((prev) => prev.filter((x) => x.host !== f.host || x.port !== f.port));
      void load();
    } catch (e) {
      toast.error(`Thêm loa lỗi: ${e instanceof Error ? e.message : e}`);
    } finally { setBusy(false); }
  };

  // Hẹn giờ đọc thông báo ra loa (sau N phút, kèm âm lượng %).
  const sendAnnounce = async () => {
    if (!ann.speaker.trim() || !ann.text.trim()) {
      toast.error("Chọn loa và nhập nội dung thông báo"); return;
    }
    setBusy(true);
    try {
      await request.post("/api/voice/announce", {
        speaker: ann.speaker.trim(), text: ann.text.trim(),
        delay_seconds: Math.max(0, Number(ann.delayMin) || 0) * 60,
        volume: Number(ann.volPct),
      });
      toast.success(Number(ann.delayMin) > 0
        ? `Đã hẹn đọc sau ${ann.delayMin} phút ra ${ann.speaker}`
        : `Đang đọc ra ${ann.speaker}`);
      setAnn({ ...ann, text: "" });
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e instanceof Error ? e.message : String(e));
      toast.error(`Hẹn thông báo lỗi: ${msg}`);
    } finally { setBusy(false); }
  };

  // Mở nhạc theo yêu cầu trên loa R1 (YouTube).
  const playMusic = async (id: string) => {
    const query = window.prompt("Mở nhạc gì trên R1? (vd: nhạc không lời, lofi chill)", "nhạc không lời");
    if (!query || !query.trim()) return;
    setBusy(true);
    try {
      const r = await request.post(`/api/voice/speakers/${id}/music`, { query: query.trim() });
      const d = r.data as { song?: { title?: string } };
      toast.success(`Đang phát: ${d?.song?.title || query.trim()}`);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e instanceof Error ? e.message : String(e));
      toast.error(`Mở nhạc lỗi: ${msg}`);
    } finally { setBusy(false); }
  };

  const tts = status?.tts;
  const stt = status?.stt;

  return (
    <Card>
      <CardContent className="space-y-4 pt-4">
        <div className="text-sm font-semibold flex items-center gap-2">
          <Volume2 className="size-4 text-emerald-500" /> Giọng nói &amp; Loa
        </div>

        {/* Trạng thái engine */}
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-border p-2 text-[11px] space-y-0.5">
            <div className="font-semibold">🔊 Đọc (TTS)</div>
            <div>{tts?.enabled ? "✅ sẵn sàng" : "⚠️ chưa sẵn sàng"} · backend {tts?.backend || "?"}</div>
            <div>Giọng: <b>{tts?.voice || "-"}</b> {tts?.model_ready ? "" : "(chưa tải file giọng)"}</div>
            <div className="text-muted-foreground">
              {tts?.piper_bin ? `piper: ${tts.piper_bin}` : "chưa có binary piper trong image"}
              {" · "}{(tts?.local_voices || []).length} giọng trên volume
            </div>
          </div>
          <div className="rounded-md border border-border p-2 text-[11px] space-y-0.5">
            <div className="font-semibold">🎤 Nghe (STT)</div>
            <div>{stt?.enabled ? "✅ sẵn sàng" : "⚠️ chưa sẵn sàng"} · backend {stt?.backend || "?"}</div>
            <div>
              Ngôn ngữ: <b>{
                stt?.language === "auto" ? "auto (VI→EN)"
                  : stt?.language === "en" ? "English (en)"
                  : "Tiếng Việt (vi)"
              }</b>
            </div>
            <div className="text-muted-foreground">
              VI {stt?.model_ready ? "✓" : "—"} · EN {stt?.en_model_ready ? "✓" : "—"}
              {" · "}sherpa-onnx {stt?.sherpa_installed ? "có" : "chưa cài"}
            </div>
          </div>
        </div>
        <p className="text-[10px] text-muted-foreground -mt-1">
          Model KHÔNG nằm trong image. Tải về volume:{" "}
          <code>python scripts/download_piper_voices.py --pack minimal</code> (giọng) và{" "}
          <code>python scripts/download_stt_model.py</code> (+{" "}
          <code>download_stt_en_model.py</code> nếu dùng English/auto).
        </p>

        {/* Cấu hình engine — TTS + STT đối xứng */}
        <div className="text-xs font-semibold text-muted-foreground">🔊 Cấu hình đọc (TTS)</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div>
            <label className="text-xs text-muted-foreground">Backend đọc (TTS)</label>
            <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
              value={String(ttsCfg.backend || "auto")}
              onChange={(e) => patchVoice("tts", { backend: e.target.value })}>
              <option value="auto">Tự động (local trước, rồi Wyoming)</option>
              <option value="local">Chỉ local (Piper trong image)</option>
              <option value="wyoming">Chỉ Wyoming (server sẵn có)</option>
              <option value="off">Tắt</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Giọng đọc mặc định</label>
            <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
              value={String(ttsCfg.voice || tts?.voice || "")}
              onChange={(e) => patchVoice("tts", { voice: e.target.value })}>
              {catalog.length === 0 && <option value="">(chưa tải giọng nào)</option>}
              {catalog.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.id}{v.language_label ? ` · ${v.language_label}` : ""}{v.downloaded ? "" : " (chưa tải)"}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="text-xs text-muted-foreground">Wyoming TTS (tuỳ chọn)</label>
            <Input value={String(ttsCfg.wyoming_url || "")}
              onChange={(e) => patchVoice("tts", { wyoming_url: e.target.value })}
              placeholder="tcp://192.0.2.10:10200" />
          </div>
        </div>

        <div className="text-xs font-semibold text-muted-foreground pt-1">🎤 Cấu hình nghe (STT)</div>
        <div className="grid gap-2 sm:grid-cols-2 rounded-md border border-border/60 bg-muted/20 p-2.5">
          <div>
            <label className="text-xs text-muted-foreground">Backend nghe (STT)</label>
            <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
              value={String(sttCfg.backend || stt?.backend || "auto")}
              onChange={(e) => patchVoice("stt", { backend: e.target.value })}>
              <option value="auto">Tự động (local trước, rồi Wyoming)</option>
              <option value="local">Chỉ local (Zipformer / Parakeet)</option>
              <option value="wyoming">Chỉ Wyoming (server STT sẵn có)</option>
              <option value="off">Tắt</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">
              Ngôn ngữ STT (chatgpt2api — không theo HA Assist)
            </label>
            <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
              value={String(sttCfg.language || stt?.language || "vi")}
              onChange={(e) => patchVoice("stt", { language: e.target.value })}>
              <option value="vi">Tiếng Việt (vi) — Zipformer</option>
              <option value="en">English (en) — Parakeet</option>
              <option value="auto">Auto — thử VI rồi EN (cần cả 2 model)</option>
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="text-xs text-muted-foreground">Wyoming STT client (tuỳ chọn)</label>
            <Input value={String(sttCfg.wyoming_url || "")}
              onChange={(e) => patchVoice("stt", { wyoming_url: e.target.value })}
              placeholder="tcp://… (client; server nhúng đã có port riêng)" />
            <p className="text-[10px] text-muted-foreground mt-1">
              Ngôn ngữ STT do <b>chatgpt2api</b> quyết định (ô trên). Assist / Wyoming gửi
              language gì cũng bị bỏ qua. Chọn backend + ngôn ngữ → <b>Lưu cấu hình giọng nói</b>
              → nói thử (không cần Reload HA).
            </p>
          </div>
        </div>
        <div>
          <label className="text-xs text-muted-foreground">
            URL công khai của gateway (loa trong nhà kéo file từ đây — KHÔNG dùng localhost)
          </label>
          <Input value={String(voiceCfg.public_base_url || "")}
            onChange={(e) => setField("voice", { ...voiceCfg, public_base_url: e.target.value })}
            placeholder="http://IP-GATEWAY:3030" />
        </div>

        <Button onClick={async () => { await saveConfig(); toast.success("Đã lưu cấu hình giọng nói"); void load(); }}
          disabled={isSavingConfig} className="w-full" size="sm">
          <Save className="size-3.5 mr-1.5" />
          {isSavingConfig ? "Đang lưu..." : "Lưu cấu hình giọng nói"}
        </Button>

        <hr className="border-border" />

        {/* Nghe thử & chọn giọng */}
        <div className="text-sm font-semibold">🎧 Nghe thử &amp; chọn giọng ({catalog.length})</div>
        <p className="text-[10px] text-muted-foreground -mt-1">
          Bấm ▶️ để nghe một câu mẫu, thấy ưng thì bấm <b>Chọn</b> để đặt làm giọng
          mặc định. Giọng &quot;chưa tải&quot; cần chạy{" "}
          <code>python scripts/download_piper_voices.py --pack full</code> rồi tải lại trang.
        </p>
        <div className="grid gap-1.5 sm:grid-cols-2">
          {catalog.map((v) => {
            const active = String(ttsCfg.voice || tts?.voice || "") === v.id;
            return (
              <div key={v.id}
                className={`flex items-center gap-2 rounded-md border p-1.5 ${active ? "border-emerald-500 bg-emerald-500/10" : "border-border"}`}>
                <button type="button" title="Nghe thử"
                  className="shrink-0 text-emerald-500 disabled:opacity-40"
                  disabled={!v.downloaded || previewing === v.id}
                  onClick={() => void preview(v.id)}>
                  <PlayCircle className={`size-5 ${previewing === v.id ? "animate-pulse" : ""}`} />
                </button>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium truncate">
                    {v.id}{v.default ? " ⭐" : ""}
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    {v.language_label}{v.downloaded ? "" : " · chưa tải"}
                  </div>
                </div>
                {active ? (
                  <span className="text-[10px] text-emerald-500 font-semibold px-1">✓ đang dùng</span>
                ) : (
                  <Button type="button" variant="ghost" size="sm" className="h-6 text-[11px]"
                    disabled={!v.downloaded}
                    onClick={() => patchVoice("tts", { voice: v.id })}>
                    Chọn
                  </Button>
                )}
              </div>
            );
          })}
        </div>
        <p className="text-[10px] text-muted-foreground -mt-1">
          Sau khi bấm <b>Chọn</b>, nhớ bấm <b>Lưu cấu hình giọng nói</b> ở trên để áp dụng.
        </p>

        <hr className="border-border" />

        {/* Sổ loa */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold flex-1 min-w-full sm:min-w-0">📢 Loa đã kết nối ({rows.length})</span>
          <select className="rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
            value={scanKind} onChange={(e) => setScanKind(e.target.value)} title="Loại loa cần dò">
            <option value="all">Tất cả loại</option>
            <option value="cast">Google Cast</option>
            <option value="dlna">DLNA / UPnP</option>
            <option value="r1">Loa R1</option>
          </select>
          <Button type="button" variant="outline" size="sm" onClick={() => void discover()} disabled={scanning || busy}>
            <Radar className={`size-3.5 mr-1 ${scanning ? "animate-spin" : ""}`} /> {scanning ? "Đang dò..." : "Dò loa"}
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => void importHa()} disabled={busy}>
            <Download className="size-3.5 mr-1" /> Nhập từ Home Assistant
          </Button>
        </div>
        <p className="text-[10px] text-muted-foreground">
          Đặt tên loa như đặt tên người (vd &quot;loa phòng khách&quot;) để ra lệnh tự nhiên:
          &quot;phát ra loa phòng khách&quot;. Cast/DLNA/R1 nối thẳng bằng IP.
          <b> Dò loa</b> quét cổng cố định (Cast 8009, R1 2847) trong LAN — loa DLNA cổng động
          thì vẫn nhập tay hoặc nhập từ Home Assistant.
        </p>

        {/* Kết quả dò loa: bấm ➕ để thêm nhanh */}
        {found.length > 0 && (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/5 p-2 space-y-1.5">
            <div className="text-[11px] font-semibold text-emerald-600">🔎 Tìm thấy {found.length} loa — bấm ➕ để thêm</div>
            {found.map((f) => (
              <div key={`${f.host}:${f.port}`} className="flex items-center gap-2 text-xs">
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]">{KIND_LABEL[f.kind] || f.kind}</span>
                <span className="flex-1 min-w-0 truncate">{f.name} · <code className="text-[10px]">{f.host}:{f.port}</code></span>
                {f.known
                  ? <span className="text-[10px] text-muted-foreground px-1">đã có</span>
                  : <Button type="button" variant="ghost" size="sm" className="h-6" onClick={() => void addFound(f)} disabled={busy}>
                      <Plus className="size-3.5" />
                    </Button>}
              </div>
            ))}
          </div>
        )}

        <div className="space-y-2">
          {rows.map((r) => (
            <div key={r.id} className="rounded-md border border-border p-2 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold min-w-32">{r.name}</span>
              <span className="text-[10px] rounded bg-muted px-1.5 py-0.5">{KIND_LABEL[r.kind] || r.kind}</span>
              <code className="text-[10px] flex-1 break-all text-muted-foreground">
                {r.kind === "ha" ? r.entity_id : r.host}
              </code>
              {r.kind === "cast" && (
                <span className="flex items-center gap-1" title="Âm lượng (kéo rồi thả — lưu làm mặc định)">
                  <Volume2 className="size-3.5 text-muted-foreground" />
                  <input type="range" min={0} max={100} defaultValue={55}
                    className="w-20 accent-primary"
                    onMouseUp={(e) => void setVol(r.id, Number((e.target as HTMLInputElement).value))}
                    onTouchEnd={(e) => void setVol(r.id, Number((e.target as HTMLInputElement).value))} />
                </span>
              )}
              {r.kind === "cast" && (
                <>
                  <Button type="button" variant="ghost" size="sm" title="Bật (đánh thức loa)"
                    onClick={() => void ctl(r.id, "on")} disabled={busy}>⏻</Button>
                  <Button type="button" variant="ghost" size="sm" title="Dừng phát"
                    onClick={() => void ctl(r.id, "stop")} disabled={busy}>⏹</Button>
                  <Button type="button" variant="ghost" size="sm" title="Tắt (thoát app đang cast)"
                    onClick={() => void ctl(r.id, "off")} disabled={busy}>🔌</Button>
                </>
              )}
              {r.kind === "r1" && (
                <>
                  <span className="flex items-center gap-1" title="Âm lượng R1 (kéo rồi thả)">
                    <Volume2 className="size-3.5 text-muted-foreground" />
                    <input type="range" min={0} max={100} defaultValue={40}
                      className="w-20 accent-primary"
                      onMouseUp={(e) => void setVol(r.id, Number((e.target as HTMLInputElement).value))}
                      onTouchEnd={(e) => void setVol(r.id, Number((e.target as HTMLInputElement).value))} />
                  </span>
                  <Button type="button" variant="ghost" size="sm" title="Mở nhạc theo yêu cầu (YouTube)"
                    onClick={() => void playMusic(r.id)} disabled={busy}>
                    <Music className="size-3.5" />
                  </Button>
                  <Button type="button" variant="ghost" size="sm" title="Dừng phát"
                    onClick={() => void ctl(r.id, "stop")} disabled={busy}>⏹</Button>
                </>
              )}
              <Button type="button" variant="ghost" size="sm" onClick={() => void act(r.id, "test")} disabled={busy}>
                <PlugZap className="size-3.5" />
              </Button>
              {r.kind !== "r1" && (
                <Button type="button" variant="ghost" size="sm" onClick={() => void act(r.id, "play")} disabled={busy}
                  title="Đọc thử một câu">
                  <PlayCircle className="size-3.5" />
                </Button>
              )}
              <Button type="button" variant="ghost" size="sm" onClick={() => void act(r.id, "delete")} disabled={busy}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
          {rows.length === 0 && (
            <p className="text-[11px] text-muted-foreground italic">Chưa có loa nào — thêm bên dưới.</p>
          )}
        </div>

        {/* Hẹn giờ thông báo ra loa */}
        {rows.length > 0 && (
          <div className="rounded-md border border-dashed border-border p-2 space-y-2">
            <div className="text-xs font-medium">⏰ Hẹn giờ đọc thông báo ra loa</div>
            <div className="grid gap-2 sm:grid-cols-2">
              <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                value={ann.speaker} onChange={(e) => setAnn({ ...ann, speaker: e.target.value })}>
                <option value="">— chọn loa —</option>
                {rows.filter((r) => r.kind !== "r1").map((r) => (
                  <option key={r.id} value={r.name}>{r.name}</option>
                ))}
              </select>
              <Input value={ann.text} onChange={(e) => setAnn({ ...ann, text: e.target.value })}
                placeholder="Nội dung (vd: kiểm tra loa)" />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-[11px] text-muted-foreground flex items-center gap-1">
                Sau
                <input type="number" min={0} step={1} value={ann.delayMin}
                  onChange={(e) => setAnn({ ...ann, delayMin: Number(e.target.value) })}
                  className="w-16 rounded-md border border-border bg-background px-2 py-1 text-xs" /> phút
              </label>
              <label className="text-[11px] text-muted-foreground flex items-center gap-1">
                Âm lượng
                <input type="number" min={0} max={100} step={5} value={ann.volPct}
                  onChange={(e) => setAnn({ ...ann, volPct: Number(e.target.value) })}
                  className="w-16 rounded-md border border-border bg-background px-2 py-1 text-xs" /> %
              </label>
              <Button type="button" variant="outline" size="sm" className="ml-auto"
                onClick={() => void sendAnnounce()} disabled={busy}>
                {Number(ann.delayMin) > 0 ? "Hẹn giờ" : "Đọc ngay"}
              </Button>
            </div>
            <p className="text-[10px] text-muted-foreground -mt-1">
              Đọc bằng giọng TTS ra loa Cast/DLNA/HA. Âm lượng chỉ áp cho loa Cast.
              Bộ hẹn nhẹ trong RAM — khởi động lại app thì mất hẹn đang chờ.
            </p>
          </div>
        )}

        {/* Thêm loa */}
        <div className="rounded-md border border-dashed border-border p-2 space-y-2">
          <div className="text-xs font-medium">➕ Thêm loa</div>
          <div className="grid gap-2 sm:grid-cols-3">
            <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="Tên loa (vd: loa phòng khách)" />
            <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
              value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
              <option value="cast">Google Cast</option>
              <option value="dlna">DLNA / UPnP</option>
              <option value="r1">Loa R1 (Phicomm)</option>
              <option value="ha">Qua Home Assistant</option>
            </select>
            {draft.kind === "ha" ? (
              <Input value={draft.entity_id || ""} onChange={(e) => setDraft({ ...draft, entity_id: e.target.value })}
                placeholder="media_player.phong_khach" />
            ) : (
              <Input value={draft.host || ""} onChange={(e) => setDraft({ ...draft, host: e.target.value })}
                placeholder={draft.kind === "cast" ? "IP loa Cast"
                  : draft.kind === "r1" ? "IP loa R1 (vd 192.168.1.50)"
                  : "http://IP:PORT/ của loa DLNA"} />
            )}
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => void addSpeaker()} disabled={busy}>
            Thêm loa
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
