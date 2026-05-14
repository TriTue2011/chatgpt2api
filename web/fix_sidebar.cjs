const fs = require('fs');
const path = require('path');

const filePath = path.join(__dirname, 'src', 'components', 'sidebar.tsx');
let content = fs.readFileSync(filePath, 'utf8');

function repl(old, newStr) {
    content = content.split(old).join(newStr);
}

// Imports
if (!content.includes('import { useLangStore } from "@/store/lang";')) {
    content = content.replace('import { cn } from "@/lib/utils";', 'import { cn } from "@/lib/utils";\nimport { useLangStore } from "@/store/lang";\nimport { translations, TranslationKey } from "@/lib/i18n";');
}

// Store hook
if (!content.includes('const { lang } = useLangStore();')) {
    content = content.replace('export function Sidebar() {', 'export function Sidebar() {\n  const { lang } = useLangStore();\n  const t = (key: TranslationKey) => translations[lang][key] || key;');
}

// Nav items translation logic (using dynamic keys)
repl('label: "Tổng quan"', 'labelKey: "nav_overview" as TranslationKey');
repl('label: "Tài khoản"', 'labelKey: "nav_accounts" as TranslationKey');
repl('label: "Nhà cung cấp"', 'labelKey: "nav_providers" as TranslationKey');
repl('label: "Quản lý Model"', 'labelKey: "nav_models" as TranslationKey');
repl('label: "Mô hình kết hợp"', 'labelKey: "nav_combos" as TranslationKey');
repl('label: "Vẽ ảnh"', 'labelKey: "nav_image" as TranslationKey');
repl('label: "Thư viện ảnh"', 'labelKey: "nav_imageLibrary" as TranslationKey');
repl('label: "Tìm kiếm"', 'labelKey: "nav_search" as TranslationKey');
repl('label: "Sao lưu"', 'labelKey: "nav_backup" as TranslationKey');
repl('label: "Cài đặt"', 'labelKey: "nav_settings" as TranslationKey');

// Use translated labels in render
repl('title={collapsed ? item.label : undefined}', 'title={collapsed ? t(item.labelKey) : undefined}');
repl('<span>{item.label}</span>', '<span>{t(item.labelKey)}</span>');

// Other strings
repl('isAdmin ? "Quản trị viên" : "Người dùng"', 'isAdmin ? t("admin") : t("user")');
repl('Quản lý hệ thống', '{t("systemManagement")}');
repl('title="Đăng xuất"', 'title={t("logout")}');
repl('!collapsed && "Đăng xuất"', '!collapsed && t("logout")');

fs.writeFileSync(filePath, content, 'utf8');
console.log('Successfully updated sidebar with i18n!');
