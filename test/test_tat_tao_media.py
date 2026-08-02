"""Đường tắt TẠO ẢNH / TẠO VIDEO: nhận ý bằng từ khoá, hiện menu ngay.

VÌ SAO CẦN: menu chọn model chỉ là ghép chuỗi từ danh sách model đã cache — gần
như tức thì. Nhưng để tới được nó, mỗi câu phải đi qua một lượt gọi model định
tuyến. Đo thật 01–02/08 trên máy chủ (bảng `runs`):

    bước hiện menu, tạo ảnh  :  9,2s · 12,0s · 11,8s · 13,5s
    bước hiện menu, tạo video:  6s   · 7s    · 13s   · 14s
    "xin chào" (KHÔNG tool, KHÔNG menu): 11,2s

Câu chào không dùng tool nào cũng mất 11,2 giây ⇒ toàn bộ thời gian là độ trễ của
model, không phải của việc dựng menu. Nên bỏ được lượt gọi đó là menu ra ngay.

Bất biến quan trọng nhất ở đây là ĐỪNG BẮT SAI. Bắt nhầm hai loại câu này thì hỏng
nặng hơn là chậm:

  1. Nội dung NÚT BẤM của chính menu ("tạo video bằng model flow/veo-3.1-lite: …").
     Bắt nó = hiện lại menu = lặp vô tận, người dùng không bao giờ tạo được gì.
  2. Câu nói về media ĐÃ CÓ ("xóa ảnh vừa tạo", "gửi lại ảnh", "vừa tạo bằng model
     gì") — đường tắt thư viện lo, đừng giành.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

GOC = pathlib.Path(__file__).resolve().parents[1]
NGUON = GOC / "services" / "agent" / "orchestrator.py"

_TEN_CAN = ("_TAT_TAO_MEDIA", "_KHONG_PHAI_TAO_MOI", "_TAT_VE_ANH", "_BO_DAU_MO_TA",
            "_NUT_MENU_A", "_NUT_MENU_B")
_HAM_CAN = ("_la_yeu_cau_tao_media", "_doc_nut_menu_media")


def _nap_ns() -> dict:
    """Nạp RIÊNG bộ nhận ý — import cả orchestrator sẽ kéo theo config/DB/model."""
    src = NGUON.read_text("utf-8")
    tree = ast.parse(src)
    phan = ["from __future__ import annotations", "import re"]
    for n in tree.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in _TEN_CAN:
            phan.append(ast.get_source_segment(src, n))
        if isinstance(n, ast.FunctionDef) and n.name in _HAM_CAN:
            phan.append(ast.get_source_segment(src, n))
    ns: dict = {}
    exec("\n".join(phan), ns)
    return ns


def _nap():
    return _nap_ns()["_la_yeu_cau_tao_media"]


class NhanDungYTests(unittest.TestCase):
    def setUp(self):
        self.f = _nap()

    def test_video_lay_dung_mo_ta(self):
        self.assertEqual(self.f("Tạo video cảnh biển hoàng hôn"),
                         ("video", "cảnh biển hoàng hôn"))
        self.assertEqual(self.f("em tạo cho anh 1 video về mưa rơi"),
                         ("video", "mưa rơi"))

    def test_anh_lay_dung_mo_ta(self):
        self.assertEqual(self.f("tạo ảnh con mèo"), ("image", "con mèo"))
        self.assertEqual(self.f("hãy vẽ hình ảnh: rừng thông buổi sớm"),
                         ("image", "rừng thông buổi sớm"))

    def test_ve_khong_can_chu_anh(self):
        """'vẽ một cô gái' là xin ảnh, rõ như 'tạo ảnh cô gái'."""
        self.assertEqual(self.f("vẽ một cô gái mặc áo dài"),
                         ("image", "một cô gái mặc áo dài"))

    def test_khong_dau_van_nhan_khi_co_chu_loai(self):
        self.assertEqual(self.f("tao anh con meo"), ("image", "con meo"))

    def test_mo_ta_rong_van_hop_le(self):
        """Capability tự hỏi lại 'muốn tạo gì' — vẫn nhanh hơn qua model."""
        self.assertEqual(self.f("Tạo video"), ("video", ""))
        self.assertEqual(self.f("tạo ảnh"), ("image", ""))

    def test_mo_ta_dai_van_nhan(self):
        cau = ("Tạo video Một chàng trai, một cô gái yêu nhau đang vui đùa, "
               "nữ cầm vòi tưới cây xịt vào nam")
        got = self.f(cau)
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "video")
        self.assertTrue(got[1].startswith("Một chàng trai"))


class KhongDuocBatSaiTests(unittest.TestCase):
    def setUp(self):
        self.f = _nap()

    def test_noi_dung_nut_menu_phai_bo_qua(self):
        """Bắt nó = hiện lại menu = lặp vô tận."""
        for c in ("tạo video bằng model flow/veo-3.1-lite: cảnh biển",
                  "tạo video bằng model flow/omni-flash params duration=6: x",
                  "tạo ảnh bằng model flow/banana-2: con mèo"):
            self.assertIsNone(self.f(c), c)

    def test_noi_ve_media_da_co_phai_bo_qua(self):
        for c in ("Bạn vừa tạo video bằng model gì", "xóa ảnh vừa tạo",
                  "gửi lại ảnh", "tải về video vừa rồi", "xoá hết ảnh"):
            self.assertIsNone(self.f(c), c)

    def test_capability_khac_phai_bo_qua(self):
        """'tạo' còn dùng cho automation / nhạc / nhắc việc."""
        for c in ("tạo automation bật đèn", "tạo nhạc vui",
                  "tạo nhắc việc 7h sáng", "tạo tài khoản mới"):
            self.assertIsNone(self.f(c), c)

    def test_cau_hoi_va_chao_phai_bo_qua(self):
        for c in ("xin chào", "cho tôi biết tạo ảnh thế nào",
                  "hôm nay thế nào", ""):
            self.assertIsNone(self.f(c), c)


class NutBamMenuRaTucThiTests(unittest.TestCase):
    """Nội dung nút bấm do CHÍNH code sinh nên phân tích được chắc chắn.

    Bắt được nó thì cả ba bước — chọn model → thời lượng → số lượng — đều ra tức
    thì, thay vì mỗi bước một lượt gọi model ~10 giây. Chuỗi trong test copy đúng
    khuôn `capabilities.py` sinh ra (dòng 141, 179/184, 449, 460, 474).
    """

    def setUp(self):
        self.f = _nap_ns()["_doc_nut_menu_media"]

    def test_chon_model_khong_params(self):
        self.assertEqual(
            self.f("tạo video bằng model flow/veo-3.1-lite: cảnh biển hoàng hôn"),
            ("video", {"prompt": "cảnh biển hoàng hôn", "model": "flow/veo-3.1-lite"}))

    def test_chon_thoi_luong(self):
        got = self.f("tạo video bằng model flow/omni-flash params duration=6: mưa rơi")
        self.assertEqual(got, ("video", {"prompt": "mưa rơi",
                                         "model": "flow/omni-flash",
                                         "params": {"duration": "6"}}))

    def test_chon_so_luong_kem_thoi_luong(self):
        got = self.f("tạo video bằng model flow/omni-flash params count=3 duration=10: mưa")
        self.assertEqual(got[1]["params"], {"count": "3", "duration": "10"})

    def test_menu_anh_va_menu_tham_so(self):
        self.assertEqual(self.f("vẽ bằng model flow/banana-2: con mèo mướp"),
                         ("image", {"prompt": "con mèo mướp", "model": "flow/banana-2"}))
        # _param_choice_menu: mô tả nằm TRONG nháy, params ở cuối, KHÔNG có dấu ':'
        got = self.f("vẽ 'con mèo mướp' bằng model gpt-image-2 params size=1024x1024 quality=hd")
        self.assertEqual(got, ("image", {"prompt": "con mèo mướp",
                                         "model": "gpt-image-2",
                                         "params": {"size": "1024x1024",
                                                    "quality": "hd"}}))

    def test_bang_mac_dinh_CO_Y_khong_bat(self):
        """`_h_generate_video` chỉ dùng model mặc định khi ctx có auto_approve, mà
        bật cờ đó ở đây sẽ bỏ luôn các bước hỏi thời lượng/số lượng — đổi hành vi."""
        self.assertIsNone(self.f("tạo video bằng mặc định: cảnh biển"))

    def test_cau_nguoi_go_va_cau_hoi_khong_lot_vao_day(self):
        for c in ("tạo video cảnh biển", "xin chào",
                  "Bạn vừa tạo video bằng model gì"):
            self.assertIsNone(self.f(c), c)


class DuocNoiVaoOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.code = "\n".join(
            l for l in NGUON.read_text("utf-8").splitlines()
            if not l.lstrip().startswith("#"))

    def test_goi_dung_capability_theo_loai(self):
        i = self.code.index("_nut = _doc_nut_menu_media(user_text)")
        khuc = self.code[i:i + 1800]
        self.assertIn('"generate_video" if _kind == "video" else "generate_image"', khuc)

    def test_van_di_qua_bo_loc_chuc_nang(self):
        """Đường tắt rút ngắn đường đi, KHÔNG mở thêm quyền."""
        i = self.code.index("_nut = _doc_nut_menu_media(user_text)")
        khuc = self.code[i:i + 1800]
        self.assertIn("allow is None or _nhom in allow", khuc)

    def test_dat_sau_duong_tat_thu_vien(self):
        """'xóa ảnh vừa tạo' phải được đường tắt thư viện tiêu thụ trước."""
        self.assertLess(self.code.index("agent_tat_media"),
                        self.code.index("agent_tat_tao_media"))


if __name__ == "__main__":
    unittest.main()
