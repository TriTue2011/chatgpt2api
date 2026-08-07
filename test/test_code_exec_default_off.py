"""Chạy thật code do LLM sinh phải TẮT mặc định — chỉ soi tĩnh.

Báo cáo bảo mật 07/08 (Critical): tầng chạy thử chỉ có blacklist + rlimit,
không cô lập mạng/filesystem, container chạy root → không phải sandbox thật.
_pipeline_chay_thu_bat() mặc định False; chỉ bật khi pipeline_chay_thu=true.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class CodeExecDefaultOffTests(unittest.TestCase):
    def setUp(self):
        from services.protocol import openai_v1_chat_complete as occ
        self.occ = occ

    def test_mac_dinh_tat(self):
        from services.config import config
        with mock.patch.object(config, "data", {}):
            self.assertFalse(self.occ._pipeline_chay_thu_bat(),
                             "chạy thật code phải TẮT khi chưa cấu hình")

    def test_bat_tuong_minh_moi_chay(self):
        from services.config import config
        with mock.patch.object(config, "data", {"pipeline_chay_thu": True}):
            self.assertTrue(self.occ._pipeline_chay_thu_bat())

    def test_dat_false_van_tat(self):
        from services.config import config
        with mock.patch.object(config, "data", {"pipeline_chay_thu": False}):
            self.assertFalse(self.occ._pipeline_chay_thu_bat())


if __name__ == "__main__":
    unittest.main()
