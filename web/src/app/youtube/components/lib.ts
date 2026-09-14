import { toast } from "sonner";

import { httpRequest } from "@/lib/request";

export type Nguon = "youtube" | "zing" | "http";

export type ThietBi = {
  entity_id: string;
  ten: string;
  trang_thai: string;
  loai: "tivi" | "loa";
  nen_tang: string;
  am_luong: number | null;
  chinh_am_luong: boolean;
  tam_dung: boolean;
  dung: boolean;
  /** Loa tua được (bit SEEK) — để loa nhập vào video đang xem thì tua tới chỗ hình. */
  tua: boolean;
  /** Giây đang phát, máy chủ tính tới lúc trả lời; null nếu loa không báo. */
  vi_tri: number | null;
  /** Độ dài bài loa báo (media_duration), giây. */
  thoi_luong: number | null;
  tieu_de: string;
  nghe_si: string;
  an: boolean;
  transport: string;
  phat_duoc: boolean;
  youtube: "goc" | "am_thanh";
};

export type BaiHat = {
  source: Nguon;
  kind?: string;
  id: string;
  url: string;
  title: string;
  channel?: string;
  artist?: string;
  duration: number | null;
  thumbnail: string;
  playlist_id?: string;
  media_content_type?: string;
};

/** Một phiên = một nhóm loa phát chung một bài (mỗi loa thuộc một phiên). */
export type Phien = {
  session_id: string;
  controller?: string;
  revision: number;
  state: string;
  item: BaiHat | null;
  queue: { index: number; items: BaiHat[] };
  output_entity_ids: string[];
};

export type KetNoi = { url: string; token: string; url_lan: string };

type Tra<T> = T & { ok: boolean; error?: string };

/** GET/POST tới `/api/youtube-phat/*`; `ok=false` thì báo toast câu máy chủ gửi và trả null. */
export async function goi<T>(path: string, body?: Record<string, unknown>): Promise<Tra<T> | null> {
  try {
    const res = await httpRequest<Tra<T>>(`/api/youtube-phat/${path}`, body ? { method: "POST", body } : { method: "GET" });
    if (!res?.ok) {
      toast.error(res?.error || "Không thực hiện được.");
      return null;
    }
    return res;
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "Lỗi mạng.");
    return null;
  }
}

export function thoiLuong(giay: number | null | undefined): string {
  const v = Number(giay);
  if (!Number.isFinite(v) || v <= 0) return "";
  const h = Math.floor(v / 3600);
  const m = Math.floor((v % 3600) / 60);
  const s = String(Math.floor(v % 60)).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** Nhãn kiểu kết nối — phân biệt hai thực thể cùng tên (FPT Box qua Cast và qua Android TV). */
export const NHAN_KET_NOI: Record<string, string> = {
  google_cast_video: "Tivi Cast · mở YouTube",
  google_cast_audio: "Loa Google Cast",
  google_cast_unknown: "Google Cast · âm thanh",
  android_tv: "Android TV · mở YouTube",
  lg_webos: "Tivi LG · mở YouTube",
  dlna: "DLNA · âm thanh",
  generic_audio: "Loa · âm thanh",
  unsupported: "Không nhận phát nhạc",
};

export const TEN_NGUON: Record<Nguon, string> = { youtube: "YouTube", zing: "Zing MP3", http: "Link audio" };

export function dangHoatDong(tb: ThietBi): boolean {
  return ["playing", "paused", "buffering"].includes(tb.trang_thai);
}

/** Chép vào bộ nhớ tạm. Mở trang bằng http://IP (không phải HTTPS) thì trình duyệt
 *  khoá Clipboard API — khi đó bôi đen sẵn ô để chủ máy tự nhấn Ctrl+C. */
export async function chep(text: string, o: HTMLInputElement | null, nhan: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`Đã copy ${nhan}.`);
  } catch {
    o?.focus();
    o?.select();
    toast.message(`Trình duyệt chặn copy tự động — ${nhan} đã được bôi đen, nhấn Ctrl+C.`);
  }
}
