const fs = require('fs');
const path = require('path');

const filePath = path.join(__dirname, 'src', 'app', 'accounts', 'page.tsx');
let content = fs.readFileSync(filePath, 'utf8');

function repl(old, newStr) {
    content = content.split(old).join(newStr);
}

// 1. Types and Constants updates
repl('const accountStatusOptions: { label: string; value: AccountStatus | "all" }[] = [', 'const accountStatusOptions: { labelKey: TranslationKey; value: AccountStatus | "all" }[] = [');
repl('{ label: "Tất cả trạng thái", value: "all" },', '{ labelKey: "allStatus", value: "all" },');
repl('{ label: "Bình thường", value: "正常" },', '{ labelKey: "status_normal", value: "正常" },');
repl('{ label: "Giới hạn", value: "限流" },', '{ labelKey: "status_limited", value: "限流" },');
repl('{ label: "Lỗi", value: "异常" },', '{ labelKey: "status_error", value: "异常" },');
repl('{ label: "Vô hiệu hóa", value: "禁用" },', '{ labelKey: "status_disabled", value: "禁用" },');

repl('key: "total", label: "Tổng tài khoản", icon: UserRound,', 'key: "total", labelKey: "totalAccounts" as TranslationKey, icon: UserRound,');
repl('key: "active", label: "Hoạt động", icon: CheckCircle2,', 'key: "active", labelKey: "active" as TranslationKey, icon: CheckCircle2,');
repl('key: "limited", label: "Bị giới hạn", icon: CircleAlert,', 'key: "limited", labelKey: "limited" as TranslationKey, icon: CircleAlert,');
repl('key: "abnormal", label: "Bị lỗi", icon: CircleOff,', 'key: "abnormal", labelKey: "abnormal" as TranslationKey, icon: CircleOff,');
repl('key: "disabled", label: "Đã vô hiệu", icon: Ban,', 'key: "disabled", labelKey: "disabled" as TranslationKey, icon: Ban,');
repl('key: "quota", label: "Hạn mức còn lại", icon: RefreshCw,', 'key: "quota", labelKey: "quotaRemaining" as TranslationKey, icon: RefreshCw,');

// 2. Component Logic and Imports
// Make sure imports are correct (already have useLangStore and i18n from previous turn's view)
if (!content.includes('import { useLangStore } from "@/store/lang";')) {
    content = content.replace('import { cn } from "@/lib/utils";', 'import { cn } from "@/lib/utils";\nimport { useLangStore } from "@/store/lang";\nimport { translations, TranslationKey } from "@/lib/i18n";');
}

if (!content.includes('const { lang, setLang } = useLangStore();')) {
    content = content.replace('function AccountsPageContent() {', 'function AccountsPageContent() {\n  const { lang, setLang } = useLangStore();\n  const t = (key: TranslationKey) => translations[lang][key] || key;');
}

// 3. JSX Content
repl('<h1 className="text-[26px] font-bold tracking-tight text-slate-900">Quản lý tài khoản</h1>', '<h1 className="text-[26px] font-bold tracking-tight text-slate-900">{t("title")}</h1>');
repl('<p className="text-[14px] text-slate-500 mt-0.5">Quản lý token và trạng thái tài khoản ChatGPT</p>', '<p className="text-[14px] text-slate-500 mt-0.5">{t("subtitle")}</p>');
repl('placeholder="Tìm kiếm Email"', 'placeholder={t("searchPlaceholder")}');
repl('>{option.label}<', '>{t(option.labelKey)}<');
repl('>{item.label}</p>', '>{t(item.labelKey)}</p>');

repl('Làm mới tài khoản đã chọn', '{t("refreshSelected")}');
repl('Xóa tài khoản lỗi', '{t("deleteError")}');
repl('Xóa mục đã chọn', '{t("deleteSelected")}');
repl('Đã chọn {selectedIds.length} mục', '{t("selectedCount").replace("{count}", String(selectedIds.length))}');

repl('<DialogTitle>Sửa tài khoản</DialogTitle>', '<DialogTitle>{t("editStatus")}</DialogTitle>');
repl('Thay đổi trạng thái tài khoản thủ công.', '{t("editStatusDesc")}');
repl('<label className="text-sm font-medium text-stone-700">Trạng thái</label>', '<label className="text-sm font-medium text-stone-700">{t("status")}</label>');
repl('Hủy\n            </Button>', '{t("cancel")}\n            </Button>');
repl('Lưu thay đổi\n            </Button>', '{t("saveChanges")}\n            </Button>');

repl('<h2 className="text-lg font-semibold tracking-tight">Danh sách tài khoản</h2>', '<h2 className="text-lg font-semibold tracking-tight">{t("title")}</h2>');
repl('Đang tải tài khoản', '{t("loadingAccounts")}');
repl('Đang đồng bộ danh sách và trạng thái từ backend.', '{t("syncingAccounts")}');

repl('<span>Tài khoản</span>', '<span>{t("account")}</span>');
repl('<span>Loại · Trạng thái</span>', '<span>{t("typeStatus")}</span>');
repl('<span>Hạn mức ảnh</span>', '<span>{t("imageQuota")}</span>');
repl('<span>Thời gian dùng gần nhất</span>', '<span>{t("lastUsed")}</span>');
repl('<span>Yêu cầu</span>', '<span>{t("requests")}</span>');
repl('<span className="w-24">Hành động</span>', '<span className="w-24">{t("actions")}</span>');

repl('Làm mới\n          </Button>', '{t("refresh")}\n          </Button>');
repl('Làm mới tất cả\n          </Button>', '{t("refreshAll")}\n          </Button>');
repl('Xuất Token\n          </Button>', '{t("exportTokens")}\n          </Button>');

repl('Tất cả các loại', '{t("allTypes")}');
repl('t.relative', 'formatRestoreAt(account.restore_at, lang).relative'); // fixing any missed calls

fs.writeFileSync(filePath, content, 'utf8');
console.log('Successfully updated accounts page with i18n!');
