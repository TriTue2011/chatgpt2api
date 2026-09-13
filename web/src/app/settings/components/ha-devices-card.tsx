"use client";

/**
 * Thiết bị & tên — danh sách ĐẦY ĐỦ thiết bị/thực thể (HA + MQTT + Tuya).
 *
 * Chủ máy 13/09/2026:
 * - "chia tầng 1 là homeassistant, MQTT, tuya. Tầng 2 chia theo từng loại";
 * - "thêm cả nút xóa thiết bị" → BỎ KHỎI c2a (thiết bị vẫn còn trong HA), xoá
 *   lịch sử c2a; "hơn 100 cái lâu quá, thêm bỏ tất cả và tích các cái cần bỏ";
 * - "Khôi phục tôi cũng muốn chia rõ ràng từng mục chứ không gộp toàn bộ" → mục
 *   đã bỏ có trang riêng, chia theo đúng loại, tích rồi khôi phục một lượt;
 * - "phía trên là tên phía dưới là cảm biến rồi nên đâu cần đặt tên mà là chỉnh
 *   sửa tên" → ô tên điền sẵn tên hiện tại;
 * - "search theo tên hoặc entity … tìm cả ở đã bỏ qua lẫn không bỏ qua" → ô tìm
 *   quét MỌI nguồn, cả đang dùng lẫn đã bỏ.
 * Tên nhóm tầng 2 do máy chủ tính (`api/hoc_hoi.nhom_ha`), thẻ này chỉ gom và hiện.
 * Sổ đã bỏ nằm trong DATA_DIR nên cập nhật ảnh không mất.
 */

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Search, Trash2, Undo2 } from "lucide-react";

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
const TEN_NGUON: Record<Muc["nguon"], string> = { ha: "HA", mqtt: "MQTT", tuya: "Tuya" };

/** Nhóm "khác" xuống cuối; còn lại theo bảng chữ cái. */
function thuTuNhom(a: string, b: string): number {
  const cuoi = (n: string) => (/khác/i.test(n) ? 1 : 0);
  return cuoi(a) - cuoi(b) || a.localeCompare(b, "vi");
}

/** So khớp không phân biệt dấu và hoa thường: "den bep" tìm ra "Đèn bếp". */
function boDau(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
}

