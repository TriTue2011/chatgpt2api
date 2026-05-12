"use client";

import { useEffect, useState } from "react";
import {
  Combine, Plus, Trash2, ArrowDown, MessageSquare,
  ImageIcon, Eye, X, ChevronDown, Save,
} from "lucide-react";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

type ModelInfo = {
  id: string;
  owned_by: string;
  capability: string;
  capabilities: string[];
  capability_labels: string[];
  enabled: boolean;
};

type ComboModels = Record<string, string[]>;

const CAP_COLORS: Record<string, string> = {
  chat: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  vision: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  image: "bg-amber-500/10 text-amber-400 border-amber-500/20",
};

const CAP_ICONS: Record<string, typeof MessageSquare> = {
  chat: MessageSquare,
  vision: Eye,
  image: ImageIcon,
};

export default function CombosPage() {
  const [combos, setCombos] = useState<ComboModels>({});
  const [allModels, setAllModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [filterCap, setFilterCap] = useState<string>("all");
  const [dropdownOpen, setDropdownOpen] = useState(false);

  useEffect(() => {
    loadAll();
  }, []);

  async function loadAll() {
    setLoading(true);
    try {
      const [comboRes, modelsRes] = await Promise.all([
        request.get("/api/settings"),
        request.get("/api/v1/models-with-capabilities"),
      ]);
      const config = (comboRes.data as any)?.config || {};
      setCombos(config.combo_models || {});
      setAllModels((modelsRes.data as any)?.models || []);
    } catch (e) {
      console.error("Failed to load", e);
    } finally {
      setLoading(false);
    }
  }

  async function saveCombos(updated: ComboModels) {
    // Optimistic UI update first
    setCombos(updated);
    setSaved(true);
    setError("");
    try {
      const res = await request.post("/api/settings", { combo_models: updated });
      const cfg = (res.data as any)?.config || {};
      const returned = cfg.combo_models || {};
      setCombos(returned);
      if (JSON.stringify(returned) !== JSON.stringify(updated)) {
        console.warn("Combo save mismatch, server returned:", returned);
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail?.error || e?.message || "Lỗi lưu";
      setError(msg);
      await loadAll(); // Reload from server to restore correct state
    }
    setTimeout(() => setSaved(false), 2000);
  }

  function addCombo() {
    const name = newName.trim();
    if (!name) return;
    if (selectedModels.length < 2) {
      setError("Cần ít nhất 2 model trong 1 combo (để fallback)");
      return;
    }
    const updated = { ...combos, [name]: [...selectedModels] };
    saveCombos(updated);
    setNewName("");
    setSelectedModels([]);
  }

  function removeCombo(name: string) {
    const updated = { ...combos };
    delete updated[name];
    // Optimistic update — remove from UI immediately
    setCombos(updated);
    saveCombos(updated);
  }

  function addModelToSelection(modelId: string) {
    if (!selectedModels.includes(modelId)) {
      setSelectedModels([...selectedModels, modelId]);
    }
    setDropdownOpen(false);
  }

  function removeModelFromSelection(idx: number) {
    setSelectedModels(selectedModels.filter((_, i) => i !== idx));
  }

  const filteredModels = allModels.filter(m => {
    if (filterCap === "all") return true;
    return (m.capabilities || [m.capability]).includes(filterCap);
  });

  const availableForSelection = filteredModels.filter(m => !selectedModels.includes(m.id));

  // Counts (a model can have multiple capabilities)
  const counts = { chat: 0, vision: 0, image: 0 };
  for (const m of allModels) {
    const caps = m.capabilities || [m.capability];
    for (const c of caps) {
      if (c in counts) counts[c as keyof typeof counts]++;
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-stone-500">Đang tải...</p>
      </div>
    );
  }

  const comboEntries = Object.entries(combos);

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-stone-900">Mô hình kết hợp</h1>
            {saved && <span className="text-xs text-emerald-600 font-medium">✓ Đã lưu</span>}
          </div>
          <button
            type="button"
            onClick={() => saveCombos(combos)}
            className="inline-flex items-center gap-2 rounded-xl bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-800 transition"
          >
            <Save className="size-4" />
            Lưu tất cả
          </button>
        </div>
        <p className="mt-1 text-sm text-stone-500">
          Combo model tự động fallback qua nhiều provider theo thứ tự ưu tiên. Chọn model từ danh sách đã bật trong Quản lý Model.
        </p>
      </div>

      {/* Model stats */}
      <div className="flex gap-3 flex-wrap">
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-400">
          <MessageSquare className="size-3" /> Chat: {counts.chat}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-purple-500/20 bg-purple-500/10 px-3 py-1.5 text-xs text-purple-400">
          <Eye className="size-3" /> Phân tích ảnh: {counts.vision}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-400">
          <ImageIcon className="size-3" /> Tạo ảnh: {counts.image}
        </span>
      </div>

      {/* Add new combo */}
      <div className="rounded-xl border border-stone-200 bg-white/80 p-5">
        <h3 className="mb-3 text-sm font-semibold text-stone-900">Thêm combo mới</h3>

        {/* Combo name */}
        <div className="mb-3">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Tên combo (vd: ha-agent)"
            className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none"
          />
        </div>

        {/* Selected models (ordered) */}
        {selectedModels.length > 0 && (
          <div className="mb-3 space-y-1.5">
            <p className="text-[10px] font-medium uppercase tracking-wider text-stone-500">
              Thứ tự fallback ({selectedModels.length} model)
            </p>
            {selectedModels.map((modelId, idx) => {
              const info = allModels.find(m => m.id === modelId);
              const cap = info?.capability || "chat";
              const CapIcon = CAP_ICONS[cap] || MessageSquare;
              return (
                <div key={idx} className="flex items-center gap-2 rounded-lg bg-stone-100/50 px-3 py-2">
                  <span className={cn(
                    "text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center shrink-0",
                    idx === 0 ? "bg-emerald-500/20 text-emerald-400" : "bg-stone-200 text-stone-500",
                  )}>
                    {idx + 1}
                  </span>
                  <CapIcon className="size-3 shrink-0 text-stone-500" />
                  <span className="flex-1 text-xs font-mono text-stone-800 truncate">{modelId}</span>
                  {(info?.capability_labels || [info?.capability_label || "Chat"]).map((label: string) => {
                    const capKey = label === "Chat" ? "chat" : label === "Phân tích ảnh" ? "vision" : "image";
                    return <span key={label} className={cn("text-[10px] px-1.5 py-0.5 rounded border", CAP_COLORS[capKey])}>{label}</span>;
                  })}
                  <button
                    type="button"
                    onClick={() => removeModelFromSelection(idx)}
                    className="rounded p-0.5 text-stone-500 hover:bg-red-500/10 hover:text-red-400"
                  >
                    <X className="size-3.5" />
                  </button>
                  {idx < selectedModels.length - 1 && (
                    <ArrowDown className="size-3 text-stone-600 shrink-0" />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Model picker */}
        <div className="flex gap-2 mb-3">
          {/* Capability filter */}
          <div className="flex rounded-lg border border-stone-200 overflow-hidden text-xs">
            {(["all", "chat", "vision", "image"] as const).map(cap => (
              <button
                key={cap}
                type="button"
                onClick={() => setFilterCap(cap)}
                className={cn(
                  "px-3 py-1.5 transition",
                  filterCap === cap
                    ? "bg-stone-900 text-white"
                    : "text-stone-500 hover:text-stone-700",
                )}
              >
                {cap === "all" ? "Tất cả" : cap === "chat" ? "Chat" : cap === "vision" ? "Vision" : "Tạo ảnh"}
              </button>
            ))}
          </div>

          {/* Dropdown */}
          <div className="relative flex-1">
            <button
              type="button"
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex w-full items-center justify-between rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-900 hover:border-stone-600 transition"
            >
              <span className="text-stone-500">Chọn model để thêm vào chuỗi fallback...</span>
              <ChevronDown className="size-4 text-stone-500" />
            </button>

            {dropdownOpen && (
              <div className="absolute z-30 mt-1 w-full max-h-64 overflow-y-auto rounded-lg border border-stone-200 bg-white shadow-xl">
                {availableForSelection.length === 0 ? (
                  <p className="px-3 py-4 text-xs text-stone-500 text-center">
                    {filterCap !== "all" ? "Không có model nào trong danh mục này" : "Tất cả model đã được chọn"}
                  </p>
                ) : (
                  availableForSelection.map(m => {
                    const CapIcon = CAP_ICONS[m.capability] || MessageSquare;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => addModelToSelection(m.id)}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-stone-100 transition"
                      >
                        <CapIcon className="size-3 shrink-0 text-stone-500" />
                        <span className="text-stone-800 font-mono truncate flex-1">{m.id}</span>
                        {(m.capability_labels || [m.capability_label || "Chat"]).map((label: string) => {
                          const capKey = label === "Chat" ? "chat" : label === "Phân tích ảnh" ? "vision" : "image";
                          return <span key={label} className={cn("text-[10px] px-1.5 py-0.5 rounded border shrink-0", CAP_COLORS[capKey])}>{label}</span>;
                        })}
                        </span>
                        <span className="text-[10px] text-stone-600">{m.owned_by}</span>
                      </button>
                    );
                  })
                )}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={addCombo}
            disabled={!newName.trim() || selectedModels.length < 2}
            className="inline-flex items-center gap-1.5 rounded-lg bg-stone-100 px-4 py-2 text-sm font-medium text-stone-950 transition hover:bg-white disabled:opacity-40 shrink-0"
          >
            <Plus className="size-4" />
            Thêm
          </button>
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>

      {/* Existing combos */}
      {comboEntries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-stone-500">
          <Combine className="size-12 mb-3 opacity-50" />
          <p>Chưa có combo model nào</p>
          <p className="text-xs mt-1">Tạo combo đầu tiên để tự động fallback khi provider lỗi</p>
        </div>
      ) : (
        <div className="space-y-3">
          {comboEntries.map(([name, models]) => (
            <div key={name} className="rounded-xl border border-stone-200 bg-white/80 p-5">
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Combine className="size-4 text-stone-500" />
                  <h3 className="font-semibold text-stone-900">{name}</h3>
                  <span className="rounded-md bg-stone-100 px-2 py-0.5 text-[10px] text-stone-500">
                    {models.length} model
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => removeCombo(name)}
                  className="rounded-md p-1.5 text-stone-500 transition hover:bg-red-500/10 hover:text-red-400"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>

              {/* Model chain */}
              <div className="space-y-1.5">
                {models.map((modelId, idx) => {
                  const info = allModels.find(m => m.id === modelId);
                  const cap = info?.capability || "chat";
                  const CapIcon = CAP_ICONS[cap] || MessageSquare;
                  return (
                    <div key={idx} className="flex items-center gap-2">
                      <span className={cn(
                        "text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center shrink-0",
                        idx === 0 ? "bg-emerald-500/20 text-emerald-400" : "bg-stone-200 text-stone-500",
                      )}>
                        {idx + 1}
                      </span>
                      <CapIcon className="size-3 shrink-0 text-stone-500" />
                      <span className={cn(
                        "rounded-lg px-3 py-1.5 text-xs font-mono",
                        idx === 0
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                          : "bg-stone-100 text-stone-700",
                      )}>
                        {modelId}
                      </span>
                      {(info?.capability_labels || [info?.capability_label || "Chat"]).map((label: string) => {
                        const capKey = label === "Chat" ? "chat" : label === "Phân tích ảnh" ? "vision" : "image";
                        return <span key={label} className={cn("text-[10px] px-1.5 py-0.5 rounded border", CAP_COLORS[capKey])}>{label}</span>;
                      })}
                      {idx < models.length - 1 && (
                        <ArrowDown className="size-3 text-stone-600" />
                      )}
                    </div>
                  );
                })}
              </div>
              <p className="mt-3 text-xs text-stone-500">
                Thứ tự fallback: thử model ❶ trước → nếu lỗi mới thử model tiếp theo
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
