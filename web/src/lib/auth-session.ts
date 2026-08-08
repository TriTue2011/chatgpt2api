"use client";

import webConfig from "@/constants/common-env";
import { fetchBrowserSession, login } from "@/lib/api";
import { dangNhapPhien, nhanCsrfToken } from "@/lib/browser-session";
import { clearStoredAuthSession, getStoredAuthSession, setStoredAuthSession, type StoredAuthSession } from "@/store/auth";

export async function getValidatedAuthSession(): Promise<StoredAuthSession | null> {
  const storedSession = await getStoredAuthSession();
  if (!storedSession) {
    return null;
  }

  // Đã di trú sang cookie: hỏi bằng đúng cookie, KHÔNG dùng `login()` — hàm đó
  // luôn gắn `Authorization: Bearer <khoá>`, mà giờ không còn khoá.
  if (storedSession.viaCookie) {
    // CSRF token nằm ở `sessionStorage`, vốn RIÊNG theo tab: mở tab thứ hai là
    // tab đó không có token, dù cookie phiên vẫn còn nguyên.
    //
    // Bản đầu coi đó là "hết phiên" và gọi `clearStoredAuthSession` — mà hàm đó
    // xoá kho DÙNG CHUNG và thu hồi luôn phiên phía máy chủ, nên mở thêm một
    // tab là ĐĂNG XUẤT Ở MỌI TAB. Nay xin lại token: `/auth/browser-session`
    // xác thực bằng chính cookie và trả token của phiên hiện tại.
    try {
      const data = await fetchBrowserSession();
      if (data.csrf_token) nhanCsrfToken(data.csrf_token);
      const nextSession: StoredAuthSession = {
        key: "",
        role: data.role,
        subjectId: data.id === "admin" ? "admin" : String(data.id || ""),
        name: data.name,
        viaCookie: true,
      };
      await setStoredAuthSession(nextSession);
      return nextSession;
    } catch {
      await clearStoredAuthSession();
      return null;
    }
  }

  try {
    const data = await login(storedSession.key);
    // Chưa di trú mà máy chủ ĐÃ bật cờ → di trú ngay tại đây, không bắt người
    // dùng đăng nhập lại. Thất bại thì giữ nguyên đường Bearer, không chặn ai.
    const phien = await dangNhapPhien(webConfig.apiUrl, storedSession.key);
    const daDoi = phien.trangThai === "thanh_cong";
    const nextSession: StoredAuthSession = {
      key: daDoi ? "" : storedSession.key,
      role: data.role,
      subjectId: data.subject_id,
      name: data.name,
      ...(daDoi ? { viaCookie: true } : {}),
    };
    await setStoredAuthSession(nextSession);
    return nextSession;
  } catch {
    await clearStoredAuthSession();
    return null;
  }
}
