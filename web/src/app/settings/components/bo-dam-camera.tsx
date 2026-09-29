"use client";

/**
 * BoDamCamera — khung bộ đàm ngay trong web c2a: chọn camera → xem trực tiếp + đàm thoại.
 *
 * Chủ máy 24/09/2026: "dùng mic điện thoại … phát ra loa giữ nguyên gốc, rồi nghe
 * được người bên cam nói gì — giống như app Imou", và "làm cả trên c2a".
 * 29/09/2026: "chỗ đàm thoại thêm live cam … có list cam, tích cam nào live cam đó và bật
 * đàm thoại cam đó. Và làm như HA, thêm chế độ tích luôn mic, và chế độ giữ mic để nói."
 *
 * Xem trực tiếp: thẻ `<img>` đọc MJPEG c2a dựng từ luồng camera (`/api/camera/xem/{ten}`) —
 * trình duyệt mở c2a bằng https không gọi thẳng được go2rtc trong mạng nhà.
 *
 * Đàm thoại: một WebSocket hai chiều (`/api/camera/bo_dam/{ten}/ws`): máy chủ gửi tiếng mic
 * camera (PCM16 mono 16 kHz), trình duyệt gửi tiếng mic và chữ `het` khi thôi nói. Máy chủ chỉ
 * mở kênh nói tới camera khi có tiếng người và đóng sau một quãng im — camera tắt mic của nó
 * suốt lúc kênh nói mở, nên thôi nói là nghe lại được bên kia. Hai chế độ:
 *   - «Giữ để nói»: chỉ gửi mic lúc giữ nút.
 *   - «Bật mic luôn»: bấm một lần là gửi mic suốt (như mục 🎙️ của thẻ WebRTC trong HA); máy
 *     chủ tự mở loa khi có tiếng người, im 1,5 giây là đóng để nghe bên kia.
 *
 * WebSocket và `<img>` không gửi được header nên xin vé một lần trước (khuôn SSE của trang Đăng
 * ký). Mic trình duyệt chỉ dùng được trên https.
 *
 * Thoát trang, chuyển tab / ứng dụng khác, tắt màn hình → ĐÓNG bộ đàm (chủ máy 29/09/2026: "khi
 * thoát hay chuyển trang thì cũng thoát bộ đàm"): chuyển trang trong c2a thì React gỡ khung và
 * dọn (mic, WebSocket, hình); trang bị ẩn hay bị rời thì React không gỡ gì — bắt
 * `visibilitychange` / `pagehide`. Thẻ `<img>` đã gỡ khỏi trang vẫn có thể tải tiếp luồng
 * MJPEG, nên phải xoá `src` cho trình duyệt cắt kết nối.
 *
 * Xin quyền mic NGAY KHI MỞ, không đợi lúc bấm nút: bản đầu xin lúc ấn giữ, hộp hỏi quyền hiện
 * lên cướp mất thao tác giữ nút (chủ máy 25/09/2026: "bật bộ đàm rồi không được" — hai phiên,
 * 0 giây ra loa). Vạch mức mic cho thấy mic có thu.
 */

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import webConfig from "@/constants/common-env";
import { request } from "@/lib/request";

const TAN_SO = 16000;
const KHOA_CHE_DO = "c2a_bo_dam_che_do";

type CamBoDam = { loa_kieu?: string; ve_tinh_cong?: number | ""; note?: string };
type CheDoMic = "giu" | "luon";

/** Camera này nói được qua loa không: EZVIZ khai «HCNetSDK», Imou/Dahua có cổng vệ tinh. */
export const noiDuoc = (c: CamBoDam | undefined): boolean =>
  !!c && (c.loa_kieu === "hik" || !!c.ve_tinh_cong);

const goc = () => webConfig.apiUrl.replace(/\/$/, "") || window.location.origin;

const xinVe = async (duong: string): Promise<string> => {
  const r = await request.post(duong, {});
  const ve = (r.data as { ticket?: string })?.ticket;
  if (!ve) throw new Error("không xin được vé");
  return ve;
};

