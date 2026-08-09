"""Thân yêu cầu của đường Flow REST phải đúng từng trường.

VÌ SAO CẦN. Đường REST (`captcha-solver/src/solvers/flow_rest.py`) gửi thẳng
JSON cho Google thay vì bấm giao diện. Mọi thứ trước đây "bấm sai thì thấy ngay
trên màn hình" nay nằm hết trong một dict — sai một tên trường thì Google trả
400 INVALID_ARGUMENT không nói trường nào, hoặc tệ hơn là nhận và dựng sai loại.

ĐO THẬT 09/08/2026 (tài khoản google-benbap115). API kiểm `imageModelName`
TRƯỚC cửa reCAPTCHA nên đo được trực tiếp từng tên:

    NARWHAL / HARBOR_SEAL   hợp lệ
    NANO_BANANA_PRO         400 INVALID_ARGUMENT — KHÔNG tồn tại
    IMAGEN_4                400 INVALID_ARGUMENT — KHÔNG tồn tại

`NANO_BANANA_PRO` lại đang là model mặc định của `flow/auto` và `flow/banana-pro`
ở `services/image_providers/flow_google.py`, và là giá trị dự phòng cuối cùng
của `_resolve_model()`. Đường DOM che mất lỗi này vì nó chỉ dùng chuỗi đó làm
khoá tra NHÃN dropdown. Ngày ai đó nối đường REST vào adapter cũ, mặc định đó sẽ
đi thẳng xuống Google và mọi lượt tạo ảnh 400. Test đầu tiên ở đây chốt việc
chặn phải xảy ra tại chỗ, kèm thông báo nêu tên đúng.

Phần còn lại chốt hình dạng thân yêu cầu tạo ảnh: `clientContext` phải có ở cả
hai tầng, `count` phải nhân bản request chứ không bắn nhiều lời gọi, và mã lỗi
không bao giờ được mang giá trị 2xx.
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


class MaLoiKhongDuocLaThanhCong(unittest.TestCase):
    """`LoiFlowRest` không bao giờ được mang mã 2xx.

    `main.py::_loi_flow_rest` chuyển thẳng `.status` thành `HTTPException`, nên
    một lỗi mang mã 200 sẽ trả về HTTP 200 kèm thân `detail` — bên gọi đọc thấy
    thành công trong khi thật ra hỏng. Hai chỗ "HTTP 200 nhưng thân đáp vô dụng"
    (upload không có mediaId, đáp thiếu media) từng dùng mã 200 đúng theo nghĩa
    đen của tầng HTTP, và đó là cái bẫy.
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


if __name__ == "__main__":
    unittest.main()
