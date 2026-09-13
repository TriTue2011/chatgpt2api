"use client";

/**
 * Thiết bị & tên — danh sách ĐẦY ĐỦ thiết bị/thực thể (HA + MQTT + Tuya), bấm
 * vào đặt tên/khu vực ngay. Trước đây phần này nằm trong tab "Học hỏi" nhưng
 * chỉ liệt kê thứ ĐÃ TỪNG gặp (sổ tên), không cho duyệt toàn bộ danh sách
 * thiết bị đang có — chủ máy chốt chuyển sang đây, đúng chỗ quản lý thiết bị.
 *
 * Chủ máy 13/09/2026: "chia tầng 1 là homeassistant, MQTT, tuya. Tầng 2 chia
 * theo từng loại, xem homeassistant", và "thêm cả nút xóa thiết bị … để xóa
 * các thiết bị không cần thiết" — chọn nghĩa BỎ KHỎI c2a (thiết bị vẫn còn
 * trong HA) và xoá luôn lịch sử. Tên nhóm tầng 2 do máy chủ tính
 * (`api/hoc_hoi.nhom_ha`), thẻ này chỉ gom và hiện.
 *
 * Chủ máy 13/09/2026: "hơn 100 cái lâu quá, thêm bỏ tất cả và tích các cái cần
 * bỏ rồi bỏ qua theo các mục tích" — tích từng hàng, cả nhóm, hoặc mọi mục đang
 * hiện, rồi bỏ một lượt (`/api/hoc-hoi/thiet-bi/bo-nhieu`). Sổ đã bỏ nằm trong
 * DATA_DIR nên cập nhật ảnh không mất.
 */

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Trash2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { httpRequest } from "@/lib/request";

type Muc = {
  khoa: string;
  nguon: "ha" | "mqtt" | "tuya";
  ma: string;
  ten_goc: string;
  ten: string;
  khu_vuc: string;
  khu_vuc_goi_y: string;
  nhom: string;
  da_bo: boolean;
};

const NGUON: { khoa: Muc["nguon"]; nhan: string }[] = [
  { khoa: "ha", nhan: "Home Assistant" },
  { khoa: "mqtt", nhan: "MQTT" },
  { khoa: "tuya", nhan: "Tuya" },
];

const NHOM_DA_BO = "Đã bỏ khỏi c2a";

/** Nhóm "khác" và "đã bỏ" xuống cuối; còn lại theo bảng chữ cái. */
function thuTuNhom(a: string, b: string): number {
  const cuoi = (n: string) => (n === NHOM_DA_BO ? 2 : /khác/i.test(n) ? 1 : 0);
  return cuoi(a) - cuoi(b) || a.localeCompare(b, "vi");
}

