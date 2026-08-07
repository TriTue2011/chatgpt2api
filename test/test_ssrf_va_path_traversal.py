"""Chặn SSRF khi tải ảnh HTTP + path traversal khi xoá backup.

Báo cáo bảo mật 07/08:
- delete_backup(filename) ghép thẳng BACKUP_DIR/filename → `../..` xoá được file
  ngoài thư mục backup mà tiến trình container có quyền ghi.
- image_url http(s) do client/model cung cấp được tải bằng urllib.urlopen thẳng,
  không guard → đọc localhost/LAN/169.254.169.254 rồi base64 lên provider.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class DeleteBackupPathTraversalTests(unittest.TestCase):
    def setUp(self):
        from services.state_backup import state_backup, BACKUP_DIR
        self.sb = state_backup
        self.dir = BACKUP_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def test_tu_choi_path_ra_ngoai_thu_muc(self):
        victim = self.dir.parent / "victim_test_xyz.txt"
        victim.write_text("không được xoá")
        try:
            r = self.sb.delete_backup("../victim_test_xyz.txt")
            self.assertFalse(r, "traversal phải bị từ chối")
            self.assertTrue(victim.exists(), "file ngoài BACKUP_DIR không được xoá")
        finally:
            if victim.exists():
                victim.unlink()

    def test_tu_choi_path_tuyet_doi(self):
        self.assertFalse(self.sb.delete_backup("/etc/hostname"))

    def test_van_xoa_duoc_file_hop_le_trong_backup(self):
        good = self.dir / "good_test_xyz.json"
        good.write_text("{}")
        r = self.sb.delete_backup("good_test_xyz.json")
        self.assertTrue(r)
        self.assertFalse(good.exists())


class SniffImageMimeTests(unittest.TestCase):
    def test_nhan_dang_dinh_dang_anh(self):
        from services.protocol.openai_v1_chat_complete import _sniff_image_mime
        self.assertEqual(_sniff_image_mime(b"\x89PNG\r\n\x1a\n" + b"0" * 8), "image/png")
        self.assertEqual(_sniff_image_mime(b"\xff\xd8\xff" + b"0" * 12), "image/jpeg")
        self.assertEqual(_sniff_image_mime(b"GIF89a" + b"0" * 8), "image/gif")
        self.assertEqual(
            _sniff_image_mime(b"RIFF" + b"0000" + b"WEBP" + b"0" * 8), "image/webp")

    def test_khong_phai_anh_tra_rong(self):
        from services.protocol.openai_v1_chat_complete import _sniff_image_mime
        self.assertEqual(_sniff_image_mime(b"<!DOCTYPE html><html></html>"), "")
        self.assertEqual(_sniff_image_mime(b""), "")
        self.assertEqual(_sniff_image_mime(b"{}"), "")


class ImageUrlSsrfTests(unittest.TestCase):
    def test_url_metadata_bi_chan_bo_anh(self):
        from services.protocol.openai_v1_chat_complete import _convert_images_for_openai
        msgs = [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": "http://169.254.169.254/latest/meta-data/"}},
        ]}]
        out = _convert_images_for_openai(msgs)
        parts = out[0]["content"]
        # net_guard chặn IP metadata → ảnh bị bỏ, không nhồi lên provider.
        self.assertEqual(len(parts), 0)

    def test_url_localhost_bi_chan(self):
        from services.protocol.openai_v1_chat_complete import _convert_images_for_openai
        msgs = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "http://127.0.0.1:8000/x.png"}},
        ]}]
        out = _convert_images_for_openai(msgs)
        self.assertEqual(len(out[0]["content"]), 0)

    def test_data_url_giu_nguyen(self):
        from services.protocol.openai_v1_chat_complete import _convert_images_for_openai
        du = "data:image/png;base64,iVBORw0KGgo="
        msgs = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": du}},
        ]}]
        out = _convert_images_for_openai(msgs)
        self.assertEqual(out[0]["content"][0]["image_url"]["url"], du)


if __name__ == "__main__":
    unittest.main()
