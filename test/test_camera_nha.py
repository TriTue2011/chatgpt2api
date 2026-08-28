"""Camera nhà: sổ camera, khớp tên, và hai đường bóc ảnh.

Không chạm camera thật. Đường go2rtc thay ``httpx.get`` bằng hàm giả; đường RTSP
chỉ kiểm nhánh lỗi (không có máy chủ nào để nối), vì nhánh thành công cần một
luồng RTSP thật — thuộc loại e2e, không đưa vào CI.
"""

from __future__ import annotations

import os
import shutil
import unittest
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import camera_nha as cam  # noqa: E402
from services.config import config  # noqa: E402

GO2RTC = {"kind": "go2rtc", "base": "http://10.0.0.9:1984", "src": "san"}
RTSP = {"kind": "rtsp", "url": "rtsp://admin:BiMat@10.0.0.5:554/stream1"}


class _So:
    """Đặt sổ camera vào config mà không ghi ra đĩa."""

    def __init__(self, so: dict) -> None:
        self.so = so

    def __enter__(self):
        self._cu = config.data.get("cameras")
        config.data["cameras"] = self.so
        self._p = mock.patch.object(config, "_save", lambda: None)
        self._p.start()
        return self

    def __exit__(self, *a) -> None:
        self._p.stop()
        if self._cu is None:
            config.data.pop("cameras", None)
        else:
            config.data["cameras"] = self._cu


@pytest.mark.pure
class CheBiMatTests(unittest.TestCase):
    def test_bo_mat_khau_khoi_url_rtsp(self) -> None:
        ra = cam.che_bi_mat("rtsp://admin:BiMat@10.0.0.5:554/stream1")
        self.assertNotIn("BiMat", ra)
        self.assertIn("admin", ra)
        self.assertIn("10.0.0.5:554", ra)

    def test_url_khong_co_mat_khau_giu_nguyen(self) -> None:
        u = "http://10.0.0.9:1984"
        self.assertEqual(cam.che_bi_mat(u), u)

    def test_url_rac_van_che_duoc(self) -> None:
        self.assertNotIn("BiMat", cam.che_bi_mat("rtsp://user:BiMat@[không-hợp-lệ"))


@pytest.mark.pure
class SoCameraTests(unittest.TestCase):
    def test_them_go2rtc_va_rtsp(self) -> None:
        with _So({}):
            cam.them("Sân trước", "go2rtc", base="http://10.0.0.9:1984/", src="san")
            cam.them("Bếp", "rtsp", url="rtsp://admin:BiMat@10.0.0.5/s1")
            ten = {c["name"] for c in cam.danh_sach()}
            self.assertEqual(ten, {"Sân trước", "Bếp"})

    def test_them_bo_dau_gach_cuoi_cua_base(self) -> None:
        with _So({}):
            ra = cam.them("Sân", "go2rtc", base="http://10.0.0.9:1984/", src="san")
            self.assertEqual(ra["base"], "http://10.0.0.9:1984")

    def test_kieu_la_bi_tu_choi(self) -> None:
        with _So({}), self.assertRaises(cam.LoiCamera):
            cam.them("Sân", "onvif", url="http://x")

    def test_go2rtc_thieu_src_bi_tu_choi(self) -> None:
        with _So({}), self.assertRaises(cam.LoiCamera):
            cam.them("Sân", "go2rtc", base="http://10.0.0.9:1984")

    def test_rtsp_sai_giao_thuc_bi_tu_choi(self) -> None:
        with _So({}), self.assertRaises(cam.LoiCamera):
            cam.them("Sân", "rtsp", url="http://10.0.0.5/stream")

    def test_ten_rong_bi_tu_choi(self) -> None:
        with _So({}), self.assertRaises(cam.LoiCamera):
            cam.them("   ", "rtsp", url="rtsp://10.0.0.5/s")

    def test_danh_sach_che_mat_khau(self) -> None:
        with _So({"Bếp": dict(RTSP)}):
            [c] = cam.danh_sach()
            self.assertNotIn("BiMat", c["url"])
            self.assertNotIn("password", c)

    def test_danh_sach_kem_bi_mat_tra_ban_that(self) -> None:
        with _So({"Bếp": dict(RTSP)}):
            [c] = cam.danh_sach(kem_bi_mat=True)
            self.assertIn("BiMat", c["url"])

    def test_them_khong_tra_mat_khau_ve(self) -> None:
        with _So({}):
            ra = cam.them("Sân", "go2rtc", base="http://x:1984", src="s",
                          username="u", password="BiMat")
            self.assertNotIn("password", ra)

    def test_xoa(self) -> None:
        with _So({"Bếp": dict(RTSP)}):
            self.assertTrue(cam.xoa("Bếp"))
            self.assertEqual(cam.danh_sach(), [])

    def test_xoa_ten_khong_co_tra_false(self) -> None:
        with _So({"Bếp": dict(RTSP)}):
            self.assertFalse(cam.xoa("Sân"))


