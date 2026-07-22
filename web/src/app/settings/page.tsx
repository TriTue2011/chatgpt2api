"use client";

import { useEffect, useRef } from "react";
import { LoaderCircle, Settings, KeyRound, Cpu, Zap, Link, Archive, Plug, MessageCircle, Cloud, Volume2, GraduationCap } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { SettingsSection } from "@/components/settings-section";

import { BackupSettingsCard } from "./components/backup-settings-card";
import { HACard } from "./components/ha-card";
import { EmailCalendarCard } from "./components/email-calendar-card";
import { VoiceSpeakersCard } from "./components/voice-speakers-card";
import { TeacherSettingsCard } from "./components/teacher-settings-card";
import { PersonasCard } from "./components/personas-card";
import { TelegramCloudflareCard, CloudflareInfraCard } from "./components/telegram-cloudflare-card";
import { ConfigCard } from "./components/config-card";
import { GeminiCard } from "./components/gemini-card";
import { NvidiaNimCard } from "./components/nvidia-nim-card";
import { CustomProvidersCard } from "./components/custom-providers-card";
import { FlowCard } from "./components/flow-card";
import { ChatGPTOnboardCard } from "./components/chatgpt-onboard-card";
import { CodexOnboardCard } from "./components/codex-onboard-card";
import { GoogleProvidersCard } from "./components/google-providers-card";
import { ImportBrowserDialog } from "./components/import-browser-dialog";
import { SettingsHeader } from "./components/settings-header";
import { UserKeysCard } from "./components/user-keys-card";
import { useSettingsStore } from "./store";

function SettingsDataController() {
  const didLoadRef = useRef(false);
  const initialize = useSettingsStore((state) => state.initialize);
  const loadPools = useSettingsStore((state) => state.loadPools);
  const loadBackups = useSettingsStore((state) => state.loadBackups);
  const pools = useSettingsStore((state) => state.pools);
  const backupState = useSettingsStore((state) => state.backupState);

  useEffect(() => {
    if (didLoadRef.current) return;
    didLoadRef.current = true;
    void initialize();
  }, [initialize]);

  useEffect(() => {
    const hasRunningJobs = pools.some((pool) => {
      const status = pool.import_job?.status;
      return status === "pending" || status === "running";
    });
    if (!hasRunningJobs) return;
    const timer = window.setInterval(() => { void loadPools(true); }, 1500);
    return () => window.clearInterval(timer);
  }, [loadPools, pools]);

  useEffect(() => {
    if (!backupState?.running) return;
    const timer = window.setInterval(() => { void loadBackups(true); }, 3000);
    return () => window.clearInterval(timer);
  }, [backupState?.running, loadBackups]);

  return null;
}

function SettingsPageContent() {
  return (
    <>
      <SettingsDataController />
      <SettingsHeader />

      <section className="space-y-3">
        <SettingsSection
          title="Cấu hình hệ thống"
          description="Proxy, rate limit, tự động xóa tài khoản, system prompt, kiểm duyệt AI"
          icon={<Settings className="size-5" />}
        >
          <ConfigCard />
        </SettingsSection>

        <SettingsSection
          title="Gemini AI Studio"
          description="Google Gemini với Google Search — miễn phí 15 RPM, hỗ trợ nhiều API key"
          icon={<span className="text-lg">🔮</span>}
        >
          <GeminiCard />
        </SettingsSection>

        <SettingsSection
          title="NVIDIA NIM"
          description="80+ model qua NVIDIA — chat, vision, tạo ảnh FLUX — build.nvidia.com"
          icon={<span className="text-lg">🟢</span>}
        >
          <NvidiaNimCard />
        </SettingsSection>

        <SettingsSection
          title="Custom Providers"
          description="Kết nối bất kỳ OpenAI-compatible API: DeepSeek, vLLM, LiteLLM, Gemini Server..."
          icon={<Link className="size-5" />}
        >
          <CustomProvidersCard />
        </SettingsSection>

        <SettingsSection
          title="Provider qua tài khoản Google"
          description="Đăng nhập Google một lần, tái dùng chung cho Google Labs Flow, ChatGPT, Gemini Web API và Claude."
          icon={<KeyRound className="size-5" />}
        >
          <GoogleProvidersCard />
        </SettingsSection>

        <SettingsSection
          title="Codex Auto-Login (Đăng nhập Hàng loạt)"
          description="Danh sách tài khoản Codex (Github) để tự động đăng nhập hàng loạt lấy JWT"
          icon={<Plug className="size-5" />}
        >
          <CodexOnboardCard />
        </SettingsSection>

        <SettingsSection
          title="Khóa người dùng"
          description="Tạo API key riêng cho người dùng thường — chỉ truy cập trang vẽ ảnh"
          icon={<KeyRound className="size-5" />}
        >
          <UserKeysCard />
        </SettingsSection>

        <SettingsSection
          title="Kênh chat (Telegram / Zalo)"
          description="Bot token, admin, lọc thread, nhánh agent — từng kênh độc lập"
          icon={<MessageCircle className="size-5" />}
        >
          <TelegramCloudflareCard />
        </SettingsSection>

        <SettingsSection
          title="Cloudflare (hạ tầng chung)"
          description="Một domain HTTPS + tunnel cho mọi bot — không cấu hình lặp theo kênh"
          icon={<Cloud className="size-5" />}
        >
          <CloudflareInfraCard />
        </SettingsSection>

        <SettingsSection
          title="Home Assistant"
          description="Kết nối HA để AI biết trạng thái nhà và điều khiển thiết bị"
          icon={<Archive className="size-5" />}
        >
          <HACard />
        </SettingsSection>

        <SettingsSection
          title="Email · Lịch · Model hints"
          description="IMAP/SMTP, ICS calendar, định tuyến model burst/reason (Phase C)"
          icon={<MessageCircle className="size-5" />}
        >
          <EmailCalendarCard />
        </SettingsSection>

        <SettingsSection
          title="Giọng nói & Loa"
          description="TTS/STT (Piper · Zipformer), nghe thử 19 giọng, phát ra loa Cast/DLNA"
          icon={<Volume2 className="size-5" />}
        >
          <VoiceSpeakersCard />
        </SettingsSection>

        <SettingsSection
          title="Giáo viên (mọi cấp)"
          description="Lớp 1–12 Toán·Văn·Anh: giọng VI/EN, loa, import PDF SGK, quiz/chấm, filter Zalo/Tele"
          icon={<GraduationCap className="size-5" />}
        >
          <TeacherSettingsCard />
          <PersonasCard />
        </SettingsSection>

        <SettingsSection
          title="Sao lưu & Phục hồi"
          description="Tạo và quản lý bản sao lưu toàn bộ hệ thống"
          icon={<Archive className="size-5" />}
        >
          <BackupSettingsCard />
        </SettingsSection>
      </section>

      <ImportBrowserDialog />
    </>
  );
}

export default function SettingsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return <SettingsPageContent />;
}
