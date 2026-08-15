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
    assert "vào thẳng việc" in khoi, "mất nét của band tuổi"
    assert "cách kiểm chứng" in khoi, "mất nét của nghề"
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
    assert "NHÂN VẬT" in khoi
    assert khoi.strip().endswith("</nhan_vat>")


def test_moi_tong_deu_co_kieu_doc_cho_giong_vieneu():
    """Tông thiếu trong _TONE_STYLE thì giọng đọc rơi về kiểu trung tính —
    chọn "Ma mị" mà máy đọc giọng bản tin là công dựng persona đổ sông."""
    for t in persona.ui_options()["tones"]:
        assert persona._TONE_STYLE.get(t), f"tông {t} chưa có kiểu đọc"


def test_van_phong_khong_duoc_nuot_thong_tin():
    """Nghiên cứu về persona prompt: persona kéo chú ý của model về phía chỉ dẫn
    văn phong và giảm chú ý vào nội dung — nên "nói ngắn kiểu giang hồ" rất dễ
    thành bỏ bớt số liệu. Khối nào cũng phải mang câu chặn đó."""
    for sel in ({}, {"tone": "Giang hồ"}, {"gender": "Nữ", "region": "Huế"}):
        khoi = persona.preview(sel)
        assert "KHÔNG đổi nội dung" in khoi
        assert "không bỏ bớt" in khoi


def test_boc_the_de_tach_lop_ao_khoi_viec():
    khoi = persona.preview({"tone": "Ấm áp"})
    assert khoi.startswith("<nhan_vat>") and khoi.endswith("</nhan_vat>")


def test_tu_ngu_vung_mien_van_con_nguyen():
    """Từ ngữ theo vùng là thứ làm nhân vật nổi bật nhất — cắt token ở chỗ khác,
    không cắt ở đây."""
    hue = persona.preview({"region": "Huế"})
    assert "chi, mô, răng, rứa" in hue and "dạ thưa" in hue
    tay = persona.preview({"region": "Miền Tây"})
    assert "nghen" in tay and "quá trời" in tay


def test_moi_lua_chon_deu_co_mo_ta_rieng():
    """Mục nào trong ô chọn mà thiếu mô tả thì chọn nó cũng như không chọn —
    người dùng bấm mà nhân vật chẳng đổi gì, không ai báo."""
    o = persona.ui_options()
    thieu = []
    for ten, ds, bang in (("tuổi", o["ages"], persona.AGE_HINT),
                          ("giới", o["genders"], persona.GENDER_HINT),
                          ("nghề", o["jobs"], persona.JOB_HINT),
                          ("tông", o["tones"], persona.TONE_HINT),
                          ("vùng", o["regions"], persona.REGION_STYLE)):
        thieu += [f"{ten}: {x}" for x in ds if not bang.get(x)]
    assert not thieu, f"chưa có mô tả: {thieu}"


def test_mo_ta_khong_trung_nhau_giua_cac_muc():
    """Hai mục cùng một câu mô tả nghĩa là chọn khác nhau mà ra giọng y hệt."""
    for ten, bang in (("tuổi", persona.AGE_HINT), ("nghề", persona.JOB_HINT),
                      ("tông", persona.TONE_HINT)):
        gia_tri = list(bang.values())
        assert len(set(gia_tri)) >= len(gia_tri) - 2, (
            f"bảng {ten} có mô tả trùng nhau")


def test_gioi_tinh_vao_duoc_khoi_chu_khong_chi_doi_xung_ho():
    nu = persona.preview({"gender": "Nữ", "age": "26-40 tuổi"})
    nam = persona.preview({"gender": "Nam", "age": "26-40 tuổi"})
    assert "hihi" in nu and "haha" in nam
    assert nu != nam


def test_viec_dich_thi_khong_bom_persona():
    """Dịch cần nguyên văn, không cần được kể lại bằng giọng nhân vật."""
    for cau in ("/dich xin chào",
                "/dịch tiếng nhật: hôm nay trời đẹp",
                "dịch câu này sang tiếng Hàn giúp em",
                "dịch giúp anh đoạn này ra tiếng Anh",
                "translate this please"):
        assert persona.viec_doi_nguyen_van(cau), f"bỏ sót: {cau}"


def test_khong_bat_nham_cuoc_tro_chuyen_thuong():
    """Bắt nhầm thì nhân vật đột ngột biến mất giữa cuộc mà không ai hiểu vì
    sao — hỏng nặng hơn là để bản dịch hơi có giọng."""
    for cau in ("bài dịch của em hay quá",
                "anh đang dịch tài liệu, mệt ghê",
                "em thấy bản dịch này ổn không",
                "tối nay ăn gì",
                "dịch vụ này giá bao nhiêu"):
        assert not persona.viec_doi_nguyen_van(cau), f"bắt nhầm: {cau}"
