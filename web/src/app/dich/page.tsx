"use client";

import { useRef, useState } from "react";
import { Languages, LoaderCircle, Upload, FileText, Download, Copy, Check } from "lucide-react";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { request } from "@/lib/request";
import webConfig from "@/constants/common-env";
import { cn } from "@/lib/utils";

/** Khúc upload 25MB — đường domain qua Cloudflare chặn thân request ~100MB,
 *  nên tệp lớn phải đi thành nhiều request nhỏ; LAN thì đằng nào cũng nhanh. */
const KHUC = 25 * 1024 * 1024;
const TRAN_TEP = 4 * 1024 * 1024 * 1024;

const DUOI_NHAN = ".mp4,.mov,.mkv,.webm,.avi,.m4v,.ts,.3gp,.mp3,.m4a,.aac,.ogg,.opus,.wav,.flac,"
  + ".jpg,.jpeg,.png,.webp,.gif,.bmp,.pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.odt,.odp,.txt,.epub,.html,.htm";

/** Chọn theo CẶP, máy tự nhận diện chiều: nguồn tiếng Việt thì dịch sang
 *  tiếng kia, ngược lại dịch về tiếng Việt. Video/âm thanh: bộ nghe hiện có
 *  tiếng Việt + Anh; Trung/Nhật/Hàn mới áp cho chữ, ảnh, tài liệu, link. */
const DICH_SANG = [
  { value: "", label: "Việt ↔ Anh (tự nhận diện)" },
  { value: "cap:zh", label: "Việt ↔ Trung" },
  { value: "cap:ja", label: "Việt ↔ Nhật" },
  { value: "cap:ko", label: "Việt ↔ Hàn" },
];

const DUOI_NGHE = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp",
  ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"];

type KetQua = {
  kieu: string;                 // "chu" | "tep" | "phu-de"
  text?: string;
  goc?: string;                 // chữ OCR đọc được (dịch ảnh)
  nguon?: string;
  dich?: string;
  tep?: { ten: string; url: string }[];
  bao_cao?: string;
};

function layLoi(e: unknown): string {
  const err = e as { response?: { data?: { detail?: { error?: string }; error?: string } }; message?: string };
  return err?.response?.data?.detail?.error || err?.response?.data?.error || err?.message || "lỗi không rõ";
}

