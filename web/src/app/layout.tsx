import type { Metadata, Viewport } from "next";
import { Toaster } from "sonner";
import "./globals.css";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "chatgpt2api — Bảng điều khiển",
  description: "Bảng điều khiển quản lý tài khoản ChatGPT, nhà cung cấp AI, tạo ảnh, sao lưu",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#0c0a09",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <body
        className="antialiased"
        style={{
          fontFamily:
            '"Inter","SF Pro Display","SF Pro Text","Helvetica Neue",sans-serif',
        }}
      >
        {/* Theme-aware toast: dùng biến popover nên nền/chữ luôn tương phản ở cả
            light & dark (trước đây không set theme → sonner mặc định light → nền
            trắng chữ trắng khi app ở dark). */}
        <Toaster
          position="top-right"
          richColors
          offset={48}
          toastOptions={{
            style: {
              background: "var(--popover)",
              color: "var(--popover-foreground)",
              border: "1px solid var(--border)",
            },
          }}
        />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
