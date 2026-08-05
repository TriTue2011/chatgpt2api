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

type Truong = {
  /** Đúng tên khoá rclone dùng — chuỗi này đi thẳng vào `rclone config create`. */
  khoa: string;
  nhan: string;
  batBuoc?: boolean;
  /** Ô mật khẩu: che khi gõ. rclone tự làm rối các giá trị này khi lưu xuống. */
  biMat?: boolean;
  goiY?: string;
  chuThich?: string;
  macDinh?: string;
};

/** Mỗi loại kho khai đủ trường của riêng nó, MỖI THÔNG TIN MỘT Ô RIÊNG.
 *
 *  Danh sách này chỉ gồm các loại **tự chạy được**: điền xong là dùng, không
 *  phải mở trình duyệt cấp quyền lần nào. Google Drive vào được nhờ đường tài
 *  khoản dịch vụ; OneDrive và Dropbox không có ở đây vì chúng buộc phải cấp
 *  quyền qua trình duyệt (xem ghi chú dưới biểu mẫu).
 *
 *  Thêm loại mới chỉ cần thêm một mục ở đây — biểu mẫu tự dựng ô theo nó, và
 *  `tao_remote` phía máy chủ vốn nhận tham số tuỳ ý nên không phải sửa gì thêm.
 */
