"use client";

import { PersonaInline } from "./personas-card";

import { useEffect, useRef, useState } from "react";
import { Save, MessageCircle, Cloud } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { request } from "@/lib/request";
import { ChannelActivityPanel } from "@/components/channel-activity";
import { ZaloPersonalPanel } from "./zalo-personal-panel";
import { useSettingsStore } from "../store";

// Nhóm chức năng cho bộ lọc theo thread — PHẢI khớp capabilities._CAP_GROUP
// + _FLOW_GROUPS (backend). rag/word/summary gác luồng PDF/tài liệu của bot.
const FUNCTION_GROUPS: [string, string][] = [
  ["homeassistant", "🏠 Nhà (HA)"],
  ["server", "🖥️ Server"],
  ["image", "🎨 Ảnh"],
  ["video", "🎬 Video"],
  ["music", "🎵 Nhạc"],
  ["web", "🌐 Web"],
  ["code", "💻 Code"],
  ["memory", "🧠 Ghi nhớ"],
  ["rag", "📚 RAG / tài liệu"],
  ["word", "📝 PDF → Word"],
  ["summary", "🧾 Tổng hợp thông tin"],
  ["schedule", "⏰ Nhắc hẹn / định kỳ"],
  ["skills", "🧩 Skill / Workflow"],
  ["wiki", "📖 Wiki / Ingest"],
  ["contacts", "📒 Danh bạ / gửi tin"],
  ["tts_reply", "🔉 Trả lời bằng giọng nói"],
  ["tts_speaker", "📢 Được ra lệnh phát loa"],
  ["teacher", "📚 Giáo viên (tiểu học · THCS · THPT)"],
];

type AdminEntry = {
  chat_id: string;
  name: string;
  kind: "private" | "group";
  /** Model / nền tảng AI riêng từng admin (vd. AI text, chatgpt/…) */
  ai_model: string;
  notify_enabled: boolean;
  account_log_enabled: boolean;
  account_update_log_enabled: boolean;
  newchat_alert_enabled: boolean;
  ha_fastpath: boolean;
  fallback_enabled: boolean;
  emphasis_enabled: boolean;
  emphasis_numbers: boolean;
  emphasis_units: boolean;
  emphasis_key_info: boolean;
  emphasis_style: string;
  /** Zalo Bot only: red|orange|yellow|green|none (Tele không có màu) */
  markdown_color: string;
  /** Zalo Bot only: normal|big → {big} trong markdown */
  markdown_size: string;
};

function emptyAdmin(partial?: Partial<AdminEntry>): AdminEntry {
  return {
    chat_id: "", name: "", kind: "private", ai_model: "",
    notify_enabled: true, account_log_enabled: true,
    account_update_log_enabled: false,
    newchat_alert_enabled: true, ha_fastpath: true, fallback_enabled: false,
    emphasis_enabled: true, emphasis_numbers: true,
    emphasis_units: true, emphasis_key_info: true, emphasis_style: "bold",
    markdown_color: "orange", markdown_size: "normal",
    ...partial,
  };
}

type FallbackOpt = { value: string; label: string; channel: string };

function guessKind(chatId: string): "private" | "group" {
  const s = String(chatId || "").trim();
  if (s.startsWith("-100") || (s.startsWith("-") && /^\-\d+$/.test(s))) return "group";
  return "private";
}

function parseAdminEntries(b: any): AdminEntry[] {
  const out: AdminEntry[] = [];
  const seen = new Set<string>();
  const push = (e: Partial<AdminEntry> & { chat_id?: string }) => {
    const cid = String(e.chat_id || "").trim();
    if (cid && seen.has(cid)) return;
    if (cid) seen.add(cid);
    const k = String(e.kind || "").toLowerCase();
    out.push(emptyAdmin({
      chat_id: cid,
      name: String(e.name || "").trim(),
      kind: k === "group" || k === "1" ? "group"
        : k === "private" || k === "0" ? "private"
        : (cid ? guessKind(cid) : "private"),
      ai_model: String(e.ai_model || "").trim(),
      notify_enabled: e.notify_enabled !== false,
      account_log_enabled: e.account_log_enabled !== false,
      account_update_log_enabled: Boolean(e.account_update_log_enabled),
      newchat_alert_enabled: e.newchat_alert_enabled !== false,
      // Mặc định bật HA; fallback tắt (bật tay từng admin)
      ha_fastpath: e.ha_fastpath !== false,
      fallback_enabled: Boolean(e.fallback_enabled),
      emphasis_enabled: e.emphasis_enabled !== false,
      emphasis_numbers: e.emphasis_numbers !== false,
      emphasis_units: e.emphasis_units !== false,
      emphasis_key_info: e.emphasis_key_info !== false,
      emphasis_style: String(e.emphasis_style || "bold") || "bold",
      markdown_color: String(
        e.markdown_color || e.emphasis_color || "orange",
      ).trim().toLowerCase() || "orange",
      markdown_size: String(
        e.markdown_size || e.emphasis_size || e.text_size || "normal",
      ).trim().toLowerCase() || "normal",
    }));
  };
  if (Array.isArray(b?.admin_entries)) {
    for (const x of b.admin_entries) {
      if (typeof x === "string") push({ chat_id: x });
      else if (x && typeof x === "object") push(x);
    }
  }
  const hasRealAdmin = () => out.some((a) => a.chat_id.trim());
  if (!hasRealAdmin()) {
    const ths: string[] = Array.isArray(b?.admin_threads)
      ? b.admin_threads.map((x: any) => String(x || "").trim()).filter(Boolean)
      : [];
    const one = String(b?.admin_thread || "").trim();
    if (one && !ths.includes(one)) ths.push(one);
    const legacyGroup = String(b?.admin_thread_type || "0") === "1";
    for (const t of ths) push({ chat_id: t, kind: legacyGroup ? "group" : guessKind(t) });
  }
  // Legacy: ID admin chỉ nằm trong chat_ids (ô -100… = Admin #1) → card admin đủ cột
  // Ô Chat IDs đã bỏ — ID này không còn hiển thị ở allowlist.
  if (!hasRealAdmin() && Array.isArray(b?.chat_ids)) {
    out.splice(0, out.length);
    seen.clear();
    const botModel = String(b?.ai_model || "").trim();
    for (const t of b.chat_ids) {
      const s = String(t || "").trim();
      if (s) push({ chat_id: s, kind: guessKind(s), ai_model: botModel });
    }
  }
  // Admin chưa có model → kế thừa model bot (1 lần khi load)
  const botModel = String(b?.ai_model || "").trim();
  if (botModel) {
    for (let i = 0; i < out.length; i++) {
      if (!out[i].ai_model) out[i] = { ...out[i], ai_model: botModel };
    }
  }
  if (!out.length) out.push(emptyAdmin());
  // Admin có ID thật đứng trước slot trống (Admin #1 = ID legacy)
  out.sort((a, b2) => {
    const ae = a.chat_id.trim() ? 0 : 1;
    const be = b2.chat_id.trim() ? 0 : 1;
    return ae - be;
  });
  return out;
}

