import fs from 'fs';

const path = 'd:/Chatgpt/chatgpt2api/chatgpt2api-1/web/src/app/accounts/page.tsx';
let content = fs.readFileSync(path, 'utf8');

// Add imports
content = content.replace(
  'import { cn } from "@/lib/utils";',
  'import { cn } from "@/lib/utils";\nimport { useLangStore } from "@/store/lang";\nimport { translations, TranslationKey } from "@/lib/i18n";'
);

// We need to use `const { lang, setLang } = useLangStore();` in AccountsPageContent
content = content.replace(
  'function AccountsPageContent() {',
  'function AccountsPageContent() {\n  const { lang, setLang } = useLangStore();\n  const t = (key: TranslationKey) => translations[lang][key] || key;'
);

// We should replace some strings in AccountsPageContent
const replacements = [
  ['"Danh sách tài khoản"', 't("title")'],
  ['"Quản lý và giám sát trạng thái tài khoản hệ thống"', 't("subtitle")'],
  ['"Tất cả trạng thái"', 't("allStatus")'],
  ['"Làm mới danh sách"', 't("refreshList")'],
  ['"Nhập token"', 't("importTokens")'],
  ['"Tài khoản"', 't("account")'],
  ['"Loại · Trạng thái"', 't("typeStatus")'],
  ['"Sửa trạng thái"', 't("editStatus")'],
  ['"Xóa"', 't("delete")'],
  ['"Hạn mức ảnh"', 't("imageQuota")'],
  ['"Không có tài khoản nào phù hợp"', 't("noMatches")'],
  ['"Thử điều chỉnh bộ lọc hoặc từ khóa tìm kiếm."', 't("tryAdjusting")'],
  ['"Yêu cầu"', 't("requests")'],
  ['"Thành công"', 't("success")'],
  ['"Thất bại"', 't("fail")'],
  ['"Dùng lần cuối"', 't("lastUsed")'],
  ['"Phục hồi lúc"', 't("restoreAt")'],
  ['"Chi tiết giới hạn"', 't("limitDetails")'],
  ['"Hành động"', 't("actions")'],
  ['"Thời gian"', 't("lastUsed")'], // approximations
  ['"Sao chép Token"', 't("copyToken")'],
  ['"Làm mới"', 't("refresh")'],
  ['"Chỉnh sửa trạng thái"', 't("editStatus")'],
  ['"Hiển thị "', 't("showing") + " "'],
  ['" mục"', '" " + t("items")'],
  ['"Tìm theo ID hoặc Email..."', 't("searchPlaceholder")'],
  ['"Tổng tài khoản"', 't("totalAccounts")'],
  ['"Hoạt động"', 't("active")'],
  ['"Bị giới hạn"', 't("limited")'],
  ['"Bị lỗi"', 't("abnormal")'],
  ['"Đã vô hiệu"', 't("disabled")'],
  ['"Hạn mức còn lại"', 't("quotaRemaining")'],
];

for (const [vn, en] of replacements) {
  // Be careful with exact matches, we use global replace where possible
  // We'll just replace instances that are likely text nodes or props
  content = content.split(vn).join(`{${en}}`);
  // For props that were string literals e.g. placeholder="Tìm theo..."
  // content = content.split(`="${vn.replace(/"/g, '')}"`).join(`={${en}}`);
}

// Special case for placeholder
content = content.replace(/placeholder=\{t\("searchPlaceholder"\)\}/g, 'placeholder={t("searchPlaceholder")}');
content = content.replace(/placeholder="\{t\("searchPlaceholder"\)\}"/g, 'placeholder={t("searchPlaceholder")}');

// Fix the feature names inside limits_progress map:
content = content.replace(
  'label={lp.feature_name ?? `Limit ${i + 1}`}',
  'label={t(lp.feature_name as TranslationKey) ?? lp.feature_name ?? `Limit ${i + 1}`}'
);

