"""Theo dõi chủ đề: lưu an toàn, chọn rõ ràng, báo tin không trùng."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


def _patch_dir(tmp_path, monkeypatch):
    import services.config as cfg
    monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path), raising=False)


def test_them_liet_ke_gan_nhat(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt
    assert tt.them("u1", "vụ cháy Hải Dương")
    assert tt.them("u1", "giá vàng")
    ds = tt.liet_ke("u1")
    assert [m["chu_de"] for m in ds] == ["giá vàng", "vụ cháy Hải Dương"]
    assert tt.gan_nhat("u1") == "giá vàng"
    # Mỗi mục mới phải là một bản ghi có trạng thái, không còn chỉ {chu_de, ts}.
    assert ds[0]["id"]
    assert ds[0]["query"] == "giá vàng"
    assert ds[0]["alert_interval_min"] is None
    assert ds[0]["last_checked_at"] is None


def test_khu_trung_khong_dau_va_nang_len_dau(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt
    tt.them("u2", "vụ cháy Hải Dương")
    tt.them("u2", "giá vàng")
    tt.them("u2", "Vụ CHÁY Hải Dương")     # trùng (không dấu) → nâng lên đầu
    ds = tt.liet_ke("u2")
    assert len(ds) == 2
    assert ds[0]["chu_de"] == "Vụ CHÁY Hải Dương"


def test_xoa_chinh_xac_va_rieng_theo_nguoi(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt
    tt.them("uA", "bão số 3")
    tt.them("uB", "chứng khoán")
    # Không được tự xoá mọi mục chỉ vì chứa một từ ngắn mơ hồ.
    assert tt.xoa("uA", "bão") is False
    assert tt.xoa("uA", "bão số 3") is True
    assert tt.liet_ke("uA") == []
    assert tt.xoa("uA", "không tồn tại") is False
    assert [m["chu_de"] for m in tt.liet_ke("uB")] == ["chứng khoán"]


def test_handler_add_list_remove(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import capabilities as caps
    ctx = {"user_id": "uH"}
    out = caps._h_theo_doi_chu_de({"op": "add", "chu_de": "vụ cháy Hải Dương"}, ctx)
    assert "cháy Hải Dương" in out["text"]
    out2 = caps._h_theo_doi_chu_de({"op": "list"}, ctx)
    assert "cháy Hải Dương" in out2["text"]
    out3 = caps._h_theo_doi_chu_de(
        {"op": "remove", "chu_de": "vụ cháy Hải Dương"}, ctx
    )
    assert "bỏ theo dõi" in out3["text"].lower()
    out4 = caps._h_theo_doi_chu_de({"op": "list"}, ctx)
    assert "chưa theo dõi" in out4["text"].lower()


def test_loi_ghi_file_khong_duoc_bao_da_luu(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt

    monkeypatch.setattr(tt, "_ghi_file", lambda _doc: False)
    assert tt.them("u1", "giá vàng") is False
    assert tt.liet_ke("u1") == []


def test_xoa_mo_tra_ve_cac_muc_de_nguoi_dung_chon(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt

    assert tt.them("u1", "bão số 3")
    assert tt.them("u1", "bão Biển Đông")
    matches = tt.tim_muc("u1", "bão")
    assert [m["chu_de"] for m in matches] == ["bão Biển Đông", "bão số 3"]
    assert tt.xoa("u1", "bão") is False


def test_bat_bao_va_tick_chi_gui_ket_qua_chua_thay(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt

    assert tt.them("zalo_123:u456", "giá vàng")
    topic = tt.liet_ke("zalo_123:u456")[0]
    delivery = {"channel": "zalo", "chat_id": "123", "meta": {"bot_id": "9"}}
    assert tt.bat_bao("zalo_123:u456", topic["id"], 60, delivery=delivery, now=999)

    sent: list[tuple[dict, str]] = []
    fetch = lambda _query, _uid: "Giá vàng tăng https://example.test/gold-1"
    deliver = lambda rec, text: sent.append((rec, text))
    assert tt.tick_once(fetcher=fetch, deliver=deliver, now=1_000) == 1
    assert len(sent) == 1
    assert sent[0][0]["delivery"]["chat_id"] == "123"  # không gửi vào khóa :u456

    # Ép tới lượt quét kế tiếp nhưng kết quả y hệt: không báo lại bài đã thấy.
    assert tt.dat_lan_kiem_tra("zalo_123:u456", topic["id"], 1_001)
    assert tt.tick_once(fetcher=fetch, deliver=deliver, now=1_001) == 0
    assert len(sent) == 1


def test_bao_tin_can_bat_ro_rang_va_co_the_tam_dung(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt

    assert tt.them("u1", "bão số 3")
    topic = tt.liet_ke("u1")[0]
    assert topic["alert_interval_min"] is None
    assert tt.bat_bao("u1", topic["id"], 1440, delivery={"channel": "tg", "chat_id": "u1"})
    assert tt.liet_ke("u1")[0]["alert_interval_min"] == 1440
    assert tt.tam_dung_bao("u1", topic["id"])
    assert tt.liet_ke("u1")[0]["alert_interval_min"] is None
