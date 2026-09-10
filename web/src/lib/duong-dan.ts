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

/** Mở màn hình noVNC — chạy được với MỌI đường vào, và tự lo xác thực.
 *
 * **Vì sao không dựng `<host>:6080` nữa.** noVNC lắng nghe ở cổng 6080 và cổng
 * đó được publish ra LAN, nên vào bằng IP thì `http://172.16.10.38:6080` mở
 * được. Vào bằng tên miền thì KHÔNG: Cloudflare Tunnel chỉ trỏ một dịch vụ
 * (cổng 3030 của web UI này), không có đường nào tới 6080 — bấm "Mở noVNC" ở
 * `https://gpt.vhtatn.io.vn/settings/` ra `https://gpt.vhtatn.io.vn:6080/…`,
 * cổng không tồn tại nên trình duyệt treo rồi báo lỗi (chủ máy báo 09/09).
 *
 * Máy chủ nay có proxy cùng gốc (`api/novnc_proxy.py`): `/novnc/…` đi ra đúng
 * cổng 6080 nội bộ. Cùng gốc nghĩa là dùng chung cổng, chung chứng chỉ HTTPS —
 * nên một đường này đúng cho cả IP, tên miền, và tunnel.
 *
 * **Vì sao phải xin vé.** Tab mới là điều hướng thường của trình duyệt, không
 * có JavaScript nào gắn `Authorization` vào được — bản đầu để proxy đòi header
 * nên mọi lần mở đều 401 (chủ máy dán ảnh 09/09). Nên xin vé bằng đường API
 * bình thường trước, rồi nhét vé vào URL; máy chủ đổi vé lấy cookie ngắn hạn
 * cho các tệp con. Vé sống 60 giây, dùng một lần.
 *
 * **Mở tab TRƯỚC khi `await`.** Trình duyệt chỉ cho `window.open` chạy ngay
 * trong nhịp người dùng bấm; gọi sau `await` là bị chặn pop-up. Nên mở tab
 * trắng trước, xin vé xong mới trỏ nó tới đích.
 *
 * @param dacTa tuỳ chọn cho `window.open` (ví dụ `"noopener,width=1024,height=720"`).
 * @returns cửa sổ vừa mở, hoặc `null` nếu trình duyệt chặn.
 */
export async function moNoVNC(dacTa?: string): Promise<Window | null> {
  const tab = window.open("about:blank", "_blank", dacTa);
  try {
    const { request } = await import("@/lib/request");
    const res = await request.post("/api/novnc/ve");
    const ve = (res.data as { ticket?: string })?.ticket || "";
    // `path` phải là đường TUYỆT ĐỐI (có `/` đầu). noVNC ghép `path` vào GỐC
    // TRANG, mà trang nằm ở `/novnc/vnc.html`, nên viết `novnc/websockify`
    // (không dấu `/`) cho ra `/novnc/novnc/websockify` — hai lần "novnc".
    //
    // Đo thật 10/09/2026 trên log máy chủ: 9/9 lần nối đều gọi đúng đường sai
    // đó và bị trả 403, không lần nào chạm được endpoint thật. Chủ máy thấy
    // "Failed to connect to server".
    const dich = `/novnc/vnc.html?autoconnect=1&path=/novnc/websockify&ve=${encodeURIComponent(ve)}`;
    if (tab) tab.location.href = dich;
    else window.location.href = dich;  // bị chặn pop-up → đi thẳng
    return tab;
  } catch (e) {
    tab?.close();
    throw e;
  }
}
