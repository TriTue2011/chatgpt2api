"""Luật «tự nhắc»: ai nhắc tới TÊN + có hẹn → đặt nhắc trước 1 ngày/1 giờ.

`quet_nhac_hen` là hàm THUẦN (bơm hai callable): test được KHÔNG cần LLM thật hay
nhắc-hẹn thật. Kiểm: CRUD luật, đúng mốc lead, bỏ mốc quá khứ, không tạo trùng,
và chỉ đọc phạm vi mình được phép (qua «Kết nối bộ nhớ»).
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import capabilities, chatlog  # noqa: E402

DM = "zalop_ca"            # chat riêng của chủ (nơi nhận nhắc)
G1 = "zalop_g1:u9"         # nhóm g1 (đã kết nối tới DM)
G2 = "zalop_g2:u9"         # nhóm g2 (KHÔNG kết nối)


class _Moi(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="chatlog-nhac-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        chatlog._reset_for_tests(self.tmp / "chatlog.sqlite")
        self.addCleanup(chatlog._reset_for_tests, None)
        self.cfg: dict = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def _bat(self, khoa: str):
        self.cfg.setdefault("chatlog_settings", {})[khoa] = {
            "enabled": True, "retention_days": 30}

    def _noi_dm_g1(self):
        # CHÍNH = DM (zalop:ca) đọc được PHỤ = nhóm g1
        self.cfg["memory_links"] = [{"id": "1", "kind": "chinh_phu",
            "primary": [{"kenh": "zalop", "chat": "ca"}],
            "secondary": [{"kenh": "zalop", "chat": "g1"}]}]

    def _iso(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, chatlog._TZ).strftime("%Y-%m-%dT%H:%M")


class LuatCRUD(_Moi):
    def test_them_list_off(self):
        r = chatlog.luat_them(DM, "Việt")
        self.assertIsNotNone(r)
        self.assertEqual(r["lead_min"], [1440, 60])           # mặc định 1 ngày, 1 giờ
        ds = chatlog.luat_ds(DM)
        self.assertEqual(len(ds), 1)
        self.assertEqual(chatlog.luat_tat(DM, r["id"]), 1)
        self.assertEqual(chatlog.luat_ds(DM), [])

    def test_them_hai_lan_cung_ten_khong_nhan_doi(self):
        chatlog.luat_them(DM, "Việt", lead_min=[120])
        chatlog.luat_them(DM, "việt", lead_min=[1440, 60])    # bỏ dấu = trùng
        ds = chatlog.luat_ds(DM)
        self.assertEqual(len(ds), 1)
        self.assertEqual(ds[0]["lead_min"], [1440, 60])       # bản sau đè


class QuetNhac(_Moi):
    def _quet(self, appt_ts: float, now: float | None = None):
        """Quét với LLM giả (mọi tin khớp → 1 hẹn tại appt_ts) + thu nhắc đã tạo."""
        tao: list[tuple] = []
        trich = lambda msgs: {m["id"]: {"iso": self._iso(appt_ts), "label": "họp"}
                              for m in msgs}
        chatlog.quet_nhac_hen(
            trich_hen=trich,
            tao_nhac=lambda dt, txt, khi, meta: tao.append((dt, txt, khi, meta)),
            now=now)
        return tao

    def test_tao_dung_hai_moc(self):
        self._noi_dm_g1()
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="Nam", text="@Việt mai 8h họp nhé")
        chatlog.luat_them(DM, "Việt")
        now = time.time()
        appt = now + 3 * 86400                                # 3 ngày nữa
        tao = self._quet(appt, now=now)
        self.assertEqual(len(tao), 2)                          # -1 ngày, -1 giờ
        khi = sorted(t[2] for t in tao)
        # iso mốc hẹn chỉ tới PHÚT → sai lệch giây khi parse lại (< 60s)
        self.assertAlmostEqual(khi[0], appt - 1440 * 60, delta=61)
        self.assertAlmostEqual(khi[1], appt - 60 * 60, delta=61)
        self.assertTrue(all(t[0] == DM for t in tao))          # gửi tới DM chủ

    def test_khong_tao_trung(self):
        self._noi_dm_g1()
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="Nam", text="@Việt mai 8h họp")
        chatlog.luat_them(DM, "Việt")
        now = time.time()
        appt = now + 3 * 86400
        self.assertEqual(len(self._quet(appt, now=now)), 2)
        self.assertEqual(len(self._quet(appt, now=now)), 0)    # lần 2 không tạo lại

    def test_bo_moc_qua_khu(self):
        self._noi_dm_g1()
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="Nam", text="@Việt họp gấp")
        chatlog.luat_them(DM, "Việt")
        now = time.time()
        appt = now + 30 * 60                                   # chỉ còn 30 phút
        tao = self._quet(appt, now=now)
        self.assertEqual(len(tao), 0)                          # cả -1 giờ lẫn -1 ngày đã qua

    def test_chi_doc_pham_vi_da_noi(self):
        # KHÔNG nối g2 → tin ở g2 không tới được DM → không nhắc
        self._noi_dm_g1()
        self._bat("zalop:g1")
        self._bat("zalop:g2")
        chatlog.ghi(G2, sender_name="X", text="@Việt mai 8h họp")   # g2 không nối
        chatlog.luat_them(DM, "Việt")
        now = time.time()
        self.assertEqual(len(self._quet(now + 3 * 86400, now=now)), 0)

    def test_khong_hen_thi_khong_nhac(self):
        self._noi_dm_g1()
        self._bat("zalop:g1")
        chatlog.ghi(G1, sender_name="Nam", text="@Việt xem giúp cái này")
        chatlog.luat_them(DM, "Việt")
        # LLM giả trả RỖNG (không có hẹn) → không tạo nhắc
        tao: list = []
        chatlog.quet_nhac_hen(trich_hen=lambda msgs: {},
                              tao_nhac=lambda *a: tao.append(a))
        self.assertEqual(tao, [])


class ToolLuatNhac(_Moi):
    def test_set_list_off_qua_tool(self):
        cap = capabilities.CAPABILITIES["luat_nhac"]
        ctx = {"user_id": DM}
        out = cap.handler({"op": "set", "ten": "Việt", "gio_truoc": [24, 1]}, ctx)["text"]
        self.assertIn("Việt", out)
        ds = chatlog.luat_ds(DM)
        self.assertEqual(ds[0]["lead_min"], [1440, 60])       # 24h, 1h → phút
        out2 = cap.handler({"op": "list"}, ctx)["text"]
        self.assertIn("Việt", out2)
        out3 = cap.handler({"op": "off"}, ctx)["text"]
        self.assertIn("gỡ", out3.lower())
        self.assertEqual(chatlog.luat_ds(DM), [])

    def test_set_thieu_ten_thi_hoi_lai(self):
        out = capabilities.CAPABILITIES["luat_nhac"].handler(
            {"op": "set"}, {"user_id": DM})["text"]
        self.assertIn("TÊN", out)
        self.assertEqual(capabilities.group_of("luat_nhac"), "memory")


if __name__ == "__main__":
    unittest.main()
