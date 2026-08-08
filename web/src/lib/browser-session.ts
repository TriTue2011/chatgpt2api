"use client";

/**
 * Phiên trình duyệt bằng cookie HttpOnly — thay cho việc giữ khoá API trong
 * localStorage/IndexedDB.
 *
 * Vấn đề đang có: `store/auth.ts` lưu chính `CHATGPT2API_AUTH_KEY`. Khoá đó
 * mở mọi endpoint, sống vĩnh viễn, và bất kỳ script nào chạy trong trang đều
 * đọc được. Một lỗ XSS là mất trọn quyền quản trị, mà thu hồi thì kéo theo cả
 * Home Assistant, Zalo và mọi script khác.
 *
 * Sau khi đổi: session id nằm trong cookie `HttpOnly` (JavaScript không đọc
 * được), còn thứ duy nhất JS giữ là CSRF token — token đó tự nó vô dụng nếu
 * không kèm cookie.
 *
 * Di trú theo hai bước, KHÔNG cắt đường cũ:
 *   1. Đăng nhập như cũ bằng khoá → gọi ngay `/auth/browser-login` → có cookie
 *      → xoá khoá khỏi kho cục bộ.
 *   2. Máy chủ chưa bật cờ (trả 404) thì giữ nguyên đường Bearer như trước.
 *
 * Nhờ vậy web mới chạy được với cả image cũ lẫn image mới — bật cờ lúc nào
 * cũng được, không phải canh đúng thời điểm.
 */

const CSRF_STORAGE_KEY = "chatgpt2api_csrf";

/** Giữ trong RAM để không phải chạm storage mỗi request. */
let csrfTrongRam = "";

/**
 * `sessionStorage` chứ không phải `localStorage`: CSRF token chỉ có nghĩa
 * trong đúng tab đang mở, và đóng tab là hết. Nó KHÔNG phải bí mật ngang khoá
 * API — không kèm cookie thì không dùng được vào việc gì.
 */
export function layCsrfToken(): string {
    if (csrfTrongRam) return csrfTrongRam;
    if (typeof window === "undefined") return "";
    try {
        csrfTrongRam = window.sessionStorage.getItem(CSRF_STORAGE_KEY) || "";
    } catch {
        csrfTrongRam = "";
    }
    return csrfTrongRam;
}

function luuCsrfToken(token: string) {
    csrfTrongRam = String(token || "").trim();
    if (typeof window === "undefined") return;
    try {
        if (csrfTrongRam) {
            window.sessionStorage.setItem(CSRF_STORAGE_KEY, csrfTrongRam);
        } else {
            window.sessionStorage.removeItem(CSRF_STORAGE_KEY);
        }
    } catch {
        /* chế độ riêng tư chặn storage — vẫn chạy được nhờ bản trong RAM */
    }
}

/** Nhận CSRF token do máy chủ cấp lại cho tab này (xem `/auth/browser-session`). */
export function nhanCsrfToken(token: string): void {
    if (token) luuCsrfToken(token);
}

/**
 * Header xác thực cho các lời gọi `fetch` THẲNG (không qua axios `request`).
 *
 * Có phiên cookie → gắn `X-CSRF-Token`, cookie tự đi kèm. Chưa di trú → Bearer
 * như cũ. Không có gì cả → trả rỗng, để nơi gọi tự quyết định báo lỗi.
 */
export function headerXacThuc(khoaBearer = ""): Record<string, string> {
    const csrf = layCsrfToken();
    if (csrf) return {"X-CSRF-Token": csrf};
    return khoaBearer ? {Authorization: `Bearer ${khoaBearer}`} : {};
}

export function coPhienTrinhDuyet(): boolean {
    return Boolean(layCsrfToken());
}

export type KetQuaDangNhapPhien =
    | { trangThai: "thanh_cong"; vaiTro: string; ten: string }
    | { trangThai: "chua_bat" }        // máy chủ chưa bật cờ → giữ đường Bearer
    | { trangThai: "that_bai"; loi: string };

/**
 * Đổi khoá API lấy cookie phiên.
 *
 * Gọi `fetch` thẳng thay vì qua `request` axios: lúc này chưa có cookie nên
 * interceptor chưa có gì để gắn, và ta cần đọc mã lỗi 404 nguyên vẹn để phân
 * biệt "máy chủ chưa bật" với "khoá sai" — hai thứ dẫn tới hai hành vi khác
 * hẳn nhau.
 */
export async function dangNhapPhien(
    apiUrl: string,
    khoa: string,
): Promise<KetQuaDangNhapPhien> {
    const goc = String(apiUrl || "").replace(/\/$/, "");
    try {
        const resp = await fetch(`${goc}/auth/browser-login`, {
            method: "POST",
            credentials: "include",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({key: String(khoa || "").trim()}),
        });
        if (resp.status === 404) {
            return {trangThai: "chua_bat"};
        }
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            return {
                trangThai: "that_bai",
                loi: String(data?.detail?.error || `Đăng nhập thất bại (${resp.status})`),
            };
        }
        luuCsrfToken(String(data?.csrf_token || ""));
        return {
            trangThai: "thanh_cong",
            vaiTro: String(data?.role || ""),
            ten: String(data?.name || ""),
        };
    } catch (e) {
        return {trangThai: "that_bai", loi: e instanceof Error ? e.message : String(e)};
    }
}

export async function dangXuatPhien(apiUrl: string): Promise<void> {
    const goc = String(apiUrl || "").replace(/\/$/, "");
    const csrf = layCsrfToken();
    luuCsrfToken("");
    if (!csrf) return;
    try {
        await fetch(`${goc}/auth/browser-logout`, {
            method: "POST",
            credentials: "include",
            headers: {"X-CSRF-Token": csrf},
        });
    } catch {
        /* Xoá được cookie hay không thì phía client cũng đã quên token rồi;
           phiên còn lại trên máy chủ sẽ tự hết hạn. */
    }
}
