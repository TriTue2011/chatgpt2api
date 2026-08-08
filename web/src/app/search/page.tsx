"use client";

import { useEffect, useState } from "react";
import { Search, CheckCircle2, Globe, Database, ArrowUp, ArrowDown, Cpu, LoaderCircle } from "lucide-react";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

const SEARCH_BACKENDS = [
  { value: "gemini", label: "Gemini Google Search", desc: "Google Search qua Gemini API — cần API key AI Studio", icon: Search },
  { value: "serper", label: "Serper.dev", desc: "Google Search API nhanh — 2.500 req/tháng miễn phí", icon: Search },
  { value: "searxng", label: "SearXNG (tự cài)", desc: "Tự host, riêng tư, không giới hạn", icon: Database },
  { value: "brave", label: "Brave Search", desc: "Brave Search API — 2.000 req/tháng miễn phí", icon: Search },
];

/** Backend xác thực bằng API key → cần ô nhập, và xoay được nhiều khoá.
 *  `searxng` tự host nên không có khoá; `gemini` đặt ở Cài đặt → Gemini. */
const BACKEND_CAN_KHOA: Record<string, {nhan: string; goi_y: string}> = {
  serper: {nhan: "Serper.dev", goi_y: "2.500 req/tháng mỗi khoá — serper.dev"},
  brave:  {nhan: "Brave Search", goi_y: "2.000 req/tháng mỗi khoá — brave.com/search/api"},
};

type CustomProvider = {
  name: string;
  prefix: string;
};

