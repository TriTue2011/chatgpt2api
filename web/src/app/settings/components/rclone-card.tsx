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
  /** Ô mật khẩu: che khi gõ. Máy chủ luôn chạy kèm `--obscure` khi lưu. */
  biMat?: boolean;
  goiY?: string;
  chuThich?: string;
  macDinh?: string;
  /** Tập giá trị hữu hạn → hiện danh sách chọn thay vì bắt gõ tay. */
  chon?: string[];
};

/** Bảy kho chủ máy quan tâm, cộng hai lớp bọc ngoài đã chốt (crypt, union).
 *
 *  Tên khoá và giá trị hợp lệ lấy thẳng từ tài liệu rclone (đọc 05/08/2026):
 *  rclone.org/drive, /googlephotos, /s3, /swift, /mega.
 *
 *  `loai` là kiểu rclone THẬT — nhiều mục dùng chung kiểu `s3` nhưng khác nhà
 *  cung cấp, nên khoá của bảng này là tên hiển thị chứ không phải kiểu rclone.
 *  `coDinh` là tham số gắn cứng theo mục, người dùng không phải điền.
 */
const KHO: Record<string, {
  nhan: string;
  loai: string;
  coDinh?: Record<string, string>;
  ghiChu?: string;
  /** Hướng dẫn lấy từng thông tin, hiện ngay khi chọn loại kho. */
  cacBuoc: string[];
  truong: Truong[];
}> = {
  drive: {
    cacBuoc: [
      "Vào console.cloud.google.com, tạo một dự án mới (hoặc chọn dự án có sẵn).",
      "Vào «APIs & Services» → «Library», tìm «Google Drive API» rồi bấm Enable.",
      "Vào «APIs & Services» → «Credentials» → Create credentials → Service account. Đặt tên bất kỳ rồi bấm Done.",
      "Bấm vào tài khoản dịch vụ vừa tạo → thẻ «Keys» → Add key → Create new key → chọn JSON. Tệp khoá tự tải về máy.",
      "Chép tệp JSON đó lên máy chủ, ví dụ vào /app/data/rclone/khoa.json, rồi điền đúng đường dẫn ấy vào ô bên dưới.",
      "Sao chép địa chỉ email của tài khoản dịch vụ (dạng ten@duan.iam.gserviceaccount.com) — nó hiện ngay trong trang Credentials.",
      "Mở Google Drive, chuột phải vào thư mục muốn bot dùng → Chia sẻ → dán email đó vào, cấp quyền «Người chỉnh sửa». Bước này bắt buộc, bỏ qua là bot không thấy gì.",
      "Mở thư mục đó ra, nhìn thanh địa chỉ có dạng .../folders/<mã> — sao chép phần mã dán vào ô «Mã thư mục gốc».",
    ],
    nhan: "Google Drive (tài khoản dịch vụ)",
    loai: "drive",
    ghiChu: "Không cần trình duyệt lần nào. Nhưng tài khoản dịch vụ không có dung lượng riêng — phải vào Drive chia sẻ thư mục đích cho địa chỉ email của nó, rồi dán mã thư mục vào ô bên dưới.",
    truong: [
      { khoa: "service_account_file", nhan: "Đường dẫn tệp khoá JSON", batBuoc: true,
        goiY: "/app/data/rclone/khoa.json",
        chuThich: "Tải tệp khoá từ Google Cloud rồi đặt vào thư mục data của máy chủ." },
      { khoa: "scope", nhan: "Phạm vi quyền", macDinh: "drive",
        chon: ["drive", "drive.readonly", "drive.file", "drive.appfolder",
               "drive.metadata.readonly"],
        chuThich: "drive = toàn quyền. drive.file = chỉ thấy tệp do bot tạo ra." },
      { khoa: "root_folder_id", nhan: "Mã thư mục gốc", goiY: "1AbCdEf…",
        chuThich: "Lấy từ địa chỉ thư mục trên trình duyệt: .../folders/<mã này>" },
      { khoa: "team_drive", nhan: "Mã ổ chung (Shared Drive)" },
      { khoa: "impersonate", nhan: "Mạo danh người dùng (Workspace)",
        goiY: "nguoidung@tenmien.com",
        chuThich: "Chỉ dùng cho Google Workspace có uỷ quyền toàn miền. Không có thì bỏ trống và dùng cách chia sẻ thư mục." },
    ],
  },
  googlephotos: {
    cacBuoc: [
      "Trên một máy CÓ MÀN HÌNH (máy tính của anh/chị), tải rclone từ rclone.org/downloads.",
      "Mở cửa sổ dòng lệnh, chạy: rclone authorize \"googlephotos\"",
      "Trình duyệt tự mở ra — đăng nhập tài khoản Google có thư viện ảnh, rồi bấm Cho phép.",
      "Quay lại cửa sổ dòng lệnh, nó in ra một chuỗi dài bắt đầu bằng {\"access_token\":",
      "Sao chép NGUYÊN chuỗi đó, cả hai dấu ngoặc nhọn, rồi dán vào ô Token bên dưới.",
    ],
    nhan: "Google Photos",
    loai: "googlephotos",
    ghiChu: "Google Photos KHÔNG dùng được tài khoản dịch vụ — đây là loại duy nhất trong danh sách bắt buộc cấp quyền qua trình duyệt một lần. Chạy `rclone authorize \"googlephotos\"` trên máy có màn hình rồi dán chuỗi token nó in ra vào ô dưới.",
    truong: [
      { khoa: "token", nhan: "Token (dán nguyên chuỗi JSON)", batBuoc: true, biMat: true,
        goiY: '{"access_token":"…","refresh_token":"…","expiry":"…"}' },
      { khoa: "client_id", nhan: "Client ID",
        chuThich: "Bỏ trống thì dùng của rclone — chậm hơn vì dùng chung hạn mức." },
      { khoa: "client_secret", nhan: "Client Secret", biMat: true },
      { khoa: "read_only", nhan: "Chỉ đọc", macDinh: "true", chon: ["true", "false"],
        chuThich: "Nên để true: bot chỉ xem ảnh, không sửa được thư viện ảnh của gia đình." },
    ],
  },
  r2: {
    cacBuoc: [
      "Đăng nhập dash.cloudflare.com, vào mục R2.",
      "Bấm «Manage R2 API Tokens» → «Create API token».",
      "Chọn quyền «Object Read & Write», chọn bucket muốn dùng, rồi bấm Create.",
      "Trang kết quả hiện Access Key ID và Secret Access Key — sao chép cả hai NGAY, phần Secret chỉ hiện đúng một lần.",
      "Endpoint nằm ngay trang đó, dạng https://<mã tài khoản>.r2.cloudflarestorage.com — sao chép luôn.",
    ],
    nhan: "Cloudflare R2",
    loai: "s3",
    coDinh: { provider: "Cloudflare" },
    ghiChu: "Lấy Access Key trong Cloudflare: R2 → Manage API Tokens. Endpoint nằm ngay trang tổng quan R2.",
    truong: [
      { khoa: "access_key_id", nhan: "Access Key ID", batBuoc: true },
      { khoa: "secret_access_key", nhan: "Secret Access Key", batBuoc: true, biMat: true },
      { khoa: "endpoint", nhan: "Endpoint", batBuoc: true,
        goiY: "https://<mã tài khoản>.r2.cloudflarestorage.com" },
      { khoa: "region", nhan: "Vùng", macDinh: "auto",
        chuThich: "R2 luôn là auto — Cloudflare tự trải bucket ra các trung tâm dữ liệu." },
    ],
  },
  megas4: {
    cacBuoc: [
      "Đăng nhập mega.io, vào mục S4 (MEGA S4 Object Storage).",
      "Tạo một Access Key mới, lưu lại Access Key ID và Secret Access Key.",
      "Xem dữ liệu của mình đặt ở vùng nào, rồi chọn đúng vùng đó ở ô Endpoint bên dưới.",
    ],
    nhan: "MEGA S4 (giao thức S3)",
    loai: "s3",
    coDinh: { provider: "Mega" },
    truong: [
      { khoa: "access_key_id", nhan: "Access Key ID", batBuoc: true },
      { khoa: "secret_access_key", nhan: "Secret Access Key", batBuoc: true, biMat: true },
      { khoa: "endpoint", nhan: "Endpoint theo vùng", batBuoc: true,
        macDinh: "s3.ap-tokyo.megas4.com",
        chon: ["s3.ap-tokyo.megas4.com", "s3.eu-amsterdam.megas4.com",
               "s3.eu-luxembourg.megas4.com", "s3.eu-paris.megas4.com",
               "s3.eu-barcelona.megas4.com", "s3.ca-montreal.megas4.com",
               "s3.ca-vancouver.megas4.com"],
        chuThich: "Chọn vùng gần Việt Nam nhất thì nhanh nhất — Tokyo." },
    ],
  },
  drime: {
    cacBuoc: [
      "Đăng nhập Drime bằng trình duyệt.",
      "Vào Settings → Developer.",
      "Tạo một token mới để dùng làm khoá truy cập API.",
      "Sao chép token đó và dán vào ô bên dưới. Chỉ cần đúng một ô này.",
    ],
    nhan: "Drime",
    loai: "drime",
    ghiChu: "Drime có backend riêng trong rclone (từ bản 1.73), chỉ cần một token — không dùng Access Key/Secret/Endpoint kiểu S3.",
    truong: [
      { khoa: "access_token", nhan: "API Access Token", batBuoc: true, biMat: true },
      { khoa: "root_folder_id", nhan: "Mã thư mục gốc",
        chuThich: "Bỏ trống thì dùng thư mục gốc của tài khoản." },
      { khoa: "workspace_id", nhan: "Mã không gian làm việc",
        chuThich: "Chỉ điền nếu tài khoản có nhiều không gian làm việc." },
      { khoa: "hard_delete", nhan: "Xoá hẳn thay vì bỏ vào thùng rác",
        macDinh: "false", chon: ["false", "true"] },
    ],
  },
  mega: {
    cacBuoc: [
      "Mở mega.nz bằng trình duyệt và đăng nhập ÍT NHẤT MỘT LẦN. Bắt buộc: MEGA chỉ sinh khoá mã hoá sau lần đăng nhập đầu tiên, chưa có khoá thì rclone báo sai mật khẩu dù mật khẩu đúng.",
      "Điền chính email và mật khẩu vừa đăng nhập vào hai ô bên dưới.",
      "Nếu tài khoản có bật xác thực hai bước thì điền thêm mã 6 số vào ô tương ứng.",
    ],
    nhan: "MEGA (tài khoản thường)",
    loai: "mega",
    ghiChu: "Phải đăng nhập MEGA bằng trình duyệt ÍT NHẤT MỘT LẦN trước đã — MEGA chỉ sinh khoá mã hoá sau lần đăng nhập đầu, chưa có khoá thì rclone báo sai mật khẩu dù mật khẩu đúng.",
    truong: [
      { khoa: "user", nhan: "Email đăng nhập", batBuoc: true },
      { khoa: "pass", nhan: "Mật khẩu", batBuoc: true, biMat: true },
      { khoa: "2fa", nhan: "Mã xác thực hai bước",
        chuThich: "Chỉ điền nếu tài khoản có bật xác thực hai bước." },
      { khoa: "hard_delete", nhan: "Xoá hẳn thay vì bỏ vào thùng rác",
        macDinh: "false", chon: ["false", "true"] },
    ],
  },
  swift: {
    cacBuoc: [
      "Vào bảng điều khiển OpenStack của nhà cung cấp → «API Access» → «Download OpenStack RC File».",
      "Mở tệp vừa tải bằng trình soạn thảo văn bản. Trong đó có các dòng OS_USERNAME, OS_PASSWORD, OS_AUTH_URL, OS_TENANT_NAME.",
      "Chép từng giá trị sang đúng ô cùng tên bên dưới.",
      "Ô Vùng cứ để trống trước; nếu máy chủ báo lỗi thì mới quay lại điền.",
    ],
    nhan: "OpenStack Swift",
    loai: "swift",
    truong: [
      { khoa: "user", nhan: "Tên đăng nhập", batBuoc: true, chuThich: "Biến môi trường OS_USERNAME" },
      { khoa: "key", nhan: "Mật khẩu", batBuoc: true, biMat: true, chuThich: "OS_PASSWORD" },
      { khoa: "auth", nhan: "Địa chỉ máy chủ xác thực", batBuoc: true,
        goiY: "https://auth.example.com/v3", chuThich: "OS_AUTH_URL" },
      { khoa: "tenant", nhan: "Tên dự án (tenant)", batBuoc: true, chuThich: "OS_TENANT_NAME" },
      { khoa: "domain", nhan: "Miền người dùng", macDinh: "Default",
        chuThich: "Cần cho xác thực Keystone phiên bản 3." },
      { khoa: "region", nhan: "Vùng", chuThich: "Thử bỏ trống trước; máy chủ báo lỗi thì mới điền." },
      { khoa: "auth_version", nhan: "Phiên bản xác thực", macDinh: "3", chon: ["3", "2", "1", "0"] },
    ],
  },
  crypt: {
    cacBuoc: [
      "Khai xong kho thật trước đã (Google Drive, R2…), và nhớ tên kho đó.",
      "Điền tên kho kèm thư mục vào ô «Kho bọc bên trong», ví dụ drive:ThuMucMaHoa.",
      "Tự đặt hai mật khẩu và LƯU LẠI Ở CHỖ KHÁC. Mất là mất luôn dữ liệu, không ai khôi phục hộ được.",
    ],
    nhan: "🔒 Mã hoá — bọc ngoài một kho đã khai",
    loai: "crypt",
    ghiChu: "Đây là thứ làm các phạm vi thật sự không thấy của nhau khi dữ liệu đã lên mây: mã hoá cả nội dung lẫn tên tệp trước khi gửi đi. Mất hai mật khẩu dưới đây là mất luôn dữ liệu, không ai khôi phục hộ được.",
    truong: [
      { khoa: "remote", nhan: "Kho bọc bên trong", batBuoc: true, goiY: "drive:ThuMucMaHoa",
        chuThich: "Tên một kho đã khai ở trên, kèm thư mục." },
      { khoa: "password", nhan: "Mật khẩu", batBuoc: true, biMat: true },
      { khoa: "password2", nhan: "Mật khẩu phụ (làm rối tên tệp)", biMat: true },
      { khoa: "filename_encryption", nhan: "Mã hoá tên tệp", macDinh: "standard",
        chon: ["standard", "obfuscate", "off"] },
    ],
  },
  union: {
    cacBuoc: [
      "Khai từng tài khoản thành các kho riêng trước, ví dụ drive1, drive2, drive3.",
      "Điền tên các kho đó vào ô «Các kho thành viên», cách nhau bằng dấu cách, nhớ dấu hai chấm ở cuối mỗi tên.",
    ],
    nhan: "🧩 Gộp nhiều tài khoản thành một",
    loai: "union",
    ghiChu: "Ghi tệp mới vào tài khoản còn nhiều chỗ trống nhất, bỏ qua tài khoản dưới 1 GB. Hợp để gom nhiều tài khoản miễn phí thành một kho lớn.",
    truong: [
      { khoa: "upstreams", nhan: "Các kho thành viên", batBuoc: true,
        goiY: "drive1: drive2: drive3:",
        chuThich: "Tên các kho đã khai, cách nhau bằng dấu cách." },
      { khoa: "create_policy", nhan: "Chọn kho khi ghi tệp mới", macDinh: "epmfs",
        chon: ["epmfs", "eplfs", "lus", "lfs", "epall", "all"],
        chuThich: "epmfs = kho còn nhiều chỗ trống nhất." },
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
      // Tham số gắn cứng theo mục (vd R2 luôn là provider=Cloudflare) đi trước,
      // rồi tới các ô người dùng điền. Chỉ gửi ô CÓ giá trị: rclone ghi cả khoá
      // rỗng vào cấu hình, làm bẩn file và che mất giá trị mặc định của nó.
      const ts: Record<string, string> = { ...(KHO[loaiMoi]?.coDinh || {}) };
      for (const t of KHO[loaiMoi]?.truong || []) {
        const v = (giaTri[t.khoa] || "").trim();
        if (v) ts[t.khoa] = v;
      }
      await request.post("/api/rclone/remotes",
        { ten: tenMoi, loai: KHO[loaiMoi].loai, tham_so: ts });
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
                Nối Google Drive, Google Photos, Cloudflare R2, MEGA, Swift, Drime qua rclone. Bot xem, tải về và gửi lên được.
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

              {/* Hướng dẫn lấy từng thông tin — hiện ngay khi đổi loại kho, để
                  không phải rời trang đi tra tài liệu rồi quay lại. */}
              <details open className="rounded-xl border border-[var(--border)] px-3 py-2">
                <summary className="cursor-pointer text-xs font-medium">
                  Lấy các thông tin này ở đâu — {KHO[loaiMoi]?.nhan}
                </summary>
                <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-xs text-[var(--muted-foreground)]">
                  {(KHO[loaiMoi]?.cacBuoc || []).map((b, i) => <li key={i}>{b}</li>)}
                </ol>
              </details>

              <div className="grid gap-3 sm:grid-cols-2">
                {(KHO[loaiMoi]?.truong || []).map((t) => (
                  <div key={t.khoa} className="space-y-1">
                    <label className="text-xs font-medium">
                      {t.nhan}{t.batBuoc ? <span className="text-red-500"> *</span> : null}
                    </label>
                    {t.chon ? (
                      // Tập giá trị hữu hạn thì cho chọn, không bắt gõ tay —
                      // gõ sai một chữ là hỏng mà không biết hỏng ở đâu.
                      <select
                        value={giaTri[t.khoa] || t.macDinh || t.chon[0]}
                        onChange={(e) => setGiaTri((s) => ({ ...s, [t.khoa]: e.target.value }))}
                        className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm"
                      >
                        {t.chon.map((v) => <option key={v} value={v}>{v}</option>)}
                      </select>
                    ) : (
                      <Input
                        type={t.biMat ? "password" : "text"}
                        autoComplete="off"
                        value={giaTri[t.khoa] || ""}
                        onChange={(e) => setGiaTri((s) => ({ ...s, [t.khoa]: e.target.value }))}
                        placeholder={t.goiY || ""}
                        className="h-11 rounded-xl"
                      />
                    )}
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
              <p className="text-xs text-[var(--muted-foreground)]">
                Tám trong chín loại trên điền xong là chạy ngay. Riêng <strong>Google Photos</strong> bắt buộc cấp quyền qua
                trình duyệt một lần. Ngại chép token thì có cách khác: mở đường hầm
                <code className="mx-1 rounded bg-[var(--secondary)] px-1">ssh -L localhost:53682:localhost:53682 root@máy-chủ</code>
                rồi chạy <code className="mx-1 rounded bg-[var(--secondary)] px-1">rclone config</code> ngay trên máy chủ và trả lời
                <strong> Y</strong> ở bước hỏi trình duyệt — mở đường dẫn nó in ra bằng trình duyệt máy mình, cấu hình rơi
                thẳng vào máy chủ, khỏi dán gì vào đây.
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
