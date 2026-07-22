"use client";

/**
 * Thanh Persona GỌN ngay trên ô nhập tab Chat — tick bật mới hiện 4 lựa chọn
 * (Vùng miền · Giới tính · Độ tuổi · Nghề). Khối mô tả chi tiết KHÔNG hiển thị
 * — backend sinh và đi ngầm vào request dạng system message. Lưu localStorage.
 */

import { useEffect, useState } from "react";

import { request } from "@/lib/request";

type Opts = {
  regions: string[]; genders: string[]; ages: string[]; jobs: string[];
};
type Sel = { region: string; gender: string; age: string; job: string };

const SEL_CLS =
  "h-7 rounded-md border border-input bg-background px-1 text-xs";
const LS_KEY = "chat_persona_v1";

export function ChatPersonaBar({ onPrompt }: { onPrompt: (p: string) => void }) {
  const [on, setOn] = useState(false);
  const [opts, setOpts] = useState<Opts | null>(null);
  const [sel, setSel] = useState<Sel>({ region: "", gender: "", age: "", job: "" });

  useEffect(() => {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        if (d && typeof d === "object") {
          setOn(!!d.on);
          setSel((p) => ({ ...p, ...(d.sel || {}) }));
        }
      }
    } catch { /* bỏ qua localStorage hỏng */ }
  }, []);

  useEffect(() => {
    try { localStorage.setItem(LS_KEY, JSON.stringify({ on, sel })); } catch {}
    if (!on) { onPrompt(""); return; }
    if (!opts) {
      request.get("/api/personas")
        .then((r) => setOpts(r.data?.options || null))
        .catch(() => {});
    }
    if (!(sel.region || sel.gender || sel.age || sel.job)) { onPrompt(""); return; }
    request.post("/api/personas/preview", { sel })
      .then((r) => onPrompt(String(r.data?.prompt || "")))
      .catch(() => onPrompt(""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, sel]);

  const set = (k: keyof Sel, v: string) => setSel((p) => ({ ...p, [k]: v }));

  return (
    <div className="mb-1 flex flex-wrap items-center gap-1 text-xs">
      <label className="flex cursor-pointer items-center gap-1 select-none">
        <input type="checkbox" checked={on}
               onChange={(e) => setOn(e.target.checked)} />
        🎭 Persona
      </label>
      {on && (
        <>
          <select className={SEL_CLS} value={sel.region}
                  onChange={(e) => set("region", e.target.value)}>
            <option value="">Vùng miền…</option>
            {(opts?.regions || []).map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
          <select className={SEL_CLS} value={sel.gender}
                  onChange={(e) => set("gender", e.target.value)}>
            <option value="">Giới tính…</option>
            {(opts?.genders || []).map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
          <select className={SEL_CLS} value={sel.age}
                  onChange={(e) => set("age", e.target.value)}>
            <option value="">Độ tuổi…</option>
            {(opts?.ages || []).map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
          <select className={SEL_CLS} value={sel.job}
                  onChange={(e) => set("job", e.target.value)}>
            <option value="">Nghề nghiệp…</option>
            {(opts?.jobs || []).map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </>
      )}
    </div>
  );
}
