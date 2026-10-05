"use client";

/**
 * Tâm hồn theo TỪNG thread (Kênh chat › Lọc thread) — chủ máy 05/10/2026: "Tâm hồn (làm thơ, cảm xúc) phải gán vào
 * trong lọc thread ID chứ sao lại để ở học hỏi. Ngoài thơ thì văn, nói chuyện phiếm".
 * Bài bot tự viết gửi thẳng vào thread tích đúng kiểu; «Nói chuyện phiếm» còn cho cảm xúc thấm vào lời trò chuyện ở
 * thread đó. Lưu ở sổ riêng của tâm hồn: GET /api/tam-hon (thread) · POST /api/tam-hon/thread.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { request } from "@/lib/request";

const KIEU = [["tho", "Thơ"], ["van", "Văn"], ["phiem", "Nói chuyện phiếm"]] as const;

let _bang: Promise<Record<string, string[]>> | null = null;
function docBang(): Promise<Record<string, string[]>> {
  _bang ??= request.get("/api/tam-hon")
    .then((r) => Object.fromEntries(((r.data?.thread || []) as { khoa: string; kieu: string[] }[]).map((x) => [x.khoa, x.kieu])))
    .catch(() => ({}));
  return _bang;
}

export function TamHonThread({ khoa }: { khoa: string }) {
  const [kieu, setKieu] = useState<string[]>([]);
  useEffect(() => {
    let song = true;
    void docBang().then((b) => { if (song) setKieu(b[khoa] || []); });
    return () => { song = false; };
  }, [khoa]);

  const doi = async (k: string) => {
    const moi = kieu.includes(k) ? kieu.filter((x) => x !== k) : [...kieu, k];
    try {
      const r = await request.post("/api/tam-hon/thread", { khoa, kieu: moi });
      if (!r.data?.ok) { toast.error(r.data?.error || "Lưu thất bại"); return; }
      const luu = (r.data.kieu || []) as string[];
      setKieu(luu);
      void docBang().then((b) => { b[khoa] = luu; });
    } catch { toast.error("Lưu thất bại"); }
  };

  return (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <span>🖋️ Tâm hồn:</span>
      {KIEU.map(([k, ten]) => (
        <label key={k} className="flex cursor-pointer select-none items-center gap-1">
          <input type="checkbox" className="size-3.5" checked={kieu.includes(k)} onChange={() => void doi(k)} />
          {ten}
        </label>
      ))}
    </div>
  );
}
