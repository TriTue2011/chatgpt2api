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
  // Số điện thoại của từng tài khoản Zalo cá nhân. Chủ máy chốt 13/09/2026:
  // nhãn nên là tên thread + TÊN BOT, riêng Zalo cá nhân thì + SỐ ĐIỆN THOẠI —
  // vì cái mơ hồ thật sự là "bot nào / tài khoản nào", không phải "nền tảng
  // nào" (ba kênh cùng tên "Đại ca" nằm ở hai bot Zalo khác nhau).
  //
  // Số này KHÔNG có trong config, chỉ lấy được qua `/api/zalo-personal/accounts`
  // — endpoint đã có sẵn, nên không dựng nguồn thứ hai cho cùng một dữ liệu.
  const [soDt, setSoDt] = useState<Record<string, string>>({});

  // Kênh chọn được = thread đã đặt trong «Lọc thread» (đã có tên sẵn).
  const tf = (config as Record<string, unknown> | null)?.thread_filters as
    Record<string, unknown> | undefined;
  const tfMeta = (config as Record<string, unknown> | null)?.thread_filter_meta as
    Record<string, { name?: string }> | undefined;
  // Nhãn NGẮN. Bản đầu ghép nguyên khoá (`zalop:4757…:6643…`, đo được dài
  // 28–45 ký tự) nên trên điện thoại mỗi ô rộng hơn màn hình: tràn ra ngoài,
  // bị cắt cụt, 11 kênh × 14 dòng thành không dùng nổi (chủ máy gửi ảnh
  // 13/09/2026).
  //
  // Nhưng CHỈ TÊN thì sai: đo cùng ngày, tên "Đại ca" trùng ở BA kênh khác
  // nhau (một Zalo cá nhân, hai Zalo Bot) — chỉ hiện tên là không biết đang
  // tick cái nào. Nên ghép thêm nền tảng, và chỉ khi VẪN còn trùng mới thêm
  // bốn ký tự cuối mã phòng; thêm mã cho mọi ô là quay lại đúng cái vừa bỏ.
  // Tên bot lấy thẳng từ config — `zalo-personal-panel.tsx:293` đã duyệt đúng
  // hai khoá này, nên bám theo nếp sẵn có thay vì gọi thêm API.
  const nhanBot: Record<string, string> = (() => {
    const c = (config as Record<string, unknown> | null) || {};
    const ra: Record<string, string> = {};
    for (const khoa of ["telegram_bots", "zalo_bots"]) {
      for (const b of ((c[khoa] as Record<string, unknown>[]) || [])) {
        const id = String((b as { token?: string })?.token || "").split(":")[0].trim();
        const nhan = String((b as { label?: string })?.label || "").trim();
        if (id && nhan) ra[id] = nhan;
      }
    }
    return ra;
  })();

  const kenhCo: { value: string; label: string }[] = (() => {
    const tho = Object.keys(tf || {}).map((k) => {
      const phan = k.split(":");
      const plat = phan[0] || "";
      const bot = phan[1] || "";
      // Zalo cá nhân → số điện thoại của tài khoản; bot → tên bot chủ máy đặt.
      // Tra không ra (bot đã xoá, hoặc máy chủ Zalo cá nhân im) thì lùi về tên
      // nền tảng: thà chung chung còn hơn hiện mã máy dài không đọc nổi.
      const nguon = plat === "zalop"
        ? soDt[bot] || TEN_NEN.zalop
        : nhanBot[bot] || TEN_NEN[plat as keyof typeof TEN_NEN] || plat || "?";
      return {
        value: k,
        ten: (tfMeta?.[k]?.name || "").trim() || "(chưa đặt tên)",
        nguon,
        chat: phan[2] || "",
      };
    });
    // Chỉ thêm đuôi mã phòng khi cặp (tên, nguồn) VẪN còn trùng — thêm cho mọi
    // ô là quay lại đúng cái nhãn dài đã bỏ.
    const dem = new Map<string, number>();
    for (const x of tho) {
      const kh = `${x.ten}|${x.nguon}`;
      dem.set(kh, (dem.get(kh) || 0) + 1);
    }
    return tho.map((x) => {
      // Thread trùng tên với chính bot của nó (đo thật: thread "chatgpt" trên
      // bot nhãn "chatgpt") thì đừng in hai lần — "chatgpt · chatgpt" không
      // thêm thông tin nào, chỉ tốn chỗ trên màn hình hẹp.
      const goc = x.ten === x.nguon ? x.ten : `${x.ten} · ${x.nguon}`;
      return {
        value: x.value,
        label: (dem.get(`${x.ten}|${x.nguon}`) || 0) > 1
          ? `${goc} …${x.chat.slice(-4)}`
          : goc,
      };
    });
  })();

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
      try {
        const d = (await request.get("/api/zalo-personal/accounts")).data as
          { ok?: boolean; accounts?: { ownId?: string; phoneNumber?: string }[] };
        if (huy || !d?.ok) return;
        const m: Record<string, string> = {};
        for (const a of d.accounts || []) {
          const id = String(a?.ownId || "").trim();
          const sdt = String(a?.phoneNumber || "").trim();
          if (id && sdt) m[id] = sdt;
        }
        setSoDt(m);
      } catch {
        // Máy chủ Zalo cá nhân không trả lời thì thôi: nhãn rơi về tên nền
        // tảng. Không được để việc tra SỐ ĐIỆN THOẠI làm hỏng cả trang thông
        // báo — đó là thứ phụ, còn danh sách thông báo mới là việc chính.
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
                        // xem được, mà không làm rộng ô.
                        title={k.value}
                        className={
                          "max-w-full truncate rounded-full border px-2.5 py-0.5 text-xs " +
                          (chon
                            ? "border-transparent bg-primary text-primary-foreground"
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
