"use client";

import { useState } from "react";
import { Sidebar } from "@/components/sidebar";
import { useLangStore } from "@/store/lang";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { lang } = useLangStore();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="flex min-h-screen bg-[#f4f6fb] text-stone-900 font-sans">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />
      <main
        className="flex-1 overflow-x-hidden transition-[padding-left] duration-300 ease-in-out"
        style={{
          paddingLeft: sidebarCollapsed ? "68px" : "16rem",
        }}
      >
        <div className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </div>
      </main>
    </div>
  );
}
