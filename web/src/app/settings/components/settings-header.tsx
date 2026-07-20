"use client";

export function SettingsHeader() {
  return (
    <section className="flex flex-col gap-4 border-b border-black/[0.04] pb-6 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <p className="text-[11px] font-bold tracking-widest text-amber-500 uppercase mb-1">Hệ thống</p>
        <h1 className="text-[26px] font-bold tracking-tight text-[var(--foreground)]">Cài đặt</h1>
        <p className="text-[14px] text-[var(--muted-foreground)] mt-0.5">Cấu hình proxy, rate limit, system prompt và các tích hợp nâng cao</p>
      </div>
    </section>
  );
}


