"""Lượt hỏi thời tiết: giữ LỜI DẶN của người dùng, và tách ĐÚNG tên địa danh.

Đo thật trên Zalo ngày 29/08 (nguyên văn, rút gọn):

    16:02:01 người dùng : lần sau khi hỏi thời tiết thêm lưu ý là lời dặn dò, khuyến cáo
    16:02:21 bot        : Dạ em nhớ rồi ạ 🧠: Khi người dùng hỏi thời tiết… cần thêm
                          phần lưu ý/lời dặn dò, khuyến cáo phù hợp…
    16:02:35 bot        : Em cập nhật thời tiết Hoàng Mai hiện có mưa, khoảng 31°C…
    16:02:55 người dùng : không có khuyên cáo hay lời dặn dò à
    16:03:17 bot        : Em báo thời tiết Hoàng Mai hiện có mưa, khoảng 31°C…
    16:03:30 người dùng : vẫn không có khuyến cáo, dặn dò
    16:04:29 người dùng : tại sao hay quên thế

    16:05:05 người dùng : anh lại hỏi thời tiết hồ chí minh
    16:05:17 bot        : Em báo anh thời tiết An Hoi hiện patchy rain nearby, 32°C…

Hai lỗi tách bạch nằm sau đoạn hội thoại đó:

1. Câu thời tiết đi ĐƯỜNG TẮT (`ha_local_fastpath_answer`) rồi chỉ nhờ model
   diễn đạt lại. Khối lời dặn kèm theo lượt diễn đạt ấy chỉ nhận những dòng
   trí nhớ khớp từ khoá TRÌNH BÀY ("ngắn gọn", "chia mục", "bỏ link"…), nên lời
   dặn "thêm lưu ý, khuyến cáo" ghi nhớ được mà không dòng nào khớp — bot lưu
   xong rồi quên đúng ba lượt liền, và tự hứa "từ giờ em sẽ tự ép theo cấu
   trúc" mà không có gì trong code đỡ lời hứa đó.

2. `_extract_weather_city` chỉ cắt cụm dẫn ("thời tiết") khi nó nằm ngay ĐẦU
   câu. "anh lại hỏi thời tiết hồ chí minh" có ba chữ đứng trước nên cả câu bị
   đem đi geocode, ra một chỗ tên "An Hoi" và mô tả tiếng Anh. Log máy chủ ghi
   đúng lời gọi ấy: `autocomplete?query=anh+lại+hỏi+thời+tiết+hồ+chí+minh`.

3. Chính lượt nhờ model diễn đạt lại cũng bị gateway đem đi TRA WEB (log
   16:05:06: `{"event": "search_executing", "query": "Tin nhắn: anh lại hỏi
   thời tiết hồ chí minh\nKết quả từ hệ thống nhà: …"}`). Kết quả tra về tiêm
   vào lượt kèm câu "BẮT BUỘC ĐỌC VÀ TRẢ LỜI DỰA TRÊN ĐÂY" — tranh chỗ với lời
   dặn của người dùng, cho một việc chỉ là viết lại đoạn văn đã có sẵn.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402
import services.protocol.openai_v1_chat_complete as api  # noqa: E402
from services.agent import state  # noqa: E402

#: Đúng câu bot đã lưu lúc 16:02:21.
LOI_DAN = ("- Khi người dùng hỏi thời tiết, ngoài thông tin thời tiết cần thêm "
           "phần lưu ý/lời dặn dò, khuyến cáo phù hợp như mang ô/áo mưa, tránh "
           "nắng, chú ý dông gió, uống nước, bảo vệ sức khỏe.")


class NhanRaLoiDanThemKhuyenCao(unittest.TestCase):
    """Dặn THÊM một phần vào câu trả lời cũng là dặn cách trả lời."""

    def test_nhan_dung_cau_bot_da_luu(self):
        with patch.object(state, "load_memory", return_value=LOI_DAN):
            self.assertEqual(len(orch._so_thich_trinh_bay()), 1)

    def test_nhan_ca_khi_go_khong_dau(self):
        with patch.object(state, "load_memory",
                          return_value="- Hoi thoi tiet thi nho them khuyen cao nhe."):
            self.assertEqual(len(orch._so_thich_trinh_bay()), 1)

    def test_du_kien_thuong_van_bi_bo_qua(self):
        """Không được nới rộng tới mức lôi cả dữ kiện riêng vào prompt."""
        mem = "\n".join(["- Anh tên là Việt, ở Hà Nội.",
                         "- Mật khẩu wifi là 12345678.",
                         "- Con trai học lớp 2."])
        with patch.object(state, "load_memory", return_value=mem):
            self.assertEqual(orch._so_thich_trinh_bay(), [])


class LoiDanToiDuocLuotDienDatDuongTat(unittest.TestCase):
    """Đường tắt thời tiết phải ĐƯA lời dặn vào lượt nhờ model diễn đạt.

    Đây là chỗ hỏng thật: đường tắt trả lời trước khi model được gọi, nên lời
    dặn nằm trong trí nhớ không có đường nào chạm tới câu trả lời.
    """

    FP = "Thời tiết Hoàng Mai hiện có mưa, khoảng 31°C, độ ẩm 70%."

    def _chay(self, mem: str) -> dict:
        thay: dict = {}

        def _bat(model, messages, **kw):
            thay["messages"] = messages
            thay["kw"] = kw
            return {"choices": [{"message": {"content": "câu đã diễn đạt lại"}}]}

        # Orchestrator gọi bản CHI TIẾT (trả thêm tên bộ dò) — xem
        # `ha_local_fastpath_chi_tiet`. Vá bản gọn thì nhánh diễn đạt không
        # chạy tới và `kw` rỗng.
        with patch.object(api, "ha_local_fastpath_chi_tiet",
                          return_value=(self.FP, False, "_ha_local_weather")), \
             patch.object(orch, "call_model", side_effect=_bat), \
             patch.object(orch, "_persist_history", lambda *a, **k: None), \
             patch.object(state, "load_memory", return_value=mem):
            orch._orchestrate_locked("thời tiết hôm nay", "u_test_thoi_tiet",
                                     ha_fastpath=True)
        return thay

    def _he_thong(self, mem: str) -> str:
        return " ".join(str(m.get("content") or "")
                        for m in (self._chay(mem).get("messages") or [])
                        if m.get("role") == "system")

    def test_loi_dan_co_trong_prompt_dien_dat(self):
        self.assertIn("khuyến cáo", self._he_thong(LOI_DAN),
                      "lời dặn không tới được lượt diễn đạt = ghi nhớ rồi bỏ đó")

    def test_prompt_khong_cam_phan_them(self):
        """"Không bịa thêm" nói về SỐ LIỆU. Phải nói rõ phần lưu ý được phép
        thêm, kẻo model hiểu lời dặn là điều bị cấm rồi bỏ luôn."""
        self.assertIn("PHẢI làm theo", self._he_thong(LOI_DAN))

    def test_khong_co_loi_dan_thi_khong_them_khoi_nao(self):
        msgs = self._chay("- Anh tên là Việt, ở Hà Nội.").get("messages") or []
        self.assertEqual(sum(1 for m in msgs if m.get("role") == "system"), 1,
                         "không có lời dặn mà vẫn nhét khối rỗng = tốn token")

    def test_luot_dien_dat_khong_duoc_tra_web(self):
        """Log máy chủ 29/08 16:05 cho thấy chính câu nhờ diễn đạt bị đem đi
        search, rồi kết quả tra về được tiêm kèm "BẮT BUỘC ĐỌC VÀ TRẢ LỜI DỰA
        TRÊN ĐÂY" — tranh chỗ với lời dặn, và tốn thêm hơn mười giây."""
        kw = self._chay(LOI_DAN).get("kw") or {}
        self.assertEqual(kw.get("allowed_groups"), set(),
                         "lượt chỉ viết lại đoạn văn có sẵn thì không được tra web")


