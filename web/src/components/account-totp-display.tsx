"use client";

import { useEffect, useState, useCallback } from "react";
import { Shield, Eye, EyeOff, Copy } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { request } from "@/lib/request";

const STORAGE_KEY = "chatgpt2api_totp_secrets";

/**
 * Hạt giống TOTP KHÔNG còn được lưu ở trình duyệt.
 *
 * Hạt giống sinh ra mọi mã 6 số từ nay về sau; mã 6 số thì chết sau 30 giây.
 * Giữ hạt giống trong `localStorage` nghĩa là một lỗ XSS lấy được yếu tố thứ
 * hai của tài khoản Google — vĩnh viễn, và không cách nào thu hồi ngoài việc
 * đăng ký lại 2FA. Nay máy chủ giữ hạt giống (đã mã hoá AES-256-GCM trong
 * `accounts.db`) và chỉ trả MÃ HIỆN TẠI.
 *
 * Hai hàm dưới đây chỉ còn để DỌN dữ liệu cũ khỏi máy người dùng.
 */
function loadSecrets(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch { return {}; }
}

/** Xoá hạt giống còn sót lại từ bản cũ. Gọi khi đã lấy được mã từ máy chủ. */
export function donHatGiongCu(email: string) {
  try {
    const secrets = loadSecrets();
    if (!(email in secrets)) return;
    delete secrets[email];
    if (Object.keys(secrets).length) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(secrets));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch { /* chế độ riêng tư chặn storage */ }
}

export function AccountTotpDisplay({ email, label }: { email: string; label?: string }) {
  const [secret, setSecret] = useState("");
  const [showInput, setShowInput] = useState(false);
  const [code, setCode] = useState("");
  const [remaining, setRemaining] = useState(30);

  const refresh = useCallback(async () => {
    // Chỉ lấy MÃ dùng một lần do máy chủ sinh. Fallback về hạt giống cũ ở
    // localStorage vừa kéo dài cửa sổ XSS, vừa làm mã ngừng cập nhật sau reload
    // vì state `secret` rỗng dù server đã có seed.
    try {
      const r = await request.get(
        `/api/captcha/v1/accounts/saved/${encodeURIComponent(email)}/totp`);
      const d = r.data as { code?: string; seconds_remaining?: number };
      if (d?.code) {
        setCode(d.code);
        setRemaining(Number(d.seconds_remaining ?? 30));
        donHatGiongCu(email);
        return;
      }
    } catch { /* chưa có seed trên máy chủ hoặc request lỗi */ }
    setCode("");
  }, [email]);

  const migrateLegacySeed = useCallback(async () => {
    // Bản cũ có thể chỉ giữ seed ở localStorage. Di trú nó thẳng vào server
    // rồi mới xóa; tuyệt đối không đưa vào state hay dùng để tự sinh mã ở
    // browser. Nếu server chưa nhận được thì giữ seed cũ để lần mở sau thử lại,
    // thay vì làm người dùng mất phương án đăng nhập.
    const seed = String(loadSecrets()[email] || "").trim();
    if (!seed) return;
    try {
      // Máy chủ đã có hạt giống thì bản trong trình duyệt là bản CŨ — đẩy lên
      // là ghi đè hạt giống đang dùng được, tức mất phương án đăng nhập hai
      // lớp. Chỉ di trú khi máy chủ chưa có gì.
      const daCo = await request.get(
        `/api/captcha/v1/accounts/saved/${encodeURIComponent(email)}/totp`);
      if ((daCo.data as { code?: string })?.code) {
        donHatGiongCu(email);
        return;
      }
    } catch { /* máy chủ chưa có seed hoặc lỗi mạng → thử di trú bên dưới */ }
    try {
      await request.put(
        `/api/captcha/v1/accounts/saved/${encodeURIComponent(email)}/totp`,
        {totp_secret: seed},
      );
      donHatGiongCu(email);
      await refresh();
    } catch {
      /* giữ dữ liệu cũ để có thể di trú lại khi server hoạt động */
    }
  }, [email, refresh]);

  useEffect(() => {
    // Component được tái sử dụng khi người dùng mở một account khác. Không
    // giữ seed đang gõ của account trước, nếu không một lần bấm Lưu có thể ghi
    // nhầm hạt giống sang email mới.
    setSecret("");
    setShowInput(false);
    void migrateLegacySeed();
  }, [migrateLegacySeed]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // Gửi hạt giống LÊN MÁY CHỦ (nơi nó được mã hoá), không lưu ở trình duyệt.
  const datTotpTrenMayChu = async (seed: string) => {
    await request.put(
      `/api/captcha/v1/accounts/saved/${encodeURIComponent(email)}/totp`,
      {totp_secret: seed});
  };

  const handleSave = async () => {
    try {
      await datTotpTrenMayChu(secret.trim());
      donHatGiongCu(email);
      setSecret("");
      setShowInput(false);
      toast.success("Đã lưu TOTP secret trên máy chủ");
      void refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Không lưu được TOTP secret");
    }
  };

  const handleClear = async () => {
    try {
      await datTotpTrenMayChu("");
      donHatGiongCu(email);
      setSecret("");
      setCode("");
      toast.success("Đã xóa TOTP secret");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Không xoá được TOTP secret");
    }
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
