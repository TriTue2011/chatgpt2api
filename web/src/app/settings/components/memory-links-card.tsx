"use client";

/**
 * «Kết nối bộ nhớ» — nối những phạm vi ĐỘC LẬP lại với nhau.
 *
 * Mặc định mỗi kênh / nhóm / topic / người là một phạm vi riêng, không thấy dữ
 * liệu của nhau (services/agent/scope.py). Tab này khai những chỗ CÓ liên quan:
 *
 *   • Bình đẳng — các thành viên đọc được của nhau, HAI CHIỀU.
 *   • Chính phụ — CHÍNH đọc được PHỤ, PHỤ không đọc được CHÍNH, MỘT CHIỀU.
 *
 * Kết nối chỉ mở đường ĐỌC. Ghi vẫn vào phạm vi của chính lượt đó, nên gỡ nối
 * là hết thấy ngay — dữ liệu chưa từng chảy sang nhau.
 *
 * Danh sách chọn lấy từ chính «Lọc thread»: nhóm/topic ở `thread_filters`,
 * người ở `thread_user_filters`. Không dựng danh sách thứ hai để chủ máy phải
 * đặt tên hai lần.
 *
 * Ghi ra config `memory_links` (đọc bởi services/agent/scope.pham_vi_doc_them).
 */

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSettingsStore } from "../store";

/** Một đầu mối được nối. Ô trống = mọi giá trị (nối «cả nhóm» là một dòng). */
type ThanhVien = { kenh: string; chat: string; topic: string; user: string };

type MoiNoi = {
  uiId: number;
  id: string;
  kind: "binh_dang" | "chinh_phu";
  name: string;
  enabled: boolean;
  members: ThanhVien[];
  primary: ThanhVien[];
  secondary: ThanhVien[];
};

const NHAN_KENH: Record<string, string> = {
  tg: "Telegram", zalo: "Zalo Bot", zalop: "Zalo cá nhân", mail: "Email",
};

/** Khoá «Lọc thread» → thành viên có cấu trúc.
 *
 * Khoá nhóm:  'plat:bot:chat[#topic]' hoặc 'plat:chat[#topic]'
 * Khoá người: khoá nhóm + ':user'
 * Chuỗi thô nhập nhằng (ba phần có thể là bot+chat hoặc chat+user) nên chỗ gọi
 * phải nói rõ đang tách khoá loại nào — backend nhận bản CÓ CẤU TRÚC này. */
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
  // Còn lại: [bot, chat] hoặc [chat]
  const chatPart = con.length >= 2 ? con.slice(1).join(":") : (con[0] || "");
  if (!chatPart) return null;
  const i = kenh === "tg" ? chatPart.indexOf("#") : -1;
  const chat = i >= 0 ? chatPart.slice(0, i) : chatPart;
  const topic = i >= 0 ? chatPart.slice(i + 1) : "";
  return { kenh, chat, topic, user };
}

function maThanhVien(tv: ThanhVien): string {
  return [tv.kenh, tv.chat, tv.topic, tv.user].join("|");
}

function nhanThanhVien(tv: ThanhVien, ten?: string): string {
  const dich = tv.chat + (tv.topic ? ` › topic ${tv.topic}` : "")
    + (tv.user ? ` › người ${tv.user}` : "");
  const kenh = NHAN_KENH[tv.kenh] || tv.kenh;
  return ten ? `${ten} · ${kenh} ${dich}` : `${kenh} ${dich}`;
}

