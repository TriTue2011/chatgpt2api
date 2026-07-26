"use client";

/**
 * Panel Zalo Cá Nhân — chuyển từ trang /zalo về Settings → Kênh chat → tab
 * "Zalo Cá Nhân" → "🔑 Tài khoản & QR": đăng nhập QR, danh sách tài khoản,
 * webhook per-account, proxy, danh bạ & blacklist.
 *
 * Backend: /api/zalo-personal/* (api/zalo_personal.py) proxy tới bot server
 * zca-js. Auth do trang Settings guard sẵn — panel không tự guard.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "@/lib/request";
import { ChannelActivityPanel } from "@/components/channel-activity";
import { useSettingsStore } from "../store";
import {
  RefreshCw, QrCode, Webhook, Globe, Users, Send, Trash2,
  CheckCircle2, XCircle, Copy, MessageCircle, Home, Plus, Shield, ChevronRight, ChevronDown,
} from "lucide-react";

const INPUT =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]";
const BTN =
  "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition disabled:opacity-50";
const BTN_PRIMARY = `${BTN} bg-[var(--neon-cyan)]/15 text-[var(--neon-cyan)] hover:bg-[var(--neon-cyan)]/25 border border-[var(--neon-cyan)]/30`;
const BTN_GHOST = `${BTN} border border-[var(--border)] hover:bg-[var(--card)]`;
const BTN_DANGER = `${BTN} border border-red-400/30 text-red-400 hover:bg-red-400/10`;
const CARD = "rounded-xl border border-[var(--border)] bg-[var(--card)]/60 p-4";

type Toast = { msg: string; ok: boolean } | null;

type Account = { ownId: string; phoneNumber?: string; displayName?: string; isOnline?: boolean; proxy?: string };
type Status = {
  enabled: boolean; server_url: string; reachable: boolean; accounts: Account[];
  ai_enabled: boolean; ai_model: string; chat_ids: string[]; auto_webhook: boolean;
  webhook_receiver: string; ha_enabled: boolean; ha_url: string;
  notify_enabled: boolean; admin_thread: string; error?: string;
};

/** Nhãn acc = SĐT / tên (không hiện ownId). zca đôi khi gắn "(ownId)" vào displayName. */
function accountLabel(a?: Pick<Account, "displayName" | "phoneNumber"> | null, fallback = "Tài khoản Zalo") {
  if (!a) return fallback;
  let name = String(a.displayName || "").trim()
    .replace(/\s*\(\d{8,}\)\s*$/g, "")
    .trim();
  const phone = String(a.phoneNumber || "").trim();
  if (name && phone && name !== phone && !name.includes(phone)) {
    return `${name} · ${phone}`;
  }
  if (phone) return phone;
  if (name) return name;
  return fallback;
}

type TabId = "accounts" | "channel" | "admin" | "webhooks" | "proxies" | "contacts";

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "accounts", label: "Tài khoản & QR", icon: Users },
  { id: "channel", label: "Cài đặt kênh", icon: Home },
  { id: "admin", label: "Admin", icon: Shield },
  { id: "webhooks", label: "Webhook", icon: Webhook },
  { id: "proxies", label: "Proxy", icon: Globe },
  { id: "contacts", label: "Event & Blacklist", icon: MessageCircle },
];

