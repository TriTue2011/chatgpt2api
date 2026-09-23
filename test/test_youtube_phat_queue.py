"""Queue của trang YouTube c2a — cùng luật với thẻ HA 0.27.0 (chủ máy 23/09/2026)."""
from __future__ import annotations

import json
import os
import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.youtube_phat import hang_cho  # noqa: E402

LOA = "media_player.phong_khach"
MAY = "device:3f2a9c1e77b0"


def bai(i: int, source: str = "youtube") -> dict:
    if source == "zing":
        return {"source": "zing", "id": "Z6ABWEDF", "url": "https://zingmp3.vn/bai-hat/Thu/Z6ABWEDF.html",
                "title": f"Bài {i}"}
    if source == "facebook":
        return {"source": "facebook", "id": "1964113577722801", "title": f"Bài {i}"}
    return {"source": "youtube", "id": "kJQP7kiw5F" + "abcdefghijk"[i], "title": f"Bài {i}", "duration": 200}


class KhoTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.kho = hang_cho.KhoHangCho(Path(self._tmp.name) / "queue.json")

    def them(self, key: str, n: int) -> None:
        self.kho.doi({"key": key, "action": "add", "items": [bai(i) for i in range(n)]})

    def test_khoa_chi_nhan_loa_hoac_may(self) -> None:
        for sai in ("", "light.den", "media_player.Phong", "device:ab", "../../etc", None):
            with self.assertRaises(ValueError):
                self.kho.doi({"key": sai, "action": "clear"})

    def test_ba_nguon_di_qua_cung_bo_chuan_hoa_playlist(self) -> None:
        self.kho.doi({"key": LOA, "action": "add", "items": [bai(0), bai(1, "zing"), bai(2, "facebook")]})
        self.assertEqual([i["source"] for i in self.kho.lay(LOA)["items"]], ["youtube", "zing", "facebook"])
        with self.assertRaises(ValueError):
            self.kho.doi({"key": LOA, "action": "add", "items": [{"source": "youtube", "id": "rac", "title": "x"}]})

    def test_lan_luot_het_thi_dung_va_luu_ra_file(self) -> None:
        self.them(LOA, 3)
        self.assertEqual([self.kho.tiep(LOA)["title"] for _ in range(3)], ["Bài 0", "Bài 1", "Bài 2"])
        self.assertIsNone(self.kho.tiep(LOA))
        # Tải lại từ file (khởi động lại c2a) vẫn còn nguyên.
        kho2 = hang_cho.KhoHangCho(self.kho.path)
        self.assertEqual(len(kho2.lay(LOA)["items"]), 3)
        self.assertFalse(kho2.co_bai_ke(LOA))

    def test_chon_mot_bai_roi_bai_ke_la_bai_dung_sau(self) -> None:
        self.them(MAY, 4)
        uid = self.kho.lay(MAY)["items"][1]["uid"]
        _q, item = self.kho.doi({"key": MAY, "action": "select", "uid": uid})
        self.assertEqual(item["title"], "Bài 1")
        self.assertEqual(self.kho.tiep(MAY)["title"], "Bài 2")

    def test_xoa_bai_dang_phat_van_sang_bai_dung_sau(self) -> None:
        self.them(LOA, 3)
        uids = [i["uid"] for i in self.kho.lay(LOA)["items"]]
        self.kho.doi({"key": LOA, "action": "select", "uid": uids[1]})
        self.kho.doi({"key": LOA, "action": "remove", "uid": uids[1]})
        self.assertEqual(self.kho.tiep(LOA)["title"], "Bài 2")

    def test_tron_moi_bai_mot_lan(self) -> None:
        self.them(LOA, 6)
        self.kho.doi({"key": LOA, "action": "set", "order": "shuffle"})
        with patch.object(hang_cho.random, "choice", random.Random(3).choice):
            thay = [self.kho.tiep(LOA)["title"] for _ in range(6)]
        self.assertEqual(sorted(thay), [f"Bài {i}" for i in range(6)])
        self.assertIsNone(self.kho.tiep(LOA))

    def test_xoa_tat_ca_giu_che_do_va_moi_may_moi_danh_sach(self) -> None:
        self.them(MAY, 2)
        self.them(LOA, 1)
        self.kho.doi({"key": MAY, "action": "set", "mode": "audio"})
        self.kho.doi({"key": MAY, "action": "clear"})
        self.assertEqual((self.kho.lay(MAY)["items"], self.kho.lay(MAY)["mode"]), ([], "audio"))
        self.assertEqual(len(self.kho.lay(LOA)["items"]), 1)
        doc = json.loads(self.kho.path.read_text(encoding="utf-8"))
        self.assertEqual(set(doc["queues"]), {MAY, LOA})


