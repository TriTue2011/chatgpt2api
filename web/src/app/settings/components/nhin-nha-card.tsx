"use client";

/**
 * NhinNhaCard — «mắt của nhà»: YOLO26 nhận vật thể + nhận khuôn mặt kiểu IRIS,
 * chạy ngay trên máy, không cần Frigate.
 *
 * Cấu hình nằm ở `nhin_nha` trong config nên lưu bằng saveConfig như mọi thẻ
 * khác (thẻ này là chủ DUY NHẤT của khoá đó). Sổ khuôn mặt (người, mặt lạ, sự
 * kiện) đi qua /api/nhin-nha/* — ảnh mặt trả về dạng data URL thu nhỏ, không có
 * đường tĩnh công khai nào cho kho mặt.
 *
 * Báo tin (người lạ / người quen về / hỏi tên) KHÔNG bật ở đây: như mọi thông
 * báo khác, bật và chọn kênh ở Cài đặt → Thông báo.
 */

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

type Canh = {
  bat?: boolean; frigate?: boolean; yolo_quet?: boolean; chu_ky_giay?: number;
  cach_giay?: number; phien_phut?: number; camera?: string[]; camera_ve?: string[];
  hoi_ten_sau?: number; nhan?: string[];
};
type NhinNha = {
  yolo?: { model?: string; nguong?: number; luong?: number };
  khuon_mat?: { bo?: string; nguong_co_the?: number; nguong_chac?: number; luong?: number };
  canh?: Canh;
};
type ModelTT = { ma: string; mb: number; mo_ta: string; da_tai: boolean };
type TrangThai = {
  model: {
    yolo: { model: string; da_tai: boolean; cac_model: ModelTT[] };
    khuon_mat: { bo: string; da_tai: boolean; cac_bo: ModelTT[] };
    lenh_tai: string;
    nhan?: { ma: string; ten: string }[];
  };
  canh: { dang_chay: boolean; quet: number; co_nguoi: number; nhan_mat: number;
          su_kien: number; frigate: number; loi: number; loi_cuoi: string };
};
type MatAnh = { id: string; anh: string; nguon: string };
type Nguoi = { id: string; ten: string; so_mat: number; anh: string; mat_ds?: MatAnh[];
               lan_cuoi: number | null; so_lan: number };
type MatLa = { id: string; anh: string; anh_ds?: string[]; so_lan: number; lan_cuoi: number;
               camera: string; da_hoi: number };
type SuKien = { id: number; ts: number; camera: string; nguon: string; loai: string;
                ten: string | null; nguoi_id: string | null; mat_la_id: string | null;
                do_giong: number; anh_nho?: string };

const luc = (ts: number | null) =>
  ts ? new Date(ts * 1000).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit",
                                                     day: "2-digit", month: "2-digit" }) : "—";
