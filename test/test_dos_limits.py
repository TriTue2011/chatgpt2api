"""Giới hạn DoS: upload đọc vào RAM, TAR restore, thread webhook Zalo.

Báo cáo bảo mật 07/08: upload/audio/PDF đọc trọn vào RAM không trần; TAR
restore đọc mọi member không giới hạn; webhook Zalo tạo thread không giới hạn.
Một user key / secret hợp lệ có thể làm cạn RAM/thread.
"""
import asyncio
import io
import os
import sys
import tarfile
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class _FakeUpload:
    """Giả UploadFile: trả dữ liệu theo khối như Starlette."""
    def __init__(self, data: bytes, chunk: int = 1024 * 1024):
        self._buf = io.BytesIO(data)
        self._chunk = chunk

    async def read(self, n: int = -1) -> bytes:
        return self._buf.read(self._chunk if n is None or n < 0 else n)


class ReadUploadLimitedTests(unittest.TestCase):
    def test_duoi_tran_doc_binh_thuong(self):
        from api.support import read_upload_limited
        data = b"x" * (2 * 1024 * 1024)
        out = asyncio.run(read_upload_limited(_FakeUpload(data), max_bytes=5 * 1024 * 1024))
        self.assertEqual(out, data)

    def test_vuot_tran_nem_413(self):
        from api.support import read_upload_limited
        from fastapi import HTTPException
        data = b"x" * (6 * 1024 * 1024)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(read_upload_limited(_FakeUpload(data), max_bytes=5 * 1024 * 1024))
        self.assertEqual(ctx.exception.status_code, 413)


class TarRestoreLimitTests(unittest.TestCase):
    def _make_tar(self, n_files: int) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for i in range(n_files):
                b = b"{}"
                ti = tarfile.TarInfo(name=f"snapshots/s{i}.json")
                ti.size = len(b)
                tar.addfile(ti, io.BytesIO(b))
        return buf.getvalue()

    def test_qua_nhieu_member_bi_tu_choi(self):
        from services.backup_service import BackupService, BackupError
        svc = BackupService.__new__(BackupService)
        payload = self._make_tar(5)
        with mock.patch.object(BackupService, "_TAR_MAX_MEMBERS", 2):
            with self.assertRaises(BackupError):
                svc._decode_archive_detail(payload)

    def test_binh_thuong_van_doc_duoc(self):
        from services.backup_service import BackupService
        svc = BackupService.__new__(BackupService)
        payload = self._make_tar(3)
        out = svc._decode_archive_detail(payload)
        self.assertEqual(len(out["snapshots"]), 3)


class ZaloWorkerBoundTests(unittest.TestCase):
    def test_het_slot_thi_bo_tin(self):
        # Bound worker Zalo Bot nay ở services.zalo_bot._zalo_worker (đặt ở đúng
        # điểm spawn _process_message). Vét sạch pool → lượt kế bị bỏ (False),
        # không gọi fn. (Semaphore api-level cũ _webhook_sem đã bỏ ở 994be1f.)
        from services.ingress_guard import make_worker_pool
        import threading
        spawn = make_worker_pool("zalo_test", 1)
        release = threading.Event()
        calls = []
        self.assertTrue(spawn(lambda: (calls.append(1), release.wait(2))))
        # Slot đã đầy → lượt kế bị bỏ, KHÔNG chạy fn thứ hai.
        self.assertFalse(spawn(lambda: calls.append(2)))
        release.set()
        self.assertNotIn(2, calls)


if __name__ == "__main__":
    unittest.main()
