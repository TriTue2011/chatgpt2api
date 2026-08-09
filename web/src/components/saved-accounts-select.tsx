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
  /**
   * `password` và `totp_secret` LUÔN rỗng kể từ 08/08/2026 — máy chủ không trả
   * credential về trình duyệt nữa. Giữ hai trường để không phải sửa mọi nơi
   * gọi; dùng `has_password`/`has_totp` khi cần biết đã cấu hình hay chưa.
   */
  onSelect: (email: string, account: {
    email: string; password: string; totp_secret: string;
    has_password?: boolean; has_totp?: boolean;
  }) => void;
  disabled?: boolean;
  refreshKey?: number;
  /**
   * Kho credential nào: "google" (mặc định) hay "openai". Hai kho TÁCH BIỆT —
   * cùng một địa chỉ email có thể nằm ở cả hai với hai mật khẩu khác nhau.
   * Không truyền đúng thì thẻ OpenAI gốc hiện tài khoản Google và người dùng
   * chọn nhầm, rồi luồng đăng nhập nhận về mật khẩu của dịch vụ kia.
   */
  loai?: "google" | "openai";
};

// Cache PHẢI tách theo kho: dùng chung một khoá thì thẻ OpenAI gốc chớp hiện
// danh sách tài khoản Google ở lần vẽ đầu (trước khi fetch về), người dùng kịp
// bấm là chọn nhầm sang kho kia.
const STORAGE_KEY = "chatgpt2api_saved_accounts_cache";
const khoaCache = (loai: string) => `${STORAGE_KEY}_${loai}`;

// Hide junk rows (empty / non-email like "" or "a") so only real accounts show.
function isValidAccount(a: SavedAccount): boolean {
  return !!a && typeof a.email === "string" && a.email.trim().length > 2;
}

function cacheAccounts(loai: string, accounts: SavedAccount[]) {
  try { localStorage.setItem(khoaCache(loai), JSON.stringify(accounts)); } catch {}
}

function loadCached(loai: string): SavedAccount[] {
  try { return (JSON.parse(localStorage.getItem(khoaCache(loai)) || "[]") as SavedAccount[]).filter(isValidAccount); } catch { return []; }
}