@pytest.mark.pure
class KhopTenTests(unittest.TestCase):
    def test_khop_khong_dau(self) -> None:
        with _So({"Sân trước": dict(GO2RTC)}):
            ten, ban_ghi, _ = cam.tim("san truoc")
            self.assertEqual(ten, "Sân trước")
            self.assertIsNotNone(ban_ghi)

    def test_khop_khi_co_them_tu_chung(self) -> None:
        with _So({"Sân trước": dict(GO2RTC), "Bếp": dict(RTSP)}):
            ten, _, _ = cam.tim("xem camera sân trước")
            self.assertEqual(ten, "Sân trước")

    def test_mot_camera_thi_noi_camera_la_du(self) -> None:
        with _So({"Sân trước": dict(GO2RTC)}):
            ten, ban_ghi, _ = cam.tim("camera")
            self.assertEqual(ten, "Sân trước")
            self.assertIsNotNone(ban_ghi)

    def test_map_mo_thi_khong_doan_bua(self) -> None:
        # Hai camera cùng chữ "sân" — phải hỏi lại, không được chọn liều.
        with _So({"Sân trước": dict(GO2RTC), "Sân sau": dict(GO2RTC)}):
            ten, ban_ghi, goi_y = cam.tim("camera sân")
            self.assertEqual(ten, "")
            self.assertIsNone(ban_ghi)
            self.assertEqual(goi_y, ["Sân sau", "Sân trước"])

    def test_nhieu_camera_ma_noi_trong_khong_thi_hoi_lai(self) -> None:
        with _So({"Sân trước": dict(GO2RTC), "Bếp": dict(RTSP)}):
            _, ban_ghi, goi_y = cam.tim("camera")
            self.assertIsNone(ban_ghi)
            self.assertEqual(goi_y, ["Bếp", "Sân trước"])

    def test_khop_theo_ghi_chu(self) -> None:
        with _So({"cam1": dict(GO2RTC, note="cổng ngoài"),
                  "cam2": dict(RTSP, note="phòng khách")}):
            ten, _, _ = cam.tim("cổng ngoài")
            self.assertEqual(ten, "cam1")

    def test_chua_khai_camera_nao(self) -> None:
        with _So({}):
            ten, ban_ghi, goi_y = cam.tim("sân")
            self.assertEqual((ten, ban_ghi, goi_y), ("", None, []))


class _Đáp:
    def __init__(self, status: int, content: bytes = b"") -> None:
        self.status_code = status
        self.content = content


@pytest.mark.pure
class ChupGo2rtcTests(unittest.TestCase):
    def _chup(self, dap, **kw):
        with _So({"Sân": dict(GO2RTC, **kw)}), \
             mock.patch("httpx.get", return_value=dap) as g, \
             mock.patch.object(cam, "_thu_nho", lambda b, c: b):
            return cam.chup("Sân"), g

    def test_lay_duoc_khung(self) -> None:
        (ket_qua, g) = self._chup(_Đáp(200, b"\xff\xd8jpeg"))
        ten, jpeg = ket_qua
        self.assertEqual(ten, "Sân")
        self.assertEqual(jpeg, b"\xff\xd8jpeg")
        # Đúng endpoint và đúng tên luồng — đây là hợp đồng với go2rtc.
        self.assertEqual(g.call_args.args[0], "http://10.0.0.9:1984/api/frame.jpeg")
        self.assertEqual(g.call_args.kwargs["params"], {"src": "san"})

    def test_gui_kem_tai_khoan_khi_co_khai(self) -> None:
        (_, g) = self._chup(_Đáp(200, b"x"), username="u", password="p")
        self.assertEqual(g.call_args.kwargs["auth"], ("u", "p"))

    def test_khong_khai_tai_khoan_thi_khong_gui_auth(self) -> None:
        (_, g) = self._chup(_Đáp(200, b"x"))
        self.assertIsNone(g.call_args.kwargs["auth"])

    def test_404_noi_ro_thieu_luong(self) -> None:
        with self.assertRaises(cam.LoiCamera) as e:
            self._chup(_Đáp(404))
        self.assertIn("san", str(e.exception))

    def test_401_noi_ro_sai_mat_khau(self) -> None:
        with self.assertRaises(cam.LoiCamera) as e:
            self._chup(_Đáp(401))
        self.assertIn("mật khẩu", str(e.exception))

    def test_khung_qua_lon_bi_chan(self) -> None:
        with self.assertRaises(cam.LoiCamera):
            self._chup(_Đáp(200, b"x" * (cam.TOI_DA_BYTE + 1)))

    def test_khong_noi_duoc_may_chu(self) -> None:
        with _So({"Sân": dict(GO2RTC)}), \
             mock.patch("httpx.get", side_effect=OSError("connection refused")), \
             self.assertRaises(cam.LoiCamera) as e:
            cam.chup("Sân")
        self.assertIn("go2rtc", str(e.exception))


