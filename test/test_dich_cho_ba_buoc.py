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


def test_o_long_tieng_hien_cho_video_va_link_nhung_khong_cho_tep_srt():
    """ĐỔI 18/08: link cũng lồng tiếng được — services.video_tai tải hình về
    nên lý do cũ ("chưa tải cả hình về gateway") hết hiệu lực. Tệp .srt vẫn
    không: nó không có luồng hình nào để thay tiếng."""
    k = _tep()
    assert "7. Lồng tiếng video" in dc.menu_buoc(k)

    dc._pending.clear()
    dc.set_pending(k, url="https://youtu.be/abcdefghijk", ten="YouTube")
    assert "Lồng tiếng video" in dc.menu_buoc(k)

    dc._pending.clear()
    dc.set_pending(k, path="", ten="phim.srt")
    assert "Lồng tiếng video" not in dc.menu_buoc(k)


def test_long_tieng_di_qua_tieng_nguon_va_tieng_dich():
    k = _tep()
    assert dc.tra_loi_buoc(k, "7") == {"tiep": True}
    assert dc.tra_loi_buoc(k, "2") == {"tiep": True}  # nguồn Anh
    ra = dc.tra_loi_buoc(k, "1")                       # đích Việt
    assert ra == {"kieu": "long-tieng", "target": "vi", "nguon": "en"}


def test_ba_buoc_di_het_va_nho_duoc_lua_chon_giua_chung():
    k = _tep()
    assert dc.tra_loi_buoc(k, "3") == {"tiep": True}      # dịch ra bản chữ
    assert "nói tiếng gì" in dc.menu_buoc(k)
    assert dc.tra_loi_buoc(k, "3") == {"tiep": True}      # tệp nói tiếng Nhật
    m = dc.menu_buoc(k)
    assert "từ tiếng Nhật" in m
    ra = dc.tra_loi_buoc(k, "1")                          # sang tiếng Việt
    # target là MÃ TRƠ, không bọc "cap:" — xem test dịch giữa hai tiếng khác.
    assert ra == {"kieu": "chu", "target": "vi", "nguon": "ja"}


def test_tieng_dich_khong_liet_ke_tieng_nguon():
    k = _tep()
    dc.tra_loi_buoc(k, "3")
    dc.tra_loi_buoc(k, "3")            # nguồn = Nhật
    m = dc.menu_buoc(k)
    duoi = m.split("sang tiếng nào")[-1]
    assert "Tiếng Nhật" not in duoi
    # 4 tiếng đích + 1 dòng "giữ nguyên tiếng gốc"
    assert len([d for d in m.splitlines() if d.strip()[:1].isdigit()]) == 5


def test_viec_khong_dich_dung_lai_ngay_sau_tieng_nguon():
    """/stt: việc đã chốt sẵn là chép lời, hỏi tiếp tiếng đích là câu vô nghĩa."""
    k = "k_stt"
    dc.mo_stt(k)
    dc.nap_tep(k, "/tmp/a.mp3", "ghi-am.mp3", 1 << 20)
    ra = dc.tra_loi_buoc(k, "2")                          # tệp nói tiếng Anh
    assert ra == {"kieu": "chu", "target": "giu-goc", "nguon": "en"}


def test_van_chep_loi_duoc_tu_menu_bay_o():
    """Menu bảy ô bỏ hai ô "chép lời" riêng, nhưng KHÔNG bỏ chức năng: nó thành
    lựa chọn cuối ở bước hỏi tiếng đích. Thiếu nó thì video tiếng Anh muốn phụ
    đề tiếng Anh là không bấm được nữa."""
    k = _tep()
    dc.tra_loi_buoc(k, "3")                               # dịch ra bản chữ
    dc.tra_loi_buoc(k, "3")                               # tệp nói tiếng Nhật
    m = dc.menu_buoc(k)
    assert "Giữ nguyên tiếng Nhật" in m
    so_giu = [d.strip()[0] for d in m.splitlines() if "Giữ nguyên" in d][0]
    assert dc.tra_loi_buoc(k, so_giu) == {"kieu": "chu", "target": "giu-goc",
                                          "nguon": "ja"}


