"use client";

/**
 * BoDamCamera — bộ đàm với một camera Dahua/Imou, ngay trong web c2a.
 *
 * Chủ máy 24/09/2026: "dùng mic điện thoại … phát ra loa giữ nguyên gốc, rồi nghe
 * được người bên cam nói gì — giống như app Imou", và "làm cả trên c2a".
 *
 * Một WebSocket hai chiều (`/api/camera/bo_dam/{ten}/ws`): máy chủ gửi tiếng mic
 * camera (PCM16 mono 16 kHz), trình duyệt gửi tiếng mic lúc GIỮ nút Nói và chữ
 * `het` lúc thả. Máy chủ chỉ mở kênh nói tới camera khi có tiếng người — camera
 * tắt mic của nó suốt lúc kênh nói mở, nên thả nút là nghe lại được ngay.
 *
 * WebSocket không gửi được header nên xin vé một lần trước (khuôn SSE của
 * trang Đăng ký). Mic trình duyệt chỉ dùng được trên https.
 *
 * Xin quyền mic NGAY KHI MỞ, không đợi lúc bấm nút: bản đầu xin lúc ấn giữ, hộp
 * hỏi quyền hiện lên cướp mất thao tác giữ nút (chủ máy 25/09/2026: "bật bộ đàm
 * rồi không được" — hai phiên, 0 giây ra loa). Vạch mức mic cho thấy mic có thu.
 */

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import webConfig from "@/constants/common-env";
import { request } from "@/lib/request";

const TAN_SO = 16000;

export function BoDamCamera({ ten, onClose }: { ten: string; onClose: () => void }) {
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
        const r = await request.post(`/api/camera/bo_dam/${encodeURIComponent(ten)}/ve`, {});
        const ve = (r.data as { ticket?: string })?.ticket;
        if (dong || !ve) return;
        const goc = webConfig.apiUrl.replace(/\/$/, "") || window.location.origin;
        const s = new WebSocket(`${goc.replace(/^http/, "ws")}/api/camera/bo_dam/`
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

  return (
    <div className="rounded border border-primary/40 p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">📞 Bộ đàm — {ten}</span>
        <span className="text-xs text-muted-foreground">{trangThai}</span>
        <span className="h-2 w-24 overflow-hidden rounded bg-muted" title="Tiếng từ camera">
          <span className="block h-full bg-emerald-500 transition-[width]"
            style={{ width: `${Math.min(100, mucNghe * 300)}%` }} />
        </span>
        <Button size="sm" variant="outline" className="ml-auto" onClick={onClose}>Đóng</Button>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>🎙️ Mic điện thoại:</span>
        {micSan === "san" ? (
          <span className="h-2 w-24 overflow-hidden rounded bg-muted" title="Mức mic điện thoại">
            <span className={`block h-full transition-[width] ${dangNoi ? "bg-red-500" : "bg-sky-500"}`}
              style={{ width: `${Math.min(100, mucMic * 200)}%` }} />
          </span>
        ) : <span>{micSan === "dang_xin" ? "đang xin quyền…" : "chưa có quyền"}</span>}
      </div>
      <button
        type="button"
        className={`w-full select-none rounded-lg py-6 text-base font-medium touch-none ${
          dangNoi ? "bg-red-600 text-white" : "bg-primary text-primary-foreground"}`}
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); void batDau(); }}
        onPointerUp={ketThuc}
        onPointerCancel={ketThuc}
        onContextMenu={(e) => e.preventDefault()}
      >
        {dangNoi ? "🔴 Đang nói — thả ra để nghe" : "🎙️ Giữ để nói"}
      </button>
      <p className="text-xs text-muted-foreground">
        Tiếng camera phát liên tục ở đây. Giữ nút để nói — giọng bạn ra loa camera nguyên
        gốc; thả nút là nghe lại người bên kia (camera tắt mic trong lúc bạn nói).
      </p>
      {loi ? <p className="text-xs text-amber-600">⚠️ {loi}</p> : null}
    </div>
  );
}
