#!/usr/bin/env node
/**
 * Kiểm layout mobile bằng cách ĐỌC MÃ NGUỒN (tĩnh, không cần trình duyệt).
 *
 * Bắt đúng ba kiểu hỏng đã thấy trên máy thật ở khổ 390px:
 *   1. Hàng flex ngang không cho xuống dòng → hai bên giành chỗ, chữ vỡ từng
 *      chữ một ("Bỏ chọn tất cả" thành 3 dòng).
 *   2. Bề rộng/đệm ghi cứng vượt khổ điện thoại → tràn ngang.
 *   3. Chữ tối ghi cứng không kèm biến cho chế độ tối → tàng hình.
 *
 * Chạy: node scripts/kiem-mobile.mjs
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const GOC = new URL("../src", import.meta.url).pathname;
const loi = [];

function duyet(thuMuc) {
  for (const ten of readdirSync(thuMuc)) {
    const duong = join(thuMuc, ten);
    if (statSync(duong).isDirectory()) duyet(duong);
    else if (/\.(tsx|jsx)$/.test(ten)) soi(duong);
  }
}

// Lấy trọn chuỗi className, kể cả khi trải nhiều dòng.
function cacLopTrongTep(noiDung) {
  const ra = [];
  const re = /className=(?:"([^"]*)"|\{`([^`]*)`\}|\{cn\(([\s\S]{0,900}?)\)\})/g;
  let m;
  while ((m = re.exec(noiDung))) {
    const chuoi = m[1] || m[2] || m[3] || "";
    const dong = noiDung.slice(0, m.index).split("\n").length;
    ra.push({ chuoi, dong });
  }
  return ra;
}

function soi(duong) {
  const noiDung = readFileSync(duong, "utf8");
  const ten = relative(GOC, duong);

  loi.push(...soiTheoThe(noiDung, ten));
  loi.push(...soiHangNut(noiDung, ten));

  for (const { chuoi, dong } of cacLopTrongTep(noiDung)) {
    const co = (r) => r.test(chuoi);

    // 1. Hàng ngang không xuống dòng được.
    const hangNgang = co(/\bflex\b/) && !co(/\bflex-col\b/) && !co(/\binline-flex\b/);
    const chiaHaiBen = co(/\bjustify-between\b/);
    const choXuongDong =
      co(/\bflex-wrap\b/) ||
      co(/\b(sm|md|lg):flex-row\b/) ||   // mặc định cột, chỉ ngang từ breakpoint
      co(/\bflex-col\b/);
    if (hangNgang && chiaHaiBen && !choXuongDong && !MIEN_TRU.has(ten)) {
      loi.push({ ten, dong, muc: "hang-ngang-khong-xuong-dong",
        chi: "flex + justify-between mà không flex-wrap: trên 390px hai bên giành chỗ, chữ vỡ từng chữ" });
    }

    // 2. Bề rộng SÀN ghi cứng vượt khổ điện thoại (390px trừ đệm còn ~358px).
    //    Chỉ tính `w-` và `min-w-`: đó là bề rộng BẮT BUỘC. `max-w-` là trần,
    //    co lại được nên không gây tràn. Bảng nằm trong `overflow-x-auto` cũng
    //    không tính — cuộn ngang ở bảng nhật ký là CÓ CHỦ Ý.
    const mw = chuoi.match(/(?<!max-)\b(?:min-w|w)-\[(\d+)px\]/);
    const trongVungCuon = /overflow-x-auto/.test(noiDung.slice(Math.max(0, noiDung.indexOf(chuoi) - 400), noiDung.indexOf(chuoi)));
    if (mw && Number(mw[1]) > 358 && !co(/\b(sm|md|lg):/) && !co(/\bw-full\b/) && !trongVungCuon) {
      loi.push({ ten, dong, muc: "be-rong-ghi-cung",
        chi: `w-[${mw[1]}px] > 358px khả dụng trên máy 390px → tràn ngang` });
    }

    // 3. Lưới nhiều cột không đổ xuống trên điện thoại. `columns-*` (báo Masonry)
    //    được miễn: đó là bố cục CỘT BÁO, tự co theo bề ngang.
    const mg = chuoi.match(/\bgrid-cols-([3-9]|1[0-2])\b/);
    if (mg && !/\b(sm|md|lg|xl):(grid-cols-|block|columns-)/.test(chuoi)) {
      loi.push({ ten, dong, muc: "luoi-nhieu-cot-co-dinh",
        chi: `grid-cols-${mg[1]} không có bản ít cột hơn cho điện thoại → ô bị bóp/tràn` });
    }

    // 5. Chữ tối ghi cứng, không có bản cho chế độ tối.
    if (co(/\btext-(?:slate|gray|zinc|neutral|stone)-(?:[789]00)\b/) && !co(/\bdark:text-/)) {
      // Nền sáng ghi cứng đi kèm thì vẫn đọc được — bỏ qua.
      const coNenSang = co(/\bbg-(?:\w+)-(?:50|100|200)\b/) || co(/\bbg-white\b/);
      if (!coNenSang)
        loi.push({ ten, dong, muc: "chu-toi-khong-co-ban-toi",
          chi: "chữ tối ghi cứng, thiếu dark: → tàng hình ở chế độ tối" });
    }
  }
}

/**
 * Soi theo THẺ HTML — cần biết phần tử có bấm được không, mà chuỗi className
 * đơn lẻ thì không nói lên điều đó.
 *
 *  A. Ô nhập chữ < 16px  → iOS Safari tự phóng to trang khi bấm vào. Cộng với
 *     viewport khoá zoom là người dùng kẹt luôn ở trạng thái phóng to.
 *  B. Vùng chạm < 24px   → WCAG 2.2 Target Size (mức AA). Lớp phủ trong suốt
 *     `before:size-6` là cách hợp lệ để đạt chuẩn mà không đổi nét vẽ.
 */
