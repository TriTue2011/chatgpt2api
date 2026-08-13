"""Đăng bài vào NHÓM Facebook — phần services (config, hàng đợi nền, flow menu).

Phần trình duyệt thật nằm ở captcha-solver, không unit-test được ở đây; các
test này khoá phần code thuần: nhặt link nhóm, hàng đợi giãn cách, dừng cả đợt
khi mất phiên, và menu «Đăng vào nhóm» chạy bằng sentinel không qua LLM.
"""

from __future__ import annotations

import time

import pytest

import services.facebook_group as fbg
import services.facebook_page as fb


class _FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self):
        return self.data

    def update(self, d):
        self.data.update(d)
        return self.data


@pytest.fixture()
def cfg(monkeypatch):
    c = _FakeConfig({"facebook": {"pages": [
        {"id": "111", "name": "Page Nhà", "access_token": "tokA"}]}})
    monkeypatch.setattr(fbg, "config", c)
    monkeypatch.setattr(fb, "config", c)
    return c


# ── Cấu hình nhóm ────────────────────────────────────────────────────────────

@pytest.mark.pure
def test_them_nhom_nhat_moi_link_va_khong_trung(cfg):
    moi = fbg.them_nhom(
        "nhóm 1 https://www.facebook.com/groups/123456/ và nhóm 2 "
        "https://facebook.com/groups/ten.nhom?ref=share xong")
    assert [g["id"] for g in moi] == ["123456", "ten.nhom"]
    # dán lại link cũ → không nhân đôi
    assert fbg.them_nhom("https://facebook.com/groups/123456") == []
    assert len(fbg.nap_nhom()) == 2
    # slug trần cũng nhận
    assert [g["id"] for g in fbg.them_nhom("smarthomevn")] == ["smarthomevn"]
    assert fbg.go_het_nhom() == 3
    assert fbg.nap_nhom() == []


@pytest.mark.pure
def test_auto_share_bat_tat(cfg):
    assert not fbg.auto_share_bat()
    assert fbg.doi_auto_share() is True
    assert fbg.auto_share_bat()
    assert fbg.doi_auto_share() is False


@pytest.mark.pure
def test_bai_cuoi_het_han(cfg, monkeypatch):
    fbg.ghi_bai_cuoi("u1", "bài nè", link="https://vd.com")
    assert fbg.bai_cuoi("u1")["message"] == "bài nè"
    tuong_lai = time.time() + fbg._BAI_TTL + 1
    monkeypatch.setattr(fbg.time, "time", lambda: tuong_lai)
    assert fbg.bai_cuoi("u1") is None


# ── Hàng đợi nền ─────────────────────────────────────────────────────────────

def _cho_xong(gioi_han=5.0):
    t0 = time.time()
    while fbg.dang_chay() and time.time() - t0 < gioi_han:
        time.sleep(0.02)
    assert not fbg.dang_chay(), "hàng đợi phải xong trong giới hạn"


@pytest.mark.pure
def test_chia_se_nen_di_het_cac_nhom(cfg, monkeypatch):
    monkeypatch.setattr(fbg, "_GIAN_CACH_S", (0, 0.01))
    goi = []
    monkeypatch.setattr(fbg, "dang_mot_nhom",
                        lambda gid, msg: (goi.append((gid, msg)),
                                          {"status": "ok"})[1])
    fbg.them_nhom("facebook.com/groups/g1 facebook.com/groups/g2")
    ra = fbg.chia_se_nen("u1", {"message": "bài", "link": "https://vd.com"})
    assert "2 nhóm" in ra
    _cho_xong()
    assert [g for g, _ in goi] == ["g1", "g2"]
    assert all("bài" in m and "https://vd.com" in m for _, m in goi)
    assert all(x.startswith("✅") for x in fbg.ket_qua_gan_nhat())


@pytest.mark.pure
def test_chia_se_nen_mat_phien_dung_ca_dot(cfg, monkeypatch):
    """Nhóm đầu báo chưa đăng nhập → không bắn tiếp các nhóm sau."""
    monkeypatch.setattr(fbg, "_GIAN_CACH_S", (0, 0.01))
    goi = []
    monkeypatch.setattr(fbg, "dang_mot_nhom",
                        lambda gid, msg: (goi.append(gid),
                                          {"status": "chua_dang_nhap"})[1])
    fbg.them_nhom("facebook.com/groups/g1 facebook.com/groups/g2")
    fbg.chia_se_nen("u1", {"message": "bài"})
    _cho_xong()
    assert goi == ["g1"]                          # dừng ngay sau nhóm đầu
    assert any("chưa đăng nhập" in x for x in fbg.ket_qua_gan_nhat())


