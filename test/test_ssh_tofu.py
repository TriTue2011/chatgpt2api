"""Policy host-key SSH phải FAIL-CLOSED.

Bối cảnh: bản đầu của `services/ssh_tofu.py` chỉ `logger.warning` khi không ghi
được known_hosts rồi vẫn chấp nhận khoá. Như thế là vô hiệu hoá chính nó — không
lưu được thì mọi lần kết nối sau đều là "lần đầu", khoá máy chủ có bị tráo cũng
không ai biết, đúng cái lỗ của `AutoAddPolicy` mà file này sinh ra để bịt.

Ba tình huống bắt buộc:
1. Khoá lần đầu → ghi được xuống known_hosts.
2. Khoá ĐỔI so với lần trước → từ chối.
3. Không ghi được (thư mục chỉ-đọc) → từ chối kết nối, KHÔNG chấp nhận suông.
"""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import paramiko  # noqa: E402

from services.ssh_tofu import fingerprint, tofu_policy  # noqa: E402

HOST = "[10.9.9.9]:2222"


def _khoa():
    """Sinh một khoá máy chủ. RSA 1024 cho nhanh — test không cần độ mạnh."""
    return paramiko.RSAKey.generate(1024)


class GhiKhoaLanDauTests(unittest.TestCase):
    def test_khoa_lan_dau_duoc_ghi_xuong_known_hosts(self):
        with tempfile.TemporaryDirectory() as d:
            kh = Path(d) / "sub" / "known_hosts"   # thư mục con chưa tồn tại
            client = paramiko.SSHClient()
            key = _khoa()

            tofu_policy(kh).missing_host_key(client, HOST, key)

            self.assertTrue(kh.exists(), "phải tạo cả thư mục cha và file")
            hk = paramiko.HostKeys(str(kh))
            self.assertIn(HOST, hk.keys())
            self.assertEqual(fingerprint(hk[HOST][key.get_name()]), fingerprint(key))

    def test_file_khong_de_nguoi_khac_doc(self):
        with tempfile.TemporaryDirectory() as d:
            kh = Path(d) / "known_hosts"
            tofu_policy(kh).missing_host_key(paramiko.SSHClient(), HOST, _khoa())
            self.assertEqual(stat.S_IMODE(kh.stat().st_mode), 0o600)


class KhoaDoiBiTuChoiTests(unittest.TestCase):
    def test_khoa_doi_thi_khong_con_khop(self):
        """Sau khi ghi nhớ, một khoá KHÁC cho cùng host phải không khớp.

        Đây chính là dữ kiện `SSHClient.connect` dùng để ném BadHostKeyException
        trước khi policy được hỏi tới — nên kiểm ở tầng HostKeys là kiểm đúng
        thứ quyết định, mà không cần dựng một máy chủ SSH thật.
        """
        with tempfile.TemporaryDirectory() as d:
            kh = Path(d) / "known_hosts"
            cu = _khoa()
            tofu_policy(kh).missing_host_key(paramiko.SSHClient(), HOST, cu)

            hk = paramiko.HostKeys(str(kh))
            self.assertTrue(hk.check(HOST, cu), "khoá cũ phải vẫn khớp")

            moi = _khoa()
            self.assertNotEqual(fingerprint(moi), fingerprint(cu))
            self.assertFalse(hk.check(HOST, moi), "khoá đổi mà vẫn khớp là hỏng")

    def test_host_da_biet_thi_policy_khong_duoc_goi(self):
        """Nạp known_hosts rồi thì host đó không còn là 'missing' nữa.

        Chốt lại đường đi: policy CHỈ áp cho host chưa từng thấy; host đã ghi
        nhớ do paramiko tự xử lý (khớp thì đi tiếp, lệch thì BadHostKeyException).
        """
        with tempfile.TemporaryDirectory() as d:
            kh = Path(d) / "known_hosts"
            key = _khoa()
            tofu_policy(kh).missing_host_key(paramiko.SSHClient(), HOST, key)

            client = paramiko.SSHClient()
            client.load_host_keys(str(kh))
            self.assertIsNotNone(client.get_host_keys().lookup(HOST))


class KhongGhiDuocThiTuChoiTests(unittest.TestCase):
    def test_thu_muc_chi_doc_thi_tu_choi_ket_noi(self):
        with tempfile.TemporaryDirectory() as d:
            ro = Path(d) / "ro"
            ro.mkdir()
            os.chmod(ro, 0o500)          # r-x: không tạo được file mới
            try:
                pol = tofu_policy(ro / "known_hosts")
                with self.assertRaises(paramiko.SSHException) as ctx:
                    pol.missing_host_key(paramiko.SSHClient(), HOST, _khoa())
                self.assertIn("Từ chối kết nối", str(ctx.exception))
            finally:
                # Trả quyền TRONG khối with — addCleanup chạy sau khi
                # TemporaryDirectory đã xoá xong, lúc đó chmod không còn gì để sửa.
                os.chmod(ro, 0o700)

    def test_khong_co_noi_luu_thi_tu_choi_ket_noi(self):
        """`tofu_policy(None)` — nhánh xảy ra khi không lấy được DATA_DIR."""
        with self.assertRaises(paramiko.SSHException) as ctx:
            tofu_policy(None).missing_host_key(paramiko.SSHClient(), HOST, _khoa())
        self.assertIn("Từ chối kết nối", str(ctx.exception))

    def test_tu_choi_thay_vi_am_tham_chap_nhan(self):
        """Chốt lại điều dễ hồi quy nhất: KHÔNG được nuốt lỗi rồi đi tiếp."""
        with tempfile.TemporaryDirectory() as d:
            ro = Path(d) / "ro"
            ro.mkdir()
            os.chmod(ro, 0o500)
            kh = ro / "known_hosts"
            try:
                try:
                    tofu_policy(kh).missing_host_key(paramiko.SSHClient(), HOST, _khoa())
                except paramiko.SSHException:
                    pass
                else:
                    self.fail("chấp nhận khoá dù không lưu được — lỗ hổng đã quay lại")
                self.assertFalse(kh.exists())
            finally:
                os.chmod(ro, 0o700)


if __name__ == "__main__":
    unittest.main()
