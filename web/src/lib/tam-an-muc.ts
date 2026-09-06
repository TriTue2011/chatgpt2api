/** Tạm ẩn một mục trong checklist «Bắt đầu ở đây», hẹn ngày nhắc lại.
 *
 * **Vì sao cần.** Có mục người dùng đã cân nhắc và quyết định chưa làm — proxy
 * khi mạng nhà chưa bị chặn, kiểm duyệt khi chưa cho ai ngoài dùng. Nếu checklist
 * cứ nhắc mãi thì nó thành thứ để lờ đi, và lúc đó nó cũng thôi cảnh báo được
 * những việc thật sự cần.
 *
 * **Vì sao để trong trình duyệt chứ không lưu vào cấu hình máy chủ.** Đây là lựa
 * chọn HIỂN THỊ của một người, không phải trạng thái của hệ thống: giấu lời nhắc
 * không làm hệ thống đổi gì. Ghi vào `config.json` sẽ khiến một quản trị viên bấm
 * bỏ qua là người kia cũng mất lời nhắc, và một thao tác giao diện thuần lại đi
 * sửa tệp cấu hình chung.
 *
 * **Không giấu vĩnh viễn.** Mọi lựa chọn đều có hạn; hết hạn là mục hiện lại. Số
 * mục đang ẩn luôn hiển thị kèm nút hiện lại, nên không có gì biến mất lặng lẽ.
 */

const KHOA = "chatgpt2api:checklist_tam_an";

/** Các mốc nhắc lại, tính bằng ngày. */
export const MOC_NHAC: { ngay: number; nhan: string }[] = [
  { ngay: 1, nhan: "1 ngày" },
  { ngay: 5, nhan: "5 ngày" },
  { ngay: 15, nhan: "15 ngày" },
  { ngay: 30, nhan: "30 ngày" },
  { ngay: 90, nhan: "90 ngày" },
];

const MOT_NGAY = 24 * 60 * 60 * 1000;

/** `{ id mục: mốc thời gian hiện lại }`. Đọc hỏng thì coi như chưa ẩn gì. */
export function docTamAn(): Record<string, number> {
  try {
    const raw = localStorage.getItem(KHOA);
    if (!raw) return {};
    const d = JSON.parse(raw) as unknown;
    if (!d || typeof d !== "object" || Array.isArray(d)) return {};
    const ra: Record<string, number> = {};
    for (const [k, v] of Object.entries(d as Record<string, unknown>)) {
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) ra[k] = n;
    }
    return ra;
  } catch {
    // Cửa sổ ẩn danh hoặc trình duyệt chặn lưu trữ: coi như không ẩn mục nào.
    // Thà nhắc thừa còn hơn giấu mất một việc người dùng cần biết.
    return {};
  }
}

function ghi(d: Record<string, number>): void {
  try {
    localStorage.setItem(KHOA, JSON.stringify(d));
  } catch {
    // Ghi hỏng thì mục sẽ hiện lại ở lần tải sau — hướng an toàn.
  }
}

/** Ẩn `id` và hẹn hiện lại sau `soNgay`. */
export function datTamAn(id: string, soNgay: number): Record<string, number> {
  const d = docTamAn();
  d[id] = Date.now() + Math.max(1, soNgay) * MOT_NGAY;
  ghi(d);
  return d;
}

/** Bỏ ẩn `id`; không truyền `id` thì bỏ ẩn tất cả. */
export function boTamAn(id?: string): Record<string, number> {
  if (!id) {
    ghi({});
    return {};
  }
  const d = docTamAn();
  delete d[id];
  ghi(d);
  return d;
}

/** Còn trong hạn ẩn không. Hết hạn thì tự coi như hiện lại. */
export function dangAn(d: Record<string, number>, id: string, bayGio = Date.now()): boolean {
  const t = d[id];
  return typeof t === "number" && t > bayGio;
}

/** Còn bao nhiêu ngày nữa thì mục hiện lại (làm tròn lên, tối thiểu 1). */
export function conLaiNgay(d: Record<string, number>, id: string, bayGio = Date.now()): number {
  const t = d[id];
  if (typeof t !== "number" || t <= bayGio) return 0;
  return Math.max(1, Math.ceil((t - bayGio) / MOT_NGAY));
}
