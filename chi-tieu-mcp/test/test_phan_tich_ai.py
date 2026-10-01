"""Test app/phan_tich_ai.py -- đọc câu trả lời JSON của AI cho thẻ "Phân tích
AI" trên /ui (spec 2026-09-23-thiet-ke-lai-ui-design.md, mục "Phân tích AI có
cấu trúc"). AI trả gì cũng không được làm vỡ trang: sai thì None (lùi về
markdown) hoặc bỏ riêng phần sai."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.phan_tich_ai import phan_tich_json

MA = ["thiet_yeu", "gia_dinh", "hoc_tap", "du_phong", "huong_thu", "tu_do_tai_chinh"]
TY_LE = {"thiet_yeu": 55, "gia_dinh": 13, "hoc_tap": 8, "du_phong": 10, "huong_thu": 5, "tu_do_tai_chinh": 9}


def _mau(**ghi_de):
    du_lieu = {
        "tom_tat": "Đã dùng 89% ngân sách.",
        "tung_hu": [{"ma": "thiet_yeu", "danh_gia": "Vượt", "nhan_xet": "Chi gấp 1,78 lần."}],
        "nen_lam": ["Giữ dưới 114.583đ/ngày."],
        "ty_le_goi_y": dict(TY_LE),
    }
    du_lieu.update(ghi_de)
    return json.dumps(du_lieu, ensure_ascii=False)


def test_json_tran_doc_du_4_phan():
    assert phan_tich_json(_mau(), MA) == {
        "tom_tat": "Đã dùng 89% ngân sách.",
        "tung_hu": [{"ma": "thiet_yeu", "danh_gia": "Vượt", "nhan_xet": "Chi gấp 1,78 lần."}],
        "nen_lam": ["Giữ dưới 114.583đ/ngày."],
        "ty_le_goi_y": {ma: float(v) for ma, v in TY_LE.items()},
    }


def test_json_trong_rao_kem_chu_thua_truoc_va_sau():
    van_ban = "Đây là phân tích:\n```json\n" + _mau() + "\n```\nChúc bạn {vui}!"
    assert phan_tich_json(van_ban, MA)["tom_tat"] == "Đã dùng 89% ngân sách."


def test_khong_phai_object_json_hop_le_tra_none():
    for van_ban in ("### Nhận xét\n- ổn", "", "{hỏng", "[1, 2]", '{"a": 1}', None, 5):
        assert phan_tich_json(van_ban, MA) is None


def test_thieu_ca_tom_tat_lan_tung_hu_tra_none():
    assert phan_tich_json(json.dumps({"nen_lam": ["x"], "ty_le_goi_y": TY_LE}), MA) is None


def test_bo_ma_hu_la_trung_va_muc_sai_kieu():
    tung_hu = [
        {"ma": "thiet_yeu", "danh_gia": "Vượt", "nhan_xet": "a"},
        {"ma": "thiet_yeu", "danh_gia": "Trùng", "nhan_xet": "b"},
        {"ma": "khong_co", "danh_gia": "x", "nhan_xet": "y"},
        "chuoi",
        {"ma": "gia_dinh", "danh_gia": 5, "nhan_xet": None},
        {"ma": "hoc_tap", "danh_gia": "Ổn"},
    ]
    ket_qua = phan_tich_json(_mau(tung_hu=tung_hu), MA)
    assert [(m["ma"], m["danh_gia"], m["nhan_xet"]) for m in ket_qua["tung_hu"]] == [
        ("thiet_yeu", "Vượt", "a"), ("hoc_tap", "Ổn", "")]


def test_cat_do_dai_gop_khoang_trang_va_toi_da_5_viec():
    ket_qua = phan_tich_json(_mau(tom_tat="a  \n b" + "x" * 1000, nen_lam=["v" * 500] * 8 + [3, " "]), MA)
    assert ket_qua["tom_tat"].startswith("a b") and len(ket_qua["tom_tat"]) <= 600
    assert len(ket_qua["nen_lam"]) == 5 and all(len(v) <= 200 for v in ket_qua["nen_lam"])
    dai = phan_tich_json(_mau(tung_hu=[{"ma": "gia_dinh", "danh_gia": "d" * 50, "nhan_xet": "n" * 900}]), MA)
    assert len(dai["tung_hu"][0]["danh_gia"]) <= 24 and len(dai["tung_hu"][0]["nhan_xet"]) <= 300


def test_ty_le_goi_y_sai_thi_chi_bo_rieng_phan_do():
    sai = [
        dict(TY_LE, thiet_yeu=70),                               # tổng 115
        {k: v for k, v in TY_LE.items() if k != "gia_dinh"},     # thiếu hũ
        dict(TY_LE, la=0),                                       # thừa mã lạ
        dict(TY_LE, thiet_yeu=True),
        dict(TY_LE, thiet_yeu="55"),
        dict(TY_LE, thiet_yeu=-5, gia_dinh=73),                  # tổng đúng nhưng có số âm
        "55/13/8",
        None,
    ]
    for ty_le in sai:
        ket_qua = phan_tich_json(_mau(ty_le_goi_y=ty_le), MA)
        assert ket_qua is not None and ket_qua["ty_le_goi_y"] is None, ty_le


def test_ty_le_goi_y_lam_tron_1_chu_so_don_phan_du_vao_hu_lon_nhat():
    """AI hay đưa số lẻ tổng 99,9/100,1 sau làm tròn -- /ui chỉ cho lưu khi
    đúng 100, nên dồn phần dư vào hũ lớn nhất để "Điền vào bảng" lưu được ngay."""
    ty_le = {"thiet_yeu": 50.04, "gia_dinh": 12.62, "hoc_tap": 9.97,
             "du_phong": 11.9, "huong_thu": 6.03, "tu_do_tai_chinh": 9.44}
    ket_qua = phan_tich_json(_mau(ty_le_goi_y=ty_le), MA)["ty_le_goi_y"]
    assert round(sum(ket_qua.values()), 1) == 100.0
    assert ket_qua == {"thiet_yeu": 50.1, "gia_dinh": 12.6, "hoc_tap": 10.0,
                       "du_phong": 11.9, "huong_thu": 6.0, "tu_do_tai_chinh": 9.4}


def test_so_vo_cuc_va_long_qua_sau_khong_lam_vo():
    ty_le = ", ".join(f'"{ma}": {"1e999" if ma == "thiet_yeu" else 0}' for ma in MA)
    assert phan_tich_json('{"tom_tat": "x", "ty_le_goi_y": {' + ty_le + "}}", MA)["ty_le_goi_y"] is None
    assert phan_tich_json('{"a":' * 200_000, MA) is None
