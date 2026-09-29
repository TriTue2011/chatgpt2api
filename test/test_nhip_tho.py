"""Nhịp thơ cho TTS (29/09/2026): nhận ra thể bằng số chữ mỗi dòng, chèn phẩy ở chỗ ngắt nhịp.

Bộ mẫu ``test/data/tho_mau.json``: 111 bài Wikisource (hết bản quyền), 78 bài có thể do người
soạn ghi. Đo trên 1342 câu trả lời thật của bot (runs.sqlite, 73 câu ≥ 4 dòng): 0 câu bị coi là
thơ — văn xuôi nhiều dòng không bị chèn phẩy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import engines, nhip_tho  # noqa: E402

_MAU = json.loads((Path(__file__).parent / "data" / "tho_mau.json").read_text(encoding="utf-8"))
_NHOM = {"that_ngon_bat_cu": "bay_chu", "that_ngon_tu_tuyet": "bay_chu", "bay_chu_tho_moi": "bay_chu",
         "ngu_ngon_tu_tuyet": "ngu_ngon", "ngu_ngon_bat_cu": "ngu_ngon"}


def test_nhan_ra_the_dung_voi_nhan_nguoi_soan():
    co_nhan = [b for b in _MAU if b["nguon_nhan"] == "wikisource"]
    dung = sum(1 for b in co_nhan if nhip_tho.the_tho(b["dong"]) == _NHOM.get(b["the"], b["the"]))
    assert len(co_nhan) >= 70
    assert dung / len(co_nhan) >= 0.95                 # đo 29/09/2026: 76/78


KIEU = "Trăm năm trong cõi người ta\nChữ tài chữ mệnh khéo là ghét nhau\nTrải qua một cuộc bể dâu\nNhững điều trông thấy mà đau đớn lòng"


def test_luc_bat_nhip_chinh_va_day_du():
    chinh = nhip_tho.danh_nhip(KIEU, "chinh").split("\n")
    assert chinh[0] == "Trăm năm, trong cõi người ta"
    assert chinh[1] == "Chữ tài chữ mệnh, khéo là ghét nhau"
    du = nhip_tho.danh_nhip(KIEU, "day_du").split("\n")
    assert du[0] == "Trăm năm, trong cõi, người ta"
    assert du[1] == "Chữ tài, chữ mệnh, khéo là, ghét nhau"
    assert nhip_tho.danh_nhip(KIEU, "tat") == KIEU


def test_that_ngon_4_3_giu_dau_cuoi_dong():
    thu_dieu = ("Ao thu lạnh lẽo nước trong veo,\nMột chiếc thuyền câu bé tẻo teo.\n"
                "Sóng biếc theo làn hơi gợn tí,\nLá vàng trước gió khẽ đưa vèo.")
    ra = nhip_tho.danh_nhip(thu_dieu).split("\n")
    assert ra[0] == "Ao thu lạnh lẽo, nước trong veo,"
    assert ra[3] == "Lá vàng trước gió, khẽ đưa vèo."


def test_song_that_cau_bay_3_4():
    cpn = ("Thuở trời đất nổi cơn gió bụi\nKhách má hồng nhiều nỗi truân chuyên\n"
           "Xanh kia thăm thẳm tầng trên\nVì ai gây dựng cho nên nỗi này")
    ra = nhip_tho.danh_nhip(cpn, "chinh").split("\n")
    assert ra[0] == "Thuở trời đất, nổi cơn gió bụi"
    assert ra[2] == "Xanh kia, thăm thẳm tầng trên"
    assert ra[3] == "Vì ai gây dựng, cho nên nỗi này"
    du = nhip_tho.danh_nhip(cpn, "day_du").split("\n")
    assert du[0] == "Thuở trời đất, nổi cơn gió bụi"          # câu bảy vẫn 3/4
    assert du[2] == "Xanh kia, thăm thẳm, tầng trên"
    assert du[3] == "Vì ai, gây dựng, cho nên, nỗi này"


def test_mac_dinh_la_nhip_day_du():
    """Chủ máy nghe mẫu hai giọng 29/09/2026 rồi chọn nhịp đầy đủ."""
    from services.voice import config as vcfg

    with mock.patch.object(vcfg, "_sub", lambda _k: {}):
        assert vcfg.tts_nhip_tho() == "day_du"
    assert nhip_tho.danh_nhip(KIEU) == nhip_tho.danh_nhip(KIEU, "day_du")


def test_dong_da_co_dau_giua_thi_giu_nguyen():
    tho = "Suối tiễn, oanh đưa, những ngậm ngùi\n" + "\n".join(KIEU.split("\n")[1:]) + "\nTrăm năm trong cõi người ta"
    ra = nhip_tho.danh_nhip(tho).split("\n")
    assert ra[0] == "Suối tiễn, oanh đưa, những ngậm ngùi"


def test_van_xuoi_tam_chu_tu_do_it_dong_khong_doi():
    van = ("Hôm nay trời nắng đẹp.\nNhiệt độ khoảng ba mươi độ.\nChiều có thể mưa rào rải rác ở vài nơi.\n"
           "Anh nhớ mang ô khi ra ngoài.")
    assert nhip_tho.danh_nhip(van) == van
    tam = "Lòng ta là một bài thơ mãnh liệt\nVăng tung lên trên thế giới mông lung\nNức lời ra réo bao niềm bi thiết\nCho thấm thía đủ mùi xuân trai trẻ"
    assert nhip_tho.danh_nhip(tam) == tam
    assert nhip_tho.danh_nhip("Trăm năm trong cõi người ta\nChữ tài chữ mệnh khéo là ghét nhau") \
        == "Trăm năm trong cõi người ta\nChữ tài chữ mệnh khéo là ghét nhau"


def test_bo_mau_moi_bai_co_khuon_deu_duoc_danh_nhip_khong_bai_nao_hong_chu():
    """Chèn phẩy không được làm mất hay đổi chữ nào: bỏ phẩy ra phải về đúng bài gốc."""
    for b in _MAU:
        goc = "\n".join(b["dong"])
        for muc in ("chinh", "day_du"):
            ra = nhip_tho.danh_nhip(goc, muc).replace("\n\n\n", "\n\n")
            assert ra.replace(",", "") == goc.replace(",", ""), b["ten"]


def test_het_kho_tho_nghi_gap_doi_van_xuoi_giu_nguyen():
    kho = KIEU + "\n\n" + KIEU
    ra = nhip_tho.danh_nhip(kho)
    assert "\n\n\n" in ra                                # dấu hết khổ
    kinds = [k for _p, k in engines._tach_doan(ra)]
    assert kinds.count("kho") == 1 and kinds.count("paragraph") == 6
    assert engines._nghi_ms("kho", 350, 0, 600, 0) == 2 * engines._nghi_ms("paragraph", 350, 0, 600, 0)
    # Văn xuôi: một dòng trống vẫn chỉ là tách đoạn (câu trả lời của bot dùng rất nhiều).
    van = "Đoạn đầu đủ dài để đứng một mình.\n\nĐoạn sau cũng đủ dài để đứng một mình."
    assert nhip_tho.danh_nhip(van) == van
    assert [k for _p, k in engines._tach_doan(van)] == ["paragraph", ""]


def test_loa_camera_giu_xuong_dong_cua_bai_tho():
    from services import loa_camera

    doc = []
    with mock.patch("services.voice.engines.synthesize", lambda cau, giong: doc.append(cau) or b"wav"), \
            mock.patch.object(loa_camera, "phat", lambda ten, wav: {"ten": ten, "giay": 1.0}):
        loa_camera.noi("Cam", "  Trăm năm   trong cõi người ta\nChữ tài chữ mệnh\n\n\n\nkhổ sau  ")
    assert doc == ["Trăm năm trong cõi người ta\nChữ tài chữ mệnh\n\nkhổ sau"]
