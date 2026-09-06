/** Chuẩn hoá đường dẫn: bỏ dấu gạch chéo cuối.
 *
 * `next.config.mjs` bật `output: "export"` + `trailingSlash: true`, nên
 * `usePathname()` trả về `/login/` chứ không phải `/login`. Mọi phép so sánh
 * bằng `===` với chuỗi không gạch cuối đều SAI, và sai im lặng:
 *
 *   · `pathname === "/login"` không bao giờ đúng → màn đăng nhập mang nguyên
 *     thanh công cụ quản trị và chừa 250px trống cho thanh bên không tồn tại;
 *   · `pageTitles[pathname]` trượt khoá → mọi trang trừ trang chủ hiện tiêu đề
 *     dự phòng "chatgpt2api" thay cho tên thật;
 *   · `pathname === item.href` trượt → mục đang xem không bao giờ sáng.
 *
 * Chạy `next dev` thì có thể không gạch cuối, nên phải chịu được cả hai dạng.
 */
export function chuanHoaDuong(duong: string | null | undefined): string {
  const s = String(duong || "/");
  return s.length > 1 && s.endsWith("/") ? s.slice(0, -1) : s;
}

/** Hai đường dẫn có trỏ cùng một trang không (bỏ qua gạch cuối). */
export function cungDuong(a: string | null | undefined, b: string | null | undefined): boolean {
  return chuanHoaDuong(a) === chuanHoaDuong(b);
}
