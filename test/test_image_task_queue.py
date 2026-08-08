"""Tác vụ ảnh phải có TRẦN đồng thời, không tạo thread vô hạn.

Bản cũ tạo một `threading.Thread` cho MỖI tác vụ, không giới hạn. Một người dùng
hợp lệ chỉ cần gửi nhiều `client_task_id` khác nhau là dựng được vô số thread —
cạn RAM/CPU của gateway và đốt sạch quota provider. Đây là lỗ mở đúng lúc hệ
thống sắp cấp key cho nhiều người dùng.
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import image_task_service as m  # noqa: E402
from services.image_task_service import ImageTaskService, TaskQueueFull  # noqa: E402


class _Handler:
    """Handler giả: chặn ở một Event nên tác vụ 'đang chạy' cho tới khi test thả."""

    def __init__(self):
        self.tha = threading.Event()
        self.dang_chay = threading.Semaphore(0)

    def __call__(self, payload):
        self.dang_chay.release()
        self.tha.wait(timeout=10)
        return {"data": [{"url": "http://x/a.png"}]}


class TranDongThoiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # addCleanup chạy LIFO: đăng ký xoá thư mục TRƯỚC để nó chạy SAU cùng.
        # Xoá thư mục khi tác vụ nền còn đang ghi tasks.json là lỗi dựng lên bởi
        # test, không phải lỗi của mã đang kiểm.
        self.addCleanup(self.tmp.cleanup)
        self.h = _Handler()
        self.addCleanup(self._cho_chay_xong)
        self.svc = ImageTaskService(
            Path(self.tmp.name) / "tasks.json",
            generation_handler=self.h,
            edit_handler=self.h,
            retention_days_getter=lambda: 7,
        )

    def _cho_chay_xong(self):
        """Thả handler rồi CHỜ mọi slot được nhả — tức là không tác vụ nào còn ghi."""
        self.h.tha.set()
        lay_duoc = 0
        for _ in range(m.MAX_CONCURRENT_TASKS):
            if self.svc._slots.acquire(timeout=10):
                lay_duoc += 1
        for _ in range(lay_duoc):
            self.svc._slots.release()

    def _gui(self, owner: str, task_id: str):
        return self.svc.submit_generation(
            {"id": owner}, client_task_id=task_id, prompt="ve con meo",
            model="gpt-image-2", size=None, base_url="http://x",
        )

    def test_mot_nguoi_dung_khong_vuot_tran_rieng(self):
        for i in range(m.MAX_CONCURRENT_PER_OWNER):
            self._gui("u1", f"t{i}")
        with self.assertRaises(TaskQueueFull) as ctx:
            self._gui("u1", "t-thua")
        self.assertIn("tác vụ ảnh chạy dở", str(ctx.exception))

    def test_tu_choi_xong_thi_gui_lai_duoc_cung_task_id(self):
        """Tác vụ bị từ chối phải được xoá khỏi sổ.

        Nếu để lại trạng thái 'queued' mà không có gì chạy thì nó treo vĩnh viễn
        VÀ chiếm luôn khoá idempotency — người dùng không gửi lại được nữa.
        """
        for i in range(m.MAX_CONCURRENT_PER_OWNER):
            self._gui("u2", f"a{i}")
        with self.assertRaises(TaskQueueFull):
            self._gui("u2", "a-thua")
        ds = self.svc.list_tasks({"id": "u2"}, ["a-thua"])
        self.assertEqual(ds["missing_ids"], ["a-thua"])

    def test_tran_toan_he_thong_chan_nhieu_nguoi_dung_cong_lai(self):
        n = 0
        try:
            for u in range(20):
                for i in range(m.MAX_CONCURRENT_PER_OWNER):
                    self._gui(f"u{u}", f"t{i}")
                    n += 1
        except TaskQueueFull:
            pass
        self.assertLessEqual(n, m.MAX_CONCURRENT_TASKS,
                             "trần toàn hệ thống không chặn được khi nhiều người cùng gửi")

    def _cho_owner_ranh(self, owner: str, han: float = 10.0) -> None:
        """Chờ tới khi owner không còn tác vụ nào chiếm slot."""
        import time
        het = time.monotonic() + han
        while time.monotonic() < het:
            with self.svc._lock:
                if self.svc._dang_chay.get(owner, 0) == 0:
                    return
            time.sleep(0.01)
        self.fail(f"slot của {owner} không được nhả sau {han}s")

    def test_xong_mot_tac_vu_thi_slot_duoc_tra_lai(self):
        for i in range(m.MAX_CONCURRENT_PER_OWNER):
            self._gui("u3", f"t{i}")
        with self.assertRaises(TaskQueueFull):
            self._gui("u3", "t-thua")
        self.h.tha.set()                 # cho các tác vụ chạy xong
        self._cho_owner_ranh("u3")       # chờ slot THẬT SỰ được nhả
        self._gui("u3", "t-moi")         # không được ném nữa

    def test_gui_lai_dung_task_id_khong_ton_them_slot(self):
        """Idempotency: gửi lại cùng client_task_id trả về tác vụ cũ."""
        a = self._gui("u4", "same")
        b = self._gui("u4", "same")
        self.assertEqual(a["id"], b["id"])
        self._gui("u4", "khac")   # vẫn còn slot thứ hai vì lần gửi lại không chiếm


if __name__ == "__main__":
    unittest.main()
