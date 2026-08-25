"""Bước LLM tùy chọn + tự chắt lọc thuật ngữ — services/dich_llm.py.

Không chạm mạng/GPU: hàm ``goi_model`` được giả lập. Kiểm phần TẤT ĐỊNH: rã số
dòng, fallback khi lệch, bóc JSON thuật ngữ, ghi_hoc gộp đúng, và glue trong
video_dich tôn trọng công tắc.
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
from services import video_dich as vd

_GLOSSARY_EN = {"cong_nghe": {"cache": "bộ nhớ đệm", "compiler": "trình biên dịch",
                              "thread": "luồng"}}


class _DataTmp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        data = Path(self._tmp.name)
        (data / "glossary").mkdir(parents=True)
        (data / "glossary" / "en.json").write_text(
            json.dumps(_GLOSSARY_EN, ensure_ascii=False), encoding="utf-8")
        self._cu = cfg.DATA_DIR
        cfg.DATA_DIR = data
        self._data = data
        tn._reset_cache_cho_test()

    def tearDown(self) -> None:
        cfg.DATA_DIR = self._cu
        tn._reset_cache_cho_test()
        self._tmp.cleanup()


class ChinhTests(_DataTmp):
    def test_rã_dong_so_dung(self):
        self.assertEqual(dl._tach_dong_so("1. a\n2. b\n3. c", 3), ["a", "b", "c"])

    def test_rã_lech_so_dong_tra_none(self):
        self.assertIsNone(dl._tach_dong_so("1. a\n2. b", 3))  # thiếu dòng 3

    def test_chinh_nhan_ket_qua(self):
        cap = [("clear the cache", "xóa bộ nhớ đệm"), ("run it", "chạy nó")]
        def goi(model, messages):
            return "1. xoá bộ nhớ đệm cho nhanh\n2. chạy chương trình"
        ra = dl.chinh(cap, ["cong_nghe"], "en", "fake/model", goi)
        self.assertEqual(ra, ["xoá bộ nhớ đệm cho nhanh", "chạy chương trình"])

    def test_chinh_lech_dong_giu_nhap(self):
        cap = [("a", "nháp a"), ("b", "nháp b")]
        ra = dl.chinh(cap, ["cong_nghe"], "en", "fake/model",
                      lambda m, msg: "1. chỉ một dòng")     # lệch → giữ nháp
        self.assertEqual(ra, ["nháp a", "nháp b"])

    def test_chinh_model_loi_giu_nhap(self):
        cap = [("a", "nháp a")]
        def goi(m, msg):
            raise dl.LoiLLM("hết lượt")
        self.assertEqual(dl.chinh(cap, ["cong_nghe"], "en", "x", goi), ["nháp a"])

    def test_chinh_khong_model_giu_nhap(self):
        cap = [("a", "nháp a")]
        self.assertEqual(dl.chinh(cap, ["cong_nghe"], "en", "",
                                  lambda *a: "1. x"), ["nháp a"])


class HocTests(_DataTmp):
    def test_boc_json_co_rao_code(self):
        raw = '```json\n[{"src":"kernel","vi":"nhân"}]\n```'
        self.assertEqual(dl._rã_json_terms(raw), [{"src": "kernel", "vi": "nhân"}])

    def test_hoc_thuat_ngu_gan_linh_vuc_chinh(self):
        cap = [("the kernel panics", "nhân sụp")]
        def goi(m, msg):
            return '[{"src":"kernel","vi":"nhân hệ điều hành"},{"src":"","vi":"x"}]'
        ra = dl.hoc_thuat_ngu(cap, ["cong_nghe", "y_khoa"], "en", "fake", goi)
        self.assertEqual(ra, {"cong_nghe": {"kernel": "nhân hệ điều hành"}})

    def test_chinh_va_hoc_ghi_vao_hoc_json(self):
        cap = [("the kernel is fast", "nhân nhanh")]
        def goi(model, messages):
            # gọi 1: chỉnh (1 dòng); gọi 2: chắt lọc JSON
            if messages[0]["content"].startswith("Bạn là biên tập"):
                return "1. nhân chạy nhanh"
            return '[{"src":"kernel","vi":"nhân hệ điều hành"}]'
        ra = dl.chinh_va_hoc(cap, ["cong_nghe"], "en", "fake/model", goi)
        self.assertEqual(ra, ["nhân chạy nhanh"])
        # đã ghi vào en.hoc.json và thuat_ngu đọc gộp được
        hoc = json.loads((self._data / "glossary" / "en.hoc.json").read_text("utf-8"))
        self.assertEqual(hoc["cong_nghe"]["kernel"], "nhân hệ điều hành")
        goi_glo = tn.nap_glossary("en")
        self.assertEqual(goi_glo["cong_nghe"]["kernel"], "nhân hệ điều hành")
        self.assertEqual(goi_glo["cong_nghe"]["cache"], "bộ nhớ đệm")  # curated còn


class GhiHocTests(_DataTmp):
    def test_khong_de_len_curated(self):
        # 'cache' đã curated → ghi_hoc bỏ qua, chỉ thêm term mới.
        them = tn.ghi_hoc("en", {"cong_nghe": {"cache": "SAI", "socket": "ổ cắm"}})
        self.assertEqual(them, 1)
        goi = tn.nap_glossary("en")
        self.assertEqual(goi["cong_nghe"]["cache"], "bộ nhớ đệm")   # curated thắng
        self.assertEqual(goi["cong_nghe"]["socket"], "ổ cắm")

    def test_khong_trung_lap_trong_hoc(self):
        tn.ghi_hoc("en", {"cong_nghe": {"socket": "ổ cắm"}})
        them = tn.ghi_hoc("en", {"cong_nghe": {"socket": "ổ khác"}})  # đã có
        self.assertEqual(them, 0)


class GlueCongTacTests(_DataTmp):
    """Glue trong video_dich đọc config dich_llm và tôn trọng công tắc."""

    def _nhom(self):
        return [vd.Doan(0.0, 1.0, "clear the cache"),
                vd.Doan(1.0, 2.0, "use a compiler")]

    def test_tat_thi_giu_nguyen_khong_goi_model(self):
        cu = cfg.config.get
        cfg.config.get = lambda: {}          # không có dich_llm
        try:
            ra = vd._chinh_llm_neu_bat(self._nhom(), ["x", "y"], "en", "vi")
        finally:
            cfg.config.get = cu
        self.assertEqual(ra, ["x", "y"])

    def test_bat_thi_goi_model(self):
        from services.agent import runtime as rt
        cu_get, cu_call = cfg.config.get, rt.call_model
        cfg.config.get = lambda: {"dich_llm": {"bat": True, "model": "fake/m"}}
        rt.call_model = lambda model, messages, **k: {
            "choices": [{"message": {"content": "1. xoá bộ nhớ đệm\n2. dùng trình biên dịch"}}]}
        try:
            ra = vd._chinh_llm_neu_bat(self._nhom(), ["a", "b"], "en", "vi")
        finally:
            cfg.config.get, rt.call_model = cu_get, cu_call
        self.assertEqual(ra, ["xoá bộ nhớ đệm", "dùng trình biên dịch"])


if __name__ == "__main__":
    unittest.main()
