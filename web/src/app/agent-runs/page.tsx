"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { request } from "@/lib/request";

type RunRow = {
  id: string;
  user_id: string;
  channel: string;
  model: string;
  hint: string;
  status: string;
  user_text: string;
  reply_text: string;
  tools: string[];
  steps: number;
  duration_ms: number;
  error: string;
  created_at: number;
  source_kind?: string;
  source_account?: string;
  source_peer?: string;
  dest_provider?: string;
  dest_account?: string;
  dest_model?: string;
  from_label?: string;
  to_label?: string;
  meta?: Record<string, unknown>;
};

type Stats = {
  total?: number;
  avg_duration_ms?: number;
  by_status?: Record<string, number>;
  by_channel?: Record<string, number>;
  by_source?: Record<string, number>;
  by_kind?: Record<string, number>;
};

/** Khớp bộ lọc thread (ảnh #1) — nhóm chức năng. */
const GROUP_LABELS: Record<string, string> = {
  homeassistant: "🏠 Nhà (HA)",
  server: "🖥️ Server",
  image: "🎨 Ảnh",
  video: "🎬 Video",
  music: "🎵 Nhạc",
  web: "🌐 Web",
  code: "💻 Code",
  memory: "🧠 Ghi nhớ",
  rag: "📚 RAG / tài liệu",
  word: "📝 PDF → Word",
  summary: "🧾 Tổng hợp tin tức",
  schedule: "⏰ Nhắc hẹn / định kỳ",
  skills: "🧩 Skill / Workflow",
  wiki: "📖 Wiki / Ingest",
  contacts: "📒 Danh bạ / gửi tin",
  tts_reply: "🔉 Trả lời bằng giọng nói",
  tts_speaker: "📢 Được ra lệnh phát loa",
  teacher: "📚 Giáo viên (tiểu học · THCS · THPT)",
  chat: "💬 Chat",
};

/** Loại run — chat / vision / tạo ảnh / tạo video / agent. */
const KIND_LABELS: Record<string, string> = {
  chat: "💬 Chat",
  vision: "🖼️ Phân tích ảnh",
  image_gen: "🎨 Tạo ảnh",
  video_gen: "🎬 Tạo video",
  agent: "🤖 Agent",
  reason: "🤖 Agent",
  api: "🔌 API",
  burst: "⚡ Burst",
};

