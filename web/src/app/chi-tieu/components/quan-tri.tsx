"use client";

import { useCallback, useEffect, useState } from "react";
import { Link2, Plus, Unlink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { gui, lay } from "../lib";

type SoQt = { id: number; ten: string; chu: string | null; lien_ket: { kenh_user: string; ten: string; gan_boi: string }[] };
type Nguoi = { kenh_user: string; ten: string; kenh: string; bot: string; bot_id: string };

/** Quản trị CHỈ thấy tên sổ + kênh đã gắn — không có số tiền nào (chủ máy 02/10/2026). */
export function QuanTri() {
  const [d, setD] = useState<{ so: SoQt[]; nguoi: Nguoi[] } | null>(null);
  const [chon, setChon] = useState<Record<string, string>>({});
  const [tenMoi, setTenMoi] = useState("");
  const tai = useCallback(async () => {
    const r = await lay<{ so: SoQt[]; nguoi: Nguoi[] }>("/api/chi-tieu/quan-tri");
    if (r.ok) setD(r);
  }, []);
  useEffect(() => { void tai(); }, [tai]);
  if (!d) return null;
  const soCua = new Map(d.so.flatMap((s) => s.lien_ket.map((l) => [l.kenh_user, s] as const)));
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">
        Chỉ thấy TÊN sổ và kênh chat đã gắn — không xem được số tiền của ai. Gán xong, bot nhắn cho chính người được gán biết
        họ vừa được nối vào sổ nào.
      </p>
      <div className="rounded-md border p-3">
        <div className="mb-1 font-medium">Các sổ</div>
        {d.so.map((s) => (
          <div key={s.id} className="flex flex-wrap items-center gap-2 border-t py-1 text-xs first:border-t-0">
            <b className="w-48 truncate">{s.ten}</b>
            <span className="text-muted-foreground">{s.chu ? "có tài khoản web" : "chỉ dùng qua chat"}</span>
            <span className="flex-1">{s.lien_ket.map((l) => l.ten || l.kenh_user).join(", ") || "— chưa gắn kênh nào"}</span>
          </div>
        ))}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Input className="h-8 w-56" placeholder="Tên sổ cho người không có tài khoản web" value={tenMoi} onChange={(e) => setTenMoi(e.target.value)} />
          <Button size="sm" variant="outline" disabled={!tenMoi.trim()} onClick={async () => {
            if (await gui("/api/chi-tieu/quan-tri/tao-so", { ten: tenMoi })) { setTenMoi(""); await tai(); }
          }}><Plus className="mr-1 size-4" /> Tạo sổ</Button>
        </div>
      </div>
      <div className="rounded-md border p-3">
        <div className="mb-1 font-medium">Người chat (Zalo / Telegram) → sổ</div>
        <div className="divide-y">
          {d.nguoi.map((n) => {
            const dang = soCua.get(n.kenh_user);
            return (
              <div key={n.kenh_user} className="flex flex-wrap items-center gap-2 py-1 text-xs">
                <span className="w-40 truncate font-medium">{n.ten || n.kenh_user}</span>
                <span className="w-32 truncate text-muted-foreground">{n.kenh} · {n.bot}</span>
                <span className="w-40 truncate">{dang ? `→ ${dang.ten}` : "chưa gắn"}</span>
                <select className="rounded border bg-background px-1 py-0.5" value={chon[n.kenh_user] ?? ""}
                  onChange={(e) => setChon({ ...chon, [n.kenh_user]: e.target.value })}>
                  <option value="">chọn sổ…</option>
                  {d.so.map((s) => <option key={s.id} value={s.id}>{s.ten}</option>)}
                </select>
                <Button size="sm" variant="outline" className="h-7" disabled={!chon[n.kenh_user]} onClick={async () => {
                  const so = d.so.find((s) => String(s.id) === chon[n.kenh_user]);
                  if (!so || !window.confirm(`Gắn ${n.ten || n.kenh_user} vào sổ «${so.ten}»? Người đó sẽ nhận tin báo.`)) return;
                  if (await gui("/api/chi-tieu/quan-tri/gan", { kenh_user: n.kenh_user, so_id: so.id, ten: n.ten, bot_id: n.bot_id })) await tai();
                }}><Link2 className="mr-1 size-3.5" /> Gán</Button>
                {dang ? (
                  <Button size="sm" variant="ghost" className="h-7 text-destructive" onClick={async () => {
                    if (window.confirm("Bỏ gắn?") && await gui("/api/chi-tieu/quan-tri/bo", { kenh_user: n.kenh_user })) await tai();
                  }}><Unlink className="size-3.5" /></Button>
                ) : null}
              </div>
            );
          })}
          {!d.nguoi.length ? <p className="py-2 text-xs text-muted-foreground">Chưa có người chat nào trong danh bạ kênh.</p> : null}
        </div>
      </div>
    </div>
  );
}
