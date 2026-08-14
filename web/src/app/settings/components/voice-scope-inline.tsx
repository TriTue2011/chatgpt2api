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
 *   • 🎙️ Tiếng nghe: chọn MỘT hoặc NHIỀU tiếng cho phạm vi này (14/08). Một
 *     tiếng = khoá cứng, nhanh và chuẩn nhất. Hai tiếng = máy dò bằng độ tự tin
 *     giải mã (đo thật: model đúng tiếng ~-0,04 so với model sai ~-0,5). Ba
 *     tiếng trở lên = mỗi tiếng thêm MỘT lượt nghe (chậm gấp N) và biên an toàn
 *     hẹp lại — UI phải nói thẳng, không để người dùng tự vỡ mặt.
 *     Bỏ hết = theo cài đặt của tính năng (voice.dung_cho.<tên>.stt_tieng).
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { request } from "@/lib/request";

type VoiceItem = { id: string; language_label?: string; downloaded?: boolean };

// Catalog giọng: tải 1 lần, chia sẻ cho mọi instance.
let _voiceCache: VoiceItem[] | null = null;

const SEL_XS = "h-6 rounded border border-input bg-background px-1 text-[11px]";

/** Tiếng có model nghe. Một tiếng = khoá cứng (nhanh, chuẩn nhất). */
const TIENG: [string, string][] = [
  ["vi", "Việt"], ["en", "Anh"], ["ja", "Nhật"], ["zh", "Trung"], ["ko", "Hàn"],
];

export function VoiceScopeInline({ sessionKey, showVoicePicker = false }: {
  sessionKey: string; showVoicePicker?: boolean;
}) {
  const key = (sessionKey || "").trim();
  const [voices, setVoices] = useState<VoiceItem[]>(_voiceCache || []);
  const [voice, setVoice] = useState("");
  const [ttsOff, setTtsOff] = useState(false);
  const [tieng, setTieng] = useState<string[]>([]);
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
      // Bản cũ chỉ có stt_language ("en"/"vi") — đọc lên thành danh sách một phần tử.
      const nhom = String(c.stt_nhom_tieng || c.stt_language || "")
        .split(",").map((x) => x.trim()).filter((x) => x && x !== "auto");
      setTieng(nhom);
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
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        🎙️ Tiếng nghe:
        {TIENG.map(([ma, ten]) => (
          <label key={ma} className="flex cursor-pointer items-center gap-1 select-none">
            <input type="checkbox" checked={tieng.includes(ma)}
                   onChange={(e) => {
                     const moi = e.target.checked
                       ? [...tieng, ma]
                       : tieng.filter((x) => x !== ma);
                     setTieng(moi);
                     // Lưu cả stt_language cho bản cũ đọc được (một tiếng đầu).
                     save({ stt_nhom_tieng: moi.join(","),
                            stt_language: moi[0] || "" });
                   }} />
            {ten}
          </label>
        ))}
        {tieng.length === 0 && <span className="opacity-70">(theo cài đặt tính năng)</span>}
        {tieng.length >= 3 && (
          <span className="text-amber-600 dark:text-amber-500">
            ⚠️ {tieng.length} tiếng = {tieng.length} lượt nghe mỗi lần (chậm gấp {tieng.length}) và dễ nhận sai hơn
          </span>
        )}
      </span>
    </div>
  );
}
