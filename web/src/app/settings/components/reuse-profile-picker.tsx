"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { request } from "@/lib/request";

type CSCfg = { url: string; apiKey: string };

// Browser profiles that are NOT real Google-account sessions (system / tool
// profiles) — hidden from the reuse picker so users only see real accounts.
const SYSTEM_PROFILES = new Set([
  "default", "nopecha",
  "stealth-check", "cfdemo",
]);

// Keep only profiles that look like a real onboarded Google account, dropping
// junk/test/probe dirs and invalid names (e.g. "chatgpt-*", names with a comma
// from a stray account-type label, probes, test-onboard-*, *-default).
function isAccountProfile(n: string): boolean {
  if (!n) return false;
  if (/[,*\s]/.test(n)) return false; // junk: comma / asterisk / whitespace
  if (SYSTEM_PROFILES.has(n)) return false;
  if (/(^|[-_])default$/i.test(n)) return false; // default, gemini-web-default
  if (/^diag\d*$/i.test(n)) return false;
  if (/^pn-/i.test(n)) return false;
  if (/(^|-)probe\d*$/i.test(n)) return false; // chatgpt-probe, -probe2
  if (/^test[-_]|[-_]test$|^nonexistent/i.test(n)) return false; // test-*, *-test
  if (/^github-/i.test(n) || /^codex-/i.test(n) || /^chatgpt-/i.test(n)) return false; // non-google accounts
  // `openai-*` là tài khoản OpenAI GỐC — không có tài khoản Google nào phía
  // sau, nên mọi thứ ô chọn này làm được (tái dùng phiên Google cho Flow /
  // ChatGPT / Gemini / Claude) đều không áp dụng. Để nó lọt vào danh sách chỉ
  // sinh ra hai chuyện: người dùng chọn nhầm rồi nhận lỗi khó hiểu, và MỘT tài
  // khoản hiện thành HAI dòng khi trên đĩa có cả `google-<tên>` lẫn
  // `openai-<tên>` (đo 29/08/2026: bios-disused99-6e84t67f hiện đúng hai lần).
  if (/^openai-/i.test(n)) return false;
  return true;
}

// ── Nguồn sự thật DUY NHẤT cho danh sách hồ sơ ──────────────────────────────
// Trang Settings gắn NĂM ô chọn (Flow, ChatGPT, Gemini Web API, Claude, "Tái
// dùng tất cả") và các thẻ khác gắn thêm nữa. Bản cũ cho mỗi ô một `useState`
// riêng, chỉ nạp lúc mount và chỉ nạp lại sau khi CHÍNH NÓ xoá — nên xoá ở ô
// này thì các ô kia vẫn hiện tên đã xoá cho tới khi tải lại trang.
//
// Đo thật 29/08/2026: đĩa máy chủ có đúng 12 hồ sơ hợp lệ; ô ChatGPT hiện 12,
// ô Gemini hiện 17 — thừa năm cái `google-AngianoLandro8821`,
// `google-DegaustGellert3920`, `google-ErkerSchopper0973`,
// `google-MorkveJorie191`, `google-StelmackMalagarie974` không còn tồn tại
// trên đĩa.
//
// Một kho dùng chung + danh sách người nghe: mọi ô cùng đọc một mảng, và một
// lượt nạp phục vụ cả trang (bản cũ bắn năm request giống hệt nhau mỗi lần mở).
let khoDanhSach: string[] = [];
let khoDangTai = false;
let dangNap: Promise<void> | null = null;
const nguoiNghe = new Set<() => void>();

function bao() {
  for (const f of nguoiNghe) f();
}

