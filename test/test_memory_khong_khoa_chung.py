"""Memory không được dồn vào một khoá chung khi lời gọi thiếu định danh.

Đo thật trên máy chủ 03/08: bảng memory có 1.162 bản ghi và ĐÚNG MỘT `user_id`
— toàn bộ nằm ở khoá mặc định `chatgpt2api`. Nguyên nhân ở `prepare()`:

    user_id = str(body.get("user") or self._cfg.get("user_id") or "chatgpt2api")

Lời gọi nào không khai `user` đều rơi về khoá đó, nên ký ức của người này được
tra ra rồi chèn vào prompt của người kia. Nhìn từ ngoài hệ thống vẫn "chạy tốt",
không có lỗi nào để mà phát hiện.

Quy tắc thay thế: thiếu định danh tin cậy thì TẮT memory cho lượt đó.
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import memory_service as ms  # noqa: E402

CAU = "Nhà mình có mấy cái loa trong phòng khách nhỉ, anh nhớ giúp em với"


def _body(**kw) -> dict:
    b = {"model": "gpt-5.5", "messages": [{"role": "user", "content": CAU}]}
    b.update(kw)
    return b


class _Kho(ms.MemoryService):
    """Bản thật nhưng chặn mọi đường chạm đĩa — chỉ quan tâm tới việc CHỌN KHOÁ."""

    def __init__(self, cfg: dict):
        self._cfg_gia = cfg
        self.da_tra: list[str] = []

    @property
    def is_enabled(self) -> bool:
        return True

    @property
    def _cfg(self) -> dict:
        return self._cfg_gia

    def recall(self, query: str, user_id: str):
        self.da_tra.append(user_id)
        return []


class ThieuDinhDanhThiTatMemory(unittest.TestCase):
    def test_khong_neu_user_thi_khong_tra_memory(self):
        kho = _Kho({})
        self.assertIsNone(kho.prepare(_body()))
        self.assertEqual(kho.da_tra, [])          # KHÔNG chạm vào kho ký ức

    def test_khong_con_khoa_chatgpt2api(self):
        kho = _Kho({})
        kho.prepare(_body())
        self.assertNotIn("chatgpt2api", kho.da_tra)

    def test_user_rong_hoac_toan_khoang_trang_cung_bi_chan(self):
        for xau in ("", "   ", None):
            kho = _Kho({})
            self.assertIsNone(kho.prepare(_body(user=xau)), xau)
            self.assertEqual(kho.da_tra, [])

    def test_co_user_thi_tra_dung_khoa_do(self):
        kho = _Kho({})
        kho.prepare(_body(user="v2:local:tg:bot1:123#general:u9"))
        self.assertEqual(kho.da_tra, ["v2:local:tg:bot1:123#general:u9"])

    def test_config_co_khai_user_id_thi_van_dung_duoc(self):
        """Máy chủ một người dùng vẫn khai được khoá cố định trong config."""
        kho = _Kho({"user_id": "nha_minh"})
        kho.prepare(_body())
        self.assertEqual(kho.da_tra, ["nha_minh"])

    def test_body_thang_config(self):
        kho = _Kho({"user_id": "nha_minh"})
        kho.prepare(_body(user="rieng_toi"))
        self.assertEqual(kho.da_tra, ["rieng_toi"])


class KhongConTrongMaNguon(unittest.TestCase):
    def test_ma_nguon_khong_con_khoa_mac_dinh(self):
        """Chốt bằng mã nguồn: đường lùi này từng bị thêm lại sau khi gỡ."""
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "memory_service.py").read_text("utf-8")
        i = src.index("def prepare(")
        than = src[i:i + 3000]
        self.assertNotIn('or "chatgpt2api"', than)


if __name__ == "__main__":
    unittest.main()
