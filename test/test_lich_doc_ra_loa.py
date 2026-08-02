"""Đặt LỊCH đọc ra loa: sống qua restart, lịch giữ file — phát ngay thì xoá file.

Yêu cầu 02/08: "có thể hẹn giờ phát âm thanh qua loa như đặt lịch (nếu là đặt lịch
thì file âm thanh lưu lại db, lúc cần thì phát và không phải lịch thì phát xong
xoá file đi)".

Trạng thái TRƯỚC file này: `announce.schedule` dùng `threading.Timer` — chính
docstring của module đã ghi "KHÔNG sống qua restart … cần bền vững thì dùng
agent_reminders (SQLite)". Đủ cho "sau 1 phút", vô dụng cho "8h sáng mai".

Cách làm: KHÔNG dựng bộ hẹn giờ thứ hai. Ghi vào đúng bảng `reminders` với
`mode='loa'` — dùng lại vòng chạy, phép chống chạy trùng (`last_run_at`), bộ hiểu
thời gian tiếng Việt (`parse_when`), lịch lặp (`rrule`) và chỗ xem/huỷ có sẵn.

Hai bất biến về FILE, đây là phần dễ sai nhất:
  · Âm thanh của LỊCH nằm trong `media_dir` (để `/media/voice/<tên>` phục vụ được
    cho loa kéo về) nhưng phải sống sót `cleanup_media()` — hàm đó xoá theo TUỔI,
    mặc định 24h, nên lịch 8h sáng mai đặt từ tối nay sẽ mất tiếng. Giải: tiền tố
    `lich_`, cleanup bỏ qua.
  · Âm thanh PHÁT NGAY thì xoá sau khi đọc xong. Phải CHỜ đúng độ dài: `play_on()`
    trả về trước khi loa phát xong, xoá sớm là loa đang kéo dở thì mất tiếng.
"""
from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import voice  # noqa: E402
from services.agent import reminders as rem  # noqa: E402
from services.voice import announce as ann  # noqa: E402

LOA = {"id": "spk1", "name": "loa phòng khách", "kind": "cast", "host": "192.168.1.9"}
NOI_DUNG = "chuẩn bị đi ngủ thôi các con"


class GiuFileCuaLichTests(unittest.TestCase):
    """`cleanup_media` xoá theo tuổi — file của lịch phải sống sót."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="loa-lich-")
        self.p = mock.patch("services.voice.config.media_dir", lambda: Path(self.tmp))
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_file_lich_co_tien_to_rieng(self):
        p = voice.save_media(b"RIFF....", giu_lai=True)
        self.assertTrue(p.name.startswith(voice.LICH_PREFIX))

    def test_file_thuong_khong_co_tien_to(self):
        self.assertFalse(voice.save_media(b"RIFF....").name.startswith(voice.LICH_PREFIX))

    def test_cleanup_KHONG_xoa_file_cua_lich(self):
        cua_lich = voice.save_media(b"RIFF-lich", giu_lai=True)
        thuong = voice.save_media(b"RIFF-thuong")
        cu = time.time() - 90 * 3600            # 90 giờ trước, quá hạn 24h
        os.utime(cua_lich, (cu, cu))
        os.utime(thuong, (cu, cu))
        voice.cleanup_media(max_age_hours=24)
        self.assertTrue(cua_lich.is_file(), "âm thanh của lịch bị dọn mất tiếng")
        self.assertFalse(thuong.is_file(), "file thường quá hạn phải bị dọn")


class XoaFilePhatNgayTests(unittest.TestCase):
    """Phát ngay xong là xoá — và phải CHỜ loa đọc hết mới xoá."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="loa-ngay-"))

    def _file(self, ten: str) -> Path:
        p = self.tmp / ten
        p.write_bytes(b"RIFF....")
        return p

    def test_xoa_file_thuong_sau_khi_doc_xong(self):
        f1, f2 = self._file("a.wav"), self._file("b.wav")
        with mock.patch.object(ann, "_do_dai_audio", lambda url: 0.0):
            ann._tra_am_luong_sau_khi_phat(LOA, None, "http://x/b.wav", [f1, f2])
        for _ in range(50):
            if not f1.is_file() and not f2.is_file():
                break
            time.sleep(0.02)
        self.assertFalse(f1.is_file())
        self.assertFalse(f2.is_file())

    def test_KHONG_xoa_file_cua_lich_du_bi_truyen_vao(self):
        """Chặn hai lớp: nếu chỗ nào lỡ truyền file lịch vào đây, vẫn không mất."""
        f = self._file(voice.LICH_PREFIX + "c.wav")
        with mock.patch.object(ann, "_do_dai_audio", lambda url: 0.0):
            ann._tra_am_luong_sau_khi_phat(LOA, None, "http://x/c.wav", [f])
        time.sleep(0.1)
        self.assertTrue(f.is_file())

    def test_cho_dung_do_dai_roi_moi_xoa(self):
        """play_on() trả về trước khi loa phát xong — xoá sớm là mất tiếng."""
        f = self._file("d.wav")
        with mock.patch.object(ann, "_do_dai_audio", lambda url: 0.35):
            ann._tra_am_luong_sau_khi_phat(LOA, None, "http://x/d.wav", [f])
            time.sleep(0.1)
            self.assertTrue(f.is_file(), "chưa đọc xong đã xoá")
        for _ in range(60):
            if not f.is_file():
                break
            time.sleep(0.02)
        self.assertFalse(f.is_file())


class DatLichTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="loa-dat-"))
        self.p1 = mock.patch("services.voice.config.media_dir", lambda: self.tmp)
        self.p1.start(); self.addCleanup(self.p1.stop)
        self.p2 = mock.patch.object(ann, "_resolve_one", lambda q: dict(LOA))
        self.p2.start(); self.addCleanup(self.p2.stop)
        self.p3 = mock.patch.object(voice, "speak", lambda text, v="", **k: b"RIFF-wav")
        self.p3.start(); self.addCleanup(self.p3.stop)
        self.da_tao: list[dict] = []

        def _create(user_id, text, lich, *, mode="notify", meta_extra=None):
            row = {"id": "r1", "user_id": user_id, "text": text, "mode": mode,
                   "kind": lich.get("kind"), "next_run_at": lich["next_run_at"],
                   "hour": lich.get("hour"), "minute": lich.get("minute"),
                   "due_at": lich.get("due_at"), "interval_min": lich.get("interval_min"),
                   "rrule": None, "meta": meta_extra or {}}
            self.da_tao.append(row)
            return row
        self.p4 = mock.patch.object(rem, "create", _create)
        self.p4.start(); self.addCleanup(self.p4.stop)

    def test_ghi_dung_mode_loa_va_du_thong_tin(self):
        row = ann.dat_lich("zalo_9", "loa phòng khách", NOI_DUNG, "8h sáng mai",
                           volume=0.6, voice_name="vi-nu-nhe")
        self.assertEqual(row["mode"], "loa")
        meta = row["meta"]
        self.assertEqual(meta["speaker_id"], "spk1")
        self.assertEqual(meta["volume"], 0.6)
        self.assertEqual(meta["voice"], "vi-nu-nhe")
        self.assertTrue(Path(meta["audio_path"]).is_file())

    def test_tieng_duoc_doc_SAN_va_giu_file(self):
        """Tới giờ chỉ phát file — lịch vẫn chạy dù engine giọng lúc đó đang lỗi."""
        row = ann.dat_lich("zalo_9", "loa phòng khách", NOI_DUNG, "mỗi ngày 6h")
        p = Path(row["meta"]["audio_path"])
        self.assertEqual(p.read_bytes(), b"RIFF-wav")
        self.assertTrue(p.name.startswith(voice.LICH_PREFIX))

    def test_khong_hieu_thoi_diem_thi_bao_ngay(self):
        with self.assertRaises(ValueError):
            ann.dat_lich("zalo_9", "loa phòng khách", NOI_DUNG, "khi nào rảnh")

    def test_TTS_hong_thi_bao_ngay_khong_de_lich_im_lang(self):
        with mock.patch.object(voice, "speak",
                               side_effect=RuntimeError("chưa nạp model giọng")):
            with self.assertRaises(RuntimeError):
                ann.dat_lich("zalo_9", "loa phòng khách", NOI_DUNG, "8h sáng mai")

    def test_tao_lich_hong_thi_khong_de_lai_file_mo_coi(self):
        with mock.patch.object(rem, "create", side_effect=RuntimeError("DB hỏng")):
            with self.assertRaises(RuntimeError):
                ann.dat_lich("zalo_9", "loa phòng khách", NOI_DUNG, "8h sáng mai")
        self.assertEqual(list(self.tmp.glob("*")), [])


class PhatKhiToiGioTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="loa-gio-"))
        self.f = self.tmp / (voice.LICH_PREFIX + "x.wav")
        self.f.write_bytes(b"RIFF....")
        self.da_phat: list = []
        self.p1 = mock.patch("services.voice.speakers.get", lambda sid: dict(LOA))
        self.p1.start(); self.addCleanup(self.p1.stop)
        self.p2 = mock.patch.object(voice, "media_url", lambda p: f"http://x/{p.name}")
        self.p2.start(); self.addCleanup(self.p2.stop)
        self.p3 = mock.patch.object(voice, "play_on",
                                    lambda rec, url: self.da_phat.append(url))
        self.p3.start(); self.addCleanup(self.p3.stop)

    def _meta(self, **over) -> dict:
        m = {"speaker_id": "spk1", "audio_path": str(self.f), "voice": "", "volume": None}
        m.update(over)
        return m

    def test_phat_dung_file_da_luu(self):
        ok, ten = rem._phat_ra_loa(self._meta(), NOI_DUNG)
        self.assertTrue(ok)
        self.assertEqual(ten, "loa phòng khách")
        self.assertEqual(self.da_phat, [f"http://x/{self.f.name}"])

    def test_mat_file_thi_doc_lai_chu_khong_im_lang(self):
        self.f.unlink()
        goi: list = []
        with mock.patch.object(voice, "play_text_on",
                               lambda t, rec, v="", **k: goi.append((t, v)) or "http://x/y.wav"):
            ok, _ = rem._phat_ra_loa(self._meta(voice="vi-nu-nhe"), NOI_DUNG)
        self.assertTrue(ok)
        self.assertEqual(goi, [(NOI_DUNG, "vi-nu-nhe")])

    def test_loa_da_bi_xoa_thi_bao_ro(self):
        with mock.patch("services.voice.speakers.get", lambda sid: None):
            ok, ly_do = rem._phat_ra_loa(self._meta(), NOI_DUNG)
        self.assertFalse(ok)
        self.assertIn("spk1", ly_do)

    def test_dat_am_luong_roi_tra_ve_muc_cu(self):
        dat: list[float] = []
        with mock.patch("services.voice.speakers.get_volume", lambda rec: 0.25), \
             mock.patch("services.voice.speakers.set_volume",
                        lambda rec, level: dat.append(round(float(level), 3))), \
             mock.patch.object(ann, "_do_dai_audio", lambda url: 0.0):
            ok, _ = rem._phat_ra_loa(self._meta(volume=0.7), NOI_DUNG)
        self.assertTrue(ok)
        for _ in range(50):
            if len(dat) >= 2:
                break
            time.sleep(0.02)
        self.assertEqual(dat, [0.7, 0.25])


class HuyLichThiXoaFileTests(unittest.TestCase):
    """File của lịch có tiền tố `lich_` nên cleanup CỐ Ý không dọn — chỉ có một
    đường ra duy nhất là huỷ lịch."""

    def test_xoa_audio_khi_huy(self):
        import json
        import tempfile
        p = Path(tempfile.mkdtemp()) / (voice.LICH_PREFIX + "z.wav")
        p.write_bytes(b"RIFF")
        rem._xoa_audio_cua_lich([
            {"id": "r1", "mode": "loa", "meta": json.dumps({"audio_path": str(p)})}])
        self.assertFalse(p.is_file())

    def test_khong_dung_den_lich_khac_mode(self):
        import json
        import tempfile
        p = Path(tempfile.mkdtemp()) / "khong-phai-loa.wav"
        p.write_bytes(b"RIFF")
        rem._xoa_audio_cua_lich([
            {"id": "r2", "mode": "notify", "meta": json.dumps({"audio_path": str(p)})}])
        self.assertTrue(p.is_file())

    def test_meta_rac_khong_no(self):
        rem._xoa_audio_cua_lich([{"id": "r3", "mode": "loa", "meta": "khong-phai-json"}])
        rem._xoa_audio_cua_lich([{"id": "r4", "mode": "loa"}])


class DungLaiBangReminderTests(unittest.TestCase):
    """Không dựng bộ hẹn giờ thứ hai — dùng đúng bảng và vòng chạy có sẵn."""

    def setUp(self):
        import pathlib
        self.code = (pathlib.Path(__file__).resolve().parents[1]
                     / "services" / "agent" / "reminders.py").read_text("utf-8")

    def test_mode_loa_duoc_chap_nhan(self):
        self.assertIn('_MODES = ("notify", "task", "loa")', self.code)

    def test_fire_co_nhanh_loa(self):
        i = self.code.index('elif mode == "loa":')
        self.assertIn("_phat_ra_loa(meta, text)", self.code[i:i + 400])

    def test_khong_them_cot_moi_vao_bang(self):
        """Dữ liệu loa nằm trong cột `meta` sẵn có."""
        self.assertNotIn("ADD COLUMN speaker_id", self.code)
        self.assertNotIn("ADD COLUMN audio_path", self.code)
        self.assertIn("meta_extra", self.code)

    def test_huy_lich_thi_don_file(self):
        i = self.code.index("def cancel(")
        self.assertIn("_xoa_audio_cua_lich", self.code[i:i + 900])


if __name__ == "__main__":
    unittest.main()