function napKho(cs: CSCfg): Promise<void> {
  if (!cs.url) return Promise.resolve();
  if (dangNap) return dangNap; // gộp các lượt nạp trùng nhau trong cùng một nhịp
  khoDangTai = true;
  bao();
  dangNap = (async () => {
    try {
      const res = await request.get(`${cs.url}/v1/session/list`);
      khoDanhSach = ((res.data?.profiles || []) as { name?: string }[])
        .map((p) => p.name || "")
        .filter(isAccountProfile)
        .sort();
    } catch (e: any) {
      // KHÔNG nuốt im. Bản cũ `catch { /* network blip — leave list as-is */ }`
      // giữ nguyên danh sách cũ mà không để lại dấu vết nào, nên một danh sách
      // quá hạn trông y hệt một danh sách vừa nạp xong.
      //
      // Và báo ở ĐÂY chứ không phải trong `useEffect` của từng ô: trang có năm
      // ô chọn, báo trong component là năm toast giống hệt nhau cho cùng MỘT
      // lần nạp hỏng. Kho là một, lượt nạp là một, nên lời báo cũng là một.
      toast.error(`Không tải được danh sách profile: ${String(e?.message || e)}`);
    } finally {
      khoDangTai = false;
      dangNap = null;
      bao();
    }
  })();
  return dangNap;
}

/**
 * Shared "reuse an already-onboarded profile" control.
 *
 * Lists the captcha-solver browser profiles (each = one Google account that
 * already has a live session) and lets the user pick one + click "Tái dùng".
 * The parent card supplies `onReuse(profile)` with its own provider-specific
 * logic (ChatGPT → add token to pool, Gemini → save config, Flow → add
 * account). This powers "Cách A": log in any provider first, then add the
 * others on the SAME profile without re-entering email/password.
 */
export function ReuseProfilePicker({
  cs,
  onReuse,
}: {
  cs: CSCfg;
  onReuse: (profile: string) => Promise<void>;
}) {
  // Danh sách đọc từ kho dùng chung; chỉ ô ĐANG CHỌN là của riêng mỗi ô.
  const [, veLai] = useState(0);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const profiles = khoDanhSach;
  const loading = khoDangTai;

  useEffect(() => {
    const f = () => veLai((n) => n + 1);
    nguoiNghe.add(f);
    return () => {
      nguoiNghe.delete(f);
    };
  }, []);

  useEffect(() => {
    void napKho(cs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cs.url, cs.apiKey]);

  // Tên đang chọn biến mất khỏi danh sách (ô khác vừa xoá nó) thì nhảy về tên
  // đầu tiên, đừng để nút "Tái dùng" trỏ vào một hồ sơ không còn tồn tại.
  useEffect(() => {
    setSelected((s) => (s && profiles.includes(s) ? s : profiles[0] || ""));
  }, [profiles]);

  // Delete the browser SESSION (user-data-dir) of the selected profile. This is
  // the only place a session is removed deliberately — it logs the Google
  // account out of EVERY provider sharing the profile, but never touches the
  // saved-credential vault or any provider's pool entry.
  async function deleteSession() {
    if (!selected || !cs.url) return;
    const ok = window.confirm(
      `Xóa session "${selected}"?\n\n` +
      `Tài khoản Google này sẽ bị ĐĂNG XUẤT khỏi MỌI provider dùng chung profile ` +
      `(ChatGPT / Flow / Gemini Web). KHÔNG xóa credential đã lưu — vẫn onboard lại được.`,
    );
    if (!ok) return;
    setBusy(true);
    try {
      await request.delete(`${cs.url}/v1/profiles/${encodeURIComponent(selected)}`);
      toast.success(`Đã xóa session ${selected}`);
      await napKho(cs);
    } catch (e: any) {
      toast.error(`Xóa session lỗi: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <select
        className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        disabled={busy || loading}
      >
        {profiles.length === 0 && (
          <option value="">{loading ? "Đang tải…" : "(chưa có profile)"}</option>
        )}
        {profiles.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={() => void napKho(cs)}
        disabled={busy || loading}
        title="Tải lại danh sách profile"
      >
        <RefreshCw className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        onClick={async () => {
          if (!selected) return;
          setBusy(true);
          try {
            await onReuse(selected);
          } finally {
            setBusy(false);
          }
        }}
        disabled={busy || loading || !selected}
      >
        {busy ? <LoaderCircle className="mr-1 h-4 w-4 animate-spin" /> : null}
        Tái dùng
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={() => void deleteSession()}
        disabled={busy || loading || !selected}
        title="Xóa session (đăng xuất Google khỏi MỌI provider dùng profile này — không xóa credential đã lưu)"
        className="border-rose-200 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
}
