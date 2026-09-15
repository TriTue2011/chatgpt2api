"use client";

/**
 * Playlist chung cả nhà — lưu trên máy chủ c2a (`services/youtube_phat/playlists.py`),
 * tích hợp Home Assistant nối vào c2a thấy cùng danh sách.
 *
 * Chủ máy 14/09/2026: "thêm các bài hát yêu thích vào playlist để nghe hoặc nghe playlist
 * của người khác chia sẻ. Có thể tạo nhiều playlist khác nhau", "lưu luôn playlist này
 * lại, không phải lưu tay từng bài mà lưu toàn bộ qua link". Nên:
 * - dán link playlist YouTube, album/playlist Zing MP3 hoặc mã chia sẻ → lưu cả playlist;
 * - nút "+" ở mỗi kết quả tìm → thêm bài vào playlist có sẵn hoặc playlist mới;
 * - phát playlist: có tích loa thì loa phát và hàng đợi là cả playlist (máy chủ tự
 *   chuyển bài), không tích thì nghe/xem trên máy này;
 * - mã chia sẻ mở được ở c2a khác và ở tích hợp Home Assistant.
 */

import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronDown,
  Copy,
  Headphones,
  ListMusic,
  ListPlus,
  LoaderCircle,
  MonitorPlay,
  Music2,
  Pencil,
  Play,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import { type BaiHat, goi, TEN_NGUON, thoiLuong } from "./lib";

export type Playlist = {
  id: string;
  name: string;
  created_at: number;
  updated_at: number;
  source_url: string;
  items: BaiHat[];
};

export type NguonHang = { items: BaiHat[]; playlist_id?: string };

type KetQuaLenh = { playlists: Playlist[]; playlist?: Playlist; added?: number; code?: string };

/** Danh sách playlist giữ ngoài component: chuyển tab rồi quay lại không phải tải lại. */
let boNho: Playlist[] | null = null;

export type KhoPlaylist = {
  ds: Playlist[] | null;
  tai: () => Promise<void>;
  nhan: (r: KetQuaLenh | null) => KetQuaLenh | null;
  lenh: (body: Record<string, unknown>) => Promise<KetQuaLenh | null>;
};

export function useKhoPlaylist(): KhoPlaylist {
  const [ds, setDs] = useState<Playlist[] | null>(boNho);
  const nhan = (r: KetQuaLenh | null) => {
    if (r) {
      // Máy chủ cũ (chưa có playlist) trả ok mà không kèm danh sách: coi như rỗng.
      const ds = Array.isArray(r.playlists) ? r.playlists : [];
      boNho = ds;
      setDs(ds);
    }
    return r;
  };
  const tai = useCallback(async () => {
    nhan(await goi<KetQuaLenh>("playlist"));
  }, []);
  const lenh = useCallback(async (body: Record<string, unknown>) => nhan(await goi<KetQuaLenh>("playlist", body)), []);
  useEffect(() => {
    if (boNho !== null) return;
    let bo = false;
    void goi<KetQuaLenh>("playlist").then((r) => {
      if (!bo) nhan(r);
    });
    return () => {
      bo = true;
    };
  }, []);
  return { ds, tai, lenh, nhan };
}

/** Chữ trông như link hay mã (kể cả link không hỗ trợ): gửi máy chủ để nó báo đọc được không. */
const giongLink = (text: string) => /^(https?:\/\/|TTPL)/i.test(text.trim());

/** Link mà máy chủ lưu được cả playlist (máy chủ kiểm lại kỹ). */
export function laLinkPlaylist(text: string): boolean {
  const t = text.trim();
  return /^TTPL1\./.test(t)
    || /^https?:\/\/([a-z0-9-]+\.)*(youtube\.com|youtu\.be)\/\S*[?&]list=[A-Za-z0-9_-]+/i.test(t)
    || /^https?:\/\/([a-z0-9-]+\.)*zingmp3\.vn\/(album|playlist)\//i.test(t);
}

