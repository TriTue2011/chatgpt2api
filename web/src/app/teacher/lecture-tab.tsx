"use client";

/* Bài giảng hai khung + trình xem SGK theo lớp của MỘT học sinh.
 *
 * Component ở MODULE SCOPE, file riêng — không định nghĩa lồng trong
 * TeacherPage: component lồng bị tạo lại mỗi render, remount cả cây con và
 * là đúng họ lỗi React #310 đã phải vá ở trang này.
 *
 * Khung phải: ảnh trang SGK qua /api/teacher/page-img/{slug}/{page}.
 * `page` của route là THỨ TỰ ẢNH (bìa = 1); số IN trên giấy = thứ tự − offset.
 * Offset do backend trả (đo thật = 1) — UI chỉ cộng, không tự đoán.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen, ChevronLeft, ChevronRight, Loader2, MessageCircleQuestion,
  Sparkles, Volume2, ZoomIn, ZoomOut,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { httpRequest } from "@/lib/request";

type Student = { student_key: string; display_name?: string; grade?: number };
type Book = { slug: string; title: string; volume?: string; pages: number; offset: number };
type Segment = { heading?: string; text: string; tts?: string; page?: number | null };
type Lecture = {
  title?: string; muc_tieu?: string; segments: Segment[];
  cau_hoi_kiem_tra?: string; subject?: string; bai?: string;
  books?: Book[]; grounded?: { sgk?: boolean; sgv?: boolean };
  created?: string;
};
type Speaker = { id: string; name: string; kind?: string };
type TocRow = { bai?: string; ten: string; trang?: number | null; tap?: string };

const SUBJECTS: { id: string; label: string }[] = [
  { id: "toan", label: "Toán" },
  { id: "tviet", label: "Tiếng Việt" },
  { id: "van", label: "Ngữ văn" },
  { id: "anh", label: "Tiếng Anh" },
  { id: "sudia", label: "Lịch sử & Địa lí" },
  { id: "su", label: "Lịch sử" },
  { id: "dia", label: "Địa lí" },
  { id: "ly", label: "Vật lí" },
  { id: "hoa", label: "Hoá học" },
  { id: "sinh", label: "Sinh học" },
];

function imgUrl(slug: string, imgIndex: number) {
  return `/api/teacher/page-img/${encodeURIComponent(slug)}/${imgIndex}`;
}

/* ── Khung xem trang sách (dùng chung cho tab Bài giảng và tab SGK) ────── */

export function PageViewer({ book, printedPage, onPrinted }: {
  book: Book | null;
  printedPage: number;                       // số trang IN đang xem
  onPrinted?: (p: number) => void;           // người dùng tự lật
}) {
  const [zoom, setZoom] = useState(1);
  const [err, setErr] = useState(false);
  useEffect(() => { setErr(false); }, [book?.slug, printedPage]);

  if (!book) {
    return (
      <div className="rounded border border-dashed border-border p-6 text-center text-xs text-muted-foreground">
        Chưa tìm thấy bản đồ trang của SGK lớp–môn này. Bài giảng vẫn dùng được
        ở khung chữ; ảnh trang sẽ có sau khi kho SGK được nạp.
      </div>
    );
  }
  const total = Math.max(1, book.pages - book.offset); // số trang in tối đa
  const p = Math.min(Math.max(1, printedPage), total);
  const idx = p + book.offset;               // thứ tự ảnh trên kho

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-[11px]">
        <BookOpen className="size-3.5 text-emerald-600 shrink-0" />
        <span className="truncate" title={book.title}>{book.title}</span>
        <span className="ml-auto whitespace-nowrap text-muted-foreground">trang {p}/{total}</span>
      </div>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="outline" className="h-7 px-2"
          disabled={p <= 1} onClick={() => onPrinted?.(p - 1)}>
          <ChevronLeft className="size-3.5" />
        </Button>
        <Button size="sm" variant="outline" className="h-7 px-2"
          disabled={p >= total} onClick={() => onPrinted?.(p + 1)}>
          <ChevronRight className="size-3.5" />
        </Button>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="outline" className="h-7 px-2"
            onClick={() => setZoom((z) => Math.max(1, +(z - 0.25).toFixed(2)))}>
            <ZoomOut className="size-3.5" />
          </Button>
          <span className="text-[10px] self-center w-9 text-center">{Math.round(zoom * 100)}%</span>
          <Button size="sm" variant="outline" className="h-7 px-2"
            onClick={() => setZoom((z) => Math.min(3, +(z + 0.25).toFixed(2)))}>
            <ZoomIn className="size-3.5" />
          </Button>
        </div>
      </div>
      <div className="rounded border border-border bg-white overflow-auto" style={{ maxHeight: "70vh" }}>
        {err ? (
          <div className="p-6 text-center text-xs text-muted-foreground">
            Không tải được ảnh trang này (kho ảnh chưa có hoặc CDN chặn).
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imgUrl(book.slug, idx)}
            alt={`Trang ${p}`}
            onError={() => setErr(true)}
            style={{ width: `${zoom * 100}%`, maxWidth: "none" }}
          />
        )}
      </div>
    </div>
  );
}

