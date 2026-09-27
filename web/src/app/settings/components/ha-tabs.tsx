"use client";

/**
 * Thanh tab cho mục "Home Assistant" — bốn thẻ (Kết nối HA / Camera / MQTT /
 * Tuya) trước đây xếp DỌC, tổng ~1600 dòng nên mở mục ra là phải cuộn dài.
 *
 * Cùng lối với tab kênh ở telegram-cloudflare-card.tsx (CH_TABS + tabBtn):
 * chọn tab nào chỉ dựng tab đó, nên MqttCard — thẻ gọi 5-6 API và chạy
 * setInterval ngay khi mount — không còn chạy ngầm lúc người dùng chỉ mở mục
 * để sửa token HA.
 */

import { useState } from "react";
import Link from "next/link";

import { HACard } from "./ha-card";
import { CameraCard } from "./camera-card";
import { MqttCard } from "./mqtt-card";
import { TuyaCard } from "./tuya-card";
import { HaDevicesCard } from "./ha-devices-card";

const HA_TABS = ["ha", "camera", "khuon-mat", "mqtt", "tuya", "thiet-bi"] as const;
type HaTab = (typeof HA_TABS)[number];

const NHAN: [HaTab, string][] = [
  ["ha", "🏠 Kết nối HA"],
  ["camera", "📷 Camera"],
  ["khuon-mat", "🧑 Khuôn mặt"],
  ["mqtt", "📡 MQTT"],
  ["tuya", "🔌 Tuya"],
  ["thiet-bi", "🏷️ Thiết bị & tên"],
];

export function HomeAssistantTabs() {
  // Đọc ngay lúc KHỞI TẠO state, không đặt lại trong useEffect: đặt trong
  // effect làm render hai lượt và người dùng thấy tab nháy từ HA sang tab đích
  // (xem chú thích cùng việc ở telegram-cloudflare-card.tsx).
  const [tab, setTab] = useState<HaTab>(() => {
    if (typeof window === "undefined") return "ha";   // dựng tĩnh: chưa có URL
    const t = new URLSearchParams(window.location.search).get("tab");
    return t && (HA_TABS as readonly string[]).includes(t) ? (t as HaTab) : "ha";
  });

  const tabBtn = (active: boolean) =>
    `px-3 py-1.5 rounded-md text-xs font-semibold border transition ${active
      ? "border-primary text-primary bg-primary/10"
      : "border-border text-muted-foreground hover:bg-muted/40"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {NHAN.map(([k, lb]) => (
          <button key={k} type="button" className={tabBtn(tab === k)}
            onClick={() => setTab(k)}>
            {lb}
          </button>
        ))}
      </div>

      {tab === "ha" && <HACard />}
      {tab === "camera" && <CameraCard />}
      {/* Chủ máy 27/09/2026: khuôn mặt ra tab chính (/khuon-mat) để xem nhanh — một chỗ
          sửa duy nhất cho khoá `nhin_nha`, ở đây chỉ còn đường dẫn. */}
      {tab === "khuon-mat" && (
        <p className="text-sm">
          Khuôn mặt, người lạ, cách canh camera nay ở tab riêng:{" "}
          <Link href="/khuon-mat" className="font-medium text-primary underline">mở tab Khuôn mặt</Link>.
        </p>
      )}
      {tab === "mqtt" && <MqttCard />}
      {tab === "tuya" && <TuyaCard />}
      {tab === "thiet-bi" && <HaDevicesCard />}
    </div>
  );
}
