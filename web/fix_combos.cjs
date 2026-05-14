const fs = require('fs');
const path = require('path');

const filePath = path.join(__dirname, 'src', 'app', 'combos', 'page.tsx');
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
    content = content.replace('export default function CombosPage() {', 'export default function CombosPage() {\n  const { lang } = useLangStore();\n  const t = (key: TranslationKey) => translations[lang][key] || key;');
}

// Logic
repl('"Lỗi lưu"', 't("saveError")');
repl('"Cần ít nhất 2 model trong 1 combo (để fallback)"', 't("atLeastTwoModels")');
repl('"Đang tải..."', 't("loading")');

// UI
repl('<h1 className="text-[24px] font-bold tracking-tight text-slate-900">Mô hình kết hợp</h1>', '<h1 className="text-[24px] font-bold tracking-tight text-slate-900">{t("combosTitle")}</h1>');
repl('{saved && <span className="text-[13px] text-emerald-600 font-medium">✓ Đã lưu</span>}', '{saved && <span className="text-[13px] text-emerald-600 font-medium">✓ {t("saved")}</span>}');
repl('<Save className="size-4" />\n            Lưu', '<Save className="size-4" />\n            {t("save")}');
repl('<p className="text-[14px] text-slate-500">\n          Combo model tự động fallback qua nhiều provider theo thứ tự ưu tiên. Chỉ hiển thị model đã bật trong Quản lý Model.\n        </p>', '<p className="text-[14px] text-slate-500">\n          {t("combosSubtitle")}\n        </p>');

repl('Chat: {counts.chat}', '{t("chat")}: {counts.chat}');
repl('Phân tích ảnh: {counts.vision}', '{t("vision")}: {counts.vision}');
repl('Tạo ảnh: {counts.image}', '{t("imageGen")}: {counts.image}');

repl('<h3 className="mb-4 text-[15px] font-bold text-slate-900">Thêm combo mới</h3>', '<h3 className="mb-4 text-[15px] font-bold text-slate-900">{t("addNewCombo")}</h3>');
repl('placeholder="Tên combo (vd: ha-agent)"', 'placeholder={t("comboNamePlaceholder")}');
repl('Thứ tự fallback ({selectedModels.length} model)', '{t("fallbackOrder").replace("{count}", String(selectedModels.length))}');

// Cap labels
repl('label === "Phân tích ảnh" ? "vision"', 'label === t("vision") ? "vision" : label === "Phân tích ảnh" ? "vision"'); 
// The above is tricky because capability_labels might be coming from API. 
// Let's just translate them in the render.

repl('cap === "all" ? "Tất cả" : cap === "chat" ? "Chat" : cap === "vision" ? "Vision" : "Tạo ảnh"', 'cap === "all" ? t("all") : cap === "chat" ? t("chat") : cap === "vision" ? t("vision") : t("imageGen")');
repl('<span className="text-stone-500">Chọn model để thêm vào chuỗi fallback...</span>', '<span className="text-stone-500">{t("selectModelPlaceholder")}</span>');
repl('filterCap !== "all" ? "Không có model nào trong danh mục này" : "Tất cả model đã được chọn"', 'filterCap !== "all" ? t("noModelsInCategory") : t("allModelsSelected")');

repl('<Plus className="size-4" />\n            Thêm', '<Plus className="size-4" />\n            {t("add")}');

repl('<p>Chưa có combo model nào</p>', '<p>{t("noCombos")}</p>');
repl('<p className="text-xs mt-1">Tạo combo đầu tiên để tự động fallback khi provider lỗi</p>', '<p className="text-xs mt-1">{t("createFirstCombo")}</p>');

repl('{models.length} model', '{models.length} {t("models")}');
repl('<p className="mt-3 text-xs text-stone-500">\n                Thứ tự fallback: thử model ❶ trước → nếu lỗi mới thử model tiếp theo\n              </p>', '<p className="mt-3 text-xs text-stone-500">\n                {t("fallbackLogicDesc")}\n              </p>');

fs.writeFileSync(filePath, content, 'utf8');
console.log('Successfully updated combos page with i18n!');
