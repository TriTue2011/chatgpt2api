"""Nạp hàng loạt: một trang chi tiết có NHIỀU loại tài liệu, không chỉ SGK.

Trước đây `run()` lấy đúng `readers[0]` — tức một quyển SGK — nên sách giáo viên
và vở bài tập không có đường nào vào kho. Giờ nạp theo loại, và ba bất biến dưới
đây là chỗ dễ sai nhất:

  1. NHÃN phải nói đúng loại. Nhãn cứng "SGK" cho mọi thứ khiến một chunk sách
     giáo viên vẫn tự giới thiệu là SGK, rồi bot trích lời hướng dẫn dạy như thể
     là nội dung học sinh phải học.
  2. KHOÁ nối lại phải gồm cả slug trang đọc. Một quyển có thể có hai tài liệu
     cùng loại (hai tập vở bài tập); dùng chung khoá thì cái sau bị coi là "đã
     nạp" và bị bỏ qua vĩnh viễn.
  3. SGK phải nạp TRƯỚC. Dừng giữa đường thì thứ quan trọng nhất đã vào kho.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

_SRC = _ROOT / "services" / "agent" / "sgk_bulk.py"


def _load(tmp: Path):
    pkg = types.ModuleType("services")
    pkg.__path__ = [str(_ROOT / "services")]
    ag = types.ModuleType("services.agent")
    ag.__path__ = [str(_ROOT / "services" / "agent")]
    cfg = types.ModuleType("services.config")
    cfg.DATA_DIR = tmp
    tw = types.ModuleType("services.agent.teacher_workspace")
    tw.GRADES = tuple(range(1, 13))
    tw.SUBJECT_LABEL = {"toan": "Toán", "tviet": "Tiếng Việt", "anh": "Tiếng Anh"}
    # sgk_fetch soi chiếu hai tên này khi TestTachKho nạp sgk_taphuan thật.
    tw.SUBJECTS = ("toan", "tviet", "anh")
    tw.GRADE_SUBJECTS = {g: ("toan",) for g in range(1, 13)}
    ng = types.ModuleType("services.net_guard")
    ng.safe_fetch = lambda *a, **k: b""
    sys.modules["services.net_guard"] = ng
    # TestTachKho nạp sgk_taphuan thật; nó soi chiếu sgk_fetch.KIND_COLLECTION.
    sf = types.ModuleType("services.agent.sgk_fetch")
    sf.SUBJECTS = {}
    sf.SUBJECT_LABEL = {}
    sf.normalize_subject = lambda s: s
    sf.KIND_COLLECTION = {
        "sgk": "kb_giao_duc", "nangcao": "kb_nangcao",
        "sgv": "kb_giao_duc_sgv", "vbt": "kb_giao_duc_vbt",
        "tap_huan": "kb_giao_duc_tailieu", "slide": "kb_giao_duc_slide",
        "other": "kb_giao_duc_tailieu",
    }
    sys.modules["services.agent.sgk_fetch"] = sf
    tp = types.ModuleType("services.agent.sgk_taphuan")
    tp.DOC_KIND_LABEL = {
        "sgk": "SGK",
        "sgv": "SGV/KHBD (sách giáo viên · kế hoạch bài dạy)",
        "vbt": "VBT/SBT (vở & sách bài tập)",
        "tap_huan": "Tài liệu tập huấn",
        "other": "Tài liệu",
    }
    tp.doc_kind = lambda u: "sgk"
    # `sgk_bulk._theo_tap` hỏi hàm này để biết slug có mang tập hay không (quyển
    # dùng chung cả năm thì slug KHÔNG có tập). Giữ y hệt bản thật ở
    # `sgk_taphuan._volume_of_slug` — ống rỗng thiếu nó là AttributeError.
    tp._volume_of_slug = lambda slug: (
        "tập một" if "tap-mot" in slug else "tập hai" if "tap-hai" in slug else ""
    )
    tp.is_sample = lambda u: "bai-mau" in str(u)
    tp.reader_urls = lambda u, k=(): []
    tp.COLLECTION_FOR_SET = lambda bs="", kind="sgk": "kb"
    tp.import_reader = lambda *a, **k: {"ok": False}
    tp.list_books = lambda g, all_sets=False: []
    for name, mod in (("services", pkg), ("services.agent", ag),
                      ("services.config", cfg),
                      ("services.agent.teacher_workspace", tw),
                      ("services.agent.sgk_taphuan", tp)):
        sys.modules[name] = mod
    spec = importlib.util.spec_from_file_location("_sgk_bulk_test", _SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture()
def sb(tmp_path: Path):
    return _load(tmp_path)


BOOK = {"grade": 4, "slug": "toan-4-tap-mot-939781966", "volume": "tập một",
        "book_set": ""}


class TestChonLoai:
    def test_mac_dinh_chi_sgk(self, sb):
        assert sb.DEFAULT_KINDS == ("sgk",)
        assert sb.normalize_kinds(()) == ("sgk",)
        assert sb.normalize_kinds(None) == ("sgk",)

    def test_sgk_dung_truoc_sgv_va_vbt(self, sb):
        """Dừng giữa đường thì sách học sinh phải đã vào kho, không phải SGV."""
        assert sb.normalize_kinds(["vbt", "sgv", "sgk"])[0] == "sgk"
        assert sb.normalize_kinds(["tap_huan", "sgk"]) == ("sgk", "tap_huan")

    def test_slide_dung_truoc_ca_sgk(self, sb):
        """Slide gần như miễn phí (chữ thật, 0 lượt gọi vision) nên chạy đầu:
        dừng ngay sau đó thì vẫn đã có phân bổ tuần–tiết của mọi quyển."""
        assert sb.normalize_kinds(["sgk", "slide"]) == ("slide", "sgk")
        assert sb.KIND_ORDER[0] == "slide"

    def test_slide_khong_di_qua_doc_sach(self, sb):
        """Slide nằm trên Google Slides, không phải link /doc-sach/ — để nó lọt
        vào reader_urls() thì lượt chạy báo 'không thấy link đọc sách'."""
        assert "slide" in sb.NON_READER_KINDS
        assert "sgk" not in sb.NON_READER_KINDS

    def test_bo_loai_la(self, sb):
        assert sb.normalize_kinds(["sgk", "abc", ""]) == ("sgk",)
        # Toàn loại lạ → về mặc định, KHÔNG trả rỗng: rỗng thì reader_urls hiểu
        # là "không lọc" và nạp cả tài liệu tập huấn vào kho SGK.
        assert sb.normalize_kinds(["abc", "xyz"]) == ("sgk",)

    def test_chuan_hoa_hoa_thuong_va_khoang_trang(self, sb):
        assert sb.normalize_kinds([" SGV ", "VBT"]) == ("sgv", "vbt")

    def test_khong_trung_lap(self, sb):
        assert sb.normalize_kinds(["sgk", "sgk", "sgk"]) == ("sgk",)


class TestNhan:
    def test_nhan_theo_loai(self, sb):
        assert sb._label_of(BOOK, "toan", "sgk").startswith("SGK lớp 4")
        assert "SGV" in sb._label_of(BOOK, "toan", "sgv")
        assert "VBT" in sb._label_of(BOOK, "toan", "vbt")
        assert "tập huấn" in sb._label_of(BOOK, "toan", "tap_huan")

    def test_sgv_khong_tu_nhan_la_sgk(self, sb):
        """Lỗi gốc: nhãn cứng "SGK" nên chunk sách giáo viên tự nhận là SGK."""
        lb = sb._label_of(BOOK, "toan", "sgv")
        assert not lb.startswith("SGK "), lb

    def test_nhan_co_mon_tap_va_bo(self, sb):
        lb = sb._label_of(BOOK, "toan", "sgk")
        assert "Toán" in lb and "tập một" in lb and "bộ chính" in lb

    def test_bo_khac_hien_ro(self, sb):
        lb = sb._label_of({**BOOK, "book_set": "3"}, "toan", "sgk")
        assert "bộ 3" in lb and "bộ chính" not in lb

    def test_bai_mau_phai_noi_thang(self, sb):
        """Để bot tưởng có cả quyển vở bài tập thì nó sẽ khẳng định chắc nịch về
        những bài tập không hề nằm trong đó."""
        lb = sb._label_of(BOOK, "toan", "vbt", sample=True)
        assert "BÀI MẪU" in lb and "không phải cả quyển" in lb

    def test_loai_la_khong_tu_thanh_sgk(self, sb):
        assert "SGK" not in sb._label_of(BOOK, "toan", "khong-biet")


class TestKhoaNoiLai:
    def test_hai_tai_lieu_cung_loai_khac_khoa(self, sb):
        """Hai tập vở bài tập trong cùng một quyển — dùng chung khoá thì tập hai
        bị coi là 'đã nạp' và bị bỏ qua vĩnh viễn."""
        a = sb._doc_key(BOOK, "vbt", "https://x/doc-sach/vbt-toan-4-tap-1.111")
        b = sb._doc_key(BOOK, "vbt", "https://x/doc-sach/vbt-toan-4-tap-2.222")
        assert a != b

    def test_khac_loai_khac_khoa(self, sb):
        a = sb._doc_key(BOOK, "sgk", "https://x/doc-sach/sgk-toan-4.1")
        b = sb._doc_key(BOOK, "sgv", "https://x/doc-sach/sgv-toan-4.2")
        assert a != b

    def test_khac_bo_khac_khoa(self, sb):
        a = sb._doc_key(BOOK, "sgk", "https://x/doc-sach/sgk-toan-4.1")
        b = sb._doc_key({**BOOK, "book_set": "3"}, "sgk",
                        "https://x/doc-sach/sgk-toan-4.1")
        assert a != b

    def test_cung_tai_lieu_thi_cung_khoa(self, sb):
        """Bất biến của việc nối lại: chạy lần hai phải nhận ra đã nạp."""
        u = "https://x/doc-sach/sgk-toan-4-tap-mot.4714093295"
        assert sb._doc_key(BOOK, "sgk", u) == sb._doc_key(BOOK, "sgk", u)

    def test_bo_dau_gach_cuoi(self, sb):
        assert (sb._doc_key(BOOK, "sgk", "https://x/doc-sach/a.1/")
                == sb._doc_key(BOOK, "sgk", "https://x/doc-sach/a.1"))


class TestTachKho:
    def test_moi_loai_mot_kho(self, sb):
        """Đi qua sgk_taphuan thật, không phải ống rỗng — đây là bất biến quan
        trọng nhất của việc thêm SGV/VBT."""
        import importlib.util as iu
        spec = iu.spec_from_file_location(
            "_tp_real", _ROOT / "services" / "agent" / "sgk_taphuan.py")
        real = iu.module_from_spec(spec)
        sys.modules["_tp_real"] = real
        spec.loader.exec_module(real)  # type: ignore[union-attr]
        got = {k: real.COLLECTION_FOR_SET("", k)
               for k in ("sgk", "sgv", "vbt", "tap_huan")}
        assert len(set(got.values())) == 4, got
        assert got["sgk"] == "kb_giao_duc"

    def test_nhan_lay_tu_sgk_taphuan_khong_giu_bang_rieng(self):
        """Hai bảng nhãn song song là lý do thêm loại ở một chỗ mà chỗ kia vẫn
        gắn nhãn cũ — đúng lỗi đã xảy ra với danh mục môn trước đây."""
        src = _SRC.read_text(encoding="utf-8")
        assert "_KIND_SHORT = dict(tp.DOC_KIND_LABEL)" in src, (
            "sgk_bulk phải soi chiếu tp.DOC_KIND_LABEL, không tự khai bảng nhãn")
