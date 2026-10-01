"""Đối chiếu hóa đơn điện tử với Excel danh mục (chủ máy 01/10/2026: "check thông tin với bản excel xem có
đúng không. Ví dụ pdf hóa đơn với excel danh mục")."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import importlib.util  # noqa: E402

import pytest  # noqa: E402

from services import hoa_don as hd  # noqa: E402

#: Ảnh chạy thật có pandas + openpyxl (markitdown[xlsx] kéo theo); uv.lock của CI thì không — như
#: test_office_bo_sung, phần đọc Excel bỏ qua khi thiếu.
can_excel = pytest.mark.skipif(not all(importlib.util.find_spec(m) for m in ("pandas", "openpyxl")),
                               reason="cần pandas + openpyxl")

XML = """<?xml version="1.0" encoding="UTF-8"?>
<HDon xmlns="http://example.com/hddt"><DLHDon Id="d1">
 <TTChung><PBan>2.0.1</PBan><KHMSHDon>1</KHMSHDon><KHHDon>C26TAA</KHHDon><SHDon>123</SHDon><NLap>2026-09-30</NLap></TTChung>
 <NDHDon>
  <NBan><Ten>Công ty TNHH Vật Tư Minh An</Ten><MST>0101234567</MST></NBan>
  <NMua><Ten>Công ty Cổ phần Xây dựng Hà Thành</Ten><MST>0109876543</MST></NMua>
  <DSHHDVu>
   <HHDVu><TChat>1</TChat><STT>1</STT><THHDVu>Xi măng PCB40</THHDVu><DVTinh>Tấn</DVTinh>
     <SLuong>10</SLuong><DGia>1500000</DGia><ThTien>15000000</ThTien><TSuat>10%</TSuat></HHDVu>
   <HHDVu><TChat>1</TChat><STT>2</STT><THHDVu>Thép cuộn D8</THHDVu><DVTinh>kg</DVTinh>
     <SLuong>500</SLuong><DGia>16000</DGia><ThTien>8000000</ThTien><TSuat>10%</TSuat></HHDVu>
   <HHDVu><TChat>1</TChat><STT>3</STT><THHDVu>Cát vàng</THHDVu><DVTinh>m3</DVTinh>
     <SLuong>5</SLuong><DGia>400000</DGia><ThTien>2100000</ThTien><TSuat>10%</TSuat></HHDVu>
  </DSHHDVu>
  <TToan><TgTCThue>25100000</TgTCThue><TgTThue>2510000</TgTThue><TgTTTBSo>27610000</TgTTTBSo></TToan>
 </NDHDon></DLHDon></HDon>"""


@pytest.fixture
def xml(tmp_path):
    x = tmp_path / "hd.xml"
    x.write_text(XML, encoding="utf-8")
    return x


@pytest.fixture
def tep(tmp_path, xml):
    import pandas as pd
    x = xml
    dm = tmp_path / "danh_muc.xlsx"
    # Tiêu đề ở dòng 3 (hai dòng đầu là tên bảng và ngày) — như bảng kế toán thật.
    pd.DataFrame([["DANH MỤC VẬT TƯ NHẬP", None, None, None, None],
                  ["Tháng 9/2026", None, None, None, None],
                  ["STT", "Tên vật tư", "ĐVT", "Số lượng", "Đơn giá"],
                  [1, "Xi măng PCB 40", "Tấn", 10, 1500000],
                  [2, "Thép cuộn D8", "kg", 450, 16000],
                  [3, "Gạch đặc A1", "viên", 2000, 1200],
                  [None, "Cộng", None, None, None]]).to_excel(dm, header=False, index=False)
    return x, dm


def test_doc_xml_bo_namespace(xml):
    h = hd.doc_xml(xml)
    assert h["so"] == "123" and h["ky_hieu"] == "C26TAA" and h["ban"]["mst"] == "0101234567"
    assert [d["ten"] for d in h["dong"]] == ["Xi măng PCB40", "Thép cuộn D8", "Cát vàng"]
    assert h["dong"][0]["sl"] == 10 and h["tong"]["thanh_toan"] == 27610000


def test_kiem_phep_tinh_bat_dong_sai(xml):
    loi = hd.kiem_phep_tinh(hd.doc_xml(xml))
    assert len(loi) == 1 and "Cát vàng" in loi[0] and "2.000.000" in loi[0] and "2.100.000" in loi[0]


@can_excel
def test_doc_bang_tu_tim_dong_tieu_de(tep):
    b = hd.doc_bang(tep[1])
    assert [d["ten"] for d in b["dong"]] == ["Xi măng PCB 40", "Thép cuộn D8", "Gạch đặc A1"]   # bỏ dòng «Cộng»


@can_excel
def test_doi_chieu_bao_lech_va_mot_ben(tep):
    kq = hd.doi_chieu_tep(tep[0], tep[1])
    bc = kq["bao_cao"]
    assert kq["ok"] and "# Đối chiếu hóa đơn C26TAA-123 với danh_muc.xlsx" in bc
    assert "| Thép cuộn D8 | số lượng | 500 | 450 |" in bc
    assert "| Xi măng PCB40 | tên (ghép gần đúng) | Xi măng PCB40 | Xi măng PCB 40 |" in bc
    assert "**Chỉ có trên hóa đơn:** Cát vàng" in bc and "**Chỉ có trong danh mục:** Gạch đặc A1" in bc
    assert "❌ «Cát vàng»" in bc


def test_bang_markdown_tu_pdf_bo_dong_danh_so_cot():
    md = """Số: 0000456
