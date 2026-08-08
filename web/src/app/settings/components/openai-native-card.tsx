"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Eye, EyeOff, KeyRound, LoaderCircle, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { SavedAccountsSelect } from "@/components/saved-accounts-select";

/**
 * Đăng nhập ChatGPT bằng TÀI KHOẢN OPENAI GỐC — email + mật khẩu + TOTP.
 *
 * Khác thẻ "ChatGPT via Google OAuth" ngay bên cạnh: thẻ đó bấm "Tiếp tục với
 * Google" và chỉ phục vụ tài khoản Google. Thẻ này điền thẳng vào form của
 * OpenAI, cho tài khoản mua theo lô.
 *
 * ĐUÔI EMAIL KHÔNG QUYẾT ĐỊNH DÙNG THẺ NÀO. Đo thật 08/08/2026: một địa chỉ
 * @gmail.com vẫn đi qua form của OpenAI (ô "Địa chỉ email" → "Nhập mật khẩu của
 * bạn" → "Kiểm tra ứng dụng xác thực"), không chạm Google lần nào. Cái quyết
 * định là tài khoản đó đăng nhập bằng form nào, không phải nó mang tên miền gì.
 */

type TrangThai = {
  profile: string;
  email: string;
  state: "none" | "starting" | "running" | "need_code" | "success" | "failed";
  message: string;
  error?: string | null;
  access_token_preview?: string;
  captured_email?: string;
  has_token?: boolean;
  elapsed_sec?: number;
};

function _profileTu(email: string): string {
  const local = (email.split("@")[0] || "default").replace(/[^a-z0-9-]/gi, "-");
  return `openai-${local}`;
}

