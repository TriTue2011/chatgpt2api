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
import { cachXuLyTuChoi } from "./tu-choi-phat";

export type Hang = { items: BaiHat[]; index: number };
/** `tuChoi` = lý do trình duyệt không phát tiếng bài đang nghe ("" = không có). */
export type TrangThaiNghe = { bai: BaiHat | null; hang: Hang | null; chay: boolean; cungLoa: boolean; tuChoi: string };

export const KHOA_NGHE_NEN = "c2a-youtube:nghe-khi-tat-man-hinh";

// Nửa giây im lặng: phát ngay trong cú bấm để Safari/iOS mở khoá thẻ âm thanh, rồi
// mới đổi sang luồng thật khi máy chủ trả link (lúc đó cú bấm đã qua).
const AM_LANG = "data:audio/wav;base64,UklGRrQBAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YZABAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA";

const TRONG: TrangThaiNghe = { bai: null, hang: null, chay: false, cungLoa: false, tuChoi: "" };

let am: HTMLAudioElement | null = null;
let trangThai: TrangThaiNghe = TRONG;
let luot = 0;
// Tăng mỗi lần đổi nguồn. Sự kiện `error` của nguồn cũ tới muộn thì bỏ.
let lanNguon = 0;
let mucCungLoa = "";
let dungKhiAn = false;
let henAn: ReturnType<typeof setTimeout> | undefined;
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
  /* PHẦN TỬ PHẢI NẰM TRONG TRANG. `new Audio()` tạo một phần tử rời, không gắn vào đâu
     cả — và khung web của app Home Assistant chỉ chịu đi lấy dữ liệu cho phần tử rời ấy
     khi trang bị ẩn rồi hiện lại. Chủ máy đo 21/09/2026 trên thẻ dùng cùng mô hình:
     "thoát app ra rồi vào lại là nghe được luôn, nhưng nếu không thoát là tiếng mãi
     không nghe được. iPhone tương tự". */
  a.setAttribute("playsinline", "");
  a.setAttribute("webkit-playsinline", "");
  Object.assign(a.style, {
    position: "fixed", top: "-9999px", left: "-9999px",
    width: "1px", height: "1px", opacity: "0.01",
  });
  document.body.append(a);
  a.addEventListener("play", () => dat({ chay: true }));
  a.addEventListener("pause", () => dat({ chay: false }));
  a.addEventListener("playing", () => {
    if (trangThai.tuChoi) dat({ tuChoi: "" });
  });
  a.addEventListener("ended", () => {
    // Hết bài khi nghe một mình: sang bài kế, kể cả khi đang ở trang khác.
    if (amThat() && trangThai.bai && !trangThai.cungLoa) chuyen(1);
  });
  a.addEventListener("error", () => {
    const ma = a.error?.code;
    // 1 = MEDIA_ERR_ABORTED: đổi nguồn thì trình duyệt huỷ lượt cũ, không phải hỏng.
    if (!ma || ma === 1) return;
    const lan = lanNguon;
    // Chờ một nhịp. Chrome Android báo lỗi rồi vẫn phát được; chỉ kết luận khi
    // lỗi còn đó và vẫn là nguồn này.
    setTimeout(() => {
      if (lan !== lanNguon || !amThat() || !a.error || a.error.code === 1) return;
      dat({ tuChoi: `MediaError ${a.error.code}` });
      toast.error(`Không phát được bài này trên máy này (mã lỗi ${a.error.code}).`);
    }, 400);
  });
  // Nút "Nghe khi tắt màn hình" đang tắt: trang bị ẩn thì dừng, mở lại thì phát tiếp —
  // chỉ phát tiếp những gì chính đoạn này đã dừng.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      // Ứng dụng Home Assistant báo trang ẩn trong chốc lát khi vào toàn màn hình (chủ máy
      // 15/09/2026: "phóng to dừng video"): toàn màn hình là đang xem, không phải tắt màn hình.
      // Nó có thể báo ẩn trước khi toàn màn hình kịp bắt đầu, nên nửa giây sau xét lại: tắt
      // màn hình thật thì lúc đó vẫn ẩn.
      clearTimeout(henAn);
      henAn = setTimeout(() => {
        if (document.visibilityState !== "hidden" || document.fullscreenElement) return;
        if (!ngheNenDangBat() && amThat() && !a.paused) {
          a.pause();
          dungKhiAn = true;
        }
      }, 500);
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

// Link tiếng xin trước khi mở video (máy chủ ký một giờ): dùng lại trong mười phút.
const linkXinTruoc = new Map<string, { luc: number; tra: Promise<{ url: string } | null>; url?: string }>();
const khoaLink = (bai: BaiHat) => `${bai.source}:${bai.url || bai.id}`;

