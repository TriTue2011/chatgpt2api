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


class LenhGhepDungThuTuDauVao(unittest.TestCase):
    """Lọc `concat` của ffmpeg đọc n*(v+a) đầu vào theo nhóm ĐOẠN, không theo LOẠI.

    Đo 10/08/2026 khi ghép 4 clip Flow 8 giây: bản cũ xếp `[v0][v1][v2][v3]` rồi
    mới tới `[0:a][1:a][2:a][3:a]`, nên ffmpeg nhận nhầm một nhánh video vào chân
    audio và chết lúc dựng đồ thị lọc. Với MỘT clip thì hai cách xếp trùng nhau
    nên lỗi ẩn hoàn toàn — đường ghép video dài giữ tiếng gốc chưa bao giờ chạy.
    """

    def _loc(self, so_clip: int, co_voiceover: bool = False) -> str:
        tep = []
        for i in range(so_clip):
            fd, p = tempfile.mkstemp(suffix=f"_{i}.mp4")
            os.close(fd)
            Path(p).write_bytes(b"\0" * 32)
            tep.append(p)
        tieng = None
        if co_voiceover:
            fd, tieng = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            Path(tieng).write_bytes(b"\0" * 32)
        fd, ra = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        Path(ra).write_bytes(b"\0" * 32)
        ket = mock.Mock(returncode=0, stderr=b"")
        with mock.patch.object(subprocess, "run", return_value=ket) as chay:
            A.concat_clips(tep, tieng, ra)
        for p in tep + ([tieng] if tieng else []) + [ra]:
            try:
                os.unlink(p)
            except OSError:
                pass
        cmd = chay.call_args[0][0]
        return cmd[cmd.index("-filter_complex") + 1]

    def test_giu_tieng_goc_thi_xen_ke_video_audio(self):
        loc = self._loc(4)
        self.assertIn("[v0][0:a][v1][1:a][v2][2:a][v3][3:a]concat=n=4:v=1:a=1", loc)

    def test_khong_con_xep_het_video_roi_moi_toi_audio(self):
        loc = self._loc(3)
        self.assertNotIn("[v0][v1][v2][0:a]", loc)

    def test_mot_clip_van_dung(self):
        """Ca duy nhất trước đây chạy được — không được làm hỏng nó."""
        self.assertIn("[v0][0:a]concat=n=1:v=1:a=1", self._loc(1))

    def test_co_voiceover_thi_chi_concat_video(self):
        """Nhánh thay tiếng bằng voiceover xếp toàn video là ĐÚNG (a=0)."""
        loc = self._loc(3, co_voiceover=True)
        self.assertIn("[v0][v1][v2]concat=n=3:v=1:a=0", loc)


