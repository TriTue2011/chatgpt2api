"""Cấp quyền dùng bot ngay trong kênh, có thời hạn (chủ máy 03/10/2026). Không gọi mạng."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import admin_workspace as aw, cap_quyen as cq  # noqa: E402
from services.config import config  # noqa: E402

LIEN_HE = {"key": "zalop:acc:555", "bot_id": "acc", "chat_id": "555", "user_id": "555",
           "display_name": "Nguyen Van A", "kind": "user"}


@pytest.fixture
def so(tmp_path, monkeypatch):
    cq._reset_for_tests(tmp_path / "cq.json")
    aw._reset_for_tests(tmp_path / "aw.json")
    cu = dict(config.data.get("thread_filters") or {})
    monkeypatch.setattr(config, "_save", lambda: None)
    yield
    config.data["thread_filters"] = cu


@pytest.mark.parametrize("chu,goi,giay", [
    ("1", "khach", 86400), ("2", "khach", 7 * 86400), ("3", "nguoi_nha", 7 * 86400), ("4", "nguoi_nha", None),
    ("5", "chan", None), ("6", "bo", None), ("khách 3 ngày", "khach", 3 * 86400),
    ("Người nhà 12 giờ", "nguoi_nha", 12 * 3600), ("người nhà mãi mãi", "nguoi_nha", None), ("chặn", "chan", None),
])
def test_doc_lua_chon(chu, goi, giay):
    assert cq.doc_lua_chon(chu) == {"goi": goi, "giay": giay}


@pytest.mark.parametrize("chu", ["có", "hôm nay trời đẹp", "7", "khách sạn ở đâu"])
def test_khong_phai_lua_chon(chu):
    assert cq.doc_lua_chon(chu) is None


def test_tin_bao_kem_lua_chon_va_tra_loi_so_thi_tu_tich(so):
    nhac = aw.start_save_prompt("zalop", "admin1", LIEN_HE)
    assert "Cấp quyền dùng bot" in nhac and "Lưu" in nhac
    tl = aw.handle_admin_text("zalop", "admin1", "3")
    assert "Người nhà" in tl and "Nguyen Van A" in tl
    nhom = config.data["thread_filters"]["zalop:acc:555"]
    assert "homeassistant" in nhom and "camera" in nhom
    assert not set(nhom) & cq.KHONG_TU_CAP, "không bao giờ tự cấp máy chủ/code/…"
    assert aw.get_ws("zalop", "admin1")["contact_aliases"]["zalop:acc:555"] == "Nguyen Van A"
    assert aw.get_pending("zalop", "admin1") is None


def test_het_han_thi_go_va_bao(so):
    cq.cap("zalop", "acc", "555", "khach", 3600, ten="A", now=1000)
    assert cq.het_han(now=2000) == [] and "zalop:acc:555" in config.data["thread_filters"]
    bao = cq.het_han(now=1000 + 3601)
    assert "em đã gỡ quyền" in bao[0] and "zalop:acc:555" not in config.data["thread_filters"]


def test_anh_sua_tay_thi_het_han_khong_dung(so):
    cq.cap("zalop", "acc", "555", "khach", 3600, ten="A", now=1000)
    config.data["thread_filters"]["zalop:acc:555"] = ["web", "camera"]
    assert "sửa tay" in cq.het_han(now=99999)[0]
    assert config.data["thread_filters"]["zalop:acc:555"] == ["web", "camera"]


def test_chan_la_ban_ghi_rong_vinh_vien(so):
    assert "chặn" in cq.cap("zalop", "acc", "555", "chan", None).lower()
    assert config.data["thread_filters"]["zalop:acc:555"] == [] and cq.het_han(now=1e12) == []


def test_buoc_dat_ten_khong_bi_hieu_nham_thanh_cap_quyen(so):
    aw.start_save_prompt("zalop", "admin1", LIEN_HE)
    aw.handle_admin_text("zalop", "admin1", "có")
    tl = aw.handle_admin_text("zalop", "admin1", "Khách")      # tên tự đặt
    assert "Đã lưu **Khách**" in tl and "Cấp quyền dùng bot" in tl
    assert "zalop:acc:555" not in (config.data.get("thread_filters") or {})
    assert "Khách" in aw.handle_admin_text("zalop", "admin1", "1"), "sau khi lưu tên thì hỏi quyền"
    assert "zalop:acc:555" in config.data["thread_filters"]