| STT | Tên hàng hóa, dịch vụ | Đơn vị tính | Số lượng | Đơn giá | Thành tiền |
|---|---|---|---|---|---|
| 1 | 2 | 3 | 4 | 5 | 6 = 4 x 5 |
| 1 | Xi măng PCB40 | Tấn | 10 | 1.500.000 | 15.000.000 |
| 2 | Thép cuộn D8 | kg | 500 | 16.000 | 8.000.000 |
|  | Cộng tiền hàng |  |  |  | 23.000.000 |
"""
    d = hd.bang_tu_markdown(md)
    assert [x["ten"] for x in d] == ["Xi măng PCB40", "Thép cuộn D8"] and d[0]["dg"] == 1500000


@can_excel
def test_nhan_tep_gom_du_hai_tep_roi_doi_chieu(tep, tmp_path):
    hd._reset_for_tests()
    with mock.patch("services.agent.luu_tru_day.luu_vao_thu_muc_lam_viec",
                    side_effect=lambda ten, dl: str(tmp_path / ("ws_" + ten))) as luu:
        (tmp_path / "ws_hd.xml").write_bytes(tep[0].read_bytes())
        (tmp_path / "ws_danh_muc.xlsx").write_bytes(tep[1].read_bytes())
        a = hd.nhan_tep("u1", str(tep[0]), "hd.xml")
        assert "Đã nhận hóa đơn" in a and "Excel danh mục" in a
        b = hd.nhan_tep("u1", str(tep[1]), "danh_muc.xlsx")
    assert luu.call_count == 2 and "# Đối chiếu hóa đơn" in b


def test_loi_ro_rang():
    assert "không đọc được XML" in hd.doc_xml(__file__)["loi"]
    assert "hóa đơn phải là" in hd.doc_hoa_don("a.docx")["loi"]


def test_menu_tep_xml_chi_co_doi_chieu():
    from services import pdf_intent as pi
    assert pi.la_hoa_don("HD_0000123.XML") and not pi.la_hoa_don("a.pdf")
    y = pi.y_dinh_cho_hoa_don(None)
    assert y == {pi.DOI_CHIEU}
    assert "🧾" in pi.ask_text("hd.xml", y) and "Đã nhận hóa đơn XML" in pi.ask_text("hd.xml", y)
    assert pi.parse_intent("1", y) == pi.DOI_CHIEU


def test_doi_chieu_voi_excel_khong_thanh_chuyen_excel():
    from services import pdf_intent as pi
    assert pi.parse_intent("đối chiếu với excel") == pi.DOI_CHIEU
    assert pi.parse_intent("chuyển excel") == pi.EXCEL
    assert pi.DOI_CHIEU in pi.allowed_intents({"word"}) and pi.DOI_CHIEU not in pi.y_dinh_cho_office(None)
    assert pi.DOI_CHIEU in pi.them_doi_chieu(pi.y_dinh_cho_office(None), "danh_muc.XLSX", None)
    assert pi.DOI_CHIEU not in pi.them_doi_chieu(pi.y_dinh_cho_office(None), "hop_dong.docx", None)
    assert pi.them_doi_chieu(set(), "a.csv", {"rag"}) == set()          # nhóm không có quyền Office


def test_cong_cu_bot_doc_trong_workspace(tmp_path, monkeypatch, xml):
    monkeypatch.setenv("OFFICECLI_WORKSPACE", str(tmp_path / "ws"))
    from services.agent import capabilities as caps
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "hd.xml").write_bytes(xml.read_bytes())
    ra = caps._h_office_doi_chieu_hoa_don({"tep_hoa_don": "hd.xml", "tep_danh_muc": "khong_co.xlsx"}, {})
    assert "Không đối chiếu được" in ra["text"]
    ra = caps._h_office_doi_chieu_hoa_don({"tep_hoa_don": "/etc/passwd", "tep_danh_muc": "hd.xml"}, {})
    assert "workspace" in ra["text"]


# Chữ PDF trích ra đúng các tật đo được trên hóa đơn thật (01/10/2026, mẫu easyinvoice): tiêu đề «Tên hàng hóa» nằm
# ngoài bảng, STT dính tên hàng, số lượng dính đơn giá, trang 2 thành một dòng chữ liền, gạch chân cắt giữa chữ.
MD_PDF_LECH = """Ký hiệu *(Serial)*: 1C26TAA
Tên hàng hóa, dịch vụ Thành tiền

