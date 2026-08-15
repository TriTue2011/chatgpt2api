"""Câu trả lời dài: cắt thì phải BÁO, và model phải được dặn viết gọn.

Chủ máy nêu 16/08/2026: một bản chép lời dài bị xé thành nhiều tin liên tiếp
thì đọc rất mệt — "nhiều tin tổng hợp căn cứ vào đó để có thể làm tổng hợp
càng ngắn càng tốt".

Hai chỗ hỏng nằm sau nhận xét đó:

1. `send_message` gửi tối đa `_MAX_CHUNKS` khúc rồi **lặng lẽ bỏ phần còn
   lại** (`chunks[:_MAX_CHUNKS]`). Nội dung mất mà không có dấu hiệu nào —
   người đọc tưởng đã hết.
2. System prompt không hề nói cho model biết trần một tin là bao nhiêu, nên
   nó không có căn cứ nào để tự viết gọn.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_personal as zp  # noqa: E402
from services.telegram.format import split_message  # noqa: E402


class TestSoTinToiDa(unittest.TestCase):
    def test_khong_qua_ba_tin_cho_mot_cau_tra_loi(self) -> None:
        self.assertLessEqual(zp._MAX_CHUNKS, 3)

    def test_moi_khuc_van_nam_trong_tran_zalo(self) -> None:
        dai = "Một câu tiếng Việt có dấu, đủ dài để phải cắt. " * 500
        for khuc in split_message(dai, limit=zp._MAX_LEN, prefer=zp._MAX_LEN):
            self.assertLessEqual(len(khuc), 3000)


class TestBaoKhiCat(unittest.TestCase):
    """Phần bị cắt phải hiện ra trong tin cuối, không được im lặng."""

    def _gui(self, raw: str) -> list[str]:
        da_gui: list[str] = []

        def _gia(_method, _path, payload=None, **_kw):
            body = (payload or {}).get("message") or {}
            da_gui.append(str(body.get("msg") or ""))
            return {"ok": True, "data": {"ok": True}}

        import unittest.mock as m
        with m.patch.object(zp, "_request", side_effect=_gia), \
             m.patch.object(zp, "_account_for_send", return_value="acc1"):
            zp.send_message("thread1", raw, 0, account="acc1", rich=False)
        return da_gui

    def test_dai_vua_thi_gui_du_khong_them_ghi_chu(self) -> None:
        raw = "x" * (zp._MAX_LEN * 2 - 10)
        gui = self._gui(raw)
        self.assertEqual(len(gui), 2)
        self.assertNotIn("còn ~", gui[-1])

    def test_dai_qua_thi_tin_cuoi_noi_ro_da_cat(self) -> None:
        raw = "y" * (zp._MAX_LEN * (zp._MAX_CHUNKS + 3))
        gui = self._gui(raw)
        self.assertEqual(len(gui), zp._MAX_CHUNKS, "gửi quá số tin cho phép")
        self.assertIn("còn ~", gui[-1])
        self.assertIn("tệp", gui[-1].lower(), "phải mời gửi bản đầy đủ bằng tệp")


class TestDanModelVietGon(unittest.TestCase):
    def test_system_prompt_neu_tran_mot_tin(self) -> None:
        from services.agent import orchestrator as orch

        prompt = orch._build_system_prompt("zalop_thread1")
        self.assertIn("Độ dài câu trả lời", prompt)
        self.assertIn("3.000 ký tự", prompt)
        self.assertIn("2.900", prompt)


if __name__ == "__main__":
    unittest.main()