@pytest.mark.pure
def test_chia_se_nen_tu_choi_khi_dang_chay(cfg, monkeypatch):
    fbg.them_nhom("facebook.com/groups/g1")
    fbg._dang_chay.set()
    try:
        ra = fbg.chia_se_nen("u1", {"message": "bài"})
        assert "đợt trước" in ra
    finally:
        fbg._dang_chay.clear()


@pytest.mark.pure
def test_ghep_bai_khong_lap_link(cfg):
    assert fbg._ghep_bai({"message": "xem https://vd.com nhé",
                          "link": "https://vd.com"}) == "xem https://vd.com nhé"
    assert fbg._ghep_bai({"message": "bài", "link": "https://vd.com"}) \
        == "bài\n\nhttps://vd.com"


# ── Menu «Đăng vào nhóm» — sentinel, không LLM ───────────────────────────────

@pytest.mark.pure
def test_menu_nhom_du_muc(cfg):
    ra = fb.bat_dau_flow("u9", fb.FLOW_NHOM)
    for sen in (fb.NHOM_CHIA_SE, fb.NHOM_THEM, fb.NHOM_AUTO,
                fb.NHOM_LOGIN, fb.NHOM_GO):
        assert sen in ra
    assert "TẮT" in ra                            # auto mặc định tắt


@pytest.mark.pure
def test_them_nhom_qua_flow(cfg):
    fb.xoa_flow("u9")
    assert "LINK nhóm" in fb.bat_dau_flow("u9", fb.NHOM_THEM)
    r = fb.tiep_flow("u9", "đây https://facebook.com/groups/abc123 ạ")
    assert "Đã lưu thêm 1 nhóm" in r["text"]
    assert not fb.co_flow("u9")
    # dán rác → hỏi lại, giữ chờ
    fb.bat_dau_flow("u9", fb.NHOM_THEM)
    assert "hoi" in fb.tiep_flow("u9", "cái gì đó không phải link mấy")
    assert fb.co_flow("u9")
    fb.xoa_flow("u9")


@pytest.mark.pure
def test_chia_se_can_bai_va_can_xac_nhan(cfg, monkeypatch):
    fb.xoa_flow("u9")
    fbg.them_nhom("facebook.com/groups/g1")
    # chưa có bài Page nào → nhắc đăng trước
    fbg._bai_cuoi.clear()
    assert "Chưa có bài Page" in fb.bat_dau_flow("u9", fb.NHOM_CHIA_SE)
    # có bài → hỏi xác nhận, bấm Ok mới chạy
    fbg.ghi_bai_cuoi("u9", "bài hay", link="https://vd.com")
    hoi = fb.bat_dau_flow("u9", fb.NHOM_CHIA_SE)
    assert "bài hay" in hoi and fb.NHOM_OK in hoi
    goi = {}

    def _gia(uid, bai, nhom=None):
        goi["bai"] = bai
        return "📤 ok"

    monkeypatch.setattr(fbg, "chia_se_nen", _gia)
    ra = fb.bat_dau_flow("u9", fb.NHOM_OK)
    assert ra == "📤 ok"
    assert goi["bai"]["message"] == "bài hay"
    assert not fb.co_flow("u9")
    # bấm Ok lần nữa khi không còn gì chờ → nói thẳng
    assert "Không có đợt" in fb.bat_dau_flow("u9", fb.NHOM_OK)


@pytest.mark.pure
def test_chia_se_khi_chua_co_nhom_thi_xin_link(cfg):
    fb.xoa_flow("u9")
    fbg.ghi_bai_cuoi("u9", "bài hay")
    ra = fb.bat_dau_flow("u9", fb.NHOM_CHIA_SE)
    assert "Chưa có nhóm" in ra and "LINK nhóm" in ra
    assert fb.co_flow("u9")
    fb.xoa_flow("u9")
