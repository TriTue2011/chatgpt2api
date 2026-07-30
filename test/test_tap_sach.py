"""TẬP của quyển sách — đoán, lưu, và ghi đè đúng phạm vi.

Vì sao có bộ test này: kho gộp cả hai tập của một môn dưới cùng lớp–môn, và
trước bản này không đâu ghi TẬP cả. Ba hậu quả người dùng đã nêu đích danh:
danh sách sách "chưa rõ ràng đã có tập bao nhiêu"; "nạp thêm hay ghi đè không
có tập nào nên ghi đè hay nạp có thể sai" (ghi đè xoá theo cả môn — nạp tập
hai làm mất tập một); và bốn loại kho trông như bị gộp làm một vì bảng tổng chỉ
đếm file .md của sách học sinh.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TW = ROOT / "services" / "agent" / "teacher_workspace.py"


def _detect():
    """Nạp riêng detect_volume — module đầy đủ cần fitz."""
    src = TW.read_text("utf-8")
    i = src.index("_VOL_RE = re.compile(")
    j = src.index("def import_sgk_pdf")
    ns: dict = {"re": re}
    exec(src[i:j], ns)  # noqa: S102
    return ns["detect_volume"]


class TestDoanTap:
    @pytest.mark.parametrize("ten,mong", [
        # tên tệp THẬT trên máy chủ (đã gây ra vụ "chưa rõ tập")
        ("2026-07-20_0839_SGK_Toán_4_KNTT_tập_1.pdf", "tập một"),
        ("SGK Toán 4 KNTT tập 2.pdf", "tập hai"),
        # slug kho taphuan — dấu nối là gạch ngang, không dấu
        ("sgk-tieng-viet-5-tap-hai.4699750731", "tập hai"),
        ("sgk-toan-5-tap-mot.4699756373", "tập một"),
        # tiêu đề người gõ
        ("Toán 4 tập một", "tập một"),
        ("Ngữ văn 12, tập hai", "tập hai"),
        ("Tiếng Anh 8 Global Success Volume 1", "tập một"),
    ])
    def test_doan_dung(self, ten, mong):
        assert _detect()(ten) == mong

    @pytest.mark.parametrize("ten", [
        "SGK Lịch sử và Địa lí 5",          # một quyển cả năm — không có tập
        "tmp_sgk_toan4.pdf",                 # không nói gì về tập
        "shs-tieng-anh-7-global-success",    # cả năm
        "tap hop va phan tu",                # "tập hợp" ≠ "tập 1" — không khớp bừa
    ])
    def test_khong_doan_bua(self, ten):
        assert _detect()(ten) == ""

    def test_nhieu_nguon_lay_nguon_dau_khop(self):
        f = _detect()
        assert f("không rõ", "SGK Toán 4 tập 2.pdf") == "tập hai"


class TestGhiDeTheoTap:
    def test_replace_gui_where_khi_co_tap(self):
        src = TW.read_text("utf-8")
        i = src.index('if mode == "replace":')
        body = src[i:src.index("Best-effort", i)]
        assert '"volume"' in body and '"where"' in body, \
            "replace không thu hẹp theo tập — nạp tập hai sẽ xoá luôn tập một"
        assert "if vol:" in body, "phải phân nhánh: có tập mới thu hẹp"

    def test_hub_forget_nhan_where(self):
        hub = (ROOT / "vn-mcp-hub" / "src" / "main.py").read_text("utf-8")
        i = hub.index('@app.post("/api/rag/forget/{collection}")')
        body = hub[i:i + 4000]
        assert 'body.get("where")' in body
        # where chỉ nhận vô hướng — dict/list lồng là mở đường "khớp mọi thứ"
        assert "isinstance(v, (str, int, float, bool))" in body
        # điều kiện where phải THAM GIA lọc, không chỉ được parse
        assert "all((m or {}).get(k) == v for k, v in loc.items())" in body

    def test_volume_di_vao_metadata_khi_nap(self):
        src = TW.read_text("utf-8")
        i = src.index("def push_sgk_to_rag")
        body = src[i:i + 5000]
        assert '"volume": volume' in body.replace("**({", "").replace("} if volume else {})", ""), \
            "chunk nạp mới không mang tập thì ghi đè theo tập không bao giờ khớp"

    def test_danh_sach_pdf_co_tap(self):
        src = TW.read_text("utf-8")
        i = src.index("def list_imports")
        body = src[i:i + 3000]
        assert '"volume": detect_volume(pdf.name)' in body


class TestThongKeKhoTheoLoai:
    def test_hub_co_endpoint_thong_ke(self):
        hub = (ROOT / "vn-mcp-hub" / "src" / "main.py").read_text("utf-8")
        assert '/api/rag/thong-ke/{collection}' in hub
        i = hub.index('/api/rag/thong-ke/{collection}')
        body = hub[i:i + 2500]
        for khoa in ('"grade"', '"subject"', '"volume"'):
            assert khoa in body, f"thống kê thiếu chiều {khoa}"

    def test_app_gom_du_nam_kho(self):
        api = (ROOT / "api" / "teacher.py").read_text("utf-8")
        i = api.index("kho-theo-loai")
        body = api[i:i + 3000]
        for kind in ('"sgk"', '"sgv"', '"vbt"', '"tap_huan"', '"slide"'):
            assert kind in body, f"bảng kho theo loại thiếu {kind}"