export function MemoryLinksCard() {
  const config = useSettingsStore((s) => s.config);
  const setField = useSettingsStore((s) => s.setField);
  const [rows, setRows] = useState<MoiNoi[]>([]);
  const seq = useRef(1);
  const inited = useRef(false);

  // ── Danh sách chọn: lấy thẳng từ «Lọc thread» ───────────────────────────
  const cfg = (config || {}) as Record<string, unknown>;
  const tf = (cfg.thread_filters || {}) as Record<string, unknown>;
  const tuf = (cfg.thread_user_filters || {}) as Record<string, unknown>;
  const meta = (cfg.thread_filter_meta || {}) as Record<string, { name?: string }>;
  const chonDuoc: { ma: string; nhan: string; tv: ThanhVien }[] = [];
  const daCo = new Set<string>();
  for (const [key, laNguoi] of [
    ...Object.keys(tf).map((k) => [k, false] as [string, boolean]),
    ...Object.keys(tuf).map((k) => [k, true] as [string, boolean]),
  ]) {
    const tv = tachKhoa(key, laNguoi);
    if (!tv) continue;
    const ma = maThanhVien(tv);
    if (daCo.has(ma)) continue;
    daCo.add(ma);
    chonDuoc.push({ ma, nhan: nhanThanhVien(tv, meta[key]?.name), tv });
  }
  const nhanMap = new Map(chonDuoc.map((c) => [c.ma, c.nhan]));

  useEffect(() => {
    if (inited.current || !config) return;
    inited.current = true;
    const ds = Array.isArray(cfg.memory_links) ? (cfg.memory_links as unknown[]) : [];
    const tvList = (v: unknown): ThanhVien[] =>
      Array.isArray(v)
        ? v.filter((x) => x && typeof x === "object").map((x) => {
          const o = x as Record<string, unknown>;
          return {
            kenh: String(o.kenh || ""), chat: String(o.chat || ""),
            topic: String(o.topic || ""), user: String(o.user || ""),
          };
        })
        : [];
    setRows(ds.filter((x) => x && typeof x === "object").map((x) => {
      const o = x as Record<string, unknown>;
      return {
        uiId: seq.current++,
        id: String(o.id || ""),
        kind: o.kind === "chinh_phu" ? "chinh_phu" : "binh_dang",
        name: String(o.name || ""),
        enabled: o.enabled === undefined ? true : Boolean(o.enabled),
        members: tvList(o.members),
        primary: tvList(o.primary),
        secondary: tvList(o.secondary),
      } as MoiNoi;
    }));
  }, [config, cfg.memory_links]);

  const luu = (ds: MoiNoi[]) => {
    setRows(ds);
    setField("memory_links", ds.map((r) => ({
      id: r.id || `ml_${r.uiId}`,
      kind: r.kind,
      name: r.name,
      enabled: r.enabled,
      ...(r.kind === "binh_dang"
        ? { members: r.members }
        : { primary: r.primary, secondary: r.secondary }),
    })));
  };

  const them = (kind: MoiNoi["kind"]) => luu([...rows, {
    uiId: seq.current++, id: `ml_${Date.now()}`, kind, enabled: true,
    name: kind === "binh_dang" ? "Nhóm bình đẳng" : "Chính phụ",
    members: [], primary: [], secondary: [],
  }]);

  const sua = (uiId: number, thay: Partial<MoiNoi>) =>
    luu(rows.map((r) => (r.uiId === uiId ? { ...r, ...thay } : r)));

  const themTV = (r: MoiNoi, o: "members" | "primary" | "secondary", ma: string) => {
    const found = chonDuoc.find((c) => c.ma === ma);
    if (!found) return;
    const cu = r[o];
    if (cu.some((t) => maThanhVien(t) === ma)) return;
    sua(r.uiId, { [o]: [...cu, found.tv] } as Partial<MoiNoi>);
  };

  const boTV = (r: MoiNoi, o: "members" | "primary" | "secondary", ma: string) =>
    sua(r.uiId, { [o]: r[o].filter((t) => maThanhVien(t) !== ma) } as Partial<MoiNoi>);

  /** Một ô danh sách thành viên (dùng cho cả bình đẳng lẫn chính/phụ). */
  const OThanhVien = ({ r, o, tieuDe }: {
    r: MoiNoi; o: "members" | "primary" | "secondary"; tieuDe: string;
  }) => (
    <div className="flex-1 min-w-[220px] rounded border border-border/60 p-2">
      <div className="text-[11px] font-medium mb-1">{tieuDe}</div>
      {r[o].length === 0 && (
        <div className="text-[10px] text-muted-foreground mb-1">Chưa có ai.</div>
      )}
      <div className="space-y-1 mb-2">
        {r[o].map((t) => (
          <div key={maThanhVien(t)}
            className="flex items-center justify-between gap-2 text-[11px] rounded bg-muted/40 px-2 py-1">
            {/* Đã nối rồi mà sau đó bị xoá khỏi «Lọc thread» thì không còn tên —
                vẫn hiện dòng đó để chủ máy thấy và tự gỡ, không im lặng biến mất. */}
            <span className="truncate">
              {nhanMap.get(maThanhVien(t)) || nhanThanhVien(t)}
            </span>
            <button type="button" className="text-red-500 shrink-0"
              onClick={() => boTV(r, o, maThanhVien(t))}>✕</button>
          </div>
        ))}
      </div>
      <select
        className="w-full h-7 rounded border border-input bg-background px-2 text-[11px]"
        value=""
        onChange={(e) => { themTV(r, o, e.target.value); e.target.value = ""; }}>
        <option value="">➕ Thêm nhóm / topic / người…</option>
        {chonDuoc
          .filter((c) => !r[o].some((t) => maThanhVien(t) === c.ma))
          .map((c) => <option key={c.ma} value={c.ma}>{c.nhan}</option>)}
      </select>
    </div>
  );

  return (
    <div className="space-y-3 mt-1">
      <p className="text-[10px] text-muted-foreground leading-relaxed">
        Mặc định mỗi nhóm / topic / người là một <b>bộ nhớ riêng</b>, không thấy của
        nhau. Ở đây khai những chỗ CÓ liên quan.<br />
        <b>Bình đẳng</b>: các thành viên đọc được của nhau (hai chiều).{" "}
        <b>Chính phụ</b>: bên <b>Chính</b> đọc được bên <b>Phụ</b>, bên Phụ KHÔNG đọc
        được bên Chính (một chiều).<br />
        Kết nối chỉ mở đường <b>đọc</b> — ghi vẫn vào bộ nhớ của chính nơi đó, nên gỡ
        kết nối là hết thấy ngay.
      </p>

      {chonDuoc.length === 0 && (
        <p className="text-[11px] text-amber-600">
          Chưa có nhóm/người nào trong «Lọc thread» — vào tab <b>🎚️ Lọc thread</b>{" "}
          thêm trước, danh sách ở đây lấy từ đó.
        </p>
      )}

      <div className="flex gap-2">
        <Button type="button" size="sm" variant="outline"
          onClick={() => them("binh_dang")}>➕ Bình đẳng</Button>
        <Button type="button" size="sm" variant="outline"
          onClick={() => them("chinh_phu")}>➕ Chính phụ</Button>
      </div>

      {rows.length === 0 && (
        <p className="text-[11px] text-muted-foreground">
          Chưa có kết nối nào — mọi bộ nhớ đang độc lập hoàn toàn.
        </p>
      )}

      {rows.map((r) => (
        <div key={r.uiId} className="rounded-lg border border-border p-3 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={"text-[10px] px-2 py-0.5 rounded-full "
              + (r.kind === "binh_dang"
                ? "bg-emerald-500/15 text-emerald-600"
                : "bg-sky-500/15 text-sky-600")}>
              {r.kind === "binh_dang" ? "⇄ Bình đẳng" : "→ Chính phụ"}
            </span>
            <Input className="h-7 text-xs max-w-[240px]" value={r.name}
              placeholder="Tên kết nối (vd: Nhà mình)"
              onChange={(e) => sua(r.uiId, { name: e.target.value })} />
            <label className="flex items-center gap-1 text-[11px]">
              <input type="checkbox" checked={r.enabled}
                onChange={(e) => sua(r.uiId, { enabled: e.target.checked })} />
              Bật
            </label>
            <button type="button" className="ml-auto text-[11px] text-red-500"
              onClick={() => luu(rows.filter((x) => x.uiId !== r.uiId))}>
              🗑 Xoá
            </button>
          </div>

          <div className="flex gap-2 flex-wrap">
            {r.kind === "binh_dang" ? (
              <OThanhVien r={r} o="members" tieuDe="Thành viên (đọc được của nhau)" />
            ) : (
              <>
                <OThanhVien r={r} o="primary" tieuDe="Chính (đọc được bên Phụ)" />
                <OThanhVien r={r} o="secondary" tieuDe="Phụ (KHÔNG đọc được bên Chính)" />
              </>
            )}
          </div>

          {r.kind === "binh_dang" && r.members.length === 1 && (
            <p className="text-[10px] text-amber-600">
              Mới có một thành viên — cần ít nhất hai thì kết nối mới có tác dụng.
            </p>
          )}
          {r.kind === "chinh_phu" && (r.primary.length === 0 || r.secondary.length === 0) && (
            <p className="text-[10px] text-amber-600">
              Cần ít nhất một bên Chính và một bên Phụ.
            </p>
          )}
        </div>
      ))}

      <p className="text-[10px] text-muted-foreground">
        Chọn <b>cả nhóm</b> thì mọi người trong nhóm đó đều được tính. Nhóm đã đặt lọc
        theo từng người (tab «Lọc thread» → cấp User) thì mỗi người là một bộ nhớ
        riêng — muốn nối đích danh ai thì chọn dòng người đó.
      </p>
    </div>
  );
}
