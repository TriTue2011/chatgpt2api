"""Khối persona phải mang ĐỦ năm chiều: giới, tuổi, vùng, nghề, tông.

Bug đã sửa 15/08: nét của TUỔI và NGHỀ chỉ được lấy khi người dùng KHÔNG chọn
gì khác, nên càng chọn kỹ persona càng nhạt — chọn thêm tông là mất luôn
"chững chạc, thực tế" của band 26-40 và "chêm thuật ngữ" của dân IT. Hai chiều
đó chính là thứ làm hai nhân vật cùng tông khác hẳn nhau.
"""

from __future__ import annotations

from services.agent import persona


def _khoi(**sel) -> str:
    return persona.preview(sel)


def test_ba_tong_moi_co_trong_danh_sach_chon():
    tones = persona.ui_options()["tones"]
    for t in ("Vui tươi", "Ma mị", "Ấm áp", "Giang hồ"):
        assert t in tones, f"thiếu tông {t} trong ô chọn"
        assert t in persona.TONE_HINT, f"tông {t} chưa có mô tả cách cư xử"


def test_moi_tong_mang_theo_cach_cu_xu_chu_khong_chi_mot_tinh_tu():
    khoi = _khoi(gender="Nam", age="26-40 tuổi", tone="Ma mị")
    assert "tông ma mị" in khoi.lower()
    assert "rùng rợn ở CÁCH VÍ" in khoi or "cách ví" in khoi.lower()
    assert "số liệu vẫn đúng" in khoi


def test_chon_tong_khong_lam_mat_net_tuoi_va_nghe():
    """Chính là bug cũ: có tone thì AGE_HINT/JOB_HINT bị bỏ."""
    khoi = _khoi(gender="Nam", age="26-40 tuổi", job="Dân IT", tone="Ấm áp")
    assert "chững chạc" in khoi, "mất nét của band tuổi"
    assert "thuật ngữ" in khoi, "mất nét của nghề"
    assert "tông ấm áp" in khoi.lower()


def test_du_ca_nam_chieu_trong_mot_khoi():
    khoi = _khoi(gender="Nữ", age="18-25 tuổi", region="Miền Tây",
                 job="Sinh viên", tone="Vui tươi", voice="Hoạt bát")
    assert "Nữ" in khoi and "18-25" in khoi
    assert "Miền Tây" in khoi and "Sinh viên" in khoi
    assert "nghen" in khoi or "hen" in khoi          # phương ngữ vùng
    assert "tông vui tươi" in khoi.lower()
    assert "hào hứng" in khoi                        # cách cư xử của tông


def test_chon_moi_tong_thi_khong_goi_no_thanh_giong():
    """Bug cũ: nối chuỗi "Giọng " + ", tông ".join() chỉ đúng khi có ĐỦ voice và
    tone; chọn mỗi tông thì ra "Giọng ma mị" — gọi tông thành giọng."""
    khoi = _khoi(tone="Ma mị")
    assert "tông ma mị" in khoi.lower()
    assert "giọng ma mị" not in khoi.lower()
    khoi2 = _khoi(voice="Nhẹ nhàng")
    assert "giọng nhẹ nhàng" in khoi2.lower() and "tông" not in khoi2.split(".")[1].lower()


def test_giang_ho_khong_keo_theo_chui_boi():
    """Chất giang hồ ở nhịp nói và nghĩa khí, không ở lời tục — bot chửi tục
    thì hết đường dùng trong nhà."""
    khoi = _khoi(gender="Nam", age="26-40 tuổi", tone="Giang hồ")
    assert "nghĩa khí" in khoi
    assert "KHÔNG chửi tục" in khoi and "không doạ nạt" in khoi


def test_khong_chon_gi_thi_khong_no_ra_loi():
    khoi = _khoi()
    assert "NHÂN VẬT" in khoi and khoi.strip().endswith(".")


def test_moi_tong_deu_co_kieu_doc_cho_giong_vieneu():
    """Tông thiếu trong _TONE_STYLE thì giọng đọc rơi về kiểu trung tính —
    chọn "Ma mị" mà máy đọc giọng bản tin là công dựng persona đổ sông."""
    for t in persona.ui_options()["tones"]:
        assert persona._TONE_STYLE.get(t), f"tông {t} chưa có kiểu đọc"
