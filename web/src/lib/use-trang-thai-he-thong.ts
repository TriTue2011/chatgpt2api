"use client";

import { useCallback, useEffect, useState } from "react";

import { request } from "@/lib/request";
import type { SettingsConfig } from "@/lib/api";
import type { TrangThaiHeThong } from "@/lib/feature-registry";

type HealthAccounts = { total?: number; active?: number };
type HealthShape = { accounts?: HealthAccounts };

const RONG: TrangThaiHeThong = {
  config: null,
  soTaiKhoan: 0,
  soTaiKhoanSong: 0,
  coConfig: false,
  coHealth: false,
};

/**
 * Gom trạng thái thật của hệ thống cho checklist và ô tìm nhanh.
 *
 * Đọc từ hai API ĐÃ CÓ (`/api/settings`, `/api/v1/health`) chứ không thêm
 * endpoint mới. `/api/v1/health` có sẵn bộ nhớ đệm 30 giây phía máy chủ
 * (api/system.py) nên gọi ở đây không tạo thêm tải.
 *
 * Hai cờ RIÊNG chứ không gộp một. Gộp lại thì một API hỏng cũng bị coi là đã
 * tải đủ, và phần dữ liệu thiếu bị đọc thành "chưa cấu hình": health có thể tốn
 * tới 30 giây ở lần gọi nguội, lúc đó màn hình sẽ báo đỏ "chưa có tài khoản nào"
 * trên hệ thống đầy tài khoản đang chạy tốt.
 */
export function useTrangThaiHeThong(
  /**
   * Bật/tắt việc gọi API. Ô tìm nhanh nằm trong AppShell nên mount ở MỌI trang;
   * gọi ngay lúc mount là mỗi lần chuyển trang lại thêm hai lời gọi, và với
   * người dùng thường thì một trong hai luôn trả 403 vì /api/settings chỉ cho
   * admin. Truyền false cho tới lúc thật sự cần.
   */
  batDau = true,
): TrangThaiHeThong & { taiLai: () => void } {
  const [tt, datTt] = useState<TrangThaiHeThong>(RONG);

  const tai = useCallback(async () => {
    const [cfg, health] = await Promise.allSettled([
      request.get<{ config: SettingsConfig }>("/api/settings"),
      request.get<HealthShape>("/api/v1/health"),
    ]);

    // Người dùng thường không đọc được /api/settings (chỉ admin). Đó KHÔNG phải
    // lỗi: vẫn dựng được trạng thái từ health, chỉ là phần cấu hình bỏ trống.
    const config =
      cfg.status === "fulfilled" ? (cfg.value.data?.config ?? null) : null;
    const acc =
      health.status === "fulfilled" ? (health.value.data?.accounts ?? {}) : {};

    datTt({
      config,
      soTaiKhoan: acc.total ?? 0,
      soTaiKhoanSong: acc.active ?? 0,
      coConfig: cfg.status === "fulfilled",
      coHealth: health.status === "fulfilled",
    });
  }, []);

  useEffect(() => {
    if (!batDau) return;
    void tai();
  }, [batDau, tai]);

  return { ...tt, taiLai: () => void tai() };
}
