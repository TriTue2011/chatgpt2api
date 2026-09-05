#!/usr/bin/env node
/**
 * Đo tương phản WCAG cho MỌI cặp token màu trong globals.css.
 *
 * Vì sao cần: đo ngày 05/09/2026 thấy chủ đề sáng có vàng #d4af37 trên nền kem
 * chỉ đạt 1,86:1 (chuẩn AA cần 4,5:1) — chữ gần như vô hình. Kiểu lỗi này không
 * ai phát hiện khi đọc diff, vì trong code nó chỉ là một mã màu trông bình
 * thường; phải ĐO mới thấy. Bộ này biến "màu nhìn ổn" thành lệnh đạt/không đạt.
 *
 *   node scripts/kiem-tuong-phan.mjs          # đo, sai thì thoát mã 1
 *   node scripts/kiem-tuong-phan.mjs --tat-ca # in cả những cặp đã đạt
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const GOC = join(dirname(fileURLToPath(import.meta.url)), "..");
const CSS = join(GOC, "src/app/globals.css");

const AA_CHU = 4.5;   // chữ thường
const AA_TO = 3.0;    // chữ to (≥18,66px đậm hoặc ≥24px) và ranh giới đồ hoạ

/** Khối chủ đề cần đo: [tên hiển thị, bộ chọn CSS, khối nền kế thừa] */
const CHU_DE = [
  ["Mặc định · sáng", ":root", null],
  ["Mặc định · tối", ".dark", null],
  ["Linear · sáng", 'html[data-brand="linear"]:not(.dark)', ":root"],
  ["Linear · tối", 'html[data-brand="linear"].dark', ".dark"],
  ["Supabase · sáng", 'html[data-brand="supabase"]:not(.dark)', ":root"],
  ["Supabase · tối", 'html[data-brand="supabase"].dark', ".dark"],
];

/**
 * Cặp cần đo: [nhãn, biến chữ, biến nền, ngưỡng, bắtBuộc].
 *
 * `bắtBuộc = false` là cặp CHỈ BÁO, không làm hỏng lệnh. Dùng cho đường kẻ
 * TRANG TRÍ: WCAG 1.4.11 chỉ bắt 3:1 với ranh giới cần thiết để HIỂU giao diện
 * (viền ô nhập, vòng focus), còn viền thẻ và đường phân cách thuần trang trí thì
 * miễn. `--border` đang dùng ở 443 chỗ làm viền thẻ; ép nó lên 3:1 sẽ thành viền
 * đen sì khắp nơi — làm giao diện xấu đi mà vẫn không đúng chuẩn hơn.
 *
 * Ngược lại `--input` LÀ viền ô nhập thật (xem `border-input` trong
 * src/components/ui/input.tsx) nên bắt buộc: không thấy viền thì không biết gõ
 * vào đâu.
 */
const CAP = [
  ["Chữ chính trên nền", "foreground", "background", AA_CHU, true],
  ["Chữ trên thẻ", "card-foreground", "card", AA_CHU, true],
  ["Chữ trên popover", "popover-foreground", "popover", AA_CHU, true],
  ["Chữ phụ trên nền", "muted-foreground", "background", AA_CHU, true],
  ["Chữ phụ trên thẻ", "muted-foreground", "card", AA_CHU, true],
  ["Chữ phụ trên khối mờ", "muted-foreground", "muted", AA_CHU, true],
  ["Chữ trên khối phụ", "secondary-foreground", "secondary", AA_CHU, true],
  ["Màu nhấn làm chữ trên nền", "primary", "background", AA_CHU, true],
  ["Màu nhấn làm chữ trên thẻ", "primary", "card", AA_CHU, true],
  ["Chữ trên nút chính", "primary-foreground", "primary", AA_CHU, true],
  ["Màu phụ trợ làm chữ trên nền", "accent", "background", AA_CHU, true],
  ["Chữ trên nút phụ trợ", "accent-foreground", "accent", AA_CHU, true],
  ["Màu báo lỗi trên nền", "destructive", "background", AA_CHU, true],
  ["Màu báo lỗi trên thẻ", "destructive", "card", AA_CHU, true],
  ["Chữ sidebar", "sidebar-foreground", "sidebar", AA_CHU, true],
  ["Mục sidebar đang chọn", "sidebar-accent-foreground", "sidebar", AA_CHU, true],
  ["Chữ trên nút sidebar", "sidebar-primary-foreground", "sidebar-primary", AA_CHU, true],
  ["Viền ô nhập trên nền", "input", "background", AA_TO, true],
  ["Viền ô nhập trên thẻ", "input", "card", AA_TO, true],
  ["Vòng focus trên nền", "ring", "background", AA_TO, true],
  ["Vòng focus trên thẻ", "ring", "card", AA_TO, true],
  ["Viền trang trí trên nền", "border", "background", AA_TO, false],
  // Chuỗi biểu đồ là ĐỐI TƯỢNG ĐỒ HOẠ mang thông tin (WCAG 1.4.11 → 3:1).
  // Trang chủ vẽ chúng trên thẻ nên nền so sánh là --card.
  ["Biểu đồ chuỗi 1", "chart-1", "card", AA_TO, true],
  ["Biểu đồ chuỗi 2", "chart-2", "card", AA_TO, true],
  ["Biểu đồ chuỗi 3", "chart-3", "card", AA_TO, true],
  ["Biểu đồ chuỗi 4", "chart-4", "card", AA_TO, true],
  ["Biểu đồ chuỗi 5", "chart-5", "card", AA_TO, true],
  ["Biểu đồ chuỗi 6", "chart-6", "card", AA_TO, true],
  ["Biểu đồ chuỗi 7", "chart-7", "card", AA_TO, true],
  ["Biểu đồ chuỗi 8", "chart-8", "card", AA_TO, true],
];

