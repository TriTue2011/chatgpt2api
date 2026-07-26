"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

/** Một hộp mail trong UI (khớp services/email_channel._norm_account). */
type EmailAcc = {
  uiId: number;
  id: string; label: string; enabled: boolean;
  imap_host: string; imap_port: string; smtp_host: string; smtp_port: string;
  user: string; password: string;
  allowed_senders: string; poll_seconds: string;
  reply_enabled: boolean; summarize_files: boolean;
  notify_on_new: boolean; notify_times: string; notify_targets: string[];
};

/** Một lịch ICS trong UI (khớp services/calendar_connector._norm_cal). */
type CalRow = {
  uiId: number;
  id: string; label: string; enabled: boolean;
  ics_url: string; days_ahead: string;
  notify_on_new: boolean; notify_times: string; notify_targets: string[];
};

const APP_PW_NOTE = (
  <>
    Gmail/Outlook bật 2FA thì mật khẩu thường KHÔNG dùng được — phải tạo{" "}
    <b>App Password</b> (mật khẩu ứng dụng 16 ký tự):{" "}
    <a className="underline" href="https://myaccount.google.com/apppasswords"
      target="_blank" rel="noreferrer">Gmail</a>{" · "}
    <a className="underline" href="https://account.live.com/proofs/AppPassword"
      target="_blank" rel="noreferrer">Outlook</a>
  </>
);

