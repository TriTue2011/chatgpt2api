"""Bot trả lời trong nhóm Zalo cá nhân thì tag người vừa hỏi.

Chủ máy 14/09/2026: "Tự tag người gửi mỗi khi bot trả lời trong nhóm. Cái này hợp lý
khi trả lời người hỏi bot, để họ biết được phản hồi". 15/09/2026: "thêm bật tắt tag người
khi phản hồi trên webui giống như tích tag bot" — ô trong Lọc thread, mặc định tắt.

Khoá các chỗ dễ sai: chỉ nhóm; chỉ khi gửi vào ĐÚNG nhóm người đó vừa hỏi (bot có
thể gửi sang nhóm khác trong cùng lượt); @All thắng; vị trí style/mention theo
UTF-16 (tên có emoji); tin của chính chủ không tự tag.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import zalo_personal as zp


class TagNguoiHoiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.goi: list[dict] = []

        def fake(method, path, payload=None, **k):
            self.goi.append(payload or {})
            return {"ok": True, "data": {"success": True}}

        for p in (patch.object(zp, "_request", side_effect=fake),
                  patch.object(zp, "_account_for_send", return_value="acc1")):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: [setattr(zp._msg_ctx, k, "") for k in ("hoi_thread", "hoi_uid", "hoi_ten")])

    def _hoi(self, thread_id="g1", uid="u42", ten="Nguyễn Việt"):
        zp._msg_ctx.hoi_thread, zp._msg_ctx.hoi_uid, zp._msg_ctx.hoi_ten = thread_id, uid, ten

    def _gui(self, thread_id, text, ttype, **kw):
        self.goi.clear()
        zp.send_message(thread_id, text, ttype, account="acc1", **kw)
        return [g.get("message", {}) for g in self.goi]

    def test_tra_loi_trong_nhom_tag_nguoi_hoi(self) -> None:
        self._hoi()
        m = self._gui("g1", "Dạ giá vàng hôm nay là…", 1)[0]
        self.assertTrue(m["msg"].startswith("@Nguyễn Việt "), m["msg"])
        self.assertEqual([{"pos": 0, "uid": "u42", "len": len("@Nguyễn Việt")}], m["mentions"])

    def test_gui_sang_nhom_khac_hoac_chat_rieng_thi_khong_tag(self) -> None:
        self._hoi()
        self.assertNotIn("mentions", self._gui("g2", "tin cho nhóm khác", 1)[0])
        self.assertNotIn("mentions", self._gui("g1", "tin riêng", 0)[0])

    def test_all_thang_tag_mot_nguoi_va_tin_chinh_chu_khong_tag(self) -> None:
        self._hoi()
        m = self._gui("g1", "cả nhà họp nhé", 1, mention_all=True)[0]
        self.assertEqual([{"pos": 0, "uid": "-1", "len": 4}], m["mentions"])
        self._hoi(uid="")
        self.assertNotIn("mentions", self._gui("g1", "chính chủ hỏi", 1)[0])

    def test_ten_co_emoji_tinh_vi_tri_theo_utf16(self) -> None:
        self._hoi(ten="Bé Na 🌸")
        m = self._gui("g1", "**Đậm** ở đầu", 1)[0]
        self.assertEqual(len("@Bé Na ".encode("utf-16-le")) // 2 + 2, m["mentions"][0]["len"])
        if m.get("styles"):
            self.assertEqual(len("@Bé Na 🌸 ".encode("utf-16-le")) // 2, min(s["start"] for s in m["styles"]))

    def test_chi_khuc_dau_co_tag(self) -> None:
        self._hoi()
        tin = self._gui("g1", "a" * 5000, 1)
        self.assertGreater(len(tin), 1)
        self.assertIn("mentions", tin[0])
        self.assertTrue(all("mentions" not in m for m in tin[1:]))


class BatTatTheoNhomTest(unittest.TestCase):
    """Ô «Tag người hỏi» trong Lọc thread (thread_mention_filters.tag_asker)."""

    def setUp(self) -> None:
        self.addCleanup(lambda: [setattr(zp._msg_ctx, k, "") for k in ("hoi_thread", "hoi_uid", "hoi_ten")])

    def _dat(self, cau_hinh, **ev):
        from services.agent import capabilities as caps

        tin = {"thread_id": "g1", "thread_type": 1, "account_id": "acc1", "sender_id": "u42", "display_name": "Việt", **ev}
        with patch("services.config.config.get", return_value={"thread_mention_filters": cau_hinh}):
            zp._dat_nguoi_hoi(tin, caps)
        return (zp._msg_ctx.hoi_thread, zp._msg_ctx.hoi_uid, zp._msg_ctx.hoi_ten)

    def test_mac_dinh_tat_khong_tag(self) -> None:
        self.assertEqual(("", "", ""), self._dat({}))
        self.assertEqual(("", "", ""), self._dat({"zalop:acc1:g1": {"required": True, "keyword": "@bot"}}))

    def test_nhom_tich_o_thi_tag_nguoi_hoi(self) -> None:
        self.assertEqual(("g1", "u42", "Việt"), self._dat({"zalop:acc1:g1": {"tag_asker": True}}))
        # Khoá chung mọi tài khoản cũng được.
        self.assertEqual(("g1", "u42", "Việt"), self._dat({"zalop:g1": {"tag_asker": True}}))
        # Chat riêng, hay tin của chính chủ: không tag.
        self.assertEqual(("", "", ""), self._dat({"zalop:acc1:g1": {"tag_asker": True}}, thread_type=0))
        self.assertEqual("", self._dat({"zalop:acc1:g1": {"tag_asker": True}}, is_self=True)[1])

    def test_luu_cau_hinh_giu_o_nay(self) -> None:
        from services.config import _normalize_thread_mention_filters as chuan

        self.assertTrue(chuan({"zalop:acc1:g1": {"tag_asker": True}})["zalop:acc1:g1"]["tag_asker"])
        self.assertNotIn("tag_asker", chuan({"zalop:acc1:g1": {"required": True, "tag_asker": False}})["zalop:acc1:g1"])


if __name__ == "__main__":
    unittest.main()