export function ZaloPersonalPanel() {
  const [tab, setTab] = useState<TabId>("accounts");
  const [toast, setToast] = useState<Toast>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(false);

  const showToast = useCallback((msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const refreshStatus = useCallback(async () => {
    setLoading(true);
    try {
      const r = await request.get("/api/zalo-personal/status");
      setStatus(r.data as Status);
    } catch (e) {
      showToast(`Lỗi tải trạng thái: ${e instanceof Error ? e.message : e}`, false);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  // Nạp trạng thái 1 LẦN khi panel hiện ra.
  const loadedOnce = useRef(false);
  useEffect(() => {
    if (loadedOnce.current) return;
    loadedOnce.current = true;
    void refreshStatus();
  }, [refreshStatus]);

  return (
    <div className="space-y-4">
      {/* Header gọn — panel nằm trong tab kênh Zalo Cá Nhân */}
      <div className="flex flex-wrap items-center gap-3">
        <p className="flex-1 text-xs text-[var(--muted-foreground)]">
          Tài khoản Zalo cá nhân qua bot server zca-js — QR login, webhook, proxy, danh bạ.
        </p>
        <StatusBadge status={status} />
        <button onClick={() => void refreshStatus()} className={BTN_GHOST} disabled={loading}>
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Làm mới
        </button>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1.5 border-b border-[var(--border)] pb-2">
        {TABS.map(t => {
          const Icon = t.icon;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`${BTN} ${tab === t.id
                ? "bg-[var(--neon-cyan)]/15 text-[var(--neon-cyan)] border border-[var(--neon-cyan)]/30"
                : "text-[var(--muted-foreground)] hover:bg-[var(--card)]"}`}>
              <Icon className="size-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "accounts" && <AccountsTab status={status} refresh={refreshStatus} showToast={showToast} />}
      {tab === "channel" && <ChannelTab status={status} showToast={showToast} />}
      {tab === "admin" && <AdminTab status={status} showToast={showToast} />}
      {tab === "webhooks" && <WebhooksTab status={status} showToast={showToast} />}
      {tab === "proxies" && <ProxiesTab showToast={showToast} />}
      {tab === "contacts" && <ContactsTab status={status} showToast={showToast} refresh={refreshStatus} />}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-5 right-5 z-50 flex items-center gap-2 rounded-xl border px-4 py-3 text-sm shadow-lg backdrop-blur
          ${toast.ok ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300" : "border-red-400/30 bg-red-400/10 text-red-300"}`}>
          {toast.ok ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}
          <span className="max-w-md">{toast.msg}</span>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: Status | null }) {
  if (!status) return null;
  if (!status.enabled)
    return <span className="rounded-full border border-[var(--border)] px-3 py-1 text-xs text-[var(--muted-foreground)]">Đang tắt</span>;
  return status.reachable
    ? <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs text-emerald-300">● Kết nối bot server OK</span>
    : <span className="rounded-full border border-red-400/30 bg-red-400/10 px-3 py-1 text-xs text-red-300">● Không kết nối được bot server</span>;
}

// ── Tab: Tài khoản & QR ───────────────────────────────────────────────────────

function AccountsTab({ status, refresh, showToast }:
  { status: Status | null; refresh: () => Promise<void>; showToast: (m: string, ok?: boolean) => void }) {
  const [qr, setQr] = useState("");
  const [qrLoading, setQrLoading] = useState(false);
  const [testThread, setTestThread] = useState("");
  const [testType, setTestType] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const getQr = async () => {
    setQrLoading(true);
    setQr("");
    try {
      const r = await request.post("/api/zalo-personal/login-qr", {}, { timeout: 80000 });
      if (r.data?.ok && r.data?.qr) {
        setQr(r.data.qr);
        showToast("Quét mã QR bằng app Zalo trên điện thoại (biểu tượng QR)");
        // Poll tài khoản 5s/lần trong 2 phút — đăng nhập xong tự làm mới danh sách
        let n = 0;
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = setInterval(() => {
          n += 1;
          void refresh();
          if (n > 24 && pollRef.current) clearInterval(pollRef.current);
        }, 5000);
      } else {
        showToast(r.data?.error || "Không lấy được mã QR", false);
      }
    } catch (e) {
      showToast(`Lỗi lấy QR: ${e instanceof Error ? e.message : e}`, false);
    } finally {
      setQrLoading(false);
    }
  };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const testSend = async () => {
    if (!testThread.trim()) { showToast("Nhập Thread ID trước", false); return; }
    try {
      const r = await request.post("/api/zalo-personal/test-send",
        { thread_id: testThread.trim(), type: testType });
      showToast(r.data?.ok ? "Đã gửi tin test ✓" : (r.data?.error || "Gửi thất bại"), !!r.data?.ok);
    } catch (e) {
      showToast(`Lỗi gửi: ${e instanceof Error ? e.message : e}`, false);
    }
  };

  const accounts = status?.accounts || [];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className={CARD}>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-bold"><Users className="size-4" /> Tài khoản đã đăng nhập ({accounts.length})</h2>
        {accounts.length === 0 && (
          <p className="text-xs text-[var(--muted-foreground)]">Chưa có tài khoản nào — tạo mã QR bên cạnh rồi quét bằng app Zalo.</p>
        )}
        <div className="space-y-2">
          {accounts.map(a => (
            <div key={a.ownId} className="flex items-center gap-3 rounded-lg border border-[var(--border)] px-3 py-2">
              <span className={`size-2 rounded-full ${a.isOnline ? "bg-emerald-400" : "bg-red-400"}`} />
              <div className="flex-1 text-xs">
                <div className="font-semibold">{accountLabel(a)}</div>
                <div className="text-[var(--muted-foreground)]">Proxy: {a.proxy || "không"}</div>
              </div>
            </div>
          ))}
        </div>
        {/* Test gửi tin */}
        <div className="mt-4 border-t border-[var(--border)] pt-3">
          <div className="mb-2 text-xs font-semibold">Gửi tin test</div>
          <div className="flex flex-wrap gap-2">
            <input className={`${INPUT} !w-56`} placeholder="Thread ID (user/nhóm)"
              value={testThread} onChange={e => setTestThread(e.target.value)} />
            <select className={`${INPUT} !w-28`} value={testType} onChange={e => setTestType(Number(e.target.value))}>
              <option value={0}>Cá nhân</option>
              <option value={1}>Nhóm</option>
            </select>
            <button onClick={() => void testSend()} className={BTN_PRIMARY}><Send className="size-3.5" /> Gửi test</button>
          </div>
        </div>
      </div>

      <div className={CARD}>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-bold"><QrCode className="size-4" /> Đăng nhập Zalo bằng QR</h2>
        <p className="mb-3 text-xs text-[var(--muted-foreground)]">
          Bấm tạo mã, mở Zalo trên điện thoại → biểu tượng QR → quét. Mã hết hạn sau ~60 giây.
          Cookie được bot server lưu lại, tự đăng nhập lại khi khởi động.
        </p>
        <button onClick={() => void getQr()} className={BTN_PRIMARY} disabled={qrLoading}>
          <QrCode className="size-3.5" /> {qrLoading ? "Đang tạo mã QR..." : "Tạo mã QR đăng nhập"}
        </button>
        {qr && (
          <div className="mt-4 flex justify-center rounded-xl border border-[var(--border)] bg-white p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={qr} alt="QR đăng nhập Zalo" className="max-h-72 w-auto" />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Tab: Cài đặt kênh (chuyển từ Settings → Kênh chat → Zalo Cá Nhân) ────────
// KHÔNG lặp lại thứ đã có ở «Lọc thread»: model AI và đường tắt HA cài theo
// TỪNG THREAD ở đó, nên ở đây chỉ còn cái thuộc về KÊNH / TÀI KHOẢN.

type ZpAccCfg = {
  enabled?: boolean; fallback_enabled?: boolean;
  fallback_channel?: string; fallback_bot_name?: string; fallback_thread?: string;
};

function ChannelTab({ status, showToast }:
  { status: Status | null; showToast: (m: string, ok?: boolean) => void }) {
  const config = useSettingsStore(s => s.config);
  const setField = useSettingsStore(s => s.setField);
  const saveConfig = useSettingsStore(s => s.saveConfig);
  const isSaving = useSettingsStore(s => s.isSavingConfig);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const cfg = (config || {}) as Record<string, unknown>;
  const map = (cfg.zalo_personal_account_admins || {}) as Record<string, ZpAccCfg>;
  const accounts = status?.accounts || [];

  // Danh sách bot/tài khoản ĐANG CÓ để chọn fallback (không bắt gõ tay).
  // value = "<channel>::<tên bot>" — khớp cách lưu fallback_channel +
  // fallback_bot_name; Zalo CN dùng ownId làm tên.
  const fallbackOptions: { value: string; label: string }[] = [];
  for (const b of ((cfg.telegram_bots as Record<string, unknown>[]) || [])) {
    const tok = String(b?.token || "");
    const name = String(b?.label || tok.split(":")[0] || "").trim();
    if (name) fallbackOptions.push({ value: `telegram::${name}`, label: `Telegram · ${name}` });
  }
  for (const b of ((cfg.zalo_bots as Record<string, unknown>[]) || [])) {
    const tok = String(b?.token || "");
    const name = String(b?.label || tok.split(":")[0] || "").trim();
    if (name) fallbackOptions.push({ value: `zalo::${name}`, label: `Zalo Bot · ${name}` });
  }
  for (const a of accounts) {
    fallbackOptions.push({ value: `zalo_personal::${a.ownId}`, label: `Zalo CN · ${accountLabel(a)}` });
  }

  const patchAcc = (ownId: string, p: ZpAccCfg) => {
    const entry = map[ownId] || {};
    setField("zalo_personal_account_admins", { ...map, [ownId]: { ...entry, ...p } });
  };

  const save = async () => {
    try { await saveConfig(); showToast("Đã lưu cài đặt kênh ✓"); }
    catch (e) { showToast(`Lỗi lưu: ${e instanceof Error ? e.message : e}`, false); }
  };

  return (
    <div className="space-y-4">
      <div className={CARD}>
        <h2 className="mb-3 text-sm font-bold">Bật/tắt kênh</h2>
        <label className="mb-2 flex cursor-pointer select-none items-center gap-2 text-xs">
          <input type="checkbox" checked={Boolean(cfg.zalo_personal_enabled)}
            onChange={e => setField("zalo_personal_enabled", e.target.checked)} />
          Bật kênh Zalo Cá Nhân
        </label>
        <Field label="Tài khoản gửi mặc định (trống = tài khoản đầu danh sách)">
          <select className={INPUT} value={String(cfg.zalo_personal_account_id || "")}
            onChange={e => setField("zalo_personal_account_id", e.target.value)}>
            <option value="">-- Tài khoản đầu trong danh sách --</option>
            {accounts.map(a => (
              <option key={a.ownId} value={a.ownId}>{accountLabel(a)}</option>
            ))}
          </select>
        </Field>
        <p className="mt-2 text-[11px] text-[var(--muted-foreground)]">
          🤖 Model AI, ⚡ đường tắt điều khiển nhà và bật/tắt AI theo thread cài ở tab
          «Lọc thread». Hoạt động &amp; blacklist xem ở tab «Event &amp; Blacklist».
        </p>
      </div>

      <div className={CARD}>
        <h2 className="mb-2 text-sm font-bold">Từng tài khoản</h2>
        {accounts.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)]">
            Chưa có tài khoản — đăng nhập QR ở tab &quot;Tài khoản &amp; QR&quot; trước.
          </p>
        ) : (
          <div className="space-y-2">
            {accounts.map(a => {
              const e = map[a.ownId] || {};
              const isOpen = open[a.ownId] ?? false;
              return (
                <div key={a.ownId} className="rounded-lg border border-[var(--border)] p-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="flex shrink-0 cursor-pointer select-none items-center gap-1 text-xs"
                      onClick={ev => ev.stopPropagation()}>
                      <input type="checkbox" checked={e.enabled !== false}
                        onChange={ev => patchAcc(a.ownId, { enabled: ev.target.checked })} />
                      Bật
                    </label>
                    <div className="flex min-w-0 flex-1 cursor-pointer select-none items-center gap-2"
                      onClick={() => setOpen(s => ({ ...s, [a.ownId]: !isOpen }))}
                      title={isOpen ? "Thu gọn" : "Mở xem thêm cài đặt"}>
                      {isOpen ? <ChevronDown className="size-4 shrink-0" /> : <ChevronRight className="size-4 shrink-0" />}
                      <span className="flex-1 truncate text-xs font-medium">{accountLabel(a)}</span>
                    </div>
                  </div>
                  {isOpen && (
                    <div className="mt-2 space-y-2 border-t border-[var(--border)] pt-2">
                      <label className="flex cursor-pointer select-none items-center gap-2 text-xs">
                        <input type="checkbox" checked={Boolean(e.fallback_enabled)}
                          onChange={ev => patchAcc(a.ownId, { fallback_enabled: ev.target.checked })} />
                        Fallback khi tài khoản này gửi không được (dùng bot khác)
                      </label>
                      {e.fallback_enabled && (
                        <div className="grid gap-2 md:grid-cols-2">
                          <Field label="Gửi qua bot nào (chọn từ bot đang có)">
                            <select className={INPUT}
                              value={e.fallback_channel && e.fallback_bot_name
                                ? `${e.fallback_channel}::${e.fallback_bot_name}` : ""}
                              onChange={ev => {
                                const v = ev.target.value;
                                if (!v) { patchAcc(a.ownId, { fallback_channel: "", fallback_bot_name: "" }); return; }
                                const [ch, ...rest] = v.split("::");
                                patchAcc(a.ownId, { fallback_channel: ch, fallback_bot_name: rest.join("::") });
                              }}>
                              <option value="">— Chọn bot —</option>
                              {fallbackOptions.map(o => (
                                <option key={o.value} value={o.value}>{o.label}</option>
                              ))}
                            </select>
                          </Field>
                          <Field label="Thread nhận fallback (chat ID nơi gửi tới)">
                            <input className={INPUT} value={String(e.fallback_thread || "")}
                              onChange={ev => patchAcc(a.ownId, { fallback_thread: ev.target.value })}
                              placeholder="-100… / user id" />
                          </Field>
                        </div>
                      )}
                      {e.fallback_enabled && fallbackOptions.length === 0 && (
                        <p className="text-[10px] text-[var(--muted-foreground)]">
                          Chưa có bot nào để chọn — thêm bot Telegram/Zalo ở kênh tương ứng trước.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        <button onClick={() => void save()} className={`${BTN_PRIMARY} mt-3`} disabled={isSaving}>
          {isSaving ? "Đang lưu…" : "Lưu cài đặt kênh"}
        </button>
      </div>

    </div>
  );
}

// ── Tab: Webhook ─────────────────────────────────────────────────────────────

type HookRow = { ownId: string; messageWebhookUrl?: string; groupEventWebhookUrl?: string; reactionWebhookUrl?: string };

type HookUrls = {
  auto?: boolean; internal_base?: string; secret?: string; events?: string[];
  internal?: Record<string, string>;
  public_base?: string; public?: Record<string, string>;
};

/** Hạ tầng zca-js + webhook tự động (chuyển từ tab "Cài đặt kênh" sang đây).
 *  Tick tự đăng ký → URL do hệ thống sinh, CHỈ ĐỌC (có nút copy).
 *  Bỏ tick  → tự nhập URL từng tài khoản bên dưới (server khác / định dạng khác). */
function WebhookInfraBlock({ showToast }: { showToast: (m: string, ok?: boolean) => void }) {
  const config = useSettingsStore(s => s.config);
  const setField = useSettingsStore(s => s.setField);
  const saveConfig = useSettingsStore(s => s.saveConfig);
  const isSaving = useSettingsStore(s => s.isSavingConfig);
  const [urls, setUrls] = useState<HookUrls | null>(null);

  const loadUrls = useCallback(() => {
    request.get("/api/zalo-personal/webhook-urls")
      .then(r => setUrls((r.data || {}) as HookUrls))
      .catch(() => setUrls(null));
  }, []);
  useEffect(() => { loadUrls(); }, [loadUrls]);

  const cfg = (config || {}) as Record<string, unknown>;
  const auto = Boolean(cfg.zalo_personal_auto_webhook ?? true);
  const evLabel: Record<string, string> = {
    message: "💬 message", group_event: "👥 group_event", reaction: "❤️ reaction",
  };

  const urlRow = (label: string, u: string) => (
    <div key={label} className="flex items-center gap-1.5">
      <span className="w-28 shrink-0 text-[10px] text-[var(--muted-foreground)]">{label}</span>
      <code className="flex-1 break-all rounded bg-[var(--background)] px-1.5 py-0.5 text-[11px]">{u}</code>
      <CopyBtn text={u} showToast={showToast} title="Copy URL webhook" />
    </div>
  );

  return (
    <div className={CARD}>
      <h2 className="mb-2 text-sm font-bold">Hạ tầng zca-js &amp; webhook</h2>
      <label className="mb-2 flex cursor-pointer select-none items-center gap-2 text-xs">
        <input type="checkbox" checked={auto}
          onChange={e => setField("zalo_personal_auto_webhook", e.target.checked)} />
        Tự đăng ký webhook mọi tài khoản về gateway
      </label>
      {auto ? (
        <div className="space-y-2">
          <p className="text-[11px] text-[var(--muted-foreground)]">
            URL do hệ thống <b>tự sinh</b> (chỉ đọc) — bấm biểu tượng để copy. zca-js nhúng
            cùng container nên dùng URL <b>nội bộ</b> là nhanh nhất.
          </p>
          {urls?.internal ? (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold text-[var(--muted-foreground)]">
                Nội bộ (LAN / trong container) — {urls.internal_base}
              </p>
              {Object.entries(urls.internal).map(([ev, u]) => urlRow(evLabel[ev] || ev, u))}
            </div>
          ) : (
            <p className="text-[11px] text-[var(--muted-foreground)]">Chưa lấy được URL — bấm Tải lại URL.</p>
          )}
          {urls?.public ? (
            <div className="space-y-1 border-t border-[var(--border)] pt-2">
              <p className="text-[10px] font-semibold text-[var(--muted-foreground)]">
                Qua domain (từ ngoài) — {urls.public_base}
              </p>
              {Object.entries(urls.public).map(([ev, u]) => urlRow(evLabel[ev] || ev, u))}
              <p className="text-[10px] text-[var(--muted-foreground)]">
                Gateway nhận webhook ở cùng một endpoint nên gọi bằng IP nội bộ hay domain
                đều vào chung một chỗ — <b>dùng song song được</b>. Nhưng zca-js chỉ gọi
                <b> một URL đã đăng ký</b> cho mỗi loại sự kiện.
              </p>
            </div>
          ) : (
            <p className="text-[10px] text-[var(--muted-foreground)]">
              Chưa cấu hình domain → chỉ có webhook nội bộ. Đặt domain ở mục
              <b> Cloudflare (hạ tầng chung)</b> thì URL domain sẽ hiện ở đây.
            </p>
          )}
        </div>
      ) : (
        <p className="text-[11px] text-[var(--muted-foreground)]">
          Đã tắt tự đăng ký — bạn <b>tự nhập</b> URL cho từng tài khoản ở danh sách bên dưới
          (bấm <b>Sửa</b>). Có thể trỏ sang IP máy chủ khác hoặc dùng định dạng webhook riêng.
        </p>
      )}

      <div className="mt-3 space-y-2 border-t border-[var(--border)] pt-3">
        <Field label="Webhook base nội bộ (trống = trong container, http://127.0.0.1:80)">
          <input className={INPUT} value={String(cfg.zalo_personal_webhook_base || "")}
            onChange={e => setField("zalo_personal_webhook_base", e.target.value)}
            placeholder="Trống = 127.0.0.1:80" />
        </Field>
        <div className="grid gap-2 md:grid-cols-2">
          <Field label="User bot server">
            <input className={INPUT} value={String(cfg.zalo_personal_username || "")}
              onChange={e => setField("zalo_personal_username", e.target.value)} placeholder="admin" />
          </Field>
          <Field label="Mật khẩu bot server">
            <input className={INPUT} type="password" value={String(cfg.zalo_personal_password || "")}
              onChange={e => setField("zalo_personal_password", e.target.value)} placeholder="admin" />
          </Field>
        </div>
        <div className="flex gap-2 pt-1">
          <button className={BTN_PRIMARY} disabled={isSaving}
            onClick={async () => {
              try {
                await saveConfig();
                showToast("Đã lưu hạ tầng webhook ✓");
                loadUrls();
              } catch (e) { showToast(`Lỗi lưu: ${e instanceof Error ? e.message : e}`, false); }
            }}>
            {isSaving ? "Đang lưu…" : "Lưu"}
          </button>
          <button className={BTN_GHOST} onClick={() => loadUrls()}>Tải lại URL</button>
        </div>
      </div>
    </div>
  );
}

function WebhooksTab({ status, showToast }:
  { status: Status | null; showToast: (m: string, ok?: boolean) => void }) {
  const [rows, setRows] = useState<HookRow[]>([]);
  const [edit, setEdit] = useState<HookRow | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await request.get("/api/zalo-personal/webhooks");
      // Bot server trả {success, data:{default, accounts:{ownId:{...}}}} → phải bóc
      // lớp `data` rồi mới tới `accounts`, kẻo lặp key "success"/"data" thành hàng lạ.
      let d = (r.data?.data ?? {}) as Record<string, unknown>;
      if (d && typeof d === "object" && d.data && typeof d.data === "object") {
        d = d.data as Record<string, unknown>;
      }
      const map = (d.accounts && typeof d.accounts === "object")
        ? (d.accounts as Record<string, unknown>) : d;
      const list: HookRow[] = [];
      for (const [ownId, v] of Object.entries(map)) {
        if (ownId === "default" || ownId === "success" || typeof v !== "object" || v === null) continue;
        list.push({ ownId, ...(v as Omit<HookRow, "ownId">) });
      }
      // Thêm tài khoản đã login nhưng chưa có webhook
      for (const a of status?.accounts || []) {
        if (!list.some(x => x.ownId === a.ownId)) list.push({ ownId: a.ownId });
      }
      setRows(list);
    } catch (e) {
      showToast(`Lỗi tải webhook: ${e instanceof Error ? e.message : e}`, false);
    } finally {
      setLoading(false);
    }
  }, [showToast, status]);

  useEffect(() => { void load(); }, [load]);

  const applyAuto = async () => {
    try {
      const r = await request.post("/api/zalo-personal/webhook-config/auto");
      if (r.data?.ok) {
        showToast(`Đã trỏ webhook về chatgpt2api (${(r.data.updated || []).length || "không cần"} thay đổi)`);
        void load();
      } else showToast(r.data?.error || "Thất bại", false);
    } catch (e) { showToast(`Lỗi: ${e instanceof Error ? e.message : e}`, false); }
  };

  const save = async () => {
    if (!edit) return;
    try {
      const r = await request.post("/api/zalo-personal/webhook-config", edit);
      showToast(r.data?.ok ? "Đã lưu webhook ✓" : (r.data?.error || "Lưu thất bại"), !!r.data?.ok);
      setEdit(null);
      void load();
    } catch (e) { showToast(`Lỗi: ${e instanceof Error ? e.message : e}`, false); }
  };

  const del = async (ownId: string) => {
    try {
      const r = await request.delete(`/api/zalo-personal/webhook-config/${ownId}`);
      showToast(r.data?.ok ? "Đã xóa cấu hình webhook" : (r.data?.error || "Xóa thất bại"), !!r.data?.ok);
      void load();
    } catch (e) { showToast(`Lỗi: ${e instanceof Error ? e.message : e}`, false); }
  };

  return (
    <div className="space-y-4">
      <WebhookInfraBlock showToast={showToast} />
      <div className={CARD}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="flex-1 text-sm font-bold">Webhook theo tài khoản</h2>
          <button onClick={() => void load()} className={BTN_GHOST} disabled={loading}>
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Tải lại
          </button>
          <button onClick={() => void applyAuto()} className={BTN_PRIMARY}>
            <Webhook className="size-3.5" /> Trỏ tất cả về chatgpt2api
          </button>
        </div>
        <p className="mb-3 text-xs text-[var(--muted-foreground)]">
          Receiver của gateway: <code className="rounded bg-[var(--background)] px-1.5 py-0.5">{status?.webhook_receiver || "(chưa cấu hình webhook base)"}</code>
          {" "}— tin nhắn đến sẽ vào AI + chuyển tiếp Home Assistant theo cài đặt.
        </p>
        <div className="space-y-2">
          {rows.map(row => {
            const acc = (status?.accounts || []).find(a => a.ownId === row.ownId);
            return (
            <div key={row.ownId} className="rounded-lg border border-[var(--border)] p-3 text-xs">
              <div className="mb-1 flex items-center gap-2">
                <span className="font-semibold">{accountLabel(acc)}</span>
                <span className="flex-1" />
                <button onClick={() => setEdit({ ...row })} className={BTN_GHOST}>Sửa</button>
                <button onClick={() => void del(row.ownId)} className={BTN_DANGER}><Trash2 className="size-3" /></button>
              </div>
              {(() => {
                const eff = row.messageWebhookUrl || status?.webhook_receiver || "";
                return eff ? (
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <span className="shrink-0 rounded bg-[var(--background)] px-1.5 py-0.5 text-[10px]">
                      {row.messageWebhookUrl ? "✓ đã đăng ký" : "tự sinh — bấm 'Trỏ tất cả về chatgpt2api'"}
                    </span>
                    <code className="flex-1 break-all text-[11px]">{eff}</code>
                    <CopyBtn text={eff} showToast={showToast} title="Copy link webhook" />
                  </div>
                ) : null;
              })()}
              <div className="grid gap-1 text-[var(--muted-foreground)] md:grid-cols-3">
                <div>💬 message: <span className="break-all">{row.messageWebhookUrl || "—"}</span></div>
                <div>👥 group: <span className="break-all">{row.groupEventWebhookUrl || "—"}</span></div>
                <div>❤️ reaction: <span className="break-all">{row.reactionWebhookUrl || "—"}</span></div>
              </div>
            </div>
            );
          })}
          {rows.length === 0 && <p className="text-xs text-[var(--muted-foreground)]">Chưa có tài khoản/webhook nào.</p>}
        </div>
      </div>

      {edit && (
        <div className={CARD}>
          <h3 className="mb-3 text-sm font-bold">
            Sửa webhook — {accountLabel((status?.accounts || []).find(a => a.ownId === edit.ownId))}
          </h3>
          <div className="space-y-2">
            <Field label="Message webhook URL">
              <input className={INPUT} value={edit.messageWebhookUrl || ""}
                onChange={e => setEdit({ ...edit, messageWebhookUrl: e.target.value })} />
            </Field>
            <Field label="Group event webhook URL">
              <input className={INPUT} value={edit.groupEventWebhookUrl || ""}
                onChange={e => setEdit({ ...edit, groupEventWebhookUrl: e.target.value })} />
            </Field>
            <Field label="Reaction webhook URL">
              <input className={INPUT} value={edit.reactionWebhookUrl || ""}
                onChange={e => setEdit({ ...edit, reactionWebhookUrl: e.target.value })} />
            </Field>
            <div className="flex gap-2 pt-1">
              <button onClick={() => void save()} className={BTN_PRIMARY}>Lưu</button>
              <button onClick={() => setEdit(null)} className={BTN_GHOST}>Hủy</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tab: Proxy ───────────────────────────────────────────────────────────────

function ProxiesTab({ showToast }: { showToast: (m: string, ok?: boolean) => void }) {
  const [proxies, setProxies] = useState<string[]>([]);
  const [newProxy, setNewProxy] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await request.get("/api/zalo-personal/proxies");
      const d = r.data?.data;
      const list = Array.isArray(d) ? d : (d?.data || d?.proxies || []);
      setProxies((list as unknown[]).map(p => typeof p === "string" ? p : (p as { url?: string; proxyUrl?: string }).url || (p as { proxyUrl?: string }).proxyUrl || JSON.stringify(p)));
    } catch (e) { showToast(`Lỗi tải proxy: ${e instanceof Error ? e.message : e}`, false); }
  }, [showToast]);

  useEffect(() => { void load(); }, [load]);

  const add = async () => {
    if (!newProxy.trim()) return;
    const r = await request.post("/api/zalo-personal/proxies", { proxyUrl: newProxy.trim() });
    showToast(r.data?.ok ? "Đã thêm proxy" : (r.data?.error || "Thêm thất bại"), !!r.data?.ok);
    setNewProxy("");
    void load();
  };

  const remove = async (p: string) => {
    const r = await request.delete("/api/zalo-personal/proxies", { data: { proxyUrl: p } });
    showToast(r.data?.ok ? "Đã xóa proxy" : (r.data?.error || "Xóa thất bại"), !!r.data?.ok);
    void load();
  };

  return (
    <div className={CARD}>
      <h2 className="mb-3 text-sm font-bold">Proxy cho đăng nhập Zalo (tùy chọn)</h2>
      <div className="mb-3 flex gap-2">
        <input className={INPUT} placeholder="http://user:pass@host:port"
          value={newProxy} onChange={e => setNewProxy(e.target.value)} />
        <button onClick={() => void add()} className={BTN_PRIMARY}><Plus className="size-3.5" /> Thêm</button>
      </div>
      <div className="space-y-2">
        {proxies.map(p => (
          <div key={p} className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-xs">
            <span className="flex-1 break-all">{p}</span>
            <button onClick={() => void remove(p)} className={BTN_DANGER}><Trash2 className="size-3" /></button>
          </div>
        ))}
        {proxies.length === 0 && <p className="text-xs text-[var(--muted-foreground)]">Chưa có proxy nào — đăng nhập trực tiếp.</p>}
      </div>
    </div>
  );
}

// ── Tab: Danh bạ (bạn bè + nhóm → lấy thread ID) ─────────────────────────────

type Contact = { id: string; name: string; kind: "user" | "group" };

function ContactsTab({ status, showToast, refresh }:
  { status: Status | null; showToast: (m: string, ok?: boolean) => void; refresh: () => Promise<void> }) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");

  const load = async (kind: "user" | "group") => {
    setLoading(true);
    try {
      const path = kind === "user" ? "/api/zalo-personal/friends" : "/api/zalo-personal/groups";
      const r = await request.post(path, {});
      const d = r.data?.data;
      const raw = Array.isArray(d) ? d : (d?.data || d?.friends || d?.groups || d?.gridInfoMap || []);
      const list: Contact[] = [];
      if (Array.isArray(raw)) {
        for (const f of raw as Record<string, unknown>[]) {
          const id = String(f.userId || f.uid || f.id || f.groupId || "");
          const name = String(f.displayName || f.zaloName || f.name || f.username || id);
          if (id) list.push({ id, name, kind });
        }
      } else if (raw && typeof raw === "object") {
        for (const [id, v] of Object.entries(raw as Record<string, { name?: string }>)) {
          list.push({ id, name: v?.name || id, kind });
        }
      }
      setContacts(list);
      if (!list.length) showToast(r.data?.error || "Danh sách trống", !r.data?.error);
    } catch (e) {
      showToast(`Lỗi tải danh bạ: ${e instanceof Error ? e.message : e}`, false);
    } finally { setLoading(false); }
  };

  const addTo = async (key: "zalo_personal_chat_ids" | "zalo_personal_forward", id: string, kind: "group" | "user" = "group") => {
    try {
      if (key === "zalo_personal_chat_ids") {
        const list: string[] = status?.chat_ids || [];
        if (list.includes(id)) { showToast("Đã có trong danh sách"); return; }
        await request.post("/api/settings", { zalo_personal_chat_ids: [...list, id] });
        showToast("Đã cho phép AI trả lời thread này ✓");
        void refresh();
        return;
      }
      // Thêm thread vào webhook chuyển tiếp đầu tiên (tạo mới nếu chưa có)
      const s = await request.get("/api/settings");
      const cfg = (s.data?.config || {}) as any;
      let webhooks: any[] = Array.isArray(cfg.zalo_personal_forward_webhooks)
        ? cfg.zalo_personal_forward_webhooks.map((w: any) => ({ ...w }))
        : [];
      if (!webhooks.length) {
        const haUrl = String(cfg.zalo_personal_ha_url || "").trim();
        webhooks = [{
          id: "legacy-ha",
          enabled: Boolean(cfg.zalo_personal_ha_enabled ?? true),
          url: haUrl,
          label: haUrl ? "Home Assistant" : "Webhook",
          filters: Array.isArray(cfg.zalo_personal_ha_filters) ? cfg.zalo_personal_ha_filters : [],
        }];
      }
      const dest = webhooks[0];
      const filters: any[] = Array.isArray(dest.filters) ? [...dest.filters] : [];
      if (filters.some((f) => String(f?.thread_id || "") === id)) {
        showToast("Đã có trong bộ lọc webhook đầu tiên");
        return;
      }
      filters.push({ thread_id: id, kind, user_ids: [] });
      dest.filters = filters;
      webhooks[0] = dest;
      await request.post("/api/settings", {
        zalo_personal_forward_webhooks: webhooks,
        zalo_personal_ha_filters: filters,
        zalo_personal_ha_enabled: dest.enabled !== false,
        zalo_personal_ha_url: String(dest.url || cfg.zalo_personal_ha_url || ""),
      });
      showToast("Đã thêm thread vào webhook chuyển tiếp đầu tiên ✓");
      void refresh();
    } catch (e) { showToast(`Lỗi: ${e instanceof Error ? e.message : e}`, false); }
  };

  const shown = contacts.filter(c => !filter || c.name.toLowerCase().includes(filter.toLowerCase()) || c.id.includes(filter));

  return (
    <div className="space-y-4">
      <div className={CARD}>
        <h2 className="mb-2 text-sm font-bold">🔔 Hoạt động gần đây & Blacklist</h2>
        <p className="mb-3 text-xs text-[var(--muted-foreground)]">
          Ai vừa nhắn tới — qua tài khoản nào, Chat ID, User ID bao nhiêu cho lần gần nhất.
          Bấm chặn để loại nhóm/cá nhân không muốn nhận hoặc hiển thị (tự báo admin qua
          Zalo Cá Nhân, Zalo Bot, Telegram).
        </p>
        <ChannelActivityPanel platform="zalop" title="Zalo Cá Nhân" />
      </div>
      <div className={CARD}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="flex-1 text-sm font-bold">Danh bạ — lấy Thread ID</h2>
        <button onClick={() => void load("user")} className={BTN_GHOST} disabled={loading}><Users className="size-3.5" /> Tải bạn bè</button>
        <button onClick={() => void load("group")} className={BTN_GHOST} disabled={loading}><MessageCircle className="size-3.5" /> Tải nhóm</button>
      </div>
      <input className={`${INPUT} mb-3`} placeholder="Tìm theo tên hoặc ID..." value={filter} onChange={e => setFilter(e.target.value)} />
      <div className="max-h-[28rem] space-y-1.5 overflow-y-auto pr-1">
        {shown.map(c => (
          <div key={`${c.kind}:${c.id}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-xs">
            <span className="rounded bg-[var(--background)] px-1.5 py-0.5">{c.kind === "group" ? "👥" : "👤"}</span>
            <span className="min-w-32 font-semibold">{c.name}</span>
            <code className="flex-1 break-all text-[var(--muted-foreground)]">{c.id}</code>
            <CopyBtn text={c.id} showToast={showToast} title="Copy Thread ID" />
            <button onClick={() => void addTo("zalo_personal_chat_ids", c.id)} className={BTN_GHOST} title="Cho phép AI trả lời thread này">🤖 AI</button>
            <button onClick={() => void addTo("zalo_personal_forward", c.id, c.kind === "group" ? "group" : "user")} className={BTN_GHOST} title="Thêm thread vào webhook chuyển tiếp đầu tiên"><Home className="size-3" /> WH</button>
          </div>
        ))}
        {shown.length === 0 && (
          <p className="text-xs text-[var(--muted-foreground)]">
            {loading ? "Đang tải..." : "Bấm 'Tải bạn bè' hoặc 'Tải nhóm' để liệt kê thread ID (cần ít nhất 1 tài khoản đã đăng nhập)."}
          </p>
        )}
      </div>
      </div>
    </div>
  );
}

// ── Shared ───────────────────────────────────────────────────────────────────

// ── Tab: Admin (nhận thông báo log/hệ thống) ─────────────────────────────────
// Admin = NƠI NHẬN THÔNG BÁO. Chức năng AI của thread do Lọc thread quyết định;
// admin không có trong lọc → bot im lặng, chỉ nhận thông báo. Config ghi vào
// `zalo_personal_account_admins[ownId].admin_entries` (khớp services/zalo_personal.py).
type ZpAdminEntry = {
  chat_id: string;
  kind: "private" | "group";
  notify_enabled: boolean;              // 🔔 hệ thống
  account_log_enabled: boolean;         // 📋 log tài khoản
  account_update_log_enabled: boolean;  // 🔄 cập nhật tài khoản
  newchat_alert_enabled: boolean;       // 💬 chat mới
};

function emptyZpAdmin(): ZpAdminEntry {
  return {
    chat_id: "", kind: "private", notify_enabled: true,
    account_log_enabled: true, account_update_log_enabled: false, newchat_alert_enabled: true,
  };
}

const ZP_ADMIN_TOGGLES: readonly [keyof ZpAdminEntry, string][] = [
  ["notify_enabled", "🔔 Hệ thống"],
  ["account_log_enabled", "📋 Log tài khoản"],
  ["account_update_log_enabled", "🔄 Cập nhật TK"],
  ["newchat_alert_enabled", "💬 Chat mới"],
];

function AdminTab({ status, showToast }:
  { status: Status | null; showToast: (m: string, ok?: boolean) => void }) {
  const config = useSettingsStore((s) => s.config);
  const setField = useSettingsStore((s) => s.setField);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const isSaving = useSettingsStore((s) => s.isSavingConfig);

  // Local state giữ cả slot trống khi đang nhập; config chỉ lưu admin có Thread ID.
  const [rows, setRows] = useState<Record<string, ZpAdminEntry[]>>({});
  const [openAcc, setOpenAcc] = useState<string>("");
  // Collapse cấp 2: mỗi admin thu gọn (key ownId-idx; mặc định ẩn, admin mới = mở)
  const [openAdm, setOpenAdm] = useState<Record<string, boolean>>({});
  const inited = useRef(false);

  useEffect(() => {
    if (inited.current || !config) return;
    inited.current = true;
    const admins = ((config as any).zalo_personal_account_admins || {}) as Record<string, any>;
    const next: Record<string, ZpAdminEntry[]> = {};
    for (const [ownId, v] of Object.entries(admins)) {
      const raw = (v as any)?.admin_entries;
      if (Array.isArray(raw)) {
        next[ownId] = raw.map((e: any) => typeof e === "string"
          ? { ...emptyZpAdmin(), chat_id: e }
          : { ...emptyZpAdmin(), ...e, kind: e?.kind === "group" ? "group" : "private" });
      }
    }
    setRows(next);
  }, [config]);

  // Danh sách account = union tài khoản đang đăng nhập + ownId đã có admin trong config.
  const cfgAdmins = ((config as any)?.zalo_personal_account_admins || {}) as Record<string, any>;
  const accountList: { ownId: string; label: string; acc?: Account }[] = (() => {
    const seen = new Set<string>();
    const out: { ownId: string; label: string; acc?: Account }[] = [];
    for (const a of status?.accounts || []) {
      if (!a.ownId || seen.has(a.ownId)) continue;
      seen.add(a.ownId);
      out.push({ ownId: a.ownId, label: accountLabel(a), acc: a });
    }
    for (const ownId of Object.keys(cfgAdmins)) {
      if (ownId && !seen.has(ownId)) { seen.add(ownId); out.push({ ownId, label: `Tài khoản ${ownId} (offline)` }); }
    }
    return out;
  })();

  const commitToConfig = (nextRows: Record<string, ZpAdminEntry[]>) => {
    const out: Record<string, any> = { ...cfgAdmins };
    const ids = new Set<string>([...Object.keys(out), ...Object.keys(nextRows)]);
    for (const ownId of ids) {
      const clean = (nextRows[ownId] || []).filter((e) => e.chat_id.trim());
      if (clean.length) {
        out[ownId] = { ...(out[ownId] || {}), admin_entries: clean };
      } else if (out[ownId]) {
        const rest = { ...out[ownId] };
        delete rest.admin_entries;
        if (Object.keys(rest).length) out[ownId] = rest; else delete out[ownId];
      }
    }
    setField("zalo_personal_account_admins", out);
  };

  const entriesFor = (ownId: string): ZpAdminEntry[] => rows[ownId] ?? [];
  const setAcc = (ownId: string, list: ZpAdminEntry[]) => {
    const next = { ...rows, [ownId]: list };
    setRows(next);
    commitToConfig(next);
  };
  const update = (ownId: string, idx: number, patch: Partial<ZpAdminEntry>) => {
    const list = [...entriesFor(ownId)];
    list[idx] = { ...list[idx], ...patch };
    setAcc(ownId, list);
  };
  const addAdmin = (ownId: string) => setAcc(ownId, [...entriesFor(ownId), emptyZpAdmin()]);
  const removeAdmin = (ownId: string, idx: number) => {
    const list = [...entriesFor(ownId)];
    list.splice(idx, 1);
    setAcc(ownId, list);
  };

  const save = async () => {
    try { await saveConfig(); showToast("Đã lưu admin Zalo cá nhân ✓"); }
    catch (e) { showToast(`Lỗi lưu: ${e instanceof Error ? e.message : e}`, false); }
  };

  if (!accountList.length) {
    return (
      <div className={CARD}>
        <p className="text-xs text-[var(--muted-foreground)]">
          Chưa có tài khoản Zalo nào. Vào tab &quot;Tài khoản &amp; QR&quot; đăng nhập trước, rồi quay lại đây thêm admin.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--muted-foreground)]">
        Admin = nơi <b>nhận thông báo</b> (📋 log tài khoản / 🔔 hệ thống / 🔄 cập nhật / 💬 chat mới).
        Chức năng AI của thread do <b>Lọc thread</b> quyết định — admin không thêm trong lọc thì bot im lặng, chỉ nhận thông báo.
        Lấy Thread ID ở tab &quot;Danh bạ &amp; Blacklist&quot;.
      </p>
      {accountList.map(({ ownId, label }) => {
        const open = openAcc === ownId;
        const list = entriesFor(ownId);
        const filled = list.filter((e) => e.chat_id.trim()).length;
        return (
          <div key={ownId} className={CARD}>
            <button onClick={() => setOpenAcc(open ? "" : ownId)}
              className="flex w-full items-center justify-between gap-2 text-left">
              <span className="flex items-center gap-2 font-semibold text-sm">
                {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                {label}
              </span>
              <span className="text-xs text-[var(--muted-foreground)]">{filled} admin</span>
            </button>
            {open && (
              <div className="mt-3 space-y-3">
                {list.map((e, i) => {
                  const akey = `${ownId}-${i}`;
                  const aOpen = openAdm[akey] ?? !e.chat_id.trim();
                  return (
                  <div key={i} className="rounded-lg border border-[var(--border)] p-3 space-y-2">
                    <div className="flex items-center gap-2 cursor-pointer select-none"
                      onClick={() => setOpenAdm((s) => ({ ...s, [akey]: !aOpen }))}>
                      {aOpen ? <ChevronDown className="size-4 shrink-0" /> : <ChevronRight className="size-4 shrink-0" />}
                      <span className="flex-1 truncate font-mono text-xs">
                        {e.chat_id.trim() || <span className="text-[var(--muted-foreground)] not-italic">Admin mới — nhập Thread ID</span>}
                      </span>
                      <span className="text-[10px] text-[var(--muted-foreground)]">{e.kind === "group" ? "Nhóm" : "Cá nhân"}</span>
                      <button onClick={(ev) => { ev.stopPropagation(); removeAdmin(ownId, i); }} className={BTN_DANGER} title="Xóa admin">
                        <Trash2 className="size-3" />
                      </button>
                    </div>
                    {aOpen && (
                    <>
                    <div className="flex flex-wrap items-center gap-2">
                      <input className={INPUT} placeholder="Thread ID admin"
                        value={e.chat_id}
                        onChange={(ev) => update(ownId, i, { chat_id: ev.target.value })} />
                      <select className={`${INPUT} w-28`} value={e.kind}
                        onChange={(ev) => update(ownId, i, { kind: ev.target.value === "group" ? "group" : "private" })}>
                        <option value="private">Cá nhân</option>
                        <option value="group">Nhóm</option>
                      </select>
                    </div>
                    <div className="flex flex-wrap gap-3 text-xs">
                      {ZP_ADMIN_TOGGLES.map(([k, lbl]) => (
                        <label key={k} className="inline-flex cursor-pointer items-center gap-1.5">
                          <input type="checkbox" checked={Boolean(e[k])}
                            onChange={(ev) => update(ownId, i, { [k]: ev.target.checked } as Partial<ZpAdminEntry>)} />
                          {lbl}
                        </label>
                      ))}
                    </div>
                    </>
                    )}
                  </div>
                  );
                })}
                <button onClick={() => addAdmin(ownId)} className={BTN_GHOST}>
                  <Plus className="size-3" /> Thêm admin
                </button>
              </div>
            )}
          </div>
        );
      })}
      <button onClick={() => void save()} className={BTN_PRIMARY} disabled={isSaving}>
        {isSaving ? "Đang lưu..." : "Lưu admin"}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold text-[var(--muted-foreground)]">{label}</span>
      {children}
    </label>
  );
}

function CopyBtn({ text, showToast, title }: { text: string; showToast: (m: string, ok?: boolean) => void; title?: string }) {
  return (
    <button title={title} className={BTN_GHOST}
      onClick={() => { void navigator.clipboard.writeText(text); showToast("Đã copy: " + text); }}>
      <Copy className="size-3" />
    </button>
  );
}