export function EmailCalendarCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const hints = (config?.agent_model_hints as Record<string, unknown>) || {};

  const seq = useRef(1);
  const inited = useRef(false);
  const [accs, setAccs] = useState<EmailAcc[]>([]);
  const [cals, setCals] = useState<CalRow[]>([]);
  const [openAcc, setOpenAcc] = useState<Record<number, boolean>>({});
  const [openCal, setOpenCal] = useState<Record<number, boolean>>({});
  const [burst, setBurst] = useState("");
  const [reason, setReason] = useState("");
  const [chat, setChat] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<Record<string, string>>({});
  const [statusLine, setStatusLine] = useState("");

  // Kênh nhận = các thread ĐÃ đặt trong «Lọc thread» (có tên sẵn) — chọn nhiều.
  const tf = (config as Record<string, unknown> | null)?.thread_filters as
    Record<string, unknown> | undefined;
  const tfMeta = (config as Record<string, unknown> | null)?.thread_filter_meta as
    Record<string, { name?: string }> | undefined;
  const targetOptions: { value: string; label: string }[] = Object.keys(tf || {})
    .map((key) => ({
      value: key,
      label: (tfMeta?.[key]?.name ? `${tfMeta[key].name} · ` : "") + key,
    }));

  useEffect(() => {
    if (inited.current || !config) return;
    inited.current = true;
    const toList = (v: unknown): string[] =>
      Array.isArray(v) ? v.map((x) => String(x)) : [];
    // email_accounts mới; rỗng → email_channel cũ thành hộp #1 (như backend)
    const rawAccs = (config as Record<string, unknown>).email_accounts;
    const em = (config as Record<string, unknown>).email_channel as
      Record<string, unknown> | undefined;
    const srcAccs: Record<string, unknown>[] =
      Array.isArray(rawAccs) && rawAccs.length
        ? (rawAccs as Record<string, unknown>[])
        : (em && String(em.user || "").trim()
          ? [{ ...em, label: "Hộp mail chính", reply_enabled: em.reply_enabled ?? true }]
          : []);
    setAccs(srcAccs.map((a) => ({
      uiId: seq.current++,
      id: String(a.id || ""), label: String(a.label || ""),
      enabled: Boolean(a.enabled),
      imap_host: String(a.imap_host || ""), imap_port: String(a.imap_port ?? 993),
      smtp_host: String(a.smtp_host || ""), smtp_port: String(a.smtp_port ?? 465),
      user: String(a.user || ""), password: String(a.password || ""),
      allowed_senders: toList(a.allowed_senders).join(", "),
      poll_seconds: String(a.poll_seconds ?? 60),
      reply_enabled: Boolean(a.reply_enabled),
      summarize_files: a.summarize_files === undefined ? true : Boolean(a.summarize_files),
      notify_on_new: a.notify_on_new === undefined ? true : Boolean(a.notify_on_new),
      notify_times: toList(a.notify_times).join(", "),
      notify_targets: toList(a.notify_targets),
    })));
    const rawCals = (config as Record<string, unknown>).calendars;
    const cal = (config as Record<string, unknown>).calendar_connector as
      Record<string, unknown> | undefined;
    const srcCals: Record<string, unknown>[] =
      Array.isArray(rawCals) && rawCals.length
        ? (rawCals as Record<string, unknown>[])
        : (cal && String(cal.ics_url || "").trim()
          ? [{ ...cal, label: "Lịch chính" }] : []);
    setCals(srcCals.map((c) => ({
      uiId: seq.current++,
      id: String(c.id || ""), label: String(c.label || ""),
      enabled: Boolean(c.enabled),
      ics_url: String(c.ics_url || ""), days_ahead: String(c.days_ahead ?? 7),
      notify_on_new: c.notify_on_new === undefined ? true : Boolean(c.notify_on_new),
      notify_times: toList(c.notify_times).join(", "),
      notify_targets: toList(c.notify_targets),
    })));
    setBurst(String(hints.burst || ""));
    setReason(String(hints.reason || ""));
    setChat(String(hints.chat || ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  useEffect(() => {
    void (async () => {
      try {
        const res = await request.get("/api/v1/email/status");
        const d = res.data as {
          enabled?: boolean; running?: boolean; processed?: number;
          count?: number; last_error?: string;
        };
        setStatusLine(
          d.enabled
            ? `Email: ${d.count ?? 0} hộp · ${d.running ? "đang poll" : "chờ tick"} · processed=${d.processed ?? 0}`
            + (d.last_error ? ` · ${d.last_error}` : "")
            : "Email: chưa bật hộp nào",
        );
      } catch { /* ignore */ }
    })();
  }, [saved]);

  const splitList = (s: string) =>
    s.split(",").map((x) => x.trim()).filter(Boolean);

  const save = async (nextAccs?: EmailAcc[], nextCals?: CalRow[]) => {
    const A = nextAccs ?? accs;
    const C = nextCals ?? cals;
    await saveConfig({
      ...config,
      email_accounts: A.map((a) => ({
        id: a.id || undefined, label: a.label.trim(), enabled: a.enabled,
        imap_host: a.imap_host.trim(),
        imap_port: Math.max(1, parseInt(a.imap_port) || 993),
        smtp_host: a.smtp_host.trim(),
        smtp_port: Math.max(1, parseInt(a.smtp_port) || 465),
        user: a.user.trim(), password: a.password, use_ssl: true,
        poll_seconds: Math.max(20, parseInt(a.poll_seconds) || 60),
        allowed_senders: splitList(a.allowed_senders), mark_seen: true,
        reply_enabled: a.reply_enabled, summarize_files: a.summarize_files,
        notify_on_new: a.notify_on_new,
        notify_times: splitList(a.notify_times),
        notify_targets: a.notify_targets,
      })),
      calendars: C.map((c) => ({
        id: c.id || undefined, label: c.label.trim(), enabled: c.enabled,
        ics_url: c.ics_url.trim(),
        days_ahead: Math.max(1, parseInt(c.days_ahead) || 7),
        max_events: 8, cache_seconds: 900,
        notify_on_new: c.notify_on_new,
        notify_times: splitList(c.notify_times),
        notify_targets: c.notify_targets,
      })),
      agent_model_hints: {
        enabled: true, chat: chat.trim(), burst: burst.trim(), reason: reason.trim(),
      },
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const patchAcc = (uiId: number, p: Partial<EmailAcc>) =>
    setAccs((prev) => prev.map((a) => (a.uiId === uiId ? { ...a, ...p } : a)));
  const patchCal = (uiId: number, p: Partial<CalRow>) =>
    setCals((prev) => prev.map((c) => (c.uiId === uiId ? { ...c, ...p } : c)));

  const call = async (key: string, url: string, body: Record<string, unknown>) => {
    setBusy(key);
    const msgKey = key.replace(/-(test|poll|digest)$/, "");
    setMsg((m) => ({ ...m, [msgKey]: "Đang chạy…" }));
    try {
      const res = await request.post(url, body);
      const d = res.data as { ok?: boolean; message?: string; error?: string };
      const line = d.ok ? (d.message || "✅ OK") : (d.error || "❌ Lỗi không rõ");
      setMsg((m) => ({ ...m, [msgKey]: line }));
    } catch (e: unknown) {
      setMsg((m) => ({
        ...m, [msgKey]: `❌ ${e instanceof Error ? e.message : String(e)}`,
      }));
    } finally {
      setBusy("");
    }
  };

  /** Chọn kênh nhận (nhiều) + mốc giờ + cứ-có-mới — dùng chung email và lịch. */
  const notifyBlock = (
    targets: string[], onNew: boolean, times: string,
    set: (p: { notify_targets?: string[]; notify_on_new?: boolean; notify_times?: string }) => void,
  ) => (
    <div className="rounded border border-dashed border-border/70 p-2 space-y-1.5">
      <p className="text-xs font-medium">📣 Gửi tóm tắt tới kênh</p>
      {targetOptions.length === 0 ? (
        <p className="text-[10px] text-amber-600">
          Chưa có thread nào trong «Lọc thread» — vào Kênh chat → Lọc thread thêm
          thread trước, rồi quay lại chọn ở đây.
        </p>
      ) : (
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {targetOptions.map((o) => (
            <label key={o.value}
              className="flex items-center gap-1 text-[11px] text-muted-foreground cursor-pointer select-none">
              <input type="checkbox" className="size-3.5"
                checked={targets.includes(o.value)}
                onChange={() => set({
                  notify_targets: targets.includes(o.value)
                    ? targets.filter((x) => x !== o.value)
                    : [...targets, o.value],
                })} />
              {o.label}
            </label>
          ))}
        </div>
      )}
      <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
        <input type="checkbox" className="size-3.5" checked={onNew}
          onChange={() => set({ notify_on_new: !onNew })} />
        ⚡ Cứ có mới là tóm tắt gửi ngay
      </label>
      <div>
        <label className="text-[10px] text-muted-foreground">
          🕐 Mốc giờ định kỳ (phẩy, vd: 07:00, 18:30) — gom các mục mới, tới giờ gửi
          MỘT bản tổng hợp; trống = không gửi định kỳ
        </label>
        <Input value={times} className="h-7 text-xs"
          onChange={(e) => set({ notify_times: e.target.value })}
          placeholder="07:00, 18:30" />
      </div>
    </div>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Email · Lịch · Model hints</CardTitle>
        <CardDescription>
          Nhiều hộp mail + nhiều lịch — mỗi nguồn tự chọn kênh nhận, gửi ngay khi có
          mới hoặc gom theo mốc giờ. Tóm tắt cả nội dung thư lẫn tệp đính kèm.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-muted-foreground">{statusLine}</p>

        {/* ── Hộp mail ─────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">📬 Hộp mail ({accs.length})</p>
          <Button type="button" variant="outline" size="sm"
            onClick={() => {
              const row: EmailAcc = {
                uiId: seq.current++, id: "", label: "", enabled: true,
                imap_host: "imap.gmail.com", imap_port: "993",
                smtp_host: "", smtp_port: "465", user: "", password: "",
                allowed_senders: "*", poll_seconds: "60",
                reply_enabled: false, summarize_files: true,
                notify_on_new: true, notify_times: "", notify_targets: [],
              };
              setAccs((p) => [...p, row]);
              setOpenAcc((s) => ({ ...s, [row.uiId]: true }));
            }}>
            + Thêm hộp mail
          </Button>
        </div>
        {accs.map((a) => {
          const open = openAcc[a.uiId] ?? !a.user.trim();
          const mkey = `em-${a.uiId}`;
          return (
            <div key={a.uiId} className="rounded-md border border-border p-2 space-y-2">
              <div className="flex items-center gap-2 cursor-pointer select-none"
                onClick={() => setOpenAcc((s) => ({ ...s, [a.uiId]: !open }))}>
                <span className="inline-flex size-5 shrink-0 items-center justify-center rounded border border-border bg-muted/40 text-[10px] text-muted-foreground">{open ? "▾" : "▸"}</span>
                <span className="text-[11px] font-medium truncate flex-1">
                  {a.label.trim() || a.user.trim() || "Hộp mail mới"}
                  {a.user.trim() ? <> · <span className="font-mono">{a.user.trim()}</span></> : null}
                </span>
                <span className="text-[10px] text-muted-foreground shrink-0">
                  {a.enabled ? "đang bật" : "tắt"}
                </span>
                <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-[10px]"
                  onClick={(e) => {
                    e.stopPropagation();
                    const next = accs.filter((x) => x.uiId !== a.uiId);
                    setAccs(next); void save(next, undefined);
                  }}>Xóa</Button>
              </div>
              {open ? (
                <>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div>
                      <label className="text-[10px] text-muted-foreground">Tên hiển thị</label>
                      <Input value={a.label} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { label: e.target.value })}
                        placeholder="Gmail chính" />
                    </div>
                    <label className="flex items-end gap-1.5 pb-1 text-xs cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={a.enabled}
                        onChange={() => patchAcc(a.uiId, { enabled: !a.enabled })} />
                      Bật hộp này
                    </label>
                    <div>
                      <label className="text-[10px] text-muted-foreground">IMAP host</label>
                      <Input value={a.imap_host} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { imap_host: e.target.value })}
                        placeholder="imap.gmail.com" />
                    </div>
                    <div>
                      <label className="text-[10px] text-muted-foreground">IMAP port</label>
                      <Input value={a.imap_port} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { imap_port: e.target.value })} />
                    </div>
                    <div>
                      <label className="text-[10px] text-muted-foreground">
                        SMTP host (trống = tự đoán từ IMAP)
                      </label>
                      <Input value={a.smtp_host} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { smtp_host: e.target.value })}
                        placeholder="smtp.gmail.com" />
                    </div>
                    <div>
                      <label className="text-[10px] text-muted-foreground">SMTP port</label>
                      <Input value={a.smtp_port} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { smtp_port: e.target.value })} />
                    </div>
                    <div>
                      <label className="text-[10px] text-muted-foreground">Địa chỉ email</label>
                      <Input value={a.user} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { user: e.target.value })}
                        placeholder="ban@gmail.com" />
                    </div>
                    <div>
                      <label className="text-[10px] text-muted-foreground">App Password</label>
                      <Input type="password" value={a.password} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { password: e.target.value })}
                        placeholder="16 ký tự — KHÔNG phải mật khẩu đăng nhập" />
                    </div>
                  </div>
                  <p className="text-[10px] text-muted-foreground">{APP_PW_NOTE}</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div>
                      <label className="text-[10px] text-muted-foreground">
                        Người gửi được nhận (phẩy; * = tất cả; trống = chặn hết)
                      </label>
                      <Input value={a.allowed_senders} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { allowed_senders: e.target.value })}
                        placeholder="ban@gmail.com, @congty.com, *" />
                    </div>
                    <div>
                      <label className="text-[10px] text-muted-foreground">Poll (giây, ≥20)</label>
                      <Input value={a.poll_seconds} className="h-8 text-xs"
                        onChange={(e) => patchAcc(a.uiId, { poll_seconds: e.target.value })} />
                    </div>
                  </div>
                  <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                    <input type="checkbox" className="size-3.5" checked={a.summarize_files}
                      onChange={() => patchAcc(a.uiId, { summarize_files: !a.summarize_files })} />
                    📎 Tóm tắt CẢ nội dung tệp đính kèm (PDF/Word/Excel/txt…)
                  </label>
                  <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                    <input type="checkbox" className="size-3.5" checked={a.reply_enabled}
                      onChange={() => patchAcc(a.uiId, { reply_enabled: !a.reply_enabled })} />
                    🤖 AI trả lời thẳng vào email (tắt = chỉ tóm tắt gửi kênh)
                  </label>
                  {notifyBlock(a.notify_targets, a.notify_on_new, a.notify_times,
                    (p) => patchAcc(a.uiId, p))}
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" variant="outline" size="sm" className="h-7 text-[11px]"
                      disabled={busy === `${mkey}-test`}
                      onClick={() => void call(`${mkey}-test`, "/api/v1/email/test",
                        { account_id: a.id || a.user.trim() })}>
                      {busy === `${mkey}-test` ? "…" : "Test IMAP"}
                    </Button>
                    <Button type="button" variant="outline" size="sm" className="h-7 text-[11px]"
                      disabled={busy === `${mkey}-poll`}
                      onClick={() => void call(`${mkey}-poll`, "/api/v1/email/poll",
                        { account_id: a.id || a.user.trim() })}>
                      {busy === `${mkey}-poll` ? "…" : "Đọc mail ngay"}
                    </Button>
                    <Button type="button" variant="outline" size="sm" className="h-7 text-[11px]"
                      disabled={busy === `${mkey}-digest`}
                      onClick={() => void call(`${mkey}-digest`, "/api/v1/email/digest",
                        { account_id: a.id || a.user.trim() })}>
                      {busy === `${mkey}-digest` ? "…" : "Gửi thử tới kênh"}
                    </Button>
                  </div>
                  {msg[mkey] ? <p className="text-[10px] text-muted-foreground">{msg[mkey]}</p> : null}
                  <p className="text-[10px] text-muted-foreground">
                    Lưu trước rồi mới bấm Test/Đọc/Gửi thử (server đọc cấu hình đã lưu).
                  </p>
                </>
              ) : null}
            </div>
          );
        })}

        <hr className="border-border" />

        {/* ── Lịch ─────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">📅 Lịch ({cals.length})</p>
          <Button type="button" variant="outline" size="sm"
            onClick={() => {
              const row: CalRow = {
                uiId: seq.current++, id: "", label: "", enabled: true,
                ics_url: "", days_ahead: "7",
                notify_on_new: true, notify_times: "", notify_targets: [],
              };
              setCals((p) => [...p, row]);
              setOpenCal((s) => ({ ...s, [row.uiId]: true }));
            }}>
            + Thêm lịch
          </Button>
        </div>
        {cals.map((c) => {
          const open = openCal[c.uiId] ?? !c.ics_url.trim();
          const mkey = `cal-${c.uiId}`;
          return (
            <div key={c.uiId} className="rounded-md border border-border p-2 space-y-2">
              <div className="flex items-center gap-2 cursor-pointer select-none"
                onClick={() => setOpenCal((s) => ({ ...s, [c.uiId]: !open }))}>
                <span className="inline-flex size-5 shrink-0 items-center justify-center rounded border border-border bg-muted/40 text-[10px] text-muted-foreground">{open ? "▾" : "▸"}</span>
                <span className="text-[11px] font-medium truncate flex-1">
                  {c.label.trim() || "Lịch mới"}
                </span>
                <span className="text-[10px] text-muted-foreground shrink-0">
                  {c.enabled ? "đang bật" : "tắt"}
                </span>
                <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-[10px]"
                  onClick={(e) => {
                    e.stopPropagation();
                    const next = cals.filter((x) => x.uiId !== c.uiId);
                    setCals(next); void save(undefined, next);
                  }}>Xóa</Button>
              </div>
              {open ? (
                <>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div>
                      <label className="text-[10px] text-muted-foreground">Tên hiển thị</label>
                      <Input value={c.label} className="h-8 text-xs"
                        onChange={(e) => patchCal(c.uiId, { label: e.target.value })}
                        placeholder="Lịch gia đình" />
                    </div>
                    <label className="flex items-end gap-1.5 pb-1 text-xs cursor-pointer select-none">
                      <input type="checkbox" className="size-3.5" checked={c.enabled}
                        onChange={() => patchCal(c.uiId, { enabled: !c.enabled })} />
                      Bật lịch này
                    </label>
                  </div>
                  <div>
                    <label className="text-[10px] text-muted-foreground">
                      Link ICS (Google Calendar → Cài đặt lịch → «Địa chỉ bí mật ở định dạng iCal»)
                    </label>
                    <Input value={c.ics_url} className="h-8 text-xs font-mono"
                      onChange={(e) => patchCal(c.uiId, { ics_url: e.target.value })}
                      placeholder="https://calendar.google.com/calendar/ical/…/basic.ics" />
                  </div>
                  <div>
                    <label className="text-[10px] text-muted-foreground">Nhìn trước (ngày)</label>
                    <Input value={c.days_ahead} className="h-8 text-xs w-24"
                      onChange={(e) => patchCal(c.uiId, { days_ahead: e.target.value })} />
                  </div>
                  {notifyBlock(c.notify_targets, c.notify_on_new, c.notify_times,
                    (p) => patchCal(c.uiId, p))}
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" variant="outline" size="sm" className="h-7 text-[11px]"
                      disabled={busy === `${mkey}-test`}
                      onClick={() => void call(`${mkey}-test`, "/api/v1/calendar/test",
                        { calendar_id: c.id })}>
                      {busy === `${mkey}-test` ? "…" : "Kiểm tra lịch"}
                    </Button>
                    <Button type="button" variant="outline" size="sm" className="h-7 text-[11px]"
                      disabled={busy === `${mkey}-digest`}
                      onClick={() => void call(`${mkey}-digest`, "/api/v1/calendar/digest",
                        { calendar_id: c.id })}>
                      {busy === `${mkey}-digest` ? "…" : "Gửi thử tới kênh"}
                    </Button>
                  </div>
                  {msg[mkey] ? <p className="text-[10px] text-muted-foreground">{msg[mkey]}</p> : null}
                  <p className="text-[10px] text-muted-foreground">
                    «Kiểm tra lịch» tải thật link ICS: báo đọc được không, bao nhiêu sự
                    kiện và 3 mục gần nhất. Lưu trước rồi mới bấm.
                  </p>
                </>
              ) : null}
            </div>
          );
        })}

        <hr className="border-border" />

        <p className="text-sm font-medium">Model hints (để trống = dùng telegram_ai_model / branch)</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className="text-sm">chat</label>
            <Input value={chat} onChange={(e) => setChat(e.target.value)} placeholder="cx/auto" />
          </div>
          <div>
            <label className="text-sm">burst (rẻ/nhanh — dùng tóm tắt email/lịch)</label>
            <Input value={burst} onChange={(e) => setBurst(e.target.value)} placeholder="gma/flash" />
          </div>
          <div>
            <label className="text-sm">reason (agent)</label>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="claude/sonnet" />
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void save()}>{saved ? "Đã lưu!" : "Lưu"}</Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Supervisor chạy nền liên tục: thêm/bật hộp mail hay lịch có hiệu lực ngay
          sau khi Lưu, không cần restart. Người gửi mặc định fail-closed (trống =
          chặn hết). Mỗi mốc giờ định kỳ chỉ gửi 1 lần/ngày; không có mục mới thì
          không gửi (không spam).
        </p>
      </CardContent>
    </Card>
  );
}
