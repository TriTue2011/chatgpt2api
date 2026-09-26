"use client";

/**
 * Sổ cách đọc — chủ máy dạy cách đọc một chữ ("TBBH" → "trung tâm bảo hành"), từ đó
 * mọi giọng tiếng Việt (loa, tin thoại, trợ lý) đọc đúng.
 *
 * Backend: api/voice.py (/api/voice/cach-doc) → services/voice/cach_doc.py. Dạy qua bot
 * (Zalo/Telegram, công cụ day_cach_doc) cũng ghi vào cùng sổ này.
 */

import { useCallback, useEffect, useState } from "react";
import { PlayCircle, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";

type Dong = { chu: string; doc: string; luc?: number };

export function CachDocCard() {
  const [rows, setRows] = useState<Dong[]>([]);
  const [chu, setChu] = useState("");
  const [doc, setDoc] = useState("");
  const [dangGhi, setDangGhi] = useState(false);
  const [dangDoc, setDangDoc] = useState("");

  const tai = useCallback(async () => {
    try {
      const res = await request.get("/api/voice/cach-doc");
      setRows((res.data?.rows as Dong[]) || []);
    } catch (e) {
      toast.error(`Không tải được sổ cách đọc: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, []);

  useEffect(() => { void tai(); }, [tai]);

  const day = async () => {
    if (!chu.trim() || !doc.trim()) return;
    setDangGhi(true);
    try {
      await request.post("/api/voice/cach-doc", { chu: chu.trim(), doc: doc.trim() });
      toast.success(`Đã ghi: ${chu.trim()} → ${doc.trim()}`);
      setChu(""); setDoc("");
      await tai();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setDangGhi(false);
    }
  };

  const xoa = async (c: string) => {
    if (!confirm(`Bỏ cách đọc của "${c}"?`)) return;
    try {
      await request.delete("/api/voice/cach-doc", { params: { chu: c } });
      await tai();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  /** Nghe thử bằng giọng mặc định: câu chứa đúng chữ đã dạy, đi qua đường đọc thật. */
  const ngheThu = async (c: string) => {
    setDangDoc(c);
    try {
      const { getStoredAuthKey } = await import("@/store/auth");
      let key = await getStoredAuthKey();
      if (!key) { try { key = localStorage.getItem("chatgpt2api_auth_key") || ""; } catch { /* noop */ } }
      const url = `/api/voice/preview?stream=1&text=${encodeURIComponent(`${c}.`)}`
        + `&key=${encodeURIComponent(key || "")}`;
      const audio = new Audio(url);
      audio.onended = () => setDangDoc("");
      audio.onerror = () => { setDangDoc(""); toast.error("Nghe thử lỗi"); };
      await audio.play();
    } catch (e) {
      setDangDoc("");
      toast.error(`Nghe thử lỗi: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <div className="font-medium">Cách đọc</div>
        <p className="text-sm text-muted-foreground">
          Máy đọc sai một chữ (viết tắt, tên hãng…) thì dạy ở đây — mọi giọng đọc theo ngay.
          Chữ có HOA khớp đúng hoa (&quot;TV&quot;), chữ thường khớp mọi kiểu (&quot;smart&quot;).
          Cũng dạy được qua bot: <i>&quot;dạy đọc: TBBH là trung tâm bảo hành&quot;</i>.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-40" placeholder="Chữ (vd TBBH)" value={chu}
          onChange={(e) => setChu(e.target.value)} />
        <span className="text-muted-foreground">→</span>
        <Input className="min-w-56 flex-1" placeholder="Đọc là (vd trung tâm bảo hành)" value={doc}
          onChange={(e) => setDoc(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void day(); }} />
        <Button type="button" onClick={() => void day()} disabled={dangGhi || !chu.trim() || !doc.trim()}>
          <Plus className="size-4" /> Dạy
        </Button>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Sổ đang trống.</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {rows.map((r) => (
            <li key={r.chu} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className="font-mono font-medium">{r.chu}</span>
              <span className="text-muted-foreground">→</span>
              <span className="flex-1">{r.doc}</span>
              <button type="button" title="Nghe thử" disabled={dangDoc === r.chu}
                onClick={() => void ngheThu(r.chu)}>
                <PlayCircle className={`size-5 ${dangDoc === r.chu ? "animate-pulse" : ""}`} />
              </button>
              <button type="button" title="Bỏ" onClick={() => void xoa(r.chu)}>
                <Trash2 className="size-4 text-destructive" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
