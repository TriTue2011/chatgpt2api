"use client";

/**
 * «Nhật ký nhóm» — bật/tắt việc GHI LẠI mọi tin nghe được, theo từng phạm vi.
 *
 * MẶC ĐỊNH TẮT: không phạm vi nào ghi cho tới khi chủ máy bật riêng ở đây. Lưu
 * lời người khác nên phải opt-in từng chỗ. Bật rồi thì bot ghi mọi tin nó NGHE
 * được (Zalo Cá Nhân; Telegram khi bot là admin / tắt privacy) — vẫn chỉ TRẢ
 * LỜI khi được tag, ghi ≠ trả lời.
 *
 * Đặt ĐỘC LẬP theo kênh / nhóm / topic / người, kế thừa HẸP thắng RỘNG:
 *   người → topic → nhóm → cả kênh. Bật cả kênh mà tắt riêng một nhóm thì nhóm
 *   đó không ghi (khoá hẹp đè khoá rộng) — y như «Lọc thread».
 *
 * Danh sách chọn lấy từ «Lọc thread» (nhóm/topic ở thread_filters, người ở
 * thread_user_filters) + ba mục «cả kênh». Ghi ra config `chatlog_settings`
 * (đọc bởi services/agent/chatlog.cai_dat).
 */

import { useSettingsStore } from "../store";

type ThanhVien = { kenh: string; chat: string; topic: string; user: string };
type CaiDat = { enabled?: boolean; retention_days?: number };

const NHAN_KENH: Record<string, string> = {
  tg: "Telegram", zalo: "Zalo Bot", zalop: "Zalo cá nhân", mail: "Email",
};

/** Khoá «Lọc thread» → thành viên có cấu trúc (bỏ bot/account — chatlog dùng
 *  khoá `kenh:chat[#topic][:user]`, không kèm bot). Giống memory-links. */
function tachKhoa(key: string, laNguoi: boolean): ThanhVien | null {
  const parts = String(key || "").split(":");
  if (parts.length < 2) return null;
  const kenh = parts[0];
  let user = "";
  let con = parts.slice(1);
  if (laNguoi) {
    user = con[con.length - 1] || "";
    con = con.slice(0, -1);
  }
  const chatPart = con.length >= 2 ? con.slice(1).join(":") : (con[0] || "");
  if (!chatPart) return null;
  const i = kenh === "tg" ? chatPart.indexOf("#") : -1;
  const chat = i >= 0 ? chatPart.slice(0, i) : chatPart;
  const topic = i >= 0 ? chatPart.slice(i + 1) : "";
  return { kenh, chat, topic, user };
}

/** Thành viên → khoá chatlog `kenh:chat[#topic][:user]` (chat rỗng = cả kênh).
 *  Phải khớp CHÍNH XÁC services/agent/chatlog._cac_khoa_cai_dat. */
function khoaChatlog(tv: ThanhVien): string {
  let k = tv.kenh;
  if (tv.chat) {
    k += `:${tv.chat}`;
    if (tv.topic) k += `#${tv.topic}`;
    if (tv.user) k += `:${tv.user}`;
  }
  return k;
}

function nhanChatlog(tv: ThanhVien, ten?: string): string {
  const kenh = NHAN_KENH[tv.kenh] || tv.kenh;
  if (!tv.chat) return `Cả kênh ${kenh}`;
  const dich = tv.chat + (tv.topic ? ` › topic ${tv.topic}` : "")
    + (tv.user ? ` › người ${tv.user}` : "");
  return ten ? `${ten} · ${kenh} ${dich}` : `${kenh} ${dich}`;
}

