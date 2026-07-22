"use client";

/**
 * Speech Persona theo phiên — 4 phạm vi ĐỘC LẬP (giống webhook chuyển tiếp):
 *   • admin / user 1-1  : chỉ điền User ID
 *   • cả NHÓM (fallback): chỉ điền Nhóm ID — áp mọi user chưa cài riêng
 *   • user TRONG nhóm   : điền cả Nhóm ID + User ID
 * Tick «Bật persona» → chọn 4 mục (Vùng miền · Giới tính · Độ tuổi · Nghề)
 * → backend TỰ SINH khối «NHẬP VAI» nén (~60 token) đầy đủ giọng/nét phù hợp.
 */

import { useCallback, useEffect, useState } from "react";
import { Drama, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";

type Row = { key: string; prompt: string; sel: Record<string, unknown> };
type Options = {
  regions: string[]; genders: string[]; ages: string[]; jobs: string[];
};

const SEL_CLS =
  "h-8 w-full rounded-md border border-input bg-background px-2 text-sm";
const SEL_XS =
  "h-6 rounded border border-input bg-background px-1 text-[11px]";

/**
 * PersonaInline — nhúng vào TỪNG dòng (admin/thread/user-trong-thread/HA),
 * độc lập y hệt fallback webhook: tick bật → 4 lựa chọn → mô tả chi tiết
 * hiện ngay phía dưới. Tự lưu (POST) khi đổi, bỏ tick = xóa (DELETE).
 */
export function PersonaInline({ platform, groupId = "", userId = "" }: {
  platform: string; groupId?: string; userId?: string;
}) {
  const [on, setOn] = useState(false);
  const [sel, setSel] = useState<Record<string, string>>({
    region: "", gender: "", age: "", job: "",
  });
  const [desc, setDesc] = useState("");
  const [opts, setOpts] = useState<Options | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [custom, setCustom] = useState(false);   // ✍️ Tự viết nguyên văn
  const [customText, setCustomText] = useState("");

  const keyOf = useCallback(() => {
    const gid = groupId.trim(), uid = userId.trim();
    if (platform === "ha") return "ha";
    if (platform === "tg") return gid && uid ? `${gid}:u${uid}` : (gid || uid);
    const pre = platform === "zalo" ? "zalo_" : "zalop_";
    return gid && uid ? `${pre}${gid}:u${uid}` : `${pre}${gid || uid}`;
  }, [platform, groupId, userId]);

  useEffect(() => {
    request.get("/api/personas").then((r) => {
      setOpts(r.data?.options || null);
      const row = (r.data?.rows || []).find((x: Row) => x.key === keyOf());
      if (row) {
        setOn(true);
        setDesc(row.prompt || "");
        const s = (row.sel || {}) as Record<string, string>;
        if ((s as Record<string, unknown>).custom) {
          setCustom(true);
          setCustomText(row.prompt || "");
        }
        setSel({ region: s.region || "", gender: s.gender || "",
                 age: s.age || "", job: s.job || "" });
      }
      setLoaded(true);
    }).catch(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyOf]);

  const save = (next: Record<string, string>) => {
    request.post("/api/personas", { key: keyOf(), sel: next })
      .then((r) => { if (r.data?.ok) setDesc(r.data.prompt || ""); })
      .catch(() => toast.error("Lưu persona thất bại"));
  };

  const toggle = (v: boolean) => {
    setOn(v);
    if (!v) {
      setDesc("");
      request.delete("/api/personas", { data: { key: keyOf() } }).catch(() => {});
    } else if (sel.region || sel.gender || sel.age || sel.job) {
      save(sel);
    }
  };

  const set = (k: string, v: string) => {
    const next = { ...sel, [k]: v };
    setSel(next);
    if (on) save(next);
  };

  if (!loaded) return null;
  return (
    <div className="mt-1 space-y-1">
      <div className="flex flex-wrap items-center gap-1 text-[11px]">
        <label className="flex cursor-pointer items-center gap-1 select-none">
          <input type="checkbox" checked={on}
                 onChange={(e) => toggle(e.target.checked)} />
          🎭 Persona
        </label>
        {on && (
          <label className="flex cursor-pointer items-center gap-1 select-none">
            <input type="checkbox" checked={custom}
                   onChange={(e) => setCustom(e.target.checked)} />
            ✍️ Tự viết
          </label>
        )}
        {on && !custom && (
          <>
            <select className={SEL_XS} value={sel.region}
                    onChange={(e) => set("region", e.target.value)}>
              <option value="">Vùng miền…</option>
              {(opts?.regions || []).map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
            <select className={SEL_XS} value={sel.gender}
                    onChange={(e) => set("gender", e.target.value)}>
              <option value="">Giới tính…</option>
              {(opts?.genders || []).map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
            <select className={SEL_XS} value={sel.age}
                    onChange={(e) => set("age", e.target.value)}>
              <option value="">Độ tuổi…</option>
              {(opts?.ages || []).map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
            <select className={SEL_XS} value={sel.job}
                    onChange={(e) => set("job", e.target.value)}>
              <option value="">Nghề nghiệp…</option>
              {(opts?.jobs || []).map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </>
        )}
      </div>
      {on && custom && (
        <div className="space-y-1">
          <textarea
            className="w-full rounded-md border border-input bg-background p-1.5 text-[11px]"
            rows={4}
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            placeholder="Dán nguyên văn persona (vd: NHÂN VẬT: Mộc Miên, 20t… GIỌNG & NGÔN NGỮ: …)"
          />
          <Button size="sm" className="h-6 px-2 text-[11px]" onClick={() => {
            if (!customText.trim()) { toast.error("Chưa có nội dung"); return; }
            request.post("/api/personas", { key: keyOf(), prompt: customText.trim() })
              .then((r) => {
                if (r.data?.ok) { setDesc(r.data.prompt || ""); toast.success("Đã lưu persona tự viết"); }
                else toast.error(r.data?.error || "Lưu thất bại");
              })
              .catch(() => toast.error("Lưu thất bại"));
          }}>Lưu bản tự viết</Button>
        </div>
      )}
      {on && !custom && desc && (
        <div className="rounded border bg-muted/40 p-1.5 text-[11px] text-muted-foreground">
          {desc}
        </div>
      )}
    </div>
  );
}

export function PersonasCard() {
  const [rows, setRows] = useState<Row[]>([]);
  const [opts, setOpts] = useState<Options | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [platform, setPlatform] = useState("tg");
  const [groupId, setGroupId] = useState("");
  const [userId, setUserId] = useState("");
  const [region, setRegion] = useState("");
  const [gender, setGender] = useState("");
  const [age, setAge] = useState("");
  const [job, setJob] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await request.get("/api/personas");
      setRows(r.data?.rows || []);
      setOpts(r.data?.options || null);
    } catch {
      toast.error("Không tải được danh sách persona");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    if (platform !== "ha" && !groupId.trim() && !userId.trim()) {
      toast.error("Cần Nhóm ID hoặc User ID"); return;
    }
    if (!region && !gender && !age && !job) {
      toast.error("Chọn ít nhất 1 trong 4 mục"); return;
    }
    setBusy(true);
    try {
      const r = await request.post("/api/personas", {
        platform, group_id: groupId.trim(), user_id: userId.trim(),
        sel: { region, gender, age, job },
      });
      if (r.data?.ok) {
        toast.success(`Đã lưu: ${r.data.prompt?.slice(0, 80)}…`);
        setGroupId(""); setUserId("");
        void load();
      } else toast.error(r.data?.error || "Lưu thất bại");
    } catch { toast.error("Lưu thất bại"); }
    setBusy(false);
  };

  const del = async (key: string) => {
    try {
      await request.delete("/api/personas", { data: { key } });
      void load();
    } catch { toast.error("Xóa thất bại"); }
  };

  return (
    <Card>
      <CardContent className="space-y-3 pt-4">
        <div className="flex items-center gap-2">
          <Drama className="size-4" />
          <span className="text-sm font-medium">
            Persona theo phiên (admin · user · nhóm · user-trong-nhóm)
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          Chỉ User ID = user 1-1/admin · chỉ Nhóm ID = CẢ nhóm (fallback) ·
          cả hai = đúng 1 user trong nhóm. Trong chat gõ «persona» cũng cài
          được cho phiên đó.
        </p>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={enabled}
                 onChange={(e) => setEnabled(e.target.checked)} />
          Bật persona (chọn 4 mục → tự sinh mô tả đầy đủ, nén token)
        </label>

        {enabled && (
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-2">
              <select className={SEL_CLS} value={platform}
                      onChange={(e) => setPlatform(e.target.value)}>
                <option value="tg">Telegram</option>
                <option value="zalo">Zalo Bot</option>
                <option value="zalop">Zalo Cá nhân</option>
                <option value="ha">Home Assistant</option>
              </select>
              <Input className="h-8" placeholder="Nhóm ID (trống = 1-1)"
                     value={groupId}
                     onChange={(e) => setGroupId(e.target.value)} />
              <Input className="h-8" placeholder="User ID (trống = cả nhóm)"
                     value={userId}
                     onChange={(e) => setUserId(e.target.value)} />
            </div>
            <div className="grid grid-cols-4 gap-2">
              <select className={SEL_CLS} value={region}
                      onChange={(e) => setRegion(e.target.value)}>
                <option value="">Vùng miền…</option>
                {(opts?.regions || []).map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
              <select className={SEL_CLS} value={gender}
                      onChange={(e) => setGender(e.target.value)}>
                <option value="">Giới tính…</option>
                {(opts?.genders || []).map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
              <select className={SEL_CLS} value={age}
                      onChange={(e) => setAge(e.target.value)}>
                <option value="">Độ tuổi…</option>
                {(opts?.ages || []).map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
              <select className={SEL_CLS} value={job}
                      onChange={(e) => setJob(e.target.value)}>
                <option value="">Nghề nghiệp…</option>
                {(opts?.jobs || []).map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>
            <Button size="sm" onClick={() => void save()} disabled={busy}>
              <Plus className="size-3" /> Sinh & Lưu
            </Button>
          </div>
        )}

        {rows.length > 0 && (
          <div className="space-y-1">
            {rows.map((r) => (
              <div key={r.key}
                   className="flex items-start justify-between gap-2 rounded-md border p-2 text-xs">
                <div className="min-w-0">
                  <div className="font-mono font-medium">{r.key}</div>
                  <div className="text-muted-foreground line-clamp-2">
                    {r.prompt}
                  </div>
                </div>
                <Button size="sm" variant="ghost"
                        onClick={() => void del(r.key)} title="Xóa persona">
                  <Trash2 className="size-3" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
