"""Xem — soát — xoá kho thuật ngữ, để người dùng tự quản không cần mở máy chủ.

Trước đây API chỉ trả về bảng sửa tay cộng SỐ ĐẾM mỗi lĩnh vực, nên người dùng
không có cách nào biết máy tự học được từ gì; một từ học sai (đo thật: "operational
voltage" → "điện áp điều khiển") nằm im kéo mọi bản dịch sau đi lệch, mà chỉ phát
hiện được bằng cách mở tệp trên máy chủ ra đọc.

Bộ test giữ bốn tính chất:

  1. ``liet_ke`` gộp đủ ba tầng và ghi đúng nguồn, theo đúng thứ tự ưu tiên lúc
     dịch (sửa tay > tự học > bản chuẩn) — cái UI hiện ra phải là cái thật sự
     được dùng.
  2. ``xoa_hoc`` bỏ được mục tự học (``ghi_hoc`` cố ý không đè, nên không xoá
     thì học sai một lần là sai mãi).
  3. ``soat_thuat_ngu`` chỉ trả về mục NÊN SỬA, và lọc sạch rác của model: term
     bịa ra ngoài lô, và "sửa" thành đúng cái đang có.
  4. Model hỏng → trả rỗng, KHÔNG bao giờ tự ghi vào từ điển.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.config as cfg
from services import thuat_ngu as tn
from services import dich_llm as dl


class KhoTamTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._data = Path(self._tmp.name)
        (self._data / "glossary").mkdir(parents=True)
        self._ghi("en.json", {"ky_thuat": {"circuit breaker": "máy cắt",
                                           "busbar": "thanh cái"}})
        self._ghi("en.hoc.json", {"ky_thuat": {"operational voltage": "điện áp điều khiển",
                                               "shunt release": "cuộn cắt"}})
        self._ghi("en.sua.json", {"ky_thuat": {"busbar": "thanh dẫn"}})
        self._cu = cfg.DATA_DIR
        cfg.DATA_DIR = self._data
        tn._reset_cache_cho_test()

    def tearDown(self) -> None:
        cfg.DATA_DIR = self._cu
        tn._reset_cache_cho_test()
        self._tmp.cleanup()

    def _ghi(self, ten: str, noi_dung: dict) -> None:
        (self._data / "glossary" / ten).write_text(
            json.dumps(noi_dung, ensure_ascii=False), encoding="utf-8")

    # ── liệt kê ─────────────────────────────────────────────────────────────
    def test_liet_ke_gop_ba_tang_va_ghi_dung_nguon(self):
        ra = {m["term"]: m for m in tn.liet_ke("en", "ky_thuat")}
        self.assertEqual(ra["circuit breaker"]["nguon"], "chuan")
        self.assertEqual(ra["shunt release"]["nguon"], "hoc")
        # busbar có ở CẢ bản chuẩn lẫn sửa tay → sửa tay thắng, đúng như lúc dịch
        self.assertEqual(ra["busbar"]["nguon"], "sua")
        self.assertEqual(ra["busbar"]["vi"], "thanh dẫn")

    def test_liet_ke_linh_vuc_trong_thi_rong(self):
        self.assertEqual(tn.liet_ke("en", "y_khoa"), [])

    # ── xoá mục tự học ──────────────────────────────────────────────────────
    def test_xoa_hoc_bo_duoc_muc_hoc_sai(self):
        self.assertTrue(tn.xoa_hoc("en", "ky_thuat", "operational voltage"))
        con = {m["term"] for m in tn.liet_ke("en", "ky_thuat")}
        self.assertNotIn("operational voltage", con)
        self.assertIn("shunt release", con)   # không đụng mục khác

    def test_xoa_hoc_khong_dung_toi_ban_chuan(self):
        self.assertFalse(tn.xoa_hoc("en", "ky_thuat", "circuit breaker"))
        self.assertIn("circuit breaker",
                      {m["term"] for m in tn.liet_ke("en", "ky_thuat")})

    def test_xoa_hoc_xong_thi_hoc_lai_duoc(self):
        # ghi_hoc không đè mục đã có; xoá đi thì lượt học sau mới có cơ hội.
        self.assertEqual(tn.ghi_hoc("en", {"ky_thuat": {"operational voltage": "điện áp vận hành"}}), 0)
        tn.xoa_hoc("en", "ky_thuat", "operational voltage")
        self.assertEqual(tn.ghi_hoc("en", {"ky_thuat": {"operational voltage": "điện áp vận hành"}}), 1)

    # ── soát bằng LLM ───────────────────────────────────────────────────────
    def test_soat_chi_tra_ve_muc_nen_sua(self):
        cap = [("operational voltage", "điện áp điều khiển"),
               ("shunt release", "cuộn cắt")]
        raw = json.dumps([{"src": "operational voltage", "vi": "điện áp vận hành",
                           "ly_do": "điều khiển là control voltage, khác nghĩa"}])
        ra = dl.soat_thuat_ngu(cap, "ky_thuat", "en", "m", lambda m, msg: raw)
        self.assertEqual(len(ra), 1)
        self.assertEqual(ra[0]["term"], "operational voltage")
        self.assertEqual(ra[0]["hien_tai"], "điện áp điều khiển")
        self.assertEqual(ra[0]["de_xuat"], "điện áp vận hành")
        self.assertIn("control voltage", ra[0]["ly_do"])

    def test_soat_bo_term_model_bia_ra_ngoai_lo(self):
        cap = [("shunt release", "cuộn cắt")]
        raw = json.dumps([{"src": "khong-he-co-trong-lo", "vi": "gì đó"}])
        self.assertEqual(dl.soat_thuat_ngu(cap, "ky_thuat", "en", "m",
                                           lambda m, msg: raw), [])

    def test_soat_bo_de_xuat_trung_cai_dang_dung(self):
        cap = [("shunt release", "cuộn cắt")]
        raw = json.dumps([{"src": "shunt release", "vi": "  Cuộn Cắt  "}])
        self.assertEqual(dl.soat_thuat_ngu(cap, "ky_thuat", "en", "m",
                                           lambda m, msg: raw), [])

    def test_soat_model_hong_thi_rong_khong_ghi_gi(self):
        def hong(m, msg):
            raise dl.LoiLLM("sập")
        truoc = tn.doc_hoc("en")
        self.assertEqual(dl.soat_thuat_ngu([("shunt release", "cuộn cắt")],
                                           "ky_thuat", "en", "m", hong), [])
        self.assertEqual(tn.doc_hoc("en"), truoc)

    def test_soat_khong_co_model_thi_rong(self):
        self.assertEqual(dl.soat_thuat_ngu([("a", "b")], "ky_thuat", "en", "",
                                           lambda m, msg: "[]"), [])


if __name__ == "__main__":
    unittest.main()
