/** Ẩn một mục trong checklist «Bắt đầu ở đây».
 *
 * **Vì sao cần.** Có mục người dùng đã cân nhắc và quyết định chưa làm — proxy
 * khi mạng nhà chưa bị chặn, kiểm duyệt khi chưa cho ai ngoài dùng. Nếu checklist
 * cứ nhắc mãi thì nó thành thứ để lờ đi, và lúc đó nó cũng thôi cảnh báo được
 * những việc thật sự cần.
 *
 * **Lưu ở ĐÂU — và vì sao đổi.** Bản đầu chỉ ghi `localStorage` với lý do "đây là
 * lựa chọn hiển thị của MỘT người, ghi vào config chung thì admin này bấm ẩn là
 * admin kia mất lời nhắc". Lý do đó không đúng với hệ thống này: nó có ĐÚNG MỘT
 * admin, còn `user_keys` chỉ mở được các trang tác vụ chứ không vào cài đặt.
 * Hệ quả thật của cách cũ là ẩn trên máy tính xong mở điện thoại lại thấy đủ,
 * vì `localStorage` gắn với từng trình duyệt.
 *
 * Nay ghi lên `config.van_an_checklist` để mọi thiết bị thấy như nhau.
 * `localStorage` vẫn được giữ làm bộ đệm: đọc được ngay lúc mở trang (khỏi nháy
 * một nhịp mới ẩn) và vẫn dùng được khi mất mạng.
 *
 * **Ẩn vĩnh viễn.** Ngoài các mốc ngày còn có lựa chọn ẩn hẳn. Số mục đang ẩn
 * luôn hiển thị kèm nút hiện lại, nên không có gì biến mất mà không lấy lại được.
 */

import { fetchSettingsConfig, updateSettingsConfig } from "@/lib/api";
import type { SettingsConfig } from "@/lib/api";

const KHOA = "chatgpt2api:checklist_tam_an";
/** Khoá trong config máy chủ — đồng bộ giữa các thiết bị. */
const KHOA_CONFIG = "van_an_checklist";

/** Mốc thời gian của mục ẩn vĩnh viễn. Đủ xa để coi như không bao giờ tới. */
export const VINH_VIEN = 8.64e15; // giới hạn của Date trong JS

/** Các mốc nhắc lại, tính bằng ngày. */
export const MOC_NHAC: { ngay: number; nhan: string }[] = [
  { ngay: 1, nhan: "1 ngày" },
  { ngay: 5, nhan: "5 ngày" },
  { ngay: 15, nhan: "15 ngày" },
  { ngay: 30, nhan: "30 ngày" },
  { ngay: 90, nhan: "90 ngày" },
];

const MOT_NGAY = 24 * 60 * 60 * 1000;

function locHopLe(d: unknown): Record<string, number> {
  if (!d || typeof d !== "object" || Array.isArray(d)) return {};
  const ra: Record<string, number> = {};
  for (const [k, v] of Object.entries(d as Record<string, unknown>)) {
    const n = Number(v);
    if (Number.isFinite(n) && n > 0) ra[k] = n;
  }
  return ra;
}

/** Đọc bộ đệm cục bộ. Hỏng thì coi như chưa ẩn gì. */
export function docTamAn(): Record<string, number> {
  try {
    const raw = localStorage.getItem(KHOA);
    return raw ? locHopLe(JSON.parse(raw) as unknown) : {};
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

/** Đẩy lên máy chủ. Hỏng thì im lặng: bộ đệm cục bộ đã ghi rồi, không chặn thao tác. */
async function dongBoLen(d: Record<string, number>): Promise<void> {
  try {
    await updateSettingsConfig({ [KHOA_CONFIG]: d } as unknown as SettingsConfig);
  } catch {
    // Mất mạng hoặc máy chủ lỗi — lần sau mở trang sẽ đẩy lại.
  }
}

/**
 * Đọc từ máy chủ và trộn với bộ đệm cục bộ.
 *
 * Trộn theo mốc XA HƠN thắng: ẩn ở máy này 30 ngày, máy kia 5 ngày thì giữ 30 —
 * người dùng đã bảo "đừng nhắc nữa", lấy lựa chọn mạnh hơn mới đúng ý.
 */
export async function napTamAn(): Promise<Record<string, number>> {
  const cucBo = docTamAn();
  try {
    // `fetchSettingsConfig` trả BỌC trong { config: … } — đọc thẳng cfg[khoá]
    // luôn ra undefined, và bug đó im lặng: mọi thiết bị đều tưởng chưa ẩn gì.
    const { config: cfg } = await fetchSettingsConfig();
    const tren = locHopLe((cfg as unknown as Record<string, unknown>)?.[KHOA_CONFIG]);
    const gop: Record<string, number> = { ...cucBo };
    for (const [k, v] of Object.entries(tren)) {
      if (!(k in gop) || v > gop[k]) gop[k] = v;
    }
    ghi(gop);
    // Máy này có mục mà máy chủ chưa biết thì đẩy lên cho thiết bị khác thấy.
    const canDay = Object.keys(gop).some((k) => tren[k] !== gop[k]);
    if (canDay) void dongBoLen(gop);
    return gop;
  } catch {
    return cucBo;
  }
}

/** Ẩn `id` và hẹn hiện lại sau `soNgay`; truyền `VINH_VIEN` để ẩn hẳn. */
export function datTamAn(id: string, soNgay: number): Record<string, number> {
  const d = docTamAn();
  d[id] = soNgay >= VINH_VIEN ? VINH_VIEN : Date.now() + Math.max(1, soNgay) * MOT_NGAY;
  ghi(d);
  void dongBoLen(d);
  return d;
}

/** Bỏ ẩn `id`; không truyền `id` thì bỏ ẩn tất cả. */
export function boTamAn(id?: string): Record<string, number> {
  if (!id) {
    ghi({});
    void dongBoLen({});
    return {};
  }
  const d = docTamAn();
  delete d[id];
  ghi(d);
  void dongBoLen(d);
  return d;
}

/** Còn trong hạn ẩn không. Hết hạn thì tự coi như hiện lại. */
export function dangAn(d: Record<string, number>, id: string, bayGio = Date.now()): boolean {
  const t = d[id];
  return typeof t === "number" && t > bayGio;
}

/** Mục này bị ẩn vĩnh viễn chứ không phải hẹn ngày. */
export function anVinhVien(d: Record<string, number>, id: string): boolean {
  return d[id] === VINH_VIEN;
}

/** Còn bao nhiêu ngày nữa thì mục hiện lại (làm tròn lên, tối thiểu 1). */
export function conLaiNgay(d: Record<string, number>, id: string, bayGio = Date.now()): number {
  const t = d[id];
  if (typeof t !== "number" || t <= bayGio) return 0;
  return Math.max(1, Math.ceil((t - bayGio) / MOT_NGAY));
}
