"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { LoaderCircle, KeyRound, Sparkles, Smartphone, X, ExternalLink, Shield, Eye, EyeOff, RefreshCw } from "lucide-react";
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
  email: string;
  state: "none" | "starting" | "running" | "need_tap" | "need_code" | "success" | "failed";
  message: string;
  tap_number?: string | null;
  elapsed_sec?: number;
  error?: string | null;
  access_token?: string | null;
  expires?: string | null;
  captured_email?: string | null;
  access_token_preview?: string | null;
};

type CaptchaSolverCfg = {
  url: string;
  apiKey: string;
};

export function ChatGPTOnboardCard() {
  // Reuse the same captcha-solver creds the Flow card stores under
  // providers.flow — admins shouldn't have to enter them twice.
  const [cs, setCs] = useState<CaptchaSolverCfg>({
    url: "/api/captcha",
    apiKey: "",
  });
  const [draft, setDraft] = useState({ email: "", password: "", code: "", totpSecret: "" });
  const [running, setRunning] = useState(false);
  const [session, setSession] = useState<OnboardState | null>(null);
  const pollRef = useRef<number | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [totpRemaining, setTotpRemaining] = useState(30);
  const totpTimerRef = useRef<number | null>(null);
  const [selectedAccount, setSelectedAccount] = useState("");
  const [showPassword, setShowPassword] = useState(true);
  const [isSavingAccount, setIsSavingAccount] = useState(false);
  const [savedRefreshKey, setSavedRefreshKey] = useState(0);

  async function refreshNow() {
    if (!draft.email.trim()) {
      toast.error("Chọn tài khoản trước");
      return;
    }
    const profile = profileSuggestion();
    toast.info(`Đang refresh token cho ${profile}...`);
    try {
      const res = await fetch(`${cs.url}/v1/chatgpt/${encodeURIComponent(profile)}/refresh-jwt`, {
        headers: { Authorization: `Bearer ${cs.apiKey}` },
      });
      const data = await res.json();
      if (data.ok) {
        toast.success(`Refresh OK (${data.method}): ${data.access_token_preview}`);
      } else {
        toast.error(`Refresh fail: ${data.error}`);
      }
    } catch { toast.error("Lỗi gọi refresh"); }
  }

  // Auto-refresh TOTP code when secret is provided
  const refreshTotp = useCallback(async (secret: string) => {
    if (!secret.trim()) { setTotpCode(""); return; }
    try {
      const code = await generateTotpCode(secret);
      setTotpCode(code);
      setTotpRemaining(totpSecondsRemaining());
    } catch { setTotpCode(""); }
  }, []);

  // Keep TOTP code live
  useEffect(() => {
    if (!draft.totpSecret.trim()) { setTotpCode(""); return; }
    void refreshTotp(draft.totpSecret);
    totpTimerRef.current = window.setInterval(() => {
      void refreshTotp(draft.totpSecret);
    }, 5000);
    return () => {
      if (totpTimerRef.current) window.clearInterval(totpTimerRef.current);
    };
  }, [draft.totpSecret, refreshTotp]);

  useEffect(() => {
    void fetchCfg();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  async function fetchCfg() {
    try {
      const data = await request.get("/api/settings");
      const provs = ((data.data as any)?.config?.providers || {});
      const flow = provs.flow || {};
      const cgFree = provs.chatgpt_free || {};
      setCs({
        url: "/api/captcha",
        apiKey: cgFree.captcha_solver_api_key || flow.captcha_solver_api_key || "",
      });
    } catch (e) {
      console.error(e);
    }
  }

  function stopPolling() {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function profileSuggestion() {
    // Account-centric profile name (provider-neutral) so the SAME Google
    // account reuses ONE browser profile across ChatGPT / Gemini Web / Flow.
    // (Was "chatgpt-<local>" which made cross-provider reuse carry a
    // provider-specific name.)
    const local = (draft.email.split("@")[0] || "default").replace(/[^a-z0-9-]/gi, "-");
    return `google-${local}`;
  }

  async function pollOnboardStatus(profile: string, onSuccess: (s: OnboardState) => void) {
    try {
      const res = await fetch(`${cs.url}/v1/chatgpt/${encodeURIComponent(profile)}/onboard-status`, {
        headers: { Authorization: `Bearer ${cs.apiKey}` },
      });
      if (!res.ok) return;
      const data: OnboardState = await res.json();
      setSession(data);
      if (data.state === "success" || data.state === "failed") {
        stopPolling();
        if (data.state === "success") {
          toast.success(`Login ChatGPT OK (${data.captured_email})`);
          onSuccess(data);
        } else {
          toast.error(`Login fail: ${data.error || data.message}`);
          setRunning(false);
        }
      }
    } catch {
      /* network blip — keep polling */
    }
  }

  async function onboardAndAddToPool() {
    if (!draft.email.trim() || !draft.password) {
      toast.error("Cần email + mật khẩu Google");
      return;
    }
    const profile = profileSuggestion();
    stopPolling();
    setRunning(true);
    setSession(null);
    try {
      // 1) Start captcha-solver onboard
      const res = await fetch(`${cs.url}/v1/chatgpt/onboard`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${cs.apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          profile,
          email: draft.email.trim(),
          password: draft.password,
          totp_secret: draft.totpSecret.trim(),
        }),
      });
      if (!res.ok) throw new Error(`onboard HTTP ${res.status}`);
      const initial = await res.json();
      setSession(initial);
      // Open noVNC so user can monitor / handle anti-bot challenges
      const noVncUrl = `${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`;
      window.open(noVncUrl, "_blank", "noopener,width=1024,height=720");

      // 2) Poll for success
      const handleSuccess = async (s: OnboardState) => {
        if (!s.access_token) {
          toast.error("Login OK nhưng không có access_token");
          setRunning(false);
          return;
        }
        // 3) POST token to chatgpt2api accounts pool
        try {
          const label = s.captured_email || profile;
          await request.post("/api/accounts", { tokens: [s.access_token] });
          // Tag the account with the Google login email so it's identifiable
          try {
            await request.post("/api/accounts/update", {
              access_token: s.access_token,
              type: `free,${label?.split("@")[0] || profile}`,
            });
          } catch { /* tag update is best-effort */ }
          toast.success(`Đã thêm account ${label} vào pool`);
          setDraft({ email: "", password: "", code: "", totpSecret: "" });
        } catch (e: any) {
          toast.error(`Add to pool fail: ${e?.message || e}`);
        } finally {
          setRunning(false);
        }
      };
      if (initial.state === "success") {
        void handleSuccess(initial);
      } else if (initial.state === "failed") {
        toast.error(`Onboard fail: ${initial.error || initial.message}`);
        setRunning(false);
      } else {
        pollRef.current = window.setInterval(() => {
          void pollOnboardStatus(profile, handleSuccess);
        }, 1500);
      }
    } catch (e: any) {
      toast.error(`Onboard error: ${e?.message}`);
      setRunning(false);
    }
  }

  // Cách A — reuse an existing profile's Google session (no email/password).
  // Used when the account was already onboarded via Flow / Gemini Web first.
  async function reuseOnboard(profile: string) {
    stopPolling();
    setRunning(true);
    setSession(null);
    try {
      const res = await fetch(`${cs.url}/v1/chatgpt/onboard`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ profile, email: "", password: "", reuse_session: true }),
      });
      if (!res.ok) throw new Error(`reuse HTTP ${res.status}`);
      const initial = await res.json();
      setSession(initial);
      toast.info(`Đang tái dùng session của ${profile}…`);
      const handleSuccess = async (s: OnboardState) => {
        if (!s.access_token) {
          toast.error("Tái dùng OK nhưng không có access_token");
          setRunning(false);
          return;
        }
        try {
          const label = s.captured_email || profile;
          await request.post("/api/accounts", { tokens: [s.access_token] });
          try {
            await request.post("/api/accounts/update", {
              access_token: s.access_token,
              type: `free,${label?.split("@")[0] || profile}`,
            });
          } catch { /* tag best-effort */ }
          toast.success(`Đã thêm ${label} vào pool (tái dùng)`);
        } catch (e: any) {
          toast.error(`Add to pool fail: ${e?.message || e}`);
        } finally {
          setRunning(false);
        }
      };
      if (initial.state === "success") {
        void handleSuccess(initial);
      } else if (initial.state === "failed") {
        toast.error(`Reuse fail: ${initial.error || initial.message}`);
        setRunning(false);
      } else {
        pollRef.current = window.setInterval(() => {
          void pollOnboardStatus(profile, handleSuccess);
        }, 1500);
      }
    } catch (e: any) {
      toast.error(`Reuse error: ${e?.message}`);
      setRunning(false);
    }
  }

  // Auto-login ONLY — establish the Google session in the profile WITHOUT
  // adding any token to the pool. Prep a fresh account, then add providers
  // (ChatGPT/Gemini/Flow) via the "Tái dùng" buttons. 2FA: TOTP auto, else
  // approve on noVNC (device-tap).
  async function autoLoginOnly() {
    if (!draft.email.trim() || !draft.password) {
      toast.error("Cần email + mật khẩu Google");
      return;
    }
    const profile = profileSuggestion();
    stopPolling();
    setRunning(true);
    setSession(null);
    try {
      const res = await fetch(`${cs.url}/v1/session/auto-login`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          profile,
          email: draft.email.trim(),
          password: draft.password,
          totp_secret: draft.totpSecret.trim(),
          prefer_method: draft.totpSecret.trim() ? "auth" : "tap",
        }),
      });
      if (!res.ok) throw new Error(`auto-login HTTP ${res.status}`);
      const initial = await res.json();
      setSession({ ...initial, profile, email: draft.email.trim() });
      const noVncUrl = `${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`;
      window.open(noVncUrl, "_blank", "noopener,width=1024,height=720");
      toast.info(`Đang đăng nhập Google vào ${profile} (KHÔNG add pool)…`);
      if (initial.state === "success") {
        setRunning(false);
        toast.success(`Đăng nhập ${profile} xong — CHƯA add pool. Dùng nút "Tái dùng" để thêm ChatGPT/Gemini/Flow.`);
      } else if (initial.state === "failed") {
        setRunning(false);
        toast.error(`Login fail: ${initial.error || initial.message}`);
      } else {
        pollRef.current = window.setInterval(async () => {
          try {
            const r = await fetch(`${cs.url}/v1/session/${encodeURIComponent(profile)}/auto-login-status`, {
              headers: { Authorization: `Bearer ${cs.apiKey}` },
            });
            if (!r.ok) return;
            const data = await r.json();
            setSession({ ...data, profile, email: draft.email.trim() });
            if (data.state === "success") {
              stopPolling();
              setRunning(false);
              toast.success(`Đăng nhập ${profile} xong — CHƯA add pool. Dùng nút "Tái dùng" để thêm ChatGPT/Gemini/Flow.`);
            } else if (data.state === "failed") {
              stopPolling();
              setRunning(false);
              toast.error(`Login fail: ${data.error || data.message}`);
            }
          } catch { /* ignore */ }
        }, 1500);
      }
    } catch (e: any) {
      toast.error(`Auto-login error: ${e?.message}`);
      setRunning(false);
    }
  }

  async function submit2faCode() {
    if (!session?.profile || !draft.code.trim()) {
      toast.error("Cần mã 2FA");
      return;
    }
    try {
      const res = await fetch(
        `${cs.url}/v1/chatgpt/${encodeURIComponent(session.profile)}/onboard-2fa-code`,
        {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${cs.apiKey}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ code: draft.code.trim() }),
        },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      toast.success("Đã gửi mã, đợi xác minh…");
      setDraft({ ...draft, code: "" });
    } catch (e: any) {
      toast.error(`Lỗi gửi mã: ${e?.message}`);
    }
  }

  function cancelSession() {
    stopPolling();
    setSession(null);
    setRunning(false);
    setDraft({ email: "", password: "", code: "", totpSecret: "" });
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
      setDraft({ email: "", password: "", code: "", totpSecret: "" });
      setSelectedAccount("");
      setSavedRefreshKey((k) => k + 1);
    } catch {
      toast.error("Lưu tài khoản thất bại");
    } finally {
      setIsSavingAccount(false);
    }
  }

  function openNoVNC() {
    const noVncUrl = `${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`;
    window.open(noVncUrl, "_blank");
  }

  return (
    <Card className="rounded-3xl border-blue-100/80 bg-blue-50/30">
      <CardContent className="space-y-4 p-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-blue-600" />
              <h3 className="text-sm font-semibold text-blue-900">ChatGPT via Google OAuth</h3>
            </div>
            <p className="text-xs text-blue-700/70 mt-0.5">
              Tự động login chat.openai.com bằng tài khoản Google → scrape JWT access_token → add vào pool ChatGPT free.
              Bypass hoàn toàn 24KB session-token limit.
            </p>
          </div>
        </div>

        {/* 1-click form */}
        <div className="space-y-2 rounded-xl border-2 border-blue-300 bg-gradient-to-br from-blue-50/60 to-cyan-50/60 p-3">
          <p className="text-xs font-bold text-blue-800 flex items-center gap-1.5">
            <KeyRound className="size-3.5" /> 1-click thêm ChatGPT free (qua Google)
          </p>
          <p className="text-[10px] text-blue-700/70 leading-relaxed">
            Nhập email + mật khẩu Google. Backend Playwright tự click "Continue with Google" trên chat.openai.com,
            login qua trang Google (cùng flow như Flow), redirect về chatgpt.com, scrape JWT, save vào pool.
            Khi gặp 2FA, dùng panel xanh chàm bên dưới.
          </p>

          {/* Saved accounts dropdown */}
          <SavedAccountsSelect
            csUrl={cs.url}
            csApiKey={cs.apiKey}
            selected={selectedAccount}
            onSelect={(email, acct) => {
              setSelectedAccount(email);
              setDraft({ email: acct.email, password: acct.password, code: "", totpSecret: acct.totp_secret || "" });
            }}
            disabled={running}
            refreshKey={savedRefreshKey}
          />

          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Email Google</label>
              <Input
                value={draft.email}
                onChange={(e) => setDraft({ ...draft, email: e.target.value })}
                placeholder="you@gmail.com"
                className="mt-1 h-8 rounded-lg border-blue-200 text-xs font-mono"
                autoComplete="off"
                disabled={running}
              />
            </div>
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Mật khẩu Google</label>
              <div className="relative">
                <Input
                  type={showPassword ? "text" : "password"}
                  value={draft.password}
                  onChange={(e) => setDraft({ ...draft, password: e.target.value })}
                  placeholder="••••••••"
                  className="mt-1 h-8 rounded-lg border-blue-200 text-xs font-mono pr-8"
                  autoComplete="off"
                  disabled={running}
                />
                <button
                  type="button"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)] hover:text-[var(--muted-foreground)]"
                  onClick={() => setShowPassword(!showPassword)}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                </button>
              </div>
            </div>
          </div>
          <div>
            <label className="text-[11px] text-[var(--muted-foreground)] flex items-center gap-1">
              <Shield className="size-3" /> TOTP Secret — để TRỐNG = xác minh qua thiết bị (tap điện thoại); điền secret = Authenticator tự sinh mã
            </label>
            <Input
              value={draft.totpSecret}
              onChange={(e) => setDraft({ ...draft, totpSecret: e.target.value })}
              placeholder="xxxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx"
              className="mt-1 h-8 rounded-lg border-blue-200 text-xs font-mono"
              autoComplete="off"
              disabled={running}
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
          <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-2 space-y-1">
            <p className="text-[11px] font-medium text-emerald-700">
              Tái dùng profile đã onboard (Flow/Gemini/ChatGPT) — không cần nhập lại email/mật khẩu:
            </p>
            <ReuseProfilePicker cs={cs} onReuse={reuseOnboard} />
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
              className="h-9 rounded-lg bg-gradient-to-r from-blue-600 to-cyan-600 px-3 text-xs font-bold text-white hover:from-blue-700 hover:to-cyan-700 shadow-lg shadow-blue-200"
              onClick={onboardAndAddToPool}
              disabled={running}
            >
              {running
                ? <><LoaderCircle className="size-3.5 animate-spin" /> Đang chạy…</>
                : <><Sparkles className="size-3.5" /> Tự động setup (1-click)</>}
            </Button>
            <Button
              className="h-9 rounded-lg border border-amber-300 bg-amber-50 px-3 text-xs font-semibold text-amber-800 hover:bg-amber-100"
              onClick={autoLoginOnly}
              disabled={running || !draft.email.trim() || !draft.password}
              title="Chỉ đăng nhập Google vào profile, KHÔNG add vào pool. Sau đó dùng nút Tái dùng để thêm provider."
            >
              <KeyRound className="size-3.5" /> Chỉ đăng nhập
            </Button>
            <Button
              className="h-9 rounded-lg border border-blue-200 bg-[var(--card)] px-3 text-xs text-blue-700 hover:bg-blue-50"
              onClick={openNoVNC}
            >
              <ExternalLink className="size-3.5" /> Mở noVNC
            </Button>
            <Button
              className="h-9 rounded-lg border border-purple-200 bg-[var(--card)] px-3 text-xs text-purple-700 hover:bg-purple-50"
              onClick={refreshNow}
              disabled={running || !draft.email.trim()}
            >
              <RefreshCw className="size-3.5" /> Refresh ngay
            </Button>
            {session && session.state !== "none" && (
              <Button
                className="h-9 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                onClick={cancelSession}
              >
                <X className="size-3.5" /> Đóng phiên
              </Button>
            )}
          </div>

          {/* Status panel */}
          {session && session.state !== "none" && (
            <div className={`mt-2 rounded-lg border p-3 text-xs space-y-2 ${
              session.state === "success" ? "border-emerald-300 bg-emerald-50/70"
              : session.state === "failed" ? "border-rose-300 bg-rose-50/70"
              : session.state === "need_tap" ? "border-violet-300 bg-violet-50/70"
              : session.state === "need_code" ? "border-amber-300 bg-amber-50/70"
              : "border-blue-200 bg-[var(--card)]/80"
            }`}>
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${
                  session.state === "success" ? "bg-emerald-100 text-emerald-700"
                  : session.state === "failed" ? "bg-rose-100 text-rose-700"
                  : session.state === "need_tap" ? "bg-violet-100 text-violet-700"
                  : session.state === "need_code" ? "bg-amber-100 text-amber-700"
                  : "bg-blue-100 text-blue-700"
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

              {session.state === "need_tap" && (
                <div className="flex items-center gap-2 rounded-md bg-violet-100/60 px-2 py-1.5">
                  <Smartphone className="size-4 text-violet-700" />
                  <span className="text-violet-900">
                    Mở app Gmail/Google trên điện thoại
                    {session.tap_number ? (
                      <> và bấm số <b className="text-base font-mono">{session.tap_number}</b></>
                    ) : (
                      <> và bấm "Có" để xác minh</>
                    )}
                  </span>
                </div>
              )}

              {session.state === "need_code" && (
                <div className="space-y-2">
                  {/* Auto-generated TOTP code when secret is available */}
                  {totpCode && (
                    <div className="flex items-center gap-2 rounded-md bg-amber-100/70 px-2 py-1.5">
                      <Shield className="size-4 text-amber-700" />
                      <span className="text-amber-800 text-[11px]">Ma tu sinh tu TOTP secret:</span>
                      <span className="text-amber-900 font-mono text-lg font-bold tracking-widest">
                        {totpCode}
                      </span>
                      <span className="text-[10px] text-amber-500 ml-auto">({totpRemaining}s)</span>
                    </div>
                  )}
                  {/* Manual fallback input */}
                  <div className="flex items-end gap-2">
                    <div className="flex-1">
                      <label className="text-[11px] text-amber-800">
                        {totpCode ? "Hoac nhap thu cong:" : "Ma 2FA (SMS hoac Authenticator)"}
                      </label>
                      <Input
                        value={draft.code}
                        onChange={(e) => setDraft({ ...draft, code: e.target.value })}
                        placeholder="123456"
                        className="mt-1 h-8 rounded-lg border-amber-200 text-xs font-mono"
                        autoComplete="off"
                        onKeyDown={(e) => { if (e.key === "Enter") void submit2faCode(); }}
                      />
                    </div>
                    <Button
                      className="h-8 rounded-lg bg-amber-600 px-3 text-xs text-white hover:bg-amber-700"
                      onClick={submit2faCode}
                    >
                      Gửi mã
                    </Button>
                  </div>
                </div>
              )}

              {session.state === "success" && session.access_token_preview && (
                <div className="text-emerald-700 text-[11px] font-mono break-all">
                  ✓ Token captured: {session.access_token_preview}
                  <div className="text-[10px] text-emerald-600 mt-0.5">Đã add vào pool. Email: {session.captured_email}</div>
                </div>
              )}

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
