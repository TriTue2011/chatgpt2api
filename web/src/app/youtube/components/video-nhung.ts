"use client";

/**
 * Điều khiển khung nhúng YouTube bằng postMessage — không nạp script ngoài
 * (CSP đích của c2a chỉ cho script cùng nguồn).
 *
 * Đo trong Chrome 14/09/2026: với `enablejsapi=1&origin=…`, trang nói "listening"
 * thì khung gửi trạng thái (`infoDelivery`: playerState, currentTime) và nhận
 * lệnh playVideo / pauseVideo / seekTo / mute / unMute / loadVideoById (đổi bài
 * không nạp lại khung), báo hết bài bằng playerState 0.
 *
 * YouTube từ chối một số video trong khung nhúng (video hãng đĩa như VEVO khi trang
 * mở bằng địa chỉ IP — đo 14/09/2026: "M2M - The Day You Went Away" bị chặn, mở bằng
 * tên máy thì phát được): khung gửi `onError`, `khiLoi` báo cho trình phát. Khi đó
 * trang phát HÌNH RIÊNG (luồng chỉ-hình qua máy chủ) bằng thẻ <video> gắn qua `ganHinh`:
 * mọi lệnh và trạng thái chuyển sang thẻ đó, phần còn lại của trình phát không đổi.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { BaiHat } from "./lib";

export const GOC_NHUNG = "https://www.youtube-nocookie.com";
const MA_VIDEO = /^[A-Za-z0-9_-]{11}$/;

export type CheDoXem = "vua" | "rap" | "nho";

export function laVideo(bai: BaiHat | null | undefined): bai is BaiHat {
  return !!bai && bai.source === "youtube" && MA_VIDEO.test(bai.id);
}

export function srcNhung(id: string, tatTieng: boolean, batDau = 0): string {
  const p = new URLSearchParams({ enablejsapi: "1", autoplay: "1", rel: "0", playsinline: "1", origin: window.location.origin });
  if (tatTieng) p.set("mute", "1");
  if (batDau >= 1) p.set("start", String(Math.floor(batDau)));
  return `${GOC_NHUNG}/embed/${id}?${p}`;
}

/** playerState của YouTube: -1 chưa chạy, 0 hết, 1 đang phát, 2 tạm dừng, 3 đang tải, 5 đã nạp. */
export type VideoNhung = {
  /** Gắn vào `ref` của iframe. */
  ganKhung: (el: HTMLIFrameElement | null) => void;
  sanSang: boolean;
  trangThai: number;
  /** Khung báo đang tắt tiếng (null = chưa báo). */
  tatTieng: boolean | null;
  lenh: (func: string, args?: unknown[]) => void;
  thoiGian: () => number;
  khiNap: () => void;
  datLai: () => void;
  /** Gắn thẻ <video> hình riêng (null = bỏ). */
  ganHinh: (el: HTMLVideoElement | null) => void;
  /** Tua hình tới chỗ tiếng đang phát, đón trước quãng hình cần để hiện sau khi tua. */
  tuaTheoTieng: (giayTieng: number) => void;
};

