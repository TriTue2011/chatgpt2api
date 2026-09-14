"use client";

/**
 * Trình phát — chức năng như thẻ Lovelace TriTue Music (tìm YouTube/Zing, link
 * audio, chọn nhiều loa/tivi, phát/tạm dừng/dừng, bài trước/tiếp, âm lượng từng
 * loa, tự chuyển bài), nhưng chạy thẳng trên c2a: `api/youtube_phat.py`.
 *
 * Một nút ▶ cho mỗi bài: có chọn loa thì phát ra loa, chưa chọn thì (bài YouTube)
 * xem video ngay trên trang. Nút điều khiển áp cho video khi video chạy một mình,
 * cho loa khi có loa. Loa kèm video (chủ máy 14/09/2026: "nếu tích loa thì có nghe
 * được nhạc không, kèm xem video không"): loa phát tiếng, video trên trang tắt
 * tiếng và tua theo vị trí loa báo về; đang xem mà tích loa thì loa phát bài đó
 * và — nếu loa tua được — tua tới chỗ video đang chạy.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { httpRequest } from "@/lib/request";
import { cn } from "@/lib/utils";

import { DangPhat, type VideoMo } from "./dang-phat";
import { DanhSachThietBi } from "./danh-sach-thiet-bi";
import { type BaiHat, dangHoatDong, goi, type Nguon, type Phien, type ThietBi } from "./lib";
import { TimNhac } from "./tim-nhac";
import { type CheDoXem, laVideo, srcNhung, useVideoNhung } from "./video-nhung";

const KHOA_CHON = "c2a-youtube:chon";
const KHOA_CHE_DO_XEM = "c2a-youtube:che-do-xem";
const DUOI_AUDIO = /\.(aac|flac|m3u8|m4a|mp3|ogg|opus|wav)$/i;
const DANG_CHAY = [1, 3];

type KetQuaPhat = { da_gui: string[]; bo_qua: { entity_id: string; ly_do: string }[]; phien: Phien };
type Hang = { items: BaiHat[]; index: number };

function docChon(): Set<string> {
  try {
    const v = JSON.parse(localStorage.getItem(KHOA_CHON) || "[]");
    return new Set(Array.isArray(v) ? v.map(String) : []);
  } catch {
    return new Set();
  }
}

function luuChon(chon: Set<string>) {
  try {
    localStorage.setItem(KHOA_CHON, JSON.stringify([...chon]));
  } catch {
    // Trình duyệt chặn bộ nhớ: vẫn chạy, chỉ không nhớ lựa chọn.
  }
}

/** Link audio dán tay → một "bài" để phát, kiểm sơ bộ ở trình duyệt (máy chủ kiểm lại). */
function baiTuLink(text: string): BaiHat {
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    throw new Error("Link không hợp lệ.");
  }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error("Chỉ nhận link http/https không kèm tài khoản.");
  }
  if (/(^|\.)youtube\.com$|^youtu\.be$/i.test(url.hostname)) {
    throw new Error("Đây là trang YouTube — chọn nguồn YouTube rồi dán link vào ô tìm.");
  }
  let ten = url.pathname.split("/").filter(Boolean).pop() || url.hostname;
  try {
    ten = decodeURIComponent(ten);
  } catch {
    // Giữ tên còn mã hoá khi link có ký tự thoát hỏng.
  }
  return {
    source: "http",
    id: url.href,
    url: url.href,
    title: ten,
    channel: DUOI_AUDIO.test(url.pathname) ? "Link audio" : "Link audio (đoán là MP3)",
    duration: null,
    thumbnail: "",
  };
}

const cungBai = (a: BaiHat, b: BaiHat) => (a.url || a.id) === (b.url || b.id);

