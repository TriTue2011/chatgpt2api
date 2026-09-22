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
 * - YouTube từ chối video trong khung nhúng: đóng khung, xem một mình thì nghe tiếng
 *   bài đó trên máy, có loa hay đang nghe bằng thẻ âm thanh thì tiếng vẫn chạy.
 */

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

import { httpRequest } from "@/lib/request";
import { cn } from "@/lib/utils";

import { DangPhat, type HinhRieng, type VideoMo, type ViTri } from "./dang-phat";
import { DanhSachThietBi } from "./danh-sach-thiet-bi";
import { type BaiHat, dangHoatDong, dangPhatBai, goi, laFacebook, type Nguon, type Phien, type ThietBi } from "./lib";
import * as mayNghe from "./nghe-tren-may";
import { DanhSachPlaylist, type NguonHang, useKhoPlaylist } from "./playlist";
import { TimNhac } from "./tim-nhac";
import { type CheDoXem, laTao, laVideo, srcNhung, useVideoNhung } from "./video-nhung";

const KHOA_CHON = "c2a-youtube:chon";
const KHOA_CHE_DO_XEM = "c2a-youtube:che-do-xem";
const DUOI_AUDIO = /\.(aac|flac|m3u8|m4a|mp3|ogg|opus|wav)$/i;
const DANG_CHAY = [1, 3];

type KetQuaPhat = { da_gui: string[]; bo_qua: { entity_id: string; ly_do: string }[]; phien: Phien };
type Hang = mayNghe.Hang;

