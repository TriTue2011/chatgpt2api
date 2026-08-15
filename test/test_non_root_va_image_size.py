"""Hai món nợ cuối: tách quyền cho runtime, và chặn đầu vào của image-size.

Cả hai đều là loại "chưa xong hẳn", nên test ở đây chốt đúng những gì ĐÃ làm
và những gì phải giữ nguyên để bước cuối không hỏng.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
DOCKERFILE = (GOC / "Dockerfile").read_text(encoding="utf-8")
SUPERVISOR = (GOC / "deploy/supervisord.conf").read_text(encoding="utf-8")
COMPOSE = (GOC / "docker-compose.yml").read_text(encoding="utf-8")
ZALO = (GOC / "zalo-server/api/zalo/zalo.js").read_text(encoding="utf-8")


class MacDinhKhongDoiHanhViTests(unittest.TestCase):
    """Bước chuẩn bị KHÔNG được đổi gì cho tới khi chủ máy chủ động bật."""

    def test_APP_USER_mac_dinh_la_root(self):
        self.assertRegex(DOCKERFILE, r"(?m)^ENV APP_USER=root")
        self.assertIn("APP_USER: ${APP_USER:-root}", COMPOSE)

    def test_APP_PORT_mac_dinh_la_80(self):
        self.assertIn("APP_PORT: ${APP_PORT:-80}", COMPOSE)
        self.assertIn("${APP_PORT:-80}", SUPERVISOR)

    def test_healthcheck_theo_APP_PORT(self):
        """Non-root phải dùng 8080, nên healthcheck không được đóng đinh 80."""
        expected = "os.getenv('APP_PORT', '80')"
        self.assertIn(expected, DOCKERFILE)
        self.assertIn(expected, COMPOSE)
        self.assertNotIn("localhost:80/version", DOCKERFILE)
        self.assertNotIn("localhost:80/version", COMPOSE)

    def test_co_nguoi_dung_khong_dac_quyen_san(self):
        self.assertRegex(DOCKERFILE, r"useradd .*c2a")


class TachQuyenTests(unittest.TestCase):
    def test_bon_dich_vu_ung_dung_chay_duoi_APP_USER(self):
        for ten in ("vn-mcp-hub", "captcha-api", "zalo-server", "chatgpt2api"):
            i = SUPERVISOR.index(f"[program:{ten}]")
            khoi = SUPERVISOR[i:SUPERVISOR.index("[program:", i + 10)] \
                if "[program:" in SUPERVISOR[i + 10:] else SUPERVISOR[i:]
            self.assertIn("user=%(ENV_APP_USER)s", khoi, f"{ten} chưa theo APP_USER")

    def test_bo_X_VAN_chay_root(self):
        """Xvfb/x11vnc cần root — ép chúng non-root là màn hình chết."""
        for ten in ("xvfb", "x11vnc", "novnc", "fluxbox"):
            i = SUPERVISOR.index(f"[program:{ten}]")
            khoi = SUPERVISOR[i:i + 400]
            self.assertNotIn("user=%(ENV_APP_USER)s", khoi,
                             f"{ten} bị ép sang APP_USER")

    def test_tu_chown_volume_TRUOC_khi_khoi_dong(self):
        """Bind mount mang UID của host — không chown thì container lên được
        nhưng không ghi nổi config/cookie, hỏng im lặng."""
        self.assertIn("[program:chuan-bi-quyen]", SUPERVISOR)
        i = SUPERVISOR.index("[program:chuan-bi-quyen]")
        khoi = SUPERVISOR[i:i + 600]
        self.assertIn("chown -R", khoi)
        self.assertIn("priority=1", khoi)

    def test_chown_KHONG_chay_khi_van_la_root(self):
        """Chạy root thì chown là thao tác thừa trên toàn bộ volume."""
        i = SUPERVISOR.index("[program:chuan-bi-quyen]")
        self.assertIn('"$APP_USER" != "root"', SUPERVISOR[i:i + 600])

    def test_canh_bao_ve_cong_dac_quyen(self):
        """Đổi APP_USER mà quên APP_PORT thì app không bind được cổng 80."""
        self.assertIn("đặc quyền", SUPERVISOR)
        self.assertIn("1024", SUPERVISOR)

    def test_uu_tien_chuan_bi_quyen_thap_hon_moi_dich_vu(self):
        so = {}
        for m in re.finditer(r"\[program:([\w-]+)\]", SUPERVISOR):
            ten = m.group(1)
            khoi = SUPERVISOR[m.start():m.start() + 700]
            p = re.search(r"(?m)^priority=(\d+)", khoi)
            if p:
                so[ten] = int(p.group(1))
        self.assertLess(so["chuan-bi-quyen"], min(v for k, v in so.items()
                                                  if k != "chuan-bi-quyen"))


class ChanDauVaoImageSizeTests(unittest.TestCase):
    """`image-size` có lỗ DoS mà thượng nguồn CHƯA có bản vá (fixAvailable:false).

    Ảnh ở đây do người dùng Zalo gửi lên — dữ liệu kẻ tấn công điều khiển được.
    """

    def test_truyen_BUFFER_chu_khong_truyen_duong_dan(self):
        self.assertNotIn("sizeOf(filePath)", ZALO,
                         "vẫn để thư viện tự đọc bao nhiêu tuỳ nó")
        self.assertIn("sizeOf(dau)", ZALO)

    def test_co_tran_cho_phan_header_doc_vao(self):
        i = ZALO.index("TRAN_HEADER")
        self.assertIn("256 * 1024", ZALO[i:i + 200])

    def test_khong_doc_qua_kich_thuoc_file_that(self):
        """File nhỏ hơn trần thì chỉ đọc đúng phần có thật."""
        i = ZALO.index("TRAN_HEADER")
        self.assertIn("Math.min(stats.size, TRAN_HEADER)", ZALO[i:i + 300])

    def test_dong_file_ke_ca_khi_loi(self):
        """Rò file descriptor là kiểu lỗi chỉ lộ ra sau nhiều ngày chạy."""
        i = ZALO.index("const fdH = fs.openSync")
        self.assertIn("finally { fs.closeSync(fdH); }", ZALO[i:i + 300])


if __name__ == "__main__":
    unittest.main()
