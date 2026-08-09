"""Thân yêu cầu của đường Flow REST phải đúng từng trường.

VÌ SAO CẦN. Đường REST (`captcha-solver/src/solvers/flow_rest.py`) gửi thẳng
JSON cho Google thay vì bấm giao diện. Mọi thứ trước đây "bấm sai thì thấy ngay
trên màn hình" nay nằm hết trong một dict — sai một tên trường thì Google trả
400 INVALID_ARGUMENT không nói trường nào, hoặc tệ hơn là nhận và dựng sai loại.

ĐO THẬT 09/08/2026 (tài khoản google-benbap115). Tên model bị kiểm TRƯỚC cửa
reCAPTCHA nên đo được trực tiếp từng tên mà không tốn tín dụng:

    ẢNH    GEM_PIX_2 / NARWHAL / HARBOR_SEAL   hợp lệ
           NANO_BANANA_PRO / IMAGEN_4          400 — KHÔNG tồn tại
           GEM_PIX / IMAGEN_3_5                404 — tài khoản không có

    VIDEO  abra_t2v_5s / abra_r2v_5s           404 — Omni Flash chỉ có 4/6/8s
           veo_3_1_r2v / veo_3_1_r2v_fast      404 — thành phần chỉ có Lite

`NANO_BANANA_PRO` lại đang là model mặc định của `flow/auto` và `flow/banana-pro`
ở `services/image_providers/flow_google.py`, và là giá trị dự phòng cuối cùng
của `_resolve_model()`. Đường DOM che mất lỗi này vì nó chỉ dùng chuỗi đó làm
khoá tra NHÃN dropdown. Ngày ai đó nối đường REST vào adapter cũ, mặc định đó sẽ
đi thẳng xuống Google và mọi lượt tạo ảnh 400. Test đầu tiên ở đây chốt việc
chặn phải xảy ra tại chỗ, kèm thông báo nêu tên đúng.

Phần còn lại chốt bốn chế độ video, vì chúng khác nhau ở đúng những chi tiết dễ
lẫn: endpoint nào, ảnh nằm ở trường nào, và chế độ ảnh-đầu-và-cuối đòi CẢ HAI
ảnh (thiếu ảnh cuối là 400, không nói thiếu trường nào).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]


def _nap_module():
    """Nạp flow_rest.py theo đường dẫn.

    `captcha-solver` có dấu gạch ngang nên không phải package import được từ gốc
    kho; các test khác chạm vào bộ lái cũng đọc theo đường dẫn (xem
    `test_flow_khong_tao_nham_loai.py`). Import tương đối trong file đều nằm
    TRONG thân hàm nên nạp module không kéo theo browser_pool.
    """
    duong = GOC / "captcha-solver/src/solvers/flow_rest.py"
    spec = importlib.util.spec_from_file_location("flow_rest_kiem_thu", duong)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FR = _nap_module()


class ChanModelDaDoLaSai(unittest.TestCase):
    def test_hai_ten_da_do_la_sai_deu_bi_chan(self):
        for ten in FR.MODEL_ANH_DA_DO_LA_SAI:
            with self.subTest(ten=ten):
                with self.assertRaises(ValueError) as ngu_canh:
                    FR.kiem_model_anh(ten)
                loi = str(ngu_canh.exception)
                # Thông báo phải nêu tên dùng được, nếu không người đọc lại đi
                # thử tiếp một tên bịa khác.
                self.assertIn("NARWHAL", loi)
                self.assertIn(ten, loi)

    def test_chan_ca_khi_viet_thuong(self):
        with self.assertRaises(ValueError):
            FR.kiem_model_anh("nano_banana_pro")

    def test_ten_hop_le_di_qua(self):
        self.assertEqual(FR.kiem_model_anh("NARWHAL"), "NARWHAL")
        self.assertEqual(FR.kiem_model_anh("HARBOR_SEAL"), "HARBOR_SEAL")

    def test_ten_la_van_di_qua(self):
        """Flow ra model mới liên tục; chặn cứng sẽ khoá mất model mới."""
        self.assertEqual(FR.kiem_model_anh("model_moi_nao_do"), "MODEL_MOI_NAO_DO")

    def test_rong_thi_ve_ten_da_do_la_dung(self):
        self.assertIn(FR.kiem_model_anh(""), FR.MODEL_ANH_DA_DO_LA_DUNG)

    def test_tao_anh_khong_dung_ten_sai_lam_mac_dinh(self):
        """Mặc định của endpoint không được là một tên đã đo là hỏng."""
        nguon = (GOC / "captcha-solver/src/main.py").read_text(encoding="utf-8")
        dau = nguon.index("class FlowRestImageReq")
        than = nguon[dau:dau + 900]
        for ten in FR.MODEL_ANH_DA_DO_LA_SAI:
            self.assertNotIn(f'model: str = "{ten}"', than)


class QuanLyModelKhongDuocChaoTenChet(unittest.TestCase):
    """Bảng bí danh phía dịch vụ không được trỏ vào tên API đã đo là không có.

    Đây chính là lớp lỗi vừa xảy ra: `flow/banana-pro` và `flow/auto` trỏ vào
    `NANO_BANANA_PRO` suốt một thời gian dài mà không ai thấy, vì đường DOM chỉ
    dùng chuỗi đó làm khoá tra NHÃN dropdown chứ không bao giờ gửi xuống API.
    Chỉ tới khi đường REST gửi thẳng mới lộ ra là tên đó chưa từng tồn tại.

    Test này bắt tay đôi giữa hai file: cái đo được (flow_rest) và cái đang chào
    ra ngoài (Quản lý Model).
    """

    def _alias(self) -> dict:
        import ast
        nguon = (GOC / "services/image_providers/flow_google.py").read_text(encoding="utf-8")
        for nut in ast.walk(ast.parse(nguon)):
            if (isinstance(nut, ast.Assign) and isinstance(nut.value, ast.Dict)
                    and any(isinstance(t, ast.Name) and t.id == "_MODEL_ALIASES"
                            for t in nut.targets)):
                return ast.literal_eval(nut.value)
        self.fail("không đọc được _MODEL_ALIASES")

    def test_khong_bi_danh_nao_tro_vao_ten_da_do_la_sai(self):
        chet = set(FR.MODEL_ANH_DA_DO_LA_SAI)
        pham = sorted({v for v in self._alias().values() if v in chet})
        self.assertEqual(pham, [], f"Quản lý Model đang chào tên API không tồn tại: {pham}")

    def test_model_manh_nhat_van_la_ten_con_song(self):
        """`auto` là thứ người dùng nhận khi không chọn gì — sai là hỏng mặc định."""
        self.assertIn(self._alias().get("auto"), FR.MODEL_ANH_DA_DO_LA_DUNG)


class MaLoiKhongDuocLaThanhCong(unittest.TestCase):
    """`LoiFlowRest` không bao giờ được mang mã 2xx.

    `main.py::_loi_flow_rest` chuyển thẳng `.status` thành `HTTPException`, nên
    một lỗi mang mã 200 sẽ trả về HTTP 200 kèm thân `detail` — bên gọi đọc thấy
    thành công trong khi thật ra hỏng. Ba chỗ "HTTP 200 nhưng thân đáp vô dụng"
    (upload không có mediaId, đáp thiếu media, đáp thiếu Generation ID) từng
    dùng mã 200 đúng theo nghĩa đen của tầng HTTP, và đó là cái bẫy.
    """

    def test_moi_ma_nem_ra_deu_tu_400_tro_len(self):
        import ast
        nguon = (GOC / "captcha-solver/src/solvers/flow_rest.py").read_text(encoding="utf-8")
        ma_so: list[int] = []
        for nut in ast.walk(ast.parse(nguon)):
            if not isinstance(nut, ast.Call):
                continue
            ten = getattr(nut.func, "id", None) or getattr(nut.func, "attr", None)
            if ten != "LoiFlowRest" or not nut.args:
                continue
            dau = nut.args[0]
            if isinstance(dau, ast.Constant) and isinstance(dau.value, int):
                ma_so.append(dau.value)
        self.assertTrue(ma_so, "không tìm thấy chỗ nào ném LoiFlowRest với mã cố định")
        for ma in ma_so:
            self.assertGreaterEqual(ma, 400, f"mã {ma} sẽ biến lỗi thành thành công")


class ThanTaoAnh(unittest.TestCase):
    def _than(self, **kw):
        goc = dict(project_id="p1", prompt="ấm trà đỏ", model="NARWHAL",
                   session_id="111", batch_id="b1", seeds=[7, 8, 9])
        goc.update(kw)
        return FR.than_tao_anh(**goc)

    def test_count_nhan_ban_request_moi_ban_mot_seed(self):
        than = self._than(count=3)
        self.assertEqual(len(than["requests"]), 3)
        self.assertEqual([r["seed"] for r in than["requests"]], [7, 8, 9])

    def test_client_context_co_o_ca_hai_tang(self):
        than = self._than()
        self.assertEqual(than["clientContext"]["projectId"], "p1")
        self.assertEqual(than["requests"][0]["clientContext"]["projectId"], "p1")

    def test_tier_anh_la_mot_khong_phai_hai(self):
        """Ảnh dùng PAYGATE_TIER_ONE, video dùng TIER_TWO — app gửi khác nhau."""
        self.assertEqual(self._than()["clientContext"]["userPaygateTier"],
                         "PAYGATE_TIER_ONE")

    def test_recaptcha_gan_vao_ca_hai_tang(self):
        than = self._than(recaptcha="TOK")
        for ctx in (than["clientContext"], than["requests"][0]["clientContext"]):
            self.assertEqual(ctx["recaptchaContext"]["token"], "TOK")
            self.assertEqual(ctx["recaptchaContext"]["applicationType"],
                             "RECAPTCHA_APPLICATION_TYPE_WEB")

    def test_khong_co_recaptcha_thi_khong_co_truong_thua(self):
        than = self._than()
        self.assertNotIn("recaptchaContext", than["clientContext"])

    def test_anh_tham_chieu_thanh_image_inputs(self):
        than = self._than(media_ids=["m1", "m2"])
        self.assertEqual(than["requests"][0]["imageInputs"], [
            {"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": "m1"},
            {"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": "m2"},
        ])

    def test_ty_le_doi_sang_hang_so_cua_flow(self):
        self.assertEqual(self._than(aspect_ratio="1:1")["requests"][0]["imageAspectRatio"],
                         "IMAGE_ASPECT_RATIO_SQUARE")

    def test_ty_le_la_giu_nguyen(self):
        """Cho phép truyền thẳng hằng số Flow khi bảng chưa kịp cập nhật."""
        than = self._than(aspect_ratio="IMAGE_ASPECT_RATIO_MOI")
        self.assertEqual(than["requests"][0]["imageAspectRatio"], "IMAGE_ASPECT_RATIO_MOI")

    def test_model_sai_nem_loi_truoc_khi_dung_than(self):
        with self.assertRaises(ValueError):
            self._than(model="NANO_BANANA_PRO")


class ThanTaoVideo(unittest.TestCase):
    ANH = [{"name": "Lan.png", "mediaId": "m1"}, {"name": "Hoa.png", "mediaId": "m2"}]

    def _than(self, che_do, **kw):
        goc = dict(project_id="p1", prompt="Lan đang chạy", che_do=che_do,
                   model_key="k", session_id=";111", batch_id="b1", seeds=[7])
        goc.update(kw)
        return FR.than_tao_video(**goc)

    def test_bon_che_do_deu_co_endpoint(self):
        self.assertEqual(set(FR.CHE_DO_VIDEO), {
            "text_to_video", "image_start", "image_start_end", "component"})

    def test_che_do_la_bi_chan(self):
        with self.assertRaises(ValueError):
            self._than("image_to_video")

    def test_khung_chung(self):
        than = self._than("text_to_video")
        self.assertIs(than["useV2ModelConfig"], True)
        self.assertEqual(than["mediaGenerationContext"]["audioFailurePreference"],
                         "RETURN_SILENCED_VIDEOS")
        self.assertEqual(than["clientContext"]["userPaygateTier"], "PAYGATE_TIER_TWO")

    def test_text_to_video_khong_gan_anh(self):
        than = self._than("text_to_video", anh=self.ANH)
        yc = than["requests"][0]
        self.assertNotIn("startImage", yc)
        self.assertNotIn("referenceImages", yc)

    def test_image_start_khong_kem_crop(self):
        """Chỉ chế độ ảnh-đầu-và-cuối mới gửi cropCoordinates."""
        yc = self._than("image_start", anh=self.ANH)["requests"][0]
        self.assertEqual(yc["startImage"], {"mediaId": "m1"})
        self.assertNotIn("endImage", yc)

    def test_image_start_end_co_crop_phu_tron_khung(self):
        yc = self._than("image_start_end", anh=self.ANH)["requests"][0]
        for khoa in ("startImage", "endImage"):
            self.assertEqual(yc[khoa]["cropCoordinates"],
                             {"top": 0, "left": 0, "bottom": 1, "right": 1})
        self.assertEqual(yc["startImage"]["mediaId"], "m1")
        self.assertEqual(yc["endImage"]["mediaId"], "m2")

    def test_component_gan_reference_images(self):
        yc = self._than("component", anh=self.ANH)["requests"][0]
        self.assertEqual(yc["referenceImages"], [
            {"mediaId": "m1", "imageUsageType": "IMAGE_USAGE_TYPE_ASSET"},
            {"mediaId": "m2", "imageUsageType": "IMAGE_USAGE_TYPE_ASSET"},
        ])

    def test_component_cat_prompt_theo_ten_tep(self):
        yc = self._than("component", anh=self.ANH)["requests"][0]
        phan = yc["textInput"]["structuredPrompt"]["parts"]
        self.assertEqual(phan[0]["reference"]["media"]["mediaId"], "m1")
        self.assertEqual(phan[0]["reference"]["media"]["handle"], "Lan.png")
        self.assertEqual(phan[1]["text"], " đang chạy")


class TachPromptTheoAnh(unittest.TestCase):
    def test_khong_ten_nao_khop_thi_giu_nguyen_prompt(self):
        phan = FR.tach_prompt_theo_anh("trời mưa", [{"name": "Lan.png", "mediaId": "m1"}])
        self.assertEqual(phan, [{"text": "trời mưa"}])

    def test_ten_dai_duoc_uu_tien(self):
        """'Lan Anh' không được để 'Lan' cắt mất."""
        anh = [{"name": "Lan.png", "mediaId": "m1"},
               {"name": "Lan Anh.png", "mediaId": "m2"}]
        phan = FR.tach_prompt_theo_anh("Lan Anh cười", anh)
        self.assertEqual(phan[0]["reference"]["media"]["mediaId"], "m2")

    def test_moi_media_chi_nhac_mot_lan(self):
        anh = [{"name": "Lan.png", "mediaId": "m1"}]
        phan = FR.tach_prompt_theo_anh("Lan gặp Lan", anh)
        so_ref = sum(1 for p in phan if "reference" in p)
        self.assertEqual(so_ref, 1)

    def test_giu_doan_van_ban_truoc_va_sau(self):
        anh = [{"name": "Lan.png", "mediaId": "m1"}]
        phan = FR.tach_prompt_theo_anh("cô Lan cười", anh)
        self.assertEqual(phan[0], {"text": "cô "})
        self.assertEqual(phan[-1], {"text": " cười"})

    def test_khong_phan_biet_hoa_thuong(self):
        anh = [{"name": "Lan.png", "mediaId": "m1"}]
        phan = FR.tach_prompt_theo_anh("LAN cười", anh)
        self.assertTrue(any("reference" in p for p in phan))

    def test_anh_thieu_media_id_bi_bo_qua(self):
        phan = FR.tach_prompt_theo_anh("Lan cười", [{"name": "Lan.png"}])
        self.assertEqual(phan, [{"text": "Lan cười"}])


class ChonModelVideo(unittest.TestCase):
    def test_hai_che_do_khung_hinh_bo_qua_nhan(self):
        """App gán cứng biến thể Lite ưu tiên thấp; chọn Quality cũng không đổi."""
        self.assertEqual(
            FR.chon_model_video("image_start", "Veo 3.1 - Quality", "8s"),
            "veo_3_1_i2v_lite_low_priority")
        self.assertEqual(
            FR.chon_model_video("image_start_end", "Veo 3.1 - Quality", "8s"),
            "veo_3_1_interpolation_lite_low_priority")

    def test_nhan_doi_thanh_khoa_t2v(self):
        self.assertEqual(FR.chon_model_video("text_to_video", "Veo 3.1 - Fast", None),
                         "veo_3_1_t2v_fast")

    def test_component_dung_bang_r2v(self):
        """Nhãn Fast/Quality ở chế độ thành phần trỏ vào khoá 404 — xem
        `DoThatTrenDuongVideo`. Chỉ Lite là dùng được."""
        self.assertEqual(FR.chon_model_video("component", "Veo 3.1 - Lite", None),
                         "veo_3_1_r2v_lite")

    def test_omni_flash_gan_so_giay(self):
        self.assertEqual(FR.chon_model_video("text_to_video", "Omni Flash", "8s"),
                         "abra_t2v_8s")

    def test_omni_flash_thieu_thoi_luong_thi_ve_mac_dinh_co_that(self):
        """Xem `DoThatTrenDuongVideo`: 5 giây trả 404, mặc định phải là 8."""
        self.assertEqual(FR.chon_model_video("text_to_video", "Omni Flash", None),
                         f"abra_t2v_{FR.GIAY_OMNI_FLASH_MAC_DINH}s")

    def test_nhan_la_ve_mac_dinh(self):
        self.assertEqual(FR.chon_model_video("text_to_video", "Model Nao Do", None),
                         "veo_3_1_t2v_lite_low_priority")


class DocDapTraLoi(unittest.TestCase):
    def test_uu_tien_primary_media_id(self):
        dap = {"workflows": [
            {"name": "w1", "metadata": {"primaryMediaId": "m1"}},
            {"name": "w2"},
        ]}
        self.assertEqual(FR.doc_gen_ids(dap), ["m1", "w2"])

    def test_bo_trung(self):
        dap = {"workflows": [{"metadata": {"primaryMediaId": "m1"}},
                             {"metadata": {"primaryMediaId": "m1"}}]}
        self.assertEqual(FR.doc_gen_ids(dap), ["m1"])

    def test_khong_co_workflow_thi_rong(self):
        self.assertEqual(FR.doc_gen_ids({}), [])

    def test_trang_thai_xong_lay_duoc_link(self):
        dap = {"media": [{
            "name": "m1", "videoUrl": "https://x/v.mp4",
            "mediaMetadata": {"mediaStatus": {"mediaGenerationStatus":
                                              "MEDIA_GENERATION_STATUS_SUCCESSFUL"}},
        }]}
        tt = FR.doc_trang_thai(dap, ["m1"])
        self.assertEqual(tt["m1"]["status"], "COMPLETED")
        self.assertEqual(tt["m1"]["url"], "https://x/v.mp4")

    def test_trang_thai_hong_giu_ly_do(self):
        dap = {"media": [{
            "name": "m1",
            "mediaMetadata": {"mediaStatus": {
                "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_FAILED",
                "failureReason": "vi phạm chính sách"}},
        }]}
        tt = FR.doc_trang_thai(dap, ["m1"])
        self.assertEqual(tt["m1"]["status"], "FAILED")
        self.assertEqual(tt["m1"]["reason"], "vi phạm chính sách")

    def test_chua_thay_trong_dap_thi_van_la_dang_chay(self):
        """Thiếu tin không được coi là hỏng, nếu không vòng chờ sẽ bỏ cuộc sớm."""
        tt = FR.doc_trang_thai({"media": []}, ["m1"])
        self.assertEqual(tt["m1"]["status"], "PROCESSING")


class DoThatTrenDuongVideo(unittest.TestCase):
    """Hai lỗi đo được ngày 09/08/2026, chốt lại để đừng ai gỡ ra.

    Khoá model hỏng ở đường VIDEO trả 404 chứ không phải 400 như đường ảnh, và
    thông báo là "Requested entity was not found" — không nói model nào sai.
    Endpoint …StartAndEndImage thiếu ảnh cuối thì trả 400 cũng không nói thiếu
    trường nào. Cả hai đều là loại lỗi tốn hàng giờ nếu phải lần từ thông báo.
    """

    ANH = [{"name": "a.png", "mediaId": "m1"}, {"name": "b.png", "mediaId": "m2"}]

    def _than(self, che_do, anh):
        return FR.than_tao_video(project_id="p1", prompt="x", che_do=che_do,
                                 model_key="k", anh=anh, seeds=[1],
                                 session_id=";1", batch_id="b1")

    def test_anh_dau_cuoi_thieu_anh_cuoi_thi_dung_ngay(self):
        with self.assertRaises(ValueError) as ngu_canh:
            self._than("image_start_end", self.ANH[:1])
        self.assertIn("cần 2 ảnh", str(ngu_canh.exception))

    def test_anh_dau_cuoi_du_hai_anh_thi_co_ca_hai_truong(self):
        yc = self._than("image_start_end", self.ANH)["requests"][0]
        self.assertEqual(yc["startImage"]["mediaId"], "m1")
        self.assertEqual(yc["endImage"]["mediaId"], "m2")

    def test_che_do_can_anh_ma_khong_co_anh_thi_dung(self):
        for che_do in ("image_start", "image_start_end", "component"):
            with self.subTest(che_do=che_do), self.assertRaises(ValueError):
                self._than(che_do, [])

    def test_text_to_video_khong_doi_anh(self):
        self.assertEqual(len(self._than("text_to_video", [])["requests"]), 1)

    def test_khoa_model_da_do_la_404_bi_chan_kem_ten_thay_the(self):
        # "Veo 3.1 - Quality" ở chế độ thành phần → veo_3_1_r2v → 404.
        with self.assertRaises(ValueError) as ngu_canh:
            FR.chon_model_video("component", "Veo 3.1 - Quality", None)
        loi = str(ngu_canh.exception)
        self.assertIn("veo_3_1_r2v", loi)
        self.assertIn("veo_3_1_r2v_lite", loi, "phải nêu khoá còn dùng được")

    def test_omni_flash_mac_dinh_khong_con_la_5_giay(self):
        """5 giây trả 404. Trước đây nó là mặc định khi thiếu thời lượng."""
        self.assertEqual(FR.chon_model_video("text_to_video", "Omni Flash", None),
                         "abra_t2v_8s")

    def test_omni_flash_thoi_luong_khong_co_that_bi_chan(self):
        with self.assertRaises(ValueError) as ngu_canh:
            FR.chon_model_video("text_to_video", "Omni Flash", "5s")
        self.assertIn("4s, 6s, 8s", str(ngu_canh.exception))

    def test_ba_thoi_luong_do_duoc_deu_di_qua(self):
        for giay in FR.GIAY_OMNI_FLASH:
            self.assertEqual(
                FR.chon_model_video("text_to_video", "Omni Flash", f"{giay}s"),
                f"abra_t2v_{giay}s")

    def test_moi_khoa_trong_bang_video_deu_khong_nam_trong_nhom_404(self):
        """Trừ nhánh r2v Fast/Quality — đó là hai khoá cố ý giữ để báo lỗi rõ."""
        for khoa in FR.MODEL_VIDEO_MAC_DINH.values():
            self.assertNotIn(khoa, FR.MODEL_VIDEO_DA_DO_LA_KHONG_CO)


class ChoXongRoiTra(unittest.TestCase):
    """Chế độ `wait` — chỉ dùng cho bên gọi không có hàng đợi.

    Đường DOM cũ giữ một request HTTP mở suốt 300 giây và đã đo được là chết
    đúng mốc đó với thông báo RỖNG. Đường REST sinh ra để bỏ cái bẫy đó, nên
    `wait` phải mặc định TẮT — bật mặc định là lặng lẽ dựng lại y nguyên nó.
    """

    def test_wait_mac_dinh_tat(self):
        nguon = (GOC / "captcha-solver/src/main.py").read_text(encoding="utf-8")
        dau = nguon.index("class FlowRestVideoReq")
        than = nguon[dau:nguon.index("class FlowRestStatusReq")]
        self.assertIn("wait: bool = False", than)

    def test_gom_ket_qua_dung_khoa_url(self):
        """`api/veo_video.py` đọc thẳng data[0]["url"] — đổi tên là hỏng ngầm."""
        xong, hong = FR.gom_ket_qua({
            "m1": {"status": "COMPLETED", "url": "https://x/1.mp4", "reason": None},
        })
        self.assertEqual(xong, [{"url": "https://x/1.mp4", "id": "m1"}])
        self.assertEqual(hong, [])

    def test_gom_ket_qua_tach_cai_hong_kem_ly_do(self):
        xong, hong = FR.gom_ket_qua({
            "m1": {"status": "COMPLETED", "url": "https://x/1.mp4", "reason": None},
            "m2": {"status": "FAILED", "url": None, "reason": "vi phạm chính sách"},
        })
        self.assertEqual(len(xong), 1)
        self.assertEqual(hong, ["m2: vi phạm chính sách"])

    def test_xong_nhung_thieu_url_thi_khong_tinh_la_xong(self):
        xong, _ = FR.gom_ket_qua({"m1": {"status": "COMPLETED", "url": None}})
        self.assertEqual(xong, [])

    def test_con_dang_chay(self):
        self.assertTrue(FR.con_dang_chay({"m1": {"status": "PROCESSING"}}))
        self.assertFalse(FR.con_dang_chay({"m1": {"status": "COMPLETED"},
                                           "m2": {"status": "FAILED"}}))


if __name__ == "__main__":
    unittest.main()
