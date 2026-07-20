"use client";

import { useEffect, useState } from "react";
import {
  Combine, Plus, Trash2, ArrowDown, MessageSquare,
  ImageIcon, Eye, X, ChevronDown, Save, Video, Camera,
  Pencil, Check, ArrowUp,
} from "lucide-react";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";
import { useLangStore } from "@/store/lang";
import { translations, TranslationKey } from "@/lib/i18n";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

function ModelPickerModal({
  open, onClose, title, models, excludeIds, selectedIds, onPick,
  showSearch, onSearchChange, emptyMessage,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  models: ModelInfo[];
  excludeIds: string[];
  selectedIds?: string[];
  onPick: (id: string) => void;
  showSearch?: boolean;
  onSearchChange?: (v: string) => void;
  emptyMessage: string;
}) {
  const filtered = models.filter((m) => !excludeIds.includes(m.id));
  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent showCloseButton className="!p-0">
        <DialogHeader className="px-6 pt-6">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {filtered.length} model khả dụng
            {excludeIds.length > 0 ? ` (đã loại ${excludeIds.length} model đã thêm)` : ""}
          </DialogDescription>
        </DialogHeader>
        {showSearch && (
          <div className="px-6 pb-2">
            <input
              autoFocus
              className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:border-[var(--border)] focus:outline-none"
              placeholder="Tìm model... (lọc theo tên)"
              onChange={(e) => onSearchChange?.(e.target.value)}
            />
          </div>
        )}
        <div className="flex-1 overflow-y-auto px-3 pb-3">
          {filtered.length === 0 ? (
            <p className="px-4 py-8 text-sm text-[var(--muted-foreground)] text-center">{emptyMessage}</p>
          ) : filtered.map((m) => {
            const isSelected = selectedIds?.includes(m.id);
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => onPick(m.id)}
                className={cn(
                  "flex w-full items-center gap-3 px-4 py-2.5 text-left rounded-lg transition mb-0.5",
                  isSelected ? "bg-emerald-50 border border-emerald-200" : "hover:bg-[var(--muted)] border border-transparent",
                )}
              >
                <span className="text-[13px] font-mono text-[var(--foreground)] truncate flex-1">{m.id}</span>
                <span className="text-[10px] text-[var(--muted-foreground)]">{m.owned_by}</span>
                {isSelected && <Check className="size-4 text-emerald-500 shrink-0" />}
              </button>
            );
          })}
        </div>
        <DialogFooter className="px-6 pb-6">
          <Button
            variant="secondary"
            className="h-10 rounded-xl bg-[var(--secondary)] px-5 text-[var(--foreground)] hover:bg-[var(--secondary)]"
            onClick={onClose}
          >
            Đóng
          </Button>
          <Button
            className="h-10 rounded-xl bg-[var(--primary)] px-5 text-[var(--primary-foreground)] hover:brightness-110"
            onClick={onClose}
          >
            Xong
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type ModelInfo = {
  id: string;
  owned_by: string;
  capability: string;
  capabilities: string[];
  capability_labels: string[];
  enabled: boolean;
};

type ComboModels = Record<string, string[]>;

// Combo Code (pipeline bố-con) — config key riêng `pipeline_models`,
// TÁCH BIỆT hoàn toàn với combo_models: BỐ lập kế hoạch, CON viết code.
type PipelineModels = Record<string, { architects: string[]; editors: string[] }>;

const CAP_COLORS: Record<string, string> = {
  chat: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  vision: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  image: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  video: "bg-rose-500/10 text-rose-400 border-rose-500/20",
};

const CAP_ICONS: Record<string, typeof MessageSquare> = {
  chat: MessageSquare, vision: Eye, image: ImageIcon, video: Video,
};

const TINT_CYCLE = ["card-tint-indigo", "card-tint-emerald", "card-tint-amber", "card-tint-violet", "card-tint-sky", "card-tint-rose"] as const;

