"""Tầng T0 không được tuyên bố thua khi các tầng trình duyệt còn chưa chạy.

SỰ CỐ 09/08/2026. Chủ máy nhận đúng chuỗi này qua Telegram:

    ⚠️ ChatGPT free — nguyenvanviet210290@gmail.com
    Lỗi: dead:periodic_scan
    → [T0] Không có refresh_token nên không tự khôi phục được.
    ❌ Cần đăng nhập lại thủ công qua noVNC (cổng 6080).

    ⚠️ ChatGPT free — nguyenvanviet210290@gmail.com
    Lỗi: dead:periodic_scan
    → Đang tự khôi phục (tài khoản Google)…

    🔧 [T3] Đang đăng nhập lại tài khoản Google (giống nút 'Chỉ đăng nhập')…

Lời tuyên bố thua đến TRƯỚC cả lúc hệ thống bắt đầu thử. Hai câu đó mâu thuẫn
nhau trong cùng một phút, về cùng một tài khoản.

NGUYÊN NHÂN

`codex_error_recovery_scheduler._recover_one` chạy LẦN LƯỢT hai hàm: T0
(`recover_and_notify`, làm mới bằng refresh_token) rồi T1–T3
(`recover_provider_account`, đăng nhập lại bằng trình duyệt). Nhưng T0 không
biết có ai chạy sau mình, nên thiếu refresh_token là nó kết luận luôn "cần đăng
nhập tay".

Cái giá không chỉ là khó chịu: người vận hành đọc dòng ❌ rồi đi đăng nhập tay
một tài khoản mà máy tự chữa được — hoặc tệ hơn, quen với việc thông báo nói
sai rồi bỏ qua cả những lần nó nói đúng.

CÁCH SỬA

`con_tang_trinh_duyet()` tách riêng phép kiểm "sau T0 còn tầng nào chạy được
không", dùng chung registry `_PROVIDERS` nên áp cho MỌI provider nhiều tầng
(codex, ChatGPT free, và bất kỳ provider nào bật sau này). Còn tầng thì T0 im
lặng nhường lượt; hết tầng thì mới báo tay.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))

ACC = {"email": "nguyenvanviet210290@gmail.com",
       "access_token": "tok-cu", "refresh_token": ""}


def _chay(account: dict, con_tang: bool, refresh_ok: bool = False):
    """Chạy `recover_and_notify` với các phụ thuộc bị thay, trả list thông báo."""
    from services import account_recovery as ar
    ar._last_attempt.clear()
    goi: list[str] = []
    with mock.patch.object(ar, "_notify", side_effect=lambda t, d=None: goi.append(t)), \
         mock.patch.object(ar, "con_tang_trinh_duyet", return_value=con_tang), \
         mock.patch.dict("sys.modules", {}):
        with mock.patch("services.account_service.account_group", return_value="free"):
            if refresh_ok:
                # Không dựng đường refresh thật — ca này đã có test riêng.
                pass
            ar.recover_and_notify(dict(account), reason="dead:periodic_scan")
    return goi


class T0KhongTuyenBoThuaSomTests(unittest.TestCase):
    def test_con_tang_trinh_duyet_thi_T0_IM_LANG(self):
        """Đây là ca đã gây ra sự cố: không có refresh_token nhưng còn T1–T3."""
        goi = _chay(ACC, con_tang=True)
        self.assertEqual(goi, [],
                         "T0 phải im lặng nhường lượt cho tầng trình duyệt; "
                         f"nhưng đã gửi: {goi}")

    def test_het_tang_thi_van_bao_can_dang_nhap_tay(self):
        """Không được im luôn — hết đường thật thì người vận hành phải biết."""
        goi = _chay(ACC, con_tang=False)
        self.assertEqual(len(goi), 1)
        self.assertIn("Cần đăng nhập lại thủ công", goi[0])
        self.assertIn("không còn đường đăng nhập lại", goi[0],
                      "phải nói RÕ là đã hết đường, không phải chỉ 'thiếu refresh_token'")

    def test_tai_khoan_khuyet_danh_van_im_lang(self):
        """Acc tự thu thập không có email → không có đường nào, và báo mỗi lần
        chỉ là nhiễu. Hành vi cũ, không được làm hỏng."""
        goi = _chay({"access_token": "x", "refresh_token": "", "email": ""},
                    con_tang=False)
        self.assertEqual(goi, [])


class ThongDiepMauThuanTests(unittest.TestCase):
    """Soi ở mức nguồn: không còn câu nào tuyên bố thua vô điều kiện."""

    def setUp(self):
        self.nguon = (GOC / "services/account_recovery.py").read_text(encoding="utf-8")
        dau = self.nguon.index("def recover_and_notify")
        self.than = self.nguon[dau:]

    def test_moi_cau_bao_dang_nhap_tay_deu_sau_mot_phep_kiem(self):
        for moc in ("Cần đăng nhập lại thủ công", "Cần đăng nhập lại qua noVNC"):
            i = self.than.index(moc)
            truoc = self.than[max(0, i - 700):i]
            self.assertIn("con_tang_trinh_duyet", truoc,
                          f"câu «{moc}» không nằm sau phép kiểm còn tầng hay không")

    def test_refresh_truot_ma_con_tang_thi_noi_la_CHUYEN_TIEP(self):
        i = self.than.index("chuyển sang đăng nhập lại bằng trình duyệt")
        truoc = self.than[max(0, i - 400):i]
        self.assertIn("con_tang_trinh_duyet", truoc)

    def test_ham_kiem_dung_registry_nen_phu_moi_provider(self):
        i = self.nguon.index("def con_tang_trinh_duyet")
        than = self.nguon[i:i + 1200]
        self.assertIn("_PROVIDERS", than,
                      "phải tra registry để áp cho mọi provider nhiều tầng, "
                      "không hardcode riêng ChatGPT free")
        self.assertIn("enabled", than,
                      "provider chưa bật thì không tính là còn tầng")


if __name__ == "__main__":
    unittest.main()