export function HaDevicesCard() {
  const [ds, setDs] = useState<Muc[]>([]);
  const [dangTai, setDangTai] = useState(false);
  const [tim, setTim] = useState("");
  const [nguon, setNguon] = useState<Muc["nguon"]>("ha");
  const [xemDaBo, setXemDaBo] = useState(false);
  const [nhap, setNhap] = useState<Record<string, { ten: string; khu_vuc: string }>>({});
  const [tin, setTin] = useState("");
  const [chon, setChon] = useState<Set<string>>(new Set());
  const [dangLam, setDangLam] = useState(false);

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

  const tenHienTai = (m: Muc) => m.ten || m.ten_goc;
  const giaTri = (m: Muc) => nhap[m.khoa] || { ten: tenHienTai(m), khu_vuc: m.khu_vuc || m.khu_vuc_goi_y };

  const luu = async (m: Muc) => {
    const v = giaTri(m);
    const res = await httpRequest<{ ok?: boolean; error?: string }>("/api/hoc-hoi/ten/dat", {
      method: "POST",
      body: { nguon: m.nguon, loai: "thiet_bi", ma: m.ma, ten: v.ten.trim(), khu_vuc: v.khu_vuc.trim() },
    });
    setTin(res?.ok ? `Đã lưu "${v.ten.trim()}".` : `Không lưu được: ${res?.error || "lỗi không rõ"}`);
    if (res?.ok) void tai();
  };
  const veTenGoc = async (m: Muc) => {
    await httpRequest("/api/hoc-hoi/ten/xoa", { method: "POST", body: { khoa: m.khoa } });
    setTin(`"${m.ma}" dùng lại tên gốc "${m.ten_goc}".`);
    void tai();
  };

  const lamNhieu = async (muc: Muc[], boDi: boolean) => {
    if (!muc.length) return;
    if (boDi && !window.confirm(
      `Bỏ ${muc.length} thiết bị khỏi c2a?\n\nBot sẽ không thấy, không điều khiển, không học các thiết bị này, `
      + "và LỊCH SỬ c2a đã ghi của chúng bị xoá (không lấy lại được). "
      + "Thiết bị vẫn còn nguyên trong Home Assistant / MQTT / Tuya.")) return;
    setDangLam(true);
    try {
      const body = { muc: muc.map((m) => ({ nguon: m.nguon, ma: m.ma })) };
      if (boDi) {
        const r = await httpRequest<{
          ok?: boolean; error?: string; da_bo?: string[];
          loi?: { ma: string; error: string }[]; xoa?: { su_kien: number; so_do: number };
        }>("/api/hoc-hoi/thiet-bi/bo-nhieu", { method: "POST", body });
        const loi = r.loi || [];
        setTin(!r.ok ? `Không bỏ được: ${r.error || "lỗi không rõ"}`
          : `Đã bỏ ${r.da_bo?.length ?? 0} thiết bị — xoá ${r.xoa?.su_kien ?? 0} sự kiện, ${r.xoa?.so_do ?? 0} số đo.`
            + (loi.length ? ` ${loi.length} mục không bỏ được: ${loi.slice(0, 3).map((x) => `${x.ma} (${x.error})`).join("; ")}` : ""));
        if (r.ok) void tai();
      } else {
        const r = await httpRequest<{ ok?: boolean; error?: string; khoi_phuc?: string[] }>(
          "/api/hoc-hoi/thiet-bi/bo-lai-nhieu", { method: "POST", body });
        setTin(r.ok
          ? `Đã khôi phục ${r.khoi_phuc?.length ?? 0} thiết bị — bot thấy lại ngay, lịch sử ghi từ bây giờ.`
          : `Không khôi phục được: ${r.error || "lỗi không rõ"}`);
        if (r.ok) void tai();
      }
    } finally {
      setDangLam(false);
    }
  };

  const doiChon = (khoa: string[], bat: boolean) => {
    const moi = new Set(chon);
    for (const k of khoa) {
      if (bat) moi.add(k); else moi.delete(k);
    }
    setChon(moi);
  };

  // Đang tìm: quét MỌI nguồn, cả đang dùng lẫn đã bỏ. Không tìm: theo nguồn và trang.
  const timXuong = boDau(tim.trim());
  const dangTim = timXuong.length > 0;
  const hien = ds.filter((m) => dangTim
    ? [m.ten_goc, m.ten, m.ma].some((x) => boDau(x).includes(timXuong))
    : m.nguon === nguon && m.da_bo === xemDaBo);
  const theoNhom = new Map<string, Muc[]>();
  for (const m of hien) {
    const n = m.nhom || "Khác";
    theoNhom.set(n, [...(theoNhom.get(n) || []), m]);
  }
  const nhom = [...theoNhom.keys()].sort(thuTuNhom);
  const dem = (k: Muc["nguon"], daBo: boolean) => ds.filter((m) => m.nguon === k && m.da_bo === daBo).length;
  const daTich = ds.filter((m) => chon.has(m.khoa));
  const tichDangDung = daTich.filter((m) => !m.da_bo);
  const tichDaBo = daTich.filter((m) => m.da_bo);

  return (
    <div className="space-y-3 rounded-xl border-2 border-slate-200 bg-[var(--card)]/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-xs font-bold text-slate-800">Thiết bị & tên</p>
          <p className="text-[10px] text-[var(--muted-foreground)]">
            Toàn bộ thiết bị/thực thể, chia theo nguồn rồi theo loại. Sửa tên cho dễ gọi, bỏ thứ bot không cần.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-2 size-4 text-[var(--muted-foreground)]" />
        <Input placeholder="Tìm theo tên hoặc entity — tìm cả mục đang dùng lẫn đã bỏ…" value={tim}
          onChange={(e) => setTim(e.target.value)} className="h-8 pl-8 text-xs" />
      </div>

      {dangTim ? (
        <p className="text-[11px] text-[var(--muted-foreground)]">
          {hien.length} kết quả ở mọi nguồn ({hien.filter((m) => m.da_bo).length} đã bỏ).
        </p>
      ) : (
        <>
          {/* Tầng 1: nguồn */}
          <div className="flex flex-wrap gap-1.5">
            {NGUON.map((n) => (
              <button key={n.khoa} type="button" onClick={() => setNguon(n.khoa)}
                className={"rounded-full border px-3 py-1 text-xs " + (nguon === n.khoa
                  ? "border-transparent bg-primary text-primary-foreground"
                  : "text-muted-foreground")}>
                {n.nhan} ({dem(n.khoa, false)})
              </button>
            ))}
          </div>
          {/* Đang dùng / đã bỏ — mỗi trang chia theo loại như nhau */}
          <div className="flex gap-1 text-xs">
            {[false, true].map((daBo) => (
              <button key={String(daBo)} type="button" onClick={() => setXemDaBo(daBo)}
                className={"rounded border px-2.5 py-1 " + (xemDaBo === daBo
                  ? "border-primary font-medium text-primary" : "text-muted-foreground")}>
                {daBo ? "Đã bỏ" : "Đang dùng"} ({dem(nguon, daBo)})
              </button>
            ))}
          </div>
        </>
      )}

      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Button variant="outline" size="sm" className="h-7" disabled={!hien.length}
          onClick={() => doiChon(hien.map((m) => m.khoa), true)}>
          Chọn tất cả ({hien.length})
        </Button>
        {daTich.length ? (
          <>
            <span className="text-[var(--muted-foreground)]">Đã tích {daTich.length}</span>
            <Button variant="ghost" size="sm" className="h-7" onClick={() => setChon(new Set())}>Bỏ chọn</Button>
            {tichDangDung.length ? (
              <Button variant="outline" size="sm" className="h-7 text-destructive" disabled={dangLam}
                onClick={() => void lamNhieu(tichDangDung, true)}>
                {dangLam ? <LoaderCircle className="mr-1 size-3.5 animate-spin" /> : <Trash2 className="mr-1 size-3.5" />}
                Bỏ {tichDangDung.length} mục
              </Button>
            ) : null}
            {tichDaBo.length ? (
              <Button variant="outline" size="sm" className="h-7" disabled={dangLam}
                onClick={() => void lamNhieu(tichDaBo, false)}>
                {dangLam ? <LoaderCircle className="mr-1 size-3.5 animate-spin" /> : <Undo2 className="mr-1 size-3.5" />}
                Khôi phục {tichDaBo.length} mục
              </Button>
            ) : null}
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
          {/* Tầng 2: loại. Đang tìm thì mở sẵn mọi nhóm để thấy ngay kết quả. */}
          {nhom.map((n) => {
            const muc = theoNhom.get(n) || [];
            const caNhom = muc.length > 0 && muc.every((m) => chon.has(m.khoa));
            return (
              <details key={`${nguon}-${xemDaBo}-${n}-${dangTim ? "tim" : ""}`} open={dangTim}
                className="rounded border border-border">
                <summary className="flex cursor-pointer select-none items-center gap-2 bg-muted/40 px-2 py-1.5 text-xs font-medium">
                  <input type="checkbox" checked={caNhom} title="Tích cả nhóm"
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => doiChon(muc.map((m) => m.khoa), e.target.checked)} />
                  <span>{n} <span className="text-[var(--muted-foreground)]">({muc.length})</span></span>
                </summary>
                <div className="divide-y divide-border/60">
                  {muc.map((m) => {
                    const v = giaTri(m);
                    const doiTen = v.ten.trim() !== tenHienTai(m) || v.khu_vuc.trim() !== (m.khu_vuc || m.khu_vuc_goi_y);
                    return (
                      <div key={m.khoa} className="grid gap-1.5 px-2 py-1.5 text-xs sm:grid-cols-[1.2rem_1fr_9rem_auto] sm:items-center">
                        <input type="checkbox" checked={chon.has(m.khoa)}
                          onChange={(e) => doiChon([m.khoa], e.target.checked)} />
                        <div className="min-w-0 space-y-1">
                          <Input value={v.ten} className="h-7 text-xs" title="Sửa tên cho dễ gọi"
                            onChange={(e) => setNhap({ ...nhap, [m.khoa]: { ...v, ten: e.target.value } })} />
                          <div className="flex min-w-0 flex-wrap items-center gap-1 text-[10px] text-[var(--muted-foreground)]">
                            <span className="truncate">{m.ma}</span>
                            {dangTim ? <span className="rounded bg-muted px-1">{TEN_NGUON[m.nguon]}</span> : null}
                            {m.da_bo ? <span className="rounded bg-amber-100 px-1 text-amber-800">đã bỏ</span> : null}
                            {m.ten ? <span title={`Tên gốc: ${m.ten_goc}`}>· gốc: {m.ten_goc}</span> : null}
                          </div>
                        </div>
                        <Input value={v.khu_vuc} className="h-7 text-xs"
                          placeholder={m.khu_vuc_goi_y ? `gợi ý: ${m.khu_vuc_goi_y}` : "khu vực"}
                          onChange={(e) => setNhap({ ...nhap, [m.khoa]: { ...v, khu_vuc: e.target.value } })} />
                        <div className="flex flex-wrap justify-end gap-1">
                          <Button variant="outline" size="sm" className="h-7" disabled={!doiTen || !v.ten.trim()}
                            onClick={() => void luu(m)}>Lưu</Button>
                          {m.ten ? (
                            <Button variant="ghost" size="sm" className="h-7" title="Bỏ tên đã sửa, dùng lại tên gốc"
                              onClick={() => void veTenGoc(m)}>Tên gốc</Button>
                          ) : null}
                          {m.da_bo ? (
                            <Button variant="outline" size="sm" className="h-7" disabled={dangLam}
                              onClick={() => void lamNhieu([m], false)}>
                              <Undo2 className="mr-1 size-3.5" /> Khôi phục
                            </Button>
                          ) : (
                            <Button variant="ghost" size="sm" className="h-7 text-destructive" disabled={dangLam}
                              title="Bỏ khỏi c2a và xoá lịch sử" onClick={() => void lamNhieu([m], true)}>
                              <Trash2 className="mr-1 size-3.5" /> Bỏ
                            </Button>
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
            <p className="px-2 py-3 text-center text-xs text-[var(--muted-foreground)]">
              {dangTim ? "Không có thiết bị nào khớp." : xemDaBo ? "Chưa bỏ thiết bị nào ở nguồn này." : "Không có thiết bị nào."}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
