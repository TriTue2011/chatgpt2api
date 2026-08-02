"use client";

/**
 * Panel Zalo Bot — "🔗 Webhook": CHỈ chế độ nhận tin (webhook ⟷ long-polling).
 *
 * KHÔNG có mục "chuyển tiếp tin ra webhook ngoài" ở đây: việc đó đã có sẵn trong
 * tab "🎚️ Lọc thread" (config `thread_forward_filters`, hàm
 * services/agent/capabilities.forward_event — đã nối vào services/zalo_bot.py).
 * Cấu hình theo TỪNG thread/topic/người, không có công tắc tổng. Thêm một cơ chế
 * thứ hai ở đây là hai nguồn sự thật cho cùng một việc.
 *
 * Backend: /api/zalo-bot/* (api/zalo_bot.py).
 *   GET  /api/zalo-bot/status         getWebhookInfo từng bot (có gọi mạng)
 *   POST /api/zalo-bot/webhook-config {enabled} → setWebhook / deleteWebhook
 *   POST /api/zalo-bot/apply-mode     áp lại đúng chế độ đang cấu hình
 *
 * Docs Zalo Bot Platform (bot.zapps.me/docs):
 *   setWebhook     — POST, tham số `url` (PHẢI HTTPS) + `secret_token` (8–256 ký tự)
 *   deleteWebhook  — POST, KHÔNG tham số
 *   getWebhookInfo — POST, KHÔNG tham số, result = {url, updated_at}
 *   webhook/       — Zalo POST {ok, result:{event_name, message}} kèm header
 *                    X-Bot-Api-Secret-Token
 * Vì `result` của getWebhookInfo chỉ có url + updated_at, panel này KHÔNG hiển
 * thị các trường kiểu Telegram (pending_update_count, last_error_message…) —
 * Zalo không trả về chúng.
 *
 * Auth do trang Settings guard sẵn — panel không tự guard.
 */

import { useCallback, useEffect, useState } from "react";
import { request } from "@/lib/request";
import {
  RefreshCw, Webhook, CheckCircle2, XCircle, AlertTriangle, Radio, Copy,
} from "lucide-react";

const BTN =
  "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition disabled:opacity-50";
const BTN_PRIMARY = `${BTN} bg-[var(--neon-cyan)]/15 text-[var(--neon-cyan)] hover:bg-[var(--neon-cyan)]/25 border border-[var(--neon-cyan)]/30`;
const BTN_GHOST = `${BTN} border border-[var(--border)] hover:bg-[var(--card)]`;
const BTN_DANGER = `${BTN} border border-red-400/30 text-red-400 hover:bg-red-400/10`;
const CARD = "rounded-xl border border-[var(--border)] bg-[var(--card)]/60 p-4";

type Toast = { msg: string; ok: boolean } | null;

type BotInfo = {
  bot_id: string;
  label?: string;
  ok: boolean;
  /** result của getWebhookInfo — docs chỉ có url + updated_at. */
  info?: { url?: string; updated_at?: number } | null;
  error?: string;
  polling: boolean;
  /** URL RIÊNG của bot này — thứ setWebhook thật sự đăng ký. */
  expected_url?: string;
};

type Status = {
  configured: boolean;
  mode: "webhook" | "long-polling";
  webhook_enabled: boolean;
  webhook_url: string;
  expected_webhook_url: string;
  polling: boolean;
  bots_count: number;
  bots_polling: number;
  bots: BotInfo[];
};

function tsLabel(ms?: number): string {
  if (!ms) return "";
  try {
    return new Date(ms).toLocaleString("vi-VN");
  } catch {
    return String(ms);
  }
}