@pytest.mark.pure
class ChupSaiTenTests(unittest.TestCase):
    def test_chua_khai_gi(self) -> None:
        with _So({}), self.assertRaises(cam.LoiCamera) as e:
            cam.chup("sân")
        self.assertIn("Chưa có camera nào", str(e.exception))

    def test_map_mo_thi_liet_ke_de_hoi_lai(self) -> None:
        with _So({"Sân trước": dict(GO2RTC), "Sân sau": dict(GO2RTC)}), \
             self.assertRaises(cam.LoiCamera) as e:
            cam.chup("sân")
        self.assertIn("Sân trước", str(e.exception))
        self.assertIn("Sân sau", str(e.exception))


CO_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.mark.pure
class ThieuFfmpegTests(unittest.TestCase):
    """Máy không có ffmpeg thì phải nói thẳng, và KHÔNG được nuốt mất ảnh."""

    def test_rtsp_thieu_ffmpeg_bao_ro(self) -> None:
        with _So({"Bếp": dict(RTSP)}), \
             mock.patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg")), \
             self.assertRaises(cam.LoiCamera) as e:
            cam.chup("Bếp")
        self.assertIn("ffmpeg", str(e.exception))

    def test_thu_nho_thieu_ffmpeg_thi_tra_nguyen_ban(self) -> None:
        # Thu nhỏ là bước làm-đẹp: thiếu ffmpeg thì gửi ảnh to, không phải hỏng lượt.
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg")):
            self.assertEqual(cam._thu_nho(b"anh-goc", 768), b"anh-goc")

    def test_thu_nho_ffmpeg_loi_thi_tra_nguyen_ban(self) -> None:
        with mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout=b"", stderr=b"loi")):
            self.assertEqual(cam._thu_nho(b"anh-goc", 768), b"anh-goc")


@pytest.mark.pure
class KichThuocJpegTests(unittest.TestCase):
    """Đọc kích thước từ header, và KHÔNG mã hoá lại ảnh đã đủ nhỏ.

    Đo trên camera thật: khung luồng phụ 640×480 nặng 27 KB, cho qua ffmpeg với
    đích 1600 px thì ra 69 KB — to gấp hai rưỡi mà chất lượng kém đi.
    """

    def _jpeg(self, w: int, h: int) -> bytes:
        import io

        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (w, h), (10, 20, 30)).save(b, format="JPEG")
        return b.getvalue()

    def test_doc_dung_kich_thuoc(self) -> None:
        self.assertEqual(cam.kich_thuoc_jpeg(self._jpeg(640, 480)), (640, 480))
        self.assertEqual(cam.kich_thuoc_jpeg(self._jpeg(1920, 1080)), (1920, 1080))

    def test_khong_phai_jpeg_thi_tra_none(self) -> None:
        self.assertIsNone(cam.kich_thuoc_jpeg(b"\x89PNG\r\n\x1a\n"))
        self.assertIsNone(cam.kich_thuoc_jpeg(b""))
        self.assertIsNone(cam.kich_thuoc_jpeg(b"\xff\xd8ngan"))

    def test_anh_da_du_nho_thi_giu_nguyen_byte(self) -> None:
        goc = self._jpeg(640, 480)
        with mock.patch("subprocess.run") as ff:
            self.assertEqual(cam._thu_nho(goc, cam.CANH_GUI), goc)
        ff.assert_not_called()      # không gọi ffmpeg = không phình, không mất chất

    def test_anh_to_hon_dich_thi_van_thu_nho(self) -> None:
        goc = self._jpeg(1920, 1080)
        with mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout=b"nho")) as ff:
            self.assertEqual(cam._thu_nho(goc, cam.CANH_AI), b"nho")
        ff.assert_called_once()

    def test_khong_doc_duoc_kich_thuoc_thi_van_thu_nho(self) -> None:
        # Không biết to hay nhỏ thì cứ thu — an toàn hơn là gửi ảnh khổng lồ.
        with mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout=b"nho")) as ff:
            self.assertEqual(cam._thu_nho(b"khong-phai-jpeg", cam.CANH_AI), b"nho")
        ff.assert_called_once()


