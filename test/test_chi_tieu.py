"""Chi tiêu theo hũ (chuyển từ chi-tieu-mcp, Quiz99, MIT) — mỗi người một sổ, hũ là dữ liệu."""
from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.chi_tieu import kho, ngan_sach as ns, nghiep_vu as nv  # noqa: E402


@pytest.fixture
def so(tmp_path):
    kho._reset_for_tests(tmp_path / "ct.db")
    s = kho.tao_so("Sổ thử", "u1")
    kho.sua_so(s["id"], luong=10_000_000, ngay_bat_dau=1)
    yield s["id"]


def _hu(so_id, ten):
    return nv.tim_hu(so_id, ten)["id"]


def test_nhan_ky_theo_ngay_bat_dau():
    assert ns.nhan_ky(date(2026, 10, 5), 1) == "2026-10"
    assert ns.nhan_ky(date(2026, 10, 5), 10) == "2026-09"
    assert ns.nhan_ky(date(2026, 1, 3), 10) == "2025-12"
    assert ns.lui_ky("2026-01", 1) == "2025-12"
    assert ns.so_ngay_con_lai(date(2026, 10, 31), 1) == 1


def test_so_moi_co_6_hu_mau_tong_100(so):
    assert len(kho.ds_hu(so)) == 6 and nv.tong_ty_le(so) == 100.0


def test_tim_hu_theo_ten_khong_dau(so):
    assert nv.tim_hu(so, "huong thu")["ten"] == "Hưởng Thụ"
    assert nv.tim_hu(so, "thiết yếu")["ten"] == "Thiết Yếu"
    with pytest.raises(nv.LoiChiTieu):
        nv.tim_hu(so, "không có")


def test_tu_bu_rut_theo_thu_tu_bu(so):
    """Như bản gốc: Thiết Yếu vượt thì rút Hưởng Thụ trước (thu_tu_bu nhỏ nhất), rồi Dự Phòng."""
    nv.ghi_chi(so, "Thiết Yếu", 5_500_000 + 1_200_000, xac_nhan_vuot_tong=True)
    n = ns.tinh(so)
    ty = next(h for h in n["hu"] if h["ten"] == "Thiết Yếu")
    assert ty["duoc_bu"] == 1_200_000
    assert [b["ten"] for b in ty["bu_tu"]] == ["Hưởng Thụ", "Dự Phòng & Tiết Kiệm"]
    assert n["tong_con_lai"] == 10_000_000 - 6_700_000


def test_chi_phi_dac_biet_tru_hu_hung_theo_thu_tu(so):
    nv.ghi_ky("chi_phi_dac_biet", so, "Học phí", 1_500_000)
    n = ns.tinh(so)
    hl = {h["ten"]: h["han_muc_truoc_bu"] for h in n["hu"]}
    assert hl["Dự Phòng & Tiết Kiệm"] == 0 and hl["Hưởng Thụ"] == 500_000
    assert n["tong_ngan_sach"] == 8_500_000


def test_doi_hu_hung_dac_biet_va_ten_trong_canh_bao(so):
    """Lỗi bản gốc: câu cảnh báo ghi cứng «Dự Phòng + Hưởng Thụ». Nay lấy tên thật của hũ hứng."""
    nv.sua_hu(so, _hu(so, "Hưởng Thụ"), ten="Giải Trí")
    nv.ghi_ky("chi_phi_dac_biet", so, "Sửa xe", 3_000_000)
    cb = nv.xem_ngan_sach(so)["canh_bao_chi_phi_dac_biet"]
    assert "Dự Phòng & Tiết Kiệm + Giải Trí" in cb and "Hưởng Thụ" not in cb


def test_cong_vuot_tong_khi_them_va_khi_sua(so):
    """Lỗi bản gốc: sửa khoản chi trên /ui tăng số tiền mà không qua cổng «vượt tổng» như lúc thêm."""
    r = nv.ghi_chi(so, "Thiết Yếu", 9_000_000)
    assert r["da_ghi"]
    r = nv.ghi_chi(so, "Học Tập", 2_000_000)
    assert r["can_xac_nhan"] and not r["da_ghi"]
    id_ = nv.xem_lich_su(so)["giao_dich"][0]["id"]
    hoi = nv.sua_chi(so, id_, so_tien=11_000_000)
    assert hoi.get("can_xac_nhan") and kho.chi_theo_id(so, id_)["so_tien"] == 9_000_000
    assert nv.sua_chi(so, id_, so_tien=11_000_000, xac_nhan_vuot_tong=True)["da_sua"]
    assert nv.sua_chi(so, id_, so_tien=100_000)["da_sua"], "giảm tiền thì không cần hỏi"


