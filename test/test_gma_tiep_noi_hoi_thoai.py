"""Test tiếp nối hội thoại native GMA + đính message.txt + lọc [ToolCalls] stream.

Kho hội thoại (services/gma_conversation_store.py) thuần stdlib nên import
thẳng. Các hàm trong api/gemini_web.py thì bóc qua bệ thử AST (máy dev Python
3.9 không import được cả module vì chuỗi phụ thuộc pydantic 3.10+).
"""
from __future__ import annotations

import ast
import os
import tempfile
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Phần 1: kho hội thoại ────────────────────────────────────────────────────

def _kho_moi():
    from services.gma_conversation_store import KhoHoiThoaiGma
    fd, duong = tempfile.mkstemp(suffix=".db", prefix="gma_kho_")
    os.close(fd)
    return KhoHoiThoaiGma(duong), duong


def _hoi_thoai():
    return [
        {"role": "system", "content": "Bạn là trợ lý."},
        {"role": "user", "content": "Xin chào"},
        {"role": "assistant", "content": "Chào bạn! Tôi giúp gì được?"},
        {"role": "user", "content": "Kể một câu chuyện cười"},
        {"role": "assistant", "content": "Con cá không biết bơi... đùa thôi!"},
    ]


class KhoHoiThoaiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kho, self.duong = _kho_moi()

    def tearDown(self) -> None:
        try:
            os.unlink(self.duong)
        except OSError:
            pass

    def test_khop_prefix_dai_nhat(self) -> None:
        msgs = _hoi_thoai()
        self.assertTrue(self.kho.luu(msgs[:3], "auto", "google-a", ["cid1", "rid1", None]))
        self.assertTrue(self.kho.luu(msgs, "auto", "google-a", ["cid2", "rid2", None]))
        # Lịch sử mới = 5 tin cũ + 1 câu hỏi mới → phải khớp bản ghi DÀI NHẤT (5 tin)
        truy_van = msgs + [{"role": "user", "content": "Kể tiếp đi"}]
        khop = self.kho.tim(truy_van, "auto")
        self.assertIsNotNone(khop)
        self.assertEqual(khop["so_tin"], 5)
        self.assertEqual(khop["metadata"][0], "cid2")
        self.assertEqual(khop["profile"], "google-a")

    def test_khop_fuzzy_whitespace_va_hoa_thuong(self) -> None:
        msgs = _hoi_thoai()[:3]
        self.assertTrue(self.kho.luu(msgs, "auto", "google-a", ["cid1"]))
        # Client phát lại lịch sử nhưng trim/đổi hoa thường — tầng fuzzy phải chịu được
        bien_the = [
            {"role": "system", "content": "bạn là trợ lý.  "},
            {"role": "user", "content": "XIN CHÀO"},
            {"role": "assistant", "content": "Chào bạn!  Tôi giúp gì được ?"},
            {"role": "user", "content": "tiếp"},
        ]
        khop = self.kho.tim(bien_the, "auto")
        self.assertIsNotNone(khop)
        self.assertEqual(khop["so_tin"], 3)

    def test_khac_model_khong_khop(self) -> None:
        msgs = _hoi_thoai()[:3]
        self.kho.luu(msgs, "3.5-flash", "google-a", ["cid1"])
        self.assertIsNone(self.kho.tim(msgs + [{"role": "user", "content": "?"}], "3.1-pro"))

    def test_metadata_rong_khong_luu(self) -> None:
        msgs = _hoi_thoai()[:3]
        self.assertFalse(self.kho.luu(msgs, "auto", "google-a", []))
        self.assertFalse(self.kho.luu(msgs, "auto", "google-a", [None, "rid"]))
        self.assertIsNone(self.kho.tim(msgs + [{"role": "user", "content": "?"}], "auto"))

    def test_tool_calls_doi_id_van_khop(self) -> None:
        # id do provider sinh ngẫu nhiên mỗi lần — hash phải bỏ id, sort theo (name, args)
        goc = [
            {"role": "user", "content": "bật đèn"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_aaa", "type": "function",
                 "function": {"name": "control_home", "arguments": '{"thiet_bi": "den", "trang_thai": "on"}'}},
                {"id": "call_bbb", "type": "function",
                 "function": {"name": "search_sgk", "arguments": '{"q": "x"}'}},
            ]},
            {"role": "tool", "content": "ok", "name": "control_home"},
            {"role": "assistant", "content": "Đã bật đèn."},
        ]
        self.assertTrue(self.kho.luu(goc, "auto", "google-a", ["cid9"]))
        # Truy vấn: id khác + đảo thứ tự call + arguments đổi thứ tự key
        bien_the = [
            {"role": "user", "content": "bật đèn"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_zzz", "type": "function",
                 "function": {"name": "search_sgk", "arguments": '{"q": "x"}'}},
                {"id": "call_yyy", "type": "function",
                 "function": {"name": "control_home", "arguments": '{"trang_thai": "on", "thiet_bi": "den"}'}},
            ]},
            {"role": "tool", "content": "ok", "name": "control_home"},
            {"role": "assistant", "content": "Đã bật đèn."},
            {"role": "user", "content": "tắt đi"},
        ]
        khop = self.kho.tim(bien_the, "auto")
        self.assertIsNotNone(khop)
        self.assertEqual(khop["so_tin"], 4)

    def test_khoi_toolcalls_noi_tuyen_vo_hinh_voi_hash(self) -> None:
        # Bản phát lại nhúng khối [ToolCalls] vào content; bản client giữ content
        # sạch — hai dạng phải hash trùng nhau.
        co_khoi = [
            {"role": "user", "content": "hỏi"},
            {"role": "assistant",
             "content": "Đã xong.\n[ToolCalls]\n[Call:x]\n[/Call]\n[/ToolCalls]"},
        ]
        sach = [
            {"role": "user", "content": "hỏi"},
            {"role": "assistant", "content": "Đã xong."},
            {"role": "user", "content": "tiếp"},
        ]
        self.assertTrue(self.kho.luu(co_khoi, "auto", "google-a", ["cid3"]))
        khop = self.kho.tim(sach, "auto")
        self.assertIsNotNone(khop)
        self.assertEqual(khop["so_tin"], 2)

    def test_ttl_don_dep_khi_luu(self) -> None:
        import services.gma_conversation_store as mod
        msgs = _hoi_thoai()[:3]
        self.kho.luu(msgs, "auto", "google-a", ["cid-cu"])
        # Già hoá bản ghi quá TTL bằng SQL rồi lưu bản mới → bản cũ bị dọn
        import time as _time
        with self.kho._lock:
            self.kho._con.execute("UPDATE hoi_thoai SET cap_nhat = ?",
                                  (_time.time() - mod.TTL_GIAY - 60,))
            self.kho._con.commit()
        self.kho.luu(_hoi_thoai(), "auto", "google-a", ["cid-moi"])
        self.assertIsNone(self.kho.tim(msgs + [{"role": "user", "content": "?"}], "auto"))

    def test_xoa_ban_ghi(self) -> None:
        msgs = _hoi_thoai()[:3]
        self.kho.luu(msgs, "auto", "google-a", ["cid1"])
        khop = self.kho.tim(msgs + [{"role": "user", "content": "?"}], "auto")
        self.assertIsNotNone(khop)
        self.kho.xoa(khop["strict_hash"])
        self.assertIsNone(self.kho.tim(msgs + [{"role": "user", "content": "?"}], "auto"))

    def test_anh_trong_lich_su_van_khop(self) -> None:
        msgs = [
            {"role": "user", "content": [
                {"type": "text", "text": "ảnh này là gì?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ]},
            {"role": "assistant", "content": "Là con mèo."},
        ]
        self.assertTrue(self.kho.luu(msgs, "auto", "google-a", ["cid4"]))
        khop = self.kho.tim(msgs + [{"role": "user", "content": "màu gì?"}], "auto")
        self.assertIsNotNone(khop)
        self.assertEqual(khop["so_tin"], 2)


# ── Phần 2: bệ thử AST cho api/gemini_web.py ─────────────────────────────────

def _nap_tu_gemini_web(*ten_can: str) -> dict:
    """Bóc đúng các hàm/lớp cần test từ api/gemini_web.py rồi exec.

    Máy dev 3.9 không import được cả module (chuỗi phụ thuộc pydantic 3.10+),
    nhưng thân hàm giữ NGUYÊN nên vẫn kiểm được đúng code thật.
    """
    src = open(os.path.join(GOC, "api", "gemini_web.py"), encoding="utf-8").read()
    cay = ast.parse(src)
    chon = []
    thay = set()
    for node in cay.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in ten_can:
            chon.append(node)
            thay.add(node.name)
        elif isinstance(node, ast.Assign):
            # hằng số module (vd _LOI_NHAN_TEP_DAI) cũng bóc được
            ten = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in ten_can for t in ten):
                chon.append(node)
                thay.update(ten)
    thieu = set(ten_can) - thay
    if thieu:
        raise AssertionError(f"api/gemini_web.py thiếu: {thieu}")
    module = ast.Module(body=chon, type_ignores=[])

    class _DummyLog:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass

    import json as _json
    import re as _re
    import uuid as _uuid
    ns: dict = {
        "os": os, "re": _re, "json": _json, "uuid": _uuid,
        "tempfile": tempfile, "Any": object,
        "_logger": lambda: _DummyLog(),
        "_cfg": lambda: {},
    }
    exec(compile(module, "<gemini_web-trich>", "exec"), ns)
    return ns


class LocToolCallStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = _nap_tu_gemini_web("_LocToolCallStream")

    def _loc(self):
        return self.ns["_LocToolCallStream"]()

    def test_marker_tach_doi_giua_hai_chunk_khong_lo(self) -> None:
        loc = self._loc()
        phat = loc.feed("Đang xử lý [Tool")
        phat += loc.feed("Calls]\n[Call:search]\n[/Call]\n[/ToolCalls]")
        phat += loc.flush()
        self.assertEqual(phat, "Đang xử lý ")
        self.assertNotIn("[ToolCalls]", phat)

    def test_call_truc_tiep_khong_co_bao_ngoai(self) -> None:
        loc = self._loc()
        phat = loc.feed("[Call:control_home]\n...")
        phat += loc.flush()
        self.assertEqual(phat, "")

    def test_van_ban_thuong_di_qua_nguyen_ven(self) -> None:
        loc = self._loc()
        cau = "Kết quả đây [link](http://x) và [▶️ Bấm để nghe](http://y)."
        phat = loc.feed(cau) + loc.flush()
        self.assertEqual(phat, cau)

    def test_duoi_do_dang_khong_phai_marker_duoc_tra_lai(self) -> None:
        loc = self._loc()
        p1 = loc.feed("Xem [Tool")
        p2 = loc.feed("box] nhé")
        p3 = loc.flush()
        self.assertEqual(p1 + p2 + p3, "Xem [Toolbox] nhé")

    def test_duoi_do_dang_cuoi_stream_duoc_flush(self) -> None:
        loc = self._loc()
        p1 = loc.feed("Đọc trang [Ca")
        p2 = loc.flush()
        self.assertEqual(p1 + p2, "Đọc trang [Ca")


class DongGoiPromptDaiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = _nap_tu_gemini_web("_dong_goi_prompt_dai", "_cleanup",
                                     "_gioi_han_ky_tu", "_LOI_NHAN_TEP_DAI",
                                     "_GMA_MAX_CHARS_MAC_DINH")

    def test_ngan_giu_nguyen(self) -> None:
        p, files = self.ns["_dong_goi_prompt_dai"]("ngắn thôi", ["a.png"], gioi_han=100)
        self.assertEqual(p, "ngắn thôi")
        self.assertEqual(files, ["a.png"])

    def test_dai_dinh_message_txt_nguyen_van(self) -> None:
        prompt = "x" * 250
        p, files = self.ns["_dong_goi_prompt_dai"](prompt, ["a.png"], gioi_han=100)
        self.assertNotEqual(p, prompt)
        self.assertIn("message.txt", p)
        self.assertEqual(len(files), 2)
        self.assertEqual(os.path.basename(files[0]), "message.txt")
        self.assertEqual(files[1], "a.png")
        with open(files[0], encoding="utf-8") as f:
            self.assertEqual(f.read(), prompt)   # NGUYÊN VĂN, không nén mất chữ
        # _cleanup phải xoá cả tệp lẫn thư mục gma_txt_* bao ngoài
        thu_muc = os.path.dirname(files[0])
        self.ns["_cleanup"]([files[0]])
        self.assertFalse(os.path.exists(files[0]))
        self.assertFalse(os.path.isdir(thu_muc))


class ExtractToolCallsTests(unittest.TestCase):
    def test_giu_content_khi_co_tool_call(self) -> None:
        ns = _nap_tu_gemini_web("_extract_tool_calls")
        text = ("Tôi sẽ tra cứu.\n[ToolCalls]\n[Call:search]\n"
                "[CallParameter:q]\n```\nthời tiết\n```\n[/CallParameter]\n"
                "[/Call]\n[/ToolCalls]")
        clean, calls = ns["_extract_tool_calls"](text)
        self.assertEqual(clean, "Tôi sẽ tra cứu.")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "search")


if __name__ == "__main__":
    unittest.main()
