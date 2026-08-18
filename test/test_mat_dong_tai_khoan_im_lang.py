"""Mất một dòng tài khoản thì phải BÁO, không được lặng lẽ.

Vì sao có test này — đo thật 18/08 trên máy chủ đang chạy:

- Pool đánh khoá bằng ``access_token``. Khi một dòng được cấp token đã thuộc về
  dòng khác, ``update_account`` gọi ``self._accounts.pop(new_token, None)`` rồi
  đi tiếp. Không nhật ký, không thông báo.
- Nhật ký cho thấy **21 token** từng bị một dòng "ChatGPT free" vô danh (email
  rỗng) và một tài khoản có tên dùng chung. Chừng ấy dòng đã biến mất mà không
  để lại vết nào — đúng thứ người vận hành báo: "nhiều tài khoản codex tự xoá
  mà không thấy gửi thông tin".
- Hệ quả thứ hai: dòng sống sót mang token không phải của nó, nên chết ngay và
  rơi vào vòng ``dead:periodic_scan`` chạy mãi, trong khi đăng nhập tay vẫn tốt.

Đúng chuỗi sự kiện đo được lúc 01:01 ngày 18/08:

    01:01:32  Thêm ChatGPT free   provider=free  email=""              token=a42cfcbebc
    01:01:35  Cập nhật tài khoản  provider=codex email=nguyenvanviet…  token=a42cfcbebc
"""

from __future__ import annotations

import pytest


def _pool(monkeypatch, tmp_path):
    """Một pool sạch, không đụng dữ liệu thật."""
    from services import account_service as mod

    sv = mod.account_service
    monkeypatch.setattr(sv, "_accounts", {}, raising=False)
    monkeypatch.setattr(sv, "_save_accounts", lambda: None, raising=False)
    return mod, sv


def _bat_thong_bao(monkeypatch):
    """Bắt mọi lời gọi notify_admin mà không gửi đi đâu cả."""
    import services.notifier as notifier

    da_goi: list[str] = []
    monkeypatch.setattr(notifier, "notify_admin",
                        lambda text, **kw: da_goi.append(text), raising=False)
    return da_goi


def _bat_nhat_ky(monkeypatch, mod):
    ghi: list[tuple] = []
    monkeypatch.setattr(mod.log_service, "add",
                        lambda *a, **kw: ghi.append(a), raising=False)
    return ghi


@pytest.mark.pure
def test_dong_khac_danh_tinh_bi_de_thi_phai_bao_admin(monkeypatch, tmp_path):
    """Đúng cảnh 01:01: dòng free vô danh bị tài khoản Codex đè mất."""
    mod, sv = _pool(monkeypatch, tmp_path)
    da_goi = _bat_thong_bao(monkeypatch)
    _bat_nhat_ky(monkeypatch, mod)

    sv._accounts["tok_free"] = {"access_token": "tok_free", "email": "", "status": "error"}
    sv._accounts["tok_codex"] = {"access_token": "tok_codex",
                                 "email": "nguyenvanviet210290@gmail.com",
                                 "status": "active"}

    # Codex đổi khoá sang đúng token dòng free đang giữ.
    sv.update_account("tok_codex", {"access_token": "tok_free"})

    assert "tok_codex" not in sv._accounts
    assert sv._accounts["tok_free"]["email"] == "nguyenvanviet210290@gmail.com"
    assert da_goi, "dòng bị đè mất mà không báo admin — đúng lỗi đã xảy ra thật"
    assert "trùng access_token" in da_goi[0]


@pytest.mark.pure
def test_bao_du_ca_hai_ben_de_con_biet_mat_cai_gi(monkeypatch, tmp_path):
    """Báo mà không nói mất cái nào thì cũng như không."""
    mod, sv = _pool(monkeypatch, tmp_path)
    da_goi = _bat_thong_bao(monkeypatch)
    _bat_nhat_ky(monkeypatch, mod)

    sv._accounts["t1"] = {"access_token": "t1", "email": "ai_do@gmail.com", "status": "active"}
    sv._accounts["t2"] = {"access_token": "t2", "email": "nguoi_khac@gmail.com", "status": "active"}
    sv.update_account("t2", {"access_token": "t1"})

    tin = da_goi[0]
    assert "ai_do@gmail.com" in tin, "không nói rõ mất dòng nào"
    assert "nguoi_khac@gmail.com" in tin, "không nói rõ giữ lại dòng nào"


@pytest.mark.pure
def test_cung_email_thi_chi_ghi_nhat_ky_khong_lam_phien(monkeypatch, tmp_path):
    """Gộp hai dòng CÙNG một tài khoản là chuyện thường — đừng báo động giả.

    Báo động cho mọi lần gộp thì admin sẽ tắt kênh, và lần mất thật sẽ chìm
    theo. Vẫn ghi nhật ký để còn truy được.
    """
    mod, sv = _pool(monkeypatch, tmp_path)
    da_goi = _bat_thong_bao(monkeypatch)
    ghi = _bat_nhat_ky(monkeypatch, mod)

    sv._accounts["t1"] = {"access_token": "t1", "email": "a@gmail.com", "status": "error"}
    sv._accounts["t2"] = {"access_token": "t2", "email": "a@gmail.com", "status": "active"}
    sv.update_account("t2", {"access_token": "t1"})

    assert not da_goi, "cùng một email mà cũng báo động thì admin sẽ tắt kênh"
    assert any("Gộp dòng trùng token" in str(g) for g in ghi), "vẫn phải để lại vết"


@pytest.mark.pure
def test_doi_khoa_binh_thuong_khong_bao_gi(monkeypatch, tmp_path):
    """Làm mới token mà không đụng dòng nào khác thì im lặng là đúng."""
    mod, sv = _pool(monkeypatch, tmp_path)
    da_goi = _bat_thong_bao(monkeypatch)
    ghi = _bat_nhat_ky(monkeypatch, mod)

    sv._accounts["cu"] = {"access_token": "cu", "email": "a@gmail.com", "status": "active"}
    sv.update_account("cu", {"access_token": "moi"})

    assert "moi" in sv._accounts and "cu" not in sv._accounts
    assert not da_goi
    assert not any("trùng access_token" in str(g) for g in ghi)
