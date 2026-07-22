"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { LoaderCircle, KeyRound, Bot, Smartphone, X, ExternalLink, Shield, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { SavedAccountsSelect } from "@/components/saved-accounts-select";
import { generateTotpCode, totpSecondsRemaining } from "@/lib/totp";
import { TotpSecretGuide, TotpSecretLabel } from "@/components/google-security-hints";
import { ReuseProfilePicker } from "./reuse-profile-picker";

type OnboardState = {
  profile: string;
  email?: string;
  state: "none" | "starting" | "running" | "need_tap" | "need_code" | "success" | "failed";
  message: string;
  tap_number?: string | null;
  elapsed_sec?: number;
  error?: string | null;
  session_key?: string | null;
  session_key_preview?: string | null;
  has_session_key?: boolean;
};

type CaptchaSolverCfg = { url: string; apiKey: string };

export function ClaudeCard() {
  // Reuse the same captcha-solver creds the Flow card stores under providers.flow.
  const [cs, setCs] = useState<CaptchaSolverCfg>({ url: "/api/captcha", apiKey: "" });
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

  const refreshTotp = useCallback(async (secret: string) => {
    if (!secret.trim()) { setTotpCode(""); return; }
    try {
      setTotpCode(await generateTotpCode(secret));
      setTotpRemaining(totpSecondsRemaining());
    } catch { setTotpCode(""); }
  }, []);

  useEffect(() => {
    if (!draft.totpSecret.trim()) { setTotpCode(""); return; }
    void refreshTotp(draft.totpSecret);
    totpTimerRef.current = window.setInterval(() => { void refreshTotp(draft.totpSecret); }, 5000);
    return () => { if (totpTimerRef.current) window.clearInterval(totpTimerRef.current); };
  }, [draft.totpSecret, refreshTotp]);

  useEffect(() => {
    void fetchCfg();
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, []);

  async function fetchCfg() {
    try {
      const data = await request.get("/api/settings");
      const provs = ((data.data as any)?.config?.providers || {});
      const flow = provs.flow || {};
      const claude = provs.claude || {};
      setCs({
        url: "/api/captcha",
        apiKey: claude.captcha_solver_api_key || flow.captcha_solver_api_key || "",
      });
    } catch (e) {
      console.error(e);
    }
  }

  function stopPolling() {
    if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
  }

  function profileSuggestion() {
    const local = (draft.email.split("@")[0] || "default").replace(/[^a-z0-9-]/gi, "-");
    return `google-${local}`;
  }

  // Save the scraped sessionKey into providers.claude so api/claude.py can read it.
  async function persistClaudeConfig(prof: string) {
    const cur = await request.get("/api/settings");
    const config = (cur.data as any)?.config || {};
    config.providers = config.providers || {};
    const currentProfiles = Array.isArray(config.providers.claude?.profiles) 
      ? config.providers.claude.profiles 
      : (config.providers.claude?.profile ? [config.providers.claude.profile] : []);
    if (!currentProfiles.includes(prof)) {
      currentProfiles.push(prof);
    }

    config.providers.claude = {
      ...(config.providers.claude || {}),
      enabled: true,
      captcha_solver_url: cs.url,
      captcha_solver_api_key: cs.apiKey,
      profiles: currentProfiles,
      model: config.providers.claude?.model || "auto",
    };
    await request.post("/api/settings", { providers: config.providers });
  }

  async function pollOnboardStatus(profile: string, onSuccess: (s: OnboardState) => void, onFail?: (s: OnboardState) => void) {
    try {
      const res = await fetch(`${cs.url}/v1/claude-web/${encodeURIComponent(profile)}/onboard-status`, {
        headers: { Authorization: `Bearer ${cs.apiKey}` },
      });
      if (!res.ok) return;
      const data: OnboardState = await res.json();
      setSession(data);
      if (data.state === "success" || data.state === "failed") {
        stopPolling();
        if (data.state === "success") {
          toast.success(`Login Claude OK${data.session_key_preview ? ` (${data.session_key_preview})` : ""}`);
          onSuccess(data);
        } else {
          if (onFail) {
            onFail(data);
          } else {
            toast.error(`Login fail: ${data.error || data.message}`);
            setRunning(false);
          }
        }
      }
    } catch {
      /* network blip — keep polling */
    }
  }

  async function autoRecoverGoogleThenReuse(profile: string) {
    toast.info(`Claude tái dùng thất bại. Tự động Đăng nhập lại Google cho ${profile}...`);
    try {
      const r = await fetch(`${cs.url}/v1/session/auto-login-saved`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ profile }),
      });
      if (!r.ok) {
        toast.error(`Khởi tạo đăng nhập Google thất bại (HTTP ${r.status})`);
        setRunning(false);
        return;
      }
      const initData = await r.json();
      setSession(initData);
      
      // Mở noVNC để user giải captcha/BotGuard nếu cần (giống "Chỉ đăng nhập")
      const vncWin = window.open(`${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`, "_blank", "noopener,width=1024,height=720");
      
      const pollId = window.setInterval(async () => {
        try {
          const r2 = await fetch(`${cs.url}/v1/session/${encodeURIComponent(profile)}/auto-login-status`, { 
            headers: { Authorization: `Bearer ${cs.apiKey}` } 
          });
          if (!r2.ok) return;
          const st2 = await r2.json();
          // Trick TypeScript by casting to any or just setting partial state
          setSession({ ...st2, message: `[Auto-Login Google] ${st2.message || ""}` } as any);
          
          if (st2.state === "success" || st2.state === "failed") {
            window.clearInterval(pollId);
            if (st2.state === "success") {
              if (vncWin) vncWin.close(); // Đóng captcha/noVNC
              toast.success(`Đăng nhập Google thành công. Tự động tái dùng lại Claude...`);
              setTimeout(() => { void reuseOnboard(profile, true); }, 1500);
            } else {
              toast.error(`Auto-login Google thất bại: ${st2.error || st2.message}`);
              setRunning(false);
            }
          }
        } catch {}
      }, 1500);
      pollRef.current = pollId;
    } catch (e: any) {
      toast.error(`Lỗi gọi auto-login: ${e?.message}`);
      setRunning(false);
    }
  }


  // 1-click: Google login (Playwright) on claude.ai → scrape sessionKey → save config.
  async function onboardAndSave() {
    if (!draft.email.trim() || !draft.password) { toast.error("Cần email + mật khẩu Google"); return; }
    const profile = profileSuggestion();
    stopPolling();
    setRunning(true);
    setSession(null);
    try {
      const res = await fetch(`${cs.url}/v1/claude-web/onboard`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ profile, email: draft.email.trim(), password: draft.password, totp_secret: draft.totpSecret.trim() }),
      });
      if (!res.ok) throw new Error(`onboard HTTP ${res.status}`);
      const initData = await res.json();
      setSession(initData);
      window.open(`${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`, "_blank", "noopener,width=1024,height=720");
      const handleSuccess = async () => {
        try {
          await persistClaudeConfig(profile);
          toast.success(`Claude sẵn sàng — đã lưu sessionKey vào config (${profile}) ✓`);
          setDraft({ email: "", password: "", code: "", totpSecret: "" });
        } catch (e: any) {
          toast.error(`Lưu config fail: ${e?.message || e}`);
        } finally {
          setRunning(false);
        }
      };
      if (initData.state === "success") {
        void handleSuccess();
      } else if (initData.state === "failed") {
        toast.error(`Onboard fail: ${initData.error || initData.message}`);
        setRunning(false);
      } else {
        pollRef.current = window.setInterval(() => { void pollOnboardStatus(profile, handleSuccess); }, 1500);
      }
    } catch (e: any) {
      toast.error(`Onboard error: ${e?.message}`);
      setRunning(false);
    }
  }

  // Reuse an existing profile's Google session (no email/password).
  async function reuseOnboard(profile: string, isAutoRecovered: boolean = false) {
    stopPolling();
    setRunning(true);
    setSession(null);
    try {
      const res = await fetch(`${cs.url}/v1/claude-web/onboard`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ profile }),
      });
      if (!res.ok) throw new Error(`reuse HTTP ${res.status}`);
      const initData = await res.json();
      setSession(initData);
      toast.info(`Đang tái dùng session của ${profile}…`);
      
      const handleSuccess = async () => {
        try {
          await persistClaudeConfig(profile);
          toast.success(`Đã lưu Claude config (tái dùng ${profile}) ✓`);
        } catch (e: any) {
          toast.error(`Lưu config fail: ${e?.message || e}`);
        } finally {
          setRunning(false);
        }
      };

      const handleFail = (data: any) => {
        if (!isAutoRecovered) {
          void autoRecoverGoogleThenReuse(profile);
        } else {
          toast.error(`Reuse fail (sau khi recover): ${data.error || data.message}`);
          setRunning(false);
        }
      };

      if (initData.state === "success") {
        void handleSuccess();
      } else if (initData.state === "failed") {
        handleFail(initData);
      } else {
        pollRef.current = window.setInterval(() => { void pollOnboardStatus(profile, handleSuccess, handleFail); }, 1500);
      }
    } catch (e: any) {
      toast.error(`Reuse error: ${e?.message}`);
      setRunning(false);
    }
  }

  async function submit2faCode() {
    if (!session?.profile || !draft.code.trim()) { toast.error("Cần mã 2FA"); return; }
    try {
      const res = await fetch(`${cs.url}/v1/claude-web/${encodeURIComponent(session.profile)}/onboard-2fa-code`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ code: draft.code.trim() }),
      });
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
    if (!draft.email.trim() || !draft.password) { toast.error("Cần email + mật khẩu để lưu"); return; }
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
    window.open(`${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`, "_blank");
  }

  return (
    <Card className="rounded-3xl border-orange-100/80 bg-orange-50/30">
      <CardContent className="space-y-4 p-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Bot className="size-4 text-orange-600" />
              <h3 className="text-sm font-semibold text-orange-900">Claude via Google OAuth</h3>
            </div>
            <p className="text-xs text-orange-700/70 mt-0.5">
              Tự động login claude.ai bằng tài khoản Google → scrape cookie sessionKey → lưu config Claude.
              Chat qua model <code className="font-mono text-[10px]">claude/auto</code>.
            </p>
          </div>
        </div>

        <div className="space-y-2 rounded-xl border-2 border-orange-300 bg-gradient-to-br from-orange-50/60 to-amber-50/60 p-3">
          <p className="text-xs font-bold text-orange-800 flex items-center gap-1.5">
            <KeyRound className="size-3.5" /> 1-click thêm Claude free (qua Google)
          </p>
          <p className="text-[10px] text-orange-700/70 leading-relaxed">
            Nhập email + mật khẩu Google. Backend Playwright tự click "Continue with Google" trên claude.ai,
            login qua trang Google, redirect về claude.ai, scrape sessionKey, lưu config. 2FA dùng panel bên dưới.
          </p>

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
                className="mt-1 h-8 rounded-lg border-orange-200 text-xs font-mono"
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
                  className="mt-1 h-8 rounded-lg border-orange-200 text-xs font-mono pr-8"
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
            <TotpSecretLabel />
            <Input
              value={draft.totpSecret}
              onChange={(e) => setDraft({ ...draft, totpSecret: e.target.value })}
              placeholder="xxxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx"
              className="mt-1 h-8 w-full rounded-lg border-orange-200 text-xs font-mono"
              autoComplete="off"
              disabled={running}
            />
            {totpCode && (
              <div className="mt-1 flex items-center gap-2">
                <span className="text-[11px] text-amber-700">Mã hiện tại:</span>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-mono text-sm font-bold tracking-widest">
                  {totpCode}
                </span>
                <span className="text-[10px] text-amber-500">({totpRemaining}s)</span>
              </div>
            )}
            <TotpSecretGuide />
          </div>
          <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-2 space-y-1">
            <p className="text-[11px] font-medium text-emerald-700">
              Tái dùng profile đã onboard (Flow/Gemini/ChatGPT) — không cần nhập lại email/mật khẩu:
            </p>
            <ReuseProfilePicker cs={cs} onReuse={reuseOnboard} />
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              type="button" size="sm" variant="outline"
              className="h-7 rounded-lg text-[11px]"
              onClick={handleSaveAccount}
              disabled={isSavingAccount || !draft.email.trim() || !draft.password}
            >
              {isSavingAccount ? <LoaderCircle className="mr-1 size-3 animate-spin" /> : null}
              Lưu tài khoản
            </Button>
            <Button
              className="h-9 rounded-lg bg-gradient-to-r from-orange-600 to-amber-600 px-3 text-xs font-bold text-white hover:from-orange-700 hover:to-amber-700 shadow-lg shadow-orange-200"
              onClick={onboardAndSave}
              disabled={running}
            >
              {running ? <><LoaderCircle className="size-3.5 animate-spin" /> Đang chạy…</>
                : <><Bot className="size-3.5" /> Tự động setup (1-click)</>}
            </Button>
            <Button
              className="h-9 rounded-lg border border-orange-200 bg-[var(--card)] px-3 text-xs text-orange-700 hover:bg-orange-50"
              onClick={openNoVNC}
            >
              <ExternalLink className="size-3.5" /> Mở noVNC
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

          {session && session.state !== "none" && (
            <div className={`mt-2 rounded-lg border p-3 text-xs space-y-2 ${
              session.state === "success" ? "border-emerald-300 bg-emerald-50/70"
              : session.state === "failed" ? "border-rose-300 bg-rose-50/70"
              : session.state === "need_tap" ? "border-violet-300 bg-violet-50/70"
              : session.state === "need_code" ? "border-amber-300 bg-amber-50/70"
              : "border-orange-200 bg-[var(--card)]/80"
            }`}>
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${
                  session.state === "success" ? "bg-emerald-100 text-emerald-700"
                  : session.state === "failed" ? "bg-rose-100 text-rose-700"
                  : session.state === "need_tap" ? "bg-violet-100 text-violet-700"
                  : session.state === "need_code" ? "bg-amber-100 text-amber-700"
                  : "bg-orange-100 text-orange-700"
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
                    {session.tap_number ? (<> và bấm số <b className="text-base font-mono">{session.tap_number}</b></>)
                      : (<> và bấm "Có" để xác minh</>)}
                  </span>
                </div>
              )}

              {session.state === "need_code" && (
                <div className="space-y-2">
                  {totpCode && (
                    <div className="flex items-center gap-2 rounded-md bg-amber-100/70 px-2 py-1.5">
                      <Shield className="size-4 text-amber-700" />
                      <span className="text-amber-800 text-[11px]">Ma tu sinh tu TOTP secret:</span>
                      <span className="text-amber-900 font-mono text-lg font-bold tracking-widest">{totpCode}</span>
                      <span className="text-[10px] text-amber-500 ml-auto">({totpRemaining}s)</span>
                    </div>
                  )}
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

              {session.state === "success" && session.session_key_preview && (
                <div className="text-emerald-700 text-[11px] font-mono break-all">
                  ✓ sessionKey: {session.session_key_preview}
                  <div className="text-[10px] text-emerald-600 mt-0.5">Đã lưu vào providers.claude.</div>
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
