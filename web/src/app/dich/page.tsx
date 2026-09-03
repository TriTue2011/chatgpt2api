"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Languages, LoaderCircle, Upload, FileText, Download, Copy, Check, Mic, MessagesSquare, Volume2 } from "lucide-react";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { request } from "@/lib/request";
import webConfig from "@/constants/common-env";
import { cn } from "@/lib/utils";

/** Khúc upload 25MB — đường domain qua Cloudflare chặn thân request ~100MB,
 *  nên tệp lớn phải đi thành nhiều request nhỏ; LAN thì đằng nào cũng nhanh. */
const KHUC = 25 * 1024 * 1024;
const TRAN_TEP = 4 * 1024 * 1024 * 1024;

const DUOI_NHAN = ".mp4,.mov,.mkv,.webm,.avi,.m4v,.ts,.3gp,.mp3,.m4a,.aac,.ogg,.opus,.wav,.flac,"
  + ".srt,.vtt,.jpg,.jpeg,.png,.webp,.gif,.bmp,.pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.odt,.odp,.txt,.epub,.html,.htm";

/** Chọn RIÊNG tiếng nguồn và tiếng đích, không chọn theo "cặp".
 *
 *  Bản trước chỉ có bốn cặp và cặp nào cũng neo vào tiếng Việt, nên Nhật → Hàn
 *  hay Anh → Trung là không chọn được — dù máy dịch trong stack làm được đủ 20
 *  chiều (hỏi /languages ngày 15/08: cả năm tiếng đều nhận cả năm làm đích).
 *
 *  Khai tiếng nguồn còn giúp video/âm thanh: biết trước thì bộ nghe khoá cứng
 *  một model, khỏi tốn lượt nghe thử để dò. Để "tự nhận" thì máy dò như cũ. */
/** Trần ký tự nhét vào URL Google Dịch. Trình duyệt và máy chủ đều cắt URL quá
 *  dài, mà cắt thì mất im lặng — nên chặn ở đây và nói rõ cho người dùng. */
const GOOGLE_TRAN_KY_TU = 1800;

type NghiaTu = { vi: string; tu_loai: string; vi_du: string };
type TraCuu = {
  tu: string; goc?: string; ipa: string; nghia: NghiaTu[]; co_tu_dien: boolean;
  /** Bản dịch máy của Google, chỉ có khi từ điển tại chỗ không trả gì VÀ
   *  chủ máy đã bật Google — dùng cho Nhật/Trung/Hàn, thứ kho chưa phủ. */
  google?: string;
};

// Nhiều tiếng cho ĐƯỜNG GOOGLE (mở trên trình duyệt): máy dịch trong stack chỉ
// có 5 tiếng, còn Google 100+. Chỉ liệt kê các tiếng hay dùng; "auto" = tự nhận.
const TIENG_GOOGLE: { value: string; label: string }[] = [
  { value: "auto", label: "Tự nhận tiếng" },
  { value: "vi", label: "Việt" }, { value: "en", label: "Anh" },
  { value: "zh-CN", label: "Trung (giản thể)" }, { value: "zh-TW", label: "Trung (phồn thể)" },
  { value: "ja", label: "Nhật" }, { value: "ko", label: "Hàn" },
  { value: "fr", label: "Pháp" }, { value: "de", label: "Đức" },
  { value: "es", label: "Tây Ban Nha" }, { value: "pt", label: "Bồ Đào Nha" },
  { value: "it", label: "Ý" }, { value: "ru", label: "Nga" },
  { value: "th", label: "Thái" }, { value: "id", label: "Indonesia" },
  { value: "ms", label: "Mã Lai" }, { value: "km", label: "Khmer" },
  { value: "lo", label: "Lào" }, { value: "hi", label: "Hindi" },
  { value: "ar", label: "Ả Rập" }, { value: "nl", label: "Hà Lan" },
  { value: "pl", label: "Ba Lan" }, { value: "tr", label: "Thổ Nhĩ Kỳ" },
  { value: "uk", label: "Ukraina" }, { value: "fa", label: "Ba Tư" },
  { value: "he", label: "Do Thái" }, { value: "sv", label: "Thụy Điển" },
  { value: "el", label: "Hy Lạp" }, { value: "cs", label: "Séc" },
  { value: "ro", label: "Rumani" }, { value: "hu", label: "Hungary" },
  { value: "fi", label: "Phần Lan" }, { value: "da", label: "Đan Mạch" },
  { value: "no", label: "Na Uy" }, { value: "my", label: "Miến Điện" },
  { value: "bn", label: "Bengal" }, { value: "ta", label: "Tamil" },
  { value: "tl", label: "Philippines" },
];

// Tiếng cho MÁY DỊCH TRONG STACK (kết quả hiện ngay trong app, tự chủ, không
// bên thứ ba). Khớp đúng engine.ISO2FLORES của vn-translate — model NLLB-200 đã
// nạp dịch trực tiếp giữa hai tiếng bất kỳ ở đây (en↔vi dùng EnViT5, còn lại
// NLLB). Đo 28/08 trên máy chủ: fr/ru/th → vi đều chạy. Thêm tiếng = thêm vào
// ISO2FLORES rồi dựng lại image vn-translate (NLLB có sẵn 200 tiếng, không tải
// thêm). KHÁC TIENG_GOOGLE (mở trình duyệt) — đây là bản dịch tại chỗ.
const CAC_TIENG = [
  { value: "vi", label: "Tiếng Việt" },
  { value: "en", label: "Tiếng Anh" },
  { value: "zh", label: "Tiếng Trung" },
  { value: "ja", label: "Tiếng Nhật" },
  { value: "ko", label: "Tiếng Hàn" },
  { value: "fr", label: "Tiếng Pháp" },
  { value: "de", label: "Tiếng Đức" },
  { value: "es", label: "Tiếng Tây Ban Nha" },
  { value: "pt", label: "Tiếng Bồ Đào Nha" },
  { value: "it", label: "Tiếng Ý" },
  { value: "ru", label: "Tiếng Nga" },
  { value: "uk", label: "Tiếng Ukraina" },
  { value: "pl", label: "Tiếng Ba Lan" },
  { value: "nl", label: "Tiếng Hà Lan" },
  { value: "tr", label: "Tiếng Thổ Nhĩ Kỳ" },
  { value: "ar", label: "Tiếng Ả Rập" },
  { value: "hi", label: "Tiếng Hindi" },
  { value: "th", label: "Tiếng Thái" },
  { value: "id", label: "Tiếng Indonesia" },
  { value: "km", label: "Tiếng Khmer" },
  { value: "lo", label: "Tiếng Lào" },
  { value: "ms", label: "Tiếng Mã Lai" },
  { value: "tl", label: "Tiếng Philippines" },
  { value: "my", label: "Tiếng Miến Điện" },
  { value: "bn", label: "Tiếng Bengal" },
  { value: "ta", label: "Tiếng Tamil" },
  { value: "ur", label: "Tiếng Urdu" },
  { value: "fa", label: "Tiếng Ba Tư" },
  { value: "he", label: "Tiếng Do Thái" },
  { value: "el", label: "Tiếng Hy Lạp" },
  { value: "cs", label: "Tiếng Séc" },
  { value: "ro", label: "Tiếng Rumani" },
  { value: "hu", label: "Tiếng Hungary" },
  { value: "sv", label: "Tiếng Thụy Điển" },
  { value: "fi", label: "Tiếng Phần Lan" },
  { value: "da", label: "Tiếng Đan Mạch" },
  { value: "no", label: "Tiếng Na Uy" },
  { value: "bg", label: "Tiếng Bulgaria" },
  { value: "sr", label: "Tiếng Serbia" },
  { value: "sw", label: "Tiếng Swahili" },
];

/** Đuôi cho ra PHỤ ĐỀ (hiện lựa chọn Phụ đề/Bản chữ): video, âm thanh, và
 *  tệp phụ đề sẵn (.srt/.vtt — đường nhanh nhất cho phim, khỏi nghe). */
const DUOI_NGHE = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp",
  ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac", ".srt", ".vtt"];
