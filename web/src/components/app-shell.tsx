"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/sidebar";
import { useLangStore } from "@/store/lang";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { lang } = useLangStore();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "dark" || (!stored && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
      setDarkMode(true);
      document.documentElement.classList.add("dark");
    }
  }, []);

  const toggleDarkMode = () => {
    setDarkMode(prev => {
      const next = !prev;
      if (next) {
        document.documentElement.classList.add("dark");
        localStorage.setItem("theme", "dark");
      } else {
        document.documentElement.classList.remove("dark");
        localStorage.setItem("theme", "light");
      }
      return next;
    });
  };

  return (
    <div className="flex min-h-screen bg-circles text-stone-900 dark:text-stone-100 font-sans">
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
      <button
        onClick={toggleDarkMode}
        className="fixed bottom-4 right-4 z-50 flex size-10 items-center justify-center rounded-full border border-slate-200 bg-white shadow-lg transition-all hover:scale-105 dark:border-slate-700 dark:bg-slate-800"
        title={darkMode ? "Light mode" : "Dark mode"}
      >
        {darkMode ? "☀️" : "🌙"}
      </button>
    </div>
  );
}
