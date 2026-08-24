"""Lõi glossary + hậu kỳ thay thuật ngữ (không LLM) — services/thuat_ngu.py.

Test đúng phần TẤT ĐỊNH: đọc glossary, đoán lĩnh vực bằng thống kê, và thay
chuỗi NLLB đã dịch bằng thuật ngữ VI chuẩn. Không chạm mạng/máy dịch: hàm
``render_nllb`` được giả lập.
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

_GLOSSARY_EN = {
    "cong_nghe": {
        "cache": "bộ nhớ đệm",
        "buffer": "vùng đệm",
        "compiler": "trình biên dịch",
        "thread": "luồng",
        "machine learning": "học máy",
    },
    "y_khoa": {
        "cell": "tế bào",
        "tissue": "mô",
        "artery": "động mạch",
    },
}


class ThuatNguTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._data = Path(self._tmp.name)
        (self._data / "glossary").mkdir(parents=True)
        (self._data / "glossary" / "en.json").write_text(
            json.dumps(_GLOSSARY_EN, ensure_ascii=False), encoding="utf-8")
        self._cu = cfg.DATA_DIR
        cfg.DATA_DIR = self._data
        tn._reset_cache_cho_test()

    def tearDown(self) -> None:
        cfg.DATA_DIR = self._cu
        tn._reset_cache_cho_test()
        self._tmp.cleanup()

    # ── đoán lĩnh vực ────────────────────────────────────────────────────────
    def test_doan_linh_vuc_du_nguong(self):
        # 4 term công nghệ (cache/buffer/compiler/thread) ≥ ngưỡng 3.
        lv = tn.doan_linh_vuc(
            "We optimize the CACHE and buffer using a compiler for the thread", "en")
        self.assertEqual(lv, ["cong_nghe"])

    def test_doan_linh_vuc_duoi_nguong_thi_rong(self):
        # chỉ 1 term → dưới ngưỡng → không đoán lĩnh vực nào.
        self.assertEqual(tn.doan_linh_vuc("just one cache here", "en"), [])

    def test_khong_co_glossary_tra_rong(self):
        self.assertEqual(tn.doan_linh_vuc("bất kỳ", "ja"), [])

    # ── hậu kỳ thay thuật ngữ ────────────────────────────────────────────────
    def test_thay_bang_thuat_ngu_chuan(self):
        # NLLB dịch "cache" thành "bộ đệm ẩn"; hậu kỳ nắn về "bộ nhớ đệm".
        render = {"cache": "bộ đệm ẩn"}
        ra = tn.hau_ky_thuat_ngu(
            ban_dich="xóa bộ đệm ẩn cho nhanh",
            nguon="clear the cache for speed",
            src="en", linh_vuc=["cong_nghe"],
            render_nllb=lambda t: render.get(t, t))
        self.assertEqual(ra, "xóa bộ nhớ đệm cho nhanh")

    def test_khong_thay_khi_term_vang_o_nguon(self):
        # "cache" KHÔNG có trong câu nguồn → dù chuỗi "bộ đệm ẩn" tình cờ có
        # trong bản dịch cũng không đụng.
        ra = tn.hau_ky_thuat_ngu(
            ban_dich="cái bộ đệm ẩn kia",
            nguon="that thing over there",
            src="en", linh_vuc=["cong_nghe"],
            render_nllb=lambda t: "bộ đệm ẩn")
        self.assertEqual(ra, "cái bộ đệm ẩn kia")

    def test_cum_dai_thay_truoc_khong_bi_cat(self):
        # "machine learning" phải nắn nguyên cụm, không bị "thread"/"cache" xen.
        render = {"machine learning": "học tập máy móc"}
        ra = tn.hau_ky_thuat_ngu(
            ban_dich="khoá học tập máy móc rất hay",
            nguon="the machine learning course",
            src="en", linh_vuc=["cong_nghe"],
            render_nllb=lambda t: render.get(t, t))
        self.assertEqual(ra, "khoá học máy rất hay")

    def test_render_moi_term_mot_lan_nho_cache(self):
        goi = {"n": 0}
        def render(t):
            goi["n"] += 1
            return "bộ đệm ẩn"
        cache: dict[str, str] = {}
        for _ in range(3):
            tn.hau_ky_thuat_ngu(
                "xóa bộ đệm ẩn", "clear the cache", "en", ["cong_nghe"],
                render, cache_render=cache)
        self.assertEqual(goi["n"], 1)  # 'cache' chỉ dịch-đơn một lần

    def test_render_giong_chuan_thi_bo_qua(self):
        # NLLB đã ra đúng "bộ nhớ đệm" → không cần thay, không đổi gì.
        ra = tn.hau_ky_thuat_ngu(
            "xóa bộ nhớ đệm", "clear the cache", "en", ["cong_nghe"],
            render_nllb=lambda t: "bộ nhớ đệm")
        self.assertEqual(ra, "xóa bộ nhớ đệm")


if __name__ == "__main__":
    unittest.main()