// Ô tìm và kết quả giữ theo trang web: chuyển sang tab khác rồi quay lại vẫn còn.
const ghiNhoTim = { nguon: "youtube" as Nguon, tuKhoa: "", ketQua: [] as BaiHat[], xemPlaylist: false };

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
  const [nguon, setNguon] = useState<Nguon>(ghiNhoTim.nguon);
  const [tuKhoa, setTuKhoa] = useState(ghiNhoTim.tuKhoa);
  const [ketQua, setKetQua] = useState<BaiHat[]>(ghiNhoTim.ketQua);
  useEffect(() => {
    Object.assign(ghiNhoTim, { nguon, tuKhoa, ketQua });
  }, [nguon, tuKhoa, ketQua]);
  const [dangTim, setDangTim] = useState(false);
  const khoPlaylist = useKhoPlaylist();
  const [xemPlaylist, setXemPlaylist] = useState(ghiNhoTim.xemPlaylist);
  const [playlistMoSan, setPlaylistMoSan] = useState("");
  const [dangLuuPlaylist, setDangLuuPlaylist] = useState(false);
  useEffect(() => {
    ghiNhoTim.xemPlaylist = xemPlaylist;
  }, [xemPlaylist]);
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
      return localStorage.getItem(mayNghe.KHOA_NGHE_NEN) === "1";
    } catch {
      return false;
    }
  });
  // Tiếng trên máy này (thẻ <audio>) sống ngoài component: chuyển tab rồi quay lại vẫn
  // thấy đúng bài đang nghe (xem nghe-tren-may.ts).
  const mayTrangThai = useSyncExternalStore(mayNghe.dangKy, mayNghe.layTrangThai, mayNghe.layTrangThaiMayChu);
  const nghe = mayTrangThai.bai;
  const ngheChay = mayTrangThai.chay;
  // Máy này nghe cùng loa (không mở video, hoặc bật nghe khi tắt màn hình): <audio> bám vị trí loa.
  const ngheCungLoa = mayTrangThai.cungLoa;
  // Trình duyệt chặn tiếng tự phát của khung video: bảo người xem chạm vào video.
  const [canCham, setCanCham] = useState(false);
  // Hàng đợi của video/bài nghe một mình trên trang. Loa dùng hàng đợi của phiên máy chủ.
  const [hangVideo, setHangVideo] = useState<Hang | null>(null);
  const daNapChon = useRef(false);
  const lucTai = useRef(0);
  const dongBo = useRef({ luiTuaDen: 0, luiTuaAm: 0, giuDen: 0, choTua: null as null | { id: string; tu: number; luc: number } });

  const hetVideo = useRef<() => void>(() => undefined);
  // Ở ngoài nhà người xem đã đồng ý xem hình (qua máy chủ) trong lần xem này.
  const dongYNgoaiNha = useRef(false);
  // Thẻ âm thanh không lấy được tiếng cho video đang xem: đừng thử chuyển tiếng sang nó nữa.
  const tiengMayHong = useRef(false);
  const loiVideo = useRef<() => void>(() => undefined);
  const nhung = useVideoNhung(() => hetVideo.current(), () => loiVideo.current());

  const taiThietBi = useCallback(async (imLang: boolean) => {
    try {
      const r = await httpRequest<{ ok: boolean; error?: string; canh_bao?: string; items: ThietBi[]; phien: Phien; cac_phien: Phien[] }>(
        "/api/youtube-phat/thiet-bi", { method: "GET" });
      if (!r?.ok) {
        setLoiHa(r?.error || "Không đọc được danh sách thiết bị.");
        return;
      }
      lucTai.current = Date.now();
      setLoiHa(r.canh_bao || "");
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
  /** Thúc tiếng sau khi khung vừa nạp — bậc thang 0 / 300 / 800 / 2000 mili giây.
   *
   * Chép của thẻ `phicomm-r1-card` chủ máy đưa 20/09/2026 (dòng 1904-1908), kèm
   * xác nhận thẻ ấy nghe nhạc và xem video trên iPhone đều bình thường. Giao diện
   * lập trình của trình phát YouTube chưa nhận lệnh ngay lúc khung vừa nạp, nên
   * gửi đúng một lần là rơi vào khoảng chưa ai nghe.
   */
  const thucTiengKhung = () => {
    const thuc = () => {
      nhung.lenh("unMute");
      nhung.lenh("setVolume", [100]);
    };
    thuc();
    [300, 800, 2000].forEach((cho) => setTimeout(thuc, cho));
  };

  /** BẬT TIẾNG CHO KHUNG — dựng lại khung, KHÔNG gửi lệnh `unMute`.
   *
   * Cú bấm của người dùng nằm ở TRANG, còn trình phát nằm trong khung
   * youtube-nocookie.com khác miền. Lệnh `unMute` đi qua postMessage nên cử chỉ
   * ấy không đi theo: với trình duyệt, đó là cảnh một video đang tự phát ở chế độ
   * câm bỗng bật tiếng mà không ai chạm vào nó — và cách nó xử là TẠM DỪNG video.
   * Luật này có ở cả Chrome trên Android lẫn WebKit trên iPhone và macOS.
   *
   * Chủ máy đo được đúng chuyện này trên Android 20/09/2026, với thẻ Home
   * Assistant dùng cùng một mô hình: "nghe trên máy này mà đang phát ra loa bị
   * dừng video, nhưng chọn cả nghe khi tắt màn hình thì không sao" — nhánh
   * tắt-màn-hình để khung câm nguyên và cho thẻ âm thanh mang tiếng.
   *
   * Thẻ `phicomm-r1-card` chạy được trên mọi máy vì địa chỉ nhúng của nó không hề
   * có tham số `mute`: khung sinh ra đã có tiếng sẵn, ngay trong cú bấm.
   */
  const batTiengKhung = (v: VideoMo, giayBatDau?: number) => {
    // Hình riêng (thẻ <video> của chính trang) không dính luật của khung nhúng.
    if (v.hinh) {
      setVideo({ ...v, ngheTrenMay: true });
      return;
    }
    if (nhung.tatTieng === false) {
      // Khung đang có tiếng sẵn: nạp lại chỉ tổ mất toàn màn hình và mất mấy giây.
      nhung.lenh("playVideo");
      setVideo({ ...v, ngheTrenMay: true });
      return;
    }
    const giay = giayBatDau ?? nhung.thoiGian();
    nhung.datLai();
    setVideo({ ...v, src: srcNhung(v.bai.id, false, giay), ngheTrenMay: true });
    thucTiengKhung();
  };

  const moVideo = (bai: BaiHat, voiLoa: boolean, batDau = 0, theoMay = false) => {
    if (!laVideo(bai)) return;
    if (!video || video.bai.id !== bai.id) tiengMayHong.current = false;
    const ngheTrenMay = theoMay ? false : voiLoa ? (video?.theoLoa ? video.ngheTrenMay : false) : true;
    // Xem một mình: link tiếng sẵn sàng phòng khi khung bị chặn tiếng tự phát.
    if (ngheTrenMay && !voiLoa) mayNghe.taiTruoc(bai);
    // Đang hiện hình riêng (bài trước bị chặn nhúng): nạp lại khung để thử nhúng bài này.
    if (video && nhung.sanSang && !video.hinh) {
      // Cùng khung: đổi bài không nạp lại, giữ nguyên cỡ xem và toàn màn hình.
      if (video.bai.id !== bai.id) nhung.lenh("loadVideoById", [{ videoId: bai.id, startSeconds: batDau }]);
      if (ngheTrenMay) {
        // Cùng lớp lỗi: khung đang câm thì phải dựng lại, đừng gửi `unMute`.
        batTiengKhung({ ...video, bai, theoLoa: voiLoa, theoMay }, batDau);
      } else {
        nhung.lenh("mute");
        setVideo({ ...video, bai, theoLoa: voiLoa, ngheTrenMay, theoMay });
      }
    } else {
      nhung.datLai();
      setVideo({ bai, src: srcNhung(bai.id, !ngheTrenMay, batDau), theoLoa: voiLoa, ngheTrenMay, theoMay });
    }
    dongBo.current.luiTuaDen = 0;
    if (cheDo !== "nho") {
      requestAnimationFrame(() => document.getElementById("khoi-dang-phat")?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    }
  };

  /** Facebook không nhúng được như YouTube. Hình đi qua máy chủ, cùng đường thẻ
   *  Home Assistant dùng khi khung YouTube bị từ chối. */
  const moHinh = (bai: BaiHat, voiLoa: boolean) => {
    const nguonHinh = bai.source === "facebook" ? "facebook_video" : "youtube_video";
    setVideo({
      bai, src: "about:blank", theoLoa: voiLoa, ngheTrenMay: false, theoMay: !voiLoa,
      hinh: { trangThai: "lay" },
    });
    void goi<{ url: string; direct_url?: string; height?: number; bitrate_kbps?: number }>("nghe", {
      source: nguonHinh, target: bai.url || bai.id, max_height: caoHinh(),
    }).then((r) => setVideo((v) => {
      if (!v || v.bai.id !== bai.id || !v.hinh) return v;
      if (!r) return { ...v, hinh: { trangThai: "loi" } };
      return {
        ...v,
        hinh: {
          trangThai: r.direct_url ? "thang" : dongYNgoaiNha.current ? "ky" : "ngoai",
          thang: r.direct_url, ky: r.url, cao: r.height,
          mbPhut: Math.max(1, Math.round(((r.bitrate_kbps || 1000) * 60) / 8 / 1000)),
        },
      };
    }));
  };

  const dongVideo = () => {
    dongYNgoaiNha.current = false;
    nhung.datLai();
    dongBo.current.choTua = null;
    setVideo(null);
  };

  /** Nghe một bài trên máy này; `batDau` = giây bắt đầu (chuyển từ video sang). Gọi ngay
   *  trong cú bấm — kho mở khoá thẻ âm thanh trước mọi `await`. */
  const ngheBai = (bai: BaiHat, hangMoi: Hang, batDau = 0, dongHinh = false) => {
    void mayNghe.ngheBai(bai, hangMoi, batDau);
    // Video đang mở thì theo bài mới, tắt tiếng, chạy theo tiếng; chỉ nghe hoặc bài không có video thì đóng.
    if (video && laVideo(bai) && !dongHinh) moVideo(bai, false, batDau, true);
    else if (video && laFacebook(bai) && !dongHinh) moHinh(bai, false);
    else if (video) dongVideo();
  };

  const dungNghe = () => mayNghe.dung();

  /** Chủ máy 15/09/2026: "khi nhấn xem bằng video không phát luôn mà tôi phải kích vào màn hình
   *  youtube, kích vào nút play của mình không hoạt động". Khung YouTube chỉ chịu phát có tiếng
   *  khi chạm thẳng vào nó (lệnh gửi từ trang bị chặn): tiếng chuyển sang thẻ âm thanh của trang
   *  (mở khoá trong cú bấm mở video) từ giây đang xem, video tắt tiếng chạy theo. */
  const chuyenTiengSangMay = () => {
    if (!video || video.theoLoa || video.theoMay || video.hinh || tiengMayHong.current) return;
    ngheBai(video.bai, hangVideo ?? { items: [video.bai], index: 0 }, nhung.thoiGian());
  };

  const caoHinh = () =>
    window.matchMedia?.("(pointer: coarse)").matches && Math.min(screen.width, screen.height) < 600 ? 720 : 1080;

  const hinhSan = () => setVideo((v) => (v?.hinh ? { ...v, hinh: { ...v.hinh, coHinh: true } } : v));

  const hinhLoi = () => setVideo((v) => {
    if (!v?.hinh || v.hinh.coHinh) return v;
    if (v.hinh.trangThai === "thang") {
      // Không tải thẳng được: máy này không cùng mạng nhà với máy chủ (đang ở ngoài nhà).
      return { ...v, hinh: { ...v.hinh, trangThai: dongYNgoaiNha.current && v.hinh.ky ? "ky" : "ngoai" } };
    }
    if (v.hinh.trangThai === "ky") return { ...v, hinh: { ...v.hinh, trangThai: "loi" } };
    return v;
  });

  const xemHinhNgoaiNha = () => {
    const h = video?.hinh;
    if (!video || !h || h.trangThai !== "ngoai" || !h.ky) return;
    const dongY = window.confirm(
      `Xem hình khi ở ngoài mạng nhà: hình ${h.cao ?? ""}p đi từ mạng nhà qua Internet tới máy này, `
      + `khoảng ${h.mbPhut ?? 1} MB mỗi phút — tốn dữ liệu di động của máy và băng thông tải lên của nhà. Xem hình?`,
    );
    if (!dongY) return;
    // Đồng ý một lần: các video bị chặn tiếp theo trong lần xem này tự mở hình.
    dongYNgoaiNha.current = true;
    setVideo({ ...video, hinh: { ...h, trangThai: "ky" } });
  };

  /** Chủ máy 15/09/2026: "Có cách nào xem video quay lại về chỉ nghe không" — tắt hình,
   *  tiếng chạy tiếp từ giây đang xem (loa hay thẻ âm thanh đang giữ tiếng thì chỉ tắt hình). */
  const chiNghe = () => {
    if (!video) return;
    if (video.theoLoa || video.theoMay) {
      dongVideo();
      return;
    }
    ngheBai(video.bai, hangVideo ?? { items: [video.bai], index: 0 }, nhung.thoiGian(), true);
  };

  const capNhatPhien = (r: { cac_phien?: Phien[] } | null) => {
    if (r?.cac_phien) setCacPhien(r.cac_phien);
    void taiThietBi(true);
  };

  /** `xem` = nút xem video; không thì chỉ nghe. `nguonHang` = hàng đợi khác kết quả tìm (playlist). */
  const phat = async (bai: BaiHat, xem = false, nguonHang?: NguonHang) => {
    const ids = [...chon].filter((id) => theoMa.get(id)?.phat_duoc);
    if (!chon.size) {
      // Chưa tích loa: nghe hoặc xem ngay trên máy này, với hàng đợi riêng.
      const ds = nguonHang?.items ?? ketQua;
      const i = ds.findIndex((k) => cungBai(k, bai));
      const hangMoi = i >= 0 ? { items: ds, index: i } : { items: [bai], index: 0 };
      if (xem && laVideo(bai) && nghe && cungBai(nghe, bai)) {
        // Đúng bài đang nghe: mở video tại giây đang nghe, tiếng chạy tiếp — không phát lại từ đầu.
        if (!video) moVideo(nghe, false, mayNghe.thoiGian(), true);
        return;
      }
      if (xem && laVideo(bai)) {
        if (ngheNen) {
          // Nghe khi tắt màn hình: tiếng từ thẻ âm thanh, video tắt tiếng chạy theo.
          const coHinh = !!video;
          void ngheBai(bai, hangMoi);
          if (!coHinh) moVideo(bai, false, 0, true);
          return;
        }
        if (nghe) dungNghe();
        // Mở khoá thẻ âm thanh ngay trong cú bấm: khung YouTube bị chặn tiếng tự phát thì
        // tiếng chuyển sang thẻ này mà không cần chạm vào video.
        mayNghe.moKhoaTruoc();
        setHangVideo(hangMoi);
        moVideo(bai, false);
        return;
      }
      if (xem && laFacebook(bai)) {
        mayNghe.moKhoaTruoc();
        setHangVideo(hangMoi);
        void mayNghe.ngheBai(bai, hangMoi, 0);
        moHinh(bai, false);
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
    if (xem && laVideo(bai) && !video && phienXem?.item && cungBai(phienXem.item, bai)
        && ids.every((id) => phienXem.output_entity_ids.includes(id))) {
      // Loa đang tích đã phát đúng bài này: mở hình theo vị trí loa, không gửi lại bài từ đầu.
      moVideo(bai, true);
      return;
    }
    const ma = bai.url || bai.id;
    setDangGuiMa(ma);
    const r = await goi<KetQuaPhat>("phat", {
      source: bai.source,
      target: ma,
      entity_ids: ids,
      ...(bai.media_content_type ? { media_content_type: bai.media_content_type } : {}),
      // Hàng đợi của loa là cả playlist; máy chủ tự chuyển bài.
      ...(nguonHang?.playlist_id ? { playlist_id: nguonHang.playlist_id } : {}),
    });
    setDangGuiMa("");
    if (!r) return;
    if (nghe) {
      /* CÙNG BÀI thì giữ tiếng trên máy tới lúc loa kêu (xem «nhuongTiengChoLoa»);
         BÀI KHÁC thì dừng ngay — vừa chọn bài mới mà còn nghe bài cũ mới là lạ. */
      if (ids[0] && cungBai(nghe, bai)) nhuongTiengChoLoa(ids[0], () => dungNghe());
      else dungNghe();
    }
    const ten = (id: string) => theoMa.get(id)?.ten ?? id;
    if (r.bo_qua.length) {
      toast.warning(`Đã gửi tới ${r.da_gui.map(ten).join(", ")}. Bỏ qua: ${r.bo_qua.map((b) => ten(b.entity_id)).join(", ")}.`);
    } else {
      toast.success(`Đang phát trên ${r.da_gui.map(ten).join(", ")}.`);
    }
    if (xem && laVideo(bai)) {
      moVideo(bai, true);
    } else if (xem && laFacebook(bai)) {
      moHinh(bai, true);
    } else if (video) {
      // Hình theo loa: bài có hình thì bám loa; nguồn chỉ có tiếng thì đóng hình.
      if (laVideo(bai)) moVideo(bai, true);
      else if (laFacebook(bai)) moHinh(bai, true);
      else dongVideo();
    }
    void taiThietBi(true);
  };

  const hang = nghe ? mayTrangThai.hang : videoMotMinh ? hangVideo : phienXem?.queue ?? null;
  const coBai = (buoc: number) => !!hang && hang.index >= 0 && !!hang.items[hang.index + buoc];

  const chuyenBai = async (buoc: number) => {
    if (nghe) {
      mayNghe.chuyen(buoc);
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
  const moiNhat = useRef({ chuyenBai, video, thietBi, loaPhien, nhung, baiPhienXem, ngheNen, chuyenTiengSangMay, hinhLoi });
  useEffect(() => {
    moiNhat.current = { chuyenBai, video, thietBi, loaPhien, nhung, baiPhienXem, ngheNen, chuyenTiengSangMay, hinhLoi };
    hetVideo.current = () => {
      // Hết video xem một mình: tự sang bài kế trên trang. Có loa thì máy chủ lo.
      const v = moiNhat.current.video;
      if (v && !v.theoLoa && !v.theoMay) void moiNhat.current.chuyenBai(1);
    };
    loiVideo.current = () => {
      // Không để khung chết: tiếng vẫn phát (loa hoặc thẻ âm thanh), hình lấy riêng qua máy chủ.
      if (!video || video.hinh) return;
      const bai = video.bai;
      const host = window.location.hostname;
      const lyDo = /^[\d.]+$/.test(host) || host.includes(":")
        ? `YouTube không cho nhúng “${bai.title || bai.id}” khi mở trang bằng địa chỉ IP.`
        : `YouTube không cho nhúng “${bai.title || bai.id}” vào trang.`;
      if (!video.theoLoa && !video.theoMay) void mayNghe.ngheBai(bai, hangVideo ?? { items: [bai], index: 0 });
      setVideo({ ...video, theoMay: !video.theoLoa, ngheTrenMay: false, hinh: { trangThai: "lay" } });
      toast.message(`${lyDo} Đang nghe tiếng, đang lấy hình.`);
      void goi<{ url: string; direct_url?: string; height?: number; bitrate_kbps?: number }>("nghe", {
        source: "youtube_video", target: bai.url || bai.id, max_height: caoHinh(),
      }).then((r) => setVideo((v) => {
        if (!v || v.bai.id !== bai.id || !v.hinh) return v;
        if (!r) return { ...v, hinh: { trangThai: "loi" } };
        const hinh: HinhRieng = {
          trangThai: r.direct_url ? "thang" : dongYNgoaiNha.current ? "ky" : "ngoai",
          thang: r.direct_url, ky: r.url, cao: r.height,
          mbPhut: Math.max(1, Math.round(((r.bitrate_kbps || 1000) * 60) / 8 / 1000)),
        };
        return { ...v, hinh };
      }));
    };
  });

  // Tích sang loa khác: video đổi sang bài của loa đó và tua theo loa.
  useEffect(() => {
    if (!video?.theoLoa || !baiPhienXem) return;
    if (baiPhienXem.id === video.bai.id) return;
    if (laVideo(baiPhienXem)) {
      moVideo(baiPhienXem, true);
    } else if (laFacebook(baiPhienXem)) {
      moHinh(baiPhienXem, true);
    } else {
      dongVideo();
      toast.message("Loa này đang phát Zing hoặc link audio — không có video.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baiPhienXem?.id, video?.theoLoa]);

  // Hình trên trang bám theo loa: tạm dừng/phát theo loa, tua khi lệch quá nửa giây.
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
      // Loa phát luồng tiếng riêng nên hình (tắt tiếng) bám vị trí loa báo về. Lệch quá 0,8 giây
      // là thấy lệch khẩu hình, nhịp (chủ máy 15/09/2026: "khi xem hình ko đc khớp với audio").
      // Home Assistant báo vị trí loa trễ vài trăm mili giây nên nửa giây là mức siết giữ được
      // mà hình không tua liên tục; nghỉ 5 giây sau mỗi lần tua để khỏi đuổi qua đuổi lại.
      /* KHUNG ĐANG MANG TIẾNG thì mỗi cú tua là một lần tiếng nhảy trong tai người
         nghe. Khung câm lệch nửa giây thì tua cho khớp khẩu hình; khung có tiếng chỉ
         chữa khi lệch tới mức nghe ra là hai nơi đang ở hai chỗ khác nhau. */
      const nguongLech = v?.ngheTrenMay ? 5 : 0.5;
      if (n.trangThai === 1 && Math.abs(viTriLoa - n.thoiGian()) > nguongLech) {
        n.tuaTheoTieng(viTriLoa);
        db.luiTuaDen = Date.now() + 5000;
      }
    }, 2000);
    return () => clearInterval(hen);
  }, [theoLoa]);

  const layViTri = (): ViTri => {
    if (nghe) return mayNghe.viTri();
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

  const luuCaPlaylist = async () => {
    setDangLuuPlaylist(true);
    const r = await khoPlaylist.lenh({ action: "import", text: tuKhoa.trim() });
    setDangLuuPlaylist(false);
    if (!r?.playlist) return;
    toast.success(`Đã lưu “${r.playlist.name}” (${r.playlist.items.length} bài) vào Playlist.`);
    setPlaylistMoSan(r.playlist.id);
    setXemPlaylist(true);
  };

  /** NHƯỜNG TIẾNG CHO LOA ĐÚNG LÚC LOA LÊN TIẾNG, ĐỪNG CẮT TRƯỚC.
   *
   *  Gửi bài cho loa xong mà tắt tiếng trên máy ngay thì sinh một quãng IM LẶNG: máy
   *  chủ còn giải bài (đo 20/09/2026: YouTube 1,59 giây), loa còn nạp đệm. Với người
   *  nghe thì quãng ấy đúng là "mất tiếng". Nên giữ tiếng trên máy tới nhịp đầu tiên
   *  loa thật sự báo "playing"; quá 15 giây loa vẫn im thì thôi, không nhường — loa
   *  hỏng thì ít nhất còn nghe được trên máy. Trong lúc chờ thì hỏi trạng thái nhanh
   *  hơn nhịp thường, vì nhịp thường 2,5–5 giây là nhường trễ hơn cả quãng cần chữa. */
  const nhuongTiengChoLoa = (id: string, nhuong: () => void) => {
    const batDau = Date.now();
    const hen = setInterval(() => {
      const loa = (moiNhat.current.thietBi ?? []).find((t) => t.entity_id === id);
      if (loa?.trang_thai !== "playing" && Date.now() - batDau < 15000) {
        void taiThietBi(true);
        return;
      }
      clearInterval(hen);
      if (loa?.trang_thai === "playing") nhuong();
    }, 800);
  };

  const loaNhapVideo = async (tb: ThietBi, v: VideoMo) => {
    const tu = nhung.thoiGian();
    const r = await goi<KetQuaPhat>("phat", { source: "youtube", target: v.bai.url || v.bai.id, entity_ids: [tb.entity_id] });
    if (!r) return;
    // Khung giữ tiếng tới lúc loa kêu rồi mới câm — xem «nhuongTiengChoLoa».
    setVideo({ ...v, theoLoa: true, ngheTrenMay: true });
    nhuongTiengChoLoa(tb.entity_id, () => {
      nhung.lenh("mute");
      setVideo((cu) => (cu ? { ...cu, ngheTrenMay: false } : cu));
    });
    dongBo.current.choTua = { id: tb.entity_id, tu, luc: Date.now() };
    toast.success(`${tb.ten} sắp phát; tiếng giữ trên trang tới khi loa kêu rồi tự tắt.`);
    void taiThietBi(true);
  };

  const batTat = (tb: ThietBi) => {
    const moi = new Set(chon);
    if (moi.has(tb.entity_id)) {
      moi.delete(tb.entity_id);
      if (video?.theoLoa && !moi.size) {
        // Không còn loa nào tích: video trên trang phát tiếp một mình, có tiếng.
        dongBo.current.choTua = null;
        batTiengKhung({ ...video, theoLoa: false });
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
      mayNghe.phatTamDung();
      return;
    }
    if (videoMotMinh) {
      if ((canCham || [-1, 5].includes(nhung.trangThai)) && video && !video.hinh) {
        // Khung chưa chạy hoặc đang chờ chạm (bị chặn tự phát): cú bấm này phát tiếng bằng thẻ
        // âm thanh của trang — kể cả khi lần tự chuyển trước bị từ chối, vì giờ đang trong cú bấm.
        tiengMayHong.current = false;
        chuyenTiengSangMay();
        return;
      }
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

  const tatNgheCungLoa = () => mayNghe.tatCungLoa();

  /** Bắt đầu nghe cùng loa trên máy này; phải gọi trong cú bấm để mở khoá thẻ âm thanh. */
  const batNgheCungLoa = () => {
    const bai = phienXem?.item;
    if (!bai || bai.source === "http") {
      toast.error("Link audio chỉ nghe được trên loa.");
      return;
    }
    /* Truyền cả bài và giây loa để «batCungLoa» phát NGAY trong cú bấm này khi địa chỉ
       luồng đã xin sẵn — đi qua một await là lệnh phát nằm ngoài cử chỉ người dùng, và
       trình duyệt đòi chạm thêm một lần nữa. */
    const loa = loaPhien.find((t) => dangHoatDong(t) && t.vi_tri !== null);
    const giay = loa?.vi_tri != null ? loa.vi_tri + (Date.now() - lucTai.current) / 1000 : 0;
    mayNghe.batCungLoa(bai, Math.max(0, Math.floor(giay)));
  };

  // Tiếng trên máy này khi phát ra loa: <audio> nghe cùng loa, hoặc khung video bật tiếng.
  const tiengTrenMay = ngheCungLoa || !!(video?.theoLoa && video.ngheTrenMay);
  /** NGHE BÀI CỦA LOA BẰNG CHÍNH KHUNG YOUTUBE — đường nhanh, chép cách thẻ
   *  `phicomm-r1-card` làm.
   *
   *  Đo trên máy chủ 20/09/2026, cùng một bài, tính từ lúc có địa chỉ luồng:
   *  lấy byte đầu **từ đầu bài** mất 0,10 giây, nhưng **nhảy vào giữa bài** mất
   *  **1,64 giây** — googlevideo phải mở lại luồng ở đúng chỗ ấy. Mà "nghe cùng loa"
   *  thì lần nào cũng là nhảy vào giữa bài. Khung YouTube không có chặng đó: địa chỉ
   *  nhúng mang sẵn `start`, trình phát của Google tự lo.
   *
   *  Trả về true nếu đã nhận việc; false thì người gọi đi đường thẻ âm thanh. */
  const ngheBangKhung = () => {
    const bai = phienXem?.item;
    if (!bai || !laVideo(bai)) return false;
    const loa = loaPhien.find((t) => dangHoatDong(t) && t.vi_tri !== null);
    const giay = loa?.vi_tri != null ? loa.vi_tri + (Date.now() - lucTai.current) / 1000 : 0;
    nhung.datLai();
    setVideo({ bai, src: srcNhung(bai.id, false, Math.max(0, Math.floor(giay))), theoLoa: true, ngheTrenMay: true, chiTieng: true });
    return true;
  };

  const doiNgheTrenMay = () => {
    if (tiengTrenMay) {
      if (ngheCungLoa) tatNgheCungLoa();
      if (video?.theoLoa && video.ngheTrenMay) {
        // Khung mở ra chỉ để mang tiếng: tắt tiếng là đóng hẳn, đừng để nó chạy câm.
        if (video.chiTieng) dongVideo();
        else {
          nhung.lenh("mute");
          setVideo({ ...video, ngheTrenMay: false });
        }
      }
      return;
    }
    /* CHỈ MÁY NHÀ TÁO ĐI ĐƯỜNG KHUNG — luật ĐO ĐƯỢC, không phải đoán.
       Ảnh chụp Android của chủ máy 21/09/2026: khung dựng lại kèm tiếng vẫn hiện nút
       play đỏ của YouTube và dòng "Chạm vào video để phát có tiếng" — Chrome chặn tự
       phát kèm tiếng, dù khung đã lấy từ www.youtube.com. Máy nhà Táo thì ngược lại:
       thẻ âm thanh của WebKit đo được là không tải nổi, còn khung thì chạy.
       Thẻ âm thanh phải mở khoá NGAY TRONG CÚ BẤM này («batCungLoa» gọi «moKhoa»
       đồng bộ) — thử khung trước rồi mới lùi là mở khoá ngoài cử chỉ, Chrome từ chối. */
    if (laTao()) {
      if (video?.theoLoa) {
        batTiengKhung(video);
        return;
      }
      if (ngheBangKhung()) return;
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
        mayNghe.tatCungLoa();
        return;
      }
      /* Vào đúng chỗ NGAY TỪ ĐẦU. Trước đây thẻ âm thanh phát từ giây 0 rồi vòng canh
         bên dưới mới kéo về chỗ loa: người nghe được một quãng sai chỗ, và cú kéo ấy
         tốn thêm một lượt xin dữ liệu (đo 20/09: 1,64 giây với YouTube). */
      const loaDan = m.loaPhien.find((t) => dangHoatDong(t) && t.vi_tri !== null);
      const giayLoa = loaDan?.vi_tri != null ? loaDan.vi_tri + (Date.now() - lucTai.current) / 1000 : 0;
      void mayNghe.taiCungLoa(bai, Math.max(0, giayLoa));
      const a = mayNghe.amThat();
      if (!a) return;
      if (document.visibilityState === "hidden" && !document.fullscreenElement && !m.ngheNen) return;
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

  /* Loa đổi bài mà khung đang mang tiếng: khung theo bài mới. Thiếu chỗ này thì máy
     vẫn hát bài cũ trong khi loa đã sang bài khác. */
  const baiLoaId = phienXem?.item?.id ?? "";
  useEffect(() => {
    const v = moiNhat.current.video;
    if (!v?.chiTieng || !baiLoaId || v.bai.id === baiLoaId) return;
    const bai = moiNhat.current.baiPhienXem;
    if (bai && laVideo(bai)) {
      nhung.datLai();
      setVideo({ bai, src: srcNhung(bai.id, false, 0), theoLoa: true, ngheTrenMay: true, chiTieng: true });
    } else {
      // Bài mới không phải YouTube (Zing, link): khung không phát được, trả về thẻ âm thanh.
      dongVideo();
      batNgheCungLoa();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baiLoaId]);

  /* XIN SẴN ĐỊA CHỈ LUỒNG CỦA BÀI LOA ĐANG PHÁT. Bài Zing hay link thì khung YouTube
     không phát được, vẫn phải đi thẻ âm thanh — mà chặng chậm nhất của đường ấy là lượt
     hỏi máy chủ giải bài (đo 20/09: YouTube 1,59 giây, Zing 1,08 giây). Xin trước thì
     lúc bấm không còn lượt hỏi nào; hỏng thì im lặng, không ảnh hưởng gì. */
  useEffect(() => {
    const bai = moiNhat.current.baiPhienXem;
    if (bai && bai.source !== "http") mayNghe.taiTruoc(bai);
  }, [baiLoaId]);

  const doiNgheNen = () => {
    const bat = !ngheNen;
    setNgheNen(bat);
    try {
      localStorage.setItem(mayNghe.KHOA_NGHE_NEN, bat ? "1" : "0");
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

  // Video chạy theo thẻ âm thanh: tạm dừng/phát theo, tua khi lệch quá 0,35 giây (đồng hồ của
  // thẻ âm thanh chính xác). Mở lại màn hình sau khi nghe nền thì hình tự về đúng chỗ tiếng.
  const theoMay = !!video?.theoMay;
  useEffect(() => {
    if (!theoMay) return;
    const hen = setInterval(() => {
      const n = moiNhat.current.nhung;
      const a = mayNghe.amThat();
      if (!n.sanSang || !a) return;
      if (a.paused && DANG_CHAY.includes(n.trangThai)) n.lenh("pauseVideo");
      if (!a.paused && [-1, 2, 5].includes(n.trangThai)) n.lenh("playVideo");
      // Tiếng còn đang tải (chưa có dữ liệu, vị trí 0) hoặc đang tua tới giây bắt đầu: để yên
      // hình — bám theo lúc đó kéo hình về 0 giây (chủ máy 15/09/2026: "cứ quay về 0s liên tục").
      if (a.paused || a.readyState < 3 || a.seeking || n.trangThai !== 1 || Date.now() < dongBo.current.luiTuaDen) return;
      if (Math.abs(a.currentTime - n.thoiGian()) > 0.35) {
        n.tuaTheoTieng(a.currentTime);
        dongBo.current.luiTuaDen = Date.now() + 3000;
      }
    }, 1000);
    return () => clearInterval(hen);
  }, [theoMay]);

  // Bài nghe trên máy tự sang bài kế (kể cả lúc ở trang khác) mà video đang theo tiếng:
  // video đổi theo bài mới.
  useEffect(() => {
    if (!video?.theoMay || !nghe || nghe.id === video.bai.id) return;
    if (laVideo(nghe)) moVideo(nghe, false, 0, true);
    else dongVideo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nghe?.id]);

  // Video xem trên máy (có tiếng) mà trình duyệt chặn tiếng tự phát: thử bật tiếng
  // một lần, vẫn chặn thì hiện "Chạm vào video" — chỉ cú chạm vào chính khung mới mở.
  // Chủ máy 15/09/2026: "Khi chọn xem video thì mất 1 2 s video mới chạy" — kiểm từ giây
  // thứ nhất, mỗi nửa giây; khung đã sẵn sàng mà hai lần liền vẫn chặn thì xử lý ngay,
  // khung chưa nạp xong thì chờ tiếp (kẻo máy cho tự phát lại bị tắt tiếng oan).
  const muonTieng = !!video?.ngheTrenMay;
  useEffect(() => {
    setCanCham(false);
    if (!muonTieng) return;
    const chan = () => {
      const n = moiNhat.current.nhung;
      return n.tatTieng === true || [-1, 5].includes(n.trangThai);
    };
    let henLai: ReturnType<typeof setTimeout> | undefined;
    let lan = 0;
    let chanLienTiep = 0;
    const kiem = () => {
      const n = moiNhat.current.nhung;
      if (n.sanSang && n.trangThai === 1 && n.tatTieng === false) return;
      chanLienTiep = n.sanSang && chan() ? chanLienTiep + 1 : 0;
      if (chanLienTiep < 2 && ++lan < 20) {
        hen = setTimeout(kiem, 500);
        return;
      }
      if (!chan()) return;
      const v = moiNhat.current.video;
      if (v && !v.theoLoa && !v.theoMay && !tiengMayHong.current) {
        // Xem một mình: tiếng sang thẻ âm thanh của trang, video tắt tiếng chạy theo.
        moiNhat.current.chuyenTiengSangMay();
        return;
      }
      moiNhat.current.nhung.lenh("unMute");
      moiNhat.current.nhung.lenh("playVideo");
      henLai = setTimeout(() => setCanCham(chan()), 1500);
    };
    let hen = setTimeout(kiem, 1000);
    return () => {
      clearTimeout(hen);
      clearTimeout(henLai);
    };
  }, [muonTieng, video?.src, video?.bai.id]);
  useEffect(() => {
    if (canCham && nhung.trangThai === 1 && nhung.tatTieng !== true) setCanCham(false);
  }, [canCham, nhung.trangThai, nhung.tatTieng]);

  // Video theo thẻ âm thanh mà thẻ đó không phát được tiếng (máy chủ không trả luồng, hoặc
  // trình duyệt từ chối phát): khung tự giữ tiếng lại, dừng và bật tiếng để một chạm vào
  // video là phát có tiếng. Cứ bám theo tiếng câm thì chạm phát trong khung là bị dừng lại
  // (chủ máy 15/09/2026, card HA: "Kích vào play trên khung video thì giật rồi dừng").
  // Chờ nửa giây rồi xét lại phần tử: Chrome Android từ chối play() một lúc rồi vẫn phát
  // (22/09/2026). Đang có dữ liệu hoặc đang chạy thì không cắt.
  const coNghe = !!nghe;
  const tiengMayTuChoi = !!mayTrangThai.tuChoi;
  useEffect(() => {
    if (!video?.theoMay || video.hinh || (coNghe && !tiengMayTuChoi)) return;
    const hen = setTimeout(() => {
      const tt = mayNghe.layTrangThai();
      const a = mayNghe.amThat();
      if (tt.bai && !tt.tuChoi) return;
      if (a && !a.error && (a.readyState >= 2 || !a.paused)) return;
      if (tt.bai) mayNghe.dung();
      tiengMayHong.current = true;
      nhung.lenh("pauseVideo");
      nhung.lenh("unMute");
      setVideo((v) => (v?.theoMay ? { ...v, theoMay: false, ngheTrenMay: true } : v));
    }, 500);
    return () => clearTimeout(hen);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coNghe, tiengMayTuChoi, video?.theoMay, video?.hinh]);

  // Tải thẳng hình quá 8 giây chưa có hình: coi như không tải thẳng được.
  const giaiDoanHinh = video?.hinh?.trangThai;
  useEffect(() => {
    if (giaiDoanHinh !== "thang") return;
    const hen = setTimeout(() => moiNhat.current.hinhLoi(), 8000);
    return () => clearTimeout(hen);
  }, [giaiDoanHinh, video?.bai.id]);

  const coDieuKhien = loaPhien.some((t) => t.trang_thai !== "unavailable" && (t.tam_dung || t.dung));
  const rap = !!video && cheDo === "rap";

  // Cùng bố cục thẻ: video rồi loa bên trái, danh sách bên phải, hai cột ngang nhau.
  // Cột 80% đẩy cột tìm xuống dưới 20% và thông báo lỗi che hết ô tìm.
  return (
    <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:grid-rows-[auto_auto]">
      <DangPhat
        className={cn("min-w-0", rap ? "lg:col-span-2" : "lg:col-start-1 lg:row-start-1")}
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
        hinhLoi={hinhLoi}
        hinhSan={hinhSan}
        xemHinhNgoaiNha={xemHinhNgoaiNha}
        nhung={nhung}
        cheDo={cheDo}
        doiCheDo={doiCheDo}
        dongVideo={dongVideo}
        chiNghe={chiNghe}
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
              ? laVideo(nghe) ? () => moVideo(nghe, false, mayNghe.thoiGian(), true) : laFacebook(nghe) ? () => moHinh(nghe, false) : null
              : laVideo(phienXem?.item) ? () => moVideo(phienXem!.item!, loaPhien.some(dangHoatDong)) : laFacebook(phienXem?.item) ? () => moHinh(phienXem!.item!, true) : null
        }
        chonNhom={chonNhom}
        ngheCung={ngheCungIds.length ? () => void ngheCung() : null}
        tiengTrenMay={phienXem?.item && !nghe && !videoMotMinh ? tiengTrenMay : null}
        doiNgheTrenMay={doiNgheTrenMay}
      />
      <DanhSachThietBi
        className="min-w-0 lg:col-start-1 lg:row-start-2"
        thietBi={thietBi}
        loi={loiHa}
        chon={chon}
        batTat={batTat}
        amLuong={(tb, v) => void goi("dieu-khien", { lenh: "am_luong", entity_ids: [tb.entity_id], am_luong: v })}
        an={an}
        taiLai={() => void taiThietBi(false)}
      />
      <TimNhac
        className={cn("min-w-0", rap ? "lg:col-start-1 lg:row-start-2" : "lg:col-start-2 lg:row-span-2 lg:row-start-1")}
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
        kho={khoPlaylist}
        xemPlaylist={xemPlaylist}
        doiXemPlaylist={setXemPlaylist}
        luuCaPlaylist={() => void luuCaPlaylist()}
        dangLuuPlaylist={dangLuuPlaylist}
        bangPlaylist={
          <DanhSachPlaylist
            kho={khoPlaylist}
            coLoa={chon.size > 0}
            dangPhatMa={video ? video.bai.url || video.bai.id : nghe ? nghe.url || nghe.id : phienXem?.item ? phienXem.item.url || phienXem.item.id : ""}
            dangGuiMa={dangGuiMa}
            phat={(bai, xem, hang) => void phat(bai, xem, hang)}
            moSan={playlistMoSan}
          />
        }
      />
    </div>
  );
}