export function SavedAccountsSelect({ csUrl, csApiKey, selected, onSelect, disabled, refreshKey, loai = "google" }: Props) {
  const [accounts, setAccounts] = useState<SavedAccount[]>(() => loadCached(loai));
  // Cờ "kho đang giữ gì" của tài khoản đang chọn. Server chỉ trả has_password/
  // has_totp — không có cách nào xem giá trị thật từ trình duyệt.
  const [flags, setFlags] = useState<{ pw: boolean; totp: boolean } | null>(null);
  // Mã TOTP 6 số sinh TRÊN MÁY CHỦ từ hạt giống trong kho — giá trị dùng một
  // lần, hạt giống không rời solver. So với app Authenticator trên điện thoại:
  // trùng số nghĩa là hạt giống lưu đúng.
  const [maTotp, setMaTotp] = useState<{ code: string; remaining: number } | null>(null);

  // Mã chết theo cửa sổ 30 giây: đếm ngược mỗi giây, hết giờ tự xin mã mới thay
  // vì tiếp tục hiển thị một con số đã vô dụng.
  useEffect(() => {
    if (!maTotp) return;
    const t = window.setTimeout(() => {
      if (maTotp.remaining <= 1) void fetchTotpCode();
      else setMaTotp({ code: maTotp.code, remaining: maTotp.remaining - 1 });
    }, 1000);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maTotp]);

  async function fetchTotpCode() {
    if (!selected) return;
    try {
      const res = await fetch(`${csUrl}/v1/accounts/saved/${encodeURIComponent(selected)}/totp?loai=${loai}`, {
        headers: { Authorization: `Bearer ${csApiKey}` },
      });
      const d = await res.json().catch(() => null);
      if (res.ok && d?.code) {
        setMaTotp({ code: String(d.code), remaining: Number(d.seconds_remaining) || 30 });
        return;
      }
      setMaTotp(null);
      toast.error(String(d?.detail || `Không lấy được mã TOTP (HTTP ${res.status})`));
    } catch {
      setMaTotp(null);
      toast.error("Không lấy được mã TOTP (mạng/captcha-solver)");
    }
  }

  useEffect(() => {
    void fetchAccounts();
    // csApiKey included: it loads from config AFTER first render while csUrl is
    // now a constant ("/api/captcha"), so without it the list never re-fetches
    // with a valid token and stays empty.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [csUrl, csApiKey, refreshKey, loai]);

  async function fetchAccounts() {
    try {
      const res = await fetch(`${csUrl}/v1/accounts/saved?loai=${loai}`, {
        headers: { Authorization: `Bearer ${csApiKey}` },
      });
      if (res.ok) {
        const data = (await res.json() as SavedAccount[]).filter(isValidAccount);
        setAccounts(data);
        cacheAccounts(loai, data);
      }
    } catch { /* ignore */ }
  }

  async function loadAccount(email: string) {
    setFlags(null);
    setMaTotp(null);
    if (!email) {
      onSelect("", { email: "", password: "", totp_secret: "" });
      return;
    }
    try {
      // KHÔNG lấy credential về trình duyệt nữa. Endpoint này giờ chỉ trả
      // email/nhãn/`has_password`/`has_totp` — mật khẩu và hạt giống TOTP nằm
      // trong `accounts.db` đã mã hoá và không rời khỏi máy chủ.
      //
      // Đăng nhập đi đường `/v1/session/auto-login-saved`: nó nhận tên profile
      // rồi TỰ tra credential. Form vì thế để trống ô mật khẩu — đó là chủ ý,
      // không phải thiếu dữ liệu.
      const res = await fetch(`${csUrl}/v1/accounts/saved/${encodeURIComponent(email)}?loai=${loai}`, {
        headers: { Authorization: `Bearer ${csApiKey}` },
      });
      if (res.ok) {
        const acct = await res.json();
        setFlags({ pw: Boolean(acct?.has_password), totp: Boolean(acct?.has_totp) });
        onSelect(email, {
          email: String(acct?.email || email),
          password: "",
          totp_secret: "",
          has_password: Boolean(acct?.has_password),
          has_totp: Boolean(acct?.has_totp),
        });
        return;
      }
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
      await fetch(`${csUrl}/v1/accounts/saved/${encodeURIComponent(email)}?loai=${loai}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${csApiKey}` },
      });
      toast.success("Đã xóa");
      if (selected === email) {
        setFlags(null);
        setMaTotp(null);
        onSelect("", { email: "", password: "", totp_secret: "" });
      }
      fetchAccounts();
    } catch { toast.error("Lỗi xóa"); }
  }

  return (
    <div>
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
      {selected && flags && (
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px]">
          <span className={flags.pw ? "text-emerald-600" : "text-rose-500"}>
            🔑 {flags.pw ? "có mật khẩu" : "chưa có mật khẩu"}
          </span>
          <span className="text-[var(--muted-foreground)]">·</span>
          <span className={flags.totp ? "text-emerald-600" : "text-rose-500"}>
            🛡 {flags.totp ? "có TOTP" : "chưa có TOTP"}
          </span>
          {flags.totp && (
            <button
              type="button"
              className="text-blue-600 underline underline-offset-2 disabled:opacity-50"
              disabled={disabled}
              onClick={() => (maTotp ? setMaTotp(null) : void fetchTotpCode())}
            >
              {maTotp ? "Ẩn mã" : "Xem mã TOTP"}
            </button>
          )}
          {maTotp && (
            <>
              <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs font-bold tracking-widest text-amber-900">
                {maTotp.code}
              </span>
              <span className="text-[var(--muted-foreground)]">({maTotp.remaining}s)</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
