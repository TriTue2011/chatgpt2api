"use client";

/**
 * VoiceScopeInline — cấu hình GIỌNG NÓI theo từng phạm vi (kênh / bot / nhóm /
 * user-trong-nhóm / admin / cá nhân). Lưu RIÊNG ở voice_sessions.json qua
 * /api/voice/session-config (KHÁC config thread_filters). `sessionKey` phải
 * đúng dạng dispatcher tra: 'plat:bot:chat' hoặc 'plat:bot:chat:user'
 * (plat = tg | zalo | zalop).
 *
 *   • 🔊 Giọng đọc  : CHỈ hiện khi bật «Trả lời bằng giọng nói» (tts_reply).
 *     Bỏ trống = theo persona; chọn giọng = ép giọng ĐỌC (giọng VĂN vẫn theo
 *     persona đang bật).
 *   • 🔇 Tắt giọng nói (TTS): chặn hẳn voice-reply cho phạm vi này.
 *   • 🎙️ STT tiếng Anh: nghe thoại bằng tiếng Anh (bỏ = tiếng Việt mặc định).
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { request } from "@/lib/request";

type VoiceItem = { id: string; language_label?: string; downloaded?: boolean };

// Catalog giọng: tải 1 lần, chia sẻ cho mọi instance.
let _voiceCache: VoiceItem[] | null = null;

const SEL_XS = "h-6 rounded border border-input bg-background px-1 text-[11px]";

export function VoiceScopeInline({ sessionKey, showVoicePicker = false }: {
  sessionKey: string; showVoicePicker?: boolean;
}) {
  const key = (sessionKey || "").trim();
  const [voices, setVoices] = useState<VoiceItem[]>(_voiceCache || []);
  const [voice, setVoice] = useState("");
  const [ttsOff, setTtsOff] = useState(false);
  const [sttEn, setSttEn] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (_voiceCache) return;
    request.get("/api/voice/catalog").then((r) => {
      _voiceCache = ((r.data?.voices || []) as VoiceItem[]).filter((v) => v.downloaded);
      setVoices(_voiceCache);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!key) { setLoaded(true); return; }
    request.get(`/api/voice/session-config?key=${encodeURIComponent(key)}`).then((r) => {
      const c = (r.data?.config || {}) as Record<string, unknown>;
      setVoice(String(c.tts_voice || ""));
      setTtsOff(c.tts_enabled === false);
      setSttEn(String(c.stt_language || "") === "en");
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, [key]);

  const save = useCallback((patch: Record<string, unknown>) => {
    if (!key) return;
    request.post("/api/voice/session-config", { key, ...patch })
      .catch(() => toast.error("Lưu cấu hình giọng thất bại"));
  }, [key]);

  if (!key || !loaded) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
      {showVoicePicker && (
        <label className="flex items-center gap-1">
          🔊 Giọng đọc:
          <select
            className={SEL_XS}
            value={voice}
            onChange={(e) => { setVoice(e.target.value); save({ tts_voice: e.target.value }); }}
          >
            <option value="">(theo persona)</option>
            {voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.id}{v.language_label ? ` · ${v.language_label}` : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="flex cursor-pointer items-center gap-1 select-none">
        <input type="checkbox" checked={ttsOff}
               onChange={(e) => { setTtsOff(e.target.checked); save({ tts_enabled: !e.target.checked }); }} />
        🔇 Tắt giọng nói (TTS)
      </label>
      <label className="flex cursor-pointer items-center gap-1 select-none">
        <input type="checkbox" checked={sttEn}
               onChange={(e) => { setSttEn(e.target.checked); save({ stt_language: e.target.checked ? "en" : "vi" }); }} />
        🎙️ STT: nghe tiếng Anh
      </label>
    </div>
  );
}
