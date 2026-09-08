"use client";

import { cloneElement, useCallback, useEffect, useId, useRef, useState } from "react";
import { request } from "@/lib/request";

type OAuthStatus = { status: string; expires_at?: number; can_refresh?: boolean; scope?: string; error?: string };
type ExternalMcp = {
  id: string; name: string; url: string; description?: string;
  transport?: string; enabled?: boolean; has_api_key?: boolean; header_names?: string[];
  auth_type?: string; oauth?: OAuthStatus;
};
type Report = { name: string; version?: string; protocol_version?: string; transport?: string; tools: { name: string; description: string }[] };
type Props = { showToast: (msg: string, ok?: boolean) => void };
const INPUT = "w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--ring)]";
const statusLabels: Record<string, string> = {
  connected: "Đã kết nối", pending: "Đang chờ đăng nhập", reauth_required: "Cần đăng nhập lại", disconnected: "Chưa kết nối",
};
function Field({ label, children }: { label: string; children: React.ReactElement<{ id?: string }> }) {
  const id = useId();
  return <div className="space-y-1.5"><label htmlFor={id} className="block text-sm">{label}</label>{cloneElement(children, { id })}</div>;
}

export default function ExternalTab({ showToast }: Props) {
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [headersJson, setHeadersJson] = useState("{}");
  const [transport, setTransport] = useState("auto");
  const [auth, setAuth] = useState("manual");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [scope, setScope] = useState("");
  const [valid, setValid] = useState<Report | null>(null);
  const [list, setList] = useState<ExternalMcp[]>([]);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [pending, setPending] = useState<{ id: string; url: string; deadline: number } | null>(null);
  const popup = useRef<Window | null>(null);
  const alive = useRef(true);
  const form = useRef<HTMLDivElement>(null);
  const toastRef = useRef(showToast);
  useEffect(() => { toastRef.current = showToast; }, [showToast]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const load = useCallback(async () => {
    try {
      const response = await request.get("/api/mcp/custom");
      const rows: ExternalMcp[] = response.data?.mcps || [];
      if (alive.current) { setList(rows); setLoadError(""); }
      return rows;
    } catch (error) {
      if (alive.current) setLoadError((error as Error).message);
      return null;
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!pending) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const rows = await load();
      if (stopped) return;
      const status = rows?.find((row) => row.id === pending.id)?.oauth;
      if (status?.status === "connected") {
        popup.current?.close();
        setPending(null);
        toastRef.current("Đã kết nối OAuth. Bấm Kiểm tra để xem các công cụ.");
      } else if ((rows && status?.status !== "pending") || Date.now() >= pending.deadline) {
        setPending(null);
        toastRef.current(status?.error || "Phiên đăng nhập đã kết thúc; hãy kết nối lại.", false);
      } else {
        timer = setTimeout(poll, 2000);
      }
    };
    timer = setTimeout(poll, 1500);
    return () => { stopped = true; clearTimeout(timer); };
  }, [pending, load]);

  const parsedHeaders = () => {
    const parsed: unknown = JSON.parse(headersJson || "{}");
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object" || Object.values(parsed).some((v) => typeof v !== "string")) {
      throw new Error("Headers phải là JSON object với giá trị dạng chuỗi");
    }
    return parsed as Record<string, string>;
  };
  const connection = () => ({ url: url.trim(), api_key: key.trim(), headers: parsedHeaders(), transport });
  const newId = () => "ext_" + (name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 32) || "mcp") + "_" + crypto.randomUUID().slice(0, 8);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try { await action(); } catch (error) { showToast((error as Error).message, false); }
    finally { if (alive.current) setBusy(false); }
  };
  const validate = () => run(async () => {
    setValid(null);
    const response = await request.post("/api/mcp/validate", connection());
    if (!response.data?.ok) throw new Error((response.data?.errors || ["Không kết nối được MCP"]).join(". "));
    setValid(response.data);
    if (!name) setName(response.data.name || "MCP");
  });
  const add = () => run(async () => {
    await request.post("/api/mcp/install", { ...connection(), id: newId(), name: name.trim(), description: description.trim(), url_override: url.trim() });
    showToast(`Đã thêm ${name}`);
    setValid(null); setUrl(""); setKey(""); setHeadersJson("{}"); setName(""); setDescription("");
    await load();
  });
  const connect = () => {
    // Open synchronously so the provider login isn't blocked as an unsolicited popup.
    const loginWindow = window.open("about:blank", "_blank", "popup,width=620,height=780");
    if (loginWindow) loginWindow.opener = null;
    popup.current = loginWindow;
    void run(async () => {
      try {
        const response = await request.post("/api/mcp/oauth/start", {
          id: editing || newId(), name: name.trim(), description: description.trim(),
          url: url.trim(), headers: parsedHeaders(), client_id: clientId.trim(), client_secret: clientSecret,
          preserve_headers: !!editing && Object.keys(parsedHeaders()).length === 0,
          scope: scope.trim() || null,
        });
        setClientSecret(""); setEditing(response.data.id);
        if (loginWindow && !loginWindow.closed) loginWindow.location.href = response.data.authorization_url;
        setPending({ id: response.data.id, url: response.data.authorization_url, deadline: Date.now() + 600_000 });
        await load();
      } catch (error) {
        loginWindow?.close();
        throw error;
      }
    });
  };
  const reconnect = (row: ExternalMcp) => {
    setAuth("oauth"); setEditing(row.id); setName(row.name); setDescription(row.description || ""); setUrl(row.url);
    setKey(""); setHeadersJson("{}"); setClientId(""); setClientSecret(""); setScope(row.oauth?.scope || ""); setValid(null);
    form.current?.scrollIntoView({ behavior: "smooth" });
  };
  const disconnect = (row: ExternalMcp) => run(async () => {
    await request.post(`/api/mcp/oauth/${encodeURIComponent(row.id)}/disconnect`);
    if (pending?.id === row.id) { setPending(null); popup.current?.close(); }
    showToast(`Đã ngắt kết nối ${row.name}`); await load();
  });
  const testSaved = (row: ExternalMcp) => run(async () => {
    const response = await request.post(`/api/mcp/oauth/${encodeURIComponent(row.id)}/validate`);
    await load();
    if (!response.data?.ok) throw new Error((response.data?.errors || ["Không kết nối được MCP"]).join(". "));
    showToast(`${row.name}: ${response.data.tools?.length || 0} công cụ, ${response.data.transport}`);
  });
  const remove = (row: ExternalMcp) => {
    if (!window.confirm(`Xoá MCP ${row.name}?`)) return;
    void run(async () => {
      await request.post(`/api/mcp/uninstall/${encodeURIComponent(row.id)}`);
      if (pending?.id === row.id) setPending(null);
      if (editing === row.id) setEditing(null);
      showToast(`Đã xoá ${row.name}`); await load();
    });
  };

  return <div className="space-y-4">
    <div className="card" ref={form}><div className="card-body space-y-3 max-w-xl">
      <h3 className="font-semibold">{editing ? "Kết nối lại MCP" : "Thêm MCP Server"}</h3>
      <Field label="URL MCP"><input className={INPUT} placeholder="https://example.com/mcp" value={url} onChange={(e) => { setUrl(e.target.value); setValid(null); setEditing(null); }} /></Field>
      <Field label="Tên MCP"><input className={INPUT} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Mô tả"><input className={INPUT} maxLength={1000} placeholder="Giúp AI biết khi nào nên dùng MCP này" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Xác thực"><select className={INPUT} value={auth} onChange={(e) => { setAuth(e.target.value); setValid(null); setEditing(null); }}>
        <option value="manual">Không xác thực / API key / Headers</option><option value="oauth">OAuth — đăng nhập tài khoản</option>
      </select></Field>
      {auth === "oauth" ? <>
        <p className="text-sm text-[var(--muted-foreground)]">Đăng nhập trên trang nhà cung cấp để cấp quyền cho MCP qua Streamable HTTP. Token được lưu mã hóa trên máy chủ và tự gia hạn nếu nhà cung cấp hỗ trợ.</p>
        <details><summary className="cursor-pointer text-sm">Cấu hình OAuth nâng cao</summary><div className="space-y-3 mt-3">
          <p className="text-xs text-[var(--muted-foreground)]">Để trống nếu nhà cung cấp cho phép tự đăng ký. Với client riêng, đăng ký callback tại origin API + /api/mcp/oauth/callback.</p>
          <Field label="Client ID"><input className={INPUT} autoComplete="off" value={clientId} onChange={(e) => setClientId(e.target.value)} /></Field>
          <Field label="Client Secret (nếu cần)"><input type="password" className={INPUT} autoComplete="new-password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} /></Field>
          <Field label="Scope (cách nhau bằng dấu cách)"><input className={INPUT} placeholder="Để trống: dùng quyền nhà cung cấp yêu cầu" value={scope} onChange={(e) => setScope(e.target.value)} /></Field>
        </div></details>
      </> : <>
        <Field label="Transport"><select className={INPUT} value={transport} onChange={(e) => { setTransport(e.target.value); setValid(null); }}>
          <option value="auto">Tự nhận dạng (khuyên dùng)</option><option value="streamable_http">Streamable HTTP</option><option value="sse">HTTP + SSE cũ</option>
        </select></Field>
        <Field label="Bearer/API Key (nếu cần)"><input type="password" className={INPUT} value={key} onChange={(e) => { setKey(e.target.value); setValid(null); }} /></Field>
      </>}
      <Field label="Custom headers (JSON)"><textarea className={`${INPUT} min-h-24 font-mono`} value={headersJson} onChange={(e) => { setHeadersJson(e.target.value); setValid(null); }} /></Field>
      {editing && <p className="text-xs text-[var(--muted-foreground)]">Để headers rỗng để giữ các header đã lưu.</p>}
      <div className="flex gap-2">
        {auth === "oauth" ? <button disabled={busy || !url.trim() || !name.trim() || !!pending} className="btn btn-primary" onClick={connect}>{busy ? "Đang xử lý…" : "Kết nối OAuth"}</button>
          : <button disabled={busy || !url.trim()} className="btn btn-primary" onClick={validate}>{busy ? "Đang kiểm tra…" : "Kiểm tra"}</button>}
        {editing && <button className="btn" disabled={busy || !!pending} onClick={() => { setEditing(null); setUrl(""); setName(""); setClientId(""); setClientSecret(""); }}>Thêm MCP khác</button>}
      </div>
      {pending && <p role="status" className="text-sm">Đang chờ đăng nhập. <a className="underline" href={pending.url} target="_blank" rel="noopener noreferrer">Mở trang đăng nhập</a> nếu cửa sổ chưa xuất hiện.</p>}
      {valid && auth === "manual" && <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 space-y-2">
        <p className="text-sm text-emerald-600">{valid.name} {valid.version} · {valid.tools.length} công cụ</p>
        <p className="text-xs text-[var(--muted-foreground)]">{valid.transport} · MCP {valid.protocol_version || "legacy"}</p>
        <button disabled={busy || !name.trim()} className="btn btn-primary" onClick={add}>Thêm MCP</button>
      </div>}
    </div></div>
    <div className="card"><div className="card-body">
      <div className="flex justify-between mb-3"><h3 className="font-semibold">External MCPs đã thêm</h3><button className="text-sm underline" onClick={() => void load()}>Làm mới</button></div>
      {loadError && <p role="alert" className="text-sm text-red-500">{loadError}</p>}
      <div className="space-y-2">
        {!list.length && !loadError && <p className="text-sm text-[var(--muted-foreground)]">Chưa có.</p>}
        {list.map((row) => <div key={row.id} className="rounded-lg border border-[var(--border)] p-3 space-y-2">
          <div className="flex gap-2 flex-wrap items-center"><span className="text-sm font-medium">{row.name}</span>
            {row.oauth && <span className={`text-xs rounded px-2 py-1 ${row.oauth.status === "connected" ? "bg-emerald-500/10 text-emerald-600" : "bg-amber-500/10 text-amber-600"}`}>OAuth · {statusLabels[row.oauth.status] || row.oauth.status}</span>}
            {row.enabled === false && <span className="text-xs">Đang tắt</span>}
          </div>
          <p className="text-xs text-[var(--muted-foreground)] break-all">{row.url}</p>
          {row.description && <p className="text-sm">{row.description}</p>}
          <p className="text-xs text-[var(--muted-foreground)]">{row.transport || "auto"}{row.has_api_key ? " · Bearer" : ""}{row.header_names?.length ? ` · ${row.header_names.join(", ")}` : ""}</p>
          {row.oauth?.expires_at && <p className="text-xs">Token hết hạn: {new Date(row.oauth.expires_at * 1000).toLocaleString("vi-VN")}{row.oauth.can_refresh ? " · Tự gia hạn" : ""}</p>}
          {row.oauth?.scope && <p className="text-xs break-all">Quyền: {row.oauth.scope}</p>}
          {row.oauth?.error && <p className="text-xs text-red-500">{row.oauth.error}</p>}
          <div className="flex gap-2 flex-wrap text-xs">
            {row.oauth && <>
              {row.oauth.status === "connected" && <button disabled={busy} className="btn" onClick={() => void testSaved(row)}>Kiểm tra</button>}
              <button disabled={busy || !!pending} className="btn" onClick={() => reconnect(row)}>{row.oauth.status === "connected" ? "Đổi tài khoản" : "Kết nối lại"}</button>
              {["connected", "pending", "reauth_required"].includes(row.oauth.status) && <button disabled={busy} className="btn" onClick={() => void disconnect(row)}>{row.oauth.status === "pending" ? "Hủy đăng nhập" : "Ngắt kết nối"}</button>}
            </>}
            <button disabled={busy} className="ml-auto px-2 py-1 rounded-md bg-red-500/10 text-red-500" onClick={() => remove(row)}>Xoá</button>
          </div>
        </div>)}
      </div>
    </div></div>
  </div>;
}