class DocPromptCanhTuDapLLM(unittest.TestCase):
    """Bộ tách cảnh của gateway làm TỐT, nhưng bước đọc kết quả ném hết đi.

    Đo 10/08/2026 trên máy chạy thật: LLM trả bốn prompt cảnh có nhân vật xuyên
    suốt, mỗi cảnh một dòng, ngăn nhau bằng dấu phẩy cuối dòng — không phải mảng
    JSON. Bản cũ chỉ nhận JSON (tìm `[` và `]`), không thấy là coi như thất bại
    rồi âm thầm trả về `[prompt] * n`. Hệ quả: cả bốn cảnh dùng CHUNG một mô tả,
    model dựng ra bốn biến thể na ná nhau, nối lại càng thấy vô lý — mà không
    log nào ghi lại.
    """

    DAP_THAT = (
        "A cinematic early morning scene at a tiny seaside coffee shop in Vietnam, "
        "the same young Vietnamese barista opening wooden shutters as warm light spills in.,\n"
        "Inside the same small Vietnamese seaside cafe, the same barista prepares "
        "traditional coffee with a metal phin filter, steam rising from the cup.,\n"
        "The same traveler sits by the window of the seaside cafe, slowly stirring "
        "the coffee while gentle ocean waves roll behind the glass.,\n"
        "Wide shot of the same seaside cafe from the beach, barista and traveler "
        "small in frame, morning light warm across the sand."
    )

    def test_doc_duoc_dap_van_ban_thuong(self):
        ra = S._doc_canh(self.DAP_THAT)
        self.assertEqual(len(ra), 4)
        self.assertTrue(all(len(x) > 40 for x in ra))
        # Không được còn dấu phẩy ngăn dòng ở cuối mỗi cảnh.
        self.assertFalse(any(x.endswith(",") for x in ra))

    def test_bon_canh_phai_KHAC_nhau(self):
        """Đây là toàn bộ mục đích: bốn cảnh giống nhau là video vô lý."""
        ra = S._doc_canh(self.DAP_THAT)
        self.assertEqual(len(set(ra)), len(ra))

    def test_van_doc_duoc_mang_JSON(self):
        """Model nào chịu trả JSON thì đường cũ vẫn phải chạy."""
        ra = S._doc_canh('["' + "canh mot day du dai de vuot nguong doc" + '", "'
                         + "canh hai cung day du dai de vuot nguong doc" + '"]')
        self.assertEqual(len(ra), 2)

    def test_bo_so_thu_tu_va_gach_dau_dong(self):
        ra = S._doc_canh(
            "1. Canh mot mo ta day du de vuot qua nguong ky tu toi thieu\n"
            "2) Canh hai mo ta day du de vuot qua nguong ky tu toi thieu\n"
            "- Canh ba mo ta day du de vuot qua nguong ky tu toi thieu")
        self.assertEqual(len(ra), 3)
        self.assertFalse(any(x[0].isdigit() or x[0] in "-*•" for x in ra))

    def test_bo_dong_dan_nhap(self):
        ra = S._doc_canh(
            "Here are 4 scenes:\n"
            "Canh mot mo ta day du de vuot qua nguong ky tu toi thieu roi\n"
            "Canh hai mo ta day du de vuot qua nguong ky tu toi thieu roi")
        self.assertEqual(len(ra), 2)

    def test_dap_rong_thi_tra_rong(self):
        self.assertEqual(S._doc_canh(""), [])
        self.assertEqual(S._doc_canh("   "), [])


class GhepPhaiTONTRONGKhungHinh(unittest.TestCase):
    """`/v1/video/compose` khai nhận `aspect_ratio` nhưng chưa bao giờ dùng.

    Lệnh gọi bỏ trắng width/height nên `concat_clips` lấy mặc định 1080x1920,
    tức khung DỌC. Đo 10/08/2026: ghép hai clip 1280x720 kèm
    `aspect_ratio: "16:9"`, kết quả ra 1080x1920 — clip ngang bị scale lên rồi
    cắt mất hai bên. Lỗi không ném ra, chỉ là video sai khung.
    """

    def setUp(self):
        self.ma = "\n".join(
            l for l in (Path(__file__).resolve().parents[1] / "api/veo_video.py")
            .read_text(encoding="utf-8").splitlines()
            if not l.lstrip().startswith("#"))

    def test_doc_ty_le_tu_than_yeu_cau(self):
        self.assertIn('(body or {}).get("aspect_ratio") or "9:16"', self.ma)

    def test_16_9_ra_khung_ngang(self):
        self.assertIn('(1920, 1080) if ty_le == "16:9" else (1080, 1920)', self.ma)

    def test_truyen_width_height_xuong_ham_ghep(self):
        self.assertIn("concat_clips(clip_paths, audio_path, None, width=w, height=h)",
                      self.ma)

    def test_video_ghep_phai_vao_thu_vien(self):
        """Đo 10/08/2026: ghép 4 clip ra MP4 32 giây, thư viện vẫn đúng 16 mục.

        Chính bản dài — thứ tốn nhiều tín dụng nhất để dựng — lại là thứ duy
        nhất không được lưu: tải lại trang là mất, "Quản lý Video" không thấy.
        """
        i = self.ma.index("def handle_video_compose")
        j = self.ma.index("def handle_video_story")
        self.assertIn("_luu_thu_vien(", self.ma[i:j])


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
