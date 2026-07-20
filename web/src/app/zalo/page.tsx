import { redirect } from "next/navigation";

// Trang /zalo đã gom về Settings → Kênh chat → tab "Zalo Cá Nhân" →
// "🔑 Tài khoản & QR". Giữ route chỉ để link cũ không chết.
export default function ZaloPersonalPage() {
  redirect("/settings");
}