def test_tach_giu_ky_va_kiem_tong(so):
    r = nv.ghi_chi(so, "Thiết Yếu", 300_000, "đi chợ + sách")
    with pytest.raises(nv.LoiChiTieu):
        nv.tach_chi(so, r["id"], [{"hu": "Thiết Yếu", "so_tien": 200_000}, {"hu": "Học Tập", "so_tien": 50_000}])
    kq = nv.tach_chi(so, r["id"], [{"hu": "Thiết Yếu", "so_tien": 200_000}, {"hu": "Học Tập", "so_tien": 100_000}])
    assert len(kq["id_moi"]) == 2 and kho.chi_theo_id(so, r["id"]) is None


def test_de_xuat_chia_theo_thu_nhap_cua_tung_ky(so):
    """Lỗi bản gốc: xu hướng chia cho lương cố định, phân bổ đề xuất chia cho thu nhập kỳ hiện tại — hai số khác
    nhau cho cùng một hũ. Nay mỗi kỳ chia cho thu nhập của CHÍNH kỳ đó."""
    hien = ns.ky_hien_tai(kho.so(so))
    ty = _hu(so, "Thiết Yếu")
    for lui in (1, 2, 3):
        k = ns.lui_ky(hien, lui)
        kho.ghi_chi(so, ty, 7_000_000, "", "web", k)
    kho.ghi_ky("thu_nhap_them", so, "thưởng", 10_000_000, hien)       # kỳ hiện tại có thưởng
    tl = ns.ty_le_thuc_te_3_ky(so, hien)
    assert round(tl[ty], 1) == 70.0, "thưởng kỳ này không được kéo % của 3 kỳ trước xuống"
    assert any("Thiết Yếu" in x and "70.0%" in x for x in nv.de_xuat(so)["de_xuat"])


def test_xoa_hu_con_khoan_chi_thi_xoa_mem_va_van_tinh_tong(so):
    h = _hu(so, "Học Tập")
    nv.ghi_chi(so, h, 400_000)
    nv.xoa_hu(so, h)
    assert all(x["id"] != h for x in kho.ds_hu(so))
    assert ns.tinh(so)["tong_da_chi"] == 400_000
    assert nv.xem_lich_su(so)["giao_dich"][0]["hu_ten"] == "Học Tập"


def test_moi_tai_khoan_chi_thay_so_cua_minh(tmp_path):
    """Chủ máy 02/10/2026: "mỗi account chỉ xem được chi tiêu của họ, kể cả admin cũng thế"."""
    kho._reset_for_tests(tmp_path / "ct.db")
    a = nv.so_cua_tai_khoan({"id": "admin", "name": "Chủ", "role": "admin"})
    b = nv.so_cua_tai_khoan({"id": "k2", "name": "Vợ", "role": "user"})
    assert a["id"] != b["id"] and nv.so_cua_tai_khoan({"id": "admin"})["id"] == a["id"]
    nv.ghi_chi(b["id"], "Thiết Yếu", 50_000)
    assert ns.tinh(a["id"])["tong_da_chi"] == 0
    id_b = nv.xem_lich_su(b["id"])["giao_dich"][0]["id"]
    with pytest.raises(nv.LoiChiTieu):
        nv.xoa_chi(a["id"], id_b)          # id của sổ khác: như không tồn tại
    ds = kho.moi_so()
    assert all("tong_da_chi" not in s and "luong" not in s for s in ds), "danh sách cho admin không kèm số tiền"


def test_lien_ket_bang_ma_mot_lan(so):
    m = nv.tao_ma_lien_ket(so)
    assert nv.lien_ket_bang_ma("zalop_123", m["ma"], "Bố")["da_lien_ket"]
    assert nv.so_cua_chat("zalop_123") == so
    with pytest.raises(nv.LoiChiTieu):
        nv.lien_ket_bang_ma("zalop_999", m["ma"])     # mã dùng một lần
    with pytest.raises(nv.LoiChiTieu):
        nv.lien_ket_bang_ma("zalop_999", "12")


