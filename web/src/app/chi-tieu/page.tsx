"use client";

/**
 * Tab "Chi tiêu" — sổ chi tiêu theo hũ (JARS) của CHÍNH tài khoản đang đăng nhập.
 *
 * Chủ máy 02/10/2026: tích hợp chi-tieu-mcp (Quiz99) thành tab riêng như YouTube; "phải chỉnh sửa, xoá, thêm các
 * thông tin ngay trên webui để phù hợp cho tất cả mọi người"; "mỗi account chỉ xem được chi tiêu của họ, kể cả
 * admin cũng thế"; "admin nhìn thấy tên sổ chi tiêu, để gán theo zalo tương ứng".
 * Backend: api/chi_tieu.py → services/chi_tieu.
 */

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";

import { CongTy } from "./components/cong-ty";
import { HopThuTab } from "./components/hop-thu";
import { HuLuong } from "./components/hu-luong";
import { Ky } from "./components/ky";
import { LichSu } from "./components/lich-su";
import { LienKetTab } from "./components/lien-ket";
import { QuanTri } from "./components/quan-tri";
import { TongQuanTab } from "./components/tong-quan";
import { lay, type TongQuan } from "./lib";

const TAB = [
  ["tong", "Tổng quan"], ["lich", "Lịch sử chi"], ["hu", "Hũ & lương"], ["ky", "Thu nhập · Chi phí đặc biệt"],
  ["cty", "Tạm ứng công ty"], ["mail", "Email"], ["lk", "Liên kết Zalo/Telegram"],
] as const;

export default function ChiTieuPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin", "user"]);
  const [tq, setTq] = useState<TongQuan | null>(null);
  const [tab, setTab] = useState<string>("tong");
  const [thang, setThang] = useState("");

  const tai = useCallback(async () => {
    const r = await lay<TongQuan>(`/api/chi-tieu${thang ? `?thang=${encodeURIComponent(thang)}` : ""}`);
    if (r.ok) setTq(r);
  }, [thang]);

  useEffect(() => {
    if (session) void tai();
  }, [session, tai]);

  if (isCheckingAuth || !session || !tq) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  const tabs = [...TAB, ...(tq.la_admin ? ([["qt", "Gán Zalo (quản trị)"]] as const) : [])];
  return (
    <div className="mx-auto w-full max-w-5xl space-y-4 px-4 py-6" style={{ paddingInline: "max(16px, env(safe-area-inset-left))" }}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">{tq.so.ten}</h1>
          <p className="text-xs text-muted-foreground">
            Sổ chi tiêu theo hũ của riêng tài khoản này — người khác (kể cả quản trị) không xem được. Ghi nhanh qua chat:
            nhắn bot «vừa chi 50k ăn trưa» sau khi liên kết Zalo/Telegram.
          </p>
        </div>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          Kỳ
          <input type="month" className="rounded border bg-background px-1 py-0.5" value={thang || tq.ngan_sach.thang}
            onChange={(e) => setThang(e.target.value)} />
        </label>
      </div>
      <div className="flex flex-wrap gap-1 border-b pb-1">
        {tabs.map(([k, ten]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
            className={`rounded-md px-3 py-1 text-sm ${tab === k ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>
            {ten}
          </button>
        ))}
      </div>
      {tab === "tong" && <TongQuanTab tq={tq} taiLai={tai} />}
      {tab === "lich" && <LichSu tq={tq} thang={thang || tq.ngan_sach.thang} taiLai={tai} />}
      {tab === "hu" && <HuLuong tq={tq} taiLai={tai} />}
      {tab === "ky" && <Ky tq={tq} taiLai={tai} />}
      {tab === "cty" && <CongTy />}
      {tab === "mail" && <HopThuTab taiLai={tai} />}
      {tab === "lk" && <LienKetTab tq={tq} taiLai={tai} />}
      {tab === "qt" && tq.la_admin && <QuanTri />}
    </div>
  );
}
