"""Tạo ảnh Flow đi đường REST, không còn điều khiển giao diện trình duyệt.

Vì sao đổi — số đo thật 10/08/2026, cùng model Nano Banana Pro, cùng tài khoản:

                    xin 16:9         xin 9:16        thời gian
    REST         1376x768  ĐÚNG   768x1376 ĐÚNG      30-33 giây
    giao diện     720x1280  SAI    720x1280          73-94 giây

Đường giao diện phải BẤM vào ô chọn khung hình. Cú bấm đó trượt mà không báo, và
Flow nhớ lựa chọn theo từng hồ sơ, nên một lượt video dọc để lại 9:16 rồi mọi
lượt ảnh sau đó ra ảnh dọc. Nó còn lấy ảnh từ `src` của thẻ <img> đang hiện trên
trang — bản đã co để vừa khung xem.

Hai đường có HỢP ĐỒNG KHÁC NHAU, và đây là chỗ dễ hỏng im lặng nhất khi đổi:

    giao diện:  aspect_ratio = "IMAGE_ASPECT_RATIO_LANDSCAPE"   (hằng số)
    REST:       aspect_ratio = "16:9"                            (nhãn)

    giao diện:  image_b64 = "<một tấm>"        đáp: {"images": [{"url": ...}]}
    REST:       images_b64 = ["<nhiều tấm>"]   đáp: {"urls": [...], ...}

Gửi hằng số vào đường REST thì Google trả 400 kèm tên trường — ồn ào, dễ thấy.
Nhưng đọc đáp sai khoá thì trả về danh sách ảnh RỖNG mà không lỗi nào: người
dùng thấy "đã tạo" mà chẳng có ảnh. Test khoá cả hai chiều.
"""
from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.image_providers import flow_google as M  # noqa: E402

AD = M.flow_image_adapter


class ThanYeuCauDungHopDongREST(unittest.TestCase):
    def test_khung_hinh_gui_NHAN_khong_gui_hang_so(self):
        than = AD.build_body("flow/banana-pro", {"prompt": "ấm trà"})
        self.assertEqual(than["aspect_ratio"], "16:9")
        self.assertNotIn("IMAGE_ASPECT_RATIO", than["aspect_ratio"])

    def test_mac_dinh_khong_khai_gi_la_16_9(self):
        """Người dùng không nêu khung hình thì phải ra ngang, không ra dọc."""
        than = AD.build_body("flow/auto", {"prompt": "x"})
        self.assertEqual(than["aspect_ratio"], "16:9")

    def test_xin_doc_thi_van_duoc_doc(self):
        """Sửa lỗi 'xin ngang ra dọc' không được biến thành 'luôn ngang'."""
        than = AD.build_body("flow/banana-pro",
                             {"prompt": "x", "extra_body": {"aspect_ratio": "9:16"}})
        self.assertEqual(than["aspect_ratio"], "9:16")

    def test_moi_nhan_khung_hinh_deu_doi_duoc_xuoi_nguoc(self):
        """Mỗi hằng số phải có đúng một nhãn — thiếu là rơi về 16:9 lặng lẽ."""
        for nhan, hang in M._ASPECT_FROM_LABEL.items():
            with self.subTest(nhan=nhan):
                self.assertIn(hang, M._ASPECT_LABEL_FROM_CONST)
        for nhan in ("16:9", "4:3", "1:1", "3:4", "9:16"):
            with self.subTest(nhan=nhan):
                than = AD.build_body("flow/banana-pro",
                                     {"prompt": "x",
                                      "extra_body": {"aspect_ratio": nhan}})
                self.assertEqual(than["aspect_ratio"], nhan)

    def test_anh_tham_chieu_la_MANG(self):
        """REST nhận `images_b64` dạng mảng; gửi `image_b64` một tấm là bị bỏ qua
        im lặng — sửa ảnh biến thành vẽ mới từ văn bản."""
        than = AD.build_body("flow/banana-pro",
                             {"prompt": "x", "images": [(b"\x89PNG..", "a.png", "image/png")]})
        self.assertIsInstance(than.get("images_b64"), list)
        self.assertEqual(len(than["images_b64"]), 1)
        self.assertNotIn("image_b64", than)

    def test_khong_gui_co_cua_duong_giao_dien(self):
        """`return_binary` là cờ của đường giao diện; REST không có trường đó."""
        than = AD.build_body("flow/banana-pro", {"prompt": "x"})
        self.assertNotIn("return_binary", than)

    def test_khong_can_hien_man_hinh(self):
        """Trình duyệt chỉ còn để lấy bearer + reCAPTCHA, không bấm gì."""
        than = AD.build_body("flow/banana-pro", {"prompt": "x"})
        self.assertIs(than["headless"], True)


class DiaChiTroDungDuongREST(unittest.TestCase):
    def test_url_la_duong_rest(self):
        cfg = {"captcha_solver_url": "http://solver:8010",
               "accounts": [{"profile": "p1", "project_id": "pr1"}]}
        with mock.patch.object(M, "_pool_config", return_value=cfg):
            url = AD.build_url("flow/banana-pro", {}, 0)
        self.assertTrue(url.endswith("/v1/google/flow/rest/generate-image"), url)

    def test_retry_khong_duoc_giu_lai_profile_da_het_han_muc(self):
        """Hết account thứ hai thì không được dùng lại account thứ nhất."""
        stale = {"profile": "main", "project_id": "p-main"}
        credentials = {"_flow_account": stale}
        cfg = {"captcha_solver_url": "http://solver:8010", "accounts": [stale]}
        with mock.patch.object(M, "_pool_config", return_value=cfg), \
                mock.patch.object(AD, "_current_account", return_value=None):
            AD.build_url("flow/banana-pro", credentials, 1)
        self.assertNotIn("_flow_account", credentials)


class _DapGia:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class DocDapTheoKhoaURLS(unittest.TestCase):
    def test_doc_urls_va_tai_ve(self):
        anh = b"\xff\xd8\xff\xe0GIA"
        with mock.patch("services.image_providers._base.url_to_base64",
                        return_value=base64.b64encode(anh).decode()) as fetch:
            ra = AD.parse_response(_DapGia({
                "urls": ["https://flow-content.google/image/abc?Signature=x"],
                "media_ids": ["abc"], "model": "GEM_PIX_2", "elapsed_ms": 31000}))
        self.assertEqual(len(ra["data"]), 1)
        self.assertEqual(base64.b64decode(ra["data"][0]["b64_json"]), anh)
        self.assertEqual(ra["data"][0]["_flow_meta"]["media_ids"], ["abc"])
        fetch.assert_called_once_with("https://flow-content.google/image/abc?Signature=x", timeout=60)

    def test_khoa_cu_images_KHONG_con_duoc_doc(self):
        """Nếu ai đó trỏ lại đường giao diện, đáp dạng cũ phải ra rỗng chứ không
        được lặng lẽ 'thành công' — rỗng thì người gọi báo lỗi, còn đọc nhầm
        khoá mà vẫn kêu ok là kiểu hỏng không ai lần ra."""
        ra = AD.parse_response(_DapGia({"images": [{"url": "http://x/y.jpg"}]}))
        self.assertEqual(ra["data"], [])

    def test_het_han_muc_van_bat_duoc_de_xoay_tai_khoan(self):
        d = _DapGia({}, status=429)
        d.text = "quota exceeded"
        with self.assertRaises(RuntimeError):
            AD.parse_response(d)


if __name__ == "__main__":
    unittest.main()
