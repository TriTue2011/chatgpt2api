"""Nhật ký nhóm: opt-in (mặc định TẮT), hạn giữ theo phạm vi (kế thừa hẹp→rộng),
đọc theo kết nối bộ nhớ, tìm "việc nhắc tới tôi".

Điều khoá chặt nhất: **mặc định KHÔNG ghi gì** — lưu lời người khác nên phải bật
riêng từng phạm vi. Và nhật ký là SỔ CHUNG cấp nhóm (mọi thành viên góp vào một
cuốn), khác memory có thể tách theo người.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import chatlog, scope  # noqa: E402

# khoá phiên: nhóm Zalo cá nhân G1 (user 9), nhóm Telegram -100
G1 = "zalop_g1:u9"
G1_U10 = "zalop_g1:u10"
TG = "-100:u5"


class _Moi(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="chatlog-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        chatlog._reset_for_tests(self.tmp / "chatlog.sqlite")
        self.addCleanup(chatlog._reset_for_tests, None)
        self.cfg: dict = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def _bat(self, khoa: str, days: int = 30):
        self.cfg.setdefault("chatlog_settings", {})[khoa] = {
            "enabled": True, "retention_days": days}


class MacDinhTat(_Moi):
    def test_khong_cau_hinh_thi_KHONG_ghi(self):
        self.assertFalse(chatlog.ghi(G1, sender_name="A", text="xin chào cả nhà"))
        self.assertEqual(chatlog.doc_ngay(G1), [])

    def test_cau_hinh_enabled_false_van_khong_ghi(self):
        self.cfg["chatlog_settings"] = {"zalop:g1": {"enabled": False}}
        self.assertFalse(chatlog.ghi(G1, text="test"))

    def test_bat_thi_ghi(self):
        self._bat("zalop:g1")
        self.assertTrue(chatlog.ghi(G1, sender_name="A", text="họp lúc 3h chiều"))
        ds = chatlog.doc_ngay(G1)
        self.assertEqual(len(ds), 1)
        self.assertIn("họp", ds[0]["text"])


class SoChungCapNhom(_Moi):
    def test_moi_thanh_vien_gop_vao_MOT_cuon(self):
        """u9 và u10 cùng nhóm → cùng sổ (dù group có thể lọc user cho memory)."""
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="Chín", text="tối nay ăn gì")
        chatlog.ghi(G1_U10, sender_name="Mười", text="ăn phở đi")
        ds = chatlog.doc_ngay(G1)
        self.assertEqual(len(ds), 2)               # cả hai trong một sổ
        self.assertEqual(len(chatlog.doc_ngay(G1_U10)), 2)  # u10 đọc cùng sổ

    def test_nhom_khac_KHONG_thay(self):
        self._bat("zalop:g1")
        self._bat("tg:-100")
        chatlog.ghi(G1, text="bí mật nhóm g1")
        self.assertEqual(chatlog.doc_ngay(TG), [])  # nhóm tg không thấy g1


class KeThuaCauHinh(_Moi):
    def test_bat_o_cap_KENH_ap_cho_nhom_con(self):
        self.cfg["chatlog_settings"] = {"zalop": {"enabled": True, "retention_days": 30}}
        self.assertTrue(chatlog.ghi(G1, text="theo cấp kênh"))

    def test_cap_NHOM_de_len_cap_kenh(self):
        self.cfg["chatlog_settings"] = {
            "zalop": {"enabled": True},
            "zalop:g1": {"enabled": False},   # nhóm g1 tắt riêng, đè kênh
        }
        self.assertFalse(chatlog.ghi(G1, text="g1 tắt riêng"))
        self.assertTrue(chatlog.ghi("zalop_g2", text="g2 theo kênh"))

    def test_cap_NGUOI_de_len_cap_nhom(self):
        self.cfg["chatlog_settings"] = {
            "zalop:g1": {"enabled": True},
            "zalop:g1:9": {"enabled": False},  # riêng người 9 không ghi
        }
        self.assertFalse(chatlog.ghi("zalop_g1:u9", text="của 9"))
        self.assertTrue(chatlog.ghi("zalop_g1:u10", text="của 10"))


class TopicRieng(_Moi):
    """Mỗi TOPIC là một sổ riêng (topic thắng nhóm), cấu hình theo topic đè nhóm."""

    T975 = "-100#975:u5"      # nhóm -100, topic 975
    T976 = "-100#976:u5"      # nhóm -100, topic 976 (khác)

    def test_hai_topic_la_hai_so(self):
        self._bat("tg:-100")                       # bật cả nhóm
        chatlog.ghi(self.T975, sender_name="A", text="việc của topic 975")
        chatlog.ghi(self.T976, sender_name="B", text="việc của topic 976")
        d975 = [r["text"] for r in chatlog.doc_ngay(self.T975)]
        d976 = [r["text"] for r in chatlog.doc_ngay(self.T976)]
        self.assertEqual(d975, ["việc của topic 975"])
        self.assertEqual(d976, ["việc của topic 976"])   # không lẫn nhau

    def test_cau_hinh_topic_de_len_nhom(self):
        self.cfg["chatlog_settings"] = {
            "tg:-100": {"enabled": True},
            "tg:-100#976": {"enabled": False},     # riêng topic 976 tắt
        }
        self.assertTrue(chatlog.ghi(self.T975, text="975 ghi"))
        self.assertFalse(chatlog.ghi(self.T976, text="976 tắt riêng"))

    def test_bat_rieng_MOT_topic(self):
        self.cfg["chatlog_settings"] = {"tg:-100#975": {"enabled": True}}
        self.assertTrue(chatlog.ghi(self.T975, text="chỉ topic 975 bật"))
        self.assertFalse(chatlog.ghi(self.T976, text="976 chưa bật"))   # nhóm chưa bật


class DiTheoKetNoi(_Moi):
    def test_chinh_phu_doc_duoc_nhat_ky_nhom_phu(self):
        # CHÍNH = cá nhân zalop_ca; PHỤ = nhóm g1
        self.cfg["memory_links"] = [{"id": "1", "kind": "chinh_phu",
            "primary": [{"kenh": "zalop", "chat": "ca"}],
            "secondary": [{"kenh": "zalop", "chat": "g1"}]}]
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="A", text="lịch tiêm phòng thứ Ba")
        # cá nhân (chính) hỏi → đọc được nhật ký nhóm phụ
        self.assertTrue(chatlog.doc_ngay("zalop_ca"))
        # nhưng nhóm phụ KHÔNG đọc ngược của chính (1 chiều) — chính chưa ghi gì nên rỗng
        self.assertEqual(chatlog.doc_ngay("zalop_khac"), [])


class NhacToiToi(_Moi):
    def test_tim_tin_nhac_ten_toi(self):
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="A", text="chuyện không liên quan")
        chatlog.ghi(G1, sender_name="B", text="@Việt ơi mai đi họp nhé")
        r = chatlog.nhac_toi(G1, "Việt")
        self.assertEqual(len(r), 1)
        self.assertIn("họp", r[0]["text"])

    def test_khop_khong_dau(self):
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="B", text="@Việt xem giúp")
        self.assertTrue(chatlog.nhac_toi(G1, "viet"))   # gõ không dấu vẫn ra

    def test_tag_all_tinh_la_nhac_moi_nguoi(self):
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="B", text="@all họp khẩn 5h")
        self.assertTrue(chatlog.nhac_toi(G1, "bất kỳ ai"))


class HanGiu(_Moi):
    def test_xoa_tin_qua_han(self):
        self._bat("zalop:g1", days=7)
        # chèn tin cũ 10 ngày trực tiếp
        chatlog.ghi(G1, text="tin mới hôm nay")
        old_day = (datetime.now(chatlog._TZ) - timedelta(days=10)).strftime("%Y-%m-%d")
        with chatlog._lock:
            db = chatlog._db()
            db.execute("INSERT INTO chatlog (scope, ts, day, sender_id, sender_name,"
                       " text, text_fold, mentions_fold) VALUES (?,?,?,?,?,?,?,?)",
                       (scope.khoa_nhat_ky(G1), time.time() - 10 * 86400, old_day,
                        "", "X", "tin cũ 10 ngày", "tin cu 10 ngay", ""))
            db.commit()
        # ghi thêm 1 tin → kích _don → tin cũ quá 7 ngày bị xoá
        chatlog.ghi(G1, text="tin mới nữa")
        days = {r["text"] for r in chatlog.doc_ngay(G1)}
        self.assertNotIn("tin cũ 10 ngày", " ".join(
            r["text"] for r in chatlog.doc_ngay(G1, day=old_day)))
        self.assertIn("tin mới hôm nay", days)


if __name__ == "__main__":
    unittest.main()


class TagBotTrongLocNhatKyTests(_Moi):
    """Ô «Tag bot» của «Lọc nhật ký» — CHẠY NGƯỢC CHIỀU các ô khác.

    Chủ máy chốt 07/08: bỏ tick (mặc định) = ghi cả hội thoại KHÔNG tag; tick
    vào = SIẾT LẠI, chỉ tin có tag bot mới lưu.

    Đây là công tắc tag THỨ BA, rời hẳn hai cái đã có ở «Lọc thread»: trả lời
    (`thread_mention_filters`) và đẩy webhook (`thread_forward_filters.tag_mode`).
    Gộp ba cái là hỏng đúng cái ý nghĩa của nhật ký nhóm — **ghi ≠ trả lời**.
    """

    def _bat_tag_only(self, khoa: str, tag_only: bool):
        self.cfg.setdefault("chatlog_settings", {})[khoa] = {
            "enabled": True, "retention_days": 30, "tag_only": tag_only}

    def test_mac_dinh_ghi_ca_tin_khong_tag(self):
        self._bat("zalop:g1")
        self.assertTrue(chatlog.ghi(G1, sender_id="9", text="hôm nay trời đẹp",
                                    tagged=False))

    def test_bat_tag_only_thi_tin_khong_tag_bi_bo(self):
        self._bat_tag_only("zalop:g1", True)
        self.assertFalse(chatlog.ghi(G1, sender_id="9", text="hôm nay trời đẹp",
                                     tagged=False))

    def test_bat_tag_only_van_ghi_tin_co_tag(self):
        self._bat_tag_only("zalop:g1", True)
        self.assertTrue(chatlog.ghi(G1, sender_id="9", text="@bot bật đèn",
                                    tagged=True))

    def test_khong_biet_co_tag_hay_khong_thi_VAN_GHI(self):
        """Kênh nào quên truyền cờ thì hậu quả là nhật ký RỘNG hơn ý muốn — còn
        làm ngược lại thì nhật ký im lặng rỗng và không ai biết vì sao."""
        self._bat_tag_only("zalop:g1", True)
        self.assertTrue(chatlog.ghi(G1, sender_id="9", text="không rõ", tagged=None))

    def test_cai_dat_tra_ve_tag_only(self):
        self._bat_tag_only("zalop:g1", True)
        self.assertTrue(chatlog.cai_dat("zalop", "g1")["tag_only"])

    def test_ban_ghi_CU_khong_co_truong_nay_thi_ghi_het(self):
        """Cấu hình đang chạy trên máy chủ không có `tag_only` — phải giữ NGUYÊN
        hành vi cũ, không được im lặng bớt tin của chủ máy."""
        self._bat("zalop:g1")
        self.assertFalse(chatlog.cai_dat("zalop", "g1")["tag_only"])
        self.assertTrue(chatlog.ghi(G1, sender_id="9", text="tin chay",
                                    tagged=False))
