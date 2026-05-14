import re

path = r"d:\Chatgpt\chatgpt2api\chatgpt2api-1\web\src\app\accounts\page.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

def repl(old, new):
    global content
    content = content.replace(old, new)

repl('''const accountStatusOptions: { label: string; value: AccountStatus | "all" }[] = [
  { label: "Tất cả trạng thái", value: "all" },
  { label: "Bình thường", value: "正常" },
  { label: "Giới hạn", value: "限流" },
  { label: "Lỗi", value: "异常" },
  { label: "Vô hiệu hóa", value: "禁用" },
];''', '''const accountStatusOptions: { labelKey: TranslationKey; value: AccountStatus | "all" }[] = [
  { labelKey: "allStatus", value: "all" },
  { labelKey: "status_normal", value: "正常" },
  { labelKey: "status_limited", value: "限流" },
  { labelKey: "status_error", value: "异常" },
  { labelKey: "status_disabled", value: "禁用" },
];''')

repl('''const metricCards = [
  {
    key: "total", label: "Tổng tài khoản", icon: UserRound,
    gradient: "from-indigo-500 to-blue-600", shadow: "shadow-indigo-200",
    bg: "from-indigo-50/80 to-blue-50/80", textColor: "text-indigo-900", labelColor: "text-indigo-600",
  },
  {
    key: "active", label: "Hoạt động", icon: CheckCircle2,
    gradient: "from-emerald-500 to-teal-600", shadow: "shadow-emerald-200",
    bg: "from-emerald-50/80 to-teal-50/80", textColor: "text-emerald-900", labelColor: "text-emerald-600",
  },
  {
    key: "limited", label: "Bị giới hạn", icon: CircleAlert,
    gradient: "from-amber-500 to-orange-500", shadow: "shadow-amber-200",
    bg: "from-amber-50/80 to-orange-50/80", textColor: "text-amber-900", labelColor: "text-amber-600",
  },
  {
    key: "abnormal", label: "Bị lỗi", icon: CircleOff,
    gradient: "from-rose-500 to-red-600", shadow: "shadow-rose-200",
    bg: "from-rose-50/80 to-red-50/80", textColor: "text-rose-900", labelColor: "text-rose-600",
  },
  {
    key: "disabled", label: "Đã vô hiệu", icon: Ban,
    gradient: "from-slate-400 to-slate-500", shadow: "shadow-slate-200",
    bg: "from-slate-50/80 to-slate-100/80", textColor: "text-slate-700", labelColor: "text-slate-500",
  },
  {
    key: "quota", label: "Hạn mức còn lại", icon: RefreshCw,
    gradient: "from-sky-500 to-cyan-600", shadow: "shadow-sky-200",
    bg: "from-sky-50/80 to-cyan-50/80", textColor: "text-sky-900", labelColor: "text-sky-600",
  },
] as const;''', '''const metricCards = [
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
] as const;''')

repl('''<h1 className="text-[26px] font-bold tracking-tight text-slate-900">Quản lý tài khoản</h1>''', '''<h1 className="text-[26px] font-bold tracking-tight text-slate-900">{t("title")}</h1>''')
repl('''<p className="text-[14px] text-slate-500 mt-0.5">Quản lý token và trạng thái tài khoản ChatGPT</p>''', '''<p className="text-[14px] text-slate-500 mt-0.5">{t("subtitle")}</p>''')
repl('''<Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-500" />
              <Input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="Tìm kiếm Email"''', '''<Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-500" />
              <Input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder={t("searchPlaceholder")}''')

repl('>{option.label}<', '>{t(option.labelKey)}<')
repl('<p className={cn("text-[11px] font-semibold mb-1", item.labelColor)}>{item.label}</p>', '<p className={cn("text-[11px] font-semibold mb-1", item.labelColor)}>{t(item.labelKey)}</p>')

repl('Làm mới tài khoản đã chọn', '{t("refreshSelected")}')
repl('Xóa tài khoản lỗi', '{t("deleteError")}')
repl('Xóa mục đã chọn', '{t("deleteSelected")}')
repl('Đã chọn {selectedIds.length} mục', '{t("selectedCount").replace("{count}", String(selectedIds.length))}')

repl('''<DialogTitle>Sửa tài khoản</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              Thay đổi trạng thái tài khoản thủ công.
            </DialogDescription>''', '''<DialogTitle>{t("editStatus")}</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              {t("editStatusDesc")}
            </DialogDescription>''')

