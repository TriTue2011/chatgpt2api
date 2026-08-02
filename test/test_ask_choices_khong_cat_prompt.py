"""Menu chọn model KHÔNG được cắt mất prompt dài.

Đo thật 02/08 — lỗi âm thầm, mất cả buổi mới lần ra:

Menu chọn model nhồi prompt vào chính chuỗi `send` của lựa chọn:
    "tạo video bằng model flow/veo-3.1-lite: <toàn bộ prompt>"
mà `extract()` lại cắt `send` ở 200 ký tự. Bốn lượt tạo video/ảnh của chủ máy đều
lưu `user_text` ĐÚNG 200 ký tự, cắt giữa từ:

    16:23 | 200 ký tự | …đang chạy cầm 1 gáo nước, 1 xô nước. Người
    16:20 | 200 ký tự | … gáo nước, 1 xô nước. Người nam đang dùng
    14:41 | 200 ký tự | …i cây phun nhiều tia nước về phía chàng tr
    14:35 | 200 ký tự | …u tia nước về phía chàng trai. Chàng trai

Phần mô tả còn lại bị bỏ, nên Flow tạo ảnh/video theo prompt BỊ CHẶT — người dùng
thấy "ảnh ra không đúng ý" mà không có dấu hiệu nào báo là prompt đã mất phần cuối.

Chú thích cũ biện minh trần 200 là "để người dùng không bao giờ gửi thứ họ chưa
thấy". Nhưng `send` KHÔNG BAO GIỜ ra khỏi máy chủ: kênh chỉ nhận `label`
(`format_numbered` in danh sách số; Telegram dùng `callback_data='ask:<i>'`), và
`resolve_reply` tra lại `send` theo CHỈ SỐ. Trần đó không bảo vệ điều gì.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import ask_choices as ac  # noqa: E402

# Prompt thật của chủ máy 02/08 (dài hơn 200 ký tự sau khi ghép tiền tố menu).
PROMPT_DAI = ("Một chàng trai, một cô gái yêu nhau đang vui đùa trong sân nhà, "
              "cô gái cầm vòi tưới cây nhiều tia xịt vào chàng trai, chàng trai "
              "đang chạy cầm 1 gáo nước, 1 xô nước. Người nam đang dùng gáo té "
              "nước vào cô gái.")


def _menu(prompt: str) -> str:
    """Dựng đúng khuôn `_ask_video_provider` sinh ra."""
    return ("🎬 Chọn model ạ?\n<<<ASK>>>\n"
            f"flow/veo-3.1-lite | tạo video bằng model flow/veo-3.1-lite: {prompt}\n"
            "<<<END>>>")


class KhongCatPromptTests(unittest.TestCase):
    def test_prompt_dai_di_qua_NGUYEN_VEN(self):
        _, choices = ac.extract(_menu(PROMPT_DAI))
        self.assertEqual(len(choices), 1)
        send = choices[0]["send"]
        self.assertGreater(len(send), 200, "phải dài hơn trần cũ mới là phép đo thật")
        self.assertTrue(send.endswith(PROMPT_DAI),
                        f"prompt bị cắt: …{send[-40:]!r}")
        # Câu cuối — thứ bị mất trong ca thật — phải còn.
        self.assertIn("Người nam đang dùng gáo té nước vào cô gái.", send)

    def test_nhan_van_bi_cat_ngan_cho_de_doc(self):
        """Chỉ `label` ra tới người dùng nên vẫn cắt ngắn — đó là hiển thị."""
        _, choices = ac.extract(_menu(PROMPT_DAI))
        self.assertLessEqual(len(choices[0]["label"]), 40)

    def test_prompt_cuc_dai_van_co_tran(self):
        """Vẫn phải có chặn để không phình vô hạn."""
        _, choices = ac.extract(_menu("x" * 9000))
        self.assertLessEqual(len(choices[0]["send"]), ac._SEND_MAX)

    def test_tran_du_rong_cho_prompt_anh_chi_tiet(self):
        """Prompt ảnh chi tiết (máy ảnh, ống kính, ánh sáng…) dài cỡ 900 ký tự."""
        self.assertGreaterEqual(ac._SEND_MAX, 2000)


class ChonBangSoVanDungTests(unittest.TestCase):
    """`send` dài không phá luồng chọn — vì nó tra theo CHỈ SỐ, không theo chữ."""

    def setUp(self):
        self.uid = "test_user_cat_prompt"
        ac.clear_pending(self.uid)

    def test_tra_loi_so_1_lay_dung_send_day_du(self):
        text, choices = ac.extract(_menu(PROMPT_DAI))
        ac.set_pending(self.uid, choices)
        got = ac.resolve_reply(self.uid, "1")
        self.assertIsNotNone(got)
        self.assertTrue(got.endswith(PROMPT_DAI))

    def test_kenh_chi_nhan_label_khong_nhan_send(self):
        """Bằng chứng cho việc trần 200 không bảo vệ gì: chuỗi gửi ra kênh KHÔNG
        chứa prompt."""
        text, choices = ac.extract(_menu(PROMPT_DAI))
        ra_kenh = ac.format_numbered(text, choices)
        self.assertNotIn("gáo té nước", ra_kenh)
        self.assertIn("flow/veo-3.1-lite", ra_kenh)   # nhãn thì có


if __name__ == "__main__":
    unittest.main()
