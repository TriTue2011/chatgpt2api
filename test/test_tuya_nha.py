"""Test lớp Tuya — ký request, che bí mật, khớp tên, dịch lỗi.

Không gọi mạng thật: mọi lời gọi HTTP đều bị chặn bằng mock.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest import mock


class TuyaTest(unittest.TestCase):
    AID = "test_access_id_123"
    SEC = "test_secret_456"

    def setUp(self) -> None:
        from services import tuya_nha as t
        from services.config import config

        self.t = t
        self._cu = config.data.get("tuya")
        config.data["tuya"] = {"bat": True, "access_id": self.AID,
                               "access_secret": self.SEC, "endpoint": "america"}
        t._reset_for_tests()

    def tearDown(self) -> None:
        from services.config import config
        if self._cu is None:
            config.data.pop("tuya", None)
        else:
            config.data["tuya"] = self._cu
        self.t._reset_for_tests()

    def _tra(self, *payloads):
        """Giả lập urlopen trả lần lượt các payload."""
        it = iter(payloads)

        class _R:
            def __init__(self, d): self._d = json.dumps(d).encode()
            def read(self): return self._d
            def __enter__(self): return self
            def __exit__(self, *a): return False

        return mock.patch.object(self.t.urllib.request, "urlopen",
                                 side_effect=lambda *a, **k: _R(next(it)))

    def _token_ok(self):
        return {"success": True, "result": {"access_token": "TOK", "expire_time": 7200}}

    # ── ký ─────────────────────────────────────────────────────────────────
    def test_ky_dung_cong_thuc_cua_tuya(self) -> None:
        """Sai một dấu xuống dòng là Tuya trả 'sign invalid'."""
        body_hash = hashlib.sha256(b"").hexdigest()
        chuoi = f"{self.AID}1234GET\\n{body_hash}\\n\\n/v1.0/token?grant_type=1"
        mong = hmac.new(self.SEC.encode(), chuoi.encode(),
                        hashlib.sha256).hexdigest().upper()
        self.assertEqual(self.t._ky(self.SEC, chuoi), mong)

    def test_header_co_du_truong_bat_buoc(self) -> None:
        ghi = {}

        class _R:
            def read(self): return json.dumps({"success": True, "result": {}}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _bat(req, *a, **k):
            ghi.update(dict(req.headers))
            return _R()

        with mock.patch.object(self.t.urllib.request, "urlopen", side_effect=_bat):
            self.t._goi("/v1.0/token?grant_type=1")
        thap = {k.lower() for k in ghi}
        for c in ("client_id", "sign", "t", "sign_method"):
            self.assertIn(c, thap, f"thiếu header {c}")

    def test_token_duoc_dung_lai_khong_xin_moi_moi_lan(self) -> None:
        with self._tra(self._token_ok(), {"success": True, "result": []},
                       {"success": True, "result": []}):
            self.t.goi_api("/a")
            self.t.goi_api("/b")
        self.assertEqual(self.t._stats["goi"], 3, "1 lần token + 2 lần gọi")

    # ── che bí mật ─────────────────────────────────────────────────────────
    def test_che_bi_mat_khong_lo_secret(self) -> None:
        """Lộ cặp access_id + secret là điều khiển được KHOÁ CỬA từ xa."""
        c = self.t.che_bi_mat({"access_id": "aaaa1111bbbb2222cccc",
                               "access_secret": "dddd3333eeee4444ffff",
                               "password": "MatKhau@123", "local_key": "abc123"})
        phang = json.dumps(c, ensure_ascii=False)
        for bi_mat in ("dddd3333eeee4444ffff", "MatKhau@123", "abc123",
                       "aaaa1111bbbb2222cccc"):
            self.assertNotIn(bi_mat, phang, f"{bi_mat!r} BỊ LỘ")

    def test_ten_truong_tuya_nam_trong_danh_sach_bi_mat(self) -> None:
        """settings_secrets phải tự che khi trả /api/settings."""
        from services import settings_secrets as ss
        che = ss.che_giau({"tuya": {"access_id": "A", "access_secret": "B",
                                    "local_key": "C", "endpoint": "america"}})["tuya"]
        for k in ("access_id", "access_secret", "local_key"):
            self.assertIsInstance(che[k], dict, f"{k} phải bị che")
        self.assertEqual(che["endpoint"], "america", "endpoint không phải bí mật")

    # ── dịch lỗi sang tiếng Việt ───────────────────────────────────────────
    def test_bao_ro_khi_het_han_goi_dich_vu(self) -> None:
        with self._tra({"success": False, "msg": "IoT Core service subscription has expired."}):
            with self.assertRaises(self.t.LoiTuya) as e:
                self.t._goi("/v1.0/x")
        self.assertIn("hết hạn", str(e.exception))
        self.assertIn("iot.tuya.com", str(e.exception))

    def test_bao_ro_khi_sai_chu_ky(self) -> None:
        with self._tra({"success": False, "msg": "sign invalid"}):
            with self.assertRaises(self.t.LoiTuya) as e:
                self.t._goi("/v1.0/x")
        self.assertIn("Access Secret", str(e.exception))

    def test_bao_ro_khi_sai_vung(self) -> None:
        with self._tra({"success": False, "msg": "cross-region access is not allowed"}):
            with self.assertRaises(self.t.LoiTuya) as e:
                self.t._goi("/v1.0/x")
        self.assertIn("vùng", str(e.exception).lower())

    def test_chua_khai_thi_bao_cho_nhap(self) -> None:
        from services.config import config
        config.data["tuya"] = {"bat": True}
        with self.assertRaises(self.t.LoiTuya) as e:
            self.t._goi("/v1.0/x")
        self.assertIn("Cài đặt", str(e.exception))

    # ── thiết bị ───────────────────────────────────────────────────────────
    def test_page_size_khong_qua_20(self) -> None:
        """Đo thật: 50 và 100 đều trả 'param size too much'."""
        goi = []

        class _R:
            def read(self): return json.dumps({"success": True, "result": []}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _bat(req, *a, **k):
            goi.append(req.full_url)
            return _R()

        with mock.patch.object(self.t.urllib.request, "urlopen", side_effect=_bat):
            self.t._token["token"] = "TOK"
            self.t._token["het_han"] = 9e18
            self.t.danh_sach_thiet_bi()
        self.assertTrue(any("page_size=20" in u for u in goi))
        self.assertFalse(any("page_size=100" in u or "page_size=50" in u for u in goi))

    def test_SAP_XEP_THAM_SO_TRUOC_KHI_KY(self) -> None:
        """Tuya đòi tham số truy vấn sắp theo bảng chữ cái, nếu không → "sign
        invalid" — rất dễ tưởng nhầm là nhập sai Access Secret.

        Đo thật 09/09/2026: cùng URL, để nguyên thứ tự thì hỏng, sắp xếp thì
        trả về 20 bản ghi.
        """
        gui = []

        class _R:
            def read(self): return json.dumps({"success": True, "result": {}}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _bat(req, *a, **k):
            gui.append(req.full_url)
            return _R()

        with mock.patch.object(self.t.urllib.request, "urlopen", side_effect=_bat):
            self.t._goi("/v1.0/x?start_time=1&end_time=9&type=7&size=20")
        duong = gui[0].split("?", 1)[1]
        self.assertEqual(duong, "&".join(sorted(duong.split("&"))),
                         "tham số phải được sắp xếp")

    def test_doan_loai_thiet_bi(self) -> None:
        self.assertEqual(self.t._doan_loai({"category": "videolock"}),
                         "khoá cửa có camera")
        self.assertEqual(self.t._doan_loai({"category": "kg"}), "công tắc")

    def test_loai_la_khong_doan_bua(self) -> None:
        """Mã lạ thì hiện nguyên mã, KHÔNG bịa tên."""
        self.assertEqual(self.t._doan_loai({"category": "xyz999"}), "loại xyz999")
        self.assertEqual(self.t._doan_loai({}), "chưa rõ loại")

    # ── khớp tên ───────────────────────────────────────────────────────────
    DS = [{"id": "d1", "ten": "Smart Lock", "loai": "khoá cửa có camera"},
          {"id": "d2", "ten": "HA gateway", "loai": "cổng kết nối"}]

    def test_khop_ten_tieng_viet_qua_LOAI(self) -> None:
        """Thiết bị tên tiếng Anh, người dùng gọi tiếng Việt — phải khớp."""
        self.assertEqual(self.t._khop_ten("khoá cửa", self.DS), "d1")
        self.assertEqual(self.t._khop_ten("khoa cua", self.DS), "d1")

    def test_khop_ten_tieng_anh(self) -> None:
        self.assertEqual(self.t._khop_ten("smart lock", self.DS), "d1")

    def test_MAP_MO_THI_TRA_RONG(self) -> None:
        """Mở nhầm KHOÁ CỬA là chuyện không sửa lại được — thà hỏi lại."""
        self.assertEqual(self.t._khop_ten("cái gì đó", self.DS), "")
        self.assertEqual(self.t._khop_ten("", self.DS), "")

    def test_thu_ket_noi_khong_raise_khi_hong(self) -> None:
        with self._tra({"success": False, "msg": "sign invalid"}):
            kq = self.t.thu_ket_noi()
        self.assertFalse(kq["ok"])
        self.assertIn("error", kq)

    def test_stats_khong_lo_secret(self) -> None:
        s = self.t.stats()
        self.assertNotIn(self.SEC, json.dumps(s))
        self.assertNotIn(self.AID, json.dumps(s))


if __name__ == "__main__":
    unittest.main()
