"""Seed + parse skill/workflow giáo viên tiểu học."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import skills as sk  # noqa: E402
from services.agent import workflows as wf  # noqa: E402


class GiaoVienTieuHocSkillTests(unittest.TestCase):
    def test_default_skill_file_exists(self) -> None:
        p = Path(sk.__file__).with_name("skills_default") / "giao-vien-tieu-hoc" / "SKILL.md"
        self.assertTrue(p.is_file(), p)
        text = p.read_text(encoding="utf-8")
        meta, body = sk.split_frontmatter(text)
        self.assertEqual(meta.get("name"), "Giáo viên tiểu học")
        self.assertIn("TTS", body)
        self.assertIn("Socratic", body)
        err = sk.validate_description(meta.get("description") or "")
        self.assertIsNone(err, err)

    def test_skill_seeds_into_data_dir(self) -> None:
        # Force re-seed path: empty temp skills dir.
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            with mock.patch.object(sk, "_SKILLS_DIR", root), \
                    mock.patch.object(sk, "_seeded", False):
                items = sk.list_skills(enabled_only=True)
            slugs = {m.slug for m in items}
            for s in ("giao-vien-tieu-hoc", "giao-vien-thcs", "giao-vien-thpt"):
                self.assertIn(s, slugs)
                self.assertTrue((root / s / "SKILL.md").is_file())

    def test_workflow_default_exists_and_parses(self) -> None:
        p = Path(wf.__file__).with_name("workflows_default") / "bai-hoc-tieu-hoc.md"
        self.assertTrue(p.is_file(), p)
        text = p.read_text(encoding="utf-8")
        meta, body = sk.split_frontmatter(text)
        self.assertIn("tiểu học", (meta.get("name") or "").lower()
                      + (meta.get("description") or "").lower())
        self.assertRegex(body, r"Bước\s*1")
        self.assertRegex(body, r"Bước\s*3")
        self.assertIn("TTS", body)


if __name__ == "__main__":
    unittest.main()
