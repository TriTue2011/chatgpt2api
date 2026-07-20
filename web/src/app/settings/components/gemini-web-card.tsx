"use client";

import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Sparkles, ExternalLink, X, Save, Shield } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { SavedAccountsSelect } from "@/components/saved-accounts-select";
import { generateTotpCode, totpSecondsRemaining } from "@/lib/totp";
import { ReuseProfilePicker } from "./reuse-profile-picker";

type OnboardState = {
  profile: string;
  state: "none" | "starting" | "running" | "need_tap" | "need_code" | "success" | "failed";
  message: string;
  elapsed_sec?: number;
  error?: string | null;
};

type CSCfg = { url: string; apiKey: string };

export function GeminiWebCard() {
  const [cs, setCs] = useState<CSCfg>({
    url: "/api/captcha",
    apiKey: "",
  });
  const [profile, setProfile] = useState("gemini-web-default");
  const [timeout, setTimeoutVal] = useState(120);
  const [draft, setDraft] = useState({ email: "", password: "", totpSecret: "" });
  const [selectedAccount, setSelectedAccount] = useState("");
  const [isSavingAccount, setIsSavingAccount] = useState(false);
  const [savedRefreshKey, setSavedRefreshKey] = useState(0);
  const [running, setRunning] = useState(false);
  const [session, setSession] = useState<OnboardState | null>(null);
  const [savingCfg, setSavingCfg] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [totpRemaining, setTotpRemaining] = useState(30);
  const pollRef = useRef<number | null>(null);
  const totpTimerRef = useRef<number | null>(null);

  // Auto-refresh TOTP code
  useEffect(() => {
    if (!draft.totpSecret.trim()) { setTotpCode(""); return; }
    const refresh = async () => {
      try {
        setTotpCode(await generateTotpCode(draft.totpSecret));
        setTotpRemaining(totpSecondsRemaining());
      } catch { setTotpCode(""); }
    };
    void refresh();
    totpTimerRef.current = window.setInterval(refresh, 5000);
    return () => { if (totpTimerRef.current) window.clearInterval(totpTimerRef.current); };
  }, [draft.totpSecret]);

  useEffect(() => {
    void fetchCfg();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  // Account-centric profile suggestion: when an email is entered and the
  // profile is still the untouched default, suggest google-<localpart> so the
  // SAME Google account reuses ONE browser profile across ChatGPT / Gemini
  // Web / Flow (provider-neutral naming). Won't override a custom value.
  useEffect(() => {
    const local = (draft.email.split("@")[0] || "").replace(/[^a-z0-9-]/gi, "-");
    if (local && (profile === "" || profile === "gemini-web-default")) {
      setProfile(`google-${local}`);
    }
  }, [draft.email, profile]);

  async function fetchCfg() {
    try {
      const data = await request.get("/api/settings");
      const cfg = (data.data as any)?.config?.providers || {};
      const flow = cfg.flow || {};
      const gemw = cfg.gemini_web || {};
      setCs({
        url: "/api/captcha",
        apiKey: gemw.captcha_solver_api_key || flow.captcha_solver_api_key || "",
      });
      setProfile(gemw.profile || "gemini-web-default");
      setTimeoutVal(Number(gemw.timeout) || 120);
    } catch (e) {
      console.error(e);
    }
  }

  async function saveProviderCfg() {
    setSavingCfg(true);
    try {
      const cur = await request.get("/api/settings");
      const config = (cur.data as any)?.config || {};
      config.providers = config.providers || {};
      config.providers.gemini_web = {
        ...(config.providers.gemini_web || {}),
        profile: profile.trim() || "gemini-web-default",
        timeout: Math.max(30, Math.min(600, timeout)),
      };
      await request.post("/api/settings", { providers: config.providers });
      toast.success("Đã lưu config Gemini Web");
    } catch (e: any) {
      toast.error(`Save fail: ${e?.message || e}`);
    } finally {
      setSavingCfg(false);
    }
  }

  async function persistGeminiWebConfig(prof: string) {
    try {
      const cur = await request.get("/api/settings");
      const config = (cur.data as any)?.config || {};
      config.providers = config.providers || {};
      const geminiWeb = config.providers.gemini_web || {};
      const accounts = Array.isArray(geminiWeb.accounts) ? [...geminiWeb.accounts] : [];
      if (!accounts.some((a: any) => a.profile === prof)) {
        accounts.push({ profile: prof, label: prof });
      }
      config.providers.gemini_web = {
        ...geminiWeb,
        enabled: true,
        profile: prof, // Keep legacy field for fallback
        accounts,
      };
      await request.post("/api/settings", { providers: config.providers });
      toast.success(`Đã lưu config Gemini Web (${prof}) ✓`);
    } catch (e: any) {
      toast.error(`Lưu config fail: ${e?.message || e}`);
    }
  }

  function stopPolling() {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function pollStatus() {
    try {
      const res = await fetch(
        `${cs.url}/v1/gemini-web/${encodeURIComponent(profile)}/onboard-status`,
        { headers: { Authorization: `Bearer ${cs.apiKey}` } },
      );
      if (!res.ok) return;
      const data: OnboardState = await res.json();
      setSession(data);
      if (data.state === "success" || data.state === "failed") {
        stopPolling();
        setRunning(false);
        if (data.state === "success") {
          toast.success(`Gemini Web profile sẵn sàng ✓`);
          void persistGeminiWebConfig(profile);
        }
        else toast.error(`Onboard fail: ${data.error || data.message}`);
      }
    } catch {
      /* ignore */
    }
  }

  // Cách A — reuse an existing profile's Google session for Gemini Web (no
  // email/password). Onboard short-circuits if the session is alive, then we
  // point the gemini_web provider at this profile.
  async function reuseOnboard(prof: string) {
    stopPolling();
    setProfile(prof);
    setRunning(true);
    setSession(null);
    try {
      const res = await fetch(`${cs.url}/v1/gemini-web/onboard`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ profile: prof, email: "", password: "" }),
      });
      if (!res.ok) throw new Error(`reuse HTTP ${res.status}`);
      const initial = await res.json();
      setSession(initial);
      toast.info(`Đang tái dùng ${prof} cho Gemini Web…`);
      const handleSuccess = async (data: OnboardState) => {
        await persistGeminiWebConfig(prof);
      };
      
      if (initial.state === "success") {
        setRunning(false);
        void handleSuccess(initial as OnboardState);
      } else if (initial.state === "failed") {
        setRunning(false);
        toast.error(`Reuse fail: ${initial.error || initial.message}`);
      } else {
        pollRef.current = window.setInterval(async () => {
          try {
            const r = await fetch(`${cs.url}/v1/gemini-web/${encodeURIComponent(prof)}/onboard-status`, {
              headers: { Authorization: `Bearer ${cs.apiKey}` },
            });
            if (!r.ok) return;
            const data: OnboardState = await r.json();
            setSession(data);
            if (data.state === "success") {
              stopPolling();
              setRunning(false);
              void handleSuccess(data);
            } else if (data.state === "failed") {
              stopPolling();
              setRunning(false);
              toast.error(`Reuse fail: ${data.error || data.message}`);
            }
          } catch { /* ignore */ }
        }, 1500);
      }
    } catch (e: any) {
      toast.error(`Reuse error: ${e?.message}`);
      setRunning(false);
    }
  }

  async function onboard() {
    if (!draft.email.trim() || !draft.password) {
      toast.error("Cần email + mật khẩu Google");
      return;
    }
    stopPolling();
    setRunning(true);
    setSession(null);
    try {
      const res = await fetch(`${cs.url}/v1/gemini-web/onboard`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${cs.apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          profile, email: draft.email.trim(), password: draft.password, totp_secret: draft.totpSecret.trim(),
        }),
      });
      if (!res.ok) throw new Error(`onboard HTTP ${res.status}`);
      const initial = await res.json();
      setSession(initial);
      const noVncUrl = `${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`;
      window.open(noVncUrl, "_blank", "noopener,width=1024,height=720");
      if (initial.state === "success" || initial.state === "failed") {
        void pollStatus();
      } else {
        pollRef.current = window.setInterval(() => void pollStatus(), 1500);
      }
    } catch (e: any) {
      toast.error(`Onboard error: ${e?.message}`);
      setRunning(false);
    }
  }

  function openNoVNC() {
    window.open(`${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`, "_blank");
  }

  async function handleSaveAccount() {
    if (!draft.email.trim() || !draft.password) {
      toast.error("Cần email + mật khẩu để lưu");
      return;
    }
    setIsSavingAccount(true);
    try {
      await fetch(`${cs.url}/v1/accounts/saved`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ email: draft.email.trim(), password: draft.password, totp_secret: draft.totpSecret.trim() }),
      });
      toast.success("Đã lưu tài khoản");
      setDraft({ email: "", password: "", totpSecret: "" });
      setSelectedAccount("");
      setSavedRefreshKey((k) => k + 1);
    } catch {
      toast.error("Lưu tài khoản thất bại");
    } finally {
      setIsSavingAccount(false);
    }
  }

  function cancelSession() {
    stopPolling();
    setSession(null);
    setRunning(false);
    setDraft({ email: "", password: "", totpSecret: "" });
    setSelectedAccount("");
  }

  return (
    <Card className="rounded-3xl border-violet-100/80 bg-violet-50/30">
      <CardContent className="space-y-4 p-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-violet-600" />
              <h3 className="text-sm font-semibold text-violet-900">Gemini Web (gemini.google.com)</h3>
            </div>
            <p className="text-xs text-violet-700/70 mt-0.5">
              DOM scrape gemini.google.com (chat / image / vision). Bypass VN geo-block của Gemini API.
              Endpoint OpenAI-compat: <code className="font-mono text-[10px]">model=gmw/chat</code>,{" "}
              <code className="font-mono text-[10px]">gmw/image</code>,{" "}
              <code className="font-mono text-[10px]">gmw/vision</code>.
            </p>
          </div>
        </div>

        <div className="space-y-2 rounded-xl border border-violet-200 bg-[var(--card)]/80 p-3">
          <p className="text-xs font-bold text-violet-800">Cấu hình provider</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Profile (captcha-solver user-data-dir)</label>
              <Input
                value={profile} onChange={(e) => setProfile(e.target.value)}
                placeholder="gemini-web-default"
                className="mt-1 h-8 rounded-lg border-violet-200 text-xs font-mono"
              />
            </div>
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Timeout (giây)</label>
              <Input
                type="number" min={30} max={600}
                value={timeout}
                onChange={(e) => setTimeoutVal(Number(e.target.value))}
                className="mt-1 h-8 rounded-lg border-violet-200 text-xs font-mono"
              />
            </div>
          </div>
          <Button
            className="h-8 rounded-lg bg-violet-600 px-3 text-xs text-white hover:bg-violet-700"
            onClick={saveProviderCfg} disabled={savingCfg}
          >
            {savingCfg ? <LoaderCircle className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
            {" "}Lưu config
          </Button>
        </div>

        <div className="space-y-1 rounded-xl border border-emerald-200 bg-emerald-50/50 p-3">
          <p className="text-xs font-bold text-emerald-800">Tái dùng profile đã onboard</p>
          <p className="text-[10px] text-emerald-700/70 leading-relaxed">
            Chọn profile Google đã có session (qua Flow/ChatGPT/Gemini) → dùng cho Gemini Web, không cần đăng nhập lại.
          </p>
          <ReuseProfilePicker cs={cs} onReuse={reuseOnboard} />
        </div>

        <div className="space-y-2 rounded-xl border-2 border-violet-300 bg-gradient-to-br from-violet-50/60 to-fuchsia-50/60 p-3">
          <p className="text-xs font-bold text-violet-800">1-click onboard (Google OAuth)</p>
          <p className="text-[10px] text-violet-700/70 leading-relaxed">
            Nếu profile đã login Google (qua Flow/ChatGPT onboard), short-circuit success ngay.
            Nếu chưa, mở Playwright + login chuẩn — theo dõi qua noVNC khi cần thao tác manual.
          </p>
          <SavedAccountsSelect
            csUrl={cs.url}
            csApiKey={cs.apiKey}
            selected={selectedAccount}
            onSelect={(email, acct) => {
              setSelectedAccount(email);
              setDraft({ email: acct.email, password: acct.password, totpSecret: acct.totp_secret || "" });
            }}
            disabled={running}
            refreshKey={savedRefreshKey}
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Email Google</label>
              <Input
                value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })}
                placeholder="you@gmail.com"
                className="mt-1 h-8 rounded-lg border-violet-200 text-xs font-mono"
                autoComplete="off" disabled={running}
              />
            </div>
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Mật khẩu Google</label>
              <Input
                type="password" value={draft.password}
                onChange={(e) => setDraft({ ...draft, password: e.target.value })}
                placeholder="••••••••"
                className="mt-1 h-8 rounded-lg border-violet-200 text-xs font-mono"
                autoComplete="off" disabled={running}
              />
            </div>
          </div>
          <div>
            <label className="text-[11px] text-[var(--muted-foreground)] flex items-center gap-1">
              <Shield className="size-3" /> TOTP Secret
            </label>
            <Input
              value={draft.totpSecret}
              onChange={(e) => setDraft({ ...draft, totpSecret: e.target.value })}
              placeholder="xxxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx"
              className="mt-1 h-8 rounded-lg border-amber-200 text-xs font-mono bg-amber-50/30"
              autoComplete="off" disabled={running}
            />
            {totpCode && (
              <div className="mt-1 flex items-center gap-2">
                <span className="text-[11px] text-amber-700">Ma hien tai:</span>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-mono text-sm font-bold tracking-widest">
                  {totpCode}
                </span>
                <span className="text-[10px] text-amber-500">({totpRemaining}s)</span>
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 rounded-lg text-[11px]"
              onClick={handleSaveAccount}
              disabled={isSavingAccount || !draft.email.trim() || !draft.password}
            >
              {isSavingAccount ? <LoaderCircle className="mr-1 size-3 animate-spin" /> : null}
              Lưu tài khoản
            </Button>
            <Button
              className="h-9 rounded-lg bg-gradient-to-r from-violet-600 to-fuchsia-600 px-3 text-xs font-bold text-white hover:from-violet-700 hover:to-fuchsia-700 shadow-lg shadow-violet-200"
              onClick={onboard} disabled={running}
            >
              {running ? <><LoaderCircle className="size-3.5 animate-spin" /> Đang chạy…</>
                : <><Sparkles className="size-3.5" /> Onboard</>}
            </Button>
            <Button
              className="h-9 rounded-lg border border-violet-200 bg-[var(--card)] px-3 text-xs text-violet-700 hover:bg-violet-50"
              onClick={openNoVNC}
            >
              <ExternalLink className="size-3.5" /> Mở noVNC
            </Button>
            {session && session.state !== "none" && (
              <Button
                className="h-9 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                onClick={cancelSession}
              >
                <X className="size-3.5" /> Đóng
              </Button>
            )}
          </div>

          {session && session.state !== "none" && (
            <div className={`mt-2 rounded-lg border p-2 text-xs space-y-1 ${
              session.state === "success" ? "border-emerald-300 bg-emerald-50/70"
              : session.state === "failed" ? "border-rose-300 bg-rose-50/70"
              : "border-violet-200 bg-[var(--card)]/80"
            }`}>
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${
                  session.state === "success" ? "bg-emerald-100 text-emerald-700"
                  : session.state === "failed" ? "bg-rose-100 text-rose-700"
                  : "bg-violet-100 text-violet-700"
                }`}>
                  {(session.state === "running" || session.state === "starting") && (
                    <LoaderCircle className="size-3 animate-spin" />
                  )}
                  {session.state}
                </span>
                <span className="text-[var(--muted-foreground)]">{session.message}</span>
                {typeof session.elapsed_sec === "number" && (
                  <span className="ml-auto text-[10px] text-[var(--muted-foreground)] font-mono">{session.elapsed_sec}s</span>
                )}
              </div>
              {session.state === "failed" && session.error && (
                <p className="text-rose-700 text-[11px]">{session.error}</p>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
