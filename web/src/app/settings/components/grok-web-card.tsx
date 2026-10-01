"use client";

/**
 * Grok (grok.com) — tài khoản như các provider khác: danh sách có thứ tự (đầu = Main), bật/tắt, xoá, đăng nhập.
 *
 * Khác ở đường đăng nhập: grok.com chặn Chrome của captcha-solver trên máy này, nên mỗi tài khoản là một hồ sơ
 * Firefox riêng. Bấm «Đăng nhập» → Firefox mở trên noVNC → anh đăng nhập (Google hay email đều được) → phiên sống
 * thì cookie được ghi và Firefox tự tắt. Chat không mở trình duyệt.
 *
 * Backend: api/grok_tai_khoan.py → api/grok_firefox.py.
 */

import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, LoaderCircle, LogIn, Monitor, Plus, Power, PowerOff, RefreshCw, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { moNoVNC } from "@/lib/duong-dan";

export type GrokTaiKhoan = {
  profile: string; label: string; email?: string; enabled?: boolean; ordinal: number; is_primary: boolean;
  phien_song: boolean | null; da_dang_nhap: boolean; firefox_mo: boolean; cookie_luc: number | null;
};

export async function grokViec(body: Record<string, unknown>): Promise<boolean> {
  try {
    const r = await request.post("/api/grok-web/tai-khoan", body);
    const d = r.data as { ok?: boolean; error?: string };
    if (!d?.ok) {
      toast.error(d?.error || "Không làm được.");
      return false;
    }
    return true;
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "Lỗi mạng.");
    return false;
  }
}

/** Mở Firefox của tài khoản trên noVNC để anh đăng nhập; cookie tự ghi, Firefox tự tắt khi phiên sống. */
export async function grokDangNhap(profile: string): Promise<boolean> {
  const ok = await grokViec({ viec: "dang_nhap", profile });
  if (ok) {
    void moNoVNC("noopener,width=1100,height=760");
    toast.info("Firefox đã mở trên noVNC — đăng nhập grok.com (Google hay email đều được). Xong là tự lưu và tự tắt.");
  }
  return ok;
}

export function TrangThaiGrok({ tk }: { tk: GrokTaiKhoan }) {
  if (tk.firefox_mo) return <Badge className="bg-sky-100 text-sky-700">Firefox đang mở — chờ đăng nhập</Badge>;
  if (!tk.da_dang_nhap) return <Badge className="bg-amber-100 text-amber-700">chưa đăng nhập</Badge>;
  if (tk.phien_song === false) return <Badge className="bg-rose-100 text-rose-700">hết phiên</Badge>;
  if (tk.phien_song === true) return <Badge className="bg-emerald-100 text-emerald-700">phiên sống</Badge>;
  return <Badge variant="secondary">đã đăng nhập</Badge>;
}

