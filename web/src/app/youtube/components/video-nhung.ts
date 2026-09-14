"use client";

/**
 * Điều khiển khung nhúng YouTube bằng postMessage — không nạp script ngoài
 * (CSP đích của c2a chỉ cho script cùng nguồn).
 *
 * Đo trong Chrome 14/09/2026: với `enablejsapi=1&origin=…`, trang nói "listening"
 * thì khung gửi trạng thái (`infoDelivery`: playerState, currentTime) và nhận
 * lệnh playVideo / pauseVideo / seekTo / mute / unMute / loadVideoById (đổi bài
 * không nạp lại khung), báo hết bài bằng playerState 0.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { BaiHat } from "./lib";

export const GOC_NHUNG = "https://www.youtube-nocookie.com";
const MA_VIDEO = /^[A-Za-z0-9_-]{11}$/;

export type CheDoXem = "vua" | "rap" | "nho";

export function laVideo(bai: BaiHat | null | undefined): bai is BaiHat {
  return !!bai && bai.source === "youtube" && MA_VIDEO.test(bai.id);
}

export function srcNhung(id: string, tatTieng: boolean): string {
  const p = new URLSearchParams({ enablejsapi: "1", autoplay: "1", rel: "0", playsinline: "1", origin: window.location.origin });
  if (tatTieng) p.set("mute", "1");
  return `${GOC_NHUNG}/embed/${id}?${p}`;
}

/** playerState của YouTube: -1 chưa chạy, 0 hết, 1 đang phát, 2 tạm dừng, 3 đang tải, 5 đã nạp. */
export type VideoNhung = {
  /** Gắn vào `ref` của iframe. */
  ganKhung: (el: HTMLIFrameElement | null) => void;
  sanSang: boolean;
  trangThai: number;
  lenh: (func: string, args?: unknown[]) => void;
  thoiGian: () => number;
  khiNap: () => void;
  datLai: () => void;
};

export function useVideoNhung(khiHet: () => void): VideoNhung {
  const khung = useRef<HTMLIFrameElement>(null);
  const [sanSang, setSanSang] = useState(false);
  const [trangThai, setTrangThai] = useState(-1);
  const moc = useRef({ t: 0, luc: 0, trangThai: -1, sanSang: false });
  const khiHetMoi = useRef(khiHet);
  const henBatTay = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  useEffect(() => {
    khiHetMoi.current = khiHet;
  });

  const gui = useCallback((o: Record<string, unknown>) => {
    khung.current?.contentWindow?.postMessage(JSON.stringify({ ...o, id: 1, channel: "widget" }), GOC_NHUNG);
  }, []);

  const lenh = useCallback((func: string, args: unknown[] = []) => gui({ event: "command", func, args }), [gui]);

  useEffect(() => {
    const doi = (s: number) => {
      if (!Number.isFinite(s) || s === moc.current.trangThai) return;
      moc.current.trangThai = s;
      setTrangThai(s);
      if (s === 0) khiHetMoi.current();
    };
    const nghe = (e: MessageEvent) => {
      if (e.origin !== GOC_NHUNG || !khung.current || e.source !== khung.current.contentWindow) return;
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
      const info = d.info as { currentTime?: unknown; playerState?: unknown } | null;
      if ((d.event === "infoDelivery" || d.event === "initialDelivery") && info && typeof info === "object") {
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
  }, []);

  const khiNap = useCallback(() => {
    // Khung chỉ báo trạng thái sau khi trang nói đang nghe.
    clearInterval(henBatTay.current);
    let lan = 0;
    henBatTay.current = setInterval(() => {
      if (moc.current.sanSang || ++lan > 40) {
        clearInterval(henBatTay.current);
        return;
      }
      gui({ event: "listening" });
      lenh("addEventListener", ["onStateChange"]);
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
  }, []);

  const thoiGian = useCallback(
    () => moc.current.t + (moc.current.trangThai === 1 && moc.current.luc ? (Date.now() - moc.current.luc) / 1000 : 0),
    [],
  );

  return { ganKhung, sanSang, trangThai, lenh, thoiGian, khiNap, datLai };
}
