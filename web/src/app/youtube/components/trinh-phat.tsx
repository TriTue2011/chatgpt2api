"use client";

/**
 * Trình phát — tìm YouTube/Zing, link audio, phát ra loa/tivi HA theo PHIÊN.
 *
 * Chủ máy 14/09/2026: "Làm mỗi loa một bài hoặc chạy cùng 1 bài", "tắt trình duyệt
 * vẫn hoạt động", "mở mỗi bài 1 loa thì làm sao xem nó phát đến đâu, video đến đâu
 * khi tích vào mỗi loa". Luật:
 * - Tích loa = xem và điều khiển loa đó: "Đang phát", tiến độ và video theo phiên
 *   của loa vừa tích. Tích/bỏ tích không tự phát hay tắt loa.
 * - Mỗi bài hai nút: nghe (chỉ tiếng) và xem video. Có tích loa: phát ra các loa đó
 *   (thành một phiên, rời phiên cũ), nút xem video mở thêm video tắt tiếng theo loa.
 *   Chưa tích loa: nghe hoặc xem ngay trên máy này.
 * - ⏹ dừng các loa đang tích; ⏮⏭ theo hàng đợi của phiên. Máy chủ c2a tự chuyển
 *   bài khi loa hết bài (`services/youtube_phat/tu_chuyen_bai.py`), nên đóng trang
 *   nhạc vẫn chạy.
 * - Phát ra loa (chỉ nghe hoặc kèm video): máy này tắt tiếng; nút "Nghe cả trên máy
 *   này" mở tiếng trên máy, chạy theo vị trí loa. Không tích loa: máy này phát tiếng.
 *   Đang xem một mình mà tích loa thì loa phát tiếng video đó.
 * - Nghe trên máy này dùng thẻ <audio> qua luồng máy chủ. Nút "Nghe khi tắt màn
 *   hình" (nhớ lựa chọn, mặc định tắt): tắt thì trang bị ẩn (tắt màn hình, đổi ứng
 *   dụng) là tiếng trên máy dừng, mở lại thì phát tiếp; bật thì nghe tiếp, có nút ở
 *   màn hình khoá, và video xem trên máy (nếu mở) tắt tiếng chạy theo tiếng.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { httpRequest } from "@/lib/request";
import { cn } from "@/lib/utils";

import { DangPhat, type VideoMo, type ViTri } from "./dang-phat";
import { DanhSachThietBi } from "./danh-sach-thiet-bi";
import { type BaiHat, dangHoatDong, dangPhatBai, goi, type Nguon, type Phien, TEN_NGUON, type ThietBi } from "./lib";
import { TimNhac } from "./tim-nhac";
import { type CheDoXem, laVideo, srcNhung, useVideoNhung } from "./video-nhung";

const KHOA_CHON = "c2a-youtube:chon";
const KHOA_CHE_DO_XEM = "c2a-youtube:che-do-xem";
const KHOA_NGHE_NEN = "c2a-youtube:nghe-khi-tat-man-hinh";
// Nửa giây im lặng: phát ngay trong cú bấm để Safari/iOS mở khoá thẻ âm thanh, rồi
// mới đổi sang luồng thật khi máy chủ trả link (lúc đó cú bấm đã qua).
const AM_LANG = "data:audio/wav;base64,UklGRrQBAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YZABAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA";
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
  const [cacPhien, setCacPhien] = useState<Phien[]>([]);
  const [chon, setChon] = useState<Set<string>>(new Set());
  const [loaVuaTich, setLoaVuaTich] = useState("");
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
  const [ngheNen, setNgheNen] = useState(() => {
    try {
      return localStorage.getItem(KHOA_NGHE_NEN) === "1";
    } catch {
      return false;
    }
  });
  // Bài đang nghe trên máy này bằng thẻ <audio> (nghe khi tắt màn hình, hoặc Zing).
  const [nghe, setNghe] = useState<BaiHat | null>(null);
  const [ngheChay, setNgheChay] = useState(false);
  const am = useRef<HTMLAudioElement | null>(null);
  const luotNghe = useRef(0);
  // Máy này nghe cùng loa (không mở video, hoặc bật nghe khi tắt màn hình): <audio> bám vị trí loa.
  const [ngheCungLoa, setNgheCungLoa] = useState(false);
  const mucCungLoa = useRef("");
  // Trình duyệt chặn tiếng tự phát của khung video: bảo người xem chạm vào video.
  const [canCham, setCanCham] = useState(false);
  // Hàng đợi của video/bài nghe một mình trên trang. Loa dùng hàng đợi của phiên máy chủ.
  const [hangVideo, setHangVideo] = useState<Hang | null>(null);
  const daNapChon = useRef(false);
  const lucTai = useRef(0);
  const dongBo = useRef({ luiTuaDen: 0, luiTuaAm: 0, giuDen: 0, choTua: null as null | { id: string; tu: number; luc: number } });

  const hetVideo = useRef<() => void>(() => undefined);
  const nhung = useVideoNhung(() => hetVideo.current());

  const taiThietBi = useCallback(async (imLang: boolean) => {
    try {
      const r = await httpRequest<{ ok: boolean; error?: string; items: ThietBi[]; phien: Phien; cac_phien: Phien[] }>(
        "/api/youtube-phat/thiet-bi", { method: "GET" });
      if (!r?.ok) {
        setLoiHa(r?.error || "Không đọc được danh sách thiết bị.");
        return;
      }
      lucTai.current = Date.now();
      setLoiHa("");
      setThietBi(r.items);
      setCacPhien(r.cac_phien ?? []);
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

  // Phiên đang xem: của loa vừa tích, không thì của loa đang tích bất kỳ, không tích gì thì phiên mới nhất.
  const phienXem = useMemo(() => {
    if (loaVuaTich && chon.has(loaVuaTich)) {
      const cua = cacPhien.find((p) => p.output_entity_ids.includes(loaVuaTich));
      if (cua) return cua;
    }
    return cacPhien.find((p) => p.output_entity_ids.some((id) => chon.has(id))) ?? (chon.size ? null : cacPhien[0] ?? null);
  }, [cacPhien, chon, loaVuaTich]);
  const cacPhienKhac = cacPhien.filter((p) => p.session_id !== phienXem?.session_id);
  const ngheCungIds = phienXem
    ? daChon.filter((t) => !phienXem.output_entity_ids.includes(t.entity_id) && t.trang_thai !== "unavailable" && t.phat_duoc).map((t) => t.entity_id)
    : [];

  // Video tự phát tiếng trên trang (không theo loa, không theo thẻ âm thanh).
  const videoMotMinh = !!video && !video.theoLoa && !video.theoMay;
  const loaPhien = phienXem ? phienXem.output_entity_ids.map((id) => theoMa.get(id)).filter((t): t is ThietBi => !!t) : daChon;
  const dangChay = nghe ? ngheChay : videoMotMinh ? DANG_CHAY.includes(nhung.trangThai) : loaPhien.some((t) => t.trang_thai === "playing");

  const doiChon = (moi: Set<string>) => {
    setChon(moi);
    luuChon(moi);
  };

  /** `theoMay` = tiếng do thẻ <audio> của máy này phát; video tắt tiếng và chạy theo. */
  const moVideo = (bai: BaiHat, voiLoa: boolean, batDau = 0, theoMay = false) => {
    if (!laVideo(bai)) return;
    const ngheTrenMay = theoMay ? false : voiLoa ? (video?.theoLoa ? video.ngheTrenMay : false) : true;
    if (video && nhung.sanSang) {
      // Cùng khung: đổi bài không nạp lại, giữ nguyên cỡ xem và toàn màn hình.
      if (video.bai.id !== bai.id) nhung.lenh("loadVideoById", [{ videoId: bai.id, startSeconds: batDau }]);
      nhung.lenh(ngheTrenMay ? "unMute" : "mute");
      setVideo({ ...video, bai, theoLoa: voiLoa, ngheTrenMay, theoMay });
    } else {
      nhung.datLai();
      setVideo({ bai, src: srcNhung(bai.id, !ngheTrenMay, batDau), theoLoa: voiLoa, ngheTrenMay, theoMay });
    }
    dongBo.current.luiTuaDen = 0;
    if (cheDo !== "nho") {
      requestAnimationFrame(() => document.getElementById("khoi-dang-phat")?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    }
  };

  const dongVideo = () => {
    nhung.datLai();
    dongBo.current.choTua = null;
    setVideo(null);
  };

  const theAm = () => {
    if (!am.current) {
      const a = new Audio();
      a.preload = "auto";
      const that = () => !!a.getAttribute("src") && !a.getAttribute("src")!.startsWith("data:");
      a.addEventListener("play", () => setNgheChay(true));
      a.addEventListener("pause", () => setNgheChay(false));
      a.addEventListener("ended", () => {
        if (that()) moiNhat.current.hetNghe();
      });
      a.addEventListener("error", () => {
        if (that()) toast.error("Không phát được bài này trên máy này.");
      });
      am.current = a;
    }
    return am.current;
  };

  /** Nghe một bài trên máy này bằng <audio>; `batDau` = giây bắt đầu (chuyển từ video sang). */
  const ngheBai = async (bai: BaiHat, hangMoi: Hang, batDau = 0, dongHinh = false) => {
    const a = theAm();
    const luot = ++luotNghe.current;
    a.src = AM_LANG;
    void a.play().catch(() => undefined);
    // Video đang mở thì theo bài mới, tắt tiếng, chạy theo tiếng; chỉ nghe hoặc bài không có video thì đóng.
    if (video && laVideo(bai) && !dongHinh) moVideo(bai, false, batDau, true);
    else if (video) dongVideo();
    setNgheCungLoa(false);
    setHangVideo(hangMoi);
    setNghe(bai);
    const ke = hangMoi.items[hangMoi.index + 1];
    const r = await goi<{ url: string }>("nghe", {
      source: bai.source,
      target: bai.url || bai.id,
      ...(ke && ke.source !== "http" ? { ke } : {}),
    });
    if (luot !== luotNghe.current) return;
    if (!r) {
      dungNghe();
      return;
    }
    a.src = r.url;
    if (batDau >= 1) a.addEventListener("loadedmetadata", () => { a.currentTime = batDau; }, { once: true });
    a.play().catch(() => toast.message("Trình duyệt chặn tự phát có tiếng — bấm ▶ để nghe."));
  };

  const dungNghe = () => {
    luotNghe.current++;
    const a = am.current;
    if (a) {
      a.pause();
      a.removeAttribute("src");
      a.load();
    }
    setNghe(null);
    setNgheChay(false);
  };

  const capNhatPhien = (r: { cac_phien?: Phien[] } | null) => {
    if (r?.cac_phien) setCacPhien(r.cac_phien);
    void taiThietBi(true);
  };

  /** `xem` = nút xem video; không thì chỉ nghe. */
  const phat = async (bai: BaiHat, xem = false) => {
    const ids = [...chon].filter((id) => theoMa.get(id)?.phat_duoc);
    if (!chon.size) {
      // Chưa tích loa: nghe hoặc xem ngay trên máy này, với hàng đợi riêng.
      const i = ketQua.findIndex((k) => cungBai(k, bai));
      const hangMoi = i >= 0 ? { items: ketQua, index: i } : { items: [bai], index: 0 };
      if (xem && laVideo(bai)) {
        if (ngheNen) {
          // Nghe khi tắt màn hình: tiếng từ thẻ âm thanh, video tắt tiếng chạy theo.
          const coHinh = !!video;
          void ngheBai(bai, hangMoi);
          if (!coHinh) moVideo(bai, false, 0, true);
          return;
        }
        if (nghe) dungNghe();
        setHangVideo(hangMoi);
        moVideo(bai, false);
        return;
      }
      if (bai.source === "http") {
        toast.error("Tích loa hoặc tivi để phát link audio.");
        return;
      }
      void ngheBai(bai, hangMoi, 0, true);
      return;
    }
    if (!ids.length) {
      toast.error("Thiết bị đang tích không nhận phát nhạc.");
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
    if (nghe) dungNghe();
    const ten = (id: string) => theoMa.get(id)?.ten ?? id;
    if (r.bo_qua.length) {
      toast.warning(`Đã gửi tới ${r.da_gui.map(ten).join(", ")}. Bỏ qua: ${r.bo_qua.map((b) => ten(b.entity_id)).join(", ")}.`);
    } else {
      toast.success(`Đang phát trên ${r.da_gui.map(ten).join(", ")}.`);
    }
    if (xem && laVideo(bai)) {
      moVideo(bai, true);
    } else if (video) {
      // Hình theo loa: bài YouTube tắt tiếng và bám loa; nguồn chỉ có tiếng thì đóng hình.
      if (laVideo(bai)) moVideo(bai, true);
      else dongVideo();
    }
    void taiThietBi(true);
  };

  const hang = videoMotMinh || nghe ? hangVideo : phienXem?.queue ?? null;
  const coBai = (buoc: number) => !!hang && hang.index >= 0 && !!hang.items[hang.index + buoc];

  const chuyenBai = async (buoc: number) => {
    if (nghe) {
      const bai = hangVideo?.items[hangVideo.index + buoc];
      if (!hangVideo || !bai || bai.source === "http") return;
      void ngheBai(bai, { ...hangVideo, index: hangVideo.index + buoc });
      return;
    }
    if (videoMotMinh) {
      if (!hangVideo) return;
      const bai = hangVideo.items[hangVideo.index + buoc];
      if (!bai || !laVideo(bai)) return;
      setHangVideo({ ...hangVideo, index: hangVideo.index + buoc });
      moVideo(bai, false);
      return;
    }
    if (!phienXem) return;
    setDangGuiMa("chuyen-bai");
    const r = await goi<{ cac_phien: Phien[] }>("chuyen-bai", { session_id: phienXem.session_id, buoc });
    setDangGuiMa("");
    capNhatPhien(r);
  };

  // Mọi hàm chạy trong hẹn giờ đọc bản mới nhất qua ref này.
  const baiPhienXem = phienXem?.item ?? null;
  const moiNhat = useRef({
    chuyenBai, video, thietBi, loaPhien, nhung, baiPhienXem, nghe, dungNghe, ngheNen,
    taiCungLoa: async (_bai: BaiHat) => undefined as void,
    tatNgheCungLoa: () => undefined as void,
    hetNghe: () => undefined as void,
  });
  useEffect(() => {
    moiNhat.current = {
      chuyenBai, video, thietBi, loaPhien, nhung, baiPhienXem, nghe, dungNghe, ngheNen, taiCungLoa, tatNgheCungLoa,
      // Hết bài đang nghe trên máy này: sang bài kế của hàng đợi trên trang.
      hetNghe: () => {
        if (moiNhat.current.nghe) void moiNhat.current.chuyenBai(1);
      },
    };
    hetVideo.current = () => {
      // Hết video xem một mình: tự sang bài kế trên trang. Có loa thì máy chủ lo.
      const v = moiNhat.current.video;
      if (v && !v.theoLoa && !v.theoMay) void moiNhat.current.chuyenBai(1);
    };
  });

  // Tích sang loa khác: video đổi sang bài của loa đó và tua theo loa.
  useEffect(() => {
    if (!video?.theoLoa || !baiPhienXem) return;
    if (baiPhienXem.id === video.bai.id) return;
    if (laVideo(baiPhienXem)) {
      moVideo(baiPhienXem, true);
    } else {
      dongVideo();
      toast.message("Loa này đang phát Zing/link audio — không có video.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baiPhienXem?.id, video?.theoLoa]);

  // Hình trên trang bám theo loa: tạm dừng/phát theo loa, tua khi lệch quá 2 giây.
  useEffect(() => {
    if (!theoLoa) return;
    const hen = setInterval(() => {
      const { loaPhien: ds, nhung: n, baiPhienXem: baiLoa, video: v } = moiNhat.current;
      if (!n.sanSang) return;
      const db = dongBo.current;
      if (db.choTua) {
        const loa = ds.find((t) => t.entity_id === db.choTua?.id);
        if (Date.now() - db.choTua.luc > 60000) {
          db.choTua = null;
        } else if (loa?.trang_thai === "playing" && dangPhatBai(loa, v?.bai)) {
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
      const loa = ds.find((t) => dangHoatDong(t));
      // Loa còn báo bài trước (vừa gửi bài mới): chưa bám theo, kẻo hình nhảy tới giây cũ.
      if (!loa || Date.now() < db.giuDen || !dangPhatBai(loa, baiLoa)) return;
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

  const layViTri = (): ViTri => {
    if (nghe) {
      const a = am.current;
      if (!a || !a.getAttribute("src") || a.getAttribute("src")!.startsWith("data:")) return null;
      return { giay: a.currentTime, tong: Number.isFinite(a.duration) && a.duration > 0 ? a.duration : Number(nghe.duration || 0) };
    }
    if (videoMotMinh) {
      if (nhung.trangThai === -1) return null;
      return { giay: nhung.thoiGian(), tong: Number(video?.bai.duration || 0) };
    }
    const dan = loaPhien.find((t) => t.vi_tri !== null && dangPhatBai(t, phienXem?.item));
    if (!phienXem || !dan || dan.vi_tri === null) return null;
    const giay = dan.vi_tri + (dan.trang_thai === "playing" ? (Date.now() - lucTai.current) / 1000 : 0);
    return { giay, tong: Number(dan.thoi_luong || phienXem.item?.duration || 0) };
  };

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
    nhung.lenh("mute");
    setVideo({ ...v, theoLoa: true, ngheTrenMay: false });
    dongBo.current.choTua = { id: tb.entity_id, tu, luc: Date.now() };
    toast.success(`${tb.ten} phát tiếng; video trên trang tắt tiếng và chạy theo loa.`);
    void taiThietBi(true);
  };

  const batTat = (tb: ThietBi) => {
    const moi = new Set(chon);
    if (moi.has(tb.entity_id)) {
      moi.delete(tb.entity_id);
      if (video?.theoLoa && !moi.size) {
        // Không còn loa nào tích: video trên trang phát tiếp một mình, có tiếng.
        nhung.lenh("unMute");
        dongBo.current.choTua = null;
        setVideo({ ...video, theoLoa: false, ngheTrenMay: true });
      }
    } else {
      moi.add(tb.entity_id);
      setLoaVuaTich(tb.entity_id);
      if (videoMotMinh && video && tb.trang_thai !== "unavailable") void loaNhapVideo(tb, video);
    }
    doiChon(moi);
  };

  const chonNhom = (p: Phien) => {
    doiChon(new Set(p.output_entity_ids));
    setLoaVuaTich(p.output_entity_ids[0] ?? "");
  };

  const ngheCung = async () => {
    if (!phienXem?.item || !ngheCungIds.length) return;
    const r = await goi<KetQuaPhat>("phat", {
      source: phienXem.item.source,
      target: phienXem.item.url || phienXem.item.id,
      entity_ids: ngheCungIds,
      session_id: phienXem.session_id,
      join_ids: phienXem.output_entity_ids,
    });
    if (r) toast.success("Đã cho nghe cùng bài đang phát.");
    void taiThietBi(true);
  };

  const phatTamDung = () => {
    if (nghe) {
      const a = am.current;
      if (a?.paused) void a.play().catch(() => undefined);
      else a?.pause();
      return;
    }
    if (videoMotMinh) {
      nhung.lenh(DANG_CHAY.includes(nhung.trangThai) ? "pauseVideo" : "playVideo");
      return;
    }
    const ids = loaPhien.filter((t) => t.trang_thai !== "unavailable" && t.tam_dung).map((t) => t.entity_id);
    if (!ids.length) {
      toast.error("Loa đang xem không hỗ trợ phát/tạm dừng.");
      return;
    }
    if (video) {
      nhung.lenh(dangChay ? "pauseVideo" : "playVideo");
      // Loa báo trạng thái mới sau vài giây; đừng để vòng bám loa đảo lại lần bấm này.
      dongBo.current.giuDen = Date.now() + 7000;
    }
    void goi("dieu-khien", { lenh: "phat_tam_dung", entity_ids: ids }).then(() => taiThietBi(true));
  };

  const dung = async () => {
    if (nghe) {
      dungNghe();
      if (video?.theoMay) dongVideo();
      return;
    }
    if (video) nhung.lenh("stopVideo");
    if (phienXem) {
      // Dừng các loa đang tích; phiên chỉ kết thúc khi mọi loa của nó dừng.
      const tich = phienXem.output_entity_ids.filter((id) => chon.has(id));
      const r = tich.length && tich.length < phienXem.output_entity_ids.length
        ? await goi<{ cac_phien: Phien[] }>("bo-loa", { entity_ids: tich })
        : await goi<{ cac_phien: Phien[] }>("dung-phien", { session_id: phienXem.session_id });
      capNhatPhien(r);
      return;
    }
    const ids = daChon.filter((t) => t.dung && t.trang_thai !== "unavailable").map((t) => t.entity_id);
    if (ids.length) void goi("dieu-khien", { lenh: "dung", entity_ids: ids }).then(() => taiThietBi(true));
    else if (!video) toast.error("Không có gì đang phát.");
  };

  const an = async (ids: string[], giaTri: boolean) => {
    if (!(await goi("an", { entity_ids: ids, an: giaTri }))) return;
    if (giaTri) doiChon(new Set([...chon].filter((id) => !ids.includes(id))));
    await taiThietBi(true);
  };

  const tatNgheCungLoa = () => {
    setNgheCungLoa(false);
    mucCungLoa.current = "";
    luotNghe.current++;
    const a = am.current;
    if (a) {
      a.pause();
      a.removeAttribute("src");
      a.load();
    }
  };

  /** Bắt đầu nghe cùng loa trên máy này; phải gọi trong cú bấm để mở khoá thẻ âm thanh. */
  const batNgheCungLoa = () => {
    const bai = phienXem?.item;
    if (!bai || bai.source === "http") {
      toast.error("Link audio chỉ nghe được trên loa.");
      return;
    }
    const a = theAm();
    a.src = AM_LANG;
    void a.play().catch(() => undefined);
    mucCungLoa.current = "";
    setNgheCungLoa(true);
  };

  const taiCungLoa = async (bai: BaiHat) => {
    const luot = ++luotNghe.current;
    const r = await goi<{ url: string }>("nghe", { source: bai.source, target: bai.url || bai.id });
    if (luot !== luotNghe.current || !r) return;
    const a = theAm();
    a.src = r.url;
    a.play().catch(() => toast.message("Trình duyệt chặn tự phát có tiếng — bấm lại nút nghe trên máy này."));
  };

  // Tiếng trên máy này khi phát ra loa: <audio> nghe cùng loa, hoặc khung video bật tiếng.
  const tiengTrenMay = ngheCungLoa || !!(video?.theoLoa && video.ngheTrenMay);
  const doiNgheTrenMay = () => {
    if (tiengTrenMay) {
      if (ngheCungLoa) tatNgheCungLoa();
      if (video?.theoLoa && video.ngheTrenMay) {
        nhung.lenh("mute");
        setVideo({ ...video, ngheTrenMay: false });
      }
      return;
    }
    if (video?.theoLoa && !ngheNen) {
      nhung.lenh("unMute");
      setVideo({ ...video, ngheTrenMay: true });
      return;
    }
    batNgheCungLoa();
  };

  // Nghe cùng loa: nạp bài của loa đang xem (đổi bài thì nạp lại), tạm dừng/phát theo
  // loa, tua khi lệch quá 2 giây. Hết phiên thì thôi.
  useEffect(() => {
    if (!ngheCungLoa) return;
    const hen = setInterval(() => {
      const m = moiNhat.current;
      const bai = m.baiPhienXem;
      if (!bai || bai.source === "http") {
        m.tatNgheCungLoa();
        return;
      }
      const muc = `${bai.source}:${bai.url || bai.id}`;
      if (mucCungLoa.current !== muc) {
        mucCungLoa.current = muc;
        void m.taiCungLoa(bai);
        return;
      }
      const a = am.current;
      if (!a || !a.getAttribute("src") || a.getAttribute("src")!.startsWith("data:")) return;
      if (document.visibilityState === "hidden" && !m.ngheNen) return;
      const loa = m.loaPhien.find((t) => dangHoatDong(t));
      if (!loa || !dangPhatBai(loa, bai)) return;
      if (loa.trang_thai === "paused" && !a.paused) a.pause();
      if (loa.trang_thai === "playing" && a.paused) void a.play().catch(() => undefined);
      if (loa.trang_thai !== "playing" || loa.vi_tri === null || Date.now() < dongBo.current.luiTuaAm) return;
      const viTri = loa.vi_tri + (Date.now() - lucTai.current) / 1000;
      if (Math.abs(viTri - a.currentTime) > 2) {
        a.currentTime = viTri;
        dongBo.current.luiTuaAm = Date.now() + 4000;
      }
    }, 1000);
    return () => clearInterval(hen);
  }, [ngheCungLoa]);

  const doiNgheNen = () => {
    const bat = !ngheNen;
    setNgheNen(bat);
    try {
      localStorage.setItem(KHOA_NGHE_NEN, bat ? "1" : "0");
    } catch {
      // Như trên.
    }
    if (bat && videoMotMinh && video) {
      // Đang xem có tiếng: tiếng chuyển sang thẻ âm thanh từ giây đang xem, video tắt tiếng chạy theo.
      void ngheBai(video.bai, hangVideo ?? { items: [video.bai], index: 0 }, nhung.thoiGian());
    } else if (bat && video?.theoLoa && video.ngheTrenMay) {
      // Video theo loa đang bật tiếng trên máy: tiếng chuyển sang thẻ âm thanh.
      nhung.lenh("mute");
      setVideo({ ...video, ngheTrenMay: false });
      batNgheCungLoa();
    }
    toast.message(bat
      ? "Bật nghe khi tắt màn hình: tắt màn hình vẫn nghe tiếp trên máy này."
      : "Đã tắt: tắt màn hình thì tiếng trên máy này dừng, mở lại thì phát tiếp.");
  };

  // Nút tắt: trang bị ẩn (tắt màn hình, đổi ứng dụng) thì dừng tiếng trên máy, mở lại
  // thì phát tiếp — chỉ phát tiếp những gì chính đoạn này đã dừng.
  const dungKhiAn = useRef(false);
  useEffect(() => {
    const doi = () => {
      const a = am.current;
      if (!a) return;
      if (document.visibilityState === "hidden") {
        const src = a.getAttribute("src");
        if (!moiNhat.current.ngheNen && !a.paused && src && !src.startsWith("data:")) {
          a.pause();
          dungKhiAn.current = true;
        }
      } else if (dungKhiAn.current) {
        dungKhiAn.current = false;
        void a.play().catch(() => undefined);
      }
    };
    document.addEventListener("visibilitychange", doi);
    return () => document.removeEventListener("visibilitychange", doi);
  }, []);

  // Video chạy theo thẻ âm thanh: tạm dừng/phát theo, tua khi lệch quá 2 giây. Mở lại
  // màn hình sau khi nghe nền thì hình tự về đúng chỗ tiếng.
  const theoMay = !!video?.theoMay;
  useEffect(() => {
    if (!theoMay) return;
    const hen = setInterval(() => {
      const n = moiNhat.current.nhung;
      const a = am.current;
      if (!n.sanSang || !a || !a.getAttribute("src") || a.getAttribute("src")!.startsWith("data:")) return;
      if (a.paused && DANG_CHAY.includes(n.trangThai)) n.lenh("pauseVideo");
      if (!a.paused && [-1, 2, 5].includes(n.trangThai)) n.lenh("playVideo");
      if (a.paused || Date.now() < dongBo.current.luiTuaDen) return;
      if (Math.abs(a.currentTime - n.thoiGian()) > 2) {
        n.lenh("seekTo", [a.currentTime, true]);
        dongBo.current.luiTuaDen = Date.now() + 4000;
      }
    }, 1000);
    return () => clearInterval(hen);
  }, [theoMay]);

  // Thẻ âm thanh trên màn hình khoá / thanh thông báo của điện thoại.
  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    if (!nghe) {
      ms.metadata = null;
      return;
    }
    ms.metadata = new MediaMetadata({
      title: nghe.title || nghe.id,
      artist: nghe.channel || nghe.artist || TEN_NGUON[nghe.source],
      artwork: /^https?:\/\//.test(nghe.thumbnail || "") ? [{ src: nghe.thumbnail }] : [],
    });
    const dat = (hanhDong: MediaSessionAction, lam: MediaSessionActionHandler | null) => {
      try {
        ms.setActionHandler(hanhDong, lam);
      } catch {
        // Trình duyệt không hỗ trợ hành động này.
      }
    };
    dat("play", () => void am.current?.play().catch(() => undefined));
    dat("pause", () => am.current?.pause());
    dat("previoustrack", () => void moiNhat.current.chuyenBai(-1));
    dat("nexttrack", () => void moiNhat.current.chuyenBai(1));
    dat("stop", () => moiNhat.current.dungNghe());
    return () => {
      for (const h of ["play", "pause", "previoustrack", "nexttrack", "stop"] as MediaSessionAction[]) dat(h, null);
    };
  }, [nghe]);

  // Video xem trên máy (có tiếng) mà trình duyệt chặn tiếng tự phát: thử bật tiếng
  // một lần, vẫn chặn thì hiện "Chạm vào video" — chỉ cú chạm vào chính khung mới mở.
  const muonTieng = !!video?.ngheTrenMay;
  useEffect(() => {
    setCanCham(false);
    if (!muonTieng) return;
    const chan = () => {
      const n = moiNhat.current.nhung;
      return n.tatTieng === true || [-1, 5].includes(n.trangThai);
    };
    let henLai: ReturnType<typeof setTimeout> | undefined;
    const hen = setTimeout(() => {
      if (!chan()) return;
      moiNhat.current.nhung.lenh("unMute");
      moiNhat.current.nhung.lenh("playVideo");
      henLai = setTimeout(() => setCanCham(chan()), 1500);
    }, 3500);
    return () => {
      clearTimeout(hen);
      clearTimeout(henLai);
    };
  }, [muonTieng, video?.src, video?.bai.id]);
  useEffect(() => {
    if (canCham && nhung.trangThai === 1 && nhung.tatTieng !== true) setCanCham(false);
  }, [canCham, nhung.trangThai, nhung.tatTieng]);

  const coDieuKhien = loaPhien.some((t) => t.trang_thai !== "unavailable" && (t.tam_dung || t.dung));
  const rap = !!video && cheDo === "rap";

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <DangPhat
        className={cn("min-w-0", rap ? "lg:col-span-2" : "lg:col-start-2 lg:row-start-1")}
        phien={phienXem}
        cacPhienKhac={cacPhienKhac}
        ngheCungTen={ngheCungIds.map((id) => theoMa.get(id)?.ten ?? id)}
        thietBi={thietBi ?? []}
        video={video}
        nghe={nghe}
        hang={hang}
        ngheNen={ngheNen}
        doiNgheNen={doiNgheNen}
        canCham={canCham}
        nhung={nhung}
        cheDo={cheDo}
        doiCheDo={doiCheDo}
        dongVideo={dongVideo}
        dangChay={dangChay}
        dangGui={!!dangGuiMa}
        layViTri={layViTri}
        truoc={coBai(-1) ? () => void chuyenBai(-1) : null}
        tiep={coBai(1) ? () => void chuyenBai(1) : null}
        phatTamDung={nghe || video || coDieuKhien ? phatTamDung : null}
        dung={nghe || video || phienXem || coDieuKhien ? () => void dung() : null}
        xemTaiDay={
          video
            ? null
            : nghe
              ? laVideo(nghe) ? () => moVideo(nghe, false, am.current?.currentTime ?? 0, true) : null
              : laVideo(phienXem?.item) ? () => moVideo(phienXem!.item!, loaPhien.some(dangHoatDong)) : null
        }
        chonNhom={chonNhom}
        ngheCung={ngheCungIds.length ? () => void ngheCung() : null}
        tiengTrenMay={phienXem?.item && !nghe && !videoMotMinh ? tiengTrenMay : null}
        doiNgheTrenMay={doiNgheTrenMay}
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
        dangPhatMa={video ? video.bai.url || video.bai.id : nghe ? nghe.url || nghe.id : phienXem?.item ? phienXem.item.url || phienXem.item.id : ""}
        dangGuiMa={dangGuiMa}
        coLoa={chon.size > 0}
        phat={(bai, xem) => void phat(bai, xem)}
      />
    </div>
  );
}
