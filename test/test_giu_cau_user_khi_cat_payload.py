"""Cắt payload cho ChatGPT web không được vứt CÂU USER CUỐI, và không được
tính bytes ảnh vào trần JSON.

Hai lỗi đo thật ngày 07/08 trên máy chủ (combo "AI text"/"AI vision" rơi về
chatgpt_free sau khi codex hết credential và gemini_free lỗi 400):

1. 19:46–19:47, 4/4 lượt chat Zalo ("Em tên gì", "Em có thể làm gì"…) chỉ
   nhận một câu chào "Dạ em đây ạ 😊…". System prompt của agent (kèm tài liệu
   86 tool) MỘT MÌNH đã vượt trần 45KB, vòng pop(0) trong _truncate_messages
   vứt sạch tin không-system — kể cả câu hỏi vừa gửi — nên ChatGPT web chỉ
   thấy system prompt và chào lại theo persona.
2. 20:07, phân tích ảnh camera trả humans_detected=0 cho MỌI khung hình: ảnh
   ~300KB bị tính bytes thật vào trần 45KB dù ảnh thực tế upload riêng qua
   /backend-api/files (asset_pointer, vài trăm byte trong payload), nên câu
   lệnh "phân tích ảnh" bị vứt, model trả "Hi! How can I help you today?" và
   bộ ép JSON (response_format_fallback_defaults) điền toàn số 0.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class TruncateGiuCauUserTests(unittest.TestCase):

    def test_system_qua_tran_van_giu_cau_user(self):
        from services.protocol.conversation import (
            _truncate_messages, _MAX_PAYLOAD_BYTES,
        )
        msgs = [
            {"role": "system", "content": "x" * (_MAX_PAYLOAD_BYTES + 5000)},
            {"role": "user", "content": "Em tên gì"},
        ]
        out = _truncate_messages(msgs)
        users = [m for m in out if m.get("role") == "user"]
        self.assertEqual(len(users), 1, "câu user cuối phải sống sót")
        self.assertIn("Em tên gì", str(users[0].get("content")))
        # Chỗ phải nhường là SYSTEM (bị cắt), không phải câu hỏi (bị vứt).
        sys_out = next(m for m in out if m.get("role") == "system")
        self.assertLess(len(str(sys_out["content"])), _MAX_PAYLOAD_BYTES)

    def test_lich_su_cu_van_bi_cat_nhu_truoc(self):
        from services.protocol.conversation import _truncate_messages
        msgs = [
            {"role": "system", "content": "s" * 30_000},
            {"role": "user", "content": "cũ " * 7_000},
            {"role": "assistant", "content": "đáp cũ " * 4_000},
            {"role": "user", "content": "Em có thể làm gì"},
        ]
        out = _truncate_messages(msgs)
        self.assertTrue(
            any(m.get("role") == "user" and "Em có thể làm gì" in str(m.get("content"))
                for m in out),
            "câu hỏi hiện tại phải còn",
        )
        self.assertFalse(
            any("đáp cũ" in str(m.get("content")) for m in out),
            "lịch sử cũ vẫn phải được cắt để xuống dưới trần",
        )
        # System không bị đụng vì cắt lịch sử là đủ.
        self.assertEqual(len(next(m for m in out if m.get("role") == "system")["content"]), 30_000)

    def test_anh_khong_tinh_bytes_vao_tran(self):
        from services.protocol.conversation import (
            _payload_size_bytes, _MAX_PAYLOAD_BYTES,
        )
        img = {"role": "user", "content": [
            {"type": "image", "data": b"j" * 300_000, "mime": "image/jpeg"},
        ]}
        msgs = [
            {"role": "system", "content": "persona ngắn"},
            {"role": "user", "content": "Phân tích ảnh, trả JSON humans_detected"},
            img,
        ]
        self.assertLess(_payload_size_bytes(msgs), _MAX_PAYLOAD_BYTES)

    def test_vision_giu_ca_lenh_lan_anh(self):
        from services.protocol.conversation import _truncate_messages
        img = {"role": "user", "content": [
            {"type": "image", "data": b"j" * 300_000, "mime": "image/jpeg"},
        ]}
        msgs = [
            {"role": "system", "content": "persona ngắn"},
            {"role": "user", "content": "Phân tích ảnh, trả JSON humans_detected"},
            img,
        ]
        out = _truncate_messages(msgs)
        self.assertEqual(len(out), 3, "payload nhỏ (ảnh upload riêng) — không được vứt gì")
        self.assertTrue(any(
            m.get("role") == "user" and "Phân tích ảnh" in str(m.get("content"))
            for m in out
        ))


class RtkCompressGiuCauUserTests(unittest.TestCase):

    def test_nhieu_system_qua_tran_van_giu_cau_user(self):
        from services.protocol.conversation import _rtk_compress_messages
        # Mỗi system ≤3000 byte để Step 1 không nén; tổng system > max_bytes
        # để Step 3 (vòng pop) phải chạy tới đáy — đúng ca 07/08.
        msgs = [{"role": "system", "content": f"hệ{i} " * 500} for i in range(6)]
        msgs += [
            {"role": "user", "content": "câu hỏi cũ"},
            {"role": "assistant", "content": "trả lời cũ"},
            {"role": "user", "content": "Em có thể làm gì"},
        ]
        out = _rtk_compress_messages(msgs, 10_000)
        self.assertTrue(
            any(m.get("role") == "user" and "Em có thể làm gì" in str(m.get("content"))
                for m in out),
            "câu user cuối phải sống sót qua Step 3",
        )


if __name__ == "__main__":
    unittest.main()
