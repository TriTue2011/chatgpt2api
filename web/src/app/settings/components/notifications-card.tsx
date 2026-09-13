"use client";

/**
 * NotificationsCard — MỘT nơi duy nhất bật/tắt và chọn kênh cho TỪNG thông báo.
 *
 * Chủ máy chốt 13/09/2026: "gom toàn bộ các cài đặt thông báo về 1 chỗ, cài đặt
 * độc lập mỗi thông báo", "toàn bộ các thông báo theo cài đặt webui, không mặc
 * định", "cài đặt thông báo ở tab cũ xóa đi tránh xung đột", và nói rõ là "kể
 * cả thông báo khoá cửa hay tương tự".
 *
 * VÌ SAO KHÔNG DÙNG `saveConfig` NHƯ CÁC THẺ KHÁC: `store.saveConfig` POST
 * NGUYÊN CẢ config lên `/api/settings`, nên thẻ nào nạp dữ liệu cũ sẽ ghi đè
 * phần của thẻ khác. Chuyện đó đã xảy ra thật và được ghi lại thành bẫy #9 của
 * kho này (mất `du_doan.kenh_nhan`). Trang gom cài đặt về một chỗ mà lặp lại
 * đúng cái bẫy ấy thì vô nghĩa — nên ở đây ghi qua endpoint HẸP
 * `POST /api/thong-bao/luu`, chỉ đụng đúng mục `thong_bao`.
 *
 * Danh sách kênh lấy từ «Lọc thread» đang có sẵn trong config (`thread_filters`
 * + `thread_filter_meta`) — cùng nguồn mà thẻ Email/Lịch đang dùng, nên không
 * đẻ thêm một danh sách kênh thứ hai để lệch nhau.
 */

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import { useSettingsStore } from "../store";
import { request } from "@/lib/request";

type SuKien = {
  khoa: string;
  nhan: string;
  mo_ta: string;
  nhom: string;
  bat: boolean;
  kenh: string[];
};

type DapAn = { ok?: boolean; su_kien?: SuKien[]; error?: string };

/** Tiền tố nền tảng → chữ người đọc được. Khoá kênh có dạng `plat:bot:chat`,
 *  và `plat` chỉ nhận ba giá trị này (xem `services/digest.parse_target`). */
const TEN_NEN = {
  tg: "Telegram",
  zalo: "Zalo Bot",
  zalop: "Zalo cá nhân",
} as const;

