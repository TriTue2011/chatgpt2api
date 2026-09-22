/** Lời từ chối của `play()` xử lý thế nào.
 *
 * `play()` xét trạng thái phần tử ngay lúc gọi, không phải kết quả đã kiểm của
 * nguồn mới. Chrome trên Android hay trả `NotSupportedError` trong lượt vừa gán
 * `src` (đường không có đuôi tệp, kiểu nội dung chưa biết) rồi nguồn đó vẫn phát
 * được — đo 22/09/2026 với bài vF4UE-dOMdg: báo lỗi, một lúc sau vẫn chạy, xem
 * lại có lúc không bị. Kết luận «không phát được» chỉ thuộc sự kiện `error` của
 * phần tử khi lỗi còn gắn với đúng nguồn này.
 */
export type CachXuLyTuChoi = "bo" | "lai" | "bao";

export function cachXuLyTuChoi(ten: string, coLoi: boolean, daThuLai: boolean): CachXuLyTuChoi {
  if (ten === "AbortError") return "bo";
  if (ten === "NotSupportedError") return !coLoi && !daThuLai ? "lai" : "bo";
  return "bao";
}
