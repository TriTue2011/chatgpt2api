"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, Plus, Save, Trash2, ExternalLink, Sparkles, KeyRound, RotateCw, Smartphone, X, Shield, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { SavedAccountsSelect } from "@/components/saved-accounts-select";
import { ReuseProfilePicker } from "./reuse-profile-picker";
import { generateTotpCode, totpSecondsRemaining } from "@/lib/totp";
import { TotpSecretGuide, TotpSecretLabel } from "@/components/google-security-hints";

type FlowAccount = {
  profile: string;
  project_id: string;
  label?: string;
  remainingCredits?: number;
};

type AutoLoginState = {
  profile: string;
  email: string;
  state: "none" | "pending" | "starting" | "running" | "need_tap" | "need_code" | "success" | "failed";
  message: string;
  tap_number?: string | null;
  elapsed_sec?: number;
  error?: string | null;
};

type FlowConfig = {
  enabled: boolean;
  captcha_solver_url: string;
  captcha_solver_api_key: string;
  accounts: FlowAccount[];
  cooldown_seconds?: number;
};

const DEFAULT_BASE_PROFILE = "google-fx";
const EMPTY_ACCOUNT: FlowAccount = { profile: DEFAULT_BASE_PROFILE, project_id: "", label: "Main" };

/** Find the next unused suffix for a base profile name.
 *
 *   existing: ["google-fx"]                        â†’ "google-fx-1"
 *   existing: ["google-fx", "google-fx-1"]         â†’ "google-fx-2"
 *   existing: ["google-fx-1", "google-fx-3"]       â†’ "google-fx" (base free)
 *   existing: ["google-fx", "google-fx-1", "google-fx-2"] â†’ "google-fx-3"
 *   existing: []                                   â†’ "google-fx"
 */
function nextProfileName(existing: string[], base = DEFAULT_BASE_PROFILE): string {
  const set = new Set(existing);
  if (!set.has(base)) return base;
  for (let i = 1; i < 1000; i++) {
    const candidate = `${base}-${i}`;
    if (!set.has(candidate)) return candidate;
  }
  return `${base}-${Date.now()}`;
}

/** Suggest the next label that fits the FIFO fallback chain. Order:
 *  Main â†’ Backup â†’ Spare 1 â†’ Spare 2 â†’ Spare 3 â†’ Standby â†’ Spare 4 ...
 *  Skips labels already in use so two accounts never collide.
 */
function nextLabel(existing: string[]): string {
  const used = new Set(existing.map((s) => s.trim()).filter(Boolean));
  const preset = ["Main", "Backup", "Spare 1", "Spare 2", "Spare 3", "Standby"];
  for (const label of preset) {
    if (!used.has(label)) return label;
  }
  // Pool past the preset list â€” keep generating Spare N.
  for (let i = 4; i < 1000; i++) {
    const candidate = `Spare ${i}`;
    if (!used.has(candidate)) return candidate;
  }
  return `Account ${used.size + 1}`;
}

