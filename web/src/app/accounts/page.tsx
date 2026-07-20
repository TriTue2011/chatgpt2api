"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentProps } from "react";
import {
  ArrowUp,
  ArrowDown,
  Ban,
  Bot,
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
  Power,
  PowerOff,
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
  promoteAccount,
  demoteAccount,
  type Account,
  type AccountStatus,
} from "@/lib/api";
import { request } from "@/lib/request";
import { AccountTotpDisplay } from "@/components/account-totp-display";
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
    gradient: "from-[#D4AF37] to-[#B8860B]", shadow: "shadow-amber-200",
    bg: "from-amber-50/80 to-blue-50/80", textColor: "text-amber-900", labelColor: "text-amber-600",
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
    gradient: "from-[var(--muted-foreground)] to-[var(--muted-foreground)]", shadow: "shadow-slate-200",
    bg: "from-[var(--muted)]/80 to-[var(--secondary)]/80", textColor: "text-[var(--foreground)]", labelColor: "text-[var(--muted-foreground)]",
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

function tryDecodeJwtEmail(token?: string): string | null {
  if (!token) return null;
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const payload = JSON.parse(atob(parts[1]));
    const profile = payload?.["https://api.openai.com/profile"];
    return typeof profile?.email === "string" ? profile.email : null;
  } catch {
    return null;
  }
}

