"""Hai dòng tranh cùng một access_token thì Codex được ưu tiên.

Vì sao có test này — chủ máy chốt 21/08/2026 sau khi nhận thông báo:

    ⚠️ Mất một dòng tài khoản (trùng access_token)
    Bị đè mất: (không có email) · free · error
    Giữ lại  : smarthomebanbap2011@gmail.com · free

``update_account`` cho dòng ĐANG VÀO thắng vô điều kiện, nên một dòng free
re-key trúng token của tài khoản Codex là xoá luôn ``refresh_token`` — mất
credential OAuth, phải đăng nhập lại bằng tay.

Luật mới:

1. Codex thắng free.
2. Trừ khi dòng Codex đang nghỉ hạn — quota Codex và quota web free là hai
   đồng hồ khác nhau trên cùng một tài khoản, nên lúc đó giữ dòng free để tài
   khoản vẫn chạy được đường web.
3. Nhường chỗ thì credential OAuth vẫn được cất sang dòng sống dưới tiền tố
   ``codex_``, kèm mốc nghỉ hạn, để sau còn đăng nhập lại Codex.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _pool(monkeypatch):
    """Một pool sạch, không đụng dữ liệu thật."""
    from services import account_service as mod

    sv = mod.account_service
    monkeypatch.setattr(sv, "_accounts", {}, raising=False)
    monkeypatch.setattr(sv, "_save_accounts", lambda: None, raising=False)
    monkeypatch.setattr(mod.log_service, "add", lambda *a, **kw: None, raising=False)
    import services.notifier as notifier
    monkeypatch.setattr(notifier, "notify_admin", lambda text, **kw: None, raising=False)
    return mod, sv


def _sau(gio: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=gio)).isoformat()


def _truoc(gio: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=gio)).isoformat()


@pytest.mark.pure
def test_codex_dung_duoc_thi_free_khong_duoc_de(monkeypatch):
    """Dòng free re-key trúng token Codex → Codex ở lại, credential còn nguyên."""
    mod, sv = _pool(monkeypatch)

    sv._accounts["tok_codex"] = {"access_token": "tok_codex", "type": "codex",
                                 "email": "chu@gmail.com", "status": "active",
                                 "refresh_token": "rt-that"}
    sv._accounts["tok_free"] = {"access_token": "tok_free", "type": "free",
                                "email": "", "status": "active"}

    sv.update_account("tok_free", {"access_token": "tok_codex"})

    con_lai = sv._accounts["tok_codex"]
    assert "tok_free" not in sv._accounts
    assert con_lai["refresh_token"] == "rt-that", "mất credential OAuth của Codex"
    assert con_lai["email"] == "chu@gmail.com"
    assert mod.account_group(con_lai) == mod.GROUP_CODEX


@pytest.mark.pure
def test_codex_dang_nghi_han_thi_nhuong_cho_free(monkeypatch):
    """Codex hết quota → giữ dòng free để tài khoản vẫn chạy đường web."""
    mod, sv = _pool(monkeypatch)

    het_nghi = _sau(5)
    sv._accounts["tok_codex"] = {"access_token": "tok_codex", "type": "codex",
                                 "email": "chu@gmail.com", "status": "limited",
                                 "restore_at": het_nghi, "refresh_token": "rt-that",
                                 "expires_at": 1770000000, "device_id": "dev-1"}
    sv._accounts["tok_free"] = {"access_token": "tok_free", "type": "free",
                                "email": "chu@gmail.com", "status": "active"}

    sv.update_account("tok_free", {"access_token": "tok_codex"})

    con_lai = sv._accounts["tok_codex"]
    assert con_lai["type"] == "free", "phải là dòng free thì mới chạy được đường web"
    assert con_lai["status"] == "active"
    # Credential Codex được cất lại, KHÔNG vứt.
    assert con_lai["codex_refresh_token"] == "rt-that"
    assert con_lai["codex_expires_at"] == 1770000000
    assert con_lai["codex_device_id"] == "dev-1"
    assert con_lai["codex_type"] == "codex"
    # Mốc thời gian để sau còn đăng nhập lại Codex.
    assert con_lai["codex_limited_at"], "không lưu thời điểm bị limit"
    assert con_lai["codex_restore_at"] == het_nghi


@pytest.mark.pure
def test_dong_free_giu_lai_khong_bi_keo_ve_pool_codex(monkeypatch):
    """Cất credential mà làm dòng free hoá codex thì giữ nó cũng vô nghĩa.

    `account_group` xếp "gói trả phí + có refresh_token" vào pool codex. Nếu
    cất thẳng vào `refresh_token`, một tài khoản plus vừa nhường chỗ sẽ quay
    lại đúng cái pool đang nghỉ và ăn 429 tiếp.
    """
    mod, sv = _pool(monkeypatch)

    sv._accounts["tok_codex"] = {"access_token": "tok_codex", "type": "codex",
                                 "plan": "plus", "email": "chu@gmail.com",
                                 "status": "limited", "restore_at": _sau(5),
                                 "refresh_token": "rt-that"}
    sv._accounts["tok_free"] = {"access_token": "tok_free", "type": "free",
                                "plan": "plus", "email": "chu@gmail.com",
                                "status": "active"}

    sv.update_account("tok_free", {"access_token": "tok_codex"})

    con_lai = sv._accounts["tok_codex"]
    assert not con_lai.get("refresh_token"), "cất thẳng vào refresh_token là kéo về pool codex"
    assert mod.account_group(con_lai) == mod.GROUP_FREE


@pytest.mark.pure
def test_limited_khong_co_han_nghi_van_la_dang_nghi(monkeypatch):
    """`limited` mà không biết bao giờ hồi thì cũng không dùng được."""
    mod, sv = _pool(monkeypatch)

    sv._accounts["tok_codex"] = {"access_token": "tok_codex", "type": "codex",
                                 "email": "chu@gmail.com", "status": "limited",
                                 "refresh_token": "rt-that"}
    sv._accounts["tok_free"] = {"access_token": "tok_free", "type": "free",
                                "email": "chu@gmail.com", "status": "active"}

    sv.update_account("tok_free", {"access_token": "tok_codex"})

    assert sv._accounts["tok_codex"]["type"] == "free"
    assert sv._accounts["tok_codex"]["codex_refresh_token"] == "rt-that"


@pytest.mark.pure
def test_han_nghi_da_qua_thi_codex_van_thang(monkeypatch):
    """Sắp được hồi thì đừng nhường — `revive_stuck_limited` sẽ bật lại ngay."""
    mod, sv = _pool(monkeypatch)

    sv._accounts["tok_codex"] = {"access_token": "tok_codex", "type": "codex",
                                 "email": "chu@gmail.com", "status": "limited",
                                 "restore_at": _truoc(2), "refresh_token": "rt-that"}
    sv._accounts["tok_free"] = {"access_token": "tok_free", "type": "free",
                                "email": "chu@gmail.com", "status": "active"}

    sv.update_account("tok_free", {"access_token": "tok_codex"})

    con_lai = sv._accounts["tok_codex"]
    assert con_lai["refresh_token"] == "rt-that"
    assert mod.account_group(con_lai) == mod.GROUP_CODEX


@pytest.mark.pure
def test_hai_dong_cung_loai_thi_giu_nep_cu(monkeypatch):
    """Đều free (hoặc đều Codex) → dòng đang vào thắng, y như trước."""
    mod, sv = _pool(monkeypatch)

    sv._accounts["t1"] = {"access_token": "t1", "type": "free",
                          "email": "cu@gmail.com", "status": "error"}
    sv._accounts["t2"] = {"access_token": "t2", "type": "free",
                          "email": "moi@gmail.com", "status": "active"}

    sv.update_account("t2", {"access_token": "t1"})

    assert sv._accounts["t1"]["email"] == "moi@gmail.com"
    assert "t2" not in sv._accounts


@pytest.mark.pure
def test_codex_nhuong_cho_thi_bao_kem_moc_nghi_han(monkeypatch):
    """Không mất gì, nhưng vẫn phải báo — kèm giờ để còn login lại Codex."""
    from services import account_service as mod
    import services.notifier as notifier

    sv = mod.account_service
    monkeypatch.setattr(sv, "_accounts", {}, raising=False)
    monkeypatch.setattr(sv, "_save_accounts", lambda: None, raising=False)
    monkeypatch.setattr(mod.log_service, "add", lambda *a, **kw: None, raising=False)
    da_goi: list[str] = []
    monkeypatch.setattr(notifier, "notify_admin",
                        lambda text, **kw: da_goi.append(text), raising=False)

    het_nghi = _sau(5)
    sv._accounts["tok_codex"] = {"access_token": "tok_codex", "type": "codex",
                                 "email": "chu@gmail.com", "status": "limited",
                                 "restore_at": het_nghi, "refresh_token": "rt-that"}
    sv._accounts["tok_free"] = {"access_token": "tok_free", "type": "free",
                                "email": "chu@gmail.com", "status": "active"}

    sv.update_account("tok_free", {"access_token": "tok_codex"})

    assert da_goi, "Codex nhường chỗ mà im lặng thì không ai biết đường login lại"
    tin = da_goi[0]
    assert "nghỉ hạn" in tin
    assert het_nghi in tin, "không nói bao giờ hết nghỉ thì mốc thời gian vô dụng"
    assert "Mất một dòng tài khoản" not in tin, "không mất gì mà báo động giả"


# ─────────────────────────────────────────────────────────────────────────────
# Nhường chỗ rồi thì phải TỰ lấy lại — không bắt người vận hành login bằng tay.
# ─────────────────────────────────────────────────────────────────────────────


def _dong_da_nhuong_cho(nghi_tu: str, het_nghi: str | None) -> dict:
    """Đúng hình dạng dòng free sau khi Codex nhường chỗ cho nó."""
    return {
        "access_token": "tok", "type": "free", "email": "chu@gmail.com",
        "status": "active",
        "codex_refresh_token": "rt-that", "codex_expires_at": 1770000000,
        "codex_device_id": "dev-1", "codex_project_id": "prj-1",
        "codex_type": "codex", "codex_limited_at": nghi_tu,
        "codex_restore_at": het_nghi,
    }


@pytest.mark.pure
def test_het_han_nghi_thi_tu_bat_lai_codex(monkeypatch):
    """Trọn vòng đời: nhường chỗ → hết hạn → credential về đúng chỗ cũ."""
    mod, sv = _pool(monkeypatch)
    sv._accounts["tok"] = _dong_da_nhuong_cho("2026-08-21 01:00:00", _truoc(1))

    da_bat = sv.khoi_phuc_codex_het_nghi()

    assert da_bat == ["tok"]
    con_lai = sv._accounts["tok"]
    assert con_lai["refresh_token"] == "rt-that"
    assert con_lai["expires_at"] == 1770000000
    assert con_lai["device_id"] == "dev-1"
    assert con_lai["project_id"] == "prj-1"
    assert "codex" in con_lai["type"].split(",")
    assert mod.account_group(con_lai) == mod.GROUP_CODEX
    # Chỗ cất tạm phải dọn sạch, không thì lần sau bật lại lần nữa.
    assert not [k for k in con_lai if k.startswith("codex_")]


@pytest.mark.pure
def test_chua_het_han_nghi_thi_de_yen(monkeypatch):
    """Bật sớm là ăn 429 tiếp — đúng thứ việc nhường chỗ định tránh."""
    mod, sv = _pool(monkeypatch)
    sv._accounts["tok"] = _dong_da_nhuong_cho("2026-08-21 01:00:00", _sau(5))

    assert sv.khoi_phuc_codex_het_nghi() == []
    con_lai = sv._accounts["tok"]
    assert not con_lai.get("refresh_token")
    assert con_lai["codex_refresh_token"] == "rt-that"


@pytest.mark.pure
def test_khong_co_han_nghi_thi_dem_tu_luc_bi_limit(monkeypatch):
    """Upstream không báo hạn → không được giam dòng đó vĩnh viễn."""
    from datetime import datetime as _dt

    mod, sv = _pool(monkeypatch)
    gan_day = (_dt.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    lau_roi = (_dt.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")

    sv._accounts["tok"] = _dong_da_nhuong_cho(gan_day, None)
    assert sv.khoi_phuc_codex_het_nghi() == [], "mới 2 giờ mà đã bật lại"

    sv._accounts["tok"] = _dong_da_nhuong_cho(lau_roi, None)
    assert sv.khoi_phuc_codex_het_nghi() == ["tok"], "30 giờ rồi vẫn nằm chờ"


@pytest.mark.pure
def test_dong_khong_cat_gi_thi_khong_dung_toi(monkeypatch):
    """Quét cả pool nhưng chỉ đụng đúng dòng có credential cất tạm."""
    mod, sv = _pool(monkeypatch)
    sv._accounts["thuong"] = {"access_token": "thuong", "type": "free",
                              "email": "ai_do@gmail.com", "status": "active"}

    assert sv.khoi_phuc_codex_het_nghi() == []
    assert sv._accounts["thuong"]["type"] == "free"


@pytest.mark.pure
def test_quota_watcher_co_goi_bo_bat_lai(monkeypatch):
    """Điểm đấu nối: viết đúng hàm rồi quên cắm thì nó không bao giờ chạy."""
    from services import quota_watcher as qw

    da_goi: list[int] = []
    monkeypatch.setattr(qw.account_service, "list_accounts", lambda: [], raising=False)
    monkeypatch.setattr(qw.account_service, "revive_stuck_limited",
                        lambda **kw: [], raising=False)
    monkeypatch.setattr(qw.account_service, "khoi_phuc_codex_het_nghi",
                        lambda: da_goi.append(1) or [], raising=False)

    qw.QuotaWatcher._rebuild(qw.quota_watcher)

    assert da_goi, "quota_watcher không gọi khoi_phuc_codex_het_nghi — bộ bật lại nằm chết"
