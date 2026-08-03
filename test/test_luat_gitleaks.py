"""Luật gitleaks riêng của repo: bắt khoá thật, thôi bắt mã bình thường.

Đo thật 03/08 (bản quét sâu định kỳ trên main): luật cũ nhận BẤT KỲ phép gán nào
dài ≥7 ký tự sau `api_key/auth_key/...`, nên nó bắt cả `api_key = os.getenv(...)`,
`cfg.api_key = keysArr[0]`, `has_api_key: boolean`, `_BEARER = re.compile(...)`.
Kết quả 62/65 phát hiện là mã bình thường. Một cổng bảo mật lúc nào cũng đỏ vì
báo nhầm thì người ta ngừng đọc nó — đó mới là rủi ro thật.

File này khoá cả hai chiều: ba dạng khoá thật đã từng lộ vẫn phải BẮT, và năm
dạng mã bình thường phải BỎ QUA. Sửa regex trong `.gitleaks.toml` mà làm hỏng
chiều nào thì test này đổ ngay, không cần chờ tới lần quét định kỳ.
"""
from __future__ import annotations

import pathlib
import re
import unittest

GOC = pathlib.Path(__file__).resolve().parents[1]
CAU_HINH = GOC / ".gitleaks.toml"


def _luat_repo() -> tuple[str, int]:
    """(regex, secretGroup) của luật `chatgpt2api-inline-authkey`."""
    txt = CAU_HINH.read_text("utf-8")
    i = txt.index('id = "chatgpt2api-inline-authkey"')
    khoi = txt[i:i + 1200]
    rx = re.search(r"regex = '''(.+?)'''", khoi, re.S)
    sg = re.search(r"secretGroup = (\d+)", khoi)
    assert rx, "không tìm thấy regex của luật"
    return rx.group(1), int(sg.group(1)) if sg else 0


class LuatBatKhoaThat(unittest.TestCase):
    def setUp(self):
        mau, self.nhom = _luat_repo()
        self.rx = re.compile(mau)

    # ------------------------------------------------------------ phải BẮT
    def test_bat_auth_key_dang_bien_moi_truong(self):
        """Tên biến thật là CHATGPT2API_AUTH_KEY — ký tự trước 'AUTH' là '_' nên
        một `\\b` ở đầu regex sẽ trượt đúng ca đã xảy ra."""
        self.assertTrue(self.rx.search(
            "CHATGPT2API_AUTH_KEY=sk-live-abcdef0123456789"))

    def test_bat_authorization_bearer_dang_json(self):
        self.assertTrue(self.rx.search(
            '"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"'))

    def test_bat_api_key_gan_chuoi_cung(self):
        self.assertTrue(self.rx.search('api_key = "sk-proj-Abc123Def456Ghi789Jkl"'))

    # -------------------------------------------------------- phải BỎ QUA
    def test_bo_qua_doc_tu_bien_moi_truong(self):
        self.assertIsNone(self.rx.search('api_key = os.environ.get("OPENAI_API_KEY")'))

    def test_bo_qua_gan_tu_bien(self):
        self.assertIsNone(self.rx.search("cfg.api_key = keysArr[0]"))

    def test_bo_qua_khai_bao_kieu(self):
        self.assertIsNone(self.rx.search("has_api_key: boolean"))

    def test_bo_qua_dinh_nghia_regex(self):
        self.assertIsNone(self.rx.search('_BEARER = re.compile(r"Bearer (.+)")'))

    def test_bo_qua_gia_tri_qua_ngan(self):
        """Khoá thật đều dài; ngưỡng 16 ký tự cắt phần lớn báo nhầm."""
        self.assertIsNone(self.rx.search('api_key = "abc123"'))

    # ------------------------------------------------------------ cấu hình
    def test_secret_group_tro_vao_GIA_TRI(self):
        """Không có secretGroup thì allowlist so với cả dòng, lọc theo giá trị
        (vd `os.environ.get`) không có tác dụng."""
        self.assertEqual(self.nhom, 2)

    def test_allowlist_khong_che_khoa_that_trong_repo(self):
        """Client secret Google đang nằm trong mã KHÔNG được bị allowlist bỏ qua.

        Nó do bộ luật mặc định của gitleaks bắt, nhưng allowlist là TOÀN CỤC nên
        một mẫu quá rộng vẫn che được nó.
        """
        txt = CAU_HINH.read_text("utf-8")
        khoi = txt[txt.index("[allowlist]"):]
        mau_allow = re.findall(r"'''(.+?)'''", khoi, re.S)
        that = "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"
        for m in mau_allow:
            if m.startswith("\\.") or m.endswith("$)") or "/" in m:
                continue      # nhóm `paths`, không áp cho giá trị
            self.assertIsNone(re.search(m, that), m)


if __name__ == "__main__":
    unittest.main()
