"use client";

import { useRef, useState } from "react";
import { Languages, LoaderCircle, Upload, FileText, Download, Copy, Check, Mic, MessagesSquare } from "lucide-react";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { request } from "@/lib/request";
import webConfig from "@/constants/common-env";
import { cn } from "@/lib/utils";

/** Khúc upload 25MB — đường domain qua Cloudflare chặn thân request ~100MB,
 *  nên tệp lớn phải đi thành nhiều request nhỏ; LAN thì đằng nào cũng nhanh. */
const KHUC = 25 * 1024 * 1024;
const TRAN_TEP = 4 * 1024 * 1024 * 1024;

const DUOI_NHAN = ".mp4,.mov,.mkv,.webm,.avi,.m4v,.ts,.3gp,.mp3,.m4a,.aac,.ogg,.opus,.wav,.flac,"
  + ".srt,.vtt,.jpg,.jpeg,.png,.webp,.gif,.bmp,.pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.odt,.odp,.txt,.epub,.html,.htm";

/** Chọn RIÊNG tiếng nguồn và tiếng đích, không chọn theo "cặp".
 *
 *  Bản trước chỉ có bốn cặp và cặp nào cũng neo vào tiếng Việt, nên Nhật → Hàn
 *  hay Anh → Trung là không chọn được — dù máy dịch trong stack làm được đủ 20
 *  chiều (hỏi /languages ngày 15/08: cả năm tiếng đều nhận cả năm làm đích).
 *
 *  Khai tiếng nguồn còn giúp video/âm thanh: biết trước thì bộ nghe khoá cứng
 *  một model, khỏi tốn lượt nghe thử để dò. Để "tự nhận" thì máy dò như cũ. */
const CAC_TIENG = [
  { value: "vi", label: "Tiếng Việt" },
  { value: "en", label: "Tiếng Anh" },
  { value: "ja", label: "Tiếng Nhật" },
  { value: "zh", label: "Tiếng Trung" },
  { value: "ko", label: "Tiếng Hàn" },
];

/** Đuôi cho ra PHỤ ĐỀ (hiện lựa chọn Phụ đề/Bản chữ): video, âm thanh, và
 *  tệp phụ đề sẵn (.srt/.vtt — đường nhanh nhất cho phim, khỏi nghe). */