const KHO: Record<string, { nhan: string; ghiChu?: string; truong: Truong[] }> = {
  drive: {
    nhan: "Google Drive (tài khoản dịch vụ)",
    ghiChu: "Tài khoản dịch vụ không có dung lượng riêng — vào Drive chia sẻ thư mục đích cho email của nó, rồi dán mã thư mục vào ô dưới.",
    truong: [
      { khoa: "service_account_file", nhan: "Đường dẫn tệp khoá JSON", batBuoc: true,
        goiY: "/app/data/rclone/khoa.json",
        chuThich: "Tải tệp khoá từ Google Cloud rồi đặt vào thư mục data của máy chủ." },
      { khoa: "root_folder_id", nhan: "Mã thư mục gốc trên Drive",
        goiY: "1AbCdEf…", chuThich: "Lấy từ địa chỉ thư mục: .../folders/<mã này>" },
      { khoa: "team_drive", nhan: "Mã Shared Drive (nếu dùng ổ chung)" },
    ],
  },
  googlecloudstorage: {
    nhan: "Google Cloud Storage",
    truong: [
      { khoa: "service_account_file", nhan: "Đường dẫn tệp khoá JSON", batBuoc: true,
        goiY: "/app/data/rclone/khoa.json" },
      { khoa: "project_number", nhan: "Mã dự án" },
      { khoa: "bucket_policy_only", nhan: "Chỉ dùng quyền cấp bucket", macDinh: "true" },
    ],
  },
  s3: {
    nhan: "S3 / Cloudflare R2 / Wasabi / MinIO",
    truong: [
      { khoa: "provider", nhan: "Nhà cung cấp", batBuoc: true, macDinh: "Cloudflare",
        goiY: "Cloudflare | AWS | Wasabi | Minio | Other" },
      { khoa: "access_key_id", nhan: "Access Key ID", batBuoc: true },
      { khoa: "secret_access_key", nhan: "Secret Access Key", batBuoc: true, biMat: true },
      { khoa: "endpoint", nhan: "Endpoint",
        goiY: "https://<mã>.r2.cloudflarestorage.com",
        chuThich: "R2, Wasabi, MinIO thì bắt buộc. AWS thì để trống, chỉ cần vùng." },
      { khoa: "region", nhan: "Vùng", macDinh: "auto", goiY: "auto | ap-southeast-1" },
    ],
  },
  b2: {
    nhan: "Backblaze B2",
    truong: [
      { khoa: "account", nhan: "Application Key ID", batBuoc: true },
      { khoa: "key", nhan: "Application Key", batBuoc: true, biMat: true },
    ],
  },
  azureblob: {
    nhan: "Azure Blob Storage",
    truong: [
      { khoa: "account", nhan: "Tên tài khoản lưu trữ", batBuoc: true },
      { khoa: "key", nhan: "Khoá truy cập", biMat: true,
        chuThich: "Điền khoá, hoặc bỏ trống và dùng ô SAS URL bên dưới." },
      { khoa: "sas_url", nhan: "SAS URL", biMat: true },
    ],
  },
  webdav: {
    nhan: "WebDAV (Nextcloud, ownCloud, Synology…)",
    truong: [
      { khoa: "url", nhan: "Địa chỉ WebDAV", batBuoc: true,
        goiY: "https://may-chu/remote.php/dav/files/tentaikhoan/" },
      { khoa: "vendor", nhan: "Loại máy chủ", macDinh: "nextcloud",
        goiY: "nextcloud | owncloud | sharepoint | other" },
      { khoa: "user", nhan: "Tên đăng nhập", batBuoc: true },
      { khoa: "pass", nhan: "Mật khẩu", batBuoc: true, biMat: true,
        chuThich: "Nextcloud nên dùng mật khẩu ứng dụng, đừng dùng mật khẩu chính." },
    ],
  },
  sftp: {
    nhan: "SFTP (qua SSH)",
    truong: [
      { khoa: "host", nhan: "Máy chủ", batBuoc: true, goiY: "192.168.1.10" },
      { khoa: "port", nhan: "Cổng", macDinh: "22" },
      { khoa: "user", nhan: "Tên đăng nhập", batBuoc: true },
      { khoa: "pass", nhan: "Mật khẩu", biMat: true,
        chuThich: "Điền mật khẩu, hoặc bỏ trống và dùng khoá riêng bên dưới." },
      { khoa: "key_file", nhan: "Đường dẫn khoá riêng", goiY: "/app/data/rclone/id_ed25519" },
    ],
  },
  ftp: {
    nhan: "FTP",
    truong: [
      { khoa: "host", nhan: "Máy chủ", batBuoc: true },
      { khoa: "port", nhan: "Cổng", macDinh: "21" },
      { khoa: "user", nhan: "Tên đăng nhập", batBuoc: true },
      { khoa: "pass", nhan: "Mật khẩu", batBuoc: true, biMat: true },
      { khoa: "tls", nhan: "Dùng TLS", macDinh: "true" },
    ],
  },
  smb: {
    nhan: "SMB / chia sẻ mạng Windows",
    truong: [
      { khoa: "host", nhan: "Máy chủ", batBuoc: true },
      { khoa: "user", nhan: "Tên đăng nhập", batBuoc: true },
      { khoa: "pass", nhan: "Mật khẩu", batBuoc: true, biMat: true },
      { khoa: "domain", nhan: "Miền", macDinh: "WORKGROUP" },
    ],
  },
  mega: {
    nhan: "MEGA",
    truong: [
      { khoa: "user", nhan: "Email đăng nhập", batBuoc: true },
      { khoa: "pass", nhan: "Mật khẩu", batBuoc: true, biMat: true },
    ],
  },
  seafile: {
    nhan: "Seafile",
    truong: [
      { khoa: "url", nhan: "Địa chỉ máy chủ", batBuoc: true, goiY: "https://seafile.tenmien.vn/" },
      { khoa: "user", nhan: "Email đăng nhập", batBuoc: true },
      { khoa: "pass", nhan: "Mật khẩu", batBuoc: true, biMat: true },
      { khoa: "library", nhan: "Tên thư viện" },
    ],
  },
  storj: {
    nhan: "Storj",
    truong: [
      { khoa: "access_grant", nhan: "Access Grant", batBuoc: true, biMat: true },
    ],
  },
  crypt: {
    nhan: "🔒 Mã hoá — bọc ngoài một kho đã khai",
    ghiChu: "Đây là thứ làm các phạm vi thật sự không thấy của nhau khi dữ liệu đã lên mây: nó mã hoá cả nội dung lẫn tên tệp trước khi gửi đi. Mất hai mật khẩu dưới đây là mất luôn dữ liệu — không ai khôi phục hộ được.",
    truong: [
      { khoa: "remote", nhan: "Kho bọc bên trong", batBuoc: true,
        goiY: "drive:ThuMucMaHoa",
        chuThich: "Tên một kho đã khai ở trên, kèm thư mục." },
      { khoa: "password", nhan: "Mật khẩu", batBuoc: true, biMat: true },
      { khoa: "password2", nhan: "Mật khẩu phụ (làm rối tên tệp)", biMat: true },
      { khoa: "filename_encryption", nhan: "Mã hoá tên tệp", macDinh: "standard",
        goiY: "standard | obfuscate | off" },
    ],
  },
  union: {
    nhan: "🧩 Gộp nhiều tài khoản thành một",
    ghiChu: "Ghi tệp mới vào tài khoản còn nhiều chỗ trống nhất, bỏ qua tài khoản dưới 1 GB. Hợp để gom nhiều tài khoản miễn phí thành một kho lớn.",
    truong: [
      { khoa: "upstreams", nhan: "Các kho thành viên", batBuoc: true,
        goiY: "drive1: drive2: drive3:",
        chuThich: "Tên các kho đã khai, cách nhau bằng dấu cách." },
      { khoa: "create_policy", nhan: "Chọn kho khi ghi tệp mới", macDinh: "epmfs",
        goiY: "epmfs = còn nhiều chỗ nhất" },
    ],
  },
};

const DANH_SACH_LOAI = Object.keys(KHO);