const loiCua = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function NhinNhaCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);

  const [nn, setNn] = useState<NhinNha>({});
  const [tt, setTt] = useState<TrangThai | null>(null);
  const [nguoi, setNguoi] = useState<Nguoi[]>([]);
  const [matLa, setMatLa] = useState<MatLa[]>([]);
  const [suKien, setSuKien] = useState<SuKien[]>([]);
  const [msg, setMsg] = useState("");
  const [saved, setSaved] = useState(false);
  const [tenDay, setTenDay] = useState("");
  const [tepDay, setTepDay] = useState<File[]>([]);
  const [canEp, setCanEp] = useState(false);
  const [tenLa, setTenLa] = useState<Record<string, string>>({});
  // Khi chọn «đặt tên mới» trong danh sách thả xuống thì gõ tên vào đây.
  const [tenMoiLa, setTenMoiLa] = useState<Record<string, string>>({});
  const [suaTen, setSuaTen] = useState<Record<string, string>>({});
  // Tab đang mở: mã người, hoặc "la" cho tab mặt khác. Rỗng = lấy tab đầu tiên.
  const [tab, setTab] = useState<string>("");
  // Ảnh mặt nào đang được chọn chuyển sang ai (theo mã ảnh mặt).
  const [chuyenTen, setChuyenTen] = useState<Record<string, string>>({});
  const [chuyenMoi, setChuyenMoi] = useState<Record<string, string>>({});
  // Gán lại MỘT lượt trong lịch sử (theo số hiệu lượt).
  const [ganTen, setGanTen] = useState<Record<number, string>>({});
  const [ganMoi, setGanMoi] = useState<Record<number, string>>({});

  const cams = Object.keys(((config as any)?.cameras as Record<string, unknown>) || {});

  useEffect(() => {
    setNn(((config as any)?.nhin_nha as NhinNha) || {});
  }, [(config as any)?.nhin_nha]);

  const tai = useCallback(async () => {
    try {
      const [a, b, c, d] = await Promise.all([
        request.get("/api/nhin-nha/trang-thai"), request.get("/api/nhin-nha/nguoi"),
        // 7 ngày chứ không phải 24 giờ: soi nhận nhầm cần đủ lượt để nhìn ra,
        // mà cả tuần ở nhà này mới có khoảng trăm lượt.
        request.get("/api/nhin-nha/mat-la"), request.get("/api/nhin-nha/su-kien?so_gio=168"),
      ]);
      setTt(a.data as TrangThai);
      setNguoi(((b.data as any)?.nguoi as Nguoi[]) || []);
      setMatLa(((c.data as any)?.mat_la as MatLa[]) || []);
      setSuKien(((d.data as any)?.su_kien as SuKien[]) || []);
    } catch (e) {
      setMsg(`❌ ${loiCua(e)}`);
    }
  }, []);

  useEffect(() => { void tai(); }, [tai]);

  const canh: Canh = nn.canh || {};
  const datCanh = (p: Partial<Canh>) => setNn({ ...nn, canh: { ...canh, ...p } });
  const batTat = (ds: string[] | undefined, t: string) =>
    (ds || []).includes(t) ? (ds || []).filter((x) => x !== t) : [...(ds || []), t];

  const luu = async () => {
    await saveConfig({ ...config, nhin_nha: nn } as any);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
    void tai();
  };

  // Gửi LẦN LƯỢT từng ảnh với CÙNG một tên. `so_mat_nha.day()` vốn đã cộng dồn:
  // người chưa có thì tạo, có rồi thì thêm mặt — nên nhiều ảnh = một người nhiều
  // khuôn mặt, đúng kiểu CompreFace. Trước đây ô chọn tệp chỉ nhận MỘT ảnh, tức
  // giao diện tự mâu thuẫn với chính lời khuyên «dạy 3–4 ảnh» ngay bên dưới nó.
  const day = async (ep: boolean, tenSan?: string) => {
    const ten = (tenSan ?? tenDay).trim();
    if (!ten || tepDay.length === 0) {
      setMsg("❌ Cần cả tên và ít nhất một ảnh."); return;
    }
    setMsg(`Đang dạy mặt (0/${tepDay.length})…`);
    let xong = 0;
    let cuoi: any = null;
    const loi: string[] = [];
    for (const tep of tepDay) {
      const fd = new FormData();
      fd.append("ten", ten);
      fd.append("anh", tep);
      fd.append("ep", ep ? "true" : "false");
      try {
        const d = (await request.post("/api/nhin-nha/day", fd)).data as any;
        if (d.ok) {
          xong += 1; cuoi = d;
          setMsg(`Đang dạy mặt (${xong}/${tepDay.length})…`);
        } else {
          loi.push(`${tep.name}: ${d.error}`);
          if (String(d.error || "").includes("chắc chắn")) setCanEp(true);
        }
      } catch (e) { loi.push(`${tep.name}: ${loiCua(e)}`); }
    }
    // Một ảnh hỏng KHÔNG được làm mất các ảnh đã nhận: báo rõ cái nào bỏ qua.
    if (xong > 0) {
      setMsg(`✅ Đã nhớ mặt «${cuoi.ten}» — thêm ${xong}/${tepDay.length} ảnh, `
             + `tổng ${cuoi.so_mat} ảnh mặt.`
             + (loi.length ? ` Bỏ qua: ${loi.join("; ")}` : ""));
      setTenDay(""); setTepDay([]);
      if (!loi.length) setCanEp(false);
    } else {
      setMsg(`❌ ${loi.join("; ") || "Không dạy được ảnh nào"}`);
    }
    void tai();
  };

  const goi = async (fn: () => Promise<{ data: any }>, xong: string) => {
    try {
      const d = (await fn()).data;
      setMsg(d.ok ? `✅ ${xong}` : `❌ ${d.error || "Không làm được"}`);
      void tai();
    } catch (e) { setMsg(`❌ ${loiCua(e)}`); }
  };

  const oTich = (nhan: string, co: boolean, doi: (v: boolean) => void) => (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={co} onChange={(e) => doi(e.target.checked)} />
      {nhan}
    </label>
  );
  const oSo = (nhan: string, gt: number | undefined, macDinh: number, doi: (v: number) => void) => (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      {nhan}
      <Input className="w-20" type="number" value={gt ?? macDinh}
        onChange={(e) => doi(Number(e.target.value))} />
    </label>
  );

  const m = tt?.model;
  const chuaTai = m && (!m.yolo.da_tai || !m.khuon_mat.da_tai);
  // Tab đang mở thật sự: người đầu tiên khi chưa chọn gì, "la" khi chưa dạy ai.
  const tabHt = tab || nguoi[0]?.id || "la";
  const nguoiHt = nguoi.find((n) => n.id === tabHt) || null;
  // Lịch sử của ĐÚNG tab đang mở: tab người quen thì lấy lượt máy gán cho người
  // đó, tab «Mặt khác» lấy mọi lượt máy không nhận ra ai.
  const lichSu = suKien.filter((s) => (tabHt === "la" ? !s.nguoi_id : s.nguoi_id === tabHt));

  return (
    <Card>
      <CardHeader>
        <CardTitle>🧑 Khuôn mặt &amp; vật thể (YOLO26 + InsightFace)</CardTitle>
        <CardDescription>
          Chạy ngay trên máy, không gửi ảnh đi đâu, không cần Frigate. Hỏi «bếp có mấy người»,
          «ai đang ở cửa»; gửi ảnh vào chat rồi chọn «Dạy khuôn mặt» hoặc «Đây là ai?».
          Cần tích 📷 Camera nhà cho hội thoại ở Kênh chat → Lọc thread.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">

        {/* ── Model ───────────────────────────────────────────────────── */}
        <div className="space-y-2">
          <p className="text-sm font-medium">Model</p>
          {chuaTai ? (
            <p className="text-xs text-amber-600">
              ⚠️ Chưa tải đủ model. Chạy trên máy chủ:{" "}
              <code className="break-all">{m!.lenh_tai} --yolo {nn.yolo?.model || m!.yolo.model} --mat {nn.khuon_mat?.bo || m!.khuon_mat.bo}</code>
            </p>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <label className="text-xs text-muted-foreground">Nhận vật thể{" "}
              <select className="h-9 rounded border border-input bg-background px-2 text-sm"
                value={nn.yolo?.model || m?.yolo.model || "yolo26n"}
                onChange={(e) => setNn({ ...nn, yolo: { ...nn.yolo, model: e.target.value } })}>
                {(m?.yolo.cac_model || []).map((x) => (
                  <option key={x.ma} value={x.ma}>{x.ma} · {x.mb} MB{x.da_tai ? " ✓" : " (chưa tải)"}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-muted-foreground">Nhận mặt{" "}
              <select className="h-9 rounded border border-input bg-background px-2 text-sm"
                value={nn.khuon_mat?.bo || m?.khuon_mat.bo || "buffalo_s"}
                onChange={(e) => setNn({ ...nn, khuon_mat: { ...nn.khuon_mat, bo: e.target.value } })}>
                {(m?.khuon_mat.cac_bo || []).map((x) => (
                  <option key={x.ma} value={x.ma}>{x.ma}{x.da_tai ? " ✓" : " (chưa tải)"}</option>
                ))}
              </select>
            </label>
            {oSo("Ngưỡng vật thể", nn.yolo?.nguong, 0.35,
                 (v) => setNn({ ...nn, yolo: { ...nn.yolo, nguong: v } }))}
            {oSo("«Có thể là» từ", nn.khuon_mat?.nguong_co_the, 40,
                 (v) => setNn({ ...nn, khuon_mat: { ...nn.khuon_mat, nguong_co_the: v } }))}
            {oSo("Nhận chắc từ", nn.khuon_mat?.nguong_chac, 55,
                 (v) => setNn({ ...nn, khuon_mat: { ...nn.khuon_mat, nguong_chac: v } }))}
          </div>
          <p className="text-xs text-muted-foreground">
            Đổi bộ nhận mặt thì em tự tính lại mặt của mọi người từ ảnh đã lưu, không phải dạy lại.
          </p>
        </div>

        {/* ── Canh camera ─────────────────────────────────────────────── */}
        <div className="rounded border border-border/70 p-3 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            {oTich("Tự canh camera (ghi ai tới, lúc nào)", !!canh.bat, (v) => datCanh({ bat: v }))}
            {tt ? (
              <span className="text-xs text-muted-foreground">
                {tt.canh.dang_chay ? "luồng nền đang chạy" : "luồng nền chưa chạy"} · quét {tt.canh.quet} ·
                thấy người {tt.canh.co_nguoi} · Frigate {tt.canh.frigate} · nhận mặt {tt.canh.nhan_mat} ·
                ghi {tt.canh.su_kien} lượt{tt.canh.loi ? ` · lỗi ${tt.canh.loi}: ${tt.canh.loi_cuoi}` : ""}
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-4">
            {oTich("Nguồn: sự kiện person của Frigate", canh.frigate !== false, (v) => datCanh({ frigate: v }))}
            {oTich("Nguồn: YOLO tự quét luồng phụ", canh.yolo_quet !== false, (v) => datCanh({ yolo_quet: v }))}
          </div>
          <div className="flex flex-wrap gap-3">
            {oSo("Nghỉ giữa hai vòng quét (giây)", canh.chu_ky_giay, 2, (v) => datCanh({ chu_ky_giay: v }))}
            {oSo("Cùng người trong (phút) là một lượt", canh.phien_phut, 10, (v) => datCanh({ phien_phut: v }))}
            {oSo("Hỏi tên mặt lạ sau (lượt)", canh.hoi_ten_sau, 3, (v) => datCanh({ hoi_ten_sau: v }))}
          </div>
          <div className="text-xs text-muted-foreground space-y-1">
            <p>Nhãn cần tìm khi quét — chỉ «người» mới kéo theo nhận khuôn mặt,
               các nhãn khác chỉ báo tin «thấy vật»:</p>
            <div className="flex flex-wrap gap-3 max-h-28 overflow-y-auto pr-1">
              {(tt?.model.nhan || []).map((n) => (
                <span key={n.ma}>{oTich(n.ten, (canh.nhan || ["person"]).includes(n.ma),
                                        () => datCanh({ nhan: batTat(canh.nhan, n.ma) }))}</span>
              ))}
            </div>
            <p>Camera được canh (KHÔNG tích cái nào = không canh camera nào):</p>
            <div className="flex flex-wrap gap-3">
              {cams.map((t) => (
                <span key={t}>{oTich(t, (canh.camera || []).includes(t),
                                     () => datCanh({ camera: batTat(canh.camera, t) }))}</span>
              ))}
            </div>
            <p>Camera tính là «về nhà» (báo «người quen về»):</p>
            <div className="flex flex-wrap gap-3">
              {cams.map((t) => (
                <span key={t}>{oTich(t, (canh.camera_ve || []).includes(t),
                                     () => datCanh({ camera_ve: batTat(canh.camera_ve, t) }))}</span>
              ))}
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Báo tin người lạ / người quen về / hỏi tên mặt lạ: bật và chọn kênh ở{" "}
            <b>Cài đặt → Thông báo</b> (nhóm «Nhà»). Mặc định tắt cả ba.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={luu}>{saved ? "Đã lưu!" : "Lưu cài đặt"}</Button>
          {msg ? <span className="text-xs text-muted-foreground">{msg}</span> : null}
        </div>

        {/* ── Ảnh khuôn mặt: mỗi người quen một tab, cuối là tab mặt khác ── */}
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1">
            {nguoi.map((n) => (
              <Button key={n.id} size="sm" variant={tabHt === n.id ? "default" : "outline"}
                onClick={() => setTab(n.id)}>
                {n.ten} ({n.so_mat})
              </Button>
            ))}
            <Button size="sm" variant={tabHt === "la" ? "default" : "outline"}
              onClick={() => setTab("la")}>
              Mặt khác ({matLa.length})
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Mở từng tab để soi có ảnh nào bị nhận nhầm. Thấy ảnh lạc chỗ thì chọn
            «Chuyển sang…» ngay dưới ảnh đó — ảnh giữ nguyên, chỉ đổi chủ, không phải dạy lại.
          </p>
          <div className="flex flex-wrap gap-2">
            {nguoi.filter((n) => n.id === tabHt).map((n) => (
              <div key={n.id} className="w-full rounded border border-border/70 p-2 space-y-2">
                {/* Mỗi ảnh kèm ô «Chuyển sang…». Mặt vào sổ qua «đặt tên cho mặt
                    lạ» nên có thể là người khác; xoá rồi dạy lại thì mất ảnh
                    camera không chụp lại được, nên sửa bằng cách đổi chủ. */}
                <div className="flex flex-wrap gap-2">
                  {(n.mat_ds || []).map((mt) => {
                    const dich = mt.id in chuyenTen && chuyenTen[mt.id] === "__moi__"
                      ? (chuyenMoi[mt.id] || "") : (chuyenTen[mt.id] || "");
                    return (
                      <div key={mt.id} className="w-28 space-y-1">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={mt.anh} alt={`${n.ten} ${mt.id}`}
                             className="h-24 w-28 rounded object-cover" />
                        <p className="text-[10px] text-muted-foreground">
                          {mt.nguon === "camera" ? "📷 từ camera" : `✋ ${mt.nguon}`}
                        </p>
                        <select
                          className="w-full rounded border border-border/70 bg-background px-1 py-0.5 text-[11px]"
                          value={chuyenTen[mt.id] ?? ""}
                          onChange={(e) => setChuyenTen({ ...chuyenTen, [mt.id]: e.target.value })}>
                          <option value="">Chuyển sang…</option>
                          {nguoi.filter((k) => k.id !== n.id).map((k) => (
                            <option key={k.id} value={k.ten}>{k.ten}</option>
                          ))}
                          <option value="__moi__">➕ Người mới…</option>
                        </select>
                        {chuyenTen[mt.id] === "__moi__" ? (
                          <Input className="h-7 text-xs" placeholder="Tên người mới"
                            value={chuyenMoi[mt.id] || ""}
                            onChange={(e) => setChuyenMoi({ ...chuyenMoi, [mt.id]: e.target.value })} />
                        ) : null}
                        {dich.trim() ? (
                          <Button size="sm" variant="outline" className="h-7 w-full text-[11px]"
                            onClick={async () => {
                              await goi(() => request.post(
                                `/api/nhin-nha/mat/${mt.id}/chuyen`, { ten: dich.trim() }),
                                `Đã chuyển sang «${dich.trim()}».`);
                              // Ảnh đổi chủ nhưng GIỮ NGUYÊN mã, nên không xoá lựa
                              // chọn cũ là sang tab người nhận vẫn thấy nút «Chuyển»
                              // với một tên không còn nằm trong danh sách chọn.
                              setChuyenTen({ ...chuyenTen, [mt.id]: "" });
                              setChuyenMoi({ ...chuyenMoi, [mt.id]: "" });
                            }}>
                            Chuyển
                          </Button>
                        ) : null}
                      </div>
                    );
                  })}
                  {!(n.mat_ds || []).length ? (
                    <p className="text-xs text-muted-foreground">Chưa có ảnh mặt nào.</p>
                  ) : null}
                </div>
                <Input value={suaTen[n.id] ?? n.ten}
                  onChange={(e) => setSuaTen({ ...suaTen, [n.id]: e.target.value })} />
                <p className="text-[11px] text-muted-foreground">
                  {n.so_mat} ảnh mặt · gặp {n.so_lan} lượt · {luc(n.lan_cuoi)}
                  {/* Nói rõ khi CHƯA hiện hết: người soi để tìm ảnh nhận nhầm mà
                      không biết mình đang bị giấu bớt thì kết luận sai. */}
                  {n.so_mat > (n.mat_ds?.length ?? 0)
                    ? ` · chỉ hiện ${n.mat_ds?.length ?? 0} ảnh mới nhất`
                    : ""}
                </p>
                <div className="flex gap-1">
                  {suaTen[n.id] !== undefined && suaTen[n.id] !== n.ten ? (
                    <Button size="sm" variant="outline" onClick={() => goi(
                      () => request.post(`/api/nhin-nha/nguoi/${n.id}/doi-ten`, { ten: suaTen[n.id] }),
                      "Đã đổi tên.")}>Lưu tên</Button>
                  ) : null}
                  <Button size="sm" variant="outline" onClick={() => {
                    if (window.confirm(`Xoá mặt của «${n.ten}» và mọi ảnh mặt đã lưu?`)) {
                      void goi(() => request.delete(`/api/nhin-nha/nguoi/${n.id}`), "Đã xoá.");
                    }
                  }}>Xoá</Button>
                </div>
              </div>
            ))}
          </div>
          <div className="rounded border border-dashed border-border/70 p-3 space-y-2">
            <p className="text-sm font-medium">
              {nguoiHt ? `Thêm ảnh cho «${nguoiHt.ten}»` : "Dạy mặt mới"}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {/* Đang ở tab của một người thì khỏi gõ lại tên — gõ sai một ký tự
                  là đẻ ra người trùng, đúng cái bẫy ô chọn mặt lạ đã tránh. */}
              {nguoiHt ? null : (
                <Input className="w-48" value={tenDay} onChange={(e) => setTenDay(e.target.value)}
                  placeholder="Tên, vd: Bà ngoại" />
              )}
              <input type="file" accept="image/*" multiple className="text-xs"
                onChange={(e) => setTepDay(Array.from(e.target.files || []))} />
              {tepDay.length ? (
                <span className="text-xs text-muted-foreground">đã chọn {tepDay.length} ảnh</span>
              ) : null}
              <Button size="sm" onClick={() => day(false, nguoiHt?.ten)}>
                {nguoiHt ? "Thêm ảnh" : "Dạy"}
              </Button>
              {canEp ? (
                <Button size="sm" variant="outline" onClick={() => day(true, nguoiHt?.ten)}>
                  Đúng là người này
                </Button>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">
              Ảnh chỉ có mặt người đó (hoặc mặt đó to rõ nhất). <b>Chọn nhiều ảnh một lần</b> —
              3–4 tấm khác góc, khác ánh sáng thì nhận chắc hơn hẳn. Gõ đúng tên người đã có
              là ảnh mới được cộng thêm vào người đó chứ không tạo người mới.
            </p>
          </div>
        </div>

        {/* ── Tab «Mặt khác»: cụm camera gom được nhưng chưa biết là ai ── */}
        {tabHt === "la" ? (
        <div className="space-y-2">
          <p className="text-sm font-medium">Mặt khác camera gặp ({matLa.length})</p>
          {matLa.length === 0 ? (
            <p className="text-xs text-muted-foreground">Chưa có — bật «Tự canh camera» thì em mới gom.</p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {matLa.map((x) => (
              <div key={x.id} className="w-44 rounded border border-border/70 p-2 space-y-1">
                {/* Bày ảnh của TỪNG lượt gặp, không chỉ tấm đại diện: nhóm trộn
                    nhầm hai người chỉ lộ ra khi xem cạnh nhau. Tấm đầu là ảnh
                    đại diện của nhóm, nên nó to hơn. */}
                {x.anh ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={x.anh} alt={`mặt lạ ${x.id}`} className="h-24 w-full rounded object-cover" />
                ) : null}
                {x.anh_ds && x.anh_ds.length > 1 ? (
                  <div className="flex flex-wrap gap-1">
                    {x.anh_ds.map((a, i) => (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img key={i} src={a} alt={`lượt ${i + 1}`}
                           className="h-10 w-10 rounded object-cover" />
                    ))}
                  </div>
                ) : null}
                <p className="text-[11px] text-muted-foreground">
                  «{x.id}» · {x.so_lan} lượt · {x.camera} · {luc(x.lan_cuoi)}
                  {x.anh_ds && x.anh_ds.length > 1
                    ? ` · ${x.anh_ds.length} ảnh — xem có lẫn người khác không`
                    : ""}
                </p>
                {/* Chọn người ĐÃ CÓ thì mặt này được cộng vào hồ sơ người đó
                    (`dat_ten_mat_la` gọi `day(..., ep=True)`, mà `day` đã cộng
                    dồn). Gõ tay tên có sẵn cũng ra kết quả ấy, nhưng gõ sai một
                    ký tự là đẻ ra người trùng — nên cho chọn từ danh sách. */}
                <select
                  className="w-full rounded border border-border/70 bg-background px-2 py-1 text-xs"
                  value={tenLa[x.id] ?? ""}
                  onChange={(e) => setTenLa({ ...tenLa, [x.id]: e.target.value })}>
                  <option value="">Đây là ai?</option>
                  {nguoi.map((n) => <option key={n.id} value={n.ten}>{n.ten}</option>)}
                  <option value="__moi__">➕ Người mới…</option>
                </select>
                {tenLa[x.id] === "__moi__" ? (
                  <Input autoFocus placeholder="Tên người mới" value={tenMoiLa[x.id] || ""}
                    onChange={(e) => setTenMoiLa({ ...tenMoiLa, [x.id]: e.target.value })} />
                ) : null}
                <div className="flex gap-1">
                  <Button size="sm" variant="outline"
                    disabled={!((tenLa[x.id] === "__moi__" ? tenMoiLa[x.id] : tenLa[x.id]) || "").trim()}
                    onClick={() => goi(() => request.post(`/api/nhin-nha/mat-la/${x.id}/dat-ten`,
                      { ten: tenLa[x.id] === "__moi__" ? tenMoiLa[x.id] : tenLa[x.id] }),
                      "Đã nhớ tên.")}>
                    Đặt tên
                  </Button>
                  <Button size="sm" variant="outline"
                    onClick={() => goi(() => request.post(`/api/nhin-nha/mat-la/${x.id}/thoi-hoi`),
                                       "Sẽ không hỏi về mặt này nữa.")}>
                    Đừng hỏi
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
        ) : null}

        {/* ── Lịch sử nhận diện, chia theo TAB đang mở ──────────────────
            Đây mới là chỗ soi được nhận nhầm: ảnh mẫu chỉ có vài tấm, còn lịch
            sử là mọi lần máy ĐÃ kết luận ai là ai. */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium">
              Lịch sử 7 ngày · {nguoiHt ? `máy bảo là «${nguoiHt.ten}»` : "máy không nhận ra ai"}
              {" "}({lichSu.length} lượt)
            </p>
            <Button size="sm" variant="outline" onClick={() => void tai()}>Làm mới</Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Ảnh nào <b>không phải</b> người của tab này là một lần nhận nhầm — chọn «Đây là ai?»
            ngay dưới ảnh để gán lại. Chỉ sửa đúng lượt đó, không đụng lượt khác.
          </p>
          {lichSu.length === 0 ? (
            <p className="text-xs text-muted-foreground">Chưa có lượt nào trong tab này.</p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {lichSu.map((s) => {
              const dich = ganTen[s.id] === "__moi__" ? (ganMoi[s.id] || "") : (ganTen[s.id] || "");
              return (
                <div key={s.id} className="w-32 space-y-1 rounded border border-border/70 p-1">
                  {s.anh_nho ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={s.anh_nho} alt={`lượt ${s.id}`}
                         className="h-28 w-full rounded object-cover" />
                  ) : (
                    <div className="flex h-28 w-full items-center justify-center rounded bg-muted
                                    text-center text-[10px] text-muted-foreground">
                      lượt cũ,<br />không kèm ảnh
                    </div>
                  )}
                  <p className="text-[10px] text-muted-foreground">
                    {luc(s.ts)} · {s.camera} · {s.nguon}
                    {s.loai === "co_the" ? ` · ngờ ${Math.round(s.do_giong)}/100` : ""}
                    {s.loai === "la" && s.mat_la_id ? ` · nhóm «${s.mat_la_id.slice(-4)}»` : ""}
                  </p>
                  <select
                    className="w-full rounded border border-border/70 bg-background px-1 py-0.5 text-[11px]"
                    value={ganTen[s.id] ?? ""}
                    onChange={(e) => setGanTen({ ...ganTen, [s.id]: e.target.value })}>
                    <option value="">Đây là ai?</option>
                    {nguoi.map((k) => <option key={k.id} value={k.ten}>{k.ten}</option>)}
                    <option value="__moi__">➕ Người mới…</option>
                  </select>
                  {ganTen[s.id] === "__moi__" ? (
                    <Input className="h-7 text-xs" placeholder="Tên người mới"
                      value={ganMoi[s.id] || ""}
                      onChange={(e) => setGanMoi({ ...ganMoi, [s.id]: e.target.value })} />
                  ) : null}
                  {dich.trim() ? (
                    <Button size="sm" variant="outline" className="h-7 w-full text-[11px]"
                      onClick={async () => {
                        await goi(() => request.post(`/api/nhin-nha/su-kien/${s.id}/chuyen`,
                          { ten: dich.trim() }), `Đã gán lượt này cho «${dich.trim()}».`);
                        setGanTen({ ...ganTen, [s.id]: "" });
                        setGanMoi({ ...ganMoi, [s.id]: "" });
                      }}>
                      Gán lại
                    </Button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