@pytest.mark.pure
class SoHongTests(unittest.TestCase):
    """Bản ghi lạ lọt vào config (sửa tay, card lỗi) phải báo đúng chỗ sai."""

    def test_kieu_la_bao_ro_thay_vi_do_loi_sang_ffmpeg(self) -> None:
        with _So({"Bếp": {"kind": "onvif", "url": ""}}), \
             self.assertRaises(cam.LoiCamera) as e:
            cam.chup("Bếp")
        loi = str(e.exception)
        self.assertIn("onvif", loi)
        self.assertNotIn("ffmpeg", loi)

    def test_thieu_han_kieu_cung_bao_ro(self) -> None:
        with _So({"Bếp": {"url": "rtsp://x/y"}}), \
             self.assertRaises(cam.LoiCamera) as e:
            cam.chup("Bếp")
        self.assertNotIn("ffmpeg", str(e.exception))


@pytest.mark.integration
@unittest.skipUnless(CO_FFMPEG, "máy này không có ffmpeg — chỉ kiểm được trong image/CI")
class ChupRtspTests(unittest.TestCase):
    """Chạm ffmpeg thật. Bỏ qua khi máy không có, KHÔNG đạt suông."""

    def test_khong_noi_duoc_thi_bao_loi_doc_duoc(self) -> None:
        # 127.0.0.1:1 chắc chắn không có ai nghe → ffmpeg thoát với lỗi, không treo.
        with _So({"Bếp": {"kind": "rtsp", "url": "rtsp://127.0.0.1:1/none"}}), \
             self.assertRaises(cam.LoiCamera) as e:
            cam.chup("Bếp", timeout=15)
        loi = str(e.exception)
        self.assertIn("ffmpeg", loi)
        self.assertNotIn("thiếu ffmpeg", loi)   # phải là lỗi KẾT NỐI, không phải thiếu lệnh

    def test_thu_nho_that_su_giam_kich_thuoc(self) -> None:
        import io

        from PIL import Image

        goc = io.BytesIO()
        Image.new("RGB", (1920, 1080), (30, 90, 160)).save(goc, format="JPEG")
        nho = cam._thu_nho(goc.getvalue(), cam.CANH_AI)
        w, h = Image.open(io.BytesIO(nho)).size
        self.assertEqual(max(w, h), cam.CANH_AI)
        self.assertLess(len(nho), len(goc.getvalue()))


if __name__ == "__main__":
    unittest.main()


# ── Capability xem_camera ────────────────────────────────────────────────────

