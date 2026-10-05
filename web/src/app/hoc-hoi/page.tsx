"use client";

/**
 * Tab "Học hỏi" — xem / sửa / xoá những gì bot đã học, và tự thêm tay.
 *
 * Chủ máy 05/10/2026: "Tab học hỏi đang dài dòng khó hiểu… càng đơn giản, trình bày mạch lạc". Còn: Thiết bị
 * (mỗi thiết bị gập; Bật / Tắt gập; trường hợp ✓ ✗ ✎ 🗑) · Người nhà & nếp sinh hoạt (gộp 3 mục cũ) · Sơ đồ nhà ·
 * Nhật ký · Tâm hồn · Kỹ thuật (gập — ngưỡng, độ tin, luật bot tự học: "ẩn rồi kích vào sẽ ra cụ thể").
 * API ở `api/hoc_hoi.py`.
 *
 * Tên thiết bị & khu vực KHÔNG nằm ở đây — chủ máy chốt chuyển sang Settings
 * → Home Assistant → "Thiết bị & tên" (ha-devices-card.tsx), vì đó là nơi cần
 * duyệt TOÀN BỘ danh sách thiết bị, không chỉ thứ bot từng gặp.
 */

import { useEffect } from "react";
import { LoaderCircle } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";
import { SettingsSection } from "@/components/settings-section";
import { BoLocCaiDat } from "@/components/settings-filter";

import { TongQuan } from "./components/tong-quan";
import { HieuThietBi } from "./components/hieu-thiet-bi";
import { SoDo } from "./components/so-do";
import { SoDoNha } from "./components/so-do-nha";
import { KichHoat } from "./components/kich-hoat";
import { NhatKyKichHoat } from "./components/nhat-ky-kich-hoat";
import { LichSinhHoat } from "./components/lich-sinh-hoat";
import { GoiY } from "./components/goi-y";
import { NepSinhHoat } from "./components/nep-sinh-hoat";
import { ThietBiNha } from "./components/thiet-bi";
import { Nguong } from "./components/nguong";
import { DoTin } from "./components/do-tin";
import { TheoNep } from "./components/theo-nep";
import { TamHonCard } from "../settings/components/tam-hon-card";
import { useSettingsStore } from "../settings/store";

function TamHonMuc() {
  const config = useSettingsStore((s) => s.config);
  const loadConfig = useSettingsStore((s) => s.loadConfig);
  useEffect(() => { if (!config) void loadConfig(); }, [config, loadConfig]);
  return config ? <TamHonCard /> : (
    <div className="flex items-center gap-2 p-3 text-xs text-muted-foreground">
      <LoaderCircle className="size-4 animate-spin" /> Đang tải…
    </div>
  );
}

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
          <SettingsSection title="Thiết bị" defaultOpen
            tuKhoa="thiet bi bat tat truong hop dieu kien kich hoat kiem chung ngoai vi duyet sua xoa o lai vang binh nong lanh theo nep">
            <ThietBiNha />
          </SettingsSection>
          <SettingsSection title="Người nhà & nếp sinh hoạt"
            tuKhoa="nguoi thanh vien gia dinh lich sinh hoat ngu day di lam vang an toi nep thoi quen goi y du doan">
            <div className="space-y-4">
              <LichSinhHoat />
              <div><h3 className="mb-1 text-xs font-medium">Nếp bot nhận ra</h3><NepSinhHoat /></div>
              <div><h3 className="mb-1 text-xs font-medium">Gợi ý theo nếp nhà</h3><GoiY /></div>
            </div>
          </SettingsSection>
          <SettingsSection title="Sơ đồ nhà" tuKhoa="so do nha phong vach thong cua chinh anh camera luoi o mo ta dap an chup">
            <SoDoNha />
          </SettingsSection>
          <SettingsSection title="Nhật ký kích hoạt" tuKhoa="nhat ky lich su kich hoat bat tat khong lam ly do nguon dieu kien">
            <NhatKyKichHoat />
          </SettingsSection>
          <SettingsSection title="Tâm hồn (làm thơ, cảm xúc)"
            tuKhoa="tam hon lam tho cam xuc goc tinh cach ky uc mac dinh tat">
            <TamHonMuc />
          </SettingsSection>
          <SettingsSection title="Kỹ thuật (chi tiết bot học)"
            description="Ngưỡng, độ tin cảm biến, luật bot tự học, hướng dẫn — mở khi cần xem sâu."
            tuKhoa="ky thuat tong quan cong tac do tin cam bien nhieu ket nguong tu chu hieu thiet bi so do kich hoat ngoai vi tu bat theo nep">
            <div className="space-y-3">
              <SettingsSection title="Tổng quan (công tắc từng tầng học)"><TongQuan /></SettingsSection>
              <SettingsSection title="Độ tin cảm biến (nhiễu / kẹt / lành)"><DoTin /></SettingsSection>
              <SettingsSection title="Ngưỡng bộ não (kiểm tiến dần)"><Nguong /></SettingsSection>
              <SettingsSection title="Bot hiểu thiết bị"><HieuThietBi /></SettingsSection>
              <SettingsSection title="Sơ đồ kích hoạt (ngoại vi)"><SoDo /></SettingsSection>
              <SettingsSection title="Bot tự học bật/tắt (chi tiết)"><KichHoat /></SettingsSection>
              <SettingsSection title="Thêm thiết bị tự bật theo nếp"><TheoNep /></SettingsSection>
            </div>
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
