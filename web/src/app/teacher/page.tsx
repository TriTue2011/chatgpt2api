"use client";

/**
 * Tab Giáo viên — lớp học web:
 * 1) Bài giảng: văn chữ + kịch bản TTS
 * 2) Bài tập: giao / HS làm trên web / chấm + sửa lỗi
 * 3) Dashboard PH: weak topics theo tuần + adaptive
 * 4) Import SGK PDF theo chương
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  GraduationCap,
  BookOpen,
  ClipboardList,
  Users,
  FileUp,
  FileText,
  LoaderCircle,
  PlayCircle,
  Save,
  Send,
  Volume2,
  RefreshCw,
  Trash2,
  Maximize2,
  Minimize2,
  Sparkles,
  Route,
  UserCircle,
  ChevronDown,
  ChevronUp,
  Link2,
  Download,
  BookMarked,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { httpRequest, request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";

// Module scope, file riêng — component lồng trong TeacherPage bị tạo lại mỗi
// render (họ lỗi React #310 đã vá ở trang này).
import { LectureTab, SgkViewerTab } from "./lecture-tab";

type TabId = "roster" | "lecture" | "lesson" | "homework" | "placement" | "parent" | "sgkview" | "import";

/** Tab chỉ có nghĩa khi ĐÃ chọn một hồ sơ học sinh (lớp quyết định SGK/đề/lộ trình).
 *  Khai ở cấp module: mảng `tabs` dựng lại mỗi lần render nên không dùng được làm
 *  dependency, và nó lại khai SAU các effect — đưa vào deps là TDZ, trang trắng. */
const NEED_STUDENT: readonly TabId[] = ["lecture", "lesson", "homework", "placement", "parent", "sgkview"];

/** Hồ sơ học sinh — lớp SUY TỪ NĂM SINH nên không phải sửa tay mỗi năm. */
type StudentRow = {
  student_key: string;
  display_name?: string;
  birth_year?: number | null;
  grade?: number;               // lớp cuối cùng (khai tay > suy năm sinh)
  grade_computed?: number;      // suy từ năm sinh
  grade_override?: number | null;
  grade_source?: string;
  age?: number | null;
  school_year?: string;
  notes?: string;
  placements?: { subject: string; level?: string; score_pct?: number }[];
  roadmaps?: { subject: string; focus?: string; steps_done?: number; steps_total?: number }[];
};

type Lesson = {
  id: string;
  title: string;
  body_text: string;
  tts_script: string;
  grade: number;
  subject: string;
  workspace_id?: string;
  created?: string;
  preview?: string;
};

type Assignment = {
  id: string;
  title: string;
  grade: number;
  subject: string;
  topic?: string;
  difficulty?: string;
  n_questions?: number;
  questions?: { id: string; prompt: string; answer_hint?: string; type?: string }[];
  workspace_id?: string;
  created?: string;
  lesson_id?: string;
};

type ParentStudent = {
  workspace_id: string;
  student_key: string;
  display_name?: string;
  grade?: number;
  weak_topics?: string[];
  strong_topics?: string[];
  weekly?: { week: string; weak_topics: string[] }[];
  adaptive_level?: string;
  streak_correct?: number;
  streak_wrong?: number;
  updated?: string;
  path?: Record<
    string,
    {
      level_label?: string;
      score_pct?: number;
      current_focus?: string;
      current_topic?: string;
      steps_done?: number;
      steps_total?: number;
      last_practice?: { message?: string; action?: string; average_0_10?: number };
      weak_strands?: string[];
      strong_strands?: string[];
    }
  >;
};

type FocusInfo = {
  ok?: boolean;
  topic?: string;
  title?: string;
  step_id?: string;
  phase?: string;
  current_focus?: string;
  roadmap_steps_done?: number;
  roadmap_steps_total?: number;
  source?: string;
  error?: string;
};

/** Chỉ là LƯỚI ĐỠ khi chưa gọi được /api/teacher/subjects. Danh mục thật do
 *  backend giữ (teacher_workspace.SUBJECTS + GRADE_SUBJECTS) — khai hai nơi thì
 *  thêm môn ở backend mà dropdown vẫn thiếu, đúng lỗi vừa gặp. */
const SUBJECTS_FALLBACK = [
  { id: "toan", label: "Toán" },
  { id: "tviet", label: "Tiếng Việt" },
  { id: "van", label: "Ngữ văn" },
  { id: "anh", label: "Tiếng Anh" },
];

const GRADES = Array.from({ length: 12 }, (_, i) => i + 1);

/** Hai khối tạm ẩn theo yêu cầu — CODE GIỮ NGUYÊN, đổi thành `true` là hiện lại.
 *
 *  Cố ý dùng cờ chứ không xoá: cả hai khối đều còn dùng được, chỉ là đang không
 *  hợp lý ở vị trí hiện tại. Xoá đi rồi dựng lại từ git là tốn công vô ích.
 *
 *  - SHOW_GLOBAL_FILTERS: bộ lọc lớp–môn–học sinh ở đầu trang. Ẩn nó thì tab
 *    Import phải tự có ô chọn lớp/môn (đã thêm) — nếu không sẽ không chọn được
 *    nạp vào lớp nào.
 *  - SHOW_AUTOFILL: panel "Tự tìm & nạp SGK toàn bộ 120 tổ hợp".
 */
// Khai kiểu `boolean` (không để TS suy ra literal `false`) để không bị cảnh báo
// "điều kiện luôn sai" và để đổi thành true là chạy ngay, không phải sửa gì thêm.
const SHOW_GLOBAL_FILTERS: boolean = false;
const SHOW_AUTOFILL: boolean = false;

/** Khối thu gọn được. Mở: y hệt trước, thêm nút ▲ góc phải. Thu: còn 1 dòng
 *  tiêu đề. Trạng thái nhớ theo máy (localStorage) nên vào lại vẫn giữ nguyên. */
function Fold({
  id,
  title,
  className,
  children,
}: {
  id: string;
  title: string;
  className?: string;
  children: React.ReactNode;
}) {
  const key = `teacher.fold.${id}`;
  const [open, setOpen] = useState(true);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    // Đọc sau khi mount để không lệch server/client render (hydration).
    try {
      setOpen(localStorage.getItem(key) !== "0");
    } catch {
      /* localStorage bị chặn → mặc định mở */
    }
    setReady(true);
  }, [key]);
  const toggle = () => {
    setOpen((v) => {
      try {
        localStorage.setItem(key, v ? "0" : "1");
      } catch {
        /* bỏ qua */
      }
      return !v;
    });
  };
  if (ready && !open) {
    return (
      <Card className={className}>
        <button
          type="button"
          onClick={toggle}
          title="Mở lại"
          className="w-full flex items-center justify-between px-4 py-2.5 text-xs font-semibold text-muted-foreground hover:text-foreground"
        >
          <span className="truncate">{title}</span>
          <ChevronDown className="size-3.5 shrink-0" />
        </button>
      </Card>
    );
  }
  return (
    <Card className={`relative ${className || ""}`}>
      <button
        type="button"
        onClick={toggle}
        title={`Thu gọn: ${title}`}
        aria-label={`Thu gọn ${title}`}
        className="absolute right-1.5 top-1.5 z-10 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <ChevronUp className="size-3.5" />
      </button>
      {children}
    </Card>
  );
}

type AutofillState = {
  enabled?: boolean;
  interval_days?: number;
  running_now?: boolean;
  combos?: number;
  last?: {
    index?: number;
    total?: number;
    current?: string;
    running?: boolean;
    started_at?: string;
    finished_at?: string;
    counts?: { ok?: number; no_source?: number; failed?: number; skipped?: number };
  };
};

type BulkDoc = {
  status?: string; grade?: number; slug?: string; kind?: string;
  error?: string; pages?: number; chunks?: number; collection?: string;
  sample?: boolean;
};
type BulkResp = {
  running?: boolean;
  summary?: string;
  state?: {
    running?: boolean; stopped?: boolean; dry_run?: boolean;
    index?: number; total?: number; current?: string; current_grade?: number;
    kinds?: string[]; pages_total?: number; chunks_total?: number;
    started_at?: string; finished_at?: string;
    counts?: { ok?: number; failed?: number; skipped?: number };
    books?: Record<string, BulkDoc>;
  };
};
type StorageResp = {
  pdf_files?: number; pdf_bytes?: number; md_files?: number; md_bytes?: number;
};

const BULK_KINDS: { id: string; label: string; hint: string }[] = [
  {
    id: "slide", label: "Slide (gần như miễn phí)",
    hint: "chữ thật, hầu hết KHÔNG cần OCR — phân bổ tuần/tiết + phương pháp dạy. "
      + "192/198 quyển có; 101 bộ khác nhau, ~2,1 MB chữ; chỉ ~1% là slide ảnh "
      + "phải OCR",
  },
  { id: "sgk", label: "SGK", hint: "sách học sinh — nội dung phải học" },
  { id: "sgv", label: "SGV + KHBD", hint: "sách giáo viên, kế hoạch bài dạy — cách dạy" },
  { id: "vbt", label: "VBT + SBT", hint: "vở & sách bài tập — mẫu ra đề" },
  { id: "tap_huan", label: "Tài liệu tập huấn", hint: "bồi dưỡng giáo viên" },
];

const fmtMB = (b?: number) => `${((b || 0) / 1024 / 1024).toFixed(1)} MB`;

/** Nạp CẢ KHO taphuan vào RAG: chọn lớp + loại tài liệu, chạy nền, nối lại được.
 *
 *  Là component RIÊNG, không nhét vào TeacherPage: TeacherPage có guard
 *  `if (isCheckingAuth) return` ở giữa thân hàm, thêm hook vào đó là tái lập
 *  đúng lỗi React #310 (trang trắng) vừa phải đi vá.
 *
 *  Tiến độ đếm theo QUYỂN (trang chi tiết), còn mỗi quyển có thể ra 1–4 tài
 *  liệu tuỳ loại đã chọn — nên phần trăm là ước lượng, ghi rõ để không ai tưởng
 *  nó chính xác tới từng tài liệu. */