class TachTenDiaDanhCoLoiDanDungTruoc(unittest.TestCase):
    """Cụm dẫn ("thời tiết", "dự báo") không phải lúc nào cũng ở đầu câu."""

    def test_cau_that_luc_16h05(self):
        self.assertEqual(
            api._extract_weather_city("anh lại hỏi thời tiết hồ chí minh"),
            "hồ chí minh")

    def test_loi_dan_dai_hon(self):
        self.assertEqual(
            api._extract_weather_city("cho anh hỏi dự báo thời tiết Đà Nẵng"),
            "Đà Nẵng")

    def test_cum_dan_o_dau_cau_van_nhu_cu(self):
        for cau, mong in (("thời tiết hồ chí minh", "hồ chí minh"),
                          ("thời tiết hoàng mai", "hoàng mai"),
                          ("nhiệt độ Mai Châu bây giờ", "Mai Châu"),
                          ("chất lượng không khí Hà Nội", "Hà Nội")):
            with self.subTest(cau=cau):
                self.assertEqual(api._extract_weather_city(cau), mong)

    def test_khong_cat_nham_giua_ten_ghep(self):
        """Tên nhiều âm tiết trùng chữ đệm ("Cần *Giờ*", "*Côn* Đảo") phải
        nguyên vẹn — đây là tính chất bản cũ đã giữ, không được làm hỏng."""
        self.assertEqual(
            api._extract_weather_city("em ơi thời tiết ở Cần Giờ thế nào"), "Cần Giờ")
        self.assertEqual(
            api._extract_weather_city("thời tiết Côn Đảo hôm nay"), "Côn Đảo")

    def test_khong_co_dia_danh_thi_tra_rong(self):
        """Rỗng để lượt chat rơi về vị trí nhà, chứ không geocode cả câu."""
        self.assertEqual(api._extract_weather_city("anh lại hỏi thời tiết"), "")


if __name__ == "__main__":
    unittest.main()
