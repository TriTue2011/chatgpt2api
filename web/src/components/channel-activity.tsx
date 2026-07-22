"use client";

/**
 * Bảng "Hoạt động gần đây + Blacklist" DÙNG CHUNG cho các kênh chat.
 * Blacklist THEO TỪNG BOT / TÀI KHOẢN (account = bot_id hoặc ownId).
 * Mục không có account = blacklist CHUNG cả kênh (tương thích cũ).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "@/lib/request";
import { RefreshCw, Ban, Trash2, UserX, Users, User } from "lucide-react";

type Platform = "zalop" | "zalo" | "tg";

type RecentRow = {
  platform: string; account: string; chat_id: string; chat_name: string;
  user_id: string; user_name: string; is_group: boolean; text: string; ts: number;
};
type BlacklistItem = { id: string; kind: string; name: string; account?: string };

function timeAgo(ts: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - (ts || 0)));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

function botIdFromToken(token: string): string {
  return String(token || "").split(":")[0].trim();
}

export function ChannelActivityPanel({ platform, title }: { platform: Platform; title?: string }) {
  const [rows, setRows] = useState<RecentRow[]>([]);
  const [black, setBlack] = useState<BlacklistItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string>("");
  const [newId, setNewId] = useState("");
  const [newKind, setNewKind] = useState("chat");
  /** "" = chung cả kênh; "__all__" = xem mọi mục; else bot_id/ownId */
  const [accountScope, setAccountScope] = useState<string>("");
  const [accountOptions, setAccountOptions] = useState<{ value: string; label: string }[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadAccounts = useCallback(async () => {
    const opts: { value: string; label: string }[] = [
      { value: "", label: "Chung (cả kênh)" },
    ];
    try {
      if (platform === "zalop") {
        const res = await request.get("/api/zalo-personal/accounts");
        const list = (res.data?.accounts as any[]) || [];
        for (const a of list) {
          const id = String(a?.ownId || "").trim();
          if (!id) continue;
          const name = String(a?.displayName || "").trim();
          const phone = String(a?.phoneNumber || "").trim();
          const label = name && phone ? `${name} · ${phone}` : (name || phone || "Tài khoản Zalo");
          opts.push({ value: id, label });
        }
      } else {
        const res = await request.get("/api/settings");
        const cfg = res.data || {};
        const bots = (platform === "tg" ? cfg.telegram_bots : cfg.zalo_bots) as any[] | undefined;
        if (Array.isArray(bots)) {
          for (const b of bots) {
            const id = botIdFromToken(String(b?.token || ""));
            if (!id) continue;
            opts.push({
              value: id,
              label: b?.enabled === false ? `${id} (tắt)` : id,
            });
          }
        }
      }
    } catch {
      /* ignore */
    }
    setAccountOptions(opts);
  }, [platform]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // account set → API trả mục của bot + mục chung; trống → mọi mục platform
      const accParam =
        accountScope && accountScope !== "__all__"
          ? `&account=${encodeURIComponent(accountScope)}`
          : "";
      const [r, b] = await Promise.all([
        request.get(`/api/channels/recent?platform=${platform}&limit=100`),
        request.get(`/api/channels/blacklist?platform=${platform}${accParam}`),
      ]);
      let items = (b.data?.items as BlacklistItem[]) || [];
      // "Chung" (accountScope === "") → chỉ mục không gắn bot
      if (accountScope === "") {
        items = items.filter((it) => !it.account);
      }
      setRows((r.data?.rows as RecentRow[]) || []);
      setBlack(items);
      setMsg("");
    } catch (e) {
      setMsg(`Lỗi tải: ${e instanceof Error ? e.message : e}`);
    } finally {
      setLoading(false);
    }
  }, [platform, accountScope]);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    void load();
    timer.current = setInterval(() => void load(), 20000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load]);

  const scopeForAdd = (rowAccount?: string) => {
    // Prefer explicit scope (not __all__), else row's account, else chung
    if (accountScope && accountScope !== "__all__") return accountScope;
    if (rowAccount) return rowAccount;
    return "";
  };

  const addBlack = async (id: string, kind: string, name: string, rowAccount?: string) => {
    if (!id.trim()) return;
    const account = scopeForAdd(rowAccount);
    try {
      const r = await request.post("/api/channels/blacklist", {
        platform,
        id: id.trim(),
        kind,
        name,
        account,
      });
      setMsg(
        r.data?.ok
          ? r.data?.already
            ? "Đã có trong blacklist bot/acc này"
            : `Đã chặn ✓${account ? ` (bot/acc ${account})` : " (chung kênh)"}`
          : r.data?.error || "Chặn thất bại",
      );
      setNewId("");
      void load();
    } catch (e) {
      setMsg(`Lỗi: ${e instanceof Error ? e.message : e}`);
    }
  };

  const removeBlack = async (id: string, account?: string) => {
    try {
      await request.delete("/api/channels/blacklist", {
        data: { platform, id, account: account || "" },
      });
      setMsg("Đã gỡ khỏi blacklist");
      void load();
    } catch (e) {
      setMsg(`Lỗi: ${e instanceof Error ? e.message : e}`);
    }
  };

  const isRowBlack = (r: RecentRow) => {
    const acc = r.account || "";
    return black.some((b) => {
      const bacc = b.account || "";
      // Mục gắn bot chỉ áp đúng bot; mục chung (account rỗng) áp mọi bot
      if (bacc && bacc !== acc) return false;
      return b.id === r.chat_id || (!!r.user_id && b.id === r.user_id);
    });
  };

  const filteredRows =
    accountScope && accountScope !== "__all__"
      ? rows.filter((r) => !r.account || r.account === accountScope)
      : rows;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <h4 className="text-sm font-semibold flex-1 min-w-[8rem]">
          {title || "Hoạt động gần đây & Blacklist"}
        </h4>
        {msg && (
          <span className="text-[10px] text-muted-foreground max-w-[40%] truncate">{msg}</span>
        )}
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={`size-3 ${loading ? "animate-spin" : ""}`} /> Làm mới
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="text-[10px] text-muted-foreground shrink-0">Bot / tài khoản:</label>
        <select
          value={accountScope}
          onChange={(e) => setAccountScope(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs max-w-full"
        >
          <option value="__all__">Tất cả (xem blacklist + hoạt động)</option>
          {accountOptions.map((o) => (
            <option key={o.value || "_global"} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="text-[10px] text-muted-foreground">
          Chặn / gỡ áp theo bot đang chọn (Chung = cả kênh).
        </span>
      </div>

      {/* Recent */}
      <div className="rounded-md border border-border">
        <div className="border-b border-border px-3 py-1.5 text-[11px] font-medium text-muted-foreground">
          Ai vừa nhắn ({filteredRows.length}) — tài khoản · Chat ID · User ID · lần gần nhất
        </div>
        <div className="max-h-72 overflow-y-auto divide-y divide-border">
          {filteredRows.length === 0 && (
            <p className="px-3 py-3 text-xs text-muted-foreground">
              Chưa có hoạt động nào được ghi nhận.
              {platform === "zalo" && (
                <>
                  {" "}
                  Lưu ý: trong <b>nhóm</b>, Zalo chỉ giao tin cho bot khi tin nhắn <b>@tag bot</b> —
                  vào nhóm, @tag bot rồi nhắn <code>/id</code> để bot báo Chat ID nhóm + User ID người
                  gửi.
                </>
              )}
            </p>
          )}
          {filteredRows.map((r) => {
            const isBlack = isRowBlack(r);
            return (
              <div
                key={`${r.account}|${r.chat_id}|${r.user_id}`}
                className={`px-3 py-2 text-xs ${isBlack ? "opacity-50" : ""}`}
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5">
                    {r.is_group ? <Users className="size-3" /> : <User className="size-3" />}
                    {r.is_group ? "Nhóm" : "Cá nhân"}
                  </span>
                  <span className="font-medium">{r.user_name || r.chat_name || "(không tên)"}</span>
                  <span className="text-muted-foreground">· {timeAgo(r.ts)} trước</span>
                  <span className="flex-1" />
                  {!isBlack && (
                    <>
                      <button
                        type="button"
                        title="Chặn nhóm/chat trên bot/acc này"
                        onClick={() =>
                          void addBlack(
                            r.chat_id,
                            r.is_group ? "chat" : "user",
                            r.chat_name || r.user_name,
                            r.account,
                          )
                        }
                        className="inline-flex items-center gap-1 rounded border border-red-400/40 px-1.5 py-0.5 text-red-500 hover:bg-red-400/10"
                      >
                        <Ban className="size-3" /> Chặn {r.is_group ? "nhóm" : "chat"}
                      </button>
                      {r.is_group && r.user_id && (
                        <button
                          type="button"
                          title="Chặn riêng người gửi trên bot/acc này"
                          onClick={() => void addBlack(r.user_id, "user", r.user_name, r.account)}
                          className="inline-flex items-center gap-1 rounded border border-amber-400/40 px-1.5 py-0.5 text-amber-600 hover:bg-amber-400/10"
                        >
                          <UserX className="size-3" /> Chặn user
                        </button>
                      )}
                    </>
                  )}
                  {isBlack && <span className="text-[10px] text-red-500">đã chặn</span>}
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
                  <span>
                    Tài khoản: <code>{r.account || "—"}</code>
                  </span>
                  <span>
                    Chat ID: <code>{r.chat_id}</code>
                  </span>
                  <span>
                    User ID: <code>{r.user_id || "—"}</code>
                  </span>
                </div>
                {r.text && (
                  <div className="mt-0.5 truncate text-[11px] text-muted-foreground">💬 {r.text}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Blacklist */}
      <div className="rounded-md border border-border">
        <div className="border-b border-border px-3 py-1.5 text-[11px] font-medium text-muted-foreground">
          Blacklist ({black.length}) — không nhận / không hiển thị
          {accountScope && accountScope !== "__all__"
            ? accountScope
              ? ` · bot/acc ${accountScope}`
              : " · chung kênh"
            : ""}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
          <select
            value={newKind}
            onChange={(e) => setNewKind(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs"
          >
            <option value="chat">Nhóm/Chat</option>
            <option value="user">Cá nhân</option>
          </select>
          <input
            value={newId}
            onChange={(e) => setNewId(e.target.value)}
            placeholder="Nhập Chat ID hoặc User ID để chặn"
            className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-xs"
          />
          <button
            type="button"
            onClick={() => void addBlack(newId, newKind, "")}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            <Ban className="size-3" /> Chặn
          </button>
        </div>
        <div className="max-h-48 overflow-y-auto divide-y divide-border">
          {black.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">Chưa chặn ai.</p>
          )}
          {black.map((b) => (
            <div
              key={`${b.account || ""}|${b.id}`}
              className="flex items-center gap-2 px-3 py-1.5 text-xs"
            >
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                {b.kind === "user" ? "Cá nhân" : "Nhóm"}
              </span>
              <span className="rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-mono max-w-[7rem] truncate"
                title={b.account || "chung"}>
                {b.account || "chung"}
              </span>
              {b.name && <span className="font-medium">{b.name}</span>}
              <code className="flex-1 truncate text-muted-foreground">{b.id}</code>
              <button
                type="button"
                onClick={() => void removeBlack(b.id, b.account || "")}
                className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 hover:bg-muted"
              >
                <Trash2 className="size-3" /> Gỡ
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
