"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentProps } from "react";
import {
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  CircleAlert,
  CircleOff,
  Copy,
  Cpu,
  Download,
  ExternalLink,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Search,
  Server,
  Sparkles,
  Trash2,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  deleteAccounts,
  fetchAccounts,
  refreshAccounts,
  updateAccount,
  type Account,
  type AccountStatus,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";
import { useLangStore } from "@/store/lang";
import { translations, TranslationKey } from "@/lib/i18n";

import { AccountImportDialog } from "./components/account-import-dialog";

const accountStatusOptions: { labelKey: TranslationKey; value: AccountStatus | "all" }[] = [
  { labelKey: "allStatus", value: "all" },
  { labelKey: "status_normal", value: "active" },
  { labelKey: "status_limited", value: "limited" },
  { labelKey: "status_error", value: "error" },
  { labelKey: "status_disabled", value: "disabled" },
];

const statusMeta: Record<
  AccountStatus,
  {
    icon: typeof CheckCircle2;
    badge: ComponentProps<typeof Badge>["variant"];
  }
> = {
  active: { icon: CheckCircle2, badge: "success" },
  limited: { icon: CircleAlert, badge: "warning" },
  error: { icon: CircleOff, badge: "danger" },
  disabled: { icon: Ban, badge: "secondary" },
};

const metricCards = [
  {
    key: "total", labelKey: "totalAccounts" as TranslationKey, icon: UserRound,
    gradient: "from-indigo-500 to-blue-600", shadow: "shadow-indigo-200",
    bg: "from-indigo-50/80 to-blue-50/80", textColor: "text-indigo-900", labelColor: "text-indigo-600",
  },
  {
    key: "active", labelKey: "active" as TranslationKey, icon: CheckCircle2,
    gradient: "from-emerald-500 to-teal-600", shadow: "shadow-emerald-200",
    bg: "from-emerald-50/80 to-teal-50/80", textColor: "text-emerald-900", labelColor: "text-emerald-600",
  },
  {
    key: "limited", labelKey: "limited" as TranslationKey, icon: CircleAlert,
    gradient: "from-amber-500 to-orange-500", shadow: "shadow-amber-200",
    bg: "from-amber-50/80 to-orange-50/80", textColor: "text-amber-900", labelColor: "text-amber-600",
  },
  {
    key: "abnormal", labelKey: "abnormal" as TranslationKey, icon: CircleOff,
    gradient: "from-rose-500 to-red-600", shadow: "shadow-rose-200",
    bg: "from-rose-50/80 to-red-50/80", textColor: "text-rose-900", labelColor: "text-rose-600",
  },
  {
    key: "disabled", labelKey: "disabled" as TranslationKey, icon: Ban,
    gradient: "from-slate-400 to-slate-500", shadow: "shadow-slate-200",
    bg: "from-slate-50/80 to-slate-100/80", textColor: "text-slate-700", labelColor: "text-slate-500",
  },
  {
    key: "quota", labelKey: "quotaRemaining" as TranslationKey, icon: RefreshCw,
    gradient: "from-sky-500 to-cyan-600", shadow: "shadow-sky-200",
    bg: "from-sky-50/80 to-cyan-50/80", textColor: "text-sky-900", labelColor: "text-sky-600",
  },
] as const;

function isUnlimitedImageQuotaAccount(account: Account) {
  return account.type === "pro" || account.type === "prolite";
}

function imageQuotaUnknown(account: Account) {
  return Boolean(account.image_quota_unknown);
}

function formatCompact(value: number) {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return String(value);
}

function formatQuota(account: Account) {
  if (isUnlimitedImageQuotaAccount(account)) {
    return "∞";
  }
  if (imageQuotaUnknown(account)) {
    return "Không rõ";
  }
  return String(Math.max(0, account.quota));
}

function formatRestoreAt(value: string | null | undefined, lang: "vi" | "en") {
  const t = translations[lang];
  if (!value) {
    return { absolute: "—", relative: "" };
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return { absolute: value, relative: "" };
  }

  const diffMs = Math.max(0, date.getTime() - Date.now());
  const totalHours = Math.ceil(diffMs / (1000 * 60 * 60));
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  const relative = diffMs > 0 ? `${t.restoreIn} ${days}d ${hours}h` : t.readyToRestore;

  const pad = (num: number) => String(num).padStart(2, "0");
  const absolute = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;

  return { absolute, relative };
}

function formatQuotaSummary(accounts: Account[]) {
  const availableAccounts = accounts.filter((account) => account.status === "active");
  if (availableAccounts.some(isUnlimitedImageQuotaAccount)) {
    return "∞";
  }
  if (availableAccounts.some(imageQuotaUnknown)) {
    return "Không rõ";
  }
  return formatCompact(availableAccounts.reduce((sum, account) => sum + Math.max(0, account.quota), 0));
}

function maskToken(token?: string) {
  if (!token) return "—";
  if (token.length <= 18) return token;
  return `${token.slice(0, 16)}...${token.slice(-8)}`;
}

function downloadTokens(accounts: Account[]) {
  const content = `${accounts.map((account) => account.access_token).join("\n")}\n`;
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `accounts-${Date.now()}.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

function displayAccountType(account: Account) {
  return account.type || "Free";
}

function translateStatus(status: string, lang: "vi" | "en") {
  const t = translations[lang];
  switch (status) {
    case "active": return t.status_normal;
    case "limited": return t.status_limited;
    case "error": return t.status_error;
    case "disabled": return t.status_disabled;
    default: return status;
  }
}

function formatRelativeTime(value: string | null | undefined, lang: "vi" | "en"): string {
  const t = translations[lang];
  if (!value) return "—";
  const date = new Date(value);
  if (isNaN(date.getTime())) return value;
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return t.justNow;
  if (mins < 60) return `${mins} ${t.minsAgo}`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} ${t.hrsAgo}`;
  return `${Math.floor(hrs / 24)} ${t.daysAgo}`;
}

function QuotaBar({
  label, used, max, resetAfter
}: { label: string; used: number; max: number; resetAfter?: string | null }) {
  const pct = max > 0 ? Math.min(100, Math.round((used / max) * 100)) : 0;
  const remaining = Math.max(0, max - used);
  const remainPct = 100 - pct;
  const dotColor = remainPct > 70 ? "bg-emerald-500" : remainPct > 30 ? "bg-amber-400" : "bg-rose-500";
  const barColor = remainPct > 70 ? "bg-emerald-500" : remainPct > 30 ? "bg-amber-400" : "bg-rose-500";
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className={`size-2 rounded-full shrink-0 ${dotColor}`} />
          <span className="text-[11px] font-medium text-slate-500">{label}</span>
        </div>
        {resetAfter && (
          <span className="text-[10px] text-slate-400 shrink-0">{resetAfter}</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <div className="relative flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${barColor}`}
            style={{ width: `${remainPct}%` }}
          />
        </div>
        <span className="text-[11px] text-slate-500 shrink-0 w-20 text-right">
          {remaining} / {max}
        </span>
        <span className={`text-[11px] font-bold shrink-0 w-8 text-right ${dotColor.replace('bg-', 'text-')}`}>
          {remainPct}%
        </span>
      </div>
    </div>
  );
}

function AccountsPageContent() {
  const { lang, setLang } = useLangStore();
  const t = (key: TranslationKey) => translations[lang][key] || key;
  const didLoadRef = useRef(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [providerTree, setProviderTree] = useState<any[]>([]);
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<AccountStatus | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState("10");
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [editStatus, setEditStatus] = useState<AccountStatus>("active");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  const loadAccounts = async (silent = false) => {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      const data = await fetchAccounts();
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Tải danh sách tài khoản thất bại";
      toast.error(message);
    } finally {
      if (!silent) {
        setIsLoading(false);
      }
    }
  };

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;
    void loadAccounts();
    void fetchProviderTree();
  }, []);

  const fetchProviderTree = async () => {
    try {
      const data = await request.get("/api/v1/provider-tree");
      setProviderTree((data.data as any)?.tree || []);
    } catch {
      // Build fallback from health + custom providers
      await buildFallbackTree();
    }
  };

  const buildFallbackTree = async () => {
    try {
      const [healthRes, cpRes] = await Promise.all([
        request.get("/api/v1/health"),
        request.get("/api/v1/custom-providers"),
      ]);
      const health = (healthRes.data as any) || {};
      const customProviders = (cpRes.data as any)?.custom_providers || {};

      const tree: any[] = [];
      const gemini = health.gemini || {};

      // ── Built-in providers ──
      const builtinList: any[] = [];
      if (gemini.gemini_api === "available" || gemini.gemini_api === "no_key") {
        builtinList.push({
          id: "gemini_free",
          name: "Gemini API",
          has_key: gemini.gemini_api === "available",
          key_preview: gemini.gemini_api === "available" ? "Google AI Studio" : "Chưa có key",
          base_url: "generativelanguage.googleapis.com",
          status: gemini.gemini_api === "available" ? "available" : gemini.gemini_api,
          models: gemini.models_count || 0,
        });
      }
      if (builtinList.length > 0) {
        tree.push({ provider: "Providers", icon: "cpu", type: "providers", instances: builtinList, total: builtinList.length });
      }

      // ── Custom APIs ──
      const customList: any[] = [];
      const seenIds = new Set<string>();

      // New format: instances array from health check
      const instances = gemini.instances || [];
      for (const inst of instances) {
        seenIds.add(inst.id);
        customList.push({
          id: inst.id, name: inst.name, prefix: inst.prefix,
          base_url: inst.base_url, port: inst.port,
          status: inst.status, models: inst.models || inst.clients || 0, error: inst.error,
        });
      }

      // Old format: single geminiapi field
      if (instances.length === 0 && gemini.geminiapi) {
        const oldInst: any = {
          id: "geminiapi", name: "Geminiapi", prefix: "geminiapi",
          base_url: `http://172.16.10.200:${gemini.geminiapi_port || "8002"}`,
          port: gemini.geminiapi_port || "8002",
          status: gemini.geminiapi === "available" ? "available" : gemini.geminiapi,
          models: 0, error: null,
        };
        if (gemini.geminiapi_clients) oldInst.clients = gemini.geminiapi_clients;
        if (gemini.geminiapi_entries) oldInst.entries = gemini.geminiapi_entries;
        seenIds.add("geminiapi");
        customList.push(oldInst);
      }

      // All custom providers from config (catch any not covered above)
      for (const [cpId, cpCfg] of Object.entries(customProviders)) {
        if (seenIds.has(cpId)) continue;
        const cfg = cpCfg as any;
        if (!cfg.enabled && cfg.enabled !== undefined) continue;
        const baseUrl = cfg.base_url || "";
        customList.push({
          id: cpId, name: cfg.name || cpId, prefix: cfg.prefix || cpId,
          base_url: baseUrl, port: baseUrl.split(":").pop() || "—",
          status: "unknown", models: 0, error: null,
        });
      }

      if (customList.length > 0) {
        tree.push({ provider: "Custom APIs", icon: "server", type: "custom", instances: customList, total: customList.length });
      }

      setProviderTree(tree);
    } catch {
      // silent
    }
  };

  const filteredAccounts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return accounts.filter((account) => {
      const searchMatched =
        normalizedQuery.length === 0 || (account.email ?? "").toLowerCase().includes(normalizedQuery);
      const typeMatched = typeFilter === "all" || displayAccountType(account) === typeFilter;
      const statusMatched = statusFilter === "all" || account.status === statusFilter;
      return searchMatched && typeMatched && statusMatched;
    });
  }, [accounts, query, statusFilter, typeFilter]);

  const pageCount = Math.max(1, Math.ceil(filteredAccounts.length / Number(pageSize)));
  const safePage = Math.min(page, pageCount);
  const startIndex = (safePage - 1) * Number(pageSize);
  const currentRows = filteredAccounts.slice(startIndex, startIndex + Number(pageSize));
  const allCurrentSelected =
    currentRows.length > 0 && currentRows.every((row) => selectedIds.includes(row.access_token));

  const summary = useMemo(() => {
    const total = accounts.length;
    const active = accounts.filter((item) => item.status === "active").length;
    const limited = accounts.filter((item) => item.status === "limited").length;
    const abnormal = accounts.filter((item) => item.status === "error").length;
    const disabled = accounts.filter((item) => item.status === "disabled").length;
    const quota = formatQuotaSummary(accounts);

    return { total, active, limited, abnormal, disabled, quota };
  }, [accounts]);

  const accountTypeOptions = useMemo(
    () => [
      { label: `Tất cả`, value: "all" },
      ...Array.from(new Set(accounts.map(displayAccountType))).map((type) => ({ label: type, value: type })),
    ],
    [accounts],
  );

  const groupedAccounts = useMemo(() => {
    const groups = new Map<string, Account[]>();
    for (const acc of filteredAccounts) {
      const type = displayAccountType(acc);
      const list = groups.get(type);
      if (list) list.push(acc);
      else groups.set(type, [acc]);
    }
    return Array.from(groups.entries()).map(([type, items]) => {
      const active = items.filter(a => a.status === "active").length;
      const limited = items.filter(a => a.status === "limited").length;
      const error = items.filter(a => a.status === "error").length;
      return { key: type, label: type, count: items.length, items, active, limited, error };
    });
  }, [filteredAccounts]);

  // Merge filtered accounts + provider tree for unified tree view
  const mergedTree = useMemo(() => {
    const tree: any[] = [];

    // ChatGPT branch from filtered accounts
    if (groupedAccounts.length > 0) {
      tree.push({
        provider: "ChatGPT",
        icon: "chatgpt",
        type: "accounts",
        groups: groupedAccounts,
        total: filteredAccounts.length,
      });
    }

    // Providers + Custom APIs from backend tree
    for (const branch of providerTree) {
      if (branch.type !== "accounts") {
        tree.push(branch);
      }
    }

    return tree;
  }, [groupedAccounts, filteredAccounts, providerTree]);

  function toggleGroup(type: string) {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  const selectedTokens = useMemo(() => {
    const selectedSet = new Set(selectedIds);
    return accounts.filter((item) => selectedSet.has(item.access_token)).map((item) => item.access_token);
  }, [accounts, selectedIds]);

  const abnormalTokens = useMemo(() => {
    return accounts.filter((item) => item.status === "error").map((item) => item.access_token);
  }, [accounts]);

  const paginationItems = useMemo(() => {
    const items: (number | "...")[] = [];
    const start = Math.max(1, safePage - 1);
    const end = Math.min(pageCount, safePage + 1);

    if (start > 1) items.push(1);
    if (start > 2) items.push("...");
    for (let current = start; current <= end; current += 1) items.push(current);
    if (end < pageCount - 1) items.push("...");
    if (end < pageCount) items.push(pageCount);

    return items;
  }, [pageCount, safePage]);

  const handleDeleteTokens = async (tokens: string[]) => {
    if (tokens.length === 0) {
      toast.error("Vui lòng chọn tài khoản muốn xóa");
      return;
    }

    setIsDeleting(true);
    try {
      const data = await deleteAccounts(tokens);
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
      toast.success(`Đã xóa ${data.removed ?? 0} tài khoản`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Xóa tài khoản thất bại";
      toast.error(message);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRefreshAccounts = async (accessTokens: string[]) => {
    if (accessTokens.length === 0) {
      toast.error("Không có tài khoản nào cần làm mới");
      return;
    }

    setIsRefreshing(true);
    try {
      const data = await refreshAccounts(accessTokens);
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
      if (data.errors.length > 0) {
        const firstError = data.errors[0]?.error;
        toast.error(
          `Làm mới thành công ${data.refreshed}, thất bại ${data.errors.length}${firstError ? `，Lỗi đầu tiên: ${firstError}` : ""}`,
        );
      } else {
        toast.success(`Làm mới thành công ${data.refreshed} tài khoản`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Làm mới tài khoản thất bại";
      toast.error(message);
    } finally {
      setIsRefreshing(false);
    }
  };

  const openEditDialog = (account: Account) => {
    setEditingAccount(account);
    setEditStatus(account.status);
  };

  const handleUpdateAccount = async () => {
    if (!editingAccount) {
      return;
    }

    setIsUpdating(true);
    try {
      const data = await updateAccount(editingAccount.access_token, {
        status: editStatus,
      });
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
      setEditingAccount(null);
      toast.success("Thông tin tài khoản đã được cập nhật");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Cập nhật tài khoản thất bại";
      toast.error(message);
    } finally {
      setIsUpdating(false);
    }
  };

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...currentRows.map((item) => item.access_token)])));
      return;
    }
    setSelectedIds((prev) => prev.filter((id) => !currentRows.some((row) => row.access_token === id)));
  };

  return (
    <>
      {/* ── Header: multi-row layout ── */}
      <section className="space-y-3">
        {/* Row 1: Title + count */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-[22px] font-bold tracking-tight text-slate-900">{t("title")}</h1>
            <Badge variant="secondary" className="rounded-lg bg-stone-200 px-2.5 py-0.5 text-sm text-stone-700">
              {filteredAccounts.length} tài khoản
            </Badge>
          </div>
        </div>

        {/* Row 2: Import / Export */}
        <div className="flex flex-wrap items-center gap-2">
          <AccountImportDialog
            disabled={isLoading || isRefreshing || isDeleting}
            onImported={(items) => {
              setAccounts(items);
              setSelectedIds([]);
              setPage(1);
            }}
          />
          <a
            href="/settings"
            className="inline-flex items-center gap-1.5 h-9 rounded-lg border border-black/[0.08] bg-white px-3.5 text-[13px] font-medium text-slate-600 hover:bg-slate-50 transition"
          >
            <ExternalLink className="size-3.5" />
            Custom API
          </a>
          <Button
            variant="outline"
            className="h-9 rounded-lg border-black/[0.08] bg-white px-3.5 text-[13px] text-slate-600 hover:bg-slate-50"
            onClick={() => downloadTokens(accounts)}
            disabled={accounts.length === 0}
          >
            <Download className="size-3.5" />
            Xuất Token
          </Button>
        </div>

        {/* Row 3: Refresh + Search + Filters */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:flex-wrap">
          <Button
            variant="outline"
            className="h-9 rounded-lg border-black/[0.08] bg-white px-3 text-[13px] text-slate-600 hover:bg-slate-50"
            onClick={() => void loadAccounts()}
            disabled={isLoading || isRefreshing || isDeleting}
          >
            <RefreshCw className={cn("size-3.5 mr-1.5", isLoading ? "animate-spin" : "")} />
            Làm mới
          </Button>
          <Button
            variant="outline"
            className="h-9 rounded-lg border-black/[0.08] bg-white px-3 text-[13px] text-slate-600 hover:bg-slate-50"
            onClick={() => void handleRefreshAccounts(accounts.map((item) => item.access_token))}
            disabled={isLoading || isRefreshing || isDeleting || accounts.length === 0}
          >
            <RefreshCw className={cn("size-3.5 mr-1.5", isRefreshing ? "animate-spin" : "")} />
            Làm mới tất cả
          </Button>

          <div className="flex-1" />

          <div className="relative w-full sm:w-[200px]">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-slate-400" />
            <Input
              value={query}
              onChange={(event) => { setQuery(event.target.value); setPage(1); }}
              placeholder="Tìm kiếm..."
              className="h-9 rounded-lg border-slate-200 bg-white pl-8 w-full text-sm"
            />
          </div>
          <Select value={typeFilter} onValueChange={(value) => { setTypeFilter(value); setPage(1); }}>
            <SelectTrigger className="h-9 rounded-lg border-slate-200 bg-white w-[110px] text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {accountTypeOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={statusFilter} onValueChange={(value) => { setStatusFilter(value as AccountStatus | "all"); setPage(1); }}>
            <SelectTrigger className="h-9 rounded-lg border-slate-200 bg-white w-[120px] text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {accountStatusOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </section>

      <Dialog open={Boolean(editingAccount)} onOpenChange={(open) => (!open ? setEditingAccount(null) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>{t("editStatus")}</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              {t("editStatusDesc")}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">{t("status")}</label>
              <Select value={editStatus} onValueChange={(value) => setEditStatus(value as AccountStatus)}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {accountStatusOptions
                    .filter((option) => option.value !== "all")
                    .map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setEditingAccount(null)}
              disabled={isUpdating}
            >
              Hủy
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-900 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleUpdateAccount()}
              disabled={isUpdating}
            >
              {isUpdating ? <LoaderCircle className="size-4 animate-spin" /> : null}
              Lưu thay đổi
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Stat cards */}
      <section className="space-y-3">
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-6">
          {metricCards.map((item) => {
            const Icon = item.icon;
            const value = summary[item.key];
            return (
              <div
                key={item.key}
                className={cn(
                  "rounded-xl p-2.5 card-3d",
                  `bg-gradient-to-br ${item.bg}`,
                )}
              >
                <div className="flex items-start justify-between gap-1">
                  <div className="min-w-0">
                    <p className={cn("text-[10px] font-semibold mb-0.5 truncate", item.labelColor)}>{t(item.labelKey)}</p>
                    <p className={cn("text-lg font-bold leading-none", item.textColor)}>
                      {typeof value === "number" ? formatCompact(value) : value}
                    </p>
                  </div>
                  <div className={cn(
                    "size-6 rounded-full flex items-center justify-center shrink-0",
                    `bg-gradient-to-br ${item.gradient}`,
                  )}>
                    <Icon className="size-3 text-white" />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="space-y-4">
        {/* Tree View */}

        {isLoading && accounts.length === 0 ? (
          <Card className="rounded-2xl card-3d card-tint-emerald">
            <CardContent className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
              <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                <LoaderCircle className="size-5 animate-spin" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium text-stone-700">{t("loadingAccounts")}</p>
                <p className="text-sm text-stone-500">{t("syncingAccounts")}</p>
              </div>
            </CardContent>
          </Card>
        ) : null}

        {/* 3-Level Provider Tree */}
        {!isLoading && (
          <div className="space-y-2">
            {mergedTree.map((provider: any) => {
              const isProviderOpen = expandedProviders.has(provider.provider);
              const tintClass =
                provider.provider === "ChatGPT" ? "card-tint-emerald" :
                provider.provider === "Providers" ? "card-tint-indigo" :
                "card-tint-violet";
              const Icon = provider.icon === "chatgpt" ? Sparkles :
                provider.icon === "cpu" ? Cpu : Server;
              return (
                <div key={provider.provider} className="rounded-[16px] card-3d overflow-hidden">
                  {/* Level 1: Provider header */}
                  <button
                    type="button"
                    onClick={() => {
                      setExpandedProviders(prev => {
                        const next = new Set(prev);
                        if (next.has(provider.provider)) next.delete(provider.provider);
                        else next.add(provider.provider);
                        return next;
                      });
                    }}
                    className={cn(
                      "flex w-full items-center gap-3 px-5 py-4 text-left transition-colors",
                      tintClass,
                      isProviderOpen && "border-b border-black/[0.04]"
                    )}
                  >
                    <ChevronDown className={cn(
                      "size-4 text-slate-400 transition-transform",
                      isProviderOpen && "rotate-180"
                    )} />
                    <div className="flex size-9 items-center justify-center rounded-xl bg-white/60">
                      <Icon className="size-4 text-slate-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <span className="text-[15px] font-bold text-slate-800">{provider.provider}</span>
                    </div>
                    <Badge variant="secondary" className="rounded-md bg-white/60 text-[11px] px-2 text-slate-500">
                      {provider.total} mục
                    </Badge>
                  </button>

                  {/* Level 2: Sub-items */}
                  {isProviderOpen && (
                    <div className="divide-y divide-black/[0.03]">
                      {/* ChatGPT: groups by account type */}
                      {provider.type === "accounts" && provider.groups?.map((group: any) => {
                        const isGroupOpen = expandedGroups.has(`${provider.provider}/${group.key}`);
                        return (
                          <div key={group.key}>
                            <button
                              type="button"
                              onClick={() => {
                                setExpandedGroups(prev => {
                                  const next = new Set(prev);
                                  const gid = `${provider.provider}/${group.key}`;
                                  if (next.has(gid)) next.delete(gid);
                                  else next.add(gid);
                                  return next;
                                });
                              }}
                              className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-slate-50/60 transition-colors"
                            >
                              <ChevronDown className={cn(
                                "size-3.5 text-slate-400 transition-transform",
                                isGroupOpen && "rotate-180"
                              )} />
                              <span className="flex-1 text-[13px] font-semibold text-slate-700">{group.label}</span>
                              <Badge variant="secondary" className="rounded-md bg-slate-100 text-[10px] px-1.5 text-slate-500">
                                {group.count}
                              </Badge>
                              <span className="flex items-center gap-1 text-[10px] text-emerald-600">{group.active} active</span>
                              <span className="flex items-center gap-1 text-[10px] text-amber-600">{group.limited} limited</span>
                              {group.error > 0 && (
                                <span className="flex items-center gap-1 text-[10px] text-rose-500">{group.error} err</span>
                              )}
                            </button>

                            {/* Level 3: Individual accounts */}
                            {isGroupOpen && group.items?.map((account: Account) => {
                              const accountExpanded = expandedId === account.access_token;
                              const status = statusMeta[account.status];
                              const StatusIcon = status.icon;
                              const isUnlimited = isUnlimitedImageQuotaAccount(account);
                              const quotaVal = Math.max(0, account.quota);
                              return (
                                <div key={account.access_token}>
                                  <div
                                    className={cn(
                                      "flex items-center gap-3 pl-12 pr-5 py-2.5 hover:bg-slate-50/60 cursor-pointer transition-colors",
                                      accountExpanded && "bg-indigo-50/40"
                                    )}
                                    onClick={() => setExpandedId(accountExpanded ? null : account.access_token)}
                                  >
                                    <div className={cn(
                                      "size-7 shrink-0 rounded-full flex items-center justify-center",
                                      account.status === "active" ? "bg-gradient-to-br from-indigo-500 to-blue-600"
                                      : account.status === "limited" ? "bg-gradient-to-br from-amber-400 to-orange-500"
                                      : account.status === "error" ? "bg-gradient-to-br from-rose-500 to-red-600"
                                      : "bg-slate-200"
                                    )}>
                                      <UserRound className="size-3 text-white" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-1.5">
                                        <span className="text-[12px] font-medium text-slate-700 truncate max-w-[140px]">
                                          {account.email ?? maskToken(account.access_token)}
                                        </span>
                                        <Badge variant={status.badge} className="inline-flex items-center gap-0.5 rounded text-[10px] px-1 py-0">
                                          <StatusIcon className="size-2.5" />
                                          {translateStatus(account.status, lang)}
                                        </Badge>
                                      </div>
                                    </div>
                                    <div className="hidden sm:flex items-center gap-2 text-[11px]">
                                      <span className="text-emerald-600">{account.success}✓</span>
                                      <span className="text-rose-400">{account.fail}✗</span>
                                    </div>
                                    <div className="text-[11px] font-bold">
                                      {isUnlimited ? <span className="text-violet-600">∞</span>
                                        : imageQuotaUnknown(account) ? <span className="text-slate-400">?</span>
                                        : <span className={quotaVal > 0 ? "text-emerald-600" : "text-rose-500"}>{quotaVal}</span>
                                      }
                                    </div>
                                    <div className="flex items-center gap-1 text-slate-400" onClick={e => e.stopPropagation()}>
                                      <button className="rounded p-0.5 hover:bg-slate-100 hover:text-slate-700" onClick={() => openEditDialog(account)}><Pencil className="size-3" /></button>
                                      <button className="rounded p-0.5 hover:bg-rose-50 hover:text-rose-500" onClick={() => void handleDeleteTokens([account.access_token])}><Trash2 className="size-3" /></button>
                                    </div>
                                  </div>
                                  {/* Account expanded detail */}
                                  {accountExpanded && (
                                    <div className="pl-12 pr-5 pb-3 bg-slate-50/50 border-t border-indigo-100">
                                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-3">
                                        <div className="rounded-[12px] p-4 card-3d card-tint-emerald space-y-3">
                                          <div className="flex items-center justify-between">
                                            <div>
                                              <p className="text-[13px] font-bold text-slate-800">{account.email ?? maskToken(account.access_token)}</p>
                                              <div className="flex items-center gap-2 mt-0.5">
                                                <Badge variant={status.badge} className="inline-flex items-center gap-0.5 rounded text-[10px] px-1 py-0">
                                                  <span className={cn("size-1.5 rounded-full mr-0.5",
                                                    account.status === "active" ? "bg-emerald-400" :
                                                    account.status === "limited" ? "bg-amber-400" :
                                                    account.status === "error" ? "bg-rose-400" : "bg-slate-300"
                                                  )} />
                                                  {translateStatus(account.status, lang)}
                                                </Badge>
                                                <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-slate-100 text-slate-500">
                                                  {displayAccountType(account)}
                                                </Badge>
                                              </div>
                                            </div>
                                          </div>
                                          {isUnlimited ? (
                                            <div className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-violet-500" /><span className="text-[11px] text-slate-500">Ảnh:</span><span className="text-[12px] font-bold text-violet-600">∞ không giới hạn</span></div>
                                          ) : !imageQuotaUnknown(account) ? (
                                            <QuotaBar label="Ảnh" used={Math.max(0, 100 - quotaVal)} max={100} resetAfter={account.restore_at ? formatRestoreAt(account.restore_at, lang).relative : undefined} />
                                          ) : null}
                                          {account.limits_progress?.map((lp, i) => (
                                            <QuotaBar key={i} label={t(lp.feature_name as TranslationKey) ?? lp.feature_name ?? `Limit ${i + 1}`} used={Math.max(0, (lp as any).total ?? 100) - (lp.remaining ?? 0)} max={(lp as any).total ?? Math.max(lp.remaining ?? 0, 40)} resetAfter={lp.reset_after ? formatRestoreAt(lp.reset_after, lang).relative : undefined} />
                                          ))}
                                          <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-100">
                                            <span>Dùng lần cuối</span>
                                            <span className="font-medium text-slate-600">{formatRelativeTime(account.last_used_at, lang)}</span>
                                          </div>
                                        </div>
                                        <div className="rounded-[12px] p-4 card-3d card-tint-sky space-y-3">
                                          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Thống kê yêu cầu</p>
                                          <div className="space-y-3">
                                            <div className="space-y-1.5">
                                              <div className="flex items-center justify-between gap-2">
                                                <div className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-emerald-500" /><span className="text-[11px] text-slate-500">Thành công</span></div>
                                                <span className="text-[11px] font-bold text-emerald-600">{account.success}</span>
                                              </div>
                                            </div>
                                            <div className="space-y-1.5">
                                              <div className="flex items-center justify-between gap-2">
                                                <div className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-rose-500" /><span className="text-[11px] text-slate-500">Thất bại</span></div>
                                                <span className="text-[11px] font-bold text-rose-500">{account.fail}</span>
                                              </div>
                                            </div>
                                          </div>
                                        </div>
                                      </div>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        );
                      })}

                      {/* Providers / Custom APIs: instance rows */}
                      {(provider.type === "providers" || provider.type === "custom") && provider.instances?.map((inst: any) => (
                        <div key={inst.id} className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50/60 transition-colors">
                          <div className={cn(
                            "size-2 rounded-full shrink-0",
                            inst.status === "available" ? "bg-emerald-500" :
                            inst.status === "configured" ? "bg-sky-500" :
                            inst.status === "offline" ? "bg-rose-500" : "bg-amber-500"
                          )} />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-[13px] font-medium text-slate-700">{inst.name}</span>
                              {inst.prefix && <code className="text-[11px] text-slate-400">{inst.prefix}/</code>}
                            </div>
                            {inst.base_url && <div className="text-[11px] text-slate-400 truncate">{inst.base_url}</div>}
                          </div>
                          {inst.has_key !== undefined && (
                            <span className="text-[10px] text-slate-400">{inst.has_key ? inst.key_preview : "Chưa có key"}</span>
                          )}
                          {inst.port !== undefined && <span className="text-[11px] text-slate-400">:{inst.port}</span>}
                          <span className={cn(
                            "text-[11px] font-medium",
                            inst.status === "available" ? "text-emerald-600" :
                            inst.status === "configured" ? "text-sky-600" :
                            inst.status === "offline" ? "text-rose-500" : "text-amber-600"
                          )}>
                            {inst.status}
                          </span>
                          {inst.models > 0 && <span className="text-[11px] text-slate-400">{inst.models} models</span>}
                          {inst.error && <span className="text-[10px] text-rose-400 max-w-[200px] truncate">{inst.error}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            {mergedTree.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center card-3d card-tint-slate rounded-[16px]">
                <Search className="size-5 text-slate-400" />
                <p className="text-sm text-slate-500">Chưa có dữ liệu provider nào</p>
              </div>
            )}
          </div>
        )}
      </section>
    </>
  );
}

export default function AccountsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-500" />
      </div>
    );
  }

  return <AccountsPageContent />;
}
