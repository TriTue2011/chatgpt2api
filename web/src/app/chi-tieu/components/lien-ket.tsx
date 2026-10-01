"use client";

import { useState } from "react";
import { Copy, KeyRound, Unlink } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

import { gui, type TongQuan } from "../lib";

const kenhChu = (k: string) => (k.startsWith("zalop_") ? "Zalo cá nhân" : k.startsWith("zalo_") ? "Zalo Bot" : "Telegram");

export function LienKetTab({ tq, taiLai }: { tq: TongQuan; taiLai: () => Promise<void> }) {
  const [ma, setMa] = useState<{ ma: string; het_han: number; cau_nhan: string } | null>(null);
  return (
    <div className="space-y-3 text-sm">
      <div className="space-y-2 rounded-md border p-3">
        <div className="font-medium">Nối Zalo / Telegram của bạn vào sổ này</div>
        <p className="text-xs text-muted-foreground">
          Bấm lấy mã, rồi từ Zalo/Telegram của CHÍNH bạn nhắn bot câu hiện ra (mã dùng một lần, hết hạn sau 10 phút). Từ đó
          «vừa chi 50k ăn trưa» sẽ ghi vào sổ này và cảnh báo hũ gửi về đó.
        </p>
        <Button size="sm" onClick={async () => {
          const r = await gui("/api/chi-tieu/lien-ket/ma");
          if (r) setMa(r as unknown as { ma: string; het_han: number; cau_nhan: string });
        }}><KeyRound className="mr-1 size-4" /> Lấy mã liên kết</Button>
        {ma ? (
          <div className="flex flex-wrap items-center gap-2 rounded bg-muted p-2">
            <span>Nhắn bot:</span><b className="font-mono">{ma.cau_nhan}</b>
            <button type="button" title="Chép" onClick={() => { void navigator.clipboard?.writeText(ma.cau_nhan); toast.success("Đã chép"); }}>
              <Copy className="size-3.5" />
            </button>
            <span className="text-xs text-muted-foreground">hết hạn {new Date(ma.het_han * 1000).toLocaleTimeString("vi-VN")}</span>
          </div>
        ) : null}
      </div>
      <div className="rounded-md border p-3">
        <div className="mb-1 font-medium">Đang nối</div>
        {tq.lien_ket.map((x) => (
          <div key={x.kenh_user} className="flex flex-wrap items-center gap-2 text-xs">
            <span className="w-24">{kenhChu(x.kenh_user)}</span>
            <span className="flex-1">{x.ten || x.kenh_user}</span>
            <span className="text-muted-foreground">{x.gan_boi === "admin" ? "quản trị gán" : "tự liên kết"} · {new Date(x.luc).toLocaleDateString("vi-VN")}</span>
            <button type="button" title="Bỏ liên kết" className="text-destructive" onClick={async () => {
              if (window.confirm("Bỏ liên kết kênh này khỏi sổ?") && await gui("/api/chi-tieu/lien-ket/bo", { kenh_user: x.kenh_user })) await taiLai();
            }}><Unlink className="size-3.5" /></button>
          </div>
        ))}
        {!tq.lien_ket.length ? <p className="text-xs text-muted-foreground">Chưa nối kênh chat nào.</p> : null}
      </div>
    </div>
  );
}
