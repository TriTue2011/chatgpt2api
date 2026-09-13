"""Sổ đăng ký thông báo: một nơi quyết định, không có đường ngầm nào khác.

Chủ máy chốt 13/09/2026: gom mọi cài đặt thông báo về một chỗ, mỗi thông báo
cài riêng, và *"toàn bộ các thông báo theo cài đặt webui, không mặc định"*.

Ba thứ phải khoá lại, vì cả ba đều đã hỏng thật trước đây:

1. **Không có mặc định.** Chưa bật hoặc chưa chọn kênh thì IM. Đường cũ
   (`canh_bao_nha._nguoi_nhan()`) rơi về admin ba tầng, và tầng 3 chỉ duyệt
   `telegram_bots` + `zalo_bots` nên không bao giờ sinh nổi tiền tố `zalop_`
   — tin khoá cửa vì thế không tài nào tới Zalo cá nhân.
2. **Chuyển dữ liệu không được đổi hành vi.** Đo 13/09/2026 trên máy thật:
   admin Telegram đang có 🔔=False và 📋=False, tức hôm nay KHÔNG nhận gì. Bản
   chuyển mà bật nó lên là tự ý đổi hành vi chủ máy không hề yêu cầu.
3. **Khoá lạ không được gửi.** Gõ sai một khoá mà tin vẫn bay đi đâu đó thì
   đúng bằng việc không có sổ đăng ký.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import thong_bao as tb


class _Cfg:
    """Config giả — chỉ cần `.data` và `.update()` gộp nông như bản thật."""

    def __init__(self, data: dict | None = None) -> None:
        self.data = data or {}

    def update(self, d: dict) -> dict:
        self.data.update(d)
        return self.data

    def get(self) -> dict:
        return self.data


class _Nen(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = _Cfg()
        p = mock.patch.object(tb, "config", self.cfg)
        p.start()
        self.addCleanup(p.stop)


class SoDangKyTests(_Nen):
    def test_khong_co_khoa_trung(self) -> None:
        khoa = [s.khoa for s in tb.SU_KIEN]
        self.assertEqual(len(khoa), len(set(khoa)))

    def test_moi_su_kien_deu_co_nhan_tieng_viet(self) -> None:
        for s in tb.SU_KIEN:
            self.assertTrue(s.nhan.strip(), s.khoa)
            self.assertTrue(s.mo_ta.strip(), s.khoa)
            self.assertTrue(s.nhom.strip(), s.khoa)

    def test_co_du_thong_bao_khoa_cua(self) -> None:
        """Chủ máy nêu đích danh: "kể cả thông báo khoá cửa hay tương tự"."""
        khoa = {s.khoa for s in tb.SU_KIEN}
        self.assertIn("nha.khoa_cua.hoi_ten", khoa)
        self.assertIn("nha.khoa_cua.mo_khuya", khoa)
        self.assertIn("nha.khoa_cua.tom_tat", khoa)

    def test_co_du_bon_ro_cua_notify_admin(self) -> None:
        khoa = {s.khoa for s in tb.SU_KIEN}
        for k in ("he_thong.loi", "tai_khoan.log", "tai_khoan.cap_nhat",
                  "chat.moi"):
            self.assertIn(k, khoa)

    def test_dang_ky_kem_cai_dat_hien_tai(self) -> None:
        self.cfg.data["thong_bao"] = {"he_thong.loi": {"bat": True,
                                                       "kenh": ["zalo:1:2"]}}
        d = {x["khoa"]: x for x in tb.dang_ky()}
        self.assertTrue(d["he_thong.loi"]["bat"])
        self.assertEqual(d["he_thong.loi"]["kenh"], ["zalo:1:2"])
        self.assertFalse(d["nha.canh_bao"]["bat"])


class KhongCoMacDinhTests(_Nen):
    """Chưa cài thì IM — và nói rõ vì sao im."""

    def _gui(self, khoa: str = "he_thong.loi") -> tuple[int, mock.Mock]:
        with mock.patch("services.digest.send_targets", return_value=1) as g:
            n = tb.gui(khoa, "tin thử")
        return n, g

    def test_chua_khai_gi_thi_khong_gui(self) -> None:
        n, g = self._gui()
        self.assertEqual(n, 0)
        g.assert_not_called()

    def test_tat_thi_khong_gui(self) -> None:
        self.cfg.data["thong_bao"] = {"he_thong.loi": {"bat": False,
                                                       "kenh": ["zalo:1:2"]}}
        n, g = self._gui()
        self.assertEqual(n, 0)
        g.assert_not_called()

    def test_bat_nhung_chua_chon_kenh_thi_khong_gui(self) -> None:
        """Đây là chỗ đường cũ rơi về admin — giờ phải im hẳn."""
        self.cfg.data["thong_bao"] = {"he_thong.loi": {"bat": True, "kenh": []}}
        n, g = self._gui()
        self.assertEqual(n, 0)
        g.assert_not_called()

    def test_khoa_la_thi_khong_gui(self) -> None:
        self.cfg.data["thong_bao"] = {"khoa.bia.dat": {"bat": True,
                                                       "kenh": ["zalo:1:2"]}}
        n, g = self._gui("khoa.bia.dat")
        self.assertEqual(n, 0)
        g.assert_not_called()

    def test_tin_rong_thi_khong_gui(self) -> None:
        self.cfg.data["thong_bao"] = {"he_thong.loi": {"bat": True,
                                                       "kenh": ["zalo:1:2"]}}
        with mock.patch("services.digest.send_targets", return_value=1) as g:
            self.assertEqual(tb.gui("he_thong.loi", "   "), 0)
        g.assert_not_called()


class GuiDungKenhDaChonTests(_Nen):
    def test_gui_dung_danh_sach_kenh(self) -> None:
        self.cfg.data["thong_bao"] = {
            "nha.khoa_cua.hoi_ten": {"bat": True,
                                     "kenh": ["zalop:475:313", "zalo:194:abc"]}}
        with mock.patch("services.digest.send_targets", return_value=2) as g:
            n = tb.gui("nha.khoa_cua.hoi_ten", "🚪 có người mở cửa")
        self.assertEqual(n, 2)
        self.assertEqual(g.call_args[0][0], ["zalop:475:313", "zalo:194:abc"])
        self.assertIn("mở cửa", g.call_args[0][1])

    def test_digest_no_loi_thi_khong_raise(self) -> None:
        self.cfg.data["thong_bao"] = {"he_thong.loi": {"bat": True,
                                                       "kenh": ["zalo:1:2"]}}
        with mock.patch("services.digest.send_targets",
                        side_effect=RuntimeError("mất mạng")):
            self.assertEqual(tb.gui("he_thong.loi", "x"), 0)


class ChuyenDuLieuGiuNguyenHanhViTests(_Nen):
    """Chép hành vi HÔM NAY sang chỗ mới — không bật thêm, không tắt bớt."""

    def setUp(self) -> None:
        super().setUp()
        self.cfg.data.update({
            # HÌNH DẠNG DỰNG, KHÔNG phải hình dạng máy thật: admin tắt 🔔/📋
            # nhưng KHÔNG tắt 💬 ở cả hai tầng. Dựng vậy để khoá đúng một luật
            # đã đọc được trong `telegram_bot.notify_admin:460` và
            # `zalo_bot.notify_admin:1200` — nhánh 💬 chỉ loại khi
            # `newchat_alert_enabled is False`, không hỏi `notify_enabled`.
            # Máy thật 13/09/2026 thì bot Telegram tắt SẠCH bốn cờ ở cả tầng
            # bot lẫn tầng dòng; ca đó có phép đo riêng ở dưới.
            "telegram_bots": [{
                "enabled": True, "token": "844111:AAA",
                "admin_entries": [{"chat_id": "-100999:975",
                                   "notify_enabled": False,
                                   "account_log_enabled": False}],
            }],
            "zalo_bots": [
                {"enabled": True, "token": "194222:BBB",
                 "admin_entries": [{"chat_id": "4e77aa",
                                    "notify_enabled": True,
                                    "account_log_enabled": True}]},
                {"enabled": True, "token": "341333:CCC",
                 "admin_entries": [{"chat_id": "41d8bb",
                                    "notify_enabled": True,
                                    "account_log_enabled": False}]},
            ],
            "zalo_personal_account_admins": {
                "475": {"enabled": True, "notify_admin_enabled": True,
                        "account_log_enabled": False,
                        "admin_entries": [{"chat_id": "664",
                                           "notify_enabled": True,
                                           "account_log_enabled": False,
                                           "newchat_alert_enabled": True}]},
            },
            "mqtt": {"canh_bao": {"kenh_nhan": ["zalop:475:313"]},
                     "bai_hoc": {"kenh_nhan": ["zalop:475:313"]}},
        })

    def test_admin_TAT_notify_thi_bi_loai_khoi_he_thong_va_log(self) -> None:
        """Admin Telegram tắt 🔔/📋 thì không được điền vào ba mục đó."""
        suy = tb.suy_ra_tu_cai_cu()
        for k in ("he_thong.loi", "tai_khoan.log", "tai_khoan.cap_nhat"):
            for x in suy[k]["kenh"]:
                self.assertFalse(x.startswith("tg:"),
                                 f"{k}: admin Telegram đang tắt mà vẫn điền {x}")

    def test_admin_TAT_notify_VAN_nhan_chat_moi(self) -> None:
        """💬 KHÔNG hỏi `notify_enabled` — đo trong `telegram_bot.notify_admin`
        (dòng 460) và `zalo_bot.notify_admin` (dòng 1200): nhánh newchat chỉ
        loại khi `newchat_alert_enabled is False`.

        Nên admin đã tắt 🔔 vẫn đang nhận 💬 hôm nay. Loại nó ra khi chuyển dữ
        liệu là âm thầm cắt mất một thông báo chủ máy đang nhận — bản chuyển
        phải chép hành vi, không được "dọn cho gọn"."""
        suy = tb.suy_ra_tu_cai_cu()
        self.assertIn("tg:844111:-100999", suy["chat.moi"]["kenh"])

    def test_HINH_DANG_MAY_THAT_bot_tat_sach_thi_vang_mat_o_MOI_muc(self) -> None:
        """Ca đúng theo máy thật, đo 13/09/2026.

        Bot Telegram `844…` tắt cả bốn cờ ở TẦNG BOT (`notify_admin_enabled`,
        `newchat_alert_enabled`, `account_log_enabled`,
        `account_update_log_enabled`) lẫn tầng từng dòng. Hôm nay nó không nhận
        gì — kể cả 💬 — nên bản chuyển dữ liệu phải bỏ nó khỏi MỌI mục.

        Giữ riêng khỏi ca tổng hợp ở trên vì hai ca đo hai thứ khác nhau: ca
        kia khoá LUẬT của nhánh 💬, ca này khoá HÌNH DẠNG máy thật."""
        self.cfg.data["telegram_bots"] = [{
            "enabled": True, "token": "844111:AAA",
            "notify_admin_enabled": False, "newchat_alert_enabled": False,
            "account_log_enabled": False, "account_update_log_enabled": False,
            "admin_entries": [{"chat_id": "-100999:975",
                               "notify_enabled": False,
                               "account_log_enabled": False,
                               "account_update_log_enabled": False,
                               "newchat_alert_enabled": False}],
        }]
        suy = tb.suy_ra_tu_cai_cu()
        for khoa, muc in suy.items():
            for k in muc["kenh"]:
                self.assertFalse(k.startswith("tg:"), f"{khoa} vẫn điền {k}")

    def test_cong_TOAN_CUC_tat_thi_ca_nen_tang_bi_loai(self) -> None:
        """`telegram_notify_enabled=False` → Telegram im hoàn toàn, kể cả 💬."""
        self.cfg.data["telegram_notify_enabled"] = False
        suy = tb.suy_ra_tu_cai_cu()
        for muc in suy.values():
            for x in muc["kenh"]:
                self.assertFalse(x.startswith("tg:"), x)

    def test_cong_CUA_BOT_tat_thi_admin_cua_no_bi_loai(self) -> None:
        """Cờ `notify_admin_enabled` của con bot nằm trên cờ từng dòng."""
        self.cfg.data["zalo_bots"][0]["notify_admin_enabled"] = False
        suy = tb.suy_ra_tu_cai_cu()
        self.assertNotIn("zalo:194222:4e77aa", suy["he_thong.loi"]["kenh"])
        # nhưng 💬 đi cổng khác, vẫn còn
        self.assertIn("zalo:194222:4e77aa", suy["chat.moi"]["kenh"])

    def test_he_thong_lay_dung_admin_dang_bat(self) -> None:
        suy = tb.suy_ra_tu_cai_cu()
        self.assertEqual(sorted(suy["he_thong.loi"]["kenh"]),
                         ["zalo:194222:4e77aa", "zalo:341333:41d8bb",
                          "zalop:475:664"])

    def test_log_tai_khoan_chi_lay_admin_bat_co_log(self) -> None:
        """Chỉ Mít Bắp bật 📋; Ben Bắp và Zalo cá nhân thì không."""
        suy = tb.suy_ra_tu_cai_cu()
        self.assertEqual(suy["tai_khoan.log"]["kenh"], ["zalo:194222:4e77aa"])

    def test_khoa_cua_duoc_dien_kenh_chu_khong_im(self) -> None:
        """Xưa nay đi ngầm qua admin — chủ máy chọn "tự điền", nên phải có kênh."""
        suy = tb.suy_ra_tu_cai_cu()
        for k in ("nha.khoa_cua.hoi_ten", "nha.khoa_cua.mo_khuya",
                  "nha.khoa_cua.tom_tat"):
            self.assertTrue(suy[k]["kenh"], k)
            self.assertTrue(suy[k]["bat"], k)

    def test_kenh_dich_danh_cu_duoc_giu_nguyen(self) -> None:
        suy = tb.suy_ra_tu_cai_cu()
        self.assertEqual(suy["nha.canh_bao"]["kenh"], ["zalop:475:313"])
        self.assertEqual(suy["hoc_hoi.ban_tin"]["kenh"], ["zalop:475:313"])

    def test_khoa_dung_khuon_plat_bot_chat(self) -> None:
        """Khoá sai khuôn thì `send_target` bỏ im — tin bay vào hư không."""
        from services import digest
        suy = tb.suy_ra_tu_cai_cu()
        for muc in suy.values():
            for k in muc["kenh"]:
                self.assertIsNotNone(digest.parse_target(k), k)

    def test_chat_id_co_thread_thi_cat_lay_phan_chat(self) -> None:
        """`_nguoi_nhan` cũ cắt 'chat:thread'; giữ nguyên nếp đó."""
        self.cfg.data["zalo_bots"] = [{
            "enabled": True, "token": "194222:BBB",
            "admin_entries": [{"chat_id": "abc:99", "notify_enabled": True}],
        }]
        suy = tb.suy_ra_tu_cai_cu()
        self.assertIn("zalo:194222:abc", suy["he_thong.loi"]["kenh"])

    def test_bot_da_TAT_thi_bo_qua(self) -> None:
        self.cfg.data["zalo_bots"][0]["enabled"] = False
        suy = tb.suy_ra_tu_cai_cu()
        self.assertNotIn("zalo:194222:4e77aa", suy["he_thong.loi"]["kenh"])

    def test_chay_mot_lan_roi_thi_KHONG_ghi_de(self) -> None:
        self.cfg.data["thong_bao"] = {"he_thong.loi": {"bat": False, "kenh": []}}
        kq = tb.chuyen_du_lieu_mot_lan()
        self.assertTrue(kq["da_co"])
        self.assertEqual(self.cfg.data["thong_bao"],
                         {"he_thong.loi": {"bat": False, "kenh": []}})

    def test_chua_co_thi_ghi_vao_config(self) -> None:
        kq = tb.chuyen_du_lieu_mot_lan()
        self.assertFalse(kq["da_co"])
        self.assertIn("thong_bao", self.cfg.data)
        self.assertTrue(self.cfg.data["thong_bao"]["he_thong.loi"]["kenh"])


class DongDONGTheoTungNguonTests(_Nen):
    """Mỗi hộp mail, mỗi lịch một dòng riêng — chủ máy chốt 13/09/2026.

    Đường này TRƯỚC ĐÓ KHÔNG có phép đo nào: bộ test cũ vẫn xanh vì mọi phép
    đo đều duyệt bất cứ thứ gì `dang_ky()` trả về, nên có hay không có dòng
    động cũng xanh như nhau. Xanh mà không đo được gì chính là cái bẫy
    "13/13 test, bắt 0 ca thật" của kho này.
    """

    def _nguon(self):
        return (
            mock.patch("services.email_channel.accounts", return_value=[
                {"id": "7823a0e2", "label": "Hộp mail chính"},
                {"id": "af931d7e", "label": "visaho"}]),
            mock.patch("services.calendar_connector.calendars", return_value=[
                {"id": "ef257920", "label": "Lịch chính"}]),
        )

    def test_moi_nguon_mot_dong_rieng(self) -> None:
        with self._nguon()[0], self._nguon()[1]:
            khoa = {x["khoa"] for x in tb.dang_ky()}
        self.assertIn("email.7823a0e2", khoa)
        self.assertIn("email.af931d7e", khoa)
        self.assertIn("lich.ef257920", khoa)

    def test_khoa_theo_ID_BEN_khong_theo_thu_tu(self) -> None:
        """Khoá theo thứ tự thì thêm/bớt một nguồn là cài đặt lặng lẽ trỏ sang
        nguồn khác. `_norm_cal` gắn id theo URL đúng để tránh chuyện đó."""
        with self._nguon()[0], self._nguon()[1]:
            khoa = {x["khoa"] for x in tb.dang_ky()}
        self.assertNotIn("email.0", khoa)
        self.assertNotIn("email.1", khoa)

    def test_GUI_duoc_qua_khoa_dong(self) -> None:
        self.cfg.data["thong_bao"] = {
            "email.af931d7e": {"bat": True, "kenh": ["zalo:350:abc"]}}
        with self._nguon()[0], self._nguon()[1], \
                mock.patch("services.digest.send_targets", return_value=1) as g:
            n = tb.gui("email.af931d7e", "📬 có thư mới")
        self.assertEqual(n, 1)
        self.assertEqual(g.call_args[0][0], ["zalo:350:abc"])

    def test_KHOA_BIA_van_bi_tu_choi(self) -> None:
        """Nới cho khoá suy ra được, KHÔNG nới cho mọi chuỗi."""
        self.cfg.data["thong_bao"] = {
            "email.khong_co_that": {"bat": True, "kenh": ["zalo:1:2"]}}
        with self._nguon()[0], self._nguon()[1], \
                mock.patch("services.digest.send_targets", return_value=1) as g:
            n = tb.gui("email.khong_co_that", "x")
        self.assertEqual(n, 0)
        g.assert_not_called()

    def test_luu_nhan_khoa_dong_nhung_bo_khoa_bia(self) -> None:
        with self._nguon()[0], self._nguon()[1]:
            tb.luu({"lich.ef257920": {"bat": True, "kenh": ["zalo:1:2"]},
                    "lich.bia_dat": {"bat": True, "kenh": ["zalo:9:9"]}})
        self.assertIn("lich.ef257920", self.cfg.data["thong_bao"])
        self.assertNotIn("lich.bia_dat", self.cfg.data["thong_bao"])


class LuuTuGiaoDienTests(_Nen):
    def test_bo_khoa_la_khong_cho_ghi_bua(self) -> None:
        tb.luu({"he_thong.loi": {"bat": True, "kenh": ["zalo:1:2"]},
                "khoa.bia": {"bat": True, "kenh": ["zalo:9:9"]}})
        self.assertIn("he_thong.loi", self.cfg.data["thong_bao"])
        self.assertNotIn("khoa.bia", self.cfg.data["thong_bao"])

    def test_ghi_dung_hinh_dang(self) -> None:
        tb.luu({"nha.goi_y": {"bat": True, "kenh": [" zalo:1:2 ", "", "x:y:z"]}})
        self.assertEqual(self.cfg.data["thong_bao"]["nha.goi_y"],
                         {"bat": True, "kenh": ["zalo:1:2", "x:y:z"]})


if __name__ == "__main__":
    unittest.main()
