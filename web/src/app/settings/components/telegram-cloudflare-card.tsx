"use client";

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

// Trình sửa DANH SÁCH bot (đa-token) — mỗi bot: token + Chat IDs + model +
// bật/tắt + Thread ID admin RIÊNG (+ loại cá nhân/nhóm).
function BotListEditor({ bots, models, tokenPlaceholder, onChange, names }: {
  bots: any[];
  models: string[];
  tokenPlaceholder: string;
  onChange: (bots: any[]) => void;
  names?: Record<string, string>; // bot_id -> tên bot (getMe), hiển thị cạnh token
}) {
  type Row = {
    id: number;
    token: string;
    label: string;
    chat_ids: string;
    ai_model: string;
    enabled: boolean;
    /** Nhiều admin thread (mỗi dòng 1 ID) — độc lập, cùng nhận alert từ bot này */
    admin_threads: string;
    admin_thread_type: string;
    ha_fastpath: boolean;
    /** Toggle thông báo RIÊNG bot này — độc lập giữa các tài khoản bot */
    notify_admin_enabled: boolean;
    account_log_enabled: boolean;
    newchat_alert_enabled: boolean;
  };
  const [rows, setRows] = useState<Row[]>([]);
  const inited = useRef(false);
  const seq = useRef(1);

  useEffect(() => {
    if (inited.current || !Array.isArray(bots)) return;
    inited.current = true;
    setRows(bots.map((b) => {
      const ths: string[] = Array.isArray(b?.admin_threads)
        ? b.admin_threads.map((x: any) => String(x || "").trim()).filter(Boolean)
        : [];
      const one = String(b?.admin_thread || "").trim();
      if (one && !ths.includes(one)) ths.push(one);
      return {
        id: seq.current++,
        token: String(b?.token || ""),
        label: String(b?.label || ""),
        chat_ids: Array.isArray(b?.chat_ids) ? b.chat_ids.join(", ") : "",
        ai_model: String(b?.ai_model || ""),
        enabled: b?.enabled !== false,
        admin_threads: ths.join("\n"),
        admin_thread_type: String(b?.admin_thread_type || "0") === "1" ? "1" : "0",
        ha_fastpath: b?.ha_fastpath !== false,
        notify_admin_enabled: b?.notify_admin_enabled !== false,
        account_log_enabled: b?.account_log_enabled !== false,
        newchat_alert_enabled: b?.newchat_alert_enabled !== false,
      };
    }));
  }, [bots]);

  const commit = (next: Row[]) => {
    setRows(next);
    onChange(
      next.filter((r) => r.token.trim()).map((r) => {
        const threads = r.admin_threads.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
        return {
          token: r.token.trim(),
          label: r.label.trim(),
          chat_ids: r.chat_ids.split(",").map((s) => s.trim()).filter(Boolean),
          ai_model: r.ai_model.trim(),
          enabled: r.enabled,
          admin_thread: threads[0] || "",
          admin_threads: threads,
          admin_thread_type: r.admin_thread_type === "1" ? "1" : "0",
          ha_fastpath: r.ha_fastpath,
          notify_admin_enabled: r.notify_admin_enabled,
          account_log_enabled: r.account_log_enabled,
          newchat_alert_enabled: r.newchat_alert_enabled,
        };
      }),
    );
  };
  const add = () => commit([...rows, {
    id: seq.current++, token: "", label: "", chat_ids: "", ai_model: "", enabled: true,
    admin_threads: "", admin_thread_type: "0", ha_fastpath: true,
    notify_admin_enabled: true, account_log_enabled: true, newchat_alert_enabled: true,
  }]);
  const remove = (id: number) => commit(rows.filter((r) => r.id !== id));
  const patch = (id: number, p: Partial<Row>) => commit(rows.map((r) => (r.id === id ? { ...r, ...p } : r)));

  return (
    <div className="space-y-2 mt-1">
      {rows.map((row) => (
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
              placeholder="VD: Bot Nhà, Bot Shop (admin đặt — hiện trong cảnh báo)"
              className="flex-1 h-8 text-xs" />
          </div>
          {names?.[row.token.split(":")[0]] ? (
            <p className="text-[11px] text-muted-foreground -mt-1">
              🤖 Username nền tảng: <b>{names[row.token.split(":")[0]]}</b>
              {row.label ? <> · label: <b>{row.label}</b></> : null}
            </p>
          ) : null}
          <Select value={row.ai_model || " "} onValueChange={(v) => patch(row.id, { ai_model: v.trim() })}>
            <SelectTrigger>
              <SelectValue placeholder="Model (trống = mặc định cx/auto)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value=" ">-- Mặc định (cx/auto) --</SelectItem>
              {Array.from(new Set([...models, ...(row.ai_model ? [row.ai_model] : [])])).map((m) => (
                <SelectItem key={m} value={m}>{m}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input value={row.chat_ids} onChange={(e) => patch(row.id, { chat_ids: e.target.value })}
            placeholder="Chat IDs (phẩy ngăn cách, trống = cho phép tất cả)" />
          <div>
            <label className="text-[10px] text-muted-foreground">
              Admin threads của bot này (mỗi dòng 1 Chat ID — nhiều admin, độc lập, cùng nhận alert)
            </label>
            <textarea
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs min-h-14"
              value={row.admin_threads}
              onChange={(e) => patch(row.id, { admin_threads: e.target.value })}
              placeholder={"123456789\n987654321"}
            />
            <p className="text-[10px] text-muted-foreground mt-0.5">
              Mỗi admin tự đặt tên bot / tên danh bạ trong thread của mình. Không chéo bot.
            </p>
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground">Loại thread admin</label>
            <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
              value={row.admin_thread_type}
              onChange={(e) => patch(row.id, { admin_thread_type: e.target.value })}>
              <option value="0">Cá nhân</option>
              <option value="1">Nhóm</option>
            </select>
          </div>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5" checked={row.ha_fastpath}
              onChange={(e) => patch(row.id, { ha_fastpath: e.target.checked })} />
            ⚡ Điều khiển nhà cục bộ (lệnh rõ ràng chạy ngay, không vòng qua provider —
            không có provider vẫn điều khiển được, trả lời văn mẫu)
          </label>
          <div className="space-y-1 rounded-md border border-border/60 p-2">
            <p className="text-[10px] text-muted-foreground">
              Thông báo qua BOT NÀY — bật/tắt độc lập từng bot, áp cho cả Chat IDs lẫn
              admin threads phía trên. Công tắc tổng của kênh (bên dưới danh sách bot) vẫn phải bật.
            </p>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
              <input type="checkbox" className="size-3.5" checked={row.notify_admin_enabled}
                onChange={(e) => patch(row.id, { notify_admin_enabled: e.target.checked })} />
              🔔 Thông báo admin (lỗi / cảnh báo hệ thống)
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
              <input type="checkbox" className="size-3.5" checked={row.account_log_enabled}
                onChange={(e) => patch(row.id, { account_log_enabled: e.target.checked })} />
              📋 Log tài khoản provider (cần bật 🔔 ở trên)
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
              <input type="checkbox" className="size-3.5" checked={row.newchat_alert_enabled}
                onChange={(e) => patch(row.id, { newchat_alert_enabled: e.target.checked })} />
              💬 Báo chat/nhóm mới nhắn bot (gửi vào admin threads của bot này)
            </label>
          </div>
        </div>
      ))}
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
  const [zalopAccounts, setZalopAccounts] = useState<string[]>([]);
  // bot_id -> tên bot (getMe) — hiển thị TÊN thay mã số cho dễ chọn đúng bot.
  const [botNames, setBotNames] = useState<{ telegram: Record<string, string>; zalo: Record<string, string> }>(
    { telegram: {}, zalo: {} });
  // Tab KÊNH + tab con — mỗi kênh (Telegram / Zalo Bot / Zalo Cá Nhân) cài đặt
  // ĐỘC LẬP: cài đặt kênh, lọc thread, nhánh agent riêng từng kênh.
  const [chTab, setChTab] = useState<"tg" | "zalo" | "zalop">("tg");
  const [subTab, setSubTab] = useState<"settings" | "zaccounts" | "filter" | "branches">("settings");

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
    // Tài khoản Zalo Cá Nhân đang đăng nhập — cho dropdown lọc theo TỪNG tài khoản.
    request.get("/api/zalo-personal/accounts")
      .then((res: any) => {
        const list = (res.data?.accounts as any[]) || [];
        setZalopAccounts(list.map((a: any) => String(a?.ownId || "")).filter(Boolean));
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
  type UserRow = { id: number; userId: string; groups: string[]; forward: boolean; forwardUrl: string; forwardTagOnly: boolean };
  // kind: thread là "group" (nhóm) hay "user" (cá nhân) — cá nhân thì KHÔNG cần
  // tầng lọc user + bộ lọc tag (ẩn đi). Lưu ở config thread_filter_meta.
  type FilterRow = {
    id: number; botKey: string; chatId: string; kind: string; groups: string[];
    users: UserRow[]; requireMention: boolean; mentionKeyword: string;
    forward: boolean; forwardUrl: string;
  };
  const [filterRows, setFilterRows] = useState<FilterRow[]>([]);
  const filterInited = useRef(false);
  const rowSeq = useRef(1);

  useEffect(() => {
    if (filterInited.current) return;
    const tf = (config as any)?.thread_filters as Record<string, string[]> | undefined;
    const tuf = (config as any)?.thread_user_filters as Record<string, string[]> | undefined;
    const tmf = (config as any)?.thread_mention_filters as Record<string, { required?: boolean; keyword?: string }> | undefined;
    const tff = (config as any)?.thread_forward_filters as Record<string, { enabled?: boolean; url?: string; tag_mode?: boolean }> | undefined;
    const tfMeta = (config as any)?.thread_filter_meta as Record<string, { kind?: string }> | undefined;
    if (!tf && !tuf && !tmf && !tff) return;
    filterInited.current = true;

    const splitParent = (key: string): { botKey: string; chatId: string } => {
      const parts = key.split(":");
      if (parts.length >= 3) return { botKey: `${parts[0]}:${parts[1]}`, chatId: parts.slice(2).join(":") };
      if (parts.length === 2) return { botKey: parts[0], chatId: parts[1] };
      return { botKey: "tg", chatId: key };
    };

    // 1. Parent rows từ thread_filters (kind đọc từ thread_filter_meta, mặc định nhóm)
    const kindOf = (key: string) => (tfMeta?.[key]?.kind === "user" ? "user" : "group");
    const rows: FilterRow[] = Object.entries(tf || {}).map(([key, groups]) => {
      const { botKey, chatId } = splitParent(key);
      return { id: rowSeq.current++, botKey, chatId, kind: kindOf(key), groups: Array.isArray(groups) ? groups : [], users: [], requireMention: false, mentionKeyword: "", forward: false, forwardUrl: "" };
    });
    const findRow = (botKey: string, chatId: string) => rows.find((r) => r.botKey === botKey && r.chatId === chatId);
    const ensureRow = (botKey: string, chatId: string) => {
      let r = findRow(botKey, chatId);
      if (!r) { r = { id: rowSeq.current++, botKey, chatId, kind: kindOf(`${botKey}:${chatId}`), groups: [...FUNCTION_GROUPS.map(([k]) => k)], users: [], requireMention: false, mentionKeyword: "", forward: false, forwardUrl: "" }; rows.push(r); }
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
      matched.users.push({ id: rowSeq.current++, userId, groups: Array.isArray(groups) ? groups : [], forward: false, forwardUrl: "", forwardTagOnly: false });
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
  const botFilterOptions: { value: string; label: string }[] = [];
  for (const b of (((config as any)?.telegram_bots as any[]) || [])) {
    const id = String(b?.token || "").split(":")[0];
    if (id) botFilterOptions.push({ value: `tg:${id}`, label: `Telegram · ${botNames.telegram[id] || id}` });
  }
  botFilterOptions.push({ value: "tg", label: "Telegram · mọi bot" });
  for (const b of (((config as any)?.zalo_bots as any[]) || [])) {
    const id = String(b?.token || "").split(":")[0];
    if (id) botFilterOptions.push({ value: `zalo:${id}`, label: `Zalo · ${botNames.zalo[id] || id}` });
  }
  botFilterOptions.push({ value: "zalo", label: "Zalo · mọi bot" });
  for (const id of zalopAccounts) {
    botFilterOptions.push({ value: `zalop:${id}`, label: `Zalo Cá Nhân · ${id}` });
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
    const tfMeta: Record<string, { kind: string }> = {};
    for (const r of rows) {
      const id = r.chatId.trim();
      if (!id) continue;
      const parent = `${r.botKey}:${id}`;
      tf[parent] = r.groups;
      tfMeta[parent] = { kind: r.kind === "user" ? "user" : "group" };
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
          tuf[`${parent}:${uid}`] = u.groups;
          const uUrl = u.forwardUrl.trim();
          if (r.forward && rUrl) {
            // Thread đang chuyển tiếp: lưu bản ghi user khi TẮT riêng hoặc
            // bật "chỉ chuyển khi tag" (mặc định = thừa hưởng, không bản ghi).
            if (!u.forward) tff[`${parent}:${uid}`] = { enabled: false, url: uUrl, tag_mode: u.forwardTagOnly };
            else if (u.forwardTagOnly) tff[`${parent}:${uid}`] = { enabled: true, url: uUrl, tag_mode: true };
          } else if (u.forward || uUrl) {
            // Thread không chuyển tiếp: user tự bật + URL riêng.
            tff[`${parent}:${uid}`] = { enabled: u.forward && !!uUrl, url: uUrl, tag_mode: u.forwardTagOnly };
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
    commitFilters([...filterRows, { id: rowSeq.current++, botKey: tabFilterOptions[0]?.value || chTab, chatId: "", kind: "group", groups: [], users: [], requireMention: false, mentionKeyword: "", forward: false, forwardUrl: "" }]);
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
      r.id === rowId ? { ...r, users: [...r.users, { id: rowSeq.current++, userId: "", groups: [...r.groups], forward: r.forward, forwardUrl: "", forwardTagOnly: false }] } : r));
  const removeUserRow = (rowId: number, userId: number) =>
    commitFilters(filterRows.map((r) =>
      r.id === rowId ? { ...r, users: r.users.filter((u) => u.id !== userId) } : r));
  const setUserField = (rowId: number, userId: number, patch: Partial<UserRow>) =>
    commitFilters(filterRows.map((r) =>
      r.id === rowId ? { ...r, users: r.users.map((u) => (u.id === userId ? { ...u, ...patch } : u)) } : r));
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
            ["filter", "🎚️ Lọc thread"],
            ["branches", "🧭 Nhánh agent"],
          ]) as ["settings" | "zaccounts" | "filter" | "branches", string][])
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
                tokenPlaceholder="123456:ABC-DEF1234ghikl..."
                onChange={(b) => setField("telegram_bots", b)}
              />
            )}
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-3.5"
              checked={Boolean((config as any)?.telegram_notify_enabled ?? true)}
              onChange={(e) => setField("telegram_notify_enabled", e.target.checked)}
            />
            Gửi thông báo admin (lỗi / cảnh báo hệ thống) qua Telegram
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-3.5"
              checked={Boolean(cfg.telegram_newchat_alert_enabled ?? true)}
              onChange={(e) => setField("telegram_newchat_alert_enabled", e.target.checked)}
            />
            🆕 Báo chat/nhóm mới nhắn bot (đủ Chat ID + User ID người gửi)
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-3.5"
              checked={Boolean(
                (config as any)?.account_log_notify_telegram ??
                (config as any)?.account_log_notify_enabled ?? true
              )}
              onChange={(e) => setField("account_log_notify_telegram", e.target.checked)}
            />
            📋 Gửi log tài khoản provider (ChatGPT free / Codex / Gemini / Flow…) qua Telegram
          </label>
          <p className="text-[10px] text-muted-foreground -mt-1">
            Bật → log tài khoản MỌI provider (thêm, xóa, JWT/RT chết, các bước khôi phục
            [T0] refresh → [T1] tái dùng session → [T2] đăng nhập Google → [T3] hàng loạt,
            kèm email + provider) gửi bot admin Telegram. Tắt → chỉ ghi log trong UI.
          </p>
          <details className="rounded-md border border-border p-2">
            <summary className="text-xs font-semibold cursor-pointer">
              ⚙️ Fallback cũ (chỉ khi bot chưa có admin threads)
            </summary>
            <p className="text-[10px] text-muted-foreground mt-1 mb-2">
              Khuyến nghị: khai báo <b>Admin threads</b> ngay trên từng bot (nhiều ID).
              Ô dưới chỉ dùng tạm khi bot chưa có admin riêng.
            </p>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-muted-foreground">Thread ID admin fallback</label>
                <Input value={String(cfg.telegram_admin_thread || "")}
                  onChange={(e) => setField("telegram_admin_thread", e.target.value)}
                  placeholder="Chỉ khi bot không có admin_threads" />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Loại thread</label>
                <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                  value={String(cfg.telegram_admin_thread_type || "0")}
                  onChange={(e) => setField("telegram_admin_thread_type", e.target.value)}>
                  <option value="0">Cá nhân</option>
                  <option value="1">Nhóm</option>
                </select>
              </div>
            </div>
          </details>
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
                tokenPlaceholder="1946930502...:HxGk..."
                onChange={(b) => setField("zalo_bots", b)}
              />
            )}
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-3.5"
              checked={Boolean((config as any)?.zalo_notify_enabled ?? true)}
              onChange={(e) => setField("zalo_notify_enabled", e.target.checked)}
            />
            Gửi thông báo admin (lỗi / cảnh báo hệ thống) qua Zalo
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-3.5"
              checked={Boolean(
                (config as any)?.account_log_notify_zalo ??
                (config as any)?.account_log_notify_enabled ?? true
              )}
              onChange={(e) => setField("account_log_notify_zalo", e.target.checked)}
            />
            📋 Gửi log tài khoản provider (ChatGPT free / Codex / Gemini / Flow…) qua Zalo Bot
          </label>
          <p className="text-[10px] text-muted-foreground -mt-1">
            Log đủ email + provider + bước khôi phục [T0]–[T3]. Cần bật thông báo admin
            Zalo ở trên thì log mới gửi qua kênh này.
          </p>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-3.5"
              checked={Boolean(cfg.zalo_newchat_alert_enabled ?? true)}
              onChange={(e) => setField("zalo_newchat_alert_enabled", e.target.checked)}
            />
            🆕 Báo chat/nhóm mới nhắn bot (đủ Chat ID + User ID người gửi)
          </label>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-muted-foreground">Thread ID admin chung (fallback)</label>
              <Input value={String(cfg.zalo_admin_thread || "")}
                onChange={(e) => setField("zalo_admin_thread", e.target.value)}
                placeholder="Dùng khi bot chưa có Thread admin riêng" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Loại thread admin chung</label>
              <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                value={String(cfg.zalo_admin_thread_type || "0")}
                onChange={(e) => setField("zalo_admin_thread_type", e.target.value)}>
                <option value="0">Cá nhân</option>
                <option value="1">Nhóm</option>
              </select>
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground">
            Mỗi bot gửi alert bằng CHÍNH token của nó tới admin thread của bot đó
            (độc lập — không còn &quot;gửi hộ qua bot A&quot;). Bot chưa đặt admin riêng
            → dùng Thread admin chung ở trên nhưng vẫn gửi bằng chính bot nhận tin;
            gửi không được thì hệ thống fallback notifier đa kênh.
          </p>
          <ChannelActivityPanel platform="zalo" title="Zalo Bot — hoạt động gần đây & blacklist" />
          </div>
        )}

        {/* ── Zalo Cá Nhân — Cài đặt kênh (tài khoản cá nhân qua zca-js) ── */}
        {chTab === "zalop" && subTab === "settings" && (
          <div className="space-y-3 mt-1">
          <p className="text-[10px] text-muted-foreground">
            Đăng nhập QR, proxy, danh bạ ở tab &quot;🔑 Tài khoản &amp; QR&quot;.
            Cài đặt kênh (AI, admin) ở đây. Public HTTPS/tunnel <b>không</b> nằm
            trong tab này — xem mục <b>Cloudflare (hạ tầng chung)</b>.
          </p>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5"
              checked={Boolean(cfg.zalo_personal_enabled)}
              onChange={(e) => setField("zalo_personal_enabled", e.target.checked)} />
            Bật kênh Zalo Cá Nhân
          </label>

          <div>
            <label className="text-xs text-muted-foreground">URL bot server (trống = zalo-server nhúng trong image 127.0.0.1:3001)</label>
            <Input value={String(cfg.zalo_personal_server_url || "")}
              onChange={(e) => setField("zalo_personal_server_url", e.target.value)}
              placeholder="Trống = nhúng nội bộ (khuyến nghị)" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-muted-foreground">Tài khoản quản trị bot server</label>
              <Input value={String(cfg.zalo_personal_username || "")}
                onChange={(e) => setField("zalo_personal_username", e.target.value)} placeholder="admin" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Mật khẩu</label>
              <Input type="password" value={String(cfg.zalo_personal_password || "")}
                onChange={(e) => setField("zalo_personal_password", e.target.value)} placeholder="admin" />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">
              URL nội bộ bot server → gateway (không phải Cloudflare; trống = 127.0.0.1:80 trong container)
            </label>
            <Input value={String(cfg.zalo_personal_webhook_base || "")}
              onChange={(e) => setField("zalo_personal_webhook_base", e.target.value)}
              placeholder="Trống = nội bộ container (khuyến nghị)" />
            <p className="text-[10px] text-muted-foreground mt-1">
              Chỉ khi zalo-server và API không cùng container. Public domain vẫn chỉ
              cấu hình ở Cloudflare chung.
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5"
              checked={Boolean(cfg.zalo_personal_auto_webhook ?? true)}
              onChange={(e) => setField("zalo_personal_auto_webhook", e.target.checked)} />
            Tự động đăng ký webhook mọi tài khoản về gateway
          </label>
          <div>
            <label className="text-xs text-muted-foreground">Tài khoản gửi mặc định (ownId — trống = tài khoản đầu tiên)</label>
            <Input value={String(cfg.zalo_personal_account_id || "")}
              onChange={(e) => setField("zalo_personal_account_id", e.target.value)} />
          </div>

          {/* AI trả lời */}
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5"
              checked={Boolean(cfg.zalo_personal_ai_enabled ?? true)}
              onChange={(e) => setField("zalo_personal_ai_enabled", e.target.checked)} />
            🤖 Bật AI trả lời tin nhắn
          </label>
          <div>
            <label className="text-xs text-muted-foreground">Model AI (trống = cx/auto)</label>
            <Select value={String(cfg.zalo_personal_ai_model || " ")}
              onValueChange={(v) => setField("zalo_personal_ai_model", v.trim())}>
              <SelectTrigger><SelectValue placeholder="Mặc định cx/auto" /></SelectTrigger>
              <SelectContent>
                <SelectItem value=" ">-- Mặc định (cx/auto) --</SelectItem>
                {Array.from(new Set([...models, ...(cfg.zalo_personal_ai_model ? [String(cfg.zalo_personal_ai_model)] : [])])).map((m) => (
                  <SelectItem key={m} value={m}>{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Thread được phép trả lời (mỗi dòng 1 Thread ID — AN TOÀN: trống = không trả lời ai)</label>
            <textarea className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs min-h-16"
              value={asText(cfg.zalo_personal_chat_ids)}
              onChange={(e) => setField("zalo_personal_chat_ids", e.target.value)} />
          </div>

          {/* Chuyển tiếp webhook: đã gom về 'Lọc chức năng theo thread' bên dưới
              (khóa zalop:...). Config legacy zalo_personal_forward_webhooks vẫn
              chạy ở backend cho cấu hình cũ, chỉ bỏ trình sửa trên UI. */}
          <p className="text-[10px] text-muted-foreground">
            🔗 Chuyển tiếp webhook (HA / n8n) giờ cấu hình ở mục <b>Lọc chức năng theo
            thread</b> bên dưới — chọn tài khoản Zalo Cá Nhân, nhập Thread ID rồi tích
            &quot;Chuyển tiếp webhook&quot;.
          </p>

          {/* Thông báo admin qua Zalo Cá Nhân */}
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5"
              checked={Boolean(cfg.zalo_personal_notify_enabled)}
              onChange={(e) => setField("zalo_personal_notify_enabled", e.target.checked)} />
            🔔 Gửi thông báo hệ thống qua Zalo Cá Nhân
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5"
              checked={Boolean(cfg.zalo_personal_newchat_alert_enabled ?? true)}
              onChange={(e) => setField("zalo_personal_newchat_alert_enabled", e.target.checked)} />
            🆕 Báo thread mới nhắn tới (đủ Thread ID + User ID người gửi + tài khoản nhận)
          </label>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" className="size-3.5"
              checked={Boolean(
                (config as any)?.account_log_notify_zalo_personal ??
                (config as any)?.account_log_notify_enabled ?? true
              )}
              onChange={(e) => setField("account_log_notify_zalo_personal", e.target.checked)} />
            📋 Gửi log tài khoản provider (ChatGPT free / Codex / Gemini / Flow…) qua Zalo Cá Nhân
          </label>
          <p className="text-[10px] text-muted-foreground -mt-1">
            Log đủ email + provider + bước khôi phục [T0]–[T3]. Cần bật 🔔 thông báo hệ
            thống + điền Thread ID admin ở trên thì log mới gửi qua kênh này.
          </p>
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">
              Thread ID admin theo từng tài khoản Zalo Cá Nhân
            </label>
            <p className="text-[10px] text-muted-foreground">
              Mỗi ownId (tài khoản đăng nhập QR) có Thread admin riêng. Báo chat mới / /id
              từ acc nào → gửi về admin của acc đó. Trống → dùng admin chung bên dưới.
            </p>
            {zalopAccounts.length === 0 ? (
              <p className="text-[10px] text-muted-foreground italic">
                Chưa thấy tài khoản đăng nhập — sang tab &quot;🔑 Tài khoản &amp; QR&quot; của kênh này đăng nhập QR, rồi tải lại Settings.
              </p>
            ) : (
              zalopAccounts.map((ownId) => {
                const map = ((config as any)?.zalo_personal_account_admins || {}) as Record<
                  string, { admin_thread?: string; admin_thread_type?: string; ha_fastpath?: boolean }
                >;
                const entry = map[ownId] || {};
                const patchAcc = (p: { admin_thread?: string; admin_thread_type?: string; ha_fastpath?: boolean }) => {
                  const next = { ...map, [ownId]: { ...entry, ...p } };
                  setField("zalo_personal_account_admins", next);
                };
                return (
                  <div key={ownId} className="rounded-md border border-border p-2 space-y-2">
                    <div className="text-[11px] font-mono text-foreground truncate" title={ownId}>
                      ownId: {ownId}
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="text-[10px] text-muted-foreground">Thread ID admin</label>
                        <Input
                          value={String(entry.admin_thread || "")}
                          onChange={(e) => patchAcc({ admin_thread: e.target.value })}
                          placeholder="Trống = admin chung"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] text-muted-foreground">Loại</label>
                        <select
                          className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                          value={String(entry.admin_thread_type || "0") === "1" ? "1" : "0"}
                          onChange={(e) => patchAcc({ admin_thread_type: e.target.value })}
                        >
                          <option value="0">Cá nhân</option>
                          <option value="1">Nhóm</option>
                        </select>
                      </div>
                    </div>
                    <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5"
                        checked={entry.ha_fastpath !== false}
                        onChange={(e) => patchAcc({ ha_fastpath: e.target.checked })} />
                      ⚡ Điều khiển nhà cục bộ (lệnh rõ ràng chạy ngay, không vòng qua provider)
                    </label>
                  </div>
                );
              })
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-muted-foreground">Thread ID admin chung (fallback)</label>
              <Input value={String(cfg.zalo_personal_admin_thread || "")}
                onChange={(e) => setField("zalo_personal_admin_thread", e.target.value)}
                placeholder="Dùng khi acc chưa có admin riêng" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Loại thread admin chung</label>
              <select className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                value={String(cfg.zalo_personal_admin_thread_type || "0")}
                onChange={(e) => setField("zalo_personal_admin_thread_type", e.target.value)}>
                <option value="0">Cá nhân</option>
                <option value="1">Nhóm</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">
              Gửi admin chung bằng tài khoản (ownId acc A sở hữu thread admin)
            </label>
            <select
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
              value={String((config as any)?.zalo_personal_admin_send_account || "")}
              onChange={(e) => setField("zalo_personal_admin_send_account", e.target.value)}
            >
              <option value="">— Acc mặc định / acc đầu —</option>
              {zalopAccounts.map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </div>
          <p className="text-[10px] text-muted-foreground">
            Admin riêng theo ownId → gửi bằng acc đó. Admin chung → gửi bằng acc chọn ở trên.
          </p>
          </div>
        )}

        {/* ── Zalo Cá Nhân — Tài khoản & QR / Webhook / Proxy / Danh bạ (từ trang /zalo cũ) ── */}
        {chTab === "zalop" && subTab === "zaccounts" && <ZaloPersonalPanel />}

        {/* ── Lọc chức năng theo thread — RIÊNG kênh đang chọn ── */}
        {subTab === "filter" && (
          <div className="space-y-3 mt-1">
          <p className="text-xs font-semibold">
            🎚️ Lọc chức năng theo thread — {chTab === "tg" ? "Telegram" : chTab === "zalo" ? "Zalo Bot" : "Zalo Cá Nhân"}
          </p>
          <p className="text-[10px] text-muted-foreground">
            Giới hạn chức năng AI cho từng khung chat, THEO TỪNG BOT — vì cùng 1 Chat
            ID nhưng ở bot khác nhau là khác nhau. Chọn bot rồi nhập Chat ID; chọn
            &quot;· mọi bot&quot; = áp cho mọi bot cùng nền tảng. Chat KHÔNG có trong
            danh sách = cho phép tất cả. Tích nhóm nào = chỉ cho phép nhóm đó; không
            tích nhóm nào = chặn hết chức năng (chỉ chat). Với NHÓM: thêm bộ lọc
            &quot;bắt buộc tag&quot; và tầng lọc theo User ID (mỗi user tick tập con
            quyền của nhóm) ngay dưới mỗi thread. Mỗi thread còn có 🔗 chuyển tiếp
            webhook (HA / n8n / URL bất kỳ): tích ở thread → mọi tin chuyển về URL của
            thread, từng user chỉ bật/tắt; không tích ở thread → từng user tự bật +
            cài URL riêng (mỗi người một webhook).
          </p>
          {filterRows.filter((r) => r.botKey === chTab || r.botKey.startsWith(`${chTab}:`)).map((row) => (
            <div key={row.id} className="rounded-md border border-border p-2 space-y-2">
              <div className="flex items-center gap-2">
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
                  onChange={(e) => setFilterField(row.id, { chatId: e.target.value })}
                  placeholder="Chat ID (vd: 123456789)"
                  className="flex-1"
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
                <Button type="button" variant="ghost" size="sm" onClick={() => removeFilterRow(row.id)}>
                  Xóa
                </Button>
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
                    <div className="flex items-center gap-2">
                      <Input
                        value={u.userId}
                        onChange={(e) => setUserField(row.id, u.id, { userId: e.target.value })}
                        placeholder="User ID (gõ /id trong nhóm để lấy)"
                        className="h-7 text-xs flex-1"
                      />
                      <Button type="button" variant="ghost" size="sm" className="h-6 text-[11px]"
                        onClick={() => removeUserRow(row.id, u.id)}>
                        Xóa
                      </Button>
                    </div>
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
                  </div>
                ))}
              </div>
              )}
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
