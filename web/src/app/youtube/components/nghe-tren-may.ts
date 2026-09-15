"use client";

/**
 * Tiếng phát TRÊN MÁY ĐANG MỞ TRANG (thẻ <audio>) — giữ ngoài component tab YouTube.
 *
 * Chủ máy 14/09/2026: "Sau khi chuyển tab quay lại thì không thấy youtube hiển thị gì
 * nữa. Nhưng vẫn đổi bài và nghe được. Chỉ mất khi refresh". Trước đây thẻ <audio> và
 * bài đang nghe nằm trong state của `TrinhPhat`: sang trang khác thì component bị gỡ,
 * thẻ <audio> vẫn chạy (và tự sang bài) nhưng bản `TrinhPhat` mới dựng lại từ đầu, không
 * biết gì về nó. Kho này sống theo trang web (hết khi tải lại trang), component chỉ đọc
 * và ra lệnh: quay lại tab là thấy đúng bài, tiến độ, hàng đợi và vẫn điều khiển được.
 *
 * Hai chế độ dùng chung một thẻ <audio>:
 * - Nghe một mình (`bai` khác null): hàng đợi trên trang, hết bài tự sang bài kế ngay
 *   cả khi không mở tab YouTube, có nút trên màn hình khoá.
 * - Nghe cùng loa (`cungLoa`): component tab nạp bài của loa và bám vị trí loa.
 */

import { toast } from "sonner";

import { type BaiHat, goi, TEN_NGUON } from "./lib";

export type Hang = { items: BaiHat[]; index: number };
export type TrangThaiNghe = { bai: BaiHat | null; hang: Hang | null; chay: boolean; cungLoa: boolean };

export const KHOA_NGHE_NEN = "c2a-youtube:nghe-khi-tat-man-hinh";

// Nửa giây im lặng: phát ngay trong cú bấm để Safari/iOS mở khoá thẻ âm thanh, rồi
// mới đổi sang luồng thật khi máy chủ trả link (lúc đó cú bấm đã qua).
const AM_LANG = "data:audio/wav;base64,UklGRrQBAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YZABAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA";

const TRONG: TrangThaiNghe = { bai: null, hang: null, chay: false, cungLoa: false };

let am: HTMLAudioElement | null = null;
let trangThai: TrangThaiNghe = TRONG;
let luot = 0;
let mucCungLoa = "";
let dungKhiAn = false;
const nguoiNghe = new Set<() => void>();

function dat(moi: Partial<TrangThaiNghe>) {
  trangThai = { ...trangThai, ...moi };
  nguoiNghe.forEach((bao) => bao());
}

/** Cho `useSyncExternalStore`. */
export function dangKy(bao: () => void): () => void {
  nguoiNghe.add(bao);
  return () => {
    nguoiNghe.delete(bao);
  };
}

export const layTrangThai = () => trangThai;
export const layTrangThaiMayChu = () => TRONG;

export function ngheNenDangBat(): boolean {
  try {
    return localStorage.getItem(KHOA_NGHE_NEN) === "1";
  } catch {
    return false;
  }
}

/** Thẻ <audio> đang phát luồng thật (không phải đoạn im lặng mở khoá). */
export function amThat(): HTMLAudioElement | null {
  const src = am?.getAttribute("src");
  return am && src && !src.startsWith("data:") ? am : null;
}

function theAm(): HTMLAudioElement {
  if (am) return am;
  const a = new Audio();
  a.preload = "auto";
  a.addEventListener("play", () => dat({ chay: true }));
  a.addEventListener("pause", () => dat({ chay: false }));
  a.addEventListener("ended", () => {
    // Hết bài khi nghe một mình: sang bài kế, kể cả khi đang ở trang khác.
    if (amThat() && trangThai.bai && !trangThai.cungLoa) chuyen(1);
  });
  a.addEventListener("error", () => {
    if (amThat()) toast.error("Không phát được bài này trên máy này.");
  });
  // Nút "Nghe khi tắt màn hình" đang tắt: trang bị ẩn thì dừng, mở lại thì phát tiếp —
  // chỉ phát tiếp những gì chính đoạn này đã dừng.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      if (!ngheNenDangBat() && amThat() && !a.paused) {
        a.pause();
        dungKhiAn = true;
      }
    } else if (dungKhiAn) {
      dungKhiAn = false;
      void a.play().catch(() => undefined);
    }
  });
  am = a;
  return a;
}

/** Mở khoá thẻ âm thanh ngay trong cú bấm mở video (nếu chưa phát gì), để lỡ khung
 *  YouTube bị chặn tiếng tự phát thì trang vẫn phát được tiếng bằng thẻ này. */