export function OpenAINativeCard() {
  const [cs, setCs] = useState({ url: "/api/captcha", apiKey: "" });
  const [draft, setDraft] = useState({ email: "", password: "", totpSecret: "" });
  const [hienMatKhau, setHienMatKhau] = useState(false);
  const [dangChay, setDangChay] = useState(false);
  const [tt, setTt] = useState<TrangThai | null>(null);
  const [maTay, setMaTay] = useState("");
  const [chon, setChon] = useState("");
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const d = await request.get("/api/settings");
        const flow = ((d.data as any)?.config?.providers || {}).flow || {};
        setCs({ url: flow.captcha_solver_url || "/api/captcha",
                apiKey: flow.captcha_solver_api_key || "" });
      } catch { /* để mặc định */ }
    })();
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, []);

  const dungPoll = useCallback(() => {
    if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const batDau = async () => {
    if (!draft.email.trim() || !draft.password) {
      toast.error("Cần email + mật khẩu");
      return;
    }
    const profile = _profileTu(draft.email);
    dungPoll();
    setDangChay(true);
    setTt(null);
    try {
      const r = await fetch(`${cs.url}/v1/openai-native/onboard`, {
        method: "POST",
        headers: { Authorization: `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          profile,
          email: draft.email.trim(),
          password: draft.password,
          totp_secret: draft.totpSecret.trim(),
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch (e: any) {
      toast.error(`Không khởi động được: ${e?.message || e}`);
      setDangChay(false);
      return;
    }

    pollRef.current = window.setInterval(async () => {
      try {
        const r = await fetch(
          `${cs.url}/v1/openai-native/${encodeURIComponent(profile)}/onboard-status`,
          { headers: { Authorization: `Bearer ${cs.apiKey}` } });
        const s = (await r.json()) as TrangThai;
        setTt(s);
        if (s.state === "success") {
          dungPoll();
          setDangChay(false);
          // Token về rồi thì đẩy thẳng vào pool — nếu không thì người dùng thấy
          // "thành công" mà pool vẫn trống, và không hiểu còn thiếu bước nào.
          try {
            const t = await fetch(
              `${cs.url}/v1/openai-native/${encodeURIComponent(profile)}/token`,
              { headers: { Authorization: `Bearer ${cs.apiKey}` } });
            const d = await t.json();
            if (d?.access_token) {
              await request.post("/api/accounts", { tokens: [d.access_token] });
              toast.success(`Đã thêm ${d.email || draft.email} vào pool`);
            }
          } catch {
            toast.error("Đăng nhập xong nhưng chưa đẩy được token vào pool");
          }
        } else if (s.state === "failed") {
          dungPoll();
          setDangChay(false);
          toast.error(s.error || "Đăng nhập thất bại");
        }
      } catch { /* mất mạng một nhịp — vòng sau thử lại */ }
    }, 3000);
  };

  const guiMa = async () => {
    if (!maTay.trim() || !tt) return;
    try {
      await fetch(
        `${cs.url}/v1/openai-native/${encodeURIComponent(tt.profile)}/onboard-2fa-code`,
        { method: "POST",
          headers: { Authorization: `Bearer ${cs.apiKey}`, "Content-Type": "application/json" },
          body: JSON.stringify({ code: maTay.trim() }) });
      setMaTay("");
      toast.success("Đã gửi mã");
    } catch (e: any) {
      toast.error(`Gửi mã lỗi: ${e?.message || e}`);
    }
  };

  return (
    <Card className="rounded-[16px] card-3d card-tint-emerald">
      <CardContent className="p-5 space-y-3">
        <div className="flex items-center gap-2">
          <KeyRound className="size-4 text-emerald-700" />
          <h3 className="text-sm font-semibold text-emerald-900">
            ChatGPT bằng tài khoản OpenAI gốc
          </h3>
        </div>
        <p className="text-[11px] text-[var(--muted-foreground)]">
          Dùng khi tài khoản có <b>mật khẩu của chính OpenAI</b> — gõ email vào ô
          &quot;Địa chỉ email&quot; trên trang đăng nhập ChatGPT rồi sang trang mật khẩu,
          không bấm &quot;Tiếp tục với Google&quot;. Đuôi email không quyết định: cả
          <code className="mx-1">@gmail.com</code> lẫn <code className="mx-1">@icloud.com</code>
          đều có thể là loại này. Nếu tài khoản đăng nhập bằng Google thì dùng thẻ
          &quot;ChatGPT via Google OAuth&quot; bên cạnh.
        </p>

        <SavedAccountsSelect
          csUrl={cs.url}
          csApiKey={cs.apiKey}
          selected={chon}
          onSelect={(email, acct) => {
            setChon(email);
            setDraft({ email: acct.email, password: acct.password,
                       totpSecret: acct.totp_secret || "" });
          }}
          disabled={dangChay}
        />

        <div className="grid gap-2 sm:grid-cols-2">
          <div>
            <label className="text-[11px] text-[var(--muted-foreground)]">Email đăng nhập</label>
            <Input
              value={draft.email}
              onChange={(e) => setDraft({ ...draft, email: e.target.value })}
              placeholder="you@gmail.com hoặc you@icloud.com"
              className="mt-1 h-8 rounded-lg text-xs font-mono"
              autoComplete="off"
              disabled={dangChay}
            />
          </div>
          <div>
            <label className="text-[11px] text-[var(--muted-foreground)]">Mật khẩu OpenAI</label>
            <div className="relative">
              <Input
                type={hienMatKhau ? "text" : "password"}
                value={draft.password}
                onChange={(e) => setDraft({ ...draft, password: e.target.value })}
                placeholder="••••••••"
                className="mt-1 h-8 rounded-lg text-xs font-mono pr-8"
                autoComplete="off"
                disabled={dangChay}
              />
              <button
                type="button"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
                onClick={() => setHienMatKhau(!hienMatKhau)}
                tabIndex={-1}
              >
                {hienMatKhau ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
              </button>
            </div>
          </div>
        </div>

        <div>
          <label className="text-[11px] text-[var(--muted-foreground)]">
            Hạt giống TOTP (bỏ trống nếu tài khoản không bật 2FA)
          </label>
          <Input
            value={draft.totpSecret}
            onChange={(e) => setDraft({ ...draft, totpSecret: e.target.value })}
            placeholder="xxxx xxxx xxxx xxxx xxxx xxxx xxxx xxxx"
            className="mt-1 h-8 rounded-lg text-xs font-mono"
            autoComplete="off"
            disabled={dangChay}
          />
          <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
            Máy chủ tự sinh mã 6 số từ hạt giống này — không cần trang sinh mã bên ngoài.
            Dán hạt giống lên trang lạ là trao cho họ quyền sinh mã vĩnh viễn.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button onClick={batDau} disabled={dangChay} className="h-8 rounded-lg text-xs">
            {dangChay ? <LoaderCircle className="mr-2 size-3.5 animate-spin" /> : null}
            Đăng nhập và thêm vào pool
          </Button>
          {dangChay && (
            <Button
              variant="secondary"
              className="h-8 rounded-lg text-xs"
              onClick={() => { dungPoll(); setDangChay(false); }}
            >
              <X className="mr-1 size-3.5" /> Ngừng theo dõi
            </Button>
          )}
        </div>

        {tt && (
          <div className="rounded-lg bg-[var(--secondary)]/50 px-3 py-2 space-y-1">
            <p className="text-[11px] text-[var(--foreground)]">
              <b>{tt.state}</b> — {tt.message}
              {tt.elapsed_sec ? ` (${tt.elapsed_sec}s)` : ""}
            </p>
            {tt.error && <p className="text-[11px] text-rose-600">{tt.error}</p>}
            {tt.state === "need_code" && (
              <div className="flex items-center gap-2 pt-1">
                <Input
                  value={maTay}
                  onChange={(e) => setMaTay(e.target.value)}
                  placeholder="mã 6 số"
                  className="h-8 w-32 rounded-lg text-xs font-mono"
                />
                <Button onClick={guiMa} className="h-8 rounded-lg text-xs">Gửi mã</Button>
              </div>
            )}
            {tt.state === "failed" && (
              <p className="text-[10px] text-[var(--muted-foreground)]">
                Mở màn hình noVNC (cổng 6080) để xem trang đang dừng ở đâu — bộ chọn
                trên trang đăng nhập của OpenAI đổi theo bản dựng.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
