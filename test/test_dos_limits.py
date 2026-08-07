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


class ZaloWebhookBoundTests(unittest.TestCase):
    def test_het_slot_thi_bo_tin_khong_spawn(self):
        import api.zalo_bot as zbmod
        called = []
        with mock.patch.object(zbmod.zb, "process_update",
                               side_effect=lambda b, bot: called.append(1)):
            # Vét sạch semaphore → lượt kế phải bị bỏ, không gọi process_update.
            sem = zbmod._webhook_sem
            got = [sem.acquire(blocking=False) for _ in range(zbmod._WEBHOOK_MAX_INFLIGHT)]
            try:
                self.assertTrue(all(got))
                zbmod._spawn_bounded_update({"x": 1}, object())
                self.assertEqual(called, [], "hết slot thì KHÔNG xử lý")
            finally:
                for _ in got:
                    sem.release()


if __name__ == "__main__":
    unittest.main()
