"""Sơ đồ nhà (29/09/2026): code đo bằng chứng, bot vẽ, người chấm rồi mới áp; nhìn lại bằng camera
chỉ đếm người trong vùng của phòng."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services import so_do_nha as sd  # noqa: E402
from services.de_luyen import hieu_so_do_nha as bo  # noqa: E402


@pytest.fixture
def so(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "_PATH", tmp_path / "so_do_nha.json")
    return sd


def test_o_va_diem_chan():
    assert sd.o_cua(0.0, 0.0) == "A1" and sd.o_cua(0.99, 0.99) == "H6" and sd.o_cua(1.2, -1) == "H1"
    assert sd.diem_chan([0.2, 0.4, 0.1, 0.5]) == pytest.approx((0.25, 0.9))


def test_kiem_va_cham_roi_ap(so):
    uv = bo.DE[0]["uv"]
    bai = {"kieu": "chung_cu", "so_tang": 1,
           "phong": [{"ten": "Phòng khách", "thong_voi": ["Bếp"]}, {"ten": "Bếp", "thong_voi": ["Phòng khách"]}],
           "cua_chinh": {"vao": "Phòng khách"},
           "camera": [{"ten": "Cam phòng khách", "thay": {"Phòng khách": ["E5"], "Bếp": ["A5"]}}], "chac": 0.8}
    k = so.kiem(bai, uv)
    assert isinstance(k, dict) and bo.cham_cho(k, bo.DE[0]["dap_an"]) == ["Phòng ngủ–Phòng khách không được ghi thông"
                                                                          ] or bo.cham_cho(k, {"kieu": "chung_cu"}) == []
    assert "không có trong đề" in so.kiem({**bai, "camera": [{"ten": "Cam lạ", "thay": {}}]}, uv)
    assert "ô phải dạng" in so.kiem({**bai, "camera": [{"ten": "Cam phòng khách", "thay": {"Bếp": ["Z9"]}}]}, uv)
    assert "không có trong danh sách" in so.kiem({**bai, "phong": [{"ten": "Bếp", "thong_voi": ["Sân"]}]}, uv)
    with so._khoa:
        d = so._nap()
        d["bai"].append({"id": 1, "luc": 0, "gia_tri": k, "ket_qua": "cho"})
        so._luu(d)
    assert so.ap() is None, "chưa chấm thì chưa áp"
    assert so.cham(1, True, cham_boi="chu_may")
    assert so.o_cua_phong("Cam phòng khách", "Bếp") == {"A5"}
    de = so.doan_de("Phòng khách")
    assert any("THÔNG với: Bếp" in x for x in de) and any("Cam phòng khách thấy Phòng khách" in x for x in de)


@pytest.mark.parametrize("d", bo.DE, ids=[d["ten"] for d in bo.DE])
def test_de_luyen_dung_khuon(d):
    de = bo.de_cho(d)
    assert "A. PHÒNG" in de and "C. CAMERA" in de and "E. CHỦ NHÀ MÔ TẢ" in de
    for a, b in d["dap_an"].get("thong", []) + d["dap_an"].get("khong_thong", []):
        assert a in de and b in de


def test_nhin_lai_chi_dem_nguoi_trong_vung_phong(so, monkeypatch):
    """Camera bếp thấy cả phòng khách: người đứng ở ô của bếp không giữ đèn phòng khách."""
    from services import camera_nha, kich_hoat_nha as kh, mqtt_nha
    with so._khoa:
        d = so._nap()
        d["ap"] = {"kieu": "chung_cu", "phong": [], "camera": [
            {"ten": "Cam bếp", "thay": {"Phòng khách": ["A6", "B6"], "Bếp": ["E2", "F2"]}}]}
        so._luu(d)
    monkeypatch.setattr(camera_nha, "danh_sach", lambda: [{"name": "Cam bếp", "src": "bep"}])
    monkeypatch.setattr(mqtt_nha, "dem_nguoi", lambda: {"bep": {"nguoi": 1}})
    ev = {"box": [0.6, 0.1, 0.1, 0.2]}                      # chân ở F2 — trong bếp
    monkeypatch.setattr(so, "_frigate", lambda duong, timeout=60: [{"data": ev}])
    assert kh._nhin_lai(["Cam bếp"], "Phòng khách") == "", "người nấu ăn ở bếp: phòng khách vẫn vắng"
    assert kh._nhin_lai(["Cam bếp"], "") == "Cam bếp", "không biết khu thì đếm cả khung"
    ev["box"] = [0.05, 0.6, 0.1, 0.35]                      # chân ở A6 — phần phòng khách
    assert kh._nhin_lai(["Cam bếp"], "Phòng khách") == "Cam bếp"


def test_doc_anh_camera_ke_luoi_yolo_bot_chia_o_roi_vao_so(so, tmp_path, monkeypatch):
    """Chủ máy 29/09/2026: "dùng cam để đo theo mô tả của tôi. Chụp ảnh mà phân tích", "dùng yolo để xác
    nhận lại". Code chụp, kẻ lưới, YOLO khoanh đồ vật; bot (model thị giác) chia ô; kết quả vào sổ như lời
    mô tả nguồn «anh:<camera>», đọc lại thì thay bản cũ."""
    import numpy as np

    from services import camera_nha, ha_client, hieu_thiet_bi_nha as ht, nhin_nha, yolo_nha

    anh = np.zeros((600, 800, 3), np.uint8)
    anh[:, :, 2] = 90                                         # ảnh màu (ban ngày)
    assert not so.la_anh_dem(anh) and so.la_anh_dem(np.full((60, 80, 3), 77, np.uint8))

    class Vat:
        nhan, diem, hop, ten = "refrigerator", 0.9, (0, 100, 200, 500), "tủ lạnh"
    assert so.mo_ta_vat(Vat(), 800, 600) == "tủ lạnh (refrigerator, 90%) — chân ô B6, trải A2–C6"
    assert so.ve_luoi(anh, [Vat()])[:2] == b"\xff\xd8"

    monkeypatch.setattr(so, "_ANH_DIR", tmp_path / "anh")
    monkeypatch.setattr(camera_nha, "chup", lambda ten, timeout=20.0: (ten, b"jpeg"))
    monkeypatch.setattr(yolo_nha, "doc_anh", lambda b: anh)
    monkeypatch.setattr(nhin_nha, "vat_the", lambda a: [Vat()])
    monkeypatch.setattr(so, "_ten_phong", lambda: ["Bếp", "Phòng khách"])
    monkeypatch.setattr(ht, "huong_dan", lambda ten: ("HƯỚNG DẪN", "v1"))
    monkeypatch.setattr(ha_client, "get_states", lambda: [])
    de: list[str] = []
    tra = ['{"thay": {"Bếp": ["A5", "B5"], "Phòng khách": ["E6"]}, "moc": "tủ lạnh ở A5", "chac": 0.8}']
    monkeypatch.setattr(so, "_goi_thi_giac", lambda noi, jpeg: de.append(noi) or tra[0])
    so.them_mo_ta("Bếp tính từ thùng gỗ xanh tới cửa ban công")
    r = so.doc_anh_camera("Cam bếp")
    assert r["ok"] and r["thay"] == {"Bếp": ["A5", "B5"], "Phòng khách": ["E6"]}
    assert "tủ lạnh (refrigerator" in de[0] and "thùng gỗ xanh" in de[0] and "Bếp, Phòng khách" in de[0]
    assert (tmp_path / "anh" / "Cam bếp.jpg").exists()
    tra[0] = '{"thay": {"Bếp": ["A5"]}, "chac": 0.9}'
    so.doc_anh_camera("Cam bếp")
    anh_mo_ta = [x for x in so.so()["mo_ta"] if x["nguon"] == "anh:Cam bếp"]
    assert len(anh_mo_ta) == 1 and "Bếp: ô A5" in anh_mo_ta[0]["noi_dung"], "đọc lại thì thay bản cũ"
    assert "thùng gỗ xanh" not in de[1].split("CHỦ NHÀ MÔ TẢ:")[0]
    assert "Ảnh Cam bếp" not in de[1], "lần đọc sau không lấy bài đọc ảnh cũ làm lời chủ nhà"
    tra[0] = '{"thay": {"Phòng học": ["A1"]}}'
    assert "không có trong nhà" in so.doc_anh_camera("Cam bếp")["loi"]
    tra[0] = '{"thay": {"Bếp": ["Z9"]}}'
    assert "ô phải dạng" in so.doc_anh_camera("Cam bếp")["loi"]


def test_de_bay_duong_di_frigate():
    de = sd.de({"phong": {}, "cung_bao": [], "camera": {}, "cua": {}, "ten": {},
                "duong": {"Cam bếp": [["C3", "F5", 40], ["A1", "B2", 25]], "Cam cửa": []}}, [], [])
    assert "C2. ĐƯỜNG ĐI" in de and "- Cam bếp: C3→F5 (40), A1→B2 (25)" in de and "Cam cửa" not in de
    assert "C2. ĐƯỜNG ĐI" not in sd.de({"phong": {}, "cung_bao": [], "camera": {}, "cua": {}, "ten": {}}, [], [])