function accountLabel(account: Account) {
  return account.email || tryDecodeJwtEmail(account.access_token) || maskToken(account.access_token);
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
  // go and free → same ChatGPT group; codex stays separate
  if (account.type === "go") return "free";
  if (account.type === "codex") return "codex";
  return account.plan || account.type || "Free";
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
  label, remaining, total, resetAfter, ordinal
}: { label: string; remaining: number; total?: number; resetAfter?: string | null; ordinal?: number }) {
  const hasMax = total !== undefined;
  const max = hasMax ? total : 40;
  const used = Math.max(0, max - remaining);
  const pct = max > 0 ? Math.min(100, Math.round((used / max) * 100)) : 0;
  const remainPct = hasMax ? 100 - pct : (remaining > 0 ? 100 : 0);
  
  const dotColor = remainPct > 70 ? "bg-emerald-500" : remainPct > 30 ? "bg-amber-400" : "bg-rose-500";
  const barColor = remainPct > 70 ? "bg-emerald-500" : remainPct > 30 ? "bg-amber-400" : "bg-rose-500";
  
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className={`size-2 rounded-full shrink-0 ${dotColor}`} />
          <span className="text-[11px] font-medium text-[var(--muted-foreground)]">{label}</span>
          {ordinal !== undefined && (
            <span className="ml-1 px-1.5 py-0.5 rounded-[4px] bg-amber-50 text-amber-600 text-[9px] font-bold">#{ordinal}</span>
          )}
        </div>
        {resetAfter && (
          <span className="text-[10px] text-[var(--muted-foreground)] shrink-0">{resetAfter}</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <div className="relative flex-1 h-1.5 rounded-full bg-[var(--secondary)] overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${barColor}`}
            style={{ width: `${remainPct}%` }}
          />
        </div>
        <span className="text-[11px] text-[var(--muted-foreground)] shrink-0 min-w-[50px] text-right">
          {hasMax ? `${remaining} / ${total}` : (remaining > 0 ? `Còn ${remaining}` : "Hết lượt")}
        </span>
        {hasMax && (
          <span className={`text-[11px] font-bold shrink-0 w-8 text-right ${dotColor.replace('bg-', 'text-')}`}>
            {remainPct}%
          </span>
        )}
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
  const [editType, setEditType] = useState<string>("");
  // Per-account notes editor (web-session rows: key = access_token / profile)
  const [notesDraft, setNotesDraft] = useState<Record<string, string>>({});
  const [savingNotes, setSavingNotes] = useState<string | null>(null);
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
    await buildProviderTree();
  };

  const buildProviderTree = async () => {
    const tree: any[] = [];
    try {
      // Fetch both endpoints in parallel — /health gives per-key status,
      // /provider-tree gives the Flow branch + custom-provider endpoints[]
      // (multi-pool URLs). Merge so the UI shows everything.
      const [healthRes, treeRes] = await Promise.all([
        request.get("/api/v1/health"),
        request.get("/api/v1/provider-tree").catch(() => ({ data: { tree: [] } })),
      ]);
      const health = (healthRes.data as any) || {};
      const gemini = health.gemini || {};
      const instances: any[] = gemini.instances || [];
      const ptBranches: any[] = ((treeRes?.data as any) || {}).tree || [];

      // ── Gemini API: separate branch like ChatGPT, each key is a row ──
      const geminiInst = instances.find((i: any) => i.id === "gemini_free");
      if (geminiInst && geminiInst.keys?.length > 0) {
        tree.push({
          provider: "Gemini API",
          icon: "gemini",
          type: "gemini_keys",
          total: geminiInst.keys.length,
          available: geminiInst.available_keys || 0,
          status: geminiInst.status,
          models: geminiInst.models || 0,
          keys: geminiInst.keys.map((k: any) => ({
            id: k.key_preview,
            key_preview: k.key_preview,
            status: k.status,
            models: k.models || 0,
            error: k.error || null,
          })),
        });
      }

      // ── Other Custom Providers ──
      const otherInsts = instances.filter((i: any) => i.id !== "gemini_free");
      if (otherInsts.length > 0) {
        tree.push({
          provider: "Providers & APIs",
          icon: "server",
          type: "providers",
          instances: otherInsts,
          total: otherInsts.length,
        });
      }

      // ── Gemini Web / ChatGPT Web / Gemini Web API profile branches ──
      // Both live in `providers.{gemini_web,chatgpt_web,gemini_web_api}.profile` rather
      // than accounts.json, so they only reach the UI via /provider-tree.
      const gwBranch = ptBranches.find((b: any) => b.type === "gemini_web");
      if (gwBranch) {
        tree.push(gwBranch);
      }
      const gwaBranch = ptBranches.find((b: any) => b.type === "gemini_web_api");
      if (gwaBranch) {
        tree.push(gwaBranch);
      }
      const cgwBranch = ptBranches.find((b: any) => b.type === "chatgpt_web");
      if (cgwBranch) {
        tree.push(cgwBranch);
      }

      // ── Flow branch — only available from /provider-tree ──
      const flowBranch = ptBranches.find((b: any) => b.provider === "Google Labs Flow" || b.type === "flow");
      if (flowBranch) {
        tree.push(flowBranch);
      }

      // ── Claude branch — only available from /provider-tree ──
      const claudeBranch = ptBranches.find((b: any) => b.type === "claude");
      if (claudeBranch) {
        tree.push(claudeBranch);
      }

    } catch (e) {
      console.error("buildProviderTree failed:", e);
    }
    setProviderTree(tree);
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
      if (branch.provider !== "ChatGPT") {
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
    setEditType(account.type || "free");
  };

  const handleToggleAccount = async (account: Account) => {
    const newStatus: AccountStatus = account.status === "active" ? "disabled" : "active";
    try {
      const data = await updateAccount(account.access_token, { status: newStatus });
      setAccounts(data.items);
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.access_token === id)));
      toast.success(newStatus === "disabled" ? "Đã vô hiệu hóa tài khoản" : "Đã kích hoạt tài khoản");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Thay đổi trạng thái thất bại");
    }
  };

  const handleUpdateAccount = async () => {
    if (!editingAccount) {
      return;
    }

    setIsUpdating(true);
    try {
      const data = await updateAccount(editingAccount.access_token, {
        status: editStatus,
        type: editType,
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

  const handleSaveNotes = async (token: string) => {
    if (!token) return;
    const value = notesDraft[token] ?? "";
    setSavingNotes(token);
    try {
      const data = await updateAccount(token, { notes: value });
      setAccounts(data.items);
      await fetchProviderTree();
      toast.success("Đã lưu ghi chú");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Lưu ghi chú thất bại");
    } finally {
      setSavingNotes(null);
    }
  };

  // Move a web-session account to #1 / to the back of its rotation pool.
  const handleReorderAccount = async (token: string, dir: "promote" | "demote") => {
    if (!token) return;
    try {
      await (dir === "promote" ? promoteAccount([token]) : demoteAccount([token]));
      await loadAccounts(true);
      await fetchProviderTree();
      toast.success(dir === "promote" ? "Đã đặt làm #1" : "Đã chuyển xuống cuối");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Đổi thứ tự thất bại");
    }
  };

  // Set the status of a web-session account (active / disabled). The profile is
  // its access_token; if it isn't pooled yet the update 404s harmlessly.
  const handleSetWebStatus = async (token: string, status: AccountStatus) => {
    if (!token) return;
    try {
      const data = await updateAccount(token, { status });
      setAccounts(data.items);
      await fetchProviderTree();
      toast.success(status === "disabled" ? "Đã vô hiệu hóa" : "Đã cập nhật trạng thái");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Cập nhật trạng thái thất bại");
    }
  };

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...currentRows.map((item) => item.access_token)])));
      return;
    }
    setSelectedIds((prev) => prev.filter((id) => !currentRows.some((row) => row.access_token === id)));
  };

  // Expandable detail panel for a web-session row (Claude / Gemini Web API),
  // mirroring the ChatGPT account detail: status + request stats + last-used +
  // an editable notes field. `inst.access_token` is the captcha-solver profile.
  const renderWebAccountDetail = (inst: any) => {
    const token = String(inst.access_token || "");
    const noteValue = notesDraft[token] ?? inst.notes ?? "";
    const clStatus = String(inst.status || "active");
    const dot =
      clStatus === "active" ? "bg-emerald-400" :
      clStatus === "error" ? "bg-rose-400" :
      clStatus === "disabled" ? "bg-[var(--secondary)]" : "bg-amber-400";
    return (
      <div className="pl-12 pr-5 pb-3 bg-[var(--muted)]/50 border-t border-[var(--border)]">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-3">
          <div className="rounded-[12px] p-4 card-3d card-tint-emerald space-y-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[13px] font-bold text-[var(--foreground)] truncate">{inst.label || inst.email || inst.profile}</p>
              <Badge variant="secondary" className="inline-flex items-center gap-1 rounded text-[10px] px-1 py-0">
                <span className={cn("size-1.5 rounded-full", dot)} />
                {translateStatus(clStatus, lang)}
              </Badge>
            </div>
            {inst.profile ? <code className="block text-[10px] text-[var(--muted-foreground)] truncate">profile: {inst.profile}</code> : null}
            <div className="flex items-center gap-4 text-[11px]">
              <span className="text-emerald-600">{inst.success ?? 0} thành công</span>
              <span className="text-rose-400">{inst.fail ?? 0} thất bại</span>
            </div>
            <div className="flex items-center justify-between text-[11px] text-[var(--muted-foreground)] pt-1 border-t border-[var(--border)]">
              <span>Dùng lần cuối</span>
              <span className="font-medium text-[var(--muted-foreground)]">{formatRelativeTime(inst.last_used_at, lang)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-[var(--border)]">
              <button
                type="button"
                onClick={() => void handleReorderAccount(token, "promote")}
                disabled={inst.is_primary}
                className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-emerald-300 hover:text-emerald-600 disabled:opacity-40"
                title="Đưa lên đầu hàng đợi (ưu tiên dùng trước)"
              >
                <ArrowUp className="size-3" /> Đặt #1
              </button>
              <button
                type="button"
                onClick={() => void handleReorderAccount(token, "demote")}
                className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
                title="Chuyển xuống cuối hàng đợi"
              >
                <ArrowDown className="size-3" /> Xuống cuối
              </button>
              <button
                type="button"
                onClick={() => void handleSetWebStatus(token, clStatus === "disabled" ? "active" : "disabled")}
                className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-amber-300 hover:text-amber-600"
                title={clStatus === "disabled" ? "Kích hoạt lại" : "Tạm vô hiệu hóa"}
              >
                {clStatus === "disabled" ? <Power className="size-3" /> : <PowerOff className="size-3" />}
                {clStatus === "disabled" ? "Kích hoạt" : "Vô hiệu hóa"}
              </button>
            </div>
          </div>
          <div className="rounded-[12px] p-4 card-3d card-tint-sky space-y-2">
            <label className="block text-[11px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Ghi chú</label>
            <textarea
              value={noteValue}
              onChange={(e) => setNotesDraft((prev) => ({ ...prev, [token]: e.target.value }))}
              placeholder="Thêm ghi chú cho tài khoản này…"
              rows={3}
              className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[12px] text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:border-[var(--border)] focus:outline-none"
            />
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => void handleSaveNotes(token)}
                disabled={savingNotes === token || noteValue === (inst.notes ?? "")}
                className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-[11px] font-medium text-white transition-colors hover:bg-slate-800 disabled:opacity-40"
              >
                {savingNotes === token ? <LoaderCircle className="size-3 animate-spin" /> : null}
                Lưu ghi chú
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  // Edit/toggle/delete a profile-style account row (flow, gemini_web,
  // chatgpt_web). Mirrors the ChatGPT pool's per-row actions: each row
  // can be removed entirely or flipped enabled/disabled in the rotation.
  const mutateProviderAccounts = async (
    providerKey: "flow" | "gemini_web" | "gemini_web_api" | "chatgpt_web" | "claude",
    profile: string,
    op: "delete" | "toggle",
  ) => {
    try {
      const cur = (await request.get("/api/settings")).data as any;
      const providers = { ...((cur?.config?.providers) || {}) };
      const cfg = { ...((providers[providerKey] as any) || {}) };
      
      if (providerKey === "claude") {
        const profiles = Array.isArray(cfg.profiles) ? cfg.profiles.slice() : (cfg.profile ? [cfg.profile] : []);
        const idx = profiles.indexOf(profile);
        if (idx < 0) {
          toast.error(`Không tìm thấy profile ${profile}`);
          return;
        }
        if (op === "delete") {
          profiles.splice(idx, 1);
          // Update primary profile if needed
          if (cfg.profile === profile) {
            cfg.profile = profiles[0] || "";
          }
        }
        cfg.profiles = profiles;
      } else {
        const accounts = Array.isArray(cfg.accounts) ? cfg.accounts.slice() : [];
        const idx = accounts.findIndex((a: any) => a?.profile === profile);
        if (idx < 0) {
          toast.error(`Không tìm thấy profile ${profile}`);
          return;
        }
        if (op === "delete") {
          accounts.splice(idx, 1);
        } else {
          const cur = accounts[idx] || {};
          accounts[idx] = { ...cur, enabled: cur.enabled === false };
        }
        cfg.accounts = accounts;
      }
      
      providers[providerKey] = cfg;
      await request.post("/api/settings", { providers });
      toast.success(op === "delete" ? "Đã xóa tài khoản" : "Đã đổi trạng thái");
      void fetchProviderTree();
    } catch (e: any) {
      toast.error(e?.message || "Thao tác thất bại");
    }
  };

  return (
    <>
      {/* ── Header: multi-row layout ── */}
      <section className="space-y-3">
        {/* Row 1: Title + count */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-[22px] font-bold tracking-tight text-[var(--foreground)]">{t("title")}</h1>
            <Badge variant="secondary" className="rounded-lg bg-[var(--secondary)] px-2.5 py-0.5 text-sm text-[var(--foreground)]">
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
            className="inline-flex items-center gap-1.5 h-9 rounded-lg border border-black/[0.08] bg-[var(--card)] px-3.5 text-[13px] font-medium text-[var(--muted-foreground)] hover:bg-[var(--muted)] transition"
          >
            <ExternalLink className="size-3.5" />
            Custom API
          </a>
          <Button
            variant="outline"
            className="h-9 rounded-lg border-black/[0.08] bg-[var(--card)] px-3.5 text-[13px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
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
            className="h-9 rounded-lg border-black/[0.08] bg-[var(--card)] px-3 text-[13px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            onClick={() => void loadAccounts()}
            disabled={isLoading || isRefreshing || isDeleting}
          >
            <RefreshCw className={cn("size-3.5 mr-1.5", isLoading ? "animate-spin" : "")} />
            Làm mới
          </Button>
          <Button
            variant="outline"
            className="h-9 rounded-lg border-black/[0.08] bg-[var(--card)] px-3 text-[13px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            onClick={() => void handleRefreshAccounts(accounts.map((item) => item.access_token))}
            disabled={isLoading || isRefreshing || isDeleting || accounts.length === 0}
          >
            <RefreshCw className={cn("size-3.5 mr-1.5", isRefreshing ? "animate-spin" : "")} />
            Làm mới tất cả
          </Button>
          <Button
            variant="outline"
            className="h-9 rounded-lg border-black/[0.08] bg-[var(--card)] px-3 text-[13px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            onClick={() => void handleRefreshAccounts(selectedTokens)}
            disabled={isLoading || isRefreshing || isDeleting || selectedTokens.length === 0}
          >
            <RefreshCw className={cn("size-3.5 mr-1.5", isRefreshing ? "animate-spin" : "")} />
            Làm mới đã chọn ({selectedTokens.length})
          </Button>

          <div className="flex-1" />

          <div className="relative w-full sm:w-[200px]">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
            <Input
              value={query}
              onChange={(event) => { setQuery(event.target.value); setPage(1); }}
              placeholder="Tìm kiếm..."
              className="h-9 rounded-lg border-[var(--border)] bg-[var(--card)] pl-8 w-full text-sm"
            />
          </div>
          <Select value={typeFilter} onValueChange={(value) => { setTypeFilter(value); setPage(1); }}>
            <SelectTrigger className="h-9 rounded-lg border-[var(--border)] bg-[var(--card)] w-[110px] text-sm">
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
            <SelectTrigger className="h-9 rounded-lg border-[var(--border)] bg-[var(--card)] w-[120px] text-sm">
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
              <label className="text-sm font-medium text-[var(--foreground)]">{t("status")}</label>
              <Select value={editStatus} onValueChange={(value) => setEditStatus(value as AccountStatus)}>
                <SelectTrigger className="h-11 rounded-xl border-[var(--border)] bg-[var(--card)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {accountStatusOptions
                    .filter((option) => option.value !== "all")
                    .map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {t(option.labelKey)}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-[var(--foreground)]">Loại (type)</label>
              <Select value={editType} onValueChange={setEditType}>
                <SelectTrigger className="h-11 rounded-xl border-[var(--border)] bg-[var(--card)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="free">free (ChatGPT Session)</SelectItem>
                  <SelectItem value="codex">codex (OAuth / 9router)</SelectItem>
                  <SelectItem value="go">go</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-[var(--secondary)] px-5 text-[var(--foreground)] hover:bg-[var(--secondary)]"
              onClick={() => setEditingAccount(null)}
              disabled={isUpdating}
            >
              Hủy
            </Button>
            <Button
              className="h-10 rounded-xl bg-[var(--primary)] px-5 text-[var(--primary-foreground)] hover:brightness-110"
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
              <div className="rounded-xl bg-[var(--secondary)] p-3 text-[var(--muted-foreground)]">
                <LoaderCircle className="size-5 animate-spin" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium text-[var(--foreground)]">{t("loadingAccounts")}</p>
                <p className="text-sm text-[var(--muted-foreground)]">{t("syncingAccounts")}</p>
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
                provider.provider === "Gemini API" ? "card-tint-violet" :
                provider.provider === "Providers & APIs" ? "card-tint-indigo" :
                "card-tint-slate";
              const Icon = provider.icon === "chatgpt" ? Sparkles :
                provider.icon === "gemini" ? Sparkles :
                provider.icon === "bot" ? Bot :
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
                      "size-4 text-[var(--muted-foreground)] transition-transform",
                      isProviderOpen && "rotate-180"
                    )} />
                    <div className="flex size-9 items-center justify-center rounded-xl bg-[var(--card)]/60">
                      <Icon className="size-4 text-[var(--muted-foreground)]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <span className="text-[15px] font-bold text-[var(--foreground)]">{provider.provider}</span>
                    </div>
                    <Badge variant="secondary" className="rounded-md bg-[var(--card)]/60 text-[11px] px-2 text-[var(--muted-foreground)]">
                      {provider.total} mục
                    </Badge>
                  </button>

                  {/* Level 2: Sub-items */}
                  {isProviderOpen && (
                    <div className="divide-y divide-black/[0.03]">
                      {/* ChatGPT: groups by account type */}
                      {provider.type === "accounts" && provider.groups?.map((group: any) => {
                        const isGroupOpen = expandedGroups.has(`${provider.provider}/${group.key}`);
                        
                        const featureRanks: Record<string, Record<string, number>> = {};
                        group.items?.forEach((acc: any) => {
                          if (acc.status === 'disabled' || acc.status === 'error') return;
                          
                          const igRemaining = Math.max(0, acc.quota || 0);
                          if (igRemaining > 0) {
                            if (!featureRanks['image_gen']) featureRanks['image_gen'] = {};
                            featureRanks['image_gen'][acc.access_token] = Object.keys(featureRanks['image_gen']).length + 1;
                          }

                          acc.limits_progress?.forEach((lp: any) => {
                            if ((lp.remaining ?? 0) > 0) {
                              if (!featureRanks[lp.feature_name]) featureRanks[lp.feature_name] = {};
                              featureRanks[lp.feature_name][acc.access_token] = Object.keys(featureRanks[lp.feature_name]).length + 1;
                            }
                          });
                        });

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
                              className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-[var(--muted)]/60 transition-colors"
                            >
                              <ChevronDown className={cn(
                                "size-3.5 text-[var(--muted-foreground)] transition-transform",
                                isGroupOpen && "rotate-180"
                              )} />
                              <span className="flex-1 text-[13px] font-semibold text-[var(--foreground)]">{group.label}</span>
                              <Badge variant="secondary" className="rounded-md bg-[var(--secondary)] text-[10px] px-1.5 text-[var(--muted-foreground)]">
                                {group.count}
                              </Badge>
                              <span className="flex items-center gap-1 text-[10px] text-emerald-600">{group.active} active</span>
                              <span className="flex items-center gap-1 text-[10px] text-amber-600">{group.limited} limited</span>
                              {group.error > 0 && (
                                <span className="flex items-center gap-1 text-[10px] text-rose-500">{group.error} err</span>
                              )}
                            </button>

                            {/* Level 3: Individual accounts */}
                            {isGroupOpen && group.items?.map((account: Account, accountIdx: number) => {
                              const accountExpanded = expandedId === account.access_token;
                              const status = statusMeta[account.status as AccountStatus] || statusMeta.error;
                              const StatusIcon = status.icon;
                              const isUnlimited = isUnlimitedImageQuotaAccount(account);
                              const quotaVal = Math.max(0, account.quota);
                              // Per-type ordinal: account #1 = primary in this
                              // type's priority queue (always tried first by the
                              // backend until it 429s). 1-indexed for humans.
                              const ordinal = accountIdx + 1;
                              
                              const featureBadges: string[] = [];
                              const hasLimitsImageGen = account.limits_progress?.some((lp: any) => lp.feature_name === 'image_gen');
                              
                              const igRank = featureRanks['image_gen']?.[account.access_token];
                              if (!hasLimitsImageGen && igRank === 1) {
                                featureBadges.push(`Tạo ảnh #1`);
                              }
                              account.limits_progress?.forEach((lp: any) => {
                                const rank = featureRanks[lp.feature_name]?.[account.access_token];
                                if (rank === 1) {
                                  featureBadges.push(`${t(lp.feature_name as TranslationKey) ?? lp.feature_name} #1`);
                                }
                              });
                              const uniqueFeatureBadges = Array.from(new Set(featureBadges));

                              const exhausted: string[] = [];
                              account.limits_progress?.forEach((lp: any) => {
                                if ((lp.remaining ?? 0) <= 0) {
                                  exhausted.push(t(lp.feature_name as TranslationKey) ?? lp.feature_name);
                                }
                              });
                              if (!hasLimitsImageGen && !isUnlimited && !imageQuotaUnknown(account) && quotaVal <= 0) {
                                exhausted.push("Tạo ảnh");
                              }
                              
                              if ((account as any).last_quota_exhausted) {
                                const val = (account as any).last_quota_exhausted;
                                const trans = val === "file_upload" ? "Gửi ảnh" :
                                              val === "advanced_data_analysis" ? "Phân tích DL" :
                                              "Text";
                                const at = (account as any).last_quota_exhausted_at?.split(' ')[1] || 'gần đây';
                                exhausted.push(`${trans} lúc ${at}`);
                              }
                              
                              const uniqueExhausted = Array.from(new Set(exhausted));

                              return (
                                <div key={account.access_token}>
                                    <div
                                      className={cn(
                                        "flex items-center gap-3 pl-12 pr-5 py-2.5 hover:bg-[var(--muted)]/60 cursor-pointer transition-colors",
                                        accountExpanded && "bg-amber-50/40"
                                      )}
                                      onClick={() => setExpandedId(accountExpanded ? null : account.access_token)}
                                    >
                                      <Checkbox
                                        className="size-4"
                                        checked={selectedIds.includes(account.access_token)}
                                        onClick={(e) => e.stopPropagation()}
                                        onCheckedChange={(checked) => {
                                          if (checked) {
                                            setSelectedIds(prev => [...prev, account.access_token]);
                                          } else {
                                            setSelectedIds(prev => prev.filter(id => id !== account.access_token));
                                          }
                                        }}
                                      />
                                    <div className={cn(
                                      "size-7 shrink-0 rounded-full flex items-center justify-center",
                                      account.status === "active" ? "bg-gradient-to-br from-[#D4AF37] to-[#B8860B]"
                                      : account.status === "limited" ? "bg-gradient-to-br from-amber-400 to-orange-500"
                                      : account.status === "error" ? "bg-gradient-to-br from-rose-500 to-red-600"
                                      : "bg-[var(--secondary)]"
                                    )}>
                                      <UserRound className="size-3 text-white" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex flex-col gap-1">
                                        <div className="flex items-center gap-1.5">
                                          <span className="text-[12px] font-medium text-[var(--foreground)] truncate max-w-[140px]">
                                            {accountLabel(account)}
                                          </span>
                                          <Badge variant={status.badge} className="inline-flex items-center gap-0.5 rounded text-[10px] px-1 py-0">
                                            <StatusIcon className="size-2.5" />
                                            {translateStatus(account.status, lang)}
                                          </Badge>
                                          {account.type && account.type !== account.plan ? (
                                            <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-amber-50 text-amber-700 border border-amber-200">
                                              {account.type}
                                            </Badge>
                                          ) : null}
                                        </div>
                                        {(uniqueFeatureBadges.length > 0 || uniqueExhausted.length > 0) && (
                                          <div className="flex flex-wrap items-center gap-1">
                                            {uniqueFeatureBadges.map(f => (
                                              <Badge key={`top-${f}`} variant="secondary" className="rounded text-[9px] px-1 py-0 bg-amber-50 text-amber-600 border border-amber-100 font-medium">
                                                {f}
                                              </Badge>
                                            ))}
                                            {uniqueExhausted.map(f => (
                                              <Badge key={`ex-${f}`} variant="secondary" className="rounded text-[9px] px-1 py-0 bg-rose-50 text-rose-500 border border-rose-100 font-medium">
                                                Hết {f}
                                              </Badge>
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                    <div className="hidden sm:flex items-center gap-2 text-[11px]">
                                      <span className="text-emerald-600">{account.success}✓</span>
                                      <span className="text-rose-400">{account.fail}✗</span>
                                    </div>
                                    <div className="text-[11px] font-bold">
                                      {isUnlimited ? <span className="text-violet-600">∞</span>
                                        : imageQuotaUnknown(account) ? <span className="text-[var(--muted-foreground)]">?</span>
                                        : <span className={quotaVal > 0 ? "text-emerald-600" : "text-rose-500"}>{quotaVal}</span>
                                      }
                                    </div>
                                    <div className="flex items-center gap-1 text-[var(--muted-foreground)]" onClick={e => e.stopPropagation()}>
                                      <button className="rounded p-0.5 hover:bg-[var(--secondary)] hover:text-[var(--foreground)]" onClick={() => openEditDialog(account)}><Pencil className="size-3" /></button>
                                      <button
                                        className="rounded p-0.5 hover:bg-amber-50 hover:text-amber-600"
                                        onClick={() => void handleToggleAccount(account)}
                                        title={account.status === "disabled" ? "Kích hoạt" : "Vô hiệu hóa"}
                                      >
                                        {account.status === "disabled" ? <Power className="size-3" /> : <PowerOff className="size-3" />}
                                      </button>
                                      <button className="rounded p-0.5 hover:bg-rose-50 hover:text-rose-500" onClick={() => void handleDeleteTokens([account.access_token])}><Trash2 className="size-3" /></button>
                                    </div>
                                  </div>
                                  {/* Account expanded detail */}
                                  {accountExpanded && (
                                    <div className="pl-12 pr-5 pb-3 bg-[var(--muted)]/50 border-t border-amber-100">
                                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-3">
                                        <div className="rounded-[12px] p-4 card-3d card-tint-emerald space-y-3">
                                          <div className="flex items-center justify-between">
                                            <div>
                                              <p className="text-[13px] font-bold text-[var(--foreground)]">{accountLabel(account)}</p>
                                              <div className="flex items-center gap-2 mt-0.5">
                                                <Badge variant={status.badge} className="inline-flex items-center gap-0.5 rounded text-[10px] px-1 py-0">
                                                  <span className={cn("size-1.5 rounded-full mr-0.5",
                                                    account.status === "active" ? "bg-emerald-400" :
                                                    account.status === "limited" ? "bg-amber-400" :
                                                    account.status === "error" ? "bg-rose-400" : "bg-[var(--secondary)]"
                                                  )} />
                                                  {translateStatus(account.status, lang)}
                                                </Badge>
                                                <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-[var(--secondary)] text-[var(--muted-foreground)]">
                                                  {displayAccountType(account)}
                                                </Badge>
                                                {account.type && account.type !== account.plan ? (
                                                  <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-amber-50 text-amber-700 border border-amber-200">
                                                    {account.type}
                                                  </Badge>
                                                ) : null}
                                              </div>
                                            </div>
                                          </div>
                                          {isUnlimited ? (
                                            <div className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-violet-500" /><span className="text-[11px] text-[var(--muted-foreground)]">Tạo ảnh:</span><span className="text-[12px] font-bold text-violet-600">∞ không giới hạn</span></div>
                                          ) : (!hasLimitsImageGen && !imageQuotaUnknown(account)) ? (
                                            <QuotaBar label="Tạo ảnh" remaining={quotaVal} resetAfter={account.restore_at ? formatRestoreAt(account.restore_at, lang).relative : undefined} ordinal={featureRanks['image_gen']?.[account.access_token]} />
                                          ) : null}
                                          {account.limits_progress?.map((lp, i) => (
                                            <QuotaBar key={i} label={t(lp.feature_name as TranslationKey) ?? lp.feature_name ?? `Limit ${i + 1}`} remaining={lp.remaining ?? 0} total={(lp as any).total} resetAfter={lp.reset_after ? formatRestoreAt(lp.reset_after, lang).relative : undefined} ordinal={featureRanks[lp.feature_name]?.[account.access_token]} />
                                          ))}
                                          <div className="flex items-center justify-between text-[11px] text-[var(--muted-foreground)] pt-1 border-t border-[var(--border)]">
                                            <span>Dùng lần cuối</span>
                                            <span className="font-medium text-[var(--muted-foreground)]">{formatRelativeTime(account.last_used_at, lang)}</span>
                                          </div>
                                        </div>
                                        <div className="rounded-[12px] p-4 card-3d card-tint-sky space-y-3">
                                          <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Thống kê yêu cầu</p>
                                          <div className="space-y-3">
                                            <div className="space-y-1.5">
                                              <div className="flex items-center justify-between gap-2">
                                                <div className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-emerald-500" /><span className="text-[11px] text-[var(--muted-foreground)]">Thành công</span></div>
                                                <span className="text-[11px] font-bold text-emerald-600">{account.success}</span>
                                              </div>
                                            </div>
                                            <div className="space-y-1.5">
                                              <div className="flex items-center justify-between gap-2">
                                                <div className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-rose-500" /><span className="text-[11px] text-[var(--muted-foreground)]">Thất bại</span></div>
                                                <span className="text-[11px] font-bold text-rose-500">{account.fail}</span>
                                              </div>
                                            </div>
                                          </div>
                                        </div>
                                      </div>
                                      {/* TOTP Authenticator display */}
                                      <div className="mt-3">
                                        <AccountTotpDisplay
                                          email={account.email || accountLabel(account)}
                                          label={account.email || accountLabel(account)}
                                        />
                                      </div>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        );
                      })}

                      {/* Gemini API: per-key rows like ChatGPT accounts */}
                      {provider.type === "gemini_keys" && provider.keys?.map((keyInfo: any) => {
                        const keyStatus = keyInfo.status;
                        const statusColor = keyStatus === "available" ? "bg-gradient-to-br from-[#D4AF37] to-[#B8860B]" :
                          keyStatus === "rate_limited" ? "bg-gradient-to-br from-amber-400 to-orange-500" :
                          keyStatus === "auth_error" ? "bg-gradient-to-br from-rose-500 to-red-600" :
                          "bg-[var(--secondary)]";
                        return (
                        <div key={keyInfo.id}>
                          <div className={cn(
                            "flex items-center gap-3 px-5 py-3 hover:bg-[var(--muted)]/60 cursor-pointer transition-colors",
                          )}>
                            <div className={cn("size-8 shrink-0 rounded-full flex items-center justify-center", statusColor)}>
                              <span className="text-[10px] font-bold text-white">K</span>
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="text-[13px] font-semibold text-[var(--foreground)]">API Key</span>
                                <code className="text-[11px] text-[var(--muted-foreground)]">{keyInfo.key_preview}</code>
                              </div>
                              <div className="flex items-center gap-2 mt-0.5">
                                <span className={cn(
                                  "inline-flex items-center gap-1 rounded-md text-[10px] px-1.5 py-0",
                                  keyStatus === "available" ? "bg-emerald-500/10 text-emerald-600" :
                                  keyStatus === "rate_limited" ? "bg-amber-500/10 text-amber-600" :
                                  keyStatus === "auth_error" ? "bg-rose-500/10 text-rose-500" :
                                  "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                                )}>
                                  {keyStatus}
                                </span>
                                {keyInfo.models > 0 && <span className="text-[10px] text-[var(--muted-foreground)]">{keyInfo.models} models</span>}
                              </div>
                            </div>
                            {keyInfo.error && (
                              <span className="text-[10px] text-rose-400 max-w-[180px] truncate text-right">{keyInfo.error}</span>
                            )}
                          </div>
                        </div>
                        );
                      })}

                      {/* Google Labs Flow accounts — profile + project_id rows with ordinals */}
                      {provider.type === "flow" && provider.instances?.map((flow: any) => (
                        <div key={`flow:${flow.profile}:${flow.project_id}`}>
                          <div className="flex items-center gap-3 px-5 py-3 hover:bg-[var(--muted)]/60 transition-colors">
                            <span
                              className={cn(
                                "shrink-0 inline-flex items-center justify-center min-w-[28px] h-5 px-1.5 rounded-md text-[11px] font-mono font-bold tabular-nums",
                                flow.is_primary
                                  ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300"
                                  : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                              )}
                              title={flow.is_primary ? "Tài khoản Flow ưu tiên #1" : `Vị trí #${flow.ordinal} trong hàng đợi`}
                            >
                              #{flow.ordinal}
                            </span>
                            <div className={cn(
                              "size-8 shrink-0 rounded-full flex items-center justify-center",
                              flow.enabled === false
                                ? "bg-[var(--secondary)]"
                                : "bg-gradient-to-br from-emerald-500 to-teal-600"
                            )}>
                              <span className="text-[10px] font-bold text-white">FL</span>
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="text-[13px] font-semibold text-[var(--foreground)] truncate">{flow.label || flow.profile}</span>
                                <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-emerald-50 text-emerald-700 border border-emerald-200">
                                  Flow
                                </Badge>
                                {flow.enabled === false && (
                                  <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-[var(--secondary)] text-[var(--muted-foreground)] border border-[var(--border)]">
                                    disabled
                                  </Badge>
                                )}
                              </div>
                              <div className="flex items-center gap-2 mt-0.5">
                                <code className="text-[10px] text-[var(--muted-foreground)]">profile: {flow.profile}</code>
                                <span className="text-[10px] text-[var(--secondary-foreground)]">·</span>
                                <code className="text-[10px] text-[var(--muted-foreground)]">project: {flow.project_preview}</code>
                              </div>
                            </div>
                            <div className="flex items-center gap-1 text-[var(--muted-foreground)]" onClick={(e) => e.stopPropagation()}>
                              <button
                                className="rounded p-0.5 hover:bg-amber-50 hover:text-amber-600"
                                onClick={() => void mutateProviderAccounts("flow", flow.profile, "toggle")}
                                title={flow.enabled === false ? "Kích hoạt" : "Vô hiệu hóa"}
                              >
                                {flow.enabled === false ? <Power className="size-3" /> : <PowerOff className="size-3" />}
                              </button>
                              <button
                                className="rounded p-0.5 hover:bg-rose-50 hover:text-rose-500"
                                onClick={() => void mutateProviderAccounts("flow", flow.profile, "delete")}
                                title="Xóa"
                              >
                                <Trash2 className="size-3" />
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}

                      {/* Gemini Web / ChatGPT Web / Gemini Web API profile rows — same rich UX as Claude.
                          Reads from config but merges with account_service for quota/status. */}
                      {(provider.type === "gemini_web" || provider.type === "chatgpt_web" || provider.type === "gemini_web_api") && provider.instances?.map((inst: any) => {
                        const providerKey = provider.type as "gemini_web" | "chatgpt_web" | "gemini_web_api";
                        const tagLabel = providerKey === "gemini_web" ? "Gemini Web" : providerKey === "chatgpt_web" ? "ChatGPT Web" : "Gemini Web API";
                        const initials = providerKey === "gemini_web" ? "GM" : providerKey === "chatgpt_web" ? "CG" : "GW";
                        const isFlowConfigured = inst.enabled !== false;
                        
                        const wbStatus = inst.status || (isFlowConfigured ? "active" : "disabled");
                        const statusColor =
                          !isFlowConfigured ? "bg-[var(--secondary)]"
                          : wbStatus === "active" ? "bg-gradient-to-br from-[#D4AF37] to-[#B8860B]"
                          : wbStatus === "error" ? "bg-gradient-to-br from-rose-500 to-red-600"
                          : wbStatus === "limited" ? "bg-gradient-to-br from-amber-400 to-orange-500"
                          : "bg-[var(--secondary)]";

                        // Quota exhausted badges
                        const wbExhausted: string[] = [];
                        if (inst.last_image_failed_at) {
                          const at = inst.last_image_failed_at.split(" ")[1] || "gần đây";
                          wbExhausted.push(`Gửi ảnh lúc ${at}`);
                        }
                        if (inst.last_analysis_failed_at) {
                          const at = inst.last_analysis_failed_at.split(" ")[1] || "gần đây";
                          wbExhausted.push(`Phân tích DL lúc ${at}`);
                        }
                        if (inst.last_quota_exhausted === "text_limit" && inst.last_quota_exhausted_at) {
                          const at = inst.last_quota_exhausted_at.split(" ")[1] || "gần đây";
                          wbExhausted.push(`Text lúc ${at}`);
                        }

                        return (
                        <div key={`${providerKey}:${inst.profile}`}>
                          <div
                            className="flex items-center gap-3 px-5 py-3 hover:bg-[var(--muted)]/60 cursor-pointer transition-colors"
                            onClick={() => setExpandedId(expandedId === (inst.access_token || inst.profile) ? null : (inst.access_token || inst.profile))}
                          >
                            <Checkbox
                              className="size-4 shrink-0"
                              checked={selectedIds.includes(inst.access_token || inst.profile)}
                              onClick={(e) => e.stopPropagation()}
                              onCheckedChange={(checked) => {
                                const id = inst.access_token || inst.profile;
                                if (checked) setSelectedIds((prev) => [...prev, id]);
                                else setSelectedIds((prev) => prev.filter((x) => x !== id));
                              }}
                            />
                            <span
                              className={cn(
                                "shrink-0 inline-flex items-center justify-center min-w-[28px] h-5 px-1.5 rounded-md text-[11px] font-mono font-bold tabular-nums",
                                inst.is_primary
                                  ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300"
                                  : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                              )}
                              title={inst.is_primary ? `${tagLabel} ưu tiên #1` : `Vị trí #${inst.ordinal}`}
                            >
                              #{inst.ordinal}
                            </span>
                            <div className={cn("size-8 shrink-0 rounded-full flex items-center justify-center", statusColor)}>
                              <span className="text-[10px] font-bold text-white">{initials}</span>
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex flex-col gap-1">
                                <div className="flex items-center gap-1.5">
                                  <span className="text-[13px] font-semibold text-[var(--foreground)] truncate max-w-[180px]">{inst.label || inst.profile}</span>
                                  <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-amber-50 text-amber-700 border border-amber-200">
                                    {tagLabel}
                                  </Badge>
                                  {inst.plan && (
                                    <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-amber-50 text-amber-700 border border-amber-200">
                                      {inst.plan}
                                    </Badge>
                                  )}
                                  <span className={cn(
                                    "inline-flex items-center gap-0.5 rounded text-[10px] px-1 py-0",
                                    !isFlowConfigured ? "bg-[var(--secondary)] text-[var(--muted-foreground)] border border-[var(--border)]"
                                    : wbStatus === "active" ? "bg-emerald-500/10 text-emerald-600"
                                    : wbStatus === "error" ? "bg-rose-500/10 text-rose-500"
                                    : "bg-amber-500/10 text-amber-600"
                                  )}>
                                    {isFlowConfigured && (
                                      <span className={cn("size-1.5 rounded-full",
                                        wbStatus === "active" ? "bg-emerald-400"
                                        : wbStatus === "error" ? "bg-rose-400"
                                        : "bg-amber-400"
                                      )} />
                                    )}
                                    {isFlowConfigured ? translateStatus(wbStatus, lang) : "disabled"}
                                  </span>
                                </div>
                                {(wbExhausted.length > 0 || inst.notes) && (
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    {wbExhausted.map(f => (
                                      <Badge key={`wb-ex-${f}`} variant="secondary" className="rounded text-[9px] px-1 py-0 bg-rose-50 text-rose-500 border border-rose-100 font-medium">
                                        Hết {f}
                                      </Badge>
                                    ))}
                                    {inst.notes ? (
                                      <span className="text-[10px] italic text-[var(--muted-foreground)] truncate max-w-[200px]" title={inst.notes}>{inst.notes}</span>
                                    ) : null}
                                  </div>
                                )}
                              </div>
                            </div>
                            <div className="hidden sm:flex items-center gap-2 text-[11px]">
                              <span className="text-emerald-600">{inst.success ?? 0}✓</span>
                              <span className="text-rose-400">{inst.fail ?? 0}✗</span>
                            </div>
                            <div className="flex items-center gap-1 text-[var(--muted-foreground)]" onClick={(e) => e.stopPropagation()}>
                              <button
                                className="rounded p-0.5 hover:bg-amber-50 hover:text-amber-600"
                                onClick={() => void mutateProviderAccounts(providerKey, inst.profile, "toggle")}
                                title={!isFlowConfigured ? "Kích hoạt" : "Vô hiệu hóa"}
                              >
                                {!isFlowConfigured ? <Power className="size-3" /> : <PowerOff className="size-3" />}
                              </button>
                              <button
                                className="rounded p-0.5 hover:bg-rose-50 hover:text-rose-500"
                                onClick={() => void mutateProviderAccounts(providerKey, inst.profile, "delete")}
                                title="Xóa"
                              >
                                <Trash2 className="size-3" />
                              </button>
                            </div>
                          </div>
                          {expandedId === (inst.access_token || inst.profile) && renderWebAccountDetail(inst)}
                        </div>
                        );
                      })}

                      {/* Claude Web account rows — reads from account_service pool (type=claude).
                          Each account shows ordinal #, status, email, quota badges, success/fail,
                          and a delete action — same UX as ChatGPT Free accounts. */}
                      {provider.type === "claude" && (
                        provider.instances && provider.instances.length > 0 ? (
                          provider.instances.map((inst: any) => {
                            const clStatus = inst.status || "active";
                            const statusColor =
                              clStatus === "active" ? "bg-gradient-to-br from-orange-500 to-amber-600"
                              : clStatus === "error" ? "bg-gradient-to-br from-rose-500 to-red-600"
                              : clStatus === "limited" ? "bg-gradient-to-br from-amber-400 to-orange-500"
                              : "bg-[var(--secondary)]";

                            // Quota exhausted badges
                            const clExhausted: string[] = [];
                            if (inst.last_image_failed_at) {
                              const at = inst.last_image_failed_at.split(" ")[1] || "gần đây";
                              clExhausted.push(`Gửi ảnh lúc ${at}`);
                            }
                            if (inst.last_analysis_failed_at) {
                              const at = inst.last_analysis_failed_at.split(" ")[1] || "gần đây";
                              clExhausted.push(`Phân tích DL lúc ${at}`);
                            }
                            if (inst.last_quota_exhausted === "text_limit" && inst.last_quota_exhausted_at) {
                              const at = inst.last_quota_exhausted_at.split(" ")[1] || "gần đây";
                              clExhausted.push(`Text lúc ${at}`);
                            }

                            return (
                            <div key={`claude:${inst.access_token || inst.ordinal}`}>
                              <div
                                className="flex items-center gap-3 px-5 py-3 hover:bg-[var(--muted)]/60 cursor-pointer transition-colors"
                                onClick={() => setExpandedId(expandedId === inst.access_token ? null : inst.access_token)}
                              >
                                <Checkbox
                                  className="size-4 shrink-0"
                                  checked={selectedIds.includes(inst.access_token)}
                                  onClick={(e) => e.stopPropagation()}
                                  onCheckedChange={(checked) => {
                                    if (checked) setSelectedIds((prev) => [...prev, inst.access_token]);
                                    else setSelectedIds((prev) => prev.filter((x) => x !== inst.access_token));
                                  }}
                                />
                                {/* Ordinal badge */}
                                <span
                                  className={cn(
                                    "shrink-0 inline-flex items-center justify-center min-w-[28px] h-5 px-1.5 rounded-md text-[11px] font-mono font-bold tabular-nums",
                                    inst.is_primary
                                      ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300"
                                      : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                                  )}
                                  title={inst.is_primary ? "Claude ưu tiên #1" : `Vị trí #${inst.ordinal} trong hàng đợi`}
                                >
                                  #{inst.ordinal}
                                </span>
                                {/* Avatar */}
                                <div className={cn("size-8 shrink-0 rounded-full flex items-center justify-center", statusColor)}>
                                  <span className="text-[10px] font-bold text-white">CL</span>
                                </div>
                                {/* Info */}
                                <div className="flex-1 min-w-0">
                                  <div className="flex flex-col gap-1">
                                    <div className="flex items-center gap-1.5">
                                      <span className="text-[13px] font-semibold text-[var(--foreground)] truncate max-w-[180px]">
                                        {inst.label || inst.email || `Account #${inst.ordinal}`}
                                      </span>
                                      <Badge variant="secondary" className="rounded text-[10px] px-1 py-0 bg-orange-50 text-orange-700 border border-orange-200">
                                        Claude
                                      </Badge>
                                      <span className={cn(
                                        "inline-flex items-center gap-0.5 rounded text-[10px] px-1 py-0",
                                        clStatus === "active" ? "bg-emerald-500/10 text-emerald-600"
                                        : clStatus === "error" ? "bg-rose-500/10 text-rose-500"
                                        : "bg-amber-500/10 text-amber-600"
                                      )}>
                                        <span className={cn("size-1.5 rounded-full",
                                          clStatus === "active" ? "bg-emerald-400"
                                          : clStatus === "error" ? "bg-rose-400"
                                          : "bg-amber-400"
                                        )} />
                                        {translateStatus(clStatus, lang)}
                                      </span>
                                    </div>
                                    {(clExhausted.length > 0 || inst.notes) && (
                                      <div className="flex flex-wrap items-center gap-1.5">
                                        {clExhausted.map(f => (
                                          <Badge key={`cl-ex-${f}`} variant="secondary" className="rounded text-[9px] px-1 py-0 bg-rose-50 text-rose-500 border border-rose-100 font-medium">
                                            Hết {f}
                                          </Badge>
                                        ))}
                                        {inst.notes ? (
                                          <span className="text-[10px] italic text-[var(--muted-foreground)] truncate max-w-[200px]" title={inst.notes}>{inst.notes}</span>
                                        ) : null}
                                      </div>
                                    )}
                                  </div>
                                </div>
                                {/* Success / fail */}
                                <div className="hidden sm:flex items-center gap-2 text-[11px]">
                                  <span className="text-emerald-600">{inst.success ?? 0}✓</span>
                                  <span className="text-rose-400">{inst.fail ?? 0}✗</span>
                                </div>
                                {/* Actions */}
                                <div className="flex items-center gap-1 text-[var(--muted-foreground)]" onClick={(e) => e.stopPropagation()}>
                                  <button
                                    className="rounded p-0.5 hover:bg-rose-50 hover:text-rose-500"
                                    onClick={() => void handleDeleteTokens([inst.access_token])}
                                    title="Xóa"
                                  >
                                    <Trash2 className="size-3" />
                                  </button>
                                </div>
                              </div>
                              {expandedId === inst.access_token && renderWebAccountDetail(inst)}
                            </div>
                            );
                          })
                        ) : (
                          <div className="flex items-center gap-3 px-5 py-4 text-[13px] text-[var(--muted-foreground)]">
                            <Bot className="size-4 text-[var(--muted-foreground)]" />
                            <span>Chưa có tài khoản Claude.</span>
                            <span className="text-[12px] text-[var(--muted-foreground)]">Thêm tài khoản qua nút "Thêm" bên trên với type = <code className="bg-[var(--secondary)] px-1 rounded">claude</code></span>
                          </div>
                        )
                      )}

                      {/* Providers / Custom APIs: rows like ChatGPT accounts */}
                      {(provider.type === "providers" || provider.type === "custom") && provider.instances?.map((inst: any) => {
                        const isInstOpen = expandedId === `inst:${inst.id}`;
                        const instStatusLabel = inst.status === "available" ? "active" : inst.status === "offline" ? "error" : inst.status === "configured" ? "active" : "limited";
                        const instStatusColor = inst.status === "available" ? "bg-gradient-to-br from-[#D4AF37] to-[#B8860B]" :
                          inst.status === "offline" ? "bg-gradient-to-br from-rose-500 to-red-600" :
                          inst.status === "configured" ? "bg-gradient-to-br from-sky-500 to-cyan-600" : "bg-[var(--secondary)]";
                        return (
                        <div key={inst.id}>
                          {/* Collapsed row — like ChatGPT account row */}
                          <div
                            className={cn(
                              "flex items-center gap-3 px-5 py-3 cursor-pointer transition-colors",
                              isInstOpen ? "bg-amber-50/60" : "hover:bg-[var(--muted)]/60"
                            )}
                            onClick={() => setExpandedId(isInstOpen ? null : `inst:${inst.id}`)}
                          >
                            <div className={cn("size-8 shrink-0 rounded-full flex items-center justify-center", instStatusColor)}>
                              <Server className="size-3.5 text-white" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="text-[13px] font-semibold text-[var(--foreground)] truncate">{inst.name}</span>
                                <span className={cn(
                                  "inline-flex items-center gap-1 rounded-md text-[10px] px-1.5 py-0",
                                  inst.status === "available" ? "bg-emerald-500/10 text-emerald-600" :
                                  inst.status === "offline" ? "bg-rose-500/10 text-rose-500" :
                                  "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                                )}>
                                  {inst.status}
                                </span>
                              </div>
                              <div className="flex items-center gap-2 mt-0.5">
                                {inst.prefix && <code className="text-[10px] text-[var(--muted-foreground)]">{inst.prefix}/</code>}
                                {inst.port && inst.port !== "—" && <span className="text-[10px] text-[var(--muted-foreground)]">:{inst.port}</span>}
                                {inst.base_url && <span className="text-[10px] text-[var(--muted-foreground)] truncate max-w-[250px]">{inst.base_url}</span>}
                              </div>
                            </div>
                            <div className="hidden sm:flex items-center gap-3 text-[11px]">
                              {(inst.endpoint_count ?? 0) > 1 && (
                                <span
                                  className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-emerald-700 ring-1 ring-emerald-200 font-mono font-semibold"
                                  title={`${inst.endpoint_count} endpoints pool — click row để xem chi tiết + ordinal`}
                                >
                                  ×{inst.endpoint_count}
                                </span>
                              )}
                              {inst.models > 0 && <span className="text-[var(--muted-foreground)]">{inst.models} models</span>}
                              {inst.clients > 0 && <span className="text-sky-600">{inst.clients} clients</span>}
                            </div>
                            <div className="flex items-center gap-1 text-[var(--muted-foreground)]" onClick={e => e.stopPropagation()}>
                              {inst.error && <span className="text-[10px] text-rose-400 max-w-[120px] truncate">{inst.error}</span>}
                            </div>
                          </div>

                          {/* Expanded detail panel — same style as ChatGPT accounts */}
                          {isInstOpen && (
                            <div className="border-t border-amber-100 bg-[var(--muted)]/60 px-5 py-4">
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                {/* Connection info card */}
                                <div className="rounded-[12px] p-4 card-3d card-tint-emerald space-y-3">
                                  <div className="flex items-center justify-between">
                                    <div>
                                      <p className="text-[13px] font-bold text-[var(--foreground)]">{inst.name}</p>
                                      <div className="flex items-center gap-2 mt-0.5">
                                        <span className={cn(
                                          "inline-flex items-center gap-0.5 rounded text-[10px] px-1.5 py-0",
                                          inst.status === "available" ? "bg-emerald-500/10 text-emerald-600" :
                                          inst.status === "offline" ? "bg-rose-500/10 text-rose-500" :
                                          "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                                        )}>
                                          <span className={cn("size-1.5 rounded-full",
                                            inst.status === "available" ? "bg-emerald-400" :
                                            inst.status === "offline" ? "bg-rose-400" : "bg-[var(--secondary)]"
                                          )} />
                                          {inst.status}
                                        </span>
                                        {inst.prefix && <code className="text-[10px] text-[var(--muted-foreground)] bg-[var(--secondary)] rounded px-1">{inst.prefix}/</code>}
                                      </div>
                                    </div>
                                  </div>

                                  <div className="space-y-2 text-[12px]">
                                    <div className="flex items-center gap-1.5">
                                      <span className="size-2 rounded-full bg-amber-500" />
                                      <span className="text-[var(--muted-foreground)]">Base URL</span>
                                      <span className="ml-auto text-[11px] text-[var(--foreground)] font-mono truncate max-w-[180px]">{inst.base_url || "—"}</span>
                                    </div>
                                    <div className="flex items-center gap-1.5">
                                      <span className="size-2 rounded-full bg-sky-500" />
                                      <span className="text-[var(--muted-foreground)]">Port</span>
                                      <span className="ml-auto text-[11px] font-bold text-[var(--foreground)]">{inst.port || "—"}</span>
                                    </div>
                                    {inst.has_key !== undefined && !inst.keys?.length && (
                                      <div className="flex items-center gap-1.5">
                                        <span className="size-2 rounded-full bg-violet-500" />
                                        <span className="text-[var(--muted-foreground)]">API Key</span>
                                        <span className="ml-auto text-[11px] text-[var(--muted-foreground)]">{inst.has_key ? inst.key_preview : "Chưa có key"}</span>
                                      </div>
                                    )}
                                  </div>

                                  {/* Multi-key listing with ordinals — Gemini /
                                      NVIDIA / OpenAI / DeepSeek frequently have
                                      multiple API keys with FIFO rotation. Show
                                      #1 (primary, emerald) through #N. */}
                                  {Array.isArray(inst.keys) && inst.keys.length > 0 && (
                                    <div className="pt-2 border-t border-[var(--border)] space-y-1">
                                      <div className="flex items-center justify-between">
                                        <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">API Keys</span>
                                        <span className="text-[10px] text-[var(--muted-foreground)]">{inst.keys.length} key{inst.keys.length > 1 ? "s" : ""}</span>
                                      </div>
                                      {inst.keys.map((k: any, ki: number) => (
                                        <div key={ki} className="flex items-center gap-2 text-[11px]">
                                          <span
                                            className={cn(
                                              "shrink-0 inline-flex items-center justify-center min-w-[28px] h-5 px-1.5 rounded-md font-mono font-bold tabular-nums",
                                              k.is_primary
                                                ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300"
                                                : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                                            )}
                                            title={k.is_primary ? "Key ưu tiên #1 — luôn được dùng trước" : `Vị trí #${k.ordinal} trong hàng đợi`}
                                          >
                                            #{k.ordinal}
                                          </span>
                                          <code className="text-[var(--muted-foreground)] font-mono truncate">{k.preview}</code>
                                        </div>
                                      ))}
                                    </div>
                                  )}

                                  {Array.isArray(inst.endpoints) && inst.endpoints.length > 1 && (
                                    <div className="pt-2 border-t border-[var(--border)] space-y-1">
                                      <div className="flex items-center justify-between">
                                        <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">Endpoints (multi-pool)</span>
                                        <span className="text-[10px] text-[var(--muted-foreground)]">{inst.endpoints.length} URLs</span>
                                      </div>
                                      {inst.endpoints.map((ep: any, ei: number) => (
                                        <div key={ei} className="flex items-center gap-2 text-[11px]">
                                          <span
                                            className={cn(
                                              "shrink-0 inline-flex items-center justify-center min-w-[28px] h-5 px-1.5 rounded-md font-mono font-bold tabular-nums",
                                              ep.is_primary
                                                ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300"
                                                : "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                                            )}
                                            title={ep.is_primary ? "Endpoint ưu tiên #1 — try first" : `Vị trí #${ep.ordinal} trong rotation`}
                                          >
                                            #{ep.ordinal}
                                          </span>
                                          <code className="text-[var(--muted-foreground)] font-mono truncate">{ep.url}</code>
                                        </div>
                                      ))}
                                    </div>
                                  )}

                                  {inst.error && (
                                    <div className="rounded-[8px] bg-rose-50 border border-rose-100 px-3 py-2 text-[11px]">
                                      <p className="font-medium text-rose-700">Lỗi kết nối</p>
                                      <p className="text-rose-500 break-all">{inst.error}</p>
                                    </div>
                                  )}
                                </div>

                                {/* Metrics card */}
                                <div className="rounded-[12px] p-4 card-3d card-tint-sky space-y-3">
                                  <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">Số liệu hoạt động</p>
                                  <div className="space-y-3">
                                    <div className="space-y-1.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-1.5">
                                          <span className="size-2 rounded-full bg-emerald-500" />
                                          <span className="text-[11px] text-[var(--muted-foreground)]">Models</span>
                                        </div>
                                        <span className="text-[11px] font-bold text-emerald-600">{inst.models || 0}</span>
                                      </div>
                                      {(inst.models || 0) > 0 && (
                                        <div className="h-1.5 w-full rounded-full bg-[var(--secondary)] overflow-hidden">
                                          <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.min(100, (inst.models || 0) * 10)}%` }} />
                                        </div>
                                      )}
                                    </div>
                                    <div className="space-y-1.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-1.5">
                                          <span className="size-2 rounded-full bg-sky-500" />
                                          <span className="text-[11px] text-[var(--muted-foreground)]">Clients</span>
                                        </div>
                                        <span className="text-[11px] font-bold text-sky-600">{inst.clients || 0}</span>
                                      </div>
                                      {(inst.clients || 0) > 0 && (
                                        <div className="h-1.5 w-full rounded-full bg-[var(--secondary)] overflow-hidden">
                                          <div className="h-full bg-sky-500 rounded-full" style={{ width: `${Math.min(100, (inst.clients || 0) * 20)}%` }} />
                                        </div>
                                      )}
                                    </div>
                                    <div className="space-y-1.5">
                                      <div className="flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-1.5">
                                          <span className="size-2 rounded-full bg-violet-500" />
                                          <span className="text-[11px] text-[var(--muted-foreground)]">Entries</span>
                                        </div>
                                        <span className="text-[11px] font-bold text-violet-600">{inst.entries || 0}</span>
                                      </div>
                                      {(inst.entries || 0) > 0 && (
                                        <div className="h-1.5 w-full rounded-full bg-[var(--secondary)] overflow-hidden">
                                          <div className="h-full bg-violet-500 rounded-full" style={{ width: `${Math.min(100, (inst.entries || 0) * 2)}%` }} />
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </div>
                                {/* Per-key status card */}
                                {inst.keys && inst.keys.length > 0 && (
                                  <div className="rounded-[12px] p-4 card-3d card-tint-indigo space-y-3 md:col-span-2">
                                    <div className="flex items-center justify-between">
                                      <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--muted-foreground)]">
                                        API Keys ({inst.available_keys}/{inst.total_keys} active)
                                      </p>
                                    </div>
                                    <div className="space-y-1.5">
                                      {inst.keys.map((keyInfo: any, ki: number) => (
                                        <div key={ki} className="flex items-center gap-3 rounded-[8px] bg-[var(--card)]/60 px-3 py-2">
                                          <span className={cn("size-2 rounded-full shrink-0",
                                            keyInfo.status === "available" ? "bg-emerald-500" :
                                            keyInfo.status === "auth_error" ? "bg-rose-500" :
                                            keyInfo.status === "rate_limited" ? "bg-amber-500" :
                                            keyInfo.status === "network_error" ? "bg-rose-400" :
                                            "bg-[var(--secondary)]"
                                          )} />
                                          <code className="text-[11px] text-[var(--muted-foreground)] flex-1">{keyInfo.key_preview}</code>
                                          <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded",
                                            keyInfo.status === "available" ? "bg-emerald-500/10 text-emerald-600" :
                                            keyInfo.status === "auth_error" ? "bg-rose-500/10 text-rose-500" :
                                            keyInfo.status === "rate_limited" ? "bg-amber-500/10 text-amber-600" :
                                            "bg-[var(--secondary)] text-[var(--muted-foreground)]"
                                          )}>
                                            {keyInfo.status}
                                          </span>
                                          {keyInfo.models > 0 && <span className="text-[10px] text-[var(--muted-foreground)]">{keyInfo.models} models</span>}
                                          {keyInfo.error && <span className="text-[10px] text-rose-400 max-w-[140px] truncate">{keyInfo.error}</span>}
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
            {mergedTree.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center card-3d card-tint-slate rounded-[16px]">
                <Search className="size-5 text-[var(--muted-foreground)]" />
                <p className="text-sm text-[var(--muted-foreground)]">Chưa có dữ liệu provider nào</p>
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
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return <AccountsPageContent />;
}
