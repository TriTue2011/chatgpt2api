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

import { useState } from "react";
import { useSettingsStore } from "../store";

type ThanhVien = { kenh: string; chat: string; topic: string; user: string };
/** `tag_only` — xem `services/agent/chatlog.cai_dat`. Thiếu = false = ghi cả
 *  tin không tag, tức bản ghi cũ giữ nguyên hành vi. */
type CaiDat = { enabled?: boolean; retention_days?: number; tag_only?: boolean;
                groups?: string[] };

/** 21 nhóm chức năng — nhãn phải khớp «Lọc thread» (test_o_tich_du_moi_nhom). */
const NHOM_CHUC_NANG: [string, string][] = [
  ["homeassistant", "🏠 Nhà (HA)"], ["server", "🖥️ Server"], ["image", "🎨 Ảnh"],
  ["video", "🎬 Video"], ["music", "🎵 Nhạc"], ["web", "🌐 Web"], ["code", "💻 Code"],
  ["memory", "🧠 Ghi nhớ"], ["rag", "📚 RAG / tài liệu"], ["word", "📝 PDF → Word"],
  ["office", "📄 Tài liệu Office"], ["device", "🔌 Thiết bị"],
  ["summary", "🧾 Tổng hợp"], ["schedule", "⏰ Nhắc hẹn"], ["skills", "🧩 Skill"],
  ["wiki", "📖 Wiki"], ["contacts", "📒 Danh bạ"], ["kho_dam_may", "☁️ Kho đám mây"],
  ["tts_reply", "🔉 Trả lời giọng nói"], ["tts_speaker", "📢 Phát loa"],
  ["teacher", "📚 Giáo viên"], ["facebook", "📘 Đăng Facebook Page"],
];

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
  /** Khối «Tự thêm» — gấp sẵn, chỉ mở khi cần khai thread lạ. */
  const [moTuThem, setMoTuThem] = useState(false);
  const [tKenh, setTKenh] = useState("zalop");
  const [tChat, setTChat] = useState("");
  const [tTopic, setTTopic] = useState("");
  const [tUser, setTUser] = useState("");

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

  /** Nhóm hiện ra cho một khoá chatlog.
   *
   *  Thread ĐÃ có bên «Lọc thread» → chỉ các nhóm đã tick bên đó (không vượt
   *  quyền được, chỉ thu hẹp). Thread TỰ THÊM → đủ cả 21, vì nó không thừa
   *  hưởng quyền từ đâu cả. Đúng luật chủ máy chốt 07/08. */
  const nhomChoThread = (khoa: string): [string, string][] => {
    for (const [k, v] of Object.entries(tf)) {
      const tv = tachKhoa(k, false);
      if (tv && khoaChatlog(tv) === khoa && Array.isArray(v))
        return NHOM_CHUC_NANG.filter(([g]) => (v as string[]).includes(g));
    }
    for (const [k, v] of Object.entries(tuf)) {
      const tv = tachKhoa(k, true);
      if (tv && khoaChatlog(tv) === khoa && Array.isArray(v))
        return NHOM_CHUC_NANG.filter(([g]) => (v as string[]).includes(g));
    }
    return NHOM_CHUC_NANG;
  };

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
      {/* Hướng dẫn GẤP SẴN — mở suốt thì đẩy danh sách phạm vi xuống dưới màn
          hình. Câu quan trọng nhất («mặc định TẮT») vẫn thấy lúc gấp. */}
      <details className="text-[10px] text-muted-foreground leading-relaxed">
        <summary className="cursor-pointer select-none">
          <b>Mặc định TẮT</b> — bấm để xem ghi được ở đâu và kế thừa thế nào
        </summary>
        <div className="mt-1 space-y-1">
          <p>
            Bật ở đây để bot GHI LẠI mọi tin nó nghe được trong một phạm vi (để sau
            tóm tắt / tìm «việc nhắc tới tôi»). Bot vẫn chỉ <b>trả lời</b> khi được
            tag — ghi ≠ trả lời.
          </p>
          <p>
            Chỉ ghi được ở nơi bot NGHE được tin không-tag: <b>Zalo Cá Nhân</b>, và{" "}
            <b>Telegram</b> khi bot là admin (hoặc tắt privacy mode). Zalo Bot API chỉ
            nhận tin có tag nên nhật ký sẽ thưa.
          </p>
          <p>
            Đặt độc lập theo <b>kênh / nhóm / topic / người</b>, khoá hẹp đè khoá rộng
            (bật cả kênh nhưng tắt riêng một nhóm → nhóm đó không ghi).
          </p>
        </div>
      </details>

      <div className="flex items-center gap-2">
        <select
          className="h-8 flex-1 min-w-0 rounded border border-input bg-background px-2 text-[12px]"
          value=""
          onChange={(e) => { addEntry(e.target.value); e.target.value = ""; }}>
          <option value="">➕ Thêm phạm vi để bật/tắt nhật ký…</option>
          {opts.filter((o) => !settings[o.key])
            .map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
        <button type="button"
          className="h-8 shrink-0 rounded border border-input px-2 text-[11px]"
          onClick={() => setMoTuThem((v) => !v)}>
          {moTuThem ? "✕ Đóng" : "✏️ Tự thêm"}
        </button>
      </div>

      {/* TỰ THÊM — thread bot ĐANG Ở TRONG nhưng chưa khai ở «Lọc thread» kênh
          nào, nên không có trong danh sách trên. Bot vẫn im lặng ở đó (không
          khai «Lọc thread» = không trả lời), nhưng nhật ký thì ghi được: mã đặt
          khối ghi TRƯỚC cổng im lặng, cố ý.

          BẮT BUỘC chọn kênh: id thô không nói được nó thuộc kênh nào, mà khoá
          phạm vi luôn mở đầu bằng kênh — thiếu là bản ghi trỏ vào hư không và
          KHÔNG có lỗi nào báo ra. */}
      {moTuThem && (
        <div className="rounded-lg border border-dashed border-border p-2.5 space-y-2">
          <p className="text-[10px] text-muted-foreground">
            Thêm thread <b>chưa có</b> ở «Lọc thread» kênh nào. Bot vẫn không trả lời
            ở đó — chỉ ghi nhật ký. Cá nhân = chat 1-1 với bot; nhóm/topic thì{" "}
            <b>bot phải ở trong đó</b>.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select value={tKenh} onChange={(e) => setTKenh(e.target.value)}
              className="h-8 rounded border border-input bg-background px-2 text-[12px]">
              {Object.entries(NHAN_KENH).filter(([k]) => k !== "mail")
                .map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input value={tChat} onChange={(e) => setTChat(e.target.value.trim())}
              placeholder="Chat / Thread ID"
              className="h-8 w-[190px] rounded border border-input bg-background px-2 text-[12px]" />
            <input value={tTopic} onChange={(e) => setTTopic(e.target.value.trim())}
              placeholder="Topic (Telegram, bỏ trống nếu không)"
              className="h-8 w-[210px] rounded border border-input bg-background px-2 text-[12px]" />
            <input value={tUser} onChange={(e) => setTUser(e.target.value.trim())}
              placeholder="Người (bỏ trống = cả nhóm)"
              className="h-8 w-[170px] rounded border border-input bg-background px-2 text-[12px]" />
            <button type="button" disabled={!tChat}
              className="h-8 rounded border border-input px-3 text-[11px] disabled:opacity-40"
              onClick={() => {
                const goc = tTopic ? `${tChat}#${tTopic}` : tChat;
                addEntry(tUser ? `${tKenh}:${goc}:${tUser}` : `${tKenh}:${goc}`);
                setTChat(""); setTTopic(""); setTUser("");
              }}>
              ➕ Thêm
            </button>
          </div>
        </div>
      )}

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
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <span>Giữ lại</span>
                <input type="number" min={0} max={3650}
                  className="h-7 w-20 rounded border border-input bg-background px-2 text-[12px]"
                  value={days}
                  onChange={(e) => {
                    const n = parseInt(e.target.value, 10);
                    setEntry(key, { retention_days: Number.isFinite(n) ? Math.max(0, n) : 30 });
                  }} />
                <span>ngày {days === 0 ? "(0 = giữ tới khi đầy ~20.000 tin)" : ""}</span>
                {/* Ô này CHẠY NGƯỢC CHIỀU mọi ô khác trong tab: tick vào là
                    SIẾT LẠI. Mặc định bỏ tick = ghi cả hội thoại không tag, kể
                    cả khi «Lọc thread» đang bắt buộc tag — ghi ≠ trả lời. */}
                <label className="ml-auto flex items-center gap-1"
                  title="Bỏ tick = ghi cả tin không tag (mặc định). Tick = chỉ ghi tin có tag bot.">
                  <input type="checkbox" checked={st.tag_only === true}
                    onChange={(e) => setEntry(key, { tag_only: e.target.checked })} />
                  Chỉ ghi tin có <b>tag bot</b>
                </label>
              </div>

              {/* 21 ô chức năng — lọc phần bot LÀM GÌ (tra web, bật đèn, tạo
                  ảnh…). Khác ô «Tag bot» ở trên: cái đó lọc LỜI NGƯỜI NÓI.

                  KHÔNG khai `groups` = ghi hết, nên cấu hình đang chạy không
                  đổi hành vi. Bỏ tick một mục là bớt ghi mục đó.

                  Chỉ hiện các nhóm thread này ĐƯỢC PHÉP dùng bên «Lọc thread» —
                  bày ra nhóm nó không có quyền là bày lựa chọn tick xong chẳng
                  đổi gì. Thread tự thêm (không có bên «Lọc thread») thì hiện đủ
                  cả 21. */}
              <details className="text-[10px]">
                <summary className="cursor-pointer select-none text-muted-foreground">
                  Ghi hoạt động của bot:{" "}
                  <b>{st.groups ? `${st.groups.length}/${nhomChoThread(key).length} nhóm`
                                 : "tất cả"}</b> — bấm để chọn bớt
                </summary>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                  {nhomChoThread(key).map(([g, nhan]) => {
                    const dang = st.groups ? st.groups.includes(g) : true;
                    return (
                      <label key={g} className="flex items-center gap-1 cursor-pointer select-none">
                        <input type="checkbox" className="size-3" checked={dang}
                          onChange={() => {
                            const tatCa = nhomChoThread(key).map(([x]) => x);
                            const cu = st.groups ?? tatCa;
                            const moi = dang ? cu.filter((x) => x !== g) : [...cu, g];
                            setEntry(key, { groups: moi });
                          }} />
                        {nhan}
                      </label>
                    );
                  })}
                </div>
              </details>
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
