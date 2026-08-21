"""Dọn thư viện media — năm cách nói của chủ máy (19/08) thành ba luật.

    "xoá ảnh vừa tạo"                        → VUA_TAO
    "xoá hết ảnh trong thư viện"             → TAT_CA
    "xoá ảnh từ 7 ngày trở về trước"         ┐
    "giữ lại ảnh 7 ngày gần nhất"            ├ CU_HON
    "giữ lại 7 ngày kể từ ảnh tạo lần cuối"  ┘

Hai câu giữa nói ngược nhau mà cùng một phép; câu cuối khác ở MỐC đếm ngược.
"""

from __future__ import annotations

import os
import time

import pytest

from services import media_don as md

NGAY = 86400


def _tep(thu_muc, ten: str, tuoi_ngay: float, noi_dung: bytes = b"x" * 10):
    p = thu_muc / ten
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(noi_dung)
    t = time.time() - tuoi_ngay * NGAY
    os.utime(p, (t, t))
    return p


@pytest.fixture
def kho(tmp_path):
    """Thư viện giả: ảnh 0/3/10/40 ngày tuổi, video 1/9 ngày, nhạc 2 ngày."""
    for ten, tuoi in (("2026/08/19/moi.png", 0), ("2026/08/16/ba-ngay.png", 3),
                      ("2026/08/09/muoi-ngay.jpg", 10), ("cu/bon-muoi.webp", 40)):
        _tep(tmp_path, ten, tuoi)
    _tep(tmp_path, "2026/08/18/clip-moi.mp4", 1)
    _tep(tmp_path, "2026/08/10/clip-cu.mp4", 9)
    _tep(tmp_path, "2026/08/17/nhac_ballad.mp4", 2)
    # Nhiễu phải bị bỏ qua: marker ẩn, thumbnail.
    _tep(tmp_path, ".expire-24h", 0)
    _tep(tmp_path, "2026/08/19/moi_thumb.png", 0)
    return tmp_path


def test_liet_ke_tach_dung_ba_loai(kho):
    anh = [x["rel"] for x in md.liet_ke("image", kho)]
    video = [x["rel"] for x in md.liet_ke("video", kho)]
    nhac = [x["rel"] for x in md.liet_ke("music", kho)]

    assert len(anh) == 4 and all(x.endswith((".png", ".jpg", ".webp")) for x in anh)
    assert "2026/08/19/moi_thumb.png" not in anh, "thumbnail không phải ảnh thư viện"
    # Nhạc là .mp4 tiền tố nhac_ → phải KHÁC video, không lẫn vào nhau.
    assert nhac == ["2026/08/17/nhac_ballad.mp4"]
    assert "2026/08/17/nhac_ballad.mp4" not in video
    assert len(video) == 2


def test_moi_nhat_dung_truoc(kho):
    anh = md.liet_ke("image", kho)
    assert anh[0]["rel"].endswith("moi.png")
    assert anh[-1]["rel"].endswith("bon-muoi.webp")


def test_xoa_anh_vua_tao_chi_lay_dung_mot(kho):
    chon = md.chon("image", md.VUA_TAO, thu_muc=kho)
    assert len(chon) == 1 and chon[0]["rel"].endswith("moi.png")


def test_xoa_video_vua_tao_khong_dung_toi_anh(kho):
    chon = md.chon("video", md.VUA_TAO, thu_muc=kho)
    assert len(chon) == 1 and chon[0]["rel"].endswith("clip-moi.mp4")


def test_xoa_het_anh_trong_thu_vien(kho):
    assert len(md.chon("image", md.TAT_CA, thu_muc=kho)) == 4
    assert len(md.chon("video", md.TAT_CA, thu_muc=kho)) == 2


def test_giu_lai_7_ngay_gan_nhat(kho):
    """Cùng một phép với 'xoá ảnh từ 7 ngày trở về trước'."""
    chon = [x["rel"] for x in md.chon("image", md.CU_HON, so_ngay=7, thu_muc=kho)]
    assert sorted(chon) == ["2026/08/09/muoi-ngay.jpg", "cu/bon-muoi.webp"]