export function BoDamCamera({ cams, ten, doiTen, onClose }: {
  cams: Record<string, CamBoDam>;
  ten: string;
  doiTen: (ten: string) => void;
  onClose: () => void;
}) {
  const [cheDo, setCheDo] = useState<CheDoMic>(() => {
    try { return localStorage.getItem(KHOA_CHE_DO) === "luon" ? "luon" : "giu"; } catch { return "giu"; }
  });
  // Trang bị ẩn / bị rời → đóng hẳn bộ đàm (xem đầu tệp).
  useEffect(() => {
    const an = () => { if (document.visibilityState === "hidden") onClose(); };
    document.addEventListener("visibilitychange", an);
    window.addEventListener("pagehide", onClose);
    return () => {
      document.removeEventListener("visibilitychange", an);
      window.removeEventListener("pagehide", onClose);
    };
  }, [onClose]);

  const chonCheDo = (m: CheDoMic) => {
    setCheDo(m);
    try { localStorage.setItem(KHOA_CHE_DO, m); } catch { /* chế độ riêng tư: không nhớ cũng được */ }
  };

  return (
    <div className="rounded border border-primary/40 p-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">📞 Bộ đàm</span>
        <Button size="sm" variant="outline" className="ml-auto" onClick={onClose}>Đóng</Button>
      </div>

      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Chọn camera">
        {Object.entries(cams).map(([t, c]) => (
          <label key={t}
            className={`flex cursor-pointer items-center gap-1.5 rounded border px-2 py-1 text-sm ${
              t === ten ? "border-primary bg-primary/10" : "border-border"}`}>
            <input type="radio" name="bo-dam-cam" checked={t === ten} onChange={() => doiTen(t)} />
            📷 {t}
            {!noiDuoc(c) ? <span className="text-[11px] text-muted-foreground">(chỉ xem)</span> : null}
          </label>
        ))}
      </div>

      <XemTrucTiep key={`xem-${ten}`} ten={ten} />

      {noiDuoc(cams[ten]) ? (
        <>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Chế độ mic">
            <Button size="sm" variant={cheDo === "giu" ? "default" : "outline"}
              title="Chỉ gửi mic lúc giữ nút — thả ra là nghe bên kia"
              onClick={() => chonCheDo("giu")}>✋ Giữ để nói</Button>
            <Button size="sm" variant={cheDo === "luon" ? "default" : "outline"}
              title="Bấm một lần là mic mở suốt — loa camera tự mở khi bạn nói, im 1,5 giây là nghe bên kia"
              onClick={() => chonCheDo("luon")}>🎙️ Bật mic luôn</Button>
          </div>
          <KenhDam key={`dam-${ten}`} ten={ten} cheDo={cheDo} />
        </>
      ) : (
        <p className="text-xs text-muted-foreground">
          Camera này chưa khai loa (Sửa → «🔊 Loa», hoặc cổng vệ tinh cho Imou/Dahua) — chỉ xem được.
        </p>
      )}
    </div>
  );
}

/** Xem trực tiếp: MJPEG qua c2a. Luồng đứt (camera rớt mạng, máy chủ khởi động lại) thì xin vé
 * mới và nối lại sau 3 giây. */
function XemTrucTiep({ ten }: { ten: string }) {
  const [src, setSrc] = useState("");
  const [loi, setLoi] = useState("");
  const [lan, setLan] = useState(0);
  // Giữ tham chiếu kể cả sau khi React gỡ thẻ, để lúc dọn còn xoá được src (cắt luồng MJPEG).
  const anh = useRef<HTMLImageElement | null>(null);

  useEffect(() => () => {
    if (anh.current) anh.current.src = "";
  }, []);

  useEffect(() => {
    let dong = false;
    setSrc("");
    xinVe(`/api/camera/xem/${encodeURIComponent(ten)}/ve`)
      .then((ve) => {
        if (!dong) setSrc(`${goc()}/api/camera/xem/${encodeURIComponent(ten)}?ve=${encodeURIComponent(ve)}`);
      })
      .catch((e) => { if (!dong) setLoi(`Không mở được hình: ${e instanceof Error ? e.message : String(e)}`); });
    return () => { dong = true; setSrc(""); };
  }, [ten, lan]);

  return (
    <div className="space-y-1">
      <div className="relative aspect-video w-full overflow-hidden rounded bg-black">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img ref={(e) => { if (e) anh.current = e; }} src={src} alt={`Camera ${ten}`}
            className="h-full w-full object-contain"
            onLoad={() => setLoi("")}
            onError={() => { setLoi("Mất hình — đang nối lại…"); setTimeout(() => setLan((x) => x + 1), 3000); }} />
        ) : (
          <span className="absolute inset-0 flex items-center justify-center text-xs text-white/70">Đang mở hình…</span>
        )}
      </div>
      {loi ? <p className="text-xs text-amber-600">⚠️ {loi}</p> : null}
    </div>
  );
}

