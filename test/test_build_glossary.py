"""Trình nạp glossary từ Wiktextract — scripts/build_glossary.py.

Fixture theo ĐÚNG schema kaikki thật (đã đối chiếu mục 'cache'): mỗi mục có
``senses[].topics`` và ``translations`` kèm ``code:"vi"`` + ``sense``.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")
GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC / "scripts"))

import build_glossary as bg  # noqa: E402

# Bốn mục theo schema thật:
_FIXTURE = [
    # 1) một lĩnh vực rõ, dịch có 'sense' ghi lĩnh vực
    {"word": "cache", "pos": "noun", "lang_code": "en",
     "senses": [{"topics": ["computing", "engineering"]}],
     "translations": [
         {"code": "vi", "word": "bộ nhớ đệm", "sense": "computing: fast storage"},
         {"code": "vi", "word": "vùng nhớ đệm", "sense": "computing: fast storage"}]},
    # 2) từ đa lĩnh vực — mỗi bản dịch gắn đúng lĩnh vực qua 'sense'
    {"word": "cell", "pos": "noun", "lang_code": "en",
     "senses": [{"topics": ["biology"]}, {"topics": ["electronics"]}],
     "translations": [
         {"code": "vi", "word": "tế bào", "sense": "biology: unit of life"},
         {"code": "vi", "word": "pin", "sense": "electronics: produces electricity"},
         # dịch KHÔNG rõ nghĩa + mục đa lĩnh vực → phải BỎ
         {"code": "vi", "word": "ô", "sense": ""}]},
    # 3) từ đời thường, không lĩnh vực → phải bị lọc bỏ hoàn toàn
    {"word": "hello", "pos": "interjection", "lang_code": "en",
     "senses": [{"glosses": ["a greeting"]}],
     "translations": [{"code": "vi", "word": "xin chào", "sense": ""}]},
    # 4) một lĩnh vực + dịch không có 'sense' → dùng lĩnh vực duy nhất của mục
    {"word": "compiler", "pos": "noun", "lang_code": "en",
     "senses": [{"topics": ["computing"]}],
     "translations": [{"code": "vi", "word": "trình biên dịch", "sense": ""}]},
]


class BuildGlossaryTests(unittest.TestCase):
    def test_slug_cho_topic(self):
        self.assertEqual(bg.slug_cho_topic("computing"), "cong_nghe")
        self.assertEqual(bg.slug_cho_topic("Medicine"), "y_khoa")
        self.assertIsNone(bg.slug_cho_topic("khong-co-topic-nay"))

    def test_nap_va_phan_linh_vuc(self):
        store = bg.nap_kaikki_en(json.dumps(e, ensure_ascii=False) for e in _FIXTURE)
        # cache → công nghệ, giữ term ĐẦU
        self.assertEqual(store["cong_nghe"].get("cache"), "bộ nhớ đệm")
        # compiler dùng lĩnh vực duy nhất của mục dù dịch không ghi sense
        self.assertEqual(store["cong_nghe"].get("compiler"), "trình biên dịch")

    def test_khu_nhap_nhang_theo_sense(self):
        store = bg.nap_kaikki_en(json.dumps(e, ensure_ascii=False) for e in _FIXTURE)
        self.assertEqual(store["sinh_hoc"].get("cell"), "tế bào")
        self.assertEqual(store["cong_nghe"].get("cell"), "pin")

    def test_bo_dich_nhap_nhang_khong_ro_nghia(self):
        # 'ô' (cell) không có sense mà mục đa lĩnh vực → không được nhét vào đâu
        store = bg.nap_kaikki_en(json.dumps(e, ensure_ascii=False) for e in _FIXTURE)
        tat_ca_vi = {v for bang in store.values() for v in bang.values()}
        self.assertNotIn("ô", tat_ca_vi)

    def test_loc_tu_doi_thuong(self):
        # 'hello' không lĩnh vực → không xuất hiện ở bất kỳ slug nào
        store = bg.nap_kaikki_en(json.dumps(e, ensure_ascii=False) for e in _FIXTURE)
        tat_ca_tu = {t for bang in store.values() for t in bang}
        self.assertNotIn("hello", tat_ca_tu)

    def test_ghi_store(self):
        import tempfile
        store = bg.nap_kaikki_en(json.dumps(e, ensure_ascii=False) for e in _FIXTURE)
        with tempfile.TemporaryDirectory() as d:
            tep = bg.ghi_store(store, "en", Path(d))
            lai = json.loads(tep.read_text(encoding="utf-8"))
            self.assertEqual(lai["cong_nghe"]["cache"], "bộ nhớ đệm")
            # đọc lại được bằng chính services.thuat_ngu
            import services.config as cfg
            from services import thuat_ngu as tn
            cu = cfg.DATA_DIR
            try:
                cfg.DATA_DIR = Path(d).parent
                (Path(d).parent / "glossary").mkdir(exist_ok=True)
                bg.ghi_store(store, "en", Path(d).parent / "glossary")
                tn._reset_cache_cho_test()
                self.assertEqual(tn.doan_linh_vuc(
                    "cache compiler and cell in one talk", "en"),
                    ["cong_nghe"])
            finally:
                cfg.DATA_DIR = cu
                tn._reset_cache_cho_test()


if __name__ == "__main__":
    unittest.main()
