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

  const loadMeta = useCallback(async () => {
    try {
      const [cat, spk, tw] = await Promise.all([
        request.get("/api/voice/catalog"),
        request.get("/api/voice/speakers"),
        request.get("/api/teacher/status").catch(() => ({ data: null })),
      ]);
      setCatalog(((cat.data as { voices?: VoiceItem[] })?.voices) || []);
      const body = spk.data as { rows?: Speaker[]; speakers?: Speaker[] };
      const list = body?.rows || body?.speakers || [];
      setSpeakers(Array.isArray(list) ? list : []);
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

        {/* 4. Loa theo thread */}
        <div className="rounded-md border border-border p-3 space-y-2">
          <div className="text-xs font-semibold">④ Loa nào cho thread nào</div>
          <p className="text-[10px] text-muted-foreground">
            Khoá giống lọc thread: <code>tg:BOT:CHAT</code>, <code>zalo:BOT:CHAT</code>,{" "}
            <code>zalop:CHAT</code>, hoặc kèm <code>:USER</code>.{" "}
            <code>*</code> = mọi loa. Trống hết = mọi thread dùng mọi loa.
          </p>
          {spkRows.map((row) => (
            <div key={row.id} className="rounded border border-border/70 p-2 space-y-1.5">
              <div className="flex gap-2 items-center">
                <Input
                  className="h-8 text-xs flex-1"
                  value={row.key}
                  placeholder="vd zalop:123456789 hoặc tg:123:456"
                  onChange={(e) =>
                    commitSpeakerFilters(
                      spkRows.map((r) =>
                        r.id === row.id ? { ...r, key: e.target.value } : r,
                      ),
                    )
                  }
                />
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
              <div className="flex flex-wrap gap-1.5">
                <label className="flex items-center gap-1 text-[10px] cursor-pointer border rounded px-1.5 py-0.5">
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
                          r.id === row.id ? { ...r, speakerIds: next.length ? next : ["*"] } : r,
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
                      className={`flex items-center gap-1 text-[10px] cursor-pointer border rounded px-1.5 py-0.5 ${on ? "border-emerald-500 bg-emerald-500/10" : ""}`}
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
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              commitSpeakerFilters([
                ...spkRows,
                { id: _seq++, key: "", speakerIds: ["*"] },
              ])
            }
          >
            + Thêm gán loa theo thread
          </Button>
          {speakers.length === 0 && (
            <p className="text-[10px] text-amber-600">
              Chưa có loa trong sổ — thêm ở tab «Giọng nói &amp; Loa» trước.
            </p>
          )}
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
