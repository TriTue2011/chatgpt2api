"""Model Codex chỉ-trả-phí (gpt-5.4) chỉ hiện khi có tài khoản trả phí.

Đo ngày 03/09/2026 trên máy chủ thật, gọi thẳng chatgpt.com/backend-api/codex/
responses bằng token của từng tài khoản:

  - Gói `free` (7 tài khoản): "gpt-5.4" trả 400, còn gpt-5.6-terra, gpt-5.6-luna,
    gpt-5.5, gpt-5.4-mini đều 200.
  - Gói `go`  (1 tài khoản): "gpt-5.4" cũng 200.

Nên model Codex là THEO GÓI. Nếu cứ hiện gpt-5.4 cho mọi người, ai chỉ có tài
khoản free chọn phải nó là nhận 400 — đúng kiểu lỗi khó hiểu. Bộ test giữ:

  1. Không có tài khoản codex trả phí dùng được → ẩn cx/gpt-5.4 (và biến thể
     -review, :text), NHƯNG giữ cx/gpt-5.4-mini (free vẫn gọi được) và cx/auto.
  2. Có tài khoản trả phí ACTIVE → hiện lại cx/gpt-5.4.
  3. Tài khoản trả phí nhưng 'limited'/'disabled' KHÔNG tính là dùng được —
     đúng hiện trạng: tài khoản `go` duy nhất đang 'limited'.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.protocol.openai_v1_models as M


MAU = [{"id": "cx/auto"}, {"id": "cx/gpt-5.6-luna"}, {"id": "cx/gpt-5.5"},
       {"id": "cx/gpt-5.4-mini"}, {"id": "cx/gpt-5.4"}, {"id": "cx/gpt-5.4:text"},
       {"id": "cx/gpt-5.4-review"}]


class CongTheoGoiTests(unittest.TestCase):
    def _giu(self, co_tra_phi: bool) -> set[str]:
        with mock.patch.object(M, "_co_codex_tra_phi", return_value=co_tra_phi):
            return {m["id"] for m in M._curate_models(list(MAU))}

    def test_khong_tra_phi_thi_an_gpt54(self):
        giu = self._giu(False)
        self.assertNotIn("cx/gpt-5.4", giu)
        self.assertNotIn("cx/gpt-5.4:text", giu)
        self.assertNotIn("cx/gpt-5.4-review", giu)
        # nhưng vẫn giữ mini (free gọi được) và auto (model chính)
        self.assertIn("cx/gpt-5.4-mini", giu)
        self.assertIn("cx/auto", giu)

    def test_co_tra_phi_thi_hien_gpt54(self):
        giu = self._giu(True)
        self.assertIn("cx/gpt-5.4", giu)
        self.assertIn("cx/gpt-5.4-mini", giu)


class DungDuocNghiaLaGiTests(unittest.TestCase):
    """`_co_codex_tra_phi` chỉ đếm tài khoản codex trả phí, trạng thái dùng được."""

    def _accs(self, *accs):
        return mock.patch.object(M.account_service, "list_accounts", return_value=list(accs))

    def _codex(self, plan, status):
        # account_group xếp vào codex khi có tag type=codex.
        return {"type": "codex", "plan": plan, "status": status,
                "access_token": "eyJx", "refresh_token": "r"}

    def test_go_active_la_co(self):
        with self._accs(self._codex("go", "active")):
            self.assertTrue(M._co_codex_tra_phi())

    def test_go_limited_la_khong(self):
        # Đúng hiện trạng đo được: tài khoản `go` duy nhất đang 'limited'.
        with self._accs(self._codex("go", "limited")):
            self.assertFalse(M._co_codex_tra_phi())

    def test_chi_toan_free_la_khong(self):
        with self._accs(self._codex("free", "active"), self._codex("free", "active")):
            self.assertFalse(M._co_codex_tra_phi())


if __name__ == "__main__":
    unittest.main()
