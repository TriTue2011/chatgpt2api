"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LoaderCircle, LockKeyhole, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { login } from "@/lib/api";
import { useRedirectIfAuthenticated } from "@/lib/use-auth-guard";
import { getDefaultRouteForRole, setStoredAuthSession } from "@/store/auth";

export default function LoginPage() {
  const router = useRouter();
  const [authKey, setAuthKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { isCheckingAuth } = useRedirectIfAuthenticated();

  const handleLogin = async () => {
    const normalizedAuthKey = authKey.trim();
    if (!normalizedAuthKey) {
      toast.error("Vui lòng nhập Mã khóa");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await login(normalizedAuthKey);
      await setStoredAuthSession({
        key: normalizedAuthKey,
        role: data.role,
        subjectId: data.subject_id,
        name: data.name,
      });
      router.replace(getDefaultRouteForRole(data.role));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Đăng nhập thất bại";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isCheckingAuth) {
    return (
      <div className="grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="relative grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
      {/* Mesh gold + blue */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 600px 400px at 20% 0%, rgba(212,175,55,0.12), transparent 60%), radial-gradient(ellipse 500px 400px at 90% 100%, rgba(56,189,248,0.08), transparent 55%)",
        }}
      />
      <Card
        className="relative w-full max-w-[440px] rounded-[24px] bg-[var(--card)]/95"
        style={{
          border: "1px solid color-mix(in srgb, var(--primary) 28%, transparent)",
          boxShadow: "0 28px 90px rgba(0,0,0,0.45), 0 0 0 1px rgba(212,175,55,0.08)",
        }}
      >
        <CardContent className="space-y-7 p-6 sm:p-8">
          <div className="space-y-4 text-center">
            <div
              className="mx-auto inline-flex size-14 items-center justify-center rounded-[18px]"
              style={{
                background: "linear-gradient(135deg, #D4AF37, #B8860B)",
                color: "#0a0a0a",
                boxShadow: "0 8px 24px rgba(212,175,55,0.35)",
              }}
            >
              <LockKeyhole className="size-5" />
            </div>
            <div className="space-y-2">
              <h1 className="text-3xl font-semibold tracking-tight gradient-text">Chào mừng trở lại</h1>
              <p className="text-sm leading-6 text-[var(--muted-foreground)]">
                Nhập Auth Key để mở dashboard, quản lý account pool và gọi OpenAI-compatible API.
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <label htmlFor="auth-key" className="block text-sm font-medium text-[var(--foreground)]">
              Mã khóa (Auth Key)
            </label>
            <div className="relative">
              <Input
                id="auth-key"
                type={showKey ? "text" : "password"}
                value={authKey}
                onChange={(event) => setAuthKey(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void handleLogin();
                  }
                }}
                placeholder="Nhập mã khóa của bạn"
                className="h-13 rounded-2xl border-[var(--border)] bg-[var(--card)] px-4 pr-12"
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                aria-label={showKey ? "Ẩn mã khóa" : "Hiện mã khóa"}
                title={showKey ? "Ẩn mã khóa" : "Hiện mã khóa"}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
              >
                {showKey ? <EyeOff className="size-[18px]" /> : <Eye className="size-[18px]" />}
              </button>
            </div>
          </div>

          <Button
            className="btn-gold h-13 w-full rounded-2xl text-[15px]"
            onClick={() => void handleLogin()}
            disabled={isSubmitting}
          >
            {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
            Đăng nhập
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
