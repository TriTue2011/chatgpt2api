"""Google Dịch làm ý kiến thứ hai — services/google_dich.py.

Không chạm mạng: chặn ``urllib.request.urlopen``. Thứ cần chốt ở đây là các
tính chất AN TOÀN, vì đây là endpoint không công bố và chữ người dùng rời máy:
mặc định TẮT, lỗi không rò ra ngoài, và hỏng thì cầu dao ngắt chứ không gọi dồn.
"""
from __future__ import annotations

import io
import os
import unittest
import urllib.error
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import config
from services import google_dich as gd

#: Đúng dạng Google trả về (đo thật 28/08/2026), gồm cả việc CHIA CÂU.
_TRA_LOI = ('[[["Anh \\u1ea5y b\\u1ecb \\u0111\\u1ed9t qu\\u1ef5. ","He had a stroke. ",null,null,3],'
            '["Huy\\u1ebft \\u00e1p cao.","Blood pressure was high.",null,null,3]],'
            'null,"en",null,null,null,1,[]]')


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _gia(raw: str):
    return lambda req, timeout=None: _Resp(raw.encode("utf-8"))


class GoogleDichTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cu = config.data.get("dich_google")
        config.data["dich_google"] = {"bat": True}
        gd._nghi_toi = 0.0

    def tearDown(self) -> None:
        if self._cu is None:
            config.data.pop("dich_google", None)
        else:
            config.data["dich_google"] = self._cu
        gd._nghi_toi = 0.0

    # ── mặc định tắt ────────────────────────────────────────────────────────
    def test_mac_dinh_tat(self):
        config.data.pop("dich_google", None)
        self.assertFalse(gd.dang_bat())
        with self.assertRaises(gd.LoiGoogle):
            gd.dich("stroke", "vi", "en")

    def test_tat_thi_khong_goi_mang(self):
        config.data["dich_google"] = {"bat": False}
        with mock.patch("urllib.request.urlopen") as mo:
            with self.assertRaises(gd.LoiGoogle):
                gd.dich("stroke", "vi", "en")
        mo.assert_not_called()

    # ── phân tích dạng trả về ───────────────────────────────────────────────
    def test_noi_lai_cac_manh_chia_cau(self):
        with mock.patch("urllib.request.urlopen", _gia(_TRA_LOI)):
            ban, nhan = gd.dich("He had a stroke. Blood pressure was high.", "vi")
        self.assertEqual(ban, "Anh ấy bị đột quỵ. Huyết áp cao.")
        self.assertEqual(nhan, "en")   # tiếng nguồn Google tự nhận

    def test_dang_la_thi_bao_loi_chu_khong_doan(self):
        for raw in ('{"khong": "phai mang"}', "[]", "không phải json"):
            with mock.patch("urllib.request.urlopen", _gia(raw)):
                with self.assertRaises(gd.LoiGoogle):
                    gd.dich("stroke", "vi")

    def test_chu_rong_khong_goi_mang(self):
        with mock.patch("urllib.request.urlopen") as mo:
            self.assertEqual(gd.dich("   ", "vi"), ("", ""))
        mo.assert_not_called()

    # ── cầu dao ─────────────────────────────────────────────────────────────
    def test_loi_mang_thi_ngat_cau_dao(self):
        loi = urllib.error.URLError("bị chặn")
        with mock.patch("urllib.request.urlopen", side_effect=loi) as mo:
            with self.assertRaises(gd.LoiGoogle):
                gd.dich("stroke", "vi")
            # Lượt sau KHÔNG được gọi mạng nữa trong thời gian nghỉ.
            with self.assertRaises(gd.LoiGoogle):
                gd.dich("stroke", "vi")
        self.assertEqual(mo.call_count, 1)

    def test_cat_chu_qua_dai(self):
        ghi: dict[str, bytes] = {}

        def bat(req, timeout=None):
            ghi["body"] = req.data
            return _Resp(_TRA_LOI.encode("utf-8"))

        with mock.patch("urllib.request.urlopen", bat):
            gd.dich("x" * (gd.TRAN_KY_TU + 500), "vi")
        # +2 cho tiền tố "q=" trong body form-encoded.
        self.assertEqual(len(ghi["body"]), gd.TRAN_KY_TU + 2)


if __name__ == "__main__":
    unittest.main()
