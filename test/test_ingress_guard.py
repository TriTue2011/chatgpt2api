"""read_json_limited (stream cap, chặn cả chunked) + make_worker_pool (bound
worker thật, giữ slot tới khi fn xong).

Báo cáo bảo mật 07/08: body cap chỉ theo Content-Length lọt chunked; semaphore
nhả trước khi worker thật chạy nên vô tác dụng.
"""
import asyncio
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class _FakeStreamRequest:
    """Giả Starlette Request: stream() trả các chunk (không cần Content-Length)."""
    def __init__(self, chunks):
        self._chunks = chunks

    async def stream(self):
        for c in self._chunks:
            yield c


class ReadJsonLimitedTests(unittest.TestCase):
    def test_duoi_tran_parse_ok(self):
        from services.ingress_guard import read_json_limited
        payload = json.dumps({"a": 1, "b": "x" * 100}).encode()
        req = _FakeStreamRequest([payload[:10], payload[10:]])
        out = asyncio.run(read_json_limited(req, max_bytes=1024))
        self.assertEqual(out, {"a": 1, "b": "x" * 100})

    def test_chunked_khong_content_length_van_bi_cap(self):
        from services.ingress_guard import read_json_limited, BodyTooLarge
        # Nhiều chunk, tổng vượt trần — không có Content-Length nào cả.
        chunks = [b"x" * 1000 for _ in range(5)]
        req = _FakeStreamRequest(chunks)
        with self.assertRaises(BodyTooLarge):
            asyncio.run(read_json_limited(req, max_bytes=2048))

    def test_body_rong_tra_dict_rong(self):
        from services.ingress_guard import read_json_limited
        self.assertEqual(asyncio.run(read_json_limited(_FakeStreamRequest([]))), {})


class WorkerPoolTests(unittest.TestCase):
    def test_giu_slot_toi_khi_fn_xong(self):
        from services.ingress_guard import make_worker_pool
        spawn = make_worker_pool("test", 2)
        started = threading.Event()
        release = threading.Event()
        done = []

        def slow():
            started.set()
            release.wait(2)
            done.append(1)

        # 2 slot: hai lần đầu OK.
        self.assertTrue(spawn(slow))
        started.wait(1)
        self.assertTrue(spawn(lambda: release.wait(2)))
        # Slot thứ 3 khi 2 cái đang chạy → bị bỏ (False), KHÔNG chờ.
        self.assertFalse(spawn(lambda: None), "hết slot phải trả False, không tạo thread")
        release.set()
        time.sleep(0.2)
        # Sau khi xong, slot nhả → spawn lại được.
        self.assertTrue(spawn(lambda: None))


if __name__ == "__main__":
    unittest.main()