function BulkSgkPanel() {
  const [st, setSt] = useState<BulkResp | null>(null);
  const [store, setStore] = useState<StorageResp | null>(null);
  const [busy, setBusy] = useState(false);
  // Bật sẵn slide: nó không tốn lượt gọi model nào mà lại là nguồn phân bổ
  // tuần–tiết duy nhất lấy được không qua OCR. Bỏ tick được nếu không muốn.
  const [kinds, setKinds] = useState<string[]>(["slide", "sgk"]);
  const [allSets, setAllSets] = useState(false);
  const [keepPdf, setKeepPdf] = useState(false);
  const [gradeFrom, setGradeFrom] = useState(1);
  const [gradeTo, setGradeTo] = useState(12);

  const load = useCallback(async () => {
    try {
      setSt(await httpRequest<BulkResp>("/api/teacher/bulk"));
    } catch { /* panel phụ — im lặng, không phá trang */ }
  }, []);

  const loadStore = useCallback(async () => {
    try {
      setStore(await httpRequest<StorageResp>("/api/teacher/storage"));
    } catch { /* im lặng */ }
  }, []);

  useEffect(() => { void load(); void loadStore(); }, [load, loadStore]);

  const running = !!st?.running;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [running, load]);

  const toggleKind = (id: string) =>
    setKinds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);

  const grades = useMemo(() => {
    const a = Math.min(gradeFrom, gradeTo);
    const b = Math.max(gradeFrom, gradeTo);
    return Array.from({ length: b - a + 1 }, (_, i) => a + i);
  }, [gradeFrom, gradeTo]);

  const start = async () => {
    if (!kinds.length) { toast.error("Chọn ít nhất một loại tài liệu"); return; }
    const n = grades.length;
    if (!window.confirm(
      `Nạp lớp ${grades[0]}–${grades[n - 1]} (${n} lớp), loại: `
      + `${kinds.join(", ")}${allSets ? ", CẢ các bộ sách khác" : ""}.\n\n`
      + `Đây là việc DÀI — mỗi 20 trang là một lượt gọi model vision, cả kho `
      + `khoảng 8.000–10.000 trang. Chạy nền, nối lại được, dừng lúc nào cũng `
      + `được và không mất công đã làm.\n\nBắt đầu?`)) return;
    setBusy(true);
    try {
      await httpRequest("/api/teacher/bulk/start", {
        method: "POST",
        body: { grades, kinds, all_sets: allSets, keep_pdf: keepPdf, skip_done: true },
      });
      toast.success("Đã bắt đầu — theo dõi tiến độ ngay bên dưới");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Không chạy được");
    } finally { setBusy(false); }
  };

  const stop = async () => {
    setBusy(true);
    try {
      await httpRequest("/api/teacher/bulk/stop", { method: "POST", body: {} });
      toast.success("Sẽ dừng sau khi xong tài liệu đang chạy");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Lỗi");
    } finally { setBusy(false); }
  };

  const purge = async () => {
    if (!window.confirm(
      "Xoá toàn bộ PDF đã lưu?\n\nAN TOÀN: PDF chỉ để đối chiếu lại. Kiến thức "
      + "đã nằm ở file .md và trong RAG — xoá PDF KHÔNG mất gì đã nạp.")) return;
    setBusy(true);
    try {
      const r = await httpRequest<{ deleted?: number; freed_bytes?: number }>(
        "/api/teacher/pdfs", { method: "DELETE" });
      toast.success(`Đã xoá ${r?.deleted ?? 0} PDF, giải phóng ${fmtMB(r?.freed_bytes)}`);
      await loadStore();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Lỗi");
    } finally { setBusy(false); }
  };

  const s = st?.state;
  const c = s?.counts || {};
  const total = s?.total || 0;
  const pct = total ? Math.min(100, Math.round(((s?.index || 0) / total) * 100)) : 0;
  const failed = Object.values(s?.books || {}).filter((r) => r.status === "failed");

  return (
    <div className="rounded border border-sky-500/25 bg-sky-500/5 p-2.5 space-y-2.5">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-[10px] font-semibold flex items-center gap-1">
          <BookMarked className="size-3 text-sky-600" />
          Nạp cả kho taphuan.nxbgd.vn vào RAG
        </div>
        <div className="flex items-center gap-1.5">
          <Button size="sm" className="h-7 text-[11px]" disabled={busy || running}
            onClick={() => void start()}>
            {busy ? <LoaderCircle className="size-3 animate-spin" /> : <PlayCircle className="size-3" />}
            <span className="ml-1">Chạy</span>
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-[11px]"
            disabled={busy || !running} onClick={() => void stop()}>
            Dừng
          </Button>
          <Button size="sm" variant="ghost" className="h-7 text-[11px]"
            disabled={busy} onClick={() => { void load(); void loadStore(); }}>
            <RefreshCw className="size-3" />
          </Button>
        </div>
      </div>

      {/* Chọn lớp */}
      <div className="flex items-end gap-2 flex-wrap">
        <div>
          <label className="text-[10px] text-muted-foreground">Từ lớp</label>
          <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-xs"
            value={gradeFrom} disabled={running}
            onChange={(e) => setGradeFrom(Number(e.target.value))}>
            {GRADES.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-muted-foreground">Đến lớp</label>
          <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-xs"
            value={gradeTo} disabled={running}
            onChange={(e) => setGradeTo(Number(e.target.value))}>
            {GRADES.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
        <p className="text-[10px] text-muted-foreground pb-1.5">
          {grades.length} lớp · môn lấy theo danh mục của dự án cho từng lớp
        </p>
      </div>

      {/* Chọn loại tài liệu — mỗi loại vào một kho RAG riêng */}
      <div className="space-y-1">
        <div className="text-[10px] font-semibold">Loại tài liệu (mỗi loại một kho riêng)</div>
        <div className="grid gap-1 sm:grid-cols-2">
          {BULK_KINDS.map((k) => (
            <label key={k.id} className="flex items-start gap-1.5 text-[10px] cursor-pointer">
              <input type="checkbox" className="mt-0.5" checked={kinds.includes(k.id)}
                disabled={running} onChange={() => toggleKind(k.id)} />
              <span><b>{k.label}</b> <span className="text-muted-foreground">— {k.hint}</span></span>
            </label>
          ))}
        </div>
        <label className="flex items-start gap-1.5 text-[10px] cursor-pointer">
          <input type="checkbox" className="mt-0.5" checked={allSets} disabled={running}
            onChange={(e) => setAllSets(e.target.checked)} />
          <span>Nạp cả <b>các bộ sách khác</b>
            <span className="text-muted-foreground"> — bộ khác là chương trình khác cho cùng môn, vào kho <code>kb_giao_duc_bo&#123;N&#125;</code> riêng</span>
          </span>
        </label>
        <label className="flex items-start gap-1.5 text-[10px] cursor-pointer">
          <input type="checkbox" className="mt-0.5" checked={keepPdf} disabled={running}
            onChange={(e) => setKeepPdf(e.target.checked)} />
          <span>Giữ lại PDF
            <span className="text-muted-foreground"> — cả kho là hàng chục GB, chỉ để đối chiếu. Bỏ tick thì xoá ngay sau khi có RAG.</span>
          </span>
        </label>
      </div>

      {/* Tiến độ */}
      {s && (
        <div className="space-y-1">
          <div className="h-1.5 rounded bg-border overflow-hidden">
            <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
          <div className="text-[10px] text-muted-foreground">
            {running ? "Đang chạy" : s.finished_at ? "Đã dừng/xong" : "Chưa chạy"}
            {" · "}~{s.index || 0}/{total} quyển ({pct}%)
            {" · "}✅ {c.ok || 0} · ↩︎ {c.skipped || 0} bỏ qua · ❌ {c.failed || 0}
            {" · "}📄 {s.pages_total || 0} trang · 🧩 {s.chunks_total || 0} chunks
          </div>
          {s.current && (
            <div className="text-[10px] truncate">Đang: <b>{s.current}</b></div>
          )}
          {!!s.kinds?.length && (
            <div className="text-[10px] text-muted-foreground">
              Lượt chạy này nạp: {s.kinds.join(", ")}
            </div>
          )}
          {failed.length > 0 && (
            <details className="text-[10px]">
              <summary className="cursor-pointer text-red-500">
                {failed.length} tài liệu lỗi — xem
              </summary>
              <ul className="mt-1 space-y-0.5 max-h-40 overflow-auto">
                {failed.slice(-25).map((r, i) => (
                  <li key={i} className="text-muted-foreground">
                    lớp {r.grade} · {r.kind || "?"} · {r.slug}: {r.error}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {/* Dung lượng */}
      <div className="flex items-center justify-between gap-2 flex-wrap border-t border-border pt-1.5">
        <div className="text-[10px] text-muted-foreground">
          PDF: <b>{store?.pdf_files ?? 0}</b> file · {fmtMB(store?.pdf_bytes)}
          {" · "}Markdown SGK: <b>{store?.md_files ?? 0}</b> file · {fmtMB(store?.md_bytes)}
        </div>
        <Button size="sm" variant="outline" className="h-7 text-[11px]"
          disabled={busy || !store?.pdf_files} onClick={() => void purge()}>
          <Trash2 className="size-3" />
          <span className="ml-1">Dọn PDF</span>
        </Button>
      </div>
    </div>
  );
}

/** Tự tìm & nạp SGK: nút chạy ngay + công tắc định kỳ + thanh tiến độ.
 *  Khi đang chạy thì hỏi tiến độ mỗi 5s, chạy xong thì thôi hỏi. */
function AutofillPanel() {
  const [st, setSt] = useState<AutofillState | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setSt(await httpRequest<AutofillState>("/api/teacher/autofill"));
    } catch {
      /* im lặng — panel phụ, không phá trang */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const running = !!st?.running_now;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [running, load]);

  const call = async (path: string, body?: unknown) => {
    setBusy(true);
    try {
      // PHẢI dùng httpRequest, KHÔNG dùng `request`: `request` là axios
      // instance thô — nó không hiểu khoá `body` (axios dùng `data`) nên POST
      // đi với thân RỖNG → /settings khai `payload: dict` bắt buộc → 422; và
      // nó trả AxiosResponse chứ không trả JSON. httpRequest map body→data và
      // trả thẳng response.data.
      const r = await httpRequest<{ ok?: boolean; message?: string }>(path, {
        method: "POST",
        body: body ?? {},
      });
      if (r?.message) toast[r.ok === false ? "warning" : "success"](r.message);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Lỗi");
    } finally {
      setBusy(false);
    }
  };

  const last = st?.last;
  const c = last?.counts || {};
  const total = last?.total || st?.combos || 0;
  const pct = total ? Math.round(((last?.index || 0) / total) * 100) : 0;

  return (
    <div className="rounded border border-amber-500/25 bg-amber-500/5 p-2.5 space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-[10px] font-semibold flex items-center gap-1">
          <Sparkles className="size-3 text-amber-600" />
          Tự tìm &amp; nạp SGK — toàn bộ {st?.combos ?? 120} tổ hợp lớp × môn
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            className="h-7 text-[11px]"
            disabled={busy || running}
            onClick={() => void call("/api/teacher/autofill/start")}
          >
            {running ? (
              <LoaderCircle className="size-3 animate-spin" />
            ) : (
              <Sparkles className="size-3" />
            )}
            {running ? "Đang chạy…" : "Chạy ngay"}
          </Button>
          {running && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-[11px]"
              disabled={busy}
              onClick={() => void call("/api/teacher/autofill/stop")}
            >
              Dừng
            </Button>
          )}
        </div>
      </div>

      <p className="text-[10px] text-muted-foreground">
        Tìm PDF công khai theo lớp–môn rồi nạp vào RAG. Lớp/môn không có sách sẽ
        được bỏ qua, không tính là lỗi. Tổ hợp đã nạp trước đó cũng bỏ qua nên
        chạy lại là đi tiếp, không tải lại từ đầu.
      </p>

      {/* Định kỳ */}
      <div className="flex items-center gap-2 flex-wrap text-[10px]">
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            className="size-3"
            checked={!!st?.enabled}
            disabled={busy}
            onChange={(e) =>
              void call("/api/teacher/autofill/settings", { enabled: e.target.checked })
            }
          />
          Tự chạy định kỳ
        </label>
        <span className="text-muted-foreground">mỗi</span>
        <select
          className="h-6 rounded border border-border bg-background px-1 text-[10px]"
          value={String(st?.interval_days ?? 7)}
          disabled={busy}
          onChange={(e) =>
            void call("/api/teacher/autofill/settings", {
              interval_days: Number(e.target.value),
            })
          }
        >
          {[1, 3, 7, 14, 30, 90].map((d) => (
            <option key={d} value={d}>
              {d} ngày
            </option>
          ))}
        </select>
      </div>

      {/* Tiến độ */}
      {last?.started_at && (
        <div className="space-y-1">
          <div className="h-1.5 w-full rounded bg-muted overflow-hidden">
            <div
              className="h-full bg-amber-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="text-[10px] text-muted-foreground">
            {last.index || 0}/{total} · ✅ {c.ok || 0} nạp được · ⬜ {c.no_source || 0} không
            có sách · ❌ {c.failed || 0} hỏng · ↩︎ {c.skipped || 0} bỏ qua
            {last.current ? ` · đang: ${last.current}` : ""}
            {!last.running && last.finished_at ? ` · xong ${last.finished_at}` : ""}
          </div>
        </div>
      )}
    </div>
  );
}

export default function TeacherPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin", "user"]);
  const [tab, setTab] = useState<TabId>("roster");

  // shared filters
  const [grade, setGrade] = useState(2);
  const [subject, setSubject] = useState("toan");
  const [student, setStudent] = useState("hs1");
  const workspace = useMemo(() => `lop${grade}-${subject}`, [grade, subject]);

  // lessons
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [lessonTitle, setLessonTitle] = useState("");
  const [lessonBody, setLessonBody] = useState("");
  const [lessonTts, setLessonTts] = useState("");
  const [activeLesson, setActiveLesson] = useState<Lesson | null>(null);
  const [busy, setBusy] = useState(false);
  const [deletingLesson, setDeletingLesson] = useState<Lesson | null>(null);
  const [deletingLessonBusy, setDeletingLessonBusy] = useState(false);

  // assignments
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [asgTitle, setAsgTitle] = useState("");
  const [asgTopic, setAsgTopic] = useState("");
  // Mục lục lớp–môn cho tab Bài tập: cùng nguồn với tab Bài giảng, để bài tập
  // cũng chọn theo BÀI của sách chứ không chỉ gõ chủ đề tự do.
  const [asgToc, setAsgToc] = useState<{ bai?: string; ten: string; trang?: number | null; tap?: string }[]>([]);
  const [asgN, setAsgN] = useState(5);
  const [asgDiff, setAsgDiff] = useState("auto");
  const [doAsg, setDoAsg] = useState<Assignment | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<any>(null);
  const [subs, setSubs] = useState<any[]>([]);
  const [hwFullscreen, setHwFullscreen] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [lessonTopic, setLessonTopic] = useState("");
  const [lessonNotes, setLessonNotes] = useState("");
  const [enSkills, setEnSkills] = useState<
    { id: string; label: string }[]
  >([]);
  const [enCefr, setEnCefr] = useState("");

  // parent
  const [dash, setDash] = useState<ParentStudent[]>([]);
  const [dashWeeks, setDashWeeks] = useState<string[]>([]);

  // import
  const [impMode, setImpMode] = useState<"append" | "replace">("append");
  const [impBusy, setImpBusy] = useState(false);
  const [impFileName, setImpFileName] = useState("");
  const [impFileSize, setImpFileSize] = useState(0);
  const impFileRef = useRef<HTMLInputElement | null>(null);
  type ImpPdfRow = {
    name: string;
    grade: number;
    subject: string;
    subject_label?: string;
    size_bytes?: number;
    mtime?: number;
    workspace?: string;
  };
  type ImpMdRow = {
    grade: number;
    subject: string;
    subject_label?: string;
    exists: boolean;
    chars: number;
    chapters: number;
    mtime?: number;
    workspace?: string;
  };
  const [impList, setImpList] = useState<ImpPdfRow[]>([]);
  const [impMd, setImpMd] = useState<ImpMdRow | null>(null);
  const [impListLoading, setImpListLoading] = useState(false);
  // Danh mục môn lấy từ backend: {id,label} toàn bộ + môn của TỪNG LỚP.
  const [subjAll, setSubjAll] = useState<{ id: string; label: string }[]>(SUBJECTS_FALLBACK);
  const [subjByGrade, setSubjByGrade] = useState<Record<string, string[]>>({});

  // Nạp bằng URL (taphuan chi-tiet / doc-sach, hoặc link .pdf trực tiếp)
  const [impUrl, setImpUrl] = useState("");
  const [impUrlBusy, setImpUrlBusy] = useState(false);
  // Danh sách SGK TOÀN BỘ 12 lớp × 3 môn — tách khỏi impList/impMd vì hai cái
  // đó chỉ là một tổ hợp lớp–môn đang chọn.
  const [sgkAll, setSgkAll] = useState<{ imports: ImpPdfRow[]; markdown: ImpMdRow[] } | null>(null);
  const [sgkLoading, setSgkLoading] = useState(false);
  // Mặc định THU HẾT — bấm lớp nào mới mở lớp đó.
  const [sgkOpen, setSgkOpen] = useState<number[]>([]);

  // placement + roadmap
  const [students, setStudents] = useState<any[]>([]);
  // Hồ sơ học sinh đang xem. "" = chưa chọn ⇒ 4 tab bên trong bị khoá, vì không
  // biết lớp thì SGK/đề/lộ trình đều không có căn cứ.
  const [pickedKey, setPickedKey] = useState("");
  const [schoolYear, setSchoolYear] = useState("");
  // Form thêm học sinh: CHỈ tên + năm sinh (lớp tự suy). Ô lớp khai tay để
  // riêng, chỉ dùng khi công thức không đúng.
  const [newName, setNewName] = useState("");
  const [newBirth, setNewBirth] = useState("");
  const [newOverride, setNewOverride] = useState("");
  const [rosterBusy, setRosterBusy] = useState(false);
  const [placeQs, setPlaceQs] = useState<any[]>([]);
  const [placeId, setPlaceId] = useState("");
  const [placeAnswers, setPlaceAnswers] = useState<Record<string, string>>({});
  const [placeResult, setPlaceResult] = useState<any>(null);
  const [roadmap, setRoadmap] = useState<any>(null);
  const [placeInfo, setPlaceInfo] = useState("");
  const [focusInfo, setFocusInfo] = useState<FocusInfo | null>(null);

  const loadLessons = useCallback(async () => {
    try {
      const r = await request.get("/api/teacher/lessons");
      setLessons((r.data as { rows?: Lesson[] })?.rows || []);
    } catch {
      /* optional */
    }
  }, []);

  const loadAssignments = useCallback(async () => {
    try {
      const r = await request.get("/api/teacher/assignments");
      setAssignments((r.data as { rows?: Assignment[] })?.rows || []);
    } catch {
      /* optional */
    }
  }, []);

  const loadDashboard = useCallback(async () => {
    try {
      const r = await request.get("/api/teacher/dashboard", {
        params: { workspace, student, weeks: 4 },
      });
      const d = r.data as { students?: ParentStudent[]; weeks?: string[] };
      setDash(d?.students || []);
      setDashWeeks(d?.weeks || []);
    } catch {
      toast.error("Không tải được dashboard PH");
    }
  }, [workspace, student]);

  const loadStudents = useCallback(async () => {
    try {
      const r = await request.get("/api/teacher/students");
      setStudents((r.data as { rows?: any[] })?.rows || []);
    } catch {
      /* */
    }
  }, []);

  const loadRoadmap = useCallback(async () => {
    try {
      const r = await request.get(
        `/api/teacher/students/${encodeURIComponent(student)}/roadmap`,
        { params: { subject } },
      );
      setRoadmap((r.data as { roadmap?: any })?.roadmap || null);
      setPlaceResult((r.data as { placement?: any })?.placement || null);
    } catch {
      setRoadmap(null);
    }
  }, [student, subject]);

  const loadFocus = useCallback(async () => {
    if (!student.trim()) {
      setFocusInfo(null);
      return;
    }
    try {
      const r = await request.get(
        `/api/teacher/students/${encodeURIComponent(student)}/focus`,
        { params: { subject, grade } },
      );
      setFocusInfo((r.data as FocusInfo) || null);
    } catch {
      setFocusInfo(null);
    }
  }, [student, subject, grade]);

  useEffect(() => {
    if (!session) return;
    void loadLessons();
    void loadAssignments();
  }, [session, loadLessons, loadAssignments]);

  useEffect(() => {
    if (tab === "parent" && session) void loadDashboard();
  }, [tab, session, loadDashboard]);

  useEffect(() => {
    if (session) void loadFocus();
  }, [session, loadFocus]);

  useEffect(() => {
    // Tab "Học sinh" cũng cần danh sách; trước chỉ nạp ở tab placement nên vào
    // thẳng tab khác là danh sách rỗng.
    if ((tab === "roster" || tab === "placement") && session) {
      void loadStudents();
    }
    // Hàng tab tầng 1 hiện TÊN học sinh ngay khi vào trang — không nạp ở đây
    // thì hàng đó rỗng cho tới khi mở tab Học sinh, trông như chưa có em nào.
    if (session && !students.length) void loadStudents();
    // Mục lục cho tab Bài tập: theo LỚP của học sinh đang chọn + môn đang chọn.
    if (tab === "homework" && session && picked?.grade) {
      void (async () => {
        try {
          const r = await httpRequest<{ rows?: any[] }>(
            `/api/teacher/lecture/toc?grade=${picked.grade}&subject=${subject}`);
          setAsgToc(r.rows || []);
        } catch { setAsgToc([]); }
      })();
    }
    if (tab === "placement" && session) {
      void loadRoadmap();
    }
  }, [tab, session, students.length, picked, subject, loadStudents, loadRoadmap]);

  const loadImports = useCallback(async () => {
    if (!session) return;
    setImpListLoading(true);
    try {
      const r = await request.get("/api/teacher/imports", {
        params: { grade, subject, limit: 40 },
      });
      const d = r.data as {
        imports?: ImpPdfRow[];
        markdown?: ImpMdRow[];
      };
      setImpList(d?.imports || []);
      const md = (d?.markdown || []).find(
        (m) => m.grade === grade && m.subject === subject,
      );
      setImpMd(md || null);
    } catch {
      setImpList([]);
      setImpMd(null);
    } finally {
      setImpListLoading(false);
    }
  }, [session, grade, subject]);

  /** Toàn bộ SGK: KHÔNG truyền grade/subject nên backend trả markdown của cả
   *  12 lớp × môn CỦA TỪNG LỚP (list_imports lặp GRADES × GRADE_SUBJECTS khi
   *  không có filter).
   *  Bản cũ luôn gọi kèm filter nên danh sách chỉ có đúng một tổ hợp — đó là
   *  lý do "danh sách SGK chưa đầy đủ". */
  const loadSgkAll = useCallback(async () => {
    if (!session) return;
    setSgkLoading(true);
    try {
      const r = await request.get("/api/teacher/imports", { params: { limit: 200 } });
      const d = r.data as { imports?: ImpPdfRow[]; markdown?: ImpMdRow[] };
      setSgkAll({ imports: d?.imports || [], markdown: d?.markdown || [] });
    } catch {
      setSgkAll(null);
    } finally {
      setSgkLoading(false);
    }
  }, [session]);

  useEffect(() => {
    if (tab === "import" && session) {
      void loadImports();
      void loadSgkAll();
    }
  }, [tab, session, loadImports, loadSgkAll]);

  // Danh mục môn — nạp một lần khi vào trang.
  useEffect(() => {
    if (!session) return;
    void (async () => {
      try {
        const r = await request.get("/api/teacher/subjects");
        const d = r.data as {
          subjects?: { id: string; label: string }[];
          by_grade?: Record<string, string[]>;
        };
        if (d?.subjects?.length) setSubjAll(d.subjects);
        if (d?.by_grade) setSubjByGrade(d.by_grade);
      } catch {
        /* giữ lưới đỡ — trang vẫn dùng được với 3 môn gốc */
      }
    })();
  }, [session]);

  /** Môn của lớp đang chọn. Chưa có bảng by_grade thì trả toàn bộ (thà rộng
   *  hơn là chặn oan lúc backend chưa kịp trả). */
  const subjectsOfGrade = useMemo(() => {
    const ids = subjByGrade[String(grade)];
    if (!ids?.length) return subjAll;
    const order = new Map(subjAll.map((s, i) => [s.id, i]));
    return ids
      .map((id) => subjAll.find((s) => s.id === id) || { id, label: id })
      .sort((a, b) => (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99));
  }, [subjByGrade, subjAll, grade]);

  // Đổi lớp mà môn đang chọn không có ở lớp đó ⇒ nhảy về môn đầu tiên hợp lệ.
  // Không làm thì màn hình hiện "Vật lí" cho lớp 1 rồi nạp vào một workspace
  // không tồn tại.
  useEffect(() => {
    if (!subjectsOfGrade.length) return;
    if (!subjectsOfGrade.some((s) => s.id === subject)) {
      setSubject(subjectsOfGrade[0].id);
    }
  }, [subjectsOfGrade, subject]);

  useEffect(() => {
    if (!session || subject !== "anh") {
      setEnSkills([]);
      setEnCefr("");
      return;
    }
    void (async () => {
      try {
        const r = await request.get("/api/teacher/english/skills", {
          params: { grade },
        });
        const d = r.data as {
          skills?: { id: string; label: string }[];
          cefr?: string;
        };
        setEnSkills(d?.skills || []);
        setEnCefr(d?.cefr || "");
      } catch {
        setEnSkills([]);
      }
    })();
  }, [session, subject, grade]);

  const saveLesson = async () => {
    if (!lessonBody.trim()) {
      toast.error("Nhập nội dung bài (văn chữ) cho học sinh");
      return;
    }
    setBusy(true);
    try {
      const r = await request.post("/api/teacher/lessons", {
        title: lessonTitle || `Bài lớp ${grade} · ${subject}`,
        body_text: lessonBody,
        tts_script: lessonTts,
        grade,
        subject,
        workspace_id: workspace,
        student_key: student,
      });
      const lesson = (r.data as { lesson?: Lesson })?.lesson;
      toast.success("Đã lưu bài giảng");
      setActiveLesson(lesson || null);
      setLessonTitle("");
      setLessonBody("");
      setLessonTts("");
      void loadLessons();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Lỗi lưu bài");
    } finally {
      setBusy(false);
    }
  };

  const previewTts = async (text: string) => {
    if (!text.trim()) {
      toast.error("Chưa có kịch bản TTS");
      return;
    }
    try {
      const { getStoredAuthKey } = await import("@/store/auth");
      let key = await getStoredAuthKey();
      if (!key) {
        try {
          key = localStorage.getItem("chatgpt2api_auth_key") || "";
        } catch {
          /* */
        }
      }
      // Dùng preview TTS hệ thống nếu có voice default
      const url =
        `/api/voice/preview?stream=1&text=${encodeURIComponent(text.slice(0, 500))}` +
        `&key=${encodeURIComponent(key || "")}`;
      const audio = new Audio(url);
      await audio.play();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Không phát được TTS");
    }
  };

  const createHomework = async (fromRoadmap = false) => {
    setBusy(true);
    try {
      const r = await request.post("/api/teacher/assignments", {
        title:
          asgTitle ||
          (fromRoadmap && focusInfo?.title
            ? `BT lộ trình: ${focusInfo.title}`
            : `BT ${subject} lớp ${grade}`),
        grade,
        subject,
        topic: fromRoadmap ? "" : asgTopic,
        workspace_id: workspace,
        n: asgN,
        difficulty: asgDiff,
        student_key: student,
        lesson_id: activeLesson?.id || "",
        from_roadmap: fromRoadmap || !asgTopic.trim(),
      });
      const asg = (r.data as { assignment?: Assignment & { topic?: string; from_roadmap?: boolean } })
        ?.assignment;
      toast.success(
        asg?.from_roadmap
          ? `Đã giao theo lộ trình · ${asg.topic || focusInfo?.topic || ""}`
          : "Đã giao bài tập",
      );
      setAsgTitle("");
      void loadAssignments();
      void loadFocus();
      if (asg?.id) {
        const full = await request.get(`/api/teacher/assignments/${asg.id}`, {
          params: { student_view: true },
        });
        setDoAsg((full.data as { assignment?: Assignment })?.assignment || null);
        setAnswers({});
        setResult(null);
        setTab("homework");
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Lỗi giao bài");
    } finally {
      setBusy(false);
    }
  };

  const openHomework = async (id: string, studentView = true) => {
    setBusy(true);
    try {
      const full = await request.get(`/api/teacher/assignments/${id}`, {
        params: { student_view: studentView },
      });
      setDoAsg((full.data as { assignment?: Assignment })?.assignment || null);
      setAnswers({});
      setResult(null);
      if (!studentView) {
        const s = await request.get(`/api/teacher/assignments/${id}/submissions`);
        setSubs((s.data as { rows?: any[] })?.rows || []);
      } else {
        setSubs([]);
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Không mở được bài");
    } finally {
      setBusy(false);
    }
  };

  const submitHomework = async () => {
    if (!doAsg?.id) return;
    setBusy(true);
    try {
      const r = await request.post(
        `/api/teacher/assignments/${doAsg.id}/submit`,
        { answers, student_key: student, use_llm: true },
      );
      setResult(r.data);
      const ru = (r.data as any)?.roadmap_update;
      toast.success(
        ru?.message
          ? `Chấm ${(r.data as any)?.average_0_10}/10 · ${ru.message}`
          : `Đã chấm: ${(r.data as any)?.average_0_10}/10`,
      );
      void loadDashboard();
      void loadFocus();
      void loadRoadmap();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Nộp bài lỗi");
    } finally {
      setBusy(false);
    }
  };

  const deleteLesson = async (id: string) => {
    setDeletingLessonBusy(true);
    try {
      await request.delete(`/api/teacher/lessons/${id}`);
      toast.success("Đã xóa bài giảng");
      if (activeLesson?.id === id) setActiveLesson(null);
      setDeletingLesson(null);
      void loadLessons();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Xóa lỗi");
    } finally {
      setDeletingLessonBusy(false);
    }
  };

  const deleteStudent = async (key: string, label?: string) => {
    const name = label || key;
    if (
      !confirm(
        `Xóa học sinh «${name}»?\n\nSẽ xóa hẳn: hồ sơ, test đầu vào, lộ trình và memory liên quan. Không hoàn tác.`,
      )
    ) {
      return;
    }
    try {
      await request.delete(`/api/teacher/students/${encodeURIComponent(key)}`, {
        params: { wipe_memory: true },
      });
      toast.success(`Đã xóa HS «${name}»`);
      if (student === key) {
        setRoadmap(null);
        setPlaceResult(null);
        setPlaceQs([]);
        setPlaceId("");
        setFocusInfo(null);
      }
      void loadStudents();
      void loadDashboard();
      void loadFocus();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Xóa học sinh lỗi");
    }
  };

  const deleteAssignment = async (id: string) => {
    if (!confirm("Xóa bài tập này và các bài nộp liên quan?")) return;
    try {
      await request.delete(`/api/teacher/assignments/${id}`);
      toast.success("Đã xóa bài tập");
      if (doAsg?.id === id) {
        setDoAsg(null);
        setAnswers({});
        setResult(null);
        setSubs([]);
        setHwFullscreen(false);
      }
      void loadAssignments();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Xóa lỗi");
    }
  };

  const aiDraftLesson = async (save = false, fromRoadmap = false) => {
    const topic = lessonTopic.trim() || lessonTitle.trim() || asgTopic.trim();
    if (!topic && !fromRoadmap && !focusInfo?.ok) {
      toast.error("Nhập chủ đề, hoặc bấm «Theo lộ trình» (cần HS đã placement)");
      return;
    }
    setAiBusy(true);
    try {
      const r = await request.post("/api/teacher/ai/lesson", {
        grade,
        subject,
        topic: fromRoadmap ? "" : topic,
        workspace_id: workspace,
        notes: lessonNotes,
        save,
        student_key: student,
        from_roadmap: fromRoadmap || !topic,
      });
      const draft = (r.data as { draft?: any; lesson?: Lesson })?.draft;
      const lesson = (r.data as { lesson?: Lesson })?.lesson;
      if (draft) {
        setLessonTitle(String(draft.title || ""));
        setLessonBody(String(draft.body_text || ""));
        setLessonTts(String(draft.tts_script || ""));
        if (draft.topic) setLessonTopic(String(draft.topic));
        toast.success(
          draft.from_roadmap
            ? `Đã soạn theo lộ trình: ${draft.focus_title || draft.topic}`
            : draft.source === "ai"
              ? "AI đã soạn bài giảng — xem & chỉnh rồi Lưu"
              : "Đã soạn mẫu (template) — chỉnh rồi Lưu",
        );
      }
      if (lesson) {
        setActiveLesson(lesson);
        void loadLessons();
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "AI soạn bài lỗi");
    } finally {
      setAiBusy(false);
    }
  };

  const aiCreateHomework = async (fromRoadmap = false) => {
    const topic = asgTopic.trim() || lessonTopic.trim();
    if (!topic && !fromRoadmap && !focusInfo?.ok) {
      toast.error("Nhập chủ đề, hoặc bấm «Theo lộ trình»");
      return;
    }
    setAiBusy(true);
    try {
      const r = await request.post("/api/teacher/ai/assignment", {
        grade,
        subject,
        topic: fromRoadmap ? "" : topic,
        n: asgN,
        difficulty: asgDiff === "auto" ? "medium" : asgDiff,
        workspace_id: workspace,
        notes: lessonNotes,
        use_ai: true,
        save: true,
        student_key: student,
        lesson_id: activeLesson?.id || "",
        title:
          asgTitle ||
          (fromRoadmap && focusInfo?.title
            ? `BT lộ trình: ${focusInfo.title}`
            : `BT ${subject} lớp ${grade}: ${topic || "lộ trình"}`),
        from_roadmap: fromRoadmap || !topic,
      });
      const asg = (r.data as { assignment?: Assignment; draft?: any })?.assignment;
      const draft = (r.data as { draft?: any })?.draft;
      toast.success(
        draft?.from_roadmap
          ? `Lộ trình · ${draft?.questions?.length || "?"} câu · ${draft?.topic || ""}`
          : draft?.source === "ai"
            ? `AI đã giao ${draft?.questions?.length || "?"} câu`
            : `Đã giao ${draft?.questions?.length || "?"} câu (generator)`,
      );
      void loadAssignments();
      void loadFocus();
      if (asg?.id) {
        const full = await request.get(`/api/teacher/assignments/${asg.id}`, {
          params: { student_view: true },
        });
        setDoAsg((full.data as { assignment?: Assignment })?.assignment || null);
        setAnswers({});
        setResult(null);
        setTab("homework");
      }
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "AI soạn đề lỗi");
    } finally {
      setAiBusy(false);
    }
  };

  const picked: StudentRow | undefined = (students as StudentRow[])
    .find((x) => x.student_key === pickedKey);

  // Lớp + student_key của mọi tab bên trong đi theo HỒ SƠ, không phải ô chọn tay.
  // Đây là điểm chính của cấu trúc mới: chọn học sinh một lần, SGK và đề tự đúng
  // lớp; sang tháng 8 hồ sơ tự lên lớp nên không phải sửa gì.
  useEffect(() => {
    if (!picked) return;
    if (picked.student_key && picked.student_key !== student) setStudent(picked.student_key);
    const g = Number(picked.grade || 0);
    if (g >= 1 && g <= 12 && g !== grade) setGrade(g);
  }, [picked, student, grade]);

  // Bỏ chọn học sinh khi đang ở tab bên trong: tab đó bị khoá nhưng NỘI DUNG
  // vẫn render, tức tiếp tục soạn bài cho một hồ sơ không còn được chọn.
  useEffect(() => {
    if (NEED_STUDENT.includes(tab) && !picked) setTab("roster");
  }, [tab, picked]);

  useEffect(() => {
    if (!session) return;
    void (async () => {
      try {
        const r = await request.get("/api/teacher/school-year");
        if (r.data?.school_year) setSchoolYear(String(r.data.school_year));
      } catch { /* không critical */ }
    })();
  }, [session]);

  // All hooks must be above this guard (Rules of Hooks).
  // KHÔNG thêm hook nào xuống dưới: lần render đầu isCheckingAuth=true nên hàm
  // thoát ở đây, hook dưới guard không chạy; auth xong render tiếp thì chúng
  // mới chạy ⇒ số hook tăng giữa hai lần render ⇒ React #310, trang trắng.
  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const startPlacement = async () => {
    setBusy(true);
    setPlaceResult(null);
    setPlaceAnswers({});
    try {
      const r = await request.post("/api/teacher/placement/start", {
        student_key: student,
        subject,
        grade,
        display_name: student,
        n_per_strand: 2,
      });
      const d = r.data as any;
      setPlaceId(d.placement_id || "");
      setPlaceQs(d.questions || []);
      setPlaceInfo(d.instructions || "");
      toast.success(`Đề đầu vào: ${d.n_questions || "?"} câu · ${d.strands?.length || "?"} mảng`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Không tạo được đề đầu vào");
    } finally {
      setBusy(false);
    }
  };

  const submitPlacement = async () => {
    if (!placeId) return;
    setBusy(true);
    try {
      const r = await request.post(`/api/teacher/placement/${placeId}/submit`, {
        answers: placeAnswers,
        student_key: student,
      });
      setPlaceResult(r.data);
      setRoadmap((r.data as any)?.roadmap || null);
      setPlaceQs([]);
      setPlaceId("");
      toast.success(`Đầu vào xong: ${(r.data as any)?.score_pct}% · ${(r.data as any)?.level_label}`);
      void loadStudents();
      void loadFocus();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Nộp placement lỗi");
    } finally {
      setBusy(false);
    }
  };

  const markStepDone = async (stepId: string) => {
    try {
      const r = await request.post(
        `/api/teacher/students/${encodeURIComponent(student)}/roadmap/advance`,
        { step_id: stepId, done: true },
        { params: { subject } },
      );
      setRoadmap((r.data as any)?.roadmap || null);
      void loadFocus();
      toast.success("Đã đánh dấu hoàn thành bước");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Cập nhật lộ trình lỗi");
    }
  };

  /** Chuẩn hoá tên thành student_key: bỏ dấu, chỉ a-z 0-9 _ -. */
  const keyFromName = (nm: string) =>
    nm.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/gi, "d")
      .toLowerCase().trim().replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "").slice(0, 40);

  const addStudent = async () => {
    const nm = newName.trim();
    if (!nm) { toast.error("Cần tên học sinh"); return; }
    const key = keyFromName(nm);
    if (!key) { toast.error("Tên không tạo được mã hồ sơ — thêm chữ hoặc số"); return; }
    if ((students as StudentRow[]).some((x) => x.student_key === key)) {
      toast.error(`Đã có hồ sơ «${key}» — đổi tên hoặc thêm họ`); return;
    }
    const by = newBirth.trim() ? Number(newBirth.trim()) : null;
    if (by !== null && (!Number.isFinite(by) || by < 1900 || by > 2200)) {
      toast.error("Năm sinh phải là số 4 chữ số, vd 2019"); return;
    }
    const ov = newOverride.trim() ? Number(newOverride.trim()) : 0;
    setRosterBusy(true);
    try {
      const r = await request.post("/api/teacher/students", {
        student_key: key, display_name: nm, birth_year: by, grade: ov,
      });
      const pf = r.data?.profile;
      if (pf?.grade) {
        toast.success(`Đã thêm ${nm} — lớp ${pf.grade} (${pf.grade_source})`);
      } else {
        toast.warning(`Đã thêm ${nm} nhưng CHƯA rõ lớp — điền năm sinh hoặc khai lớp tay`);
      }
      setNewName(""); setNewBirth(""); setNewOverride("");
      await loadStudents();
      setPickedKey(key);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Thêm học sinh lỗi");
    } finally { setRosterBusy(false); }
  };

  const patchStudent = async (key: string, fields: Record<string, unknown>) => {
    try {
      const r = await request.patch(`/api/teacher/students/${encodeURIComponent(key)}`, fields);
      const pf = r.data?.profile;
      toast.success(pf?.grade ? `Đã lưu — lớp ${pf.grade} (${pf.grade_source})` : "Đã lưu");
      await loadStudents();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Sửa hồ sơ lỗi");
    }
  };

  const removeStudent = async (row: StudentRow) => {
    const nm = row.display_name || row.student_key;
    if (!window.confirm(`Xoá hồ sơ «${nm}»?\n\nMất cả kết quả đầu vào, lộ trình và `
      + `ghi chú của em này. Kho SGK KHÔNG bị ảnh hưởng.`)) return;
    try {
      await request.delete(`/api/teacher/students/${encodeURIComponent(row.student_key)}`);
      toast.success(`Đã xoá hồ sơ ${nm}`);
      if (pickedKey === row.student_key) setPickedKey("");
      await loadStudents();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Xoá lỗi");
    }
  };

  // Ba nhóm tab, cố ý xếp theo thứ tự dùng thật:
  //  · Học sinh  — chọn hồ sơ TRƯỚC, vì lớp của hồ sơ quyết định mọi thứ sau đó
  //  · 4 tab bên trong — chỉ mở khi đã chọn học sinh, và đi theo lớp của em đó
  //  · Kho SGK   — dùng CHUNG cho mọi học sinh, không thuộc em nào
  // Hai tầng tab theo cách dùng thật:
  //  · TỔNG (chưa chọn học sinh): quản lý hồ sơ + 4 kho chung (SGK/SGV/SBT/tài liệu)
  //  · HỌC SINH (đã chọn): tab con đi theo LỚP của em đó — bài giảng hai khung,
  //    bài tập, đầu vào·lộ trình, phụ huynh, xem SGK. Mỗi em độc lập.
  const tabs: { id: TabId; label: string; icon: React.ReactNode }[] = picked
    ? [
        { id: "lecture", label: "Bài giảng", icon: <BookOpen className="size-3.5" /> },
        { id: "lesson", label: "Soạn bài (cũ)", icon: <Sparkles className="size-3.5" /> },
        { id: "homework", label: "Bài tập", icon: <ClipboardList className="size-3.5" /> },
        { id: "placement", label: "Đầu vào · Lộ trình", icon: <Route className="size-3.5" /> },
        { id: "parent", label: "Phụ huynh", icon: <Users className="size-3.5" /> },
        { id: "sgkview", label: "SGK", icon: <BookOpen className="size-3.5" /> },
      ]
    : [
        { id: "roster", label: "Học sinh", icon: <UserCircle className="size-3.5" /> },
        { id: "import", label: "Kho chung (SGK·SGV·SBT·Tài liệu)", icon: <FileUp className="size-3.5" /> },
      ];

  return (
    <div className="space-y-4 max-w-5xl">
      <div className="flex items-center gap-2">
        <GraduationCap className="size-5 text-amber-600" />
        <div>
          <h1 className="text-base font-semibold">Lớp học · Giáo viên</h1>
          <p className="text-[11px] text-muted-foreground">
            Văn chữ + lời nói (TTS) · giao bài · làm trên web · chấm sửa · theo dõi PH
          </p>
        </div>
      </div>

      {/* Bộ lọc lớp–môn–HS — tạm ẩn (SHOW_GLOBAL_FILTERS), code giữ nguyên */}
      {SHOW_GLOBAL_FILTERS && (
      <Fold id="filters" title="Bộ lọc: lớp – môn – học sinh">
        <CardContent className="pt-4 grid gap-2 sm:grid-cols-4">
          <div>
            <label className="text-[10px] text-muted-foreground">Lớp</label>
            <select
              className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
              value={grade}
              onChange={(e) => setGrade(Number(e.target.value))}
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map((g) => (
                <option key={g} value={g}>
                  Lớp {g}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground">Môn</label>
            <select
              className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            >
              {subjectsOfGrade.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground">Học sinh (id)</label>
            <Input
              className="h-9 text-xs"
              value={student}
              onChange={(e) => setStudent(e.target.value)}
              placeholder="hs1 / tên con"
            />
          </div>
          <div className="flex items-end">
            <code className="text-[10px] text-muted-foreground">
              workspace: {workspace}
              {subject === "anh" && enCefr ? ` · EN ≈ ${enCefr}` : ""}
            </code>
          </div>
          {subject === "anh" && enSkills.length > 0 && (
            <div className="sm:col-span-4 space-y-1">
              <div className="text-[10px] text-muted-foreground">
                Tiếng Anh · chọn skill / chủ đề (theo lớp {grade}):
              </div>
              <div className="flex flex-wrap gap-1">
                {enSkills.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`text-[10px] px-2 py-1 rounded-full border transition ${
                      asgTopic === s.id || lessonTopic === s.id
                        ? "border-amber-500 bg-amber-500/15"
                        : "border-border hover:bg-secondary"
                    }`}
                    onClick={() => {
                      setAsgTopic(s.id);
                      setLessonTopic(s.id);
                    }}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Fold>
      )}

      {/* Lộ trình hiện tại của HS (gắn buổi học / bài tập) */}
      {focusInfo?.ok && (
        <div className="rounded-md border border-amber-500/35 bg-amber-500/8 px-3 py-2 text-[11px] flex flex-wrap items-center gap-2 justify-between">
          <div className="space-y-0.5">
            <div className="font-semibold flex items-center gap-1">
              <Route className="size-3.5 text-amber-600" />
              Lộ trình · {student} · {subject}
            </div>
            <div>
              Đang học: <b>{focusInfo.title || focusInfo.current_focus}</b>
              {focusInfo.topic ? (
                <span className="text-muted-foreground"> · topic «{focusInfo.topic}»</span>
              ) : null}
              {typeof focusInfo.roadmap_steps_done === "number" ? (
                <span className="text-muted-foreground">
                  {" "}
                  · {focusInfo.roadmap_steps_done}/{focusInfo.roadmap_steps_total || "?"} bước
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[10px]"
              disabled={aiBusy}
              onClick={() => void aiDraftLesson(false, true)}
            >
              Soạn bài theo lộ trình
            </Button>
            <Button
              size="sm"
              className="h-7 text-[10px]"
              disabled={aiBusy || busy}
              onClick={() => void aiCreateHomework(true)}
            >
              Sinh đề theo lộ trình
            </Button>
          </div>
        </div>
      )}
      {student && focusInfo && !focusInfo.ok && (
        <p className="text-[10px] text-muted-foreground">
          Chưa có lộ trình cho {student}/{subject} — tab «Đầu vào · Lộ trình» để placement.
        </p>
      )}

      {/* Đang xem hồ sơ nào — hiện ở MỌI tab để không bao giờ soạn bài cho sai em */}
      {picked && (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/8 px-3 py-2 text-[11px] flex flex-wrap items-center gap-2">
          <UserCircle className="size-3.5 text-emerald-600 shrink-0" />
          <span>
            Đang xem <b>{picked.display_name || picked.student_key}</b>
            {picked.grade ? <> · <b>lớp {picked.grade}</b></> : <> · <span className="text-amber-600">chưa rõ lớp</span></>}
            {picked.birth_year ? <span className="text-muted-foreground"> (sinh {picked.birth_year}, lớp theo {picked.grade_source})</span> : null}
            {picked.school_year ? <span className="text-muted-foreground"> · năm học {picked.school_year}</span> : null}
          </span>
          <div className="ml-auto flex gap-1.5">
            <Button size="sm" variant="ghost" className="h-6 text-[10px]"
              onClick={() => setTab("roster")}>Đổi học sinh</Button>
            <Button size="sm" variant="ghost" className="h-6 text-[10px]"
              onClick={() => setPickedKey("")}>Bỏ chọn</Button>
          </div>
        </div>
      )}

      {/* Tầng 1: Tổng + từng học sinh. Kích tên em nào là mọi tab con đi theo lớp em đó. */}
      <div className="flex flex-wrap gap-1">
        <button type="button"
          onClick={() => { setPickedKey(""); setTab("roster"); }}
          className={`px-3 py-1.5 rounded-md text-xs transition ${!picked
            ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 font-medium"
            : "text-muted-foreground hover:bg-secondary"}`}>
          Tổng
        </button>
        {students.map((r: any) => {
          const on = picked && pickedKey === r.student_key;
          return (
            <button key={r.student_key} type="button"
              onClick={() => { setPickedKey(r.student_key); setTab("lecture"); }}
              className={`px-3 py-1.5 rounded-md text-xs transition ${on
                ? "bg-amber-500/15 text-amber-700 dark:text-amber-300 font-medium"
                : "text-muted-foreground hover:bg-secondary"}`}>
              {r.display_name || r.student_key}{r.grade ? ` · L${r.grade}` : ""}
            </button>
          );
        })}
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 border-b border-border pb-1">
        {tabs.map((t) => {
          // Khoá 4 tab bên trong khi chưa chọn hồ sơ: không biết lớp thì SGK,
          // đề và lộ trình đều không có căn cứ — mở ra chỉ để sinh nội dung sai.
          const locked = NEED_STUDENT.includes(t.id) && !picked;
          return (
          <button
            key={t.id}
            type="button"
            disabled={locked}
            title={locked ? "Chọn học sinh ở tab «Học sinh» trước" : undefined}
            onClick={() => setTab(t.id)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition ${
              locked
                ? "text-muted-foreground/40 cursor-not-allowed"
                : tab === t.id
                ? "bg-amber-500/15 text-amber-700 dark:text-amber-300 font-medium"
                : "text-muted-foreground hover:bg-secondary"
            }`}
          >
            {t.icon}
            {t.label}
            {locked && <span className="text-[9px]">🔒</span>}
          </button>
          );
        })}
      </div>

      {tab === "lecture" && picked && (
        <LectureTab student={picked as any} />
      )}
      {tab === "sgkview" && picked && (
        <SgkViewerTab student={picked as any} />
      )}

      {/* ── LESSON ── */}
      {tab === "roster" && (
        <Fold id="roster" title="Học sinh — thêm hồ sơ, lớp tự suy từ năm sinh">
          <CardContent className="pt-4 space-y-4">
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-2.5">
              <div className="text-xs font-semibold">Thêm học sinh</div>
              <div className="grid gap-2 sm:grid-cols-3">
                <div>
                  <label className="text-[10px] text-muted-foreground">Tên học sinh</label>
                  <Input className="h-9 text-xs" placeholder="Nguyễn Văn An"
                    value={newName} disabled={rosterBusy}
                    onChange={(e) => setNewName(e.target.value)} />
                </div>
                <div>
                  <label className="text-[10px] text-muted-foreground">Năm sinh</label>
                  <Input className="h-9 text-xs" placeholder="2019" inputMode="numeric"
                    value={newBirth} disabled={rosterBusy}
                    onChange={(e) => setNewBirth(e.target.value.replace(/[^0-9]/g, "").slice(0, 4))} />
                </div>
                <div>
                  <label className="text-[10px] text-muted-foreground">Lớp (chỉ khi cần khai tay)</label>
                  <Input className="h-9 text-xs" placeholder="để trống = tự suy" inputMode="numeric"
                    value={newOverride} disabled={rosterBusy}
                    onChange={(e) => setNewOverride(e.target.value.replace(/[^0-9]/g, "").slice(0, 2))} />
                </div>
              </div>
              {newBirth.length === 4 && !newOverride && (
                <p className="text-[11px] text-amber-700 dark:text-amber-300">
                  Năm học {schoolYear || "hiện tại"} → sẽ vào <b>lớp{" "}
                  {(() => {
                    const sy = Number((schoolYear || "").split("–")[0]) || new Date().getFullYear();
                    const g = sy - Number(newBirth) - 5;
                    return g >= 1 && g <= 12 ? g : "?";
                  })()}</b>
                  {(() => {
                    const sy = Number((schoolYear || "").split("–")[0]) || new Date().getFullYear();
                    const g = sy - Number(newBirth) - 5;
                    return g >= 1 && g <= 12 ? "" : " — ngoài lớp 1–12, hãy khai lớp tay";
                  })()}
                </p>
              )}
              <Button size="sm" className="h-8 text-xs" disabled={rosterBusy}
                onClick={() => void addStudent()}>
                {rosterBusy ? <LoaderCircle className="size-3.5 mr-1.5 animate-spin" /> : null}
                Thêm học sinh
              </Button>
              <p className="text-[10px] text-muted-foreground">
                Chỉ cần <b>tên + năm sinh</b>. Lớp tính theo công thức
                <code> lớp = năm học − năm sinh − 5</code> (VN vào lớp 1 lúc 6 tuổi), nên
                sang tháng 8 mọi hồ sơ <b>tự lên lớp</b>, không phải sửa tay.
                Ô lớp khai tay chỉ dùng khi học lại, học vượt hay vào lớp 1 muộn.
              </p>
            </div>

            <div className="space-y-1.5">
              <div className="text-xs font-semibold flex items-center gap-2 flex-wrap">
                Hồ sơ đã có ({students.length})
                {schoolYear && <span className="font-normal text-muted-foreground">· năm học {schoolYear}</span>}
              </div>
              {students.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  Chưa có hồ sơ nào. Thêm ở khung trên — mỗi học sinh độc lập, nhưng
                  cùng dùng chung <b>Kho SGK</b>.
                </p>
              ) : (students as StudentRow[]).map((r) => {
                const on = r.student_key === pickedKey;
                return (
                  <div key={r.student_key}
                    className={`rounded-lg border px-3 py-2 ${on
                      ? "border-amber-500 bg-amber-500/10"
                      : "border-border/60 hover:bg-secondary/50"}`}>
                    <div className="flex items-center gap-2 flex-wrap">
                      <button type="button" className="text-sm font-medium text-left hover:underline"
                        onClick={() => setPickedKey(on ? "" : r.student_key)}>
                        {r.display_name || r.student_key}
                      </button>
                      {r.grade ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 font-medium">
                          Lớp {r.grade}
                        </span>
                      ) : (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-600 font-medium">
                          chưa rõ lớp
                        </span>
                      )}
                      <span className="text-[10px] text-muted-foreground">
                        {r.birth_year ? `sinh ${r.birth_year}` : "chưa có năm sinh"}
                        {r.age ? ` · ${r.age} tuổi` : ""}
                        {r.grade_source ? ` · lớp theo ${r.grade_source}` : ""}
                      </span>
                      {on && <span className="text-[10px] font-semibold text-amber-600">◀ đang xem</span>}
                      <div className="ml-auto flex items-center gap-1.5">
                        <Input className="h-7 w-16 text-[11px]" placeholder="năm sinh"
                          defaultValue={r.birth_year ? String(r.birth_year) : ""}
                          onBlur={(e) => {
                            const v = e.target.value.replace(/[^0-9]/g, "").slice(0, 4);
                            if (v !== String(r.birth_year || "")) {
                              void patchStudent(r.student_key, { birth_year: v ? Number(v) : null });
                            }
                          }} />
                        <Input className="h-7 w-14 text-[11px]" placeholder="lớp"
                          defaultValue={r.grade_override ? String(r.grade_override) : ""}
                          onBlur={(e) => {
                            const v = e.target.value.replace(/[^0-9]/g, "").slice(0, 2);
                            if (v !== String(r.grade_override || "")) {
                              void patchStudent(r.student_key, { grade: v ? Number(v) : null });
                            }
                          }} />
                        <Button size="sm" variant="ghost" className="h-7 px-1.5 text-red-500"
                          onClick={() => void removeStudent(r)} title="Xoá hồ sơ">
                          <Trash2 className="size-3.5" />
                        </Button>
                      </div>
                    </div>
                    {on && (
                      <p className="mt-1 text-[10px] text-muted-foreground">
                        Bốn tab Bài giảng · Bài tập · Đầu vào · Dashboard PH giờ chạy theo
                        lớp {r.grade || "?"} của em này. Ô «lớp» bên phải để trống = tự suy từ năm sinh.
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Fold>
      )}

      {tab === "lesson" && (
        <div className="grid gap-4 lg:grid-cols-5">
          <Fold id="lesson-edit" title="Soạn bài giảng" className="lg:col-span-3">
            <CardContent className="pt-4 space-y-3">
              <div className="text-xs font-semibold">Soạn bài giảng (văn chữ + lời nói)</div>
              <div className="rounded border border-amber-500/25 bg-amber-500/5 p-2 space-y-2">
                <div className="text-[10px] font-semibold flex items-center gap-1">
                  <Sparkles className="size-3 text-amber-600" /> AI soạn bài
                </div>
                <Input
                  className="h-8 text-xs"
                  placeholder="Chủ đề AI (vd: trừ có mượn, chính tả hỏi ngã, animals)"
                  value={lessonTopic}
                  onChange={(e) => setLessonTopic(e.target.value)}
                />
                <Input
                  className="h-8 text-xs"
                  placeholder="Ghi chú thêm cho AI (tuỳ chọn): HS còn yếu mượn, thích ví dụ kẹo…"
                  value={lessonNotes}
                  onChange={(e) => setLessonNotes(e.target.value)}
                />
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={aiBusy}
                    onClick={() => void aiDraftLesson(false)}
                  >
                    <Sparkles className="size-3.5 mr-1" />
                    {aiBusy ? "AI đang soạn…" : "AI soạn vào form"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={aiBusy}
                    onClick={() => void aiDraftLesson(true)}
                  >
                    AI soạn + lưu luôn
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={aiBusy || !focusInfo?.ok}
                    onClick={() => void aiDraftLesson(false, true)}
                    title="Lấy current_focus từ lộ trình HS"
                  >
                    <Route className="size-3.5 mr-1" /> Theo lộ trình
                  </Button>
                </div>
              </div>
              <Input
                className="h-9 text-xs"
                placeholder="Tiêu đề bài"
                value={lessonTitle}
                onChange={(e) => setLessonTitle(e.target.value)}
              />
              <div>
                <label className="text-[10px] text-muted-foreground">
                  Nội dung cho học sinh đọc (văn chữ)
                </label>
                <textarea
                  className="w-full min-h-[160px] rounded-md border border-border bg-background px-2 py-1.5 text-xs"
                  value={lessonBody}
                  onChange={(e) => setLessonBody(e.target.value)}
                  placeholder="Viết bài giảng rõ ràng, từng bước… hoặc bấm AI soạn"
                />
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">
                  Kịch bản đọc loa / TTS (câu ngắn, không ký hiệu ×÷=)
                </label>
                <textarea
                  className="w-full min-h-[80px] rounded-md border border-border bg-background px-2 py-1.5 text-xs"
                  value={lessonTts}
                  onChange={(e) => setLessonTts(e.target.value)}
                  placeholder="Để trống = hệ thống rút từ nội dung. Ví dụ: Hôm nay học phép trừ có mượn…"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={busy} onClick={() => void saveLesson()}>
                  <Save className="size-3.5 mr-1" /> Lưu bài giảng
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void previewTts(lessonTts || lessonBody.slice(0, 400))
                  }
                >
                  <Volume2 className="size-3.5 mr-1" /> Nghe thử TTS
                </Button>
              </div>
            </CardContent>
          </Fold>
          <Fold id="lesson-saved" title="Bài đã lưu" className="lg:col-span-2">
            <CardContent className="pt-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold">Bài đã lưu</span>
                <Button size="sm" variant="ghost" className="h-7" onClick={() => void loadLessons()}>
                  <RefreshCw className="size-3" />
                </Button>
              </div>
              <div className="max-h-[360px] overflow-y-auto space-y-1.5 text-[11px]">
                {lessons.length === 0 && (
                  <p className="text-muted-foreground italic">Chưa có bài giảng.</p>
                )}
                {lessons.map((l) => (
                  <div
                    key={l.id}
                    className="flex gap-1 rounded border border-border/70 p-2 hover:bg-secondary/50"
                  >
                    <button
                      type="button"
                      className="flex-1 text-left min-w-0"
                      onClick={async () => {
                        // Chỉ set activeLesson (khối "Đang xem / HS đọc" bên dưới) —
                        // KHÔNG ghi đè lessonTitle/Body/Tts vì đó là state của form soạn
                        // bài đang dở; ghi đè sẽ làm mất bản nháp chưa lưu của giáo viên.
                        const r = await request.get(`/api/teacher/lessons/${l.id}`);
                        const full = (r.data as { lesson?: Lesson })?.lesson;
                        setActiveLesson(full || null);
                      }}
                    >
                      <div className="font-medium truncate">{l.title}</div>
                      <div className="text-muted-foreground">
                        Lớp {l.grade} · {l.subject} · {l.created}
                      </div>
                    </button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0 text-destructive shrink-0"
                      title="Xóa bài giảng"
                      onClick={() => setDeletingLesson(l)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
              {activeLesson && (
                <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2 space-y-1">
                  <div className="text-[10px] font-semibold">Đang xem / HS đọc</div>
                  <div className="text-xs font-medium">{activeLesson.title}</div>
                  <div className="text-[11px] whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {activeLesson.body_text}
                  </div>
                  {activeLesson.tts_script && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-[10px]"
                      onClick={() => void previewTts(activeLesson.tts_script)}
                    >
                      <PlayCircle className="size-3 mr-1" /> Đọc bài
                    </Button>
                  )}
                </div>
              )}
            </CardContent>
          </Fold>
        </div>
      )}

      {/* ── HOMEWORK ── */}
      {tab === "homework" && (
        <div
          className={
            hwFullscreen
              ? "fixed inset-0 z-50 bg-background p-4 overflow-y-auto"
              : "grid gap-4 lg:grid-cols-5"
          }
        >
          {!hwFullscreen && (
          <Fold id="hw-new" title="Giao bài tập mới" className="lg:col-span-2">
            <CardContent className="pt-4 space-y-2">
              <div className="text-xs font-semibold">Giao bài tập mới</div>
              <p className="text-[10px] text-muted-foreground">
                Generator bài thật · hoặc <b>AI soạn đề</b> (LLM) · adaptive sau 3 đúng/sai
              </p>
              <Input
                className="h-8 text-xs"
                placeholder="Tiêu đề bài tập"
                value={asgTitle}
                onChange={(e) => setAsgTitle(e.target.value)}
              />
              {asgToc.length > 0 && (
                <select className="w-full h-8 rounded-md border border-border bg-background px-2 text-xs"
                  value="" onChange={(e) => { if (e.target.value) setAsgTopic(e.target.value); }}>
                  <option value="">— chọn bài theo mục lục SGK ({asgToc.length} bài) —</option>
                  {asgToc.map((r, i) => (
                    <option key={i} value={`${r.bai ? r.bai + " " : ""}${r.ten}`}>
                      {r.bai ? `${r.bai} · ` : ""}{r.ten}{r.trang ? ` (tr.${r.trang})` : ""}
                    </option>
                  ))}
                </select>
              )}
              <Input
                className="h-8 text-xs"
                placeholder="Chủ đề (vd trừ có mượn · chính tả · animals)"
                value={asgTopic}
                onChange={(e) => setAsgTopic(e.target.value)}
              />
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-muted-foreground">Số câu</label>
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    className="h-8 text-xs"
                    value={asgN}
                    onChange={(e) => setAsgN(Number(e.target.value) || 5)}
                  />
                </div>
                <div>
                  <label className="text-[10px] text-muted-foreground">Độ khó</label>
                  <select
                    className="w-full h-8 rounded-md border border-border bg-background px-2 text-xs"
                    value={asgDiff}
                    onChange={(e) => setAsgDiff(e.target.value)}
                  >
                    <option value="auto">Auto (adaptive)</option>
                    <option value="easy">Dễ</option>
                    <option value="medium">Vừa</option>
                    <option value="hard">Khó</option>
                  </select>
                </div>
              </div>
              <Button
                size="sm"
                disabled={aiBusy}
                className="w-full"
                variant="default"
                onClick={() => void aiCreateHomework(!!focusInfo?.ok && !asgTopic.trim())}
              >
                <Sparkles className="size-3.5 mr-1" />
                {aiBusy
                  ? "AI đang soạn đề…"
                  : asgTopic.trim()
                    ? "AI soạn đề + giao + mở làm"
                    : focusInfo?.ok
                      ? "AI soạn theo lộ trình + giao"
                      : "AI soạn đề + giao + mở làm"}
              </Button>
              <Button
                size="sm"
                disabled={aiBusy || !focusInfo?.ok}
                className="w-full"
                variant="secondary"
                onClick={() => void aiCreateHomework(true)}
              >
                <Route className="size-3.5 mr-1" /> Sinh đề theo current_focus
              </Button>
              <Button
                size="sm"
                disabled={busy}
                className="w-full"
                variant="outline"
                onClick={() => void createHomework(!asgTopic.trim() && !!focusInfo?.ok)}
              >
                <Send className="size-3.5 mr-1" /> Giao nhanh (generator, không AI)
              </Button>

              <div className="border-t border-border pt-2 mt-2">
                <div className="text-[10px] font-semibold mb-1">Bài đã giao</div>
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {assignments.map((a) => (
                    <div
                      key={a.id}
                      className="flex items-center gap-1 text-[10px] border border-border/60 rounded p-1.5"
                    >
                      <button
                        type="button"
                        className="flex-1 text-left hover:underline min-w-0"
                        onClick={() => void openHomework(a.id, true)}
                      >
                        <div className="font-medium truncate">{a.title}</div>
                        <div className="text-muted-foreground">
                          {a.n_questions} câu · {a.difficulty} · {a.created}
                        </div>
                      </button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-[10px] shrink-0"
                        onClick={() => void openHomework(a.id, false)}
                      >
                        Nộp
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 text-destructive shrink-0"
                        title="Xóa bài tập"
                        onClick={() => void deleteAssignment(a.id)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Fold>
          )}

          <Fold id="hw-do" title="Làm bài · chấm bài" className={hwFullscreen ? "max-w-4xl mx-auto w-full" : "lg:col-span-3"}>
            <CardContent className="pt-4 space-y-3">
              {!doAsg && (
                <p className="text-xs text-muted-foreground italic">
                  Chọn bài tập bên trái hoặc bấm «AI soạn đề + giao» để HS làm trên web.
                </p>
              )}
              {doAsg && (
                <>
                  <div className="flex items-start justify-between gap-2">
                    <div className="text-sm font-semibold">
                      Làm bài: {doAsg.title}{" "}
                      <span className="font-normal text-muted-foreground text-xs">
                        · HS: {student} · {doAsg.difficulty || ""}
                      </span>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8"
                        onClick={() => setHwFullscreen((v) => !v)}
                        title={hwFullscreen ? "Thu nhỏ" : "Toàn màn hình"}
                      >
                        {hwFullscreen ? (
                          <>
                            <Minimize2 className="size-3.5 mr-1" /> Thu nhỏ
                          </>
                        ) : (
                          <>
                            <Maximize2 className="size-3.5 mr-1" /> Toàn màn hình
                          </>
                        )}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 text-destructive"
                        onClick={() => void deleteAssignment(doAsg.id)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </div>
                  {(doAsg.questions || []).map((q) => (
                    <div
                      key={q.id}
                      className={`rounded border border-border p-3 space-y-2 ${
                        hwFullscreen ? "text-base" : ""
                      }`}
                    >
                      <div
                        className={`font-medium whitespace-pre-wrap ${
                          hwFullscreen ? "text-sm" : "text-[11px]"
                        }`}
                      >
                        {q.id}. {q.prompt}
                      </div>
                      <textarea
                        className={`w-full rounded-md border border-border bg-background px-3 py-2 ${
                          hwFullscreen ? "min-h-[100px] text-base" : "min-h-[60px] text-xs"
                        }`}
                        value={answers[q.id] || ""}
                        onChange={(e) =>
                          setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                        }
                        placeholder="Viết câu trả lời / phép tính…"
                      />
                    </div>
                  ))}
                  <Button
                    size={hwFullscreen ? "default" : "sm"}
                    disabled={busy}
                    className={hwFullscreen ? "w-full h-12 text-base" : ""}
                    onClick={() => void submitHomework()}
                  >
                    <Send className="size-3.5 mr-1" /> Nộp bài &amp; chấm
                  </Button>

                  {result && (
                    <div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-3 space-y-2 text-xs">
                      <div className="font-semibold">
                        Kết quả: {result.average_0_10}/10 ({result.percent}%) · adaptive →{" "}
                        {result.adaptive_level}
                      </div>
                      <p className="text-muted-foreground">{result.summary}</p>
                      {result.roadmap_update?.message && (
                        <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2 text-[10px]">
                          <div className="font-semibold flex items-center gap-1">
                            <Route className="size-3" /> Lộ trình đã cập nhật
                          </div>
                          <div>{result.roadmap_update.message}</div>
                          {result.roadmap_update.new_focus ? (
                            <div className="text-muted-foreground mt-0.5">
                              Focus mới: <b>{result.roadmap_update.new_focus}</b>
                              {result.roadmap_update.old_focus &&
                              result.roadmap_update.old_focus !== result.roadmap_update.new_focus
                                ? ` (trước: ${result.roadmap_update.old_focus})`
                                : ""}
                            </div>
                          ) : null}
                        </div>
                      )}
                      {(result.details || []).map((d: any) => (
                        <div key={d.id} className="border-t border-border/50 pt-1.5">
                          <div>
                            <b>{d.id}</b>: {d.score_0_10}/10
                            {d.band?.band ? ` · ${d.band.band}` : ""}
                            {d.praise ? ` — ${d.praise}` : ""}
                          </div>
                          <div className="text-muted-foreground">{d.feedback}</div>
                          {(d.fixes || []).map((f: string, i: number) => (
                            <div key={i} className="text-amber-700 dark:text-amber-300">
                              · Sửa: {f}
                            </div>
                          ))}
                          {d.next_step && (
                            <div className="text-[10px]">Bước tiếp: {d.next_step}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {subs.length > 0 && (
                    <div className="text-[11px] space-y-1">
                      <div className="font-semibold">Bài đã nộp</div>
                      {subs.map((s) => (
                        <div key={s.student_key}>
                          {s.student_key}: {s.average_0_10}/10 · {s.submitted}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Fold>
        </div>
      )}

      {/* ── PLACEMENT + ROADMAP ── */}
      {tab === "placement" && (
        <div className="grid gap-4 lg:grid-cols-5">
          <Fold id="place-student" title="Học sinh (hồ sơ độc lập)" className="lg:col-span-2">
            <CardContent className="pt-4 space-y-3">
              <div className="text-xs font-semibold flex items-center gap-1">
                <UserCircle className="size-3.5" /> Học sinh (hồ sơ độc lập)
              </div>
              <p className="text-[10px] text-muted-foreground">
                Mỗi HS có profile + placement + lộ trình riêng (Toán / Văn / Anh),
                không lẫn với HS khác. Lưu tại{" "}
                <code>data/agent/teacher/students/&lt;id&gt;/</code>
              </p>
              <Input
                className="h-8 text-xs"
                placeholder="ID học sinh"
                value={student}
                onChange={(e) => setStudent(e.target.value)}
              />
              <div className="text-[10px] text-muted-foreground">
                Lớp {grade} · môn {subject} · workspace gợi ý {workspace}
              </div>
              <Button size="sm" className="w-full" disabled={busy} onClick={() => void startPlacement()}>
                <Route className="size-3.5 mr-1" />
                {busy ? "Đang tạo đề…" : "Làm test đầu vào (diagnostic)"}
              </Button>
              <Button size="sm" variant="outline" className="w-full" onClick={() => void loadRoadmap()}>
                Tải lộ trình đã lưu
              </Button>
              <div className="border-t border-border pt-2">
                <div className="text-[10px] font-semibold mb-1">Danh sách HS</div>
                <div className="max-h-40 overflow-y-auto space-y-1 text-[10px]">
                  {students.length === 0 && (
                    <p className="text-muted-foreground italic">Chưa có HS — làm placement để tạo.</p>
                  )}
                  {students.map((s) => (
                    <div
                      key={s.student_key}
                      className="flex items-stretch gap-1 rounded border border-border/60 p-1.5"
                    >
                      <button
                        type="button"
                        className="flex-1 min-w-0 text-left hover:bg-secondary/40 rounded px-0.5"
                        onClick={() => {
                          setStudent(s.student_key);
                          if (s.grade) setGrade(Number(s.grade));
                          void loadRoadmap();
                          void loadFocus();
                        }}
                      >
                        <div className="font-medium truncate">
                          {s.display_name || s.student_key}
                        </div>
                        <div className="text-muted-foreground">
                          Lớp {s.grade || "?"} · placement:{" "}
                          {(s.placements || []).map((p: any) => p.subject).join(", ") || "—"}
                        </div>
                      </button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 shrink-0 text-destructive hover:text-destructive"
                        title={`Xóa ${s.display_name || s.student_key}`}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          void deleteStudent(s.student_key, s.display_name || s.student_key);
                        }}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded bg-muted/30 p-2 text-[9px] text-muted-foreground space-y-1">
                <div className="font-semibold text-[10px]">Cách GV dạy (rút gọn)</div>
                <div>· <b>Toán</b>: chẩn đoán theo mảng (cộng/trừ/nhân…) → ôn mảng yếu trước (mastery).</div>
                <div>· <b>Văn</b>: chính tả → dấu câu → đọc → viết đoạn.</div>
                <div>· <b>Anh</b>: 5 skill CEFR (grammar/listen/speak/read/write) → skill yếu trước.</div>
              </div>
            </CardContent>
          </Fold>

          <Fold id="place-test" title="Đề đầu vào · Lộ trình" className="lg:col-span-3">
            <CardContent className="pt-4 space-y-3">
              {placeQs.length > 0 && (
                <>
                  <div className="text-xs font-semibold">Đề đầu vào · {placeId}</div>
                  {placeInfo && (
                    <p className="text-[11px] text-muted-foreground whitespace-pre-wrap">{placeInfo}</p>
                  )}
                  {placeQs.map((q) => (
                    <div key={q.id} className="rounded border border-border p-2 space-y-1">
                      <div className="text-[10px] text-amber-700 dark:text-amber-300">
                        {q.strand_label || q.strand_id}
                      </div>
                      <div className="text-[11px] font-medium whitespace-pre-wrap">
                        {q.id}. {q.prompt}
                      </div>
                      <textarea
                        className="w-full min-h-[56px] rounded-md border border-border bg-background px-2 py-1 text-xs"
                        value={placeAnswers[q.id] || ""}
                        onChange={(e) =>
                          setPlaceAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                        }
                        placeholder="Câu trả lời…"
                      />
                    </div>
                  ))}
                  <Button size="sm" disabled={busy} onClick={() => void submitPlacement()}>
                    Nộp test đầu vào → tạo lộ trình
                  </Button>
                </>
              )}

              {placeResult && (
                <div className="rounded border border-emerald-500/30 bg-emerald-500/5 p-3 space-y-2 text-xs">
                  <div className="font-semibold">
                    Kết quả đầu vào · {placeResult.subject} · {placeResult.score_pct}% ·{" "}
                    {placeResult.level_label}
                  </div>
                  <p className="text-muted-foreground">{placeResult.summary}</p>
                  <div className="grid gap-1 sm:grid-cols-2">
                    {(placeResult.strand_scores || []).map((s: any) => (
                      <div
                        key={s.strand_id}
                        className={`rounded border p-1.5 text-[10px] ${
                          s.mastered
                            ? "border-emerald-500/40"
                            : "border-amber-500/40"
                        }`}
                      >
                        <b>{s.label}</b>: {s.score_0_10}/10
                        {s.mastered ? " ✓" : " → ưu tiên"}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {roadmap && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold flex items-center gap-1">
                    <Route className="size-3.5" /> Lộ trình · {roadmap.subject} · lớp{" "}
                    {roadmap.grade}
                  </div>
                  <p className="text-[10px] text-muted-foreground">{roadmap.method}</p>
                  <p className="text-[11px]">
                    Đang học: <b>{roadmap.current_focus}</b> ({roadmap.steps_done}/
                    {(roadmap.steps || []).length} bước)
                  </p>
                  <div className="space-y-1.5 max-h-[360px] overflow-y-auto">
                    {(roadmap.steps || []).map((s: any) => (
                      <div
                        key={s.id}
                        className={`rounded border p-2 text-[11px] ${
                          s.status === "done"
                            ? "opacity-60 border-border"
                            : s.priority === "high"
                              ? "border-amber-500/50 bg-amber-500/5"
                              : "border-border"
                        }`}
                      >
                        <div className="flex justify-between gap-2">
                          <div>
                            <span className="text-[9px] uppercase text-muted-foreground">
                              {s.phase} · {s.priority || "normal"}
                            </span>
                            <div className="font-medium">{s.title}</div>
                            <div className="text-muted-foreground text-[10px]">
                              {s.description}
                            </div>
                            {s.session_recipe ? (
                              <div className="text-[9px] text-muted-foreground mt-0.5">
                                Buổi học: {s.session_recipe}
                              </div>
                            ) : null}
                            {s.estimated_sessions ? (
                              <div className="text-[9px]">≈ {s.estimated_sessions} buổi</div>
                            ) : null}
                          </div>
                          {s.status !== "done" && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 text-[10px] shrink-0"
                              onClick={() => void markStepDone(s.id)}
                            >
                              Xong
                            </Button>
                          )}
                          {s.status === "done" && (
                            <span className="text-[10px] text-emerald-600 shrink-0">✓</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {!placeQs.length && !placeResult && !roadmap && (
                <p className="text-xs text-muted-foreground italic">
                  Bấm «Làm test đầu vào» để chẩn đoán theo mảng kiến thức / 5 skill Anh,
                  rồi hệ thống tạo lộ trình riêng cho học sinh này.
                </p>
              )}
            </CardContent>
          </Fold>
        </div>
      )}

      {/* ── PARENT DASHBOARD ── */}
      {tab === "parent" && (
        <Fold id="parent" title="Dashboard phụ huynh">
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold">Dashboard phụ huynh</div>
                <p className="text-[10px] text-muted-foreground">
                  Hồ sơ HS · lộ trình · điểm yếu tuần · adaptive · workspace {workspace}
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={() => void loadDashboard()}>
                <RefreshCw className="size-3.5 mr-1" /> Tải lại
              </Button>
            </div>
            {dashWeeks.length > 0 && (
              <div className="text-[10px] text-muted-foreground">
                Tuần: {dashWeeks.join(" · ")}
              </div>
            )}
            {dash.length === 0 && (
              <p className="text-xs text-muted-foreground italic">
                Chưa có HS. Placement (tab Đầu vào) hoặc cho làm bài tập để ghi nhận.
              </p>
            )}
            <div className="space-y-3">
              {dash.map((s) => (
                <div
                  key={`${s.workspace_id}-${s.student_key}`}
                  className="rounded border border-border p-3 text-xs space-y-1.5"
                >
                  <div className="font-semibold">
                    {s.display_name || s.student_key}{" "}
                    <span className="font-normal text-muted-foreground">
                      · id {s.student_key}
                      {s.grade ? ` · lớp ${s.grade}` : ""}
                      · {s.workspace_id} · adaptive: {s.adaptive_level || "?"}
                      {typeof s.streak_correct === "number"
                        ? ` · streak đúng ${s.streak_correct}/sai ${s.streak_wrong}`
                        : ""}
                    </span>
                  </div>
                  {s.path && Object.keys(s.path).length > 0 && (
                    <div className="rounded bg-muted/40 p-2 space-y-1.5">
                      <div className="text-[10px] font-semibold flex items-center gap-1">
                        <Route className="size-3" /> Lộ trình theo môn
                      </div>
                      {Object.entries(s.path).map(([sub, p]) => (
                        <div key={sub} className="text-[10px] border-t border-border/30 pt-1">
                          <b className="uppercase">{sub}</b>
                          {p.level_label ? ` · ${p.level_label}` : ""}
                          {typeof p.score_pct === "number" ? ` · đầu vào ${p.score_pct}%` : ""}
                          <div>
                            Focus: <b>{p.current_focus || "—"}</b>
                            {typeof p.steps_total === "number" && p.steps_total > 0
                              ? ` (${p.steps_done || 0}/${p.steps_total})`
                              : ""}
                          </div>
                          {p.last_practice?.message ? (
                            <div className="text-muted-foreground">
                              Sau bài gần nhất: {p.last_practice.message}
                            </div>
                          ) : null}
                          {!!(p.weak_strands && p.weak_strands.length) && (
                            <div className="text-amber-700 dark:text-amber-300">
                              Mảng yếu: {p.weak_strands.join(" · ")}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {!!(s.weak_topics && s.weak_topics.length) && (
                    <div>
                      <span className="text-amber-700 dark:text-amber-300">Điểm yếu memory: </span>
                      {s.weak_topics.join(" · ")}
                    </div>
                  )}
                  {!!(s.strong_topics && s.strong_topics.length) && (
                    <div>
                      <span className="text-emerald-700 dark:text-emerald-300">Đã vững: </span>
                      {s.strong_topics.join(" · ")}
                    </div>
                  )}
                  {(s.weekly || []).map((w) => (
                    <div key={w.week} className="text-[11px] border-t border-border/40 pt-1">
                      <b>{w.week}</b>: {(w.weak_topics || []).join(" · ") || "—"}
                    </div>
                  ))}
                  {!s.weekly?.length && !s.path && (
                    <div className="text-[10px] text-muted-foreground">
                      Chưa có bucket tuần (sẽ có sau khi chấm bài yếu).
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Fold>
      )}

      {/* ── IMPORT SGK ── */}
      {tab === "import" && (
        <Fold id="import" title="Import PDF SGK">
          <CardContent className="pt-4 space-y-3">
            {SHOW_AUTOFILL && <AutofillPanel />}
            <BulkSgkPanel />
            <div className="text-xs font-semibold flex items-center gap-1.5">
              <FileUp className="size-3.5 text-amber-600" />
              Import SGK theo chương / bài
            </div>
            <p className="text-[10px] text-muted-foreground">
              Nội dung được tách heading <code>## Chương/Bài/Unit…</code> để search từng mục.
              Đích: lớp <b>{grade}</b> · <b>{subject}</b> → workspace <code>{workspace}</code>
            </p>

            {/* Chọn đích ngay tại đây — bộ lọc chung ở đầu trang đang tạm ẩn,
                không có ô này thì không chọn được nạp vào lớp–môn nào. */}
            <div className="grid gap-2 sm:grid-cols-3">
              <div>
                <label className="text-[10px] text-muted-foreground">Lớp</label>
                <select
                  className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
                  value={grade}
                  disabled={impBusy || impUrlBusy}
                  onChange={(e) => setGrade(Number(e.target.value))}
                >
                  {GRADES.map((g) => (
                    <option key={g} value={g}>Lớp {g}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Môn</label>
                <select
                  className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
                  value={subject}
                  disabled={impBusy || impUrlBusy}
                  onChange={(e) => setSubject(e.target.value)}
                >
                  {subjectsOfGrade.map((s) => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Chế độ</label>
                <select
                  className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
                  value={impMode}
                  onChange={(e) => setImpMode(e.target.value as "append" | "replace")}
                  disabled={impBusy || impUrlBusy}
                >
                  <option value="append">Nối thêm (giữ seed)</option>
                  <option value="replace">Ghi đè file lớp–môn</option>
                </select>
              </div>
            </div>

            {/* ── Nạp từ URL ────────────────────────────────────────────── */}
            <div className="rounded-lg border border-sky-500/40 bg-sky-500/5 p-3 space-y-2">
              <div className="text-[11px] font-semibold flex items-center gap-1.5">
                <Link2 className="size-3.5 text-sky-600" />
                Nạp bằng đường dẫn
              </div>
              <div className="flex flex-col sm:flex-row gap-2">
                <Input
                  className="h-9 text-xs flex-1"
                  placeholder="https://taphuan.nxbgd.vn/tap-huan/chi-tiet-sach/… hoặc link .pdf"
                  value={impUrl}
                  disabled={impUrlBusy || impBusy}
                  onChange={(e) => setImpUrl(e.target.value)}
                />
                <Button
                  type="button"
                  className="h-9 px-4 text-xs font-semibold bg-sky-600 hover:bg-sky-500 text-white"
                  disabled={impUrlBusy || impBusy || !impUrl.trim()}
                  onClick={async () => {
                    const url = impUrl.trim();
                    // Kiểm y như backend (`url.startswith(("http://","https://"))`)
                    // để lỗi hiện ngay tại đây thay vì đi một vòng rồi mới báo.
                    const low = url.toLowerCase();
                    if (!low.startsWith("http://") && !low.startsWith("https://")) {
                      toast.error("URL phải bắt đầu bằng http:// hoặc https://");
                      return;
                    }
                    setImpUrlBusy(true);
                    toast.message("Đang nạp từ URL — sách nhiều trang có thể mất hàng chục phút…");
                    try {
                      const r = await request.post(
                        "/api/teacher/import-url",
                        { url, grade, subject, mode: impMode },
                        { timeout: 0 },
                      );
                      const d = r.data as {
                        ok?: boolean; error?: string; chars?: number;
                        chapters?: number; workspace?: string;
                        rag?: { ok?: boolean; chunks_added?: number; error?: string };
                      };
                      if (d?.ok === false) throw new Error(d.error || "nạp URL thất bại");
                      const ragMsg = d.rag?.ok
                        ? ` · RAG +${d.rag.chunks_added ?? 0} chunks`
                        : d.rag ? ` · RAG lỗi: ${d.rag.error || "thất bại"}` : "";
                      toast.success(
                        `Nạp URL OK · ${d.chars ?? "?"} ký tự · ${d.chapters ?? "?"} mục → ${d.workspace ?? workspace}${ragMsg}`,
                      );
                      setImpUrl("");
                      void loadImports();
                      void loadSgkAll();
                    } catch (err: unknown) {
                      const msg = err instanceof Error ? err.message : String(err || "lỗi");
                      // Mất kết nối KHÔNG có nghĩa là nạp thất bại: server vẫn
                      // chạy tiếp và ghi ra đĩa. Nói rõ để không nạp lại lần 2.
                      toast.error(
                        `Nạp URL lỗi: ${msg}. Nếu là timeout/mất mạng thì server có thể VẪN đang nạp — bấm «Làm mới» sau ít phút để kiểm tra trước khi thử lại.`,
                      );
                    } finally {
                      setImpUrlBusy(false);
                    }
                  }}
                >
                  {impUrlBusy ? (
                    <><LoaderCircle className="size-3.5 mr-1.5 animate-spin" />Đang nạp…</>
                  ) : (
                    <><Download className="size-3.5 mr-1.5" />Nạp từ URL</>
                  )}
                </Button>
              </div>
              <p className="text-[10px] text-muted-foreground">
                Nhận 3 dạng: link <b>chi tiết sách</b> taphuan (tự tìm link đọc), link <b>đọc sách</b> taphuan, hoặc link <b>.pdf</b> trực tiếp.
                Sách taphuan phải tải ảnh từng trang nên rất lâu; nếu mở trang qua domain thì kết nối có thể bị cắt trước khi xong — lúc đó cứ để server chạy rồi bấm «Làm mới».
              </p>
            </div>

            {/* Ẩn input native — dùng nút tự thiết kế cho dễ thấy */}
            <input
              ref={impFileRef}
              type="file"
              accept="application/pdf,.pdf"
              disabled={impBusy}
              className="sr-only"
              id="teacher-sgk-pdf-input"
              onChange={async (e) => {
                const input = e.target;
                const f = input.files?.[0];
                if (!f) {
                  setImpFileName("");
                  setImpFileSize(0);
                  return;
                }
                if (!f.name.toLowerCase().endsWith(".pdf") && f.type !== "application/pdf") {
                  toast.error("Chỉ nhận file PDF");
                  input.value = "";
                  setImpFileName("");
                  setImpFileSize(0);
                  return;
                }
                setImpFileName(f.name);
                setImpFileSize(f.size);
                setImpBusy(true);
                toast.message(`Đang import «${f.name}»…`);
                try {
                  const fd = new FormData();
                  fd.append("file", f);
                  fd.append("grade", String(grade));
                  fd.append("subject", subject);
                  fd.append("mode", impMode);
                  fd.append("title", f.name.replace(/\.pdf$/i, ""));
                  const r = await request.post("/api/teacher/import-sgk", fd, {
                    headers: { "Content-Type": "multipart/form-data" },
                    timeout: 600000,
                  });
                  const d = r.data as {
                    chars?: number;
                    chapters?: number;
                    workspace?: string;
                    ok?: boolean;
                    error?: string;
                    rag?: {
                      ok?: boolean;
                      chunks_added?: number;
                      batches?: number;
                      error?: string;
                    };
                  };
                  if (d?.ok === false) {
                    throw new Error(d.error || "import failed");
                  }
                  const rag = d.rag;
                  const ragMsg =
                    rag?.ok
                      ? ` · RAG +${rag.chunks_added ?? 0} chunks`
                      : rag
                        ? ` · RAG lỗi: ${rag.error || "thất bại"}`
                        : "";
                  toast.success(
                    `Import OK · ${d.chars ?? "?"} ký tự · ${d.chapters ?? "?"} mục/chương → ${d.workspace}${ragMsg}`,
                  );
                  void loadImports();
                } catch (err: unknown) {
                  const msg =
                    err instanceof Error
                      ? err.message
                      : String(err || "Import lỗi");
                  toast.error(`Import PDF lỗi: ${msg}`);
                } finally {
                  setImpBusy(false);
                  input.value = "";
                }
              }}
            />

            <div
              className={`rounded-lg border-2 border-dashed p-4 space-y-3 transition-colors ${
                impBusy
                  ? "border-amber-500/50 bg-amber-500/10"
                  : "border-amber-500/40 bg-amber-500/5 hover:bg-amber-500/10"
              }`}
              onDragOver={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                if (impBusy) return;
                const f = e.dataTransfer.files?.[0];
                if (!f || !impFileRef.current) return;
                const dt = new DataTransfer();
                dt.items.add(f);
                impFileRef.current.files = dt.files;
                impFileRef.current.dispatchEvent(new Event("change", { bubbles: true }));
              }}
            >
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                <Button
                  type="button"
                  size="default"
                  disabled={impBusy}
                  className="h-11 px-5 text-sm font-semibold bg-amber-600 hover:bg-amber-500 text-white shadow-md"
                  onClick={() => impFileRef.current?.click()}
                >
                  {impBusy ? (
                    <>
                      <LoaderCircle className="size-4 mr-2 animate-spin" />
                      Đang import…
                    </>
                  ) : (
                    <>
                      <FileUp className="size-4 mr-2" />
                      Chọn file PDF SGK
                    </>
                  )}
                </Button>
                <div className="text-[11px] min-w-0 flex-1">
                  {impFileName ? (
                    <div className="flex items-start gap-1.5">
                      <FileText className="size-3.5 mt-0.5 shrink-0 text-amber-600" />
                      <div className="min-w-0">
                        <div className="font-medium truncate">{impFileName}</div>
                        <div className="text-muted-foreground text-[10px]">
                          {impFileSize > 0
                            ? `${(impFileSize / (1024 * 1024)).toFixed(1)} MB`
                            : ""}
                          {impBusy ? " · đang xử lý…" : " · đã chọn"}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-muted-foreground">
                      Chưa chọn tệp — bấm nút vàng, hoặc <b>kéo-thả PDF</b> vào khung này.
                    </p>
                  )}
                </div>
              </div>
              <p className="text-[10px] text-muted-foreground">
                Chỉ nhận <code>.pdf</code>. Sau khi chọn, hệ thống upload ngay (file lớn /
                scan có thể vài phút — đừng đóng tab).
              </p>
            </div>

            {impBusy && (
              <div className="flex items-center gap-2 text-[11px] text-amber-700 dark:text-amber-300">
                <LoaderCircle className="size-3.5 animate-spin" />
                Đang trích PDF (file số nhanh; scan/OCR có thể vài phút)…
              </div>
            )}

            {/* Markdown hiện tại + danh sách PDF đã import */}
            <div className="rounded-md border border-border/60 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold">
                  Đã có trên server · lớp {grade} · {subject}
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-[10px]"
                  disabled={impListLoading || impBusy}
                  onClick={() => void loadImports()}
                >
                  {impListLoading ? (
                    <LoaderCircle className="size-3 animate-spin" />
                  ) : (
                    <RefreshCw className="size-3" />
                  )}
                  <span className="ml-1">Làm mới</span>
                </Button>
              </div>
              {impMd ? (
                <div className="text-[10px] text-muted-foreground space-y-0.5">
                  <div>
                    Markdown:{" "}
                    {impMd.exists ? (
                      <span className="text-foreground">
                        ✓ {impMd.chars.toLocaleString()} ký tự · {impMd.chapters} mục{" "}
                        <code className="text-[9px]">lop{impMd.grade}/{impMd.subject}.md</code>
                      </span>
                    ) : (
                      <span className="text-amber-600">chưa có file .md</span>
                    )}
                  </div>
                  {impMd.mtime ? (
                    <div>
                      Cập nhật:{" "}
                      {new Date(impMd.mtime * 1000).toLocaleString("vi-VN")}
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="text-[10px] text-muted-foreground">
                  {impListLoading ? "Đang tải…" : "Chưa có thông tin markdown."}
                </p>
              )}
              <div className="text-[11px] font-medium pt-1">PDF đã import</div>
              {impList.length === 0 ? (
                <p className="text-[10px] text-muted-foreground">
                  Chưa có bản PDF lưu trong{" "}
                  <code>imports/lop{grade}/{subject}/</code>. Import xong sẽ hiện ở đây.
                </p>
              ) : (
                <ul className="max-h-48 overflow-y-auto space-y-1.5 text-[10px]">
                  {impList.map((row) => (
                    <li
                      key={`${row.name}-${row.mtime}`}
                      className="flex items-start gap-1.5 rounded border border-border/40 bg-muted/20 px-2 py-1.5"
                    >
                      <FileText className="size-3 mt-0.5 shrink-0 text-amber-600" />
                      <div className="min-w-0 flex-1">
                        <div className="font-medium truncate">{row.name}</div>
                        <div className="text-muted-foreground">
                          {(row.size_bytes || 0) > 0
                            ? `${((row.size_bytes || 0) / (1024 * 1024)).toFixed(1)} MB`
                            : ""}
                          {row.mtime
                            ? ` · ${new Date(row.mtime * 1000).toLocaleString("vi-VN")}`
                            : ""}
                          {row.workspace ? ` · ${row.workspace}` : ""}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-[9px] text-muted-foreground">
                Sau convert: thông báo admin + đẩy RAG collection{" "}
                <code>kb_giao_duc</code> (chunks theo chương).
              </p>
            </div>

            {/* ── Toàn bộ SGK trên server: gom theo lớp → môn, thu hết mặc định ── */}
            <div className="rounded-md border border-border/60 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="text-[11px] font-semibold flex items-center gap-1.5">
                  <BookMarked className="size-3.5 text-amber-600" />
                  Toàn bộ SGK trên server
                  {sgkAll ? (
                    <span className="font-normal text-muted-foreground">
                      · {sgkAll.markdown.filter((m) => m.exists).length}/{sgkAll.markdown.length} tổ hợp có sách
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center gap-1.5">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-[10px]"
                    disabled={sgkLoading}
                    onClick={() =>
                      setSgkOpen((o) => (o.length ? [] : GRADES.slice()))
                    }
                  >
                    {sgkOpen.length ? "Thu hết" : "Mở hết"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-[10px]"
                    disabled={sgkLoading}
                    onClick={() => void loadSgkAll()}
                  >
                    {sgkLoading ? (
                      <LoaderCircle className="size-3 animate-spin" />
                    ) : (
                      <RefreshCw className="size-3" />
                    )}
                    <span className="ml-1">Làm mới</span>
                  </Button>
                </div>
              </div>

              {!sgkAll ? (
                <p className="text-[10px] text-muted-foreground">
                  {sgkLoading ? "Đang tải…" : "Chưa tải được danh sách."}
                </p>
              ) : (
                <div className="space-y-1">
                  {GRADES.map((g) => {
                    const rows = sgkAll.markdown.filter((m) => m.grade === g);
                    const have = rows.filter((m) => m.exists);
                    const pdfs = sgkAll.imports.filter((p) => p.grade === g);
                    const chars = have.reduce((a, m) => a + (m.chars || 0), 0);
                    const open = sgkOpen.includes(g);
                    return (
                      <div key={g} className="rounded border border-border/40">
                        <button
                          type="button"
                          className="w-full flex items-center gap-2 px-2 py-1.5 text-left hover:bg-secondary/60 transition"
                          onClick={() =>
                            setSgkOpen((o) =>
                              o.includes(g) ? o.filter((x) => x !== g) : [...o, g],
                            )
                          }
                        >
                          {open ? (
                            <ChevronUp className="size-3 shrink-0 text-muted-foreground" />
                          ) : (
                            <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
                          )}
                          <span className="text-[11px] font-medium">Lớp {g}</span>
                          <span
                            className={`text-[9px] px-1.5 py-0.5 rounded-full ${
                              have.length === rows.length && rows.length > 0
                                ? "bg-emerald-500/15 text-emerald-600"
                                : have.length > 0
                                  ? "bg-amber-500/15 text-amber-600"
                                  : "bg-muted text-muted-foreground"
                            }`}
                          >
                            {have.length}/{rows.length} môn
                          </span>
                          <span className="text-[9px] text-muted-foreground ml-auto">
                            {chars > 0 ? `${chars.toLocaleString("vi-VN")} ký tự` : "chưa có sách"}
                            {pdfs.length ? ` · ${pdfs.length} PDF` : ""}
                          </span>
                        </button>

                        {open && (
                          <div className="border-t border-border/40 px-2 py-1.5 space-y-1.5">
                            {rows.map((m) => (
                              <div
                                key={`${m.grade}-${m.subject}`}
                                className="flex items-center gap-2 text-[10px]"
                              >
                                <span className={m.exists ? "text-emerald-600" : "text-muted-foreground"}>
                                  {m.exists ? "✓" : "○"}
                                </span>
                                <span className="font-medium w-20 shrink-0">
                                  {m.subject_label || m.subject}
                                </span>
                                <span className="text-muted-foreground min-w-0 flex-1 truncate">
                                  {m.exists
                                    ? `${(m.chars || 0).toLocaleString("vi-VN")} ký tự · ${m.chapters || 0} mục${
                                        m.mtime
                                          ? ` · ${new Date(m.mtime * 1000).toLocaleDateString("vi-VN")}`
                                          : ""
                                      }`
                                    : "chưa có file .md"}
                                </span>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="ghost"
                                  className="h-6 text-[9px] px-1.5 shrink-0"
                                  disabled={impBusy || impUrlBusy}
                                  onClick={() => {
                                    setGrade(m.grade);
                                    setSubject(m.subject);
                                    toast.message(`Đích nạp → lớp ${m.grade} · ${m.subject_label || m.subject}`);
                                  }}
                                >
                                  Chọn làm đích
                                </Button>
                              </div>
                            ))}
                            {pdfs.length > 0 && (
                              <ul className="pt-1 space-y-1 border-t border-border/30">
                                {pdfs.map((p) => (
                                  <li
                                    key={`${p.name}-${p.mtime}`}
                                    className="flex items-start gap-1.5 text-[9px] text-muted-foreground"
                                  >
                                    <FileText className="size-2.5 mt-0.5 shrink-0 text-amber-600" />
                                    <span className="min-w-0 flex-1 truncate">{p.name}</span>
                                    <span className="shrink-0">{p.workspace || ""}</span>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              <p className="text-[9px] text-muted-foreground">
                Đếm theo file <code>sgk/lop&lt;N&gt;/&lt;môn&gt;.md</code> trên server. Môn khác nhau theo lớp, giữ đúng tên sách: lớp 1–5 <b>Tiếng Việt</b>, lớp 6–12 <b>Ngữ văn</b>; lớp 4–9 có <b>Lịch sử và Địa lí</b> (một quyển), lớp 10–12 tách <b>Lịch sử</b> · <b>Địa lí</b> · <b>Vật lí</b>.
              </p>
            </div>
          </CardContent>
        </Fold>
      )}

      <Dialog open={Boolean(deletingLesson)} onOpenChange={(open) => (!open ? setDeletingLesson(null) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>Xóa bài giảng</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              Bạn có chắc chắn muốn xóa bài giảng "{deletingLesson?.title}"? Hành động này không thể hoàn tác.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" className="rounded-xl" onClick={() => setDeletingLesson(null)} disabled={deletingLessonBusy}>
              Hủy
            </Button>
            <Button
              className="rounded-xl bg-rose-600 text-white hover:bg-rose-700"
              onClick={() => deletingLesson && void deleteLesson(deletingLesson.id)}
              disabled={deletingLessonBusy || !deletingLesson}
            >
              {deletingLessonBusy ? <LoaderCircle className="size-4 animate-spin" /> : null}
              Xác nhận xóa
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
