"""Đoạn nối glossary trong video_dich: NLLB (giả lập) → hậu kỳ thuật ngữ.

Không chạm máy dịch/GPU: hàm render (``translate_service.translate``) được thay
bằng bảng tra cố định, nên test kiểm ĐÚNG phần glue tất định — đoán lĩnh vực một
lần, thay thuật ngữ từng câu, và cổng lọc theo tiếng nguồn.
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
from services import video_dich as vd

_GLOSSARY_EN = {
    "cong_nghe": {
        "cache": "bộ nhớ đệm",
        "compiler": "trình biên dịch",
        "thread": "luồng",
    }
}


class HauKyGlossaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        data = Path(self._tmp.name)
        (data / "glossary").mkdir(parents=True)
        (data / "glossary" / "en.json").write_text(
            json.dumps(_GLOSSARY_EN, ensure_ascii=False), encoding="utf-8")
        self._cu_data = cfg.DATA_DIR
        cfg.DATA_DIR = data
        tn._reset_cache_cho_test()
        # render giả: NLLB dịch từng thuật ngữ ra chữ gì (đếm số lần gọi).
        self._render = {"cache": "bộ đệm ẩn", "compiler": "trình biên dịch",
                        "thread": "luồng chạy"}
        self._goi = {"n": 0}
        self._cu_translate = vd.ts.translate

        def fake_translate(text, target, source="auto"):
            self._goi["n"] += 1
            return self._render.get(tn.thuong_hoa(text), text)

        vd.ts.translate = fake_translate

    def tearDown(self) -> None:
        vd.ts.translate = self._cu_translate
        cfg.DATA_DIR = self._cu_data
        tn._reset_cache_cho_test()
        self._tmp.cleanup()

    def _nhom(self):
        return [
            vd.Doan(0.0, 1.0, "clear the cache"),
            vd.Doan(1.0, 2.0, "use a compiler"),
            vd.Doan(2.0, 3.0, "spawn a thread"),
        ]

    def test_nan_thuat_ngu_dung_nganh(self):
        nhom = self._nhom()
        ban_dich = ["xóa bộ đệm ẩn", "dùng trình biên dịch", "tạo luồng chạy"]
        ra = vd.hau_ky_glossary(nhom, ban_dich, "en", "vi")
        self.assertEqual(ra[0], "xóa bộ nhớ đệm")   # cache: bộ đệm ẩn → bộ nhớ đệm
        self.assertEqual(ra[1], "dùng trình biên dịch")  # đã đúng → không đổi
        self.assertEqual(ra[2], "tạo luồng")        # thread: luồng chạy → luồng

    def test_render_nho_dem_moi_thuat_ngu_mot_lan(self):
        nhom = self._nhom() + [vd.Doan(3.0, 4.0, "flush the cache again")]
        ban_dich = ["xóa bộ đệm ẩn", "dùng trình biên dịch",
                    "tạo luồng chạy", "xả bộ đệm ẩn lần nữa"]
        vd.hau_ky_glossary(nhom, ban_dich, "en", "vi")
        # 3 thuật ngữ riêng (cache/compiler/thread) → đúng 3 lần render dù
        # 'cache' xuất hiện ở hai câu.
        self.assertEqual(self._goi["n"], 3)

    def test_nguon_auto_bo_qua_khong_goi_render(self):
        nhom = self._nhom()
        ban_dich = ["xóa bộ đệm ẩn", "dùng trình biên dịch", "tạo luồng chạy"]
        ra = vd.hau_ky_glossary(nhom, ban_dich, "auto", "vi")
        self.assertEqual(ra, ban_dich)       # nguồn không xác định → giữ nguyên
        self.assertEqual(self._goi["n"], 0)  # không đụng máy dịch

    def test_duoi_nguong_linh_vuc_giu_nguyen(self):
        nhom = [vd.Doan(0.0, 1.0, "clear the cache")]  # chỉ 1 term < ngưỡng 3
        ban_dich = ["xóa bộ đệm ẩn"]
        ra = vd.hau_ky_glossary(nhom, ban_dich, "en", "vi")
        self.assertEqual(ra, ban_dich)
        self.assertEqual(self._goi["n"], 0)

    def test_ma_tieng_glossary(self):
        self.assertEqual(vd._ma_tieng_glossary("en"), "en")
        self.assertEqual(vd._ma_tieng_glossary("JA"), "ja")
        self.assertEqual(vd._ma_tieng_glossary("zh-Hans"), "zh")
        self.assertEqual(vd._ma_tieng_glossary("ko"), "ko")
        self.assertEqual(vd._ma_tieng_glossary("auto"), "")
        self.assertEqual(vd._ma_tieng_glossary("vi"), "")
        self.assertEqual(vd._ma_tieng_glossary(""), "")


if __name__ == "__main__":
    unittest.main()
