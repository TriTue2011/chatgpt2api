"use client";

/**
 * Tab "Học hỏi" — xem / sửa / xoá những gì bot đã học, và tự thêm tay.
 *
 * Gom mọi tầng học về một chỗ, mỗi mục là một SettingsSection gập/mở (bám khuôn
 * trang Cài đặt): Tổng quan · Bot hiểu thiết bị · Sơ đồ kích hoạt · Lịch sinh hoạt ·
 * Bật/tắt thiết bị · Gợi ý theo
 * nếp nhà · Nếp sinh hoạt (thói quen). API ở `api/hoc_hoi.py`.
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
import { DuyetTruongHop } from "./components/duyet-truong-hop";
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
          <SettingsSection title="Tổng quan" defaultOpen tuKhoa="cong tac diem tin cay kenh">
            <TongQuan />
          </SettingsSection>
          <SettingsSection title="Độ tin cảm biến (nhiễu / kẹt / lành)"
            tuKhoa="do tin cam bien nhieu ket lanh flap dwell doi lien tuc setting dat qua nhay radar khoang cach loc mem">
            <DoTin />
          </SettingsSection>
          <SettingsSection title="Ngưỡng bộ não (tự chủ, kiểm tiến dần)"
            tuKhoa="nguong tu chu tu lam so luot ty le dung sai kiem tien dan ngay do chac mo mieng mac dinh">
            <Nguong />
          </SettingsSection>
          <SettingsSection title="Bot hiểu thiết bị" tuKhoa="ket luan du kien huong dan lich su giai">
            <HieuThietBi />
          </SettingsSection>
          <SettingsSection title="Sơ đồ kích hoạt" tuKhoa="nhan to chinh ngoai vi dieu kien tich bot dieu khien">
            <SoDo />
          </SettingsSection>
          <SettingsSection title="Sơ đồ nhà" tuKhoa="so do nha phong vach thong cua chinh anh camera luoi o mo ta dap an chup">
            <SoDoNha />
          </SettingsSection>
          <SettingsSection title="Người trong nhà & lịch sinh hoạt"
            tuKhoa="nguoi thanh vien gia dinh ca nha tuoi nam sinh con tre em lich sinh hoat ngu day di lam vang nha an toi thu">
            <LichSinhHoat />
          </SettingsSection>
          <SettingsSection title="Duyệt trường hợp bật/tắt" tuKhoa="duyet truong hop tinh huong kich ban bat tat sua them bo">
            <DuyetTruongHop />
          </SettingsSection>
          <SettingsSection title="Bật/tắt thiết bị" tuKhoa="bat tat thiet bi kich hoat luat ngoai le tu lam bao ao vang">
            <KichHoat />
          </SettingsSection>
          <SettingsSection title="Tự bật theo nếp (bình nóng lạnh…)"
            tuKhoa="tu bat theo nep lich gio binh nong lanh may loc nuoc thoi luong tu tat">
            <TheoNep />
          </SettingsSection>
          <SettingsSection title="Nhật ký kích hoạt" tuKhoa="nhat ky lich su kich hoat bat tat khong lam ly do nguon dieu kien">
            <NhatKyKichHoat />
          </SettingsSection>
          <SettingsSection title="Gợi ý theo nếp nhà" tuKhoa="du doan goi y cham dung sai">
            <GoiY />
          </SettingsSection>
          <SettingsSection title="Nếp sinh hoạt (thói quen)" tuKhoa="tinh huong them tay thoi quen">
            <NepSinhHoat />
          </SettingsSection>
          <SettingsSection title="Tâm hồn (làm thơ, cảm xúc)"
            tuKhoa="tam hon lam tho cam xuc goc tinh cach ky uc mac dinh tat">
            <TamHonMuc />
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
