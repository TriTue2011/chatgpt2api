"""Chấm bộ đề đọc ảnh camera (`services/de_luyen/doc_anh_camera.py`): đáp án là vùng chủ nhà khoanh."""

from services.de_luyen import doc_anh_camera as bo

DA = {"phong": {"Bếp": ["E4", "F4", "E5", "F5"], "Phòng khách": ["H8", "I8", "H9", "I9", "J9", "K9"]},
      "do": ["J1", "J2", "K1"], "trung": ["G7"]}


def test_cham_dung_khi_du_san_va_it_sai():
    bai = {"thay": {"Bếp": ["E4", "F4", "E5", "F5"], "Phòng khách": ["H8", "I8", "H9", "I9", "J9", "K9", "G7"]}}
    assert bo.cham_cho(bai, DA) == []
    assert bo.do(bai, DA)["dung"] and not bo.do(bai, DA)["thieu"], "ô trung lập (G7) không tính"


def test_do_dac_gan_thanh_san_va_nham_phong_la_loi():
    """Lỗi đo 30/09/2026: bot gán cả tủ lạnh vào bếp và lấy sàn phòng khách làm bếp."""
    bai = {"thay": {"Bếp": ["E4", "F4", "E5", "F5", "J1", "J2", "K1", "H8", "I8"],
                    "Phòng khách": ["H9", "I9", "J9", "K9"]}}
    r = bo.do(bai, DA)
    assert sorted(r["nham_do"]) == ["J1", "J2", "K1"] and sorted(r["nham_phong"]) == ["H8", "I8"]
    assert any("gán sai 5 ô" in x for x in bo.cham_cho(bai, DA))


def test_bo_sot_san_va_camera_ngoai_nha():
    assert any("bỏ sót sàn" in x for x in bo.cham_cho({"thay": {"Bếp": ["E4"]}}, DA))
    ngoai = {"phong": {}, "do": [], "trung": []}
    assert bo.cham_cho({"thay": {}}, ngoai) == []
    assert bo.cham_cho({"thay": {"Bếp": ["A1"]}}, ngoai)
    assert bo.cham_cho("không đọc được JSON", DA) == ["bài bị loại: không đọc được JSON"]