export function useVideoNhung(khiHet: () => void, khiLoi: () => void): VideoNhung {
  const khung = useRef<HTMLIFrameElement>(null);
  const [sanSang, setSanSang] = useState(false);
  const [trangThai, setTrangThai] = useState(-1);
  const [tatTieng, setTatTieng] = useState<boolean | null>(null);
  const moc = useRef({ t: 0, luc: 0, trangThai: -1, sanSang: false });
  const khiHetMoi = useRef(khiHet);
  const khiLoiMoi = useRef(khiLoi);
  const hinh = useRef<HTMLVideoElement | null>(null);
  const henBatTay = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  // Hình mất một lúc mới hiện sau khi tua (tải đoạn mới): `don` giây đón trước, đo lại mỗi lần tua.
  const tua = useRef({ don: 0.3, luc: 0 });

  useEffect(() => {
    khiHetMoi.current = khiHet;
    khiLoiMoi.current = khiLoi;
  });

  const gui = useCallback((o: Record<string, unknown>) => {
    khung.current?.contentWindow?.postMessage(JSON.stringify({ ...o, id: 1, channel: "widget" }), GOC_NHUNG);
  }, []);

  const lenh = useCallback((func: string, args: unknown[] = []) => {
    const h = hinh.current;
    if (!h) {
      gui({ event: "command", func, args });
      return;
    }
    // Hình riêng không có tiếng: chỉ phát, dừng, tua.
    if (func === "playVideo") void h.play().catch(() => undefined);
    else if (func === "pauseVideo") h.pause();
    else if (func === "stopVideo") {
      h.pause();
      h.currentTime = 0;
    } else if (func === "seekTo" && typeof args[0] === "number") h.currentTime = args[0];
  }, [gui]);

  const doi = useCallback((s: number) => {
    if (!Number.isFinite(s) || s === moc.current.trangThai) return;
    if (s === 1 && moc.current.trangThai === 3 && tua.current.luc) {
      // Lần tua vừa rồi mất bao lâu mới hiện: quãng đón cho lần sau (trung bình dần, ≤ 1,5 giây).
      const mat = (Date.now() - tua.current.luc) / 1000;
      if (mat < 4) tua.current.don = Math.min(1.5, (tua.current.don + mat) / 2);
      tua.current.luc = 0;
    }
    moc.current.trangThai = s;
    setTrangThai(s);
    if (s === 0) khiHetMoi.current();
  }, []);

  const ganHinh = useCallback((el: HTMLVideoElement | null) => {
    hinh.current = el;
    if (!el) return;
    for (const [ten, s] of [["playing", 1], ["pause", 2], ["waiting", 3], ["ended", 0]] as const) {
      el.addEventListener(ten, () => {
        if (hinh.current === el) doi(el.ended ? 0 : s);
      });
    }
    el.addEventListener("loadeddata", () => {
      if (hinh.current !== el) return;
      moc.current.sanSang = true;
      setSanSang(true);
    });
  }, [doi]);

  useEffect(() => {
    const nghe = (e: MessageEvent) => {
      if (hinh.current || e.origin !== GOC_NHUNG || !khung.current || e.source !== khung.current.contentWindow) return;
      let d: { event?: string; info?: unknown };
      try {
        d = typeof e.data === "string" ? JSON.parse(e.data) : e.data;
      } catch {
        return;
      }
      if (!d || typeof d !== "object") return;
      if (!moc.current.sanSang) {
        moc.current.sanSang = true;
        setSanSang(true);
      }
      if (d.event === "onError") {
        khiLoiMoi.current();
        return;
      }
      const info = d.info as { currentTime?: unknown; playerState?: unknown; muted?: unknown } | null;
      if ((d.event === "infoDelivery" || d.event === "initialDelivery") && info && typeof info === "object") {
        if (typeof info.muted === "boolean") setTatTieng(info.muted);
        if (typeof info.currentTime === "number") {
          moc.current.t = info.currentTime;
          moc.current.luc = Date.now();
        }
        if (typeof info.playerState === "number") doi(info.playerState);
      } else if (d.event === "onStateChange") {
        doi(Number(d.info));
      }
    };
    window.addEventListener("message", nghe);
    return () => {
      window.removeEventListener("message", nghe);
      clearInterval(henBatTay.current);
    };
  }, [doi]);

  const khiNap = useCallback(() => {
    // Khung chỉ báo trạng thái sau khi trang nói đang nghe. Khung vừa nạp trang mới (đổi bài
    // khi trang cũ chưa xong) thì trang mới chưa nghe gì: tin của trang cũ đã đánh dấu sẵn
    // sàng và dừng bắt tay, nên khung mới bỏ qua mọi lệnh — phát, dừng, tắt tiếng (tái hiện
    // trên card Home Assistant 15/09/2026: video đứng yên trong khi tiếng máy chạy).
    if (!hinh.current) {
      moc.current.sanSang = false;
      setSanSang(false);
    }
    clearInterval(henBatTay.current);
    let lan = 0;
    henBatTay.current = setInterval(() => {
      if (moc.current.sanSang || ++lan > 40) {
        clearInterval(henBatTay.current);
        return;
      }
      gui({ event: "listening" });
      lenh("addEventListener", ["onStateChange"]);
      lenh("addEventListener", ["onError"]);
    }, 250);
  }, [gui, lenh]);

  const ganKhung = useCallback((el: HTMLIFrameElement | null) => {
    khung.current = el;
  }, []);

  const datLai = useCallback(() => {
    clearInterval(henBatTay.current);
    moc.current = { t: 0, luc: 0, trangThai: -1, sanSang: false };
    setSanSang(false);
    setTrangThai(-1);
    setTatTieng(null);
  }, []);

  const thoiGian = useCallback(
    () => hinh.current
      ? hinh.current.currentTime
      : moc.current.t + (moc.current.trangThai === 1 && moc.current.luc ? (Date.now() - moc.current.luc) / 1000 : 0),
    [],
  );

  const tuaTheoTieng = useCallback((giayTieng: number) => {
    lenh("seekTo", [giayTieng + tua.current.don, true]);
    tua.current.luc = Date.now();
  }, [lenh]);

  return { ganKhung, sanSang, trangThai, tatTieng, lenh, thoiGian, khiNap, datLai, ganHinh, tuaTheoTieng };
}
