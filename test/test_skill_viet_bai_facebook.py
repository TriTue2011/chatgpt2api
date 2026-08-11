"""Skill mặc định 'viết bài Facebook tự nhiên' — parse + seed + nội dung lõi.

Phỏng theo harshaneel/humanize nhưng CHUYỂN sang tiếng Việt. Test giữ ba bảo
đảm: (1) frontmatter hợp lệ & description qua validate_description (≤150, không
sáo) để router không cắt mất; (2) thân skill trỏ đúng tool `dang_facebook` +
cổng duyệt và chứa các quy tắc chống-giọng-máy tiếng Việt (không phải danh sách
tiếng Anh vô dụng); (3) seed được vào data dir như các skill khác.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import skills as sk  # noqa: E402

SLUG = "viet-bai-facebook"


class VietBaiFacebookSkillTests(unittest.TestCase):
    def _read(self) -> tuple[dict, str]:
        p = Path(sk.__file__).with_name("skills_default") / SLUG / "SKILL.md"
        self.assertTrue(p.is_file(), p)
        meta, body = sk.split_frontmatter(p.read_text(encoding="utf-8"))
        return meta, body

    def test_frontmatter_va_description_hop_le(self) -> None:
        meta, _ = self._read()
        self.assertEqual(meta.get("name"), "Viết bài Facebook tự nhiên")
        self.assertEqual(meta.get("group"), "Nội dung")
        desc = meta.get("description") or ""
        self.assertLessEqual(len(desc), sk.SKILL_DESC_MAX, f"desc dài {len(desc)}")
        self.assertIsNone(sk.validate_description(desc),
                          sk.validate_description(desc))
        self.assertIn("Facebook", desc)

    def test_than_tro_dung_diem_dau_noi_va_quy_tac_viet(self) -> None:
        _, body = self._read()
        # Điểm đấu nối: tool đăng + cổng duyệt (không tự đăng).
        self.assertIn("dang_facebook", body)
        self.assertIn("duyệt", body.lower())
        # Là bản tiếng Việt: có danh sách từ máy tiếng Việt, không nhét từ Anh.
        for cum in ("Hơn nữa", "Bên cạnh đó", "Hy vọng bài viết hữu ích",
                    "không chỉ", "emoji"):
            self.assertIn(cum, body, cum)
        self.assertNotIn("delve", body.lower())
        self.assertNotIn("leverage", body.lower())

    def test_seed_vao_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            with mock.patch.object(sk, "_SKILLS_DIR", root), \
                    mock.patch.object(sk, "_seeded", False):
                items = sk.list_skills(enabled_only=True)
            slugs = {m.slug for m in items}
            self.assertIn(SLUG, slugs)
            self.assertTrue((root / SLUG / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
