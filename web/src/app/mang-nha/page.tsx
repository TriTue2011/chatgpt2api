"use client";

/**
 * Tab "Mạng nhà" — quản lý mạng qua router MikroTik (services/mang_nha.py, API-SSL).
 *
 * Chủ máy 03/10/2026: "chưa có trang quản lý mạng trên c2a", "tab mạng nhà để ở tab cạnh như học hỏi, khuôn mặt",
 * "đầy đủ chức năng chứ không chỉ là như ảnh". Mọi việc đi qua POST /api/mang-nha/viec — cùng hàm bot dùng khi anh
 * nhắn trong chat, nên trang và chat không bao giờ làm khác nhau. Router từ chối thì hiện NGUYÊN lý do.
 *
 * Không có cột sóng wifi (dBm): router nhà này không phát wifi, hai AP làm cầu nên router không biết sóng.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { request } from "@/lib/request";

type May = {
  id: string; ip: string; mac: string; host: string; ten: string; duyet: boolean; khoa: boolean;
  trang_thai: string; thay: string; chan: boolean; chan_con: string; toc_do: string; nhom: string;
  het_han: number | null;
};
type Cho = { mac: string; ip: string; host: string; cong: string };
type Vpn = { gd: string; ten: string; bat: boolean; bat_tay: string };
type DuLieu = {
  ok: boolean; loi?: string; router?: string; may: May[]; cho: Cho[]; dhcp_khoa: boolean; ep_dns: boolean;
  vpn: Vpn[]; nhom: Record<string, string>; bang_thong: Record<string, string>;
};

const HAN: [string, string][] = [
  ["", "Mãi mãi"], ["60", "1 giờ"], ["120", "2 giờ"], ["1440", "1 ngày"], ["4320", "3 ngày"], ["10080", "7 ngày"],
];
const LOC: [string, string][] = [
  ["", "Tất cả"], ["duyet", "Đã duyệt"], ["cho", "Chưa duyệt (động)"], ["chan", "Đang chặn / kick"],
  ["toc", "Có giới hạn tốc độ"], ["vang", "Đang offline"],
];
const chon = "h-8 rounded-md border border-border bg-transparent px-2 text-xs";
const huy = (s: number | null) =>
  s ? new Date(s * 1000).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "";

function Nhan({ mau, children }: { mau: string; children: React.ReactNode }) {
  return <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${mau}`}>{children}</span>;
}

function docMang(): Promise<DuLieu> {
  return request.get("/api/mang-nha/may")
    .then((r) => r.data as DuLieu)
    .catch((e: any) => ({ ok: false, loi: e?.message || "Không gọi được máy chủ" }) as DuLieu);
}

export default function MangNhaPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return <MangNha />;
}

function MangNha() {
  const [d, setD] = useState<DuLieu | null>(null);
  const [dang, setDang] = useState(false);
  const [tin, setTin] = useState("");
  const [tim, setTim] = useState("");
  const [loc, setLoc] = useState("");
  const [da, setDa] = useState<Set<string>>(new Set());
  const [hanLo, setHanLo] = useState("120");
  const [tocLo, setTocLo] = useState("2M");

  const tai = useCallback(() => docMang().then(setD), []);

  useEffect(() => {
    let song = true;
    const nap = () => docMang().then((x) => { if (song) setD(x); });
    void nap();
    const t = setInterval(() => void nap(), 30000);
    return () => { song = false; clearInterval(t); };
  }, []);

  const viec = async (body: Record<string, unknown>, xacNhan = true): Promise<string> => {
    setDang(true);
    try {
      let r = await request.post("/api/mang-nha/viec", body);
      let t = String((r.data as { text?: string }).text || "");
      // Việc nguy hiểm (khoá DHCP, ép DNS) lần đầu chỉ cảnh báo — hỏi lại rồi mới làm.
      if (xacNhan && t.startsWith("⚠️") && window.confirm(`${t}\n\nVẫn làm?`)) {
        r = await request.post("/api/mang-nha/viec", { ...body, xac_nhan: true });
        t = String((r.data as { text?: string }).text || "");
      }
      return t;
    } catch (e: any) {
      return `❌ ${e?.message || "lỗi gọi máy chủ"}`;
    } finally {
      setDang(false);
    }
  };

  const lam = async (body: Record<string, unknown>) => {
    setTin(await viec(body));
    await tai();
  };

  const loHang = async (body: Record<string, unknown>) => {
    const ds = [...da];
    const kq: string[] = [];
    for (const ip of ds) kq.push(await viec({ ...body, may: ip }, false));
    setTin(kq.join("\n"));
    setDa(new Set());
    await tai();
  };

  const may = useMemo(() => {
    const q = tim.trim().toLowerCase();
    return (d?.may || []).filter((m) => {
      if (q && ![m.ten, m.host, m.ip, m.mac].some((x) => (x || "").toLowerCase().includes(q))) return false;
      if (loc === "duyet") return m.duyet;
      if (loc === "cho") return !m.duyet;
      if (loc === "chan") return m.chan || m.khoa;
      if (loc === "toc") return !!m.toc_do;
      if (loc === "vang") return m.trang_thai !== "bound";
      return true;
    });
  }, [d, tim, loc]);

  if (!d) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const nhom = d.nhom || {};
  const tatCa = may.length > 0 && may.every((m) => da.has(m.ip));

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 px-4 py-6" style={{ paddingInline: "max(16px, env(safe-area-inset-left))" }}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">🌐 Mạng nhà</h1>
          <p className="text-xs text-muted-foreground">{d.ok ? d.router : `❌ ${d.loi}`}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void tai()} disabled={dang}>
          <RefreshCw className="mr-1 size-3.5" /> Làm mới
        </Button>
      </div>

      {tin ? (
        <pre className="whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3 text-xs">{tin}</pre>
      ) : null}

      {!d.ok ? (
        <Card>
          <CardContent className="py-4 text-sm">
            Chưa đọc được router. Kiểm tra tài khoản ở Cài đặt › Home Assistant › 🌐 Mạng nhà.
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Điều khiển chung</CardTitle>
              <CardDescription>
                Khoá DHCP: chỉ máy đã duyệt mới nhận IP — máy lạ biết mật khẩu wifi cũng không có mạng. Ép DNS: mọi
                máy phải hỏi tên miền qua AdGuard (máy tự đặt 8.8.8.8 để lách bộ lọc sẽ không phân giải được).
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button size="sm" variant={d.dhcp_khoa ? "default" : "outline"} disabled={dang}
                onClick={() => void lam({ viec: "khoa_dhcp", bat: !d.dhcp_khoa })}>
                {d.dhcp_khoa ? "🔒 DHCP đang khoá — mở" : "🔓 DHCP đang mở — khoá"}
              </Button>
              <Button size="sm" variant={d.ep_dns ? "default" : "outline"} disabled={dang}
                onClick={() => void lam({ viec: "ep_dns", bat: !d.ep_dns })}>
                {d.ep_dns ? "🛡️ Đang ép DNS qua AdGuard — bỏ" : "🛡️ Ép DNS qua AdGuard"}
              </Button>
              {d.vpn.map((v) => (
                <Button key={v.gd} size="sm" variant={v.bat ? "default" : "outline"} disabled={dang}
                  onClick={() => void lam({ viec: "vpn", ten: v.gd, bat: !v.bat })}>
                  🔐 VPN {v.ten}: {v.bat ? `bật${v.bat_tay ? ` · bắt tay ${v.bat_tay}` : " · chưa bắt tay"}` : "tắt"}
                </Button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">🔔 Thiết bị chờ duyệt ({d.cho.length})</CardTitle>
              <CardDescription>
                Máy chưa có địa chỉ cố định: lease động, hoặc MAC chỉ thấy trên bridge (sau khi khoá DHCP). Duyệt =
                cấp IP cố định + nhóm + thời hạn (hết hạn em tự đá ra). Kick = không cấp IP, cắt mạng ngay.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {d.cho.length === 0 ? <p className="text-xs text-muted-foreground">Không có máy nào chờ.</p> : null}
              {d.cho.map((c) => <ChoDuyet key={c.mac} c={c} nhom={nhom} dang={dang} lam={lam} />)}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Thiết bị ({may.length}/{d.may.length})</CardTitle>
              <div className="flex flex-wrap gap-2 pt-2">
                <Input className="h-8 w-56" placeholder="Tìm tên, IP, MAC…" value={tim} onChange={(e) => setTim(e.target.value)} />
                <select className={chon} value={loc} onChange={(e) => setLoc(e.target.value)}>
                  {LOC.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              {da.size ? (
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 p-2 text-xs">
                  <b>{da.size} máy:</b>
                  <select className={chon} value={hanLo} onChange={(e) => setHanLo(e.target.value)}>
                    {HAN.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  <Button size="sm" variant="destructive" disabled={dang} onClick={() => void loHang({ viec: "chan", phut: hanLo })}>Chặn</Button>
                  <Button size="sm" variant="outline" disabled={dang} onClick={() => void loHang({ viec: "mo" })}>Mở</Button>
                  <Input className="h-8 w-24" value={tocLo} onChange={(e) => setTocLo(e.target.value)} />
                  <Button size="sm" variant="outline" disabled={dang} onClick={() => void loHang({ viec: "gioi_han", toc_do: tocLo })}>Giới hạn</Button>
                  <Button size="sm" variant="outline" disabled={dang} onClick={() => void loHang({ viec: "gioi_han", toc_do: "bo" })}>Bỏ giới hạn</Button>
                  <Button size="sm" variant="destructive" disabled={dang}
                    onClick={() => window.confirm(`Kick ${da.size} máy? Router sẽ không cấp IP cho chúng nữa.`) && void loHang({ viec: "kick" })}>Kick</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDa(new Set())}>Bỏ chọn</Button>
                </div>
              ) : null}
            </CardHeader>
            <CardContent className="space-y-1">
              <label className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
                <input type="checkbox" checked={tatCa}
                  onChange={(e) => setDa(e.target.checked ? new Set(may.map((m) => m.ip)) : new Set())} />
                Chọn tất cả đang hiện
              </label>
              {may.map((m) => (
                <DongMay key={`${m.mac || m.ip}|${m.ten}`} m={m} nhom={nhom} dang={dang} lam={lam}
                  chon={da.has(m.ip)}
                  doiChon={(v) => setDa((s) => { const n = new Set(s); if (v) n.add(m.ip); else n.delete(m.ip); return n; })} />
              ))}
            </CardContent>
          </Card>

          <BangThong d={d} dang={dang} lam={lam} />
        </>
      )}
    </div>
  );
}

function ChoDuyet({ c, nhom, dang, lam }: {
  c: Cho; nhom: Record<string, string>; dang: boolean; lam: (b: Record<string, unknown>) => Promise<void>;
}) {
  const [ten, setTen] = useState(c.host || "");
  const [nh, setNh] = useState("khach");
  const [han, setHan] = useState("4320");
  return (
    <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <b className="font-mono text-sm">{c.mac}</b>
        <Nhan mau="border-amber-500 text-amber-600">pending</Nhan>
        <span className="text-xs text-muted-foreground">
          {c.host || "không tên"} · {c.ip ? `IP ${c.ip}` : "chưa có IP"}{c.cong ? ` · cổng ${c.cong}` : ""}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <Input className="h-8 w-48" placeholder="Đặt tên thiết bị…" value={ten} onChange={(e) => setTen(e.target.value)} />
        <select className={chon} value={nh} onChange={(e) => setNh(e.target.value)}>
          {Object.entries(nhom).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className={chon} value={han} onChange={(e) => setHan(e.target.value)}>
          {HAN.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <Button size="sm" disabled={dang} onClick={() => void lam({ viec: "duyet", may: c.mac, ten, nhom: nh, phut: han })}>
          ✅ Duyệt
        </Button>
        <Button size="sm" variant="destructive" disabled={dang} onClick={() => void lam({ viec: "kick", may: c.mac })}>
          🚫 Kick
        </Button>
      </div>
    </div>
  );
}

function DongMay({ m, nhom, dang, lam, chon: daChon, doiChon }: {
  m: May; nhom: Record<string, string>; dang: boolean; lam: (b: Record<string, unknown>) => Promise<void>;
  chon: boolean; doiChon: (v: boolean) => void;
}) {
  const [ten, setTen] = useState(m.ten);
  const [han, setHan] = useState("120");
  const may = m.ip || m.mac;
  const luuTen = () => { if (ten.trim() && ten.trim() !== m.ten) void lam({ viec: "dat_ten", may, ten: ten.trim() }); };
  return (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border px-2 py-2 text-xs ${m.khoa || m.chan ? "border-red-500/40 bg-red-500/5" : "border-border"}`}>
      <input type="checkbox" checked={daChon} onChange={(e) => doiChon(e.target.checked)} />
      <Input className="h-8 w-40" placeholder="Nhập tên…" value={ten} onChange={(e) => setTen(e.target.value)}
        onBlur={luuTen} onKeyDown={(e) => { if (e.key === "Enter") luuTen(); }} />
      <div className="min-w-36">
        <div className="text-sm font-semibold">{m.ten || m.host || "không tên"}</div>
        <div className="text-[10px] text-muted-foreground">{m.host}</div>
      </div>
      <div className="min-w-36 font-mono">
        <div>{m.mac}</div>
        <div className="text-primary">{m.ip}</div>
      </div>
      <select className={chon} value={m.nhom} disabled={dang}
        onChange={(e) => void lam({ viec: "duyet", may, nhom: e.target.value })}>
        <option value="" disabled>Nhóm…</option>
        {Object.entries(nhom).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <div className="flex flex-wrap gap-1">
        {m.duyet ? <Nhan mau="border-emerald-500 text-emerald-600">known</Nhan> : <Nhan mau="border-amber-500 text-amber-600">pending</Nhan>}
        {m.khoa ? <Nhan mau="border-red-500 text-red-600">kick</Nhan> : null}
        {m.chan ? <Nhan mau="border-red-500 text-red-600">chặn{m.chan_con ? ` · còn ${m.chan_con}` : ""}</Nhan> : null}
        {m.toc_do ? <Nhan mau="border-sky-500 text-sky-600">⚡ {m.toc_do}</Nhan> : null}
        {m.het_han ? <Nhan mau="border-violet-500 text-violet-600">hạn {huy(m.het_han)}</Nhan> : null}
      </div>
      <div className="text-muted-foreground">{m.trang_thai === "bound" ? "đang dùng" : m.trang_thai || "?"}{m.thay ? ` · ${m.thay} trước` : ""}</div>
      <div className="ml-auto flex flex-wrap gap-1">
        {m.chan ? (
          <Button size="sm" variant="outline" disabled={dang} onClick={() => void lam({ viec: "mo", may })}>Mở</Button>
        ) : (
          <>
            <select className={chon} value={han} onChange={(e) => setHan(e.target.value)}>
              {HAN.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <Button size="sm" variant="outline" disabled={dang} onClick={() => void lam({ viec: "chan", may, phut: han })}>Chặn</Button>
          </>
        )}
        <Button size="sm" variant="outline" disabled={dang}
          onClick={() => {
            const t = window.prompt("Tốc độ tối đa (vd 2M, hoặc 1M/5M = tải lên/tải xuống; để trống = bỏ giới hạn)", m.toc_do);
            if (t !== null) void lam({ viec: "gioi_han", may, toc_do: t.trim() || "bo" });
          }}>⚡ Tốc độ</Button>
        {m.khoa ? (
          <Button size="sm" variant="outline" disabled={dang} onClick={() => void lam({ viec: "bo_kick", may })}>Bỏ kick</Button>
        ) : (
          <Button size="sm" variant="destructive" disabled={dang}
            onClick={() => window.confirm(`Kick ${m.ten || m.ip}? Router sẽ không cấp IP cho máy này nữa.`) && void lam({ viec: "kick", may })}>
            Kick
          </Button>
        )}
      </div>
    </div>
  );
}

function BangThong({ d, dang, lam }: { d: DuLieu; dang: boolean; lam: (b: Record<string, unknown>) => Promise<void> }) {
  const [bt, setBt] = useState<Record<string, string>>(() => ({ ...d.bang_thong }));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Băng thông theo nhóm</CardTitle>
        <CardDescription>
          Áp khi duyệt / đổi nhóm một máy. Trống = không giới hạn. Viết «2M» (hai chiều) hoặc «1M/5M» (tải lên/tải
          xuống). Camera nên để trống.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-3">
        {Object.entries(d.nhom).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 text-xs">
            <span className="w-20">{v}</span>
            <Input className="h-8 w-24" placeholder="không giới hạn" value={bt[k] || ""}
              onChange={(e) => setBt({ ...bt, [k]: e.target.value })} />
            <Button size="sm" variant="outline" disabled={dang || (bt[k] || "") === (d.bang_thong[k] || "")}
              onClick={() => void lam({ viec: "bang_thong", nhom: k, toc_do: bt[k] || "" })}>Lưu</Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
