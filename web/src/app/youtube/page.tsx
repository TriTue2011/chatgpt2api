"use client";

/**
 * Tab "YouTube" — tìm YouTube / Zing MP3 và phát ra loa, tivi trong Home Assistant.
 *
 * Chủ máy 14/09/2026: "token sinh ra thì phải có chỗ hiển thị trên webui để tôi
 * copy. Xây dựng 1 tab youtube riêng hiển thị token và có chức năng như card nhưng
 * thiết kế lại đẹp hơn". Trình phát nằm ngay trong c2a (`services/youtube_phat/`),
 * thay add-on TriTue YouTube Player; HA nối tới bằng URL + token ở thẻ trên cùng.
 * Chỉ quản trị: tab điều khiển thiết bị trong nhà.
 */

import { LoaderCircle } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";

import { KetNoiHa } from "./components/ket-noi-ha";
import { TrinhPhat } from "./components/trinh-phat";

export default function YoutubePage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 px-4 py-6" style={{ paddingInline: "max(16px, env(safe-area-inset-left))" }}>
      <div>
        <h1 className="text-lg font-semibold">YouTube</h1>
        <p className="text-xs text-muted-foreground">
          Tìm YouTube, Zing MP3 hoặc dán link audio rồi phát ra loa và tivi trong nhà. Tivi mở thẳng ứng dụng YouTube; loa
          nhận âm thanh qua c2a.
        </p>
      </div>
      <KetNoiHa />
      <TrinhPhat />
    </div>
  );
}
