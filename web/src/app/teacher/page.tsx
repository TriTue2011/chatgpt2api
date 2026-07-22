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
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";

type TabId = "lesson" | "homework" | "placement" | "parent" | "import";

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

const SUBJECTS = [
  { id: "toan", label: "Toán" },
  { id: "van", label: "Văn / TV" },
  { id: "anh", label: "Anh" },
];

export default function TeacherPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin", "user"]);
  const [tab, setTab] = useState<TabId>("lesson");

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

  // assignments
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [asgTitle, setAsgTitle] = useState("");
  const [asgTopic, setAsgTopic] = useState("");
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

  // placement + roadmap
  const [students, setStudents] = useState<any[]>([]);
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
    if (tab === "placement" && session) {
      void loadStudents();
      void loadRoadmap();
    }
  }, [tab, session, loadStudents, loadRoadmap]);

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

  useEffect(() => {
    if (tab === "import" && session) {
      void loadImports();
    }
  }, [tab, session, loadImports]);

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
    if (!confirm("Xóa bài giảng này?")) return;
    try {
      await request.delete(`/api/teacher/lessons/${id}`);
      toast.success("Đã xóa bài giảng");
      if (activeLesson?.id === id) setActiveLesson(null);
      void loadLessons();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Xóa lỗi");
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

  // All hooks must be above this guard (Rules of Hooks).
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

  const tabs: { id: TabId; label: string; icon: React.ReactNode }[] = [
    { id: "lesson", label: "Bài giảng", icon: <BookOpen className="size-3.5" /> },
    { id: "homework", label: "Bài tập", icon: <ClipboardList className="size-3.5" /> },
    { id: "placement", label: "Đầu vào · Lộ trình", icon: <Route className="size-3.5" /> },
    { id: "parent", label: "Dashboard PH", icon: <Users className="size-3.5" /> },
    { id: "import", label: "Import SGK", icon: <FileUp className="size-3.5" /> },
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

      {/* Bộ lọc lớp–môn–HS */}
      <Card>
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
              {SUBJECTS.map((s) => (
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
      </Card>

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

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 border-b border-border pb-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition ${
              tab === t.id
                ? "bg-amber-500/15 text-amber-700 dark:text-amber-300 font-medium"
                : "text-muted-foreground hover:bg-secondary"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* ── LESSON ── */}
      {tab === "lesson" && (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-3">
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
          </Card>
          <Card className="lg:col-span-2">
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
                        const r = await request.get(`/api/teacher/lessons/${l.id}`);
                        const full = (r.data as { lesson?: Lesson })?.lesson;
                        setActiveLesson(full || null);
                        if (full) {
                          setLessonTitle(full.title);
                          setLessonBody(full.body_text);
                          setLessonTts(full.tts_script);
                        }
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
                      onClick={() => void deleteLesson(l.id)}
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
          </Card>
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
          <Card className="lg:col-span-2">
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
          </Card>
          )}

          <Card className={hwFullscreen ? "max-w-4xl mx-auto w-full" : "lg:col-span-3"}>
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
          </Card>
        </div>
      )}

      {/* ── PLACEMENT + ROADMAP ── */}
      {tab === "placement" && (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-2">
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
          </Card>

          <Card className="lg:col-span-3">
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
          </Card>
        </div>
      )}

      {/* ── PARENT DASHBOARD ── */}
      {tab === "parent" && (
        <Card>
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
        </Card>
      )}

      {/* ── IMPORT SGK ── */}
      {tab === "import" && (
        <Card>
          <CardContent className="pt-4 space-y-3">
            <div className="text-xs font-semibold flex items-center gap-1.5">
              <FileUp className="size-3.5 text-amber-600" />
              Import PDF SGK theo chương / bài
            </div>
            <p className="text-[10px] text-muted-foreground">
              PDF được tách heading <code>## Chương/Bài/Unit…</code> để search từng mục.
              Lớp <b>{grade}</b> · <b>{subject}</b> → workspace <code>{workspace}</code>
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <label className="text-[10px] text-muted-foreground">Chế độ</label>
                <select
                  className="w-full h-9 rounded-md border border-border bg-background px-2 text-xs"
                  value={impMode}
                  onChange={(e) => setImpMode(e.target.value as "append" | "replace")}
                  disabled={impBusy}
                >
                  <option value="append">Nối thêm (giữ seed)</option>
                  <option value="replace">Ghi đè file lớp–môn</option>
                </select>
              </div>
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
          </CardContent>
        </Card>
      )}
    </div>
  );
}