/** Xin sẵn link tiếng của video vừa mở: khung YouTube bị chặn tiếng tự phát thì tiếng
 *  chuyển sang thẻ này ngay, không phải chờ máy chủ giải bài. Hỏng thì im lặng. */
export function taiTruoc(bai: BaiHat) {
  const khoa = khoaLink(bai);
  const co = linkXinTruoc.get(khoa);
  if (bai.source === "http" || (co && Date.now() - co.luc < 600000)) return;
  const tra = goi<{ url: string }>("nghe", { source: bai.source, target: bai.url || bai.id }, true).then((r) => {
    if (!r) linkXinTruoc.delete(khoa);
    // Giữ luôn địa chỉ đã giải: lúc bấm còn dùng được NGAY, không phải chờ lời hứa.
    else {
      const muc = linkXinTruoc.get(khoa);
      if (muc) muc.url = r.url;
    }
    return r;
  });
  linkXinTruoc.set(khoa, { luc: Date.now(), tra });
}

async function linkSan(bai: BaiHat): Promise<{ url: string } | null> {
  const co = linkXinTruoc.get(khoaLink(bai));
  return co && Date.now() - co.luc < 600000 ? co.tra : null;
}

/** Đặt nguồn rồi phát, vào đúng giây bằng mảnh địa chỉ `#t=` — không chờ
 *  `loadedmetadata` rồi mới tua, vì cú tua muộn ấy còn đè lên vị trí mới hơn mà vòng
 *  canh vừa đặt (dựng lại được trong Chrome 21/09/2026: tiếng nhảy lùi hai giây). */
function datNguon(a: HTMLAudioElement, url: string, batDau: number, goiY?: string) {
  lanNguon++;
  a.src = batDau >= 1 ? `${url}#t=${Math.floor(batDau)}` : url;
  // Gán `src` chưa xoá `error` của nguồn cũ trong cùng lượt. Không gọi `load()`
  // thì `play()` nhìn lỗi cũ và từ chối NotSupportedError dù nguồn mới phát được.
  a.load();
  phatHoacThuLai(a, goiY);
}

/** play() bị từ chối. NotSupportedError lúc nguồn chưa có lỗi thì thử lại khi đã
 *  có dữ liệu — xem `cachXuLyTuChoi`. */
function phatHoacThuLai(a: HTMLAudioElement, goiY?: string, daThuLai = false) {
  const lan = lanNguon;
  void a.play().catch((e: unknown) => {
    if (lan !== lanNguon) return;
    const ten = e instanceof DOMException ? e.name : "Error";
    const cach = cachXuLyTuChoi(ten, !!a.error, daThuLai);
    if (cach === "bo") return;
    if (cach === "lai") {
      let xong = false;
      const lai = () => {
        if (xong) return;
        xong = true;
        a.removeEventListener("loadeddata", lai);
        a.removeEventListener("canplay", lai);
        if (lan !== lanNguon || !amThat()) return;
        phatHoacThuLai(a, goiY, true);
      };
      if (a.readyState >= 2) lai();
      else {
        a.addEventListener("loadeddata", lai);
        a.addEventListener("canplay", lai);
      }
      return;
    }
    tuChoiPhat(e, goiY);
  });
}

/** play() bị từ chối và đây là kết luận (không phải lượt đổi nguồn). */
function tuChoiPhat(e: unknown, goiY = "bấm ▶ để nghe") {
  const ten = e instanceof DOMException ? e.name : "Error";
  if (cachXuLyTuChoi(ten, true, true) !== "bao") return;
  dat({ tuChoi: ten });
  if (ten === "NotAllowedError") toast.message(`Trình duyệt chặn tự phát có tiếng — ${goiY}.`);
  else toast.error(`Máy này không phát được tiếng bài này (${ten}).`);
}

