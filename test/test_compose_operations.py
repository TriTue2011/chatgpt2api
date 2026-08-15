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


if __name__ == "__main__":
    unittest.main()
