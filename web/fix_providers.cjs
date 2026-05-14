const fs = require('fs');
const path = require('path');

const filePath = path.join(__dirname, 'src', 'app', 'providers', 'page.tsx');
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
    content = content.replace('export default function ProvidersPage() {', 'export default function ProvidersPage() {\n  const { lang } = useLangStore();\n  const t = (key: TranslationKey) => translations[lang][key] || key;');
}

// UI
repl('"Đang tải..."', 't("loading")');
repl('<h1 className="text-[24px] font-bold tracking-tight text-slate-900">Nhà cung cấp AI</h1>', '<h1 className="text-[24px] font-bold tracking-tight text-slate-900">{t("providersTitle")}</h1>');
repl('<p className="text-[14px] text-slate-500">\n          Quản lý các nhà cung cấp AI bên ngoài — miễn phí và có API key\n        </p>', '<p className="text-[14px] text-slate-500">\n          {t("providersSubtitle")}\n        </p>');

repl('provider.enabled ? "Đã bật" : "Đã tắt"', 'provider.enabled ? t("enabledText") : t("disabledText")');
repl('Không cần API key', '{t("noApiKeyNeeded")}');
repl('Đã cấu hình API key', '{t("apiKeyConfigured")}');
repl('Đã cấu hình URL', '{t("baseUrlConfigured")}');

repl('isTesting ? "Đang kiểm tra..." : "Kiểm tra kết nối"', 'isTesting ? t("testing") : t("checkConnection")');
repl('testResult ? "Kết nối OK" : "Lỗi kết nối"', 'testResult ? t("connectionOk") : t("connectionError")');

repl('<p>Chưa có nhà cung cấp nào được cấu hình</p>', '<p>{t("noProviders")}</p>');
repl('<p className="text-xs mt-1">Thêm provider vào config.json để bắt đầu</p>', '<p className="text-xs mt-1">{t("addProviderInConfig")}</p>');

fs.writeFileSync(filePath, content, 'utf8');
console.log('Successfully updated providers page with i18n!');
