"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

export function EmailCalendarCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const em = (config?.email_channel as Record<string, unknown>) || {};
  const cal = (config?.calendar_connector as Record<string, unknown>) || {};
  const hints = (config?.agent_model_hints as Record<string, unknown>) || {};

  const [enabled, setEnabled] = useState(false);
  const [imapHost, setImapHost] = useState("");
  const [imapPort, setImapPort] = useState("993");
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("465");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [allowed, setAllowed] = useState("");
  const [poll, setPoll] = useState("60");
  const [calEnabled, setCalEnabled] = useState(false);
  const [icsUrl, setIcsUrl] = useState("");
  const [burst, setBurst] = useState("");
  const [reason, setReason] = useState("");
  const [chat, setChat] = useState("");
  const [saved, setSaved] = useState(false);
  const [testMsg, setTestMsg] = useState("");
  const [statusLine, setStatusLine] = useState("");

  useEffect(() => {
    setEnabled(Boolean(em.enabled));
    setImapHost(String(em.imap_host || ""));
    setImapPort(String(em.imap_port ?? 993));
    setSmtpHost(String(em.smtp_host || ""));
    setSmtpPort(String(em.smtp_port ?? 465));
    setUser(String(em.user || ""));
    setPassword(String(em.password || ""));
    const al = Array.isArray(em.allowed_senders) ? (em.allowed_senders as string[]).join(", ") : "";
    setAllowed(al);
    setPoll(String(em.poll_seconds ?? 60));
    setCalEnabled(Boolean(cal.enabled));
    setIcsUrl(String(cal.ics_url || ""));
    setBurst(String(hints.burst || ""));
    setReason(String(hints.reason || ""));
    setChat(String(hints.chat || ""));
  }, [
    em.enabled, em.imap_host, em.imap_port, em.smtp_host, em.smtp_port,
    em.user, em.password, em.allowed_senders, em.poll_seconds,
    cal.enabled, cal.ics_url, hints.burst, hints.reason, hints.chat,
  ]);

  useEffect(() => {
    void (async () => {
      try {
        const res = await request.get("/api/v1/email/status");
        const d = res.data as { enabled?: boolean; running?: boolean; processed?: number; last_error?: string };
        setStatusLine(
          d.enabled
            ? `Email: ${d.running ? "đang poll" : "đã bật (poll ở tick kế tiếp)"} · processed=${d.processed ?? 0}`
            + (d.last_error ? ` · lỗi: ${d.last_error}` : "")
            : "Email channel: tắt",
        );
      } catch {
        /* ignore */
      }
    })();
  }, [saved]);

  const save = async () => {
    const senders = allowed
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    await saveConfig({
      ...config,
      email_channel: {
        enabled,
        imap_host: imapHost.trim(),
        imap_port: Math.max(1, parseInt(imapPort) || 993),
        smtp_host: smtpHost.trim(),
        smtp_port: Math.max(1, parseInt(smtpPort) || 465),
        user: user.trim(),
        password: password,
        use_ssl: true,
        poll_seconds: Math.max(20, parseInt(poll) || 60),
        allowed_senders: senders,
        mark_seen: true,
      },
      calendar_connector: {
        enabled: calEnabled,
        ics_url: icsUrl.trim(),
        max_events: 8,
        days_ahead: 7,
        cache_seconds: 900,
      },
      agent_model_hints: {
        enabled: true,
        chat: chat.trim(),
        burst: burst.trim(),
        reason: reason.trim(),
      },
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const testImap = async () => {
    setTestMsg("Đang kiểm tra IMAP…");
    try {
      const res = await request.post("/api/v1/email/test", {});
      const d = res.data as { ok?: boolean; error?: string };
      setTestMsg(d.ok ? "IMAP OK" : `Lỗi: ${d.error || "unknown"}`);
    } catch (e: unknown) {
      setTestMsg(`Lỗi: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Email · Lịch · Model hints</CardTitle>
        <CardDescription>
          Kênh email IMAP/SMTP (Phase C), lịch ICS cho super-context, và định tuyến model theo hint
          (burst / reason / chat).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-muted-foreground">{statusLine}</p>

        <div className="flex items-center gap-2">
          <input type="checkbox" id="em-en" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <label htmlFor="em-en" className="text-sm font-medium">Bật email channel</label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="text-sm">IMAP host</label>
            <Input value={imapHost} onChange={(e) => setImapHost(e.target.value)} placeholder="imap.gmail.com" />
          </div>
          <div>
            <label className="text-sm">IMAP port</label>
            <Input value={imapPort} onChange={(e) => setImapPort(e.target.value)} />
          </div>
          <div>
            <label className="text-sm">SMTP host</label>
            <Input value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} placeholder="smtp.gmail.com" />
          </div>
          <div>
            <label className="text-sm">SMTP port</label>
            <Input value={smtpPort} onChange={(e) => setSmtpPort(e.target.value)} />
          </div>
          <div>
            <label className="text-sm">User / email</label>
            <Input value={user} onChange={(e) => setUser(e.target.value)} />
          </div>
          <div>
            <label className="text-sm">Password / app password</label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="text-sm">Allowed senders (phẩy; * = tất cả; trống = chặn hết)</label>
          <Input value={allowed} onChange={(e) => setAllowed(e.target.value)} placeholder="you@gmail.com, @family.com" />
        </div>
        <div>
          <label className="text-sm">Poll seconds</label>
          <Input value={poll} onChange={(e) => setPoll(e.target.value)} />
        </div>

        <hr className="border-border" />

        <div className="flex items-center gap-2">
          <input type="checkbox" id="cal-en" checked={calEnabled} onChange={(e) => setCalEnabled(e.target.checked)} />
          <label htmlFor="cal-en" className="text-sm font-medium">Bật lịch ICS</label>
        </div>
        <div>
          <label className="text-sm">ICS URL (Google Calendar secret link…)</label>
          <Input value={icsUrl} onChange={(e) => setIcsUrl(e.target.value)} placeholder="https://calendar.google.com/calendar/ical/…/basic.ics" />
        </div>

        <hr className="border-border" />

        <p className="text-sm font-medium">Model hints (để trống = dùng telegram_ai_model / branch)</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className="text-sm">chat</label>
            <Input value={chat} onChange={(e) => setChat(e.target.value)} placeholder="cx/auto" />
          </div>
          <div>
            <label className="text-sm">burst (rẻ/nhanh)</label>
            <Input value={burst} onChange={(e) => setBurst(e.target.value)} placeholder="gma/flash" />
          </div>
          <div>
            <label className="text-sm">reason (agent)</label>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="claude/sonnet" />
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void save()}>{saved ? "Đã lưu!" : "Lưu"}</Button>
          <Button variant="outline" onClick={() => void testImap()}>Test IMAP</Button>
        </div>
        {testMsg ? <p className="text-xs text-muted-foreground">{testMsg}</p> : null}
        <p className="text-xs text-muted-foreground">
          Supervisor email luôn chạy nền: bật/tắt trong Settings có hiệu lực từ tick kế tiếp
          (≤ poll_seconds), không cần restart container. Allowed senders mặc định fail-closed (trống = chặn hết).
        </p>
      </CardContent>
    </Card>
  );
}
