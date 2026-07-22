"use client";
import { useState, useEffect, useRef } from "react";
import { LoaderCircle, Sparkles, KeyRound, ExternalLink, Shield, Eye, EyeOff, Plus, Trash2, Play, X, Smartphone } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { SavedAccountsSelect } from "@/components/saved-accounts-select";
import { generateTotpCode, totpSecondsRemaining } from "@/lib/totp";
import { TotpSecretGuide, TotpSecretLabel } from "@/components/google-security-hints";
import { ReuseProfilePicker } from "./reuse-profile-picker";

type FlowAccount = { profile: string; project_id: string; label?: string };
type Cfg = { url: string; apiKey: string };
type FlowCfg = { enabled: boolean; captcha_solver_url: string; captcha_solver_api_key: string; accounts: FlowAccount[]; cooldown_seconds: number };
type LoginSt = { profile: string; state: string; message: string; tap_number?: string | null; elapsed_sec?: number; error?: string | null; access_token?: string | null; captured_email?: string | null };

function nextLabel(existing: string[]) {
  const used = new Set(existing.map(s => s.trim()).filter(Boolean));
  for (const l of ["Main","Backup","Spare 1","Spare 2","Spare 3","Standby"]) if (!used.has(l)) return l;
  for (let i = 4; i < 99; i++) { const c = `Spare ${i}`; if (!used.has(c)) return c; }
  return `Account ${used.size+1}`;
}

function StatusBox({ st }: { st: LoginSt }) {
  const color = st.state==="success"?"border-emerald-300 bg-emerald-50":st.state==="failed"?"border-rose-300 bg-rose-50":st.state==="need_tap"?"border-violet-300 bg-violet-50":st.state==="need_code"?"border-amber-300 bg-amber-50":"border-blue-200 bg-[var(--card)]";
  return (
    <div className={`rounded-lg border p-2 text-xs space-y-1 ${color}`}>
      <div className="flex items-center gap-2">
        {(st.state==="running"||st.state==="starting") && <LoaderCircle className="size-3 animate-spin"/>}
        <span className="font-semibold uppercase tracking-wide">{st.state}</span>
        <span className="text-[var(--muted-foreground)] flex-1">{st.message}</span>
        {st.elapsed_sec != null && <span className="text-[var(--muted-foreground)] font-mono text-[10px]">{st.elapsed_sec}s</span>}
      </div>
      {st.state==="need_tap" && (
        <div className="flex items-center gap-2 rounded bg-violet-100/60 px-2 py-1">
          <Smartphone className="size-3.5 text-violet-700"/>
          <span className="text-violet-900 text-[11px]">Mở app Google trên điện thoại{st.tap_number ? ` → bấm số ${st.tap_number}` : " → bấm Có"}</span>
        </div>
      )}
      {st.state==="need_code" && (
        <div className="rounded bg-amber-100/60 px-2 py-1 text-[11px] text-amber-900">
          ⚠️ Hệ thống đang chờ mã 2FA. Nếu bạn <strong>đã tự đăng nhập xong trên noVNC</strong> — chờ tối đa 60s hệ thống tự nhận ra.
        </div>
      )}
      {st.state==="failed" && st.error && <p className="text-rose-700">{st.error}</p>}
      {st.state==="success" && st.captured_email && <p className="text-emerald-700">✓ {st.captured_email}</p>}
    </div>
  );
}