const DUOI_NGHE = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp",
  ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac", ".srt", ".vtt"];

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
  const [target, setTarget] = useState("en");
  const [nguon, setNguon] = useState("");   // "" = để máy tự nhận
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
      const res = await request.post("/api/dich/chu", { noi_dung: nd, target, nguon });
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
      await request.post("/api/dich/tep", { viec_id: viecId, target, nguon, kieu_ra: kieuRa });
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

  function doiNguon(moi: string) {
    setNguon(moi);
    // Nguồn được chọn sau khi đích đã chọn có thể làm UI giữ một state không
    // hợp lệ (ví dụ đích Nhật rồi đổi nguồn sang Nhật). Đổi đích nguyên tử để
    // request không bị backend từ chối vì dịch một ngôn ngữ sang chính nó.
    if (moi && moi === target) {
      const dichMoi = CAC_TIENG.find((o) => o.value !== moi)?.value;
      if (dichMoi) setTarget(dichMoi);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Languages className="size-6" />
        <div>
          <h1 className="text-xl font-semibold">Dịch</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Chữ, link YouTube, ảnh, tài liệu, video — dịch bằng máy dịch trong stack, không tốn lượt AI.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <select value={nguon} onChange={(e) => doiNguon(e.target.value)} disabled={dangChay}
            className="rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
            <option value="">Tự nhận tiếng</option>
            {CAC_TIENG.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <span className="text-[var(--muted-foreground)]">→</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)} disabled={dangChay}
            className="rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
            {CAC_TIENG.filter((o) => o.value !== nguon).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Dán chữ hoặc link */}
      <div className="space-y-3 rounded-[16px] border border-[var(--border)] p-4">
        <textarea value={chu} onChange={(e) => setChu(e.target.value)} rows={5} disabled={dangChay}
          placeholder="Dán chữ cần dịch, hoặc link YouTube có phụ đề để dịch…"
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
            <span>Bấm chọn hoặc kéo thả — video/âm thanh (≤4GB, ≤150 phút — phim 2h nghe mất ~1,5h), phụ đề .srt/.vtt (dịch vài chục giây), ảnh, PDF/Word/Excel…</span>
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

const NGON_NGU: Record<string, string> = {
  vi: "Tiếng Việt", en: "Tiếng Anh", zh: "Tiếng Trung", ja: "Tiếng Nhật", ko: "Tiếng Hàn",
};

/** Đàm thoại 2 chiều bấm-nói-thả: bấm mic bên tiếng nào là máy nghe tiếng đó
 *  rồi dịch sang bên kia. Không streaming — mỗi lượt nói là một lần gửi. */
function DamThoai() {
  const [tiengA, setTiengA] = useState("vi");
  const [tiengKia, setTiengKia] = useState("en");
  const [docTts, setDocTts] = useState(true);
  const [dangGhi, setDangGhi] = useState("");        // "" | mã tiếng đang ghi
  const [dangMo, setDangMo] = useState("");          // đang xin quyền/mở mic
  const [dangXuLy, setDangXuLy] = useState(false);
  const [loi, setLoi] = useState("");
  const [luot, setLuot] = useState<{ ben: string; goc: string; dich: string }[]>([]);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function nhanMic(lang: string) {
    setLoi("");
    if (dangGhi) {
      mediaRef.current?.stop();
      return;
    }
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setLoi("Trình duyệt không hỗ trợ micro (cần HTTPS hoặc mở qua domain).");
      return;
    }
    setDangMo(lang);   // mở mic mất ~nửa giây — nói sớm là mất chữ đầu
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      let mime = "";
      for (const c of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"]) {
        if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported?.(c)) { mime = c; break; }
      }
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setDangGhi("");
        const type = mr.mimeType || mime || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        if (blob.size < 800) return;   // bấm nhầm, chưa nói gì
        setDangXuLy(true);
        try {
          const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
          const khac = lang === tiengA ? tiengKia : tiengA;
          const fd = new FormData();
          fd.append("tieng", blob, `mic.${ext}`);
          fd.append("lang_noi", lang);
          fd.append("lang_kia", khac);
          fd.append("tts", docTts ? "1" : "0");
          const res = await request.post("/api/dich/noi", fd);
          const d = res.data as { goc: string; dich: string; tieng: string | null };
          if (d.goc) {
            setLuot((prev) => [...prev, { ben: lang, goc: d.goc, dich: d.dich }]);
            if (d.tieng) void new Audio(`data:audio/wav;base64,${d.tieng}`).play().catch(() => {});
          } else {
            setLoi("Không nghe ra chữ nào — thử nói lại gần mic hơn.");
          }
        } catch (e) {
          setLoi(layLoi(e));
        }
        setDangXuLy(false);
      };
      mr.start(250);
      mediaRef.current = mr;
      setDangMo("");
      setDangGhi(lang);
    } catch {
      setDangMo("");
      setLoi("Không truy cập được micro — kiểm tra quyền Micro của trình duyệt (ổ khóa cạnh URL).");
    }
  }

  const hai_ben = [tiengA, tiengKia];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          Phiên dịch giữa:
          <select value={tiengA} onChange={(e) => { setTiengA(e.target.value); setLuot([]); }}
            disabled={!!dangGhi || dangXuLy}
            className="rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
            {["vi", "en", "zh", "ja", "ko"].filter((m) => m !== tiengKia).map((m) => (
              <option key={m} value={m}>{NGON_NGU[m]}</option>
            ))}
          </select>
          <span className="text-[var(--muted-foreground)]">↔</span>
          <select value={tiengKia} onChange={(e) => { setTiengKia(e.target.value); setLuot([]); }}
            disabled={!!dangGhi || dangXuLy}
            className="rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
            {["vi", "en", "zh", "ja", "ko"].filter((m) => m !== tiengA).map((m) => (
              <option key={m} value={m}>{NGON_NGU[m]}</option>
            ))}
          </select>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-sm">
          <input type="checkbox" checked={docTts} onChange={(e) => setDocTts(e.target.checked)} />
          Đọc bản dịch thành tiếng
        </label>
        {dangXuLy && (
          <span className="flex items-center gap-1.5 text-sm text-[var(--muted-foreground)]">
            <LoaderCircle className="size-4 animate-spin" /> đang nghe và dịch…
          </span>
        )}
      </div>
      {loi && <div className="rounded-[12px] bg-red-50 p-3 text-sm text-red-600 dark:bg-red-950/40 dark:text-red-400">{loi}</div>}

      <div className="grid gap-4 sm:grid-cols-2">
        {hai_ben.map((lang) => (
          <div key={lang} className="flex min-h-72 flex-col rounded-[16px] border border-[var(--border)] p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="font-medium">{NGON_NGU[lang]}</span>
              <button type="button" onClick={() => nhanMic(lang)}
                disabled={dangXuLy || !!dangMo || (!!dangGhi && dangGhi !== lang)}
                className={cn(
                  "flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium text-white disabled:opacity-40",
                  dangGhi === lang ? "animate-pulse bg-red-600 hover:bg-red-700" : "bg-slate-900 hover:bg-slate-800")}>
                <Mic className="size-4" />
                {dangGhi === lang ? "Bấm để dừng"
                  : dangMo === lang ? "Đang mở mic…" : "Bấm, chờ ĐỎ, rồi nói"}
              </button>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto text-sm">
              {luot.length === 0 && (
                <p className="text-[var(--muted-foreground)]">
                  Bấm mic bên {NGON_NGU[lang]} khi người nói dùng {NGON_NGU[lang].toLowerCase()}…
                </p>
              )}
              {luot.map((t, i) =>
                t.ben === lang ? (
                  <p key={i} className="rounded-[10px] bg-[var(--muted)] p-2">🎙 {t.goc}</p>
                ) : (
                  <p key={i} className="rounded-[10px] border border-[var(--border)] p-2">→ {t.dich}</p>
                ))}
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-[var(--muted-foreground)]">
        Mỗi lượt nói tối đa 90 giây. Máy nghe theo tiếng của nút mic đã bấm — không đoán tiếng, nên
        hai người cứ thay nhau bấm đúng bên mình. Giọng đọc: Việt (NghiTTS), Anh (Kokoro),
        Trung (Kokoro đa ngữ), Nhật + Hàn (Supertonic) — thiếu model giọng nào thì bên đó chỉ hiện chữ.
      </p>
    </div>
  );
}

export default function DichPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  const [tab, setTab] = useState<"dich" | "dam-thoai">("dich");

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6 pb-2">
      <div className="flex gap-2">
        <button type="button" onClick={() => setTab("dich")}
          className={cn("flex items-center gap-2 rounded-[12px] px-4 py-2 text-sm font-medium",
            tab === "dich" ? "bg-slate-900 text-white" : "border border-[var(--border)] hover:border-slate-400")}>
          <Languages className="size-4" /> Dịch
        </button>
        <button type="button" onClick={() => setTab("dam-thoai")}
          className={cn("flex items-center gap-2 rounded-[12px] px-4 py-2 text-sm font-medium",
            tab === "dam-thoai" ? "bg-slate-900 text-white" : "border border-[var(--border)] hover:border-slate-400")}>
          <MessagesSquare className="size-4" /> Đàm thoại
        </button>
      </div>
      {tab === "dich" ? <DichPageContent /> : <DamThoai />}
    </div>
  );
}
