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
import {
  RefreshCw, QrCode, Webhook, Globe, Users, Send, Trash2,
  CheckCircle2, XCircle, Copy, MessageCircle, Home, Plus,
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

type TabId = "accounts" | "webhooks" | "proxies" | "contacts";

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "accounts", label: "Tài khoản & QR", icon: Users },
  { id: "webhooks", label: "Webhook", icon: Webhook },
  { id: "proxies", label: "Proxy", icon: Globe },
  { id: "contacts", label: "Danh bạ & Blacklist", icon: MessageCircle },
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
                <div className="font-semibold">{a.phoneNumber || a.displayName || a.ownId}</div>
                <div className="text-[var(--muted-foreground)]">ID: {a.ownId} · Proxy: {a.proxy || "không"}</div>
              </div>
              <CopyBtn text={a.ownId} showToast={showToast} title="Copy ownId" />
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

// ── Tab: Webhook ─────────────────────────────────────────────────────────────

type HookRow = { ownId: string; messageWebhookUrl?: string; groupEventWebhookUrl?: string; reactionWebhookUrl?: string };

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
          {rows.map(row => (
            <div key={row.ownId} className="rounded-lg border border-[var(--border)] p-3 text-xs">
              <div className="mb-1 flex items-center gap-2">
                <span className="font-semibold">{row.ownId}</span>
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
          ))}
          {rows.length === 0 && <p className="text-xs text-[var(--muted-foreground)]">Chưa có tài khoản/webhook nào.</p>}
        </div>
      </div>

      {edit && (
        <div className={CARD}>
          <h3 className="mb-3 text-sm font-bold">Sửa webhook — {edit.ownId}</h3>
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