export function GoogleProvidersCard() {
  const [cs, setCs] = useState<Cfg>({ url: "/api/captcha", apiKey: "" });
  const [flowCfg, setFlowCfg] = useState<FlowCfg>({ enabled:true, captcha_solver_url:"", captcha_solver_api_key:"", accounts:[], cooldown_seconds:3600 });
  const [flowDraft, setFlowDraft] = useState({ profile:"google-fx", project_id:"", label:"Main" });
  const [draft, setDraft] = useState({ email:"", password:"", totpSecret:"" });
  const [showPw, setShowPw] = useState(true);
  const [running, setRunning] = useState(false);
  const [loginSt, setLoginSt] = useState<LoginSt|null>(null);
  const [flowSt, setFlowSt] = useState<LoginSt|null>(null);
  const [chatgptSt, setChatgptSt] = useState<LoginSt|null>(null);
  const [geminiSt, setGeminiSt] = useState<LoginSt|null>(null);
  const [claudeSt, setClaudeSt] = useState<LoginSt|null>(null);
  const [selAcc, setSelAcc] = useState("");
  const [savedKey, setSavedKey] = useState(0);
  const [totpCode, setTotpCode] = useState("");
  const [totpRem, setTotpRem] = useState(30);
  const [reuseAllRunning, setReuseAllRunning] = useState(false);
  const [reuseAllStep, setReuseAllStep] = useState("");
  const [savingFlow, setSavingFlow] = useState(false);
  const pollRef = useRef<number|null>(null);
  const totpRef = useRef<number|null>(null);

  useEffect(() => { void load(); return () => { if(pollRef.current) clearInterval(pollRef.current); if(totpRef.current) clearInterval(totpRef.current); }; }, []);

  useEffect(() => {
    if (!draft.totpSecret.trim()) { setTotpCode(""); return; }
    const refresh = async () => { try { setTotpCode(await generateTotpCode(draft.totpSecret)); setTotpRem(totpSecondsRemaining()); } catch { setTotpCode(""); } };
    void refresh();
    totpRef.current = window.setInterval(refresh, 5000);
    return () => { if(totpRef.current) clearInterval(totpRef.current); };
  }, [draft.totpSecret]);

  async function load() {
    try {
      const d = await request.get("/api/settings");
      const p = (d.data as any)?.config?.providers || {};
      const fl = p.flow || {};
      // Always use the /api/captcha proxy — the captcha_solver_url in config is internal (backend→backend)
      // and cannot be reached directly from the browser.
      setCs({ url: "/api/captcha", apiKey: fl.captcha_solver_api_key||"" });
      setFlowCfg({ enabled: fl.enabled!==false, captcha_solver_url: fl.captcha_solver_url||"/api/captcha", captcha_solver_api_key: fl.captcha_solver_api_key||"", accounts: Array.isArray(fl.accounts)?fl.accounts:[], cooldown_seconds: fl.cooldown_seconds||3600 });
    } catch {}
  }

  function stopPoll() { if(pollRef.current) { clearInterval(pollRef.current); pollRef.current=null; } }
  function profileOf(email: string) { const local = (email||"fx").split("@")[0]; return `google-${local.replace(/[^a-z0-9]/gi,"-").toLowerCase()}`; }

  async function saveFlow(next: FlowCfg) {
    setSavingFlow(true);
    try {
      const cur = await request.get("/api/settings");
      const provs = { ...((cur.data as any)?.config?.providers||{}) };
      provs.flow = next;
      await request.post("/api/settings", { providers: provs });
      setFlowCfg(next);
      setCs({ url: "/api/captcha", apiKey: next.captcha_solver_api_key });
      toast.success("Đã lưu Flow config");
    } catch (e:any) { toast.error(e?.message||"Lỗi lưu"); }
    finally { setSavingFlow(false); }
  }

  async function saveAccount() {
    if (!draft.email.trim()||!draft.password) { toast.error("Cần email + mật khẩu"); return; }
    try {
      await request.post(`${cs.url}/v1/accounts/saved`, { email:draft.email.trim(), password:draft.password, totp_secret:draft.totpSecret.trim() });
      toast.success("Đã lưu tài khoản");
      setDraft({ email:"", password:"", totpSecret:"" }); setSelAcc(""); setSavedKey(k=>k+1);
    } catch { toast.error("Lưu thất bại"); }
  }

  async function pollLogin(profile: string, onOk?: (s: LoginSt)=>void) {
    try {
      const r = await request.get(`${cs.url}/v1/session/${encodeURIComponent(profile)}/auto-login-status`);
      const d: LoginSt = r.data;
      setLoginSt(d);
      if(d.state==="success"||d.state==="failed") { stopPoll(); setRunning(false); if(d.state==="success"&&onOk) onOk(d); else if(d.state==="failed") toast.error(`Login fail: ${d.error||d.message}`); }
    } catch {}
  }

  async function autoLoginOnly() {
    if(!draft.email.trim()||!draft.password) { toast.error("Cần email + mật khẩu"); return; }
    const profile = profileOf(draft.email);
    stopPoll(); setRunning(true); setLoginSt(null);
    try {
      const r = await request.post(`${cs.url}/v1/session/auto-login`, { profile, email:draft.email.trim(), password:draft.password, totp_secret:draft.totpSecret.trim(), prefer_method:draft.totpSecret.trim()?"auth":"tap" });
      const d = r.data;
      setLoginSt({...d, profile});
      const vncWin = window.open(`${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`,"_blank","noopener,width=1024,height=720");
      if(d.state==="success") { 
        setRunning(false); 
        toast.success(`Đã đăng nhập ${profile} ✓`); 
        if(vncWin) vncWin.close(); 
      }
      else if(d.state==="failed") { setRunning(false); toast.error(`Login fail: ${d.error||d.message}`); }
      else { 
        pollRef.current = window.setInterval(()=>void pollLogin(profile, (st) => {
          toast.success(`Đã đăng nhập ${profile} ✓`);
          if (vncWin) vncWin.close();
        }), 1500); 
      }
    } catch(e:any) { toast.error(`Lỗi: ${e?.message}`); setRunning(false); }
  }

  // ---- per-provider reuse ----
  async function pollUntilDone(url: string, profile: string, setSt: React.Dispatch<React.SetStateAction<LoginSt|null>>): Promise<void> {
    return new Promise((resolve, reject) => {
      const iv = window.setInterval(async () => {
        try {
          const r = await request.get(url);
          const d = r.data;
          setSt(d);
          if(d.state==="success") { clearInterval(iv); resolve(); }
          else if(d.state==="failed") { clearInterval(iv); reject(new Error(d.error||d.message)); }
        } catch {}
      }, 1500);
    });
  }

  async function reuseFlow(prof: string) {
    const existing = flowCfg.accounts.findIndex(a=>a.profile===prof);
    setFlowSt({ profile:prof, state:"running", message: existing>=0 ? "Profile đã có, đang cập nhật project_id..." : "Đang lấy project_id..." });
    try {
      const r = await request.post(`${cs.url}/v1/google/flow/get-or-create-project`, { profile:prof, headless:true, timeout:150 });
      const d = r.data;
      if(!d.project_id) throw new Error(d.detail||d.error||"no project_id");
      let next: FlowCfg;
      if(existing>=0) {
        // Update existing entry
        const accs = [...flowCfg.accounts];
        accs[existing] = { ...accs[existing], project_id: String(d.project_id) };
        next = { ...flowCfg, accounts: accs };
      } else {
        const label = nextLabel(flowCfg.accounts.map(a=>a.label||""));
        next = { ...flowCfg, accounts:[...flowCfg.accounts,{ profile:prof, project_id:String(d.project_id), label }] };
      }
      await saveFlow(next);
      setFlowSt({ profile:prof, state:"success", message: existing>=0 ? `Đã cập nhật project_id` : `Đã thêm tài khoản Flow` });
    } catch(e:any) { setFlowSt({ profile:prof, state:"failed", message:"Lỗi", error:e?.message }); throw e; }
  }

  async function reuseChatGPT(prof: string) {
    setChatgptSt({ profile:prof, state:"running", message:"Đang khởi tạo..." });
    try {
      const r = await request.post(`${cs.url}/v1/chatgpt/onboard`, { profile:prof, email:"", password:"", reuse_session:true });
      const init = r.data;
      setChatgptSt(init);
      if(init.state==="failed") throw new Error(init.error||init.message);
      if(init.state!=="success") await pollUntilDone(`${cs.url}/v1/chatgpt/${encodeURIComponent(prof)}/onboard-status`, prof, setChatgptSt);
      const fin = init.state==="success"?init:(await request.get(`${cs.url}/v1/chatgpt/${encodeURIComponent(prof)}/onboard-status`)).data;
      if(fin.access_token) { await request.post("/api/accounts",{tokens:[fin.access_token]}); setChatgptSt({...fin, state:"success", message:"Đã thêm token vào pool"}); }
    } catch(e:any) { setChatgptSt({ profile:prof, state:"failed", message:"Lỗi", error:e?.message }); throw e; }
  }

  async function reuseGeminiApi(prof: string) {
    setGeminiSt({ profile:prof, state:"running", message:"Đang khởi tạo..." });
    try {
      const r = await request.post(`${cs.url}/v1/gemini-web/onboard`, { profile:prof, email:"", password:"" });
      const init = r.data;
      setGeminiSt(init);
      if(init.state==="failed") throw new Error(init.error||init.message);
      if(init.state!=="success") await pollUntilDone(`${cs.url}/v1/gemini-web/${encodeURIComponent(prof)}/onboard-status`, prof, setGeminiSt);
      const cur = await request.get("/api/settings");
      const provs = { ...((cur.data as any)?.config?.providers||{}) };
      const gwa = provs.gemini_web_api||{};
      const profiles: string[] = Array.isArray(gwa.profiles)?[...gwa.profiles]:[];
      if(!profiles.includes(prof)) profiles.push(prof);
      provs.gemini_web_api = { ...gwa, enabled:true, profile:prof, profiles };
      await request.post("/api/settings", { providers: provs });
      setGeminiSt(prev=>prev ? {...prev, state:"success", message:"Đã lưu config"} : null);
    } catch(e:any) { setGeminiSt({ profile:prof, state:"failed", message:"Lỗi", error:e?.message }); throw e; }
  }

  async function reuseClaude(prof: string) {
    setClaudeSt({ profile:prof, state:"running", message:"Đang khởi tạo..." });
    try {
      const r = await request.post(`${cs.url}/v1/claude-web/onboard`, { profile:prof });
      const init = r.data;
      setClaudeSt(init);
      if(init.state==="failed") throw new Error(init.error||init.message);
      if(init.state!=="success") await pollUntilDone(`${cs.url}/v1/claude-web/${encodeURIComponent(prof)}/onboard-status`, prof, setClaudeSt);
      const cur = await request.get("/api/settings");
      const provs = { ...((cur.data as any)?.config?.providers||{}) };
      const cl = provs.claude||{};
      const profiles: string[] = Array.isArray(cl.profiles)?[...cl.profiles]:(cl.profile?[cl.profile]:[]);
      if(!profiles.includes(prof)) profiles.push(prof);
      provs.claude = { ...cl, enabled:true, captcha_solver_url:cs.url, captcha_solver_api_key:cs.apiKey, profiles, model:cl.model||"auto" };
      await request.post("/api/settings", { providers: provs });
      setClaudeSt(prev=>prev ? {...prev, state:"success", message:"Đã lưu config Claude"} : null);
    } catch(e:any) { setClaudeSt({ profile:prof, state:"failed", message:"Lỗi", error:e?.message }); throw e; }
  }

  async function reuseAll(prof: string) {
    setReuseAllRunning(true);
    const steps: [string, (p:string)=>Promise<void>][] = [["Google Labs Flow",reuseFlow],["ChatGPT",reuseChatGPT],["Gemini Web API",reuseGeminiApi],["Claude",reuseClaude]];
    for (const [label, fn] of steps) {
      setReuseAllStep(`Đang tái dùng ${label}…`);
      try { await fn(prof); } catch { /* lỗi đã toast ở trong, tiếp tục */ }
    }
    setReuseAllStep("Hoàn tất ✅");
    setReuseAllRunning(false);
  }

  const suggestedLabel = nextLabel(flowCfg.accounts.map(a=>a.label||""));

  return (
    <Card className="rounded-3xl border-blue-100/80 bg-gradient-to-br from-blue-50/40 to-amber-50/30">
      <CardContent className="space-y-5 p-5">

        {/* HEADER */}
        <div className="flex items-center gap-2">
          <span className="text-xl">🔑</span>
          <div>
            <h3 className="text-sm font-semibold text-blue-900">Provider qua tài khoản Google</h3>
            <p className="text-xs text-blue-700/70">Đăng nhập Google một lần → tái dùng chung cho Flow, ChatGPT, Gemini Web API và Claude</p>
          </div>
        </div>

        {/* ── 1. ĐĂNG NHẬP GOOGLE ── */}
        <div className="space-y-3 rounded-xl border-2 border-blue-300 bg-[var(--card)]/60 p-3">
          <p className="text-xs font-bold text-blue-800 flex items-center gap-1.5"><KeyRound className="size-3.5"/>Đăng nhập tài khoản Google</p>
          <p className="text-[10px] text-blue-700/70">Lưu tài khoản và đăng nhập Google vào browser profile. Sau đó dùng các nút Tái dùng bên dưới để thêm từng provider.</p>

          <SavedAccountsSelect csUrl={cs.url} csApiKey={cs.apiKey} selected={selAcc} onSelect={(email,acct)=>{setSelAcc(email);setDraft({email:acct.email,password:acct.password,totpSecret:acct.totp_secret||""});}} disabled={running} refreshKey={savedKey}/>

          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Email Google</label>
              <Input value={draft.email} onChange={e=>setDraft({...draft,email:e.target.value})} placeholder="you@gmail.com" className="mt-1 h-8 rounded-lg border-blue-200 text-xs font-mono" autoComplete="off" disabled={running}/>
            </div>
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Mật khẩu</label>
              <div className="relative">
                <Input type={showPw?"text":"password"} value={draft.password} onChange={e=>setDraft({...draft,password:e.target.value})} placeholder="••••••••" className="mt-1 h-8 rounded-lg border-blue-200 text-xs font-mono pr-8" autoComplete="off" disabled={running}/>
                <button type="button" className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]" onClick={()=>setShowPw(!showPw)} tabIndex={-1}>{showPw?<EyeOff className="size-3.5"/>:<Eye className="size-3.5"/>}</button>
              </div>
            </div>
          </div>
          <div>
            <TotpSecretLabel />
            <Input value={draft.totpSecret} onChange={e=>setDraft({...draft,totpSecret:e.target.value})} placeholder="xxxx xxxx xxxx xxxx..." className="mt-1 h-8 rounded-lg border-amber-200 text-xs font-mono bg-amber-50/30" autoComplete="off" disabled={running}/>
            {totpCode && <div className="mt-1 flex items-center gap-2"><span className="text-[11px] text-amber-700">Mã TOTP:</span><span className="px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-mono text-sm font-bold tracking-widest">{totpCode}</span><span className="text-[10px] text-amber-500">({totpRem}s)</span></div>}
            <TotpSecretGuide />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" className="h-7 text-[11px] rounded-lg" onClick={saveAccount} disabled={!draft.email.trim()||!draft.password}>Lưu tài khoản</Button>
            <Button className="h-9 rounded-lg bg-blue-600 px-3 text-xs text-white hover:bg-blue-700" onClick={autoLoginOnly} disabled={running}>
              {running?<><LoaderCircle className="size-3.5 animate-spin mr-1"/>Đang đăng nhập…</>:<><KeyRound className="size-3.5 mr-1"/>Chỉ đăng nhập</>}
            </Button>
            <Button className="h-9 rounded-lg border border-blue-200 bg-[var(--card)] px-3 text-xs text-blue-700" onClick={()=>window.open(`${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`,"_blank")}><ExternalLink className="size-3.5 mr-1"/>Mở noVNC</Button>
            {loginSt && loginSt.state!=="none" && <Button className="h-9 rounded-lg border bg-[var(--card)] px-3 text-xs text-[var(--muted-foreground)]" onClick={()=>{stopPoll();setLoginSt(null);setRunning(false);}}><X className="size-3.5"/></Button>}
          </div>
          {loginSt && loginSt.state!=="none" && <StatusBox st={loginSt}/>}
        </div>

        {/* ── 2. FLOW ── */}
        <div className="space-y-3 rounded-xl border-2 border-emerald-300 bg-[var(--card)]/60 p-3">
          <p className="text-xs font-bold text-emerald-800 flex items-center gap-1.5"><Sparkles className="size-3.5 text-emerald-600"/>Google Labs Flow</p>

          {/* Captcha-solver chạy nội bộ — chỉ còn Cooldown */}
          <div className="grid gap-2 sm:grid-cols-3">
            <div>
              <label className="text-[11px] text-[var(--muted-foreground)]">Cooldown rate-limit (giây)</label>
              <Input type="number" min={60} max={86400} value={flowCfg.cooldown_seconds} onChange={e=>setFlowCfg({...flowCfg,cooldown_seconds:parseInt(e.target.value)||3600})} onBlur={()=>void saveFlow(flowCfg)} className="mt-1 h-8 rounded-lg border-emerald-200 text-xs font-mono"/>
            </div>
          </div>

          {/* Accounts list */}
          {flowCfg.accounts.length>0 && (
            <div className="space-y-1.5">
              <p className="text-[11px] font-semibold text-emerald-700">Tài khoản hiện có ({flowCfg.accounts.length}) — #1 ưu tiên trước</p>
              {flowCfg.accounts.map((a,i)=>(
                <div key={`${a.profile}:${a.project_id}`} className="flex items-center gap-2 rounded-lg border border-emerald-200/60 bg-emerald-50/40 px-3 py-1.5">
                  <span className={`shrink-0 min-w-[24px] text-center text-[11px] font-bold font-mono rounded px-1 ${i===0?"bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300":"bg-[var(--secondary)] text-[var(--muted-foreground)]"}`}>#{i+1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-[var(--foreground)]">{a.label||a.profile}</div>
                    <div className="text-[10px] text-[var(--muted-foreground)] font-mono truncate">{a.profile} · {a.project_id}</div>
                  </div>
                  <Button className="h-6 w-6 p-0 rounded bg-rose-50 text-rose-500 hover:bg-rose-100" onClick={()=>void saveFlow({...flowCfg,accounts:flowCfg.accounts.filter((_,j)=>j!==i)})} disabled={savingFlow}><Trash2 className="size-3"/></Button>
                </div>
              ))}
            </div>
          )}

          {/* Reuse picker */}
          <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-2 space-y-1">
            <p className="text-[11px] font-medium text-emerald-700">Tái dùng profile Google → thêm vào Flow</p>
            <div className="flex gap-2 items-center"><ReuseProfilePicker cs={cs} onReuse={reuseFlow}/>{flowSt && flowSt.state!=="none" && <Button variant="ghost" size="sm" onClick={()=>setFlowSt(null)}><X className="size-3"/></Button>}</div>
            {flowSt && flowSt.state!=="none" && <div className="mt-2"><StatusBox st={flowSt}/></div>}
          </div>
        </div>

        {/* ── 3. CHATGPT ── */}
        <div className="space-y-2 rounded-xl border-2 border-blue-200 bg-[var(--card)]/60 p-3">
          <p className="text-xs font-bold text-blue-800 flex items-center gap-1.5"><span>💬</span>ChatGPT via Google OAuth</p>
          <p className="text-[10px] text-blue-700/70">Tái dùng profile Google đã đăng nhập → scrape JWT access_token → add vào pool ChatGPT free.</p>
          <div className="flex gap-2 items-center"><ReuseProfilePicker cs={cs} onReuse={reuseChatGPT}/>{chatgptSt && chatgptSt.state!=="none" && <Button variant="ghost" size="sm" onClick={()=>setChatgptSt(null)}><X className="size-3"/></Button>}</div>
          {chatgptSt && chatgptSt.state!=="none" && <div className="mt-2"><StatusBox st={chatgptSt}/></div>}
        </div>

        {/* ── 4. GEMINI WEB API ── */}
        <div className="space-y-2 rounded-xl border-2 border-violet-200 bg-[var(--card)]/60 p-3">
          <p className="text-xs font-bold text-violet-800 flex items-center gap-1.5"><span>♊</span>Gemini Web API (gemini.google.com)</p>
          <p className="text-[10px] text-violet-700/70">Tái dùng profile → lấy cookie __Secure-1PSID → gọi API ẩn gemini.google.com.</p>
          <div className="flex gap-2 items-center"><ReuseProfilePicker cs={cs} onReuse={reuseGeminiApi}/>{geminiSt && geminiSt.state!=="none" && <Button variant="ghost" size="sm" onClick={()=>setGeminiSt(null)}><X className="size-3"/></Button>}</div>
          {geminiSt && geminiSt.state!=="none" && <div className="mt-2"><StatusBox st={geminiSt}/></div>}
        </div>

        {/* ── 5. CLAUDE ── */}
        <div className="space-y-2 rounded-xl border-2 border-orange-200 bg-[var(--card)]/60 p-3">
          <p className="text-xs font-bold text-orange-800 flex items-center gap-1.5"><span>🤖</span>Claude via Google OAuth</p>
          <p className="text-[10px] text-orange-700/70">Tái dùng profile → scrape sessionKey → lưu config Claude.</p>
          <div className="flex gap-2 items-center"><ReuseProfilePicker cs={cs} onReuse={reuseClaude}/>{claudeSt && claudeSt.state!=="none" && <Button variant="ghost" size="sm" onClick={()=>setClaudeSt(null)}><X className="size-3"/></Button>}</div>
          {claudeSt && claudeSt.state!=="none" && <div className="mt-2"><StatusBox st={claudeSt}/></div>}
        </div>

        {/* ── 6. TÁI DÙNG TẤT CẢ ── */}
        <div className="space-y-2 rounded-xl border-2 border-fuchsia-300 bg-gradient-to-br from-fuchsia-50/60 to-cyan-50/60 p-3">
          <p className="text-xs font-bold text-fuchsia-800 flex items-center gap-1.5"><Play className="size-3.5"/>Tái dùng tất cả (Flow → ChatGPT → Gemini → Claude)</p>
          <p className="text-[10px] text-fuchsia-700/70">Chọn profile Google → lần lượt tái dùng cho từng provider. Đợi xong 1 provider mới chuyển sang provider tiếp theo.</p>
          {reuseAllStep && <div className="flex items-center gap-2 text-[11px] text-fuchsia-800"><LoaderCircle className="size-3 animate-spin"/>{reuseAllStep}</div>}
          <ReuseProfilePicker cs={cs} onReuse={reuseAll}/>
        </div>

      </CardContent>
    </Card>
  );
}
