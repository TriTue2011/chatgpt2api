"use client";

import { useEffect, useState } from "react";
import { Combine, Plus, Trash2, ArrowDown, GripVertical } from "lucide-react";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

type ComboModels = Record<string, string[]>;

export default function CombosPage() {
  const [combos, setCombos] = useState<ComboModels>({});
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [newModels, setNewModels] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetchCombos();
  }, []);

  async function fetchCombos() {
    try {
      const data = await request.get("/api/settings");
      const config = (data.data as any)?.config || {};
      setCombos(config.combo_models || {});
    } catch (e) {
      console.error("Failed to fetch combos", e);
    } finally {
      setLoading(false);
    }
  }

  async function saveCombos(updated: ComboModels) {
    try {
      await request.post("/api/settings", { combo_models: updated });
      setCombos(updated);
      setError("");
    } catch (e: any) {
      setError(e?.message || "Lỗi lưu");
    }
  }

  function addCombo() {
    const name = newName.trim();
    const modelsStr = newModels.trim();
    if (!name || !modelsStr) return;
    const models = modelsStr.split(",").map((s) => s.trim()).filter(Boolean);
    if (models.length < 2) {
      setError("Cần ít nhất 2 model trong 1 combo (để fallback)");
      return;
    }
    const updated = { ...combos, [name]: models };
    saveCombos(updated);
    setNewName("");
    setNewModels("");
  }

  function removeCombo(name: string) {
    const updated = { ...combos };
    delete updated[name];
    saveCombos(updated);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-stone-400">Đang tải...</p>
      </div>
    );
  }

  const comboEntries = Object.entries(combos);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">Mô hình kết hợp</h1>
        <p className="mt-1 text-sm text-stone-400">
          Combo model tự động fallback qua nhiều provider khi một provider lỗi
        </p>
      </div>

      {/* Add new combo */}
      <div className="rounded-xl border border-stone-800 bg-stone-900/50 p-5">
        <h3 className="mb-3 text-sm font-semibold text-white">Thêm combo mới</h3>
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Tên combo (vd: ha-agent)"
            className="min-w-[180px] rounded-lg border border-stone-700 bg-stone-800 px-3 py-2 text-sm text-white placeholder:text-stone-500 focus:border-stone-500 focus:outline-none"
          />
          <input
            type="text"
            value={newModels}
            onChange={(e) => setNewModels(e.target.value)}
            placeholder="Danh sách model (vd: oc/auto, chatgpt/auto)"
            className="min-w-[320px] flex-1 rounded-lg border border-stone-700 bg-stone-800 px-3 py-2 text-sm text-white placeholder:text-stone-500 focus:border-stone-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={addCombo}
            disabled={!newName.trim() || !newModels.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-stone-50 px-4 py-2 text-sm font-medium text-stone-950 transition hover:bg-white disabled:opacity-40"
          >
            <Plus className="size-4" />
            Thêm
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      </div>

      {/* Combo list */}
      {comboEntries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-stone-500">
          <Combine className="size-12 mb-3 opacity-50" />
          <p>Chưa có combo model nào</p>
          <p className="text-xs mt-1">Tạo combo đầu tiên để tự động fallback khi provider lỗi</p>
        </div>
      ) : (
        <div className="space-y-3">
          {comboEntries.map(([name, models]) => (
            <div
              key={name}
              className="rounded-xl border border-stone-800 bg-stone-900/50 p-5"
            >
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Combine className="size-4 text-stone-400" />
                  <h3 className="font-semibold text-white">{name}</h3>
                  <span className="rounded-md bg-stone-800 px-2 py-0.5 text-[10px] text-stone-400">
                    {models.length} providers
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
              <div className="flex flex-wrap items-center gap-2">
                {models.map((model, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    {idx > 0 && (
                      <ArrowDown className="size-3 text-stone-600" />
                    )}
                    <span
                      className={cn(
                        "rounded-lg px-3 py-1.5 text-xs font-medium",
                        idx === 0
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                          : "bg-stone-800 text-stone-300",
                      )}
                    >
                      {idx === 0 && "❶ "}
                      {model}
                    </span>
                  </div>
                ))}
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
