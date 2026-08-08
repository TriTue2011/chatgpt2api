"use client";

import localforage from "localforage";

import webConfig from "@/constants/common-env";
import { dangXuatPhien } from "@/lib/browser-session";

export type AuthRole = "admin" | "user";

export type StoredAuthSession = {
  /** Rỗng khi đã di trú sang cookie phiên — xem `viaCookie`. */
  key: string;
  role: AuthRole;
  subjectId: string;
  name: string;
  /**
   * true = xác thực bằng cookie `HttpOnly`, KHÔNG còn khoá API nào nằm trong
   * IndexedDB/localStorage. Đây là mục đích của cả bản di trú: một lỗ XSS
   * không lấy được thứ gì mở được API.
   */
  viaCookie?: boolean;
};

export const AUTH_KEY_STORAGE_KEY = "chatgpt2api_auth_key";
export const AUTH_SESSION_STORAGE_KEY = "chatgpt2api_auth_session";

const authStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "auth",
});

function normalizeSession(value: unknown, fallbackKey = ""): StoredAuthSession | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Partial<StoredAuthSession>;
  const viaCookie = candidate.viaCookie === true;
  // Đã di trú thì cố ý KHÔNG nhận lại khoá, kể cả khi còn sót trong kho cũ.
  const key = viaCookie ? "" : String(candidate.key || fallbackKey || "").trim();
  const role = candidate.role === "admin" || candidate.role === "user" ? candidate.role : null;
  if (!role || (!viaCookie && !key)) {
    return null;
  }

  return {
    key,
    role,
    subjectId: String(candidate.subjectId || "").trim(),
    name: String(candidate.name || "").trim(),
    ...(viaCookie ? {viaCookie: true} : {}),
  };
}

export function getDefaultRouteForRole(role: AuthRole) {
  // User thường → Studio (chat); admin → quản lý tài khoản
  return role === "admin" ? "/accounts" : "/chat";
}

export async function getStoredAuthKey() {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    const value = await authStorage.getItem<string>(AUTH_KEY_STORAGE_KEY);
    if (value) {
      const key = String(value).trim();
      // Sync to localStorage so chat page can read it
      try { localStorage.setItem(AUTH_KEY_STORAGE_KEY, key); } catch (e) {}
      return key;
    }
  } catch (e) {}
  // Fallback: localStorage
  try {
    const fallback = localStorage.getItem(AUTH_KEY_STORAGE_KEY);
    if (fallback) return fallback.trim();
  } catch (e) {}
  return "";
}

export async function getStoredAuthSession() {
  if (typeof window === "undefined") {
    return null;
  }

  const [storedKey, storedSession] = await Promise.all([
    authStorage.getItem<string>(AUTH_KEY_STORAGE_KEY),
    authStorage.getItem<StoredAuthSession>(AUTH_SESSION_STORAGE_KEY),
  ]);

  const normalizedSession = normalizeSession(storedSession, String(storedKey || ""));
  if (normalizedSession) {
    if (normalizedSession.key !== String(storedKey || "").trim()) {
      await authStorage.setItem(AUTH_KEY_STORAGE_KEY, normalizedSession.key);
    }
    return normalizedSession;
  }

  if (String(storedKey || "").trim()) {
    await clearStoredAuthSession();
  }
  return null;
}

export async function setStoredAuthSession(session: StoredAuthSession) {
  const normalizedSession = normalizeSession(session);
  if (!normalizedSession) {
    await clearStoredAuthSession();
    return;
  }

  if (normalizedSession.viaCookie) {
    // Đây là bước ăn tiền của cả bản di trú: XOÁ HẲN khoá khỏi IndexedDB và
    // localStorage. Giữ lại "cho chắc" là giữ nguyên lỗ hổng — cookie chỉ
    // thêm một lớp chứ không thay được gì nếu khoá vẫn nằm đó.
    await Promise.all([
      authStorage.removeItem(AUTH_KEY_STORAGE_KEY),
      authStorage.setItem(AUTH_SESSION_STORAGE_KEY, normalizedSession),
    ]);
    try { localStorage.removeItem(AUTH_KEY_STORAGE_KEY); } catch (e) {}
    return;
  }

  await Promise.all([
    authStorage.setItem(AUTH_KEY_STORAGE_KEY, normalizedSession.key),
    authStorage.setItem(AUTH_SESSION_STORAGE_KEY, normalizedSession),
  ]);
  // Also save to localStorage
  try { localStorage.setItem(AUTH_KEY_STORAGE_KEY, normalizedSession.key); } catch (e) {}
}

export async function setStoredAuthKey(authKey: string) {
  const normalizedAuthKey = String(authKey || "").trim();
  if (!normalizedAuthKey) {
    await clearStoredAuthSession();
    return;
  }
  await authStorage.setItem(AUTH_KEY_STORAGE_KEY, normalizedAuthKey);
  // Also save to localStorage for pages that can't access IndexedDB
  try { localStorage.setItem(AUTH_KEY_STORAGE_KEY, normalizedAuthKey); } catch (e) {}
}

export async function clearStoredAuthSession() {
  if (typeof window === "undefined") {
    return;
  }
  // Thu hồi luôn phiên phía máy chủ. Đặt ở đây vì đây là điểm nghẽn DUY NHẤT
  // của việc đăng xuất — sidebar, top-nav, app-shell và bộ xử lý 401 đều gọi
  // vào đúng hàm này. Thêm ở từng chỗ gọi thì sẽ sót đúng cái quên nhất.
  await dangXuatPhien(webConfig.apiUrl);
  await Promise.all([
    authStorage.removeItem(AUTH_KEY_STORAGE_KEY),
    authStorage.removeItem(AUTH_SESSION_STORAGE_KEY),
  ]);
  try { localStorage.removeItem(AUTH_KEY_STORAGE_KEY); } catch (e) {}
}

export async function clearStoredAuthKey() {
  await clearStoredAuthSession();
}
