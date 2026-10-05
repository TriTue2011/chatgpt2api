"""Lịch sinh hoạt THEO TỪNG NGƯỜI (chủ máy 30/09/2026: "chia theo từng người trong gia đình, có thể tự thêm,
căn cứ vào độ tuổi để có list thời gian phù hợp, có thể tự thêm tay") — và dùng được cho mọi nhà."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

_TZ = timezone(timedelta(hours=7))


@pytest.fixture
def lsh(tmp_path):
    from services import lich_sinh_hoat
    lich_sinh_hoat._reset_for_tests(tmp_path / "lich.json")
    yield lich_sinh_hoat
    lich_sinh_hoat._reset_for_tests(tmp_path / "khac.json")


def _luc(thu: int, gio: str) -> float:
    """Thứ (0 = thứ 2) của tuần 28/09/2026 (thứ 2), giờ HH:MM."""
    h, m = map(int, gio.split(":"))
    return (datetime(2026, 9, 28, h, m, tzinfo=_TZ) + timedelta(days=thu)).timestamp()


def test_lich_cu_khong_co_thanh_vien_van_la_ca_nha(lsh, tmp_path):
    (tmp_path / "lich.json").write_text('{"muc": [{"ma": "ngu", "ten": "Cả nhà ngủ", "loai": "ngu", '
                                        '"tu": "21:45", "den": "06:00", "thu": [0,1,2,3,4,5,6]}]}', encoding="utf-8")
    assert lsh.ds()[0]["ai"] == [] and lsh.thanh_vien() == []
    assert lsh.ca_nha("ngu", _luc(0, "23:00")) and not lsh.ca_nha("ngu", _luc(0, "12:00"))


def test_thanh_vien_nhom_tuoi_va_goi_y(lsh):
    nam = datetime.now(_TZ).year
    lsh.dat([], [{"ten": "Bé Na", "nam_sinh": nam - 4}, {"ten": "Ông", "nam_sinh": nam - 70}, {"ten": "Khách"}])
    tv = {x["ten"]: x for x in lsh.thanh_vien()}
    assert (tv["Bé Na"]["nhom"], tv["Bé Na"]["tuoi"]) == ("tre_nho", 4)
    assert tv["Ông"]["nhom"] == "nguoi_gia" and tv["Khách"]["nhom"] is None
    assert tv["Bé Na"]["ma"] == "be_na"
    goi = lsh.goi_y("tre_nho")
    assert any(x["ten"] == "Ngủ trưa" and x["loai"] == "ngu" for x in goi)
    for m, *_ in lsh.NHOM:
        assert lsh.goi_y(m), f"nhóm {m} phải có gợi ý"
        lsh._chuan({**lsh.goi_y(m)[0]})          # gợi ý phải qua được kiểm tra như mục chủ nhà gõ


def test_muc_theo_nguoi_ca_nha_chi_khi_ai_cung(lsh):
    """Một người đi làm KHÔNG phải cả nhà vắng; ai cũng vắng thì mới là cả nhà vắng."""
    lsh.dat([{"ten": "Chồng đi làm", "loai": "vang", "tu": "07:30", "den": "17:30", "thu": [0, 1, 2, 3, 4], "ai": ["Chồng"]},
             {"ten": "Vợ đi làm", "loai": "vang", "tu": "08:00", "den": "17:00", "thu": [0, 1, 2, 3, 4], "ai": ["Vợ"]}],
            [{"ten": "Chồng"}, {"ten": "Vợ"}])
    assert lsh.ds()[0]["ai"] == ["chong"], "web gửi theo tên thành viên mới — lưu theo mã"
    assert not lsh.ca_nha("vang", _luc(0, "07:45"))
    assert lsh.ca_nha("vang", _luc(0, "09:00"))
    assert not lsh.ca_nha("vang", _luc(5, "09:00"))


def test_tro_toi_thanh_vien_khong_co_thi_loi_khong_ghi(lsh):
    lsh.dat([], [{"ten": "An"}])
    with pytest.raises(ValueError, match="không có thành viên"):
        lsh.dat([{"ten": "Ngủ trưa", "loai": "ngu", "tu": "12:00", "den": "13:00", "thu": [0], "ai": ["binh"]}])
    with pytest.raises(ValueError, match="năm sinh"):
        lsh.dat([], [{"ten": "X", "nam_sinh": 1700}])
    assert lsh.ds() == [] and [x["ten"] for x in lsh.thanh_vien()] == ["An"]


def test_doc_cho_bot_neu_ai_va_dang_dien_ra(lsh):
    nam = datetime.now(_TZ).year
    lsh.dat([{"ten": "Ngủ trưa", "loai": "ngu", "tu": "12:00", "den": "14:00", "thu": [0, 1, 2, 3, 4, 5, 6], "ai": ["Bé"]},
             {"ten": "Ăn tối", "loai": "an", "tu": "19:00", "den": "19:45", "thu": [0, 1, 2, 3, 4, 5, 6]}],
            [{"ten": "Bé", "nam_sinh": nam - 3, "theo_doi": ["person.be", "sensor.khong_hop_le"]}])
    dong = lsh.doc_cho_bot(_luc(2, "12:30"))
    assert any("Bé (3 tuổi" in d and "person.be" in d and "sensor" not in d for d in dong)
    assert any("Lịch Bé: Ngủ trưa" in d and "ĐANG DIỄN RA" in d for d in dong)
    assert any("Lịch cả nhà: Ăn tối" in d and "ĐANG" not in d for d in dong)


def test_vai_khuon_mat_tai_khoan_chat_va_khach_quen(lsh, monkeypatch):
    """Chủ máy 05/10/2026: "Bot đã biết ai là chủ nhà, vợ chủ nhà, con chủ nhà, ai là khách chưa … chat qua kênh".
    Mỗi người: vai + khuôn mặt (sổ mặt) + tài khoản chat; khách quen KHÔNG tính vào cả nhà."""
    from services import so_mat_nha
    monkeypatch.setattr(so_mat_nha, "danh_sach_nguoi", lambda: [
        {"id": "2cf4b697e29f", "ten": "Tôi"}, {"id": "a9790070b1f2", "ten": "vợ tôi"}, {"id": "bbbbbbbbbbbb", "ten": "Bà ngoại"}])
    lsh.dat([{"ten": "Chồng đi làm", "loai": "vang", "tu": "07:30", "den": "17:30", "thu": [0, 1, 2, 3, 4], "ai": ["Việt"]},
             {"ten": "Vợ đi làm", "loai": "vang", "tu": "08:00", "den": "17:00", "thu": [0, 1, 2, 3, 4], "ai": ["Vợ"]}],
            [{"ten": "Việt", "vai": "chu_nha", "mat": "2cf4b697e29f", "chat": ["zalop:6643404425553198601"]},
             {"ten": "Vợ", "vai": "vo_chong", "mat": "a9790070b1f2", "chat": ["zalo:41d84c53141afd44a40b"]},
             {"ten": "Cô Lan", "vai": "khach_quen"}])
    assert lsh.ca_nha("vang", _luc(0, "09:00")), "khách quen không phải «cả nhà» — hai vợ chồng vắng là nhà vắng"
    assert lsh.nguoi_cua_phien("zalop_6643404425553198601")["ten"] == "Việt", "chat 1-1: mã chat là người"
    assert lsh.nguoi_cua_phien("zalop_3133467193494275911:u6643404425553198601")["ten"] == "Việt", "nhóm: người gửi"
    assert lsh.nguoi_cua_phien("zalo_41d84c53141afd44a40b")["vai"] == "vo_chong"
    assert lsh.nguoi_cua_phien("zalop_999") is None
    k = lsh.khoi_prompt_nguoi("zalo_41d84c53141afd44a40b")
    assert "«Việt» — chủ nhà" in k and "camera gọi là «Tôi»" in k
    assert "NGƯỜI ĐANG NHẮN VỚI EM: «Vợ» — vợ/chồng chủ nhà" in k
    assert "KHÁCH QUEN:" in k and "«Cô Lan»" in k and "«Bà ngoại» (camera)" in k, "mặt đã đặt tên, chưa gắn ai = khách quen"
    assert "CHƯA được gắn" in lsh.khoi_prompt_nguoi("zalop_999")
    for sai in ({"ten": "X", "vai": "sep"}, {"ten": "X", "chat": ["facebook:1"]}, {"ten": "X", "mat": "khong-hop-le!"}):
        with pytest.raises(ValueError):
            lsh._chuan_tv(sai)


def test_chua_khai_ai_thi_khong_them_gi_vao_loi_tro_chuyen(lsh):
    assert lsh.khoi_prompt_nguoi("zalop_1") == ""
