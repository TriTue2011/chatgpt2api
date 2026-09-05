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
  daTai: false,
};

/**
 * Gom trạng thái thật của hệ thống cho checklist và ô tìm nhanh.
 *
 * Đọc từ hai API ĐÃ CÓ (`/api/settings`, `/api/v1/health`) chứ không thêm
 * endpoint mới. `/api/v1/health` có sẵn bộ nhớ đệm 30 giây phía máy chủ
 * (api/system.py) nên gọi ở đây không tạo thêm tải.
 *
 * `daTai` chỉ bật khi CẢ HAI lời gọi xong. Chưa xong mà đã kết luận thì
 * checklist sẽ chớp một nhịp "còn thiếu mọi thứ" rồi mới đúng — người mới cài
 * nhìn thấy đúng cái nhịp đó sẽ hoảng.
 */
export function useTrangThaiHeThong(): TrangThaiHeThong & { taiLai: () => void } {
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
      daTai: cfg.status === "fulfilled" || health.status === "fulfilled",
    });
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  return { ...tt, taiLai: () => void tai() };
}