/** Giá trị mặc định của một loại kho — nạp sẵn vào ô để đỡ phải gõ. */
function macDinhCua(loai: string): Record<string, string> {
  const md: Record<string, string> = {};
  for (const t of KHO[loai]?.truong || []) if (t.macDinh) md[t.khoa] = t.macDinh;
  return md;
}

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

  // Thêm kho mới — mỗi thông tin một ô riêng, dựng theo loại đang chọn.
  const [tenMoi, setTenMoi] = useState("");
  const [loaiMoi, setLoaiMoi] = useState("drive");
  const [giaTri, setGiaTri] = useState<Record<string, string>>(() => macDinhCua("drive"));

  /** Đổi loại thì dựng lại bộ ô và nạp sẵn giá trị mặc định — giữ giá trị cũ
   *  của loại trước sẽ gửi lên những khoá mà loại mới không hiểu. */
  const doiLoai = (loai: string) => {
    setLoaiMoi(loai);
    setGiaTri(macDinhCua(loai));
  };

  const thieuTruongBatBuoc = (KHO[loaiMoi]?.truong || [])
    .filter((t) => t.batBuoc && !(giaTri[t.khoa] || "").trim())
    .map((t) => t.nhan);

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
      // Chỉ gửi ô có giá trị: rclone ghi cả khoá rỗng vào cấu hình, làm bẩn file.
      const ts: Record<string, string> = {};
      for (const t of KHO[loaiMoi]?.truong || []) {
        const v = (giaTri[t.khoa] || "").trim();
        if (v) ts[t.khoa] = v;
      }
      await request.post("/api/rclone/remotes", { ten: tenMoi, loai: loaiMoi, tham_so: ts });
      setThongBao(`Đã thêm kho "${tenMoi}". Thêm kho nữa thì điền tiếp bên dưới.`);
      // Dọn sạch để thêm kho tiếp theo — mỗi lần là một kho RIÊNG, không gộp.
      setTenMoi("");
      doiLoai(loaiMoi);
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
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <label className="text-xs font-medium">Tên gọi <span className="text-red-500">*</span></label>
                  <Input value={tenMoi} onChange={(e) => setTenMoi(e.target.value)}
                    placeholder="vd: drive-nha" className="h-11 rounded-xl" />
                  <p className="text-xs text-[var(--muted-foreground)]">Tên anh/chị gọi kho này khi ra lệnh cho bot.</p>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium">Loại kho</label>
                  <select value={loaiMoi} onChange={(e) => doiLoai(e.target.value)}
                    className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm">
                    {DANH_SACH_LOAI.map((v) => (
                      <option key={v} value={v}>{KHO[v].nhan}</option>
                    ))}
                  </select>
                </div>
              </div>

              {KHO[loaiMoi]?.ghiChu ? (
                <p className="rounded-xl border border-[var(--border)] bg-[var(--secondary)] px-3 py-2 text-xs">
                  {KHO[loaiMoi].ghiChu}
                </p>
              ) : null}

              <div className="grid gap-3 sm:grid-cols-2">
                {(KHO[loaiMoi]?.truong || []).map((t) => (
                  <div key={t.khoa} className="space-y-1">
                    <label className="text-xs font-medium">
                      {t.nhan}{t.batBuoc ? <span className="text-red-500"> *</span> : null}
                    </label>
                    <Input
                      type={t.biMat ? "password" : "text"}
                      autoComplete="off"
                      value={giaTri[t.khoa] || ""}
                      onChange={(e) => setGiaTri((s) => ({ ...s, [t.khoa]: e.target.value }))}
                      placeholder={t.goiY || ""}
                      className="h-11 rounded-xl"
                    />
                    {t.chuThich ? (
                      <p className="text-xs text-[var(--muted-foreground)]">{t.chuThich}</p>
                    ) : null}
                  </div>
                ))}
              </div>

              <div className="flex flex-wrap items-center justify-end gap-3">
                {thieuTruongBatBuoc.length ? (
                  <span className="text-xs text-[var(--muted-foreground)]">
                    Còn thiếu: {thieuTruongBatBuoc.join(", ")}
                  </span>
                ) : null}
                <Button className="h-10 rounded-xl" onClick={() => void themRemote()}
                  disabled={!tenMoi.trim() || thieuTruongBatBuoc.length > 0 || ban_ron === "them"}>
                  {ban_ron === "them" ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                  Thêm kho
                </Button>
              </div>
              <div className="space-y-1 text-xs text-[var(--muted-foreground)]">
                <p>
                  <strong>Google Drive khai thẳng ở đây được</strong> nếu dùng tài khoản dịch vụ: chọn loại Google Drive rồi
                  điền <code className="rounded bg-[var(--secondary)] px-1">service_account_file = /app/data/rclone/khoa.json</code>.
                  Không cần trình duyệt lần nào. Nhớ vào Drive chia sẻ thư mục đích cho email của tài khoản dịch vụ đó —
                  nó không có dung lượng riêng, phải ghi nhờ vào thư mục của anh/chị.
                </p>
                <p>
                  OneDrive và Dropbox vẫn phải cấp quyền qua trình duyệt. Nhanh nhất là mở đường hầm
                  <code className="mx-1 rounded bg-[var(--secondary)] px-1">ssh -L localhost:53682:localhost:53682 root@máy-chủ</code>
                  rồi chạy <code className="mx-1 rounded bg-[var(--secondary)] px-1">rclone config</code> trên máy chủ và trả lời
                  <strong> Y</strong> ở bước hỏi trình duyệt — mở đường dẫn nó in ra bằng trình duyệt máy mình là xong,
                  cấu hình rơi thẳng vào máy chủ, khỏi dán gì vào ô bên dưới.
                </p>
              </div>
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
