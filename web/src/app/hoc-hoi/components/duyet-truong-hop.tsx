"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Plus, RefreshCw, Send, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { layGet, goiPost } from "./lib";

/** Một trường hợp bot dựng (hoặc anh thêm) — services/kich_ban_nha.py «Duyệt trường hợp BẬT rồi TẮT». */
type Muc = { tinh_huong: string; cam_bien_thay?: string; nen: string; hien_tai: string; nguon: string };
type ThietBi = {
  ten: string; xong: boolean;
  bat: Muc[]; tat: Muc[]; bat_xong: boolean; tat_xong: boolean;
};
type Huong = "bat" | "tat";

const NEN: Record<Huong, [string, string][]> = {
  bat: [["bat", "bật"], ["khong_lam", "không bật"], ["hoi", "hỏi"]],
  tat: [["tat", "tắt"], ["giu", "giữ"]],
};
const HIEN: Record<string, [string, string]> = {
  dung: ["đang làm đúng", "bg-emerald-100 text-emerald-700"],
  sai: ["đang làm sai", "bg-rose-100 text-rose-700"],
  khong_ro: ["chưa rõ", "bg-slate-100 text-slate-600"],
};

/** Bot gửi các trường hợp BẬT để anh duyệt (thêm / sửa / bỏ), xong rồi tới TẮT — ở đây hoặc qua kênh chat. */
export function DuyetTruongHop() {
  const [ds, setDs] = useState<Record<string, ThietBi>>({});
  const [them, setThem] = useState<Record<string, string>>({});

  const tai = useCallback(async () => {
    const r = await layGet<{ duyet?: Record<string, ThietBi> }>("/api/hoc-hoi/kich-ban/duyet");
    setDs(r.duyet || {});
  }, []);
  useEffect(() => {
    let huy = false;
    void layGet<{ duyet?: Record<string, ThietBi> }>("/api/hoc-hoi/kich-ban/duyet").then((r) => {
      if (!huy) setDs(r.duyet || {});
    });
    return () => { huy = true; };
  }, []);

  const lam = async (body: Record<string, unknown>) => {
    if (await goiPost("/api/hoc-hoi/kich-ban/duyet", body)) await tai();
  };
  const nenChu = (h: Huong, nen: string) => NEN[h].find(([k]) => k === nen)?.[1] || nen;

  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Bot dựng tình huống từ sơ đồ nhà; anh duyệt phần BẬT rồi phần TẮT của từng thiết bị. Bản đã duyệt vào lời
          mô tả nhà — mọi tầng học đọc nó.
        </p>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => void tai()}><RefreshCw className="mr-1 size-3.5" /> Làm mới</Button>
          <Button size="sm" onClick={() => void lam({ viec: "bat_dau" })}><Send className="mr-1 size-3.5" /> Gửi qua kênh</Button>
        </div>
      </div>
      {!Object.keys(ds).length ? (
        <p className="text-xs text-muted-foreground">Chưa có danh sách — bấm «Gửi qua kênh» để bot dựng từ lần tình huống mới nhất.</p>
      ) : null}
      {Object.entries(ds).map(([tb, x]) => (
        <div key={tb} className="rounded-md border p-3">
          <div className="mb-2 font-medium">{x.ten} <code className="text-[10px] text-muted-foreground">{tb}</code></div>
          {(["bat", "tat"] as Huong[]).map((h) => (
            <div key={h} className="mb-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-semibold">{h === "bat" ? "Trường hợp BẬT" : "Trường hợp TẮT"}</span>
                {x[`${h}_xong`] ? (
                  <span className="rounded bg-emerald-100 px-1.5 text-[11px] text-emerald-700">đã duyệt</span>
                ) : (
                  <Button size="sm" className="h-6" onClick={() => void lam({ tb, huong: h, viec: "duyet" })}>
                    <Check className="mr-1 size-3" /> Duyệt phần {h === "bat" ? "bật" : "tắt"}
                  </Button>
                )}
              </div>
              <ol className="space-y-1">
                {x[h].map((m, i) => (
                  <li key={`${h}-${i}-${m.tinh_huong}`} className="flex flex-wrap items-center gap-1.5">
                    <span className="w-5 text-right text-xs text-muted-foreground">{i + 1}.</span>
                    <Input className="h-7 min-w-0 flex-1 text-xs" defaultValue={m.tinh_huong}
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v && v !== m.tinh_huong) void lam({ tb, huong: h, viec: "sua", so: i + 1, noi_dung: `${v} → ${nenChu(h, m.nen)}` });
                      }} />
                    <select className="h-7 rounded border bg-background px-1 text-xs" value={m.nen}
                      onChange={(e) => void lam({ tb, huong: h, viec: "sua", so: i + 1, noi_dung: `${m.tinh_huong} → ${nenChu(h, e.target.value)}` })}>
                      {NEN[h].map(([k, chu]) => <option key={k} value={k}>{chu}</option>)}
                    </select>
                    {m.nguon === "chu_may" ? (
                      <span className="rounded bg-sky-100 px-1.5 text-[10px] text-sky-700">anh thêm/sửa</span>
                    ) : (
                      <span className={`rounded px-1.5 text-[10px] ${HIEN[m.hien_tai]?.[1] || ""}`}>{HIEN[m.hien_tai]?.[0] || m.hien_tai}</span>
                    )}
                    <button type="button" title="Bỏ" className="text-destructive"
                      onClick={() => void lam({ tb, huong: h, viec: "bo", so: i + 1 })}><Trash2 className="size-3.5" /></button>
                  </li>
                ))}
              </ol>
              <div className="mt-1 flex gap-1.5">
                <Input className="h-7 text-xs" placeholder={h === "bat" ? "Thêm trường hợp, vd «đi từ bếp vào ngồi ghế → bật»" : "Thêm trường hợp, vd «ra ban công phơi đồ → giữ»"}
                  value={them[`${tb}|${h}`] || ""} onChange={(e) => setThem({ ...them, [`${tb}|${h}`]: e.target.value })} />
                <Button size="sm" variant="outline" className="h-7" onClick={async () => {
                  const v = (them[`${tb}|${h}`] || "").trim();
                  if (!v) return;
                  await lam({ tb, huong: h, viec: "them", noi_dung: v });
                  setThem({ ...them, [`${tb}|${h}`]: "" });
                }}><Plus className="size-3.5" /></Button>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