// Let's add the Language Toggle button next to Import Tokens
const importBtnStr = '<AccountImportDialog onImportSuccess={loadAccounts} />';
const toggleBtnStr = `
          <Button
            variant="outline"
            className="rounded-xl border-stone-200 bg-white"
            onClick={() => setLang(lang === "vi" ? "en" : "vi")}
          >
            {lang === "vi" ? "🇬🇧 EN" : "🇻🇳 VI"}
          </Button>
          <AccountImportDialog onImportSuccess={loadAccounts} />
`;
content = content.replace(importBtnStr, toggleBtnStr);

// To translate AccountStatusOptions and MetricCards safely, we might need to do it dynamically inside the component.
// But since they are defined outside, let's just leave them or modify the render.
// In the render:
content = content.replace(
  '{accountStatusOptions.map((opt) => (',
  '{accountStatusOptions.map((opt) => (\n                    <SelectItem key={opt.value} value={opt.value}>\n                      {opt.value === "all" ? t("allStatus") : t(`status_${opt.value === "正常" ? "normal" : opt.value === "限流" ? "limited" : opt.value === "异常" ? "error" : "disabled"}`)}\n                    </SelectItem>\n                  ))}\n                  {/* '
);
content = content.replace('</SelectItem>\n                  ))}', '</SelectItem>\n                  ))} */');

// Metric cards render:
content = content.replace(
  '<p className="truncate text-sm font-medium">{card.label}</p>',
  '<p className="truncate text-sm font-medium">{t(card.key as TranslationKey) || card.label}</p>'
);

// Account status in the table (translateStatus function is already there, but we need to update it or use `t`)
// We'll just use `translateStatus` as is, but we can update it to use `lang`.
// Since translateStatus is outside, let's pass `lang` to it.
content = content.replace('function translateStatus(status: string) {', 'function translateStatus(status: string, lang: "vi" | "en") {\n  const t = translations[lang];');
content = content.replace('case "正常": return "Bình thường";', 'case "正常": return t.status_normal;');
content = content.replace('case "限流": return "Giới hạn";', 'case "限流": return t.status_limited;');
content = content.replace('case "异常": return "Lỗi";', 'case "异常": return t.status_error;');
content = content.replace('case "禁用": return "Vô hiệu";', 'case "禁用": return t.status_disabled;');

content = content.replace(/translateStatus\(account\.status\)/g, 'translateStatus(account.status, lang)');

// formatRelativeTime and formatRestoreAt
content = content.replace('function formatRelativeTime(value?: string | null): string {', 'function formatRelativeTime(value: string | null | undefined, lang: "vi" | "en"): string {\n  const t = translations[lang];');
content = content.replace('return "Vừa xong";', 'return t.justNow;');
content = content.replace('return `${mins} phút trước`;', 'return `${mins} ${t.minsAgo}`;');
content = content.replace('return `${hrs} giờ trước`;', 'return `${hrs} ${t.hrsAgo}`;');
content = content.replace('return `${Math.floor(hrs / 24)} ngày trước`;', 'return `${Math.floor(hrs / 24)} ${t.daysAgo}`;');

content = content.replace('function formatRestoreAt(value?: string | null) {', 'function formatRestoreAt(value: string | null | undefined, lang: "vi" | "en") {\n  const t = translations[lang];');
content = content.replace('const relative = diffMs > 0 ? `Còn ${days}d ${hours}h` : "Đã đến lúc phục hồi";', 'const relative = diffMs > 0 ? `${t.restoreIn} ${days}d ${hours}h` : t.readyToRestore;');

// Update their calls
content = content.replace(/formatRelativeTime\(account\.last_used_at\)/g, 'formatRelativeTime(account.last_used_at, lang)');
content = content.replace(/formatRestoreAt\(account\.restore_at\)\.relative/g, 'formatRestoreAt(account.restore_at, lang).relative');
content = content.replace(/formatRestoreAt\(account\.restore_at\)\.absolute/g, 'formatRestoreAt(account.restore_at, lang).absolute');
content = content.replace(/formatRestoreAt\(lp\.reset_after\)\.relative/g, 'formatRestoreAt(lp.reset_after, lang).relative');


fs.writeFileSync(path, content, 'utf8');
console.log('Done rewriting accounts page');
