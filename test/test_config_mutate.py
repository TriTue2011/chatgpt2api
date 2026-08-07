"""ConfigStore.mutate: read-modify-write ATOMIC dưới một khoá.

Báo cáo bảo mật 07/08: route Devices/MCP đọc config.data, sửa rồi mới _save();
hai request đồng thời ghi đè nhau (mất cấu hình MCP, undo rotate token). mutate()
gói cả sửa + lưu trong _lock nên các thay đổi khoá KHÁC nhau không mất.
"""
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class ConfigMutateTests(unittest.TestCase):
    def setUp(self):
        from services.config import config
        self.config = config

    def test_mutate_goi_fn_va_luu_tra_ket_qua(self):
        with mock.patch.object(self.config, "_save") as save:
            self.config.data.setdefault("_mt", {})
            ret = self.config.mutate(lambda d: d["_mt"].update({"a": 1}) or "done")
            self.assertEqual(ret, "done")
            save.assert_called_once()
            self.assertEqual(self.config.data["_mt"]["a"], 1)

    def test_song_song_khong_mat_key(self):
        with mock.patch.object(self.config, "_save"):
            self.config.data["_conc"] = {}

            def add(k):
                def _f(d):
                    m = dict(d.get("_conc") or {})
                    m[k] = "v"
                    d["_conc"] = m
                return _f

            ths = [threading.Thread(target=lambda k=i: self.config.mutate(add(str(k))))
                   for i in range(30)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            self.assertEqual(len(self.config.data["_conc"]), 30,
                             "30 mutate khoá khác nhau phải giữ đủ 30 key")


if __name__ == "__main__":
    unittest.main()
