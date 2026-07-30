"""Bộ lọc lớp–môn khi tra kho SGK (kb_giao_vien._loc + teacher_lecture).

Vì sao có bộ test này: kho SGK gộp cả 12 lớp trong MỘT collection, và tra cứu đi
qua ``hybrid_query`` — mà "hybrid" ở hub nghĩa là KB + web search, KHÔNG có BM25,
tức chỉ có ngữ nghĩa thuần. Embedding không mang thông tin "lớp mấy" vì sách các
lớp dùng chung từ vựng môn học. Đo thật trên kb_giao_duc (585 chunk, 12 lớp) ngày
2026-07-29:

    hỏi kèm tên lớp trong câu ("Toán 9 định lí Viète")   → đúng  4/12
    thêm neo "lop=9 mon=toan" vào câu hỏi                → đúng  0/8  (tệ hơn!)
    lọc theo metadata grade/subject                      → đúng 12/12

Nên đường đúng là LỌC, không phải mong vector tự đoán. Test khoá hai điều:
bộ lọc sinh ra đúng cú pháp Chroma, và tầng gọi (teacher_lecture) không được
quên truyền lop/mon — quên là bài giảng lớp 1 trích sách lớp 7.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "vn-mcp-hub"
if str(HUB) not in sys.path:
    sys.path.insert(0, str(HUB))


def _loc():
    """Nạp riêng hàm _loc, không import cả module (module cần fastmcp)."""
    src = (HUB / "src" / "kb" / "giao_vien.py").read_text("utf-8")
    m = re.search(r"_MON_HOP_LE = frozenset\(.*?\n\)\n", src, re.S)
    f = re.search(r"\ndef _loc\(.*?\n    return dk\[0\].*?\n", src, re.S)
    assert m and f, "không tìm thấy _MON_HOP_LE / _loc trong giao_vien.py"
    ns: dict = {"frozenset": frozenset}
    exec(m.group(0) + f.group(0), ns)  # noqa: S102 — chạy đúng 2 khối đã trích
    return ns["_loc"]


class TestLocLopMon:
    def test_du_ca_lop_va_mon(self):
        assert _loc()(4, "tviet") == {
            "$and": [{"grade": {"$eq": 4}}, {"subject": {"$eq": "tviet"}}]
        }

    def test_chi_co_lop(self):
        assert _loc()(9, "") == {"grade": {"$eq": 9}}

    def test_chi_co_mon(self):
        assert _loc()(0, "hoa") == {"subject": {"$eq": "hoa"}}

    def test_khong_co_gi_thi_khong_loc(self):
        """Không lọc phải trả None — KHÔNG phải {} (Chroma coi {} là lọc rỗng và
        báo lỗi ValueError, làm mọi lượt tra chết thay vì tra rộng)."""
        assert _loc()(0, "") is None

    @pytest.mark.parametrize("lop", [0, 13, 99, -1, "x", None])
    def test_lop_ngoai_khoang_bi_bo(self, lop):
        assert _loc()(lop, "") is None

    @pytest.mark.parametrize("mon", ["li", "vatly", "physics", "TOÁN", "", "sudia_"])
    def test_ma_mon_la_bi_bo(self, mon):
        """Mã môn phải khớp SUBJECTS thật. `li` là bẫy đã mắc: mã đúng là `ly`,
        gieo mục lục thành lop10-li.json thì UI không thấy môn Vật lí."""
        got = _loc()(0, mon)
        assert got is None or got == {"subject": {"$eq": mon.strip().lower()}}

    def test_ma_mon_dung_duoc_nhan(self):
        for m in ("toan", "tviet", "van", "anh", "sudia", "su", "dia", "ly",
                  "hoa", "sinh"):
            assert _loc()(0, m) == {"subject": {"$eq": m}}

    def test_mon_khong_phan_biet_hoa_thuong(self):
        assert _loc()(0, " Ly ") == {"subject": {"$eq": "ly"}}


class TestTangGoiKhongQuenTruyen:
    """teacher_lecture PHẢI truyền lop/mon xuống cả ba kho."""

    def test_ba_lan_goi_deu_co_loc(self):
        src = (ROOT / "services" / "agent" / "teacher_lecture.py").read_text("utf-8")
        assert 'loc = {"lop": g, "mon": sub}' in src, "thiếu bộ lọc lớp–môn"
        for tool in ("ask_sgk", "ask_sgv", "ask_phan_bo"):
            i = src.index(f'_kb("{tool}"')
            doan = src[i:i + 400]
            assert "**loc" in doan, f"{tool} gọi mà không truyền lop/mon"

    def test_hub_nhan_tham_so(self):
        src = (HUB / "src" / "kb" / "giao_vien.py").read_text("utf-8")
        for tool in ("ask_sgk", "ask_sgv", "ask_bai_tap", "ask_phan_bo"):
            m = re.search(rf"def {tool}\((.*?)\) -> str:", src, re.S)
            assert m, f"không thấy tool {tool}"
            assert "lop: int" in m.group(1) and "mon: str" in m.group(1), \
                f"{tool} chưa nhận lop/mon"

    def test_where_xuyen_het_cac_tang(self):
        """where phải đi hết retriever → hybrid → kb_ask, không rơi ở tầng nào."""
        ret = (HUB / "src" / "rag" / "retriever.py").read_text("utf-8")
        hyb = (HUB / "src" / "rag" / "hybrid.py").read_text("utf-8")
        kba = (HUB / "src" / "kb" / "hybrid_search.py").read_text("utf-8")
        assert "where: dict[str, Any] | None = None" in ret
        assert 'kw["where"] = where' in ret
        assert "where=where" in hyb and "where: dict[str, Any] | None = None" in hyb
        assert "where: dict | None = None" in kba and "where=where" in kba


class TestDuongNapGanMetadata:
    """Chunk nạp MỚI phải có grade/subject, nếu không bộ lọc sẽ bỏ qua nó.

    Đây là nửa còn lại của cùng một việc: lọc mà dữ liệu mới không có khoá lọc
    thì sách vừa nạp biến mất khỏi kết quả — không báo lỗi, nhìn y như chưa nạp.
    Cả bốn đường nạp SGK (upload file, dán URL, kho tập huấn, seed) đều đi qua
    ``push_sgk_to_rag``, nên chỉ cần khoá ở đó và ở hub.
    """

    def test_push_gui_metadata_tuong_minh(self):
        src = (ROOT / "services" / "agent" / "teacher_workspace.py").read_text("utf-8")
        i = src.index("def push_sgk_to_rag")
        than = src[i:i + 4000]
        assert '"metadata": {' in than, "push_sgk_to_rag chưa gửi metadata"
        for khoa in ('"grade": int(grade or 0)', '"subject": subject', '"kind"'):
            assert khoa in than, f"thiếu {khoa} trong metadata gửi lên hub"

    def _than_curate(self) -> str:
        """Thân hàm `rag_curate`, cắt tới HÀM KẾ TIẾP chứ không phải N byte.

        Bản cũ dùng ``src[i:i + 3000]``. Hàm đó dài ra (thêm suy `kind`, thêm
        tiền tố `tay/`) nên chốt cần soi trôi ra NGOÀI cửa sổ 3000 byte, và test
        đỏ dù mã vẫn đúng — đúng loại test tự hỏng theo thời gian, làm người sửa
        đi tìm lỗi ở chỗ không có lỗi.
        """
        src = (HUB / "src" / "main.py").read_text("utf-8")
        i = src.index('@app.post("/api/rag/curate/{collection}")')
        j = src.find("\n    @app.", i + 10)
        return src[i:j if j > i else len(src)]

    def test_hub_nhan_metadata_va_suy_tu_source(self):
        than = self._than_curate()
        # Hai tiền tố: `teacher_sgk/` (đường nạp của dự án) và `tay/` (nạp tay).
        # Chỉ khớp `teacher_sgk` thì 18 đoạn SGK Tiếng Việt lớp 1–2 nạp tay không
        # có nhãn lớp–môn — đếm thì thấy tăng, hỏi theo lớp thì không ra.
        assert r'r"^(?:teacher_sgk|tay)/lop(\d{1,2})/([a-z_]+)/"' in than, \
            "hub không suy grade/subject từ source cho CẢ HAI tiền tố"
        assert 'body.get("metadata")' in than, "hub không nhận metadata tường minh"
        assert '**extra' in than, "metadata không được trộn vào metadatas"

    def test_hub_khong_cho_ghi_de_source(self):
        """metadata do client gửi KHÔNG được ghi đè source/chunk — hai khoá này là
        xương sống để xoá theo nguồn (``/api/rag/forget``) và đánh số đoạn."""
        assert 'if k in ("source", "chunk")' in self._than_curate()

    def test_hub_suy_kind_du_ca_nam_kho(self):
        """Suy `kind` từ tên kho phải biết CẢ NĂM loại.

        Đây là đường dự phòng khi client không gửi `metadata.kind`. Thiếu
        `_tailieu` thì mọi đoạn tài liệu tập huấn tự khai `kind="sgk"` — đúng lỗi
        đo được ở phía client ngày 2026-07-30, chỉ khác chỗ xảy ra.
        """
        than = self._than_curate()
        for hau_to in ("_vbt", "_slide", "_sgv", "_tailieu"):
            assert f'endswith("{hau_to}")' in than, f"hub không nhận kho {hau_to}"
