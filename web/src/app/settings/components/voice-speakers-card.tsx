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
  // Giọng RIÊNG của loa này. Rỗng = theo giọng của kênh/thread/topic, không có
  // nữa thì giọng hệ thống. Xem services/voice/__init__.py: giong_cho_loa().
  voice?: string;
};

type Found = { host: string; port: number; kind: string; name: string; known?: boolean; control_url?: string };

type VoiceStatus = {
  tts?: { enabled?: boolean; backend?: string; voice?: string; model_ready?: boolean;
          piper_bin?: string; local_voices?: string[]; wyoming_url?: string };
  stt?: { enabled?: boolean; backend?: string; model_ready?: boolean;
          en_model_ready?: boolean; language?: string;
          sherpa_installed?: boolean; wyoming_url?: string;
          them_ready?: Record<string, boolean> };
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
  // Nghe thử: chọn giọng ở dropdown + tự nhập đoạn muốn nghe (có sẵn câu mẫu).
  const [tryVoice, setTryVoice] = useState("");
  const SAMPLE_VI = "Xin chào, đây là giọng đọc thử của trợ lý. Bạn nghe rõ và thấy tự nhiên chứ ạ?";
  const [tryText, setTryText] = useState(SAMPLE_VI);
  const [found, setFound] = useState<Found[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanKind, setScanKind] = useState("all");
  // Dải mạng cần quét (vd "172.16.10"). Trống = tự suy từ URL Home Assistant /
  // gateway trong cấu hình — cần vì gateway chạy trong Docker bridge nên IP
  // riêng của nó (172.19.0.x) KHÔNG phải dải LAN thật.
  const [scanSubnet, setScanSubnet] = useState("");
  // media_player từ HA — dropdown chọn entity khi thêm loa kiểu 'ha'
  const [haPlayers, setHaPlayers] = useState<{ entity_id: string; name: string }[]>([]);
  // Hẹn giờ thông báo ra loa
  const [ann, setAnn] = useState({ speaker: "", text: "", delayMin: 1, volPct: 20, when: "" });

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
    // Tách riêng: HA chưa cấu hình thì list rỗng, không chặn phần trên
    try {
      const mp = await request.get("/api/voice/ha-media-players");
      setHaPlayers(((mp.data as { rows?: { entity_id: string; name: string }[] })?.rows) || []);
    } catch { /* noop */ }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Nghe thử theo DÒNG CHẢY: chữ tổng hợp tới đâu phát tới đó (stream=1) nên nghe
  // gần như tức thì thay vì chờ ~3-4s tổng hợp trọn câu. Thẻ <audio> không gửi
  // được header nên đính token qua query `key=` (giống tab Chat).
  const preview = async (voiceId: string, text?: string) => {
    setPreviewing(voiceId);
    try {
      const { getStoredAuthKey } = await import("@/store/auth");
      let key = await getStoredAuthKey();
      if (!key) { try { key = localStorage.getItem("chatgpt2api_auth_key") || ""; } catch { /* noop */ } }
      const say = (text || "").trim();
      const url = `/api/voice/preview?stream=1&voice=${encodeURIComponent(voiceId)}`
        + (say ? `&text=${encodeURIComponent(say.slice(0, 600))}` : "")
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

  const wyCfg = (voiceCfg.wyoming_server as Record<string, unknown>) || {};

  const patchVoice = (section: "tts" | "stt" | "wyoming_server",
                      patch: Record<string, unknown>) => {
    const base = section === "tts" ? ttsCfg : section === "stt" ? sttCfg : wyCfg;
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

  // Giọng riêng cho MỘT loa. Để trống = loa không có ý kiến, tầng dưới rơi xuống
  // giọng theo kênh/thread/topic rồi giọng hệ thống.
  const setGiongLoa = async (id: string, voice: string) => {
    try {
      await request.patch(`/api/voice/speakers/${id}`, { voice });
      setRows((prev) => prev.map((r) => (r.id === id ? { ...r, voice } : r)));
      toast.success(voice ? `Giọng riêng: ${voice}` : "Theo giọng kênh/thread");
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
      const r = await request.post(
        `/api/voice/discover?kind=${encodeURIComponent(scanKind)}`
        + (scanSubnet.trim() ? `&subnet=${encodeURIComponent(scanSubnet.trim())}` : ""), {});
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

  // Đọc ngay / hẹn sau N phút / ĐẶT LỊCH (mốc giờ-ngày, lịch lặp).
  // Có `when` → ghi vào SQLite, sống qua khởi động lại. Không có → bộ hẹn nhẹ
  // trong RAM như cũ.
  const sendAnnounce = async () => {
    if (!ann.speaker.trim() || !ann.text.trim()) {
      toast.error("Chọn loa và nhập nội dung thông báo"); return;
    }
    setBusy(true);
    try {
      const when = ann.when.trim();
      const r = await request.post("/api/voice/announce", {
        speaker: ann.speaker.trim(), text: ann.text.trim(),
        when,
        delay_seconds: when ? 0 : Math.max(0, Number(ann.delayMin) || 0) * 60,
        volume: Number(ann.volPct),
      });
      const lich = (r.data as { lich?: { khi?: string } })?.lich;
      toast.success(lich
        ? `Đã đặt lịch ${lich.khi || when} ra ${ann.speaker}`
        : Number(ann.delayMin) > 0
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
          Model KHÔNG nằm trong image — tải một lần về volume (giữ qua mọi lần update).
          Chạy trong container: <code>docker exec c2a /app/.venv/bin/python
          /app/scripts/download_vieneu_model.py</code> (giọng VieNeu) ·{" "}
          <code>…/download_stt_model.py --hf</code> (nghe tiếng Việt) ·{" "}
          <code>…/download_stt_en_model.py</code> (nghe tiếng Anh). Chi tiết:
          HUONG_DAN_GIONG_NOI_VA_KENH.md.
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

          {/* Giọng THEO TIẾNG — dùng cho phiên dịch đàm thoại (tab Dịch) và
              các cổng Wyoming khoá tiếng bên dưới. Kokoro EN: 11 giọng của
              gói kokoro-en-v0_19; Trung: Kokoro đa ngữ v1.1 (100 giọng, sid
              0–102); Nhật/Hàn: Supertonic (sid 0–4 nam M1-M5, 5–9 nữ F1-F5). */}
          <div className="sm:col-span-2 grid gap-2 sm:grid-cols-4 rounded-md border border-border/60 bg-muted/20 p-2.5">
            <div className="sm:col-span-4 text-xs font-medium">Giọng theo tiếng (đàm thoại + Wyoming)</div>
            <div>
              <label className="text-xs text-muted-foreground">Tiếng Anh (Kokoro)</label>
              <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                value={String(wyCfg.en_voice || "")}
                onChange={(e) => patchVoice("wyoming_server", { en_voice: e.target.value })}>
                <option value="">af (mặc định)</option>
                {["af", "af_bella", "af_nicole", "af_sarah", "af_sky",
                  "am_adam", "am_michael", "bf_emma", "bf_isabella",
                  "bm_george", "bm_lewis"].map((n) => (
                  <option key={n} value={`kokoro:${n}`}>{n}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Tiếng Trung (sid 0–102)</label>
              <Input type="number" min={0} max={102}
                value={String(ttsCfg.kokoro_zh_sid ?? "")}
                onChange={(e) => patchVoice("tts", {
                  kokoro_zh_sid: e.target.value === "" ? "" : Number(e.target.value),
                })}
                placeholder="0" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Tiếng Nhật (sid 0–9)</label>
              <Input type="number" min={0} max={9}
                value={String(ttsCfg.supertonic_ja_sid ?? "")}
                onChange={(e) => patchVoice("tts", {
                  supertonic_ja_sid: e.target.value === "" ? "" : Number(e.target.value),
                })}
                placeholder="0" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Tiếng Hàn (sid 0–9)</label>
              <Input type="number" min={0} max={9}
                value={String(ttsCfg.supertonic_ko_sid ?? "")}
                onChange={(e) => patchVoice("tts", {
                  supertonic_ko_sid: e.target.value === "" ? "" : Number(e.target.value),
                })}
                placeholder="0" />
            </div>
            {/* Quy chuẩn cổng Wyoming cho HA (chốt 14/08): 106xx = TTS,
                107xx = STT; xx = 00 việt · 01 anh · 02 nhật · 03 trung ·
                04 hàn. Trống = theo chuẩn (BẬT nếu có model), 0 = tắt.
                Nhớ publish cổng trong compose. */}
            <div className="sm:col-span-4 text-xs font-medium">
              Cổng Wyoming cho HA — 106xx đọc (TTS), 107xx nghe (STT) · việt/anh/nhật/trung/hàn · trống = chuẩn, 0 = tắt
            </div>
            {(["tts", "stt"] as const).map((vai) => (
              <div key={vai} className="sm:col-span-4 grid grid-cols-5 gap-2">
                {(["vi", "en", "ja", "zh", "ko"] as const).map((lng, i) => (
                  <div key={`${vai}_${lng}`}>
                    <label className="text-xs text-muted-foreground">
                      {vai === "tts" ? "Đọc" : "Nghe"} {{ vi: "Việt", en: "Anh", ja: "Nhật", zh: "Trung", ko: "Hàn" }[lng]}
                    </label>
                    <Input type="number" min={0} max={65535}
                      value={String(wyCfg[`${vai}_port_${lng}`] ?? "")}
                      onChange={(e) => patchVoice("wyoming_server", {
                        [`${vai}_port_${lng}`]: e.target.value === "" ? "" : Number(e.target.value),
                      })}
                      placeholder={String((vai === "tts" ? 10600 : 10700) + i)} />
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* Nhịp nghỉ khi đọc — áp cho mọi engine, xem services/voice/engines.py */}
          <div className="sm:col-span-2 grid gap-2 sm:grid-cols-3 rounded-md border border-border/60 bg-muted/20 p-2.5">
            <div>
              <label className="text-xs text-muted-foreground">Nghỉ giữa hai câu (ms)</label>
              <Input type="number" min={0} max={3000} step={10}
                value={String(ttsCfg.sentence_silence_ms ?? "")}
                onChange={(e) => patchVoice("tts", {
                  sentence_silence_ms: e.target.value === "" ? "" : Number(e.target.value),
                })}
                placeholder="350 (mặc định)" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Nghỉ sau dấu phẩy (ms)</label>
              <Input type="number" min={0} max={3000} step={10}
                value={String(ttsCfg.clause_silence_ms ?? "")}
                onChange={(e) => patchVoice("tts", {
                  clause_silence_ms: e.target.value === "" ? "" : Number(e.target.value),
                })}
                placeholder="0 = tắt (thử 180)" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Dao động ngẫu nhiên (%)</label>
              <Input type="number" min={0} max={100} step={5}
                value={String(ttsCfg.silence_jitter_percent ?? "")}
                onChange={(e) => patchVoice("tts", {
                  silence_jitter_percent: e.target.value === "" ? "" : Number(e.target.value),
                })}
                placeholder="25 (mặc định)" />
            </div>
            <p className="sm:col-span-3 text-[10px] text-muted-foreground">
              Áp cho <b>mọi giọng</b> (VieNeu, NghiTTS, Piper, Kokoro, Wyoming): văn bản được
              cắt thành mẩu, mỗi mẩu đọc một lần rồi nối lại bằng khoảng lặng. Nghỉ sau dấu
              phẩy &gt; 0 cho nhịp rõ hơn nhưng đọc lâu hơn và ngữ điệu từng mệnh đề tách rời
              nhau — thấy gượng thì để 0. Cả hai ô nghỉ = 0 → đọc trọn đoạn trong một lần,
              nhanh nhất và liền mạch nhất. Dao động rải ngẫu nhiên ±% quanh mỗi khoảng nghỉ
              để nhịp không đều tăm tắp như máy đếm. Số trong ngoặc chỉ là gợi ý — ô trống
              nghĩa là dùng mặc định.
            </p>
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
            {/* Cổng bật EN nằm ở backend (stt.en_enabled) — không có ô này thì
                chọn en/auto ở trên vẫn tự rơi về tiếng Việt, dễ tưởng là hỏng. */}
            <label className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
              <input type="checkbox" className="size-3.5"
                checked={Boolean(sttCfg.en_enabled)}
                onChange={() => patchVoice("stt", { en_enabled: !sttCfg.en_enabled })} />
              🇬🇧 Bật STT tiếng Anh (Parakeet)
              {stt?.en_model_ready ? "" : " — chưa tải model (mục tải bên dưới)"}
            </label>
            {/* Model nghe theo tiếng: có model = cổng Wyoming 107xx tự mở.
                Không có ô bật/tắt riêng — nghe không có "giọng" để chọn. */}
            <div className="mt-1 text-[11px] text-muted-foreground">
              Model nghe:{" "}
              {([["vi", stt?.model_ready], ["en", stt?.en_model_ready],
                 ["ja", stt?.them_ready?.ja], ["zh", stt?.them_ready?.zh],
                 ["ko", stt?.them_ready?.ko]] as [string, boolean | undefined][])
                .map(([l, ok]) => `${l} ${ok ? "✓" : "✗"}`).join(" · ")}
              {" "}(✗ = tải bằng scripts/download_stt_da_ngu.py)
            </div>
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

        {/* Nghe thử & chọn giọng — dropdown + đoạn tự nhập */}
        {(() => {
          const current = String(ttsCfg.voice || tts?.voice || "");
          // Giọng đang chọn để nghe thử: ưu tiên lựa chọn tay, rồi giọng đang
          // dùng, cuối cùng là giọng đầu tiên đã tải về.
          const pick = tryVoice
            || (catalog.some((v) => v.id === current && v.downloaded) ? current : "")
            || (catalog.find((v) => v.downloaded)?.id || "");
          const picked = catalog.find((v) => v.id === pick);
          const ready = Boolean(picked?.downloaded);
          const isActive = pick === current;
          return (
            <>
              <div className="text-sm font-semibold">🎧 Nghe thử &amp; chọn giọng ({catalog.length})</div>
              <p className="text-[10px] text-muted-foreground -mt-1">
                Chọn giọng, sửa đoạn muốn nghe rồi bấm ▶️ — giọng đó sẽ đọc đúng
                đoạn trong ô. Ưng thì bấm <b>Chọn làm giọng mặc định</b>.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  className="h-9 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs"
                  value={pick} onChange={(e) => setTryVoice(e.target.value)}
                  title="Giọng cần nghe thử">
                  {catalog.length === 0 ? <option value="">(chưa có giọng nào)</option> : null}
                  {catalog.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.id}{v.default ? " ⭐" : ""} · {v.language_label}
                      {v.downloaded ? "" : " · chưa tải"}
                      {v.id === current ? " · đang dùng" : ""}
                    </option>
                  ))}
                </select>
                <button type="button" title="Nghe thử đoạn trong ô"
                  className="shrink-0 text-emerald-500 disabled:opacity-40"
                  disabled={!ready || !tryText.trim() || previewing === pick}
                  onClick={() => void preview(pick, tryText)}>
                  <PlayCircle className={`size-7 ${previewing === pick ? "animate-pulse" : ""}`} />
                </button>
                {isActive ? (
                  <span className="text-[11px] text-emerald-500 font-semibold shrink-0">✓ đang dùng</span>
                ) : (
                  <Button type="button" variant="outline" size="sm" className="h-8 text-[11px] shrink-0"
                    disabled={!ready}
                    onClick={() => patchVoice("tts", { voice: pick })}>
                    Chọn làm giọng mặc định
                  </Button>
                )}
              </div>
              <textarea
                className="w-full rounded-md border border-border bg-background p-2 text-xs"
                rows={2} maxLength={600} value={tryText}
                onChange={(e) => setTryText(e.target.value)}
                placeholder="Nhập đoạn muốn nghe thử…" />
              <div className="flex flex-wrap items-center gap-2 -mt-1">
                <button type="button"
                  className="text-[10px] text-muted-foreground underline"
                  onClick={() => setTryText(SAMPLE_VI)}>Dùng câu mẫu</button>
                <span className="text-[10px] text-muted-foreground">{tryText.length}/600</span>
                {!ready && pick ? (
                  <span className="text-[10px] text-amber-500">
                    Giọng này chưa tải — chạy{" "}
                    <code>python scripts/download_piper_voices.py --pack full</code>
                  </span>
                ) : null}
              </div>
              <p className="text-[10px] text-muted-foreground -mt-1">
                Sau khi bấm <b>Chọn làm giọng mặc định</b>, nhớ bấm <b>Lưu cấu hình
                giọng nói</b> ở trên để áp dụng.
              </p>
            </>
          );
        })()}

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
          <Input value={scanSubnet} onChange={(e) => setScanSubnet(e.target.value)}
            className="h-9 w-32 text-xs" placeholder="Dải: 172.16.10"
            title="Dải mạng cần quét (trống = tự suy từ URL Home Assistant/gateway)" />
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
              <select
                className="rounded-md border border-border bg-background px-1.5 py-1 text-[10px] h-7 max-w-40"
                title="Giọng riêng của loa này. Để trống = theo giọng đã cài cho kênh / nhóm / topic, không có nữa thì giọng hệ thống."
                value={r.voice || ""}
                onChange={(e) => void setGiongLoa(r.id, e.target.value)}>
                <option value="">Giọng theo kênh/thread</option>
                {catalog.filter((v) => v.downloaded).map((v) => (
                  <option key={v.id} value={v.id}>{v.id} · {v.language_label}</option>
                ))}
              </select>
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
                Lịch
                <input value={ann.when} placeholder="8h sáng mai / mỗi ngày 6h"
                  onChange={(e) => setAnn({ ...ann, when: e.target.value })}
                  title="Điền mốc giờ-ngày hoặc lịch lặp → lưu vào DB, sống qua khởi động lại. Để trống thì dùng ô 'Sau … phút' (hẹn nhẹ trong RAM)."
                  className="w-44 rounded-md border border-border bg-background px-2 py-1 text-xs" />
              </label>
              <label className="text-[11px] text-muted-foreground flex items-center gap-1">
                Sau
                <input type="number" min={0} step={1} value={ann.delayMin}
                  disabled={!!ann.when.trim()}
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
                {ann.when.trim() ? "Đặt lịch" : Number(ann.delayMin) > 0 ? "Hẹn giờ" : "Đọc ngay"}
              </Button>
            </div>
            <p className="text-[10px] text-muted-foreground -mt-1">
              Đọc bằng giọng TTS ra loa Cast/DLNA/HA. Âm lượng chỉ áp cho loa Cast, và
              phát xong tự trả về mức cũ.
              <br />
              Ô <b>Lịch</b>: tiếng được đọc sẵn rồi lưu file, lịch ghi vào DB nên
              sống qua khởi động lại — xem/huỷ ở phần nhắc hẹn. Để trống ô đó thì
              ô <b>Sau … phút</b> là bộ hẹn nhẹ trong RAM, khởi động lại là mất.
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
              haPlayers.length > 0 ? (
                /* Dropdown media_player lấy THẲNG từ HA — khỏi gõ entity_id tay */
                <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                  value={draft.entity_id || ""}
                  onChange={(e) => {
                    const eid = e.target.value;
                    const hit = haPlayers.find((p) => p.entity_id === eid);
                    setDraft({ ...draft, entity_id: eid,
                      name: draft.name.trim() ? draft.name : (hit?.name || "") });
                  }}>
                  <option value="">— chọn media_player từ HA —</option>
                  {haPlayers.map((p) => (
                    <option key={p.entity_id} value={p.entity_id}>
                      {p.name} · {p.entity_id}
                    </option>
                  ))}
                </select>
              ) : (
                /* HA chưa kết nối / 0 media_player → mới phải gõ tay */
                <Input value={draft.entity_id || ""} onChange={(e) => setDraft({ ...draft, entity_id: e.target.value })}
                  placeholder="media_player.phong_khach (HA chưa kết nối nên phải gõ tay)" />
              )
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
