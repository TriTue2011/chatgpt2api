"""Sổ tên dùng chung — một thiết bị → mọi thiết bị."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class SoTenTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.so_ten_nha as m
        self.m = m
        self._tmp = tempfile.mkdtemp()
        m._FILE = Path(self._tmp) / "so_ten.json"
        m.config.data.setdefault("mqtt", {})["so_ten"] = {}

    def tearDown(self) -> None:
        self.m._reset_for_tests()

    # ── MẤU CHỐT: nguồn khác nhau không đè nhau ────────────────────────────
    def test_HAI_NGUON_CUNG_MA_KHONG_DE_NHAU(self) -> None:
        """Sổ cũ dùng khoá 'face#17' không có nguồn — thêm Frigate là đụng ngay.

        Khuôn mặt số 17 của Tuya và của Frigate là HAI người khác nhau.
        """
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("tuya", "face", "17", "con trai")
            self.m.dat_ten("frigate", "face", "17", "khách")
        with mock.patch.object(state, "search_memory", return_value=[]):
            self.assertEqual(self.m.ten_cua("tuya", "face", "17"), "con trai")
            self.assertEqual(self.m.ten_cua("frigate", "face", "17"), "khách")

    def test_khoa_co_du_ba_phan(self) -> None:
        self.assertEqual(self.m.khoa("tuya", "unlock", "11"), "tuya:unlock#11")

    # ── ba tầng tra tên ────────────────────────────────────────────────────
    def test_uu_tien_ten_nha_san_xuat(self) -> None:
        self.assertEqual(
            self.m.ten_cua("tuya", "face", "1", "Anh Việt"), "Anh Việt")

    def test_TEN_MAY_MOC_van_coi_la_chua_biet(self) -> None:
        """'EVN VN Device (PM110000486' là tên nhà sản xuất, nhưng với người
        vẫn là chưa có tên — đo được 101/1068 thực thể như vậy."""
        from services.agent import state
        with mock.patch.object(state, "search_memory", return_value=[]):
            self.assertEqual(
                self.m.ten_cua("ha", "cam_bien", "x", "EVN VN Device (PM110000486"), "")

    def test_ten_nguoi_that_thi_giu(self) -> None:
        self.assertFalse(self.m.ten_may_moc("Đèn phòng khách"))
        self.assertFalse(self.m.ten_may_moc("con trai"))

    def test_ten_co_nhieu_so_la_may_moc(self) -> None:
        self.assertTrue(self.m.ten_may_moc("Homeassistant (-1002793479"))
        self.assertTrue(self.m.ten_may_moc(""))

    def test_doc_duoc_ten_tu_tri_nho(self) -> None:
        from services.agent import state
        with mock.patch.object(
                state, "search_memory",
                return_value=["- [10/09] vân tay 11 là con trai"]):
            self.assertEqual(self.m.ten_cua("tuya", "vân tay", "11"), "con trai")

    def test_TRI_NHO_KHONG_KHOP_BUA_THEO_SO(self) -> None:
        """Lỗi thật ở bản cũ: lọc bằng `ma in s` nên 'ngày 11', '11 giờ' cũng
        khớp, rồi trả cả câu làm tên người."""
        from services.agent import state
        with mock.patch.object(
                state, "search_memory",
                return_value=["- [10/09] hôm 11 tháng trước nhà có khách"]):
            self.assertEqual(self.m.ten_cua("tuya", "face", "11"), "")

    # ── van chống làm phiền ────────────────────────────────────────────────
    def test_hoi_toi_da_3_lan(self) -> None:
        k = self.m.khoa("mqtt", "thiet_bi", "abc")
        for _ in range(3):
            self.assertTrue(self.m.nen_hoi(k))
            self.m.danh_dau_da_hoi(k)
        self.assertFalse(self.m.nen_hoi(k))

    def test_dat_ten_roi_thi_thoi_hoi(self) -> None:
        from services.agent import state
        k = self.m.khoa("mqtt", "thiet_bi", "abc")
        self.m.danh_dau_da_hoi(k)
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("mqtt", "thiet_bi", "abc", "ổ cắm bếp")
        self.assertFalse(self.m.nen_hoi(k), "biết tên rồi thì không hỏi nữa")
        self.assertTrue(self.m.da_biet(k))

    def test_THOI_HOI_khac_voi_HOI_DU_3_LAN(self) -> None:
        """Chủ nhà bảo «để sau» ≠ «đã hỏi 3 lần không ai trả lời».

        Gộp làm một bộ đếm thì không phân biệt được hai chuyện này.
        """
        k = self.m.khoa("frigate", "face", "9")
        self.m.thoi_hoi(k)
        self.assertFalse(self.m.nen_hoi(k))
        self.assertFalse(self.m.da_biet(k), "để sau KHÔNG phải là đã biết tên")

    # ── chỉ hỏi thứ hay dùng (chủ máy chốt) ────────────────────────────────
    def test_THU_IT_DUNG_THI_KHONG_HOI(self) -> None:
        """Nhà có 101 thứ chưa biết tên — hỏi hết là làm phiền."""
        k = self.m.khoa("ha", "cam_bien", "x")
        self.assertFalse(self.m.dang_hoi_duoc(k, so_lan_thay=1))
        self.assertFalse(self.m.dang_hoi_duoc(k, so_lan_thay=2))

    def test_thu_hay_dung_thi_hoi(self) -> None:
        k = self.m.khoa("tuya", "face", "17")
        self.assertTrue(self.m.dang_hoi_duoc(k, so_lan_thay=5))

    def test_hay_dung_nhung_da_biet_thi_thoi(self) -> None:
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("tuya", "face", "17", "mẹ")
        k = self.m.khoa("tuya", "face", "17")
        self.assertFalse(self.m.dang_hoi_duoc(k, so_lan_thay=99))

    # ── mô tả ──────────────────────────────────────────────────────────────
    def test_mo_ta_loai_da_biet(self) -> None:
        self.assertEqual(self.m.mo_ta("tuya:fingerprint#11"), "vân tay 11")
        self.assertEqual(self.m.mo_ta("frigate:face#17"), "khuôn mặt 17")

    def test_LOAI_LA_KHONG_BIA(self) -> None:
        """Thêm loại mới vẫn chạy, chỉ hiện nguyên mã."""
        self.assertEqual(self.m.mo_ta("x:loai_moi#5"), "loai_moi 5")

    # ── phát ra trí nhớ chung ──────────────────────────────────────────────
    def test_dat_ten_ghi_ca_vao_TRI_NHO_CHUNG(self) -> None:
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat") as nho:
            self.m.dat_ten("tuya", "fingerprint", "11", "con trai")
        nho.assert_called_once()
        self.assertIn("con trai", nho.call_args[0][0])

    def test_tri_nho_hong_van_luu_duoc_so(self) -> None:
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat",
                               side_effect=RuntimeError("hỏng")):
            self.assertTrue(self.m.dat_ten("tuya", "face", "3", "bà"))
        with mock.patch.object(state, "search_memory", return_value=[]):
            self.assertEqual(self.m.ten_cua("tuya", "face", "3"), "bà")

    # ── chuyển sổ cũ ───────────────────────────────────────────────────────
    def test_CHUYEN_SO_CU_KHONG_MAT_TEN_DA_DAY(self) -> None:
        """Đổi khoá mà không chuyển thì chủ máy phải dạy lại từ đầu."""
        import json
        from services.config import DATA_DIR
        cu = Path(DATA_DIR) / "agent" / "khoa_cua_nha.json"
        cu.parent.mkdir(parents=True, exist_ok=True)
        goc = cu.read_text(encoding="utf-8") if cu.exists() else None
        try:
            cu.write_text(json.dumps({"ten": {"fingerprint#11": "con trai"}}),
                          encoding="utf-8")
            self.assertEqual(self.m._chuyen_doi_so_cu(), 1)
            from services.agent import state
            with mock.patch.object(state, "search_memory", return_value=[]):
                self.assertEqual(
                    self.m.ten_cua("tuya", "fingerprint", "11"), "con trai")
        finally:
            if goc is None:
                cu.unlink(missing_ok=True)
            else:
                cu.write_text(goc, encoding="utf-8")

    def test_chuyen_hai_lan_khong_nhan_doi(self) -> None:
        import json
        from services.config import DATA_DIR
        cu = Path(DATA_DIR) / "agent" / "khoa_cua_nha.json"
        cu.parent.mkdir(parents=True, exist_ok=True)
        goc = cu.read_text(encoding="utf-8") if cu.exists() else None
        try:
            cu.write_text(json.dumps({"ten": {"face#2": "bố"}}), encoding="utf-8")
            self.m._chuyen_doi_so_cu()
            self.assertEqual(self.m._chuyen_doi_so_cu(), 0)
        finally:
            if goc is None:
                cu.unlink(missing_ok=True)
            else:
                cu.write_text(goc, encoding="utf-8")

    # ── không bao giờ raise ────────────────────────────────────────────────
    def test_ghi_hong_khong_raise(self) -> None:
        # Thư mục cha là một TỆP có sẵn: kể cả root cũng không tạo được thư mục
        # ở đó. "/khong/ton/tai/" thì root tạo được, nên nhánh ghi hỏng không hề
        # được thử khi chạy test bằng root (máy chủ, 11/09/2026).
        self.m._FILE = Path(__file__) / "so.json"
        try:
            self.m.dat_ten("x", "y", "1", "z")
        except Exception as exc:
            self.fail(f"không được ném lỗi: {exc}")

    def test_ten_rong_thi_khong_luu(self) -> None:
        self.assertFalse(self.m.dat_ten("tuya", "face", "1", "  "))

    def test_thong_ke_dem_dung(self) -> None:
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("tuya", "face", "1", "bố")
        self.m.danh_dau_da_hoi(self.m.khoa("tuya", "face", "2"))
        t = self.m.thong_ke()
        self.assertEqual(t["da_biet"], 1)
        self.assertEqual(t["chua_biet"], 1)


class TraTriNhoTheoPhamViTest(unittest.TestCase):
    """Hai lỗi thật đo 10/09/2026: dạy tên lúc 08h33, 11h32 vẫn hỏi lại."""

    def setUp(self) -> None:
        import services.so_ten_nha as m
        self.m = m
        self._tmp = tempfile.mkdtemp()
        m._FILE = Path(self._tmp) / "so_ten.json"
        m.config.data.setdefault("mqtt", {})["so_ten"] = {}

    def tearDown(self) -> None:
        self.m._reset_for_tests()

    def test_KHOP_CAU_TIENG_VIET_khong_phai_ma_may(self) -> None:
        """Bot ghi 'Khuôn mặt số 17 … là vợ của anh'; bản cũ tra chuỗi
        'face 17' nên không bao giờ khớp."""
        from services.agent import state
        dong = ("- [2026-09-10 08:34] (zalo_x) Khuôn mặt số 17 trên hệ thống "
                "khóa cửa là vợ của anh.")
        with mock.patch.object(state, "search_memory", return_value=[dong]):
            self.assertIn("vợ", self.m.ten_cua("tuya", "face", "17"))

    def test_QUET_CA_KHO_RIENG_cua_nguoi_da_day(self) -> None:
        """Bot ghi vào kho RIÊNG của người dạy, bản cũ chỉ tra kho chung."""
        from services.agent import state
        goi: list[str] = []

        def gia_lap(q, **kw):
            pv = kw.get("pham_vi") or ""
            goi.append(pv)
            if pv == "kho_cua_anh":
                return ["- [10/09] khuôn mặt 17 là vợ của anh"]
            return []

        with mock.patch.object(state, "nho_hoac_cap_nhat"), \
             mock.patch("services.agent.scope.khoa_du_lieu",
                        return_value="kho_cua_anh"):
            self.m.dat_ten("tuya", "face", "17", "vợ", user_id="zalo_x")
        # Xoá MỤC tên (giữ nguyên sổ) để buộc đi tới tầng trí nhớ — danh sách
        # phạm vi đã dạy nằm cùng file, đổi file là mất luôn nó.
        so = self.m._doc()
        so["muc"] = {}
        self.m._ghi(so)
        with mock.patch.object(state, "search_memory", side_effect=gia_lap):
            t = self.m.ten_cua("tuya", "face", "17")
        self.assertIn("vợ", t)
        self.assertIn("kho_cua_anh", goi, "phải quét kho của người đã dạy")

    def test_KHONG_KHOP_NHAM_SO_KHAC(self) -> None:
        from services.agent import state
        dong = "- [10/09] khuôn mặt 1 là con trai"
        with mock.patch.object(state, "search_memory", return_value=[dong]):
            self.assertEqual(self.m.ten_cua("tuya", "face", "17"), "")

    def test_kho_chung_van_tra_duoc(self) -> None:
        from services.agent import state
        with mock.patch.object(
                state, "search_memory",
                return_value=["- [10/09] vân tay 11 là anh Việt"]):
            self.assertIn("Việt", self.m.ten_cua("tuya", "fingerprint", "11"))

    # ── Tab Học hỏi: đặt khu vực tay + xoá ──────────────────────────────────
    def test_DAT_TEN_KEM_KHU_VUC_HIEN_TRONG_DANH_SACH(self) -> None:
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("mqtt", "thiet_bi", "den_ban_cong", "Đèn ban công",
                           khu_vuc="Ban công")
        muc = next(d for d in self.m.danh_sach() if d["ma"] == "den_ban_cong")
        self.assertEqual(muc["khu_vuc"], "Ban công")

    def test_SUA_TEN_KHONG_KEM_KHU_VUC_THI_GIU_NGUYEN_KHU_VUC_CU(self) -> None:
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("mqtt", "thiet_bi", "x", "Tên cũ", khu_vuc="Bếp")
            self.m.dat_ten("mqtt", "thiet_bi", "x", "Tên mới")
        muc = next(d for d in self.m.danh_sach() if d["ma"] == "x")
        self.assertEqual(muc["ten"], "Tên mới")
        self.assertEqual(muc["khu_vuc"], "Bếp")

    def test_XOA_MUC_KHONG_CON_TRONG_DANH_SACH(self) -> None:
        from services.agent import state
        with mock.patch.object(state, "nho_hoac_cap_nhat"):
            self.m.dat_ten("mqtt", "thiet_bi", "y", "Sẽ xoá")
        k = self.m.khoa("mqtt", "thiet_bi", "y")
        self.assertTrue(self.m.xoa(k))
        self.assertFalse(any(d["khoa"] == k for d in self.m.danh_sach()))

    def test_XOA_MUC_KHONG_TON_TAI_TRA_FALSE(self) -> None:
        self.assertFalse(self.m.xoa("mqtt:thiet_bi#khong_co"))


if __name__ == "__main__":
    unittest.main()