|STT|Đơn vị tính|Số lượng||Đơn giá||
|---|---|---|---|---|---|
|1 Băng dính trong bản 5cm|Cuộn||2 31.818,181818||63.636|
|2 Pin AA-Energizer|Đôi||4 40.909,090909||163.636|
|3 Dây thép 1,5 ly|Kg||2 45.454,545455||90.909|

(1) (2) (3) (4) (5) (6)=(4)x(5) 4 Dây thép 1ly Kg 2 <u>40.909,090909</u> 81.818 5 MCB 2P - 20A Chiếc 3 200.000 600.000
Cộng tiền hàng *(Sub total)*: 999.999 T<u>iền thuế GTGT (</u>*VAT amount)*: 99.999 Tổng cộng t<u>iền thanh toán (To</u>*tal payment)*: 1.099.998
"""


@can_excel
def test_pdf_lech_cot_neo_theo_ten_danh_muc(tmp_path):
    import pandas as pd
    dm = tmp_path / "dm.xlsx"
    pd.DataFrame([["STT", "Chủng loại vật tư", "ĐVT", "Đơn giá", "Số lượng", "Thành Tiền"],
                  [1, "Băng dính trong bản 5cm", "Cuộn", 31818.181818, 2, 63636.363636],
                  [2, "Pin AA - Energizer", "Đôi", 40909.090909, 4, 163636.363636],
                  [3, "Dây thép 1ly", "Kg", 40909.090909, 2, 81818.181818],
                  [4, "Dây thép 1,5 ly", "Kg", 45454.545455, 3, 136363.636364],
                  [5, "MCB 2P - 20A", "Chiếc", 200000, 3, 600000]]).to_excel(dm, header=False, index=False)
    pdf = tmp_path / "hd.pdf"
    pdf.write_bytes(b"%PDF")
    with mock.patch("services.pdf_intent.extract_markdown", return_value=MD_PDF_LECH):
        kq = hd.doi_chieu_tep(pdf, dm)
    bc = kq["bao_cao"]
    assert kq["ok"] and "tìm từng tên hàng của danh mục" in bc
    assert "| Dây thép 1,5 ly | số lượng | 2 | 3 |" in bc                     # «1,5 ly» không lẫn «1ly»
    assert "Tiền hàng 999.999 + thuế 99.999 = thanh toán 1.099.998" in bc     # nhãn bị gạch chân cắt giữa chữ
    assert "❌ tổng các dòng" not in bc                                       # tổng 5 dòng = 999.999 = cộng tiền hàng


def test_danh_muc_ghi_gia_gom_thue_noi_thang():
    h = {"nguon": "xml", "dong": [{"ten": f"Hàng {i}", "sl": 1.0, "dg": 1000.0 * i, "tt": 1000.0 * i}
                                  for i in range(1, 5)], "tong": {}, "ban": {}}
    d = {"dong": [{"ten": f"Hàng {i}", "sl": 1.0, "dg": 1100.0 * i, "tt": 1100.0 * i} for i in range(1, 5)]}
    assert "ĐÃ GỒM thuế GTGT 10%" in hd.doi_chieu(h, d)
    d["dong"][0]["dg"] = 1500.0                                                   # một dòng lệch thật → không gộp
    assert "ĐÃ GỒM" not in hd.doi_chieu(h, d)


def test_tep_thu_hai_vao_thang_khong_hoi_lai(xml, tmp_path):
    """Chủ máy 01/10/2026: "gửi 1 file trước có lựa chọn đối chiếu, rồi gửi file 2 là xong"."""
    hd._reset_for_tests()
    assert not hd.dang_cho("u9", "dm.xlsx")                       # chưa chọn đối chiếu tệp nào
    with mock.patch("services.agent.luu_tru_day.luu_vao_thu_muc_lam_viec",
                    side_effect=lambda ten, dl: (tmp_path / ten).write_bytes(dl) and str(tmp_path / ten)):
        hd.nhan_du_lieu("u9", xml.read_bytes(), "hd.xml")
    assert hd.dang_cho("u9", "danh_muc.xlsx")                     # đang chờ đúng loại còn thiếu
    assert not hd.dang_cho("u9", "hoa_don_khac.pdf")               # cùng vai với tệp đã có → hiện menu như cũ
    assert not hd.dang_cho("u9", "hop_dong.docx") and not hd.dang_cho("u8", "dm.xlsx")
