"""Tài khoản gói cao dùng trước, nhưng vừa cạn quota thì xuống đáy.

Yêu cầu chủ máy 10/08/2026, nguyên văn hai vế:

    "áp dụng cả ảnh cả text, pro > team/enterprise > business > plus > go > free"
    "ưu tiên nhưng khi hết quota thì cũng sắp xếp xuống cuối chứ không phải lúc
     nào cũng số #1"

VẾ HAI MỚI LÀ VẾ KHÓ. `demote_account()` đẩy tài khoản vừa dính 429 xuống cuối
pool, nhưng thứ tự pool chỉ có tác dụng khi mọi tiêu chí khác BẰNG NHAU. Trước
10/08 điều đó gần như luôn đúng ở đường text (success/fail chỉ được ghi ở đường
ảnh, nên đa số tài khoản text cùng điểm 0.5) — nên việc hạ có tác dụng thật.
Ngay khi thêm bậc gói vào khoá chọn thì nó hết tác dụng: một tài khoản Plus vừa
cạn vẫn hơn bậc mọi tài khoản free và lại được chọn ngay lượt sau. Vì vậy "đang
bị hạ" phải thành một tiêu chí ĐỨNG TRÊN bậc gói, và phải có mốc thời gian
(`demoted_at`) chứ không thể dựa vào vị trí trong pool nữa.

PHẠM VI. Bậc gói chỉ phân định TRONG CÙNG một pool. Gói đã tách pool từ trước
(`account_group`: gói trả phí → nhóm codex), nên bậc này thực tế chỉ có tác dụng
bên trong nhóm codex. Nó KHÔNG và không được phép quyết định chuyện dùng pool
nào trước — việc đó do thứ tự provider trong `combo_models`.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import (  # noqa: E402
    PAID_PLANS,
    AccountService,
    account_group,
    bac_goi,
    dang_bi_ha,
)
from services.storage.json_storage import JSONStorageBackend  # noqa: E402


def _luc(giay_truoc: float) -> str:
    return (datetime.now() - timedelta(seconds=giay_truoc)).strftime("%Y-%m-%d %H:%M:%S")


def _khoa(account: dict):
    return AccountService._selection_key(account)


class BacGoiTests(unittest.TestCase):
    def test_dung_thu_tu_chu_may_chot(self):
        r = lambda p: bac_goi({"plan": p})  # noqa: E731
        self.assertGreater(r("pro"), r("team"))
        self.assertEqual(r("team"), r("enterprise"))
        self.assertGreater(r("enterprise"), r("business"))
        self.assertGreater(r("business"), r("plus"))
        self.assertGreater(r("plus"), r("go"))
        self.assertGreater(r("go"), r("free"))

    def test_khong_ro_goi_thi_bang_free(self):
        for acc in ({"plan": "free"}, {"plan": ""}, {"plan": None}, {}, None):
            self.assertEqual(bac_goi(acc), 0, acc)

    def test_moi_goi_tra_phi_deu_co_bac(self):
        """Hai bảng phải nói cùng một danh sách. Thêm gói mới vào PAID_PLANS mà
        quên PLAN_RANK thì gói đó tụt xuống ngang free — im lặng và khó thấy."""
        for goi in PAID_PLANS:
            with self.subTest(goi=goi):
                self.assertGreater(bac_goi({"plan": goi}), 0)

    def test_hoa_thuong_va_khoang_trang(self):
        self.assertEqual(bac_goi({"plan": " Plus "}), bac_goi({"plan": "plus"}))


class DangBiHaTests(unittest.TestCase):
    def test_vua_ha_thi_dung(self):
        self.assertTrue(dang_bi_ha({"demoted_at": _luc(10)}))

    def test_qua_cua_so_thi_tro_lai(self):
        self.assertFalse(dang_bi_ha({"demoted_at": _luc(3600)}))

    def test_khong_co_moc_hoac_moc_hong_deu_la_khong(self):
        for acc in ({}, {"demoted_at": ""}, {"demoted_at": "hôm qua"}, None):
            self.assertFalse(dang_bi_ha(acc), acc)


class ThuBacKhoaChonTests(unittest.TestCase):
    """Ba tiêu chí phải đúng thứ bậc, không cái nào nuốt cái nào."""

    def test_bi_ha_thua_ca_goi_cao_nhat(self):
        """Vế hai của yêu cầu: pro vừa cạn phải thua go còn khoẻ."""
        pro_vua_can = {"plan": "pro", "demoted_at": _luc(10)}
        go_khoe = {"plan": "go"}
        self.assertGreater(_khoa(go_khoe), _khoa(pro_vua_can))

    def test_goi_cao_thang_suc_khoe(self):
        """Vế một: plus có lý lịch xấu vẫn đi trước free có lý lịch đẹp."""
        plus_te = {"plan": "plus", "success": 0, "fail": 50}
        free_tot = {"plan": "free", "success": 50, "fail": 0}
        self.assertGreater(_khoa(plus_te), _khoa(free_tot))

    def test_cung_bac_thi_suc_khoe_quyet_dinh(self):
        tot = {"plan": "plus", "success": 20, "fail": 0}
        te = {"plan": "plus", "success": 0, "fail": 20}
        self.assertGreater(_khoa(tot), _khoa(te))

    def test_bang_nhau_ca_ba_thi_giu_thu_tu_pool(self):
        """max() ổn định → hoà thì vẫn là FIFO y như trước khi có tính năng."""
        ung_vien = [("A", {"plan": "free"}), ("B", {"plan": "free"})]
        self.assertEqual(max(ung_vien, key=lambda c: _khoa(c[1]))[0], "A")


class DuongTextTests(unittest.TestCase):
    """Chọn token text: cùng pool codex, gói cao đi trước; cạn thì nhường."""

    def _dich_vu(self, tmp: str) -> AccountService:
        return AccountService(JSONStorageBackend(Path(tmp) / "accounts.json"))

    def _them(self, sv: AccountService, token: str, plan: str) -> None:
        sv.add_accounts([token])
        sv.update_account(token, {"status": "active", "plan": plan})

    def test_plus_di_truoc_go_va_free_trong_pool_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._dich_vu(tmp)
            self._them(sv, "tok-go", "go")       # thêm TRƯỚC → FIFO sẽ chọn nó
            self._them(sv, "tok-plus", "plus")
            self.assertEqual(account_group(sv._accounts["tok-plus"]), "codex")
            self.assertEqual(sv.get_text_access_token(account_type="codex"), "tok-plus")

    def test_plus_vua_can_thi_nhuong_cho_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._dich_vu(tmp)
            self._them(sv, "tok-plus", "plus")
            self._them(sv, "tok-go", "go")
            self.assertEqual(sv.get_text_access_token(account_type="codex"), "tok-plus")
            sv.demote_account("tok-plus")
            self.assertEqual(sv.get_text_access_token(account_type="codex"), "tok-go")

    def test_pool_free_khong_doi_gi(self):
        """Cả pool cùng plan=free → bậc bằng nhau → vẫn FIFO như trước."""
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._dich_vu(tmp)
            for t in ("f1", "f2", "f3"):
                self._them(sv, t, "free")
            self.assertEqual(sv.get_text_access_token(account_type="free"), "f1")

    def test_bac_goi_khong_keo_acc_tra_phi_sang_pool_free(self):
        """Ranh giới pool là bất khả xâm phạm: bậc gói xếp thứ tự TRONG pool,
        không được đưa tài khoản trả phí vào luồng free-tier (HA, n8n)."""
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._dich_vu(tmp)
            self._them(sv, "tok-plus", "plus")
            self._them(sv, "tok-free", "free")
            self.assertEqual(sv.get_text_access_token(account_type="free"), "tok-free")


class DuongAnhTests(unittest.TestCase):
    """Đường ảnh xoay vòng theo chỉ số — lọc về bậc cao nhất rồi mới xoay."""

    def _dich_vu(self, tmp: str, *cap: tuple[str, str]) -> AccountService:
        sv = AccountService(JSONStorageBackend(Path(tmp) / "accounts.json"))
        for token, plan in cap:
            sv.add_accounts([token])
            sv.update_account(token, {"status": "active", "plan": plan, "quota": 10})
        return sv

    def test_chi_giu_bac_cao_nhat(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._dich_vu(tmp, ("go", "go"), ("plus", "plus"), ("free", "free"))
            self.assertEqual(sv._loc_bac_cao_nhat(["go", "plus", "free"]), ["plus"])

    def test_cung_bac_thi_giu_ca_hai_de_con_xoay_vong(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._dich_vu(tmp, ("p1", "plus"), ("p2", "plus"), ("f", "free"))
            self.assertEqual(sv._loc_bac_cao_nhat(["p1", "p2", "f"]), ["p1", "p2"])

    def test_bac_cao_vua_can_thi_rot_xuong(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._dich_vu(tmp, ("plus", "plus"), ("go", "go"))
            self.assertEqual(sv._loc_bac_cao_nhat(["plus", "go"]), ["plus"])
            sv.demote_account("plus")
            self.assertEqual(sv._loc_bac_cao_nhat(["plus", "go"]), ["go"])

    def test_mot_ung_vien_thi_tra_nguyen(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._dich_vu(tmp, ("f", "free"))
            self.assertEqual(sv._loc_bac_cao_nhat(["f"]), ["f"])


class MocBiHaTests(unittest.TestCase):
    def test_demote_ghi_moc_chu_khong_chi_doi_vi_tri(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = AccountService(JSONStorageBackend(Path(tmp) / "accounts.json"))
            sv.add_accounts(["t"])
            sv.update_account("t", {"status": "active", "plan": "plus"})
            self.assertFalse(dang_bi_ha(sv._accounts["t"]))
            sv.demote_account("t")
            self.assertTrue(dang_bi_ha(sv._accounts["t"]))

    def test_dung_lai_duoc_thi_het_bi_ha_ngay(self):
        """Không phải chờ hết cửa sổ — giống cách provider_order đưa provider
        hồi phục về đúng chỗ cũ."""
        with tempfile.TemporaryDirectory() as tmp:
            sv = AccountService(JSONStorageBackend(Path(tmp) / "accounts.json"))
            sv.add_accounts(["t"])
            sv.update_account("t", {"status": "active", "plan": "plus",
                                    "quota": 10, "image_quota_unknown": True})
            sv.demote_account("t")
            self.assertTrue(dang_bi_ha(sv._accounts["t"]))
            sv.mark_image_result("t", True)
            self.assertFalse(dang_bi_ha(sv._accounts["t"]))


class LoiChuKhongPhaiCanQuotaTests(unittest.TestCase):
    """Tài khoản LỖI (không phải cạn quota) cũng phải tụt đáy — lần lỗi thứ hai.

    Chốt với chủ máy 10/08/2026: "lần đầu lỗi chuyển acc, lần tiếp dùng lỗi thì
    hạ".

    Vì sao cần: `_bac_uu_tien` của đường ảnh cố ý KHÔNG có thành phần sức khoẻ
    (giữ vòng xoay dàn tải), nên bộ đếm `fail` một mình không đẩy được tài khoản
    nào xuống. Trước khi có bậc gói thì vô hại — đường ảnh xoay đều nên tài khoản
    lỗi chỉ ăn 1/N lượt. Từ lúc `_loc_bac_cao_nhat` chỉ giữ bậc cao nhất, một tài
    khoản gói cao đang lỗi mà là tài khoản gói cao DUY NHẤT sẽ nhận 100% lượt.
    """

    def _sv(self, tmp: str, *cap: tuple[str, str]) -> AccountService:
        sv = AccountService(JSONStorageBackend(Path(tmp) / "accounts.json"))
        for token, plan in cap:
            sv.add_accounts([token])
            sv.update_account(token, {"status": "active", "plan": plan,
                                      "quota": 10, "image_quota_unknown": True})
        return sv

    def test_loi_lan_dau_KHONG_ha(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._sv(tmp, ("t", "plus"))
            sv.mark_image_result("t", False)
            self.assertFalse(dang_bi_ha(sv._accounts["t"]),
                             "lỗi lẻ mà đã hạ 15 phút thì tài khoản lành bị oan")
            self.assertEqual(sv._accounts["t"].get("fail_streak"), 1)

    def test_loi_lien_tiep_lan_hai_thi_ha(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._sv(tmp, ("t", "plus"))
            sv.mark_image_result("t", False)
            sv.mark_image_result("t", False)
            self.assertTrue(dang_bi_ha(sv._accounts["t"]))

    def test_thanh_cong_giua_hai_lan_loi_thi_reset_streak(self):
        """"LIÊN TIẾP" phải đúng nghĩa liên tiếp — xen một lượt tốt là tính lại."""
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._sv(tmp, ("t", "plus"))
            sv.mark_image_result("t", False)
            sv.mark_image_result("t", True)
            self.assertIsNone(sv._accounts["t"].get("fail_streak"))
            sv.mark_image_result("t", False)
            self.assertFalse(dang_bi_ha(sv._accounts["t"]),
                             "streak chưa reset nên lỗi lẻ thứ hai bị hạ oan")

    def test_goi_cao_dang_loi_phai_nhuong_cho_goi_thap(self):
        """Đúng cảnh gây lo: pro lỗi mà là gói cao duy nhất → ăn 100% lượt ảnh."""
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._sv(tmp, ("pro", "pro"), ("go", "go"))
            self.assertEqual(sv._loc_bac_cao_nhat(["pro", "go"]), ["pro"])
            sv.mark_image_result("pro", False)
            self.assertEqual(sv._loc_bac_cao_nhat(["pro", "go"]), ["pro"],
                             "lần đầu chỉ chuyển acc, chưa được hạ")
            sv.mark_image_result("pro", False)
            self.assertEqual(sv._loc_bac_cao_nhat(["pro", "go"]), ["go"],
                             "pro lỗi liên tiếp mà vẫn giữ ngôi bậc cao nhất")

    def test_hoi_phuc_thi_ve_cho_cu_ngay(self):
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._sv(tmp, ("pro", "pro"), ("go", "go"))
            sv.mark_image_result("pro", False)
            sv.mark_image_result("pro", False)
            self.assertEqual(sv._loc_bac_cao_nhat(["pro", "go"]), ["go"])
            sv.mark_image_result("pro", True)
            self.assertEqual(sv._loc_bac_cao_nhat(["pro", "go"]), ["pro"],
                             "dùng lại được rồi thì phải về ngay, không chờ 15 phút")

    def test_moc_ha_khong_bi_normalize_lam_rung(self):
        """`mark_image_result` đi qua `_normalize_account` — trường lạ mà bị lọc
        thì mốc hạ mất âm thầm, triệu chứng y như chưa sửa gì."""
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._sv(tmp, ("t", "plus"))
            sv.mark_image_result("t", False)
            sv.mark_image_result("t", False)
            luu = sv._accounts["t"]
            self.assertIn("demoted_at", luu)
            self.assertIn("fail_streak", luu)

    def test_van_dem_fail_tich_luy_nhu_cu(self):
        """Thêm streak KHÔNG được thay bộ đếm `fail` — `_selection_weight` của
        đường text đọc nó để tính success-rate."""
        with tempfile.TemporaryDirectory() as tmp:
            sv = self._sv(tmp, ("t", "plus"))
            sv.mark_image_result("t", False)
            sv.mark_image_result("t", True)
            sv.mark_image_result("t", False)
            self.assertEqual(int(sv._accounts["t"].get("fail") or 0), 2)


if __name__ == "__main__":
    unittest.main()
