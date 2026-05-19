"use client";

import { useEffect, useState } from "react";
import {
  Plug,
  Plus,
  Trash2,
  Wrench,
  RefreshCw,
  CheckCircle2,
  XCircle,
} from "lucide-react";

import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

type MCPServer = {
  id: string;
  name: string;
  url: string;
  api_key_set: boolean;
  enabled: boolean;
  transport: string;
  headers: Record<string, string>;
};

type MCPTool = {
  server_id: string;
  name: string;
  prefixed_name: string;
  description: string;
  input_schema: Record<string, unknown>;
};

type ServerForm = {
  id: string;
  name: string;
  url: string;
  api_key: string;
  enabled: boolean;
  transport: string;
};

const EMPTY_FORM: ServerForm = {
  id: "",
  name: "",
  url: "",
  api_key: "",
  enabled: true,
  transport: "http",
};

export default function MCPPage() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ServerForm>(EMPTY_FORM);
  const [savingForm, setSavingForm] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; msg: string }>>({});

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      const [srvData, toolData] = await Promise.all([
        request.get("/api/mcp/servers"),
        request.get("/api/mcp/tools").catch(() => ({ data: { tools: [] } })),
      ]);
      setServers(((srvData.data as { servers?: MCPServer[] })?.servers) || []);
      setTools(((toolData.data as { tools?: MCPTool[] })?.tools) || []);
    } catch (e) {
      console.error("Failed to load MCP servers", e);
    } finally {
      setLoading(false);
    }
  }

  function openCreateForm() {
    setForm(EMPTY_FORM);
    setShowForm(true);
  }

  function openEditForm(server: MCPServer) {
    setForm({
      id: server.id,
      name: server.name,
      url: server.url,
      api_key: "",
      enabled: server.enabled,
      transport: server.transport || "http",
    });
    setShowForm(true);
  }

  async function saveForm() {
    if (!form.url.trim()) {
      alert("URL không được trống");
      return;
    }
    setSavingForm(true);
    try {
      await request.post("/api/mcp/servers", {
        id: form.id,
        name: form.name || form.url,
        url: form.url,
        api_key: form.api_key,
        enabled: form.enabled,
        transport: form.transport,
      });
      setShowForm(false);
      await refresh();
    } catch (e) {
      alert(`Lỗi lưu: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingForm(false);
    }
  }

  async function deleteServer(id: string) {
    if (!confirm("Xóa MCP server này?")) return;
    try {
      await request.delete(`/api/mcp/servers/${id}`);
      await refresh();
    } catch (e) {
      alert(`Lỗi xóa: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function testServer(id: string) {
    setTestingId(id);
    try {
      const data = await request.post(`/api/mcp/servers/${id}/test`);
      const r = data.data as { ok?: boolean; message?: string };
      setTestResults((prev) => ({
        ...prev,
        [id]: { ok: !!r?.ok, msg: r?.message || "" },
      }));
      if (r?.ok) await refresh();
    } catch (e) {
      setTestResults((prev) => ({
        ...prev,
        [id]: { ok: false, msg: e instanceof Error ? e.message : String(e) },
      }));
    } finally {
      setTestingId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-stone-500">Đang tải...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-1 border-b border-black/[0.04] pb-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[24px] font-bold tracking-tight text-slate-900">MCP Servers</h1>
            <p className="text-[14px] text-slate-500">
              Tích hợp Model Context Protocol — tools tự động cho mọi provider
            </p>
          </div>
          <button
            type="button"
            onClick={openCreateForm}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-indigo-700"
          >
            <Plus className="size-4" />
            Thêm MCP server
          </button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {servers.map((server) => {
          const isTesting = testingId === server.id;
          const result = testResults[server.id];
          const serverTools = tools.filter((t) => t.server_id === server.id);
          return (
            <div
              key={server.id}
              className="group relative overflow-hidden rounded-[16px] p-5 card-3d card-tint-indigo transition-all duration-300 hover:-translate-y-1"
            >
              <div className="mb-3 flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <Plug className="size-5 text-indigo-500" />
                  <div>
                    <h3 className="font-semibold text-slate-900">{server.name}</h3>
                    <p className="text-xs text-slate-500 break-all">{server.url}</p>
                  </div>
                </div>
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
                    server.enabled
                      ? "bg-emerald-500/10 text-emerald-500"
                      : "bg-stone-100 text-stone-500",
                  )}
                >
                  {server.enabled ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
                  {server.enabled ? "Bật" : "Tắt"}
                </span>
              </div>

              <div className="mb-4 flex flex-wrap gap-1.5">
                <span className="rounded-md bg-slate-500/10 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                  {server.transport.toUpperCase()}
                </span>
                {server.api_key_set && (
                  <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-500">
                    API key đã set
                  </span>
                )}
                <span className="rounded-md bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-500">
                  {serverTools.length} tools
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={isTesting}
                  onClick={() => testServer(server.id)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-stone-100 px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:bg-stone-200 disabled:opacity-50"
                >
                  {isTesting ? <RefreshCw className="size-3 animate-spin" /> : <Wrench className="size-3" />}
                  {isTesting ? "Đang test..." : "Test"}
                </button>
                <button
                  type="button"
                  onClick={() => openEditForm(server)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-stone-100 px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:bg-stone-200"
                >
                  Sửa
                </button>
                <button
                  type="button"
                  onClick={() => deleteServer(server.id)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-500 transition hover:bg-red-500/20 ml-auto"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>

              {result && (
                <p className={cn("mt-2 text-xs", result.ok ? "text-emerald-500" : "text-red-500")}>
                  {result.msg}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {servers.length === 0 && (
        <div className="rounded-[16px] border border-dashed border-stone-300 p-12 text-center">
          <Plug className="mx-auto size-10 text-stone-300" />
          <p className="mt-3 text-sm text-stone-500">
            Chưa có MCP server nào. Thêm server đầu tiên để LLM có tools tự động.
          </p>
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-[16px] bg-white p-6 shadow-xl">
            <h2 className="mb-4 text-lg font-semibold text-slate-900">
              {form.id ? "Sửa MCP server" : "Thêm MCP server"}
            </h2>
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-slate-700">Tên</span>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="ai-box search"
                  className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-slate-700">URL</span>
                <input
                  type="text"
                  value={form.url}
                  onChange={(e) => setForm({ ...form, url: e.target.value })}
                  placeholder="https://api.ai-box.vn/sse"
                  className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-slate-700">API Key (tùy chọn)</span>
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder={form.id ? "(để trống nếu không đổi)" : ""}
                  className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-slate-700">Transport</span>
                <select
                  value={form.transport}
                  onChange={(e) => setForm({ ...form, transport: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                >
                  <option value="http">Streamable HTTP</option>
                  <option value="sse">SSE (cũ)</option>
                </select>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                />
                <span className="text-sm text-slate-700">Bật server này</span>
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowForm(false)}
                disabled={savingForm}
                className="rounded-lg bg-stone-100 px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-200"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={saveForm}
                disabled={savingForm}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {savingForm ? "Đang lưu..." : "Lưu"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