/** Đàm thoại với một camera: nghe tiếng camera liên tục, gửi mic theo chế độ đang chọn. */
function KenhDam({ ten, cheDo }: { ten: string; cheDo: CheDoMic }) {
  const [trangThai, setTrangThai] = useState("Đang nối…");
  const [loi, setLoi] = useState("");
  const [dangNoi, setDangNoi] = useState(false);
  const [mucNghe, setMucNghe] = useState(0);
  const [mucMic, setMucMic] = useState(0);
  const [micSan, setMicSan] = useState<"" | "dang_xin" | "san">("");
  const ws = useRef<WebSocket | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const mic = useRef<MediaStream | null>(null);
  const noi = useRef(false);
  const giu = useRef(false);          // ngón tay còn đang giữ nút

  useEffect(() => {
    let dong = false;
    const ac = new AudioContext({ sampleRate: TAN_SO });
    ctx.current = ac;
    let lich = 0;

    (async () => {
      try {
        const ve = await xinVe(`/api/camera/bo_dam/${encodeURIComponent(ten)}/ve`);
        if (dong) return;
        const s = new WebSocket(`${goc().replace(/^http/, "ws")}/api/camera/bo_dam/`
          + `${encodeURIComponent(ten)}/ws?ve=${encodeURIComponent(ve)}`);
        s.binaryType = "arraybuffer";
        ws.current = s;
        s.onopen = () => setTrangThai("Đang nghe camera");
        s.onclose = (e) => {
          if (!dong) setTrangThai(e.code === 4401 ? "Hết phiên — đóng rồi mở lại" : "Đã ngắt");
        };
        s.onmessage = (e) => {
          if (typeof e.data === "string") {
            try { setLoi((JSON.parse(e.data) as { loi?: string }).loi || ""); } catch { /* bỏ qua */ }
            return;
          }
          const i16 = new Int16Array(e.data as ArrayBuffer);
          if (!i16.length) return;
          const f = new Float32Array(i16.length);
          let dinh = 0;
          for (let i = 0; i < i16.length; i++) {
            f[i] = i16[i] / 32768;
            dinh = Math.max(dinh, Math.abs(f[i]));
          }
          setMucNghe(dinh);
          const now = ac.currentTime;
          // Tụt hậu quá 1 giây (mạng nghẽn, tab ngủ) thì bỏ khúc này để đuổi kịp.
          if (lich - now > 1.0) return;
          if (lich < now + 0.05) lich = now + 0.15;
          const buf = ac.createBuffer(1, f.length, TAN_SO);
          buf.copyToChannel(f, 0);
          const src = ac.createBufferSource();
          src.buffer = buf;
          src.connect(ac.destination);
          src.start(lich);
          lich += buf.duration;
        };
      } catch (e) {
        if (!dong) setTrangThai(`Không mở được: ${e instanceof Error ? e.message : String(e)}`);
      }
    })();

    return () => {
      dong = true;
      ws.current?.close();
      mic.current?.getTracks().forEach((t) => t.stop());
      void ac.close();
    };
  }, [ten]);

  const batMic = async () => {
    if (mic.current || !ctx.current) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("trình duyệt chỉ cho dùng mic khi mở c2a bằng https");
    }
    const ac = ctx.current;
    setMicSan("dang_xin");
    const m = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    }).catch((e) => { setMicSan(""); throw e; });
    mic.current = m;
    setMicSan("san");
    const nguon = ac.createMediaStreamSource(m);
    // ScriptProcessor: cũ nhưng chạy mọi trình duyệt, không cần tệp worklet riêng.
    const xl = ac.createScriptProcessor(2048, 1, 1);
    xl.onaudioprocess = (e) => {
      const f = e.inputBuffer.getChannelData(0);
      let dinh = 0;
      for (let i = 0; i < f.length; i++) dinh = Math.max(dinh, Math.abs(f[i]));
      setMucMic(dinh);
      const s = ws.current;
      if (!noi.current || !s || s.readyState !== WebSocket.OPEN) return;
      const i16 = new Int16Array(f.length);
      for (let i = 0; i < f.length; i++) i16[i] = Math.max(-1, Math.min(1, f[i])) * 32767;
      s.send(i16.buffer);
    };
    const cam = ac.createGain();
    cam.gain.value = 0;               // processor phải nối ra đích mới chạy; không phát lại tiếng mình
    nguon.connect(xl);
    xl.connect(cam);
    cam.connect(ac.destination);
  };

  // Xin mic ngay khi mở bộ đàm (xem đầu tệp).
  useEffect(() => {
    batMic().catch((e) => setLoi(`Không mở được mic: ${e instanceof Error ? e.message : String(e)}`));
  }, []);

  const batDau = async () => {
    giu.current = true;
    setLoi("");
    try {
      await ctx.current?.resume();
      await batMic();
    } catch (e) {
      setLoi(`Không mở được mic: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    // Thả tay trong lúc chờ (hộp hỏi quyền…) thì không bắt đầu nói.
    if (!giu.current) return;
    noi.current = true;
    setDangNoi(true);
  };

  const ketThuc = () => {
    giu.current = false;
    if (!noi.current) return;
    noi.current = false;
    setDangNoi(false);
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send("het");
  };

  // Đổi chế độ lúc mic đang mở thì tắt mic — khỏi mở suốt khi đã về «giữ để nói».
  useEffect(() => { ketThuc(); }, [cheDo]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{trangThai}</span>
        <span className="h-2 w-24 overflow-hidden rounded bg-muted" title="Tiếng từ camera">
          <span className="block h-full bg-emerald-500 transition-[width]"
            style={{ width: `${Math.min(100, mucNghe * 300)}%` }} />
        </span>
        <span>🎙️ Mic điện thoại:</span>
        {micSan === "san" ? (
          <span className="h-2 w-24 overflow-hidden rounded bg-muted" title="Mức mic điện thoại">
            <span className={`block h-full transition-[width] ${dangNoi ? "bg-red-500" : "bg-sky-500"}`}
              style={{ width: `${Math.min(100, mucMic * 200)}%` }} />
          </span>
        ) : <span>{micSan === "dang_xin" ? "đang xin quyền…" : "chưa có quyền"}</span>}
      </div>

      {cheDo === "giu" ? (
        <button
          type="button"
          className={`w-full select-none rounded-lg py-6 text-base font-medium touch-none ${
            dangNoi ? "bg-red-600 text-white" : "bg-primary text-primary-foreground"}`}
          onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); void batDau(); }}
          onPointerUp={ketThuc}
          onPointerCancel={ketThuc}
          onContextMenu={(e) => e.preventDefault()}
        >
          {dangNoi ? "🔴 Đang nói — thả ra để nghe" : "✋ Giữ để nói"}
        </button>
      ) : (
        <button
          type="button"
          className={`w-full select-none rounded-lg py-6 text-base font-medium ${
            dangNoi ? "bg-red-600 text-white" : "bg-primary text-primary-foreground"}`}
          onClick={() => (dangNoi ? ketThuc() : void batDau())}
        >
          {dangNoi ? "🔴 Mic đang mở — bấm để tắt" : "🎙️ Bấm để mở mic"}
        </button>
      )}
      <p className="text-xs text-muted-foreground">
        {cheDo === "giu"
          ? "Giữ nút để nói — giọng bạn ra loa camera; thả nút là nghe lại người bên kia."
          : "Mic mở suốt: loa camera tự mở khi bạn nói, im 1,5 giây là tự đóng để nghe người bên kia."}
        {" "}Camera tắt mic của nó trong lúc loa đang phát.
      </p>
      {loi ? <p className="text-xs text-amber-600">⚠️ {loi}</p> : null}
    </div>
  );
}
