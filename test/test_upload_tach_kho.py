"""File TẢI LÊN phải vào ĐÚNG kho theo loại, không dồn hết vào kho học sinh.

Bất đối xứng đã đo (2026-07-29):

  · `/api/teacher/import-url`  → CÓ `kind`, và với link taphuan thì `doc_kind()`
    đọc được loại thật từ slug (sgv-, vbt-, tai-lieu-…). Đúng.
  · `/api/teacher/import-sgk`  → KHÔNG có `kind` nào. `import_sgk_bytes` cũng
    không có. Nên MỌI file tải lên rơi vào `kb_giao_duc` — kho NỘI DUNG HỌC
    SINH — và thông báo còn ghi cứng đúng tên kho đó, khiến người vận hành tưởng
    đã tách kho.

Hệ quả: tải lên một quyển sách giáo viên thì gợi ý soạn giảng nằm lẫn trong kho
học sinh, `ask_sgk` đọc nó ra như thể bài học sinh phải học. Đúng lỗi đã vá ở
đường crawl (SGV vào kb_giao_duc mang nhãn SGK) nhưng đường tải lên bị bỏ sót.

File tải lên KHÔNG có slug nên không suy được loại — buộc phải khai.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

_API = _ROOT / "api" / "teacher.py"
_TW = _ROOT / "services" / "agent" / "teacher_workspace.py"
_SF = _ROOT / "services" / "agent" / "sgk_fetch.py"


def _kind_collection() -> dict[str, str]:
    """Đọc bảng loại → kho từ nguồn, không viết lại bản thứ hai trong test."""
    import re
    src = _SF.read_text(encoding="utf-8")
    i = src.index("KIND_COLLECTION: dict[str, str] = {")
    blob = src[i:src.index("}", i)]
    return dict(re.findall(r'"(\w+)":\s*"([\w]+)"', blob))


class TestBangLoaiKho:
    def test_du_nam_loai(self):
        km = _kind_collection()
        for k in ("sgk", "sgv", "vbt", "tap_huan"):
            assert k in km, k

    def test_moi_loai_mot_kho_rieng(self):
        km = _kind_collection()
        assert km["sgk"] == "kb_giao_duc"
        assert km["sgv"] != km["sgk"], "SGV phải tách khỏi kho học sinh"
        assert km["vbt"] != km["sgk"]
        assert km["tap_huan"] != km["sgk"]


class TestDuongTaiLenCoKind:
    def test_import_sgk_bytes_nhan_kind(self):
        src = _TW.read_text(encoding="utf-8")
        i = src.index("def import_sgk_bytes(")
        sig = src[i:src.index(") -> dict", i)]
        assert "kind" in sig, "import_sgk_bytes phải nhận kind"

    def test_kind_duoc_dich_thanh_collection(self):
        """Có tham số mà không dùng thì còn tệ hơn: trông như đã tách kho."""
        src = _TW.read_text(encoding="utf-8")
        i = src.index("def import_sgk_bytes(")
        body = src[i:i + 3000]
        assert "KIND_COLLECTION" in body, (
            "phải tra bảng KIND_COLLECTION, không tự dựng bảng thứ hai")
        assert "collection=collection" in body

    def test_chi_sgk_duoc_ghi_md_goc(self):
        """`search_sgk` đọc .md và KHÔNG phân biệt loại — ghi SGV/VBT vào đó là
        trả lời trộn ở đường tra offline."""
        src = _TW.read_text(encoding="utf-8")
        i = src.index("def import_sgk_bytes(")
        body = src[i:i + 3000]
        assert 'write_md=(k == "sgk")' in body

    def test_endpoint_upload_co_form_kind(self):
        src = _API.read_text(encoding="utf-8")
        i = src.index("async def teacher_import_sgk(")
        sig = src[i:src.index("):", i)]
        assert "kind" in sig and "Form(" in sig

    def test_endpoint_chan_loai_la(self):
        src = _API.read_text(encoding="utf-8")
        i = src.index("async def teacher_import_sgk(")
        body = src[i:i + 2500]
        assert "KIND_COLLECTION" in body, "phải kiểm loại theo bảng thật"
        assert "400" in body, "loại lạ phải bị từ chối, không âm thầm về sgk"


class TestKhongGhiCungTenKho:
    def test_thong_bao_khong_ghi_cung_kb_giao_duc(self):
        """Nạp SGV mà báo `kb_giao_duc` thì người vận hành tưởng đã tách kho."""
        src = _API.read_text(encoding="utf-8")
        i = src.index("async def teacher_import_sgk(")
        body = src[i:i + 4000]
        assert "RAG `kb_giao_duc`" not in body, "còn ghi cứng tên kho"
        assert "KIND_COLLECTION[kind_in]" in body
