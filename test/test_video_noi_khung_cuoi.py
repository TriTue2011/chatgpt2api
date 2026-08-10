"""Nối cảnh bằng khung hình cuối — thứ làm video 30 giây không giật ở mối nối.

Clip Veo dài 6–10 giây, muốn video 30 giây thì phải ghép nhiều clip. Ghép suông
thì mỗi mối nối là một cú nhảy hình vì cảnh sau chẳng liên quan gì cảnh trước.
Cách chữa: lấy khung CUỐI của cảnh N làm khung ĐẦU của cảnh N+1.

Máy chạy test không chắc có ffmpeg nên ở đây kiểm phần đấu nối — thứ dễ sai
nhất và sai thì im lặng: video vẫn ra, chỉ là không mượt, không ai biết. Lệnh
ffmpeg thì lấy nguyên từ app VEO3 AI Studio (đã đọc mã, `-sseof -0.1`).
"""
import base64
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))

from services.video import assemble as A  # noqa: E402
from services.video import shorts as S  # noqa: E402


class LenhLayKhungCuoi(unittest.TestCase):
    """Lệnh phải tua từ ĐUÔI clip, không phải từ đầu."""

    def _chay(self, ma_tra=0, byte_ra=b"\x89PNG..."):
        fd, ra = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Path(ra).write_bytes(byte_ra)
        fd2, clip = tempfile.mkstemp(suffix=".mp4")
        os.close(fd2)
        Path(clip).write_bytes(b"\0" * 16)
        ket = mock.Mock(returncode=ma_tra, stderr=b"loi gia")
        with mock.patch.object(subprocess, "run", return_value=ket) as chay:
            try:
                tra = A.extract_last_frame(clip, ra)
            finally:
                for f in (ra, clip):
                    try:
                        os.unlink(f)
                    except OSError:
                        pass
        return chay.call_args[0][0], tra

    def test_tua_tu_duoi_clip_lay_dung_mot_khung(self):
        cmd, _ = self._chay()
        self.assertIn("-sseof", cmd)
        # Mốc tua phải ÂM (tính ngược từ đuôi). Số dương là tua từ đầu — lấy
        # nhầm khung mở đầu thì cảnh sau lặp lại cảnh trước, nhìn như đứng hình.
        self.assertLess(float(cmd[cmd.index("-sseof") + 1]), 0)
        self.assertEqual(cmd[cmd.index("-vframes") + 1], "1")

    def test_khong_dung_do_dai_ffprobe_de_tua(self):
        """`-ss <độ dài>` là cách sai: ffprobe lệch vài ms là tua quá đuôi."""
        cmd, _ = self._chay()
        self.assertNotIn("-ss", cmd)

    def test_ma_tra_0_nhung_file_rong_van_phai_la_loi(self):
        """ffmpeg tua quá đuôi thì trả mã 0 kèm file rỗng — im lặng nuốt là
        cảnh sau nhận ảnh rỗng, Veo dựng một cảnh chẳng liên quan gì."""
        with self.assertRaises(A.VideoError):
            self._chay(ma_tra=0, byte_ra=b"")

    def test_thieu_ffmpeg_bao_ro_chu_khong_vo_tran(self):
        fd, clip = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        Path(clip).write_bytes(b"\0" * 16)
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaises(A.VideoError) as nc:
                A.extract_last_frame(clip)
        os.unlink(clip)
        self.assertIn("ffmpeg", str(nc.exception).lower())

    def test_clip_khong_ton_tai_bao_ngay(self):
        with self.assertRaises(A.VideoError):
            A.extract_last_frame("/khong/co/that.mp4")