/** Nghe một bài trên máy này; `batDau` = giây bắt đầu (chuyển từ video sang). */
export async function ngheBai(bai: BaiHat, hang: Hang, batDau = 0): Promise<void> {
  /* MỘT CÚ BẤM CHỈ CHỨNG NHẬN MỘT LẦN PHÁT. Mở khoá bằng đoạn im lặng rồi mới đổi `src`
     sang bài thật nghĩa là cú bấm chứng nhận cho đoạn im lặng; bài thật bị coi là tự phát
     nên nằm im ở "đang tải mà không có byte nào" tới khi app được đánh thức lại — chủ máy
     21/09/2026: "vẫn phải ẩn app xuống, bật app khác rồi chọn lại app HA mới hát".
     Có sẵn địa chỉ thì đặt thẳng bài thật, không mở khoá nữa. */
  const san = linkXinTruoc.get(khoaLink(bai));
  const coSan = !!san?.url && Date.now() - san.luc < 600000;
  const a = coSan ? theAm() : moKhoa();
  const lan = ++luot;
  mucCungLoa = "";
  dat({ bai, hang, cungLoa: false, tuChoi: "" });
  manHinhKhoa(bai);
  const ke = hang.items[hang.index + 1];
  // Có sẵn thì phát ngay tại đây, không `await` gì — xem chú thích đầu hàm.
  if (coSan && san) {
    datNguon(a, san.url as string, batDau);
    return;
  }
  const r = (await linkSan(bai)) ?? await goi<{ url: string }>("nghe", {
    source: bai.source,
    target: bai.url || bai.id,
    ...(ke && ke.source !== "http" ? { ke } : {}),
  });
  if (lan !== luot) return;
  if (!r) {
    dung();
    return;
  }
  datNguon(a, r.url, batDau);
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
  if (a.paused) phatHoacThuLai(a);
  else a.pause();
}

function tatAm() {
  luot++;
  lanNguon++;
  mucCungLoa = "";
  if (am) {
    am.pause();
    am.removeAttribute("src");
    am.load();
  }
}

export function dung() {
  tatAm();
  dat({ bai: null, hang: null, chay: false, cungLoa: false, tuChoi: "" });
  manHinhKhoa(null);
}

export function viTri(): { giay: number; tong: number } | null {
  const a = amThat();
  if (!a) return null;
  return { giay: a.currentTime, tong: Number.isFinite(a.duration) && a.duration > 0 ? a.duration : Number(trangThai.bai?.duration || 0) };
}

export const thoiGian = () => amThat()?.currentTime ?? 0;

/** Bắt đầu nghe cùng loa; phải gọi ngay trong cú bấm.
 *
 *  `bai` + `batDau` để PHÁT NGAY TRONG CHÍNH CÚ BẤM khi địa chỉ luồng đã xin sẵn.
 *  Trình duyệt chỉ chắc chắn cho phát khi lệnh phát nằm trong cử chỉ người dùng; đi qua
 *  một `await` là đã ra ngoài. Chủ máy đo 21/09/2026 trên thẻ Home Assistant dùng cùng
 *  mô hình: "tiếng rất lâu mới nghe thấy hoặc phải thao tác vào nghe khi tắt màn" — tức
 *  phải chạm thêm lần nữa mới có tiếng. Vào đúng giây bằng mảnh địa chỉ `#t=`, khỏi chờ
 *  `loadedmetadata` rồi mới tua.
 */
export function batCungLoa(bai?: BaiHat | null, batDau = 0) {
  if (trangThai.bai) dung();
  // Có sẵn địa chỉ thì KHÔNG mở khoá bằng đoạn im lặng — xem chú thích ở «ngheBai».
  const san = bai ? linkXinTruoc.get(khoaLink(bai)) : undefined;
  const coSan = !!san?.url && Date.now() - san.luc < 600000;
  const a = coSan ? theAm() : moKhoa();
  mucCungLoa = "";
  dat({ cungLoa: true });
  if (bai && coSan && san?.url) {
    mucCungLoa = `${bai.source}:${bai.url || bai.id}`;
    luot++;
    datNguon(a, san.url, batDau);
  }
}

export function tatCungLoa() {
  tatAm();
  dat({ cungLoa: false, chay: false });
}

/** Nạp bài của loa đang xem (bỏ qua nếu đang là bài đó); `batDau` = giây loa đang ở. */
export async function taiCungLoa(bai: BaiHat, batDau = 0): Promise<void> {
  const muc = `${bai.source}:${bai.url || bai.id}`;
  if (mucCungLoa === muc) return;
  mucCungLoa = muc;
  const lan = ++luot;
  // Dùng lại link đã xin sẵn nếu có — bớt trọn một lượt hỏi máy chủ (đo: 1,0–1,6 giây).
  const r = (await linkSan(bai)) ?? await goi<{ url: string }>("nghe", { source: bai.source, target: bai.url || bai.id });
  if (lan !== luot || !r || !trangThai.cungLoa) return;
  const a = theAm();
  /* Vào đúng chỗ NGAY TRONG ĐỊA CHỈ (`#t=`), đừng chờ `loadedmetadata` rồi mới tua: cú
     tua muộn ấy còn đè lên vị trí mới hơn mà vòng canh vừa đặt — dựng lại được trong
     Chrome 21/09/2026, tiếng nhảy lùi hai giây ngay khi vừa bắt đầu. */
  datNguon(a, r.url, batDau, "bấm lại nút nghe trên máy này");
}
