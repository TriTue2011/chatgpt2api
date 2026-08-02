"""Phát ra loa: đủ loa + âm lượng + nội dung, và báo ĐÚNG kết quả thật.

Đo thật 02/08 trên Zalo (nguyên văn):

    18:10:13 người dùng : phát thông báo ra loa với nội dung chuẩn bị đi ăn gà rán thôi các con
    18:10:26 bot        : Em định Hẹn giờ / đọc thông báo ra loa: … — duyệt không?
    18:10:37 người dùng : phát ngay
    18:10:42 bot        : … muốn phát ra loa nào vậy: loa phòng khách hay tất cả loa?
    18:10:49 người dùng : loa phòng khách
    18:11:05 bot        : Em định Phát tiếng ra loa trong nhà: … — duyệt không?
    18:11:15 người dùng : âm lượng 60%
    18:11:22 bot        : Em định Hẹn giờ / đọc thông báo ra loa: … — duyệt không?
    18:11:24 người dùng : 1
    18:11:25 bot        : [đang đọc “chuẩn bị đi ăn gà rán thôi các con” ra loa phòng khách]

Loa im. Log máy chủ nói thẳng nguyên nhân:

    announce: phát lỗi ra loa phòng khách: Chưa đặt voice.public_base_url —
    loa trong nhà không tải được file từ localhost.

Ba lỗi tách bạch:
  1. `schedule(delay=0)` chạy qua `threading.Timer(0, …)` — thread NỀN. Hàm trả
     về TRƯỚC khi biết kết quả, lỗi chỉ vào `logger.warning`, người dùng nhận một
     câu báo thành công sai sự thật.
  2. Câu duyệt lặp lại mà mất sạch «loa phòng khách» và «60%» — mỗi lượt model
     định tuyến dựng lại args từ đầu.
  3. Không có bước nào hỏi âm lượng.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

GOC = pathlib.Path(__file__).resolve().parents[1]

NOI_DUNG = "chuẩn bị đi ăn gà rán thôi các con"


def _nap(nguon: pathlib.Path, ten: tuple[str, ...], extra: dict | None = None) -> dict:
    """Nạp RIÊNG vài hàm/biến — import cả module sẽ kéo theo config/DB/model."""
    src = nguon.read_text("utf-8")
    phan = ["from __future__ import annotations", "import re", "from typing import Any"]
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ten:
            phan.append(ast.get_source_segment(src, n))
        if isinstance(n, (ast.FunctionDef,)) and n.name in ten:
            phan.append(ast.get_source_segment(src, n))
    ns: dict = {"re": re}
    ns.update(extra or {})
    exec("\n".join(phan), ns)
    return ns


def _ns_menu() -> dict:
    return _nap(GOC / "services" / "agent" / "capabilities.py",
                ("_LOA_MUC_AM", "_ask_am_luong_loa", "_mot_dong"))


def _ns_doc() -> dict:
    return _nap(GOC / "services" / "agent" / "orchestrator.py",
                ("_NUT_LOA", "_doc_nut_menu_loa"))


class MenuAmLuongTests(unittest.TestCase):
    def setUp(self):
        self.f = _ns_menu()["_ask_am_luong_loa"]

    def test_co_du_cac_muc_va_giu_nguyen(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, "loa phòng khách", 0)["text"])
        nhan = [c["label"] for c in choices]
        self.assertEqual(nhan, ["30%", "50%", "70%", "100%", "Giữ nguyên âm lượng loa"])

    def test_nut_mang_du_loa_am_luong_noi_dung(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, "loa phòng khách", 0)["text"])
        send = choices[1]["send"]        # 50%
        self.assertIn("«loa phòng khách»", send)
        self.assertIn("âm lượng 50%", send)
        self.assertTrue(send.endswith(NOI_DUNG))

    def test_co_hen_gio_thi_nut_mang_theo_thoi_diem(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, "loa phòng khách", 120)["text"])
        self.assertIn("sau 2 phút", choices[0]["send"])

    def test_noi_dung_nhieu_dong_KHONG_pha_menu(self):
        """Cùng loại lỗi đã hạ menu chọn model ảnh/video: <<<ASK>>> bóc theo DÒNG."""
        from services.agent import ask_choices as ac
        nhieu_dong = "chuẩn bị đi ăn gà rán\nnhớ rửa tay\nrồi xuống nhà"
        _, choices = ac.extract(self.f(nhieu_dong, "loa phòng khách", 0)["text"])
        self.assertEqual(len(choices), 5)
        self.assertNotIn("\n", choices[0]["send"])
        self.assertIn("rồi xuống nhà", choices[0]["send"])


class DocLaiNutTests(unittest.TestCase):
    def setUp(self):
        self.f = _ns_doc()["_doc_nut_menu_loa"]

    def test_doc_dung_loa_am_luong_noi_dung(self):
        self.assertEqual(
            self.f(f"đọc ra loa «loa phòng khách» âm lượng 60%: {NOI_DUNG}"),
            {"text": NOI_DUNG, "speaker": "loa phòng khách", "volume": 60})

    def test_giu_nguyen_thi_khong_hoi_lai_am_luong(self):
        got = self.f(f"đọc ra loa «loa bếp» âm lượng giữ nguyên: {NOI_DUNG}")
        self.assertTrue(got["giu_am_luong"])
        self.assertNotIn("volume", got)

    def test_doc_ca_hen_gio(self):
        got = self.f(f"đọc ra loa «loa phòng khách» âm lượng 30% sau 2 phút: {NOI_DUNG}")
        self.assertEqual(got["delay_minutes"], 2.0)
        self.assertEqual(got["volume"], 30)

    def test_cau_nguoi_go_va_cau_khac_khong_lot_vao_day(self):
        for c in ("phát thông báo ra loa với nội dung đi ăn cơm",
                  "âm lượng 60%", "xin chào", "mở nhạc ra loa R1 âm lượng 5", ""):
            self.assertIsNone(self.f(c), c)


class VongKhepKinTests(unittest.TestCase):
    """Nút menu sinh ra PHẢI đọc lại được — nếu không, âm lượng và loa lại bốc hơi."""

    def test_moi_nut_cua_menu_deu_doc_lai_duoc(self):
        from services.agent import ask_choices as ac
        ask = _ns_menu()["_ask_am_luong_loa"]
        doc = _ns_doc()["_doc_nut_menu_loa"]
        _, choices = ac.extract(ask(NOI_DUNG, "loa phòng khách", 120)["text"])
        self.assertEqual(len(choices), 5)
        for c in choices:
            got = doc(c["send"])
            self.assertIsNotNone(got, c["send"])
            self.assertEqual(got["speaker"], "loa phòng khách")
            self.assertEqual(got["text"], NOI_DUNG)
            self.assertEqual(got["delay_minutes"], 2.0)
            self.assertTrue("volume" in got or got.get("giu_am_luong"))


class PhatNgayPhaiDongBoTests(unittest.TestCase):
    """delay=0 → chạy đồng bộ, lỗi thật phải NÉM RA, không chìm vào thread nền."""

    def setUp(self):
        from services.voice import announce as ann
        self.ann = ann
        self.rec = {"id": "spk1", "name": "loa phòng khách", "kind": "cast"}
        self._resolve_goc = ann._resolve_one
        ann._resolve_one = lambda q: self.rec

    def tearDown(self):
        self.ann._resolve_one = self._resolve_goc

    def _cam_voice(self, loi: str | None):
        """Cắm giả `services.voice.play_text_on` mà `_run` gọi bên trong."""
        import types
        mod = sys.modules.get("services.voice")
        goc = getattr(mod, "play_text_on", None)
        da_goi: list = []

        def _play(text, rec, voice_name=""):
            da_goi.append((text, rec.get("name")))
            if loi:
                raise RuntimeError(loi)

        mod.play_text_on = _play
        self.addCleanup(lambda: setattr(mod, "play_text_on", goc)
                        if goc is not None else None)
        assert isinstance(mod, types.ModuleType)
        return da_goi

    def test_phat_xong_moi_tra_ve(self):
        da_goi = self._cam_voice(None)
        ra = self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0)
        self.assertEqual(da_goi, [(NOI_DUNG, "loa phòng khách")])   # đã phát TRƯỚC khi trả về
        self.assertEqual(ra.get("status"), "done")

    def test_loi_thi_NEM_RA_chu_khong_bao_thanh_cong(self):
        self._cam_voice("Chưa đặt voice.public_base_url — loa trong nhà không "
                        "tải được file từ localhost.")
        with self.assertRaises(RuntimeError) as e:
            self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0)
        self.assertIn("public_base_url", str(e.exception))

    def test_hen_gio_van_chay_NEN_khong_chan_luot(self):
        self._cam_voice("boom")     # lỗi cũng không được ném — job chạy sau
        ra = self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=600)
        self.assertEqual(ra.get("status"), "scheduled")
        self.ann.cancel(ra["id"])


class DiaChiCongKhaiTests(unittest.TestCase):
    """Địa chỉ công khai cho loa kéo file — đọc ĐÚNG chỗ đang có giá trị.

    Máy chủ 02/08: `config.get()["base_url"]` = '' (dict thô) nhưng
    `CHATGPT2API_BASE_URL` = 'https://gpt.vhtatn.io.vn' và
    `telegram_webhook_url` = 'https://gpt.vhtatn.io.vn'. Hàm cũ chỉ đọc dict thô
    nên báo "chưa đặt public_base_url" dù địa chỉ đã có ở hai nơi.
    """

    def setUp(self):
        from unittest import mock
        from services.config import config
        from services.voice import config as vc
        self.vc, self.config, self.mock = vc, config, mock

    def _chay(self, *, env=None, voice_rieng=None, tele=None) -> str:
        moi = {}
        if env is not None:
            moi["CHATGPT2API_BASE_URL"] = env
        with self.mock.patch.dict(os.environ, moi, clear=(env is None)), \
             self.mock.patch.dict(self.config.data, {
                 "base_url": "",
                 "telegram_webhook_url": tele or "",
                 "voice": {"public_base_url": voice_rieng or ""},
             }):
            return self.vc.public_base_url()

    def test_lay_tu_bien_moi_truong(self):
        self.assertEqual(self._chay(env="https://gpt.vhtatn.io.vn/"),
                         "https://gpt.vhtatn.io.vn")

    def test_khong_co_env_thi_lay_dia_chi_webhook_dung_chung(self):
        self.assertEqual(self._chay(tele="https://gpt.vhtatn.io.vn"),
                         "https://gpt.vhtatn.io.vn")

    def test_cai_rieng_cho_loa_thang_tat_ca(self):
        self.assertEqual(self._chay(env="https://a.example",
                                    voice_rieng="http://172.16.10.38"),
                         "http://172.16.10.38")

    def test_khong_co_gi_thi_rong(self):
        self.assertEqual(self._chay(), "")


class MenuKhongBiNenTests(unittest.TestCase):
    """Menu là GIAO DIỆN — nén nó là phá mất lựa chọn (đo thật cả ảnh và video)."""

    def test_khoi_ASK_khong_bi_nen(self):
        from services.agent import tool_compress as tc
        menu = ("🎨 Chọn model ạ?\n<<<ASK>>>\n"
                + "\n".join(f"flow/m{i} | tạo ảnh bằng model flow/m{i}: {'x' * 900}"
                            for i in range(6))
                + "\n<<<END>>>")
        self.assertGreater(len(menu), 4000)          # vượt trần → chắc chắn bị nén nếu không chặn
        self.assertEqual(tc.compress(menu, tool_name="generate_image"), menu)

    def test_van_nen_output_thuong(self):
        from services.agent import tool_compress as tc
        tho = "\n".join(f"dòng log số {i} — chi tiết dài dòng ở đây" for i in range(400))
        self.assertLess(len(tc.compress(tho, tool_name="run_shell")), len(tho))

    def test_nhan_ca_JAVIS_ASK(self):
        from services.agent import tool_compress as tc
        self.assertTrue(tc.co_menu_chon('JAVIS_ASK ["a", "b"]'))
        self.assertFalse(tc.co_menu_chon("chỉ là văn bản thường"))


class DuongTatKhongMoThemQuyenTests(unittest.TestCase):
    """Đường tắt rút ngắn đường đi, KHÔNG được mở thêm quyền.

    `announce_on_speaker` là hành động CHANGE, nên phải qua CẢ bộ lọc chức năng
    theo thread lẫn cổng duyệt — y như đường thường.
    """

    def setUp(self):
        self.code = "\n".join(
            l for l in (GOC / "services" / "agent" / "orchestrator.py")
            .read_text("utf-8").splitlines() if not l.lstrip().startswith("#"))
        self.khuc = self.code[self.code.index("_nut_loa = _doc_nut_menu_loa(user_text)"):][:1800]

    def test_van_qua_bo_loc_chuc_nang_theo_thread(self):
        self.assertIn('allow is None or "tts_speaker" in allow', self.khuc)

    def test_van_qua_cong_duyet(self):
        self.assertIn('approval_gate.needs_approval(user_id, "announce_on_speaker"', self.khuc)
        self.assertIn('approval_gate.set_pending(user_id, "announce_on_speaker"', self.khuc)

    def test_che_do_chi_doc_thi_chan(self):
        self.assertIn('approval_gate.is_blocked("announce_on_speaker"', self.khuc)

    def test_dat_truoc_fast_path_HA(self):
        self.assertLess(self.code.index("_nut_loa = _doc_nut_menu_loa(user_text)"),
                        self.code.index("if ha_fastpath and (allow is None"))


if __name__ == "__main__":
    unittest.main()