def test_cong_ty_giai_chi_khoa_ky(so):
    nv.ghi_cong_ty(so, "tam_ung", 2_000_000, "đi công tác")
    nv.ghi_cong_ty(so, "chi", 1_500_000, "khách sạn")
    assert nv.xem_cong_ty(so)["so_du"] == 500_000
    kq = nv.giai_chi(so)
    assert kq["so_du"] == 500_000 and nv.xem_cong_ty(so)["giao_dich"] == []
    with pytest.raises(nv.LoiChiTieu):
        nv.giai_chi(so)


def test_kiem_dau_vao(so):
    for sai in (0, -5, True, "abc", 1.5, 10**13):
        with pytest.raises(nv.LoiChiTieu):
            nv.ghi_chi(so, "Thiết Yếu", sai)
    assert nv.ghi_chi(so, "Thiết Yếu", "50000")["da_ghi"] and nv.ghi_chi(so, "Thiết Yếu", 50000.0)["da_ghi"]
    with pytest.raises(nv.LoiChiTieu):
        nv.luu_cau_hinh(so, ngay_bat_dau=29)
    with pytest.raises(nv.LoiChiTieu):
        nv.them_hu(so, "thiet yeu")


def test_canh_bao_moc_cao_nhat_mot_lan_moi_ky(so):
    from services.chi_tieu import canh_bao
    kho.gan_kenh("zalop_1", so, "Bố", {}, "admin")
    da: list[str] = []
    gui = lambda so_id, tin: da.append(tin) or 1  # noqa: E731
    nv.ghi_chi(so, "Học Tập", 850_000)                      # 85% hũ Học Tập (1tr)
    kq = canh_bao.kiem_so(so, gui)
    assert [x["nguong"] for x in kq] == [0.8] and "Học Tập" in da[0] and "80%" in da[0]
    assert canh_bao.kiem_so(so, gui) == [], "mốc đã gửi thì thôi"
    nv.ghi_chi(so, "Học Tập", 300_000)                      # 115% → mốc 100%
    kq = canh_bao.kiem_so(so, gui)
    assert kq == [{"khoa": f"hu:{_hu(so, 'Học Tập')}", "nguong": 1.0}] and da[-1].startswith("🔴")


def test_canh_bao_khong_gui_khi_chua_lien_ket_va_gui_loi_thi_thu_lai(so):
    from services.chi_tieu import canh_bao
    nv.ghi_chi(so, "Học Tập", 900_000)
    assert canh_bao.kiem_so(so, lambda *a: 1) == []          # chưa có kênh liên kết
    kho.gan_kenh("tg_1", so, "", {}, "ma")
    assert canh_bao.kiem_so(so, lambda *a: 0) == []          # gửi không được → chưa đánh dấu
    assert canh_bao.kiem_so(so, lambda *a: 1) != []


def test_tool_bot_chi_cham_so_da_lien_ket(so):
    from services.chi_tieu import tool_bot
    r = tool_bot.xu_ly({"viec": "ghi_chi", "hu": "Thiết Yếu", "so_tien": 50000}, {"user_id": "zalop_lạ"})
    assert "chưa có sổ" in r["loi"]
    m = nv.tao_ma_lien_ket(so)
    assert tool_bot.xu_ly({"viec": "lien_ket", "ma": m["ma"]}, {"user_id": "zalop_7"})["da_lien_ket"]
    r = tool_bot.xu_ly({"viec": "ghi_chi", "hu": "thiet yeu", "so_tien": 50000, "ghi_chu": "ăn trưa"},
                       {"user_id": "zalop_7"})
    assert r["da_ghi"] and r["hu"] == "Thiết Yếu"
    assert tool_bot.xu_ly({"viec": "ghi_chi", "hu": "xx", "so_tien": 1}, {"user_id": "zalop_7"})["loi"]
    assert tool_bot.xu_ly({"viec": "xem"}, {"user_id": "zalop_7"})["tong_da_chi"] == 50000
    assert tool_bot.xu_ly({"viec": "bay"}, {"user_id": "zalop_7"})["loi"]


def test_tao_so_dong_thoi_chi_mot_so(tmp_path):
    import threading
    kho._reset_for_tests(tmp_path / "ct.db")
    ra: list[int] = []
    t = [threading.Thread(target=lambda: ra.append(nv.so_cua_tai_khoan({"id": "u9", "name": "A"})["id"])) for _ in range(6)]
    for x in t:
        x.start()
    for x in t:
        x.join()
    assert len(set(ra)) == 1 and len(kho.moi_so()) == 1
