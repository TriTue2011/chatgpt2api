"use client";

/**
 * Kết nối phạm vi — nối những phạm vi ĐỘC LẬP lại với nhau.
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
 * HAI SỔ KẾT NỐI TÁCH RỜI, dùng CHUNG một thẻ này:
 *
 *   `memory_links`  → «Kết nối bộ nhớ»     (scope.pham_vi_doc_them)
 *   `luu_tru_links` → «Kết nối kho đám mây» (scope.kho_doc_them)
 *
 * Tách vì nối bộ nhớ là cho nhau đọc điều đã ghi nhớ, còn nối kho là cho nhau
 * đọc TỆP trong thư mục Drive — hai mức riêng tư khác hẳn nhau. Dùng chung một
 * sổ thì nối bộ nhớ là kho tự mở theo, không tắt riêng được.
 *
 * Chép thẻ này ra làm hai bản là hai bản sẽ lệch nhau; nên nó nhận `configKey`
 * và vài nhãn, còn luật hiển thị chỉ viết một lần.
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

/** Nhãn khác nhau giữa hai sổ — phần còn lại dùng chung. */
type CauHinhThe = {
  /** Khoá config được ghi ra: 'memory_links' | 'luu_tru_links'. */
  configKey: string;
  /** Tiền tố id mối nối, để đọc log biết ngay là sổ nào. */
  idPrefix: string;
  /** Danh từ chèn vào câu giải thích: 'bộ nhớ' | 'kho đám mây'. */
  doiTuong: string;
  /** Chiều GHI của từng loại — khác nhau thật, không gộp một câu được. */
  cauGhi: React.ReactNode;
};

