"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Trash2, Plus, Save, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { httpRequest } from "@/lib/request";
import { layGet, goiPost } from "./lib";
import { SuaDieuKien } from "./sua-dieu-kien";
import { ChonThietBi } from "./chon-thiet-bi";

type KetLuan = {
  id: number;
  loai_cau_hoi: string;
  khoa: string;
  ket_qua: string;
  cham_boi: string;
  ghi_chu: string;
  mo_ta?: string;
};
type DuKien = { id: number; luc: string; noi_dung: string };
type LanGiai = { id: number; luc: string; model: string; so_nhom: number; loi: string };

export function HieuThietBi() {
  const [ketLuan, setKetLuan] = useState<KetLuan[]>([]);
  const [duKien, setDuKien] = useState<DuKien[]>([]);
  const [lichSu, setLichSu] = useState<LanGiai[]>([]);
  const [huongDan, setHuongDan] = useState("");
  const [banHuongDan, setBanHuongDan] = useState("");
  const [dangTai, setDangTai] = useState(false);
  const [dkMoi, setDkMoi] = useState("");
  const [suaKhoa, setSuaKhoa] = useState<string | null>(null);
  const [dangPhanTich, setDangPhanTich] = useState(false);
  const [ketQuaPhanTich, setKetQuaPhanTich] = useState("");

  const tai = useCallback(async () => {
    setDangTai(true);
    try {
      const [kl, dk, ls, hd] = await Promise.all([
        layGet<{ danh_sach?: KetLuan[] }>("/api/hoc-hoi/ket-luan"),
        layGet<{ danh_sach?: DuKien[] }>("/api/hoc-hoi/du-kien"),
        layGet<{ danh_sach?: LanGiai[] }>("/api/hoc-hoi/lich-su-giai"),
        layGet<{ noi_dung?: string; phien_ban?: string }>("/api/hoc-hoi/huong-dan"),
      ]);
      setKetLuan(kl.danh_sach || []);
      setDuKien(dk.danh_sach || []);
      setLichSu(ls.danh_sach || []);
      setHuongDan(hd.noi_dung || "");
      setBanHuongDan(hd.phien_ban || "");
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => {
    void tai();
  }, [tai]);

  const cham = async (id: number, dung: boolean) => {
    if (await goiPost("/api/hoc-hoi/ket-luan/cham", { id, dung })) void tai();
  };
  const xoaKl = async (id: number) => {
    if (await goiPost("/api/hoc-hoi/ket-luan/xoa", { id })) void tai();
  };
  const themDk = async () => {
    if (!dkMoi.trim()) return;
    if (await goiPost("/api/hoc-hoi/du-kien/ghi", { noi_dung: dkMoi })) {
      setDkMoi("");
      void tai();
    }
  };
  const xoaDk = async (id: number) => {
    if (await goiPost("/api/hoc-hoi/du-kien/xoa", { id })) void tai();
  };
  const luuHuongDan = async () => {
    if (await goiPost("/api/hoc-hoi/huong-dan/ghi", { noi_dung: huongDan })) void tai();
  };

  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dangTai}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      {/* Chọn thiết bị bot bỏ sót → phân tích ngay */}
      <section className="rounded border border-border p-2">
        <p className="mb-1 text-xs font-semibold">Thiết bị bot bỏ sót? Chọn để phân tích ngay</p>
        <ChonThietBi
          dangChay={dangPhanTich}
          nhanNut="Phân tích ngay"
          icon={<Sparkles className="mr-1 size-3.5" />}
          onChon={async (ma) => {
            setDangPhanTich(true);
            setKetQuaPhanTich("");
            try {
              const r = await httpRequest<{ ok?: boolean; moi?: number; lap_lai?: number; error?: string }>(
                "/api/hoc-hoi/phan-tich-thiet-bi", { method: "POST", body: { ma } });
              setKetQuaPhanTich(r.ok
                ? `Xong — ${r.moi ?? 0} kết luận mới, ${r.lap_lai ?? 0} lặp lại.`
                : `Không phân tích được: ${r.error || "lỗi không rõ"}`);
              if (r.ok) void tai();
            } finally {
              setDangPhanTich(false);
            }
          }}
        />
        {ketQuaPhanTich ? <p className="mt-1 text-[11px] text-muted-foreground">{ketQuaPhanTich}</p> : null}
      </section>

      {/* Kết luận */}
      <section>
        <p className="mb-1 text-xs font-semibold">Kết luận đang hiệu lực</p>
        <div className="max-h-80 overflow-auto rounded border border-border">
          {ketLuan.map((k) => (
            <div key={k.id} className="border-b border-border/60 px-2 py-1.5 text-xs last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{k.mo_ta || k.khoa}</span>
                <span className="text-muted-foreground">[{k.loai_cau_hoi}]</span>
                <span
                  className={
                    k.ket_qua === "dung" ? "text-green-600" : k.ket_qua === "sai" ? "text-destructive" : "text-amber-600"
                  }
                >
                  {k.ket_qua}
                  {k.cham_boi ? ` · ${k.cham_boi}` : ""}
                </span>
              </div>
              {k.ghi_chu ? <p className="text-muted-foreground">{k.ghi_chu}</p> : null}
              <div className="mt-1 flex flex-wrap gap-1">
                <Button variant="outline" size="sm" className="h-7" onClick={() => void cham(k.id, true)}>Đúng</Button>
                <Button variant="outline" size="sm" className="h-7" onClick={() => void cham(k.id, false)}>Sai</Button>
                {(k.loai_cau_hoi === "hoc" || k.loai_cau_hoi === "dieu_kien") ? (
                  <Button variant="outline" size="sm" className="h-7"
                    onClick={() => setSuaKhoa(suaKhoa === k.khoa ? null : k.khoa)}>
                    Sửa điều kiện
                  </Button>
                ) : null}
                <Button variant="ghost" size="sm" className="h-7 text-destructive" onClick={() => void xoaKl(k.id)}>
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
              {suaKhoa === k.khoa ? (
                <SuaDieuKien khoa={k.khoa} onXong={() => { setSuaKhoa(null); void tai(); }} />
              ) : null}
            </div>
          ))}
          {!ketLuan.length ? <p className="px-2 py-3 text-center text-xs text-muted-foreground">Chưa có kết luận.</p> : null}
        </div>
      </section>

      {/* Sổ dữ kiện */}
      <section>
        <p className="mb-1 text-xs font-semibold">Sổ dữ kiện (chủ máy dạy bot)</p>
        <div className="mb-2 flex gap-1">
          <Input placeholder="thêm một dữ kiện…" value={dkMoi} className="h-8 text-xs"
            onChange={(e) => setDkMoi(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void themDk()} />
          <Button size="sm" className="h-8 shrink-0" onClick={() => void themDk()}><Plus className="size-3.5" /></Button>
        </div>
        <div className="max-h-64 overflow-auto rounded border border-border">
          {duKien.map((f) => (
            <div key={f.id} className="flex items-start justify-between gap-2 border-b border-border/60 px-2 py-1.5 text-xs last:border-0">
              <span><span className="text-muted-foreground">{f.luc} · </span>{f.noi_dung}</span>
              <Button variant="ghost" size="sm" className="h-6 shrink-0 text-destructive" onClick={() => void xoaDk(f.id)}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
          {!duKien.length ? <p className="px-2 py-3 text-center text-xs text-muted-foreground">Chưa có dữ kiện.</p> : null}
        </div>
      </section>

      {/* Hướng dẫn */}
      <section>
        <div className="mb-1 flex items-center justify-between">
          <p className="text-xs font-semibold">Hướng dẫn giải (bản đang dùng)</p>
          <span className="text-[11px] text-muted-foreground">phiên bản {banHuongDan || "—"}</span>
        </div>
        <Textarea value={huongDan} onChange={(e) => setHuongDan(e.target.value)}
          className="min-h-40 font-mono text-xs" spellCheck={false} />
        <div className="mt-1 flex justify-end">
          <Button size="sm" onClick={() => void luuHuongDan()}><Save className="mr-1 size-3.5" /> Lưu hướng dẫn</Button>
        </div>
      </section>

      {/* Lịch sử giải */}
      <section>
        <p className="mb-1 text-xs font-semibold">Lịch sử các lượt giải</p>
        <div className="max-h-48 overflow-auto rounded border border-border">
          {lichSu.map((l) => (
            <div key={l.id} className="border-b border-border/60 px-2 py-1 text-xs text-muted-foreground last:border-0">
              {l.luc} · {l.model} · {l.so_nhom} nhóm{l.loi ? ` · lỗi: ${l.loi}` : ""}
            </div>
          ))}
          {!lichSu.length ? <p className="px-2 py-3 text-center text-xs text-muted-foreground">Chưa có lượt giải.</p> : null}
        </div>
      </section>
    </div>
  );
}
