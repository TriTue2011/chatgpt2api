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
  Download,
  ExternalLink,
  FolderTree,
  List,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Search,
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
  const [viewMode, setViewMode] = useState<"list" | "tree">("list");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
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
  }, []);

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
      return { type, items, active, limited, error };
    });
  }, [filteredAccounts]);

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
      <section className="flex flex-col gap-4 border-b border-black/[0.04] pb-6 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-[11px] font-bold tracking-widest text-indigo-500 uppercase mb-1">Account Pool</p>
          <h1 className="text-[26px] font-bold tracking-tight text-slate-900">{t("title")}</h1>
          <p className="text-[14px] text-slate-500 mt-0.5">{t("subtitle")}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className="h-10 rounded-[12px] border-black/[0.08] bg-white px-4 text-slate-600 shadow-sm hover:bg-slate-50"
            onClick={() => void loadAccounts()}
            disabled={isLoading || isRefreshing || isDeleting}
          >
            <RefreshCw className={cn("size-4", isLoading ? "animate-spin" : "")} />
            Làm mới
          </Button>
          <Button
            variant="outline"
            className="h-10 rounded-[12px] border-black/[0.08] bg-white px-4 text-slate-600 shadow-sm hover:bg-slate-50"
            onClick={() => void handleRefreshAccounts(accounts.map((item) => item.access_token))}
            disabled={isLoading || isRefreshing || isDeleting || accounts.length === 0}
          >
            <RefreshCw className={cn("size-4", isRefreshing ? "animate-spin" : "")} />
            Làm mới tất cả
          </Button>
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
            className="inline-flex items-center gap-1.5 h-10 rounded-[12px] border border-black/[0.08] bg-white px-4 text-[13px] font-medium text-slate-600 shadow-sm hover:bg-slate-50 transition"
          >
            <ExternalLink className="size-3.5" />
            Custom APIs
          </a>
          <Button
            variant="outline"
            className="h-10 rounded-[12px] border-black/[0.08] bg-white px-4 text-slate-600 shadow-sm hover:bg-slate-50"
            onClick={() => downloadTokens(accounts)}
            disabled={accounts.length === 0}
          >
            <Download className="size-4" />
            Xuất Token
          </Button>
        </div>

        {/* Filter bar — right below action buttons */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3 pt-2">
          <div className="relative w-full sm:max-w-[280px]">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(1);
              }}
              placeholder={t("searchPlaceholder")}
              className="h-9 rounded-xl border-slate-200 bg-white pl-10 w-full text-sm"
            />
          </div>
          <Select
            value={typeFilter}
            onValueChange={(value) => {
              setTypeFilter(value);
              setPage(1);
            }}
          >
            <SelectTrigger className="h-9 rounded-xl border-slate-200 bg-white w-[130px] text-sm">
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
          <Select
            value={statusFilter}
            onValueChange={(value) => {
              setStatusFilter(value as AccountStatus | "all");
              setPage(1);
            }}
          >
            <SelectTrigger className="h-9 rounded-xl border-slate-200 bg-white w-[130px] text-sm">
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
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {metricCards.map((item) => {
            const Icon = item.icon;
            const value = summary[item.key];
            return (
              <div
                key={item.key}
                className={cn(
                  "rounded-xl p-4 card-3d",
                  `bg-gradient-to-br ${item.bg}`,
                )}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <p className={cn("text-[11px] font-semibold mb-1", item.labelColor)}>{t(item.labelKey)}</p>
                    <p className={cn("text-2xl font-bold leading-none", item.textColor)}>
                      {typeof value === "number" ? formatCompact(value) : value}
                    </p>
                  </div>
                  <div className={cn(
                    "size-9 rounded-full flex items-center justify-center shrink-0",
                    `bg-gradient-to-br ${item.gradient}`,
                    `shadow-md ${item.shadow}`
                  )}>
                    <Icon className="size-4 text-white" />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold tracking-tight">{t("title")}</h2>
            <Badge variant="secondary" className="rounded-lg bg-stone-200 px-2 py-0.5 text-stone-700">
              {filteredAccounts.length}
            </Badge>
          </div>
          <div className="flex items-center gap-1 rounded-lg border border-stone-200 bg-white p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("list")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition",
                viewMode === "list" ? "bg-stone-900 text-white" : "text-stone-500 hover:text-stone-700"
              )}
            >
              <List className="size-3.5" />
              DS
            </button>
            <button
              type="button"
              onClick={() => setViewMode("tree")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition",
                viewMode === "tree" ? "bg-stone-900 text-white" : "text-stone-500 hover:text-stone-700"
              )}
            >
              <FolderTree className="size-3.5" />
              Cây
            </button>
          </div>
        </div>

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

        {/* Tree View */}
        {viewMode === "tree" && !isLoading && (
          <div className="space-y-2">
            {groupedAccounts.map((group) => {
              const isExpanded = expandedGroups.has(group.type);
              const total = group.items.length;
              const tintClass =
                group.type === "pro" || group.type === "prolite" ? "card-tint-violet" :
                group.type === "codex" ? "card-tint-emerald" :
                group.type === "free" ? "card-tint-sky" :
                "card-tint-slate";
              return (
                <div key={group.type} className="rounded-[16px] card-3d overflow-hidden">
                  {/* Group header */}
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.type)}
                    className={cn(
                      "flex w-full items-center gap-3 px-5 py-4 text-left transition-colors",
                      tintClass,
                      isExpanded && "border-b border-black/[0.04]"
                    )}
                  >
                    <ChevronDown className={cn(
                      "size-4 text-slate-400 transition-transform",
                      isExpanded && "rotate-180"
                    )} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[14px] font-bold text-slate-800">{group.type}</span>
                        <Badge variant="secondary" className="rounded-md bg-white/60 text-[10px] px-1.5 text-slate-500">
                          {total} tk
                        </Badge>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 text-[11px]">
                      <span className="flex items-center gap-1">
                        <span className="size-1.5 rounded-full bg-emerald-500" />
                        <span className="text-emerald-600 font-medium">{group.active}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="size-1.5 rounded-full bg-amber-500" />
                        <span className="text-amber-600 font-medium">{group.limited}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="size-1.5 rounded-full bg-rose-500" />
                        <span className="text-rose-500 font-medium">{group.error}</span>
                      </span>
                    </div>
                  </button>

                  {/* Group items */}
                  {isExpanded && (
                    <div className="divide-y divide-black/[0.03]">
                      {group.items.map((account) => {
                        const status = statusMeta[account.status];
                        const StatusIcon = status.icon;
                        const isUnlimited = isUnlimitedImageQuotaAccount(account);
                        const quotaVal = Math.max(0, account.quota);
                        const quotaDisplay = isUnlimited ? "∞" : imageQuotaUnknown(account) ? "?" : String(quotaVal);
                        return (
                          <div
                            key={account.access_token}
                            className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50/60 cursor-pointer transition-colors"
                            onClick={() => setExpandedId(expandedId === account.access_token ? null : account.access_token)}
                          >
                            <div className={cn(
                              "size-8 shrink-0 rounded-full flex items-center justify-center",
                              account.status === "active" ? "bg-gradient-to-br from-indigo-500 to-blue-600"
                              : account.status === "limited" ? "bg-gradient-to-br from-amber-400 to-orange-500"
                              : account.status === "error" ? "bg-gradient-to-br from-rose-500 to-red-600"
                              : "bg-slate-200"
                            )}>
                              <UserRound className="size-3.5 text-white" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="text-[13px] font-semibold text-slate-800 truncate max-w-[160px]">
                                  {account.email ?? maskToken(account.access_token)}
                                </span>
                                <Badge variant={status.badge} className="inline-flex items-center gap-0.5 rounded text-[10px] px-1 py-0">
                                  <StatusIcon className="size-2.5" />
                                  {translateStatus(account.status, lang)}
                                </Badge>
                              </div>
                              <div className="text-[11px] text-slate-400 font-mono truncate">
                                {maskToken(account.access_token)}
                              </div>
                            </div>
                            <div className="hidden sm:flex items-center gap-3 text-[12px]">
                              <span className="text-emerald-600 font-medium">{account.success}✓</span>
                              <span className="text-rose-400">{account.fail}✗</span>
                            </div>
                            <div className="text-[12px] font-bold">
                              {isUnlimited
                                ? <span className="text-violet-600">∞</span>
                                : imageQuotaUnknown(account)
                                ? <span className="text-slate-400">?</span>
                                : <span className={quotaVal > 0 ? "text-emerald-600" : "text-rose-500"}>{quotaDisplay}</span>
                              }
                            </div>
                            <div className="flex items-center gap-1 text-slate-400" onClick={e => e.stopPropagation()}>
                              <button
                                className="rounded-lg p-1 hover:bg-slate-100 hover:text-slate-700"
                                onClick={() => openEditDialog(account)}
                                title="Chỉnh sửa"
                              >
                                <Pencil className="size-3" />
                              </button>
                              <button
                                className="rounded-lg p-1 hover:bg-rose-50 hover:text-rose-500"
                                onClick={() => void handleDeleteTokens([account.access_token])}
                                title={t("delete")}
                              >
                                <Trash2 className="size-3" />
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
            {groupedAccounts.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center card-3d card-tint-slate rounded-[16px]">
                <Search className="size-5 text-stone-400" />
                <p className="text-sm text-stone-500">Không có tài khoản nào phù hợp</p>
              </div>
            )}
          </div>
        )}

        {viewMode === "list" && (
        <div
          className={cn(
            "overflow-hidden rounded-[16px]",
            "card-main",
            isLoading && accounts.length === 0 ? "hidden" : "",
          )}
        >
          <div className="space-y-0 p-0">
            <div className="flex flex-col gap-3 border-b border-black/[0.04] bg-slate-50/50 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap items-center gap-2 text-sm text-stone-500">
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-stone-500 hover:bg-stone-200"
                  onClick={() => void handleRefreshAccounts(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isRefreshing}
                >
                  {isRefreshing ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  {t("refreshSelected")}
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                  onClick={() => void handleDeleteTokens(abnormalTokens)}
                  disabled={abnormalTokens.length === 0 || isDeleting}
                >
                  {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                  {t("deleteError")}
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                  onClick={() => void handleDeleteTokens(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isDeleting}
                >
                  {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                  {t("deleteSelected")}
                </Button>
                {selectedIds.length > 0 ? (
                  <span className="rounded-lg bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-600">
                    {t("selectedCount").replace("{count}", String(selectedIds.length))}
                  </span>
                ) : null}
              </div>
            </div>

            <div className="divide-y divide-black/[0.03]">
              {/* Table header */}
              <div className="hidden lg:grid grid-cols-[2fr_1fr_1fr_1.5fr_1fr_auto] items-center gap-4 border-b border-black/[0.04] bg-slate-50/60 px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                <span>{t("account")}</span>
                <span>{t("typeStatus")}</span>
                <span>{t("imageQuota")}</span>
                <span>{t("lastUsed")}</span>
                <span>{t("requests")}</span>
                <span className="w-24">{t("actions")}</span>
              </div>

              {currentRows.map((account) => {
                const status = statusMeta[account.status];
                const StatusIcon = status.icon;
                const isExpanded = expandedId === account.access_token;
                const quotaVal = Math.max(0, account.quota);
                const isUnlimited = isUnlimitedImageQuotaAccount(account);
                const quotaDisplay = isUnlimited ? "∞" : imageQuotaUnknown(account) ? "?" : String(quotaVal);

                // Chat limits from limits_progress
                const chatLimit = account.limits_progress?.find(l => l.feature_name?.toLowerCase().includes("chat") || l.feature_name?.toLowerCase().includes("message") || l.feature_name?.toLowerCase().includes("gpt"));
                const imageLimit = account.limits_progress?.find(l => l.feature_name?.toLowerCase().includes("image") || l.feature_name?.toLowerCase().includes("dall") || l.feature_name?.toLowerCase().includes("gpt-image"));

                return (
                  <div key={account.access_token} className="group">
                    {/* Collapsed row — click to expand */}
                    <div
                      className={cn(
                        "grid grid-cols-[auto_2fr_auto] lg:grid-cols-[2fr_1fr_1fr_1.5fr_1fr_auto] items-center gap-3 lg:gap-4 px-5 py-3.5 cursor-pointer transition-colors",
                        isExpanded ? "bg-indigo-50/60" : "hover:bg-slate-50/60"
                      )}
                      onClick={() => setExpandedId(isExpanded ? null : account.access_token)}
                    >
                      {/* Account identity */}
                      <div className="flex items-center gap-3 min-w-0">
                        <div className={cn(
                          "size-9 shrink-0 rounded-full flex items-center justify-center",
                          account.status === "active" ? "bg-gradient-to-br from-indigo-500 to-blue-600 shadow-sm shadow-indigo-200"
                          : account.status === "limited" ? "bg-gradient-to-br from-amber-400 to-orange-500 shadow-sm shadow-amber-200"
                          : account.status === "error" ? "bg-gradient-to-br from-rose-500 to-red-600 shadow-sm shadow-rose-200"
                          : "bg-slate-200"
                        )}>
                          <UserRound className="size-4 text-white" />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[13px] font-semibold text-slate-800 truncate max-w-[140px]">
                              {account.email ?? maskToken(account.access_token)}
                            </span>
                          </div>
                          <div className="text-[11px] text-slate-400 font-mono truncate">
                            {maskToken(account.access_token)}
                          </div>
                        </div>
                      </div>

                      {/* Type + Status */}
                      <div className="hidden lg:flex items-center gap-1.5 flex-wrap">
                        <Badge variant="secondary" className="rounded-md bg-slate-100 text-slate-600 text-[11px] px-1.5">
                          {displayAccountType(account)}
                        </Badge>
                        <Badge variant={status.badge} className="inline-flex items-center gap-1 rounded-md text-[11px] px-1.5">
                          <StatusIcon className="size-3" />
                          {translateStatus(account.status, lang)}
                        </Badge>
                      </div>

                      {/* Image quota */}
                      <div className="hidden lg:block text-[13px] font-bold">
                        {isUnlimited
                          ? <span className="text-violet-600">∞ ảnh</span>
                          : imageQuotaUnknown(account)
                          ? <span className="text-slate-400">?</span>
                          : <span className={quotaVal > 0 ? "text-emerald-600" : "text-rose-500"}>{quotaDisplay} ảnh</span>
                        }
                      </div>

                      {/* Last used */}
                      <div className="hidden lg:block text-[12px] text-slate-400">
                        {formatRelativeTime(account.last_used_at, lang)}
                      </div>

                      {/* Success/fail */}
                      <div className="hidden lg:flex items-center gap-2 text-[12px]">
                        <span className="text-emerald-600 font-medium">{account.success}✓</span>
                        <span className="text-rose-400">{account.fail}✗</span>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-1 text-slate-400" onClick={e => e.stopPropagation()}>
                        <button
                          className="rounded-lg p-1.5 hover:bg-slate-100 hover:text-slate-700 transition"
                          onClick={() => openEditDialog(account)}
                          disabled={isUpdating}
                          title="Chỉnh sửa"
                        >
                          <Pencil className="size-3.5" />
                        </button>
                        <button
                          className="rounded-lg p-1.5 hover:bg-slate-100 hover:text-slate-700 transition"
                          onClick={() => void handleRefreshAccounts([account.access_token])}
                          disabled={isRefreshing}
                          title={t("refresh")}
                        >
                          <RefreshCw className={cn("size-3.5", isRefreshing ? "animate-spin" : "")} />
                        </button>
                        <button
                          className="rounded-lg p-1.5 hover:bg-rose-50 hover:text-rose-500 transition"
                          onClick={() => void handleDeleteTokens([account.access_token])}
                          disabled={isDeleting}
                          title={t("delete")}
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    </div>

                    {/* Expanded detail panel — 9router style */}
                    <div className={cn(
                      "grid transition-all duration-300 ease-in-out",
                      isExpanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
                    )}>
                      <div className="overflow-hidden">
                        <div className="border-t border-indigo-100 bg-slate-50/60 px-5 py-4 space-y-4">

                          {/* 9router-style quota card grid */}
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">

                            {/* Image quota card */}
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
                                    {account.default_model_slug && (
                                      <span className="text-[10px] text-slate-400">#{account.default_model_slug}</span>
                                    )}
                                  </div>
                                </div>
                                <div className="flex gap-1">
                                  <button className="rounded-lg p-1.5 hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition" onClick={(e) => { e.stopPropagation(); void navigator.clipboard.writeText(account.access_token); toast.success("Token đã sao chép"); }} title="Copy token"><Copy className="size-3.5" /></button>
                                  <button className="rounded-lg p-1.5 hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition" onClick={(e) => { e.stopPropagation(); void handleRefreshAccounts([account.access_token]); }} disabled={isRefreshing} title={t("refresh")}><RefreshCw className={cn("size-3.5", isRefreshing && "animate-spin")} /></button>
                                </div>
                              </div>

                              {/* Image quota bar */}
                              {isUnlimited ? (
                                <div className="flex items-center gap-1.5">
                                  <span className="size-2 rounded-full bg-violet-500" />
                                  <span className="text-[11px] font-medium text-slate-500">Ảnh</span>
                                  <span className="ml-auto text-[12px] font-bold text-violet-600">∞ không giới hạn</span>
                                </div>
                              ) : !imageQuotaUnknown(account) ? (
                                <QuotaBar label="Ảnh (image)" used={Math.max(0, 100 - quotaVal)} max={100} resetAfter={account.restore_at ? formatRestoreAt(account.restore_at, lang).relative : undefined} />
                              ) : (
                                <div className="flex items-center gap-1.5">
                                  <span className="size-2 rounded-full bg-slate-300" />
                                  <span className="text-[11px] text-slate-400">Quota không rõ</span>
                                </div>
                              )}

                              {/* All limits_progress bars */}
                              {account.limits_progress?.map((lp, i) => (
                                <QuotaBar
                                  key={i}
                                  label={t(lp.feature_name as TranslationKey) ?? lp.feature_name ?? `Limit ${i + 1}`}
                                  used={Math.max(0, (lp as any).total ?? 100) - (lp.remaining ?? 0)}
                                  max={(lp as any).total ?? Math.max(lp.remaining ?? 0, 40)}
                                  resetAfter={lp.reset_after ? formatRestoreAt(lp.reset_after, lang).relative : undefined}
                                />
                              ))}

                              {/* Last used */}
                              <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-100">
                                <span>Dùng lần cuối</span>
                                <span className="font-medium text-slate-600">{formatRelativeTime(account.last_used_at, lang)}</span>
                              </div>
                            </div>

                            {/* Requests stats card */}
                            <div className="rounded-[12px] p-4 card-3d card-tint-emerald space-y-3">
                              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Thống kê yêu cầu</p>

                              {/* Success/fail bars */}
                              <div className="space-y-3">
                                <div className="space-y-1.5">
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="flex items-center gap-1.5">
                                      <span className="size-2 rounded-full bg-emerald-500" />
                                      <span className="text-[11px] font-medium text-slate-500">Thành công</span>
                                    </div>
                                    <span className="text-[11px] font-bold text-emerald-600">{account.success}</span>
                                  </div>
                                  {(account.success + account.fail) > 0 && (
                                    <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
                                      <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.round(account.success / (account.success + account.fail) * 100)}%` }} />
                                    </div>
                                  )}
                                </div>
                                <div className="space-y-1.5">
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="flex items-center gap-1.5">
                                      <span className="size-2 rounded-full bg-rose-500" />
                                      <span className="text-[11px] font-medium text-slate-500">Thất bại</span>
                                    </div>
                                    <span className="text-[11px] font-bold text-rose-500">{account.fail}</span>
                                  </div>
                                  {(account.success + account.fail) > 0 && (
                                    <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
                                      <div className="h-full bg-rose-500 rounded-full" style={{ width: `${Math.round(account.fail / (account.success + account.fail) * 100)}%` }} />
                                    </div>
                                  )}
                                </div>
                              </div>

                              {/* Restore at */}
                              {account.restore_at && (
                                <div className="rounded-[8px] bg-amber-50 border border-amber-100 px-3 py-2 text-[11px]">
                                  <p className="font-medium text-amber-700">Phục hồi: {formatRestoreAt(account.restore_at, lang).relative}</p>
                                  <p className="text-amber-500">{formatRestoreAt(account.restore_at, lang).absolute}</p>
                                </div>
                              )}

                              {/* Action buttons */}
                              <div className="flex flex-wrap gap-2 pt-1 border-t border-slate-100" onClick={e => e.stopPropagation()}>
                                <button
                                  className="flex items-center gap-1 rounded-[8px] border border-black/[0.06] bg-white px-2.5 py-1.5 text-[11px] font-medium text-indigo-600 hover:bg-indigo-50 transition"
                                  onClick={() => openEditDialog(account)}
                                >
                                  <Pencil className="size-3" /> Sửa trạng thái
                                </button>
                                <button
                                  className="flex items-center gap-1 rounded-[8px] border border-rose-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-rose-500 hover:bg-rose-50 transition"
                                  onClick={() => void handleDeleteTokens([account.access_token])}
                                  disabled={isDeleting}
                                >
                                  <Trash2 className="size-3" /> Xóa
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
              {!isLoading && currentRows.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
                  <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                    <Search className="size-5" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-stone-700">Không có tài khoản nào phù hợp</p>
                    <p className="text-sm text-stone-500">Thử điều chỉnh bộ lọc hoặc từ khóa tìm kiếm.</p>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="border-t border-black/[0.04] bg-slate-50/30 px-5 py-4">
              <div className="flex items-center justify-center gap-3 overflow-x-auto whitespace-nowrap">
                <div className="shrink-0 text-sm text-stone-500">
                Hiển thị {filteredAccounts.length === 0 ? 0 : startIndex + 1} -{" "}
                {Math.min(startIndex + Number(pageSize), filteredAccounts.length)} /{" "}
                {filteredAccounts.length} mục
                </div>

                <span className="shrink-0 text-sm leading-none text-stone-500">
                  Trang {safePage} / {pageCount}
                </span>
                <Select
                  value={pageSize}
                  onValueChange={(value) => {
                    setPageSize(value);
                    setPage(1);
                  }}
                >
                  <SelectTrigger className="h-10 w-[108px] shrink-0 rounded-lg border-stone-200 bg-white text-sm leading-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="10">10 / trang</SelectItem>
                    <SelectItem value="20">20 / trang</SelectItem>
                    <SelectItem value="50">50 / trang</SelectItem>
                    <SelectItem value="100">100 / trang</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10 shrink-0 rounded-lg border-stone-200 bg-white"
                  disabled={safePage <= 1}
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                >
                  <ChevronLeft className="size-4" />
                </Button>
                {paginationItems.map((item, index) =>
                  item === "..." ? (
                    <span key={`ellipsis-${index}`} className="px-1 text-sm text-stone-500">
                      ...
                    </span>
                  ) : (
                    <Button
                      key={item}
                      variant={item === safePage ? "default" : "outline"}
                      className={cn(
                        "h-10 min-w-10 shrink-0 rounded-lg px-3",
                        item === safePage
                          ? "bg-stone-900 text-white hover:bg-stone-800"
                          : "border-stone-200 bg-white text-stone-700",
                      )}
                      onClick={() => setPage(item)}
                    >
                      {item}
                    </Button>
                  ),
                )}
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10 shrink-0 rounded-lg border-stone-200 bg-white"
                  disabled={safePage >= pageCount}
                  onClick={() => setPage((prev) => Math.min(pageCount, prev + 1))}
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </div>
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
