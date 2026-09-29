"use client";

/**
 * Tab "Camera" — xem trực tiếp và bộ đàm với camera nhà, một chỗ riêng dễ thao tác trên điện
 * thoại.
 *
 * Chủ máy 29/09/2026: "chuyển camera ra tab như YouTube để dễ thao tác phần bộ đàm, setting
 * thì giữ nguyên". Khai / sửa camera vẫn ở Cài đặt → Home Assistant → Camera nhà; tab này chỉ
 * dùng khung bộ đàm (`BoDamCamera`) với sổ camera trong config. Chỉ quản trị: nói ra loa trong nhà.
 *
 * Bộ đàm tắt (bấm Đóng, rời trang, chuyển ứng dụng) thì hiện nút mở lại — không tự mở mic lại khi
 * quay về.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuthGuard } from "@/lib/use-auth-guard";

import { BoDamCamera, noiDuoc } from "../settings/components/bo-dam-camera";
import { useSettingsStore } from "../settings/store";

const KHOA_CHON = "c2a_camera_chon";

type CamSo = { loa_kieu?: string; ve_tinh_cong?: number | ""; note?: string };

export default function CameraPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  const config = useSettingsStore((s) => s.config);
  const loadConfig = useSettingsStore((s) => s.loadConfig);
  const [chon, setChon] = useState("");
  const [mo, setMo] = useState(true);

  useEffect(() => {
    if (session?.role === "admin" && !config) void loadConfig();
  }, [session?.role, config, loadConfig]);

  const cams = ((config as { cameras?: Record<string, CamSo> } | null)?.cameras) || {};
  const ds = Object.keys(cams);

  // Camera chọn lần trước; không còn thì camera đầu tiên nói được, rồi camera đầu tiên.
  useEffect(() => {
    if (!ds.length || (chon && cams[chon])) return;
    let nho = "";
    try { nho = localStorage.getItem(KHOA_CHON) || ""; } catch { /* chế độ riêng tư */ }
    setChon(cams[nho] ? nho : ds.find((t) => noiDuoc(cams[t])) || ds[0]);
  }, [ds.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  const doiTen = (t: string) => {
    setChon(t);
    try { localStorage.setItem(KHOA_CHON, t); } catch { /* chế độ riêng tư */ }
  };

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return (
    <div className="mx-auto w-full max-w-4xl space-y-4 px-4 py-6" style={{ paddingInline: "max(16px, env(safe-area-inset-left))" }}>
      <div>
        <h1 className="text-lg font-semibold">Camera</h1>
        <p className="text-xs text-muted-foreground">
          Chọn camera để xem trực tiếp và nói ra loa camera. Thêm / sửa camera ở{" "}
          <Link href="/settings" className="underline">Cài đặt → Home Assistant → Camera nhà</Link>.
        </p>
      </div>
      {!config ? (
        <div className="flex min-h-[20vh] items-center justify-center">
          <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
        </div>
      ) : !ds.length ? (
        <p className="text-sm text-muted-foreground">Chưa khai camera nào.</p>
      ) : mo && chon ? (
        <BoDamCamera cams={cams} ten={chon} doiTen={doiTen} onClose={() => setMo(false)} />
      ) : (
        <Button onClick={() => setMo(true)}>📞 Mở bộ đàm</Button>
      )}
    </div>
  );
}
