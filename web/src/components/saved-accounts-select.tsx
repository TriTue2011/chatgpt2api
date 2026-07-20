"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

type SavedAccount = {
  id: number;
  email: string;
  totp_secret: string;
  label: string;
};

type Props = {
  csUrl: string;
  csApiKey: string;
  selected: string;
  onSelect: (email: string, account: { email: string; password: string; totp_secret: string }) => void;
  disabled?: boolean;
  refreshKey?: number;
};

const STORAGE_KEY = "chatgpt2api_saved_accounts_cache";

// Hide junk rows (empty / non-email like "" or "a") so only real accounts show.
function isValidAccount(a: SavedAccount): boolean {
  return !!a && typeof a.email === "string" && a.email.trim().length > 2;
}

function cacheAccounts(accounts: SavedAccount[]) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(accounts)); } catch {}
}

function loadCached(): SavedAccount[] {
  try { return (JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]") as SavedAccount[]).filter(isValidAccount); } catch { return []; }
}

export function SavedAccountsSelect({ csUrl, csApiKey, selected, onSelect, disabled, refreshKey }: Props) {
  const [accounts, setAccounts] = useState<SavedAccount[]>(loadCached());

  useEffect(() => {
    void fetchAccounts();
    // csApiKey included: it loads from config AFTER first render while csUrl is
    // now a constant ("/api/captcha"), so without it the list never re-fetches
    // with a valid token and stays empty.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [csUrl, csApiKey, refreshKey]);

  async function fetchAccounts() {
    try {
      const res = await fetch(`${csUrl}/v1/accounts/saved`, {
        headers: { Authorization: `Bearer ${csApiKey}` },
      });
      if (res.ok) {
        const data = (await res.json() as SavedAccount[]).filter(isValidAccount);
        setAccounts(data);
        cacheAccounts(data);
      }
    } catch { /* ignore */ }
  }

  async function loadAccount(email: string) {
    if (!email) {
      onSelect("", { email: "", password: "", totp_secret: "" });
      return;
    }
    try {
      const res = await fetch(`${csUrl}/v1/accounts/saved/${encodeURIComponent(email)}`, {
        headers: { Authorization: `Bearer ${csApiKey}` },
      });
      if (res.ok) {
        const acct = await res.json();
        onSelect(email, acct);
        return;
      }
      // Stale cache: dropdown showed an account that no longer exists on the
      // server (404) or auth changed. Don't fail silently — warn + reset the
      // selection + refresh the list so it self-heals.
      onSelect("", { email: "", password: "", totp_secret: "" });
      if (res.status === 404) {
        toast.error("Tài khoản này không còn trên server — đã làm mới danh sách");
      } else {
        toast.error(`Không load được tài khoản (HTTP ${res.status})`);
      }
      void fetchAccounts();
    } catch { toast.error("Không load được tài khoản (mạng/captcha-solver)"); }
  }

  async function deleteAccount(email: string) {
    try {
      await fetch(`${csUrl}/v1/accounts/saved/${encodeURIComponent(email)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${csApiKey}` },
      });
      toast.success("Đã xóa");
      if (selected === email) {
        onSelect("", { email: "", password: "", totp_secret: "" });
      }
      fetchAccounts();
    } catch { toast.error("Lỗi xóa"); }
  }

  return (
    <div className="flex items-end gap-1.5">
      <div className="flex-1">
        <label className="text-[11px] text-[var(--muted-foreground)]">Tai khoan da luu</label>
        <select
          value={selected}
          onChange={(e) => loadAccount(e.target.value)}
          className="mt-1 h-8 w-full rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs font-mono px-2 text-[var(--foreground)]"
          disabled={disabled}
        >
          <option value="">-- Chon tai khoan ({accounts.length}) --</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.email}>{a.label || a.email}</option>
          ))}
        </select>
      </div>
      {selected && (
        <Button
          size="sm"
          variant="ghost"
          className="h-8 px-2 text-[10px] text-rose-500 hover:bg-rose-50"
          onClick={() => deleteAccount(selected)}
        >
          <Trash2 className="size-3" />
        </Button>
      )}
    </div>
  );
}
