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



class PivotTests(unittest.TestCase):
    """JA/ZH pivot qua tiếng Anh: term nguồn → nghĩa Anh → glossary Anh (lĩnh
    vực + thuật ngữ VI)."""

    EN = {
        "cong_nghe": {"cache": "bộ nhớ đệm", "algorithm": "thuật toán"},
        "y_khoa": {"cell": "tế bào"},
    }

    def _idx(self):
        return bg.chi_muc_en(self.EN)

    def test_cc_cedict_zh_pivot(self):
        dong = [
            "# CC-CEDICT sample",
            "高速緩存 高速缓存 [gao1 su4 huan3 cun2] /cache/buffer memory/",
            "算法 算法 [suan4 fa3] /algorithm/",
            "你好 你好 [ni3 hao3] /hello/hi/",   # 'hello' không trong glossary → bỏ
        ]
        store = bg.nap_cc_cedict(dong, self._idx())
        self.assertEqual(store["cong_nghe"].get("高速缓存"), "bộ nhớ đệm")
        self.assertEqual(store["cong_nghe"].get("算法"), "thuật toán")
        tat_ca = {t for b in store.values() for t in b}
        self.assertNotIn("你好", tat_ca)

    def test_freedict_jpn_ja_pivot(self):
        import io
        tei = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
            '<entry><form><orth>算法</orth></form>'
            '  <sense><cit type="trans" xml:lang="en"><quote>algorithm</quote></cit>'
            '         <cit type="example"><quote>not a translation</quote></cit></sense>'
            '</entry>'
            '<entry><form><orth>細胞</orth></form>'
            '  <sense><cit type="trans"><quote>cell</quote></cit></sense></entry>'
            '</body></text></TEI>'
        )
        store = bg.nap_freedict_jpn(io.StringIO(tei), self._idx())
        self.assertEqual(store["cong_nghe"].get("算法"), "thuật toán")
        self.assertEqual(store["y_khoa"].get("細胞"), "tế bào")
        # 'not a translation' (cit example) không được coi là nghĩa
        tat_ca_vi = {v for b in store.values() for v in b.values()}
        self.assertEqual(tat_ca_vi, {"thuật toán", "tế bào"})



class OmwTests(unittest.TestCase):
    """OMW: gióng synset KO↔VI, lĩnh vực lấy theo từ VI qua glossary EN."""

    EN = {"y_khoa": {"cell": "tế bào"}, "sinh_hoc": {"organism": "sinh vật"}}

    def test_chi_muc_vi_domain(self):
        idx = bg.chi_muc_vi_domain(self.EN)
        self.assertEqual(idx["tế bào"], {"y_khoa"})
        self.assertEqual(idx["sinh vật"], {"sinh_hoc"})

    def test_doc_tab_gach_duoi_va_chu_thich(self):
        d = bg.doc_omw_tab(["# chú thích", "00010-n\tkor:lemma\tNew_York"])
        self.assertEqual(d["00010-n"], {"New York"})

    def test_nap_omw_ko(self):
        vi_dom = bg.chi_muc_vi_domain(self.EN)
        kor = [
            "00001-n\tkor:lemma\t세포",
            "00002-n\tkor:lemma\t유기체",
            "00003-n\tkor:lemma\t의자",   # synset 3: từ VI không phải thuật ngữ → bỏ
        ]
        vie = [
            "# Vietnamese Wordnet",
            "00001-n\tvie:lemma\ttế bào",
            "00002-n\tvie:lemma\tsinh vật",
            "00003-n\tvie:lemma\tcái ghế",
        ]
        store = bg.nap_omw(kor, vie, vi_dom)
        self.assertEqual(store["y_khoa"].get("세포"), "tế bào")
        self.assertEqual(store["sinh_hoc"].get("유기체"), "sinh vật")
        tat_ca = {t for b in store.values() for t in b}
        self.assertNotIn("의자", tat_ca)


if __name__ == "__main__":
    unittest.main()


class NoiLongTests(unittest.TestCase):
    """Cờ hạ ngưỡng lọc: mục đa lĩnh vực, dịch không rõ sense."""

    ENTRY = {
        "word": "port", "pos": "noun", "lang_code": "en",
        "senses": [{"topics": ["computing"]}, {"topics": ["nautical"]}],
        # dịch KHÔNG ghi sense, mà mục thuộc HAI lĩnh vực.
        "translations": [{"code": "vi", "word": "cổng", "sense": ""}],
    }

    def test_chat_thi_bo(self):
        store = bg.nap_kaikki_en([json.dumps(self.ENTRY, ensure_ascii=False)])
        tat_ca = {t for b in store.values() for t in b}
        self.assertNotIn("port", tat_ca)   # nhập nhằng → bỏ

    def test_noi_long_gan_moi_linh_vuc(self):
        store = bg.nap_kaikki_en([json.dumps(self.ENTRY, ensure_ascii=False)],
                                 noi_long=True)
        self.assertEqual(store["cong_nghe"].get("port"), "cổng")
        self.assertEqual(store["hang_hai"].get("port"), "cổng")


class OmwGiaCoTests(unittest.TestCase):
    """OMW cho ja/zh phải GỘP vào file pivot sẵn có, không ghi đè."""

    def test_omw_gop_khong_de_pivot(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            thu = Path(d)
            (thu / "en.json").write_text(json.dumps(
                {"y_khoa": {"cell": "tế bào"}}, ensure_ascii=False), encoding="utf-8")
            # zh.json "pivot" đã có sẵn 1 term công nghệ.
            (thu / "zh.json").write_text(json.dumps(
                {"cong_nghe": {"算法": "thuật toán"}}, ensure_ascii=False), encoding="utf-8")
            (thu / "cmn.tab").write_text(
                "00001-n\tcmn:lemma\t细胞\n", encoding="utf-8")
            (thu / "vie.tab").write_text(
                "00001-n\tvie:lemma\ttế bào\n", encoding="utf-8")
            bg.main(["--omw-src", str(thu / "cmn.tab"),
                     "--omw-vi", str(thu / "vie.tab"),
                     "--omw-lang", "zh", "--out", str(thu)])
            zh = json.loads((thu / "zh.json").read_text(encoding="utf-8"))
            self.assertEqual(zh["cong_nghe"]["算法"], "thuật toán")  # pivot còn
            self.assertEqual(zh["y_khoa"]["细胞"], "tế bào")          # OMW thêm