function DichPageContent() {
  const [chu, setChu] = useState("");
  const [target, setTarget] = useState("");
  const [tep, setTep] = useState<File | null>(null);
  const [kieuRa, setKieuRa] = useState("phu-de");
  const [dangChay, setDangChay] = useState(false);
  const [tienDo, setTienDo] = useState(0);       // % upload; -1 = không upload
  const [buoc, setBuoc] = useState("");
  const [loi, setLoi] = useState("");
  const [ketQua, setKetQua] = useState<KetQua | null>(null);
  const [daChep, setDaChep] = useState(false);
  const chonTep = useRef<HTMLInputElement>(null);

  function batDau() {
    setLoi(""); setKetQua(null); setBuoc(""); setTienDo(-1); setDangChay(true); setDaChep(false);
  }

  /** Thăm dò việc nền tới khi xong/lỗi. Lỗi mạng lẻ tẻ thì thử tiếp,
   *  3 lần liền mới bỏ cuộc — job trên máy chủ vẫn chạy, mất mạng ≠ mất việc. */
  async function thamDo(viecId: string) {
    let hong = 0;
    for (;;) {
      await new Promise((r) => setTimeout(r, 2500));
      try {
        const res = await request.get(`/api/dich/viec/${viecId}`);
        hong = 0;
        const d = res.data as { trang_thai: string; buoc?: string; loi?: string; bao_cao?: string; ket_qua?: KetQua };
        setBuoc(d.buoc || "");
        if (d.trang_thai === "xong") {
          setKetQua({ ...(d.ket_qua as KetQua), bao_cao: d.bao_cao });
          return;
        }
        if (d.trang_thai === "loi") { setLoi(d.loi || "lỗi không rõ"); return; }
      } catch (e) {
        if (++hong >= 3) { setLoi(layLoi(e)); return; }
      }
    }
  }

  async function dichChu() {
    const nd = chu.trim();
    if (!nd || dangChay) return;
    batDau();
    try {
      const res = await request.post("/api/dich/chu", { noi_dung: nd, target });
      const d = res.data as { viec_id?: string } & KetQua;
      if (d.viec_id) {
        setBuoc("đang lấy phụ đề và dịch…");
        await thamDo(d.viec_id);
      } else {
        setKetQua(d);
      }
    } catch (e) {
      setLoi(layLoi(e));
    } finally {
      setDangChay(false);
    }
  }

  async function dichTep() {
    if (!tep || dangChay) return;
    if (tep.size > TRAN_TEP) {
      setLoi(`Tệp ${(tep.size / 1024 / 1024).toFixed(0)}MB vượt trần 250MB`);
      return;
    }
    batDau();
    setTienDo(0);
    try {
      const tong = Math.max(1, Math.ceil(tep.size / KHUC));
      let viecId = "";
      for (let i = 0; i < tong; i++) {
        const fd = new FormData();
        fd.append("viec_id", viecId);
        fd.append("chi_so", String(i));
        fd.append("tong", String(tong));
        fd.append("ten", tep.name);
        fd.append("khuc", tep.slice(i * KHUC, (i + 1) * KHUC), tep.name);
        const res = await request.post("/api/dich/khuc", fd);
        viecId = (res.data as { viec_id: string }).viec_id;
        setTienDo(Math.round(((i + 1) / tong) * 100));
      }
      setTienDo(-1);
      await request.post("/api/dich/tep", { viec_id: viecId, target, kieu_ra: kieuRa });
      setBuoc("đang xử lý…");
      await thamDo(viecId);
    } catch (e) {
      setLoi(layLoi(e));
    } finally {
      setDangChay(false);
    }
  }

  async function chepKetQua() {
    if (!ketQua?.text) return;
    await navigator.clipboard.writeText(ketQua.text);
    setDaChep(true);
    setTimeout(() => setDaChep(false), 1500);
  }

  const goc = (webConfig.apiUrl || "").replace(/\/$/, "");

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="flex items-center gap-3">
        <Languages className="size-6" />
        <div>
          <h1 className="text-xl font-semibold">Dịch</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Chữ, link YouTube, ảnh, tài liệu, video — dịch bằng máy dịch trong stack, không tốn lượt AI.
          </p>
        </div>
        <select value={target} onChange={(e) => setTarget(e.target.value)} disabled={dangChay}
          className="ml-auto rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
          {DICH_SANG.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {/* Dán chữ hoặc link */}
      <div className="space-y-3 rounded-[16px] border border-[var(--border)] p-4">
        <textarea value={chu} onChange={(e) => setChu(e.target.value)} rows={5} disabled={dangChay}
          placeholder="Dán chữ cần dịch, hoặc link YouTube/TikTok để lấy phụ đề dịch…"
          className="w-full resize-y rounded-[12px] border border-[var(--border)] bg-transparent p-3 text-sm outline-none focus:border-slate-400" />
        <div className="flex justify-end">
          <button type="button" onClick={dichChu} disabled={dangChay || !chu.trim()}
            className="rounded-[12px] bg-slate-900 px-6 py-2.5 text-[14px] font-medium text-white hover:bg-slate-800 disabled:opacity-50">
            Dịch chữ / link
          </button>
        </div>
      </div>

      {/* Tải tệp từ máy */}
      <div className="space-y-3 rounded-[16px] border border-[var(--border)] p-4"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f && !dangChay) setTep(f); }}>
        <button type="button" onClick={() => chonTep.current?.click()} disabled={dangChay}
          className="flex w-full flex-col items-center gap-2 rounded-[12px] border border-dashed border-[var(--border)] p-6 text-sm text-[var(--muted-foreground)] hover:border-slate-400">
          <Upload className="size-5" />
          {tep ? (
            <span className="text-[var(--foreground)]">{tep.name} • {(tep.size / 1024 / 1024).toFixed(1)}MB</span>
          ) : (
            <span>Bấm chọn hoặc kéo thả — video/âm thanh (≤4GB, ≤150 phút — phim 2h nghe mất ~1,5h), ảnh, PDF/Word/Excel…</span>
          )}
        </button>
        <input ref={chonTep} type="file" accept={DUOI_NHAN} className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) setTep(f); e.target.value = ""; }} />
        {tep && DUOI_NGHE.some((d) => tep.name.toLowerCase().endsWith(d)) && (
          <div className="flex items-center gap-5 text-sm">
            <span className="text-[var(--muted-foreground)]">Kết quả:</span>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="kieu-ra" checked={kieuRa === "phu-de"}
                onChange={() => setKieuRa("phu-de")} disabled={dangChay} />
              Phụ đề (.srt, có mốc thời gian)
            </label>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="kieu-ra" checked={kieuRa === "chu"}
                onChange={() => setKieuRa("chu")} disabled={dangChay} />
              Bản chữ (lời thoại đã dịch)
            </label>
          </div>
        )}
        <div className="flex items-center justify-end gap-3">
          {tienDo >= 0 && dangChay && (
            <span className="text-sm text-[var(--muted-foreground)]">đang tải lên {tienDo}%</span>
          )}
          <button type="button" onClick={dichTep} disabled={dangChay || !tep}
            className="rounded-[12px] bg-slate-900 px-6 py-2.5 text-[14px] font-medium text-white hover:bg-slate-800 disabled:opacity-50">
            Dịch tệp
          </button>
        </div>
      </div>

      {/* Trạng thái + kết quả */}
      {dangChay && (
        <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
          <LoaderCircle className="size-4 animate-spin" />
          {buoc || "đang xử lý…"}
        </div>
      )}
      {loi && <div className="rounded-[12px] bg-red-50 p-3 text-sm text-red-600 dark:bg-red-950/40 dark:text-red-400">{loi}</div>}

      {ketQua && (
        <div className="space-y-3 rounded-[16px] border border-[var(--border)] p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <FileText className="size-4" />
            {ketQua.bao_cao || `Bản dịch (${ketQua.nguon} → ${ketQua.dich})`}
          </div>
          {ketQua.tep?.map((t) => (
            <a key={t.url} href={`${goc}${t.url}`} download={t.ten}
              className="flex w-fit items-center gap-2 rounded-[10px] border border-[var(--border)] px-4 py-2 text-sm hover:border-slate-400">
              <Download className="size-4" />{t.ten}
            </a>
          ))}
          {ketQua.kieu === "phu-de" && (
            <p className="text-xs text-[var(--muted-foreground)]">
              Bản <code>phu-de-tren</code> hiện chữ ở mép trên màn hình — dùng khi video đã có chữ in sẵn ở dưới.
            </p>
          )}
          {ketQua.text && (
            <div className="relative">
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-[12px] bg-[var(--muted)] p-3 text-sm">{ketQua.text}</pre>
              <button type="button" onClick={chepKetQua} title="Chép kết quả"
                className="absolute right-2 top-2 rounded-[8px] border border-[var(--border)] bg-[var(--background)] p-1.5 hover:border-slate-400">
                {daChep ? <Check className="size-4 text-emerald-600" /> : <Copy className="size-4" />}
              </button>
            </div>
          )}
          {ketQua.goc && (
            <details>
              <summary className="cursor-pointer text-sm text-[var(--muted-foreground)]">Chữ đọc được trong ảnh (đối chiếu)</summary>
              <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-[12px] bg-[var(--muted)] p-3 text-sm">{ketQua.goc}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

export default function DichPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return <DichPageContent />;
}