export function FlowCard() {
  const [cfg, setCfg] = useState<FlowConfig>({
    enabled: true,
    captcha_solver_url: "/api/captcha",
    captcha_solver_api_key: "",
    accounts: [],
    cooldown_seconds: 3600,
  });
  const [draft, setDraft] = useState<FlowAccount>({ ...EMPTY_ACCOUNT });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  // Track which fields the user has manually edited so we don't
  // overwrite custom entries when accounts change. Sticky once typed.
  const [manuallyEditedProfile, setManuallyEditedProfile] = useState(false);
  const [manuallyEditedLabel, setManuallyEditedLabel] = useState(false);

  // Auto-login state
  const [autoLogin, setAutoLogin] = useState<{ email: string; password: string; code: string; totpSecret: string }>({
    email: "",
    password: "",
    code: "",
    totpSecret: "",
  });
  const [selectedAccount, setSelectedAccount] = useState("");
  const [isSavingAccount, setIsSavingAccount] = useState(false);
  const [savedRefreshKey, setSavedRefreshKey] = useState(0);
  const [loginSession, setLoginSession] = useState<AutoLoginState | null>(null);
  const [totpCode, setTotpCode] = useState("");
  const [totpRemaining, setTotpRemaining] = useState(30);
  const pollIntervalRef = useRef<number | null>(null);
  const totpTimerRef = useRef<number | null>(null);
  const [showPassword, setShowPassword] = useState(true);

  // Auto-refresh TOTP code
  useEffect(() => {
    if (!autoLogin.totpSecret.trim()) { setTotpCode(""); return; }
    const refresh = async () => {
      try {
        setTotpCode(await generateTotpCode(autoLogin.totpSecret));
        setTotpRemaining(totpSecondsRemaining());
      } catch { setTotpCode(""); }
    };
    void refresh();
    totpTimerRef.current = window.setInterval(refresh, 5000);
    return () => { if (totpTimerRef.current) window.clearInterval(totpTimerRef.current); };
  }, [autoLogin.totpSecret]);

  useEffect(() => { fetchCfg(); }, []);

  // Cleanup poll on unmount
  useEffect(() => () => {
    if (pollIntervalRef.current) {
      window.clearInterval(pollIntervalRef.current);
    }
  }, []);

  // Suggested values based on what's already in the pool. Both
  // re-compute whenever cfg.accounts changes (after add/remove/save).
  const suggestedProfile = useMemo(
    () => nextProfileName(cfg.accounts.map((a) => a.profile)),
    [cfg.accounts]
  );
  const suggestedLabel = useMemo(
    () => nextLabel(cfg.accounts.map((a) => a.label || "")),
    [cfg.accounts]
  );

  // Auto-fill draft with the suggestion unless the user has typed their
  // own. Triggers on every account-list update.
  useEffect(() => {
    setDraft((d) => ({
      ...d,
      profile: manuallyEditedProfile ? d.profile : suggestedProfile,
      label:   manuallyEditedLabel   ? d.label   : suggestedLabel,
    }));
  }, [suggestedProfile, suggestedLabel, manuallyEditedProfile, manuallyEditedLabel]);

  async function fetchCfg() {
    setLoading(true);
    try {
      const data = await request.get("/api/settings");
      const flow = ((data.data as any)?.config?.providers || {}).flow || {};
      setCfg({
        enabled: flow.enabled !== false,
        captcha_solver_url: "/api/captcha",
        captcha_solver_api_key: flow.captcha_solver_api_key || "",
        accounts: Array.isArray(flow.accounts) ? flow.accounts : [],
        cooldown_seconds: typeof flow.cooldown_seconds === "number" ? flow.cooldown_seconds : 3600,
      });
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  async function save(next: FlowConfig) {
    setSaving(true);
    try {
      // /api/settings does a shallow merge at the top level â€” wrapping
      // the payload as `{ config: { providers: { flow: next } } }` would
      // create a literal `config` key in settings and leave `providers`
      // untouched (so deletes/edits silently no-op). Send `providers` at
      // the top level, and merge into the existing providers dict so we
      // don't wipe sibling providers (gemini_web, chatgpt_web, ...).
      const cur = await request.get("/api/settings");
      const providers = { ...(((cur.data as any)?.config?.providers) || {}) };
      providers.flow = next;
      await request.post("/api/settings", { providers });
      toast.success("ÄÃ£ lÆ°u cáº¥u hÃ¬nh Flow");
      setCfg(next);
    } catch (e: any) {
      toast.error(e?.message || "Lá»—i lÆ°u");
    } finally { setSaving(false); }
  }

  function addAccount() {
    if (!draft.profile.trim() || !draft.project_id.trim()) {
      toast.error("Profile + project_id lÃ  báº¯t buá»™c");
      return;
    }
    const next = { ...cfg, accounts: [...cfg.accounts, { ...draft, label: draft.label?.trim() || draft.profile }] };
    void save(next);
    // Reset draft and clear manual-edit flags so the useEffect re-suggests
    // the next available profile + label after the save completes.
    setDraft({ ...EMPTY_ACCOUNT });
    setManuallyEditedProfile(false);
    setManuallyEditedLabel(false);
  }

  function removeAccount(idx: number) {
    const next = { ...cfg, accounts: cfg.accounts.filter((_, i) => i !== idx) };
    void save(next);
  }

  // CÃ¡ch A â€” reuse an existing profile's Google session for Flow: fetch/create
  // a project on that profile (no login) and add it to the pool.
  async function reuseAccount(prof: string) {
    if (cfg.accounts.some((a) => a.profile === prof)) {
      toast.info(`${prof} Ä‘Ã£ cÃ³ trong pool`);
      return;
    }
    const url = cfg.captcha_solver_url;
    const key = cfg.captcha_solver_api_key;
    try {
      toast.info(`Äang láº¥y Flow project cho ${prof}â€¦`);
      const res = await fetch(`${url}/v1/google/flow/get-or-create-project`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ profile: prof, headless: true, timeout: 150 }),
      });
      if (!res.ok) throw new Error(`get-project HTTP ${res.status}`);
      const data = await res.json();
      const projectId = data.project_id;
      if (!projectId) throw new Error(data.detail || data.error || "no project_id");
      const label = nextLabel(cfg.accounts.map((a) => a.label || ""));
      const next = { ...cfg, accounts: [...cfg.accounts, { profile: prof, project_id: String(projectId), label }] };
      await save(next);
      toast.success(`ÄÃ£ thÃªm ${prof} vÃ o Flow (project ${String(projectId).slice(0, 8)}â€¦)`);
    } catch (e: any) {
      toast.error(`Reuse Flow lá»—i: ${e?.message || e}`);
    }
  }

  function openNoVNC() {
    if (!cfg.captcha_solver_url) {
      toast.error("Cáº§n Ä‘iá»n captcha_solver_url trÆ°á»›c");
      return;
    }
    const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
    window.open(`${window.location.protocol}//${host}:6080/vnc.html?autoconnect=1`, "_blank");
  }

  async function triggerManualLogin(force = false) {
    if (!draft.profile.trim()) {
      toast.error("Cáº§n Ä‘iá»n profile trÆ°á»›c");
      return;
    }
    try {
      const res = await fetch(`${cfg.captcha_solver_url}/v1/session/manual-login`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${cfg.captcha_solver_api_key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          profile: draft.profile.trim(),
          url: "https://labs.google/fx/vi/tools/flow",
          force,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success(force ? "ÄÃ£ khá»Ÿi Ä‘á»™ng láº¡i Chrome â€” má»Ÿ noVNC" : "ÄÃ£ má»Ÿ browser session â€” má»Ÿ noVNC Ä‘á»ƒ login Google");
      openNoVNC();
    } catch (e: any) {
      toast.error(`Lá»—i gá»i manual-login: ${e?.message}`);
    }
  }

  function stopPolling() {
    if (pollIntervalRef.current) {
      window.clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }

  async function pollLoginStatus(profile: string, onSuccess?: (s: AutoLoginState) => void) {
    try {
      const res = await fetch(
        `${cfg.captcha_solver_url}/v1/session/${encodeURIComponent(profile)}/auto-login-status`,
        { headers: { Authorization: `Bearer ${cfg.captcha_solver_api_key}` } },
      );
      if (!res.ok) return;
      const data = await res.json();
      setLoginSession(data);
      if (data.state === "success" || data.state === "failed") {
        stopPolling();
        if (data.state === "success") {
          toast.success("ÄÄƒng nháº­p thÃ nh cÃ´ng ðŸŽ‰");
          if (onSuccess) onSuccess(data);
        } else {
          toast.error(`Auto-login lá»—i: ${data.error || data.message}`);
        }
      }
    } catch {
      /* network blip â€” keep polling */
    }
  }

  // â”€â”€ 1-click full automation â”€â”€
  // Auto-login â†’ wait for success â†’ call /v1/google/flow/get-or-create-project
  // â†’ push the {profile, project_id, label} into the Flow pool config.
  // Handles 2FA prompts the same way as startAutoLogin (UI shows tap-match
  // number / SMS code input), and stops at any failure with a toast.
  const [oneClickRunning, setOneClickRunning] = useState(false);
  const [oneClickStep, setOneClickStep] = useState<string>("");

  async function oneClickAddAccount() {
    if (!autoLogin.email.trim() || !autoLogin.password) {
      toast.error("Cáº§n Ä‘iá»n email + máº­t kháº©u cho 1-click");
      return;
    }
    // Account-centric profile (provider-neutral) so logging in via Flow vs
    // ChatGPT vs Gemini produces the SAME profile for one Google account â€”
    // one profile per account, clean cross-provider reuse. (Was google-fx-N.)
    const local = (autoLogin.email.split("@")[0] || "fx").replace(/[^a-z0-9-]/gi, "-");
    const profile = `google-${local}`;
    const label = suggestedLabel;
    stopPolling();
    setOneClickRunning(true);
    setOneClickStep("Äang Ä‘Äƒng nháº­p Google...");
    try {
      // 1) Start auto-login
      const loginRes = await fetch(`${cfg.captcha_solver_url}/v1/session/auto-login`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${cfg.captcha_solver_api_key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          profile,
          email: autoLogin.email.trim(),
          password: autoLogin.password,
          totp_secret: autoLogin.totpSecret.trim(),
          prefer_method: "auth",
        }),
      });
      if (!loginRes.ok) throw new Error(`auto-login HTTP ${loginRes.status}`);
      const initialSession = await loginRes.json();
      setLoginSession(initialSession);
      openNoVNC();

      // 2) Poll for success (or 2FA prompt). User must complete 2FA via
      // the existing tap/code UI (panel below). We continue when state
      // becomes success.
      const onSuccess = async () => {
        try {
          setOneClickStep("ÄÄƒng nháº­p OK â€” Ä‘ang láº¥y/táº¡o Flow project...");
          // 3) Get or create project
          const projRes = await fetch(`${cfg.captcha_solver_url}/v1/google/flow/get-or-create-project`, {
            method: "POST",
            headers: {
              "Authorization": `Bearer ${cfg.captcha_solver_api_key}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ profile, headless: false, timeout: 90 }),
          });
          if (!projRes.ok) {
            const err = await projRes.json().catch(() => ({}));
            throw new Error(err.detail || `get-or-create-project HTTP ${projRes.status}`);
          }
          const proj = await projRes.json();
          setOneClickStep(`Got project ${proj.project_id.slice(0, 8)}... (${proj.action}) â€” Ä‘ang thÃªm vÃ o pool...`);

          // 4) Save to pool config
          const newAccount: FlowAccount = {
            profile,
            project_id: proj.project_id,
            label,
          };
          const next = { ...cfg, accounts: [...cfg.accounts, newAccount] };
          await save(next);
          setOneClickStep(`HoÃ n táº¥t âœ… Account #${next.accounts.length} (${label}) Ä‘Ã£ sáºµn sÃ ng`);
          toast.success(`ÄÃ£ thÃªm account ${label} â€” profile ${profile}`);
          // Clear email/password
          setAutoLogin({ email: "", password: "", code: "", totpSecret: "" });
          setSelectedAccount("");
        } catch (e: any) {
          setOneClickStep("");
          toast.error(`Lá»—i sau login: ${e?.message}`);
        } finally {
          setOneClickRunning(false);
        }
      };
      if (initialSession.state === "success") {
        void onSuccess();
      } else if (initialSession.state === "failed") {
        toast.error(`Auto-login lá»—i: ${initialSession.error || initialSession.message}`);
        setOneClickRunning(false);
      } else {
        pollIntervalRef.current = window.setInterval(() => {
          void pollLoginStatus(profile, onSuccess);
        }, 1500);
      }
    } catch (e: any) {
      toast.error(`Lá»—i 1-click: ${e?.message}`);
      setOneClickRunning(false);
      setOneClickStep("");
    }
  }

  async function startAutoLogin() {
    if (!autoLogin.email.trim() || !autoLogin.password) {
      toast.error("Cáº§n Ä‘iá»n email + máº­t kháº©u");
      return;
    }
    // Same account-centric profile as 1-click â†’ "Chá»‰ Ä‘Äƒng nháº­p" vÃ  "Tá»± Ä‘á»™ng
    // setup" dÃ¹ng chung Má»˜T profile cho má»—i Google account (clean reuse).
    const local = (autoLogin.email.split("@")[0] || "fx").replace(/[^a-z0-9-]/gi, "-");
    const profile = `google-${local}`;
    stopPolling();
    try {
      const res = await fetch(`${cfg.captcha_solver_url}/v1/session/auto-login`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${cfg.captcha_solver_api_key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          profile,
          email: autoLogin.email.trim(),
          password: autoLogin.password,
          totp_secret: autoLogin.totpSecret.trim(),
          prefer_method: "auth",
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setLoginSession(data);
      toast.success("Auto-login Ä‘Ã£ cháº¡y â€” theo dÃµi á»Ÿ dÆ°á»›i");
      // Open noVNC so user can see Chrome live
      openNoVNC();
      if (data.state === "success") {
        toast.success("ÄÄƒng nháº­p thÃ nh cÃ´ng ðŸŽ‰");
      } else if (data.state === "failed") {
        toast.error(`Auto-login lá»—i: ${data.error || data.message}`);
      } else {
        pollIntervalRef.current = window.setInterval(() => {
          void pollLoginStatus(profile);
        }, 1500);
      }
    } catch (e: any) {
      toast.error(`Lá»—i auto-login: ${e?.message}`);
    }
  }

  async function submit2faCode() {
    const profile = loginSession?.profile;
    if (!profile || !autoLogin.code.trim()) {
      toast.error("Cáº§n mÃ£ 2FA");
      return;
    }
    try {
      const res = await fetch(
        `${cfg.captcha_solver_url}/v1/session/${encodeURIComponent(profile)}/auto-login-2fa-code`,
        {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${cfg.captcha_solver_api_key}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ code: autoLogin.code.trim() }),
        },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      toast.success("ÄÃ£ gá»­i mÃ£, Ä‘á»£i xÃ¡c nháº­nâ€¦");
      setAutoLogin((s) => ({ ...s, code: "" }));
    } catch (e: any) {
      toast.error(`Lá»—i gá»­i mÃ£: ${e?.message}`);
    }
  }

  function cancelLoginSession() {
    stopPolling();
    setLoginSession(null);
    setAutoLogin({ email: "", password: "", code: "", totpSecret: "" });
    setSelectedAccount("");
  }

  async function handleSaveAccount() {
    if (!autoLogin.email.trim() || !autoLogin.password) {
      toast.error("Cáº§n email + máº­t kháº©u Ä‘á»ƒ lÆ°u");
      return;
    }
    setIsSavingAccount(true);
    try {
      await fetch(`${cfg.captcha_solver_url}/v1/accounts/saved`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${cfg.captcha_solver_api_key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ email: autoLogin.email.trim(), password: autoLogin.password, totp_secret: autoLogin.totpSecret.trim() }),
      });
      toast.success("ÄÃ£ lÆ°u tÃ i khoáº£n");
      setAutoLogin({ email: "", password: "", code: "", totpSecret: "" });
      setSelectedAccount("");
      setSavedRefreshKey((k) => k + 1);
    } catch {
      toast.error("LÆ°u tÃ i khoáº£n tháº¥t báº¡i");
    } finally {
      setIsSavingAccount(false);
    }
  }

  return (
    <Card className="rounded-3xl border-emerald-500/25 bg-emerald-500/10">
      <CardContent className="space-y-4 p-5">
        {/* Header + global enable */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-emerald-600" />
              <h3 className="text-sm font-semibold text-emerald-600 dark:text-emerald-300">Google Labs Flow</h3>
            </div>
            <p className="text-xs text-[var(--muted-foreground)] mt-0.5">
              Sinh áº£nh qua labs.google/fx (Nano Banana Pro / 2 / Imagen 4) â€” cháº¡y qua captcha-solver browser pool
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
            <input
              type="checkbox"
              checked={cfg.enabled}
              onChange={(e) => void save({ ...cfg, enabled: e.target.checked })}
              className="size-4 rounded"
            />
            Enabled
          </label>
        </div>

        {/* Captcha-solver chạy nội bộ — chỉ còn Cooldown */}
        <div className="rounded-xl border border-emerald-200/60 bg-[var(--card)]/60 p-3">
          <div>
            <label className="text-xs text-emerald-800">Cooldown sau rate-limit (giÃ¢y)</label>
            <Input
              type="number"
              min={60}
              max={86400}
              step={60}
              value={cfg.cooldown_seconds ?? 3600}
              onChange={(e) => setCfg({ ...cfg, cooldown_seconds: parseInt(e.target.value) || 3600 })}
              onBlur={() => void save(cfg)}
              placeholder="3600"
              className="mt-1 h-9 rounded-lg border-emerald-200 text-sm font-mono"
            />
            <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
              {Math.round((cfg.cooldown_seconds ?? 3600) / 60)} phÃºt Â· Khi 1 account dÃ­nh 429/quota â†’ skip trong khoáº£ng nÃ y. Auto re-enter pool khi háº¿t.
            </p>
          </div>
        </div>

        {/* Strict-priority fallback explainer */}
        <div className="rounded-xl border border-emerald-200/40 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-700 dark:text-emerald-300">
          <span className="font-semibold">Fallback rotation:</span> Main luÃ´n Ä‘Æ°á»£c dÃ¹ng trÆ°á»›c. Khi Main dÃ­nh quota â†’ tá»± fallback sang Backup â†’ Spare 1 â†’ Spare 2 â†’ â€¦ theo thá»© tá»± trong danh sÃ¡ch. Háº¿t cooldown thÃ¬ auto re-enter pool á»Ÿ slot Æ°u tiÃªn.
        </div>

        {/* Existing accounts list */}
        {cfg.accounts.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
              TÃ i khoáº£n hiá»‡n cÃ³ ({cfg.accounts.length}) â€” #1 luÃ´n Ä‘Æ°á»£c dÃ¹ng trÆ°á»›c
            </p>
            {cfg.accounts.map((a, i) => (
              <div key={`${a.profile}:${a.project_id}`} className="flex items-center gap-2 rounded-lg border border-emerald-200/60 bg-[var(--card)]/60 px-3 py-2">
                <span className={`shrink-0 inline-flex items-center justify-center min-w-[28px] h-5 px-1.5 rounded-md text-[11px] font-mono font-bold tabular-nums ${
                  i === 0 ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300" : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                }`}>
                  #{i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-[var(--foreground)]">{a.label || a.profile}</div>
                  <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)] font-mono">
                    <span>profile: {a.profile}</span>
                    <span>Â·</span>
                    <span className="truncate">project: {a.project_id}</span>`n                      {a.remainingCredits !== undefined && (<><span className="text-[var(--secondary-foreground)]">·</span><span className="text-violet-600 font-bold truncate">{a.remainingCredits} credits</span></>)}
                  </div>
                </div>
                <Button
                  className="h-7 w-7 rounded-md bg-rose-50 text-rose-500 hover:bg-rose-100 p-0"
                  onClick={() => removeAccount(i)}
                  disabled={saving}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}

        {/* Add new account (advanced / manual project_id) */}
        <div className="space-y-2 rounded-xl border border-dashed border-emerald-300 bg-[var(--card)]/40 p-3">
          <p className="text-xs font-semibold text-emerald-800">+ ThÃªm tÃ i khoáº£n má»›i</p>
          <div className="grid gap-2 sm:grid-cols-3">
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">
                Label (chá»n hoáº·c gÃµ)
                {!manuallyEditedLabel && cfg.accounts.length > 0 && (
                  <span className="ml-1 text-emerald-600">Â· gá»£i Ã½: {suggestedLabel}</span>
                )}
              </label>
              <Input
                value={draft.label || ""}
                onChange={(e) => {
                  setDraft({ ...draft, label: e.target.value });
                  setManuallyEditedLabel(true);
                }}
                placeholder={suggestedLabel}
                className="mt-1 h-8 rounded-lg border-[var(--border)] text-xs"
                list="flow-label-presets"
                autoComplete="off"
              />
              {/* Native HTML5 datalist â€” gÃµ thoáº£i mÃ¡i, dropdown gá»£i Ã½ 6 preset
                  phá»• biáº¿n + báº¥t ká»³ label nÃ o Ä‘Ã£ dÃ¹ng trÆ°á»›c Ä‘Ã³ Ä‘á»ƒ khá»i Ä‘áº·t
                  trÃ¹ng. */}
              {/* Preset labels pháº£n Ã¡nh thá»© tá»± fallback FIFO â€” Main luÃ´n
                  #1, Backup lÃ  dá»± phÃ²ng Ä‘áº§u tiÃªn, Spare N lÃ  cÃ¡c slot dá»±
                  bá»‹ tiáº¿p theo trong rotation, Standby lÃ  account chá». */}
              <datalist id="flow-label-presets">
                <option value="Main" />
                <option value="Backup" />
                <option value="Spare 1" />
                <option value="Spare 2" />
                <option value="Spare 3" />
                <option value="Standby" />
                {cfg.accounts
                  .map((a) => a.label || "")
                  .filter((v, i, arr) => v && arr.indexOf(v) === i)
                  .map((v) => (
                    <option key={`used-${v}`} value={v} />
                  ))}
              </datalist>
            </div>
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">
                Profile (browser context)
                {!manuallyEditedProfile && cfg.accounts.length > 0 && (
                  <span className="ml-1 text-emerald-600">Â· gá»£i Ã½: {suggestedProfile}</span>
                )}
              </label>
              <Input
                value={draft.profile}
                onChange={(e) => {
                  setDraft({ ...draft, profile: e.target.value });
                  setManuallyEditedProfile(true);
                }}
                placeholder={suggestedProfile}
                className="mt-1 h-8 rounded-lg border-[var(--border)] text-xs font-mono"
              />
            </div>
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Project ID (Flow URL)</label>
              <Input
                value={draft.project_id}
                onChange={(e) => setDraft({ ...draft, project_id: e.target.value })}
                placeholder="54468d77-02ff-4a06-..."
                className="mt-1 h-8 rounded-lg border-[var(--border)] text-xs font-mono"
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              className="h-8 rounded-lg bg-emerald-600 px-3 text-xs text-white hover:bg-emerald-700"
              onClick={addAccount}
              disabled={saving}
            >
              {saving ? <LoaderCircle className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
              ThÃªm vÃ o pool
            </Button>
            <Button
              className="h-8 rounded-lg border border-emerald-200 bg-[var(--card)] px-3 text-xs text-emerald-700 hover:bg-emerald-500/10"
              onClick={() => triggerManualLogin(false)}
            >
              <ExternalLink className="size-3.5" /> Má»Ÿ noVNC + login thá»§ cÃ´ng
            </Button>
            <Button
              className="h-8 rounded-lg border border-amber-200 bg-[var(--card)] px-3 text-xs text-amber-700 hover:bg-amber-50"
              onClick={() => triggerManualLogin(true)}
              title="Kill Chrome cÅ© vÃ  má»Ÿ láº¡i â€” dÃ¹ng khi noVNC hiá»ƒn thá»‹ desktop trá»‘ng (Connected... :99)"
            >
              <RotateCw className="size-3.5" /> Khá»Ÿi Ä‘á»™ng láº¡i Chrome
            </Button>
          </div>
          <p className="text-[10px] text-[var(--muted-foreground)] leading-relaxed">
            <b>CÃ¡ch láº¥y project_id:</b> sau khi login Google trong noVNC, truy cáº­p{" "}
            <code className="text-emerald-700">labs.google/fx/vi/tools/flow</code> â†’ táº¡o project má»›i â†’ copy UUID tá»« URL{" "}
            <code className="text-emerald-700">.../project/&lt;UUID&gt;</code>.
          </p>
        </div>

        {/* â”€â”€ 1-CLICK ADD ACCOUNT â”€â”€ primary onboarding path */}
        <div className="space-y-2 rounded-xl border-2 border-fuchsia-300 bg-gradient-to-br from-fuchsia-50/60 to-cyan-50/60 p-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-bold text-fuchsia-800 flex items-center gap-1.5">
              <Sparkles className="size-3.5" /> 1-click thÃªm tÃ i khoáº£n (tá»± Ä‘á»™ng hoÃ n toÃ n)
            </p>
            <span className="text-[10px] text-fuchsia-700/80">
              auto-fill profile <code className="font-mono">{suggestedProfile}</code> Â· label <code className="font-mono">{suggestedLabel}</code>
            </span>
          </div>
          <p className="text-[10px] text-fuchsia-700/70 leading-relaxed">
            Login Google + tá»± láº¥y/táº¡o Flow project + tá»± add vÃ o pool â€” chá»‰ cáº§n email + máº­t kháº©u.
            Khi gáº·p 2FA, dÃ¹ng panel xanh chÃ m bÃªn dÆ°á»›i Ä‘á»ƒ xá»­ lÃ½ (sá»‘ tap hoáº·c mÃ£ SMS).
          </p>
          <SavedAccountsSelect
            csUrl={cfg.captcha_solver_url}
            csApiKey={cfg.captcha_solver_api_key}
            selected={selectedAccount}
            onSelect={(email, acct) => {
              setSelectedAccount(email);
              setAutoLogin({ email: acct.email, password: acct.password, code: "", totpSecret: acct.totp_secret || "" });
            }}
            disabled={oneClickRunning}
            refreshKey={savedRefreshKey}
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Email Google</label>
              <Input
                value={autoLogin.email}
                onChange={(e) => setAutoLogin({ ...autoLogin, email: e.target.value })}
                placeholder="you@gmail.com"
                className="mt-1 h-8 rounded-lg border-fuchsia-200 text-xs font-mono"
                autoComplete="off"
                disabled={oneClickRunning}
              />
            </div>
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Máº­t kháº©u</label>
              <div className="relative">
                <Input
                  type={showPassword ? "text" : "password"}
                  value={autoLogin.password}
                  onChange={(e) => setAutoLogin({ ...autoLogin, password: e.target.value })}
                  placeholder="â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢"
                  className="mt-1 h-8 rounded-lg border-fuchsia-200 text-xs font-mono pr-8"
                  autoComplete="off"
                  disabled={oneClickRunning}
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
              value={autoLogin.totpSecret}
              onChange={(e) => setAutoLogin({ ...autoLogin, totpSecret: e.target.value })}
              placeholder="xxxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx"
              className="mt-1 h-8 rounded-lg border-amber-200 text-xs font-mono bg-amber-50/30"
              autoComplete="off"
              disabled={oneClickRunning}
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
          {/* TÃ¡i dÃ¹ng profile Ä‘Ã£ onboard â€” Ä‘áº·t trong block onboard nhÆ° ChatGPT */}
          <div className="rounded-lg border border-emerald-200 bg-emerald-500/10 p-2 space-y-1">
            <p className="text-[11px] font-medium text-emerald-700">
              TÃ¡i dÃ¹ng profile Ä‘Ã£ onboard (Flow/Gemini/ChatGPT) â€” tá»± láº¥y project_id, khÃ´ng cáº§n nháº­p láº¡i email/máº­t kháº©u:
            </p>
            <ReuseProfilePicker
              cs={{ url: cfg.captcha_solver_url, apiKey: cfg.captcha_solver_api_key }}
              onReuse={reuseAccount}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 rounded-lg text-[11px]"
              onClick={handleSaveAccount}
              disabled={isSavingAccount || !autoLogin.email.trim() || !autoLogin.password}
            >
              {isSavingAccount ? <LoaderCircle className="mr-1 size-3 animate-spin" /> : null}
              LÆ°u tÃ i khoáº£n
            </Button>
            <Button
              className="h-9 rounded-lg bg-gradient-to-r from-fuchsia-600 to-cyan-600 px-3 text-xs font-bold text-white hover:from-fuchsia-700 hover:to-cyan-700 shadow-lg shadow-fuchsia-200"
              onClick={oneClickAddAccount}
              disabled={oneClickRunning}
            >
              {oneClickRunning
                ? <><LoaderCircle className="size-3.5 animate-spin" /> Äang cháº¡yâ€¦</>
                : <><Sparkles className="size-3.5" /> Tá»± Ä‘á»™ng setup (1-click)</>}
            </Button>
            <Button
              className="h-9 rounded-lg border border-amber-300 bg-amber-50 px-3 text-xs font-semibold text-amber-800 hover:bg-amber-100"
              onClick={startAutoLogin}
              disabled={oneClickRunning || loginSession?.state === "running" || loginSession?.state === "starting" || !autoLogin.email.trim() || !autoLogin.password}
              title="Chá»‰ Ä‘Äƒng nháº­p Google vÃ o profile, KHÃ”NG add vÃ o pool. Sau Ä‘Ã³ dÃ¹ng nÃºt TÃ¡i dÃ¹ng Ä‘á»ƒ thÃªm vÃ o Flow."
            >
              <KeyRound className="size-3.5" /> Chá»‰ Ä‘Äƒng nháº­p
            </Button>
            <Button
              className="h-9 rounded-lg border border-fuchsia-200 bg-[var(--card)] px-3 text-xs text-fuchsia-700 hover:bg-fuchsia-50"
              onClick={openNoVNC}
            >
              <ExternalLink className="size-3.5" /> Má»Ÿ noVNC
            </Button>
            {loginSession && loginSession.state !== "none" && (
              <Button
                className="h-9 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                onClick={cancelLoginSession}
              >
                <X className="size-3.5" /> ÄÃ³ng phiÃªn
              </Button>
            )}
          </div>
          {oneClickStep && (
            <p className="text-[11px] text-fuchsia-800 bg-[var(--card)]/60 rounded-md px-2 py-1.5 font-mono">
              {oneClickStep}
            </p>
          )}

          {/* Tráº¡ng thÃ¡i Ä‘Äƒng nháº­p (2FA / tiáº¿n trÃ¬nh) â€” chung cho 1-click & Chá»‰ Ä‘Äƒng nháº­p */}
          {loginSession && loginSession.state !== "none" && (
            <div className={`mt-1 rounded-lg border p-3 text-xs space-y-2 ${
              loginSession.state === "success" ? "border-emerald-300 bg-emerald-50/70"
              : loginSession.state === "failed" ? "border-rose-300 bg-rose-50/70"
              : loginSession.state === "need_tap" ? "border-violet-300 bg-violet-50/70"
              : loginSession.state === "need_code" ? "border-amber-300 bg-amber-50/70"
              : "border-amber-200 bg-[var(--card)]/80"
            }`}>
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${
                  loginSession.state === "success" ? "bg-emerald-100 text-emerald-700"
                  : loginSession.state === "failed" ? "bg-rose-100 text-rose-700"
                  : loginSession.state === "need_tap" ? "bg-violet-100 text-violet-700"
                  : loginSession.state === "need_code" ? "bg-amber-100 text-amber-700"
                  : "bg-amber-100 text-amber-700"
                }`}>
                  {(loginSession.state === "running" || loginSession.state === "starting") && (
                    <LoaderCircle className="size-3 animate-spin" />
                  )}
                  {loginSession.state}
                </span>
                <span className="text-[var(--muted-foreground)]">{loginSession.message}</span>
                {typeof loginSession.elapsed_sec === "number" && (
                  <span className="ml-auto text-[10px] text-[var(--muted-foreground)] font-mono">{loginSession.elapsed_sec}s</span>
                )}
              </div>

              {loginSession.state === "need_tap" && (
                <div className="flex items-center gap-2 rounded-md bg-violet-100/60 px-2 py-1.5">
                  <Smartphone className="size-4 text-violet-700" />
                  <span className="text-violet-900">
                    Má»Ÿ app Gmail/Google trÃªn Ä‘iá»‡n thoáº¡i
                    {loginSession.tap_number ? (
                      <> vÃ  báº¥m sá»‘ <b className="text-base font-mono">{loginSession.tap_number}</b></>
                    ) : (
                      <> vÃ  báº¥m "CÃ³" Ä‘á»ƒ xÃ¡c minh</>
                    )}
                  </span>
                </div>
              )}

              {loginSession.state === "need_code" && (
                <div className="flex items-end gap-2">
                  <div className="flex-1">
                    <label className="text-[11px] text-amber-800">MÃ£ 2FA (SMS hoáº·c Authenticator)</label>
                    <Input
                      value={autoLogin.code}
                      onChange={(e) => setAutoLogin({ ...autoLogin, code: e.target.value })}
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
                    Gá»­i mÃ£
                  </Button>
                </div>
              )}

              {loginSession.state === "failed" && loginSession.error && (
                <p className="text-rose-700 text-[11px]">{loginSession.error}</p>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

