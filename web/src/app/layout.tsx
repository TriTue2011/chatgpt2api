import type { Metadata, Viewport } from "next";
import { Toaster } from "sonner";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { useLangStore } from "@/store/lang";

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
  const { lang } = useLangStore();
  return (
    <html lang={lang} suppressHydrationWarning>
      <body
        className="antialiased"
        style={{
          fontFamily:
            '"Inter","SF Pro Display","SF Pro Text","Helvetica Neue",sans-serif',
        }}
      >
        <Toaster position="top-right" richColors offset={48} />
        <div className="flex min-h-screen bg-[#f4f6fb] text-stone-900 font-sans">
          <Sidebar />
          <main className="flex-1 overflow-x-hidden pl-16 lg:pl-64">
            <div className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6 lg:px-8">
              {children}
            </div>
          </main>
        </div>
      </body>
    </html>
  );
}
