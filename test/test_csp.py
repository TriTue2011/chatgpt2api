"""CSP: báo cáo trước, siết sau — và không bao giờ tự bật.

CSP là loại header bật nhầm thì TRANG TRẮNG, còn lỗi thì chỉ nằm trong console
trình duyệt. Người dùng chỉ thấy "web hỏng". Vì vậy hai cờ đều mặc định tắt, và
bước báo cáo phải chạy trước bước chặn.

Chính sách ở bước báo cáo là chính sách ĐÍCH, không nới lỏng: cho sẵn
`'unsafe-inline'` cho script thì báo cáo im lặng và ta chẳng học được gì — tới
lúc siết mới biết là hỏng.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import csp  # noqa: E402
from services.config import config  # noqa: E402


class _Nen(unittest.TestCase):
    def dat(self, security: dict):
        self._cu = config.data
        self.addCleanup(lambda: setattr(config, "data", self._cu))
        config.data = {"security": security}


class CoMacDinhTatTests(_Nen):
    def test_mac_dinh_khong_bat_csp(self):
        self.dat({})
        self.assertFalse(csp.bat_csp(config))

    def test_bat_csp_van_chi_la_bao_cao(self):
        self.dat({"csp_enabled": True})
        self.assertTrue(csp.bat_csp(config))
        self.assertFalse(csp.dang_siet(config), "bật CSP không được siết ngay")

    def test_siet_phai_khai_rieng(self):
        self.dat({"csp_enabled": True, "csp_enforce": True})
        self.assertTrue(csp.dang_siet(config))

    def test_config_hong_thi_coi_nhu_tat(self):
        self.dat({"csp_enabled": "khong-phai-bool"})
        # Chuỗi khác rỗng là truthy — đây là hành vi có chủ ý của bool(), test
        # này chốt rằng nó KHÔNG ném lỗi làm hỏng mọi phản hồi.
        try:
            csp.bat_csp(config)
        except Exception as exc:
            self.fail(f"cấu hình lạ làm sập header: {exc}")


class ChinhSachTests(unittest.TestCase):
    def test_bao_cao_dung_chinh_sach_DICH(self):
        """Nới lỏng ở bước báo cáo thì báo cáo chẳng cho biết gì."""
        s = csp.chuoi_chinh_sach(co_report_uri=True)
        self.assertIn("script-src 'self'", s)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", s)

    def test_co_du_bon_chi_thi_chu_dat(self):
        s = csp.chuoi_chinh_sach(co_report_uri=False)
        for muc in ("default-src 'self'", "object-src 'none'",
                    "base-uri 'self'", "frame-ancestors 'none'"):
            self.assertIn(muc, s)

    def test_bao_cao_co_report_uri_con_siet_thi_khong(self):
        self.assertIn("report-uri /api/csp-report",
                      csp.chuoi_chinh_sach(co_report_uri=True))
        self.assertNotIn("report-uri", csp.chuoi_chinh_sach(co_report_uri=False))

    def test_cho_phep_data_blob_cho_anh_va_audio(self):
        """Ảnh xem trước và audio phát tại chỗ là dữ liệu trang tự tạo."""
        s = csp.chuoi_chinh_sach(co_report_uri=False)
        self.assertIn("img-src 'self' data: blob:", s)
        self.assertIn("media-src 'self' data: blob:", s)


class GopBaoCaoTests(unittest.TestCase):
    def setUp(self):
        self.bo = csp._BoDemBaoCao()

    def test_lan_dau_thi_ghi(self):
        ghi, lan = self.bo.nen_ghi("script-src", "inline")
        self.assertTrue(ghi)
        self.assertEqual(lan, 1)

    def test_trung_lap_thi_thua_dan(self):
        """Một lần tải trang có thể bắn hàng trăm báo cáo giống hệt nhau."""
        so_ghi = sum(1 for _ in range(30)
                     if self.bo.nen_ghi("script-src", "inline")[0])
        self.assertLess(so_ghi, 10, f"ghi {so_ghi}/30 lần — vẫn ngập log")
        self.assertGreaterEqual(so_ghi, 1, "không ghi lần nào thì mù luôn")

    def test_vi_pham_KHAC_nhau_van_duoc_ghi(self):
        self.assertTrue(self.bo.nen_ghi("script-src", "inline")[0])
        self.assertTrue(self.bo.nen_ghi("connect-src", "https://la.com")[0])

    def test_lut_thi_ngung_han(self):
        for _ in range(csp._BoDemBaoCao.TRAN_MOI_CUA_SO + 10):
            self.bo.nen_ghi("d", f"nguon-{_}")
        self.assertFalse(self.bo.nen_ghi("d", "nguon-moi")[0])


class KhongGhiNguyenPayloadTests(unittest.TestCase):
    def test_chi_giu_ba_truong(self):
        """Payload chứa URL đầy đủ của trang, có thể mang tham số nhạy cảm."""
        src = (GOC / "services/csp.py").read_text(encoding="utf-8")
        i = src.index("def ghi_bao_cao")
        than = src[i:]
        self.assertIn("effective-directive", than)
        self.assertIn("blocked-uri", than)
        self.assertNotIn("document-uri", than, "URL trang không được vào log")

    def test_endpoint_khong_doi_auth_va_chan_body_qua_co(self):
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        i = src.index("async def csp_report")
        than = src[i:i + 1600]
        self.assertNotIn("require_admin", than,
                         "đòi auth thì không nhận được báo cáo nào")
        self.assertIn("16 * 1024", than)

    def test_doc_body_theo_CHUNK_chu_khong_nap_tron_roi_moi_do(self):
        """`await request.body()` nạp trọn rồi mới đo — với request chunked
        (không Content-Length) thì trần kiểm sau khi RAM đã mất. Endpoint này
        lại KHÔNG auth, nên đó là một đường DoS mở sẵn."""
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        i = src.index("async def csp_report")
        than = src[i:i + 1600]
        self.assertIn("read_body_limited(request, 16 * 1024)", than)
        # Bắt vào LỆNH GÁN, không phải chuỗi trần: chú thích ngay trên đó có
        # nhắc `await request.body()` để giải thích vì sao đã bỏ.
        self.assertNotIn("raw = await request.body()", than,
                         "vẫn nạp trọn body trước khi đo")


if __name__ == "__main__":
    unittest.main()