export function GrokWebCard() {
  const [ds, setDs] = useState<GrokTaiKhoan[]>([]);
  const [bat, setBat] = useState(true);
  const [dang, setDang] = useState(true);
  const [nhan, setNhan] = useState("");

  const tai = useCallback(async () => {
    setDang(true);
    try {
      const r = await request.get("/api/grok-web/tai-khoan");
      const d = r.data as { tai_khoan?: GrokTaiKhoan[]; enabled?: boolean };
      setDs(d.tai_khoan || []);
      setBat(d.enabled !== false);
    } catch {
      toast.error("Không đọc được tài khoản Grok.");
    } finally {
      setDang(false);
    }
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  const lam = async (body: Record<string, unknown>) => {
    if (await grokViec(body)) await tai();
  };
  const doiCho = (i: number, j: number) => {
    const p = ds.map((x) => x.profile);
    [p[i], p[j]] = [p[j], p[i]];
    void lam({ viec: "thu_tu", thu_tu: p });
  };

  return (
    <Card className="rounded-2xl">
      <CardContent className="space-y-3 p-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 font-medium">
            <input type="checkbox" checked={bat} onChange={(e) => void lam({ viec: e.target.checked ? "bat_provider" : "tat_provider" })} />
            Dùng Grok (model <code>grok/fast</code>, <code>grok/auto</code>, <code>gw/fast</code>)
          </label>
          <Button variant="outline" size="sm" className="ml-auto h-7" onClick={() => void tai()} disabled={dang}>
            {dang ? <LoaderCircle className="mr-1 size-3.5 animate-spin" /> : <RefreshCw className="mr-1 size-3.5" />} Kiểm phiên
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Mỗi tài khoản một hồ sơ Firefox riêng (grok.com chặn Chrome của máy này). Bấm <b>Đăng nhập</b> → Firefox mở trên
          noVNC → đăng nhập bằng Google hay email đều được → phiên sống thì tự lưu cookie và tắt Firefox. Chat xoay theo
          thứ tự: tài khoản #1 hỏng thì sang #2.
        </p>
        <div className="divide-y rounded-md border">
          {ds.map((tk, i) => (
            <div key={tk.profile} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <span className={`min-w-[28px] rounded px-1.5 text-center font-mono text-[11px] font-bold ${tk.is_primary ? "bg-emerald-100 text-emerald-700" : "bg-muted"}`}>
                #{tk.ordinal}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={`font-semibold ${tk.enabled === false ? "text-muted-foreground line-through" : ""}`}>{tk.label}</span>
                  <TrangThaiGrok tk={tk} />
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {tk.email || "chưa rõ email"} · <code>{tk.profile}</code>
                  {tk.cookie_luc ? ` · cookie ${new Date(tk.cookie_luc * 1000).toLocaleString("vi-VN")}` : ""}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button variant="outline" size="sm" className="h-7" onClick={() => void grokDangNhap(tk.profile).then(() => tai())}>
                  <LogIn className="mr-1 size-3.5" /> Đăng nhập
                </Button>
                {tk.firefox_mo ? (
                  <>
                    <Button variant="ghost" size="sm" className="h-7" title="Mở noVNC" onClick={() => void moNoVNC()}>
                      <Monitor className="size-3.5" />
                    </Button>
                    <Button variant="ghost" size="sm" className="h-7" title="Tắt Firefox" onClick={() => void lam({ viec: "tat_firefox", profile: tk.profile })}>
                      <X className="size-3.5" />
                    </Button>
                  </>
                ) : null}
                <Button variant="ghost" size="sm" className="h-7" disabled={i === 0} title="Lên" onClick={() => doiCho(i, i - 1)}>
                  <ArrowUp className="size-3.5" />
                </Button>
                <Button variant="ghost" size="sm" className="h-7" disabled={i === ds.length - 1} title="Xuống" onClick={() => doiCho(i, i + 1)}>
                  <ArrowDown className="size-3.5" />
                </Button>
                <Button variant="ghost" size="sm" className="h-7" title={tk.enabled === false ? "Bật" : "Tắt"}
                  onClick={() => void lam({ viec: tk.enabled === false ? "bat" : "tat", profile: tk.profile })}>
                  {tk.enabled === false ? <Power className="size-3.5" /> : <PowerOff className="size-3.5" />}
                </Button>
                <Button variant="ghost" size="sm" className="h-7 text-destructive" title="Xoá tài khoản và hồ sơ đăng nhập"
                  onClick={() => { if (window.confirm(`Xoá ${tk.label} (${tk.email || tk.profile}) và hồ sơ đăng nhập của nó?`)) void lam({ viec: "xoa", profile: tk.profile }); }}>
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </div>
          ))}
          {!ds.length && !dang ? <p className="px-3 py-3 text-xs text-muted-foreground">Chưa có tài khoản Grok — thêm rồi bấm Đăng nhập.</p> : null}
        </div>
        <div className="flex items-center gap-2">
          <Input className="h-8 w-48" placeholder="Nhãn (vd Main, Backup)" value={nhan} onChange={(e) => setNhan(e.target.value)} />
          <Button variant="outline" size="sm" className="h-8"
            onClick={async () => {
              if (await grokViec({ viec: "them", label: nhan })) {
                setNhan("");
                await tai();
              }
            }}>
            <Plus className="mr-1 size-3.5" /> Thêm tài khoản
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
