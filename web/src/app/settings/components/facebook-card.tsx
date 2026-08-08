"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

type FbPage = { id: string; name?: string; picture?: string };

/** 📘 Facebook — kết nối Page + gắn Page theo thread.
 *
 * Token đi theo đường: dán user token (Graph API Explorer) → server đổi
 * long-lived rồi lấy page token KHÔNG hết hạn qua /me/accounts
 * (POST /api/facebook/connect). Secret nằm trong config.facebook và bị
 * settings_secrets che khi đọc — card không bao giờ thấy token thật.
 *
 * «Gắn Page theo thread»: khoá dạng `kenh:chat` hoặc `kenh:chat#topic`
 * (kenh = tg | zalo | zalop — trùng phần đầu khoá «Lọc thread», bỏ bot id).
 * Thread chưa gắn: hệ chỉ có MỘT Page thì bot dùng luôn, nhiều Page thì bot
 * bắt gắn để không đăng nhầm chỗ.
 */
export function FacebookCard() {
  const config = useSettingsStore((s) => s.config);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const loadConfig = useSettingsStore((s) => s.loadConfig);
  const secretDaDat = useSettingsStore((s) => s.secretDaDat);
  const fb = (config?.facebook as any) || {};
  const pages: FbPage[] = Array.isArray(fb.pages) ? fb.pages : [];

  const [appId, setAppId] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [userToken, setUserToken] = useState("");
  const [threadPages, setThreadPages] = useState<Record<string, string[]>>({});
  const [threadMoi, setThreadMoi] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setAppId(String(fb.app_id || ""));
    const tp = fb.thread_pages;
    setThreadPages(
      tp && typeof tp === "object"
        ? Object.fromEntries(Object.entries(tp).map(([k, v]) =>
            [k, Array.isArray(v) ? (v as unknown[]).map(String) : []]))
        : {},
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fb.app_id, fb.thread_pages]);

  // Gợi ý khoá thread từ «Lọc thread» + «Nhật ký nhóm»: bỏ bot id / user để về
  // đúng dạng kenh:chat[#topic] mà backend tra (facebook_page.pages_cho_thread).
  const goiYThread = useMemo(() => {
    const ra = new Set<string>();
    const nap = (obj: unknown) => {
      if (!obj || typeof obj !== "object") return;
      for (const k of Object.keys(obj as Record<string, unknown>)) {
        const phan = String(k).split(":");
        if (phan.length < 2) continue;
        const kenh = phan[0];
        // phần cuối không phải user id thuần (khoá user kết thúc :<uid>) —
        // lấy dạng ngắn nhất kenh:<chat[#topic]> từ phần tử thứ 2 trở đi.
        const chat = phan[phan.length - 1];
        if (!chat) continue;
        ra.add(`${kenh}:${chat}`);
        if (phan.length >= 3) ra.add(`${kenh}:${phan[phan.length - 2]}`);
      }
    };
    nap((config as any)?.thread_filters);
    nap((config as any)?.chatlog_settings);
    return [...ra].filter((k) => /^(tg|zalo|zalop):.+/.test(k)).sort();
  }, [config]);

  const facebookDayDu = (them: Record<string, unknown>) => ({
    ...fb,
    app_id: appId.trim(),
    // để trống = giữ nguyên secret đang chạy (settings_secrets.loc_ghi)
    ...(appSecret.trim() ? { app_secret: appSecret.trim() } : {}),
    ...(userToken.trim() ? { user_token: userToken.trim() } : {}),
    thread_pages: threadPages,
    ...them,
  });

  const luu = async () => {
    await saveConfig({ ...config, facebook: facebookDayDu({}) } as any);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const ketNoi = async () => {
    setBusy("connect");
    setMsg("Đang lưu cấu hình rồi đổi token…");
    try {
      await saveConfig({ ...config, facebook: facebookDayDu({}) } as any);
      const r = await request.post("/api/facebook/connect",
        { user_token: userToken.trim() });
      const d = r.data as { ok?: boolean; error?: string; pages?: FbPage[] };
      if (d.ok) {
        setMsg(`✅ Đã nối ${d.pages?.length || 0} Page — token Page không hết hạn.`);
        setUserToken("");
        await loadConfig();
      } else {
        setMsg(`❌ ${d.error || "Không kết nối được"}`);
      }
    } catch (e) {
      setMsg(`❌ ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy("");
    }
  };

  const datPage = (khoa: string, pageId: string) => {
    setThreadPages((truoc) => {
      const cu = truoc[khoa] || [];
      const moi = cu.includes(pageId)
        ? cu.filter((x) => x !== pageId) : [...cu, pageId];
      return { ...truoc, [khoa]: moi };
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>📘 Facebook Page</CardTitle>
        <CardDescription>
          Đăng bài lên Page qua chat (lệnh /facebook, gửi ảnh/video qua kênh).
          Cần một app Meta tự tạo (developers.facebook.com) — tự dùng thì khỏi
          App Review.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="text-sm">App ID</label>
            <Input value={appId} onChange={(e) => setAppId(e.target.value)}
              placeholder="Meta app ID" />
          </div>
          <div>
            <label className="text-sm">App Secret</label>
            <Input type="password" value={appSecret}
              onChange={(e) => setAppSecret(e.target.value)}
              placeholder={secretDaDat["facebook.app_secret"]
                ? "(đã đặt — để trống là giữ nguyên)" : "Meta app secret"} />
          </div>
        </div>
        <div>
          <label className="text-sm">User token (Graph API Explorer)</label>
          <Input type="password" value={userToken}
            onChange={(e) => setUserToken(e.target.value)}
            placeholder={secretDaDat["facebook.user_token_long"]
              ? "(đã nối — chỉ dán khi cần nối lại)"
              : "Dán token có pages_show_list + pages_manage_posts"} />
          <p className="text-xs text-muted-foreground mt-1">
            developers.facebook.com → Tools → Graph API Explorer → chọn app,
            cấp quyền <b>pages_show_list, pages_manage_posts, pages_read_engagement,
            business_management</b> → Generate Access Token → dán vào đây rồi bấm
            «Kết nối». Server tự đổi sang token dài hạn; token Page lấy ra
            không hết hạn.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={luu}>{saved ? "Đã lưu!" : "Lưu"}</Button>
          <Button type="button" variant="outline" disabled={busy === "connect"}
            onClick={ketNoi}>
            {busy === "connect" ? "…" : "Kết nối + nạp Page"}
          </Button>
        </div>
        {msg ? <p className="text-xs text-muted-foreground">{msg}</p> : null}

        {pages.length > 0 && (
          <div className="rounded border border-border/70 p-2 space-y-1">
            <p className="text-sm font-medium">Page đã nối ({pages.length})</p>
            {pages.map((p) => (
              <p key={p.id} className="text-xs text-muted-foreground">
                📘 {p.name || "(không tên)"} — <code>{p.id}</code>
              </p>
            ))}
          </div>
        )}

        <div className="rounded border border-dashed border-border/70 p-2 space-y-2">
          <p className="text-sm font-medium">Gắn Page theo thread</p>
          <p className="text-xs text-muted-foreground">
            Thread nào đăng được lên Page nào. Khoá dạng{" "}
            <code>kenh:chat</code> hoặc <code>kenh:chat#topic</code>{" "}
            (kenh = tg · zalo · zalop; lấy chat id bằng lệnh <code>/id</code>).
            Nhớ bật nhóm «📘 Đăng Facebook Page» trong «Lọc thread» của kênh.
          </p>
          {Object.entries(threadPages).map(([khoa, ids]) => (
            <div key={khoa}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <code className="shrink-0">{khoa}</code>
              {pages.map((p) => (
                <label key={p.id}
                  className="flex items-center gap-1 cursor-pointer select-none">
                  <input type="checkbox" className="size-3.5"
                    checked={ids.includes(p.id)}
                    onChange={() => datPage(khoa, p.id)} />
                  {p.name || p.id}
                </label>
              ))}
              <button type="button"
                className="text-muted-foreground hover:text-destructive"
                onClick={() => setThreadPages((t) => {
                  const { [khoa]: _bo, ...con } = t;
                  return con;
                })}>✕</button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Input list="fb-thread-goi-y" value={threadMoi}
              onChange={(e) => setThreadMoi(e.target.value)}
              placeholder="vd: tg:-1001234567890 hoặc zalop:zgr-abc…"
              className="max-w-xs" />
            <datalist id="fb-thread-goi-y">
              {goiYThread.map((k) => <option key={k} value={k} />)}
            </datalist>
            <Button type="button" variant="outline" size="sm"
              disabled={!/^(tg|zalo|zalop):.+/.test(threadMoi.trim())}
              onClick={() => {
                const k = threadMoi.trim();
                setThreadPages((t) => ({ ...t, [k]: t[k] || [] }));
                setThreadMoi("");
              }}>Thêm thread</Button>
          </div>
          <p className="text-[10px] text-muted-foreground">
            Nhớ bấm <b>Lưu</b> phía trên sau khi gắn.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
