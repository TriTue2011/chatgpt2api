"""Video Flow: mô tả bằng TIẾNG ANH + lời thoại TIẾNG VIỆT tự sinh.

Đo thật 02/08: video tạo ra bị lồng tiếng ANH. Soi cả `flow_google.py`,
`api/veo_video.py` và bước mở rộng prompt thì KHÔNG có một dòng nào nói về âm
thanh, lời thoại hay ngôn ngữ. Veo 3.1 sinh âm thanh kèm video một cách tự nhiên,
và theo tài liệu Veo/Flow:

  · prompt tiếng Việt KHÔNG tự sinh thoại tiếng Việt — phải nói thẳng ra, không
    nói thì nó chọn tiếng Anh;
  · Flow CHỈ hỗ trợ prompt tiếng Anh;
  · cách đúng để có thoại tiếng khác: viết mô tả bằng tiếng Anh, còn CÂU CẦN NÓI
    đặt trong ngoặc kép bằng tiếng đó — Veo tự lo giọng và khớp môi;
  · lời thoại tiếng Việt DÀI dễ gây lỗi → giới hạn ngắn.

Điểm dễ bỏ sót: yêu cầu DÀI của người dùng (>70 ký tự) không đi qua
`_mo_rong_prompt_media`, nên nếu chỉ sửa hàm đó thì câu dài vẫn vào Flow nguyên
tiếng Việt và vẫn ra tiếng Anh. Vì vậy `_prompt_video_flow` chạy cho MỌI độ dài —
việc của nó là DỊCH + bổ sung âm thanh, không phải viết lại ý.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

GOC = pathlib.Path(__file__).resolve().parents[1]
NGUON = GOC / "services" / "agent" / "capabilities.py"

_HAM = ("_co_loi_thoai_viet", "_la_chuoi_loi_model", "_prompt_video_flow")


class _Cfg:
    def __init__(self, data=None):
        self.data = data or {}


def _nap(tra_ve="", loi=None, cfg_data=None):
    """Nạp RIÊNG 3 hàm + cắm sẵn phần phụ thuộc (config, call_model, logger…).

    Import cả `capabilities` sẽ kéo theo config/DB/MCP/model — biến một phép đo
    chắc chắn thành phép đo phụ thuộc môi trường.
    """
    src = NGUON.read_text("utf-8")
    tree = ast.parse(src)
    phan = ["from __future__ import annotations"]
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in _HAM:
            phan.append(ast.get_source_segment(src, n))

    goi: list[dict] = []

    def _call_model(model, msgs, timeout=None, max_tokens=None):
        goi.append({"model": model, "content": msgs[0]["content"]})
        if loi:
            raise RuntimeError(loi)
        return {"content": tra_ve}

    class _Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass

    ns = {
        "config": _Cfg(cfg_data),
        "call_model": _call_model,
        "content_of": lambda r: r.get("content", ""),
        "branch_model": lambda *a, **k: "cx/auto",
        "_channel_of": lambda ctx: "zalo",
        "logger": _Log(),
    }
    exec("\n".join(phan), ns)
    ns["_goi"] = goi
    return ns


class CongTacTests(unittest.TestCase):
    def test_mac_dinh_BAT(self):
        self.assertTrue(_nap()["_co_loi_thoai_viet"]())

    def test_tat_duoc(self):
        self.assertFalse(_nap(cfg_data={"video_loi_thoai_viet": False})["_co_loi_thoai_viet"]())


class LoiDanChoModelTests(unittest.TestCase):
    def _dan(self, cfg_data=None) -> str:
        ns = _nap(tra_ve="A cat walks. (no subtitles)", cfg_data=cfg_data)
        ns["_prompt_video_flow"]("con mèo đi trên mái nhà")
        return ns["_goi"][0]["content"]

    def test_bat_model_viet_TIENG_ANH(self):
        self.assertIn("TIẾNG ANH", self._dan())
        self.assertIn("Flow chỉ hiểu tiếng Anh", self._dan())

    def test_bat_them_thoai_TIENG_VIET_trong_ngoac_kep(self):
        dan = self._dan()
        self.assertIn("TIẾNG VIỆT", dan)
        self.assertIn("ngoặc kép", dan)
        self.assertIn("TỐI ĐA 12 TỪ", dan)   # thoại dài dễ gây lỗi

    def test_canh_khong_co_nguoi_thi_khong_thoai(self):
        self.assertIn("no dialogue, ambient sound only", self._dan())

    def test_luon_co_no_subtitles(self):
        self.assertIn("(no subtitles)", self._dan())

    def test_giu_dung_chi_tiet_nguoi_dung_neu(self):
        """Câu dài cũng đi qua đây, nên phải dặn ĐỪNG viết lại ý."""
        dan = self._dan()
        self.assertIn("GIỮ ĐÚNG mọi chi tiết", dan)
        self.assertIn("KHÔNG bỏ chi tiết nào", dan)

    def test_tat_cong_tac_thi_dan_KHONG_thoai(self):
        dan = self._dan(cfg_data={"video_loi_thoai_viet": False})
        self.assertIn("no dialogue, ambient sound only", dan)
        self.assertNotIn("TỐI ĐA 12 TỪ", dan)


class KetQuaTests(unittest.TestCase):
    def test_tra_ve_prompt_model_sinh(self):
        moi = ('A young man and woman play with water in a sunny garden, golden '
               'hour light. The woman says in Vietnamese: "Nuoc mat qua, anh oi!" '
               '(no subtitles)')
        ns = _nap(tra_ve=moi)
        self.assertEqual(ns["_prompt_video_flow"]("nam nữ vui đùa với nước"), moi)

    def test_chay_cho_MOI_do_dai(self):
        """Câu DÀI (>70 ký tự) cũng phải đi qua — nếu không, nó vào Flow nguyên
        tiếng Việt và vẫn ra thoại tiếng Anh."""
        dai = ("Một chàng trai, một cô gái yêu nhau đang vui đùa, nữ cầm vòi tưới "
               "cây nhiều tia xịt vào nam, người nam đang chạy cầm 1 gáo nước")
        self.assertGreater(len(dai), 70)
        ns = _nap(tra_ve="A couple plays with water. (no subtitles)")
        self.assertEqual(ns["_prompt_video_flow"](dai),
                         "A couple plays with water. (no subtitles)")
        self.assertEqual(len(ns["_goi"]), 1)

    def test_model_loi_thi_giu_prompt_goc(self):
        goc = "nam nữ vui đùa với nước"
        ns = _nap(loi="model sap")
        self.assertEqual(ns["_prompt_video_flow"](goc), goc)
        self.assertEqual(len(ns["_goi"]), 2)   # thử 2 lần rồi mới bỏ

    def test_model_tra_chuoi_loi_thi_giu_prompt_goc(self):
        goc = "nam nữ vui đùa với nước"
        ns = _nap(tra_ve="All providers failed: last error quota exceeded")
        self.assertEqual(ns["_prompt_video_flow"](goc), goc)

    def test_prompt_rong_thi_tra_rong_khong_goi_model(self):
        ns = _nap()
        self.assertEqual(ns["_prompt_video_flow"]("   "), "")
        self.assertEqual(len(ns["_goi"]), 0)

    def test_nhan_dien_chuoi_loi(self):
        f = _nap()["_la_chuoi_loi_model"]
        for x in ("All providers failed", "no usable account", "rate limit",
                  "Error: boom", "UNAUTHENTICATED"):
            self.assertTrue(f(x), x)
        self.assertFalse(f("A cat walks on the roof at sunset. (no subtitles)"))


class DuocNoiVaoLuongTaoVideoTests(unittest.TestCase):
    def setUp(self):
        self.code = "\n".join(
            l for l in NGUON.read_text("utf-8").splitlines()
            if not l.lstrip().startswith("#"))

    def test_flow_di_duong_moi_model_khac_giu_duong_cu(self):
        i = self.code.index('if m_low.startswith("flow/"):')
        khuc = self.code[i:i + 300]
        self.assertIn("_prompt_video_flow(prompt, ctx)", khuc)
        self.assertIn('_mo_rong_prompt_media(prompt, "video", ctx)', khuc)

    def test_chuan_bi_prompt_nam_SAU_cac_buoc_hoi(self):
        """Nếu chạy trước, mỗi lần hiện menu lại tốn một lượt gọi model."""
        self.assertLess(self.code.index("_ask_video_so_luong(prompt, model"),
                        self.code.index('if m_low.startswith("flow/"):'))


if __name__ == "__main__":
    unittest.main()
