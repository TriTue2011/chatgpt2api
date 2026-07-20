"use client";

import { useState, useEffect } from "react";
import { Plug, Save, LoaderCircle, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { updateSettingsConfig } from "@/lib/api";
import { httpRequest } from "@/lib/request";
import { useSettingsStore } from "../store";

export function CodexOnboardCard() {
  const config = useSettingsStore((state) => state.config);
  const setField = useSettingsStore((state) => state.setField);
  const [csUrl, setCsUrl] = useState("/api/captcha");
  const [csApiKey, setCsApiKey] = useState("");
  const [gmailEmail, setGmailEmail] = useState("");
  const [gmailAppPassword, setGmailAppPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);

  useEffect(() => {
    // Prefer server config (T3 recovery reads these); fall back to localStorage
    const fromCfgEmail = String((config as any)?.codex_imap_gmail_email || "");
    const fromCfgPass = String((config as any)?.codex_imap_gmail_app_password || "");
    setGmailEmail(fromCfgEmail || localStorage.getItem("codex_gmail_email") || "");
    setGmailAppPassword(fromCfgPass || localStorage.getItem("codex_gmail_pass") || "");

    // Get captcha-solver info
    const provs = config?.providers || {};
    const cgFree = provs.chatgpt_free || {};
    const flow = provs.flow || {};
    setCsUrl("/api/captcha");
    setCsApiKey(cgFree.captcha_solver_api_key || flow.captcha_solver_api_key || "");
  }, [config]);

  async function saveSettings() {
    setSaveLoading(true);
    try {
      // Persist shared IMAP so T3 auto-recovery uses the same credentials as batch UI
      setField("codex_imap_gmail_email", gmailEmail.trim());
      setField("codex_imap_gmail_app_password", gmailAppPassword.trim());
      localStorage.setItem("codex_gmail_email", gmailEmail.trim());
      localStorage.setItem("codex_gmail_pass", gmailAppPassword.trim());
      const next = {
        ...(config || {}),
        codex_auto_list: (config as any)?.codex_auto_list,
        codex_imap_gmail_email: gmailEmail.trim(),
        codex_imap_gmail_app_password: gmailAppPassword.trim(),
      };
      await updateSettingsConfig(next as any);
      toast.success("Đã lưu danh sách Codex + IMAP dùng chung");
    } catch (e: any) {
      toast.error(`Lỗi lưu cấu hình: ${e.message}`);
    } finally {
      setSaveLoading(false);
    }
  }

  async function startBatchLogin() {
    const listStr = String(config?.codex_auto_list || "");
    const lines = listStr.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length === 0) {
      toast.error("Vui lòng nhập ít nhất 1 tài khoản vào danh sách");
      return;
    }
    
    setIsSubmitting(true);
    let successCount = 0;
    let failCount = 0;

    // Open NoVNC for monitoring
    const noVncUrl = `${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`;
    window.open(noVncUrl, "_blank", "noopener,width=1024,height=720");
    
    try {
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const parts = line.includes('|') ? line.split('|') : line.split(':');
        const email = parts[0];
        const pass = parts[1];
        let imapEmail = parts[2] || gmailEmail;
        let imapPass = parts[3] || gmailAppPassword;

        if (!email || !pass) {
          toast.error(`Định dạng lỗi dòng ${i + 1}: ${line}`);
          failCount++;
          continue;
        }

        if (!imapEmail || !imapPass) {
          toast.error(`Thiếu cấu hình IMAP cho dòng ${i + 1}: ${email}. Vui lòng điền IMAP chung hoặc trên từng dòng.`);
          failCount++;
          continue;
        }

        toast.info(`[${i + 1}/${lines.length}] Đang xử lý: ${email}...`);
        
        try {
          const data = await httpRequest<any>("/api/oauth/codex/start");
          const auth_url = data?.auth_url;
          if (!auth_url) throw new Error("Lỗi API tạo Auth URL");

          const res = await fetch(`${csUrl}/v1/codex-onboard`, {
            method: "POST",
            headers: { "Authorization": `Bearer ${csApiKey}`, "Content-Type": "application/json" },
            body: JSON.stringify({
              auth_url,
              github_email: email.trim(),
              github_password: pass.trim(),
              gmail_email: imapEmail.trim(),
              gmail_app_password: imapPass.trim()
            }),
          });
          const rData = await res.json();
          if (rData.state !== "success" || !rData.redirect_url) {
            throw new Error(rData.error || "Playwright thất bại");
          }

          await httpRequest("/api/oauth/codex/exchange", { method: "POST", body: { redirect_url: rData.redirect_url } });
          toast.success(`Thành công tài khoản: ${email}!`);
          successCount++;
        } catch (err) {
          toast.error(`Lỗi ${email}: ${err instanceof Error ? err.message : String(err)}`);
          failCount++;
        }
      }
      
      toast.success(`Hoàn tất Auto-Login! Thành công: ${successCount}, Thất bại: ${failCount}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Xác thực thất bại toàn cục");
    } finally { 
      setIsSubmitting(false); 
    }
  }

  return (
    <Card className="rounded-3xl border-[var(--border)]/80 bg-[var(--muted)]/30">
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-col gap-2">
          <label className="text-[11px] font-semibold text-[var(--foreground)] flex items-center gap-1.5">
            <Plug className="size-3.5" /> Danh sách Tài khoản Codex (Tự động Đăng nhập Hàng loạt)
          </label>
          <Textarea
            value={String(config?.codex_auto_list || "")}
            onChange={(event) => setField("codex_auto_list", event.target.value)}
            placeholder="Ví dụ:&#10;acc1@outlook.com|pass1|receiver1@gmail.com|apppass1&#10;acc2@outlook.com|pass2|receiver2@gmail.com|apppass2"
            className="min-h-[160px] rounded-xl border-[var(--border)] bg-[var(--card)] font-mono text-xs"
          />
          <p className="text-[10px] text-[var(--muted-foreground)]">
            Cú pháp: <code className="bg-[var(--secondary)] px-1 py-0.5 rounded text-[var(--foreground)]">codex_email|codex_pass</code>
            {" "}(IMAP chung bên dưới). Tuỳ chọn: <code className="bg-[var(--secondary)] px-1 py-0.5 rounded text-[var(--foreground)]">|imap_email|imap_app_pass</code> nếu 1 dòng cần IMAP riêng.
            <br />
            <strong className="text-foreground">Outlook/Hotmail:</strong> khi Microsoft hỏi mật khẩu, bot
            bấm <em>Đăng nhập bằng mã dùng một lần</em> rồi lấy mã từ <strong>IMAP Gmail dùng chung</strong>
            (forward mail Outlook → Gmail). Không gõ mật khẩu Microsoft nếu có lựa chọn OTC.
            <br />
            Acc đã có refresh token: hệ thống ưu tiên tái sử dụng (bỏ qua OTP khi được).
          </p>
        </div>

        <div className="rounded-xl border border-blue-200 bg-blue-50/50 p-4 space-y-3">
          <p className="text-[11px] font-semibold text-blue-900">Cấu hình IMAP Gmail (Dùng chung — bắt buộc cho mã dùng một lần Microsoft / OpenAI / GitHub)</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="text-[10px] text-blue-800">Email Gmail IMAP</label>
              <Input 
                placeholder="example@gmail.com" 
                value={gmailEmail} 
                onChange={e => {
                  setGmailEmail(e.target.value);
                  localStorage.setItem("codex_gmail_email", e.target.value);
                  setField("codex_imap_gmail_email", e.target.value);
                }} 
                className="mt-1 h-8 rounded-lg text-xs"
              />
            </div>
            <div>
              <label className="text-[10px] text-blue-800">App Password Gmail</label>
              <Input 
                type="text" 
                placeholder="abcd efgh ijkl mnop" 
                value={gmailAppPassword} 
                onChange={e => {
                  setGmailAppPassword(e.target.value);
                  localStorage.setItem("codex_gmail_pass", e.target.value);
                  setField("codex_imap_gmail_app_password", e.target.value);
                }} 
                className="mt-1 h-8 rounded-lg text-xs"
              />
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-2">
          <Button
            size="sm"
            variant="outline"
            className="h-9 rounded-lg text-xs border-[var(--border)]"
            onClick={saveSettings}
            disabled={saveLoading}
          >
            {saveLoading ? <LoaderCircle className="mr-1 size-3.5 animate-spin" /> : <Save className="mr-1 size-3.5" />}
            Lưu danh sách
          </Button>

          <Button
            className="h-9 rounded-lg bg-gradient-to-r from-blue-600 to-cyan-600 px-4 text-xs font-bold text-white hover:from-blue-700 hover:to-cyan-700 shadow-md shadow-blue-200"
            onClick={startBatchLogin}
            disabled={isSubmitting}
          >
            {isSubmitting ? <><LoaderCircle className="mr-2 size-3.5 animate-spin" /> Đang chạy Auto-Login...</> : "🚀 Bắt đầu Đăng nhập Hàng loạt"}
          </Button>

          <Button
            className="h-9 rounded-lg border border-blue-200 bg-[var(--card)] px-3 text-xs text-blue-700 hover:bg-blue-50 ml-auto"
            onClick={() => {
              const noVncUrl = `${window.location.protocol}//${window.location.hostname}:6080/vnc.html?autoconnect=1`;
              window.open(noVncUrl, "_blank");
            }}
          >
            <ExternalLink className="mr-1 size-3.5" /> Theo dõi VNC
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