export function HaDevicesCard() {
  const [ds, setDs] = useState<Muc[]>([]);
  const [dangTai, setDangTai] = useState(false);
  const [loc, setLoc] = useState("");
  const [nguon, setNguon] = useState<Muc["nguon"]>("ha");
  const [nhap, setNhap] = useState<Record<string, { ten: string; khu_vuc: string }>>({});
  const [tin, setTin] = useState("");
  const [chon, setChon] = useState<Set<string>>(new Set());
  const [dangBo, setDangBo] = useState(false);

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const r = await httpRequest<{ danh_sach?: Muc[] }>(
        "/api/hoc-hoi/thiet-bi-day-du?kem_da_bo=1", { method: "GET" });
      setDs(r.danh_sach || []);
      setNhap({});
      setChon(new Set());
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => { void tai(); }, [tai]);

  const luu = async (m: Muc) => {
    const v = nhap[m.khoa] || { ten: m.ten, khu_vuc: m.khu_vuc || m.khu_vuc_goi_y };
    const res = await httpRequest<{ ok?: boolean }>("/api/hoc-hoi/ten/dat", {
      method: "POST",
      body: { nguon: m.nguon, loai: "thiet_bi", ma: m.ma, ten: v.ten, khu_vuc: v.khu_vuc },
    });
    if (res?.ok) void tai();
  };
  const xoaTen = async (khoa: string) => {
    await httpRequest("/api/hoc-hoi/ten/xoa", { method: "POST", body: { khoa } });
    void tai();
  };
  const boThietBi = async (m: Muc) => {
    if (!window.confirm(
      `Bỏ "${m.ten || m.ten_goc}" khỏi c2a?\n\nBot sẽ không thấy, không điều khiển, không học thiết bị này, `
      + "và LỊCH SỬ c2a đã ghi của nó bị xoá (không lấy lại được). "
      + "Thiết bị vẫn còn nguyên trong Home Assistant / MQTT / Tuya.")) return;
    const r = await httpRequest<{ ok?: boolean; error?: string; xoa?: { su_kien: number; so_do: number } }>(
      "/api/hoc-hoi/thiet-bi/bo", { method: "POST", body: { nguon: m.nguon, ma: m.ma } });
    setTin(r.ok
      ? `Đã bỏ "${m.ten || m.ten_goc}" — xoá ${r.xoa?.su_kien ?? 0} sự kiện, ${r.xoa?.so_do ?? 0} số đo.`
      : `Không bỏ được: ${r.error || "lỗi không rõ"}`);
    if (r.ok) void tai();
  };
  const boDaTich = async () => {
    const muc = ds.filter((m) => chon.has(m.khoa) && !m.da_bo);
    if (!muc.length || !window.confirm(
      `Bỏ ${muc.length} thiết bị đã tích khỏi c2a?\n\nBot sẽ không thấy, không điều khiển, không học các thiết bị này, `
      + "và LỊCH SỬ c2a đã ghi của chúng bị xoá (không lấy lại được). "
      + "Thiết bị vẫn còn nguyên trong Home Assistant / MQTT / Tuya.")) return;
    setDangBo(true);
    try {
      const r = await httpRequest<{
        ok?: boolean; error?: string; da_bo?: string[];
        loi?: { ma: string; error: string }[]; xoa?: { su_kien: number; so_do: number };
      }>("/api/hoc-hoi/thiet-bi/bo-nhieu", {
        method: "POST", body: { muc: muc.map((m) => ({ nguon: m.nguon, ma: m.ma })) },
      });
      if (!r.ok) {
        setTin(`Không bỏ được: ${r.error || "lỗi không rõ"}`);
        return;
      }
      const loi = r.loi || [];
      setTin(`Đã bỏ ${r.da_bo?.length ?? 0} thiết bị — xoá ${r.xoa?.su_kien ?? 0} sự kiện, ${r.xoa?.so_do ?? 0} số đo.`
        + (loi.length ? ` ${loi.length} mục không bỏ được: ${loi.slice(0, 3).map((x) => `${x.ma} (${x.error})`).join("; ")}` : ""));
      void tai();
    } finally {
      setDangBo(false);
    }
  };
  const doiChon = (khoa: string[], bat: boolean) => {
    const moi = new Set(chon);
    for (const k of khoa) {
      if (bat) moi.add(k); else moi.delete(k);
    }
    setChon(moi);
  };
  const khoiPhuc = async (m: Muc) => {
    const r = await httpRequest<{ ok?: boolean; error?: string }>(
      "/api/hoc-hoi/thiet-bi/bo-lai", { method: "POST", body: { nguon: m.nguon, ma: m.ma } });
    setTin(r.ok ? `Đã khôi phục "${m.ten_goc}".` : `Không khôi phục được: ${r.error || "lỗi không rõ"}`);
    if (r.ok) void tai();
  };

  const locXuong = loc.trim().toLowerCase();
  const khop = (m: Muc) => !locXuong || m.ten_goc.toLowerCase().includes(locXuong)
    || m.ten.toLowerCase().includes(locXuong) || m.ma.toLowerCase().includes(locXuong);
  const demNguon = (k: Muc["nguon"]) => ds.filter((m) => m.nguon === k && !m.da_bo).length;
  const theoNhom = new Map<string, Muc[]>();
  for (const m of ds.filter((x) => x.nguon === nguon && khop(x))) {
    const n = m.nhom || "Khác";
    theoNhom.set(n, [...(theoNhom.get(n) || []), m]);
  }
  const nhom = [...theoNhom.keys()].sort(thuTuNhom);
  const dangHien = [...theoNhom.values()].flat().filter((m) => !m.da_bo).map((m) => m.khoa);
  const soChon = ds.filter((m) => chon.has(m.khoa) && !m.da_bo).length;

  return (
    <div className="space-y-3 rounded-xl border-2 border-slate-200 bg-[var(--card)]/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-xs font-bold text-slate-800">Thiết bị & tên</p>
          <p className="text-[10px] text-[var(--muted-foreground)]">
            Toàn bộ thiết bị/thực thể đang có, chia theo nguồn rồi theo loại. Bấm vào đặt tên và khu vực.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      {/* Tầng 1: nguồn */}
      <div className="flex flex-wrap gap-1.5">
        {NGUON.map((n) => (
          <button key={n.khoa} type="button" onClick={() => setNguon(n.khoa)}
            className={"rounded-full border px-3 py-1 text-xs " + (nguon === n.khoa
              ? "border-transparent bg-primary text-primary-foreground"
              : "text-muted-foreground")}>
            {n.nhan} ({demNguon(n.khoa)})
          </button>
        ))}
      </div>

      <Input placeholder="Lọc theo tên hoặc mã…" value={loc} onChange={(e) => setLoc(e.target.value)}
        className="h-8 text-xs" />
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Button variant="outline" size="sm" className="h-7" disabled={!dangHien.length}
          onClick={() => doiChon(dangHien, true)}>
          Chọn tất cả ({dangHien.length})
        </Button>
        {soChon ? (
          <>
            <span className="text-[var(--muted-foreground)]">Đã tích {soChon}</span>
            <Button variant="ghost" size="sm" className="h-7" onClick={() => setChon(new Set())}>Bỏ chọn</Button>
            <Button variant="outline" size="sm" className="h-7 text-destructive" disabled={dangBo}
              onClick={() => void boDaTich()}>
              {dangBo ? <LoaderCircle className="mr-1 size-3.5 animate-spin" /> : <Trash2 className="mr-1 size-3.5" />}
              Bỏ {soChon} mục đã tích
            </Button>
          </>
        ) : null}
      </div>
      {tin ? <p className="text-[11px] text-[var(--muted-foreground)]">{tin}</p> : null}

      {dangTai && !ds.length ? (
        <div className="flex items-center gap-2 p-2 text-xs text-[var(--muted-foreground)]">
          <LoaderCircle className="size-4 animate-spin" /> Đang tải…
        </div>
      ) : (
        <div className="max-h-[36rem] space-y-1.5 overflow-auto">
          {/* Tầng 2: loại. Đang lọc thì mở sẵn mọi nhóm để thấy ngay kết quả. */}
          {nhom.map((n) => {
            const khoaNhom = (theoNhom.get(n) || []).filter((m) => !m.da_bo).map((m) => m.khoa);
            const caNhom = khoaNhom.length > 0 && khoaNhom.every((k) => chon.has(k));
            return (
            <details key={`${nguon}-${n}-${locXuong ? "loc" : ""}`} open={!!locXuong}
              className="rounded border border-border">
              <summary className="flex cursor-pointer select-none items-center gap-2 bg-muted/40 px-2 py-1.5 text-xs font-medium">
                {khoaNhom.length ? (
                  <input type="checkbox" checked={caNhom} title="Tích cả nhóm"
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => doiChon(khoaNhom, e.target.checked)} />
                ) : null}
                <span>{n} <span className="text-[var(--muted-foreground)]">({theoNhom.get(n)?.length})</span></span>
              </summary>
              <div className="divide-y divide-border/60">
                {(theoNhom.get(n) || []).map((m) => {
                  const v = nhap[m.khoa] || { ten: m.ten, khu_vuc: m.khu_vuc || m.khu_vuc_goi_y };
                  return (
                    <div key={m.khoa} className="grid gap-1.5 px-2 py-1.5 text-xs sm:grid-cols-[1fr_10rem_8rem_auto] sm:items-center">
                      <label className="flex min-w-0 items-start gap-2">
                        {m.da_bo ? null : (
                          <input type="checkbox" className="mt-0.5" checked={chon.has(m.khoa)}
                            onChange={(e) => doiChon([m.khoa], e.target.checked)} />
                        )}
                        <span className="min-w-0">
                          <span className="block truncate">{m.ten_goc}</span>
                          <span className="block truncate text-[10px] text-[var(--muted-foreground)]">{m.ma}</span>
                        </span>
                      </label>
                      {m.da_bo ? (
                        <div className="text-[10px] text-[var(--muted-foreground)] sm:col-span-2">
                          Bot không thấy thiết bị này; lịch sử cũ đã xoá.
                        </div>
                      ) : (
                        <>
                          <Input value={v.ten} placeholder="chưa đặt tên" className="h-7 text-xs"
                            onChange={(e) => setNhap({ ...nhap, [m.khoa]: { ...v, ten: e.target.value } })} />
                          <Input value={v.khu_vuc} className="h-7 text-xs"
                            placeholder={m.khu_vuc_goi_y ? `gợi ý: ${m.khu_vuc_goi_y}` : "khu vực"}
                            onChange={(e) => setNhap({ ...nhap, [m.khoa]: { ...v, khu_vuc: e.target.value } })} />
                        </>
                      )}
                      <div className="flex flex-wrap justify-end gap-1">
                        {m.da_bo ? (
                          <Button variant="outline" size="sm" className="h-7" onClick={() => void khoiPhuc(m)}>
                            <Undo2 className="mr-1 size-3.5" /> Khôi phục
                          </Button>
                        ) : (
                          <>
                            <Button variant="outline" size="sm" className="h-7" onClick={() => void luu(m)}>Lưu</Button>
                            {m.ten ? (
                              <Button variant="ghost" size="sm" className="h-7" title="Xoá tên đã đặt"
                                onClick={() => void xoaTen(m.khoa)}>Xoá tên</Button>
                            ) : null}
                            <Button variant="ghost" size="sm" className="h-7 text-destructive"
                              title="Bỏ khỏi c2a và xoá lịch sử" onClick={() => void boThietBi(m)}>
                              <Trash2 className="mr-1 size-3.5" /> Bỏ
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </details>
            );
          })}
          {!nhom.length ? (
            <p className="px-2 py-3 text-center text-xs text-[var(--muted-foreground)]">Không có thiết bị nào khớp.</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