const DUOI_VIDEO = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp"];

type GiongLongTieng = {
  id: string;
  label: string;
  downloaded: boolean;
  recommended: boolean;
};

type KetQua = {
  kieu: string;                 // "chu" | "tep" | "phu-de"
  text?: string;
  goc?: string;                 // chữ OCR đọc được (dịch ảnh)
  nguon?: string;
  dich?: string;
  tep?: { ten: string; url: string }[];
  bao_cao?: string;
  voice?: string;
  tudien?: TraCuu | null;       // MỘT từ dịch sang Việt → nghĩa từ điển đầy đủ
};

function layLoi(e: unknown): string {
  const err = e as { response?: { data?: { detail?: { error?: string }; error?: string } }; message?: string };
  return err?.response?.data?.detail?.error || err?.response?.data?.error || err?.message || "lỗi không rõ";
}

function DichPageContent() {
  const [chu, setChu] = useState("");
  const [target, setTarget] = useState("en");
  const [nguon, setNguon] = useState("");   // "" = để máy tự nhận
  const [tep, setTep] = useState<File | null>(null);
  const [kieuRa, setKieuRa] = useState("phu-de");
  const [giong, setGiong] = useState("");
  const [cacGiong, setCacGiong] = useState<GiongLongTieng[]>([]);
  const [tachAmSanSang, setTachAmSanSang] = useState<boolean | null>(null);
  const [loiTachAm, setLoiTachAm] = useState("");
  const [dangTaiGiong, setDangTaiGiong] = useState(false);
  const [dangChay, setDangChay] = useState(false);
  const [tienDo, setTienDo] = useState(0);       // % upload; -1 = không upload
  const [buoc, setBuoc] = useState("");
  // % của việc đang chạy trên máy chủ. null = giai đoạn không đo được (Whisper
  // GPU nghe cả tệp trong một lần gọi) → chạy thanh vô định thay vì số giả.
  const [phanTram, setPhanTram] = useState<number | null>(null);
  const [loi, setLoi] = useState("");
  const [ketQua, setKetQua] = useState<KetQua | null>(null);
  const [daChep, setDaChep] = useState(false);
  const chonTep = useRef<HTMLInputElement>(null);

  // Bước LLM chỉnh nghĩa chuyên ngành — TÙY CHỌN, mặc định TẮT (giữ tự chủ).
  // Cấu hình dùng chung, lưu ở config.dich_llm; đọc/ghi qua /api/settings.
  // Google Dịch — ý kiến thứ hai, mặc định TẮT vì chữ sẽ rời máy chủ này.
  const [googleBat, setGoogleBat] = useState(false);
  // Tiếng nguồn/đích RIÊNG cho đường Google (mở trình duyệt) — tách khỏi ô chọn
  // của máy dịch trong stack vì Google phủ nhiều tiếng hơn hẳn.
  const [gSl, setGSl] = useState("auto");
  const [gTl, setGTl] = useState("vi");
  const [googleKq, setGoogleKq] = useState("");
  const [googleLoi, setGoogleLoi] = useState("");
  const [googleDangChay, setGoogleDangChay] = useState(false);

  const [llmBat, setLlmBat] = useState(false);
  const [llmModel, setLlmModel] = useState("");
  const [modelsLlm, setModelsLlm] = useState<Record<string, string[]>>({});
  const [luuLlm, setLuuLlm] = useState<"" | "saved" | "err">("");

  useEffect(() => {
    request.get("/api/settings")
      .then((r) => {
        const d = ((r.data as any)?.config?.dich_llm) || {};
        setLlmBat(Boolean(d.bat));
        setLlmModel(String(d.model || ""));
        setGoogleBat(Boolean((((r.data as any)?.config?.dich_google) || {}).bat));
      })
      .catch(() => {});
    request.get("/api/v1/available-models")
      .then((r) => setModelsLlm(((r.data as any)?.providers as Record<string, string[]>) || {}))
      .catch(() => setModelsLlm({}));
  }, []);

  const luuDichGoogle = async (bat: boolean) => {
    setGoogleBat(bat);
    if (!bat) { setGoogleKq(""); setGoogleLoi(""); }
    try { await request.post("/api/settings", { dich_google: { bat } }); }
    catch { setGoogleBat(!bat); }
  };

  const xemGoogle = async () => {
    const q = chu.trim();
    if (!q) return;
    setGoogleDangChay(true); setGoogleLoi(""); setGoogleKq("");
    try {
      const r = await request.post("/api/dich/google",
        { q, target: ketQua?.dich || target, source: nguon });
      setGoogleKq(String((r.data as any)?.text || ""));
    } catch (e) {
      // 429 = Google chặn IP máy chủ (endpoint không chính thức). Không phải
      // lỗi tạm — chỉ đường qua trình duyệt (nút bên dưới) mới chắc chắn.
      const msg = layLoi(e);
      setGoogleLoi(/429|too many|chặn/i.test(msg)
        ? "Google đang chặn IP máy chủ. Dùng nút “Mở trên Google Dịch” ở khối "
          + "trên — trình duyệt của anh tự mở, không bị chặn."
        : msg);
    } finally { setGoogleDangChay(false); }
  };

  const luuDichLlm = async (bat: boolean, model: string) => {
    setLlmBat(bat); setLlmModel(model);
    try {
      await request.post("/api/settings", { dich_llm: { bat, model } });
      setLuuLlm("saved"); setTimeout(() => setLuuLlm(""), 2000);
    } catch {
      setLuuLlm("err");
    }
  };

  // Sửa thuật ngữ dịch — bản sửa tay THẮNG cả từ điển gốc, hiệu lực ngay lần
  // sau. Lưu ở máy chủ (glossary/<src>.sua.json), không mất khi cập nhật.
  const [suaSrc, setSuaSrc] = useState("en");
  const [dsLinhVuc, setDsLinhVuc] = useState<{ slug: string; ten: string }[]>([]);
  const [dsSua, setDsSua] = useState<Record<string, Record<string, string>>>({});
  const [suaLinhVuc, setSuaLinhVuc] = useState("cong_nghe");
  const [suaTerm, setSuaTerm] = useState("");
  const [suaVi, setSuaVi] = useState("");
  const [suaMsg, setSuaMsg] = useState("");

  // Kho thuật ngữ ĐANG DÙNG của lĩnh vực đang chọn: gộp bản chuẩn + máy tự học
  // + bản sửa tay. Phải cho THẤY thì người dùng mới tự phát hiện được từ máy
  // học sai; chỉ đưa con số đếm thì họ không có cách nào biết.
  type MucKho = { term: string; vi: string; nguon: "chuan" | "hoc" | "sua" };
  type DeXuat = { term: string; hien_tai: string; de_xuat: string; ly_do: string };
  const [dsKho, setDsKho] = useState<MucKho[]>([]);
  const [deXuat, setDeXuat] = useState<DeXuat[] | null>(null);
  const [dangSoat, setDangSoat] = useState(false);

  const napKho = useCallback(() => {
    request.get(`/api/dich/glossary?src=${suaSrc}&linh_vuc=${suaLinhVuc}`)
      .then((r) => {
        setDsLinhVuc(((r.data as any)?.linh_vuc as { slug: string; ten: string }[]) || []);
        setDsSua(((r.data as any)?.sua as Record<string, Record<string, string>>) || {});
        setDsKho(((r.data as any)?.danh_sach as MucKho[]) || []);
      })
      .catch(() => { setDsLinhVuc([]); setDsSua({}); setDsKho([]); });
  }, [suaSrc, suaLinhVuc]);

  useEffect(() => { napKho(); setDeXuat(null); }, [napKho]);

  // Nhờ AI soát kho. Chỉ ĐỀ XUẤT kèm lý do, không tự ghi — người dùng đọc lý do
  // rồi tự quyết, vì chọn từ ngành là việc của người biết ngành.
  const soatKho = async () => {
    setDangSoat(true); setDeXuat(null); setSuaMsg("");
    try {
      const r = await request.post("/api/dich/glossary/soat",
        { src: suaSrc, linh_vuc: suaLinhVuc });
      const ds = ((r.data as any)?.de_xuat as DeXuat[]) || [];
      setDeXuat(ds);
      setSuaMsg(ds.length
        ? `AI soát ${(r.data as any)?.da_soat ?? 0} mục, thấy ${ds.length} chỗ nên sửa.`
        : `AI soát ${(r.data as any)?.da_soat ?? 0} mục, không thấy chỗ nào cần sửa.`);
    } catch (e) { setSuaMsg("❌ " + layLoi(e)); }
    finally { setDangSoat(false); }
  };

  // Nhận một đề xuất = ghi vào bảng SỬA TAY (thắng mọi tầng), không đụng vào
  // kho tự học — giữ được dấu vết máy đã học gì để còn đối chiếu.
  const nhanDeXuat = async (d: DeXuat) => {
    try {
      await request.post("/api/dich/glossary",
        { src: suaSrc, linh_vuc: suaLinhVuc, term: d.term, vi: d.de_xuat });
      setDeXuat((cu2) => (cu2 || []).filter((x) => x.term !== d.term));
      napKho();
      setSuaMsg(`✓ Đã nhận "${d.term}" → "${d.de_xuat}".`);
    } catch (e) { setSuaMsg("❌ " + layLoi(e)); }
  };

  const xoaHoc = async (term: string) => {
    try {
      await request.post("/api/dich/glossary/xoa-hoc",
        { src: suaSrc, linh_vuc: suaLinhVuc, term });
      napKho();
      setSuaMsg(`✓ Đã xoá mục tự học "${term}" — lượt lồng tiếng sau có thể học lại.`);
    } catch (e) { setSuaMsg("❌ " + layLoi(e)); }
  };

  const tenLinhVuc = (slug: string) => dsLinhVuc.find((x) => x.slug === slug)?.ten || slug;

  // Tra từ điển tại chỗ. Máy dịch buộc phải CHỌN một nghĩa; ô này cho thấy hết
  // các nghĩa rồi để người dùng tự chọn cái đúng ngữ cảnh của mình — "stroke"
  // có tới mười nghĩa, không ngữ cảnh thì không engine nào đoán đúng được.
  const [traTu, setTraTu] = useState("");
  const [traKq, setTraKq] = useState<TraCuu | null>(null);
  const [traDangChay, setTraDangChay] = useState(false);

  const traCuu = async (tu?: string) => {
    const q = (tu ?? traTu).trim();
    if (!q) return;
    setTraDangChay(true);
    try {
      const r = await request.get(
        `/api/dich/tra-cuu?src=${suaSrc}&q=${encodeURIComponent(q)}`);
      setTraKq(r.data as TraCuu);
    } catch { setTraKq(null); }
    finally { setTraDangChay(false); }
  };

  // Chọn một nghĩa = ĐỔ vào ô sửa thuật ngữ ngay bên dưới, không lưu thẳng:
  // nghĩa trong từ điển hay ở dạng "Cú, cú đánh, đòn." — người dùng phải được
  // cắt lại còn đúng chữ mình muốn trước khi nó thành luật cho mọi lượt dịch.
  const dungNghia = (tu: string, vi: string) => {
    setSuaTerm(tu);
    setSuaVi(vi.replace(/\.$/, "").trim());
    setSuaMsg("Sửa lại cho gọn nếu cần rồi bấm Lưu.");
  };

  const luuSua = async () => {
    const term = suaTerm.trim(), vi = suaVi.trim();
    if (!term || !vi) { setSuaMsg("❌ Nhập cả từ gốc và từ Việt."); return; }
    try {
      const r = await request.post("/api/dich/glossary",
        { src: suaSrc, linh_vuc: suaLinhVuc, term, vi });
      setDsSua(((r.data as any)?.sua as Record<string, Record<string, string>>) || {});
      setSuaTerm(""); setSuaVi(""); setSuaMsg("✓ Đã lưu — lần dịch sau sẽ dùng từ này.");
      napKho();
    } catch (e) { setSuaMsg("❌ " + layLoi(e)); }
  };

  const xoaSua = async (linh_vuc: string, term: string) => {
    try {
      const r = await request.post("/api/dich/glossary/xoa", { src: suaSrc, linh_vuc, term });
      setDsSua(((r.data as any)?.sua as Record<string, Record<string, string>>) || {});
      napKho();
    } catch (e) { setSuaMsg("❌ " + layLoi(e)); }
  };

  // Mở Google Dịch trong TAB MỚI, điền sẵn nội dung. Đây KHÔNG phải tích hợp
  // API: trình duyệt của người dùng tự gọi Google, máy chủ này không gửi gì đi,
  // không cần khoá và không tốn tiền. Đổi lại, kết quả nằm bên đó chứ không
  // quay về app được. Có để dùng cho những tiếng ngoài 5 tiếng máy dịch trong
  // stack hỗ trợ — Google có hơn 130 tiếng, đổi ở ô nguồn/đích là ra sl/tl.
  const moGoogle = (op: "translate" | "websites" | "images" | "docs" = "translate") => {
    const sl = gSl || "auto";
    const tl = gTl || "vi";
    const nd = chu.trim();
    let url = `https://translate.google.com/?sl=${sl}&tl=${tl}&op=${op}`;
    if (op === "translate") {
      url += `&text=${encodeURIComponent(nd.slice(0, GOOGLE_TRAN_KY_TU))}`;
    } else if (op === "websites" && /^https?:\/\//i.test(nd)) {
      // Dạng này Google chuyển hướng thẳng sang bản dịch của trang
      // (kiểm 28/08: 302 → <tên-miền>.translate.goog), khỏi phải dán lại link.
      url = `https://translate.google.com/translate?sl=${sl}&tl=${tl}`
        + `&u=${encodeURIComponent(nd)}`;
    }
    // Ảnh và tài liệu chỉ MỞ được đúng chế độ — tệp phải tự chọn bên đó, URL
    // không đính kèm tệp được.
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const laVideo = !!tep && DUOI_VIDEO.some((d) => tep.name.toLowerCase().endsWith(d));

  useEffect(() => {
    if (kieuRa !== "long-tieng") return;
    let conHieuLuc = true;
    // Không giữ giọng của tiếng đích cũ trong lúc request mới đang chạy; nếu
    // bấm nhanh, backend sẽ nhận sai ID giọng dù select chưa kịp đổi nhãn.
    setGiong("");
    setCacGiong([]);
    setTachAmSanSang(null);
    setLoiTachAm("");
    setDangTaiGiong(true);
    request.get("/api/dich/giong", { params: { lang: target } })
      .then((res) => {
        if (!conHieuLuc) return;
        const data = res.data as { voices?: GiongLongTieng[]; mac_dinh?: string; separator_ready?: boolean; separator_error?: string };
        const rows = (data.voices || []);
        setCacGiong(rows);
        setTachAmSanSang(data.separator_ready !== false);
        setLoiTachAm(data.separator_error || "");
        setGiong((cu) => {
          if (rows.some((v) => v.id === cu && v.downloaded)) return cu;
          // Giọng chốt trong Cài đặt đứng trước giọng máy tự khuyến nghị — cùng
          // thứ tự backend dùng cho đường chat bot, để web và bot không lệch nhau.
          const macDinh = rows.find((v) => v.id === data.mac_dinh && v.downloaded);
          return macDinh?.id || rows.find((v) => v.recommended)?.id || "";
        });
      })
      .catch((e) => { if (conHieuLuc) { setCacGiong([]); setGiong(""); setLoi(layLoi(e)); } })
      .finally(() => { if (conHieuLuc) setDangTaiGiong(false); });
    return () => { conHieuLuc = false; };
  }, [kieuRa, target]);

  function batDau() {
    setLoi(""); setKetQua(null); setBuoc(""); setTienDo(-1); setPhanTram(null);
    setDangChay(true); setDaChep(false);
  }

  /** Thăm dò việc nền tới khi xong/lỗi. Lỗi mạng lẻ tẻ thì thử tiếp,
   *  3 lần liền mới bỏ cuộc — job trên máy chủ vẫn chạy, mất mạng ≠ mất việc. */
  async function thamDo(viecId: string) {
    let hong = 0;
    for (;;) {
      await new Promise((r) => setTimeout(r, 2500));
      try {
        const res = await request.get(`/api/dich/viec/${viecId}`);
        hong = 0;
        const d = res.data as { trang_thai: string; buoc?: string; phan_tram?: number | null; loi?: string; bao_cao?: string; ket_qua?: KetQua };
        setBuoc(d.buoc || "");
        setPhanTram(typeof d.phan_tram === "number" ? d.phan_tram : null);
        if (d.trang_thai === "xong") {
          setKetQua({ ...(d.ket_qua as KetQua), bao_cao: d.bao_cao });
          return;
        }
        if (d.trang_thai === "loi") { setLoi(d.loi || "lỗi không rõ"); return; }
      } catch (e) {
        if (++hong >= 3) { setLoi(layLoi(e)); return; }
      }
    }
  }

  async function dichChu() {
    const nd = chu.trim();
    if (!nd || dangChay) return;
    batDau();
    try {
      const res = await request.post("/api/dich/chu", { noi_dung: nd, target, nguon });
      const d = res.data as { viec_id?: string } & KetQua;
      if (d.viec_id) {
        setBuoc("đang lấy phụ đề và dịch…");
        await thamDo(d.viec_id);
      } else {
        setKetQua(d);
      }
    } catch (e) {
      setLoi(layLoi(e));
    } finally {
      setDangChay(false);
    }
  }

  async function dichTep() {
    if (!tep || dangChay) return;
    if (kieuRa === "long-tieng" && dangTaiGiong) {
      setLoi("Danh sách giọng vẫn đang tải, vui lòng chờ một chút.");
      return;
    }
    if (kieuRa === "long-tieng" && !giong) {
      setLoi("Chưa có giọng phù hợp đã tải trên máy; vào Cài đặt → Giọng nói để tải model.");
      return;
    }
    if (kieuRa === "long-tieng" && tachAmSanSang === false) {
      setLoi(`Máy tách lời chưa sẵn sàng: ${loiTachAm || "chưa cấu hình"}.`);
      return;
    }
    if (tep.size > TRAN_TEP) {
      setLoi(`Tệp ${(tep.size / 1024 / 1024).toFixed(0)}MB vượt trần 4GB`);
      return;
    }
    batDau();
    setTienDo(0);
    try {
      const tong = Math.max(1, Math.ceil(tep.size / KHUC));
      let viecId = "";
      for (let i = 0; i < tong; i++) {
        const fd = new FormData();
        fd.append("viec_id", viecId);
        fd.append("chi_so", String(i));
        fd.append("tong", String(tong));
        fd.append("ten", tep.name);
        fd.append("khuc", tep.slice(i * KHUC, (i + 1) * KHUC), tep.name);
        // Đếm theo BYTE chứ không theo khúc: khúc là 25 MB nên đếm theo khúc
        // thì tệp 100 MB chỉ nhảy 4 nấc, tệp nhỏ hơn 25 MB nhảy thẳng 0 → 100
        // và người dùng tưởng máy treo.
        const daXong = i * KHUC;
        const res = await request.post("/api/dich/khuc", fd, {
          onUploadProgress: (e) => {
            // e.loaded tính cả phần bọc multipart nên có thể vượt cỡ tệp.
            setTienDo(Math.min(100, Math.round(((daXong + e.loaded) / tep.size) * 100)));
          },
        });
        viecId = (res.data as { viec_id: string }).viec_id;
      }
      setTienDo(-1);
      await request.post("/api/dich/tep", {
        viec_id: viecId, target, nguon, kieu_ra: kieuRa, voice: giong,
      });
      setBuoc("đang xử lý…");
      await thamDo(viecId);
    } catch (e) {
      setLoi(layLoi(e));
    } finally {
      setDangChay(false);
    }
  }

  async function chepKetQua() {
    if (!ketQua?.text) return;
    await navigator.clipboard.writeText(ketQua.text);
    setDaChep(true);
    setTimeout(() => setDaChep(false), 1500);
  }

  const goc = (webConfig.apiUrl || "").replace(/\/$/, "");

  function doiNguon(moi: string) {
    setNguon(moi);
    // Nguồn được chọn sau khi đích đã chọn có thể làm UI giữ một state không
    // hợp lệ (ví dụ đích Nhật rồi đổi nguồn sang Nhật). Đổi đích nguyên tử để
    // request không bị backend từ chối vì dịch một ngôn ngữ sang chính nó.
    if (moi && moi === target) {
      const dichMoi = CAC_TIENG.find((o) => o.value !== moi)?.value;
      if (dichMoi) setTarget(dichMoi);
    }
  }

  function chonTepMoi(f: File) {
    setTep(f);
    const video = DUOI_VIDEO.some((d) => f.name.toLowerCase().endsWith(d));
    if (!video && kieuRa === "long-tieng") setKieuRa("phu-de");
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Languages className="size-6" />
        <div>
          <h1 className="text-xl font-semibold">Dịch</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Chữ, link YouTube, ảnh, tài liệu, video — dịch bằng máy dịch trong stack, không tốn lượt AI.
            Hơn 20 thứ tiếng (Pháp, Nga, Thái, Đức…) dịch tại chỗ; tiếng khác thì mở Google ở khối trên.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <select value={nguon} onChange={(e) => doiNguon(e.target.value)} disabled={dangChay}
            className="rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
            <option value="">Tự nhận tiếng</option>
            {CAC_TIENG.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <span className="text-[var(--muted-foreground)]">→</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)} disabled={dangChay}
            className="rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
            {CAC_TIENG.filter((o) => o.value !== nguon).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Chỉnh nghĩa chuyên ngành bằng LLM — tùy chọn, mặc định TẮT */}
      <details className="rounded-[16px] border border-[var(--border)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium">
          Chỉnh nghĩa chuyên ngành bằng LLM (tùy chọn)
          {llmBat && <span className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-700">đang bật</span>}
          {luuLlm === "saved" && <span className="ml-2 text-xs text-emerald-600">✓ đã lưu</span>}
          {luuLlm === "err" && <span className="ml-2 text-xs text-red-600">lưu lỗi</span>}
        </summary>
        <div className="mt-3 space-y-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={llmBat}
              onChange={(e) => luuDichLlm(e.target.checked, llmModel)} />
            Bật LLM chỉnh nghĩa + mượt câu (sau khi thay thuật ngữ chuẩn)
          </label>
          <div className="space-y-1">
            <label className="block text-sm text-[var(--muted-foreground)]">Model chỉnh dịch</label>
            <select value={llmModel} disabled={!llmBat}
              onChange={(e) => luuDichLlm(llmBat, e.target.value)}
              className="w-full rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm disabled:opacity-50">
              <option value="">— Chọn model (gồm cả model cục bộ) —</option>
              {Object.entries(modelsLlm).map(([nha, ds]) => (
                <optgroup key={nha} label={nha}>
                  {ds.map((m) => <option key={m} value={m}>{m}</option>)}
                </optgroup>
              ))}
            </select>
          </div>
          <p className="text-xs text-[var(--muted-foreground)]">
            Mặc định TẮT để giữ tự chủ: tắt thì chỉ dùng máy dịch trong stack + kho thuật ngữ,
            không gọi bên thứ ba. Bật thì thêm một model chỉnh nghĩa theo ngữ cảnh và làm mượt câu
            — nên chọn <b>model cục bộ</b>. Dùng model online cũng được, khi đó hệ thống tự chắt
            lọc thuật ngữ mới vào từ điển để lần sau bớt cần LLM. Cài đặt dùng chung cho mọi lượt
            dịch phụ đề/lồng tiếng.
          </p>
        </div>
      </details>

      {/* Google Dịch — đối chiếu và mở sang bản web, tuỳ chọn, mặc định TẮT */}
      <details className="rounded-[16px] border border-[var(--border)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium">
          Google Dịch (đối chiếu — tuỳ chọn)
          {googleBat && <span className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-700">đang bật</span>}
        </summary>
        <div className="mt-3 space-y-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={googleBat}
              onChange={(e) => luuDichGoogle(e.target.checked)} />
            Cho phép máy chủ hỏi Google để hiện bản dịch đối chiếu
          </label>
          <p className="text-xs text-[var(--muted-foreground)]">
            Bật thì sau mỗi lần dịch chữ sẽ có nút xem thêm bản của Google để so.
            <b> Chữ được gửi sang máy chủ Google</b> — đó là lý do mặc định tắt.
            Đường dịch chính vẫn là máy trong stack, Google hỏng hay bị chặn cũng
            không ảnh hưởng gì.
          </p>
          <div className="space-y-2">
            <div className="text-sm text-[var(--muted-foreground)]">
              Mở thẳng trang Google Dịch — trình duyệt của anh tự mở (không gửi
              gì từ máy chủ này, không bị chặn IP), <b>tự nhận tiếng</b> và hơn
              130 tiếng. Đây là đường tin cậy nhất cho các tiếng máy dịch trong
              stack chưa có:
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <select value={gSl} onChange={(e) => setGSl(e.target.value)}
                className="rounded-[10px] border border-[var(--border)] bg-transparent px-2 py-1.5">
                {TIENG_GOOGLE.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <span className="text-[var(--muted-foreground)]">→</span>
              <select value={gTl} onChange={(e) => setGTl(e.target.value)}
                className="rounded-[10px] border border-[var(--border)] bg-transparent px-2 py-1.5">
                {TIENG_GOOGLE.filter((o) => o.value !== "auto").map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => moGoogle("translate")} disabled={!chu.trim()}
                className="rounded-[10px] border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--muted)] disabled:opacity-50">
                Văn bản
              </button>
              <button type="button" onClick={() => moGoogle("websites")}
                disabled={!/^https?:\/\//i.test(chu.trim())}
                title="Dán link trang web vào ô chữ rồi bấm — Google mở luôn bản dịch của trang đó"
                className="rounded-[10px] border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--muted)] disabled:opacity-50">
                Trang web
              </button>
              <button type="button" onClick={() => moGoogle("images")}
                className="rounded-[10px] border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--muted)]">
                Hình ảnh
              </button>
              <button type="button" onClick={() => moGoogle("docs")}
                className="rounded-[10px] border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--muted)]">
                Tài liệu
              </button>
            </div>
            <p className="text-xs text-[var(--muted-foreground)]">
              <b>Văn bản</b> và <b>Trang web</b> mang sẵn nội dung/link trong ô chữ sang.
              <b> Hình ảnh</b> và <b>Tài liệu</b> chỉ mở đúng chế độ — tệp phải tự chọn
              bên đó, link không đính kèm tệp được. Ảnh và tài liệu thì tab này đã dịch
              được tại chỗ ở phần tải tệp bên dưới.
            </p>
          </div>
        </div>
      </details>

      {/* Sửa thuật ngữ dịch — thắng cả từ điển gốc, hiệu lực ngay lần sau */}
      <details className="rounded-[16px] border border-[var(--border)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium">
          Sửa thuật ngữ dịch (khi thấy từ chuyên ngành dịch sai)
        </summary>
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm">
              <span className="mr-2 text-[var(--muted-foreground)]">Tiếng gốc</span>
              <select value={suaSrc} onChange={(e) => setSuaSrc(e.target.value)}
                className="rounded-[10px] border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm">
                <option value="en">Anh</option>
                <option value="ja">Nhật</option>
                <option value="zh">Trung</option>
                <option value="ko">Hàn</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="mr-2 text-[var(--muted-foreground)]">Lĩnh vực</span>
              <select value={suaLinhVuc} onChange={(e) => setSuaLinhVuc(e.target.value)}
                className="rounded-[10px] border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm">
                {dsLinhVuc.map((lv) => <option key={lv.slug} value={lv.slug}>{lv.ten}</option>)}
              </select>
            </label>
          </div>
          {/* Tra từ điển: thấy MỌI nghĩa rồi tự chọn, thay vì để máy chọn hộ */}
          <div className="space-y-2 rounded-[12px] border border-[var(--border)] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <input value={traTu} onChange={(e) => setTraTu(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") traCuu(); }}
                placeholder="tra một từ (vd: stroke)"
                className="min-w-[160px] flex-1 rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm" />
              <button type="button" onClick={() => traCuu()} disabled={traDangChay || !traTu.trim()}
                className="rounded-[10px] border border-[var(--border)] px-4 py-2 text-sm hover:bg-[var(--muted)] disabled:opacity-50">
                {traDangChay ? "Đang tra…" : "Tra từ điển"}
              </button>
            </div>
            {traKq && !traKq.co_tu_dien && (
              <p className="text-xs text-[var(--muted-foreground)]">
                Chưa cài từ điển cho tiếng này — hiện chỉ có Anh–Việt, cài bằng
                <code className="mx-1">scripts/tai_tu_dien.py</code> trên máy chủ.
                Nhật/Trung/Hàn thì bật Google Dịch ở khối bên trên là tra được.
              </p>
            )}
            {traKq && traKq.co_tu_dien && traKq.nghia.length === 0 && !traKq.google && (
              <p className="text-xs text-[var(--muted-foreground)]">Không có từ này trong từ điển.</p>
            )}
            {traKq && traKq.nghia.length === 0 && traKq.google && (
              <div className="flex items-start gap-2 text-sm">
                <div className="flex-1">
                  <span className="text-[var(--muted-foreground)]">Google dịch </span>
                  {traKq.google}
                  <div className="text-xs text-[var(--muted-foreground)]">
                    Bản dịch máy, không phải mục từ điển — chỉ có một nghĩa và
                    không kèm ví dụ.
                  </div>
                </div>
                <button type="button" onClick={() => dungNghia(traKq.tu, traKq.google || "")}
                  className="shrink-0 rounded-[8px] border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--muted)]">
                  Dùng nghĩa này
                </button>
              </div>
            )}
            {traKq && traKq.nghia.length > 0 && (
              <div className="space-y-1">
                <div className="text-sm">
                  <b>{traKq.tu}</b>
                  {traKq.ipa && <span className="ml-2 text-[var(--muted-foreground)]">{traKq.ipa}</span>}
                  {traKq.goc && (
                    <span className="ml-2 text-xs text-[var(--muted-foreground)]">
                      (tra theo dạng gốc của &quot;{traKq.goc}&quot;)
                    </span>
                  )}
                </div>
                {traKq.nghia.map((n, i) => (
                  <div key={i} className="flex items-start gap-2 border-t border-[var(--border)] pt-1 text-sm">
                    <div className="flex-1">
                      {n.tu_loai && <span className="text-[var(--muted-foreground)]">{n.tu_loai} </span>}
                      {n.vi}
                      {n.vi_du && (
                        <div className="text-xs italic text-[var(--muted-foreground)]">{n.vi_du}</div>
                      )}
                    </div>
                    <button type="button" onClick={() => dungNghia(traKq.tu, n.vi)}
                      className="shrink-0 rounded-[8px] border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--muted)]">
                      Dùng nghĩa này
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input value={suaTerm} onChange={(e) => setSuaTerm(e.target.value)}
              placeholder="từ gốc (vd: cache)"
              className="min-w-[160px] flex-1 rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm" />
            <span className="text-[var(--muted-foreground)]">→</span>
            <input value={suaVi} onChange={(e) => setSuaVi(e.target.value)}
              placeholder="từ Việt đúng (vd: bộ nhớ đệm)"
              className="min-w-[160px] flex-1 rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm" />
            <button type="button" onClick={luuSua}
              className="rounded-[10px] bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800">
              Lưu
            </button>
          </div>
          {suaMsg && <p className="text-xs">{suaMsg}</p>}
          {Object.keys(dsSua).length > 0 && (
            <div className="space-y-2 rounded-[12px] bg-[var(--muted)] p-3">
              {Object.entries(dsSua).map(([lv, cap]) => (
                <div key={lv} className="space-y-1">
                  <div className="text-xs font-medium text-[var(--muted-foreground)]">{tenLinhVuc(lv)}</div>
                  {Object.entries(cap).map(([term, vi]) => (
                    <div key={term} className="flex items-center gap-2 text-sm">
                      <span className="flex-1"><b>{term}</b> → {vi}</span>
                      <button type="button" onClick={() => xoaSua(lv, term)}
                        className="rounded px-1.5 text-[var(--muted-foreground)] hover:text-red-600" title="Xóa">
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
          {/* Kho thuật ngữ ĐANG DÙNG của lĩnh vực này + nhờ AI soát. Đây là chỗ
              người dùng THẤY máy tự học được gì; không thấy thì không tự phát
              hiện được từ dịch sai, mà một từ học sai kéo lệch mọi bản dịch sau. */}
          <div className="space-y-2 rounded-[12px] border border-[var(--border)] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">
                Kho thuật ngữ — {tenLinhVuc(suaLinhVuc)} ({dsKho.length})
              </span>
              <button type="button" onClick={soatKho} disabled={dangSoat || !dsKho.length}
                className="ml-auto rounded-[10px] border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--muted)] disabled:opacity-50">
                {dangSoat ? "AI đang soát…" : "🔎 Nhờ AI soát"}
              </button>
            </div>

            {deXuat !== null && deXuat.length > 0 && (
              <div className="space-y-2 rounded-[10px] bg-amber-500/10 p-2">
                {deXuat.map((d) => (
                  <div key={d.term} className="space-y-0.5 border-b border-[var(--border)] pb-2 last:border-0 last:pb-0">
                    <div className="text-sm">
                      <b>{d.term}</b>: <span className="line-through opacity-60">{d.hien_tai}</span>
                      {" → "}<b>{d.de_xuat}</b>
                    </div>
                    {d.ly_do && (
                      <div className="text-xs text-[var(--muted-foreground)]">{d.ly_do}</div>
                    )}
                    <div className="flex gap-2 pt-0.5">
                      <button type="button" onClick={() => nhanDeXuat(d)}
                        className="rounded-[8px] bg-slate-900 px-2.5 py-1 text-xs text-white hover:bg-slate-800">
                        Nhận
                      </button>
                      <button type="button"
                        onClick={() => setDeXuat((c) => (c || []).filter((x) => x.term !== d.term))}
                        className="rounded-[8px] border border-[var(--border)] px-2.5 py-1 text-xs hover:bg-[var(--muted)]">
                        Bỏ qua
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {dsKho.length === 0 ? (
              <p className="text-xs text-[var(--muted-foreground)]">
                Lĩnh vực này chưa có thuật ngữ nào. Máy sẽ tự học khi bạn lồng tiếng
                một video thuộc lĩnh vực đó.
              </p>
            ) : (
              <div className="max-h-64 space-y-1 overflow-y-auto">
                {dsKho.map((m) => (
                  <div key={m.term} className="flex items-center gap-2 text-sm">
                    <span className={
                      m.nguon === "sua" ? "shrink-0 rounded bg-emerald-500/15 px-1.5 text-[10px] text-emerald-600"
                      : m.nguon === "hoc" ? "shrink-0 rounded bg-sky-500/15 px-1.5 text-[10px] text-sky-600"
                      : "shrink-0 rounded bg-[var(--muted)] px-1.5 text-[10px] text-[var(--muted-foreground)]"}>
                      {m.nguon === "sua" ? "bạn sửa" : m.nguon === "hoc" ? "máy học" : "chuẩn"}
                    </span>
                    <span className="flex-1"><b>{m.term}</b> → {m.vi}</span>
                    <button type="button" onClick={() => { setSuaTerm(m.term); setSuaVi(m.vi); }}
                      className="shrink-0 rounded px-1.5 text-xs text-[var(--muted-foreground)] hover:text-slate-900"
                      title="Đổ xuống ô sửa bên dưới">
                      sửa
                    </button>
                    {m.nguon === "hoc" && (
                      <button type="button" onClick={() => xoaHoc(m.term)}
                        className="shrink-0 rounded px-1.5 text-[var(--muted-foreground)] hover:text-red-600"
                        title="Xoá mục máy tự học — lượt sau có thể học lại">
                        ×
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
            <p className="text-xs text-[var(--muted-foreground)]">
              <b>chuẩn</b> = từ điển dựng sẵn · <b>máy học</b> = máy tự chắt lọc khi lồng
              tiếng · <b>bạn sửa</b> = bạn tự đặt, thắng cả hai. Nút <b>Nhờ AI soát</b> đọc
              phần máy học rồi chỉ ra chỗ nào sai nghĩa hay dịch thô — chỉ đề xuất, nhận
              hay không là quyền bạn.
            </p>
          </div>

          <p className="text-xs text-[var(--muted-foreground)]">
            Sửa ở đây <b>thắng cả từ điển gốc</b>, có hiệu lực ngay lượt dịch sau. Nhập
            <b> từ gốc</b> ở tiếng nguồn (vd tiếng Anh &quot;cache&quot;), không phải bản dịch —
            hệ thống sẽ tự thay đúng từ Việt anh đặt mỗi khi gặp từ đó trong lĩnh vực này.
          </p>
        </div>
      </details>

      {/* Dán chữ hoặc link */}
      <div className="space-y-3 rounded-[16px] border border-[var(--border)] p-4">
        <textarea value={chu} onChange={(e) => setChu(e.target.value)} rows={5} disabled={dangChay}
          placeholder="Dán chữ cần dịch, hoặc link YouTube có phụ đề để dịch…"
          className="w-full resize-y rounded-[12px] border border-[var(--border)] bg-transparent p-3 text-sm outline-none focus:border-slate-400" />
        <div className="flex flex-wrap items-center justify-end gap-2">
          {chu.trim().length > GOOGLE_TRAN_KY_TU && (
            <span className="mr-auto text-xs text-[var(--muted-foreground)]">
              Google Dịch chỉ nhận ~{GOOGLE_TRAN_KY_TU} ký tự đầu — phần còn lại phải dán tay.
            </span>
          )}
          <button type="button" onClick={() => moGoogle("translate")} disabled={!chu.trim()}
            className="rounded-[12px] border border-[var(--border)] px-4 py-2.5 text-[14px] hover:bg-[var(--muted)] disabled:opacity-50"
            title="Mở tab mới sang translate.google.com với nội dung điền sẵn (dùng cho tiếng máy dịch trong stack chưa có)">
            Mở trên Google Dịch
          </button>
          <button type="button" onClick={dichChu} disabled={dangChay || !chu.trim()}
            className="rounded-[12px] bg-slate-900 px-6 py-2.5 text-[14px] font-medium text-white hover:bg-slate-800 disabled:opacity-50">
            Dịch chữ / link
          </button>
        </div>
      </div>

      {/* Tải tệp từ máy */}
      <div className="space-y-3 rounded-[16px] border border-[var(--border)] p-4"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f && !dangChay) chonTepMoi(f); }}>
        <button type="button" onClick={() => chonTep.current?.click()} disabled={dangChay}
          className="flex w-full flex-col items-center gap-2 rounded-[12px] border border-dashed border-[var(--border)] p-6 text-sm text-[var(--muted-foreground)] hover:border-slate-400">
          <Upload className="size-5" />
          {tep ? (
            <span className="text-[var(--foreground)]">{tep.name} • {(tep.size / 1024 / 1024).toFixed(1)}MB</span>
          ) : (
            <span>Bấm chọn hoặc kéo thả — video/âm thanh (≤4GB, ≤150 phút — phim 2h nghe mất ~1,5h), phụ đề .srt/.vtt (dịch vài chục giây), ảnh, PDF/Word/Excel…</span>
          )}
        </button>
        <input ref={chonTep} type="file" accept={DUOI_NHAN} className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) chonTepMoi(f); e.target.value = ""; }} />
        {tep && DUOI_NGHE.some((d) => tep.name.toLowerCase().endsWith(d)) && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
            <span className="text-[var(--muted-foreground)]">Kết quả:</span>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="kieu-ra" checked={kieuRa === "phu-de"}
                onChange={() => setKieuRa("phu-de")} disabled={dangChay} />
              Phụ đề (.srt, có mốc thời gian)
            </label>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="kieu-ra" checked={kieuRa === "chu"}
                onChange={() => setKieuRa("chu")} disabled={dangChay} />
              Bản chữ (lời thoại đã dịch)
            </label>
            {laVideo && (
              <label className="flex cursor-pointer items-center gap-1.5">
                <input type="radio" name="kieu-ra" checked={kieuRa === "long-tieng"}
                  onChange={() => setKieuRa("long-tieng")} disabled={dangChay} />
                <Volume2 className="size-4" /> Lồng tiếng video
              </label>
            )}
          </div>
        )}
        {kieuRa === "long-tieng" && laVideo && (
          <div className="space-y-2 rounded-[12px] bg-[var(--muted)] p-3">
            <label htmlFor="giong-long-tieng" className="block text-sm font-medium">
              Giọng dùng cho toàn video
            </label>
            <select id="giong-long-tieng" value={giong}
              onChange={(e) => setGiong(e.target.value)} disabled={dangChay || dangTaiGiong}
              className="w-full rounded-[10px] border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm">
              {dangTaiGiong && <option value="">Đang đọc danh sách giọng…</option>}
              {!dangTaiGiong && !cacGiong.some((v) => v.downloaded) && (
                <option value="">Chưa có model giọng phù hợp đã tải</option>
              )}
              {cacGiong.map((v) => (
                <option key={v.id} value={v.id} disabled={!v.downloaded}>
                  {v.label}{v.downloaded ? "" : " · chưa tải"}
                </option>
              ))}
            </select>
            <p className="text-xs text-[var(--muted-foreground)]">
              Track âm thanh trộn gốc không được dùng; TTS được trộn với stem nhạc/hiệu ứng
              do model ước lượng. Cảnh âm thanh chồng lấn có thể còn rò giọng, và giọng hát
              trong nhạc có thể bị giảm. Bản này dùng một giọng cho mọi nhân vật và xuất kèm
              <code className="mx-1">prosody.json</code> để giữ nhịp, cao độ và năng lượng từng câu.
              Khi chưa có diarization, người nói được ghi là <code>UNKNOWN</code> để không gán nhầm giới tính.
            </p>
            {tachAmSanSang === false && (
              <p className="text-xs text-red-600">
                Máy tách lời chưa sẵn sàng: {loiTachAm || "chưa cấu hình TACH_AM_URL_GPU"}.
                Hệ thống không tạo video nếu chưa có stem nhạc/hiệu ứng hợp lệ.
              </p>
            )}
          </div>
        )}
        <div className="flex items-center justify-end gap-3">
          <button type="button" onClick={dichTep}
            disabled={dangChay || !tep || (kieuRa === "long-tieng" && (dangTaiGiong || !giong || tachAmSanSang === false))}
            className="rounded-[12px] bg-slate-900 px-6 py-2.5 text-[14px] font-medium text-white hover:bg-slate-800 disabled:opacity-50">
            {kieuRa === "long-tieng" ? "Dịch và lồng tiếng" : "Dịch tệp"}
          </button>
        </div>
      </div>

      {/* Trạng thái + kết quả */}
      {dangChay && (() => {
        // MỘT thanh cho cả hai chặng: đẩy tệp lên (đo được từng byte) rồi tới
        // việc chạy trên máy chủ. Hai chỉ báo rời nhau chỉ làm người xem phải
        // tự đoán cái nào đang nói về mình.
        const dangTai = tienDo >= 0;
        const pt = dangTai ? tienDo : phanTram;
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
              <LoaderCircle className="size-4 animate-spin" />
              <span className="flex-1">
                {dangTai ? "đang tải tệp lên máy chủ…" : (buoc || "đang xử lý…")}
              </span>
              {pt !== null && <span className="tabular-nums">{pt}%</span>}
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--border)]">
              {pt === null ? (
                // Giai đoạn không đo được: vệt nhấp nháy, cố ý KHÔNG hiện số.
                <div className="h-full w-1/3 animate-pulse rounded-full bg-slate-900 dark:bg-slate-100" />
              ) : (
                <div className="h-full rounded-full bg-slate-900 transition-[width] duration-500 dark:bg-slate-100"
                  style={{ width: `${pt}%` }} />
              )}
            </div>
          </div>
        );
      })()}
      {loi && <div className="rounded-[12px] bg-red-50 p-3 text-sm text-red-600 dark:bg-red-950/40 dark:text-red-400">{loi}</div>}

      {ketQua && (
        <div className="space-y-3 rounded-[16px] border border-[var(--border)] p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <FileText className="size-4" />
            {ketQua.bao_cao || `Bản dịch (${ketQua.nguon} → ${ketQua.dich})`}
          </div>
          {ketQua.tep?.map((t) => (
            <a key={t.url} href={`${goc}${t.url}`} download={t.ten}
              className="flex w-fit items-center gap-2 rounded-[10px] border border-[var(--border)] px-4 py-2 text-sm hover:border-slate-400">
              <Download className="size-4" />{t.ten}
            </a>
          ))}
          {ketQua.kieu === "phu-de" && (
            <p className="text-xs text-[var(--muted-foreground)]">
              Bản <code>phu-de-tren</code> hiện chữ ở mép trên màn hình — dùng khi video đã có chữ in sẵn ở dưới.
            </p>
          )}
          {ketQua.kieu === "long-tieng" && (
            <p className="text-xs text-[var(--muted-foreground)]">
              Video dùng giọng <b>{ketQua.voice}</b>; track trộn gốc không được dùng,
              TTS được ghép với stem nhạc/hiệu ứng do model tách.
              Tệp prosody đi kèm lưu nhịp và tông tương đối để tái dựng hoặc đổi giọng sau này.
            </p>
          )}
          {ketQua.tudien && ketQua.tudien.nghia.length > 0 && (
            <div className="space-y-1 rounded-[12px] border border-[var(--border)] p-3">
              <div className="text-sm">
                <b>{ketQua.tudien.tu}</b>
                {ketQua.tudien.ipa && <span className="ml-2 text-[var(--muted-foreground)]">{ketQua.tudien.ipa}</span>}
                {ketQua.tudien.goc && (
                  <span className="ml-2 text-xs text-[var(--muted-foreground)]">
                    (dạng gốc của &quot;{ketQua.tudien.goc}&quot;)
                  </span>
                )}
                <span className="ml-2 text-xs text-[var(--muted-foreground)]">— tra từ điển, {ketQua.tudien.nghia.length} nghĩa</span>
              </div>
              {ketQua.tudien.nghia.map((n, i) => (
                <div key={i} className="border-t border-[var(--border)] pt-1 text-sm">
                  {n.tu_loai && <span className="text-[var(--muted-foreground)]">{n.tu_loai} </span>}
                  {n.vi}
                  {n.vi_du && <div className="text-xs italic text-[var(--muted-foreground)]">{n.vi_du}</div>}
                </div>
              ))}
              <p className="pt-1 text-xs text-[var(--muted-foreground)]">
                Từ đơn thì từ điển đáng tin hơn máy dịch. Bản máy dịch bên dưới chỉ để tham khảo.
              </p>
            </div>
          )}
          {ketQua.text && (
            <div className="relative">
              {ketQua.tudien && ketQua.tudien.nghia.length > 0 && (
                <div className="mb-1 text-xs text-[var(--muted-foreground)]">Bản máy dịch (tham khảo)</div>
              )}
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-[12px] bg-[var(--muted)] p-3 text-sm">{ketQua.text}</pre>
              <button type="button" onClick={chepKetQua} title="Chép kết quả"
                className="absolute right-2 top-2 rounded-[8px] border border-[var(--border)] bg-[var(--background)] p-1.5 hover:border-slate-400">
                {daChep ? <Check className="size-4 text-emerald-600" /> : <Copy className="size-4" />}
              </button>
            </div>
          )}
          {googleBat && ketQua.kieu === "chu" && (
            <div className="space-y-2">
              <button type="button" onClick={xemGoogle} disabled={googleDangChay}
                className="rounded-[10px] border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--muted)] disabled:opacity-50">
                {googleDangChay ? "Đang hỏi Google…" : "Xem bản Google để đối chiếu"}
              </button>
              {googleLoi && <p className="text-xs text-red-600">{googleLoi}</p>}
              {googleKq && (
                <div>
                  <div className="text-xs text-[var(--muted-foreground)]">Bản của Google</div>
                  <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-[12px] bg-[var(--muted)] p-3 text-sm">{googleKq}</pre>
                </div>
              )}
            </div>
          )}
          {ketQua.goc && (
            <details>
              <summary className="cursor-pointer text-sm text-[var(--muted-foreground)]">Chữ đọc được trong ảnh (đối chiếu)</summary>
              <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-[12px] bg-[var(--muted)] p-3 text-sm">{ketQua.goc}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

const NGON_NGU: Record<string, string> = {
  vi: "Tiếng Việt", en: "Tiếng Anh", zh: "Tiếng Trung", ja: "Tiếng Nhật", ko: "Tiếng Hàn",
};

/** Đàm thoại 2 chiều bấm-nói-thả: bấm mic bên tiếng nào là máy nghe tiếng đó
 *  rồi dịch sang bên kia. Không streaming — mỗi lượt nói là một lần gửi. */
function DamThoai() {
  const [tiengA, setTiengA] = useState("vi");
  const [tiengKia, setTiengKia] = useState("en");
  const [docTts, setDocTts] = useState(true);
  const [dangGhi, setDangGhi] = useState("");        // "" | mã tiếng đang ghi
  const [dangMo, setDangMo] = useState("");          // đang xin quyền/mở mic
  const [dangXuLy, setDangXuLy] = useState(false);
  const [loi, setLoi] = useState("");
  const [luot, setLuot] = useState<{ ben: string; goc: string; dich: string }[]>([]);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function nhanMic(lang: string) {
    setLoi("");
    if (dangGhi) {
      mediaRef.current?.stop();
      return;
    }
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setLoi("Trình duyệt không hỗ trợ micro (cần HTTPS hoặc mở qua domain).");
      return;
    }
    setDangMo(lang);   // mở mic mất ~nửa giây — nói sớm là mất chữ đầu
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      let mime = "";
      for (const c of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"]) {
        if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported?.(c)) { mime = c; break; }
      }
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setDangGhi("");
        const type = mr.mimeType || mime || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        if (blob.size < 800) return;   // bấm nhầm, chưa nói gì
        setDangXuLy(true);
        try {
          const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
          const khac = lang === tiengA ? tiengKia : tiengA;
          const fd = new FormData();
          fd.append("tieng", blob, `mic.${ext}`);
          fd.append("lang_noi", lang);
          fd.append("lang_kia", khac);
          fd.append("tts", docTts ? "1" : "0");
          const res = await request.post("/api/dich/noi", fd);
          const d = res.data as { goc: string; dich: string; tieng: string | null };
          if (d.goc) {
            setLuot((prev) => [...prev, { ben: lang, goc: d.goc, dich: d.dich }]);
            if (d.tieng) void new Audio(`data:audio/wav;base64,${d.tieng}`).play().catch(() => {});
          } else {
            setLoi("Không nghe ra chữ nào — thử nói lại gần mic hơn.");
          }
        } catch (e) {
          setLoi(layLoi(e));
        }
        setDangXuLy(false);
      };
      mr.start(250);
      mediaRef.current = mr;
      setDangMo("");
      setDangGhi(lang);
    } catch {
      setDangMo("");
      setLoi("Không truy cập được micro — kiểm tra quyền Micro của trình duyệt (ổ khóa cạnh URL).");
    }
  }

  const hai_ben = [tiengA, tiengKia];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          Phiên dịch giữa:
          <select value={tiengA} onChange={(e) => { setTiengA(e.target.value); setLuot([]); }}
            disabled={!!dangGhi || dangXuLy}
            className="rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
            {["vi", "en", "zh", "ja", "ko"].filter((m) => m !== tiengKia).map((m) => (
              <option key={m} value={m}>{NGON_NGU[m]}</option>
            ))}
          </select>
          <span className="text-[var(--muted-foreground)]">↔</span>
          <select value={tiengKia} onChange={(e) => { setTiengKia(e.target.value); setLuot([]); }}
            disabled={!!dangGhi || dangXuLy}
            className="rounded-[10px] border border-[var(--border)] bg-transparent px-3 py-2 text-sm">
            {["vi", "en", "zh", "ja", "ko"].filter((m) => m !== tiengA).map((m) => (
              <option key={m} value={m}>{NGON_NGU[m]}</option>
            ))}
          </select>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-sm">
          <input type="checkbox" checked={docTts} onChange={(e) => setDocTts(e.target.checked)} />
          Đọc bản dịch thành tiếng
        </label>
        {dangXuLy && (
          <span className="flex items-center gap-1.5 text-sm text-[var(--muted-foreground)]">
            <LoaderCircle className="size-4 animate-spin" /> đang nghe và dịch…
          </span>
        )}
      </div>
      {loi && <div className="rounded-[12px] bg-red-50 p-3 text-sm text-red-600 dark:bg-red-950/40 dark:text-red-400">{loi}</div>}

      <div className="grid gap-4 sm:grid-cols-2">
        {hai_ben.map((lang) => (
          <div key={lang} className="flex min-h-72 flex-col rounded-[16px] border border-[var(--border)] p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="font-medium">{NGON_NGU[lang]}</span>
              <button type="button" onClick={() => nhanMic(lang)}
                disabled={dangXuLy || !!dangMo || (!!dangGhi && dangGhi !== lang)}
                className={cn(
                  "flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium text-white disabled:opacity-40",
                  dangGhi === lang ? "animate-pulse bg-red-600 hover:bg-red-700" : "bg-slate-900 hover:bg-slate-800")}>
                <Mic className="size-4" />
                {dangGhi === lang ? "Bấm để dừng"
                  : dangMo === lang ? "Đang mở mic…" : "Bấm, chờ ĐỎ, rồi nói"}
              </button>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto text-sm">
              {luot.length === 0 && (
                <p className="text-[var(--muted-foreground)]">
                  Bấm mic bên {NGON_NGU[lang]} khi người nói dùng {NGON_NGU[lang].toLowerCase()}…
                </p>
              )}
              {luot.map((t, i) =>
                t.ben === lang ? (
                  <p key={i} className="rounded-[10px] bg-[var(--muted)] p-2">🎙 {t.goc}</p>
                ) : (
                  <p key={i} className="rounded-[10px] border border-[var(--border)] p-2">→ {t.dich}</p>
                ))}
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-[var(--muted-foreground)]">
        Mỗi lượt nói tối đa 90 giây. Máy nghe theo tiếng của nút mic đã bấm — không đoán tiếng, nên
        hai người cứ thay nhau bấm đúng bên mình. Giọng đọc: Việt (NghiTTS), Anh (Kokoro),
        Trung (Kokoro đa ngữ), Nhật + Hàn (Supertonic) — thiếu model giọng nào thì bên đó chỉ hiện chữ.
      </p>
    </div>
  );
}

export default function DichPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  const [tab, setTab] = useState<"dich" | "dam-thoai">("dich");

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6 pb-2">
      <div className="flex gap-2">
        <button type="button" onClick={() => setTab("dich")}
          className={cn("flex items-center gap-2 rounded-[12px] px-4 py-2 text-sm font-medium",
            tab === "dich" ? "bg-slate-900 text-white" : "border border-[var(--border)] hover:border-slate-400")}>
          <Languages className="size-4" /> Dịch
        </button>
        <button type="button" onClick={() => setTab("dam-thoai")}
          className={cn("flex items-center gap-2 rounded-[12px] px-4 py-2 text-sm font-medium",
            tab === "dam-thoai" ? "bg-slate-900 text-white" : "border border-[var(--border)] hover:border-slate-400")}>
          <MessagesSquare className="size-4" /> Đàm thoại
        </button>
      </div>
      {tab === "dich" ? <DichPageContent /> : <DamThoai />}
    </div>
  );
}
