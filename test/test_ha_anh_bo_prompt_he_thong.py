"""HA gửi ảnh sang phân tích: bỏ prompt hệ thống, chỉ giữ lời dặn phân tích.

VÌ SAO CÓ BÀI NÀY — sự cố thật 06/08/2026, camera báo "không có ai" trong khi
ảnh có người. Đo trên máy chủ (bảng `runs`, hint='vision', source_kind='ha'):
request HA mang hơn 1500 ký tự mở đầu, thứ tự là persona của bot ("NHÂN VẬT: Nam,
18-25 tuổi… xưng em, gọi anh/chị", do `api/ai.py` chèn cho mọi request HA) rồi
tới prompt của HA ("You are a Home Assistant expert…"), lời dặn phân tích nằm SAU
CÙNG trong tin nhắn user. Model trả lời bằng lời chào theo persona, khâu ép JSON
không bóc được nên điền mặc định — thành "0 người" nói rất chắc chắn.

Cùng ảnh đó, cùng họ model, gửi riêng 198 ký tự lời dặn thì trả đúng
`humans_detected: 1`. Nên bài này chốt ĐÚNG BA điều, và điều thứ ba quan trọng
ngang hai điều đầu: chỉ bỏ cho request TỪ HA CÓ ẢNH, không được chạm vào giọng
nói của trợ lý nhà, cũng không được chạm vào ảnh do chính bot nhận.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol.openai_v1_chat_complete import _chi_giu_loi_dan_anh  # noqa: E402
from utils.helper import extract_chat_prompt  # noqa: E402

_PERSONA = "NHÂN VẬT: Nam, 18-25 tuổi, Hà Nội. Xưng em, gọi anh/chị."
_PROMPT_HA = "You are a Home Assistant expert and help users with their tasks."
_LOI_DAN = ("Đây là ảnh từ camera. Phân tích ảnh. Trả về JSON đúng các khoá: "
            "humans_detected (số nguyên), humans_detected_summary…")


def _anh(text: str) -> dict:
    return {"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]}


def _nhu_ha() -> list[dict]:
    """Đúng hình dạng máy chủ ghi lại: hai tin system rồi tới lời dặn + ảnh."""
    return [
        {"role": "system", "content": _PERSONA},
        {"role": "system", "content": _PROMPT_HA},
        _anh(_LOI_DAN),
    ]


class HaGuiAnhTests(unittest.TestCase):
    def test_bo_ca_hai_tin_system_giu_loi_dan(self) -> None:
        ra = _chi_giu_loi_dan_anh(_nhu_ha(), {"_is_ha_request": True})
        self.assertEqual([m["role"] for m in ra], ["user"])
        self.assertIn("humans_detected", str(ra[0]["content"]))

    def test_anh_van_con_nguyen(self) -> None:
        """Bỏ system không được làm mất ảnh — không còn ảnh thì hết việc."""
        ra = _chi_giu_loi_dan_anh(_nhu_ha(), {"_is_ha_request": True})
        phan = ra[0]["content"]
        self.assertTrue(any(p.get("type") == "image_url" for p in phan))

    def test_giu_luot_hoi_dap_truoc_do(self) -> None:
        """Chỉ bỏ system, không dọn hội thoại: lượt user/assistant cũ giữ nguyên."""
        msgs = [{"role": "system", "content": _PROMPT_HA},
                {"role": "user", "content": "bật đèn"},
                {"role": "assistant", "content": "Vâng ạ."},
                _anh(_LOI_DAN)]
        ra = _chi_giu_loi_dan_anh(msgs, {"_is_ha_request": True})
        self.assertEqual([m["role"] for m in ra], ["user", "assistant", "user"])


class KhongDuocChamVaoTests(unittest.TestCase):
    def test_ha_hoi_bang_giong_noi_thi_giu_persona(self) -> None:
        """Không ảnh = trợ lý nhà đang nói chuyện. Persona chính là giọng của bot,
        bỏ đi là mất giọng "em/anh chị" ở toàn bộ trợ lý nhà."""
        msgs = [{"role": "system", "content": _PERSONA},
                {"role": "system", "content": _PROMPT_HA},
                {"role": "user", "content": "mấy giờ rồi"}]
        ra = _chi_giu_loi_dan_anh(msgs, {"_is_ha_request": True})
        self.assertEqual(ra, msgs)

    def test_anh_KHONG_tu_ha_thi_giu_persona(self) -> None:
        """Ảnh gửi vào Zalo/Telegram/tab chat: đường phân tích ảnh của chính bot
        dựa vào persona để trả lời bằng giọng của nó. Cờ HA không có → không bỏ."""
        ra = _chi_giu_loi_dan_anh(_nhu_ha(), {})
        self.assertEqual(len(ra), 3)

    def test_chi_co_system_thi_giu_nguyen(self) -> None:
        """Thà để prompt HA lấn còn hơn gửi request rỗng — mọi provider trả 400
        và camera không có báo nào cả, tệ hơn báo sai."""
        msgs = [{"role": "system", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
        self.assertEqual(_chi_giu_loi_dan_anh(msgs, {"_is_ha_request": True}), msgs)

    def test_khong_co_system_thi_tra_dung_danh_sach_cu(self) -> None:
        msgs = [_anh(_LOI_DAN)]
        self.assertIs(_chi_giu_loi_dan_anh(msgs, {"_is_ha_request": True}), msgs)


class PromptTaoAnhTests(unittest.TestCase):
    """Vẽ ảnh cần ĐÚNG câu yêu cầu. Bản cũ nối mọi lượt user trong hội thoại nên
    "vẽ con mèo" thành "thời tiết thế nào\\nvẽ con mèo" — model ảnh nhận cả câu
    hỏi thời tiết làm mô tả."""

    def test_chi_lay_luot_user_cuoi(self) -> None:
        body = {"messages": [
            {"role": "system", "content": _PROMPT_HA},
            {"role": "user", "content": "thời tiết thế nào"},
            {"role": "assistant", "content": "30 độ ạ."},
            {"role": "user", "content": "vẽ con mèo"},
        ]}
        self.assertEqual(extract_chat_prompt(body), "vẽ con mèo")

    def test_prompt_he_thong_khong_bao_gio_vao_mo_ta_anh(self) -> None:
        body = {"messages": [{"role": "system", "content": _PERSONA},
                             {"role": "user", "content": "vẽ con mèo"}]}
        self.assertEqual(extract_chat_prompt(body), "vẽ con mèo")

    def test_truong_prompt_gui_thang_thi_thang(self) -> None:
        """Đường HA thật đang dùng (`/v1/images/generations`) gửi `prompt` trực
        tiếp — không được đổi hành vi đó."""
        body = {"prompt": "một chiều mưa Hà Nội",
                "messages": [{"role": "user", "content": "bỏ qua câu này"}]}
        self.assertEqual(extract_chat_prompt(body), "một chiều mưa Hà Nội")

    def test_khong_co_luot_user_nao_thi_rong(self) -> None:
        self.assertEqual(extract_chat_prompt({"messages": [
            {"role": "system", "content": _PERSONA}]}), "")


if __name__ == "__main__":
    unittest.main()
