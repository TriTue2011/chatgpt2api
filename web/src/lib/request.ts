import axios, {AxiosError, type AxiosRequestConfig} from "axios";

import webConfig from "@/constants/common-env";
import {layCsrfToken} from "@/lib/browser-session";
import {clearStoredAuthSession, getStoredAuthKey} from "@/store/auth";

type RequestConfig = AxiosRequestConfig & {
    redirectOnUnauthorized?: boolean;
};

type ErrorPayload = {
    detail?: string | { error?: string | { message?: string } };
    error?: string | { message?: string };
    message?: string;
};

function errorMessageFromValue(value: unknown): string {
    if (typeof value === "string") {
        return value;
    }
    if (!value || typeof value !== "object") {
        return "";
    }

    const item = value as { error?: unknown; message?: unknown };
    if (typeof item.message === "string") {
        return item.message;
    }
    return errorMessageFromValue(item.error);
}

export const request = axios.create({
    baseURL: webConfig.apiUrl.replace(/\/$/, ""),
    // Cần thiết để cookie phiên (HttpOnly) đi kèm request. Không bật thì
    // trình duyệt bỏ cookie ở mọi lời gọi cross-origin và phiên vô dụng.
    withCredentials: true,
});

const PHUONG_THUC_DOI_TRANG_THAI = new Set(["post", "put", "patch", "delete"]);

request.interceptors.request.use(async (config) => {
    const nextConfig = {...config};
    const headers = {...(nextConfig.headers || {})} as Record<string, string>;

    const csrf = layCsrfToken();
    if (csrf) {
        // Có phiên cookie → xác thực bằng cookie, KHÔNG gắn Bearer nữa. Đây
        // chính là điểm của cả bản thay đổi: sau khi di trú, JavaScript không
        // còn giữ thứ gì mở được API.
        if (PHUONG_THUC_DOI_TRANG_THAI.has(String(nextConfig.method || "get").toLowerCase())) {
            headers["X-CSRF-Token"] = csrf;
        }
    } else {
        // Chưa di trú (máy chủ chưa bật cờ, hoặc phiên đã hết) → đường Bearer
        // như cũ. Giữ nhánh này để web mới chạy được với cả image cũ.
        const authKey = await getStoredAuthKey();
        if (authKey && !headers.Authorization) {
            headers.Authorization = `Bearer ${authKey}`;
        }
    }

    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-expect-error
    nextConfig.headers = headers;
    return nextConfig;
});

request.interceptors.response.use(
    (response) => response,
    async (error: AxiosError<ErrorPayload>) => {
        const status = error.response?.status;
        const shouldRedirect = (error.config as RequestConfig | undefined)?.redirectOnUnauthorized !== false;
        if (status === 401 && shouldRedirect && typeof window !== "undefined") {
            // Avoid redirect loop — only redirect if not already on /login
            if (!window.location.pathname.startsWith("/login")) {
                await clearStoredAuthSession();
                window.location.replace("/login");
                // Return a never-resolving promise to prevent further error handling
                // while the browser navigates away
                return new Promise(() => {});
            }
        }

        const payload = error.response?.data;
        const message =
            errorMessageFromValue(payload?.detail) ||
            errorMessageFromValue(payload?.error) ||
            payload?.message ||
            error.message ||
            `Yêu cầu thất bại (${status || 500})`;
        return Promise.reject(new Error(message));
    },
);

type RequestOptions = {
    method?: string;
    body?: unknown;
    headers?: Record<string, string>;
    redirectOnUnauthorized?: boolean;
};

export async function httpRequest<T>(path: string, options: RequestOptions = {}) {
    const {method = "GET", body, headers, redirectOnUnauthorized = true} = options;
    const config: RequestConfig = {
        url: path,
        method,
        data: body,
        headers,
        redirectOnUnauthorized,
    };
    const response = await request.request<T>(config);
    return response.data;
}