/** Danh sách bot đa-token: tên dễ nhớ, admin 3 cột, fallback theo tên. */
function BotListEditor({ bots, models, tokenPlaceholder, onChange, names, platform, fallbackOptions }: {
  bots: any[];
  models: string[];
  tokenPlaceholder: string;
  onChange: (bots: any[]) => void;
  names?: Record<string, string>;
  platform: "tg" | "zalo";
  fallbackOptions?: FallbackOpt[];
}) {
  type Row = {
    id: number;
    token: string;
    label: string;
    /** Model mặc định cho chat AI thường (thread filter) — admin có model riêng */
    ai_model: string;
    enabled: boolean;
    admins: AdminEntry[];
  };
  const [rows, setRows] = useState<Row[]>([]);
  const inited = useRef(false);
  const seq = useRef(1);
  const [resolving, setResolving] = useState<string>("");

  useEffect(() => {
    if (inited.current || !Array.isArray(bots)) return;
    inited.current = true;
    setRows(bots.map((b) => {
      const token = String(b?.token || "");
      const bid = token.split(":")[0]?.trim() || "";
      let label = String(b?.label || "").trim();
      if (!label && bid && names?.[bid]) label = names[bid];
      const admins = parseAdminEntries(b);
      return {
        id: seq.current++,
        token,
        label,
        ai_model: String(b?.ai_model || ""),
        enabled: b?.enabled !== false,
        admins,
      };
    }));
  }, [bots, names]);

  /** UI giữ admin trống; config chỉ lưu admin có Chat ID. Chat IDs đã bỏ. */
  const commit = (next: Row[]) => {
    setRows(next);
    onChange(
      next.filter((r) => r.token.trim()).map((r) => {
        const admins = r.admins.filter((a) => a.chat_id.trim());
        // Bot-level derived: bật nếu BẤT KỲ admin nào bật (backend vẫn đọc bot flags)
        const anyNotify = admins.some((a) => a.notify_enabled);
        const anyLog = admins.some((a) => a.account_log_enabled);
        const anyNew = admins.some((a) => a.newchat_alert_enabled);
        const anyHa = admins.some((a) => a.ha_fastpath);
        const anyFb = admins.some((a) => a.fallback_enabled);
        const fbThread = admins.find((a) => a.fallback_enabled)?.chat_id || "";
        // Model bot = admin #1 nếu bot trống (tương thích cũ)
        const botModel = r.ai_model.trim()
          || admins.find((a) => a.ai_model.trim())?.ai_model.trim()
          || "";
        return {
          token: r.token.trim(),
          label: r.label.trim(),
          // Chat IDs thừa — AI thường qua bộ lọc thread; admin qua admin_entries
          chat_ids: [] as string[],
          ai_model: botModel,
          enabled: r.enabled,
          admin_entries: admins,
          admin_thread: admins[0]?.chat_id || "",
          admin_threads: admins.map((a) => a.chat_id),
          ha_fastpath: anyHa || admins.length === 0,
          notify_admin_enabled: anyNotify || admins.length === 0,
          account_log_enabled: anyLog || admins.length === 0,
          newchat_alert_enabled: anyNew || admins.length === 0,
          fallback_enabled: anyFb,
          fallback_channel: anyFb ? (platform === "zalo" ? "zalo" : "telegram") : "",
          fallback_bot_name: anyFb ? (r.label || r.token.split(":")[0] || "") : "",
          fallback_thread: fbThread,
          emphasis_enabled: true,
          emphasis_numbers: true,
          emphasis_units: true,
          emphasis_key_info: true,
          emphasis_style: "bold",
        };
      }),
    );
  };
  const emptyRow = (): Row => ({
    id: seq.current++, token: "", label: "", ai_model: "", enabled: true,
    admins: [emptyAdmin()],
  });
  const add = () => commit([...rows, emptyRow()]);
  const remove = (id: number) => commit(rows.filter((r) => r.id !== id));
  const patch = (id: number, p: Partial<Row>) => commit(rows.map((r) => (r.id === id ? { ...r, ...p } : r)));

  const patchAdmin = (rowId: number, idx: number, p: Partial<AdminEntry>) => {
    const row = rows.find((r) => r.id === rowId);
    if (!row) return;
    const admins = row.admins.map((a, i) => (i === idx ? { ...a, ...p } : a));
    patch(rowId, { admins });
  };
  const addAdmin = (rowId: number) => {
    const row = rows.find((r) => r.id === rowId);
    if (!row) return;
    patch(rowId, { admins: [...row.admins, emptyAdmin()] });
  };
  const removeAdmin = (rowId: number, idx: number) => {
    const row = rows.find((r) => r.id === rowId);
    if (!row) return;
    const next = row.admins.filter((_, i) => i !== idx);
    patch(rowId, { admins: next.length ? next : [emptyAdmin()] });
  };

  const resolveAdmin = async (row: Row, idx: number) => {
    const a = row.admins[idx];
    if (!a?.chat_id.trim()) {
      toast.error("Cần Chat ID / Thread ID");
      return;
    }
    if (platform === "tg" && !row.token.trim()) {
      toast.error("Cần token bot + Chat ID");
      return;
    }
    if (platform === "zalo" && !row.token.trim()) {
      toast.error("Cần token Zalo Bot + Chat ID");
      return;
    }
    const key = `${row.id}-${idx}`;
    setResolving(key);
    try {
      const url = platform === "zalo"
        ? "/api/zalo/resolve-chat"
        : "/api/telegram/resolve-chat";
      const res: any = await request.post(url, {
        token: row.token.trim(),
        chat_id: a.chat_id.trim(),
      });
      const d = res.data || {};
      patchAdmin(row.id, idx, {
        name: String(d.name || a.name || "").trim(),
        kind: d.kind === "group" ? "group" : "private",
      });
      if (d.ok) toast.success(d.name ? `Nhận diện: ${d.name}` : "Đã nhận diện loại thread");
      else toast.message("API chưa thấy chat — đã gán loại theo heuristic; sửa tay nếu sai");
    } catch {
      toast.error("Không resolve được chat");
    } finally {
      setResolving("");
    }
  };

  const fillLabelFromPlatform = (row: Row) => {
    const bid = row.token.split(":")[0]?.trim();
    const n = bid ? names?.[bid] : "";
    if (n) patch(row.id, { label: n });
    else toast.message("Chưa có tên từ nền tảng — điền tay hoặc lưu token rồi tải lại");
  };

  return (
    <div className="space-y-2 mt-1">
      {rows.map((row) => {
        const bid = row.token.split(":")[0]?.trim() || "";
        const platformName = names?.[bid] || "";
        return (
          <div key={row.id} className="rounded-md border border-border p-2 space-y-2">
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none shrink-0">
                <input type="checkbox" className="size-3.5" checked={row.enabled}
                  onChange={(e) => patch(row.id, { enabled: e.target.checked })} />
                Bật
              </label>
              <Input value={row.token} onChange={(e) => patch(row.id, { token: e.target.value })}
                placeholder={tokenPlaceholder} className="flex-1" />
              <Button type="button" variant="ghost" size="sm" onClick={() => remove(row.id)}>Xóa</Button>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-[11px] text-muted-foreground shrink-0">Tên dễ nhớ</label>
              <Input value={row.label} onChange={(e) => patch(row.id, { label: e.target.value })}
                placeholder="Tự lấy từ bot lúc đầu — bạn đổi được"
                className="flex-1 h-8 text-xs" />
              <Button type="button" variant="outline" size="sm" className="h-8 text-[10px] shrink-0"
                onClick={() => fillLabelFromPlatform(row)}>
                Lấy tên bot
              </Button>
            </div>
            {platformName ? (
              <p className="text-[11px] text-muted-foreground -mt-1">
                🤖 Tên bot Telegram: <b>{platformName}</b>
                {row.label && row.label !== platformName ? <> · đang dùng: <b>{row.label}</b></> : null}
              </p>
            ) : null}
            <div>
              <label className="text-[10px] text-muted-foreground">
                Model AI mặc định (chat thường qua bộ lọc thread — không áp admin)
              </label>
              <Select value={row.ai_model || " "} onValueChange={(v) => patch(row.id, { ai_model: v.trim() })}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Model mặc định bot" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value=" ">-- Mặc định hệ thống --</SelectItem>
                  {Array.from(new Set([...models, ...(row.ai_model ? [row.ai_model] : [])])).map((m) => (
                    <SelectItem key={m} value={m}>{m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Admin #1, #2… — mỗi card đủ cài đặt; không còn ô Chat IDs */}
            <div className="space-y-2">
              <label className="text-xs font-medium text-muted-foreground">
                Admin #1, #2… — Tên · ID · Loại · Nhận diện · Nền tảng (model) riêng · 🔔 📋 · HA · Fallback
              </label>
              {row.admins.map((a, idx) => (
                <div key={idx} className="rounded-md border border-border p-2.5 space-y-2 bg-muted/10">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold">Admin #{idx + 1}</span>
                    <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-[10px]"
                      onClick={() => removeAdmin(row.id, idx)}>Xóa</Button>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5">
                    <div>
                      <label className="text-[10px] text-muted-foreground">Tên</label>
                      <Input className="h-8 text-xs" value={a.name}
                        onChange={(e) => patchAdmin(row.id, idx, { name: e.target.value })}
                        placeholder="Tên dễ nhớ" />
                    </div>
                    <div>
                      <label className="text-[10px] text-muted-foreground">Chat ID</label>
                      <Input className="h-8 text-xs font-mono" value={a.chat_id}
                        onChange={(e) => {
                          const cid = e.target.value;
                          patchAdmin(row.id, idx, {
                            chat_id: cid,
                            kind: a.name ? a.kind : guessKind(cid),
                          });
                        }}
                        placeholder="-100… / user id" />
                    </div>
                    <div>
                      <label className="text-[10px] text-muted-foreground">Loại</label>
                      <div className="flex gap-1">
                        <select className="h-8 flex-1 rounded-md border border-border bg-background px-1 text-[11px]"
                          value={a.kind}
                          onChange={(e) => patchAdmin(row.id, idx, { kind: e.target.value as "private" | "group" })}>
                          <option value="private">Cá nhân</option>
                          <option value="group">Nhóm</option>
                        </select>
                        {(platform === "tg" || platform === "zalo") ? (
                          <Button type="button" variant="outline" size="sm" className="h-8 px-2 text-[10px]"
                            disabled={resolving === `${row.id}-${idx}`}
                            onClick={() => resolveAdmin(row, idx)}>
                            {resolving === `${row.id}-${idx}` ? "…" : "Nhận diện"}
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  {/* Persona riêng Admin này — độc lập, tick → 4 chọn → mô tả dưới */}
                  <PersonaInline platform={platform}
                    groupId={a.kind === "group" ? a.chat_id : ""}
                    userId={a.kind === "group" ? "" : a.chat_id} />

                  <div>
                    <label className="text-[10px] text-muted-foreground">
                      🤖 Nền tảng / Model AI (riêng Admin #{idx + 1})
                    </label>
                    <Select
                      value={a.ai_model || " "}
                      onValueChange={(v) => patchAdmin(row.id, idx, { ai_model: v.trim() })}
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Model cho admin này" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value=" ">-- Kế thừa model bot --</SelectItem>
                        {Array.from(new Set([
                          ...models,
                          ...(a.ai_model ? [a.ai_model] : []),
                          ...(row.ai_model ? [row.ai_model] : []),
                        ])).map((m) => (
                          <SelectItem key={m} value={m}>{m}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1 rounded border border-border/50 p-2">
                    <p className="text-[10px] font-medium text-muted-foreground">Thông báo tới admin này</p>
                    <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={a.notify_enabled}
                        onChange={(e) => patchAdmin(row.id, idx, { notify_enabled: e.target.checked })} />
                      🔔 Lỗi &amp; cảnh báo (không phải provider, không phải chat mới)
                    </label>
                    <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={a.account_log_enabled}
                        onChange={(e) => patchAdmin(row.id, idx, { account_log_enabled: e.target.checked })} />
                      📋 Log tài khoản provider (Thêm/Xóa/Lỗi/Quota…)
                    </label>
                    <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={a.account_update_log_enabled}
                        onChange={(e) => patchAdmin(row.id, idx, { account_update_log_enabled: e.target.checked })} />
                      🔄 Log Cập nhật tài khoản (bản ghi token/status định kỳ)
                    </label>
                    <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={a.newchat_alert_enabled}
                        onChange={(e) => patchAdmin(row.id, idx, { newchat_alert_enabled: e.target.checked })} />
                      💬 Chat/nhóm mới (thread ID + user ID) — tách hẳn 🔔/📋
                    </label>
                  </div>

                  <div className="space-y-1 rounded border border-border/50 p-2">
                    <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={a.emphasis_enabled}
                        onChange={(e) => patchAdmin(row.id, idx, { emphasis_enabled: e.target.checked })} />
                      ✍️ Nhấn mạnh số liệu &amp; thông tin chính
                    </label>
                    <div className="flex flex-wrap gap-3 pl-1">
                      <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer select-none">
                        <input type="checkbox" className="size-3.5" checked={a.emphasis_numbers}
                          disabled={!a.emphasis_enabled}
                          onChange={(e) => patchAdmin(row.id, idx, { emphasis_numbers: e.target.checked })} />
                        Số
                      </label>
                      <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer select-none">
                        <input type="checkbox" className="size-3.5" checked={a.emphasis_units}
                          disabled={!a.emphasis_enabled}
                          onChange={(e) => patchAdmin(row.id, idx, { emphasis_units: e.target.checked })} />
                        Đơn vị (°C, %)
                      </label>
                      <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer select-none">
                        <input type="checkbox" className="size-3.5" checked={a.emphasis_key_info}
                          disabled={!a.emphasis_enabled}
                          onChange={(e) => patchAdmin(row.id, idx, { emphasis_key_info: e.target.checked })} />
                        Thông tin chính
                      </label>
                    </div>
                    <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-[11px]"
                      value={a.emphasis_style || "bold"}
                      disabled={!a.emphasis_enabled}
                      onChange={(e) => patchAdmin(row.id, idx, { emphasis_style: e.target.value })}>
                      <option value="bold">Đậm (bold)</option>
                      <option value="code">Monospace</option>
                      <option value="bold_code">Đậm + monospace</option>
                    </select>
                    {/* Zalo Bot Platform: màu + cỡ chữ (Tele API không hỗ trợ) */}
                    {platform === "zalo" ? (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1 border-t border-border/40">
                        <div>
                          <label className="text-[10px] text-muted-foreground">
                            🎨 Màu chữ (Zalo Bot)
                          </label>
                          <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-[11px]"
                            value={a.markdown_color || "orange"}
                            disabled={!a.emphasis_enabled}
                            onChange={(e) => patchAdmin(row.id, idx, { markdown_color: e.target.value })}>
                            <option value="orange">Cam</option>
                            <option value="red">Đỏ</option>
                            <option value="yellow">Vàng</option>
                            <option value="green">Xanh lá</option>
                            <option value="none">Không màu (chỉ đậm)</option>
                          </select>
                        </div>
                        <div>
                          <label className="text-[10px] text-muted-foreground">
                            🔠 Cỡ chữ (Zalo Bot)
                          </label>
                          <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-[11px]"
                            value={a.markdown_size || "normal"}
                            disabled={!a.emphasis_enabled}
                            onChange={(e) => patchAdmin(row.id, idx, { markdown_size: e.target.value })}>
                            <option value="normal">Thường</option>
                            <option value="big">Lớn {"{big}"}</option>
                          </select>
                        </div>
                        <p className="sm:col-span-2 text-[10px] text-muted-foreground">
                          Theo API Zalo: màu red/orange/yellow/green; cỡ lớn = tag {"{big}"}.
                          Áp cho đoạn số liệu được nhấn mạnh.
                        </p>
                      </div>
                    ) : null}
                  </div>

                  <div className="flex flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:gap-4">
                    <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={a.ha_fastpath}
                        onChange={(e) => patchAdmin(row.id, idx, { ha_fastpath: e.target.checked })} />
                      ⚡ Điều khiển nhà cục bộ (HA fastpath)
                    </label>
                    <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={a.fallback_enabled}
                        onChange={(e) => patchAdmin(row.id, idx, { fallback_enabled: e.target.checked })} />
                      Fallback khi gửi không được (dùng admin này)
                    </label>
                  </div>
                </div>
              ))}
              <Button type="button" variant="outline" size="sm" className="h-8"
                onClick={() => addAdmin(row.id)}>+ Thêm admin</Button>
            </div>
          </div>
        );
      })}
      <Button type="button" variant="outline" size="sm" onClick={add}>+ Thêm bot</Button>
    </div>
  );
}

export function TelegramCloudflareCard() {
  const config = useSettingsStore((state) => state.config);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const setField = useSettingsStore((state) => state.setField);
  const saveConfig = useSettingsStore((state) => state.saveConfig);

  const [models, setModels] = useState<string[]>([]);
  /** Acc Zalo CN: hiển thị tên + SĐT (không hiện ownId). ownId chỉ dùng key nội bộ. */
  type ZalopAcc = { ownId: string; displayName?: string; phoneNumber?: string };
  const [zalopAccounts, setZalopAccounts] = useState<ZalopAcc[]>([]);
  // Nhận diện admin Zalo CN (state ở parent — không nằm trong BotListEditor)
  const [resolving, setResolving] = useState<string>("");
  // bot_id -> tên bot (getMe) — hiển thị TÊN thay mã số cho dễ chọn đúng bot.
  const [botNames, setBotNames] = useState<{ telegram: Record<string, string>; zalo: Record<string, string> }>(
    { telegram: {}, zalo: {} });
  // Tab KÊNH + tab con — mỗi kênh (Telegram / Zalo Bot / Zalo Cá Nhân) cài đặt
  // ĐỘC LẬP: cài đặt kênh, lọc thread, nhánh agent riêng từng kênh.
  const [chTab, setChTab] = useState<"tg" | "zalo" | "zalop">("tg");
  const [subTab, setSubTab] = useState<"settings" | "zaccounts" | "directory" | "filter" | "branches">("settings");
  // Danh bạ thread (setting ∪ auto bot) — tab riêng mỗi kênh
  type DirRow = {
    bot_id: string; bot_label: string; thread_id: string;
    kind: string; name: string; sources?: string[];
  };
  const [dirRows, setDirRows] = useState<DirRow[]>([]);
  const [dirLoading, setDirLoading] = useState(false);

  const zalopAccLabel = (a: ZalopAcc) => {
    // Không hiện ownId. displayName từ zca đôi khi là "SĐT (ownId)" → bỏ phần (id).
    let name = String(a.displayName || "").trim()
      .replace(/\s*\(\d{8,}\)\s*$/g, "")
      .trim();
    const phone = String(a.phoneNumber || "").trim();
    if (name && phone && name !== phone && !name.includes(phone)) {
      return `${name} · ${phone}`;
    }
    if (phone) return phone;
    if (name) return name;
    return "Tài khoản Zalo";
  };

  /** Options fallback theo TÊN (không mã số). */
  const fallbackOptions: FallbackOpt[] = (() => {
    const opts: FallbackOpt[] = [];
    for (const b of (((config as any)?.telegram_bots as any[]) || [])) {
      const tok = String(b?.token || "");
      const bid = tok.split(":")[0] || "";
      const name = String(b?.label || botNames.telegram[bid] || bid || "").trim();
      if (!name) continue;
      opts.push({ value: `telegram::${name}`, label: `Telegram · ${name}`, channel: "telegram" });
    }
    for (const b of (((config as any)?.zalo_bots as any[]) || [])) {
      const tok = String(b?.token || "");
      const bid = tok.split(":")[0] || "";
      const name = String(b?.label || botNames.zalo[bid] || bid || "").trim();
      if (!name) continue;
      opts.push({ value: `zalo::${name}`, label: `Zalo Bot · ${name}`, channel: "zalo" });
    }
    for (const a of zalopAccounts) {
      opts.push({
        value: `zalo_personal::${a.ownId}`,
        label: `Zalo CN · ${zalopAccLabel(a)}`,
        channel: "zalo_personal",
      });
    }
    return opts;
  })();

  useEffect(() => {
    request.get("/v1/models")
      .then((res: any) => {
        if (res.data && Array.isArray(res.data.data)) {
          setModels(res.data.data.map((m: any) => m.id));
        }
      })
      .catch((err) => console.error("Failed to load models", err));
    // Tên bot (getMe) — hiển thị tên thay mã số trong danh sách bot + dropdown lọc.
    request.get("/api/bot-names")
      .then((res: any) => {
        setBotNames({
          telegram: (res.data?.telegram as Record<string, string>) || {},
          zalo: (res.data?.zalo as Record<string, string>) || {},
        });
      })
      .catch(() => {});
    // Tài khoản Zalo Cá Nhân — nhãn = tên + SĐT (không ownId).
    request.get("/api/zalo-personal/accounts")
      .then((res: any) => {
        const list = (res.data?.accounts as any[]) || [];
        setZalopAccounts(
          list
            .map((a: any) => ({
              ownId: String(a?.ownId || "").trim(),
              displayName: String(a?.displayName || "").trim() || undefined,
              phoneNumber: String(a?.phoneNumber || "").trim() || undefined,
            }))
            .filter((a: ZalopAcc) => Boolean(a.ownId)),
        );
      })
      .catch(() => {});
  }, []);

  // ── Bộ lọc chức năng theo thread — theo TỪNG bot (đa-token) ──────────────
  // botKey: 'tg:<bot_id>' / 'zalo:<bot_id>' (bot cụ thể) hoặc 'tg' / 'zalo' (mọi bot).
  // Mỗi thread (nếu là nhóm) có thêm: TẦNG LỌC USER (mỗi user tick tập con nhóm)
  // + BỘ LỌC TAG (bật = chỉ trả lời khi tin chứa từ khóa tag bot).
  // forward/forwardUrl: chuyển tiếp webhook (HA/n8n/URL bất kỳ). Thread bật →
  // user chỉ bật/tắt (dùng URL thread); thread không bật → user bật + URL riêng.
  // forwardTagOnly: chỉ chuyển khi tin TAG bot — không tag thì ChatGPT trả lời.
  type UserRow = {
    id: number; userId: string; name?: string; groups: string[];
    forward: boolean; forwardUrl: string; forwardTagOnly: boolean;
  };
  // kind: thread là "group" (nhóm) hay "user" (cá nhân) — cá nhân thì KHÔNG cần
  // tầng lọc user + bộ lọc tag (ẩn đi). Lưu ở config thread_filter_meta.
  type FilterRow = {
    id: number; botKey: string; chatId: string; kind: string; name?: string;
    groups: string[];
    users: UserRow[]; requireMention: boolean; mentionKeyword: string;
    forward: boolean; forwardUrl: string;
  };
  const [filterRows, setFilterRows] = useState<FilterRow[]>([]);
  const filterInited = useRef(false);
  const rowSeq = useRef(1);
  // Nhận diện thread/user trong tab Lọc (zalop: resolve-thread)
  const [filterResolving, setFilterResolving] = useState<string>("");

  useEffect(() => {
    if (filterInited.current) return;
    const tf = (config as any)?.thread_filters as Record<string, string[]> | undefined;
    const tuf = (config as any)?.thread_user_filters as Record<string, string[]> | undefined;
    const tmf = (config as any)?.thread_mention_filters as Record<string, { required?: boolean; keyword?: string }> | undefined;
    const tff = (config as any)?.thread_forward_filters as Record<string, { enabled?: boolean; url?: string; tag_mode?: boolean }> | undefined;
    const tfMeta = (config as any)?.thread_filter_meta as Record<string, { kind?: string; name?: string }> | undefined;
    if (!tf && !tuf && !tmf && !tff) return;
    filterInited.current = true;

    const splitParent = (key: string): { botKey: string; chatId: string } => {
      const parts = key.split(":");
      if (parts.length >= 3) return { botKey: `${parts[0]}:${parts[1]}`, chatId: parts.slice(2).join(":") };
      if (parts.length === 2) return { botKey: parts[0], chatId: parts[1] };
      return { botKey: "tg", chatId: key };
    };

    // 1. Parent rows từ thread_filters (kind/name đọc từ thread_filter_meta)
    const kindOf = (key: string) => (tfMeta?.[key]?.kind === "user" ? "user" : "group");
    const nameOf = (key: string) => String(tfMeta?.[key]?.name || "").trim();
    const rows: FilterRow[] = Object.entries(tf || {}).map(([key, groups]) => {
      const { botKey, chatId } = splitParent(key);
      return {
        id: rowSeq.current++, botKey, chatId, kind: kindOf(key), name: nameOf(key),
        groups: Array.isArray(groups) ? groups : [], users: [],
        requireMention: false, mentionKeyword: "", forward: false, forwardUrl: "",
      };
    });
    const findRow = (botKey: string, chatId: string) => rows.find((r) => r.botKey === botKey && r.chatId === chatId);
    const ensureRow = (botKey: string, chatId: string) => {
      let r = findRow(botKey, chatId);
      if (!r) {
        const k = `${botKey}:${chatId}`;
        r = {
          id: rowSeq.current++, botKey, chatId, kind: kindOf(k), name: nameOf(k),
          groups: [...FUNCTION_GROUPS.map(([gk]) => gk)], users: [],
          requireMention: false, mentionKeyword: "", forward: false, forwardUrl: "",
        };
        rows.push(r);
      }
      return r;
    };

    // 2. Mention filters → gắn vào parent (tạo nếu chưa có, mặc định mở full nhóm)
    for (const [key, v] of Object.entries(tmf || {})) {
      const { botKey, chatId } = splitParent(key);
      const r = ensureRow(botKey, chatId);
      r.requireMention = !!v?.required;
      r.mentionKeyword = String(v?.keyword || "");
    }

    // 3. User filters: khóa = '<parentKey>:<userId>'. Ghép vào parent bằng cách
    //    khớp prefix parent dài nhất; không khớp → suy ra parent = bỏ segment cuối.
    for (const [key, groups] of Object.entries(tuf || {})) {
      let matched: FilterRow | null = null;
      let userId = "";
      for (const r of rows) {
        const prefix = `${r.botKey}:${r.chatId}:`;
        if (key.startsWith(prefix) && key.length > prefix.length) {
          const rest = key.slice(prefix.length);
          if (!rest.includes(":") || !matched) { matched = r; userId = rest; }
        }
      }
      if (!matched) {
        const idx = key.lastIndexOf(":");
        if (idx <= 0) continue;
        const { botKey, chatId } = splitParent(key.slice(0, idx));
        userId = key.slice(idx + 1);
        matched = ensureRow(botKey, chatId);
      }
      matched.users.push({
        id: rowSeq.current++, userId,
        name: nameOf(key),
        groups: Array.isArray(groups) ? groups : [],
        forward: false, forwardUrl: "", forwardTagOnly: false,
      });
    }

    // 4. Forward filters: khóa parent (khớp đúng 1 row đã có — commit luôn ghi
    //    tf cho mọi row) hoặc khóa user '<parentKey>:<userId>' như tuf.
    const explicitFwd = new Set<number>();
    for (const [key, v] of Object.entries(tff || {})) {
      const parentRow = rows.find((r) => `${r.botKey}:${r.chatId}` === key);
      if (parentRow) {
        parentRow.forward = !!v?.enabled;
        parentRow.forwardUrl = String(v?.url || "");
        continue;
      }
      let matched: FilterRow | null = null;
      let userId = "";
      for (const r of rows) {
        const prefix = `${r.botKey}:${r.chatId}:`;
        if (key.startsWith(prefix) && key.length > prefix.length) {
          const rest = key.slice(prefix.length);
          if (!rest.includes(":") || !matched) { matched = r; userId = rest; }
        }
      }
      if (!matched) {
        const idx = key.lastIndexOf(":");
        if (idx <= 0) continue;
        const { botKey, chatId } = splitParent(key.slice(0, idx));
        userId = key.slice(idx + 1);
        matched = ensureRow(botKey, chatId);
      }
      let u = matched.users.find((x) => x.userId === userId);
      if (!u) {
        u = { id: rowSeq.current++, userId, groups: [...matched.groups], forward: false, forwardUrl: "", forwardTagOnly: false };
        matched.users.push(u);
      }
      u.forward = !!v?.enabled;
      u.forwardUrl = String(v?.url || "");
      u.forwardTagOnly = !!v?.tag_mode;
      explicitFwd.add(u.id);
    }
    // Thread bật chuyển tiếp → user KHÔNG có bản ghi mặc định BẬT (thừa hưởng URL thread).
    for (const r of rows) {
      if (!r.forward) continue;
      for (const u of r.users) if (!explicitFwd.has(u.id)) u.forward = true;
    }

    setFilterRows(rows);
  }, [config]);

  // Danh sách bot cho dropdown lọc: từng bot cụ thể + 'mọi bot' mỗi nền tảng.
  // Ưu tiên label Settings (Bot Ben Bắp) — không dùng username mã hóa bot.xxx.
  const botFilterOptions: { value: string; label: string }[] = [];
  for (const b of (((config as any)?.telegram_bots as any[]) || [])) {
    const id = String(b?.token || "").split(":")[0];
    if (!id) continue;
    const name = String(b?.label || botNames.telegram[id] || id).trim();
    botFilterOptions.push({ value: `tg:${id}`, label: `Telegram · ${name}` });
  }
  botFilterOptions.push({ value: "tg", label: "Telegram · mọi bot" });
  for (const b of (((config as any)?.zalo_bots as any[]) || [])) {
    const id = String(b?.token || "").split(":")[0];
    if (!id) continue;
    const name = String(b?.label || botNames.zalo[id] || id).trim();
    botFilterOptions.push({ value: `zalo:${id}`, label: `Zalo · ${name}` });
  }
  botFilterOptions.push({ value: "zalo", label: "Zalo · mọi bot" });
  for (const a of zalopAccounts) {
    botFilterOptions.push({
      value: `zalop:${a.ownId}`,
      label: `Zalo Cá Nhân · ${zalopAccLabel(a)}`,
    });
  }
  botFilterOptions.push({ value: "zalop", label: "Zalo Cá Nhân · mọi tài khoản" });
  // Chỉ hiện bot của KÊNH đang chọn (tab) — mỗi kênh lọc thread độc lập.
  // 'zalo:'/'zalo' không khớp 'zalop:...' vì so tiền tố kèm dấu ':'.
  const tabFilterOptions = botFilterOptions.filter(
    (o) => o.value === chTab || o.value.startsWith(`${chTab}:`));
  const optionsFor = (botKey: string) => {
    const opts = [...tabFilterOptions];
    if (botKey && !opts.some((o) => o.value === botKey)) opts.push({ value: botKey, label: botKey });
    return opts;
  };

  const commitFilters = (rows: FilterRow[]) => {
    setFilterRows(rows);
    const tf: Record<string, string[]> = {};
    const tuf: Record<string, string[]> = {};
    const tmf: Record<string, { required: boolean; keyword: string }> = {};
    const tff: Record<string, { enabled: boolean; url: string; tag_mode: boolean }> = {};
    const tfMeta: Record<string, { kind: string; name?: string }> = {};
    for (const r of rows) {
      const id = r.chatId.trim();
      if (!id) continue;
      const parent = `${r.botKey}:${id}`;
      tf[parent] = r.groups;
      const tName = String(r.name || "").trim();
      tfMeta[parent] = {
        kind: r.kind === "user" ? "user" : "group",
        ...(tName ? { name: tName } : {}),
      };
      // Chuyển tiếp webhook cấp THREAD (áp cả nhóm lẫn cá nhân). Giữ URL khi
      // tạm tắt (enabled=false) để bật lại không phải nhập lại.
      const rUrl = r.forwardUrl.trim();
      if (r.forward || rUrl) tff[parent] = { enabled: r.forward && !!rUrl, url: rUrl, tag_mode: false };
      // Thread CÁ NHÂN: không lưu tag/lọc user (không áp dụng cho chat 1-1).
      if (r.kind !== "user") {
        if (r.requireMention || r.mentionKeyword.trim())
          tmf[parent] = { required: r.requireMention, keyword: r.mentionKeyword.trim() };
        for (const u of r.users) {
          const uid = u.userId.trim();
          if (!uid) continue;
          const ukey = `${parent}:${uid}`;
          tuf[ukey] = u.groups;
          const uName = String(u.name || "").trim();
          if (uName) tfMeta[ukey] = { kind: "user", name: uName };
          const uUrl = u.forwardUrl.trim();
          if (r.forward && rUrl) {
            // Thread đang chuyển tiếp: lưu bản ghi user khi TẮT riêng hoặc
            // bật "chỉ chuyển khi tag" (mặc định = thừa hưởng, không bản ghi).
            if (!u.forward) tff[ukey] = { enabled: false, url: uUrl, tag_mode: u.forwardTagOnly };
            else if (u.forwardTagOnly) tff[ukey] = { enabled: true, url: uUrl, tag_mode: true };
          } else if (u.forward || uUrl) {
            // Thread không chuyển tiếp: user tự bật + URL riêng.
            tff[ukey] = { enabled: u.forward && !!uUrl, url: uUrl, tag_mode: u.forwardTagOnly };
          }
        }
      }
    }
    setField("thread_filters", tf);
    setField("thread_user_filters", tuf);
    setField("thread_mention_filters", tmf);
    setField("thread_forward_filters", tff);
    setField("thread_filter_meta", tfMeta);
  };
  const addFilterRow = () =>
    commitFilters([...filterRows, {
      id: rowSeq.current++, botKey: tabFilterOptions[0]?.value || chTab,
      chatId: "", kind: "group", name: "", groups: [], users: [],
      requireMention: false, mentionKeyword: "", forward: false, forwardUrl: "",
    }]);
  const removeFilterRow = (id: number) =>
    commitFilters(filterRows.filter((r) => r.id !== id));
  const setFilterField = (id: number, patch: Partial<FilterRow>) =>
    commitFilters(filterRows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const toggleFilterGroup = (id: number, g: string) =>
    commitFilters(
      filterRows.map((r) =>
        r.id === id
          ? { ...r, groups: r.groups.includes(g) ? r.groups.filter((x) => x !== g) : [...r.groups, g] }
          : r,
      ),
    );
  // ── Thao tác USER trong 1 thread nhóm ──
  const addUserRow = (rowId: number) =>
    commitFilters(filterRows.map((r) =>
      r.id === rowId
        ? {
          ...r,
          users: [...r.users, {
            id: rowSeq.current++, userId: "", name: "", groups: [...r.groups],
            forward: r.forward, forwardUrl: "", forwardTagOnly: false,
          }],
        }
        : r));
  const removeUserRow = (rowId: number, userId: number) =>
    commitFilters(filterRows.map((r) =>
      r.id === rowId ? { ...r, users: r.users.filter((u) => u.id !== userId) } : r));
  const setUserField = (rowId: number, userId: number, patch: Partial<UserRow>) =>
    commitFilters(filterRows.map((r) =>
      r.id === rowId ? { ...r, users: r.users.map((u) => (u.id === userId ? { ...u, ...patch } : u)) } : r));

  /** ownId từ botKey `zalop` / `zalop:<ownId>` (trống = acc đầu). */
  const zalopAccFromBotKey = (botKey: string) => {
    if (botKey.startsWith("zalop:")) return botKey.slice("zalop:".length).trim();
    return zalopAccounts[0]?.ownId || String((config as any)?.zalo_personal_account_id || "").trim();
  };

  /** Token bot từ botKey `zalo`/`zalo:<id>` hoặc `tg`/`tg:<id>`. */
  const tokenFromBotKey = (botKey: string, platform: "zalo" | "tg") => {
    const list = (((config as any)?.[platform === "zalo" ? "zalo_bots" : "telegram_bots"] as any[]) || []);
    const bid = botKey.includes(":") ? botKey.split(":")[1] : "";
    const hit = list
      .map((b: any) => String(b?.token || ""))
      .find((t: string) => t && (!bid || t.startsWith(bid)));
    return hit || String(list[0]?.token || "");
  };

  /** Áp patch lên filterRows hiện tại (tránh stale closure sau await). */
  const patchFilterRowLive = (id: number, patch: Partial<FilterRow>) => {
    setFilterRows((prev) => {
      const next = prev.map((r) => (r.id === id ? { ...r, ...patch } : r));
      // Ghi config từ snapshot mới (không dùng filterRows ngoài closure)
      queueMicrotask(() => commitFilters(next));
      return next;
    });
  };
  const patchFilterUserLive = (rowId: number, userId: number, patch: Partial<UserRow>) => {
    setFilterRows((prev) => {
      const next = prev.map((r) =>
        r.id === rowId
          ? { ...r, users: r.users.map((u) => (u.id === userId ? { ...u, ...patch } : u)) }
          : r,
      );
      queueMicrotask(() => commitFilters(next));
      return next;
    });
  };

  const resolveFilterThread = async (row: FilterRow) => {
    const tid = row.chatId.trim();
    if (!tid) { toast.error("Cần Thread / Chat ID"); return; }
    const key = `tf-${row.id}`;
    setFilterResolving(key);
    try {
      let kind = row.kind === "user" ? "user" : "group";
      let name = "";
      let ok = false;
      if (row.botKey === "zalop" || row.botKey.startsWith("zalop:")) {
        const acc = zalopAccFromBotKey(row.botKey);
        if (!acc) { toast.error("Chưa có tài khoản Zalo CN — đăng nhập QR trước"); return; }
        const res: any = await request.post("/api/zalo-personal/resolve-thread", {
          account_id: acc,
          thread_id: tid,
          kind: row.kind === "user" ? "private" : "group",
        });
        const d = res.data || {};
        ok = !!d.ok;
        kind = d.kind === "group" ? "group" : "user";
        name = String(d.name || "").trim();
        if (!ok) toast.message("zca-js chưa thấy thread — sửa tay loại/tên nếu sai");
      } else if (row.botKey === "zalo" || row.botKey.startsWith("zalo:")) {
        const token = tokenFromBotKey(row.botKey, "zalo");
        if (!token) { toast.error("Chưa có token Zalo Bot"); return; }
        const res: any = await request.post("/api/zalo/resolve-chat", { token, chat_id: tid });
        const d = res.data || {};
        ok = !!d.ok;
        kind = d.kind === "group" ? "group" : "user";
        name = String(d.name || "").trim();
        if (!ok) toast.message("Không resolve được — gõ tên tay bên dưới hoặc kiểm tra token");
      } else {
        const token = tokenFromBotKey(row.botKey, "tg");
        if (!token) { toast.error("Chưa có token Telegram"); return; }
        const res: any = await request.post("/api/telegram/resolve-chat", { token, chat_id: tid });
        const d = res.data || {};
        ok = !!d.ok;
        kind = d.kind === "group" ? "group" : "user";
        name = String(d.name || "").trim();
        if (!ok) toast.message("Không resolve được — gõ tên tay bên dưới hoặc kiểm tra token");
      }
      // Chỉ ghi đè tên khi API trả được tên; giữ tên tay nếu resolve fail
      patchFilterRowLive(row.id, {
        kind,
        ...(name ? { name } : {}),
      });
      if (ok) {
        toast.success(
          name
            ? `Nhận diện: ${name} (${kind === "group" ? "nhóm" : "cá nhân"})`
            : "Đã nhận diện loại — có thể gõ tên tay",
        );
      }
    } catch {
      toast.error("Không resolve được thread — gõ tên tay nếu cần");
    } finally {
      setFilterResolving("");
    }
  };

  const resolveFilterUser = async (row: FilterRow, u: UserRow) => {
    const uid = u.userId.trim();
    if (!uid) { toast.error("Cần User ID"); return; }
    const key = `tfu-${row.id}-${u.id}`;
    setFilterResolving(key);
    try {
      let name = "";
      let ok = false;
      if (row.botKey === "zalop" || row.botKey.startsWith("zalop:")) {
        const acc = zalopAccFromBotKey(row.botKey);
        if (!acc) { toast.error("Chưa có tài khoản Zalo CN"); return; }
        const res: any = await request.post("/api/zalo-personal/resolve-thread", {
          account_id: acc,
          thread_id: uid,
          kind: "private",
        });
        const d = res.data || {};
        ok = !!d.ok;
        name = String(d.name || "").trim();
        if (!ok) toast.message("zca-js chưa thấy user — gõ tên tay");
      } else if (row.botKey === "zalo" || row.botKey.startsWith("zalo:")) {
        const token = tokenFromBotKey(row.botKey, "zalo");
        if (!token) { toast.error("Chưa có token Zalo Bot"); return; }
        const res: any = await request.post("/api/zalo/resolve-chat", { token, chat_id: uid });
        const d = res.data || {};
        ok = !!d.ok;
        name = String(d.name || "").trim();
        if (!ok) toast.message("Không resolve được user — gõ tên tay");
      } else if (row.botKey === "tg" || row.botKey.startsWith("tg:")) {
        const token = tokenFromBotKey(row.botKey, "tg");
        if (!token) { toast.error("Chưa có token Telegram"); return; }
        const res: any = await request.post("/api/telegram/resolve-chat", { token, chat_id: uid });
        const d = res.data || {};
        ok = !!d.ok;
        name = String(d.name || "").trim();
        if (!ok) toast.message("Không resolve được user — gõ tên tay");
      } else {
        toast.message("Chọn bot cụ thể rồi thử Nhận diện, hoặc gõ tên tay");
        return;
      }
      if (name) patchFilterUserLive(row.id, u.id, { name });
      if (ok) toast.success(name ? `Nhận diện user: ${name}` : "Đã nhận diện — có thể gõ tên tay");
    } catch {
      toast.error("Không resolve được user — gõ tên tay nếu cần");
    } finally {
      setFilterResolving("");
    }
  };
  const toggleUserGroup = (rowId: number, userId: number, g: string, parentGroups: string[]) =>
    commitFilters(filterRows.map((r) => {
      if (r.id !== rowId) return r;
      return { ...r, users: r.users.map((u) => {
        if (u.id !== userId) return u;
        // Chỉ cho tick nhóm mà THREAD cho phép (tập con) — nhóm ngoài bị bỏ qua.
        if (u.groups.includes(g)) return { ...u, groups: u.groups.filter((x) => x !== g) };
        if (!parentGroups.includes(g)) return u;
        return { ...u, groups: [...u.groups, g] };
      }) };
    }));

  // Hiển thị list (chat_ids / ha_threads) dạng text mỗi dòng 1 phần tử cho textarea.
  const asText = (v: unknown) => (Array.isArray(v) ? v.join("\n") : String(v ?? ""));
  const cfg = (config as any) || {};

  const loadDirectory = async () => {
    setDirLoading(true);
    try {
      const res: any = await request.get("/api/channels/directory", {
        params: { platform: chTab, limit: 400 },
      });
      setDirRows(Array.isArray(res.data?.rows) ? res.data.rows : []);
    } catch {
      setDirRows([]);
      toast.error("Không tải được danh bạ");
    } finally {
      setDirLoading(false);
    }
  };

  useEffect(() => {
    if (subTab === "directory") void loadDirectory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subTab, chTab]);

  // Chuyển tiếp webhook Zalo Cá Nhân: trình sửa đã GỠ khỏi UI (gom về 'Lọc chức
  // năng theo thread', khóa zalop:...). Backend vẫn đọc config legacy
  // zalo_personal_forward_webhooks / zalo_personal_ha_* cho cấu hình cũ.

  const tabBtn = (active: boolean) =>
    `px-3 py-1.5 rounded-md text-xs font-semibold border transition ${active
      ? "border-primary text-primary bg-primary/10"
      : "border-border text-muted-foreground hover:bg-muted/40"}`;

  return (
    <>
    <Card>
      <CardContent className="space-y-4 pt-4">
        <div className="text-sm font-semibold flex items-center gap-2">
          <MessageCircle className="size-4 text-blue-500" /> Kênh chat
        </div>
        {/* Tab KÊNH — mỗi kênh cài đặt độc lập */}
        <div className="flex flex-wrap gap-2">
          {([["tg", "📨 Telegram"], ["zalo", "💬 Zalo Bot"], ["zalop", "👤 Zalo Cá Nhân"]] as const)
            .map(([k, lb]) => (
              <button key={k} type="button" className={tabBtn(chTab === k)}
                onClick={() => {
                  setChTab(k);
                  // Tab '🔑 Tài khoản & QR' chỉ có ở kênh Zalo Cá Nhân.
                  if (k !== "zalop" && subTab === "zaccounts") setSubTab("settings");
                }}>
                {lb}
              </button>
            ))}
        </div>
        {/* Tab CON trong kênh */}
        <div className="flex flex-wrap gap-2">
          {(([
            ["settings", "⚙️ Cài đặt kênh"],
            ...(chTab === "zalop" ? [["zaccounts", "🔑 Tài khoản & QR"]] : []),
            ["directory", "📒 Danh bạ"],
            ["filter", "🎚️ Lọc thread"],
            ["branches", "🧭 Nhánh agent"],
          ]) as ["settings" | "zaccounts" | "directory" | "filter" | "branches", string][])
            .map(([k, lb]) => (
              <button key={k} type="button" className={tabBtn(subTab === k)}
                onClick={() => setSubTab(k)}>
                {lb}
              </button>
            ))}
        </div>

        {/* ── Telegram — Cài đặt kênh ── */}
        {chTab === "tg" && subTab === "settings" && (
          <div className="space-y-3 mt-1">
          <p className="text-[10px] text-muted-foreground">
            Domain HTTPS / Tunnel chỉ cấu hình ở mục <b>Cloudflare (hạ tầng chung)</b> —
            một lần cho mọi bot, không lặp theo kênh.
          </p>
          <div>
            <label className="text-xs text-muted-foreground">
              Danh sách bot Telegram — mỗi bot 1 token riêng (token từ @BotFather)
            </label>
            {config && (
              <BotListEditor
                bots={((config as any)?.telegram_bots as any[]) || []}
                models={models}
                names={botNames.telegram}
                platform="tg"
                fallbackOptions={fallbackOptions}
                tokenPlaceholder="123456:ABC-DEF1234ghikl..."
                onChange={(b) => setField("telegram_bots", b)}
              />
            )}
          </div>
          <p className="text-[10px] text-muted-foreground">
            🔔 thông báo · 📋 log provider · 💬 chat mới · HA · fallback · model:
            bật/tắt <b>từng Admin #1, #2…</b> trong thẻ bot ở trên (không còn công tắc kênh).
          </p>
          <ChannelActivityPanel platform="tg" title="Telegram — hoạt động gần đây & blacklist (theo từng bot)" />
          </div>
        )}

        {/* ── Zalo Bot — Cài đặt kênh ── */}
        {chTab === "zalo" && subTab === "settings" && (
          <div className="space-y-3 mt-1">
          <p className="text-[10px] text-muted-foreground">
            Webhook HTTPS dùng cấu hình <b>Cloudflare (hạ tầng chung)</b> ở mục
            Settings riêng — không cài lại ở đây. Hệ thống tự đăng ký{" "}
            <code>/zalo/webhook</code>.
          </p>
          <div>
            <label className="text-xs text-muted-foreground">
              Danh sách bot Zalo — mỗi bot 1 token riêng
            </label>
            {config && (
              <BotListEditor
                bots={((config as any)?.zalo_bots as any[]) || []}
                models={models}
                names={botNames.zalo}
                platform="zalo"
                fallbackOptions={fallbackOptions}
                tokenPlaceholder="1946930502...:HxGk..."
                onChange={(b) => setField("zalo_bots", b)}
              />
            )}
          </div>
          <p className="text-[10px] text-muted-foreground">
            🔔 · 📋 · 💬 chat mới · HA · fallback · model: cấu hình <b>từng admin</b> trong thẻ bot
            (không còn công tắc kênh).
          </p>
          <ChannelActivityPanel platform="zalo" title="Zalo Bot — hoạt động gần đây & blacklist" />
          </div>
        )}

        {/* ── Zalo Cá Nhân — Cài đặt kênh (mỗi acc = 1 thẻ, Admin #1/#2…) ── */}
        {chTab === "zalop" && subTab === "settings" && (
          <div className="space-y-3 mt-1">
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5"
              checked={Boolean(cfg.zalo_personal_enabled)}
              onChange={(e) => setField("zalo_personal_enabled", e.target.checked)} />
            Bật kênh Zalo Cá Nhân
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5"
              checked={Boolean(cfg.zalo_personal_ai_enabled ?? true)}
              onChange={(e) => setField("zalo_personal_ai_enabled", e.target.checked)} />
            🤖 Bật AI trả lời (thread thường qua bộ lọc / admin)
          </label>
          <div>
            <label className="text-[10px] text-muted-foreground">
              Model AI mặc định kênh (chat thường — admin có model riêng)
            </label>
            <Select value={String(cfg.zalo_personal_ai_model || " ")}
              onValueChange={(v) => setField("zalo_personal_ai_model", v.trim())}>
              <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Mặc định hệ thống" /></SelectTrigger>
              <SelectContent>
                <SelectItem value=" ">-- Mặc định hệ thống --</SelectItem>
                {Array.from(new Set([...models, ...(cfg.zalo_personal_ai_model ? [String(cfg.zalo_personal_ai_model)] : [])])).map((m) => (
                  <SelectItem key={m} value={m}>{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Hạ tầng gọn — tương đương token server, không phải cài admin */}
          <details className="rounded-md border border-border p-2 text-[11px]">
            <summary className="cursor-pointer font-medium text-muted-foreground">
              Hạ tầng zca-js / webhook (tuỳ chọn)
            </summary>
            <div className="space-y-2 mt-2">
              <div>
                <label className="text-[10px] text-muted-foreground">URL bot server (trống = 127.0.0.1:3001 nhúng)</label>
                <Input value={String(cfg.zalo_personal_server_url || "")}
                  onChange={(e) => setField("zalo_personal_server_url", e.target.value)}
                  placeholder="Trống = nhúng nội bộ" className="h-8 text-xs" />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-muted-foreground">User bot server</label>
                  <Input value={String(cfg.zalo_personal_username || "")}
                    onChange={(e) => setField("zalo_personal_username", e.target.value)}
                    placeholder="admin" className="h-8 text-xs" />
                </div>
                <div>
                  <label className="text-[10px] text-muted-foreground">Mật khẩu</label>
                  <Input type="password" value={String(cfg.zalo_personal_password || "")}
                    onChange={(e) => setField("zalo_personal_password", e.target.value)}
                    placeholder="admin" className="h-8 text-xs" />
                </div>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Webhook base nội bộ (trống = container)</label>
                <Input value={String(cfg.zalo_personal_webhook_base || "")}
                  onChange={(e) => setField("zalo_personal_webhook_base", e.target.value)}
                  placeholder="Trống = 127.0.0.1:80" className="h-8 text-xs" />
              </div>
              <label className="flex items-center gap-2 text-[11px] text-muted-foreground cursor-pointer select-none">
                <input type="checkbox" className="size-3.5"
                  checked={Boolean(cfg.zalo_personal_auto_webhook ?? true)}
                  onChange={(e) => setField("zalo_personal_auto_webhook", e.target.checked)} />
                Tự đăng ký webhook mọi acc về gateway
              </label>
              <div>
                <label className="text-[10px] text-muted-foreground">Acc gửi mặc định (trống = acc đầu)</label>
                <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-8"
                  value={String(cfg.zalo_personal_account_id || "")}
                  onChange={(e) => setField("zalo_personal_account_id", e.target.value)}>
                  <option value="">-- Acc đầu trong danh sách --</option>
                  {zalopAccounts.map((a) => (
                    <option key={a.ownId} value={a.ownId}>{zalopAccLabel(a)}</option>
                  ))}
                </select>
              </div>
            </div>
          </details>

          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">
              Danh sách tài khoản
            </label>
            {zalopAccounts.length === 0 ? (
              <p className="text-[10px] text-muted-foreground italic">
                Chưa thấy tài khoản — tab &quot;🔑 Tài khoản &amp; QR&quot; đăng nhập QR, rồi tải lại Settings.
              </p>
            ) : (
              zalopAccounts.map((acc) => {
                const ownId = acc.ownId;
                const map = ((config as any)?.zalo_personal_account_admins || {}) as Record<string, any>;
                const entry = map[ownId] || {};
                let admins: AdminEntry[] = parseAdminEntries(entry);
                if (!admins.length && entry.admin_thread) {
                  admins = parseAdminEntries({
                    admin_thread: entry.admin_thread,
                    admin_thread_type: entry.admin_thread_type,
                  });
                }
                const patchAcc = (p: Record<string, unknown>) => {
                  const next = { ...map, [ownId]: { ...entry, ...p } };
                  setField("zalo_personal_account_admins", next);
                };
                const setAdmins = (list: AdminEntry[]) => {
                  // Đồng bộ cờ 🔔/📋/💬 cấp acc từ Admin #N (giống Telegram/Zalo Bot)
                  const anyNotify = list.some((a) => a.notify_enabled);
                  const anyLog = list.some((a) => a.account_log_enabled);
                  const anyNew = list.some((a) => a.newchat_alert_enabled);
                  patchAcc({
                    admin_entries: list,
                    admin_thread: list[0]?.chat_id || "",
                    admin_thread_type: list[0]?.kind === "group" ? "1" : "0",
                    notify_admin_enabled: anyNotify || list.length === 0,
                    account_log_enabled: anyLog || list.length === 0,
                    newchat_alert_enabled: anyNew || list.length === 0,
                  });
                };
                const patchZalopAdmin = (idx: number, p: Partial<AdminEntry>) => {
                  setAdmins(admins.map((x, i) => (i === idx ? { ...x, ...p } : x)));
                };
                const resolveZalopAdmin = async (idx: number) => {
                  const a = admins[idx];
                  if (!a?.chat_id.trim()) {
                    toast.error("Cần Thread ID");
                    return;
                  }
                  const key = `zalop-${ownId}-${idx}`;
                  setResolving(key);
                  try {
                    const res: any = await request.post("/api/zalo-personal/resolve-thread", {
                      account_id: ownId,
                      thread_id: a.chat_id.trim(),
                      kind: a.kind,
                    });
                    const d = res.data || {};
                    patchZalopAdmin(idx, {
                      name: String(d.name || a.name || "").trim(),
                      kind: d.kind === "group" ? "group" : "private",
                    });
                    if (d.ok) toast.success(d.name ? `Nhận diện: ${d.name}` : "Đã nhận diện");
                    else toast.message("zca-js chưa thấy thread — sửa tay kind/tên nếu sai");
                  } catch {
                    toast.error("Không resolve được (zca-js / tài khoản?)");
                  } finally {
                    setResolving("");
                  }
                };
                return (
                  <div key={ownId} className="rounded-md border border-border p-2 space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <label className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none shrink-0">
                        <input type="checkbox" className="size-3.5"
                          checked={entry.enabled !== false}
                          onChange={(e) => patchAcc({ enabled: e.target.checked })} />
                        Bật
                      </label>
                      <span className="text-[12px] font-medium truncate flex-1">
                        {zalopAccLabel(acc)}
                      </span>
                    </div>

                    <div className="space-y-2">
                      <label className="text-xs font-medium text-muted-foreground">
                        Admin #1, #2… — Tên · ID · Loại · Nhận diện · Model · 🔔 📋 💬 · ✍️ · màu · HA · Fallback
                      </label>
                      {admins.map((a, idx) => (
                        <div key={idx} className="rounded-md border border-border p-2.5 space-y-2 bg-muted/10">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-semibold">Admin #{idx + 1}</span>
                            <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-[10px]"
                              onClick={() => setAdmins(admins.filter((_, i) => i !== idx))}>Xóa</Button>
                          </div>
                          <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5">
                            <div>
                              <label className="text-[10px] text-muted-foreground">Tên</label>
                              <Input className="h-8 text-xs" value={a.name}
                                onChange={(e) => patchZalopAdmin(idx, { name: e.target.value })}
                                placeholder="Tên dễ nhớ" />
                            </div>
                            <div>
                              <label className="text-[10px] text-muted-foreground">Thread ID</label>
                              <Input className="h-8 text-xs font-mono" value={a.chat_id}
                                onChange={(e) => {
                                  const cid = e.target.value;
                                  patchZalopAdmin(idx, {
                                    chat_id: cid,
                                    kind: a.name ? a.kind : guessKind(cid),
                                  });
                                }}
                                placeholder="userId / groupId" />
                            </div>
                            <div>
                              <label className="text-[10px] text-muted-foreground">Loại</label>
                              <div className="flex gap-1">
                                <select className="h-8 flex-1 rounded-md border border-border bg-background px-1 text-[11px]"
                                  value={a.kind}
                                  onChange={(e) => patchZalopAdmin(idx, {
                                    kind: e.target.value as "private" | "group",
                                  })}>
                                  <option value="private">Cá nhân</option>
                                  <option value="group">Nhóm</option>
                                </select>
                                <Button type="button" variant="outline" size="sm" className="h-8 px-2 text-[10px]"
                                  disabled={resolving === `zalop-${ownId}-${idx}`}
                                  onClick={() => resolveZalopAdmin(idx)}>
                                  {resolving === `zalop-${ownId}-${idx}` ? "…" : "Nhận diện"}
                                </Button>
                              </div>
                            </div>
                          </div>

                          {/* Persona riêng Admin (Zalo Cá nhân) — độc lập */}
                          <PersonaInline platform="zalop"
                            groupId={a.kind === "group" ? a.chat_id : ""}
                            userId={a.kind === "group" ? "" : a.chat_id} />

                          <div>
                            <label className="text-[10px] text-muted-foreground">
                              🤖 Nền tảng / Model AI (riêng Admin #{idx + 1})
                            </label>
                            <Select
                              value={a.ai_model || " "}
                              onValueChange={(v) => patchZalopAdmin(idx, { ai_model: v.trim() })}
                            >
                              <SelectTrigger className="h-8 text-xs">
                                <SelectValue placeholder="Kế thừa model kênh" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value=" ">-- Kế thừa model kênh --</SelectItem>
                                {Array.from(new Set([
                                  ...models,
                                  ...(a.ai_model ? [a.ai_model] : []),
                                  ...(cfg.zalo_personal_ai_model ? [String(cfg.zalo_personal_ai_model)] : []),
                                ])).map((m) => (
                                  <SelectItem key={m} value={m}>{m}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>

                          <div className="space-y-1 rounded border border-border/50 p-2">
                            <p className="text-[10px] font-medium text-muted-foreground">Thông báo tới admin này</p>
                            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                              <input type="checkbox" className="size-3.5" checked={a.notify_enabled}
                                onChange={(e) => patchZalopAdmin(idx, { notify_enabled: e.target.checked })} />
                              🔔 Lỗi &amp; cảnh báo
                            </label>
                            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                              <input type="checkbox" className="size-3.5" checked={a.account_log_enabled}
                                onChange={(e) => patchZalopAdmin(idx, { account_log_enabled: e.target.checked })} />
                              📋 Log tài khoản provider (Thêm/Xóa/Lỗi/Quota…)
                            </label>
                            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                              <input type="checkbox" className="size-3.5" checked={a.account_update_log_enabled}
                                onChange={(e) => patchZalopAdmin(idx, { account_update_log_enabled: e.target.checked })} />
                              🔄 Log Cập nhật tài khoản (bản ghi token/status định kỳ)
                            </label>
                            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                              <input type="checkbox" className="size-3.5" checked={a.newchat_alert_enabled}
                                onChange={(e) => patchZalopAdmin(idx, { newchat_alert_enabled: e.target.checked })} />
                              💬 Chat/nhóm mới (thread ID)
                            </label>
                          </div>

                          <div className="space-y-1 rounded border border-border/50 p-2">
                            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                              <input type="checkbox" className="size-3.5" checked={a.emphasis_enabled}
                                onChange={(e) => patchZalopAdmin(idx, { emphasis_enabled: e.target.checked })} />
                              ✍️ Nhấn mạnh số liệu &amp; thông tin chính
                            </label>
                            <div className="flex flex-wrap gap-3 pl-1">
                              <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer select-none">
                                <input type="checkbox" className="size-3.5" checked={a.emphasis_numbers}
                                  disabled={!a.emphasis_enabled}
                                  onChange={(e) => patchZalopAdmin(idx, { emphasis_numbers: e.target.checked })} />
                                Số
                              </label>
                              <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer select-none">
                                <input type="checkbox" className="size-3.5" checked={a.emphasis_units}
                                  disabled={!a.emphasis_enabled}
                                  onChange={(e) => patchZalopAdmin(idx, { emphasis_units: e.target.checked })} />
                                Đơn vị (°C, %)
                              </label>
                              <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer select-none">
                                <input type="checkbox" className="size-3.5" checked={a.emphasis_key_info}
                                  disabled={!a.emphasis_enabled}
                                  onChange={(e) => patchZalopAdmin(idx, { emphasis_key_info: e.target.checked })} />
                                Thông tin chính
                              </label>
                            </div>
                            <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-[11px]"
                              value={a.emphasis_style || "bold"}
                              disabled={!a.emphasis_enabled}
                              onChange={(e) => patchZalopAdmin(idx, { emphasis_style: e.target.value })}>
                              <option value="bold">Đậm (bold)</option>
                              <option value="code">Monospace</option>
                              <option value="bold_code">Đậm + monospace</option>
                            </select>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1 border-t border-border/40">
                              <div>
                                <label className="text-[10px] text-muted-foreground">🎨 Màu chữ (zca-js)</label>
                                <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-[11px]"
                                  value={a.markdown_color || "orange"}
                                  disabled={!a.emphasis_enabled}
                                  onChange={(e) => patchZalopAdmin(idx, { markdown_color: e.target.value })}>
                                  <option value="orange">Cam</option>
                                  <option value="red">Đỏ</option>
                                  <option value="yellow">Vàng</option>
                                  <option value="green">Xanh lá</option>
                                  <option value="none">Không màu</option>
                                </select>
                              </div>
                              <div>
                                <label className="text-[10px] text-muted-foreground">🔠 Cỡ chữ</label>
                                <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-[11px]"
                                  value={a.markdown_size || "normal"}
                                  disabled={!a.emphasis_enabled}
                                  onChange={(e) => patchZalopAdmin(idx, { markdown_size: e.target.value })}>
                                  <option value="normal">Thường</option>
                                  <option value="big">Lớn (f_18)</option>
                                  <option value="small">Nhỏ (f_13)</option>
                                </select>
                              </div>
                            </div>
                          </div>

                          <div className="flex flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:gap-4">
                            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                              <input type="checkbox" className="size-3.5" checked={a.ha_fastpath}
                                onChange={(e) => patchZalopAdmin(idx, { ha_fastpath: e.target.checked })} />
                              ⚡ Điều khiển nhà cục bộ (HA fastpath)
                            </label>
                            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                              <input type="checkbox" className="size-3.5" checked={a.fallback_enabled}
                                onChange={(e) => patchZalopAdmin(idx, { fallback_enabled: e.target.checked })} />
                              Fallback khi gửi không được (dùng admin này)
                            </label>
                          </div>
                        </div>
                      ))}
                      <Button type="button" variant="outline" size="sm" className="h-8"
                        onClick={() => setAdmins([...admins, emptyAdmin()])}>+ Thêm admin</Button>
                    </div>

                    <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5"
                        checked={entry.ha_fastpath !== false}
                        onChange={(e) => patchAcc({ ha_fastpath: e.target.checked })} />
                      ⚡ HA mặc định acc (chat không phải admin)
                    </label>
                    <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5"
                        checked={Boolean(entry.fallback_enabled)}
                        onChange={(e) => patchAcc({ fallback_enabled: e.target.checked })} />
                      Fallback khi acc này gửi không được (bot khác)
                    </label>
                    {entry.fallback_enabled ? (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                        <select className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                          value={
                            entry.fallback_channel && entry.fallback_bot_name
                              ? `${entry.fallback_channel}::${entry.fallback_bot_name}`
                              : entry.fallback_channel || ""
                          }
                          onChange={(e) => {
                            const v = e.target.value;
                            if (!v) {
                              patchAcc({ fallback_channel: "", fallback_bot_name: "" });
                              return;
                            }
                            const [ch, ...rest] = v.split("::");
                            patchAcc({ fallback_channel: ch, fallback_bot_name: rest.join("::") });
                          }}>
                          <option value="">— Chọn bot theo tên —</option>
                          {fallbackOptions.map((o) => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                        <Input className="h-8 text-xs font-mono"
                          value={String(entry.fallback_thread || "")}
                          onChange={(e) => patchAcc({ fallback_thread: e.target.value })}
                          placeholder="Thread fallback" />
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>
          <ChannelActivityPanel platform="zalop" title="Zalo Cá Nhân — hoạt động gần đây & blacklist (theo acc)" />
          </div>
        )}

        {/* ── Zalo Cá Nhân — Tài khoản & QR / Webhook / Proxy / Danh bạ (từ trang /zalo cũ) ── */}
        {chTab === "zalop" && subTab === "zaccounts" && <ZaloPersonalPanel />}

        {/* ── Danh bạ thread — setting + auto bot ── */}
        {subTab === "directory" && (
          <div className="space-y-3 mt-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold flex-1">
                📒 Danh bạ — {chTab === "tg" ? "Telegram" : chTab === "zalo" ? "Zalo Bot" : "Zalo Cá Nhân"}
              </p>
              <Button type="button" variant="outline" size="sm" className="h-8 text-xs"
                disabled={dirLoading} onClick={() => void loadDirectory()}>
                {dirLoading ? "Đang tải…" : "Làm mới"}
              </Button>
            </div>
            <p className="text-[10px] text-muted-foreground">
              Chỉ hiện mục <b>bạn đã đồng ý lưu</b> (trả lời <code>có</code> khi báo
              chat mới) hoặc đã thêm trong <b>Admin #N</b> / <b>Lọc thread</b>.
              Tin lạ không tự vào danh bạ. 4 cột: bot · Thread ID · loại · tên.
            </p>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-left text-[10px] text-muted-foreground">
                    <th className="px-2 py-1.5 font-medium">Bot / Acc</th>
                    <th className="px-2 py-1.5 font-medium">Thread ID</th>
                    <th className="px-2 py-1.5 font-medium">Loại</th>
                    <th className="px-2 py-1.5 font-medium">Tên</th>
                    <th className="px-2 py-1.5 font-medium">Nguồn</th>
                  </tr>
                </thead>
                <tbody>
                  {dirRows.length === 0 && !dirLoading && (
                    <tr>
                      <td colSpan={5} className="px-2 py-4 text-center text-muted-foreground italic">
                        Chưa có mục nào — cấu hình Admin / Lọc thread, hoặc chờ bot nhận tin.
                      </td>
                    </tr>
                  )}
                  {dirRows.map((r) => {
                    const src = (r.sources || []).map((s) => (
                      s === "admin" ? "Admin"
                        : s === "filter" ? "Lọc"
                          : s === "approved" ? "Đã duyệt"
                            : s
                    )).join(" · ");
                    return (
                      <tr key={`${r.bot_id}|${r.thread_id}`}
                        className="border-b border-border/60 hover:bg-muted/20">
                        <td className="px-2 py-1.5 max-w-[12rem]">
                          <div className="font-medium truncate" title={r.bot_label || r.bot_id}>
                            {r.bot_label || r.bot_id || "—"}
                          </div>
                        </td>
                        <td className="px-2 py-1.5 font-mono text-[11px] break-all max-w-[12rem]">
                          {r.thread_id}
                        </td>
                        <td className="px-2 py-1.5 whitespace-nowrap">
                          {r.kind === "group" ? "Nhóm" : "Cá nhân"}
                        </td>
                        <td className="px-2 py-1.5 max-w-[12rem]">
                          <span className="truncate block" title={r.name || ""}>
                            {r.name || <span className="text-muted-foreground italic">—</span>}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-[10px] text-muted-foreground whitespace-nowrap">
                          {src || "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-[10px] text-muted-foreground">
              {dirRows.length} mục · Nguồn: Admin / Lọc (Settings) · Đã duyệt
              (đồng ý khi báo 💬 chat mới).
            </p>
          </div>
        )}

        {/* ── Lọc chức năng theo thread — RIÊNG kênh đang chọn ── */}
        {subTab === "filter" && (
          <div className="space-y-3 mt-1">
          <p className="text-xs font-semibold">
            🎚️ Lọc chức năng theo thread — {chTab === "tg" ? "Telegram" : chTab === "zalo" ? "Zalo Bot" : "Zalo Cá Nhân"}
          </p>
          <p className="text-[10px] text-muted-foreground">
            Giới hạn chức năng AI cho từng khung chat, THEO TỪNG BOT. Chọn bot → nhập
            Thread/Chat ID → <b>Nhận diện</b> (tên + loại) hoặc <b>gõ tên tay</b> nếu
            API không trả. Chat KHÔNG có trong danh sách = cho phép tất cả. NHÓM: lọc
            tag + User ID (Nhận diện / gõ tên tương tự). 🔗 Webhook HA/n8n theo thread
            hoặc từng user.
          </p>
          {filterRows.filter((r) => r.botKey === chTab || r.botKey.startsWith(`${chTab}:`)).map((row) => (
            <div key={row.id} className="rounded-md border border-border p-2 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <Select
                  value={row.botKey}
                  onValueChange={(value) => setFilterField(row.id, { botKey: value })}
                >
                  <SelectTrigger className="w-44 shrink-0">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {optionsFor(row.botKey).map((o) => (
                      <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  value={row.chatId}
                  onChange={(e) => setFilterField(row.id, {
                    chatId: e.target.value,
                    // Đổi ID → xóa tên cũ (cần nhận diện / gõ lại)
                    name: e.target.value.trim() === row.chatId.trim() ? row.name : "",
                  })}
                  placeholder={
                    chTab === "zalop" || chTab === "zalo"
                      ? "Thread ID (userId / groupId)"
                      : "Chat ID (vd: 123456789)"
                  }
                  className="flex-1 min-w-[10rem] font-mono text-xs"
                />
                <select
                  className="rounded-md border border-border bg-background px-2 text-xs h-9 shrink-0"
                  value={row.kind === "user" ? "user" : "group"}
                  onChange={(e) => setFilterField(row.id, { kind: e.target.value })}
                  title="Thread này là nhóm hay chat cá nhân — cá nhân thì không cần lọc user/tag"
                >
                  <option value="group">Nhóm</option>
                  <option value="user">Cá nhân</option>
                </select>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-9 shrink-0 text-[11px]"
                  disabled={filterResolving === `tf-${row.id}` || !row.chatId.trim()}
                  onClick={() => void resolveFilterThread(row)}
                  title="Nhận diện tên + loại (Bot API / zca-js). Fail → gõ tên tay"
                >
                  {filterResolving === `tf-${row.id}` ? "…" : "Nhận diện"}
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => removeFilterRow(row.id)}>
                  Xóa
                </Button>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">
                  Tên hiển thị (tự điền sau Nhận diện — hoặc gõ tay)
                </label>
                <Input
                  value={row.name || ""}
                  onChange={(e) => setFilterField(row.id, { name: e.target.value })}
                  placeholder="Vd: Nhóm gia đình / Nguyễn Văn A"
                  className="h-8 text-xs"
                />
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {FUNCTION_GROUPS.map(([key, label]) => (
                  <label
                    key={key}
                    className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none"
                  >
                    <input
                      type="checkbox"
                      className="size-3.5"
                      checked={row.groups.includes(key)}
                      onChange={() => toggleFilterGroup(row.id, key)}
                    />
                    {label}
                  </label>
                ))}
              </div>
              {row.groups.length === 0 && (
                <p className="text-[10px] text-amber-600">
                  ⚠️ Chưa tích nhóm nào → thread này bị chặn mọi chức năng (chỉ chat).
                </p>
              )}

              {/* Bộ lọc TAG — chỉ trả lời khi bị tag (chỉ hiện với thread NHÓM) */}
              {row.kind !== "user" && (
              <div className="rounded border border-dashed border-border/70 p-2 space-y-1.5">
                <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                  <input
                    type="checkbox"
                    className="size-3.5"
                    checked={row.requireMention}
                    onChange={() => setFilterField(row.id, { requireMention: !row.requireMention })}
                  />
                  🏷️ Bắt buộc tag mới trả lời (nhóm) — không bật = trả lời mọi tin
                </label>
                {row.requireMention && (
                  <Input
                    value={row.mentionKeyword}
                    onChange={(e) => setFilterField(row.id, { mentionKeyword: e.target.value })}
                    placeholder="Từ khóa tag, vd: @Bot Bến Bắp (Telegram tự nhận @username; Zalo dùng từ khóa này)"
                    className="h-8 text-xs"
                  />
                )}
              </div>
              )}

              {/* Chuyển tiếp webhook (HA / n8n / URL bất kỳ) — cấp THREAD */}
              <div className="rounded border border-dashed border-border/70 p-2 space-y-1.5">
                <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                  <input
                    type="checkbox"
                    className="size-3.5"
                    checked={row.forward}
                    onChange={() => setFilterField(row.id, { forward: !row.forward })}
                  />
                  🔗 Chuyển tiếp webhook (HA / n8n / URL bất kỳ)
                </label>
                {row.forward && (
                  <>
                    <Input
                      value={row.forwardUrl}
                      onChange={(e) => setFilterField(row.id, { forwardUrl: e.target.value })}
                      placeholder="https://ha.local/api/webhook/xxx — POST JSON {platform, bot, chat_id, user_id, sender, text…}"
                      className="h-8 text-xs"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Mọi tin của thread này chuyển tới URL trên; từng user bên dưới có thể
                      TẮT riêng (bật/tắt, dùng chung URL thread). Không tích ở đây → từng
                      user tự bật + cài URL riêng (mỗi người một webhook khác nhau).
                    </p>
                  </>
                )}
              </div>

              {/* Tầng lọc USER trong nhóm — chỉ hiện với thread NHÓM (cá nhân không cần) */}
              {row.kind !== "user" && (
              <div className="rounded border border-dashed border-border/70 p-2 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">👥 Lọc theo User ID trong nhóm</span>
                  <Button type="button" variant="ghost" size="sm" className="h-6 text-[11px]"
                    onClick={() => addUserRow(row.id)}>
                    + Thêm user
                  </Button>
                </div>
                <p className="text-[10px] text-muted-foreground">
                  User KHÔNG có trong danh sách = hưởng full quyền của nhóm ở trên. Thêm user
                  để giới hạn riêng — chỉ tick được trong các mục nhóm đã cho phép.
                </p>
                {row.users.map((u) => (
                  <div key={u.id} className="rounded bg-muted/40 p-1.5 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Input
                        value={u.userId}
                        onChange={(e) => setUserField(row.id, u.id, {
                          userId: e.target.value,
                          name: e.target.value.trim() === u.userId.trim() ? u.name : "",
                        })}
                        placeholder="User ID (gõ /id trong nhóm để lấy)"
                        className="h-7 text-xs font-mono flex-1 min-w-[8rem]"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 text-[11px] shrink-0"
                        disabled={filterResolving === `tfu-${row.id}-${u.id}` || !u.userId.trim()}
                        onClick={() => void resolveFilterUser(row, u)}
                        title="Nhận diện tên user. Fail → gõ tên tay"
                      >
                        {filterResolving === `tfu-${row.id}-${u.id}` ? "…" : "Nhận diện"}
                      </Button>
                      <Button type="button" variant="ghost" size="sm" className="h-6 text-[11px]"
                        onClick={() => removeUserRow(row.id, u.id)}>
                        Xóa
                      </Button>
                    </div>
                    <Input
                      value={u.name || ""}
                      onChange={(e) => setUserField(row.id, u.id, { name: e.target.value })}
                      placeholder="Tên user (tự điền / gõ tay)"
                      className="h-7 text-xs"
                    />
                    <div className="flex flex-wrap gap-x-3 gap-y-1">
                      {FUNCTION_GROUPS.filter(([key]) => row.groups.includes(key)).map(([key, label]) => (
                        <label key={key}
                          className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none">
                          <input
                            type="checkbox"
                            className="size-3.5"
                            checked={u.groups.includes(key)}
                            onChange={() => toggleUserGroup(row.id, u.id, key, row.groups)}
                          />
                          {label}
                        </label>
                      ))}
                      {row.groups.length === 0 && (
                        <span className="text-[10px] text-amber-600">Thread chưa cho phép nhóm nào → user không có gì để tick.</span>
                      )}
                    </div>
                    {/* Chuyển tiếp webhook cấp USER: thread đang bật → chỉ bật/tắt
                        (dùng URL thread); thread không bật → bật + URL riêng. */}
                    <div className="space-y-1">
                      <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
                        <input
                          type="checkbox"
                          className="size-3.5"
                          checked={u.forward}
                          onChange={() => setUserField(row.id, u.id, { forward: !u.forward })}
                        />
                        🔗 Chuyển tiếp webhook{row.forward && row.forwardUrl.trim() ? " (dùng URL của thread)" : " (URL riêng của user)"}
                      </label>
                      {u.forward && !(row.forward && row.forwardUrl.trim()) && (
                        <Input
                          value={u.forwardUrl}
                          onChange={(e) => setUserField(row.id, u.id, { forwardUrl: e.target.value })}
                          placeholder="URL webhook riêng cho user này (HA / n8n / URL bất kỳ)"
                          className="h-7 text-xs"
                        />
                      )}
                      {u.forward && (
                        <>
                          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
                            <input
                              type="checkbox"
                              className="size-3.5"
                              checked={u.forwardTagOnly}
                              onChange={() => setUserField(row.id, u.id, { forwardTagOnly: !u.forwardTagOnly })}
                            />
                            🏷️ Chỉ chuyển webhook khi TAG bot — không tag thì ChatGPT trả lời
                          </label>
                          {u.forwardTagOnly && (
                            <p className="text-[10px] text-muted-foreground">
                              Tin có tag → CHỈ đi webhook (AI im lặng); tin thường → AI trả lời,
                              không chuyển. Nhận diện tag: Telegram = @mention bot hoặc từ khóa
                              tag của thread; Zalo Bot = từ khóa tag (không đặt → mọi tin nhóm
                              đều là tag vì nền tảng bắt buộc @tag); Zalo Cá Nhân = cần đặt từ
                              khóa tag ở bộ lọc tag của thread.
                            </p>
                          )}
                        </>
                      )}
                    </div>
                    {/* Persona RIÊNG user này trong thread — độc lập như webhook */}
                    <PersonaInline platform={row.botKey} groupId={row.chatId}
                      userId={u.userId} />
                  </div>
                ))}
              </div>
              )}
              {/* Persona cấp THREAD (nhóm = fallback cho user chưa cài riêng;
                  thread cá nhân/admin = persona của chính chat 1-1 đó) */}
              <PersonaInline platform={row.botKey}
                groupId={row.kind !== "user" ? row.chatId : ""}
                userId={row.kind === "user" ? row.chatId : ""} />
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" onClick={addFilterRow}>
            + Thêm thread
          </Button>
          </div>
        )}

        {/* ── Nhánh Agent (định tuyến việc) — RIÊNG kênh đang chọn ── */}
        {subTab === "branches" && (
          <div className="space-y-3 mt-1">
          <p className="text-xs font-semibold">
            🧭 Nhánh Agent — {chTab === "tg" ? "Telegram" : chTab === "zalo" ? "Zalo Bot" : "Zalo Cá Nhân"}
          </p>
          <p className="text-[10px] text-muted-foreground">
            Cài đặt RIÊNG kênh này — mục nào để trống thì kênh dùng &quot;Mặc định
            chung&quot; bên dưới. (🔎 Kiểm duyệt code là cài đặt chung.)
          </p>
          {([
            ["image_gen", "🎨 Vẽ / tạo ảnh"],
            ["vision", "🔍 Phân tích ảnh"],
            ["music_gen", "🎵 Tạo nhạc"],
            ["video_gen", "🎬 Tạo video"],
            ["code", "💻 Viết / sửa code"],
          ] as [string, string][]).map(([key, label]) => {
            const byCh = ((config as any)?.agent_branches_by_channel || {}) as Record<string, Record<string, string>>;
            const current = String(byCh?.[chTab]?.[key] || "").trim();
            const globalVal = String((config as any)?.agent_branches?.[key] || "").trim();
            const extra = key === "video_gen"
              ? ["flow/veo-3.1-fast", "flow/veo-3.1-quality", "flow/veo-3.1-lite"] : [];
            const options = Array.from(new Set([...extra, ...models, ...(current ? [current] : [])]));
            return (
              <div key={key}>
                <label className="text-xs text-muted-foreground">{label}</label>
                <Select value={current}
                  onValueChange={(value) =>
                    setField("agent_branches_by_channel", {
                      ...byCh,
                      [chTab]: { ...(byCh?.[chTab] || {}), [key]: value.trim() },
                    })}>
                  <SelectTrigger>
                    <SelectValue placeholder={`Dùng chung${globalVal ? `: ${globalVal}` : ""}`} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value=" ">{`-- Dùng chung${globalVal ? ` (${globalVal})` : ""} --`}</SelectItem>
                    {options.map((m) => (<SelectItem key={m} value={m}>{m}</SelectItem>))}
                  </SelectContent>
                </Select>
              </div>
            );
          })}

          {/* Mặc định chung — 1 nơi duy nhất, áp mọi kênh + tab chat/HA/API ngoài */}
          <details className="group rounded-md border border-border p-2">
            <summary className="text-xs font-semibold cursor-pointer select-none">
              ⚙️ Mặc định chung (mọi kênh + tab chat / HA / API ngoài)
            </summary>
            <div className="space-y-3 mt-2">
          <p className="text-[10px] text-muted-foreground">
            Mỗi loại việc dùng model ở đây (chọn combo để có fallback tự động:
            model đầu chạy trước, lỗi xoay tiếp). Bot không hỏi lại người dùng.
          </p>
          {([
            ["image_gen", "🎨 Vẽ / tạo ảnh", "gma/image"],
            ["vision", "🔍 Phân tích ảnh", "gma/3.1-pro"],
            ["music_gen", "🎵 Tạo nhạc", "gma/auto"],
            ["video_gen", "🎬 Tạo video", "flow/veo-3.1-fast"],
            ["code", "💻 Viết / sửa code", "claude/sonnet-5"],
          ] as [string, string, string][]).map(([key, label, def]) => {
            const current = String((config as any)?.agent_branches?.[key] || "").trim();
            const extra = key === "video_gen"
              ? ["flow/veo-3.1-fast", "flow/veo-3.1-quality", "flow/veo-3.1-lite"]
              : [];
            const options = Array.from(new Set([
              ...extra,
              ...models,
              ...(current ? [current] : []),
            ]));
            return (
              <div key={key}>
                <label className="text-xs text-muted-foreground">{label}</label>
                <Select
                  value={current}
                  onValueChange={(value) =>
                    setField("agent_branches", {
                      ...((config as any)?.agent_branches || {}),
                      [key]: value.trim(),
                    })
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder={`Mặc định: ${def}`} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value=" ">{`-- Dùng mặc định (${def}) --`}</SelectItem>
                    {options.map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            );
          })}

          {/* Code reviewer — separate dropdown, saved into agent_branches.code_reviewer */}
          <div>
            <label className="text-xs text-muted-foreground">
              🔎 Kiểm duyệt code (Reviewer)
            </label>
            <p className="text-[10px] text-muted-foreground mb-1">
              Model soi lại code do &quot;Viết/sửa code&quot; tạo ra. Để trống = tắt review.
            </p>
            <Select
              value={String((config as any)?.agent_branches?.code_reviewer || "").trim()}
              onValueChange={(value) =>
                setField("agent_branches", {
                  ...((config as any)?.agent_branches || {}),
                  code_reviewer: value.trim(),
                })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="-- Tắt review (để trống) --" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value=" ">-- Tắt review --</SelectItem>
                {Array.from(new Set([
                  ...models,
                  ...( String((config as any)?.agent_branches?.code_reviewer || "").trim()
                    ? [String((config as any)?.agent_branches?.code_reviewer || "").trim()] : []),
                ])).map((m) => (
                  <SelectItem key={m} value={m}>{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
            </div>
          </details>
          </div>
        )}

        <Button
          onClick={async () => {
            await saveConfig();
            toast.success("Đã lưu cấu hình kênh chat");
          }}
          disabled={isSavingConfig}
          className="w-full"
          size="sm"
        >
          <Save className="size-3.5 mr-1.5" />
          {isSavingConfig ? "Đang lưu..." : "Lưu cấu hình kênh"}
        </Button>
      </CardContent>
    </Card>
    </>
  );
}

/** Hạ tầng HTTPS/tunnel — MỘT chỗ, dùng chung mọi kênh (không nằm trong tab Telegram/Zalo). */
export function CloudflareInfraCard() {
  const config = useSettingsStore((state) => state.config);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const setField = useSettingsStore((state) => state.setField);
  const saveConfig = useSettingsStore((state) => state.saveConfig);

  return (
    <Card>
      <CardContent className="space-y-4 pt-4">
        <div className="text-sm font-semibold flex items-center gap-2">
          <Cloud className="size-4 text-orange-500" /> Cloudflare (hạ tầng chung)
        </div>
        <p className="text-[11px] text-muted-foreground">
          Cấu hình <b>một lần</b> cho cả Telegram Bot và Zalo Bot. Không phải cài
          riêng từng kênh — domain HTTPS + tunnel dùng chung.
        </p>
        <div>
          <label className="text-xs text-muted-foreground">
            Public base URL (HTTPS) — webhook Telegram + Zalo
          </label>
          <Input
            value={String(config?.telegram_webhook_url || "")}
            onChange={(e) => setField("telegram_webhook_url", e.target.value)}
            placeholder="https://your-domain.com"
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            Domain public (Cloudflare Tunnel hoặc IP + HTTPS). Hệ thống đăng ký
            <code className="mx-0.5">/telegram/webhook</code> và
            <code className="mx-0.5">/zalo/webhook</code> trên cùng base URL; mỗi bot
            phân biệt bằng secret token.
          </p>
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Cloudflare Tunnel Token</label>
          <Input
            value={String(config?.cloudflare_tunnel_token || "")}
            onChange={(e) => setField("cloudflare_tunnel_token", e.target.value)}
            placeholder="eyJhIjoi..."
            type="password"
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            Zero Trust → Tunnels → token. Lưu xong <code>cloudflared</code> tự chạy
            trong container (nếu có binary).
          </p>
        </div>
        <Button
          onClick={async () => {
            await saveConfig();
            toast.success("Đã lưu Cloudflare (dùng chung mọi kênh)");
          }}
          disabled={isSavingConfig}
          className="w-full"
          size="sm"
        >
          <Save className="size-3.5 mr-1.5" />
          {isSavingConfig ? "Đang lưu..." : "Lưu Cloudflare"}
        </Button>
      </CardContent>
    </Card>
  );
}