function LinksCard({ the }: { the: CauHinhThe }) {
  const config = useSettingsStore((s) => s.config);
  const setField = useSettingsStore((s) => s.setField);
  const [rows, setRows] = useState<MoiNoi[]>([]);
  /** Mối nối nào đang mở. Mặc định GẤP những mối đã có thành viên — nhiều mối
   *  mở hết một lúc thì trang dài, phải cuộn mới thấy nút thêm. */
  const [moRong, setMoRong] = useState<Record<number, boolean>>({});
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

  // Người ĐÃ BIẾT của từng nhóm — dựng từ chính các khoá `thread_user_filters`.
  // Nhóm nào có mặt ở đây tức là đã đặt lọc theo từng người, nghĩa là MỖI NGƯỜI
  // một bộ nhớ riêng: nối "cả nhóm" sẽ trỏ vào một bộ nhớ không ai ghi vào, nên
  // phải nêu đích danh người. Đây là danh sách để nêu đích danh.
  const nguoiCuaNhom = new Map<string, string[]>();
  for (const key of Object.keys(tuf)) {
    const tv = tachKhoa(key, true);
    if (!tv || !tv.user) continue;
    const oNhom = `${tv.kenh}|${tv.chat}|${tv.topic}`;
    const ds = nguoiCuaNhom.get(oNhom) || [];
    if (!ds.includes(tv.user)) ds.push(tv.user);
    nguoiCuaNhom.set(oNhom, ds);
  }
  const nguoiCua = (tv: ThanhVien): string[] =>
    nguoiCuaNhom.get(`${tv.kenh}|${tv.chat}|${tv.topic}`) || [];

  useEffect(() => {
    if (inited.current || !config) return;
    inited.current = true;
    const ds = Array.isArray(cfg[the.configKey]) ? (cfg[the.configKey] as unknown[]) : [];
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
  }, [config, cfg[the.configKey], the.configKey]);

  const luu = (ds: MoiNoi[]) => {
    setRows(ds);
    setField(the.configKey, ds.map((r) => ({
      id: r.id || `${the.idPrefix}${r.uiId}`,
      kind: r.kind,
      name: r.name,
      enabled: r.enabled,
      ...(r.kind === "binh_dang"
        ? { members: r.members }
        : { primary: r.primary, secondary: r.secondary }),
    })));
  };

  const them = (kind: MoiNoi["kind"]) => luu([...rows, {
    uiId: seq.current++, id: `${the.idPrefix}${Date.now()}`, kind, enabled: true,
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

  /** Đổi trường `user` của một dòng đã nối. Rỗng = cả nhóm. */
  const datUser = (r: MoiNoi, o: "members" | "primary" | "secondary",
                   ma: string, user: string) => {
    const moi = r[o].map((t) => (maThanhVien(t) === ma ? { ...t, user } : t));
    // Đặt trùng với một dòng đã có thì bỏ dòng vừa sửa, không giữ hai dòng y nhau.
    const loc = moi.filter((t, i) =>
      moi.findIndex((x) => maThanhVien(x) === maThanhVien(t)) === i);
    sua(r.uiId, { [o]: loc } as Partial<MoiNoi>);
  };

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
        {r[o].map((t, idx) => {
          const ma = maThanhVien(t);
          const dsNguoi = nguoiCua({ ...t, user: "" });
          const tachNguoi = dsNguoi.length > 0;
          // React key + id theo VỊ TRÍ, không theo `ma`: `ma` chứa `t.user`, nên
          // nếu key đổi mỗi lần gõ vào ô Người thì input bị remount và MẤT FOCUS
          // sau từng ký tự. Vị trí ổn định suốt lúc sửa (ta map tại chỗ).
          const dlId = `nguoi-${r.uiId}-${o}-${idx}`;
          return (
            <div key={`${r.uiId}-${o}-${idx}`} className="rounded bg-muted/40 px-2 py-1">
              <div className="flex items-center justify-between gap-2 text-[11px]">
                {/* Đã nối rồi mà sau đó bị xoá khỏi «Lọc thread» thì không còn
                    tên — vẫn hiện dòng đó để chủ máy thấy và tự gỡ, không im
                    lặng biến mất. */}
                <span className="truncate">
                  {nhanMap.get(ma) || nhanThanhVien(t)}
                </span>
                <button type="button" className="text-red-500 shrink-0"
                  onClick={() => boTV(r, o, ma)}>✕</button>
              </div>
              {/* Trường NGƯỜI. Nhóm đã lọc theo từng người thì mỗi người là một
                  phạm vi riêng — nối "cả nhóm" trỏ vào phạm vi không ai ghi vào,
                  nên phải nêu đích danh ở đây. */}
              <div className="flex items-center gap-1 mt-1">
                <span className="text-[10px] text-muted-foreground shrink-0">Người:</span>
                <input
                  className="h-6 flex-1 min-w-0 rounded border border-input bg-background px-1.5 text-[10px]"
                  list={dlId}
                  placeholder={tachNguoi ? "⚠ chọn đích danh" : "cả nhóm"}
                  value={t.user}
                  onChange={(e) => datUser(r, o, ma, e.target.value.trim())} />
                <datalist id={dlId}>
                  {dsNguoi.map((u) => <option key={u} value={u} />)}
                </datalist>
                {t.user && (
                  <button type="button" className="text-[10px] text-muted-foreground shrink-0"
                    title="Bỏ trống = cả nhóm"
                    onClick={() => datUser(r, o, ma, "")}>cả nhóm</button>
                )}
              </div>
              {tachNguoi && !t.user && (
                <p className="text-[10px] text-amber-600 mt-0.5">
                  Nhóm này đã lọc theo từng người → mỗi người một {the.doiTuong} riêng.
                  Để trống là nối vào {the.doiTuong} chung của nhóm mà không ai ghi vào.
                </p>
              )}
            </div>
          );
        })}
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
      {/* Hướng dẫn GẤP SẴN — đọc một lần là nhớ, để mở suốt thì đẩy phần việc
          thật xuống dưới màn hình. Dòng tóm tắt luôn thấy. */}
      <details className="text-[10px] text-muted-foreground leading-relaxed">
        <summary className="cursor-pointer select-none">
          Mặc định mỗi nhóm / topic / người là một <b>{the.doiTuong} riêng</b> —
          bấm để xem cách hoạt động
        </summary>
        <div className="mt-1 space-y-1">
          <p>
            <b>Bình đẳng</b>: các thành viên đọc được của nhau (hai chiều).{" "}
            <b>Chính phụ</b>: bên <b>Chính</b> đọc được bên <b>Phụ</b>, bên Phụ KHÔNG
            đọc được bên Chính (một chiều).
          </p>
          <p>{the.cauGhi}</p>
          <p>
            Mỗi dòng đã nối có ô <b>Người</b>: để trống là <b>cả nhóm</b>; điền vào là
            chỉ đúng người đó. Nhóm đã đặt lọc theo từng người («Lọc thread» → cấp
            User) thì <b>mỗi người là một {the.doiTuong} riêng</b> — ô Người gợi ý sẵn
            danh sách và nhắc chọn đích danh, vì để trống sẽ nối vào {the.doiTuong}{" "}
            chung của nhóm mà không ai ghi vào.
          </p>
          <p>
            Trong <b>chính phụ</b>, các bên Chính <b>độc lập với nhau</b> (không tự
            động bình đẳng), các bên Phụ cũng vậy. Muốn hai bên Chính đọc được của
            nhau thì tạo thêm một kết nối <b>bình đẳng</b> riêng.
          </p>
        </div>
      </details>

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
          Chưa có kết nối nào — mọi {the.doiTuong} đang độc lập hoàn toàn.
        </p>
      )}

      {rows.map((r) => {
        const soTV = r.kind === "binh_dang"
          ? r.members.length : r.primary.length + r.secondary.length;
        // Mở sẵn mối nối CHƯA có ai (đang dựng dở); mối đã xong thì gấp lại cho
        // trang ngắn — cùng nếp với «Lọc thread».
        const mo = moRong[r.uiId] ?? soTV === 0;
        const thieu = r.kind === "binh_dang"
          ? r.members.length === 1
          : (r.primary.length === 0 || r.secondary.length === 0);
        return (
        <div key={r.uiId} className="rounded-lg border border-border p-3 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <button type="button" aria-label={mo ? "Thu gọn" : "Mở rộng"}
              className="inline-flex size-5 shrink-0 items-center justify-center rounded border border-border bg-muted/40 text-[10px] text-muted-foreground"
              onClick={() => setMoRong((s) => ({ ...s, [r.uiId]: !mo }))}>
              {mo ? "▾" : "▸"}
            </button>
            <span className={"text-[10px] px-2 py-0.5 rounded-full "
              + (r.kind === "binh_dang"
                ? "bg-emerald-500/15 text-emerald-600"
                : "bg-sky-500/15 text-sky-600")}>
              {r.kind === "binh_dang" ? "⇄ Bình đẳng" : "→ Chính phụ"}
            </span>
            <Input className="h-7 text-xs max-w-[240px]" value={r.name}
              placeholder="Tên kết nối (vd: Nhà mình)"
              onChange={(e) => sua(r.uiId, { name: e.target.value })} />
            {/* Lúc gấp phải thấy ĐỦ để biết có cần mở ra không: số thành viên,
                và dấu ⚠ nếu mối nối chưa đủ đôi (mở ra mới biết là vô ích). */}
            {!mo && (
              <span className="text-[10px] text-muted-foreground">
                {soTV} thành viên{thieu ? " · ⚠ chưa đủ" : ""}
              </span>
            )}
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

          {mo && (<>
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
          </>)}
        </div>
        );
      })}

    </div>
  );
}