/* ── Tab BÀI GIẢNG ──────────────────────────────────────────────────────── */

export function LectureTab({ student }: { student: Student }) {
  const [subject, setSubject] = useState("toan");
  const [bai, setBai] = useState("");
  const [toc, setToc] = useState<TocRow[]>([]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [lecture, setLecture] = useState<Lecture | null>(null);
  const [active, setActive] = useState(0);            // segment đang giảng
  const [page, setPage] = useState(1);                // trang in đang hiện
  const [followPages, setFollowPages] = useState(true);

  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [speakerId, setSpeakerId] = useState("");
  const [speaking, setSpeaking] = useState(false);

  const [question, setQuestion] = useState("");
  const [askBusy, setAskBusy] = useState(false);
  const [answer, setAnswer] = useState("");
  const answerTts = useRef("");

  const books = lecture?.books || [];
  const book = books[0] || null;

  // Loa lấy từ sổ loa chung (persona/giọng đã cấu hình ở Cài đặt).
  useEffect(() => {
    (async () => {
      try {
        const r = await httpRequest<{ rows?: Speaker[] }>("/api/voice/speakers");
        const rows = r.rows || [];
        setSpeakers(rows);
        if (rows.length && !speakerId) setSpeakerId(rows[0].id);
      } catch { /* không có loa vẫn giảng được bằng chữ */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Mục lục có cấu trúc của lớp–môn: có thì chọn BÀI theo đúng sách (cả bài
  // giảng lẫn bài tập cùng nguồn này); chưa nạp thì rơi về ô gõ tay.
  useEffect(() => {
    setToc([]);
    if (!student.grade) return;
    (async () => {
      try {
        const r = await httpRequest<{ rows?: TocRow[] }>(
          `/api/teacher/lecture/toc?grade=${student.grade}&subject=${subject}`);
        setToc(r.rows || []);
      } catch { /* chưa có mục lục — dùng ô gõ tay */ }
    })();
  }, [student.grade, subject]);

  // Bài giảng gần nhất của môn này — vào tab là thấy lại, không phải soạn lại.
  useEffect(() => {
    setLecture(null); setActive(0); setAnswer("");
    (async () => {
      try {
        const r = await httpRequest<{ ok: boolean; lecture?: Lecture }>(
          `/api/teacher/lecture/last?student_key=${encodeURIComponent(student.student_key)}&subject=${subject}`);
        if (r.ok && r.lecture) setLecture(r.lecture);
      } catch { /* chưa có là bình thường */ }
    })();
  }, [student.student_key, subject]);

  // Giảng đến đâu trang lật theo đến đó — segment có trang thì đổi trang.
  useEffect(() => {
    if (!followPages || !lecture) return;
    const pg = lecture.segments[active]?.page;
    if (pg && pg > 0) setPage(pg);
  }, [active, lecture, followPages]);

  const generate = async () => {
    if (!bai.trim()) { toast.error("Nhập tên bài hoặc chủ đề"); return; }
    setBusy(true);
    try {
      const r = await httpRequest<{ ok: boolean; error?: string; lecture?: Lecture }>(
        "/api/teacher/lecture/generate", {
          method: "POST",
          body: { student_key: student.student_key, subject, bai, notes },
        });
      if (!r.ok || !r.lecture) throw new Error(r.error || "soạn lỗi");
      setLecture(r.lecture); setActive(0); setAnswer("");
      const g = r.lecture.grounded;
      if (g && !g.sgv) toast.warning("Kho SGV chưa có dữ liệu — bài soạn không có căn cứ sách giáo viên");
      else toast.success("Đã soạn bài giảng từ SGK + SGV");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Soạn bài lỗi");
    } finally { setBusy(false); }
  };

  const speak = useCallback(async (text: string) => {
    if (!speakerId) { toast.error("Chưa chọn loa"); return; }
    if (!text.trim()) return;
    setSpeaking(true);
    try {
      await httpRequest(`/api/voice/speakers/${encodeURIComponent(speakerId)}/play`, {
        method: "POST", body: { text },
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Phát loa lỗi");
    } finally { setSpeaking(false); }
  }, [speakerId]);

  const askTutor = async () => {
    if (!question.trim()) return;
    setAskBusy(true); setAnswer("");
    try {
      const r = await httpRequest<{ ok: boolean; error?: string; answer?: string; tts?: string }>(
        "/api/teacher/lecture/ask", {
          method: "POST",
          body: { student_key: student.student_key, subject, question },
        });
      if (!r.ok || !r.answer) throw new Error(r.error || "không trả lời được");
      setAnswer(r.answer);
      answerTts.current = r.tts || r.answer;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Hỏi lỗi");
    } finally { setAskBusy(false); }
  };

  const seg = lecture?.segments[active];

  return (
    <div className="space-y-3">
      {/* Chọn môn + bài + loa */}
      <Card><CardContent className="pt-4 space-y-2">
        <div className="grid gap-2 sm:grid-cols-4">
          <div>
            <label className="text-[10px] text-muted-foreground">Môn (lớp {student.grade || "?"})</label>
            <select className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
              value={subject} onChange={(e) => setSubject(e.target.value)}>
              {SUBJECTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="text-[10px] text-muted-foreground">
              Bài cần giảng {toc.length ? `(mục lục: ${toc.length} bài)` : "(gõ tay — chưa nạp mục lục môn này)"}
            </label>
            {toc.length > 0 && (
              <select className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs mb-1"
                value="" onChange={(e) => { if (e.target.value) setBai(e.target.value); }}>
                <option value="">— chọn bài theo mục lục SGK —</option>
                {toc.map((r, i) => (
                  <option key={i} value={`${r.bai ? r.bai + " " : ""}${r.ten}`}>
                    {r.bai ? `${r.bai} · ` : ""}{r.ten}{r.trang ? ` (tr.${r.trang}${r.tap ? " " + r.tap : ""})` : ""}
                  </option>
                ))}
              </select>
            )}
            <Input className="h-9 text-xs" placeholder="vd: Bài 8 D d Đ đ · phép cộng qua 10 · Mùa nước nổi"
              value={bai} onChange={(e) => setBai(e.target.value)} />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground">Loa phát lời cô</label>
            <select className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
              value={speakerId} onChange={(e) => setSpeakerId(e.target.value)}>
              {!speakers.length && <option value="">(chưa khai loa)</option>}
              {speakers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input className="h-8 text-xs flex-1 min-w-40"
            placeholder="Ghi chú cho AI (tuỳ chọn): em còn yếu chỗ nào, thích ví dụ gì…"
            value={notes} onChange={(e) => setNotes(e.target.value)} />
          <Button size="sm" disabled={busy} onClick={() => void generate()}>
            {busy ? <Loader2 className="size-3.5 mr-1 animate-spin" /> : <Sparkles className="size-3.5 mr-1" />}
            {busy ? "Đang soạn từ SGK + SGV…" : "Soạn bài giảng"}
          </Button>
          <label className="text-[10px] flex items-center gap-1 text-muted-foreground">
            <input type="checkbox" checked={followPages}
              onChange={(e) => setFollowPages(e.target.checked)} />
            trang lật theo bài giảng
          </label>
        </div>
      </CardContent></Card>

      {lecture && (
        <div className="grid gap-3 lg:grid-cols-2">
          {/* Khung trái: lời cô */}
          <Card><CardContent className="pt-4 space-y-2">
            <div className="text-sm font-semibold">{lecture.title || "Bài giảng"}</div>
            {lecture.muc_tieu && (
              <div className="text-[11px] text-muted-foreground">🎯 {lecture.muc_tieu}</div>
            )}
            <div className="space-y-1.5 max-h-[62vh] overflow-auto pr-1">
              {lecture.segments.map((s, i) => (
                <button key={i} type="button" onClick={() => setActive(i)}
                  className={`w-full text-left rounded border p-2 text-xs transition ${
                    i === active ? "border-amber-500/60 bg-amber-500/10"
                                 : "border-border hover:bg-secondary/50"}`}>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium">{i + 1}. {s.heading || `Phần ${i + 1}`}</span>
                    {s.page ? <span className="text-[9px] text-muted-foreground ml-auto">tr.{s.page}</span> : null}
                  </div>
                  <div className="mt-1 whitespace-pre-wrap">{s.text}</div>
                </button>
              ))}
              {lecture.cau_hoi_kiem_tra && (
                <div className="rounded border border-emerald-500/40 bg-emerald-500/8 p-2 text-xs">
                  ❓ Kiểm tra hiểu: {lecture.cau_hoi_kiem_tra}
                </div>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" disabled={speaking || !seg}
                onClick={() => void speak(seg?.tts || seg?.text || "")}>
                <Volume2 className="size-3.5 mr-1" />
                {speaking ? "Đang phát…" : `Đọc phần ${active + 1}`}
              </Button>
              <Button size="sm" variant="ghost" disabled={active <= 0}
                onClick={() => setActive((a) => a - 1)}>← Phần trước</Button>
              <Button size="sm" variant="ghost" disabled={!lecture || active >= lecture.segments.length - 1}
                onClick={() => setActive((a) => a + 1)}>Phần sau →</Button>
            </div>

            {/* Sau bài giảng: em nói chỗ chưa hiểu */}
            <div className="rounded border border-border p-2 space-y-1.5">
              <div className="text-[11px] font-semibold flex items-center gap-1">
                <MessageCircleQuestion className="size-3.5 text-sky-600" />
                Em chưa hiểu chỗ nào?
              </div>
              <div className="flex gap-1.5">
                <Input className="h-8 text-xs" placeholder="vd: con chưa hiểu vì sao phải nhớ 1"
                  value={question} onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") void askTutor(); }} />
                <Button size="sm" disabled={askBusy} onClick={() => void askTutor()}>
                  {askBusy ? <Loader2 className="size-3.5 animate-spin" /> : "Hỏi cô"}
                </Button>
              </div>
              {answer && (
                <div className="rounded bg-sky-500/8 border border-sky-500/30 p-2 text-xs whitespace-pre-wrap">
                  {answer}
                  <div className="mt-1.5">
                    <Button size="sm" variant="outline" className="h-6 text-[10px]"
                      disabled={speaking} onClick={() => void speak(answerTts.current)}>
                      <Volume2 className="size-3 mr-1" />Đọc lời giải thích
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </CardContent></Card>

          {/* Khung phải: trang SGK cho học sinh, phóng to được */}
          <Card><CardContent className="pt-4">
            <PageViewer book={book} printedPage={page}
              onPrinted={(p) => { setFollowPages(false); setPage(p); }} />
          </CardContent></Card>
        </div>
      )}
    </div>
  );
}

/* ── Tab SGK: xem sách theo lớp của học sinh ───────────────────────────── */

export function SgkViewerTab({ student }: { student: Student }) {
  const [subject, setSubject] = useState("toan");
  const [books, setBooks] = useState<Book[]>([]);
  const [slug, setSlug] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  const book = useMemo(() => books.find((b) => b.slug === slug) || null, [books, slug]);

  useEffect(() => {
    if (!student.grade) return;
    setLoading(true); setBooks([]); setSlug("");
    (async () => {
      try {
        const r = await httpRequest<{ ok: boolean; books?: Book[] }>(
          `/api/teacher/lecture/books?grade=${student.grade}&subject=${subject}`);
        const rows = r.books || [];
        setBooks(rows);
        if (rows.length) { setSlug(rows[0].slug); setPage(1); }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Không tải được danh sách sách");
      } finally { setLoading(false); }
    })();
  }, [student.grade, subject]);

  if (!student.grade) {
    return <div className="text-xs text-muted-foreground p-4">Hồ sơ chưa rõ lớp — bổ sung năm sinh ở tab Học sinh.</div>;
  }
  return (
    <Card><CardContent className="pt-4 space-y-2">
      <div className="grid gap-2 sm:grid-cols-3">
        <div>
          <label className="text-[10px] text-muted-foreground">Môn (lớp {student.grade})</label>
          <select className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
            value={subject} onChange={(e) => setSubject(e.target.value)}>
            {SUBJECTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label className="text-[10px] text-muted-foreground">Quyển</label>
          <select className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
            value={slug} onChange={(e) => { setSlug(e.target.value); setPage(1); }}>
            {!books.length && <option value="">{loading ? "Đang tìm sách…" : "(chưa có sách)"}</option>}
            {books.map((b) => <option key={b.slug} value={b.slug}>{b.title}</option>)}
          </select>
        </div>
      </div>
      <PageViewer book={book} printedPage={page} onPrinted={setPage} />
    </CardContent></Card>
  );
}
