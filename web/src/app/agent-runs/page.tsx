"use client";

import { useCallback, useEffect, useState } from "react";
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
};

type Stats = {
  total?: number;
  avg_duration_ms?: number;
  by_status?: Record<string, number>;
  by_channel?: Record<string, number>;
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
  if (s === "ok" || s === "media" || s === "ha_fastpath") return "default";
  if (s === "error" || s === "max_steps") return "destructive";
  if (s === "awaiting_approval" || s === "approved") return "secondary";
  return "outline";
}

function AgentRunsContent() {
  const [rows, setRows] = useState<RunRow[]>([]);
  const [stats, setStats] = useState<Stats>({});
  const [loading, setLoading] = useState(true);
  const [channel, setChannel] = useState("");
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

  return (
    <div className="space-y-4 p-1">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Agent runs</h1>
          <p className="text-sm text-muted-foreground">
            Nhật ký lượt agent: tool, model, latency (24h: {stats.total ?? 0} runs,
            avg {stats.avg_duration_ms ?? 0} ms)
          </p>
        </div>
        <div className="flex gap-2">
          <select
            className="h-9 rounded-md border border-border bg-background px-2 text-sm"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          >
            <option value="">Mọi kênh</option>
            <option value="tg">Telegram</option>
            <option value="zalo">Zalo</option>
            <option value="zalop">Zalo Personal</option>
            <option value="email">Email</option>
          </select>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className={`mr-1 size-4 ${loading ? "animate-spin" : ""}`} />
            Làm mới
          </Button>
        </div>
      </div>

      {stats.by_status && Object.keys(stats.by_status).length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.by_status).map(([k, v]) => (
            <Badge key={k} variant="outline">{k}: {v}</Badge>
          ))}
        </div>
      ) : null}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Gần đây</CardTitle>
          <CardDescription>Bấm hàng để xem nội dung đầy đủ</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex justify-center py-10">
              <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Chưa có run nào. Chat với bot agent để sinh nhật ký.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Khi</TableHead>
                    <TableHead>Kênh</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>Tools</TableHead>
                    <TableHead>ms</TableHead>
                    <TableHead>User</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow
                      key={r.id}
                      className="cursor-pointer"
                      onClick={() => setDetail(r)}
                    >
                      <TableCell className="whitespace-nowrap text-xs">
                        {timeAgo(r.created_at)}
                      </TableCell>
                      <TableCell className="text-xs">{r.channel || "—"}</TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(r.status)}>{r.status}</Badge>
                      </TableCell>
                      <TableCell className="max-w-[120px] truncate text-xs" title={r.model}>
                        {r.model || "—"}
                      </TableCell>
                      <TableCell className="max-w-[160px] truncate text-xs" title={(r.tools || []).join(", ")}>
                        {(r.tools || []).slice(0, 4).join(", ") || "—"}
                        {(r.tools || []).length > 4 ? "…" : ""}
                      </TableCell>
                      <TableCell className="text-xs">{r.duration_ms || 0}</TableCell>
                      <TableCell className="max-w-[140px] truncate text-xs" title={r.user_text}>
                        {r.user_text || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
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
              <CardTitle className="text-base">Run `{detail.id}`</CardTitle>
              <CardDescription>
                {detail.channel} · {detail.model} · {detail.steps} step(s) · {detail.duration_ms} ms
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setDetail(null)}>Đóng</Button>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <p className="font-medium">User</p>
              <pre className="mt-1 whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">{detail.user_text}</pre>
            </div>
            <div>
              <p className="font-medium">Reply</p>
              <pre className="mt-1 whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">{detail.reply_text}</pre>
            </div>
            <div>
              <p className="font-medium">Tools</p>
              <p className="text-xs text-muted-foreground">{(detail.tools || []).join(" → ") || "—"}</p>
            </div>
            {detail.error ? (
              <div>
                <p className="font-medium text-destructive">Error</p>
                <p className="text-xs">{detail.error}</p>
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
