"""Menu ba bước cho tệp/link: làm gì → tệp nói tiếng gì → dịch sang tiếng nào.

Ghim ba thứ dễ vỡ:

1. Tiến độ phải ghi vào SỔ CHỜ theo khoá. ``get_pending`` trả BẢN SAO, nên cách
   viết tự nhiên (sửa vào dict vừa lấy ra) là mất trắng bước vừa chọn, và người
   dùng bị hỏi lại vòng vo mà không hiểu vì sao.
2. Tiếng đích không được liệt kê chính tiếng nguồn — chọn "dịch từ Nhật sang
   Nhật" là một lựa chọn vô nghĩa mà vẫn bấm được.
3. Chép lời (giữ nguyên tiếng gốc) phải DỪNG sau bước 2: hỏi tiếp tiếng đích
   cho một việc không dịch là bắt người dùng trả lời câu vô nghĩa.
"""

from __future__ import annotations

import pytest

from services import dich_cho as dc


@pytest.fixture(autouse=True)
def _so_sach():
    dc._pending.clear()
    yield
    dc._pending.clear()


def _tep(key: str = "k1") -> str:
    dc.set_pending(key, path="", ten="phim.mp4", so_byte=5 << 20)
    return key


def test_buoc_1_hoi_lam_gi():
    k = _tep()
    m = dc.menu_buoc(k)
    assert "Em làm gì với tệp này" in m
    for so, nhan, _ in dc.VIEC.values():
        assert f"{so}. {nhan}" in m


def test_tep_video_co_lua_chon_long_tieng_nhung_link_va_phu_de_khong_co():
    k = _tep()
    assert "5. Lồng tiếng video" in dc.menu_buoc(k)

    dc._pending.clear()
    dc.set_pending(k, url="https://youtu.be/abcdefghijk", ten="YouTube")
    assert "Lồng tiếng video" not in dc.menu_buoc(k)

    dc._pending.clear()
    dc.set_pending(k, path="", ten="phim.srt")
    assert "Lồng tiếng video" not in dc.menu_buoc(k)


def test_long_tieng_di_qua_tieng_nguon_va_tieng_dich():
    k = _tep()
    assert dc.tra_loi_buoc(k, "5") == {"tiep": True}
    assert dc.tra_loi_buoc(k, "2") == {"tiep": True}  # nguồn Anh
    ra = dc.tra_loi_buoc(k, "1")                       # đích Việt
    assert ra == {"kieu": "long-tieng", "target": "vi", "nguon": "en"}


def test_ba_buoc_di_het_va_nho_duoc_lua_chon_giua_chung():
    k = _tep()
    assert dc.tra_loi_buoc(k, "1") == {"tiep": True}      # tạo phụ đề
    assert "nói tiếng gì" in dc.menu_buoc(k)
    assert dc.tra_loi_buoc(k, "3") == {"tiep": True}      # tệp nói tiếng Nhật
    m = dc.menu_buoc(k)
    assert "từ tiếng Nhật" in m
    ra = dc.tra_loi_buoc(k, "1")                          # sang tiếng Việt
    # target là MÃ TRƠ, không bọc "cap:" — xem test dịch giữa hai tiếng khác.
    assert ra == {"kieu": "phu-de", "target": "vi", "nguon": "ja"}


def test_tieng_dich_khong_liet_ke_tieng_nguon():
    k = _tep()
    dc.tra_loi_buoc(k, "1")
    dc.tra_loi_buoc(k, "3")            # nguồn = Nhật
    m = dc.menu_buoc(k)
    assert "Tiếng Nhật" not in m.split("sang tiếng nào")[-1]
    assert len([d for d in m.splitlines() if d.strip()[:1].isdigit()]) == 4


def test_chep_loi_dung_lai_sau_khi_biet_tieng_nguon():
    k = _tep()
    assert dc.tra_loi_buoc(k, "3") == {"tiep": True}      # chép lời ra .srt
    ra = dc.tra_loi_buoc(k, "2")                          # tệp nói tiếng Anh
    assert ra == {"kieu": "phu-de", "target": "giu-goc", "nguon": "en"}


def test_chep_loi_ra_ban_chu_la_viec_khac_voi_chep_loi_ra_srt():
    """Ô 4 chính là việc người dùng gọi là STT: không dịch, không mốc giờ, chỉ
    chữ. Ô 3 tuy cũng không dịch nhưng trả .srt đầy số thứ tự với mốc giờ, dán
    vào tài liệu là phải dọn tay."""
    k = _tep()
    assert dc.tra_loi_buoc(k, "4") == {"tiep": True}
    ra = dc.tra_loi_buoc(k, "3")                          # tệp nói tiếng Nhật
    assert ra == {"kieu": "chu", "target": "giu-goc", "nguon": "ja"}


def test_so_ngoai_menu_va_cau_khong_phai_tra_loi():
    k = _tep()
    assert dc.tra_loi_buoc(k, "6") is None      # bước 1 chỉ có 1..5
    assert dc.tra_loi_buoc(k, "mai mình đi ăn") is None
    assert dc.tra_loi_buoc(k, "thôi") == {"bo": True}


def test_phien_het_han_thi_khong_no_ra_loi():
    """Hết hạn thì im, đừng mời chọn cho tệp đã bị dọn mất."""
    assert dc.tra_loi_buoc("khong-co-phien", "1") is None
    assert dc.menu_buoc("khong-co-phien") == ""


def test_chu_van_di_mot_buoc():
    dc.set_pending("k2", chu="xin chào các bạn")
    m = dc.menu_buoc("k2")
    assert "Dịch sang tiếng nào" in m and "làm gì với tệp" not in m


def test_dich_giua_hai_tieng_KHONG_phai_tieng_viet():
    """Nhật → Hàn phải ra ĐÚNG tiếng Hàn.

    Bug tìm ra 15/08: menu cho chọn Nhật→Hàn nhưng trả về "cap:ko", mà
    giai_ma_target giải "cap:xx" thành "cặp Việt ↔ xx": nguồn không phải tiếng
    Việt thì nó luôn trả tiếng VIỆT. Tức người dùng chọn Hàn, máy dịch ra Việt,
    không báo gì.
    """
    k = _tep()
    dc.tra_loi_buoc(k, "1")               # tạo phụ đề
    dc.tra_loi_buoc(k, "3")               # tệp nói tiếng Nhật
    m = dc.menu_buoc(k)
    assert "Tiếng Hàn" in m
    so_han = [d.strip()[0] for d in m.splitlines() if "Tiếng Hàn" in d][0]
    ra = dc.tra_loi_buoc(k, so_han)
    assert ra["target"] == "ko", f"chọn Hàn mà target = {ra['target']}"
    assert ra["nguon"] == "ja"

    from services import translate_service as ts
    assert ts.giai_ma_target(ra["nguon"], ra["target"]) == "ko"


def test_menu_chu_cung_tra_thang_ma_tieng():
    """Đoạn chữ tiếng Nhật chọn "Tiếng Anh" phải ra tiếng Anh, không ra Việt."""
    from services import translate_service as ts
    ra = dc.giai_chon("2", cho_chu=True)          # 2 = Tiếng Anh
    assert ra == {"kieu": "chu", "target": "en"}
    assert ts.giai_ma_target("ja", ra["target"]) == "en"