function ModelChainView({ models, allModels, t }: { models: string[]; allModels: ModelInfo[]; t: (key: TranslationKey) => string }) {
  return (
    <div>
      <div className="space-y-1.5">
        {models.map((modelId, idx) => {
          const info = allModels.find(m => m.id === modelId);
          const cap = info?.capability || "chat";
          const CapIcon = CAP_ICONS[cap] || MessageSquare;
          return (
            <div key={idx} className="flex items-center gap-2">
              <span className={cn("text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center shrink-0", idx === 0 ? "bg-emerald-500/20 text-emerald-400" : "bg-[var(--secondary)] text-[var(--muted-foreground)]")}>{idx + 1}</span>
              <CapIcon className="size-3 shrink-0 text-[var(--muted-foreground)]" />
              <span className={cn("rounded-lg px-3 py-1.5 text-xs font-mono", idx === 0 ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-[var(--secondary)] text-[var(--foreground)]")}>{modelId}</span>
              {(info?.capability_labels || ["Chat"]).map((label: string) => {
                const capKey = label === "Chat" ? "chat" : label === t("vision") ? "vision" : label === "Phân tích ảnh" ? "vision" : label === "Video" ? "video" : label === "Phân tích video" ? "video" : "image";
                return <span key={label} className={cn("text-[10px] px-1.5 py-0.5 rounded border", CAP_COLORS[capKey])}>{label}</span>;
              })}
              {idx < models.length - 1 && <ArrowDown className="size-3 text-[var(--muted-foreground)]" />}
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-[var(--muted-foreground)]">Thứ tự fallback: thử model ❶ trước → nếu lỗi mới thử model tiếp theo</p>
    </div>
  );
}

function ComboEditView({ editModels, editName, setEditName, allModels, filteredModels, dropdownOpen, setDropdownOpen, removeFromEdit, addToEdit, swapInEdit, moveUpInEdit, moveDownInEdit, cancelEdit, saveEdit }: {
  editName: string; setEditName: (v: string) => void; swapInEdit: (idx: number, newId: string) => void;
  editModels: string[]; allModels: ModelInfo[]; filteredModels: ModelInfo[];
  dropdownOpen: boolean; setDropdownOpen: (v: boolean) => void;
  removeFromEdit: (idx: number) => void; addToEdit: (id: string) => void;
  moveUpInEdit: (idx: number) => void; moveDownInEdit: (idx: number) => void;
  cancelEdit: () => void; saveEdit: () => void;
}) {
  const [swapIdx, setSwapIdx] = useState<number | null>(null);
  return (
    <div className="space-y-3">
      <input type="text" value={editName} onChange={(e) => setEditName(e.target.value)} placeholder="Tên combo" className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm font-bold text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:border-violet-400 focus:outline-none" />
      {editModels.length > 0 && (
        <div className="space-y-1.5">
          {editModels.map((modelId, idx) => {
            const info = allModels.find(m => m.id === modelId);
            const cap = info?.capability || "chat";
            const CapIcon = CAP_ICONS[cap] || MessageSquare;
            return (
              <div key={idx} className="flex items-center gap-2">
                <span className={cn("text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center shrink-0", idx === 0 ? "bg-emerald-500/20 text-emerald-400" : "bg-[var(--secondary)] text-[var(--muted-foreground)]")}>{idx + 1}</span>
                <CapIcon className="size-3 shrink-0 text-[var(--muted-foreground)]" />
                <button type="button" onClick={() => setSwapIdx(idx)} className="rounded-lg px-3 py-1.5 text-xs font-mono bg-[var(--secondary)] text-[var(--foreground)] flex-1 text-left flex items-center justify-between hover:border-violet-400 border border-transparent transition group" title="Đổi model khác"><span>{modelId}</span><ChevronDown className="size-3 text-[var(--muted-foreground)] opacity-0 group-hover:opacity-100 transition" /></button>
                <div className="flex flex-col gap-0.5">
                  <button type="button" onClick={() => moveUpInEdit(idx)} disabled={idx === 0} className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--secondary)] hover:text-[var(--foreground)] disabled:opacity-30"><ArrowUp className="size-3" /></button>
                  <button type="button" onClick={() => moveDownInEdit(idx)} disabled={idx === editModels.length - 1} className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--secondary)] hover:text-[var(--foreground)] disabled:opacity-30"><ArrowDown className="size-3" /></button>
                </div>
                <button type="button" onClick={() => removeFromEdit(idx)} className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-rose-50 hover:text-rose-500"><X className="size-3.5" /></button>
              </div>
            );
          })}
        </div>
      )}
      <div className="relative">
        <button type="button" onClick={() => setDropdownOpen(true)} className="flex w-full items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)] hover:border-[var(--border)] transition">
          <span className="text-[var(--muted-foreground)]">+ Thêm model vào chuỗi</span>
          <ChevronDown className="size-4 text-[var(--muted-foreground)]" />
        </button>
        <ModelPickerModal
          open={dropdownOpen}
          onClose={() => setDropdownOpen(false)}
          title="Thêm Model vào chuỗi"
          models={filteredModels}
          excludeIds={editModels}
          onPick={(id) => { addToEdit(id); setDropdownOpen(false); }}
          emptyMessage="Đã thêm tất cả model"
        />
        <ModelPickerModal
          open={swapIdx !== null}
          onClose={() => setSwapIdx(null)}
          title="Đổi Model"
          models={filteredModels}
          excludeIds={editModels}
          onPick={(id) => { if (swapIdx !== null) swapInEdit(swapIdx, id); setSwapIdx(null); }}
          emptyMessage="Đã thêm tất cả model"
        />
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={cancelEdit} className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--secondary)]">Hủy</button>
        <button type="button" onClick={saveEdit} disabled={editModels.length < 2} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-xs text-[var(--primary-foreground)] hover:brightness-110 disabled:opacity-40">
          <Check className="size-3.5" /> Lưu
        </button>
      </div>
    </div>
  );
}