function timeAgo(ts: number) {
  if (!ts) return "—";
  const mins = Math.floor((Date.now() / 1000 - ts) / 60);
  if (mins < 1) return "vừa xong";
  if (mins < 60) return `${mins}p trước`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h trước`;
  return `${Math.floor(mins / 1440)}d trước`;
}

function statusVariant(s: string): "default" | "secondary" | "destructive" | "outline" {
  if (s === "ok" || s === "media" || s === "ha_fastpath" || s === "success") return "default";
  if (s === "error" || s === "max_steps" || s === "failed") return "destructive";
  if (s === "awaiting_approval" || s === "approved") return "secondary";
  return "outline";
}

function channelBadge(ch: string) {
  const c = (ch || "").toLowerCase();
  if (c === "ha") return "HA";
  if (c === "tg") return "TG";
  if (c === "zalo") return "Zalo";
  if (c === "zalop") return "ZaloP";
  if (c === "email") return "Email";
  if (c === "openapi") return "API";
  if (c === "web") return "Web";
  return ch || "—";
}

function runKind(r: RunRow): string {
  const fromMeta = String((r.meta as { kind?: string } | undefined)?.kind || "").trim();
  if (fromMeta) return fromMeta;
  const h = (r.hint || "").trim();
  if (h && h !== "api") return h;
  // Legacy API rows without kind
  if ((r.tools || []).includes("vision")) return "vision";
  if ((r.tools || []).some((t) => t.includes("image"))) return "image_gen";
  if ((r.tools || []).some((t) => t.includes("video"))) return "video_gen";
  if ((r.tools || []).length > 0) return "agent";
  return "chat";
}

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] || kind || "—";
}

function groupsOf(r: RunRow): string[] {
  const metaGroups = (r.meta as { groups?: string[] } | undefined)?.groups;
  if (Array.isArray(metaGroups) && metaGroups.length) {
    return metaGroups.map(String);
  }
  // Fallback from tools / kind
  const kind = runKind(r);
  if (kind === "image_gen" || kind === "vision") return ["image"];
  if (kind === "video_gen") return ["video"];
  if (kind === "chat") return ["chat"];
  return [];
}

function mediaUrls(r: RunRow): string[] {
  const urls = (r.meta as { urls?: unknown } | undefined)?.urls;
  if (!Array.isArray(urls)) return [];
  return urls.map(String).filter(Boolean);
}

function AgentRunsContent() {
  const [rows, setRows] = useState<RunRow[]>([]);
  const [stats, setStats] = useState<Stats>({});
  const [loading, setLoading] = useState(true);
  const [channel, setChannel] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [detail, setDetail] = useState<RunRow | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams({ limit: "80" });
      if (channel) q.set("channel", channel);
      const res = await request.get(`/api/v1/agent/runs?${q.toString()}`);
      const d = res.data as { rows?: RunRow[]; stats?: Stats };
      setRows(d.rows || []);
      setStats(d.stats || {});
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [channel]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!kindFilter) return rows;
    return rows.filter((r) => runKind(r) === kindFilter);
  }, [rows, kindFilter]);

  return (
    <div className="space-y-4 p-1">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Agent runs</h1>
          <p className="text-sm text-muted-foreground">
            Nhật ký đầy đủ: Chat · Phân tích ảnh · Tạo ảnh · Tạo video · Agent tools
            {" "}— (24h: {stats.total ?? 0} runs, avg {stats.avg_duration_ms ?? 0} ms)
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            className="h-9 rounded-md border border-border bg-background px-2 text-sm"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          >
            <option value="">Mọi nguồn</option>
            <option value="ha">Home Assistant</option>
            <option value="tg">Telegram</option>
            <option value="zalo">Zalo</option>
            <option value="zalop">Zalo Personal</option>
            <option value="email">Email</option>
            <option value="openapi">OpenAPI / key</option>
            <option value="web">Web admin</option>
          </select>
          <select
            className="h-9 rounded-md border border-border bg-background px-2 text-sm"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
          >
            <option value="">Mọi loại</option>
            <option value="chat">💬 Chat</option>
            <option value="vision">🖼️ Phân tích ảnh</option>
            <option value="image_gen">🎨 Tạo ảnh</option>
            <option value="video_gen">🎬 Tạo video</option>
            <option value="agent">🤖 Agent</option>
          </select>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className={`mr-1 size-4 ${loading ? "animate-spin" : ""}`} />
            Làm mới
          </Button>
        </div>
      </div>

      {/* Kind stats chips */}
      {stats.by_kind && Object.keys(stats.by_kind).length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.by_kind).map(([k, v]) => (
            <button
              key={`kind-${k}`}
              type="button"
              onClick={() => setKindFilter(kindFilter === k ? "" : k)}
              className="inline-flex"
            >
              <Badge variant={kindFilter === k ? "default" : "outline"}>
                {kindLabel(k)}: {v}
              </Badge>
            </button>
          ))}
        </div>
      ) : null}

      {stats.by_status && Object.keys(stats.by_status).length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.by_status).map(([k, v]) => (
            <Badge key={k} variant="outline">{k}: {v}</Badge>
          ))}
          {stats.by_channel && Object.entries(stats.by_channel).map(([k, v]) => (
            <Badge key={`ch-${k}`} variant="secondary">{channelBadge(k)}: {v}</Badge>
          ))}
        </div>
      ) : null}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Gần đây</CardTitle>
          <CardDescription>
            Bấm hàng để xem đầy đủ · Loại = Chat / Phân tích ảnh / Tạo ảnh / Tạo video · Nhóm = quyền như bộ lọc thread
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center py-10">
              <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {rows.length === 0
                ? "Chưa có run nào. Chat / phân tích ảnh / tạo ảnh / tạo video / gọi bot để sinh nhật ký."
                : "Không có run khớp bộ lọc loại."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Khi</TableHead>
                    <TableHead>Loại</TableHead>
                    <TableHead>Kênh</TableHead>
                    <TableHead>Từ</TableHead>
                    <TableHead>Tới</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>Nhóm / Tools</TableHead>
                    <TableHead>ms</TableHead>
                    <TableHead>User</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((r) => {
                    const kind = runKind(r);
                    const groups = groupsOf(r);
                    return (
                      <TableRow
                        key={r.id}
                        className="cursor-pointer"
                        onClick={() => setDetail(r)}
                      >
                        <TableCell className="whitespace-nowrap text-xs">
                          {timeAgo(r.created_at)}
                        </TableCell>
                        <TableCell className="text-xs whitespace-nowrap">
                          <Badge variant="secondary">{kindLabel(kind)}</Badge>
                        </TableCell>
                        <TableCell className="text-xs">{channelBadge(r.channel || r.source_kind || "")}</TableCell>
                        <TableCell className="max-w-[160px] truncate text-xs" title={r.from_label || `${r.source_kind} ${r.source_account} ${r.source_peer}`}>
                          {r.from_label || [r.source_kind, r.source_account, r.source_peer].filter(Boolean).join(" · ") || r.user_id || "—"}
                        </TableCell>
                        <TableCell className="max-w-[180px] truncate text-xs" title={r.to_label || `${r.dest_provider} ${r.dest_account}`}>
                          {r.to_label || [r.dest_provider, r.dest_account].filter(Boolean).join(" · ") || r.dest_model || "—"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusVariant(r.status)}>{r.status}</Badge>
                        </TableCell>
                        <TableCell className="max-w-[120px] truncate text-xs" title={r.model}>
                          {r.model || "—"}
                        </TableCell>
                        <TableCell className="max-w-[180px] truncate text-xs" title={[...groups.map((g) => GROUP_LABELS[g] || g), ...(r.tools || [])].join(", ")}>
                          {groups.length > 0
                            ? groups.map((g) => GROUP_LABELS[g] || g).slice(0, 2).join(" · ")
                            : (r.tools || []).slice(0, 3).join(", ") || "—"}
                          {(groups.length > 2 || (r.tools || []).length > 3) ? "…" : ""}
                        </TableCell>
                        <TableCell className="text-xs">{r.duration_ms || 0}</TableCell>
                        <TableCell className="max-w-[140px] truncate text-xs" title={r.user_text}>
                          {r.user_text || "—"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {detail ? (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2">
            <div>
              <CardTitle className="text-base flex flex-wrap items-center gap-2">
                Run `{detail.id}`
                <Badge variant="secondary">{kindLabel(runKind(detail))}</Badge>
              </CardTitle>
              <CardDescription>
                {detail.channel || detail.source_kind} · {detail.model} · {detail.steps} step(s) · {detail.duration_ms} ms
                {detail.meta && (detail.meta as { endpoint?: string }).endpoint
                  ? ` · ${(detail.meta as { endpoint?: string }).endpoint}`
                  : ""}
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setDetail(null)}>Đóng</Button>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="rounded-md border border-border/60 p-3">
                <p className="text-xs font-medium text-muted-foreground">Từ (nguồn)</p>
                <p className="mt-1 text-sm">{detail.from_label || "—"}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  kind={detail.source_kind || "—"} · account={detail.source_account || "—"} · peer={detail.source_peer || "—"}
                </p>
              </div>
              <div className="rounded-md border border-border/60 p-3">
                <p className="text-xs font-medium text-muted-foreground">Tới (provider)</p>
                <p className="mt-1 text-sm">{detail.to_label || "—"}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {detail.dest_provider || "—"} · {detail.dest_account || "—"} · model={detail.dest_model || detail.model || "—"}
                </p>
              </div>
            </div>

            {/* Nhóm chức năng — cùng taxonomy với bộ lọc thread (ảnh #1) */}
            <div>
              <p className="font-medium">Nhóm chức năng</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {groupsOf(detail).length > 0 ? (
                  groupsOf(detail).map((g) => (
                    <Badge key={g} variant="outline">{GROUP_LABELS[g] || g}</Badge>
                  ))
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </div>
            </div>

            <div>
              <p className="font-medium">Loại</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {kindLabel(runKind(detail))}
                {detail.meta && (detail.meta as { kind_label?: string }).kind_label
                  ? ` · ${(detail.meta as { kind_label?: string }).kind_label}`
                  : ""}
                {detail.meta && (detail.meta as { summary?: string }).summary
                  ? ` · ${(detail.meta as { summary?: string }).summary}`
                  : ""}
              </p>
            </div>

            <div>
              <p className="font-medium">User</p>
              <pre className="mt-1 whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">{detail.user_text || "—"}</pre>
            </div>
            <div>
              <p className="font-medium">Reply</p>
              <pre className="mt-1 whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">{detail.reply_text || "—"}</pre>
            </div>
            <div>
              <p className="font-medium">Tools</p>
              <p className="text-xs text-muted-foreground">{(detail.tools || []).join(" → ") || "—"}</p>
            </div>

            {mediaUrls(detail).length > 0 ? (
              <div>
                <p className="font-medium">Media URLs</p>
                <ul className="mt-1 space-y-1 text-xs break-all">
                  {mediaUrls(detail).map((u) => (
                    <li key={u}>
                      <a href={u} target="_blank" rel="noreferrer" className="text-primary underline-offset-2 hover:underline">
                        {u}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {detail.meta && typeof (detail.meta as { media_count?: number }).media_count === "number" ? (
              <p className="text-xs text-muted-foreground">
                media_count={(detail.meta as { media_count?: number }).media_count}
                {(detail.meta as { n?: number }).n != null ? ` · n=${(detail.meta as { n?: number }).n}` : ""}
                {(detail.meta as { size?: string }).size
                  ? ` · size=${(detail.meta as { size?: string }).size}`
                  : ""}
                {(detail.meta as { aspect_ratio?: string }).aspect_ratio
                  ? ` · aspect=${(detail.meta as { aspect_ratio?: string }).aspect_ratio}`
                  : ""}
                {(detail.meta as { duration?: string }).duration
                  ? ` · duration=${(detail.meta as { duration?: string }).duration}`
                  : ""}
              </p>
            ) : null}

            {detail.error ? (
              <div>
                <p className="font-medium text-destructive">Error</p>
                <p className="text-xs">{detail.error}</p>
              </div>
            ) : null}
            {detail.meta && Object.keys(detail.meta).length > 0 ? (
              <div>
                <p className="font-medium">Meta</p>
                <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">
                  {JSON.stringify(detail.meta, null, 2)}
                </pre>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

export default function AgentRunsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return <AgentRunsContent />;
}
