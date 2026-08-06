"""Kho đám mây độc lập theo phạm vi như nhật ký — kết nối mới mở đường ĐỌC.

Chủ máy chốt 06/08: "tôi muốn nó độc lập như nhật ký mà, chỉ khi kết nối mới có
quyền đọc, tải về; tải lên thì vẫn chỉ tải lên đám mây được cài đặt thôi".

Trước bản này, năng lực `kho_dam_may` cho đọc MỌI kho đã khai bất kể thread nào
gọi — tức nhóm nào bật năng lực đó là cả nhóm xem được toàn bộ đám mây của chủ
máy. Đo trên máy chủ 06/08: ba kho `drive-benbap2011`, `drime-tritue0610`,
`meha-tritue0610` đều liệt kê và mở được từ bất kỳ thread nào.

Hai chiều KHÁC HẲN nhau, và đó là điểm dễ làm lẫn nhất:

    ĐỌC  kho mình  +  kho của phạm vi đã kết nối
    GHI  CHỈ kho mình
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import luu_tru_online as lt  # noqa: E402


class _CauHinhGia:
    def __init__(self, data):
        self.data = data

    def get(self):
        return self.data

    def update(self, moi):
        self.data.update(moi)


#: Hai nhóm, hai kho khác nhau; A và B chưa nối gì.
_KHO = {
    "zalop:nhomA": {"enabled": True, "kho": "drive-A", "thu_muc": "c2a"},
    "zalop:nhomB": {"enabled": True, "kho": "drive-B", "thu_muc": "rieng"},
}
_A = "zalop_nhomA"
_B = "zalop_nhomB"


def _gan(them=None):
    d = {"luu_tru_online": dict(_KHO)}
    if them:
        d.update(them)
    import services.config as cfg_mod
    cfg_mod.config = _CauHinhGia(d)
    lt.config = cfg_mod.config
    return cfg_mod


class _Nen(unittest.TestCase):

    def setUp(self):
        import services.config as cfg_mod
        self._cfg = cfg_mod.config
        self._lt = lt.config
        self.addCleanup(setattr, cfg_mod, "config", self._cfg)
        self.addCleanup(setattr, lt, "config", self._lt)


class ChuaNoiThiDOC_LAPTests(_Nen):

    def setUp(self):
        super().setUp()
        _gan()

    def test_moi_pham_vi_chi_thay_kho_cua_minh(self):
        self.assertEqual([k["kho"] for k in lt.cac_kho_doc_duoc(_A)], ["drive-A"])
        self.assertEqual([k["kho"] for k in lt.cac_kho_doc_duoc(_B)], ["drive-B"])

    def test_khong_doc_duoc_kho_cua_nhom_khac(self):
        self.assertFalse(lt.duoc_doc(_A, "drive-B:rieng"))
        self.assertFalse(lt.duoc_doc(_B, "drive-A:c2a"))

    def test_doc_duoc_kho_cua_minh(self):
        self.assertTrue(lt.duoc_doc(_A, "drive-A:c2a"))
        self.assertTrue(lt.duoc_doc(_A, "drive-A:c2a/PDF"))

    def test_kho_khong_khai_thi_khong_doc_duoc_gi(self):
        self.assertEqual(lt.cac_kho_doc_duoc("zalop_nhom-la"), [])
        self.assertFalse(lt.duoc_doc("zalop_nhom-la", "drive-A:c2a"))


class ThuMucCUNG_KHO_KHAC_NHANHTests(_Nen):
    """So tiền tố chuỗi là 'drive-A:c2a-rieng' lọt qua vì có tiền tố
    'drive-A:c2a' — thư mục KHÁC mà vẫn đọc được là lộ dữ liệu."""

    def setUp(self):
        super().setUp()
        _gan()

    def test_thu_muc_cung_tien_to_nhung_khac_nhanh_thi_chan(self):
        for xau in ("drive-A:c2a-rieng", "drive-A:c2a-rieng/x.pdf",
                    "drive-A:c2ax", "drive-A:khac"):
            with self.subTest(xau=xau):
                self.assertFalse(lt.duoc_doc(_A, xau))

    def test_dung_nhanh_con_thi_cho_qua(self):
        for xau in ("drive-A:c2a", "drive-A:c2a/", "drive-A:c2a/PDF",
                    "drive-A:c2a/PDF/a.pdf"):
            with self.subTest(xau=xau):
                self.assertTrue(lt.duoc_doc(_A, xau))

    def test_khai_ca_kho_thi_moi_thu_muc_trong_đo_deu_duoc(self):
        _gan({"luu_tru_online": {
            "zalop:nhomA": {"enabled": True, "kho": "drive-A", "thu_muc": ""}}})
        self.assertTrue(lt.duoc_doc(_A, "drive-A:"))
        self.assertTrue(lt.duoc_doc(_A, "drive-A:bat-ky/dau"))
        self.assertFalse(lt.duoc_doc(_A, "drive-B:rieng"))

    def test_thieu_ten_kho_thi_chan(self):
        self.assertFalse(lt.duoc_doc(_A, "c2a/PDF"))
        self.assertFalse(lt.duoc_doc(_A, ""))


class NOI_BINH_DANG_ThiDocDuocCuaNhauTests(_Nen):

    def setUp(self):
        super().setUp()
        _gan({"memory_links": [{
            "id": "ml_1", "kind": "binh_dang", "name": "Nhà mình", "enabled": True,
            "members": [{"kenh": "zalop", "chat": "nhomA", "topic": "", "user": ""},
                        {"kenh": "zalop", "chat": "nhomB", "topic": "", "user": ""}],
        }]})

    def test_hai_chieu_deu_doc_duoc(self):
        self.assertTrue(lt.duoc_doc(_A, "drive-B:rieng"))
        self.assertTrue(lt.duoc_doc(_B, "drive-A:c2a"))

    def test_kho_cua_minh_dung_dau_danh_sach(self):
        ds = lt.cac_kho_doc_duoc(_A)
        self.assertEqual(ds[0]["kho"], "drive-A")
        self.assertTrue(ds[0]["cua_minh"])
        self.assertFalse(ds[1]["cua_minh"])

    def test_TAT_ket_noi_thi_thoi(self):
        _gan({"memory_links": [{
            "id": "ml_1", "kind": "binh_dang", "enabled": False,
            "members": [{"kenh": "zalop", "chat": "nhomA", "topic": "", "user": ""},
                        {"kenh": "zalop", "chat": "nhomB", "topic": "", "user": ""}],
        }]})
        self.assertFalse(lt.duoc_doc(_A, "drive-B:rieng"))


class NOI_CHINH_PHU_MotChieuTests(_Nen):
    """Chính đọc được phụ; phụ KHÔNG đọc được chính."""

    def setUp(self):
        super().setUp()
        _gan({"memory_links": [{
            "id": "ml_2", "kind": "chinh_phu", "name": "Bố mẹ ↔ con",
            "enabled": True,
            "primary": [{"kenh": "zalop", "chat": "nhomA", "topic": "", "user": ""}],
            "secondary": [{"kenh": "zalop", "chat": "nhomB", "topic": "", "user": ""}],
        }]})

    def test_chinh_doc_duoc_phu(self):
        self.assertTrue(lt.duoc_doc(_A, "drive-B:rieng"))

    def test_phu_KHONG_doc_duoc_chinh(self):
        self.assertFalse(lt.duoc_doc(_B, "drive-A:c2a"))


class GHI_CHI_VAO_KHO_CUA_MINHTests(_Nen):
    """Chủ máy chốt: "tải lên thì vẫn chỉ tải lên đám mây được cài đặt thôi"."""

    def setUp(self):
        super().setUp()
        _gan({"memory_links": [{
            "id": "ml_1", "kind": "binh_dang", "enabled": True,
            "members": [{"kenh": "zalop", "chat": "nhomA", "topic": "", "user": ""},
                        {"kenh": "zalop", "chat": "nhomB", "topic": "", "user": ""}],
        }]})

    def test_ghi_vao_kho_minh_thi_duoc(self):
        self.assertTrue(lt.duoc_ghi(_A, "drive-A:c2a/PDF"))

    def test_da_NOI_van_KHONG_ghi_duoc_sang_kho_kia(self):
        """Đọc được rồi vẫn không ghi được — kết nối CHỈ mở đường đọc."""
        self.assertTrue(lt.duoc_doc(_A, "drive-B:rieng"))
        self.assertFalse(lt.duoc_ghi(_A, "drive-B:rieng"),
                         "kết nối mở luôn cả đường ghi — nối rồi gỡ là dữ liệu "
                         "đã chảy sang nhau, không tách lại được")

    def test_kho_ghi_duoc_chi_tra_kho_cua_minh(self):
        self.assertEqual(lt.kho_ghi_duoc(_A)["kho"], "drive-A")
        self.assertEqual(lt.kho_ghi_duoc(_B)["kho"], "drive-B")

    def test_chua_khai_thi_khong_ghi_duoc(self):
        self.assertEqual(lt.kho_ghi_duoc("zalop_nhom-la"), {})
        self.assertFalse(lt.duoc_ghi("zalop_nhom-la", "drive-A:c2a"))


class CUNG_MOT_KHO_KHAC_THU_MUC_ThiVanDocLapTests(_Nen):
    """Chủ máy chốt 06/08: "ngoài 2 kho khác nhau, trong 1 kho thì thread 1
    folder cũng độc lập nhau".

    Đây là cảnh THẬT của chủ máy: cả hai phạm vi đang bật đều trỏ vào thư mục
    `c2a`, chỉ khác kho. Đổi sang một kho duy nhất (Drive 5 TB) rồi tách theo
    thư mục là cách dùng tự nhiên nhất — và khi đó ranh giới nằm ở THƯ MỤC, không
    còn ở tên kho.
    """

    KHO_CHUNG = {
        "zalop:nhomA": {"enabled": True, "kho": "drive-1", "thu_muc": "Gia dinh"},
        "zalop:nhomB": {"enabled": True, "kho": "drive-1", "thu_muc": "Cong viec"},
    }

    def setUp(self):
        super().setUp()
        _gan({"luu_tru_online": dict(self.KHO_CHUNG)})

    def test_moi_thread_chi_thay_thu_muc_cua_minh(self):
        self.assertTrue(lt.duoc_doc(_A, "drive-1:Gia dinh/PDF"))
        self.assertFalse(lt.duoc_doc(_A, "drive-1:Cong viec"),
                         "cùng kho nên lọt sang thư mục của thread khác")
        self.assertTrue(lt.duoc_doc(_B, "drive-1:Cong viec/PDF"))
        self.assertFalse(lt.duoc_doc(_B, "drive-1:Gia dinh"))

    def test_khong_ai_doc_duoc_goc_kho(self):
        """Đọc được gốc kho là thấy tên mọi thư mục của mọi thread."""
        self.assertFalse(lt.duoc_doc(_A, "drive-1:"))
        self.assertFalse(lt.duoc_doc(_B, "drive-1:"))

    def test_ghi_cung_chi_vao_thu_muc_cua_minh(self):
        self.assertTrue(lt.duoc_ghi(_A, "drive-1:Gia dinh"))
        self.assertFalse(lt.duoc_ghi(_A, "drive-1:Cong viec"))

    def test_noi_roi_thi_doc_duoc_thu_muc_kia_NHUNG_khong_ghi(self):
        _gan({"luu_tru_online": dict(self.KHO_CHUNG),
              "memory_links": [{
                  "id": "ml_1", "kind": "binh_dang", "enabled": True,
                  "members": [
                      {"kenh": "zalop", "chat": "nhomA", "topic": "", "user": ""},
                      {"kenh": "zalop", "chat": "nhomB", "topic": "", "user": ""}],
              }]})
        self.assertTrue(lt.duoc_doc(_A, "drive-1:Cong viec/PDF"))
        self.assertFalse(lt.duoc_ghi(_A, "drive-1:Cong viec"))

    def test_thu_muc_long_nhau_khong_lot(self):
        """'Gia dinh' và 'Gia dinh rieng' — tên lồng tiền tố nhau."""
        _gan({"luu_tru_online": {
            "zalop:nhomA": {"enabled": True, "kho": "drive-1", "thu_muc": "Gia dinh"},
            "zalop:nhomB": {"enabled": True, "kho": "drive-1",
                            "thu_muc": "Gia dinh rieng"}}})
        self.assertFalse(lt.duoc_doc(_A, "drive-1:Gia dinh rieng"))
        self.assertFalse(lt.duoc_doc(_B, "drive-1:Gia dinh"))


class TAI_VE_QUA_KET_NOI_VanPhaiDuocTests(_Nen):
    """Chủ máy chốt 06/08: "qua «Kết nối bộ nhớ», thêm download để khi có yêu cầu
    gửi file vẫn được".

    Kho mượn qua kết nối phải TẢI VỀ được, không thì gặp câu "gửi cho tôi file X"
    mà X nằm ở kho mượn là bot bó tay. Chỉ đường LƯU LÊN mới bị khoá.

    Tải về rồi gửi đi được vì `rclone_service.workspace_dir()` và
    `officecli.workspace()` là CÙNG một thư mục (`OFFICECLI_WORKSPACE`), nên tệp
    vừa tải xuống là `office_send` gửi đi được ngay.
    """

    def setUp(self):
        super().setUp()
        _gan({"memory_links": [{
            "id": "ml_1", "kind": "binh_dang", "enabled": True,
            "members": [{"kenh": "zalop", "chat": "nhomA", "topic": "", "user": ""},
                        {"kenh": "zalop", "chat": "nhomB", "topic": "", "user": ""}],
        }]})
        from services.agent import capabilities as caps
        from services import rclone_service as rcl
        self.caps = caps
        self.da_tai = []
        self._goc = rcl.tai_ve
        rcl.tai_ve = lambda dd, ten_luu="": (
            self.da_tai.append(dd) or {"ok": True, "duong_dan": "/ws/x.pdf", "co": 9})
        self.addCleanup(setattr, rcl, "tai_ve", self._goc)

    def _goi(self, duong_dan, op="tai_ve"):
        return self.caps._h_kho_dam_may(
            {"op": op, "duong_dan": duong_dan}, {"user_id": _A})["text"]

    def test_tai_ve_tu_kho_MUON_thi_duoc(self):
        t = self._goi("drive-B:rieng/bao-cao.pdf")
        self.assertIn("Đã tải", t)
        self.assertEqual(self.da_tai, ["drive-B:rieng/bao-cao.pdf"])

    def test_tai_ve_tu_kho_MINH_thi_duoc(self):
        self.assertIn("Đã tải", self._goi("drive-A:c2a/a.pdf"))

    def test_tai_ve_kho_NGOAI_pham_vi_thi_chan(self):
        t = self._goi("drive-LA:khac/x.pdf")
        self.assertNotIn("Đã tải", t)
        self.assertEqual(self.da_tai, [], "đã gọi rclone dù không được phép")

    def test_cau_bao_loi_NOI_RO_dung_duoc_kho_nao(self):
        """Chỉ báo 'không được phép' thì người dùng không biết mình gõ sai gì."""
        t = self._goi("drive-LA:khac/x.pdf")
        self.assertIn("drive-A", t)
        self.assertIn("drive-B", t)

    def test_liet_ke_kho_co_ca_kho_muon(self):
        t = self.caps._h_kho_dam_may({"op": "remotes"}, {"user_id": _A})["text"]
        self.assertIn("drive-A", t)
        self.assertIn("drive-B", t)
        self.assertIn("kết nối", t, "phải nói rõ kho nào là kho mượn")

    def test_LUU_LEN_kho_muon_van_bi_chan(self):
        t = self.caps._h_kho_dam_may_gui(
            {"op": "gui_len", "tep": "x.pdf", "thu_muc": "drive-B:rieng"},
            {"user_id": _A})["text"]
        self.assertIn("chỉ ghi được", t)

    def test_workspace_tai_ve_va_workspace_gui_file_LA_MOT(self):
        """Hai thư mục khác nhau thì tải về xong không gửi đi được."""
        from services import officecli, rclone_service as rcl
        self.assertEqual(officecli.workspace(), rcl.workspace_dir())


class NangLucBotPhaiDiQuaRanhGioiTests(unittest.TestCase):
    """Làm hàm phân giải mà năng lực không gọi thì ranh giới không có hiệu lực."""

    def _src(self):
        return (GOC / "services" / "agent" / "capabilities.py").read_text("utf-8")

    def test_doc_phai_kiem_duoc_doc(self):
        src = self._src()
        i = src.index("def _h_kho_dam_may(")
        khoi = src[i:i + 2600]
        self.assertIn("cac_kho_doc_duoc(", khoi)
        self.assertIn("duoc_doc(", khoi)

    def test_ghi_phai_kiem_duoc_ghi(self):
        src = self._src()
        i = src.index("def _h_kho_dam_may_gui(")
        khoi = src[i:i + 1800]
        self.assertIn("kho_ghi_duoc(", khoi)
        self.assertIn("duoc_ghi(", khoi)
        self.assertNotIn("cac_kho_doc_duoc(", khoi,
                         "đường GHI không được dùng danh sách đọc")

    def test_khong_con_liet_ke_MOI_kho_da_khai(self):
        """`rcl.remotes()` trả mọi kho của máy chủ — không được đưa thẳng ra bot."""
        src = self._src()
        i = src.index("def _h_kho_dam_may(")
        khoi = src[i:i + 2600]
        self.assertNotIn("rcl.remotes()", khoi)


if __name__ == "__main__":
    unittest.main()