class LuiBaiTest(KhoTest):
    """Nút lùi bài trong Queue (chủ máy 24/09/2026)."""

    def test_lan_luot_lui_toi_dau_roi_dung(self) -> None:
        self.them(LOA, 3)
        uids = [i["uid"] for i in self.kho.lay(LOA)["items"]]
        self.kho.doi({"key": LOA, "action": "select", "uid": uids[2]})
        _q, item = self.kho.doi({"key": LOA, "action": "prev"})
        self.assertEqual(item["title"], "Bài 1")
        _q, item = self.kho.doi({"key": LOA, "action": "prev"})
        self.assertEqual(item["title"], "Bài 0")
        _q, item = self.kho.doi({"key": LOA, "action": "prev"})
        self.assertIsNone(item)

    def test_tron_lui_theo_lich_su(self) -> None:
        self.them(LOA, 4)
        self.kho.doi({"key": LOA, "action": "set", "order": "shuffle"})
        a = self.kho.tiep(LOA)
        b = self.kho.tiep(LOA)
        _q, item = self.kho.doi({"key": LOA, "action": "prev"})
        self.assertEqual(item["uid"], a["uid"])
        self.assertNotIn(b["uid"], self.kho.lay(LOA)["played"])


class TuChuyenBaiQueueTest(unittest.TestCase):
    """Loa hết bài: Queue của loa tích đầu tiên đi TRƯỚC hàng đợi phiên."""

    def setUp(self) -> None:
        from services.youtube_phat import dich_vu, phat_ha, tu_chuyen_bai

        self.phat_ha, self.tu = phat_ha, tu_chuyen_bai
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        (Path(self._tmp.name) / "integration_token").write_text("token-thu", encoding="utf-8")
        dich_vu._reset_for_tests(Path(self._tmp.name))
        self.addCleanup(dich_vu._reset_for_tests, Path(self._tmp.name))
        tu_chuyen_bai._theo_doi.clear()
        self.addCleanup(tu_chuyen_bai._theo_doi.clear)

    def _het_bai(self, phien: dict) -> list[str]:
        trang_thai = {"trang_thai": "playing", "vi_tri": 190.0, "thoi_luong": 200.0}
        with patch.object(self.phat_ha, "cac_phien", return_value=[phien]), \
             patch.object(self.phat_ha, "danh_sach", side_effect=lambda dung_bo_dem=True: [
                 {"entity_id": LOA, "youtube": "am_thanh", **trang_thai}]), \
             patch.object(self.phat_ha, "dang_phat_bai", return_value=True):
            self.tu.mot_vong(100.0)
            trang_thai.update(trang_thai="idle")
            return self.tu.mot_vong(105.0)

    def test_queue_thang_hang_doi_phien_roi_nhuong_lai(self) -> None:
        phien = {"session_id": "s1", "controller": self.phat_ha.CONTROLLER, "output_entity_ids": [LOA],
                 "item": {"id": "kJQP7kiw5Fa", "source": "youtube", "duration": 200},
                 "queue": {"index": 0, "items": [bai(0), bai(1)]}}
        hang_cho.kho().doi({"key": LOA, "action": "add", "items": [bai(5)]})
        with patch.object(self.phat_ha, "phat_bai_trong_phien") as tu_queue, \
             patch.object(self.phat_ha, "chuyen_bai") as tu_phien:
            self.assertEqual(self._het_bai(phien), ["s1"])
            self.assertEqual(tu_queue.call_args.args[1]["title"], "Bài 5")
            tu_phien.assert_not_called()
            # Queue hết: phiên chạy tiếp như cũ.
            self.tu._theo_doi.clear()
            self.assertEqual(self._het_bai(phien), ["s1"])
            tu_phien.assert_called_once_with("s1", 1)


if __name__ == "__main__":
    unittest.main()
