"""Khôi phục tài khoản free phải chạy TỪNG CÁI MỘT — và nói đúng như thế.

SỰ CỐ 15/08/2026. Bot admin nhả một loạt sáu tin trong cùng một khoảnh khắc::

    🔧 ChatGPT free — smarthomebenbap@gmail.com
    [T3] Đang đăng nhập lại tài khoản Google (giống nút 'Chỉ đăng nhập')…
    🔧 ChatGPT free — trianhtuenhi@gmail.com
    [T3] Đang đăng nhập lại tài khoản Google (giống nút 'Chỉ đăng nhập')…
    … (bốn tài khoản nữa)

Chủ máy hỏi đúng chỗ: "sao đăng nhập hàng loạt này, từng tài khoản mà nhỉ".

Việc đăng nhập Google thì đúng là từng cái một — `_glogin_serial` giữ khoá suốt
cả lượt. Ba chỗ hỏng nằm quanh nó:

1. Tin báo gửi TRƯỚC khi giành được lượt, nên năm tài khoản đang xếp hàng vẫn
   nói "đang đăng nhập lại".
2. Ngân sách 1200 giây của một lượt khôi phục tính cả thời gian nằm chờ. Một
   lượt T3 giữ khoá tới 700 giây, nên tài khoản thứ ba trở đi hết giờ ngay khi
   tới lượt: đăng nhập Google xong xuôi nhưng bước lấy token bị bỏ qua, và tin
   cuối vẫn là "❌ KHÔNG tự khôi phục được".
3. Bộ quét JWT tạo mỗi tài khoản kẹt một luồng trong cùng một khoảnh khắc, và
   nhánh đó `continue` nhảy qua đúng quãng nghỉ rải tải đặt ngay bên dưới. Tầng
   T2 (mở onboard trong captcha-solver) không có khoá nào nên sáu phiên trình
   duyệt chạy song song thật.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from services import account_recovery as ar
from services import jwt_refresh_scheduler as sch


class _TraLoi:
    """Đáp án giả của solver — mọi lượt hỏi đều 'success'."""

    def json(self) -> dict[str, str]:
        return {"state": "success"}


@pytest.mark.pure
def test_tin_bao_T3_chi_gui_sau_khi_gianh_duoc_luot():
    thu_tu: list[str] = []

    class KhoaGhiThuTu:
        def acquire(self) -> bool:
            thu_tu.append("giành khoá")
            return True

        def release(self) -> None:
            thu_tu.append("nhả khoá")

    fake_requests = mock.Mock(post=lambda *a, **k: _TraLoi(),
                              get=lambda *a, **k: _TraLoi())
    with mock.patch.dict(sys.modules, {"requests": fake_requests}), \
            mock.patch.object(ar, "_solver_cfg", lambda: ("http://x", "k")), \
            mock.patch.object(ar, "_glogin_serial", KhoaGhiThuTu()), \
            mock.patch.object(ar.time, "sleep", lambda *_: None):
        ok = ar._freshen_google(
            "google-x", khi_toi_luot=lambda _cho: thu_tu.append("báo"))

    assert ok is True
    assert thu_tu == ["giành khoá", "báo", "nhả khoá"]


def _chay_khoi_phuc(cho_giay: float, ton_giay: float) -> tuple[list[str], list[str]]:
    """Chạy một lượt khôi phục tài khoản Google với đồng hồ giả.

    ``cho_giay`` = thời gian nằm chờ tới lượt đăng nhập Google.
    ``ton_giay`` = tổng thời gian trôi qua trong lượt T3 đó.
    Trả (các profile đã gọi bước lấy token, các tin đã báo).
    """
    # Mốc phải lớn hơn hẳn cửa sổ debounce 30 phút, kẻo lượt này bị coi là vừa
    # thử cách đây 1000 giây và bị bỏ qua trước khi chạm tới thang khôi phục.
    dong_ho = {"t": 1_000_000.0}
    da_lay_token: list[str] = []
    tin: list[str] = []

    def freshen_gia(profile: str, *, khi_toi_luot=None) -> bool:
        dong_ho["t"] += ton_giay
        if khi_toi_luot is not None:
            khi_toi_luot(cho_giay)
        return True

    def reuse_gia(profile: str, email: str) -> str:
        da_lay_token.append(profile)
        return "tok"

    ar._last_attempt.clear()
    with mock.patch.object(ar.time, "time", lambda: dong_ho["t"]), \
            mock.patch.object(ar, "_notify", lambda text, detail=None: tin.append(text)), \
            mock.patch.object(ar, "_freshen_google", freshen_gia), \
            mock.patch.object(ar, "_profile_for", lambda _e: "google-a"), \
            mock.patch.object(ar, "_dong_hang_loat", lambda _e: None), \
            mock.patch.object(ar, "_has_profile", lambda _p: False), \
            mock.patch.object(ar, "_has_google_creds", lambda _p, _e="": True), \
            mock.patch.dict(ar._PROVIDERS["free"], {"reuse": reuse_gia}):
        ar.recover_provider_account({"email": "a@gmail.com"}, "free", "stuck_status=error")
    return da_lay_token, tin


@pytest.mark.pure
def test_xep_hang_lau_van_con_ngan_sach_de_lay_token():
    """Chờ tới lượt KHÔNG được ăn vào ngân sách của lượt khôi phục.

    Trước bản sửa: tài khoản chờ hết 1200 giây thì đăng nhập Google xong là
    dừng, không ai gọi bước lấy token, và chủ máy nhận tin báo thất bại cho
    một tài khoản vừa đăng nhập được.
    """
    cho = ar._RECOVER_BUDGET_S + 600.0
    da_lay_token, tin = _chay_khoi_phuc(cho_giay=cho, ton_giay=cho + 30.0)

    assert da_lay_token == ["google-a"]
    assert any("Khôi phục xong" in t for t in tin)
    assert not any("KHÔNG tự khôi phục được" in t for t in tin)


@pytest.mark.pure
def test_ngan_sach_van_cat_khi_chinh_luot_do_chay_qua_lau():
    """Bỏ thời gian chờ ra khỏi ngân sách, không phải bỏ ngân sách."""
    da_lay_token, tin = _chay_khoi_phuc(
        cho_giay=0.0, ton_giay=ar._RECOVER_BUDGET_S + 600.0)

    assert da_lay_token == []
    assert any("KHÔNG tự khôi phục được" in t for t in tin)


@pytest.mark.pure
def test_tin_bao_keo_theo_so_phut_da_xep_hang():
    _, tin = _chay_khoi_phuc(cho_giay=1800.0, ton_giay=1900.0)

    t3 = [t for t in tin if "[T3]" in t]
    assert t3 and "30 phút xếp hàng" in t3[0]


@pytest.mark.pure
def test_bo_quet_gom_tai_khoan_ket_vao_MOT_luong_tuan_tu():
    accounts = [{"email": f"a{i}@x.com", "status": "error"} for i in range(6)]
    fake_account_service = SimpleNamespace(
        list_accounts=lambda: accounts,
        update_account=lambda *a, **k: None,
    )
    fake_mod = SimpleNamespace(account_service=fake_account_service,
                               account_group=lambda _acc: "free")
    da_tao: list[tuple] = []

    class LuongGia:
        def __init__(self, target=None, args=(), daemon=None, name=None):
            da_tao.append((target, args, name))

        def start(self) -> None:
            pass

    with mock.patch.dict(sys.modules, {"services.account_service": fake_mod}), \
            mock.patch.object(sch.threading, "Thread", LuongGia):
        sch._scan_and_refresh()

    assert len(da_tao) == 1, "sáu tài khoản kẹt vẫn chỉ được MỘT luồng"
    target, args, _ten = da_tao[0]
    assert target is sch._khoi_phuc_lan_luot
    assert len(args[0]) == 6


@pytest.mark.pure
def test_mot_tai_khoan_hong_khong_cat_luot_cac_tai_khoan_sau():
    da_chay: list[str] = []

    def recover(acc: dict, provider: str, reason: str) -> None:
        da_chay.append(acc["email"])
        if acc["email"] == "b@x.com":
            raise RuntimeError("solver chết giữa chừng")

    fake_ar = SimpleNamespace(recover_provider_account=recover)
    with mock.patch.dict(sys.modules, {"services.account_recovery": fake_ar}):
        sch._khoi_phuc_lan_luot(
            [{"email": e, "status": "error"} for e in ("a@x.com", "b@x.com", "c@x.com")])

    assert da_chay == ["a@x.com", "b@x.com", "c@x.com"]
