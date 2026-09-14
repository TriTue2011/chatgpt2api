"use client";

/**
 * Kết nối Home Assistant — URL và token để dán vào tích hợp TriTue YouTube Player.
 *
 * Chủ máy 14/09/2026: "token sinh ra thì phải có chỗ hiển thị trên webui để tôi
 * copy". c2a chạy trong container nên không tự biết IP LAN của máy chủ: ô "Địa chỉ
 * c2a trong LAN" để chủ máy đặt một lần; HA và loa dùng địa chỉ đó để tới c2a.
 */

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Copy, Eye, EyeOff, House, LoaderCircle } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { chep, goi, type KetNoi } from "./lib";

function DongCopy({ nhan, giaTri, an }: { nhan: string; giaTri: string; an?: boolean }) {
  const o = useRef<HTMLInputElement>(null);
  const [hien, setHien] = useState(!an);
  return (
    <label className="block min-w-0">
      <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{nhan}</span>
      <div className="flex items-center gap-1.5">
        <Input
          ref={o}
          readOnly
          value={giaTri}
          type={hien ? "text" : "password"}
          className="h-9 min-w-0 flex-1 font-mono text-xs"
          onFocus={(e) => e.currentTarget.select()}
        />
        {an && (
          <Button type="button" variant="outline" size="icon" aria-label={hien ? "Ẩn token" : "Hiện token"} onClick={() => setHien((v) => !v)}>
            {hien ? <EyeOff /> : <Eye />}
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={`Copy ${nhan}`}
          onClick={() => {
            if (!hien) setHien(true);
            // Ô mật khẩu không bôi đen được — hiện ra trước rồi mới chép.
            setTimeout(() => void chep(giaTri, o.current, nhan.toLowerCase()), 0);
          }}
        >
          <Copy />
        </Button>
      </div>
    </label>
  );
}

export function KetNoiHa() {
  const [kn, setKn] = useState<KetNoi | null>(null);
  const [lan, setLan] = useState("");
  const [dangLuu, setDangLuu] = useState(false);
  // Chỉ cần dán vào HA một lần: đã đặt địa chỉ LAN thì gập sẵn cho gọn (nhất là trên điện thoại).
  const [mo, setMo] = useState(false);

  useEffect(() => {
    void goi<KetNoi>("ket-noi").then((r) => {
      if (r) {
        setKn(r);
        setLan(r.url_lan);
        setMo(!r.url_lan);
      }
    });
  }, []);

  const luu = async () => {
    setDangLuu(true);
    const r = await goi<KetNoi>("ket-noi", { url_lan: lan.trim() });
    setDangLuu(false);
    if (r) {
      setKn(r);
      setLan(r.url_lan);
      toast.success(r.url_lan ? "Đã lưu địa chỉ LAN." : "Đã xoá địa chỉ LAN — dùng địa chỉ trang đang mở.");
    }
  };

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5">
      <button type="button" aria-expanded={mo} onClick={() => setMo((v) => !v)} className="flex w-full items-start gap-3 text-left">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-[color-mix(in_srgb,var(--primary)_14%,transparent)] text-[var(--primary)]">
          <House className="size-4" />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Kết nối Home Assistant</h2>
          <p className="text-xs text-muted-foreground">
            Trong HA: Thiết bị &amp; dịch vụ → TriTue YouTube Player → Cấu hình lại, dán URL và token dưới đây.
          </p>
        </div>
        <ChevronDown className={`ml-auto mt-1 size-4 shrink-0 text-muted-foreground transition ${mo ? "rotate-180" : ""}`} />
      </button>
      {!mo ? null : !kn ? (
        <div className="flex h-20 items-center justify-center"><LoaderCircle className="size-4 animate-spin text-muted-foreground" /></div>
      ) : (
        <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <DongCopy nhan="URL" giaTri={kn.url} />
          <DongCopy nhan="Token" giaTri={kn.token} an />
          <form
            className="block min-w-0"
            onSubmit={(e) => {
              e.preventDefault();
              void luu();
            }}
          >
            <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Địa chỉ c2a trong LAN</span>
            <div className="flex items-center gap-1.5">
              <Input
                value={lan}
                onChange={(e) => setLan(e.target.value)}
                placeholder="http://IP-máy-chủ:3030"
                inputMode="url"
                className="h-9 min-w-0 flex-1 font-mono text-xs"
              />
              <Button type="submit" variant="outline" size="icon" aria-label="Lưu địa chỉ LAN" disabled={dangLuu || lan.trim() === kn.url_lan}>
                {dangLuu ? <LoaderCircle className="animate-spin" /> : <Check />}
              </Button>
            </div>
          </form>
        </div>
      )}
      {mo && kn && !kn.url_lan && (
        <p className="mt-3 rounded-lg bg-[color-mix(in_srgb,var(--neon-amber)_10%,transparent)] px-3 py-2 text-xs text-[var(--neon-amber)]">
          Chưa đặt địa chỉ LAN nên URL đang theo địa chỉ trang này. Loa và HA tải nhạc nhanh, ổn định hơn qua địa chỉ LAN
          của máy chủ — điền rồi bấm lưu.
        </p>
      )}
    </section>
  );
}
