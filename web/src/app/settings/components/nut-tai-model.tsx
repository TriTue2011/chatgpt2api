"use client";

/**
 * Nút «Tải xuống» một model — máy chủ chạy đúng lệnh tải trong danh mục ở nền (POST
 * /api/models/tai), nút hỏi tiến độ mỗi 1,5 giây tới khi xong rồi gọi `onXong` để thẻ cha kiểm lại.
 * Lệnh gửi lên phải trùng NGUYÊN chuỗi một lệnh trong danh mục — máy chủ tự kiểm.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { request } from "@/lib/request";

type Viec = { id: string; lenh: string; trang_thai: "dang_chay" | "xong" | "loi"; dong: string[] };

export function NutTaiModel({ lenh, onXong, nhan = "Tải xuống" }:
  { lenh: string; onXong?: () => void; nhan?: string }) {
  const [viec, setViec] = useState<Viec | null>(null);
  const [loi, setLoi] = useState("");
  const hen = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Chỉ báo `onXong` khi CHÍNH nút này thấy đang tải → xong; việc cũ đã xong từ trước thì im,
  // không thì thẻ cha tải lại → nút hỏi lại → lại thấy «xong» → lặp mãi.
  const daThayChay = useRef(false);
  const goiXong = useRef(onXong);
  goiXong.current = onXong;

  const hoi = useCallback(async () => {
    try {
      const ds = ((await request.get("/api/models/tai")).data as { items: Viec[] }).items || [];
      const v = ds.find((x) => x.lenh === lenh) || null;
      setViec(v);
      if (v?.trang_thai === "dang_chay") {
        daThayChay.current = true;
        hen.current = setTimeout(() => void hoi(), 1500);
      } else if (v?.trang_thai === "xong" && daThayChay.current) {
        daThayChay.current = false;
        goiXong.current?.();
      }
    } catch { /* hỏi lại ở lần bấm sau */ }
  }, [lenh]);

  useEffect(() => {
    void hoi();
    return () => { if (hen.current) clearTimeout(hen.current); };
  }, [hoi]);

  const bam = async () => {
    setLoi("");
    try {
      const v = ((await request.post("/api/models/tai", { lenh })).data as { viec: Viec }).viec;
      setViec(v);
      daThayChay.current = true;
      hen.current = setTimeout(() => void hoi(), 1500);
    } catch (e: any) {
      setLoi(String(e?.response?.data?.detail || e?.message || e));
    }
  };

  const cuoi = viec?.dong?.[viec.dong.length - 1] || "";
  if (viec?.trang_thai === "dang_chay") {
    return <span className="text-xs text-amber-600">Đang tải… {cuoi}</span>;
  }
  if (viec?.trang_thai === "xong") {
    return <span className="text-xs text-green-600">✓ Đã tải xong</span>;
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button type="button" className="rounded border border-primary px-2 py-0.5 text-xs text-primary"
        onClick={() => void bam()}>
        {viec?.trang_thai === "loi" ? "Tải lại" : nhan}
      </button>
      {viec?.trang_thai === "loi" ? <span className="text-xs text-destructive">Lỗi: {cuoi}</span> : null}
      {loi ? <span className="text-xs text-destructive">{loi}</span> : null}
    </span>
  );
}