// ── Đọc và phân giải biến ───────────────────────────────────────────────────

const nguon = readFileSync(CSS, "utf-8");

/** Lấy map biến của một khối bộ chọn. */
function docKhoi(boChon) {
  // Tìm "boChon {" rồi lấy tới dấu } cân bằng đầu tiên. Các khối token đều
  // phẳng (không lồng) nên đếm ngoặc đơn giản là đủ.
  const moc = nguon.indexOf(boChon + " {");
  if (moc === -1) return null;
  const dau = nguon.indexOf("{", moc);
  let sau = dau + 1, sau_ = 1;
  while (sau < nguon.length && sau_ > 0) {
    if (nguon[sau] === "{") sau_++;
    else if (nguon[sau] === "}") sau_--;
    sau++;
  }
  const than = nguon.slice(dau + 1, sau - 1);
  const map = new Map();
  for (const m of than.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
    map.set(m[1], m[2].trim());
  }
  return map;
}

/** #rgb / #rrggbb → [r,g,b]; rgba(...) → [r,g,b,a]; var(--x) → truy ngược. */
function phanGiai(giaTri, map, nen, sau = 0) {
  if (!giaTri || sau > 8) return null;
  const s = String(giaTri).trim();

  const varM = s.match(/^var\(\s*--([\w-]+)\s*(?:,\s*(.+))?\)$/);
  if (varM) {
    const tiep = map.get(varM[1]) ?? (nen && nen.get(varM[1])) ?? varM[2];
    return phanGiai(tiep, map, nen, sau + 1);
  }

  const hex = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    let h = hex[1];
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 1];
  }

  const rgba = s.match(/^rgba?\(([^)]+)\)$/i);
  if (rgba) {
    const p = rgba[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (p.length >= 3 && p.slice(0, 3).every((n) => Number.isFinite(n))) {
      return [p[0], p[1], p[2], Number.isFinite(p[3]) ? p[3] : 1];
    }
  }
  return null; // color-mix, gradient... bỏ qua, không đo được tĩnh
}

/** Chồng màu có alpha lên nền đục để ra màu mắt thật sự nhìn thấy. */
function chong(tren, duoi) {
  const a = tren[3];
  if (a >= 1) return tren;
  return [0, 1, 2].map((i) => tren[i] * a + duoi[i] * (1 - a)).concat(1);
}

function kenh(c) {
  const v = c / 255;
  return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}
function sang(rgb) {
  return 0.2126 * kenh(rgb[0]) + 0.7152 * kenh(rgb[1]) + 0.0722 * kenh(rgb[2]);
}
function tyLe(a, b) {
  const la = sang(a), lb = sang(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// ── Chạy ────────────────────────────────────────────────────────────────────

const inTatCa = process.argv.includes("--tat-ca");
let hong = 0, daDo = 0, boQua = 0, chiBao = 0;

for (const [ten, boChon, keThua] of CHU_DE) {
  const map = docKhoi(boChon);
  if (!map) {
    console.log(`\n${ten}: KHÔNG TÌM THẤY khối "${boChon}" — bỏ qua`);
    continue;
  }
  const nen = keThua ? docKhoi(keThua) : null;
  const doc = (k) => phanGiai(map.get(k) ?? (nen && nen.get(k)), map, nen);

  const nenTrang = doc("background");
  const dong = [];

  for (const [nhan, kChu, kNen, nguong, batBuoc] of CAP) {
    const chuRaw = doc(kChu), nenRaw = doc(kNen);
    if (!chuRaw || !nenRaw) { boQua++; continue; }
    // Nền trong suốt (sidebar dùng rgba) phải chồng lên nền trang trước.
    const nenThat = chong(nenRaw, nenTrang || [255, 255, 255, 1]);
    const chuThat = chong(chuRaw, nenThat);
    const r = tyLe(chuThat, nenThat);
    daDo++;
    const dat = r >= nguong;
    if (!dat && batBuoc) hong++;
    else if (!dat) chiBao++;
    if (!dat || inTatCa) {
      const co = dat ? "đạt " : batBuoc ? "HỎNG" : "nhắc";
      dong.push(
        `  ${co} ${nhan.padEnd(32)} ${r.toFixed(2).padStart(6)}:1  (cần ${nguong})  --${kChu} trên --${kNen}`,
      );
    }
  }

  if (dong.length) {
    console.log(`\n${ten}`);
    console.log(dong.join("\n"));
  } else {
    console.log(`\n${ten}: tất cả đạt`);
  }
}

console.log(`\n${"─".repeat(66)}`);
console.log(`Đã đo ${daDo} cặp · hỏng ${hong} · nhắc ${chiBao} (viền trang trí, WCAG miễn) · bỏ qua ${boQua}`);

if (hong > 0) {
  console.error(`\nKHÔNG ĐẠT: ${hong} cặp dưới ngưỡng WCAG AA. Sửa token trong src/app/globals.css.`);
  process.exit(1);
}
console.log("ĐẠT: mọi cặp token đều đủ tương phản.");