/** Nút "+" trên một bài: thêm vào playlist có sẵn hoặc tạo playlist mới. */
export function ThemVaoPlaylist({ bai, kho }: { bai: BaiHat; kho: KhoPlaylist }) {
  const [mo, setMo] = useState(false);
  const [ten, setTen] = useState("");
  const [dangGui, setDangGui] = useState("");
  const them = async (dich: { id: string } | { name: string }) => {
    setDangGui("id" in dich ? dich.id : "moi");
    const r = await kho.lenh({ action: "add", ...dich, items: [bai] });
    setDangGui("");
    if (!r?.playlist) return;
    toast.success(r.added ? `Đã thêm vào “${r.playlist.name}”.` : `Bài này đã có trong “${r.playlist.name}”.`);
    setTen("");
    setMo(false);
  };
  return (
    <Popover open={mo} onOpenChange={setMo}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="shrink-0 rounded-full text-muted-foreground"
          aria-label={`Thêm ${bai.title || bai.id} vào playlist`}
          title="Thêm vào playlist"
        >
          <ListPlus />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 space-y-2">
        <div className="text-xs font-semibold text-muted-foreground">Thêm vào playlist</div>
        <div className="max-h-52 space-y-0.5 overflow-auto">
          {kho.ds === null ? (
            <LoaderCircle className="mx-auto size-4 animate-spin text-muted-foreground" />
          ) : !kho.ds.length ? (
            <p className="text-xs text-muted-foreground">Chưa có playlist nào — đặt tên để tạo.</p>
          ) : (
            kho.ds.map((p) => {
              const coSan = p.items.some((i) => i.source === bai.source && (i.id === bai.id || i.url === bai.url));
              return (
                <button
                  key={p.id}
                  type="button"
                  disabled={!!dangGui}
                  onClick={() => void them({ id: p.id })}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-[var(--muted)] disabled:opacity-50"
                >
                  {dangGui === p.id ? <LoaderCircle className="size-3.5 animate-spin" /> : coSan ? <Check className="size-3.5 text-[var(--primary)]" /> : <ListMusic className="size-3.5 text-muted-foreground" />}
                  <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  <span className="text-xs text-muted-foreground">{p.items.length}</span>
                </button>
              );
            })
          )}
        </div>
        <form
          className="flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (ten.trim()) void them({ name: ten.trim() });
          }}
        >
          <Input value={ten} onChange={(e) => setTen(e.target.value)} maxLength={80} placeholder="Playlist mới…" className="h-8 min-w-0 flex-1 text-sm" />
          <Button type="submit" size="icon" className="size-8 shrink-0" disabled={!ten.trim() || !!dangGui} aria-label="Tạo playlist và thêm bài">
            {dangGui === "moi" ? <LoaderCircle className="animate-spin" /> : <Plus />}
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}

type Props = {
  kho: KhoPlaylist;
  coLoa: boolean;
  dangPhatMa: string;
  dangGuiMa: string;
  /** Phát một bài với hàng đợi là cả playlist; `xem` = xem video. */
  phat: (bai: BaiHat, xem: boolean, hang: NguonHang) => void;
  /** Playlist vừa lưu từ ô tìm (mở sẵn). */
  moSan: string;
};

