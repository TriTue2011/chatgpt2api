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

/** URL mở màn hình noVNC — chạy được với MỌI đường vào.
 *
 * **Vì sao không dựng `<host>:6080` nữa.** noVNC lắng nghe ở cổng 6080 và cổng
 * đó được publish ra LAN, nên vào bằng IP thì `http://172.16.10.38:6080` mở
 * được. Vào bằng tên miền thì KHÔNG: Cloudflare Tunnel chỉ trỏ một dịch vụ
 * (cổng 3030 của web UI này), không có đường nào tới 6080 — bấm "Mở noVNC" ở
 * `https://gpt.vhtatn.io.vn/settings/` ra `https://gpt.vhtatn.io.vn:6080/…`,
 * cổng không tồn tại nên trình duyệt treo rồi báo lỗi (chủ máy báo 09/09).
 *
 * Nay máy chủ có sẵn proxy cùng gốc (`api/novnc_proxy.py`): `/novnc/…` đi ra
 * đúng cổng 6080 nội bộ. Cùng gốc nghĩa là dùng chung cổng, chung cookie phiên,
 * chung chứng chỉ HTTPS — nên một đường này đúng cho cả IP, tên miền, và tunnel,
 * không phải đoán xem người dùng đang vào bằng cách nào.
 *
 * `path=novnc/websockify` là đường WebSocket noVNC sẽ nối tới (tương đối so với
 * trang), phải khớp endpoint mà proxy mở. Thiếu tham số này thì noVNC gọi
 * `/websockify` ở gốc và gặp trang web thay vì kênh RFB → màn hình đen.
 */
export function duongNoVNC(): string {
  return "/novnc/vnc.html?autoconnect=1&path=novnc/websockify";
}
