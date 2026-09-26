"use client";

/**
 * Tab "Học hỏi" — xem / sửa / xoá những gì bot đã học, và tự thêm tay.
 *
 * Gom mọi tầng học về một chỗ, mỗi mục là một SettingsSection gập/mở (bám khuôn
 * trang Cài đặt): Tổng quan · Bot hiểu thiết bị · Sơ đồ kích hoạt · Gợi ý theo
 * nếp nhà · Nếp sinh hoạt (thói quen). API ở `api/hoc_hoi.py`.
 *
 * Tên thiết bị & khu vực KHÔNG nằm ở đây — chủ máy chốt chuyển sang Settings
 * → Home Assistant → "Thiết bị & tên" (ha-devices-card.tsx), vì đó là nơi cần
 * duyệt TOÀN BỘ danh sách thiết bị, không chỉ thứ bot từng gặp.
 */

import { LoaderCircle } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { SettingsSection } from "@/components/settings-section";
import { BoLocCaiDat } from "@/components/settings-filter";

import { TongQuan } from "./components/tong-quan";
import { HieuThietBi } from "./components/hieu-thiet-bi";
import { SoDo } from "./components/so-do";
import { KichHoat } from "./components/kich-hoat";
import { GoiY } from "./components/goi-y";
import { NepSinhHoat } from "./components/nep-sinh-hoat";

function HocHoiContent() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6" style={{ paddingInline: "max(16px, env(safe-area-inset-left))" }}>
      <div className="mb-4">
        <h1 className="text-lg font-semibold">Học hỏi</h1>
        <p className="text-xs text-muted-foreground">
          Xem, sửa, xoá những gì bot đã học — và tự thêm tay. Tắt một tầng thì bot
          ngừng học tầng đó, dữ liệu cũ vẫn giữ.
        </p>
      </div>
      <BoLocCaiDat>
        <div className="space-y-3">
          <SettingsSection title="Tổng quan" defaultOpen tuKhoa="cong tac diem tin cay kenh">
            <TongQuan />
          </SettingsSection>
          <SettingsSection title="Bot hiểu thiết bị" tuKhoa="ket luan du kien huong dan lich su giai">
            <HieuThietBi />
          </SettingsSection>
          <SettingsSection title="Sơ đồ kích hoạt" tuKhoa="nhan to chinh ngoai vi dieu kien tich bot dieu khien">
            <SoDo />
          </SettingsSection>
          <SettingsSection title="Bật/tắt thiết bị" tuKhoa="bat tat thiet bi kich hoat luat ngoai le tu lam bao ao vang">
            <KichHoat />
          </SettingsSection>
          <SettingsSection title="Gợi ý theo nếp nhà" tuKhoa="du doan goi y cham dung sai">
            <GoiY />
          </SettingsSection>
          <SettingsSection title="Nếp sinh hoạt (thói quen)" tuKhoa="tinh huong them tay thoi quen">
            <NepSinhHoat />
          </SettingsSection>
        </div>
      </BoLocCaiDat>
    </div>
  );
}

export default function HocHoiPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return <HocHoiContent />;
}