def test_giu_7_ngay_KE_TU_TEP_CUOI_khac_han_dem_tu_hom_nay(kho):
    """Thư viện để yên lâu ngày vẫn phải giữ 7 ngày cuối CÓ HOẠT ĐỘNG.

    Ở đây tệp video mới nhất 1 ngày tuổi, nên mốc lùi về 8 ngày tuổi: clip 9
    ngày bị xoá. Nếu đếm từ hôm nay thì cũng ra thế — nên phép đo thật nằm ở
    test dưới, nơi tệp mới nhất đã rất cũ.
    """
    chon = [x["rel"] for x in md.chon("video", md.CU_HON, so_ngay=7,
                                      moc=md.LAN_CUOI, thu_muc=kho)]
    assert chon == ["2026/08/10/clip-cu.mp4"]


def test_kho_de_yen_lau_ngay_thi_moc_LAN_CUOI_giu_lai_duoc(tmp_path):
    """Toàn bộ thư viện đã 100 ngày tuổi.

    Đếm từ HÔM NAY thì xoá sạch — mất luôn thứ mới nhất người dùng còn cần.
    Đếm từ TỆP CUỐI thì giữ đúng 7 ngày cuối cùng có hoạt động.
    """
    _tep(tmp_path, "a.png", 100)
    _tep(tmp_path, "b.png", 104)
    _tep(tmp_path, "c.png", 120)

    tu_hom_nay = md.chon("image", md.CU_HON, so_ngay=7, thu_muc=tmp_path)
    tu_tep_cuoi = md.chon("image", md.CU_HON, so_ngay=7, moc=md.LAN_CUOI,
                          thu_muc=tmp_path)

    assert len(tu_hom_nay) == 3, "đếm từ hôm nay thì xoá sạch"
    assert [x["rel"] for x in tu_tep_cuoi] == ["c.png"], "giữ a (mốc) và b (trong 7 ngày)"


def test_khong_co_so_ngay_thi_bao_loi_chu_khong_xoa_sach(kho):
    """Quên số ngày mà lặng lẽ coi là 0 thì ngưỡng thành 'bây giờ' → xoá tất."""
    with pytest.raises(md.LoiDonMedia):
        md.chon("image", md.CU_HON, so_ngay=0, thu_muc=kho)


def test_tham_so_la_thi_bao_loi(kho):
    with pytest.raises(md.LoiDonMedia):
        md.chon("image", "xoa-het-di", thu_muc=kho)
    with pytest.raises(md.LoiDonMedia):
        md.chon("image", md.CU_HON, so_ngay=7, moc="hom-qua", thu_muc=kho)
    with pytest.raises(md.LoiDonMedia):
        md.liet_ke("tài liệu", kho)


def test_kho_rong_thi_tra_rong_chu_khong_no(tmp_path):
    assert md.chon("image", md.TAT_CA, thu_muc=tmp_path) == []
    assert md.chon("image", md.VUA_TAO, thu_muc=tmp_path / "chua-co") == []


def test_tom_tat_noi_ro_so_tep_va_khoang_ngay(kho):
    chu = md.tom_tat(md.chon("image", md.TAT_CA, thu_muc=kho))
    assert "4 tệp" in chu and "MB" in chu and "→" in chu
    assert md.tom_tat([]) == "không có tệp nào khớp"


# ── Nối vào bot ────────────────────────────────────────────────────────────
@pytest.fixture
def cap(monkeypatch, kho):
    """Capability delete_media, trỏ thư viện vào kho giả."""
    from services.agent import capabilities as caps
    from services.config import config

    monkeypatch.setattr(type(config), "images_dir",
                        property(lambda self: kho), raising=False)
    return caps


def test_nguoi_thuong_khong_xoa_duoc_thu_vien(cap, kho):
    """Kho CHUNG có ảnh camera, ảnh người khác tạo."""
    kq = cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "tat-ca", "xac_nhan": True}, {"is_admin": False})

    assert "chủ máy" in kq["text"]
    assert len(md.liet_ke("image", kho)) == 4, "không được xoá tệp nào"


def test_lan_goi_dau_chi_dem_chu_khong_xoa(cap, kho):
    kq = cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "tat-ca"},
        {"is_admin": True, "user_id": "preview-only"})

    assert "4 tệp" in kq["text"] and "xác nhận" in kq["text"].lower()
    assert len(md.liet_ke("image", kho)) == 4, "chưa xác nhận thì chưa được xoá"