/**
 * Hàng chứa NHIỀU NÚT mà không cho xuống dòng.
 *
 * Quy tắc 1 chỉ bắt `justify-between` nên bỏ sót mẫu này: một `<div className=
 * "flex items-center gap-2">` bọc 2-3 `<Button>` chữ dài. Trên màn 390px nút
 * cuối bị cắt mất chữ — đo thật ở openai-native-card ("Ngừng theo dõi" cụt).
 */
function soiHangNut(noiDung, ten) {
  const ra = [];
  const re = /className="((?:[^"]*\bflex\b)[^"]*)"\s*>([\s\S]{0,600}?)<\/div>/g;
  let m;
  while ((m = re.exec(noiDung))) {
    const lop = m[1], than = m[2];
    if (/flex-col|flex-wrap|inline-flex/.test(lop)) continue;
    if (/\b(sm|md|lg):flex-/.test(lop)) continue;
    // đếm nút CON trực tiếp mang chữ (bỏ nút chỉ có icon — chúng nhỏ, không tràn)
    const nut = than.match(/<Button\b[^>]*>[\s\S]{0,160}?[\p{L}]{3,}/gu) || [];
    if (nut.length < 2) continue;
    const dong = noiDung.slice(0, m.index).split("\n").length;
    ra.push({ ten, dong, muc: "hang-nut-khong-xuong-dong",
      chi: `${nut.length} nút chữ trên một hàng không flex-wrap → nút cuối bị cắt trên màn hẹp` });
  }
  return ra;
}

function soiTheoThe(noiDung, ten) {
  const ra = [];
  const reThe = /<(input|textarea|select|button|a)\b[^>]{0,900}?className=(?:"([^"]*)"|\{cn\(([\s\S]{0,500}?)\)\})/g;
  let m;
  while ((m = reThe.exec(noiDung))) {
    const the = m[1];
    const lop = (m[2] || m[3] || "");
    const dong = noiDung.slice(0, m.index).split("\n").length;
    const co = (r) => r.test(lop);

    if (["input", "textarea", "select"].includes(the)) {
      const laAn = /type="(hidden|checkbox|radio)"/.test(m[0]);
      // ĐẠT khi cỡ chữ MẶC ĐỊNH (chưa có breakpoint) là >= 16px. Mẫu đúng là
      // `text-base sm:text-sm`: mobile 16px, desktop trả về 14px. Chỉ báo khi
      // cỡ mặc định vẫn là text-xs/text-sm.
      const macDinh = lop.replace(/\b(sm|md|lg|xl):[^\s"]+/g, " ");
      if (!laAn && /\btext-(xs|sm)\b/.test(macDinh))
        ra.push({ ten, dong, muc: "input-gay-zoom-ios",
          chi: "ô nhập chữ < 16px: iOS tự phóng to trang khi bấm vào" });
    }

    const msz = lop.match(/\bsize-(3\.5|4|5)\b/);
    if (msz && !co(/before:size-[6-9]/) && !co(/\bpointer-events-none\b/)) {
      const px = { "3.5": 14, "4": 16, "5": 20 }[msz[1]];
      ra.push({ ten, dong, muc: "vung-cham-qua-nho",
        chi: `vùng chạm ${px}px < 24px (WCAG 2.2); thêm before:size-6 để mở rộng mà không đổi nét vẽ` });
    }
  }
  return ra;
}

/**
 * Miễn trừ — đã soi tận nơi, xếp dọc ở đây là SAI:
 *   ui/select.tsx        ô select: nhãn và mũi tên phải cùng một dòng.
 *   app-shell.tsx        thanh trên cùng cao cố định h-14.
 *   top-nav.tsx          đã có bản responsive riêng (sm:justify-start).
 *   image-composer.tsx   đã responsive theo min-[390px] và sm.
 */
const MIEN_TRU = new Set([
  "components/ui/select.tsx",
  "components/app-shell.tsx",
  "components/top-nav.tsx",
  "app/image/components/image-composer.tsx",
]);

duyet(GOC);

const theoMuc = {};
for (const l of loi) (theoMuc[l.muc] ||= []).push(l);

const NHAN = {
  "hang-ngang-khong-xuong-dong": "Hàng ngang không xuống dòng (vỡ chữ trên điện thoại)",
  "be-rong-ghi-cung": "Bề rộng ghi cứng vượt khổ điện thoại (tràn ngang)",
  "chu-toi-khong-co-ban-toi": "Chữ tối thiếu bản cho chế độ tối (tàng hình)",
  "luoi-nhieu-cot-co-dinh": "Lưới nhiều cột không đổ xuống trên điện thoại",
  "input-gay-zoom-ios": "Ô nhập chữ < 16px (iOS tự phóng to trang)",
  "vung-cham-qua-nho": "Vùng chạm < 24px (WCAG 2.2 Target Size)",
  "hang-nut-khong-xuong-dong": "Hàng nhiều nút không xuống dòng (nút cuối bị cắt)",
};

for (const [muc, ds] of Object.entries(theoMuc)) {
  console.log(`\n${NHAN[muc]} — ${ds.length} chỗ`);
  const gon = process.argv.includes("--day-du") ? ds.length : 12;
  for (const l of ds.slice(0, gon)) console.log(`  ${l.ten}:${l.dong}`);
  if (ds.length > gon) console.log(`  … và ${ds.length - gon} chỗ nữa`);
}

console.log("\n" + "─".repeat(62));
if (!loi.length) {
  console.log("ĐẠT: không thấy lỗi bố cục mobile.");
  process.exit(0);
}
console.log(`HỎNG: ${loi.length} chỗ cần sửa.`);
process.exit(1);
