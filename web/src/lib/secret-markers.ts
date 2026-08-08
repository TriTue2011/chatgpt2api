"use client";

/**
 * Máy chủ không trả giá trị bí mật nữa — nó trả nhãn `{"is_set": true}`.
 *
 * Nếu để nguyên nhãn đó chảy vào form, mọi ô secret trong trang Cài đặt sẽ
 * hiện `[object Object]`. Chỗ này đổi nhãn thành chuỗi rỗng (ô trống, đúng
 * nghĩa "không hiển thị bí mật") và ghi lại RIÊNG một bản đồ cho biết trường
 * nào đã có giá trị, để giao diện nói được "đã đặt" mà không cần biết giá trị.
 *
 * Vì sao lưu rỗng lại AN TOÀN khi bấm Lưu: máy chủ coi chuỗi rỗng là "không
 * gửi gì mới" và giữ nguyên giá trị đang chạy (`services/settings_secrets.py`,
 * hàm `loc_ghi`). Muốn xoá hẳn thì phải gửi `clear_secret_fields` — cố ý
 * không có đường xoá bằng cách để trống, vì một ô trống do trang chưa nạp
 * xong là chuyện thường.
 *
 * Hàm này chạy được với CẢ hai kiểu phản hồi — máy chủ chưa bật cờ che thì
 * không có nhãn nào, và mọi thứ đi qua nguyên vẹn.
 */

export type BanDoSecret = Record<string, boolean>;

function laNhanSecret(v: unknown): v is { is_set?: boolean; count?: number } {
    if (!v || typeof v !== "object" || Array.isArray(v)) return false;
    const khoa = Object.keys(v as object);
    return khoa.length > 0 && khoa.every((k) => k === "is_set" || k === "count");
}

function di(nut: unknown, duong: string, banDo: BanDoSecret): unknown {
    if (laNhanSecret(nut)) {
        const daDat = Boolean((nut as { is_set?: boolean }).is_set);
        banDo[duong] = daDat;
        const soLuong = (nut as { count?: number }).count;
        // Trường nhiều khoá (api_keys) trả về mảng rỗng chứ không phải chuỗi:
        // component đang `.map()` trên nó, đưa chuỗi vào là vỡ lúc render.
        return typeof soLuong === "number" ? [] : "";
    }
    if (Array.isArray(nut)) {
        return nut.map((x, i) => di(x, `${duong}[${i}]`, banDo));
    }
    if (nut && typeof nut === "object") {
        const ra: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(nut as Record<string, unknown>)) {
            ra[k] = di(v, duong ? `${duong}.${k}` : k, banDo);
        }
        return ra;
    }
    return nut;
}

/** Trả về cấu hình đã bỏ nhãn, kèm bản đồ `đường.dẫn → đã đặt hay chưa`. */
export function boNhanSecret<T>(config: T): { config: T; daDat: BanDoSecret } {
    const banDo: BanDoSecret = {};
    const ra = di(config, "", banDo) as T;
    return { config: ra, daDat: banDo };
}

/** Số khoá đang có ở một trường dạng danh sách, khi máy chủ chỉ trả số đếm. */
export function demSecret(config: unknown, duong: string): number {
    const phan = duong.split(".");
    let nut: unknown = config;
    for (const p of phan) {
        if (!nut || typeof nut !== "object") return 0;
        nut = (nut as Record<string, unknown>)[p];
    }
    if (laNhanSecret(nut)) return Number((nut as { count?: number }).count || 0);
    return Array.isArray(nut) ? nut.length : 0;
}