class NoiCanhTruyenKhungCuoi(unittest.TestCase):
    """Cảnh sau phải NHẬN khung cuối cảnh trước — chỗ sai thì im lặng."""

    def setUp(self):
        self.goi: list[dict] = []
        clip_gia = base64.b64encode(b"MP4GIA").decode()

        def _sinh(than, _cred):
            self.goi.append(dict(than))
            return {"data": [{"b64_json": clip_gia}]}

        self.p_gen = mock.patch.object(S.veo_adapter, "generate", side_effect=_sinh)
        self.p_khung = mock.patch.object(
            S, "_khung_cuoi_b64", side_effect=lambda p: "KHUNG:" + Path(p).name)
        self.p_noi = mock.patch.object(S, "concat_clips",
                                       side_effect=lambda c, *a, **k: c[0])
        for p in (self.p_gen, self.p_khung, self.p_noi):
            p.start()
            self.addCleanup(p.stop)

    def test_canh_dau_khong_co_anh_cac_canh_sau_deu_co(self):
        S.make_story_video({}, scenes=["một", "hai", "ba"])
        self.assertEqual(len(self.goi), 3)
        self.assertNotIn("image", self.goi[0])
        self.assertTrue(self.goi[1]["image"].startswith("KHUNG:"))
        self.assertTrue(self.goi[2]["image"].startswith("KHUNG:"))

    def test_moi_canh_noi_tu_canh_LIEN_TRUOC_chu_khong_phai_canh_dau(self):
        """Nối nhầm về cảnh đầu thì video đứng yên một chỗ suốt 30 giây."""
        S.make_story_video({}, scenes=["một", "hai", "ba"])
        self.assertIn("scene0", self.goi[1]["image"])
        self.assertIn("scene1", self.goi[2]["image"])

    def test_tat_co_thi_khong_canh_nao_nhan_anh(self):
        S.make_story_video({}, scenes=["một", "hai"], chain_frames=False)
        self.assertTrue(all("image" not in g for g in self.goi))

    def test_canh_cuoi_khong_ton_cong_lay_khung(self):
        """Khung cuối của cảnh chót chẳng ai dùng — lấy là phí một lượt ffmpeg."""
        with mock.patch.object(S, "_khung_cuoi_b64",
                               side_effect=lambda p: "K") as lay:
            S.make_story_video({}, scenes=["một", "hai", "ba"])
        self.assertEqual(lay.call_count, 2)

    def test_model_flow_thi_di_Flow_chu_khong_goi_Veo(self):
        """Video dài bằng bậc Lite của Flow: `model="flow/*"` phải rẽ sang Flow.

        Không có nhánh này thì mọi lượt ghép cảnh đều đi Veo qua API Gemini, và
        bậc Lite của Flow — bậc rẻ nhất — không dùng được cho video dài.
        """
        goi: list[dict] = []
        with mock.patch.object(
                S, "_clip_bang_flow",
                side_effect=lambda p, **kw: (goi.append(kw), base64.b64encode(b"MP4").decode())[1]):
            S.make_story_video({}, scenes=["một", "hai"], model="flow/veo-3.1-lite",
                               aspect_ratio="16:9")
        self.assertEqual(len(goi), 2)
        self.assertEqual(goi[0]["model"], "flow/veo-3.1-lite")
        self.assertEqual(goi[0]["aspect_ratio"], "16:9")
        # Cảnh đầu không có khung nối, cảnh sau phải có.
        self.assertEqual(goi[0]["khung_dau"], "")
        self.assertTrue(goi[1]["khung_dau"])
        # Và KHÔNG được gọi Veo lần nào.
        self.assertEqual(len(self.goi), 0)

    def test_model_rong_van_di_Veo_nhu_cu(self):
        """Đổi đường cho Flow không được làm hỏng đường Veo đang chạy."""
        S.make_story_video({}, scenes=["một", "hai"])
        self.assertEqual(len(self.goi), 2)

    def test_lay_khung_hong_thi_van_ra_video(self):
        """ffmpeg hỏng ở giữa chừng không được làm mất trắng cả video."""
        with mock.patch.object(S, "_khung_cuoi_b64",
                               side_effect=A.VideoError("ffmpeg chết")):
            S.make_story_video({}, scenes=["một", "hai"])
        self.assertEqual(len(self.goi), 2)


if __name__ == "__main__":
    unittest.main()