export function TrinhPhat() {
  const [nguon, setNguon] = useState<Nguon>("youtube");
  const [tuKhoa, setTuKhoa] = useState("");
  const [ketQua, setKetQua] = useState<BaiHat[]>([]);
  const [dangTim, setDangTim] = useState(false);
  const [thietBi, setThietBi] = useState<ThietBi[] | null>(null);
  const [loiHa, setLoiHa] = useState("");
  const [phien, setPhien] = useState<Phien | null>(null);
  const [chon, setChon] = useState<Set<string>>(new Set());
  const [dangGuiMa, setDangGuiMa] = useState("");
  const [video, setVideo] = useState<VideoMo | null>(null);
  const [cheDo, setCheDo] = useState<CheDoXem>(() => {
    try {
      const v = localStorage.getItem(KHOA_CHE_DO_XEM);
      return v === "vua" || v === "rap" || v === "nho" ? v : "vua";
    } catch {
      return "vua";
    }
  });
  const [hangCucBo, setHangCucBo] = useState<Hang | null>(null);
  // Tự chuyển bài theo loa: nhớ thiết bị chính đã thật sự phát chưa, để "idle" lúc
  // vừa gửi lệnh không bị hiểu nhầm là bài đã hết.
  const tuChuyen = useRef({ bat: false, daPhat: false, chinh: "" });
  const daNapChon = useRef(false);
  const lucTai = useRef(0);
  const dongBo = useRef({ luiTuaDen: 0, giuDen: 0, choTua: null as null | { id: string; tu: number; luc: number } });

  const hetVideo = useRef<() => void>(() => undefined);
  const nhung = useVideoNhung(() => hetVideo.current());

  const taiThietBi = useCallback(async (imLang: boolean) => {
    try {
      const r = await httpRequest<{ ok: boolean; error?: string; items: ThietBi[]; phien: Phien }>(
        "/api/youtube-phat/thiet-bi", { method: "GET" });
      if (!r?.ok) {
        setLoiHa(r?.error || "Không đọc được danh sách thiết bị.");
        return;
      }
      lucTai.current = Date.now();
      setLoiHa("");
      setThietBi(r.items);
      setPhien(r.phien);
      if (!daNapChon.current) {
        daNapChon.current = true;
        const nho = docChon();
        const coThat = new Set(r.items.filter((t) => !t.an).map((t) => t.entity_id));
        const banDau = [...(nho.size ? nho : new Set(r.phien.output_entity_ids))].filter((id) => coThat.has(id));
        setChon(new Set(banDau));
      }
    } catch (e) {
      if (!imLang) toast.error(e instanceof Error ? e.message : "Lỗi mạng.");
    }
  }, []);

  // Loa kèm video thì hỏi dày hơn để hình bám theo loa kịp.
  const theoLoa = !!video?.theoLoa;
  useEffect(() => {
    void taiThietBi(false);
    const hen = setInterval(() => {
      if (document.visibilityState === "visible") void taiThietBi(true);
    }, theoLoa ? 2500 : 5000);
    return () => clearInterval(hen);
  }, [taiThietBi, theoLoa]);

  const doiCheDo = (c: CheDoXem) => {
    setCheDo(c);
    try {
      localStorage.setItem(KHOA_CHE_DO_XEM, c);
    } catch {
      // Như trên.
    }
  };

  const theoMa = useMemo(() => new Map((thietBi ?? []).map((t) => [t.entity_id, t])), [thietBi]);
  const daChon = useMemo(() => [...chon].map((id) => theoMa.get(id)).filter((t): t is ThietBi => !!t), [chon, theoMa]);
  const videoMotMinh = !!video && !video.theoLoa;
  const dangChay = videoMotMinh ? DANG_CHAY.includes(nhung.trangThai) : daChon.some((t) => t.trang_thai === "playing");

  const hang: Hang | null = hangCucBo ?? (phien?.state === "playing" ? phien.queue : null);
  const baiKe = (buoc: number): BaiHat | null => (hang && hang.index >= 0 ? hang.items[hang.index + buoc] ?? null : null);
  const truoc = baiKe(-1);
  const tiep = baiKe(1);

  const doiChon = (moi: Set<string>) => {
    setChon(moi);
    luuChon(moi);
  };

  const ghiHang = (bai: BaiHat) => {
    const nguonHang = ketQua.includes(bai) ? ketQua : hang?.items ?? [];
    const i = nguonHang.findIndex((k) => cungBai(k, bai));
    if (i >= 0) setHangCucBo({ items: nguonHang, index: i });
  };

  const moVideo = (bai: BaiHat, tatTieng: boolean) => {
    if (!laVideo(bai)) return;
    if (video && nhung.sanSang) {
      // Cùng khung: đổi bài không nạp lại, giữ nguyên cỡ xem và toàn màn hình.
      nhung.lenh("loadVideoById", [{ videoId: bai.id, startSeconds: 0 }]);
      nhung.lenh(tatTieng ? "mute" : "unMute");
      setVideo({ ...video, bai, theoLoa: tatTieng });
    } else {
      nhung.datLai();
      setVideo({ bai, src: srcNhung(bai.id, tatTieng), theoLoa: tatTieng });
    }
    if (cheDo !== "nho") {
      requestAnimationFrame(() => document.getElementById("khoi-dang-phat")?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    }
  };

  const dongVideo = () => {
    nhung.datLai();
    dongBo.current.choTua = null;
    setVideo(null);
  };

  const phat = async (bai: BaiHat, chiThietBi?: string[]) => {
    if (!chiThietBi) ghiHang(bai);
    const ids = chiThietBi ?? [...chon].filter((id) => theoMa.get(id)?.phat_duoc);
    if (!ids.length) {
      if (!chon.size && laVideo(bai)) {
        // Chưa chọn loa: xem ngay trên trang.
        tuChuyen.current.bat = false;
        moVideo(bai, false);
        return;
      }
      toast.error(chon.size ? "Thiết bị đã chọn không nhận phát nhạc." : "Chọn loa hoặc tivi để phát Zing MP3 hoặc link audio.");
      return;
    }
    const ma = bai.url || bai.id;
    setDangGuiMa(ma);
    const r = await goi<KetQuaPhat>("phat", {
      source: bai.source,
      target: ma,
      entity_ids: ids,
      ...(bai.media_content_type ? { media_content_type: bai.media_content_type } : {}),
    });
    setDangGuiMa("");
    if (!r) return;
    setPhien(r.phien);
    // Theo dõi hết bài trên loa nhận âm thanh: tivi mở ứng dụng YouTube chỉ báo "on",
    // không bao giờ về "idle" khi hết bài.
    const chinh = r.da_gui.find((id) => bai.source !== "youtube" || theoMa.get(id)?.youtube === "am_thanh") ?? r.da_gui[0];
    if (!chiThietBi) tuChuyen.current = { bat: true, daPhat: false, chinh };
    const ten = (id: string) => theoMa.get(id)?.ten ?? id;
    if (r.bo_qua.length) {
      toast.warning(`Đã gửi tới ${r.da_gui.map(ten).join(", ")}. Bỏ qua: ${r.bo_qua.map((b) => ten(b.entity_id)).join(", ")}.`);
    } else {
      toast.success(`Đang phát trên ${r.da_gui.map(ten).join(", ")}.`);
    }
    if (video && !chiThietBi) {
      // Hình theo loa: bài YouTube kế tiếp tắt tiếng và bám loa; nguồn chỉ có tiếng thì đóng hình.
      if (laVideo(bai)) moVideo(bai, true);
      else dongVideo();
    }
    void taiThietBi(true);
  };

  const chuyenBai = (buoc: number) => {
    const bai = baiKe(buoc);
    if (!bai) return;
    if (videoMotMinh && laVideo(bai)) {
      // Đang xem một mình: bài trước/tiếp vẫn ở trên trang.
      if (hang) setHangCucBo({ items: hang.items, index: hang.index + buoc });
      moVideo(bai, false);
      return;
    }
    void phat(bai);
  };

  // Mọi hàm chạy trong hẹn giờ đọc bản mới nhất qua ref này.
  const moiNhat = useRef({ chuyenBai, video, thietBi, chon, nhung });
  useEffect(() => {
    moiNhat.current = { chuyenBai, video, thietBi, chon, nhung };
    hetVideo.current = () => {
      // Hết video: chạy một mình thì tự sang bài kế; có loa thì loa quyết định.
      if (moiNhat.current.video && !moiNhat.current.video.theoLoa) moiNhat.current.chuyenBai(1);
    };
  });

  // Tự chuyển bài khi loa chính phát xong (không tính "tạm dừng").
  useEffect(() => {
    const tc = tuChuyen.current;
    if (!tc.bat || !tc.chinh) return;
    const tb = theoMa.get(tc.chinh);
    if (!tb) return;
    if (tb.trang_thai === "playing" || tb.trang_thai === "buffering") {
      tc.daPhat = true;
      return;
    }
    if (!tc.daPhat || !["idle", "off", "standby"].includes(tb.trang_thai)) return;
    tc.daPhat = false;
    if (tiep) void phat(tiep);
    else tc.bat = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theoMa]);

  // Hình trên trang bám theo loa: tạm dừng/phát theo loa, tua khi lệch quá 2 giây.
  useEffect(() => {
    if (!theoLoa) return;
    const hen = setInterval(() => {
      const { thietBi: ds, chon: dangChon, nhung: n } = moiNhat.current;
      if (!n.sanSang) return;
      const db = dongBo.current;
      if (db.choTua) {
        const loa = ds?.find((t) => t.entity_id === db.choTua?.id);
        if (Date.now() - db.choTua.luc > 60000) {
          db.choTua = null;
        } else if (loa?.trang_thai === "playing") {
          const cho = db.choTua;
          db.choTua = null;
          if (loa.tua) {
            // Loa vừa nhập vào video đang xem: tua loa tới chỗ hình, không kéo hình về đầu.
            void goi("dieu-khien", { lenh: "tua", entity_ids: [loa.entity_id], vi_tri: Math.round(cho.tu + (Date.now() - cho.luc) / 1000) });
            db.luiTuaDen = Date.now() + 10000;
          }
        }
        return;
      }
      const loa = ds?.find((t) => dangChon.has(t.entity_id) && dangHoatDong(t));
      if (!loa || Date.now() < db.giuDen) return;
      if (loa.trang_thai === "paused" && DANG_CHAY.includes(n.trangThai)) n.lenh("pauseVideo");
      if (loa.trang_thai === "playing" && [-1, 2, 5].includes(n.trangThai)) n.lenh("playVideo");
      if (loa.trang_thai !== "playing" || loa.vi_tri === null || Date.now() < db.luiTuaDen) return;
      const viTriLoa = loa.vi_tri + (Date.now() - lucTai.current) / 1000;
      if (Math.abs(viTriLoa - n.thoiGian()) > 2) {
        n.lenh("seekTo", [viTriLoa, true]);
        db.luiTuaDen = Date.now() + 5000;
      }
    }, 2000);
    return () => clearInterval(hen);
  }, [theoLoa]);

  const tim = async () => {
    const q = tuKhoa.trim();
    if (!q) return;
    if (nguon === "http") {
      try {
        setKetQua([baiTuLink(q)]);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Link không hợp lệ.");
      }
      return;
    }
    setDangTim(true);
    setKetQua([]);
    const r = await goi<{ items: BaiHat[] }>(`tim?source=${nguon}&q=${encodeURIComponent(q)}`);
    setDangTim(false);
    if (!r) return;
    setKetQua(r.items);
    if (!r.items.length) toast.message("Không tìm thấy bài phù hợp.");
  };

  const loaNhapVideo = async (tb: ThietBi, v: VideoMo) => {
    const tu = nhung.thoiGian();
    const r = await goi<KetQuaPhat>("phat", { source: "youtube", target: v.bai.url || v.bai.id, entity_ids: [tb.entity_id] });
    if (!r) return;
    setPhien(r.phien);
    nhung.lenh("mute");
    setVideo({ ...v, theoLoa: true });
    dongBo.current.choTua = { id: tb.entity_id, tu, luc: Date.now() };
    tuChuyen.current = { bat: true, daPhat: false, chinh: tb.entity_id };
    toast.success(`${tb.ten} phát tiếng; video trên trang tắt tiếng và chạy theo loa.`);
    void taiThietBi(true);
  };

  const batTat = (tb: ThietBi) => {
    const moi = new Set(chon);
    if (moi.has(tb.entity_id)) {
      moi.delete(tb.entity_id);
      // Bỏ chọn thiết bị đang phát thì tắt riêng nó, các loa khác phát tiếp.
      if (dangHoatDong(tb) && tb.dung) void goi("dieu-khien", { lenh: "dung_rieng", entity_ids: [tb.entity_id] });
      if (video?.theoLoa && !moi.size) {
        // Hết loa: trang lấy lại tiếng.
        nhung.lenh("unMute");
        dongBo.current.choTua = null;
        setVideo({ ...video, theoLoa: false });
      }
    } else {
      moi.add(tb.entity_id);
      if (videoMotMinh && video && tb.trang_thai !== "unavailable") {
        void loaNhapVideo(tb, video);
      } else if (tuChuyen.current.bat && phien?.state === "playing" && phien.item && tb.trang_thai !== "unavailable") {
        // Chọn thêm lúc đang phát thì thiết bị mới vào nghe cùng bài.
        void phat(phien.item, [tb.entity_id]);
      }
    }
    doiChon(moi);
  };

  const dieuKhien = async (lenh: "phat_tam_dung" | "dung", loc: (t: ThietBi) => boolean) => {
    const ids = daChon.filter((t) => t.trang_thai !== "unavailable" && loc(t)).map((t) => t.entity_id);
    if (!ids.length) return false;
    if (lenh === "dung") tuChuyen.current.bat = false;
    if (await goi("dieu-khien", { lenh, entity_ids: ids })) void taiThietBi(true);
    return true;
  };

  const phatTamDung = () => {
    if (videoMotMinh) {
      nhung.lenh(DANG_CHAY.includes(nhung.trangThai) ? "pauseVideo" : "playVideo");
      return;
    }
    if (video) {
      nhung.lenh(dangChay ? "pauseVideo" : "playVideo");
      // Loa báo trạng thái mới sau vài giây; đừng để vòng bám loa đảo lại lần bấm này.
      dongBo.current.giuDen = Date.now() + 7000;
    }
    void dieuKhien("phat_tam_dung", (t) => t.tam_dung).then((co) => {
      if (!co && !video) toast.error("Thiết bị đã chọn không hỗ trợ phát/tạm dừng.");
    });
  };

  const dung = () => {
    tuChuyen.current.bat = false;
    if (video) nhung.lenh("stopVideo");
    void dieuKhien("dung", (t) => t.dung).then((co) => {
      if (!co && !video) toast.error("Không thiết bị đã chọn nào dừng được.");
    });
  };

  const an = async (ids: string[], giaTri: boolean) => {
    if (!(await goi("an", { entity_ids: ids, an: giaTri }))) return;
    if (giaTri) doiChon(new Set([...chon].filter((id) => !ids.includes(id))));
    await taiThietBi(true);
  };

  const coLoaDieuKhien = daChon.some((t) => t.trang_thai !== "unavailable" && (t.tam_dung || t.dung));
  const baiDangPhat = phien?.state === "playing" ? phien.item : null;
  const rap = !!video && cheDo === "rap";

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <DangPhat
        className={cn("min-w-0", rap ? "lg:col-span-2" : "lg:col-start-2 lg:row-start-1")}
        phien={phien}
        thietBi={thietBi ?? []}
        video={video}
        nhung={nhung}
        cheDo={cheDo}
        doiCheDo={doiCheDo}
        dongVideo={dongVideo}
        dangChay={dangChay}
        dangGui={!!dangGuiMa}
        truoc={truoc ? () => chuyenBai(-1) : null}
        tiep={tiep ? () => chuyenBai(1) : null}
        phatTamDung={video || coLoaDieuKhien ? phatTamDung : null}
        dung={video || coLoaDieuKhien ? dung : null}
        xemTaiDay={!video && laVideo(baiDangPhat) ? () => moVideo(baiDangPhat, daChon.some(dangHoatDong)) : null}
      />
      <DanhSachThietBi
        className={cn("min-w-0", "lg:col-start-2 lg:row-start-2")}
        thietBi={thietBi}
        loi={loiHa}
        chon={chon}
        batTat={batTat}
        amLuong={(tb, v) => void goi("dieu-khien", { lenh: "am_luong", entity_ids: [tb.entity_id], am_luong: v })}
        an={an}
        taiLai={() => void taiThietBi(false)}
      />
      <TimNhac
        className={cn("min-w-0", rap ? "lg:col-start-1 lg:row-start-2" : "lg:col-start-1 lg:row-span-2 lg:row-start-1")}
        nguon={nguon}
        doiNguon={(n) => {
          setNguon(n);
          setKetQua([]);
        }}
        tuKhoa={tuKhoa}
        setTuKhoa={setTuKhoa}
        tim={() => void tim()}
        dangTim={dangTim}
        ketQua={ketQua}
        dangPhatMa={video ? video.bai.url || video.bai.id : baiDangPhat ? baiDangPhat.url || baiDangPhat.id : ""}
        dangGuiMa={dangGuiMa}
        coLoa={chon.size > 0}
        phat={(bai) => void phat(bai)}
      />
    </div>
  );
}