export function MemoryLinksCard() {
  return <LinksCard the={{
    configKey: "memory_links",
    idPrefix: "ml_",
    doiTuong: "bộ nhớ",
    cauGhi: (
      <>
        Kết nối chỉ mở đường <b>đọc</b> — ghi vẫn vào bộ nhớ của chính nơi đó, nên
        gỡ kết nối là hết thấy ngay.
      </>
    ),
  }} />;
}

export function LuuTruLinksCard() {
  return (
    <div className="space-y-2 mt-1">
      <p className="text-[10px] text-muted-foreground leading-relaxed">
        Sổ này <b>tách hẳn</b> với «Kết nối bộ nhớ»: nối bộ nhớ là cho nhau đọc điều
        đã ghi nhớ, nối ở đây là cho nhau đọc <b>tệp trong thư mục Drive</b>. Nối bên
        kia KHÔNG tự mở kho bên này, và ngược lại.
      </p>
      <LinksCard the={{
        configKey: "luu_tru_links",
        idPrefix: "kho_",
        doiTuong: "kho đám mây",
        cauGhi: (
          <>
            Kết nối chỉ mở đường <b>đọc và tải về</b>. <b>Tải lên vẫn chỉ vào kho của
            chính nơi đó</b> (khai ở tab «Lưu trữ online»), dù đã nối — nên gỡ kết nối
            là hết đọc được ngay, chưa từng có tệp nào chảy sang nhau.<br />
            Trong cùng một kho, mỗi phạm vi chỉ thấy <b>đúng thư mục của mình</b>; thư
            mục khác trong kho đó vẫn kín.
          </>
        ),
      }} />
    </div>
  );
}
