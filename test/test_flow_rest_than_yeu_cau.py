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


class TyLeKhungHinhDungHangSoCoThat(unittest.TestCase):
    """Hằng số tỷ lệ đã ĐO 10/08/2026, và hai file phải nói cùng một thứ.

    Tỷ lệ được kiểm TRƯỚC cửa reCAPTCHA và Google báo kèm tên trường, nên quét
    được miễn phí: `..._FOUR_THREE` / `..._THREE_FOUR` hợp lệ, còn `..._4_3` /
    `..._3_4` KHÔNG tồn tại — mà hai dạng sau đúng là thứ bảng bên dịch vụ dùng
    suốt thời gian qua. Đường DOM che mất vì nó chỉ dùng chuỗi làm khoá tra nhãn
    dropdown, y hệt cách `NANO_BANANA_PRO` sống sót.
    """

    KHONG_TON_TAI = ("IMAGE_ASPECT_RATIO_LANDSCAPE_4_3", "IMAGE_ASPECT_RATIO_PORTRAIT_3_4",
                     "VIDEO_ASPECT_RATIO_SQUARE", "VIDEO_ASPECT_RATIO_LANDSCAPE_FOUR_THREE")

    def test_khong_file_nao_con_dung_hang_so_da_do_la_khong_co(self):
        for duong in ("services/image_providers/flow_google.py",
                      "captcha-solver/src/solvers/flow_google.py",
                      "captcha-solver/src/solvers/flow_rest.py"):
            nguon = (GOC / duong).read_text(encoding="utf-8")
            for hang in self.KHONG_TON_TAI:
                with self.subTest(duong=duong, hang=hang):
                    # Cho phép nhắc trong chú thích (dòng bắt đầu bằng # hoặc
                    # nằm trong docstring), chỉ cấm dùng làm giá trị thật.
                    self.assertNotIn(f'"{hang}"', nguon)

    def test_bang_ty_le_anh_chi_chua_hang_so_da_do_la_co(self):
        CO = {"IMAGE_ASPECT_RATIO_SQUARE", "IMAGE_ASPECT_RATIO_LANDSCAPE",
              "IMAGE_ASPECT_RATIO_PORTRAIT", "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE",
              "IMAGE_ASPECT_RATIO_PORTRAIT_THREE_FOUR"}
        self.assertEqual(set(FR.TY_LE_ANH.values()) - CO, set())

    def test_video_chi_co_hai_ty_le(self):
        """Đo: chỉ LANDSCAPE và PORTRAIT. Không có SQUARE, không có 4:3."""
        self.assertEqual(set(FR.TY_LE_VIDEO.values()),
                         {"VIDEO_ASPECT_RATIO_LANDSCAPE", "VIDEO_ASPECT_RATIO_PORTRAIT"})


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

    def test_khong_khai_bac_tra_phi(self):
        """Client thật KHÔNG gửi `userPaygateTier` — xem bản chụp request
        09/08/2026. Ta từng bê trường này từ bản gỡ rối sang; đường ảnh được
        Google bỏ qua, còn đường video trả thẳng 403 "The caller does not have
        permission"."""
        than = self._than()
        for ctx in (than["clientContext"], than["requests"][0]["clientContext"]):
            self.assertNotIn("userPaygateTier", ctx)
        self.assertEqual(set(than["clientContext"]),
                         {"projectId", "tool", "sessionId"})

    def test_session_id_co_dau_cham_phay_dung_truoc(self):
        """Bản chụp cho thấy ";1786253707634", kể cả ở đường ảnh."""
        than = FR.than_tao_anh(project_id="p1", prompt="x", model="NARWHAL")
        self.assertTrue(than["clientContext"]["sessionId"].startswith(";"))

    def test_doc_duoc_link_anh_tu_dap(self):
        """Link nằm ở media[].image.generatedImage.fifeUrl. Bản cũ dò regex trên
        `str(dap)` — chuỗi đó dùng nháy ĐƠN nên không bao giờ khớp nháy kép."""
        dap = {"media": [{"name": "m1", "image": {"generatedImage": {
            "fifeUrl": "https://flow-content.google/image/m1?Expires=1&Signature=x"}}}]}
        self.assertEqual(FR.doc_link_anh(dap),
                         ["https://flow-content.google/image/m1?Expires=1&Signature=x"])

    def test_dap_khong_co_link_thi_tra_rong(self):
        self.assertEqual(FR.doc_link_anh({"media": [{"name": "m1"}]}), [])

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
        # Đường VIDEO CÓ gửi bậc trả phí, và giá trị đúng là ONE — đọc từ
        # telemetry thật của giao diện Flow. Bản gỡ rối ghi TWO và ta bê nguyên
        # sang: 403 "The caller does not have permission". Bỏ hẳn trường cũng
        # 403. Đường ẢNH thì ngược lại, không gửi trường này.
        self.assertEqual(than["clientContext"]["userPaygateTier"], "PAYGATE_TIER_ONE")

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

    def test_che_do_co_anh_khong_co_ban_fast_hay_quality(self):
        """Quét đủ họ 09/08: i2v, interpolation, r2v đều KHÔNG có Fast/Quality —
        `veo_3_1_r2v`, `veo_3_1_i2v_fast`… đều 404. Phải báo lỗi nêu bản có thật
        chứ không lặng lẽ hạ xuống Lite."""
        for che_do in ("component", "image_start", "image_start_end"):
            for nhan in ("Veo 3.1 - Fast", "Veo 3.1 - Quality"):
                with self.subTest(che_do=che_do, nhan=nhan):
                    with self.assertRaises(ValueError) as ngu_canh:
                        FR.chon_model_video(che_do, nhan, None)
                    self.assertIn("Veo 3.1 - Lite", str(ngu_canh.exception))

    def test_hai_che_do_khung_hinh_ton_trong_nhan_lite(self):
        """Có HAI bản Lite. Bản cũ gán cứng bản ưu tiên thấp nên người chọn
        "Lite" vẫn bị đẩy xuống hàng chờ chậm mà không biết."""
        self.assertEqual(FR.chon_model_video("image_start", "Veo 3.1 - Lite", None),
                         "veo_3_1_i2v_lite")
        self.assertEqual(
            FR.chon_model_video("image_start", "Veo 3.1 - Lite [Lower Priority]", None),
            "veo_3_1_i2v_lite_low_priority")
        self.assertEqual(FR.chon_model_video("image_start_end", "Veo 3.1 - Lite", None),
                         "veo_3_1_interpolation_lite")

    def test_nhan_la_van_ve_mac_dinh(self):
        """Nhãn ngoài bộ nhãn giao diện thì không chặn — cấu hình cũ vẫn chạy."""
        self.assertEqual(FR.chon_model_video("text_to_video", "Model nao do", None),
                         "veo_3_1_t2v_lite_low_priority")

    def test_omni_flash_chi_co_o_t2v_va_component(self):
        for che_do in ("image_start", "image_start_end"):
            with self.subTest(che_do=che_do), self.assertRaises(ValueError):
                FR.chon_model_video(che_do, "Omni Flash", "8s")

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

    def test_moi_khoa_trong_bang_deu_la_khoa_da_do_la_CO(self):
        """Bảng chỉ được chứa khoá đã quét ra là dùng được (09/08/2026)."""
        DA_DO_LA_CO = {
            "veo_3_1_t2v", "veo_3_1_t2v_fast", "veo_3_1_t2v_lite",
            "veo_3_1_t2v_lite_low_priority",
            "veo_3_1_i2v_lite", "veo_3_1_i2v_lite_low_priority",
            "veo_3_1_interpolation_lite", "veo_3_1_interpolation_lite_low_priority",
            "veo_3_1_r2v_lite", "veo_3_1_r2v_lite_low_priority",
        }
        for che_do, bang in FR.MODEL_VIDEO.items():
            for nhan, khoa in bang.items():
                with self.subTest(che_do=che_do, nhan=nhan):
                    if "{giay}" in khoa:
                        for g in FR.GIAY_OMNI_FLASH:
                            self.assertIn(khoa.format(giay=g).rsplit("_", 1)[0],
                                          ("abra_t2v", "abra_r2v"))
                    else:
                        self.assertIn(khoa, DA_DO_LA_CO)


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