def test_phu_de_giu_goc_van_di_tiep_hai_buoc_rieng():
    """Chép lời ra .srt vẫn phải hỏi vị trí chữ và dạng trả — nó vẫn là phụ đề."""
    k = _tep()
    dc.tra_loi_buoc(k, "6")                               # phụ đề
    dc.tra_loi_buoc(k, "2")                               # tệp nói tiếng Anh
    m = dc.menu_buoc(k)
    so_giu = [d.strip()[0] for d in m.splitlines() if "Giữ nguyên" in d][0]
    assert dc.tra_loi_buoc(k, so_giu) == {"tiep": True}
    assert dc.tra_loi_buoc(k, "1") == {"tiep": True}      # chữ ở dưới
    ra = dc.tra_loi_buoc(k, "1")                          # trả .srt
    assert ra["target"] == "giu-goc" and ra["kieu"] == "phu-de"


def test_so_ngoai_menu_va_cau_khong_phai_tra_loi():
    k = _tep()
    assert dc.tra_loi_buoc(k, "8") is None      # bước 1 chỉ có 1..7
    assert dc.tra_loi_buoc(k, "mai mình đi ăn") is None
    assert dc.tra_loi_buoc(k, "thôi") == {"bo": True}


def test_tra_loi_bang_CHU_cung_chon_duoc_o():
    """Ca thật 20/08: chủ máy gõ "Lồng tiếng" chứ không bấm số 7.

    Menu chỉ đọc số thì câu đó rơi xuống LLM — mà lồng tiếng không phải tool
    của LLM, nên nó quay ra đòi gửi lại video vừa gửi.
    """
    k = _tep()
    assert dc.tra_loi_buoc(k, "Lồng tiếng") == {"tiep": True}
    assert (dc.get_pending(k) or {}).get("viec") == "long-tieng"


@pytest.mark.parametrize("cau, viec", [
    ("lồng tiếng giúp em", "long-tieng"),
    ("em muốn lồng tiếng", "long-tieng"),
    ("thuyết minh", "long-tieng"),
    ("Tóm tắt", "tom-tat"),
    ("tóm tắt nội dung", "tom-tat"),
    ("phụ đề", "phu-de"),
    ("ghi chú", "ghi-chu"),
])
def test_nhan_gõ_bang_chu_ra_dung_o(cau, viec):
    k = _tep()
    assert dc.tra_loi_buoc(k, cau) is not None, cau
    xong = dc.get_pending(k) or {}
    # Ô qua LLM trả thẳng kết quả, ba ô còn lại ghi việc rồi hỏi tiếp.
    assert xong.get("viec") == viec or viec in dc.VIEC_QUA_LLM


@pytest.mark.parametrize("cau", [
    "ghi chú lại giúp em cuộc họp hôm qua",   # câu thật, không phải chọn menu
    "dịch",                                    # ô 3 hay ô 6? không đoán
    "mai là thứ mấy",
])
def test_khong_cuop_cau_noi_thuong_lam_lua_chon(cau):
    """Khớp kiểu "có chứa" thì câu thật bị nuốt làm lựa chọn — cố ý không làm."""
    k = _tep()
    assert dc.tra_loi_buoc(k, cau) is None, cau


def test_o_khong_lam_duoc_thi_go_chu_cung_khong_chon_duoc():
    """Tệp .srt không có hình để thay tiếng — nhãn gõ ra vẫn phải bị từ chối."""
    dc.set_pending("k-srt", path="", ten="phu-de.srt")
    assert dc.tra_loi_buoc("k-srt", "lồng tiếng") is None


def test_moi_nhan_chu_deu_tro_vao_mot_o_co_that():
    """Gõ sai mã việc trong bảng thì nhãn đó chết lặng, không ai thấy."""
    for nhan, viec in dc._CHU_THANH_VIEC.items():
        assert viec in dc.VIEC, f"nhãn {nhan!r} trỏ vào mã việc lạ {viec!r}"


def test_cong_tag_nhom_coi_nhan_chu_la_cau_tra_loi():
    """Nhóm bắt tag: gõ "lồng tiếng" mà cổng loại thì menu treo tới lúc hết hạn."""
    k = _tep()
    assert dc.la_cau_tra_loi(k, "lồng tiếng") is True
    assert dc.la_cau_tra_loi(k, "7") is True
    assert dc.la_cau_tra_loi(k, "mai mình đi ăn") is False


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
    dc.tra_loi_buoc(k, "3")               # dịch ra bản chữ
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
