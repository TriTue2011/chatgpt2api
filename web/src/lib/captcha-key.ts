"use client";

import { getStoredAuthKey } from "@/store/auth";

/**
 * Khoá gắn vào `Authorization` khi trình duyệt gọi thẳng `/api/captcha/*`.
 *
 * Proxy `api/captcha_proxy.py` nhận CẢ khoá dashboard lẫn khoá captcha, rồi tự gắn khoá captcha THẬT trước khi
 * chuyển tiếp. Nên trình duyệt không cần biết khoá captcha. Khi `/api/settings` che bí mật
 * (`security.settings_redact_secrets`), `captcha_solver_api_key` về rỗng — rơi về khoá dashboard đang đăng nhập.
 *
 * Chỉ dùng để GỌI. Đừng ghi kết quả hàm này vào `captcha_solver_api_key` khi lưu cài đặt: đó là ghi khoá
 * dashboard đè lên khoá captcha.
 */
export async function khoaGoiCaptcha(khoaLuu: unknown): Promise<string> {
  if (typeof khoaLuu === "string" && khoaLuu.trim()) return khoaLuu.trim();
  return (await getStoredAuthKey()) || "";
}
