"""TLS verify cho luồng đăng ký/mail — MẶC ĐỊNH BẬT, tắt được qua config.

Báo cáo bảo mật 07/08: verify=False áp cho toàn session gửi password/OTP/OAuth
code + nhận token → MITM đọc/sửa. Nay verify mặc định BẬT; chỉ tắt khi admin
đặt security.register_tls_verify=false.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class TlsVerifyDefaultTests(unittest.TestCase):
    def test_mac_dinh_bat(self):
        from services.register import openai_register as o, mail_provider as m
        from services.config import config
        with mock.patch.object(config, "get", return_value={}):
            self.assertTrue(o._tls_verify())
            self.assertTrue(m._tls_verify())

    def test_khong_con_verify_false_ky_tu(self):
        # Không còn literal verify=False trong mã (đã thay bằng _tls_verify()).
        for rel in ("services/register/openai_register.py",
                    "services/register/mail_provider.py"):
            src = (GOC / rel).read_text(encoding="utf-8")
            self.assertNotIn("verify=False", src, rel)
            self.assertNotIn(".verify = False", src, rel)

    def test_tat_duoc_qua_config(self):
        from services.register import openai_register as o, mail_provider as m
        from services.config import config
        with mock.patch.object(config, "get",
                               return_value={"security": {"register_tls_verify": False}}):
            self.assertFalse(o._tls_verify())
            self.assertFalse(m._tls_verify())


if __name__ == "__main__":
    unittest.main()
