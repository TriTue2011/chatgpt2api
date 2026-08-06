"use client";

/**
 * «Lưu trữ online» — mỗi thread lưu tệp vào tài khoản/thư mục nào.
 *
 * Đi cùng nếp «Nhật ký nhóm»: mặc định TẮT, khai theo phạm vi, danh sách chọn
 * lấy từ chính «Lọc thread» chứ không dựng danh sách thứ hai để chủ máy phải
 * đặt tên hai lần. Khoá phải khớp CHÍNH XÁC
 * services/agent/luu_tru_online._cac_khoa_cai_dat.
 *
 * Ghi ra config `luu_tru_online`.
 */

import { useEffect, useState } from "react";
import { Cloud, FolderOpen, LoaderCircle, Plus, Save, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { request } from "@/lib/request";

import { useSettingsStore } from "../store";

type ThanhVien = { kenh: string; chat: string; topic: string; user: string };
type KhoDocDuoc = { kho: string; thu_muc: string; cua_minh: boolean };
type CaiDat = {
  enabled?: boolean;
  kho?: string;
  thu_muc?: string;
  hoi_truoc?: boolean;
  giu_ngay?: Record<string, number>;
  gio_dong_bo?: string;
  /** Thread admin nhận câu hỏi xác nhận. Nhiều admin thì phải chỉ rõ ai. */
  thread_admin?: string;
};

const NHAN_KENH: Record<string, string> = {
  tg: "Telegram", zalo: "Zalo Bot", zalop: "Zalo cá nhân", mail: "Email",
};

/** Phải khớp services/agent/luu_tru_online.CAC_MUC. Mỗi mục một thư mục riêng
 *  trên đám mây, và hạn giữ đặt riêng từng mục. */
const CAC_MUC = ["PDF", "Word", "Excel", "PowerPoint", "Nhật ký", "Ảnh", "Khác"];
const GIU_MAC_DINH = 365;

/** Khoá «Lọc thread» → thành viên (bỏ bot/account). Giống chatlog + memory-links. */
function tachKhoa(key: string, laNguoi: boolean): ThanhVien | null {
  const parts = String(key || "").split(":");
  if (parts.length < 2) return null;
  const kenh = parts[0];
  let user = "";
  let con = parts.slice(1);
  if (laNguoi) {
    user = con[con.length - 1] || "";
    con = con.slice(0, -1);
  }
  const chatPart = con.length >= 2 ? con.slice(1).join(":") : (con[0] || "");
  if (!chatPart) return null;
  const i = kenh === "tg" ? chatPart.indexOf("#") : -1;
  const chat = i >= 0 ? chatPart.slice(0, i) : chatPart;
  const topic = i >= 0 ? chatPart.slice(i + 1) : "";
  return { kenh, chat, topic, user };
}

function khoaLuuTru(tv: ThanhVien): string {
  let k = tv.kenh;
  if (tv.chat) {
    k += `:${tv.chat}`;
    if (tv.topic) k += `#${tv.topic}`;
    if (tv.user) k += `:${tv.user}`;
  }
  return k;
}

function nhan(tv: ThanhVien, ten?: string): string {
  const kenh = NHAN_KENH[tv.kenh] || tv.kenh;
  if (!tv.chat) return `Cả kênh ${kenh}`;
  const dich = tv.chat + (tv.topic ? ` › topic ${tv.topic}` : "")
    + (tv.user ? ` › người ${tv.user}` : "");
  return ten ? `${ten} · ${kenh} ${dich}` : `${kenh} ${dich}`;
}

export function LuuTruOnlineCard() {
  const config = useSettingsStore((s) => s.config);
  const setField = useSettingsStore((s) => s.setField);
  const saveConfig = useSettingsStore((s) => s.saveConfig);
  const isSavingConfig = useSettingsStore((s) => s.isSavingConfig);

  const cfg = (config || {}) as Record<string, unknown>;
  const settings = (cfg.luu_tru_online || {}) as Record<string, CaiDat>;
  const tf = (cfg.thread_filters || {}) as Record<string, unknown>;
  const tuf = (cfg.thread_user_filters || {}) as Record<string, unknown>;
  const meta = (cfg.thread_filter_meta || {}) as Record<string, { name?: string }>;

  const [khoCo, setKhoCo] = useState<string[]>([]);
  /** Phạm vi nào đọc được kho nào — máy chủ tính, giao diện chỉ hiện.
   *  Tự suy từ `memory_links` ở đây là hai nơi cùng quyết định quyền đọc, và
   *  lệch nhau thì hiển thị nói một đằng bot làm một nẻo. */
  const [banDo, setBanDo] = useState<Record<string, KhoDocDuoc[]>>({});
  const [dangTai, setDangTai] = useState(true);
  const [chonThem, setChonThem] = useState("");
  /** Phạm vi nào đang mở. Mặc định GẤP phạm vi đã chọn kho — mỗi khối chiếm gần
   *  một màn hình nên để mở hết là phải cuộn rất lâu. */
  const [moRong, setMoRong] = useState<Record<string, boolean>>({});
  /** Thư mục có sẵn trên từng kho — nạp khi bấm «Chọn», để khỏi gõ tay tên thư mục. */
  const [thuMucCua, setThuMucCua] = useState<Record<string, string[]>>({});
  const [dangDoc, setDangDoc] = useState("");

  const napThuMuc = async (kho: string) => {
    if (!kho) return;
    setDangDoc(kho);
    try {
      const { data } = await request.get("/api/rclone/ls", { params: { duong_dan: `${kho}:` } });
      const ds = (Array.isArray(data?.muc) ? data.muc : [])
        .filter((m: { la_thu_muc: boolean }) => m.la_thu_muc)
        .map((m: { ten: string }) => m.ten);
      setThuMucCua((s) => ({ ...s, [kho]: ds }));
    } catch { setThuMucCua((s) => ({ ...s, [kho]: [] })); } finally { setDangDoc(""); }
  };

  useEffect(() => {
    let huy = false;
    request.get("/api/rclone/status")
      .then(({ data }) => {
        if (huy) return;
        const ds = Array.isArray(data?.remotes) ? data.remotes : [];
        setKhoCo(ds.map((r: { name: string }) => r.name));
      })
      .catch(() => { /* chưa có rclone thì để danh sách rỗng, có nhắc bên dưới */ })
      .finally(() => { if (!huy) setDangTai(false); });
    request.get("/api/rclone/kho-doc-duoc")
      .then(({ data }) => { if (!huy) setBanDo(data?.ban_do || {}); })
      .catch(() => { /* chưa lưu cấu hình thì chưa có bản đồ — không sao */ });
    return () => { huy = true; };
  }, [settings]);

  // Danh sách chọn: ba «cả kênh» + nhóm/topic/người lấy từ «Lọc thread».
  const opts: { key: string; label: string }[] = [];
  const daCo = new Set<string>();
  for (const k of ["tg", "zalo", "zalop"]) {
    opts.push({ key: k, label: `Cả kênh ${NHAN_KENH[k]}` });
    daCo.add(k);
  }
  for (const [key, laNguoi] of [
    ...Object.keys(tf).map((k) => [k, false] as [string, boolean]),
    ...Object.keys(tuf).map((k) => [k, true] as [string, boolean]),
  ]) {
    const tv = tachKhoa(key, laNguoi);
    if (!tv) continue;
    const kk = khoaLuuTru(tv);
    if (daCo.has(kk)) continue;
    daCo.add(kk);
    opts.push({ key: kk, label: nhan(tv, meta[key]?.name) });
  }
  const nhanMap = new Map(opts.map((o) => [o.key, o.label]));

  const setEntry = (key: string, patch: CaiDat) =>
    setField("luu_tru_online", {
      ...settings,
      [key]: { enabled: true, hoi_truoc: true, ...settings[key], ...patch },
    });

  const setGiu = (key: string, muc: string, so: number) => {
    const cu = settings[key]?.giu_ngay || {};
    setEntry(key, { giu_ngay: { ...cu, [muc]: Math.max(0, so || 0) } });
  };

  const xoa = (key: string) => {
    const next = { ...settings };
    delete next[key];
    setField("luu_tru_online", next);
  };

  const them = () => {
    if (!chonThem || settings[chonThem]) return;
    setField("luu_tru_online", {
      ...settings,
      [chonThem]: { enabled: true, hoi_truoc: true, kho: khoCo[0] || "", thu_muc: "",
                    gio_dong_bo: "03:00" },
    });
    setChonThem("");
  };

  const entries = Object.entries(settings);

  return (
    <Card className="rounded-2xl card-3d card-tint-slate">
      <CardContent className="space-y-5 p-6">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-[var(--secondary)]">
            <Cloud className="size-5 text-[var(--muted-foreground)]" />
          </div>
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Lưu trữ online theo thread</h2>
            <p className="text-sm text-[var(--muted-foreground)]">
              Mỗi nhóm/người lưu tệp vào một tài khoản đám mây riêng. Mặc định tắt — bật từng chỗ.
            </p>
          </div>
        </div>

        {dangTai ? (
          <div className="flex justify-center py-6">
            <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : khoCo.length === 0 ? (
          <p className="rounded-xl border border-[var(--border)] bg-[var(--secondary)] px-4 py-3 text-sm">
            Chưa khai kho nào. Lên mục <strong>Kho lưu trữ đám mây</strong> phía trên thêm tài khoản trước đã,
            rồi quay lại đây gán cho từng thread.
          </p>
        ) : null}

        {/* Thêm phạm vi */}
        <div className="flex flex-wrap items-center gap-2">
          <select value={chonThem} onChange={(e) => setChonThem(e.target.value)}
            className="h-10 min-w-64 flex-1 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm">
            <option value="">— Chọn nhóm / người / cả kênh —</option>
            {opts.filter((o) => !settings[o.key]).map((o) => (
              <option key={o.key} value={o.key}>{o.label}</option>
            ))}
          </select>
          <Button variant="outline" className="h-10 rounded-xl" onClick={them} disabled={!chonThem}>
            <Plus className="size-4" /> Thêm
          </Button>
        </div>

        {entries.length === 0 ? (
          <p className="text-sm text-[var(--muted-foreground)]">
            Chưa phạm vi nào bật lưu trữ online.
          </p>
        ) : null}

        {entries.map(([key, cd]) => {
          // Mở sẵn phạm vi CHƯA chọn kho (đang dựng dở); phạm vi đã xong thì gấp
          // lại — mỗi phạm vi chiếm gần một màn hình, ba phạm vi là phải cuộn mãi
          // mới tới nút thêm.
          const mo = moRong[key] ?? !cd.kho;
          return (
          <div key={key} className="space-y-3 rounded-xl border border-[var(--border)] p-4">
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" aria-label={mo ? "Thu gọn" : "Mở rộng"}
                className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-[var(--border)] text-xs text-[var(--muted-foreground)]"
                onClick={() => setMoRong((s) => ({ ...s, [key]: !mo }))}>
                {mo ? "▾" : "▸"}
              </button>
              <label className="flex items-center gap-2 text-sm font-medium">
                <input type="checkbox" checked={cd.enabled !== false}
                  onChange={(e) => setEntry(key, { enabled: e.target.checked })} />
                {nhanMap.get(key) || key}
              </label>
              {/* Lúc gấp vẫn phải biết nó đang lưu đi đâu, và thiếu gì. */}
              {!mo && (
                <span className="text-xs text-[var(--muted-foreground)]">
                  {cd.kho ? `${cd.kho}:${cd.thu_muc || ""}` : "⚠ chưa chọn kho"}
                  {cd.kho && !cd.thread_admin ? " · ⚠ chưa chọn thread admin" : ""}
                </span>
              )}
              <Button variant="ghost" size="sm" className="ml-auto rounded-lg"
                onClick={() => xoa(key)}>
                <Trash2 className="size-4" />
              </Button>
            </div>

            {mo && (<>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-1">
                <label className="text-xs font-medium">Tài khoản lưu</label>
                <select value={cd.kho || ""} onChange={(e) => setEntry(key, { kho: e.target.value })}
                  className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm">
                  <option value="">— chưa chọn —</option>
                  {khoCo.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">Thư mục gốc</label>
                <div className="flex gap-2">
                  {(thuMucCua[cd.kho || ""] || []).length ? (
                    <select value={cd.thu_muc || ""}
                      onChange={(e) => setEntry(key, { thu_muc: e.target.value })}
                      className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm">
                      <option value="">— thư mục gốc của kho —</option>
                      {(thuMucCua[cd.kho || ""] || []).map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                  ) : (
                    <Input value={cd.thu_muc || ""} placeholder="để trống = thư mục gốc"
                      onChange={(e) => setEntry(key, { thu_muc: e.target.value })}
                      className="h-10 rounded-xl" />
                  )}
                  <Button variant="outline" size="sm" className="h-10 shrink-0 rounded-xl"
                    onClick={() => void napThuMuc(cd.kho || "")}
                    disabled={!cd.kho || dangDoc === cd.kho}>
                    {dangDoc === cd.kho
                      ? <LoaderCircle className="size-4 animate-spin" />
                      : <FolderOpen className="size-4" />}
                  </Button>
                </div>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Bấm 📂 để lấy danh sách thư mục có sẵn trên kho.
                </p>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">Thread admin nhận xác nhận</label>
                <select value={cd.thread_admin || ""}
                  onChange={(e) => setEntry(key, { thread_admin: e.target.value })}
                  className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm">
                  <option value="">— chưa chọn: sẽ không hỏi —</option>
                  {/* KHÔNG loại chính thread này ra: chat 1-1 với admin thì hỏi
                      ngay tại đó là đúng nhất, chọn chỗ khác mới là lạ. */}
                  {opts.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.key === key ? `${o.label} (hỏi ngay tại đây)` : o.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Nhiều admin thì phải chỉ rõ gửi cho ai. Bỏ trống = không hỏi, tệp không được lưu.
                  Phải chọn thread CÙNG KÊNH với nơi nhận tệp — trả lời chéo kênh chưa hỗ trợ.
                </p>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">Giờ đồng bộ nhật ký</label>
                <Input value={cd.gio_dong_bo || "03:00"} placeholder="03:00"
                  onChange={(e) => setEntry(key, { gio_dong_bo: e.target.value })}
                  className="h-10 rounded-xl" />
                <p className="text-xs text-[var(--muted-foreground)]">Chỉ áp cho nhật ký — tệp thì hỏi ngay lúc nhận.</p>
              </div>
            </div>

            {/* Đọc được kho nào — máy chủ tính theo «Kết nối bộ nhớ». Không có
                khối này thì khai kết nối xong phải dò trong mã mới biết ai đọc
                được của ai. */}
            {(banDo[key] || []).length > 0 && (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--secondary)]/40 p-3">
                <div className="text-xs font-medium">Thread này đọc được</div>
                <ul className="mt-1 space-y-0.5">
                  {(banDo[key] || []).map((k) => (
                    <li key={k.kho + "|" + k.thu_muc} className="text-xs">
                      <span className="font-mono">{k.kho}:{k.thu_muc}</span>{" "}
                      {k.cua_minh
                        ? <span className="text-[var(--muted-foreground)]">— kho của chính nó: xem, tải về, lưu lên</span>
                        : <span className="text-amber-600 dark:text-amber-400">— qua «Kết nối bộ nhớ»: xem và TẢI VỀ được (gửi file được), KHÔNG lưu lên</span>}
                    </li>
                  ))}
                </ul>
                {(banDo[key] || []).length === 1 && (
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                    Chưa nối với phạm vi nào — độc lập hoàn toàn.
                  </p>
                )}
              </div>
            )}

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={cd.hoi_truoc !== false}
                onChange={(e) => setEntry(key, { hoi_truoc: e.target.checked })} />
              Hỏi admin trước khi lưu mỗi tệp
              <span className="text-xs text-[var(--muted-foreground)]">
                (bỏ tick = tự lưu, khỏi hỏi)
              </span>
            </label>

            <div className="space-y-1">
              <p className="text-xs font-medium">Giữ trên đám mây bao nhiêu ngày (0 = giữ mãi)</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {CAC_MUC.map((m) => (
                  <div key={m} className="space-y-1">
                    <label className="text-xs text-[var(--muted-foreground)]">{m}</label>
                    <Input type="number" min={0}
                      value={String(cd.giu_ngay?.[m] ?? GIU_MAC_DINH)}
                      onChange={(e) => setGiu(key, m, parseInt(e.target.value, 10))}
                      className="h-9 rounded-lg" />
                  </div>
                ))}
              </div>
            </div>

            <p className="text-xs text-[var(--muted-foreground)]">
              Tệp tự vào thư mục con theo loại: {CAC_MUC.join(" · ")}. Đặt cùng một tài khoản cho nhiều thread
              cũng được — mỗi thread vẫn có thư mục gốc riêng.
            </p>
            </>)}
          </div>
          );
        })}

        {/* BẮT BUỘC có: mọi thay đổi phía trên mới chỉ nằm trong trình duyệt.
            Không bấm Lưu thì tải lại trang là mất sạch, và bot không đọc được. */}
        <div className="flex items-center justify-end gap-3 border-t border-[var(--border)] pt-4">
          <span className="text-xs text-[var(--muted-foreground)]">
            Thay đổi chỉ có hiệu lực sau khi lưu.
          </span>
          <Button className="h-10 rounded-xl" onClick={() => void saveConfig()}
            disabled={isSavingConfig}>
            {isSavingConfig ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            Lưu
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
