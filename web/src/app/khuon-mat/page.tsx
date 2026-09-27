"use client";

/**
 * Tab "Khuôn mặt" — người nhà, mặt lạ, lượt thấy mặt, cách canh camera.
 *
 * Chủ máy 27/09/2026: "đưa phần khuôn mặt ra tab chính như phần học hỏi để xem cho
 * nhanh". Trước đây nằm sâu ở Cài đặt → Home Assistant → Khuôn mặt. Dùng NGUYÊN thẻ
 * `NhinNhaCard` (chủ duy nhất của khoá `nhin_nha` trong config) — thẻ đọc/lưu config
 * qua store của trang Cài đặt nên trang này tự nạp config khi mở.
 */

import { useEffect } from "react";
import { LoaderCircle } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { NhinNhaCard } from "../settings/components/nhin-nha-card";
import { useSettingsStore } from "../settings/store";

function KhuonMatContent() {
  const config = useSettingsStore((s) => s.config);
  const loadConfig = useSettingsStore((s) => s.loadConfig);

  useEffect(() => {
    if (!config) void loadConfig();
  }, [config, loadConfig]);

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6" style={{ paddingInline: "max(16px, env(safe-area-inset-left))" }}>
      {config ? <NhinNhaCard /> : (
        <div className="flex min-h-[30vh] items-center justify-center">
          <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
        </div>
      )}
    </div>
  );
}

export default function KhuonMatPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return <KhuonMatContent />;
}