export function DanhSachPlaylist({ kho, coLoa, dangPhatMa, dangGuiMa, phat, moSan }: Props) {
  const [chu, setChu] = useState("");
  const [dangLuu, setDangLuu] = useState(false);
  const [mo, setMo] = useState(moSan);
  const [moSanCu, setMoSanCu] = useState(moSan);
  const [doiTen, setDoiTen] = useState<{ id: string; ten: string } | null>(null);
  const { ds, lenh } = kho;

  // Playlist vừa lưu từ ô tìm thì mở sẵn.
  if (moSan !== moSanCu) {
    setMoSanCu(moSan);
    if (moSan) setMo(moSan);
  }
  // Mở thẻ Playlist thì tải lại: bên Home Assistant có thể vừa sửa.
  useEffect(() => {
    let bo = false;
    void goi<KetQuaLenh>("playlist").then((r) => {
      if (!bo && r) kho.nhan(r);
    });
    return () => {
      bo = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const luu = async () => {
    const t = chu.trim();
    if (!t) return;
    setDangLuu(true);
    const nhap = laLinkPlaylist(t) || giongLink(t);
    const r = nhap
      ? await lenh({ action: "import", text: t })
      : await lenh({ action: "create", name: t, items: [] });
    setDangLuu(false);
    if (!r?.playlist) return;
    setChu("");
    setMo(r.playlist.id);
    toast.success(nhap
      ? `Đã lưu “${r.playlist.name}” (${r.playlist.items.length} bài).`
      : `Đã tạo “${r.playlist.name}”. Bấm + ở kết quả tìm để thêm bài.`);
  };

  const chiaSe = async (p: Playlist) => {
    const r = await lenh({ action: "export", id: p.id });
    if (!r?.code) return;
    try {
      await navigator.clipboard.writeText(r.code);
      toast.success(`Đã chép mã chia sẻ “${p.name}”. Người nhận dán vào ô playlist (c2a hoặc Home Assistant).`);
    } catch {
      // Trang http hoặc trình duyệt chặn clipboard: hiện mã để tự chép.
      window.prompt("Mã chia sẻ — chép rồi gửi cho người nhận:", r.code);
    }
  };

  const xoa = async (p: Playlist) => {
    if (!window.confirm(`Xoá playlist “${p.name}” (${p.items.length} bài)?`)) return;
    if (await lenh({ action: "delete", id: p.id })) toast.success(`Đã xoá “${p.name}”.`);
  };

  const dongDoiTen = async () => {
    if (!doiTen) return;
    const { id, ten } = doiTen;
    setDoiTen(null);
    if (ten.trim()) await lenh({ action: "rename", id, name: ten.trim() });
  };

  return (
    <div className="space-y-3">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void luu();
        }}
      >
        <Input
          value={chu}
          onChange={(e) => setChu(e.target.value)}
          maxLength={300_000}
          placeholder="Dán link playlist YouTube, album Zing, mã chia sẻ — hoặc gõ tên để tạo mới"
          aria-label="Link playlist, mã chia sẻ hoặc tên playlist mới"
          className="h-10 min-w-0 flex-1"
        />
        <Button type="submit" className="h-10 shrink-0" disabled={dangLuu || !chu.trim()}>
          {dangLuu ? <LoaderCircle className="animate-spin" /> : laLinkPlaylist(chu) || giongLink(chu) ? <ListPlus /> : <Plus />}
          <span className="hidden sm:inline">{laLinkPlaylist(chu) || giongLink(chu) ? "Lưu cả playlist" : "Tạo"}</span>
        </Button>
      </form>
      {dangLuu && laLinkPlaylist(chu) && (
        <p className="text-xs text-muted-foreground">Đang đọc playlist — playlist dài có thể mất vài chục giây.</p>
      )}

      {ds === null ? (
        <div className="flex justify-center py-8"><LoaderCircle className="size-5 animate-spin text-muted-foreground" /></div>
      ) : !ds.length ? (
        <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
          <ListMusic className="size-8 opacity-40" />
          Chưa có playlist. Dán link playlist để lưu cả danh sách, hoặc bấm + ở kết quả tìm.
        </div>
      ) : (
        <div className="space-y-2">
          {ds.map((p) => {
            const dangMo = mo === p.id;
            const hang = { items: p.items, playlist_id: p.id };
            return (
              <div key={p.id} className="rounded-xl border border-[var(--border)]">
                <div className="flex items-center gap-2 p-2">
                  <button
                    type="button"
                    onClick={() => setMo(dangMo ? "" : p.id)}
                    aria-expanded={dangMo}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  >
                    <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition", dangMo && "rotate-180")} />
                    {doiTen?.id === p.id ? null : (
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{p.name}</span>
                        <span className="block text-xs text-muted-foreground">{p.items.length} bài</span>
                      </span>
                    )}
                  </button>
                  {doiTen?.id === p.id && (
                    <form
                      className="flex min-w-0 flex-1 gap-1"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void dongDoiTen();
                      }}
                    >
                      <Input autoFocus value={doiTen.ten} maxLength={80} onChange={(e) => setDoiTen({ id: p.id, ten: e.target.value })} className="h-8 min-w-0 flex-1 text-sm" />
                      <Button type="submit" size="icon" className="size-8" aria-label="Lưu tên"><Check /></Button>
                    </form>
                  )}
                  <Button
                    type="button"
                    size="icon"
                    variant="outline"
                    className="shrink-0 rounded-full"
                    disabled={!p.items.length || !!dangGuiMa}
                    aria-label={`Phát playlist ${p.name}`}
                    title={coLoa ? "Phát cả playlist ra loa đã chọn" : "Nghe cả playlist trên máy này"}
                    onClick={() => p.items[0] && phat(p.items[0], false, hang)}
                  >
                    {coLoa ? <Play className="translate-x-px" /> : <Headphones />}
                  </Button>
                  <Button type="button" size="icon" variant="ghost" className="shrink-0 rounded-full text-muted-foreground" aria-label={`Chia sẻ ${p.name}`} title="Chép mã chia sẻ" onClick={() => void chiaSe(p)}>
                    <Copy />
                  </Button>
                  <Button type="button" size="icon" variant="ghost" className="shrink-0 rounded-full text-muted-foreground" aria-label={`Đổi tên ${p.name}`} title="Đổi tên" onClick={() => setDoiTen({ id: p.id, ten: p.name })}>
                    <Pencil />
                  </Button>
                  <Button type="button" size="icon" variant="ghost" className="shrink-0 rounded-full text-muted-foreground hover:text-[var(--destructive)]" aria-label={`Xoá ${p.name}`} title="Xoá playlist" onClick={() => void xoa(p)}>
                    <Trash2 />
                  </Button>
                </div>
                {dangMo && (
                  <div className="space-y-1 border-t border-[var(--border)] p-2">
                    {!p.items.length && <p className="py-3 text-center text-xs text-muted-foreground">Playlist trống — bấm + ở kết quả tìm để thêm bài.</p>}
                    {p.items.map((bai, i) => {
                      const ma = bai.url || bai.id;
                      const dangPhat = ma === dangPhatMa;
                      return (
                        <div key={`${ma}-${i}`} className={cn("flex items-center gap-2 rounded-lg p-1.5", dangPhat ? "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)]" : "hover:bg-[var(--muted)]")}>
                          <span className="w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{i + 1}</span>
                          <div className="relative hidden size-10 shrink-0 overflow-hidden rounded-md bg-[var(--muted)] sm:block">
                            {/^https?:\/\//.test(bai.thumbnail) ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={bai.thumbnail} alt="" loading="lazy" className="size-full object-cover" />
                            ) : (
                              <Music2 className="absolute inset-0 m-auto size-4 text-muted-foreground" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className={cn("line-clamp-2 text-sm leading-snug", dangPhat && "text-[var(--primary)]")}>{bai.title || bai.id}</div>
                            <div className="truncate text-xs text-muted-foreground">
                              {[bai.channel || bai.artist || TEN_NGUON[bai.source], thoiLuong(bai.duration)].filter(Boolean).join(" · ")}
                            </div>
                          </div>
                          {bai.source === "youtube" && (
                            <Button type="button" size="icon" variant="ghost" className="size-8 shrink-0 rounded-full text-muted-foreground" disabled={!!dangGuiMa} aria-label={`Xem video ${bai.title}`} title="Xem video" onClick={() => phat(bai, true, hang)}>
                              <MonitorPlay />
                            </Button>
                          )}
                          <Button type="button" size="icon" variant="outline" className="size-8 shrink-0 rounded-full" disabled={!!dangGuiMa} aria-label={`Phát ${bai.title}`} title={coLoa ? "Phát ra loa (hàng đợi là playlist)" : "Nghe trên máy này"} onClick={() => phat(bai, false, hang)}>
                            {coLoa ? <Play className="translate-x-px" /> : <Headphones />}
                          </Button>
                          <div className="flex shrink-0 flex-col">
                            <button type="button" className="text-muted-foreground hover:text-foreground disabled:opacity-30" disabled={i === 0} aria-label="Lên" onClick={() => void lenh({ action: "move", id: p.id, index: i, to: i - 1 })}>
                              <ArrowUp className="size-3.5" />
                            </button>
                            <button type="button" className="text-muted-foreground hover:text-foreground disabled:opacity-30" disabled={i === p.items.length - 1} aria-label="Xuống" onClick={() => void lenh({ action: "move", id: p.id, index: i, to: i + 1 })}>
                              <ArrowDown className="size-3.5" />
                            </button>
                          </div>
                          <button type="button" className="shrink-0 text-muted-foreground hover:text-[var(--destructive)]" aria-label={`Bỏ ${bai.title} khỏi playlist`} title="Bỏ khỏi playlist" onClick={() => void lenh({ action: "remove", id: p.id, index: i })}>
                            <X className="size-4" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
