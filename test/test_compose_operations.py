"""Operational guardrails that do not depend on a Docker daemon."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ComposeOperationsTests(unittest.TestCase):
    def test_moi_stack_xoay_log_docker(self):
        for filename in ("docker-compose.yml", "docker-compose.lite.yml"):
            source = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("driver: json-file", source, filename)
            self.assertIn('max-size: "10m"', source, filename)
            self.assertIn('max-file: "5"', source, filename)

    def test_moi_service_deu_co_gioi_han_log(self):
        """Xoay log ở mỗi service `c2a` là chưa đủ — service nào cũng ghi ra
        cùng một ổ đĩa host."""
        source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        so_service = source.count("    container_name:")
        self.assertEqual(source.count("      driver: json-file"), so_service,
                         "còn service chưa đặt giới hạn log")

    def test_cong_publish_di_theo_APP_PORT(self):
        """Non-root nghe 8080; ánh xạ cứng `3030:80` thì cổng ngoài trỏ vào chỗ
        không ai nghe, mà lỗi chỉ lộ ra lúc đổi sang non-root."""
        source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('"3030:${APP_PORT:-80}"', source)
        self.assertNotIn('- "3030:80"', source)


if __name__ == "__main__":
    unittest.main()
