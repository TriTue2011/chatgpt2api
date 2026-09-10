"""Project Flow bị Google xoá KHÔNG phải là mất phiên Google.

Hai chuyện khác hẳn nhau mà solver báo về bằng cùng một lời nhắn 401:

  (a) phiên Google chết thật      → phải đăng nhập lại
  (b) project_id đã lưu bị XOÁ    → chỉ cần xin project mới

Đo 10/09/2026 (google-mitbap0610): cookie phiên còn đủ, hạn 398 ngày, mà
check-project vẫn trả 401. Tạo project mới thì HTTP 200 trong 68 giây, không
cần đăng nhập lần nào.

Kết luận nhầm (b) thành (a) là chạy đăng nhập tự động — mà mỗi lượt đó là một
lần mời Google bung captcha. Thực tế đã xảy ra: lượt khôi phục cho một tài
khoản làm ba tài khoản còn lại dính reCAPTCHA theo.
"""

from __future__ import annotations

import unittest
from unittest import mock


class ProjectHetHanTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.account_recovery as ar
        self.ar = ar

    def _tra_401(self, detail):
        """Giả lập solver trả 401 với `detail` cho trước.

        Vá thẳng `requests.post`, KHÔNG vá qua module: account_recovery import
        requests bên trong hàm nên `self.ar.requests` không tồn tại.
        """
        class _R:
            status_code = 401

            @staticmethod
            def json():
                return {"detail": detail}

        return mock.patch("requests.post", return_value=_R())

    def _co_project(self, pid="p-cu"):
        return mock.patch.object(self.ar, "_flow_project_id", return_value=pid)

    def _solver(self):
        return mock.patch.object(self.ar, "_solver_cfg",
                                 return_value=("http://x", "key"))

    # ── mấu chốt ───────────────────────────────────────────────────────────
    def test_PROJECT_XOA_THI_TAO_MOI_KHONG_DANG_NHAP(self) -> None:
        """401 + tạo được project mới → 'ok', KHÔNG kết luận mất phiên."""
        with self._solver(), self._co_project(), \
             self._tra_401("Phiên Google Flow của x cần đăng nhập lại Google."), \
             mock.patch.object(self.ar, "_flow_tao_project_moi",
                               return_value=True) as tao:
            tt = self.ar._flow_session_trang_thai("google-x")
        self.assertEqual(tt, "ok", "tạo được project mới thì phiên vẫn SỐNG")
        tao.assert_called_once()

    def test_tao_project_hong_moi_ket_luan_mat_phien(self) -> None:
        with self._solver(), self._co_project(), \
             self._tra_401("Phiên Google Flow của x cần đăng nhập lại Google."), \
             mock.patch.object(self.ar, "_flow_tao_project_moi", return_value=False):
            self.assertEqual(self.ar._flow_session_trang_thai("google-x"), "mat")

    def test_401_dang_DICT_van_hieu_dung(self) -> None:
        """Đường ném lỗi kia (main.py) trả dict có code — phải nhận cả hai dạng."""
        with self._solver(), self._co_project(), \
             self._tra_401({"code": "flow_login_required", "message": "x"}):
            self.assertEqual(self.ar._flow_session_trang_thai("google-x"), "mat")

    def test_401_la_thi_KHONG_doan_bua(self) -> None:
        """Lỗi 401 không rõ nguyên nhân → 'chua_ro', không kích hoạt gì."""
        with self._solver(), self._co_project(), self._tra_401("khoá API sai"):
            self.assertEqual(self.ar._flow_session_trang_thai("google-x"), "chua_ro")

    def test_khong_co_project_id_thi_chua_ro(self) -> None:
        with self._solver(), self._co_project(""):
            self.assertEqual(self.ar._flow_session_trang_thai("google-x"), "chua_ro")

    # ── tạo project mới ────────────────────────────────────────────────────
    def test_tao_moi_luu_lai_project_id(self) -> None:
        """Lưu lại để lần sau khỏi xin nữa."""
        class _R:
            status_code = 200

            @staticmethod
            def json():
                return {"project_id": "p-moi", "action": "created"}

        da_ghi = {}

        def _mutate(fn):
            data = {"providers": {"flow": {"accounts": [
                {"profile": "google-x", "project_id": "p-cu"}]}}}
            fn(data)
            da_ghi.update(data)

        from services.config import config
        with self._solver(), \
             mock.patch("requests.post", return_value=_R()), \
             mock.patch.object(config, "mutate", side_effect=_mutate):
            self.assertTrue(self.ar._flow_tao_project_moi("google-x"))
        acc = da_ghi["providers"]["flow"]["accounts"][0]
        self.assertEqual(acc["project_id"], "p-moi")

    def test_tao_moi_mang_hong_thi_tra_False(self) -> None:
        with self._solver(), \
             mock.patch("requests.post",
                               side_effect=RuntimeError("mất mạng")):
            self.assertFalse(self.ar._flow_tao_project_moi("google-x"))

    def test_tao_moi_khong_co_solver_thi_tra_False(self) -> None:
        with mock.patch.object(self.ar, "_solver_cfg", return_value=("", "")):
            self.assertFalse(self.ar._flow_tao_project_moi("google-x"))

    def test_ghi_config_hong_van_tra_True(self) -> None:
        """Lấy được project rồi thì ghi hỏng cũng không được phủ nhận kết quả."""
        class _R:
            status_code = 200

            @staticmethod
            def json():
                return {"project_id": "p-moi"}

        from services.config import config
        with self._solver(), \
             mock.patch("requests.post", return_value=_R()), \
             mock.patch.object(config, "mutate", side_effect=OSError("đĩa đầy")):
            self.assertTrue(self.ar._flow_tao_project_moi("google-x"))


if __name__ == "__main__":
    unittest.main()