@pytest.mark.pure
class XemCameraTests(unittest.TestCase):
    """Handler agent: quyền, đường lỗi, và ghép ảnh với câu trả lời."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        from services.agent import capabilities as C

        self.C = C
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        anh = mock.patch.object(type(config), "images_dir",
                                mock.PropertyMock(return_value=Path(self.tmp.name)))
        anh.start()
        self.addCleanup(anh.stop)

        url = mock.patch.object(C, "gateway_base_url", lambda: "http://cong:5000")
        url.start()
        self.addCleanup(url.stop)

    def _goi(self, args=None, *, admin=True):
        return self.C.CAPABILITIES["xem_camera"].handler(args or {}, {"is_admin": admin})

    def test_khong_tick_nhom_camera_thi_tool_khong_ton_tai(self) -> None:
        """Ai được xem chốt ở BỘ LỌC CHỨC NĂNG, không phải trong handler.

        Thread chưa cấu hình bộ lọc (`allow=None`) cũng KHÔNG có camera: nhóm
        `camera` nằm trong `_NHOM_PHAI_TICH`, phải tích tường minh mới có.
        """
        ten = [t["function"]["name"] for t in self.C.tools_schema(None)]
        self.assertNotIn("xem_camera", ten)
        ten = [t["function"]["name"] for t in self.C.tools_schema({"web", "image"})]
        self.assertNotIn("xem_camera", ten)
        ten = [t["function"]["name"] for t in self.C.tools_schema({"camera"})]
        self.assertIn("xem_camera", ten)

    def test_persona_khong_khoe_camera_khi_chua_tick(self) -> None:
        # Persona khoe được mà tool bị ẩn thì model BỊA ảnh camera.
        self.assertNotIn("camera nhà", self.C.persona_list(None).lower())
        self.assertIn("camera nhà", self.C.persona_list({"camera"}).lower())

    def test_gui_anh_khi_khong_hoi_gi(self) -> None:
        with mock.patch.object(cam, "chup", return_value=("Sân trước", b"gui")), \
             mock.patch.object(cam, "chup_hai_co") as hai, \
             mock.patch.object(self.C, "_hoi_ve_anh") as vision:
            ra = self._goi({"camera": "sân"})
        vision.assert_not_called()          # không hỏi thì đừng đốt lượt gọi model
        hai.assert_not_called()             # cũng đừng bấm luồng phụ làm gì
        self.assertIn("Sân trước", ra["text"])
        self.assertTrue(ra["image_url"].startswith("http://cong:5000/images/"))

    def test_anh_duoc_ghi_that_ra_thu_vien(self) -> None:
        from pathlib import Path
        with mock.patch.object(cam, "chup", return_value=("Sân", b"noi-dung-anh")):
            ra = self._goi()
        rel = ra["image_url"].split("/images/", 1)[1]
        self.assertEqual((Path(self.tmp.name) / rel).read_bytes(), b"noi-dung-anh")

    def test_ten_camera_co_dau_gach_cheo_khong_ghi_lech_thu_muc(self) -> None:
        # Tên do người dùng đặt: 'Cổng ngoài / để xe', '../../etc' đều phải ra
        # MỘT tên tệp phẳng nằm trong thư mục ảnh, không đục ra ngoài.
        from pathlib import Path
        for ten_cam in ("Cổng ngoài / để xe", "../../etc/passwd", "!!!"):
            with mock.patch.object(cam, "chup", return_value=(ten_cam, b"anh")):
                ra = self._goi()
            rel = ra["image_url"].split("/images/", 1)[1]
            tep = Path(self.tmp.name) / rel
            self.assertTrue(tep.is_file(), f"{ten_cam} → {rel}")
            self.assertEqual(tep.parent.parent.parent.parent, Path(self.tmp.name))

    def test_co_hoi_thi_kem_cau_tra_loi(self) -> None:
        with mock.patch.object(cam, "chup_hai_co",
                               return_value=("Sân", b"gui", b"anh-nho")), \
             mock.patch.object(self.C, "_hoi_ve_anh",
                               return_value="Không có ai.") as vision:
            ra = self._goi({"camera": "sân", "hoi": "có ai không"})
        # Ảnh đưa cho model phải là bản NHỎ, không phải bản gửi người xem.
        self.assertEqual(vision.call_args.args[0], b"anh-nho")
        self.assertIn("Không có ai.", ra["text"])
        self.assertIn("image_url", ra)

    def test_vision_hong_van_gui_duoc_anh(self) -> None:
        with mock.patch.object(cam, "chup_hai_co",
                               return_value=("Sân", b"gui", b"ai")), \
             mock.patch.object(self.C, "_hoi_ve_anh", return_value=""):
            ra = self._goi({"hoi": "có ai không"})
        self.assertIn("image_url", ra)      # nhánh vision chết không được nuốt ảnh

    def test_ten_map_mo_thi_thuat_lai_de_hoi_lai(self) -> None:
        with mock.patch.object(cam, "chup",
                               side_effect=cam.LoiCamera("Chưa rõ camera nào. Đang có: Bếp, Sân")):
            ra = self._goi({"camera": "cam"})
        self.assertNotIn("image_url", ra)
        self.assertIn("Đang có: Bếp, Sân", ra["text"])

    def test_loi_ngoai_du_tinh_khong_lam_vo_luot(self) -> None:
        with mock.patch.object(cam, "chup", side_effect=RuntimeError("bùm")):
            ra = self._goi()
        self.assertIn("bùm", ra["text"])
        self.assertNotIn("image_url", ra)


@pytest.mark.pure
class HoiVeAnhTests(unittest.TestCase):
    def test_gui_anh_dang_data_url_va_tra_ve_chu(self) -> None:
        from services.agent import capabilities as C
        with mock.patch("services.agent.runtime.call_model",
                        return_value={"choices": [{"message": {"content": " Có một người. "}}]}) as g, \
             mock.patch("services.agent.branches.branch_model", return_value="AI vision"):
            ra = C._hoi_ve_anh(b"\xff\xd8anh", "có ai không")
        self.assertEqual(ra, "Có một người.")
        phan = g.call_args.args[1][0]["content"]
        self.assertTrue(phan[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertIn("có ai không", phan[0]["text"])

    def test_model_bao_loi_thi_tra_rong(self) -> None:
        from services.agent import capabilities as C
        with mock.patch("services.agent.runtime.call_model",
                        return_value={"error": "hết quota"}), \
             mock.patch("services.agent.branches.branch_model", return_value="AI vision"):
            self.assertEqual(C._hoi_ve_anh(b"x", "có ai không"), "")

    def test_goi_model_no_ra_thi_tra_rong(self) -> None:
        from services.agent import capabilities as C
        with mock.patch("services.agent.runtime.call_model", side_effect=OSError("đứt mạng")), \
             mock.patch("services.agent.branches.branch_model", return_value="AI vision"):
            self.assertEqual(C._hoi_ve_anh(b"x", "có ai không"), "")


@pytest.mark.pure
class NhomCameraTests(unittest.TestCase):
    """Nhóm `camera` trong bộ lọc thread: phải TÍCH mới có, và không tự bật."""

    def test_ban_ghi_loc_cu_khong_tu_moc_them_camera(self) -> None:
        # Bộ lọc lưu trước khi có nhóm camera. Luật chung là nhóm sinh sau được
        # cộng thêm (xem test_loc_thread_nhom_moi), nhưng camera nhìn vào TRONG
        # NHÀ nên phải đứng ngoài luật đó — một bản cập nhật không được tự cấp
        # quyền chụp ảnh trong nhà cho thread cũ.
        from services.agent import capabilities as caps

        cfg = {"thread_filters": {"t1": ["web", "image"]},
               "thread_filter_meta": {"t1": {"known": ["web", "image"]}}}
        with mock.patch("services.config.config.get", return_value=cfg):
            self.assertNotIn("camera", caps.allowed_groups_for("t1"))

    def test_da_tick_thi_giu_nguyen(self) -> None:
        from services.agent import capabilities as caps

        cfg = {"thread_filters": {"t1": ["web", "camera"]},
               "thread_filter_meta": {"t1": {"known": ["web", "camera"]}}}
        with mock.patch("services.config.config.get", return_value=cfg):
            self.assertIn("camera", caps.allowed_groups_for("t1"))


# ── Khoá phiên và API ────────────────────────────────────────────────────────

@pytest.mark.pure
class KhoaPhienTests(unittest.TestCase):
    """Khoá tích trong UI phải trùng đúng chuỗi orchestrator dùng lúc chạy."""

    def test_dung_dang_tung_kenh(self) -> None:
        from services.channel_contacts import session_key
        self.assertEqual(session_key("ha", "", ""), "ha")
        self.assertEqual(session_key("tg", "12345", ""), "12345")
        self.assertEqual(session_key("tg", "-100", "7"), "-100:u7")
        self.assertEqual(session_key("zalo", "999", ""), "zalo_999")
        self.assertEqual(session_key("zalo", "999", "7"), "zalo_999:u7")
        self.assertEqual(session_key("zalop", "888", ""), "zalop_888")
        self.assertEqual(session_key("zalop", "888", "7"), "zalop_888:u7")
        self.assertEqual(session_key("zalo", "", ""), "")

    def test_khop_dang_zalo_bot_dung_luc_chay(self) -> None:
        # Đối chiếu với chuỗi services/zalo_bot.py dựng tại chỗ (`zalo_<chat>:u<uid>`).
        from services.channel_contacts import session_key
        chat_id, user_id = "555", "42"
        self.assertEqual(session_key("zalo", chat_id, user_id), f"zalo_{chat_id}:u{user_id}")
        self.assertEqual(session_key("zalo", chat_id), f"zalo_{chat_id}")


@pytest.mark.pure
class ApiCameraTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import camera as api_camera

        app = FastAPI()
        app.include_router(api_camera.create_router())
        bo_qua = mock.patch("api.camera.require_admin", lambda *a, **k: None)
        bo_qua.start()
        self.addCleanup(bo_qua.stop)
        self.client = TestClient(app)

    def test_test_thieu_ten(self) -> None:
        d = self.client.post("/api/camera/test", json={}).json()
        self.assertFalse(d["ok"])

    def test_test_tra_anh_xem_truoc(self) -> None:
        with mock.patch.object(cam, "chup", return_value=("Sân", b"\xff\xd8xyz")):
            d = self.client.post("/api/camera/test", json={"ten": "sân"}).json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["ten"], "Sân")
        self.assertEqual(d["bytes"], 5)
        self.assertTrue(d["anh"].startswith("data:image/jpeg;base64,"))

    def test_test_loi_camera_tra_cau_doc_duoc(self) -> None:
        with mock.patch.object(cam, "chup",
                               side_effect=cam.LoiCamera("go2rtc không có luồng tên 'san'")):
            d = self.client.post("/api/camera/test", json={"ten": "sân"}).json()
        self.assertFalse(d["ok"])
        self.assertIn("go2rtc", d["error"])


# ── Hai luồng: gửi lấy luồng chính, AI đọc luồng phụ ─────────────────────────

HAI_LUONG = {"kind": "rtsp", "url": "rtsp://x/main", "url_ai": "rtsp://x/sub"}


@pytest.mark.pure
class HaiLuongTests(unittest.TestCase):
    def test_khai_luong_phu_cho_ca_hai_kieu(self) -> None:
        with _So({}):
            cam.them("Sân", "rtsp", url="rtsp://x/main", url_ai="rtsp://x/sub")
            cam.them("Bếp", "go2rtc", base="http://x:1984", src="bep", src_ai="bep_sub")
            so = {c["name"]: c for c in cam.danh_sach()}
        self.assertTrue(cam.co_luong_phu(so["Sân"]))
        self.assertTrue(cam.co_luong_phu(so["Bếp"]))

    def test_khong_khai_thi_khong_co_luong_phu(self) -> None:
        with _So({}):
            cam.them("Sân", "rtsp", url="rtsp://x/main")
            [c] = cam.danh_sach()
        self.assertFalse(cam.co_luong_phu(c))

    def test_luong_phu_sai_giao_thuc_bi_tu_choi(self) -> None:
        with _So({}), self.assertRaises(cam.LoiCamera):
            cam.them("Sân", "rtsp", url="rtsp://x/main", url_ai="http://x/sub")

    def test_mat_khau_luong_phu_cung_bi_che(self) -> None:
        with _So({"Sân": {"kind": "rtsp", "url": "rtsp://a:BiMat@x/main",
                          "url_ai": "rtsp://a:BiMat@x/sub"}}):
            [c] = cam.danh_sach()
        self.assertNotIn("BiMat", c["url"])
        self.assertNotIn("BiMat", c["url_ai"])

    def test_chup_gui_dung_luong_chinh_chup_ai_dung_luong_phu(self) -> None:
        with _So({"Sân": dict(HAI_LUONG)}), \
             mock.patch.object(cam, "_chup_rtsp",
                               side_effect=lambda c, t: c["url"].encode()) as boc, \
             mock.patch.object(cam, "_thu_nho", lambda b, c: b):
            _, gui = cam.chup("Sân")
            _, ai = cam.chup("Sân", cho_ai=True)
        self.assertEqual(gui, b"rtsp://x/main")
        self.assertEqual(ai, b"rtsp://x/sub")
        self.assertEqual(boc.call_count, 2)

    def test_chup_hai_co_bam_ca_hai_luong(self) -> None:
        with _So({"Sân": dict(HAI_LUONG)}), \
             mock.patch.object(cam, "_chup_rtsp",
                               side_effect=lambda c, t: c["url"].encode()), \
             mock.patch.object(cam, "_thu_nho", lambda b, c: b):
            ten, gui, ai = cam.chup_hai_co("Sân")
        self.assertEqual((ten, gui, ai), ("Sân", b"rtsp://x/main", b"rtsp://x/sub"))

    def test_rtsp_bam_NOI_DUOI_vi_camera_khong_chiu_hai_phien(self) -> None:
        # Đo trên camera Dahua thật: hai phiên RTSP song song hỏng CẢ HAI (hết
        # 25 giây chờ), nối đuôi thì 8,6 giây là xong.
        import time
        with _So({"Sân": dict(HAI_LUONG)}), \
             mock.patch.object(cam, "_chup_rtsp",
                               side_effect=lambda c, t: (time.sleep(0.25), b"x")[1]), \
             mock.patch.object(cam, "_thu_nho", lambda b, c: b):
            t0 = time.time()
            cam.chup_hai_co("Sân")
            mat = time.time() - t0
        self.assertGreater(mat, 0.4, f"mất {mat:.2f}s — RTSP đang bấm song song, sẽ nghẽn camera")

    def test_go2rtc_van_bam_song_song(self) -> None:
        # go2rtc giữ sẵn kết nối tới camera rồi phục vụ nhiều khách, nên hai lời
        # gọi HTTP cùng lúc không phiền camera.
        import time
        cam_go = {"kind": "go2rtc", "base": "http://x:1984", "src": "s", "src_ai": "s_sub"}
        with _So({"Sân": dict(cam_go)}), \
             mock.patch.object(cam, "_chup_go2rtc",
                               side_effect=lambda c, t: (time.sleep(0.25), b"x")[1]), \
             mock.patch.object(cam, "_thu_nho", lambda b, c: b):
            t0 = time.time()
            cam.chup_hai_co("Sân")
            mat = time.time() - t0
        self.assertLess(mat, 0.45, f"mất {mat:.2f}s — go2rtc đang bấm nối đuôi, chậm gấp đôi")

    def test_luong_phu_hong_thi_dung_luong_chinh_cho_AI(self) -> None:
        # Luồng phụ chết không được làm hỏng cả lượt: vẫn trả lời được, chỉ tốn hơn.
        def boc(c, t):
            if c["url"].endswith("/sub"):
                raise cam.LoiCamera("camera không trả lời")
            return b"chinh"
        with _So({"Sân": dict(HAI_LUONG)}), \
             mock.patch.object(cam, "_chup_rtsp", side_effect=boc), \
             mock.patch.object(cam, "_thu_nho", lambda b, c: b):
            _, gui, ai = cam.chup_hai_co("Sân")
        self.assertEqual((gui, ai), (b"chinh", b"chinh"))

    def test_luong_chinh_hong_thi_bao_loi(self) -> None:
        with _So({"Sân": dict(HAI_LUONG)}), \
             mock.patch.object(cam, "_chup_rtsp",
                               side_effect=cam.LoiCamera("camera không trả lời")), \
             self.assertRaises(cam.LoiCamera):
            cam.chup_hai_co("Sân")

    def test_khong_co_luong_phu_thi_boc_MOT_lan(self) -> None:
        with _So({"Sân": {"kind": "rtsp", "url": "rtsp://x/main"}}), \
             mock.patch.object(cam, "_chup_rtsp", return_value=b"anh") as boc, \
             mock.patch.object(cam, "_thu_nho", lambda b, c: b):
            _, gui, ai = cam.chup_hai_co("Sân")
        boc.assert_called_once()            # một khung, hai cỡ — đừng gọi camera hai lượt
        self.assertEqual((gui, ai), (b"anh", b"anh"))

    def test_go2rtc_doi_dung_tham_so_src(self) -> None:
        cam_go = {"kind": "go2rtc", "base": "http://x:1984", "src": "san", "src_ai": "san_sub"}
        with _So({"Sân": dict(cam_go)}), \
             mock.patch.object(cam, "_chup_go2rtc",
                               side_effect=lambda c, t: c["src"].encode()), \
             mock.patch.object(cam, "_thu_nho", lambda b, c: b):
            _, gui, ai = cam.chup_hai_co("Sân")
        self.assertEqual((gui, ai), (b"san", b"san_sub"))


@pytest.mark.pure
class UrlCoThamSoTests(unittest.TestCase):
    """URL kiểu Dahua có ``?channel=1&subtype=0`` phải đi qua nguyên vẹn.

    Đây là dạng URL phổ biến nhất ở VN (Dahua, Amcrest, KBVision), và cũng là
    dạng dễ bị một hàm che mật khẩu viết ẩu cắt mất phần sau dấu hỏi.
    """

    DAHUA = "rtsp://CAM_USER:CAM_PASS_DA_XOA@10.0.0.9/cam/realmonitor?channel=1&subtype=0"

    def test_che_mat_khau_giu_nguyen_duong_dan_va_tham_so(self) -> None:
        ra = cam.che_bi_mat(self.DAHUA)
        self.assertIn("/cam/realmonitor?channel=1&subtype=0", ra)
        self.assertNotIn("CAM_PASS_DA_XOA", ra)

    def test_mat_khau_co_dau_a_coi_gõ_thang_van_tach_dung_host(self) -> None:
        # Người dùng hay gõ thẳng '@' thay vì '%40'. urlsplit lấy '@' CUỐI làm
        # ranh giới nên vẫn ra đúng host — ffmpeg cũng vậy (đã thử camera thật).
        ra = cam.che_bi_mat("rtsp://CAM_USER:CAM_PASS_DA_XOA@0610@10.0.0.9/cam/realmonitor?channel=1")
        self.assertIn("10.0.0.9", ra)
        self.assertIn("channel=1", ra)
        self.assertNotIn("CAM_PASS_DA_XOA", ra)

    def test_url_giu_nguyen_khi_dua_cho_ffmpeg(self) -> None:
        # Truyền dạng danh sách nên '&' không bị shell hiểu thành chạy nền.
        with _So({"Sân": {"kind": "rtsp", "url": self.DAHUA}}), \
             mock.patch("subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout=b"\xff\xd8x")) as sp:
            cam.chup_tho("Sân")
        lenh = sp.call_args.args[0]
        self.assertIn(self.DAHUA, lenh)
        self.assertIn("-rtsp_transport", lenh)

    def test_luong_phu_dahua_chi_khac_subtype(self) -> None:
        with _So({}):
            cam.them("Sân", "rtsp", url=self.DAHUA,
                     url_ai=self.DAHUA.replace("subtype=0", "subtype=1"))
            [c] = cam.danh_sach(kem_bi_mat=True)
        self.assertTrue(cam.co_luong_phu(c))
        self.assertTrue(c["url_ai"].endswith("subtype=1"))
