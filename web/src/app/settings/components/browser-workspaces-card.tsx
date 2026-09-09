"use client";

import { useCallback, useEffect, useState } from "react";
import { request } from "@/lib/request";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { moNoVNC } from "@/lib/duong-dan";

type Workspace = { profile: string; name: string; open: boolean; manual: boolean };
const API = "/api/captcha/v1/workspaces";
const INPUT = "rounded-md border border-input bg-background px-3 py-2 text-sm w-full";

export function BrowserWorkspacesCard() {
  const [rows, setRows] = useState<Workspace[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { const response = await request.get(API); setRows(response.data.workspaces || []); setError(""); }
    catch (error) { setError((error as Error).message); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try { await action(); await load(); } catch (error) { toast.error((error as Error).message); }
    finally { setBusy(false); }
  };
  const open = (row: Workspace) => {
    void run(async () => {
      const response = await request.post(`${API}/${encodeURIComponent(row.profile)}/open`, { url: url.trim() });
      // `moNoVNC` tự mở tab rồi xin vé; bị chặn pop-up thì nó điều hướng
      // ngay tab hiện tại, nên không cần link dự phòng nữa.
      await moNoVNC("popup,width=1100,height=800");
      if (response.data.warning) toast.warning(response.data.warning);
      else toast.success(`Đã mở ${row.name}`);
    });
  };
  return <div className="space-y-4">
    <p className="text-sm text-muted-foreground">Mỗi workspace giữ cookie và dữ liệu đăng nhập riêng. Tạo workspace khác cho tài khoản khác. Đóng cửa sổ để giải phóng CPU/RAM; mở lại vẫn dùng hồ sơ đã lưu, trừ khi nhà cung cấp đã hết hạn hoặc thu hồi phiên.</p>
    <div className="flex flex-wrap gap-2 items-end">
      <label className="flex-1 min-w-48 space-y-1 text-sm">Tên workspace<input className={INPUT} value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="Ví dụ: Google cá nhân" /></label>
      <Button disabled={busy || !name.trim()} onClick={() => void run(async () => {
        await request.post(API, { name: name.trim() }); setName(""); toast.success("Đã tạo hồ sơ riêng. Bấm Mở để đăng nhập.");
      })}>Tạo workspace</Button>
      <Button variant="outline" disabled={busy} onClick={() => void load()}>Làm mới</Button>
    </div>
    <label className="block space-y-1 text-sm">Trang cần mở (tùy chọn)<input className={INPUT} type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Để trống: tiếp tục trang đang mở" /></label>
    <div className="flex flex-wrap gap-2" aria-label="Chọn dịch vụ">
      {[["Google", "https://myaccount.google.com/"], ["ChatGPT", "https://chatgpt.com/"], ["Claude", "https://claude.ai/"], ["Flow", "https://labs.google/fx/tools/flow"], ["Gemini", "https://gemini.google.com/"]].map(([label, destination]) =>
        <Button key={label} size="sm" variant={url === destination ? "secondary" : "outline"} onClick={() => setUrl(destination)}>{label}</Button>)}
    </div>
    <p className="text-xs text-muted-foreground">Đăng nhập Google trong workspace, sau đó chọn dịch vụ và bấm Mở trên cùng workspace để dùng “Tiếp tục với Google”. Mỗi dịch vụ giữ phiên riêng và có thể cần xác nhận lần đầu.</p>
    <p className="text-xs text-muted-foreground">Workspace mở thủ công được giữ nguyên để bạn thao tác. Đóng workspace trước khi dùng tài khoản đó cho tác vụ tự động.</p>
    {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
    <div className="space-y-2 max-h-[32rem] overflow-y-auto">
      {!rows.length && !error && <p className="text-sm text-muted-foreground">Chưa có workspace.</p>}
      {rows.map((row) => <div key={row.profile} className="rounded-lg border p-3 space-y-2">
        <div className="flex gap-2 flex-wrap items-center"><span className="font-medium text-sm">{row.name}</span><span className="text-xs text-muted-foreground">{row.manual ? "Đang mở thủ công" : row.open ? "Đang chạy" : "Đã đóng · giữ phiên"}</span></div>
        <p className="text-xs text-muted-foreground break-all">{row.profile}</p>
        <div className="flex gap-2 flex-wrap">
          <Button size="sm" disabled={busy} onClick={() => open(row)}>Mở</Button>
          {row.open && <>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async () => {
              await request.post(`${API}/${encodeURIComponent(row.profile)}/close`); toast.success("Đã đóng trình duyệt, giữ dữ liệu đăng nhập.");
            })}>Đóng · giữ phiên</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async () => {
              const response = await request.post(`${API}/${encodeURIComponent(row.profile)}/checkbox`); toast.info(response.data.message);
            })}>Thử bấm ô reCAPTCHA</Button>
          </>}
        </div>
      </div>)}
    </div>
  </div>;
}