export function ZaloBotWebhookPanel() {
  const [toast, setToast] = useState<Toast>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const showToast = useCallback((msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 5000);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await request.get("/api/zalo-bot/status");
      setStatus(r.data as Status);
    } catch (e) {
      showToast(`Lỗi tải trạng thái: ${e instanceof Error ? e.message : e}`, false);
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => { void refresh(); }, [refresh]);

  const expected = String(status?.expected_webhook_url || "");
  const laHttps = expected.toLowerCase().startsWith("https://");

  const doiCheDo = async (enabled: boolean) => {
    setBusy(true);
    try {
      const r = await request.post("/api/zalo-bot/webhook-config", { enabled });
      const d = r.data as Record<string, unknown>;
      if (d?.fell_back_to_polling) {
        // apply_mode dừng poll TRƯỚC khi setWebhook; trượt hết thì nó tự quay về
        // polling và hạ cờ, nên phải nói rõ kẻo người dùng tưởng đã bật xong.
        showToast(
          `Không đặt được webhook (${String(d.fallback_reason || "")}) → đã tự quay về long-polling để bot không ngưng nhận tin.`,
          false,
        );
      } else if (d?.ok) {
        showToast(enabled ? "Đã bật webhook ✓" : "Đã tắt webhook, quay lại long-polling ✓");
      } else {
        const loi = (d?.bots as { error?: string }[] | undefined)?.find((b) => b?.error)?.error;
        showToast(loi || "Đổi chế độ thất bại", false);
      }
      await refresh();
    } catch (e) {
      showToast(`Lỗi: ${e instanceof Error ? e.message : e}`, false);
    } finally {
      setBusy(false);
    }
  };

  const apLaiCheDo = async () => {
    setBusy(true);
    try {
      const r = await request.post("/api/zalo-bot/apply-mode");
      const d = r.data as Record<string, unknown>;
      if (d?.fell_back_to_polling) {
        showToast(`Webhook không đặt được (${String(d.fallback_reason || "")}) → đã quay về long-polling.`, false);
      } else {
        showToast(d?.ok ? `Đã áp lại chế độ: ${String(d.mode || "")} ✓` : "Áp lại thất bại", !!d?.ok);
      }
      await refresh();
    } catch (e) {
      showToast(`Lỗi: ${e instanceof Error ? e.message : e}`, false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* ── 1. Chế độ nhận tin ────────────────────────────────────────────── */}
      <div className={CARD}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="flex-1 text-sm font-bold flex items-center gap-1.5">
            <Radio className="size-4" /> Chế độ nhận tin
          </h2>
          <button onClick={() => void refresh()} className={BTN_GHOST} disabled={loading}>
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} /> Tải lại
          </button>
          <button onClick={() => void apLaiCheDo()} className={BTN_GHOST} disabled={busy}>
            Áp lại chế độ
          </button>
        </div>

        <p className="mb-3 text-xs text-[var(--muted-foreground)]">
          Hai chế độ loại trừ nhau: <b>webhook</b> để Zalo tự POST tin vào server,
          còn <b>long-polling</b> thì server chủ động hỏi Zalo. Docs getUpdates ghi rõ
          getUpdates không hoạt động khi đã đặt webhook, nên hệ thống chỉ chạy đúng một
          chế độ tại một thời điểm.
        </p>

        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2.5">
          <span className="text-xs font-semibold">Đang chạy:</span>
          <span className={`rounded px-2 py-0.5 text-xs font-bold ${
            status?.mode === "webhook"
              ? "bg-[var(--neon-cyan)]/15 text-[var(--neon-cyan)]"
              : "bg-amber-400/15 text-amber-400"
          }`}>
            {status?.mode === "webhook" ? "🔗 Webhook" : "🔄 Long-polling"}
          </span>
          <span className="text-xs text-[var(--muted-foreground)]">
            {status?.bots_count ?? 0} bot · {status?.bots_polling ?? 0} đang poll
          </span>
          <div className="flex-1" />
          <button
            onClick={() => void doiCheDo(!status?.webhook_enabled)}
            className={status?.webhook_enabled ? BTN_DANGER : BTN_PRIMARY}
            disabled={busy || !status?.configured}
          >
            <Webhook className="size-3.5" />
            {status?.webhook_enabled ? "Tắt webhook (về polling)" : "Bật webhook"}
          </button>
        </div>

        <label className="mb-1 block text-xs font-semibold">
          URL webhook gốc — mỗi bot còn có URL riêng <code>…/webhook/&lt;bot_id&gt;</code>
        </label>
        <div className="flex items-center gap-2">
          <code className="flex-1 break-all rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs">
            {expected || "(chưa có — đặt zalo_webhook_url hoặc base_url)"}
          </code>
          {expected && <CopyBtn text={expected} showToast={showToast} title="Copy URL webhook" />}
        </div>

        {expected && !laHttps && (
          <div className="mt-2 flex gap-2 rounded-lg border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-300">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <div>
              <b>Chưa bật được webhook:</b> docs setWebhook đòi URL dạng <b>HTTPS</b>, mà
              URL hiện tại là <code>{expected.split(":")[0]}</code>. Zalo cũng không gọi
              được vào địa chỉ mạng nội bộ.
              <div className="mt-1">
                Cần một tên miền HTTPS công khai, rồi đặt <code>zalo_webhook_url</code> hoặc
                biến môi trường <code>CHATGPT2API_BASE_URL</code>.
              </div>
              <div className="mt-1 opacity-80">
                Bấm &quot;Bật webhook&quot; lúc này sẽ thất bại và hệ thống tự quay lại
                long-polling — bot vẫn nhận tin bình thường, không bị đứng.
              </div>
            </div>
          </div>
        )}

        {!status?.configured && (
          <p className="mt-2 text-xs text-amber-400">
            Chưa có bot nào được cấu hình token — thêm bot ở tab &quot;⚙️ Cài đặt kênh&quot; trước.
          </p>
        )}

        {/* getWebhookInfo từng bot */}
        {!!status?.bots?.length && (
          <div className="mt-3 space-y-1.5">
            <p className="text-xs font-semibold">Zalo đang giữ URL nào (getWebhookInfo)</p>
            {status.bots.map((b) => {
              const zaloUrl = String(b.info?.url || "");
              // So với URL RIÊNG của chính bot này, không phải URL chung.
              const mong = String(b.expected_url || expected);
              const lech = !!zaloUrl && !!mong && zaloUrl.replace(/\/$/, "") !== mong.replace(/\/$/, "");
              return (
                <div key={b.bot_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-xs">
                  {b.ok ? <CheckCircle2 className="size-3.5 text-emerald-400" /> : <XCircle className="size-3.5 text-red-400" />}
                  <span className="font-semibold">{b.label || b.bot_id}</span>
                  {b.polling && <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-amber-400">đang poll</span>}
                  <code className="flex-1 break-all text-[var(--muted-foreground)]">
                    {b.ok ? (zaloUrl || "(trống — chưa đặt webhook)") : b.error}
                  </code>
                  {!!b.info?.updated_at && (
                    <span className="text-[var(--muted-foreground)]">{tsLabel(b.info.updated_at)}</span>
                  )}
                  {!!b.expected_url && (
                    <CopyBtn text={b.expected_url} showToast={showToast}
                             title={`Copy URL riêng của bot này: ${b.expected_url}`} />
                  )}
                  {lech && (
                    <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-amber-400" title="URL Zalo đang giữ khác URL ta sẽ đăng ký — bấm 'Áp lại chế độ'">
                      lệch URL
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

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

function CopyBtn({ text, showToast, title }:
  { text: string; showToast: (m: string, ok?: boolean) => void; title?: string }) {
  return (
    <button title={title} className={BTN_GHOST}
      onClick={() => { void navigator.clipboard.writeText(text); showToast("Đã copy: " + text); }}>
      <Copy className="size-3" />
    </button>
  );
}