export function ChatlogSettingsCard() {
  const config = useSettingsStore((s) => s.config);
  const setField = useSettingsStore((s) => s.setField);

  const cfg = (config || {}) as Record<string, unknown>;
  const settings = (cfg.chatlog_settings || {}) as Record<string, CaiDat>;
  const tf = (cfg.thread_filters || {}) as Record<string, unknown>;
  const tuf = (cfg.thread_user_filters || {}) as Record<string, unknown>;
  const meta = (cfg.thread_filter_meta || {}) as Record<string, { name?: string }>;

  // ── Danh sách chọn: ba «cả kênh» + nhóm/topic/người từ «Lọc thread» ─────────
  const opts: { key: string; label: string }[] = [];
  const daCo = new Set<string>();
  for (const k of ["tg", "zalo", "zalop"]) {
    opts.push({ key: k, label: `Cả kênh ${NHAN_KENH[k]}` });
    daCo.add(k);
  }
  for (const [key, laNguoi] of [
    ...Object.keys(tf).map((k) => [k, false] as [string, boolean]),
    ...Object.keys(tuf).map((k) => [k, true] as [string, boolean]),
  ]) {
    const tv = tachKhoa(key, laNguoi);
    if (!tv) continue;
    const clKey = khoaChatlog(tv);
    if (daCo.has(clKey)) continue;
    daCo.add(clKey);
    opts.push({ key: clKey, label: nhanChatlog(tv, meta[key]?.name) });
  }
  const nhanMap = new Map(opts.map((o) => [o.key, o.label]));

  const entries = Object.entries(settings);

  const setEntry = (key: string, patch: CaiDat) =>
    setField("chatlog_settings", {
      ...settings,
      [key]: { enabled: true, retention_days: 30, ...settings[key], ...patch },
    });

  const delEntry = (key: string) => {
    const next = { ...settings };
    delete next[key];
    setField("chatlog_settings", next);
  };

  const addEntry = (key: string) => {
    if (!key || settings[key]) return;
    setField("chatlog_settings", {
      ...settings, [key]: { enabled: true, retention_days: 30 },
    });
  };

  return (
    <div className="space-y-3 mt-1">
      <p className="text-[10px] text-muted-foreground leading-relaxed">
        <b>Mặc định TẮT.</b> Bật ở đây để bot GHI LẠI mọi tin nó nghe được trong một
        phạm vi (để sau tóm tắt / tìm «việc nhắc tới tôi»). Bot vẫn chỉ <b>trả lời</b>{" "}
        khi được tag — ghi ≠ trả lời.<br />
        Chỉ ghi được ở nơi bot NGHE được tin không-tag: <b>Zalo Cá Nhân</b>, và{" "}
        <b>Telegram</b> khi bot là admin (hoặc tắt privacy mode). Zalo Bot API chỉ nhận
        tin có tag nên nhật ký sẽ thưa.<br />
        Đặt độc lập theo <b>kênh / nhóm / topic / người</b>, khoá hẹp đè khoá rộng
        (bật cả kênh nhưng tắt riêng một nhóm → nhóm đó không ghi).
      </p>

      <div className="flex items-center gap-2">
        <select
          className="h-8 flex-1 min-w-0 rounded border border-input bg-background px-2 text-[12px]"
          value=""
          onChange={(e) => { addEntry(e.target.value); e.target.value = ""; }}>
          <option value="">➕ Thêm phạm vi để bật/tắt nhật ký…</option>
          {opts.filter((o) => !settings[o.key])
            .map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
      </div>

      {entries.length === 0 && (
        <p className="text-[11px] text-muted-foreground">
          Chưa bật nhật ký ở đâu — không phạm vi nào đang được ghi lại.
        </p>
      )}

      <div className="space-y-2">
        {entries.map(([key, st]) => {
          const days = st.retention_days === undefined ? 30 : st.retention_days;
          return (
            <div key={key} className="rounded-lg border border-border p-2.5 space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[12px] font-medium truncate flex-1 min-w-[160px]">
                  {nhanMap.get(key) || key}
                </span>
                <label className="flex items-center gap-1 text-[11px]">
                  <input type="checkbox" checked={st.enabled !== false}
                    onChange={(e) => setEntry(key, { enabled: e.target.checked })} />
                  Ghi nhật ký
                </label>
                <button type="button" className="text-[11px] text-red-500"
                  onClick={() => delEntry(key)}>🗑 Bỏ</button>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span>Giữ lại</span>
                <input type="number" min={0} max={3650}
                  className="h-7 w-20 rounded border border-input bg-background px-2 text-[12px]"
                  value={days}
                  onChange={(e) => {
                    const n = parseInt(e.target.value, 10);
                    setEntry(key, { retention_days: Number.isFinite(n) ? Math.max(0, n) : 30 });
                  }} />
                <span>ngày {days === 0 ? "(0 = giữ tới khi đầy ~20.000 tin)" : ""}</span>
              </div>
            </div>
          );
        })}
      </div>

      {opts.length <= 3 && (
        <p className="text-[11px] text-amber-600">
          Chưa có nhóm/người nào trong «Lọc thread» — mới chỉ chọn được cấp «cả kênh».
          Vào tab <b>🎚️ Lọc thread</b> thêm nhóm/topic/người để bật nhật ký riêng cho từng chỗ.
        </p>
      )}
    </div>
  );
}
