"""Giọng nói độc lập theo kênh / thread / topic / loa.

Yêu cầu 02/08: "Phần giọng nói tôi muốn nó độc lập cho từng kênh, từng thread,
từng topic, từng loa" — và khi được hỏi loa hay thread thắng, chủ máy trả lời
"cái nào dùng cái đó không liên quan nhau": giọng gán cho loa là của riêng loa,
thread/topic không được ghi đè nó.

Trạng thái TRƯỚC file này:
  · `session_voice` ĐÃ làm 5 bậc kênh → bot → nhóm → topic → user (dùng cho tin
    nhắn thoại trong chat).
  · Đường PHÁT RA LOA thì không tra gì cả: `announce._run` gọi
    `play_text_on(text, rec)` KHÔNG truyền voice, nên loa luôn đọc bằng giọng mặc
    định hệ thống — mọi cài đặt riêng đều vô hiệu ở loa.
  · Không có chỗ nào gán giọng cho một loa cụ thể.

Một lỗi âm thầm nữa cùng nằm ở đây: `get_tts_voice_for_session` lấy TRỌN dict của
key khớp đầu tiên. Một nhóm chỉ cài `tts_enabled` (không cài giọng) khớp trước cấp
kênh ⇒ `tts_voice` rỗng ⇒ rơi thẳng về giọng hệ thống, vô hiệu luôn giọng đã cài
cho cả kênh. Đúng lý do `_resolve_field` được viết ra.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import voice  # noqa: E402
from services.voice import session_voice as sv  # noqa: E402

LOA_CO_GIONG = {"id": "s1", "name": "loa phòng bé", "kind": "cast", "voice": "vi-nu-nhe"}
LOA_KHONG_GIONG = {"id": "s2", "name": "loa phòng khách", "kind": "cast"}


def _cam_bang(data: dict):
    """Cắm bảng cấu hình giọng theo phiên (không chạm file thật)."""
    return mock.patch.object(sv, "_load_data", lambda: data)


class GiongRiengCuaLoaTests(unittest.TestCase):
    def test_loa_co_giong_thi_dung_giong_do(self):
        with _cam_bang({"zalo": {"tts_voice": "giong-kenh"}}):
            self.assertEqual(
                voice.giong_cho_loa(LOA_CO_GIONG, session_id="zalo:b1:c9"),
                "vi-nu-nhe")

    def test_thread_KHONG_ghi_de_giong_cua_loa(self):
        """'không liên quan nhau' — cài giọng cho nhóm không đổi giọng của loa."""
        with _cam_bang({"zalo:b1:c9": {"tts_voice": "giong-nhom"},
                        "zalo": {"tts_voice": "giong-kenh"}}):
            self.assertEqual(
                voice.giong_cho_loa(LOA_CO_GIONG, session_id="zalo:b1:c9"),
                "vi-nu-nhe")

    def test_loa_khong_co_y_kien_thi_theo_phien(self):
        with _cam_bang({"zalo:b1:c9": {"tts_voice": "giong-nhom"}}):
            self.assertEqual(
                voice.giong_cho_loa(LOA_KHONG_GIONG, session_id="zalo:b1:c9"),
                "giong-nhom")

    def test_khong_co_phien_thi_tra_rong_de_dung_giong_he_thong(self):
        with _cam_bang({}):
            self.assertEqual(voice.giong_cho_loa(LOA_KHONG_GIONG), "")

    def test_dau_vao_rac_khong_no(self):
        with _cam_bang({}):
            self.assertEqual(voice.giong_cho_loa({}), "")
            self.assertEqual(voice.giong_cho_loa(None), "")  # type: ignore[arg-type]


class BonBacPhienTests(unittest.TestCase):
    """kênh → bot → nhóm → topic → user, mỗi bậc cụ thể hơn thì thắng."""

    BANG = {
        "tg": {"tts_voice": "g-kenh"},
        "tg:b1": {"tts_voice": "g-bot"},
        "tg:b1:c9": {"tts_voice": "g-nhom"},
        "tg:b1:c9#7": {"tts_voice": "g-topic"},
        "tg:b1:c9#7:u5": {"tts_voice": "g-user"},
    }

    def _giong(self, sid: str) -> str:
        with _cam_bang(dict(self.BANG)), \
             mock.patch.object(sv.vcfg, "tts_voice", lambda: "g-he-thong"):
            return sv.get_tts_voice_for_session(sid)

    def test_tung_bac(self):
        self.assertEqual(self._giong("tg:b1:c9#7:u5"), "g-user")
        self.assertEqual(self._giong("tg:b1:c9#7"), "g-topic")
        self.assertEqual(self._giong("tg:b1:c9"), "g-nhom")
        self.assertEqual(self._giong("tg:b1:c0"), "g-bot")
        self.assertEqual(self._giong("tg:b2:c0"), "g-kenh")
        self.assertEqual(self._giong("zalo:b1:c1"), "g-he-thong")

    def test_topic_thang_ca_nhom(self):
        """Topic 7 có giọng riêng thì topic khác vẫn theo giọng nhóm."""
        self.assertEqual(self._giong("tg:b1:c9#7"), "g-topic")
        self.assertEqual(self._giong("tg:b1:c9#8"), "g-nhom")


class KeThuaTungFieldTests(unittest.TestCase):
    """Nhóm chỉ cài cờ bật/tắt KHÔNG được vô hiệu giọng của cả kênh."""

    def test_nhom_chi_cai_tts_enabled_van_ke_thua_giong_kenh(self):
        bang = {"tg:b1:c9": {"tts_enabled": True},        # không có tts_voice
                "tg": {"tts_voice": "g-kenh"}}
        with _cam_bang(bang), \
             mock.patch.object(sv.vcfg, "tts_voice", lambda: "g-he-thong"):
            self.assertEqual(sv.get_tts_voice_for_session("tg:b1:c9"), "g-kenh")

    def test_khong_ai_cai_gi_thi_giong_he_thong(self):
        with _cam_bang({}), \
             mock.patch.object(sv.vcfg, "tts_voice", lambda: "g-he-thong"):
            self.assertEqual(sv.get_tts_voice_for_session("tg:b1:c9"), "g-he-thong")

    def test_default_truyen_vao_thang_giong_he_thong(self):
        with _cam_bang({}), \
             mock.patch.object(sv.vcfg, "tts_voice", lambda: "g-he-thong"):
            self.assertEqual(sv.get_tts_voice_for_session("tg:b1:c9", "g-goi"), "g-goi")


class LuuGiongVaoSoLoaTests(unittest.TestCase):
    def test_update_nhan_field_voice(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "voice" / "speakers.py").read_text("utf-8")
        i = src.index("def update(")
        self.assertIn('"note", "voice"', src[i:i + 700])


class DuocNoiVaoDuongPhatTests(unittest.TestCase):
    def setUp(self):
        import pathlib
        self.goc = pathlib.Path(__file__).resolve().parents[1]

    def _code(self, *phan: str) -> str:
        p = self.goc.joinpath(*phan)
        return "\n".join(l for l in p.read_text("utf-8").splitlines()
                         if not l.lstrip().startswith("#"))

    def test_announce_truyen_giong_vao_play_text_on(self):
        code = self._code("services", "voice", "announce.py")
        self.assertIn('play_text_on(job["text"], rec, str(job.get("voice") or "")', code)
        self.assertIn('"voice": str(voice or "")', code)

    def test_hai_handler_loa_deu_tra_giong(self):
        code = self._code("services", "agent", "capabilities.py")
        self.assertIn("voice.giong_cho_loa(chosen, session_id=_session_id_loa(ctx))", code)
        self.assertIn("voice.giong_cho_loa(spk, session_id=_sid)", code)

    def test_khoa_phien_dung_quy_uoc_cua_kenh(self):
        code = self._code("services", "agent", "capabilities.py")
        i = code.index("def _session_id_loa(")
        self.assertIn('f"{plat}:{bot_id}:{chat_id}"', code[i:i + 900])


if __name__ == "__main__":
    unittest.main()