function SearchPageContent() {
  const [config, setConfig] = useState<any>({});
  const [combo, setCombo] = useState<string[]>([]);
  // Nhiều khoá cho mỗi backend, mỗi dòng một khoá. Máy chủ xoay vòng và treo
  // tạm khoá vừa bị 429/401/403, nên hết hạn mức khoá này thì sang khoá khác.
  const [khoaBackend, setKhoaBackend] = useState<Record<string, string>>({});
  const [customProviders, setCustomProviders] = useState<CustomProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetchConfig();
    fetchCustomProviders();
  }, []);

  async function fetchConfig() {
    try {
      const data = await request.get("/api/settings");
      const cfg = (data.data as any)?.config || {};
      const searchCfg = cfg.search || {};
      setConfig({ enabled: true, auto_detect: true, max_results: 3, ...searchCfg });
      setCombo(searchCfg.search_combo || ["gemini"]);
      const providers = cfg.providers || {};
      const nap: Record<string, string> = {};
      for (const ten of Object.keys(BACKEND_CAN_KHOA)) {
        const pc = providers[ten] || {};
        const ds: string[] = Array.isArray(pc.api_keys) ? pc.api_keys : [];
        const gop = ds.length ? ds : (pc.api_key ? [pc.api_key] : []);
        nap[ten] = gop.filter(Boolean).join("\n");
      }
      setKhoaBackend(nap);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  async function fetchCustomProviders() {
    try {
      const data = await request.get("/api/v1/custom-providers");
      const providers = (data.data as any)?.custom_providers || {};
      const list: CustomProvider[] = Object.entries(providers).map(([id, p]: any) => ({
        name: p.name || id,
        prefix: p.prefix || id,
      }));
      setCustomProviders(list);
    } catch (e) { console.error(e); }
  }

  function backendLabel(key: string): string {
    const builtin = SEARCH_BACKENDS.find(b => b.value === key);
    if (builtin) return builtin.label;
    if (key.startsWith("custom:")) {
      const cpId = key.slice(7);
      const cp = customProviders.find(p => p.prefix === cpId);
      return cp ? `${cp.name} (Custom API)` : key;
    }
    return key;
  }

  function backendDesc(key: string): string {
    if (key.startsWith("custom:")) return "Dùng model chat của custom provider để tìm kiếm";
    const builtin = SEARCH_BACKENDS.find(b => b.value === key);
    return builtin?.desc || "";
  }

  function toggleBackend(backend: string) {
    setCombo(prev => {
      if (prev.includes(backend)) return prev.filter(b => b !== backend);
      return [...prev, backend];
    });
  }

  function moveBackend(backend: string, direction: "up" | "down") {
    setCombo(prev => {
      const idx = prev.indexOf(backend);
      if (idx < 0) return prev;
      const next = [...prev];
      if (direction === "up" && idx > 0) {
        [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
      } else if (direction === "down" && idx < next.length - 1) {
        [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
      }
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setMsg("");
    try {
      await request.post("/api/settings", {
        search: { ...config, search_combo: combo },
        providers: {
          ...config.providers || {},
          // Chỉ gửi backend ĐANG trong combo: gửi cả những cái đã bỏ ra sẽ ghi
          // đè cấu hình của chúng bằng chuỗi rỗng trên màn hình này.
          ...Object.fromEntries(
            Object.keys(BACKEND_CAN_KHOA)
              .filter((ten) => combo.includes(ten))
              .map((ten) => {
                const ds = (khoaBackend[ten] || "")
                  .split("\n").map((k) => k.trim()).filter(Boolean);
                return [ten, {enabled: true, api_key: ds[0] || "", api_keys: ds}];
              })),
        },
      });
      setMsg("Đã lưu!");
      setTimeout(() => setMsg(""), 2000);
    } catch (e: any) {
      setMsg("Lỗi: " + (e?.message || "unknown"));
    } finally {
      setSaving(false);
    }
  }

  // All available backends: builtin + custom providers
  const allBackends = [
    ...SEARCH_BACKENDS,
    ...customProviders.map(cp => ({
      value: `custom:${cp.prefix}`,
      label: `${cp.name} (Custom API)`,
      desc: `Dùng model của ${cp.name} để tìm kiếm — gửi prompt search đến chat endpoint`,
      icon: Cpu,
    })),
  ];

  if (loading) {
    return <div className="flex items-center justify-center py-20"><p className="text-[var(--muted-foreground)]">Đang tải...</p></div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1 border-b border-black/[0.04] pb-5">
        <h1 className="text-[24px] font-bold tracking-tight text-[var(--foreground)]">Cấu hình tìm kiếm</h1>
        <p className="text-[14px] text-[var(--muted-foreground)]">
          Khi dùng model không có search built-in (cx/, oc/...), hệ thống sẽ tự tìm kiếm. Combo: thử lần lượt, backend trước lỗi → backend sau.
        </p>
      </div>

      {/* Enable */}
      <div className="rounded-[16px] p-5 card-3d card-tint-indigo">
        <label className="flex items-center gap-3 cursor-pointer">
          <input type="checkbox" checked={config.enabled !== false}
            onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
            className="size-4 accent-amber-500" />
          <div>
            <span className="text-[14px] font-semibold text-[var(--foreground)]">Bật tìm kiếm tự động</span>
            <p className="text-[13px] text-[var(--muted-foreground)]">Tự động phát hiện câu hỏi cần tìm kiếm và bổ sung kết quả</p>
          </div>
        </label>
      </div>

      {/* Khoá + model Gemini KHÔNG sửa ở đây.

          Trước đây màn hình này có ô nhập riêng, mà Cài đặt → Gemini cũng có —
          hai chỗ sửa cùng một trường thì sớm muộn cũng lệch nhau. Tệ hơn: ô ở
          đây chỉ nhận MỘT khoá, nên lưu từ màn hình này sẽ đè lên danh sách
          nhiều khoá bên Cài đặt. */}
      <div className="rounded-[16px] p-5 card-3d card-tint-violet">
        <h3 className="text-[15px] font-bold text-[var(--foreground)] mb-2">Gemini</h3>
        <p className="text-[13px] text-[var(--muted-foreground)]">
          Khoá, model mặc định và <b>model tìm kiếm</b> của Gemini đặt ở{" "}
          <a href="/settings" className="underline hover:text-[var(--foreground)]">
            Cài đặt → Gemini AI Studio
          </a>. Ở đó quản lý được nhiều khoá và chọn model từ tab Quản lý Model.
        </p>
      </div>

      {/* Search Combo */}
      <div className="rounded-[16px] p-5 card-main">
        <h3 className="text-[15px] font-bold text-[var(--foreground)] mb-3">
          Thứ tự tìm kiếm (Combo)
        </h3>
        <p className="text-xs text-[var(--muted-foreground)] mb-4">
          Tích chọn backend và sắp xếp thứ tự ưu tiên. Backend đầu tiên được thử trước, nếu lỗi → thử backend tiếp theo. Có thể thêm custom provider làm search backend.
        </p>

        {/* Selected backends in priority order */}
        {combo.length > 0 && (
          <div className="space-y-1 mb-4">
            {combo.map((backend, idx) => {
              const info = allBackends.find(b => b.value === backend);
              if (!info) return null;
              const Icon = info.icon || Search;
              return (
                <div key={backend} className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--muted)] px-3 py-2.5">
                  <span className={cn(
                    "text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center shrink-0",
                    idx === 0 ? "bg-emerald-500/20 text-emerald-600" : "bg-[var(--secondary)] text-[var(--muted-foreground)]",
                  )}>
                    {idx + 1}
                  </span>
                  <Icon className="size-4 text-[var(--muted-foreground)]" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm text-[var(--foreground)]">{info.label}</span>
                    <p className="text-[10px] text-[var(--muted-foreground)] truncate">{info.desc}</p>
                  </div>
                  <button onClick={() => moveBackend(backend, "up")} disabled={idx === 0}
                    className="p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-30">
                    <ArrowUp className="size-3.5" />
                  </button>
                  <button onClick={() => moveBackend(backend, "down")} disabled={idx === combo.length - 1}
                    className="p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-30">
                    <ArrowDown className="size-3.5" />
                  </button>
                  <button onClick={() => toggleBackend(backend)}
                    className="text-xs text-red-400 hover:text-red-600 ml-1">X</button>
                </div>
              );
            })}
            {/* Khoá của các backend ĐANG dùng — mỗi dòng một khoá.

                Máy chủ xoay vòng và treo tạm khoá vừa bị 429/401/403 trong 60
                giây, nên hết hạn mức khoá này thì tự sang khoá khác. Đặt ngay
                dưới danh sách thứ tự là vì hai thứ này luôn được sửa cùng lúc:
                thêm một backend thì việc kế tiếp luôn là dán khoá cho nó. */}
            {combo.filter((b) => BACKEND_CAN_KHOA[b]).map((b) => (
              <div key={`khoa-${b}`} className="rounded-lg border border-[var(--border)] bg-[var(--secondary)] px-3 py-2.5">
                <label className="text-[12px] font-medium text-[var(--foreground)]">
                  Khoá {BACKEND_CAN_KHOA[b].nhan}
                </label>
                <textarea
                  value={khoaBackend[b] || ""}
                  onChange={(e) => setKhoaBackend((prev) => ({...prev, [b]: e.target.value}))}
                  rows={3}
                  placeholder={"Mỗi dòng một khoá\nkhoa-thu-nhat\nkhoa-thu-hai"}
                  className="mt-1 w-full rounded-[10px] border border-[var(--border)] bg-[var(--muted)] px-3 py-2 font-mono text-[12px] text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:border-amber-400 focus:outline-none"
                />
                <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">
                  {BACKEND_CAN_KHOA[b].goi_y} · Nhiều khoá thì hết hạn mức khoá này
                  sẽ tự chuyển sang khoá kế tiếp.
                </p>
              </div>
            ))}
          </div>
        )}

        {/* Available backends to add */}
        <div className="space-y-1">
          {allBackends.filter(b => !combo.includes(b.value)).map(b => {
            const Icon = b.icon || Search;
            return (
              <button key={b.value} type="button"
                onClick={() => toggleBackend(b.value)}
                className="flex w-full items-center gap-3 rounded-lg border border-[var(--border)] p-3 text-left hover:border-[var(--border)] hover:bg-[var(--muted)] transition">
                <Icon className="size-4 text-[var(--muted-foreground)]" />
                <div className="flex-1">
                  <p className="text-sm text-[var(--foreground)]">{b.label}</p>
                  <p className="text-xs text-[var(--muted-foreground)]">{b.desc}</p>
                </div>
                <span className="text-xs text-[var(--muted-foreground)]">+ Thêm</span>
              </button>
            );
          })}
        </div>

        {combo.length === 0 && (
          <p className="text-xs text-[var(--muted-foreground)] italic">Chưa chọn backend nào — tìm kiếm sẽ bị tắt</p>
        )}
      </div>

      {/* ChatGPT note */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--muted)] p-4">
        <div className="flex items-center gap-2">
          <Globe className="size-4 text-[var(--muted-foreground)]" />
          <span className="text-sm font-medium text-[var(--foreground)]">ChatGPT & Custom API</span>
        </div>
        <p className="text-xs text-[var(--muted-foreground)] mt-1">
          Model <code className="bg-[var(--secondary)] px-1 rounded">chatgpt/auto</code> tự tìm kiếm web nội bộ. Custom provider (như <code className="bg-[var(--secondary)] px-1 rounded">geminiapi</code>) gửi prompt search đến chat model — phù hợp với Gemini API có Google grounding.
        </p>
      </div>

      {/* Save */}
      <div className="flex justify-end gap-3">
        {msg && <span className={cn("text-sm", msg.startsWith("Lỗi") ? "text-red-500" : "text-emerald-600")}>{msg}</span>}
        <button type="button" onClick={save} disabled={saving}
          className="rounded-[12px] bg-slate-900 px-6 py-2.5 text-[14px] font-medium text-white hover:bg-slate-800 disabled:opacity-50">
          {saving ? "Đang lưu..." : "Lưu cài đặt"}
        </button>
      </div>
    </div>
  );
}

export default function SearchPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return <SearchPageContent />;
}