repl('''<label className="text-sm font-medium text-stone-700">Trạng thái</label>''', '''<label className="text-sm font-medium text-stone-700">{t("status")}</label>''')
repl('''Hủy\n            </Button>''', '''{t("cancel")}\n            </Button>''')
repl('''Lưu thay đổi\n            </Button>''', '''{t("saveChanges")}\n            </Button>''')

repl('''<h2 className="text-lg font-semibold tracking-tight">Danh sách tài khoản</h2>''', '''<h2 className="text-lg font-semibold tracking-tight">{t("title")}</h2>''')
repl('''<p className="text-sm font-medium text-stone-700">Đang tải tài khoản</p>
                <p className="text-sm text-stone-500">Đang đồng bộ danh sách và trạng thái từ backend.</p>''', '''<p className="text-sm font-medium text-stone-700">{t("loadingAccounts")}</p>
                <p className="text-sm text-stone-500">{t("syncingAccounts")}</p>''')

repl('''<span>Tài khoản</span>
                <span>Loại · Trạng thái</span>
                <span>Hạn mức ảnh</span>
                <span>Thời gian dùng gần nhất</span>
                <span>Yêu cầu</span>
                <span className="w-24">Hành động</span>''', '''<span>{t("account")}</span>
                <span>{t("typeStatus")}</span>
                <span>{t("imageQuota")}</span>
                <span>{t("lastUsed")}</span>
                <span>{t("requests")}</span>
                <span className="w-24">{t("actions")}</span>''')

# We need to make sure we replace the buttons properly
# button "Làm mới" inside the top row
repl('''<RefreshCw className={cn("size-4", isLoading ? "animate-spin" : "")} />
            Làm mới
          </Button>''', '''<RefreshCw className={cn("size-4", isLoading ? "animate-spin" : "")} />
            {t("refresh")}
          </Button>''')

repl('''<RefreshCw className={cn("size-4", isRefreshing ? "animate-spin" : "")} />
            Làm mới tất cả
          </Button>''', '''<RefreshCw className={cn("size-4", isRefreshing ? "animate-spin" : "")} />
            {t("refreshAll")}
          </Button>''')

repl('''<Download className="size-4" />
            Xuất Token
          </Button>''', '''<Download className="size-4" />
            {t("exportTokens")}
          </Button>''')

repl('Tất cả các loại', '{t("allTypes")}')
repl('Tải danh sách tài khoản thất bại', 't("fetchAccountsFailed")')
repl('Vui lòng chọn tài khoản muốn xóa', 't("selectAccountsToDelete")')
repl('Đã xóa ${data.removed ?? 0} tài khoản', '${t("deletedAccounts").replace("{count}", String(data.removed ?? 0))}')
repl('Xóa tài khoản thất bại', 't("deleteFailed")')

repl('Không có tài khoản nào cần làm mới', 't("noAccountsToRefresh")')
repl('Làm mới thành công ${data.refreshed}, thất bại ${data.errors.length}${firstError ? `，Lỗi đầu tiên: ${firstError}` : ""}', '${t("refreshPartial").replace("{success}", String(data.refreshed)).replace("{fail}", String(data.errors.length)).replace("{error}", firstError ? `, ${t("firstError")}: ${firstError}` : "")}')
repl('Làm mới thành công ${data.refreshed} tài khoản', '${t("refreshSuccess").replace("{count}", String(data.refreshed))}')
repl('Làm mới tài khoản thất bại', 't("refreshFailed")')
repl('Thông tin tài khoản đã được cập nhật', 't("updateSuccess")')
repl('Cập nhật tài khoản thất bại', 't("updateFailed")')

repl('Hiển thị', '{t("showing")}')
repl(' mục', ' {t("items")}')

# Find the language toggle we added previously and if it's not there, add it
if 'setLang(' not in content:
    repl('''<AccountImportDialog''', '''<Button
            variant="outline"
            className="h-10 rounded-[12px] border-black/[0.08] bg-white px-4 text-slate-600 shadow-sm hover:bg-slate-50"
            onClick={() => setLang(lang === "vi" ? "en" : "vi")}
          >
            {lang === "vi" ? "🇬🇧 EN" : "🇻🇳 VI"}
          </Button>
          <AccountImportDialog''')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Updated page.tsx")
