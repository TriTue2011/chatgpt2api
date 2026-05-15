"use client";

import { Sidebar } from "@/components/sidebar";
import { useLangStore } from "@/store/lang";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { lang } = useLangStore();

  return (
    <>
      {/* lang is consumed by store but html lang is set statically in layout */}
      <div className="flex min-h-screen bg-[#f4f6fb] text-stone-900 font-sans">
        <Sidebar />
        <main className="flex-1 overflow-x-hidden pl-16 lg:pl-64">
          <div className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6 lg:px-8">
            {children}
          </div>
        </main>
      </div>
    </>
  );
}
