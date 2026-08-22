"""Trần thời gian của một lượt orchestrate().

Kênh chat (Zalo/Telegram/email) gọi orchestrate() THẲNG trong tiến trình và
không có timeout nào ở trên. Một lượt treo từng làm bot câm hoàn toàn: không
trả lời, không báo lỗi (vì treo không sinh exception nên nhánh except không
chạy), và tin sau của cùng người kẹt luôn vì khoá lịch sử không được nhả.

Hai tính chất dưới đây giữ cho tình trạng đó không quay lại.
"""

from __future__ import annotations

import os
import threading
import time
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402


class OrchestrateWatchdogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._locked = orch._orchestrate_locked
        self._budget = orch._TURN_BUDGET_S
        self._wait = orch._LOCK_WAIT_S

    def tearDown(self) -> None:
        orch._orchestrate_locked = self._locked
        orch._TURN_BUDGET_S = self._budget
        orch._LOCK_WAIT_S = self._wait

    def test_hung_turn_returns_message_instead_of_hanging(self) -> None:
        """Lượt treo cứng phải trả lời trong ngân sách, không đứng im mãi."""
        orch._TURN_BUDGET_S = 1.0
        started = threading.Event()
        # Treo bằng Event chứ KHÔNG bằng `time.sleep(300)`: `orchestrate` chạy
        # thân hàm trong `ThreadPoolExecutor`, mà luồng thợ của nó không phải
        # daemon và `concurrent.futures` đăng ký atexit join hết chúng. Ngủ cứng
        # 300 giây nghĩa là `orchestrate` vẫn thoát đúng ngân sách, test vẫn
        # đạt, nhưng TIẾN TRÌNH pytest đứng thêm 5 phút ở lúc thoát — chạy cả
        # thư mục thì đó là treo cả job CI.
        #
        # Event chặn y hệt trong lúc đo, và `addCleanup` gỡ ngay khi test xong
        # nên luồng thợ kết thúc, nhả khoá lịch sử luôn.
        thoat = threading.Event()
        self.addCleanup(thoat.set)

        def hung(*a, **k):
            started.set()
            thoat.wait(300)
            return {"text": "không bao giờ tới đây"}

        orch._orchestrate_locked = hung

        t0 = time.time()
        out = orch.orchestrate("tin tức hôm nay", "user_treo")
        elapsed = time.time() - t0

        self.assertTrue(started.wait(5), "thân hàm phải được chạy")
        self.assertLess(elapsed, 20, "phải thoát theo ngân sách")
        self.assertTrue(str(out.get("text") or "").strip(),
                        "phải có câu trả lời cho người dùng, không được im lặng")

    def test_busy_user_is_told_instead_of_queuing_forever(self) -> None:
        """Lượt trước còn kẹt → lượt sau báo bận, không xếp hàng vô hạn."""
        orch._TURN_BUDGET_S = 0.5
        orch._LOCK_WAIT_S = 0.5
        release = threading.Event()

        def slow(*a, **k):
            release.wait(30)
            return {"text": "xong"}

        orch._orchestrate_locked = slow
        try:
            first = threading.Thread(
                target=lambda: orch.orchestrate("tin 1", "user_ban"), daemon=True)
            first.start()
            time.sleep(1.0)          # để lượt 1 kịp ôm khoá

            t0 = time.time()
            out = orch.orchestrate("tin 2", "user_ban")
            elapsed = time.time() - t0

            self.assertLess(elapsed, 20, "không được xếp hàng vô hạn sau lượt kẹt")
            self.assertTrue(str(out.get("text") or "").strip(),
                            "người dùng phải nhận được phản hồi nào đó")
        finally:
            release.set()

    def test_normal_turn_passes_through_unchanged(self) -> None:
        """Lượt bình thường phải đi qua nguyên vẹn, không bị watchdog đụng vào."""
        seen = {}

        def ok(user_text, user_id, **kw):
            seen["text"] = user_text
            seen["kw"] = kw
            return {"text": "trả lời thật", "image_url": "http://x/y.png"}

        orch._orchestrate_locked = ok
        out = orch.orchestrate("chào em", "user_ok", ha_fastpath=False, model="gpt-5.5")

        self.assertEqual(out["text"], "trả lời thật")
        self.assertEqual(out["image_url"], "http://x/y.png")
        self.assertEqual(seen["text"], "chào em")
        self.assertEqual(seen["kw"]["model"], "gpt-5.5")
        self.assertIs(seen["kw"]["ha_fastpath"], False)

    def test_lock_is_released_after_turn(self) -> None:
        """Khoá phải được nhả, nếu không người dùng đó chết vĩnh viễn."""
        orch._orchestrate_locked = lambda *a, **k: {"text": "ok"}
        orch.orchestrate("lần 1", "user_nha_khoa")
        lock = orch._user_history_lock("user_nha_khoa")
        self.assertTrue(lock.acquire(timeout=2), "khoá phải được nhả sau lượt chạy")
        lock.release()


if __name__ == "__main__":
    unittest.main()