def test_co_xac_nhan_thi_xoa_that(cap, kho):
    ctx = {"is_admin": True, "user_id": "xoa-anh"}
    cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "vua-tao"}, ctx)
    cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "vua-tao", "xac_nhan": True}, ctx)

    con = [x["rel"] for x in md.liet_ke("image", kho)]
    assert len(con) == 3 and not any(x.endswith("moi.png") for x in con)


def test_xac_nhan_chi_xoa_dung_tep_da_xem_truoc(cap, kho):
    """Media sinh thêm sau preview không được lọt vào lệnh xoá đã duyệt."""
    ctx = {"is_admin": True, "user_id": "chu-may"}
    cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "vua-tao"}, ctx)
    moi_hon = _tep(kho, "2026/08/21/moi-hon.png", -1)

    cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "vua-tao", "xac_nhan": True}, ctx)

    assert moi_hon.exists(), "tệp sinh sau preview chưa từng được người dùng duyệt"
    assert not (kho / "2026/08/19/moi.png").exists(), "phải xoá đúng tệp đã preview"


def test_tep_bi_ghi_de_cung_kich_thuoc_sau_preview_thi_bo_qua(cap, kho):
    """mtime là epoch lớn: không được dùng rel_tol mặc định của math.isclose."""
    ctx = {"is_admin": True, "user_id": "ghi-de-cung-size"}
    dich = kho / "2026/08/19/moi.png"
    mtime_cu = dich.stat().st_mtime
    cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "vua-tao"}, ctx)

    dich.write_bytes(b"y" * 10)
    os.utime(dich, (mtime_cu + 0.5, mtime_cu + 0.5))
    kq = cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "vua-tao", "xac_nhan": True}, ctx)

    assert dich.exists(), "nội dung đã thay sau preview không còn là tệp được duyệt"
    assert "Bỏ qua 1 tệp" in kq["text"]


def test_tep_bi_thay_sau_buoc_kiem_tra_thi_khong_bi_xoa(cap, kho, monkeypatch):
    """Chặn khe TOCTOU giữa media_don.stat() và image_service.delete_images()."""
    from services import image_service

    ctx = {"is_admin": True, "user_id": "thay-ngay-truoc-unlink"}
    dich = kho / "2026/08/19/moi.png"
    cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "vua-tao"}, ctx)
    mtime_da_duyet = dich.stat().st_mtime
    xoa_that = image_service.delete_images

    def _thay_roi_xoa(*args, **kwargs):
        ban_moi = kho / "ban-moi-tam.png"
        ban_moi.write_bytes(b"z" * 10)
        os.utime(ban_moi, (mtime_da_duyet, mtime_da_duyet))
        os.replace(ban_moi, dich)
        return xoa_that(*args, **kwargs)

    monkeypatch.setattr(image_service, "delete_images", _thay_roi_xoa)
    kq = cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "vua-tao", "xac_nhan": True}, ctx)

    assert dich.exists(), "tệp thay vào sau bước kiểm tra chưa từng được duyệt"
    assert dich.read_bytes() == b"z" * 10
    assert "Bỏ qua 1 tệp" in kq["text"]


def test_xoa_video_khong_dung_toi_anh_va_nhac(cap, kho):
    ctx = {"is_admin": True, "user_id": "xoa-video"}
    cap.CAPABILITIES["delete_media"].handler(
        {"kind": "video", "che_do": "tat-ca"}, ctx)
    cap.CAPABILITIES["delete_media"].handler(
        {"kind": "video", "che_do": "tat-ca", "xac_nhan": True}, ctx)

    assert md.liet_ke("video", kho) == []
    assert len(md.liet_ke("image", kho)) == 4, "ảnh phải còn nguyên"
    assert len(md.liet_ke("music", kho)) == 1, "nhạc phải còn nguyên"


def test_thieu_so_ngay_thi_bao_chu_khong_xoa_sach(cap, kho):
    kq = cap.CAPABILITIES["delete_media"].handler(
        {"kind": "image", "che_do": "cu-hon", "xac_nhan": True}, {"is_admin": True})

    assert "chưa xoá được" in kq["text"]
    assert len(md.liet_ke("image", kho)) == 4


def test_la_capability_CHANGE_de_qua_cong_duyet(cap):
    """Xoá phải đi qua cổng duyệt của orchestrator như mọi hành động đổi trạng thái."""
    assert cap.CAPABILITIES["delete_media"].risk == cap.CHANGE
    assert cap._CAP_GROUP["delete_media"] == cap._CAP_GROUP["library_media"]