export function moKhoaTruoc() {
  if (!amThat()) moKhoa();
}

/** Phải gọi ngay trong cú bấm (trước mọi `await`). */
function moKhoa(): HTMLAudioElement {
  const a = theAm();
  a.src = AM_LANG;
  void a.play().catch(() => undefined);
  return a;
}

function manHinhKhoa(bai: BaiHat | null) {
  if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
  const ms = navigator.mediaSession;
  const hanhDong = (ten: MediaSessionAction, lam: MediaSessionActionHandler | null) => {
    try {
      ms.setActionHandler(ten, lam);
    } catch {
      // Trình duyệt không hỗ trợ hành động này.
    }
  };
  if (!bai) {
    ms.metadata = null;
    for (const ten of ["play", "pause", "previoustrack", "nexttrack", "stop"] as MediaSessionAction[]) hanhDong(ten, null);
    return;
  }
  ms.metadata = new MediaMetadata({
    title: bai.title || bai.id,
    artist: bai.channel || bai.artist || TEN_NGUON[bai.source],
    artwork: /^https?:\/\//.test(bai.thumbnail || "") ? [{ src: bai.thumbnail }] : [],
  });
  hanhDong("play", () => void am?.play().catch(() => undefined));
  hanhDong("pause", () => am?.pause());
  hanhDong("previoustrack", () => void chuyen(-1));
  hanhDong("nexttrack", () => void chuyen(1));
  hanhDong("stop", () => dung());
}

/** Nghe một bài trên máy này; `batDau` = giây bắt đầu (chuyển từ video sang). */
export async function ngheBai(bai: BaiHat, hang: Hang, batDau = 0): Promise<void> {
  const a = moKhoa();
  const lan = ++luot;
  mucCungLoa = "";
  dat({ bai, hang, cungLoa: false });
  manHinhKhoa(bai);
  const ke = hang.items[hang.index + 1];
  const r = await goi<{ url: string }>("nghe", {
    source: bai.source,
    target: bai.url || bai.id,
    ...(ke && ke.source !== "http" ? { ke } : {}),
  });
  if (lan !== luot) return;
  if (!r) {
    dung();
    return;
  }
  a.src = r.url;
  if (batDau >= 1) a.addEventListener("loadedmetadata", () => { a.currentTime = batDau; }, { once: true });
  a.play().catch(() => toast.message("Trình duyệt chặn tự phát có tiếng — bấm ▶ để nghe."));
}

/** Bài kế (+1) / bài trước (-1) của hàng đợi trên trang; false = hết hàng. */
export function chuyen(buoc: number): boolean {
  const { hang } = trangThai;
  const bai = hang?.items[hang.index + buoc];
  if (!hang || !bai || bai.source === "http") return false;
  void ngheBai(bai, { ...hang, index: hang.index + buoc });
  return true;
}

export function phatTamDung() {
  const a = amThat();
  if (!a) return;
  if (a.paused) void a.play().catch(() => undefined);
  else a.pause();
}

function tatAm() {
  luot++;
  mucCungLoa = "";
  if (am) {
    am.pause();
    am.removeAttribute("src");
    am.load();
  }
}

export function dung() {
  tatAm();
  dat({ bai: null, hang: null, chay: false, cungLoa: false });
  manHinhKhoa(null);
}

export function viTri(): { giay: number; tong: number } | null {
  const a = amThat();
  if (!a) return null;
  return { giay: a.currentTime, tong: Number.isFinite(a.duration) && a.duration > 0 ? a.duration : Number(trangThai.bai?.duration || 0) };
}

export const thoiGian = () => amThat()?.currentTime ?? 0;

/** Bắt đầu nghe cùng loa; phải gọi ngay trong cú bấm. */
export function batCungLoa() {
  if (trangThai.bai) dung();
  moKhoa();
  mucCungLoa = "";
  dat({ cungLoa: true });
}

export function tatCungLoa() {
  tatAm();
  dat({ cungLoa: false, chay: false });
}

/** Nạp bài của loa đang xem (bỏ qua nếu đang là bài đó). */
export async function taiCungLoa(bai: BaiHat): Promise<void> {
  const muc = `${bai.source}:${bai.url || bai.id}`;
  if (mucCungLoa === muc) return;
  mucCungLoa = muc;
  const lan = ++luot;
  const r = await goi<{ url: string }>("nghe", { source: bai.source, target: bai.url || bai.id });
  if (lan !== luot || !r || !trangThai.cungLoa) return;
  const a = theAm();
  a.src = r.url;
  a.play().catch(() => toast.message("Trình duyệt chặn tự phát có tiếng — bấm lại nút nghe trên máy này."));
}