export function NotificationsCard() {
  const config = useSettingsStore((s) => s.config);
  const [ds, setDs] = useState<SuKien[]>([]);
  const [dangTai, setDangTai] = useState(true);
  const [dangLuu, setDangLuu] = useState(false);
  const [loi, setLoi] = useState("");
  const [tin, setTin] = useState<Record<string, string>>({});
  // Danh bạ kênh của máy chủ: khoá `plat|bot|thread` → {tên thread, tên bot}.
  // `channel_contacts.bot_label()` đã tính sẵn cả chuỗi lùi (nhãn trong config
  // → số điện thoại/displayName của Zalo cá nhân → tên lấy qua getMe → mã
  // trần), nên lấy về dùng thay vì tự ghép lại ở đây.
  //
  // `null` = CHƯA tải xong. Phải tách khỏi `{}` (tải xong mà rỗng): nếu không,
  // mọi ô sẽ nháy cảnh báo "thiếu tên" trong lúc chờ mạng — cảnh báo giả.
  const [danhBa, setDanhBa] = useState<
    Record<string, { name?: string; bot_label?: string }> | null
  >(null);
  // Nền tảng mà lượt tải danh bạ hỏng — để cảnh báo không khuyên nhầm "đặt tên
  // bot" khi thật ra là chính lượt tra tên không chạy.
  const [nenLoi, setNenLoi] = useState<string[]>([]);

  // Kênh chọn được = thread đã đặt trong «Lọc thread» (đã có tên sẵn).
  const tf = (config as Record<string, unknown> | null)?.thread_filters as
    Record<string, unknown> | undefined;
  const tfMeta = (config as Record<string, unknown> | null)?.thread_filter_meta as
    Record<string, { name?: string }> | undefined;
  // Nhãn NGẮN, tên lấy từ DANH BẠ MÁY CHỦ chứ không tự ghép.
  //
  // Bản đầu in nguyên khoá (`zalop:4757…:6643…`, dài 28–45 ký tự) nên trên
  // điện thoại tràn hết màn hình. Bản thứ hai ghép "tên · nền tảng" — ngắn
  // nhưng phân biệt sai trục: ba kênh cùng tên "Đại ca" nằm ở hai bot Zalo
  // khác nhau, "Zalo Bot" không tách nổi chúng.
  //
  // Đúng thứ cần là CHỦ SỞ HỮU thật của kênh, mà máy chủ đã tính sẵn:
  // `channel_contacts.bot_label()` lùi dần nhãn-config → số điện thoại/tên
  // Zalo cá nhân → getMe → mã trần, còn `list_directory` trả kèm tên thread.
  // Đo 13/09/2026: danh bạ phủ ĐỦ 11/11 kênh đang dùng.
  type Kenh = {
    value: string; label: string; plat: string;
    thieuTen: boolean; thieuBot: boolean; khongCo: boolean;
  };
  const kenhCo: Kenh[] = (() => {
    const tho = Object.keys(tf || {}).map((k) => {
      const phan = k.split(":");
      const plat = phan[0] || "";
      const bot = phan[1] || "";
      const chat = phan.slice(2).join(":");
      // Ghép NGUYÊN VĂN, không thử dạng gần đúng. `list_directory` bước 3 đưa
      // mọi khoá «Lọc thread» vào danh bạ với `thread_id = parts[2:].join(":")`
      // — đúng chuỗi `chat` ở trên — nên tải được danh bạ là khớp. Đo từng
      // khoá 13/09/2026: 11/11 khớp nguyên văn. Bản trước thử thêm "bỏ #topic":
      // với `…5521#638` ("Tiểu Hồng") nó ra dòng nhóm cha "chatgpt" — tên SAI
      // mà trông hợp lý. Không khớp thì thà cảnh báo còn hơn.
      const r = danhBa?.[`${plat}|${bot}|${chat}`];
      const ten = (r?.name || "").trim() || (tfMeta?.[k]?.name || "").trim();
      const nguonThat = (r?.bot_label || "").trim();
      // Tách HAI loại thiếu vì cách chữa khác nhau: thiếu tên thread thì chủ
      // máy tự đặt được, thiếu tên bot thì thường là bot/máy chủ đang hỏng.
      // `bot_label` lúc bí trả về MÃ TRẦN, nên mã trần nghĩa là "chưa có tên".
      // Danh bạ chưa tải xong thì CHƯA biết — không kết luận thiếu.
      const xong = danhBa !== null;
      const thieuTen = xong && !ten;
      const thieuBot = xong && (!nguonThat || nguonThat === bot);
      // Danh bạ tải được mà KHÔNG có dòng của kênh: bot vẫn có thể có tên, cái
      // thiếu là chính dòng danh bạ — khuyên "Lấy tên bot" ở đây là chỉ sai chỗ.
      const khongCo = xong && !r;
      const nen = TEN_NEN[plat as keyof typeof TEN_NEN] || plat || "?";
      return {
        value: k,
        plat,
        ten: ten || "(chưa đặt tên)",
        nguon: nguonThat && nguonThat !== bot ? nguonThat : nen,
        chat,
        thieuTen,
        thieuBot,
        khongCo,
      };
    });
    const dem = new Map<string, number>();
    for (const x of tho) {
      const kh = `${x.ten}|${x.nguon}`;
      dem.set(kh, (dem.get(kh) || 0) + 1);
    }
    return tho.map((x) => {
      // Thread trùng tên với chính bot của nó (đo thật: thread "chatgpt" trên
      // bot nhãn "chatgpt") thì in một lần — "chatgpt · chatgpt" không thêm
      // thông tin nào, chỉ tốn chỗ.
      const goc = x.ten === x.nguon ? x.ten : `${x.ten} · ${x.nguon}`;
      const nhan = (dem.get(`${x.ten}|${x.nguon}`) || 0) > 1
        ? `${goc} …${x.chat.slice(-4)}`
        : goc;
      return {
        value: x.value,
        plat: x.plat,
        // Dấu ⚠ nằm NGAY TRÊN Ô chứ không chỉ trong `title`: chủ máy dùng điện
        // thoại, mà điện thoại không có rê chuột để hiện `title`.
        label: x.thieuTen || x.thieuBot ? `⚠ ${nhan}` : nhan,
        thieuTen: x.thieuTen,
        thieuBot: x.thieuBot,
        khongCo: x.khongCo,
      };
    });
  })();
  const kenhThieu = kenhCo.filter((k) => k.thieuTen || k.thieuBot);

  const nap = useCallback(async () => {
    setDangTai(true);
    setLoi("");
    try {
      // `request` là axios: kết quả nằm ở `.data`, KHÔNG phải ở chính đối
      // tượng trả về. Bản đầu đọc thẳng `r.ok` nên luôn `undefined` → thẻ báo
      // "Không đọc được danh sách thông báo" trong khi máy chủ trả đủ 14 dòng.
      // `tsc` không bắt được vì chính cái ép kiểu `as DapAn` của tôi đã bịt
      // miệng nó. Mọi thẻ khác đều làm `const d = r.data as {...}`.
      const d = (await request.get("/api/thong-bao")).data as DapAn;
      if (d?.ok && Array.isArray(d.su_kien)) setDs(d.su_kien);
      else setLoi(d?.error || "Không đọc được danh sách thông báo");
    } catch (e) {
      setLoi(String(e));
    } finally {
      setDangTai(false);
    }
  }, []);

  useEffect(() => {
    void nap();
  }, [nap]);

  useEffect(() => {
    let huy = false;
    void (async () => {
      // Tra TÊN hỏng thì nhãn xấu đi, nhưng danh sách thông báo vẫn phải chạy
      // — đó mới là việc chính của trang này. Một nền tảng lỗi thì chỉ RIÊNG
      // nó mất tên, và được ghi lại để cảnh báo nói đúng nguyên nhân.
      const gom: Record<string, { name?: string; bot_label?: string }> = {};
      const loi: string[] = [];
      for (const plat of ["tg", "zalo", "zalop"]) {
        try {
          const d = (await request.get(
            `/api/channels/directory?platform=${plat}`)).data as {
              ok?: boolean;
              rows?: { bot_id?: string; thread_id?: string;
                       name?: string; bot_label?: string }[];
            };
          if (!d?.ok) {
            loi.push(plat);
            continue;
          }
          for (const r of d.rows || []) {
            const kh = `${plat}|${String(r.bot_id || "")}|${String(r.thread_id || "")}`;
            gom[kh] = { name: r.name, bot_label: r.bot_label };
          }
        } catch {
          loi.push(plat);
        }
      }
      if (!huy) {
        setNenLoi(loi);
        setDanhBa(gom);
      }
    })();
    return () => { huy = true; };
  }, []);

  const doi = (khoa: string, sua: Partial<SuKien>) =>
    setDs((cu) => cu.map((x) => (x.khoa === khoa ? { ...x, ...sua } : x)));

  const bamKenh = (sk: SuKien, kenh: string) => {
    const co = sk.kenh.includes(kenh);
    doi(sk.khoa, {
      kenh: co ? sk.kenh.filter((x) => x !== kenh) : [...sk.kenh, kenh],
    });
  };

  const luu = async () => {
    setDangLuu(true);
    setLoi("");
    try {
      const muc: Record<string, { bat: boolean; kenh: string[] }> = {};
      for (const x of ds) muc[x.khoa] = { bat: x.bat, kenh: x.kenh };
      const d = (await request.post("/api/thong-bao/luu", { muc })).data as DapAn;
      if (!d?.ok) setLoi(d?.error || "Lưu không được");
    } catch (e) {
      setLoi(String(e));
    } finally {
      setDangLuu(false);
    }
  };

  const guiThu = async (khoa: string) => {
    setTin((t) => ({ ...t, [khoa]: "đang gửi…" }));
    try {
      const d = (await request.post("/api/thong-bao/thu", { khoa })).data as
        { ok?: boolean; gui?: number; error?: string };
      setTin((t) => ({
        ...t,
        [khoa]: d?.ok ? `đã gửi tới ${d.gui} kênh` : `không gửi: ${d?.error || "?"}`,
      }));
    } catch (e) {
      setTin((t) => ({ ...t, [khoa]: String(e) }));
    }
  };

  const nhomDs = Array.from(new Set(ds.map((x) => x.nhom)));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Thông báo</CardTitle>
        <CardDescription>
          Mỗi thông báo bật/tắt và chọn kênh riêng. Chưa chọn kênh thì bot IM —
          không có mặc định ngầm nào cả. Kênh lấy từ «Lọc thread» ở tab Kênh chat.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {dangTai && <p className="text-sm text-muted-foreground">Đang tải…</p>}
        {loi && <p className="text-sm text-red-600">{loi}</p>}
        {!dangTai && kenhCo.length === 0 && (
          <p className="text-sm text-amber-600">
            Chưa có thread nào trong «Lọc thread» — vào Kênh chat → Lọc thread
            thêm nơi nhận trước, rồi quay lại đây chọn.
          </p>
        )}
        {/* Cảnh báo MỘT lần cho cả thẻ, không lặp dưới từng thông báo: cùng
            một kênh thiếu tên hiện ở mọi dòng, lặp 14 lần chỉ thành nhiễu. */}
        {kenhThieu.length > 0 && (
          <div className="text-sm text-amber-600 space-y-1">
            <p>⚠ {kenhThieu.length} kênh chưa lấy được tên:</p>
            <ul className="list-disc pl-5 text-xs space-y-0.5">
              {kenhThieu.map((k) => (
                <li key={k.value} className="break-all">
                  <span className="font-mono">{k.value}</span>
                  {nenLoi.includes(k.plat) ? (
                    ` — không tải được danh bạ ${TEN_NEN[k.plat as keyof typeof TEN_NEN] || k.plat}: tải lại trang; vẫn lỗi thì máy chủ đang hỏng.`
                  ) : k.khongCo ? (
                    " — danh bạ máy chủ chưa có kênh này: vừa sửa «Lọc thread» thì lưu xong tải lại trang."
                  ) : (
                    <>
                      {k.thieuTen && " — chưa có tên thread: đặt ở Kênh chat → Lọc thread."}
                      {k.thieuBot && (k.plat === "zalop"
                        ? " — máy chủ Zalo cá nhân không trả số điện thoại: kiểm tra tài khoản còn đăng nhập."
                        : " — bot chưa có tên: bấm «Lấy tên bot» ở Kênh chat; bấm không ra tên thì bot đã chết hoặc token sai.")}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {nhomDs.map((nhom) => (
          <div key={nhom} className="space-y-2">
            <h4 className="text-sm font-semibold">{nhom}</h4>
            {ds.filter((x) => x.nhom === nhom).map((sk) => (
              <div key={sk.khoa} className="rounded-md border p-3 space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={sk.bat}
                      onChange={(e) => doi(sk.khoa, { bat: e.target.checked })}
                    />
                    <span>
                      <span className="font-medium">{sk.nhan}</span>
                      <span className="block text-xs text-muted-foreground">
                        {sk.mo_ta}
                      </span>
                    </span>
                  </label>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void guiThu(sk.khoa)}
                  >
                    Gửi thử
                  </Button>
                </div>

                <div className="flex flex-wrap gap-1.5">
                  {kenhCo.map((k) => {
                    const chon = sk.kenh.includes(k.value);
                    return (
                      <button
                        key={k.value}
                        type="button"
                        onClick={() => bamKenh(sk, k.value)}
                        // Khoá đầy đủ để trong `title`: bấm giữ / rê chuột là
                        // xem được, mà không làm rộng ô. Kênh chưa tra ra tên
                        // thì nói thẳng lý do ở đây thay vì im lặng.
                        title={k.value}
                        className={
                          "max-w-full truncate rounded-full border px-2.5 py-0.5 text-xs " +
                          (chon
                            ? "border-transparent bg-primary text-primary-foreground"
                            : k.thieuTen || k.thieuBot
                              ? "border-amber-500 text-amber-700"
                              : "text-muted-foreground")
                        }
                      >
                        {k.label}
                      </button>
                    );
                  })}
                </div>

                {sk.bat && sk.kenh.length === 0 && (
                  <p className="text-xs text-amber-600">
                    Đang bật nhưng chưa chọn kênh — thông báo này sẽ không tới ai.
                  </p>
                )}
                {tin[sk.khoa] && (
                  <p className="text-xs text-muted-foreground">{tin[sk.khoa]}</p>
                )}
              </div>
            ))}
          </div>
        ))}

        <div className="flex items-center gap-2">
          <Button onClick={() => void luu()} disabled={dangLuu || dangTai}>
            {dangLuu ? "Đang lưu…" : "Lưu"}
          </Button>
          <Button variant="outline" onClick={() => void nap()} disabled={dangTai}>
            Tải lại
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
