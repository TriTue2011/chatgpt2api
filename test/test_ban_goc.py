"""Bản chạy thật theo bản gốc trong ảnh — trừ khi đã sửa tay (`services/ban_goc.py`).

13/09/2026: hướng dẫn chọn ngoại vi, skill `giao-vien-tieu-hoc` và 2 workflow bài
học trên máy chủ đều kẹt bản chép lần đầu, vì cả ba nơi chép MỘT lần rồi thôi.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


class BanGocTest(unittest.TestCase):
    def setUp(self) -> None:
        from services import ban_goc

        self.bg = ban_goc
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.r = Path(self._tmp.name)

    # ── tệp đơn ────────────────────────────────────────────────────────────
    def test_TEP_chep_roi_theo_ban_goc_roi_GIU_ban_sua_tay(self) -> None:
        goc, chay, so = self.r / "goc.md", self.r / "chay" / "x.md", self.r / "chay" / "x.goc"
        chay.parent.mkdir()
        goc.write_text("bản 1", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="t"), "chep")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="t"), "")
        goc.write_text("bản 2", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="t"), "theo")
        self.assertEqual(chay.read_text(encoding="utf-8"), "bản 2")
        chay.write_text("bản người sửa", encoding="utf-8")
        goc.write_text("bản 3", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="t"), "giu")
        self.assertEqual(chay.read_text(encoding="utf-8"), "bản người sửa")

    def test_TEP_chua_co_so_khop_thi_ghi_so_khac_thi_giu(self) -> None:
        goc, chay, so = self.r / "goc.md", self.r / "x.md", self.r / "x.goc"
        goc.write_text("gốc", encoding="utf-8")
        chay.write_text("không rõ nguồn", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="t"), "giu")
        self.assertFalse(so.exists())
        chay.write_text("gốc", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="t"), "ghi_so")
        goc.write_text("gốc mới", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="t"), "theo")

    def test_TEP_doc_duoc_so_cu_chi_ghi_van_tay(self) -> None:
        """Sổ `.goc` của hướng dẫn ghi trước khi có file này chỉ chứa sha256 nội dung."""
        import hashlib

        goc, chay, so = self.r / "goc.md", self.r / "x.md", self.r / "x.goc"
        goc.write_text("cũ", encoding="utf-8")
        chay.write_text("cũ", encoding="utf-8")
        so.write_text(hashlib.sha256("cũ".encode()).hexdigest(), encoding="utf-8")
        goc.write_text("mới", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="t"), "theo")

    # ── thư mục (skill) ────────────────────────────────────────────────────
    def test_THU_MUC_theo_ban_goc_them_bot_tep_va_khong_dung_tep_nguoi_them(self) -> None:
        goc, chay, so = self.r / "goc", self.r / "skills" / "s", self.r / "skills" / ".s.goc"
        goc.mkdir()
        (goc / "SKILL.md").write_text("v1", encoding="utf-8")
        (goc / "cu.md").write_text("sẽ bỏ", encoding="utf-8")
        chay.parent.mkdir()
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="s"), "chep")
        (chay / "cua_nguoi.md").write_text("người thêm", encoding="utf-8")
        (goc / "SKILL.md").write_text("v2", encoding="utf-8")
        (goc / "cu.md").unlink()
        (goc / "moi.md").write_text("mới", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="s"), "theo")
        self.assertEqual(sorted(f.name for f in chay.iterdir()), ["SKILL.md", "cua_nguoi.md", "moi.md"])
        self.assertEqual((chay / "SKILL.md").read_text(encoding="utf-8"), "v2")

    def test_THU_MUC_skill_nguoi_day_them_thi_giu(self) -> None:
        goc, chay, so = self.r / "goc", self.r / "skills" / "s", self.r / "skills" / ".s.goc"
        goc.mkdir()
        (goc / "SKILL.md").write_text("v1", encoding="utf-8")
        chay.parent.mkdir()
        self.bg.dong_bo(goc, chay, so, ten="s")
        (chay / "SKILL.md").write_text("v1\n\nNgười dùng dạy thêm", encoding="utf-8")
        (goc / "SKILL.md").write_text("v2", encoding="utf-8")
        self.assertEqual(self.bg.dong_bo(goc, chay, so, ten="s"), "giu")
        self.assertIn("dạy thêm", (chay / "SKILL.md").read_text(encoding="utf-8"))

    # ── đấu nối ────────────────────────────────────────────────────────────
    def test_SKILL_va_WORKFLOW_mac_dinh_theo_ban_goc_khi_nap(self) -> None:
        from services.agent import skills as sk
        from services.agent import workflows as wf

        goc_sk, goc_wf = self.r / "sk_goc", self.r / "wf_goc"
        (goc_sk / "giao-vien").mkdir(parents=True)
        (goc_sk / "giao-vien" / "SKILL.md").write_text("---\nname: GV\ndescription: d\n---\nv1\n",
                                                       encoding="utf-8")
        goc_wf.mkdir()
        (goc_wf / "bai-hoc.md").write_text("v1", encoding="utf-8")
        chay_sk, chay_wf = self.r / "data" / "skills", self.r / "data" / "workflows"

        def nap() -> None:
            with mock.patch.object(sk, "_DEFAULTS_DIR", goc_sk), mock.patch.object(sk, "_SKILLS_DIR", chay_sk), \
                 mock.patch.object(sk, "_seeded", False), \
                 mock.patch.object(wf, "_DEFAULTS", goc_wf), mock.patch.object(wf, "_WF_DIR", chay_wf), \
                 mock.patch.object(wf, "_seeded", False):
                sk._ensure_seeded()
                wf._ensure_seeded()

        nap()
        (goc_sk / "giao-vien" / "SKILL.md").write_text("---\nname: GV\ndescription: d\n---\nv2\n",
                                                       encoding="utf-8")
        (goc_wf / "bai-hoc.md").write_text("v2", encoding="utf-8")
        nap()
        self.assertIn("v2", (chay_sk / "giao-vien" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual((chay_wf / "bai-hoc.md").read_text(encoding="utf-8"), "v2")
        self.assertEqual(sorted(f.name for f in chay_wf.glob("*.md")), ["bai-hoc.md"],
                         "sổ `.goc` không được lọt vào danh sách workflow")


if __name__ == "__main__":
    unittest.main()
