"use client";

/**
 * Thẻ «Model cần tải» — MỌI model c2a dùng, đã có chưa, có cần không, và lệnh tải để chép.
 *
 * Ảnh Docker chỉ mang chương trình chạy model; model nằm ở volume dữ liệu và tải bằng
 * `scripts/download_*.py` trong container. Danh mục và cách kiểm do máy chủ giữ
 * (`services/danh_muc_model.py`, GET /api/models/danh-muc) — thẻ này chỉ hiển thị.
 */

import { useCallback, useEffect, useState } from "react";

import { request } from "@/lib/request";

import { NutTaiModel } from "./nut-tai-model";

type Them = { lenh: string; mo_ta: string };
type BienThe = { ma: string; ten: string; da_tai: boolean; mo_ta: string; lenh: string };
type MucModel = {
  ma: string; nhom: string; ten: string; dung_cho: string; dung_luong: string;
  muc_do: "can" | "nen" | "tuy_chon"; da_tai: boolean; lenh: string; them: Them[]; ghi_chu: string;
  bien_the?: BienThe[];
};

const NHAN_MUC_DO: Record<MucModel["muc_do"], string> = {
  can: "Cần", nen: "Nên có", tuy_chon: "Tuỳ chọn",
};

export function ModelCanTaiCard() {
  const [ds, setDs] = useState<MucModel[] | null>(null);
  const [loi, setLoi] = useState("");
  const [daChep, setDaChep] = useState("");

  const tai = useCallback(async () => {
    try {
      const r = (await request.get("/api/models/danh-muc")).data as { items: MucModel[] };
      setDs(r.items || []); setLoi("");
    } catch (e: any) {
      setLoi(String(e?.message || e));
    }
  }, []);
  useEffect(() => { void tai(); }, [tai]);

  const chep = (lenh: string) => {
    void navigator.clipboard?.writeText(lenh).then(() => {
      setDaChep(lenh); setTimeout(() => setDaChep(""), 1500);
    }).catch(() => {});
  };

  if (loi) return <p className="text-sm text-destructive">Không đọc được danh mục model: {loi}</p>;
  if (!ds) return <p className="text-sm text-muted-foreground">Đang kiểm model…</p>;

  const thieuCan = ds.filter((x) => x.muc_do === "can" && !x.da_tai);
  const nhom = Array.from(new Set(ds.map((x) => x.nhom)));
  return (
    <div className="space-y-4">
      <div className="text-sm space-y-1">
        {thieuCan.length ? (
          <p className="font-medium text-destructive">
            Thiếu {thieuCan.length} model đang CẦN: {thieuCan.map((x) => x.ten).join(", ")}.
          </p>
        ) : (
          <p className="font-medium text-green-600">Đủ mọi model đang cần cho các tính năng đã bật.</p>
        )}
        <p className="text-muted-foreground">
          Ảnh Docker không kèm model. Bấm «Tải xuống» để máy chủ tự tải, hoặc chép lệnh chạy trên MÁY
          CHỦ (nơi có container <code>c2a</code>) — model tải về thư mục dữ liệu nên chỉ làm MỘT lần,
          cập nhật ảnh không mất. Tải xong thì bấm
          «Kiểm lại» — model nạp ở lần dùng đầu, không cần khởi động lại; riêng cổng Wyoming cho Home
          Assistant chỉ mở lúc c2a khởi động, nên tải model của một tiếng mới xong thì khởi động lại c2a
          một lần. «Cần» = tính năng đang bật / giọng đang gán dùng tới; «Tuỳ chọn» = chỉ khi dùng.
        </p>
        <button type="button" className="rounded border px-2 py-0.5 text-xs" onClick={() => void tai()}>
          Kiểm lại
        </button>
      </div>
      {nhom.map((n) => (
        <div key={n} className="space-y-2">
          <div className="text-sm font-medium">{n}</div>
          {ds.filter((x) => x.nhom === n).map((x) => (
            <div key={x.ma} className="rounded border p-2 text-sm space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className={x.da_tai ? "text-green-600" : x.muc_do === "can" ? "text-destructive" : "text-muted-foreground"}>
                  {x.da_tai ? "✓ Đã có" : "✗ Chưa có"}
                </span>
                <span className="font-medium">{x.ten}</span>
                <span className="rounded bg-muted px-1 text-xs">{NHAN_MUC_DO[x.muc_do]}</span>
                <span className="text-xs text-muted-foreground">{x.dung_luong}</span>
              </div>
              <div className="text-xs text-muted-foreground">{x.dung_cho}{x.ghi_chu ? ` — ${x.ghi_chu}` : ""}</div>
              {[{ lenh: x.lenh, mo_ta: "", chinh: true }, ...x.them.map((l) => ({ ...l, chinh: false }))].map((l) => (
                <div key={l.lenh} className="flex flex-wrap items-center gap-2">
                  <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded bg-muted px-1 py-0.5 text-xs">{l.lenh}</code>
                  <button type="button" className="rounded border px-2 py-0.5 text-xs" onClick={() => chep(l.lenh)}>
                    {daChep === l.lenh ? "Đã chép" : "Chép"}
                  </button>
                  {l.chinh && !x.da_tai ? <NutTaiModel lenh={l.lenh} onXong={() => void tai()} /> : null}
                  {!l.chinh ? <NutTaiModel lenh={l.lenh} nhan="Tải thêm" onXong={() => void tai()} /> : null}
                  {l.mo_ta ? <span className="text-xs text-muted-foreground">{l.mo_ta}</span> : null}
                </div>
              ))}
              {x.bien_the?.length ? (
                <div className="space-y-1 border-l pl-2">
                  <div className="text-xs text-muted-foreground">Các bản (chọn bản dùng ở thẻ Nhìn nhà):</div>
                  {x.bien_the.map((b) => (
                    <div key={b.ma} className="flex flex-wrap items-center gap-2 text-xs">
                      <span className={b.da_tai ? "text-green-600" : "text-muted-foreground"}>{b.da_tai ? "✓" : "✗"}</span>
                      <span className="font-medium">{b.ten}</span>
                      <span className="text-muted-foreground">{b.mo_ta}</span>
                      {!b.da_tai ? <NutTaiModel lenh={b.lenh} onXong={() => void tai()} /> : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
