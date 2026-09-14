"use client";

/**
 * Trình phát — tìm YouTube/Zing, link audio, phát ra loa/tivi HA theo PHIÊN.
 *
 * Chủ máy 14/09/2026: "Làm mỗi loa một bài hoặc chạy cùng 1 bài", "tắt trình duyệt
 * vẫn hoạt động", "mở mỗi bài 1 loa thì làm sao xem nó phát đến đâu, video đến đâu
 * khi tích vào mỗi loa". Luật:
 * - Tích loa = xem và điều khiển loa đó: "Đang phát", tiến độ và video theo phiên
 *   của loa vừa tích. Tích/bỏ tích không tự phát hay tắt loa.
 * - ▶ một bài: phát ra các loa đang tích (thành một phiên, rời phiên cũ). Chưa
 *   tích loa: bài YouTube xem ngay trên trang.
 * - ⏹ dừng các loa đang tích; ⏮⏭ theo hàng đợi của phiên. Máy chủ c2a tự chuyển
 *   bài khi loa hết bài (`services/youtube_phat/tu_chuyen_bai.py`), nên đóng trang
 *   nhạc vẫn chạy.
 * - Loa kèm video: loa phát tiếng, video tắt tiếng và bám vị trí loa; nút "Nghe cả
 *   trên máy này". Đang xem một mình mà tích loa thì loa phát tiếng video đó.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { httpRequest } from "@/lib/request";
import { cn } from "@/lib/utils";

import { DangPhat, type VideoMo, type ViTri } from "./dang-phat";
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
  // Hàng đợi của video xem một mình trên trang. Loa dùng hàng đợi của phiên máy chủ.
  const [hangVideo, setHangVideo] = useState<Hang | null>(null);
  const daNapChon = useRef(false);
  const lucTai = useRef(0);
  const dongBo = useRef({ luiTuaDen: 0, giuDen: 0, choTua: null as null | { id: string; tu: number; luc: number } });

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

  const videoMotMinh = !!video && !video.theoLoa;
  const loaPhien = phienXem ? phienXem.output_entity_ids.map((id) => theoMa.get(id)).filter((t): t is ThietBi => !!t) : daChon;
  const dangChay = videoMotMinh ? DANG_CHAY.includes(nhung.trangThai) : loaPhien.some((t) => t.trang_thai === "playing");

  const doiChon = (moi: Set<string>) => {
    setChon(moi);
    luuChon(moi);
  };

  const moVideo = (bai: BaiHat, voiLoa: boolean) => {
    if (!laVideo(bai)) return;
    const ngheTrenMay = voiLoa ? (video?.theoLoa ? video.ngheTrenMay : false) : true;
    if (video && nhung.sanSang) {
      // Cùng khung: đổi bài không nạp lại, giữ nguyên cỡ xem và toàn màn hình.
      nhung.lenh("loadVideoById", [{ videoId: bai.id, startSeconds: 0 }]);
      nhung.lenh(ngheTrenMay ? "unMute" : "mute");
      setVideo({ ...video, bai, theoLoa: voiLoa, ngheTrenMay });
    } else {
      nhung.datLai();
      setVideo({ bai, src: srcNhung(bai.id, !ngheTrenMay), theoLoa: voiLoa, ngheTrenMay });
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

  const capNhatPhien = (r: { cac_phien?: Phien[] } | null) => {
    if (r?.cac_phien) setCacPhien(r.cac_phien);
    void taiThietBi(true);
  };

  const phat = async (bai: BaiHat) => {
    const ids = [...chon].filter((id) => theoMa.get(id)?.phat_duoc);
    if (!chon.size) {
      if (laVideo(bai)) {
        // Chưa tích loa: xem ngay trên trang, với hàng đợi riêng.
        const i = ketQua.findIndex((k) => cungBai(k, bai));
        setHangVideo(i >= 0 ? { items: ketQua, index: i } : { items: [bai], index: 0 });
        moVideo(bai, false);
        return;
      }
      toast.error("Tích loa hoặc tivi để phát Zing MP3 hoặc link audio.");
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
    const ten = (id: string) => theoMa.get(id)?.ten ?? id;
    if (r.bo_qua.length) {
      toast.warning(`Đã gửi tới ${r.da_gui.map(ten).join(", ")}. Bỏ qua: ${r.bo_qua.map((b) => ten(b.entity_id)).join(", ")}.`);
    } else {
      toast.success(`Đang phát trên ${r.da_gui.map(ten).join(", ")}.`);
    }
    if (video) {
      // Hình theo loa: bài YouTube tắt tiếng và bám loa; nguồn chỉ có tiếng thì đóng hình.
      if (laVideo(bai)) moVideo(bai, true);
      else dongVideo();
    }
    void taiThietBi(true);
  };

  const hang = videoMotMinh ? hangVideo : phienXem?.queue ?? null;
  const coBai = (buoc: number) => !!hang && hang.index >= 0 && !!hang.items[hang.index + buoc];

  const chuyenBai = async (buoc: number) => {
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
  const moiNhat = useRef({ chuyenBai, video, thietBi, loaPhien, nhung });
  useEffect(() => {
    moiNhat.current = { chuyenBai, video, thietBi, loaPhien, nhung };
    hetVideo.current = () => {
      // Hết video xem một mình: tự sang bài kế trên trang. Có loa thì máy chủ lo.
      if (moiNhat.current.video && !moiNhat.current.video.theoLoa) void moiNhat.current.chuyenBai(1);
    };
  });

  // Tích sang loa khác: video đổi sang bài của loa đó và tua theo loa.
  const baiPhienXem = phienXem?.item ?? null;
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
      const { loaPhien: ds, nhung: n } = moiNhat.current;
      if (!n.sanSang) return;
      const db = dongBo.current;
      if (db.choTua) {
        const loa = ds.find((t) => t.entity_id === db.choTua?.id);
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
      const loa = ds.find((t) => dangHoatDong(t));
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

  const layViTri = (): ViTri => {
    if (videoMotMinh) {
      if (nhung.trangThai === -1) return null;
      return { giay: nhung.thoiGian(), tong: Number(video?.bai.duration || 0) };
    }
    const dan = loaPhien.find((t) => t.vi_tri !== null);
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

  const doiNgheTrenMay = () => {
    if (!video) return;
    const bat = !video.ngheTrenMay;
    nhung.lenh(bat ? "unMute" : "mute");
    setVideo({ ...video, ngheTrenMay: bat });
  };

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
        nhung={nhung}
        cheDo={cheDo}
        doiCheDo={doiCheDo}
        dongVideo={dongVideo}
        dangChay={dangChay}
        dangGui={!!dangGuiMa}
        layViTri={layViTri}
        truoc={coBai(-1) ? () => void chuyenBai(-1) : null}
        tiep={coBai(1) ? () => void chuyenBai(1) : null}
        phatTamDung={video || coDieuKhien ? phatTamDung : null}
        dung={video || phienXem || coDieuKhien ? () => void dung() : null}
        xemTaiDay={!video && laVideo(phienXem?.item) ? () => moVideo(phienXem!.item!, loaPhien.some(dangHoatDong)) : null}
        chonNhom={chonNhom}
        ngheCung={ngheCungIds.length ? () => void ngheCung() : null}
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
        dangPhatMa={video ? video.bai.url || video.bai.id : phienXem?.item ? phienXem.item.url || phienXem.item.id : ""}
        dangGuiMa={dangGuiMa}
        coLoa={chon.size > 0}
        phat={(bai) => void phat(bai)}
      />
    </div>
  );
}
