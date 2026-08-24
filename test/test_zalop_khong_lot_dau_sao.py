"""Zalo từ chối tin nhiều vùng định dạng — lùi từng nấc, đừng bỏ sạch.

`send_message` gửi bản đầy đủ nhất trước; Zalo từ chối thì lùi một nấc rồi gửi
lại. Hai điều phải đúng ở MỌI nấc:

  * không nấc nào để lọt dấu `**` cho người dùng;
  * nấc lùi vẫn giữ được phần đậm do chính model viết, và giữ dấu "- " dạng chữ
    (Zalo chỉ tự vẽ chấm đầu dòng khi tin còn style `lst_1`; bỏ style mà đã bóc
    mất dấu gạch thì người đọc nhận một khối chữ phẳng).

Đo thật 01/08: bản tin bọc đậm cả 8 tên mục lẫn 24 tiêu đề = 32 vùng định dạng
trong một tin; Zalo từ chối, log có HAI lệnh gửi cách nhau 1 giây, và người dùng
nhắn lại "Trình bày xấu quá, bỏ ** đi". Sau khi chỉ tô đậm tên mục (8 vùng),
lệnh gửi thành công ngay lần đầu — log chỉ còn MỘT lệnh.

Đo lại 24/08 lúc 06:23: từ 05/08 mỗi dấu đầu dòng cũng thành một vùng `lst_1`,
nên bản tin 8 mục × 3 tin vọt lên 48 vùng và hỏng y như cũ — log có đúng hai
lệnh gửi cách nhau 144 ms, và người dùng nhận bản phẳng, hỏi "không thấy màu
nhấn mạnh hay in đậm tiêu đề".
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from services import zalo_personal as zp

_HUB = Path(__file__).resolve().parents[1] / "vn-mcp-hub"
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))
try:
    from src.vn import news
except Exception:
    news = None


class TestBanDuPhongKhongLotDauSao(unittest.TestCase):
    NOI_DUNG = "**⚽ Thể thao**\n- Tin một\n- Tin hai"

    def _gui_voi_ket_qua(self, ket_qua: list[dict]) -> list[dict]:
        """Gửi thử, trả về danh sách payload đã đẩy lên zalo-server."""
        da_gui: list[dict] = []

        def _gia_request(method, path, payload=None, **kw):
            if path.endswith("/sendMessageByAccount"):
                da_gui.append(payload or {})
                return ket_qua[min(len(da_gui) - 1, len(ket_qua) - 1)]
            return {"ok": True}

        with patch.object(zp, "_request", side_effect=_gia_request), \
             patch.object(zp, "_account_for_send", return_value="acc1"):
            zp.send_message("123", self.NOI_DUNG, 0, account="acc1")
        return da_gui

    def test_gui_lan_dau_thanh_cong_thi_chi_mot_lenh(self):
        da_gui = self._gui_voi_ket_qua([{"ok": True}])
        self.assertEqual(len(da_gui), 1)
        self.assertNotIn("**", str(da_gui[0]["message"]["msg"]))

    def test_moi_nac_deu_sach_dau_sao(self):
        """Chốt chính: nấc nào cũng phải sạch `**`, kể cả nấc trơn cuối cùng."""
        da_gui = self._gui_voi_ket_qua([{"ok": False}])
        self.assertGreaterEqual(len(da_gui), 2, "phải có nấc lùi")
        for i, p in enumerate(da_gui):
            chu = str(p["message"]["msg"])
            self.assertNotIn("**", chu, f"nấc {i} để lọt dấu ** cho người dùng")
            self.assertIn("Thể thao", chu, "bóc dấu sao không được bóc luôn chữ")

    def test_nac_lui_van_con_dam_va_con_dau_gach_dau_dong(self):
        """Hỏng một lần KHÔNG có nghĩa là bỏ hết định dạng.

        Nấc 2 bỏ style theo dòng (`lst_1`) nên dấu "- " phải ở lại dạng chữ,
        còn phần đậm do model viết thì giữ nguyên.
        """
        da_gui = self._gui_voi_ket_qua([{"ok": False}, {"ok": True}])
        self.assertEqual(len(da_gui), 2)
        tin = da_gui[1]["message"]
        self.assertIn("- Tin một", str(tin["msg"]), "mất luôn dấu đầu dòng")
        self.assertTrue(any("b" in s["st"].split(",") for s in tin.get("styles") or []),
                        "nấc lùi bỏ sạch phần đậm của model")

    def test_hong_het_thi_nac_cuoi_khong_kem_styles(self):
        """Còn hỏng nữa thì mới bỏ styles — chính nó là thứ bị Zalo từ chối."""
        da_gui = self._gui_voi_ket_qua([{"ok": False}])
        self.assertNotIn("styles", da_gui[-1]["message"])
        self.assertIn("- Tin một", str(da_gui[-1]["message"]["msg"]))


@unittest.skipIf(news is None, "vn-mcp-hub chưa cài phụ thuộc trong môi trường này")
class TestChiToDamTenMuc(unittest.TestCase):
    def test_khong_to_dam_tung_tieu_de(self):
        """32 vùng định dạng bị Zalo từ chối; 8 vùng thì gửi được."""
        ket = {"the_thao": [{"title": f"Tin {i}", "summary": "", "source": "X",
                             "link": ""} for i in range(3)]}
        goi = getattr(news.get_news_sections, "fn", news.get_news_sections)
        with patch.object(news, "_lay_mot_muc",
                          side_effect=lambda tid, n, *a: ket.get(tid, [])):
            ra = goi(3, False, True, True)
        self.assertIn("**⚽ Thể thao**", ra, "tên mục vẫn phải đậm")
        self.assertIn("- Tin 0", ra)
        self.assertNotIn("- **Tin 0**", ra, "tiêu đề KHÔNG được bọc đậm")
        # Chỉ tên mục đậm → số cặp ** đúng bằng số mục có tin.
        self.assertEqual(ra.count("**"), 2)


if __name__ == "__main__":
    unittest.main()
