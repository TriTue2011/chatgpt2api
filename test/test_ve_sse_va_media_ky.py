"""Hai đường xác thực-qua-URL: vé SSE và chữ ký media.

Cả hai tồn tại vì cùng một lý do kỹ thuật — `EventSource` và loa Cast/DLNA
KHÔNG gửi được header `Authorization`. Cách cũ là nhét thẳng khoá admin vào
query string (`?token=<KHOÁ>`) hoặc bỏ auth hẳn (`/media/voice/…`). Query
string thì đi vào access log của reverse proxy, lịch sử trình duyệt, header
`Referer` và log Cloudflare; mà đó là khoá mở MỌI endpoint, xoay nó thì kéo
theo Home Assistant, Zalo và mọi script.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.signed_url import kiem_chu_ky, ky_duong_dan  # noqa: E402
from services.sse_ticket import KhoVe  # noqa: E402

ADMIN = {"id": "admin", "name": "Quản trị viên", "role": "admin"}


class VeSseTests(unittest.TestCase):
    def setUp(self):
        self.kho = KhoVe()

    def test_ve_dung_duoc_mot_lan(self):
        ve, _ = self.kho.cap(ADMIN)
        self.assertIsNotNone(self.kho.dung(ve))
        self.assertIsNone(self.kho.dung(ve), "vé dùng lại được — mất tính một lần")

    def test_ve_bia_ra_thi_khong_vao_duoc(self):
        self.kho.cap(ADMIN)
        self.assertIsNone(self.kho.dung("ve-bia-ra"))
        self.assertIsNone(self.kho.dung(""))

    def test_ve_het_han_thi_tu_choi(self):
        ve, _ = self.kho.cap(ADMIN)
        # Kéo hạn về quá khứ thay vì ngồi chờ 60 giây.
        han, identity = self.kho._ve[ve]
        self.kho._ve[ve] = (time.time() - 1, identity)
        self.assertIsNone(self.kho.dung(ve))

    def test_ve_mang_theo_dung_danh_tinh(self):
        ve, _ = self.kho.cap({"id": "u1", "name": "Người dùng", "role": "user"})
        self.assertEqual(self.kho.dung(ve)["role"], "user")

    def test_moi_ve_moi_khac_nhau(self):
        ve = {self.kho.cap(ADMIN)[0] for _ in range(50)}
        self.assertEqual(len(ve), 50, "vé bị trùng — nguồn ngẫu nhiên có vấn đề")

    def test_khong_phinh_vo_han(self):
        import services.sse_ticket as st
        for _ in range(st.GIOI_HAN + 50):
            self.kho.cap(ADMIN)
        self.assertLessEqual(self.kho.so_ve(), st.GIOI_HAN)


class ChuKyMediaTests(unittest.TestCase):
    DUONG = "/media/voice/1754600000_abc123.wav"

    def _tach(self, query: str) -> dict:
        return dict(p.split("=", 1) for p in query.split("&"))

    def test_chu_ky_do_may_chu_phat_thi_hop_le(self):
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice"))
        self.assertTrue(kiem_chu_ky(self.DUONG, q["exp"], q["sig"], pham_vi="voice"))

    def test_doi_duong_dan_thi_chu_ky_hong(self):
        """Không ràng đường dẫn thì một chữ ký mở được mọi file."""
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice"))
        self.assertFalse(kiem_chu_ky("/media/voice/file_khac.wav",
                                     q["exp"], q["sig"], pham_vi="voice"))

    def test_keo_dai_han_thi_chu_ky_hong(self):
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice"))
        self.assertFalse(kiem_chu_ky(self.DUONG, str(int(q["exp"]) + 86400),
                                     q["sig"], pham_vi="voice"))

    def test_het_han_thi_tu_choi(self):
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice", song_giay=1))
        self.assertFalse(kiem_chu_ky(self.DUONG, str(int(time.time()) - 10),
                                     q["sig"], pham_vi="voice"))

    def test_doi_pham_vi_thi_chu_ky_hong(self):
        """Chữ ký của file audio không mở được thư viện ảnh."""
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice"))
        self.assertFalse(kiem_chu_ky(self.DUONG, q["exp"], q["sig"], pham_vi="images"))

    def test_thieu_tham_so_thi_tu_choi(self):
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice"))
        self.assertFalse(kiem_chu_ky(self.DUONG, "", q["sig"], pham_vi="voice"))
        self.assertFalse(kiem_chu_ky(self.DUONG, q["exp"], "", pham_vi="voice"))
        self.assertFalse(kiem_chu_ky(self.DUONG, "khong-phai-so", q["sig"], pham_vi="voice"))

    def test_chu_ky_co_ky_tu_ngoai_ascii_khong_lam_sap(self):
        """`sig` do client gửi — `compare_digest` trên chuỗi ném TypeError."""
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice"))
        self.assertFalse(kiem_chu_ky(self.DUONG, q["exp"], "chữ ký có dấu", pham_vi="voice"))

    def test_di_len_thu_muc_cha_khong_qua_duoc(self):
        """Ký `/media/voice/a` rồi đọc `/media/voice/a/../../etc/passwd`."""
        q = self._tach(ky_duong_dan("/media/voice/a.wav", pham_vi="voice"))
        self.assertFalse(kiem_chu_ky("/media/voice/a.wav/../../etc/passwd",
                                     q["exp"], q["sig"], pham_vi="voice"))

    def test_khong_lo_khoa_goc_trong_chu_ky(self):
        q = self._tach(ky_duong_dan(self.DUONG, pham_vi="voice"))
        self.assertNotIn(os.environ["CHATGPT2API_AUTH_KEY"], q["sig"])


class VeRangVaoPhienTests(unittest.TestCase):
    """Vé chỉ dùng được từ CHÍNH phiên đã xin nó.

    Không ràng thì ai đọc được vé trong 60 giây — log của reverse proxy, lịch
    sử trình duyệt, người ngồi cạnh — đều mở được stream từ máy khác. Sống
    ngắn và dùng một lần vẫn chưa đủ: kẻ đọc được log gần như luôn đọc được
    NGAY, không phải sau một ngày.
    """

    def setUp(self):
        self.kho = KhoVe()

    def test_dung_phien_thi_qua(self):
        ve, _ = self.kho.cap(ADMIN, "bam-phien-A")
        self.assertIsNotNone(self.kho.dung(ve, "bam-phien-A"))

    def test_phien_KHAC_thi_khong_dung_duoc(self):
        ve, _ = self.kho.cap(ADMIN, "bam-phien-A")
        self.assertIsNone(self.kho.dung(ve, "bam-phien-B"))

    def test_khong_kem_phien_thi_khong_dung_duoc_ve_da_rang(self):
        ve, _ = self.kho.cap(ADMIN, "bam-phien-A")
        self.assertIsNone(self.kho.dung(ve, ""))

    def test_ve_xin_bang_Bearer_thi_khong_rang(self):
        """Bearer không có phiên cookie — vẫn còn hai lớp: một lần + 60 giây."""
        ve, _ = self.kho.cap(ADMIN, "")
        self.assertIsNotNone(self.kho.dung(ve, ""))

    def test_ve_bi_tu_choi_van_BIEN_MAT(self):
        """Không xoá thì kẻ đoán phiên có thể thử đi thử lại cùng một vé."""
        ve, _ = self.kho.cap(ADMIN, "bam-phien-A")
        self.assertIsNone(self.kho.dung(ve, "sai"))
        self.assertIsNone(self.kho.dung(ve, "bam-phien-A"), "vé vẫn còn sau lần thử sai")

    def test_co_tat_han_duong_token_cu(self):
        """Không có công tắc thì 'tạm thời' sẽ thành vĩnh viễn."""
        src = (GOC / "api/register.py").read_text(encoding="utf-8")
        self.assertIn("sse_legacy_token_disabled", src)


class NoiGoiTests(unittest.TestCase):
    def test_han_URL_voice_KHONG_dai(self):
        """URL đã ký tự nó mở được file — hạn 7 ngày biến mỗi link rò ra
        thành một tuần truy cập tự do. Lịch hẹn cần URL ký NGAY TRƯỚC LÚC
        PHÁT, không phải một link sống lâu."""
        from services.signed_url import HAN_MAC_DINH_GIAY
        src = (GOC / "services/voice/__init__.py").read_text(encoding="utf-8")
        i = src.index("def media_url")
        than = src[i:i + 1600]
        self.assertNotIn("7 * 24 * 3600", than, "URL voice vẫn sống 7 ngày")
        self.assertIn("song_giay=HAN_MAC_DINH_GIAY", than)
        self.assertLessEqual(HAN_MAC_DINH_GIAY, 900,
                             "hạn mặc định quá dài cho một URL tự mở được file")

    def test_media_url_luon_ky(self):
        """Phát URL chưa ký thì bật cờ bắt buộc lên là loa câm ngay."""
        src = (GOC / "services/voice/__init__.py").read_text(encoding="utf-8")
        i = src.index("def media_url")
        self.assertIn("ky_duong_dan", src[i:i + 1400])

    def test_kiem_chu_ky_nam_sau_co(self):
        src = (GOC / "api/voice.py").read_text(encoding="utf-8")
        i = src.index("async def media_voice")
        than = src[i:i + 1600]
        self.assertIn("signed_media_required", than)
        self.assertIn("kiem_chu_ky", than)

    def test_sse_uu_tien_ve_va_canh_bao_duong_cu(self):
        src = (GOC / "api/register.py").read_text(encoding="utf-8")
        i = src.index("async def register_events")
        than = src[i:i + 2600]
        self.assertIn("kho_ve.dung(ticket, _phien_bam(request))", than)
        self.assertIn("sse_token_trong_url", than,
                      "phải ghi cảnh báo để biết khi nào bỏ được đường ?token=")

    def test_web_khong_con_nhet_khoa_vao_url_sse(self):
        src = (GOC / "web/src/app/register/page.tsx").read_text(encoding="utf-8")
        self.assertNotIn("events?token=", src)
        self.assertIn("events?ticket=", src)

    def test_web_tu_noi_lai_bang_ve_moi(self):
        """Vé dùng một lần — reconnect sẵn có của EventSource sẽ 401 vĩnh viễn."""
        src = (GOC / "web/src/app/register/page.tsx").read_text(encoding="utf-8")
        i = src.index("onerror")
        self.assertIn("noi()", src[i:i + 260],
                      "không xin vé mới thì mạng chớp một cái là bảng đứng im")


if __name__ == "__main__":
    unittest.main()
