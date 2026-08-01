"""Người dùng KHÔNG BAO GIỜ được thấy dấu `**` trong tin nhắn.

`send_message` gửi bản có định dạng (styles zca-js) trước; thất bại thì gửi lại
bản chữ trơn. Bản trơn cũ dùng `ch` — tức chuỗi markdown THÔ — nên mỗi lần lệnh
gửi-có-định-dạng bị từ chối là người dùng nhận nguyên `**Tiêu đề**`.

Đo thật 01/08: bản tin bọc đậm cả 8 tên mục lẫn 24 tiêu đề = 32 vùng định dạng
trong một tin; Zalo từ chối, log có HAI lệnh gửi cách nhau 1 giây, và người dùng
nhắn lại "Trình bày xấu quá, bỏ ** đi". Sau khi chỉ tô đậm tên mục (8 vùng),
lệnh gửi thành công ngay lần đầu — log chỉ còn MỘT lệnh.

Hai lớp cùng khoá ở đây:
  * bản dự phòng phải là chuỗi ĐÃ bóc markdown;
  * bản tin chỉ tô đậm TÊN MỤC, không tô từng tiêu đề.
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

    def test_that_bai_thi_ban_du_phong_KHONG_con_dau_sao(self):
        """Chốt chính: gửi-có-định-dạng lỗi → bản trơn vẫn phải sạch dấu sao."""
        da_gui = self._gui_voi_ket_qua([{"ok": False}, {"ok": True}])
        self.assertEqual(len(da_gui), 2, "phải có bản dự phòng")
        trơn = str(da_gui[1]["message"]["msg"])
        self.assertNotIn("**", trơn, "bản dự phòng để lọt dấu ** cho người dùng")
        self.assertIn("Thể thao", trơn, "bóc dấu sao không được bóc luôn chữ")

    def test_ban_du_phong_khong_kem_styles(self):
        """Gửi lại thì phải bỏ styles — chính nó làm lần đầu thất bại."""
        da_gui = self._gui_voi_ket_qua([{"ok": False}, {"ok": True}])
        self.assertNotIn("styles", da_gui[1]["message"])


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
