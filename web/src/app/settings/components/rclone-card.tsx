"use client";

import { useCallback, useEffect, useState } from "react";
import { Cloud, Download, FolderOpen, LoaderCircle, Plug, Save, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";

type Remote = { name: string; type: string };
type Muc = { ten: string; la_thu_muc: boolean; co: number; sua_luc: string };

/** Các loại kho khai thẳng được ở đây — chúng chỉ cần khoá/mật khẩu.
 *  Google Drive, OneDrive, Dropbox KHÔNG có ở đây vì chúng đòi mở trình duyệt
 *  để cấp quyền; với chúng phải chạy `rclone authorize` trên máy có màn hình
 *  rồi dán kết quả vào ô cấu hình bên dưới. */
const LOAI_KHONG_CAN_OAUTH: Array<[string, string]> = [
  ["s3", "S3 / Cloudflare R2 / Wasabi / MinIO"],
  ["webdav", "WebDAV (Nextcloud, ownCloud…)"],
  ["sftp", "SFTP (qua SSH)"],
  ["ftp", "FTP"],
  ["b2", "Backblaze B2"],
  ["smb", "SMB / chia sẻ mạng Windows"],
  // Hai kiểu kho ĐẶC BIỆT: chúng bọc ngoài các kho khác chứ không tự nối đi đâu.
  ["crypt", "🔒 Mã hoá — bọc ngoài một kho đã khai (remote = ten_kho:thu/muc)"],
  ["union", "🧩 Gộp nhiều tài khoản thành một (upstreams = kho1: kho2: kho3:)"],
];

function coFile(n: number): string {
  if (n >= 1 << 30) return `${(n / (1 << 30)).toFixed(1).replace(".", ",")} GB`;
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1).replace(".", ",")} MB`;
  if (n >= 1 << 10) return `${(n / (1 << 10)).toFixed(1).replace(".", ",")} KB`;
  return `${n} B`;
}

function loi(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: { error?: string } } } })?.response?.data?.detail;
  return d?.error || (e as Error)?.message || "Lỗi không rõ";
}

export function RcloneCard() {
  const [dangTai, setDangTai] = useState(true);
  const [ban, setBan] = useState("");
  const [caiDat, setCaiDat] = useState(false);
  const [thuMuc, setThuMuc] = useState("");
  const [remotes, setRemotes] = useState<Remote[]>([]);
  const [thongBao, setThongBao] = useState("");
  const [ban_ron, setBanRon] = useState("");

  // Thêm kho mới
  const [tenMoi, setTenMoi] = useState("");
  const [loaiMoi, setLoaiMoi] = useState("s3");
  const [thamSo, setThamSo] = useState("");

  // Cấu hình thô
  const [confText, setConfText] = useState("");
  const [hienConf, setHienConf] = useState(false);

  // Duyệt file
  const [duongDan, setDuongDan] = useState("");
  const [muc, setMuc] = useState<Muc[]>([]);

  const napTrangThai = useCallback(async () => {
    try {
      const { data } = await request.get("/api/rclone/status");
      setCaiDat(Boolean(data?.ok));
      setBan(String(data?.version || ""));
      setRemotes(Array.isArray(data?.remotes) ? data.remotes : []);
      setThuMuc(String(data?.thu_muc_lam_viec || ""));
      if (!data?.ok && data?.error) setThongBao(String(data.error));
    } catch (e) {
      setThongBao(loi(e));
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => { void napTrangThai(); }, [napTrangThai]);

  const napConf = async () => {
    try {
      const { data } = await request.get("/api/rclone/config");
      setConfText(String(data?.noi_dung || ""));
      setHienConf(true);
    } catch (e) { setThongBao(loi(e)); }
  };

  const luuConf = async () => {
    setBanRon("conf");
    try {
      await request.put("/api/rclone/config", { noi_dung: confText });
      setThongBao("Đã lưu cấu hình.");
      await napTrangThai();
      setHienConf(false);
    } catch (e) { setThongBao(loi(e)); } finally { setBanRon(""); }
  };

  const themRemote = async () => {
    setBanRon("them");
    try {
      const ts: Record<string, string> = {};
      for (const dong of thamSo.split("\n")) {
        const i = dong.indexOf("=");
        if (i > 0) ts[dong.slice(0, i).trim()] = dong.slice(i + 1).trim();
      }
      await request.post("/api/rclone/remotes", { ten: tenMoi, loai: loaiMoi, tham_so: ts });
      setThongBao(`Đã thêm kho "${tenMoi}".`);
      setTenMoi(""); setThamSo("");
      await napTrangThai();
    } catch (e) { setThongBao(loi(e)); } finally { setBanRon(""); }
  };

  const thuKetNoi = async (ten: string) => {
    setBanRon(`test:${ten}`);
    try {
      const { data } = await request.post(`/api/rclone/remotes/${ten}/test`);
      setThongBao(data?.ok ? `Kho "${ten}" kết nối được.` : `Kho "${ten}" hỏng: ${data?.error}`);
    } catch (e) { setThongBao(loi(e)); } finally { setBanRon(""); }
  };

  const xoaRemote = async (ten: string) => {
    if (!window.confirm(`Xoá kho "${ten}" khỏi cấu hình? Dữ liệu trên đám mây không bị đụng tới.`)) return;
    setBanRon(`xoa:${ten}`);
    try {
      await request.delete(`/api/rclone/remotes/${ten}`);
      setThongBao(`Đã xoá kho "${ten}".`);
      await napTrangThai();
    } catch (e) { setThongBao(loi(e)); } finally { setBanRon(""); }
  };

  const xemThuMuc = async (dd: string) => {
    setBanRon("ls");
    setDuongDan(dd);
    try {
      const { data } = await request.get("/api/rclone/ls", { params: { duong_dan: dd } });
      setMuc(Array.isArray(data?.muc) ? data.muc : []);
      setThongBao("");
    } catch (e) { setThongBao(loi(e)); setMuc([]); } finally { setBanRon(""); }
  };

  const taiVe = async (ten: string) => {
    const dd = `${duongDan.replace(/\/$/, "")}/${ten}`;
    setBanRon(`tai:${ten}`);
    try {
      const { data } = await request.post("/api/rclone/tai-ve", { duong_dan: dd });
      setThongBao(`Đã tải về ${data?.duong_dan}`);
    } catch (e) { setThongBao(loi(e)); } finally { setBanRon(""); }
  };

  return (
    <Card className="rounded-2xl card-3d card-tint-slate">
      <CardContent className="space-y-6 p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-[var(--secondary)]">
              <Cloud className="size-5 text-[var(--muted-foreground)]" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">Kho lưu trữ đám mây</h2>
              <p className="text-sm text-[var(--muted-foreground)]">
                Nối Google Drive, OneDrive, Dropbox, S3/R2, WebDAV… qua rclone. Bot đọc, tải về và gửi lên được.
              </p>
            </div>
          </div>
          <Badge variant={caiDat ? "success" : "secondary"} className="w-fit rounded-md px-2.5 py-1">
            {dangTai ? "Đang kiểm tra" : caiDat ? `rclone ${ban}` : "Chưa có rclone"}
          </Badge>
        </div>

        {thongBao ? (
          <div className="rounded-xl border border-[var(--border)] bg-[var(--secondary)] px-4 py-3 text-sm">
            {thongBao}
          </div>
        ) : null}

        {dangTai ? (
          <div className="flex items-center justify-center py-10">
            <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : !caiDat ? (
          <p className="text-sm text-[var(--muted-foreground)]">
            Image đang chạy chưa có rclone. Dựng lại image rồi Update stack trong Portainer với “Re-pull image” bật lên.
          </p>
        ) : (
          <>
            {/* Danh sách kho đã khai */}
            <div className="space-y-2">
              <h3 className="text-sm font-medium">Các kho đã khai</h3>
              {remotes.length === 0 ? (
                <p className="text-sm text-[var(--muted-foreground)]">Chưa có kho nào.</p>
              ) : (
                <ul className="space-y-2">
                  {remotes.map((r) => (
                    <li key={r.name} className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2">
                      <span className="font-medium">{r.name}</span>
                      <Badge variant="secondary" className="rounded-md">{r.type}</Badge>
                      <div className="ml-auto flex gap-2">
                        <Button variant="outline" size="sm" className="rounded-lg"
                          onClick={() => void thuKetNoi(r.name)} disabled={ban_ron === `test:${r.name}`}>
                          <Plug className="size-4" /> Thử
                        </Button>
                        <Button variant="outline" size="sm" className="rounded-lg"
                          onClick={() => void xemThuMuc(`${r.name}:`)} disabled={ban_ron === "ls"}>
                          <FolderOpen className="size-4" /> Xem
                        </Button>
                        <Button variant="outline" size="sm" className="rounded-lg"
                          onClick={() => void xoaRemote(r.name)} disabled={ban_ron === `xoa:${r.name}`}>
                          <Trash2 className="size-4" />
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Duyệt thư mục */}
            {duongDan ? (
              <div className="space-y-2">
                <h3 className="text-sm font-medium">{duongDan}</h3>
                {muc.length === 0 ? (
                  <p className="text-sm text-[var(--muted-foreground)]">Thư mục trống.</p>
                ) : (
                  <ul className="max-h-72 space-y-1 overflow-y-auto">
                    {muc.map((m) => (
                      <li key={m.ten} className="flex items-center gap-2 rounded-lg px-2 py-1 text-sm hover:bg-[var(--secondary)]">
                        <span>{m.la_thu_muc ? "📁" : "📄"}</span>
                        {m.la_thu_muc ? (
                          <button className="underline-offset-2 hover:underline"
                            onClick={() => void xemThuMuc(`${duongDan.replace(/\/$/, "")}/${m.ten}`)}>
                            {m.ten}
                          </button>
                        ) : (
                          <span>{m.ten}</span>
                        )}
                        {!m.la_thu_muc ? (
                          <>
                            <span className="text-[var(--muted-foreground)]">{coFile(m.co)}</span>
                            <Button variant="ghost" size="sm" className="ml-auto rounded-lg"
                              onClick={() => void taiVe(m.ten)} disabled={ban_ron === `tai:${m.ten}`}>
                              <Download className="size-4" />
                            </Button>
                          </>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
                <p className="text-xs text-[var(--muted-foreground)]">
                  File tải về nằm ở {thuMuc} — cùng chỗ với các file Office bot soạn, nên gửi lại qua chat được ngay.
                </p>
              </div>
            ) : null}

            {/* Thêm kho không cần OAuth */}
            <div className="space-y-2 border-t border-[var(--border)] pt-4">
              <h3 className="text-sm font-medium">Thêm kho mới</h3>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input value={tenMoi} onChange={(e) => setTenMoi(e.target.value)}
                  placeholder="Tên gọi, vd: sao-luu" className="h-11 rounded-xl" />
                <select value={loaiMoi} onChange={(e) => setLoaiMoi(e.target.value)}
                  className="h-11 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm">
                  {LOAI_KHONG_CAN_OAUTH.map(([v, nhan]) => (
                    <option key={v} value={v}>{nhan}</option>
                  ))}
                </select>
              </div>
              <textarea value={thamSo} onChange={(e) => setThamSo(e.target.value)} rows={4}
                placeholder={"Mỗi dòng một tham số, dạng khoá = giá trị. Ví dụ cho S3/R2:\nprovider = Cloudflare\naccess_key_id = ...\nsecret_access_key = ...\nendpoint = https://<id>.r2.cloudflarestorage.com"}
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] p-3 font-mono text-xs" />
              <div className="flex justify-end">
                <Button className="h-10 rounded-xl" onClick={() => void themRemote()}
                  disabled={!tenMoi.trim() || ban_ron === "them"}>
                  {ban_ron === "them" ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                  Thêm kho
                </Button>
              </div>
              <p className="text-xs text-[var(--muted-foreground)]">
                Google Drive, OneDrive, Dropbox phải cấp quyền qua trình duyệt nên không khai thẳng ở đây được. Chạy
                <code className="mx-1 rounded bg-[var(--secondary)] px-1">rclone config</code>
                trên một máy có màn hình, rồi dán đoạn cấu hình thu được vào ô bên dưới.
              </p>
            </div>

            {/* Cấu hình thô */}
            <div className="space-y-2 border-t border-[var(--border)] pt-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium">Cấu hình rclone.conf</h3>
                <Button variant="outline" size="sm" className="rounded-lg" onClick={() => void napConf()}>
                  {hienConf ? "Tải lại" : "Mở"}
                </Button>
              </div>
              {hienConf ? (
                <>
                  <textarea value={confText} onChange={(e) => setConfText(e.target.value)} rows={10}
                    className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] p-3 font-mono text-xs" />
                  <p className="text-xs text-[var(--muted-foreground)]">
                    Token và mật khẩu hiển thị dưới dạng ••• — chúng không rời khỏi máy chủ. Muốn giữ nguyên kho cũ thì
                    đừng lưu đè bản đã che; chỉ lưu khi anh dán vào cấu hình thật.
                  </p>
                  <div className="flex justify-end">
                    <Button className="h-10 rounded-xl" onClick={() => void luuConf()} disabled={ban_ron === "conf"}>
                      {ban_ron === "conf" ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                      Lưu cấu hình
                    </Button>
                  </div>
                </>
              ) : null}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
