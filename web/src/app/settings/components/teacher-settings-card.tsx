"use client";

/**
 * Tab Settings — Giáo viên tiểu học
 *
 * 1) Giọng VI / EN (TTS)
 * 2) Bật phát loa khi dạy + loa mặc định
 * 3) Gán loa theo thread (thread_speaker_filters) — cùng pattern Zalo/Tele
 * 4) Ai được dùng: tick «📚 Giáo viên tiểu học» trong Lọc thread (Kênh chat)
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { GraduationCap, Save, Volume2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";
import { useSettingsStore } from "../store";

type VoiceItem = {
  id: string;
  language?: string;
  language_label?: string;
  downloaded?: boolean;
};

type Speaker = { id: string; name: string; kind?: string };

type SpkRow = {
  id: number;
  key: string; // plat:bot:chat or plat:chat
  speakerIds: string[]; // empty = *
};

let _seq = 1;

function parseSpeakerFilters(raw: unknown): SpkRow[] {
  if (!raw || typeof raw !== "object") return [];
  return Object.entries(raw as Record<string, unknown>).map(([key, val]) => {
    const ids = Array.isArray(val)
      ? val.map((x) => String(x || "").trim()).filter(Boolean)
      : [];
    return { id: _seq++, key, speakerIds: ids.length ? ids : ["*"] };
  });
}

export function TeacherSettingsCard() {
  const config = useSettingsStore((s) => s.config);
  const setField = useSettingsStore((s) => s.setField);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const isSavingConfig = useSettingsStore((s) => s.isSavingConfig);

  const [catalog, setCatalog] = useState<VoiceItem[]>([]);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [spkRows, setSpkRows] = useState<SpkRow[]>([]);
  const [llmModels, setLlmModels] = useState<string[]>([]);
  const [workspaces, setWorkspaces] = useState<
    { id: string; name: string; grade: number; subjects: string[] }[]
  >([]);
  const [sgkInfo, setSgkInfo] = useState("");
  const [impGrade, setImpGrade] = useState(2);
  const [impSubject, setImpSubject] = useState("toan");
  const [impMode, setImpMode] = useState<"append" | "replace">("append");
  const [impBusy, setImpBusy] = useState(false);

  const teacher = useMemo(
    () => ((config as any)?.teacher as Record<string, unknown>) || {},
    [config],
  );

  /**
   * Thread (chat) từ thread_filters + user từ thread_user_filters.
   * Khoá backend: parent = `tg:BOT:CHAT` / `zalop:CHAT`; user = `parent:USER_ID`.
   */
  const threadParents = useMemo(() => {
    const tf = (config as any)?.thread_filters as Record<string, unknown> | undefined;
    if (!tf || typeof tf !== "object") return [] as string[];
    return Object.keys(tf)
      .map((k) => k.trim())
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b));
  }, [config]);

  const usersByParent = useMemo(() => {
    const map: Record<string, string[]> = {};
    const tuf = (config as any)?.thread_user_filters as
      | Record<string, unknown>
      | undefined;
    if (!tuf || typeof tuf !== "object") return map;
    for (const raw of Object.keys(tuf)) {
      const k = raw.trim();
      if (!k) continue;
      let parent = "";
      let userId = "";
      for (const p of threadParents) {
        if (k.startsWith(`${p}:`) && k.length > p.length + 1 && p.length >= parent.length) {
          parent = p;
          userId = k.slice(p.length + 1);
        }
      }
      if (!parent) {
        const idx = k.lastIndexOf(":");
        if (idx > 0) {
          parent = k.slice(0, idx);
          userId = k.slice(idx + 1);
        }
      }
      if (!parent || !userId) continue;
      if (!map[parent]) map[parent] = [];
      if (!map[parent].includes(userId)) map[parent].push(userId);
    }
    for (const p of Object.keys(map)) map[p].sort((a, b) => a.localeCompare(b));
    return map;
  }, [config, threadParents]);

  /** Mọi khoá đã biết (thread + thread:user) — cho dropdown / gợi ý. */
  const knownThreadKeys = useMemo(() => {
    const keys = new Set<string>(threadParents);
    for (const [p, users] of Object.entries(usersByParent)) {
      for (const u of users) keys.add(`${p}:${u}`);
    }
    return Array.from(keys).sort((a, b) => a.localeCompare(b));
  }, [threadParents, usersByParent]);

  const splitKey = useCallback(
    (key: string): { parent: string; userId: string } => {
      const k = (key || "").trim();
      if (!k) return { parent: "", userId: "" };
      for (const p of threadParents) {
        if (k === p) return { parent: p, userId: "" };
        if (k.startsWith(`${p}:`) && k.length > p.length + 1) {
          return { parent: p, userId: k.slice(p.length + 1) };
        }
      }
      // fallback: segment cuối = user nếu ≥2 dấu ':'
      const idx = k.lastIndexOf(":");
      if (idx > 0 && k.slice(idx + 1) && k.slice(0, idx).includes(":")) {
        return { parent: k.slice(0, idx), userId: k.slice(idx + 1) };
      }
      return { parent: k, userId: "" };
    },
    [threadParents],
  );

  const buildKey = (parent: string, userId: string) => {
    const p = parent.trim();
    const u = userId.trim();
    if (!p) return u ? `?:${u}` : "";
    return u ? `${p}:${u}` : p;
  };

  // Form «+ Thêm gán loa»
  const [addParent, setAddParent] = useState("");
  const [addCustomParent, setAddCustomParent] = useState("");
  const [addUserMode, setAddUserMode] = useState<"all" | "known" | "custom">("all");
  const [addUserId, setAddUserId] = useState("");
  const [addSpeaker, setAddSpeaker] = useState("*");

  const loadMeta = useCallback(async () => {
    try {
      const [cat, spk, tw, modelsRes] = await Promise.all([
        request.get("/api/voice/catalog"),
        request.get("/api/voice/speakers"),
        request.get("/api/teacher/status").catch(() => ({ data: null })),
        request.get("/v1/models").catch(() => ({ data: null })),
      ]);
      setCatalog(((cat.data as { voices?: VoiceItem[] })?.voices) || []);
      const body = spk.data as { rows?: Speaker[]; speakers?: Speaker[] };
      const list = body?.rows || body?.speakers || [];
      setSpeakers(Array.isArray(list) ? list : []);
      // /v1/models → OpenAI-style { data: [{ id }] } or string[]
      const raw = (modelsRes as { data?: any })?.data;
      let ids: string[] = [];
      if (Array.isArray(raw?.data)) {
        ids = raw.data.map((m: { id?: string }) => String(m?.id || "")).filter(Boolean);
      } else if (Array.isArray(raw)) {
        ids = raw.map((m: unknown) =>
          typeof m === "string" ? m : String((m as { id?: string })?.id || ""),
        ).filter(Boolean);
      }
      setLlmModels(Array.from(new Set(ids)).sort((a, b) => a.localeCompare(b)));
      const td = (tw as { data?: any })?.data;
      if (td?.workspaces) setWorkspaces(td.workspaces);
      if (td?.kb) {
        setSgkInfo(
          `SGK seed: ${td.kb.sgk_files ?? "?"}/${td.kb.sgk_expected ?? 15} file · ` +
            `${td.kb.workspaces ?? "?"} workspace`,
        );
      }
    } catch {
      /* voice optional */
    }
  }, []);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    setSpkRows(parseSpeakerFilters((config as any)?.thread_speaker_filters));
  }, [config]);

  const patchTeacher = (patch: Record<string, unknown>) => {
    setField("teacher", { ...teacher, ...patch });
  };

  const commitSpeakerFilters = (rows: SpkRow[]) => {
    setSpkRows(rows);
    const out: Record<string, string[]> = {};
    for (const r of rows) {
      const k = r.key.trim();
      if (!k) continue;
      const ids = r.speakerIds.map((x) => x.trim()).filter(Boolean);
      out[k] = ids.length ? ids : ["*"];
    }
    setField("thread_speaker_filters", out);
  };

  const voicesVi = catalog.filter(
    (v) =>
      !v.language ||
      v.language.startsWith("vi") ||
      (v.language_label || "").toLowerCase().includes("việt") ||
      v.id.startsWith("vieneu:") ||
      (!v.id.startsWith("kokoro:") && !v.language?.startsWith("en")),
  );
  const voicesEn = catalog.filter(
    (v) =>
      v.id.startsWith("kokoro:") ||
      v.language?.startsWith("en") ||
      (v.language_label || "").toLowerCase().includes("anh") ||
      (v.language_label || "").toLowerCase().includes("english"),
  );
  // Fallback: nếu filter rỗng, cho chọn full catalog
  const optsVi = voicesVi.length ? voicesVi : catalog;
  const optsEn = voicesEn.length ? voicesEn : catalog;

  const voiceSelect = (
    label: string,
    value: string,
    onChange: (v: string) => void,
    opts: VoiceItem[],
  ) => (
    <div>
      <label className="text-xs text-muted-foreground">{label}</label>
      <select
        className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">(dùng giọng mặc định hệ thống)</option>
        {opts.map((v) => (
          <option key={v.id} value={v.id} disabled={v.downloaded === false}>
            {v.id}
            {v.language_label ? ` · ${v.language_label}` : ""}
            {v.downloaded === false ? " (chưa tải)" : ""}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <Card>
      <CardContent className="space-y-4 pt-4">
        <div className="text-sm font-semibold flex items-center gap-2">
          <GraduationCap className="size-4 text-amber-600" /> Giáo viên tiểu học
        </div>
        <p className="text-[11px] text-muted-foreground">
          Skill <code>giao-vien-tieu-hoc</code> · workflow <code>bai-hoc-tieu-hoc</code>.
          Quyền dùng và loa theo từng thread cấu hình giống tab{" "}
          <b>Kênh chat → Lọc thread</b> (Telegram / Zalo).
        </p>

        {/* 1. Bật / giọng */}
        <div className="rounded-md border border-border p-3 space-y-3">
          <div className="text-xs font-semibold">① Bật chức năng &amp; giọng đọc</div>
          <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-3.5"
              checked={Boolean(teacher.enabled ?? true)}
              onChange={(e) => patchTeacher({ enabled: e.target.checked })}
            />
            Bật chế độ Giáo viên tiểu học (skill / workflow)
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            {voiceSelect(
              "Giọng tiếng Việt (dạy / đọc bài VI)",
              String(teacher.voice_vi || ""),
              (v) => patchTeacher({ voice_vi: v }),
              optsVi,
            )}
            {voiceSelect(
              "Giọng tiếng Anh (từ vựng / câu EN)",
              String(teacher.voice_en || ""),
              (v) => patchTeacher({ voice_en: v }),
              optsEn,
            )}
          </div>
          <p className="text-[10px] text-muted-foreground">
            Khi phát loa / TTS, đoạn có dấu Việt → giọng VI; đoạn Latin dài → giọng EN.
            Cần tải model VieNeu / Kokoro / Piper tương ứng (tab Giọng nói &amp; Loa).
          </p>
        </div>

        {/* 1b. Model LLM — Tiếng Anh 5 kỹ năng + fallback */}
        <div className="rounded-md border border-border p-3 space-y-3">
          <div className="text-xs font-semibold">
            ①b Model AI · Tiếng Anh (Ngữ pháp · Nghe · Nói · Đọc · Viết)
          </div>
          <p className="text-[10px] text-muted-foreground">
            Mỗi kỹ năng EN có thể gắn <b>model riêng</b> (soạn đề / chấm).
            Để trống skill = dùng fallback bên dưới. Fallback trống ={" "}
            <code>telegram_ai_model</code>.
          </p>
          {(() => {
            const eng =
              ((teacher.english as Record<string, unknown> | undefined) || {});
            const models =
              ((eng.models as Record<string, string> | undefined) || {});
            const setEnModel = (skill: string, value: string) => {
              patchTeacher({
                english: {
                  ...eng,
                  models: { ...models, [skill]: value },
                },
              });
            };
            const skills: { id: string; label: string; hint: string }[] = [
              { id: "grammar", label: "Ngữ pháp (Grammar)", hint: "thì, cấu trúc, error correction" },
              { id: "listening", label: "Nghe (Listening)", hint: "script TTS + câu hỏi" },
              { id: "speaking", label: "Nói (Speaking)", hint: "dialogue, role-play, oral prompts" },
              { id: "reading", label: "Đọc (Reading)", hint: "đoạn + comprehension" },
              { id: "writing", label: "Viết (Writing)", hint: "sentence → paragraph → essay" },
            ];
            const modelOptions = (current: string) =>
              Array.from(new Set([...llmModels, ...(current ? [current] : [])]));
            return (
              <div className="space-y-2">
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {skills.map((s) => {
                    const val = String(models[s.id] || "");
                    return (
                      <div key={s.id} className="rounded border border-border/70 p-2 space-y-1">
                        <label className="text-[11px] font-medium">{s.label}</label>
                        <p className="text-[9px] text-muted-foreground">{s.hint}</p>
                        <select
                          className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[11px] h-8"
                          value={val}
                          onChange={(e) => setEnModel(s.id, e.target.value)}
                        >
                          <option value="">(fallback)</option>
                          {modelOptions(val).map((m) => (
                            <option key={m} value={m}>
                              {m}
                            </option>
                          ))}
                        </select>
                        <Input
                          className="h-7 text-[10px] font-mono"
                          placeholder="gõ model id…"
                          value={val}
                          onChange={(e) => setEnModel(s.id, e.target.value)}
                        />
                      </div>
                    );
                  })}
                </div>
                <div className="border-t border-border pt-2 grid gap-2 sm:grid-cols-2">
                  <div>
                    <label className="text-[10px] text-muted-foreground">
                      Fallback · Nghe/Nói (listening + speaking)
                    </label>
                    <select
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                      value={String(teacher.model_speak || "")}
                      onChange={(e) => patchTeacher({ model_speak: e.target.value })}
                    >
                      <option value="">(mặc định hệ thống)</option>
                      {modelOptions(String(teacher.model_speak || "")).map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-muted-foreground">
                      Fallback · Ngữ pháp/Đọc/Viết (+ Văn/Toán AI)
                    </label>
                    <select
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                      value={String(teacher.model_write || "")}
                      onChange={(e) => patchTeacher({ model_write: e.target.value })}
                    >
                      <option value="">(mặc định hệ thống)</option>
                      {modelOptions(String(teacher.model_write || "")).map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            );
          })()}
          <p className="text-[10px] text-muted-foreground">
            Khi soạn đề/chấm môn <b>Anh</b>, hệ thống chọn model theo skill
            (grammar/listening/speaking/reading/writing). Giọng TTS EN vẫn ở mục ①
            (voice_en). Danh sách model: <code>/v1/models</code>.
          </p>
        </div>

        {/* 2. Phát loa */}
        <div className="rounded-md border border-border p-3 space-y-3">
          <div className="text-xs font-semibold flex items-center gap-1.5">
            <Volume2 className="size-3.5" /> ② Giáo viên phát ra loa
          </div>
          <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
            <input
              type="checkbox"
              className="size-3.5"
              checked={Boolean(teacher.speak_to_speaker)}
              onChange={(e) => patchTeacher({ speak_to_speaker: e.target.checked })}
            />
            Cho phép đọc tóm tắt bài ra loa nhà (khi dạy)
          </label>
          <p className="text-[10px] text-muted-foreground -mt-1">
            Vẫn cần tick <b>📢 Được ra lệnh phát loa</b> trên thread trong Lọc thread,
            và gán loa bên dưới (hoặc để * = mọi loa đã kết nối).
          </p>
          <div>
            <label className="text-xs text-muted-foreground">
              Loa mặc định khi không nói rõ tên (tuỳ chọn)
            </label>
            <select
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
              value={String(teacher.default_speaker || "")}
              onChange={(e) => patchTeacher({ default_speaker: e.target.value })}
            >
              <option value="">(hỏi lại / 1 loa duy nhất thì tự chọn)</option>
              {speakers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.kind || "?"})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* 3. Ai được dùng */}
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
          <div className="text-xs font-semibold">③ Ai được dùng Giáo viên? (Zalo / Telegram)</div>
          <ol className="text-[11px] text-muted-foreground list-decimal pl-4 space-y-1">
            <li>
              Vào <b>Settings → Kênh chat</b> → tab kênh (Telegram / Zalo / Zalo CN) →{" "}
              <b>🎚️ Lọc thread</b>.
            </li>
            <li>
              Thêm thread (Chat ID) → tick <b>📚 Giáo viên tiểu học</b>.
            </li>
            <li>
              (Tuỳ chọn) Trong nhóm: thêm User ID → tick subset quyền (chỉ con / chỉ PH).
            </li>
            <li>
              Muốn phát loa: tick thêm <b>📢 Được ra lệnh phát loa</b>, rồi gán loa ở mục ④.
            </li>
          </ol>
          <p className="text-[10px] text-muted-foreground">
            Thread <b>không</b> có dòng lọc → mặc định vẫn dùng được (giống tool khác).
            Chỉ khi đã lọc mà <b>không</b> tick Giáo viên thì skill/workflow bị chặn.
          </p>
        </div>

        {/* 4. Loa theo thread / user */}
        <div className="rounded-md border border-border p-3 space-y-2">
          <div className="text-xs font-semibold">④ Loa nào cho thread / user nào</div>
          <p className="text-[10px] text-muted-foreground">
            Chọn <b>thread (Chat ID)</b> + tuỳ chọn <b>User ID</b> (trong nhóm: chỉ
            user đó được loa đó). Khoá: <code>tg:BOT:CHAT</code> /{" "}
            <code>zalop:CHAT</code> hoặc kèm <code>:USER_ID</code>.{" "}
            <code>*</code> = mọi loa. Không có dòng = mọi thread/user dùng mọi loa.
            Backend ưu tiên khoá cụ thể nhất (user → thread).
          </p>

          {/* Quick-add: thread + user + loa */}
          <div className="rounded border border-dashed border-border/80 p-2 bg-muted/20 space-y-2">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <div className="min-w-0">
                <label className="text-[10px] text-muted-foreground">
                  Thread (Chat) đã lọc
                </label>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                  value={addParent}
                  onChange={(e) => {
                    setAddParent(e.target.value);
                    setAddUserMode("all");
                    setAddUserId("");
                  }}
                >
                  <option value="">— chọn thread —</option>
                  {threadParents.map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                  <option value="__custom__">✏️ Thread nhập tay…</option>
                </select>
              </div>

              <div className="min-w-0">
                <label className="text-[10px] text-muted-foreground">
                  User ID (tuỳ chọn)
                </label>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                  value={
                    addUserMode === "all"
                      ? ""
                      : addUserMode === "custom"
                        ? "__custom__"
                        : addUserId
                  }
                  disabled={!addParent}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (!v) {
                      setAddUserMode("all");
                      setAddUserId("");
                    } else if (v === "__custom__") {
                      setAddUserMode("custom");
                      setAddUserId("");
                    } else {
                      setAddUserMode("known");
                      setAddUserId(v);
                    }
                  }}
                >
                  <option value="">Cả thread (mọi user)</option>
                  {addParent &&
                    addParent !== "__custom__" &&
                    (usersByParent[addParent] || []).map((u) => (
                      <option key={u} value={u}>
                        User {u}
                        {spkRows.some((r) => r.key === buildKey(addParent, u))
                          ? " (đã gán)"
                          : ""}
                      </option>
                    ))}
                  <option value="__custom__">✏️ Nhập User ID…</option>
                </select>
              </div>

              <div className="min-w-0">
                <label className="text-[10px] text-muted-foreground">Loa</label>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                  value={addSpeaker}
                  onChange={(e) => setAddSpeaker(e.target.value)}
                >
                  <option value="*">* mọi loa</option>
                  {speakers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.kind || "?"})
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-end">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-9 w-full"
                  onClick={() => {
                    const parent =
                      addParent === "__custom__"
                        ? addCustomParent.trim()
                        : addParent.trim();
                    let userId = "";
                    if (addUserMode === "known" || addUserMode === "custom") {
                      userId = addUserId.trim();
                    }

                    if (!parent) {
                      toast.error(
                        addParent === "__custom__"
                          ? "Nhập khoá thread (vd tg:BOT:CHAT)"
                          : "Chọn thread (Chat ID)",
                      );
                      return;
                    }
                    if (addUserMode === "custom" && !userId) {
                      toast.error("Nhập User ID hoặc chọn «Cả thread»");
                      return;
                    }
                    const key = buildKey(parent, userId);
                    if (spkRows.some((r) => r.key === key)) {
                      toast.error(`Đã có gán loa cho ${key}`);
                      return;
                    }
                    commitSpeakerFilters([
                      ...spkRows,
                      { id: _seq++, key, speakerIds: [addSpeaker || "*"] },
                    ]);
                    toast.success(
                      userId
                        ? `Đã gán loa cho thread + user ${userId}`
                        : `Đã gán loa cho cả thread ${parent}`,
                    );
                    setAddUserMode("all");
                    setAddUserId("");
                    setAddCustomParent("");
                  }}
                >
                  + Thêm gán loa
                </Button>
              </div>
            </div>

            {/* Nhập tay parent / user khi cần */}
            {(addParent === "__custom__" || addUserMode === "custom") && (
              <div className="grid gap-2 sm:grid-cols-2">
                {addParent === "__custom__" && (
                  <div>
                    <label className="text-[10px] text-muted-foreground">
                      Khoá thread (vd tg:BOT:CHAT)
                    </label>
                    <Input
                      className="h-8 text-xs font-mono"
                      placeholder="tg:123:456 hoặc zalop:789"
                      value={addCustomParent}
                      onChange={(e) => setAddCustomParent(e.target.value)}
                    />
                  </div>
                )}
                {addUserMode === "custom" && (
                  <div>
                    <label className="text-[10px] text-muted-foreground">
                      User ID (Telegram / Zalo user)
                    </label>
                    <Input
                      className="h-8 text-xs font-mono"
                      placeholder="vd 123456789"
                      value={addUserId}
                      onChange={(e) => setAddUserId(e.target.value)}
                    />
                  </div>
                )}
              </div>
            )}

            {(addParent === "__custom__" ? addCustomParent : addParent) && (
              <p className="text-[10px] text-muted-foreground font-mono">
                Khoá sẽ lưu:{" "}
                <code>
                  {buildKey(
                    addParent === "__custom__" ? addCustomParent : addParent,
                    addUserMode === "all" ? "" : addUserId,
                  ) || "—"}
                </code>
                {addUserMode === "all" ? " · cả thread" : " · theo user"}
              </p>
            )}
          </div>

          {threadParents.length === 0 && (
            <p className="text-[10px] text-amber-700 bg-amber-500/10 rounded px-2 py-1.5">
              Chưa có thread trong <b>Lọc thread</b> — vào tab Kênh chat thêm Chat ID
              (+ User ID trong nhóm nếu cần), hoặc «Thread nhập tay».
            </p>
          )}

          {spkRows.length === 0 ? (
            <p className="text-[10px] text-muted-foreground italic">
              Chưa gán loa. Chọn thread → (tuỳ chọn) User ID → loa → «+ Thêm gán loa».
            </p>
          ) : null}

          {spkRows.map((row) => {
            const { parent, userId } = splitKey(row.key);
            const userOpts = usersByParent[parent] || [];
            return (
            <div key={row.id} className="rounded border border-border/70 p-2 space-y-2">
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-12 items-end">
                <div className="lg:col-span-4 min-w-0">
                  <label className="text-[10px] text-muted-foreground">Thread</label>
                  <select
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-8"
                    value={
                      parent && threadParents.includes(parent)
                        ? parent
                        : parent
                          ? "__keep__"
                          : ""
                    }
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "__keep__") return;
                      const next = buildKey(v, userId);
                      commitSpeakerFilters(
                        spkRows.map((r) =>
                          r.id === row.id ? { ...r, key: next } : r,
                        ),
                      );
                    }}
                  >
                    <option value="">— chọn thread —</option>
                    {threadParents.map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                    {parent && !threadParents.includes(parent) ? (
                      <option value="__keep__">{parent} (tự nhập)</option>
                    ) : null}
                  </select>
                </div>
                <div className="lg:col-span-3 min-w-0">
                  <label className="text-[10px] text-muted-foreground">User ID</label>
                  <div className="flex gap-1">
                    <select
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-8 min-w-0"
                      value={
                        !userId
                          ? ""
                          : userOpts.includes(userId)
                            ? userId
                            : "__custom__"
                      }
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === "__custom__") {
                          // giữ userId hiện tại hoặc để trống cho ô input
                          commitSpeakerFilters(
                            spkRows.map((r) =>
                              r.id === row.id
                                ? { ...r, key: buildKey(parent, userId || "") }
                                : r,
                            ),
                          );
                          return;
                        }
                        commitSpeakerFilters(
                          spkRows.map((r) =>
                            r.id === row.id
                              ? { ...r, key: buildKey(parent, v) }
                              : r,
                          ),
                        );
                      }}
                    >
                      <option value="">Cả thread</option>
                      {userOpts.map((u) => (
                        <option key={u} value={u}>
                          {u}
                        </option>
                      ))}
                      <option value="__custom__">✏️ Khác…</option>
                    </select>
                  </div>
                </div>
                <div className="lg:col-span-4 min-w-0">
                  <label className="text-[10px] text-muted-foreground">
                    User ID (sửa tay) / khoá đầy đủ
                  </label>
                  <Input
                    className="h-8 text-xs font-mono"
                    value={userId || (!parent ? row.key : "")}
                    placeholder="User ID hoặc để trống = cả thread"
                    onChange={(e) => {
                      const u = e.target.value.trim();
                      // Nếu chưa có parent, coi như sửa full key
                      if (!parent) {
                        commitSpeakerFilters(
                          spkRows.map((r) =>
                            r.id === row.id ? { ...r, key: e.target.value } : r,
                          ),
                        );
                        return;
                      }
                      commitSpeakerFilters(
                        spkRows.map((r) =>
                          r.id === row.id ? { ...r, key: buildKey(parent, u) } : r,
                        ),
                      );
                    }}
                  />
                </div>
                <div className="lg:col-span-1 flex justify-end">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8"
                    onClick={() =>
                      commitSpeakerFilters(spkRows.filter((r) => r.id !== row.id))
                    }
                  >
                    Xóa
                  </Button>
                </div>
              </div>
              <p className="text-[10px] text-muted-foreground font-mono">
                Khoá: <code>{row.key || "—"}</code>
                {userId ? " · theo user" : parent ? " · cả thread" : ""}
              </p>

              <div className="text-[10px] text-muted-foreground">
                Tick loa được phép:
              </div>
              <div className="flex flex-wrap gap-1.5">
                <label
                  className={`flex items-center gap-1 text-[10px] cursor-pointer border rounded px-1.5 py-1 ${
                    row.speakerIds.includes("*")
                      ? "border-emerald-500 bg-emerald-500/10"
                      : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    className="size-3"
                    checked={row.speakerIds.includes("*")}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? ["*"]
                        : row.speakerIds.filter((x) => x !== "*");
                      commitSpeakerFilters(
                        spkRows.map((r) =>
                          r.id === row.id
                            ? { ...r, speakerIds: next.length ? next : ["*"] }
                            : r,
                        ),
                      );
                    }}
                  />
                  * mọi loa
                </label>
                {speakers.map((s) => {
                  const on = row.speakerIds.includes(s.id);
                  return (
                    <label
                      key={s.id}
                      className={`flex items-center gap-1 text-[10px] cursor-pointer border rounded px-1.5 py-1 ${
                        on ? "border-emerald-500 bg-emerald-500/10" : ""
                      } ${row.speakerIds.includes("*") ? "opacity-50" : ""}`}
                    >
                      <input
                        type="checkbox"
                        className="size-3"
                        checked={on}
                        disabled={row.speakerIds.includes("*")}
                        onChange={() => {
                          let ids = row.speakerIds.filter((x) => x !== "*");
                          if (ids.includes(s.id)) ids = ids.filter((x) => x !== s.id);
                          else ids = [...ids, s.id];
                          commitSpeakerFilters(
                            spkRows.map((r) =>
                              r.id === row.id
                                ? { ...r, speakerIds: ids.length ? ids : ["*"] }
                                : r,
                            ),
                          );
                        }}
                      />
                      {s.name}
                      <span className="text-muted-foreground">({s.kind || "?"})</span>
                    </label>
                  );
                })}
              </div>
              {speakers.length === 0 ? (
                <p className="text-[10px] text-amber-600">
                  Chưa load được sổ loa.{" "}
                  <button
                    type="button"
                    className="underline"
                    onClick={() => void loadMeta()}
                  >
                    Tải lại
                  </button>{" "}
                  hoặc thêm loa ở tab «Giọng nói &amp; Loa».
                </p>
              ) : (
                <p className="text-[10px] text-muted-foreground">
                  Đang chọn:{" "}
                  <code>
                    {row.speakerIds.includes("*")
                      ? "* (mọi loa)"
                      : row.speakerIds
                          .map(
                            (id) =>
                              speakers.find((s) => s.id === id)?.name || id,
                          )
                          .join(", ") || "—"}
                  </code>
                </p>
              )}
            </div>
            );
          })}

          <div className="flex flex-wrap gap-2 items-center">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 text-[11px]"
              onClick={() => void loadMeta()}
            >
              Làm mới danh sách loa ({speakers.length})
            </Button>
            {speakers.length > 0 && (
              <span className="text-[10px] text-muted-foreground">
                Sổ loa: {speakers.map((s) => s.name).join(" · ")}
              </span>
            )}
          </div>
        </div>

        {/* 5. Import PDF SGK — lớp 1–5 */}
        <div className="rounded-md border border-border p-3 space-y-2">
          <div className="text-xs font-semibold">
            ⑤ Import PDF SGK (lớp 1–12 · Toán/Văn/Anh · THCS/THPT)
          </div>
          <p className="text-[10px] text-muted-foreground">
            Upload PDF → trích chữ →{" "}
            <code>data/agent/teacher/sgk/lopN/&#123;mon&#125;.md</code>. Tiểu học 1–5 ·
            THCS 6–9 · THPT 10–12.
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            <div>
              <label className="text-[10px] text-muted-foreground">Lớp</label>
              <select
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                value={impGrade}
                onChange={(e) => setImpGrade(Number(e.target.value))}
              >
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((g) => (
                  <option key={g} value={g}>
                    Lớp {g}
                    {g <= 5 ? " (TH)" : g <= 9 ? " (THCS)" : " (THPT)"}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">Môn</label>
              <select
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                value={impSubject}
                onChange={(e) => setImpSubject(e.target.value)}
              >
                <option value="toan">Toán</option>
                <option value="van">Tiếng Việt</option>
                <option value="anh">Tiếng Anh</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">Chế độ</label>
              <select
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs h-9"
                value={impMode}
                onChange={(e) => setImpMode(e.target.value as "append" | "replace")}
              >
                <option value="append">Nối thêm (giữ seed)</option>
                <option value="replace">Ghi đè file lớp–môn</option>
              </select>
            </div>
          </div>
          <input
            type="file"
            accept="application/pdf,.pdf"
            className="block w-full text-xs"
            disabled={impBusy}
            onChange={async (e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              setImpBusy(true);
              try {
                const fd = new FormData();
                fd.append("file", f);
                fd.append("grade", String(impGrade));
                fd.append("subject", impSubject);
                fd.append("mode", impMode);
                fd.append("title", f.name.replace(/\.pdf$/i, ""));
                const r = await request.post("/api/teacher/import-sgk", fd, {
                  headers: { "Content-Type": "multipart/form-data" },
                });
                const d = r.data as {
                  ok?: boolean;
                  chars?: number;
                  workspace?: string;
                  path?: string;
                };
                toast.success(
                  `Đã import ${d.chars ?? "?"} ký tự → ${d.workspace || ""}`,
                );
                void loadMeta();
              } catch (err: unknown) {
                const msg =
                  (err as { response?: { data?: { detail?: string } } })?.response
                    ?.data?.detail ||
                  (err instanceof Error ? err.message : String(err));
                toast.error(`Import PDF lỗi: ${msg}`);
              } finally {
                setImpBusy(false);
              }
            }}
          />
          {impBusy && (
            <p className="text-[10px] text-amber-600">
              Đang trích PDF (scan có thể mất vài phút OCR)…
            </p>
          )}
        </div>

        {/* 6. Workspace + KB */}
        <div className="rounded-md border border-border p-3 space-y-2">
          <div className="text-xs font-semibold">⑥ Workspace lớp 1–12 (Toán · Văn · Anh)</div>
          <p className="text-[10px] text-muted-foreground">
            36 workspace: <code>lop1-toan</code> … <code>lop12-anh</code>. Tools:{" "}
            <code>search_sgk</code>, <code>teacher_quiz</code>, <code>teacher_grade</code>,{" "}
            <code>teacher_memory</code>.
            {sgkInfo ? <> · {sgkInfo}</> : null}
          </p>
          <div className="max-h-40 overflow-y-auto rounded border border-border/60 p-2 text-[10px] space-y-0.5">
            {workspaces.length === 0 ? (
              <span className="text-muted-foreground">
                Chưa load được danh sách — restart API sau khi deploy backend teacher.
              </span>
            ) : (
              workspaces.map((w) => (
                <div key={w.id}>
                  <code>{w.id}</code> — {w.name}
                </div>
              ))
            )}
          </div>
        </div>

        <Button
          className="w-full"
          size="sm"
          disabled={isSavingConfig}
          onClick={async () => {
            await saveConfig();
            toast.success("Đã lưu cấu hình Giáo viên");
          }}
        >
          <Save className="size-3.5 mr-1.5" />
          {isSavingConfig ? "Đang lưu..." : "Lưu cấu hình Giáo viên"}
        </Button>
      </CardContent>
    </Card>
  );
}