export default function CombosPage() {
  const { lang } = useLangStore();
  const t = (key: TranslationKey) => translations[lang][key] || key;
  const [combos, setCombos] = useState<ComboModels>({});
  const [allModels, setAllModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [editingCombo, setEditingCombo] = useState<string | null>(null);
  const [editModels, setEditModels] = useState<string[]>([]);
  const [editComboName, setEditComboName] = useState("");
  const [fullConfig, setFullConfig] = useState<any>({});
  const [editingPipelineName, setEditingPipelineName] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [filterCap, setFilterCap] = useState<string>("all");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [editDropdownOpen, setEditDropdownOpen] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  // ── Combo Code (pipeline bố-con) — state riêng, không dính combo thường ──
  const [pipelines, setPipelines] = useState<PipelineModels>({});
  const [plName, setPlName] = useState("");
  const [plArchitect, setPlArchitect] = useState("");
  const [plEditors, setPlEditors] = useState<string[]>([]);
  const [plArchOpen, setPlArchOpen] = useState(false);
  const [plEdOpen, setPlEdOpen] = useState(false);
  const [plError, setPlError] = useState("");
  const [swapPlIdx, setSwapPlIdx] = useState<number | null>(null);

  useEffect(() => { loadAll(); }, []);

  async function loadAll() {
    setLoading(true);
    try {
      const [comboRes, modelsRes] = await Promise.all([
        request.get("/api/settings"),
        request.get("/api/v1/models-with-capabilities"),
      ]);
      const config = (comboRes.data as any)?.config || {};
      setFullConfig(config);
      setCombos(config.combo_models || {});
      setPipelines(config.pipeline_models || {});
      setAllModels((modelsRes.data as any)?.models?.filter((m: any) => m.enabled !== false) || []);
    } catch (e) { console.error("Failed to load", e); }
    finally { setLoading(false); }
  }

  async function applyRenameAndSave(oldName: string, newName: string, isPipeline: boolean, updatedData: any) {
    if (!newName) return;
    try {
      const cur = await request.get("/api/settings");
      const cfg = (cur.data as any)?.config || {};
      
      if (oldName !== newName) {
        if (!isPipeline && cfg.combo_models && cfg.combo_models[oldName]) {
          delete cfg.combo_models[oldName];
        }
        if (isPipeline && cfg.pipeline_models && cfg.pipeline_models[oldName]) {
          delete cfg.pipeline_models[oldName];
        }

        const replaceName = (arr: string[]) => arr.map(m => m === oldName ? newName : m);
        
        if (cfg.combo_models) {
          for (const [k, v] of Object.entries(cfg.combo_models)) {
            cfg.combo_models[k] = replaceName(v as string[]);
          }
        }
        if (cfg.pipeline_models) {
          for (const [k, p] of Object.entries(cfg.pipeline_models)) {
            const pm = p as any;
            if (pm.architects) pm.architects = replaceName(pm.architects);
            if (pm.editors) pm.editors = replaceName(pm.editors);
          }
        }
        if (cfg.model_settings) {
          if (cfg.model_settings.enabled_models) {
            for (const [provider, models] of Object.entries(cfg.model_settings.enabled_models)) {
              if (Array.isArray(models)) {
                (cfg.model_settings.enabled_models as any)[provider] = replaceName(models);
              }
            }
          }
          if (cfg.model_settings.default_chat_model === oldName) cfg.model_settings.default_chat_model = newName;
          if (cfg.model_settings.default_vision_model === oldName) cfg.model_settings.default_vision_model = newName;
          if (cfg.model_settings.default_image_model === oldName) cfg.model_settings.default_image_model = newName;
          if (cfg.model_settings.default_models) {
            for (const key of Object.keys(cfg.model_settings.default_models)) {
              if (cfg.model_settings.default_models[key] === oldName) {
                cfg.model_settings.default_models[key] = newName;
              }
            }
          }
        }
        if (cfg.search && cfg.search.default_model === oldName) {
          cfg.search.default_model = newName;
        }
        if (cfg.backends) {
          if (cfg.backends.default_chat === oldName) cfg.backends.default_chat = newName;
          if (cfg.backends.default_image === oldName) cfg.backends.default_image = newName;
        }
        if (cfg.telegram_ai_model === oldName) {
          cfg.telegram_ai_model = newName;
        }
        if (cfg.openai_default_model === oldName) {
          cfg.openai_default_model = newName;
        }
        if (cfg.agent_branches) {
          for (const key of Object.keys(cfg.agent_branches)) {
            if (cfg.agent_branches[key] === oldName) {
              cfg.agent_branches[key] = newName;
            }
          }
        }
      }
      
      if (!isPipeline) {
        if (!cfg.combo_models) cfg.combo_models = {};
        cfg.combo_models[newName] = updatedData;
      } else {
        if (!cfg.pipeline_models) cfg.pipeline_models = {};
        cfg.pipeline_models[newName] = updatedData;
      }
      
      await request.post("/api/settings", cfg);
      setFullConfig(cfg);
      setCombos(cfg.combo_models || {});
      setPipelines(cfg.pipeline_models || {});
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) { console.error("Rename fail", e); }
  }

  async function saveCombos(updated: ComboModels) {
    setCombos(updated); setSaved(true); setError("");
    try {
      const res = await request.post("/api/settings", { combo_models: updated });
      const cfg = (res.data as any)?.config || {};
      setCombos(cfg.combo_models || {});
    } catch (e: any) {
      setError(e?.response?.data?.detail?.error || e?.message || t("saveError"));
      await loadAll();
    }
    setTimeout(() => setSaved(false), 2000);
  }

  // ── Combo Code (pipeline bố-con) ──
  async function savePipelines(updated: PipelineModels) {
    setPipelines(updated); setSaved(true); setPlError("");
    try {
      const res = await request.post("/api/settings", { pipeline_models: updated });
      const cfg = (res.data as any)?.config || {};
      setPipelines(cfg.pipeline_models || {});
    } catch (e: any) {
      setPlError(e?.response?.data?.detail?.error || e?.message || t("saveError"));
      await loadAll();
    }
    setTimeout(() => setSaved(false), 2000);
  }

  async function addPipeline() {
    const name = plName.trim();
    if (!name) { setPlError("Cần đặt tên (vd: code)"); return; }
    if (!plArchitect) { setPlError("Cần chọn model BỐ"); return; }
    if (plEditors.length < 1) { setPlError("Cần ít nhất 1 model CON"); return; }
    
    await applyRenameAndSave(editingPipelineName || name, name, true, { architects: [plArchitect], editors: [...plEditors] });
    setEditingPipelineName(null); setPlName(""); setPlArchitect(""); setPlEditors([]); setPlError("");
  }

  function removePipeline(name: string) {
    const updated = { ...pipelines }; delete updated[name];
    savePipelines(updated);
  }

    function editPipeline(name: string) {
    const p = pipelines[name];
    if (!p) return;
    setEditingPipelineName(name);
    setPlName(name);
    setPlArchitect((p.architects || [])[0] || "");
    setPlEditors([...(p.editors || [])]);
    setPlError("");
  }

  function movePlEditor(idx: number, dir: -1 | 1) {
    const j = idx + dir;
    if (j < 0 || j >= plEditors.length) return;
    const updated = [...plEditors];
    [updated[idx], updated[j]] = [updated[j], updated[idx]];
    setPlEditors(updated);
  }

  function addCombo() {
    const name = newName.trim();
    if (!name) return;
    if (selectedModels.length < 2) { setError(t("atLeastTwoModels")); return; }
    saveCombos({ ...combos, [name]: [...selectedModels] });
    setNewName(""); setSelectedModels([]);
  }

  function removeCombo(name: string) {
    const updated = { ...combos }; delete updated[name];
    setCombos(updated); saveCombos(updated);
  }

  function startEdit(name: string) {
    setEditingCombo(name); setEditComboName(name); setEditModels([...(combos[name] || [])]);
  }
  function cancelEdit() { setEditingCombo(null); setEditComboName(""); setEditModels([]); }
  function addToEdit(modelId: string) { if (!editModels.includes(modelId)) setEditModels([...editModels, modelId]); }
  function swapInEdit(idx: number, newId: string) {
    const updated = [...editModels];
    updated[idx] = newId;
    setEditModels(updated);
  }
  function removeFromEdit(idx: number) { setEditModels(editModels.filter((_, i) => i !== idx)); }
  function moveUpInEdit(idx: number) {
    if (idx <= 0) return;
    const updated = [...editModels];
    [updated[idx - 1], updated[idx]] = [updated[idx], updated[idx - 1]];
    setEditModels(updated);
  }
  function moveDownInEdit(idx: number) {
    if (idx >= editModels.length - 1) return;
    const updated = [...editModels];
    [updated[idx], updated[idx + 1]] = [updated[idx + 1], updated[idx]];
    setEditModels(updated);
  }
  async function saveEdit() {
    if (!editingCombo || editModels.length < 2) return;
    const newName = editComboName.trim() || editingCombo;
    await applyRenameAndSave(editingCombo, newName, false, [...editModels]);
    setEditingCombo(null); setEditComboName(""); setEditModels([]);
  }

  function addModelToSelection(modelId: string) {
    if (!selectedModels.includes(modelId)) setSelectedModels([...selectedModels, modelId]);
    setDropdownOpen(false);
  }
  function removeModelFromSelection(idx: number) { setSelectedModels(selectedModels.filter((_, i) => i !== idx)); }

  const filteredModels = allModels.filter(m => {
    // Chỉ cho chọn model đã tích trong Quản lý Model (+ các model /auto).
    if (m.enabled === false && !m.id.endsWith("/auto")) return false;
    if (modelSearch && !m.id.toLowerCase().includes(modelSearch.toLowerCase())) return false;
    if (filterCap === "all") return true;
    return (m.capabilities || [m.capability]).includes(filterCap);
  });
  const availableForSelection = filteredModels.filter(m => !selectedModels.includes(m.id));

  const counts = { chat: 0, vision: 0, image: 0, video: 0 };
  for (const m of allModels) {
    if (m.enabled === false) continue;
    for (const c of (m.capabilities || [m.capability])) { if (c in counts) counts[c as keyof typeof counts]++; }
  }

  if (loading) return <div className="flex items-center justify-center py-20"><p className="text-[var(--muted-foreground)]">Đang tải...</p></div>;

  const comboEntries = Object.entries(combos);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1 border-b border-black/[0.04] pb-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-[24px] font-bold tracking-tight text-[var(--foreground)]">{t("combosTitle")}</h1>
            {saved && <span className="text-[13px] text-emerald-600 font-medium">✓ {t("saved")}</span>}
          </div>
          <button type="button" onClick={() => saveCombos(combos)} className="inline-flex items-center gap-2 rounded-[12px] bg-slate-900 px-4 py-2 text-[14px] font-medium text-white hover:bg-slate-800 transition">
            <Save className="size-4" /> Lưu
          </button>
        </div>
        <p className="text-[14px] text-[var(--muted-foreground)]">Combo model tự động fallback qua nhiều provider theo thứ tự ưu tiên.</p>
      </div>

      <div className="flex gap-3 flex-wrap">
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-400"><MessageSquare className="size-3" /> {t("chat")}: {counts.chat}</span>
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-purple-500/20 bg-purple-500/10 px-3 py-1.5 text-xs text-purple-400"><Eye className="size-3" /> {t("vision")}: {counts.vision}</span>
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-400"><ImageIcon className="size-3" /> {t("imageGen")}: {counts.image}</span>
      </div>

      {/* ── Combo Code (pipeline bố-con) — KHU RIÊNG, tách biệt combo thường ── */}
      <div className="rounded-[16px] p-6 border-2 border-violet-300/60 bg-violet-50/40">
        <div className="mb-1 flex items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-[10px] bg-violet-100"><Combine className="size-[18px] text-violet-500" /></div>
          <h3 className="text-[15px] font-bold text-[var(--foreground)]">Combo Code — Pipeline bố-con</h3>
          <span className="rounded-md bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-600">dành cho viết code</span>
        </div>
        <p className="mb-4 text-xs text-[var(--muted-foreground)]">
          <span className="font-semibold text-amber-600">BỐ</span> (model mạnh) lập kế hoạch ngắn → <span className="font-semibold text-emerald-600">CON</span> (model rẻ/free) viết code theo kế hoạch; CON sau là fallback của CON trước. Khu này tách biệt hoàn toàn với combo thường bên dưới.
        </p>

        {/* Form tạo/sửa */}
        <div className="mb-4 space-y-2">
          <input type="text" value={plName} onChange={(e) => setPlName(e.target.value)} placeholder="Tên combo code (vd: code)" className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:border-violet-400 focus:outline-none" />
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded border bg-amber-500/10 text-amber-600 border-amber-500/20 shrink-0 w-24 text-center">BỐ · kế hoạch</span>
            <button type="button" onClick={() => setPlArchOpen(true)} className="flex flex-1 items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm hover:border-violet-400 transition">
              <span className={plArchitect ? "font-mono text-xs text-[var(--foreground)]" : "text-[var(--muted-foreground)]"}>{plArchitect || "Chọn model BỐ (mạnh, để lập kế hoạch)"}</span>
              <ChevronDown className="size-4 text-[var(--muted-foreground)]" />
            </button>
            {plArchitect && <button type="button" onClick={() => setPlArchitect("")} className="rounded p-1 text-[var(--muted-foreground)] hover:bg-rose-50 hover:text-rose-500"><X className="size-3.5" /></button>}
          </div>
          {plEditors.map((id, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded border bg-emerald-500/10 text-emerald-600 border-emerald-500/20 shrink-0 w-24 text-center">CON #{idx + 1} · code</span>
              <button type="button" onClick={() => setSwapPlIdx(idx)} className="flex-1 rounded-lg bg-[var(--card)] border border-[var(--border)] px-3 py-2 text-xs font-mono text-[var(--foreground)] text-left hover:border-violet-400 transition flex items-center justify-between group" title="Đổi model khác"><span>{id}</span><ChevronDown className="size-3 text-[var(--muted-foreground)] opacity-0 group-hover:opacity-100 transition" /></button>
              <div className="flex flex-col gap-0.5">
                <button type="button" onClick={() => movePlEditor(idx, -1)} disabled={idx === 0} className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--secondary)] disabled:opacity-30"><ArrowUp className="size-3" /></button>
                <button type="button" onClick={() => movePlEditor(idx, 1)} disabled={idx === plEditors.length - 1} className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-[var(--secondary)] disabled:opacity-30"><ArrowDown className="size-3" /></button>
              </div>
              <button type="button" onClick={() => setPlEditors(plEditors.filter((_, i) => i !== idx))} className="rounded p-1 text-[var(--muted-foreground)] hover:bg-rose-50 hover:text-rose-500"><X className="size-3.5" /></button>
            </div>
          ))}
          <div className="flex gap-2">
            <button type="button" onClick={() => setPlEdOpen(true)} className="flex flex-1 items-center justify-between rounded-lg border border-dashed border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--muted-foreground)] hover:border-violet-400 transition">
              <span>+ Thêm model CON (rẻ/free, để viết code)</span>
              <ChevronDown className="size-4 text-[var(--muted-foreground)]" />
            </button>
            {editingPipelineName && (<button type="button" onClick={() => { setPlName(""); setPlArchitect(""); setPlEditors([]); setEditingPipelineName(null); setPlError(""); }} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-2 text-sm font-medium text-[var(--muted-foreground)] hover:bg-[var(--secondary)] transition shrink-0">Hủy</button>)}
            <button type="button" onClick={addPipeline} className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-violet-700 shrink-0">
              <Check className="size-4" /> {editingPipelineName ? "Lưu (cập nhật)" : "Lưu"}
            </button>
          </div>
          {plError && <p className="text-xs text-red-400">{plError}</p>}
        </div>
        <ModelPickerModal open={plArchOpen} onClose={() => setPlArchOpen(false)} title="Chọn model BỐ (lập kế hoạch)" models={filteredModels} excludeIds={plEditors} selectedIds={plArchitect ? [plArchitect] : []} onPick={(id) => { setPlArchitect(id); setPlArchOpen(false); }} showSearch onSearchChange={setModelSearch} emptyMessage={t("allModelsSelected")} />
        <ModelPickerModal open={swapPlIdx !== null} onClose={() => setSwapPlIdx(null)} title="Đổi model CON" models={filteredModels} excludeIds={[...plEditors, ...(plArchitect ? [plArchitect] : [])]} onPick={(id) => { if (swapPlIdx !== null) { const updated = [...plEditors]; updated[swapPlIdx] = id; setPlEditors(updated); } setSwapPlIdx(null); }} showSearch onSearchChange={setModelSearch} emptyMessage={t("allModelsSelected")} />
        <ModelPickerModal open={plEdOpen} onClose={() => setPlEdOpen(false)} title="Thêm model CON (viết code)" models={filteredModels} excludeIds={[...plEditors, ...(plArchitect ? [plArchitect] : [])]} onPick={(id) => { setPlEditors([...plEditors, id]); setPlEdOpen(false); }} showSearch onSearchChange={setModelSearch} emptyMessage={t("allModelsSelected")} />

        {/* Danh sách combo code hiện có */}
        {Object.entries(pipelines).length > 0 && (
          <div className="space-y-2">
            {Object.entries(pipelines).map(([name, p]) => (
              <div key={name} className="rounded-[12px] border border-violet-200/60 bg-[var(--card)] p-4">
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h4 className="text-[14px] font-bold text-[var(--foreground)]">{name}</h4>
                    <span className="rounded-md bg-violet-100 px-2 py-0.5 text-[10px] font-medium text-violet-600">pipeline bố-con</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button type="button" onClick={() => editPipeline(name)} className="rounded-[8px] p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--secondary)] hover:text-[var(--foreground)]" title="Chỉnh sửa"><Pencil className="size-3.5" /></button>
                    <button type="button" onClick={() => removePipeline(name)} className="rounded-[8px] p-1.5 text-[var(--muted-foreground)] hover:bg-rose-50 hover:text-rose-500"><Trash2 className="size-3.5" /></button>
                  </div>
                </div>
                <div className="space-y-1">
                  {(p.architects || []).map((m, i) => (
                    <div key={`a${i}`} className="flex items-center gap-2">
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded border bg-amber-500/10 text-amber-600 border-amber-500/20 w-24 text-center shrink-0">BỐ · kế hoạch</span>
                      <span className="text-xs font-mono text-[var(--foreground)]">{m}</span>
                    </div>
                  ))}
                  {(p.editors || []).map((m, i) => (
                    <div key={`e${i}`} className="flex items-center gap-2">
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded border bg-emerald-500/10 text-emerald-600 border-emerald-500/20 w-24 text-center shrink-0">CON #{i + 1} · code</span>
                      <span className="text-xs font-mono text-[var(--foreground)]">{m}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add new combo */}
      <div className="rounded-[16px] p-6 card-main">
        <h3 className="mb-4 text-[15px] font-bold text-[var(--foreground)]">{t("addNewCombo")}</h3>
        <div className="mb-3">
          <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder={t("comboNamePlaceholder")} className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:border-[var(--border)] focus:outline-none" />
        </div>
        {selectedModels.length > 0 && (
          <div className="mb-3 space-y-1.5">
            <p className="text-[10px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">{t("fallbackOrder").replace("{count}", String(selectedModels.length))}</p>
            {selectedModels.map((modelId, idx) => {
              const info = allModels.find(m => m.id === modelId);
              const cap = info?.capability || "chat";
              const CapIcon = CAP_ICONS[cap] || MessageSquare;
              return (
                <div key={idx} className="flex items-center gap-2 rounded-lg bg-[var(--secondary)]/50 px-3 py-2">
                  <span className={cn("text-[10px] font-bold w-5 h-5 rounded-full flex items-center justify-center shrink-0", idx === 0 ? "bg-emerald-500/20 text-emerald-400" : "bg-[var(--secondary)] text-[var(--muted-foreground)]")}>{idx + 1}</span>
                  <CapIcon className="size-3 shrink-0 text-[var(--muted-foreground)]" />
                  <span className="flex-1 text-xs font-mono text-[var(--foreground)] truncate">{modelId}</span>
                  {(info?.capability_labels || ["Chat"]).map((label: string) => {
                    const capKey = label === "Chat" ? "chat" : label === t("vision") ? "vision" : label === "Phân tích ảnh" ? "vision" : label === "Video" ? "video" : label === "Phân tích video" ? "video" : "image";
                    return <span key={label} className={cn("text-[10px] px-1.5 py-0.5 rounded border", CAP_COLORS[capKey])}>{label}</span>;
                  })}
                  <button type="button" onClick={() => removeModelFromSelection(idx)} className="rounded p-0.5 text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-400"><X className="size-3.5" /></button>
                  {idx < selectedModels.length - 1 && <ArrowDown className="size-3 text-[var(--muted-foreground)] shrink-0" />}
                </div>
              );
            })}
          </div>
        )}
        <div className="flex gap-2 mb-3">
          <div className="flex rounded-lg border border-[var(--border)] overflow-hidden text-xs">
            {(["all", "chat", "vision", "image", "video"] as const).map(cap => (
              <button key={cap} type="button" onClick={() => setFilterCap(cap)} className={cn("px-3 py-1.5 transition", filterCap === cap ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]")}>
                {cap === "all" ? t("all") : cap === "chat" ? t("chat") : cap === "vision" ? t("vision") : cap === "video" ? "Video" : t("imageGen")}
              </button>
            ))}
          </div>
          <div className="relative flex-1">
            <button type="button" onClick={() => setDropdownOpen(true)} className="flex w-full items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)] hover:border-[var(--border)] transition">
              <span className="text-[var(--muted-foreground)]">{selectedModels.length > 0 ? `Đã chọn ${selectedModels.length} model` : t("selectModelPlaceholder")}</span><ChevronDown className="size-4 text-[var(--muted-foreground)]" />
            </button>
            <ModelPickerModal
              open={dropdownOpen}
              onClose={() => setDropdownOpen(false)}
              title="Chọn Model"
              models={filteredModels}
              excludeIds={[]}
              selectedIds={selectedModels}
              onPick={(id) => addModelToSelection(id)}
              showSearch
              onSearchChange={setModelSearch}
              emptyMessage={filterCap !== "all" ? t("noModelsInCategory") : t("allModelsSelected")}
            />
          </div>
          <button type="button" onClick={addCombo} disabled={!newName.trim() || selectedModels.length < 2} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--secondary)] px-4 py-2 text-sm font-medium text-[var(--foreground)] transition hover:bg-[var(--card)] disabled:opacity-40 shrink-0">
            <Plus className="size-4" /> Thêm
          </button>
        </div>
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>

      {/* Existing combos */}
      {comboEntries.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-[var(--muted-foreground)]">
          <Combine className="size-12 mb-3 opacity-50" /><p>{t("noCombos")}</p><p className="text-xs mt-1">{t("createFirstCombo")}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {comboEntries.map(([name, models], idx) => {
            const isEditing = editingCombo === name;
            return (
            <div key={name} className={cn("group relative overflow-hidden rounded-[16px] p-6 card-3d", TINT_CYCLE[idx % TINT_CYCLE.length], "transition-all duration-300 hover:-translate-y-1")}>
              <div className="absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r from-[#FFD700] to-[#D4AF37] opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="flex size-9 items-center justify-center rounded-[10px] bg-[var(--muted)]"><Combine className="size-[18px] text-[var(--muted-foreground)]" /></div>
                  <h3 className="text-[16px] font-bold tracking-tight text-[var(--foreground)]">{name}</h3>
                  <span className="rounded-md bg-[var(--secondary)] px-2 py-0.5 text-[11px] font-medium text-[var(--muted-foreground)]">{models.length} {t("models")}</span>
                </div>
                <div className="flex items-center gap-1">
                  <button type="button" onClick={() => startEdit(name)} className="rounded-[10px] p-2 text-[var(--muted-foreground)] transition hover:bg-[var(--secondary)] hover:text-[var(--foreground)]" title="Chỉnh sửa"><Pencil className="size-4" /></button>
                  <button type="button" onClick={() => removeCombo(name)} className="rounded-[10px] p-2 text-[var(--muted-foreground)] transition hover:bg-rose-50 hover:text-rose-500"><Trash2 className="size-4" /></button>
                </div>
              </div>
              {isEditing ? (
                <ComboEditView editModels={editModels} editName={editComboName} setEditName={setEditComboName} allModels={allModels} filteredModels={filteredModels} dropdownOpen={editDropdownOpen} setDropdownOpen={setEditDropdownOpen} removeFromEdit={removeFromEdit} addToEdit={addToEdit} swapInEdit={swapInEdit} moveUpInEdit={moveUpInEdit} moveDownInEdit={moveDownInEdit} cancelEdit={cancelEdit} saveEdit={saveEdit} />
              ) : (
                <ModelChainView models={models} allModels={allModels} t={t} />
              )}
            </div>
          )})}
        </div>
      )}
    </div>
  );
}
