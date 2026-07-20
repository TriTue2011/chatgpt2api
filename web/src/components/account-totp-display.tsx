"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Shield, Eye, EyeOff, Copy } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { generateTotpCode, totpSecondsRemaining } from "@/lib/totp";

const STORAGE_KEY = "chatgpt2api_totp_secrets";

function loadSecrets(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch { return {}; }
}

function saveSecrets(secrets: Record<string, string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(secrets));
}

export function getTotpSecret(email: string): string {
  const secrets = loadSecrets();
  return secrets[email] || "";
}

export function setTotpSecret(email: string, secret: string) {
  const secrets = loadSecrets();
  if (secret.trim()) {
    secrets[email] = secret.trim();
  } else {
    delete secrets[email];
  }
  saveSecrets(secrets);
}

export function AccountTotpDisplay({ email, label }: { email: string; label?: string }) {
  const [secret, setSecret] = useState("");
  const [showInput, setShowInput] = useState(false);
  const [code, setCode] = useState("");
  const [remaining, setRemaining] = useState(30);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    const saved = getTotpSecret(email);
    if (saved) setSecret(saved);
  }, [email]);

  const refresh = useCallback(async (sec: string) => {
    if (!sec.trim()) { setCode(""); return; }
    try {
      setCode(await generateTotpCode(sec));
      setRemaining(totpSecondsRemaining());
    } catch { setCode(""); }
  }, []);

  useEffect(() => {
    if (!secret.trim()) { setCode(""); return; }
    void refresh(secret);
    timerRef.current = window.setInterval(() => { void refresh(secret); }, 5000);
    return () => { if (timerRef.current) window.clearInterval(timerRef.current); };
  }, [secret, refresh]);

  const handleSave = () => {
    setTotpSecret(email, secret);
    setShowInput(false);
    toast.success("Đã lưu TOTP secret");
  };

  const handleClear = () => {
    setTotpSecret(email, "");
    setSecret("");
    setCode("");
    toast.success("Đã xóa TOTP secret");
  };

  const copyCode = () => {
    if (code) {
      navigator.clipboard.writeText(code).then(() => toast.success("Đã copy mã")).catch(() => {});
    }
  };

  const displayLabel = label || email;

  return (
    <div className="rounded-xl border border-amber-200/60 bg-amber-50/40 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Shield className="size-3.5 text-amber-600" />
          <span className="text-[11px] font-semibold text-amber-800">Authenticator</span>
          {code && (
            <span className="text-[10px] text-amber-500">({displayLabel})</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {secret ? (
            <Button size="sm" variant="ghost" className="h-6 px-1.5 text-[10px] text-amber-600 hover:text-amber-800" onClick={() => setShowInput(!showInput)}>
              {showInput ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
            </Button>
          ) : (
            <Button size="sm" variant="ghost" className="h-6 px-1.5 text-[10px] text-amber-500 hover:text-amber-700" onClick={() => setShowInput(!showInput)}>
              + Set TOTP
            </Button>
          )}
        </div>
      </div>

      {showInput && (
        <div className="space-y-1.5">
          <Input
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder="xxxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx"
            className="h-7 rounded-lg border-amber-200 text-[11px] font-mono bg-[var(--card)]"
            autoComplete="off"
          />
          <div className="flex gap-1.5">
            <Button size="sm" className="h-6 rounded-md bg-amber-600 px-2 text-[10px] text-white hover:bg-amber-700" onClick={handleSave}>
              Lưu
            </Button>
            {secret && (
              <Button size="sm" variant="ghost" className="h-6 rounded-md px-2 text-[10px] text-rose-500 hover:bg-rose-50" onClick={handleClear}>
                Xóa
              </Button>
            )}
          </div>
        </div>
      )}

      {code && (
        <div className="flex items-center gap-2 pt-0.5">
          <span className="text-[10px] text-amber-600">Ma hien tai:</span>
          <button
            onClick={copyCode}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-mono text-sm font-bold tracking-widest hover:bg-amber-200 transition-colors cursor-pointer"
            title="Copy ma"
          >
            {code}
            <Copy className="size-2.5 text-amber-500" />
          </button>
          <span className="text-[10px] text-amber-400 tabular-nums">{remaining}s</span>
        </div>
      )}
    </div>
  );
}
