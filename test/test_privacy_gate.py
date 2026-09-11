"""Privacy gate P0–P2 tests."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class PrivacyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        from services.privacy_gate import vault
        vault().clear_session("t1")
        vault().clear_session("default")
        vault().clear_session("log")

    def test_password_labeled_redacted(self) -> None:
        from services.privacy_gate import redact_text, resolve_secret_ref, vault

        raw = "đăng nhập user A mk: SuperSecret99!"
        out = redact_text(raw, session_id="t1")
        self.assertNotIn("SuperSecret99!", out)
        self.assertIn("⟦", out)
        # extract ref
        import re
        m = re.search(r"⟦[^⟧]+⟧", out)
        self.assertIsNotNone(m)
        resolved = resolve_secret_ref(m.group(0), session_id="t1")
        self.assertEqual(resolved, "SuperSecret99!")

    def test_jwt_and_sk_redacted(self) -> None:
        from services.privacy_gate import redact_text

        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        sk = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
        out = redact_text(f"token {jwt} key {sk}", session_id="t1")
        self.assertNotIn(jwt, out)
        self.assertNotIn(sk, out)

    def test_email_phone_pii(self) -> None:
        from services.privacy_gate import redact_text

        out = redact_text(
            "liên hệ a.b@example.com hoặc 0912345678",
            session_id="t1",
        )
        self.assertNotIn("a.b@example.com", out)
        self.assertNotIn("0912345678", out)

    def test_apply_to_body(self) -> None:
        from services.privacy_gate import apply_to_body

        body = {
            "user": "u1",
            "messages": [
                {"role": "user", "content": "password: MyPass1234"},
            ],
        }
        out = apply_to_body(body)
        content = out["messages"][0]["content"]
        self.assertNotIn("MyPass1234", content)
        self.assertEqual(out.get("_privacy_session"), "u1")

    def test_scrub_for_log(self) -> None:
        from services.privacy_gate import scrub_for_log

        s = scrub_for_log("user said password: leakme99")
        self.assertNotIn("leakme99", s)

    def test_resolve_in_tool_args(self) -> None:
        from services.privacy_gate import redact_text, resolve_secret_ref

        red = redact_text("mk: Abcdef12", session_id="tool")
        # full string may have prefix "mk: ⟦...⟧"
        import re
        ref = re.search(r"⟦[^⟧]+⟧", red).group(0)
        self.assertEqual(resolve_secret_ref(ref, session_id="tool"), "Abcdef12")

    # ── 11–12/09/2026: mật khẩu camera trong tên thực thể HA tới model ──────
    def test_URL_TAI_KHOAN_MAT_KHAU_ke_ca_MAT_KHAU_CO_A_CONG(self) -> None:
        from services.privacy_gate import redact_text, resolve_secret_ref
        import re

        out = redact_text("go2rtc rtsp://NguoiDung:Mat@Khau1@10.0.0.5:554/cua-sub", session_id="t1")
        self.assertNotIn("Khau1", out)
        self.assertNotIn("NguoiDung", out)
        self.assertIn("@10.0.0.5:554/cua-sub", out, "máy và luồng giữ nguyên để còn dùng")
        ref = re.search(r"⟦[^⟧]+⟧", out).group(0)
        self.assertEqual(resolve_secret_ref(ref, session_id="t1"), "NguoiDung:Mat@Khau1",
                         "tool mở lại được nguyên cặp tài khoản:mật khẩu")
        self.assertEqual(redact_text("rtsp://10.0.0.5:554/bep", session_id="t1"),
                         "rtsp://10.0.0.5:554/bep", "URL không kèm mật khẩu thì để yên")

    def test_JSON_va_THAM_SO_co_TEN_KHOA_BI_MAT(self) -> None:
        """Kết quả tool và thuộc tính HA là JSON; ảnh camera HA mang `?token=`."""
        from services.privacy_gate import redact_text

        out = redact_text('{"host": "10.0.0.5", "password": "Abc12345", "local_key": "k9k9k9k9",'
                          ' "max_tokens": 900, "pin": "85"}', session_id="t1")
        self.assertNotIn("Abc12345", out)
        self.assertNotIn("k9k9k9k9", out)
        self.assertIn('"host": "10.0.0.5"', out)
        self.assertIn('"max_tokens": 900', out, "khoá trông giống bí mật mà không phải thì để yên")
        self.assertIn('"pin": "85"', out, "pin là PIN pin điện thoại/cảm biến — không phải mật khẩu")
        anh = redact_text("/api/camera_proxy/camera.cua?token=abcdef123456&t=1", session_id="t1")
        self.assertNotIn("abcdef123456", anh)
        self.assertIn("&t=1", anh)

    def test_NHAN_TIENG_VIET_co_chu_LA(self) -> None:
        from services.privacy_gate import redact_text

        for cau in ("mật khẩu wifi nhà là Abc12345", "mat khau camera la Abc12345",
                    "Mật khẩu là Abc12345"):
            self.assertNotIn("Abc12345", redact_text(cau, session_id="t1"), cau)
        self.assertEqual(redact_text("độ ẩm phòng khách là 80 phần trăm", session_id="t1"),
                         "độ ẩm phòng khách là 80 phần trăm")

    def test_CHI_CHE_MAT_KHAU_thi_GIU_SO_DIEN_THOAI(self) -> None:
        """Lời nhắc vẽ ảnh và câu tìm kiếm: che mật khẩu, giữ số điện thoại — tờ
        rơi in số điện thoại, hay tra một số lạ, là việc bình thường."""
        from services.privacy_gate import redact_text

        out = redact_text("vẽ tờ rơi hotline 0912345678, wifi mật khẩu là Abc12345",
                          session_id="image", redact_pii=False)
        self.assertIn("0912345678", out)
        self.assertNotIn("Abc12345", out)

    def test_CHE_HAI_LAN_ra_Y_NHU_CHE_MOT_LAN(self) -> None:
        """Tin bị che ở cửa vào rồi lại ở cửa ra. Mã két `⟦PWD:1:abc⟧` có chữ
        "PWD:" — lần hai mà che lồng lên thì tool không mở lại được mật khẩu."""
        from services.privacy_gate import redact_text, resolve_secret_ref
        import re

        for tho in ("mk: Abcdef12", "rtsp://tk:MatKhau99@h/x", '{"password": "Abc12345"}',
                    "mật khẩu wifi là Abc12345", "password=Qwerty123 và token: t0k3n999"):
            mot = redact_text(tho, session_id="t1")
            self.assertEqual(redact_text(mot, session_id="t1"), mot, tho)
            for ref in re.findall(r"⟦[^⟧]+⟧", mot):
                self.assertNotEqual(resolve_secret_ref(ref, session_id="t1"), ref,
                                    f"mã két {ref} phải mở lại được")

    def test_CUA_RA_MODEL_che_ca_NOI_DUNG_CHEN_SAU_CUA_VAO(self) -> None:
        """Ngữ cảnh HA chèn SAU `apply_to_body`; `_dispatch` là cửa cuối ra model."""
        from unittest import mock
        import services.protocol.openai_v1_chat_complete as occ

        gui: list = []
        with mock.patch.object(occ, "_dispatch_provider",
                               side_effect=lambda route, msgs, *a: gui.append(msgs) or {"choices": []}):
            occ._dispatch(None, [{"role": "system", "content": "Nhà: Cam cửa rtsp://tk:MatKhau99@h/x"},
                                 {"role": "user", "content": "camera cửa sao rồi"}],
                          None, None, {"user": "u1", "_privacy_session": "u1"})
        self.assertNotIn("MatKhau99", str(gui[0]))
        self.assertIn("camera cửa sao rồi", str(gui[0]))


if __name__ == "__main__":
    unittest.main()
