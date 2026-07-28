"""Chất lượng OCR sách giáo khoa: lấy đúng ảnh trang, phân đúng loại sách,
và ĐỐI CHIẾU được model có trả đủ trang hay không.

Ba kiểu hỏng đã đo thật trên kho taphuan.nxbgd.vn ngày 2026-07-28, cả ba đều
IM LẶNG — không lỗi, không log, chỉ là kho RAG thiếu hoặc sai nội dung:

  1. Kho có HAI kiểu tên ảnh. Regex cũ chỉ khớp kiểu ``-page-N-<id>.png`` nên
     những quyển dùng kiểu ``<uuid>-<ts>-<ms>.jpg`` trả về 0 trang, tức "sách
     rỗng". Đo trên bản quét dở: 41 mục bị báo 0 trang, trong đó
     shs-tieng-viet-2-tap-mot thật ra có 156 trang.
  2. ``shs-`` là Sách Học Sinh, tức chính là SGK, nhưng bị phân vào "other" nên
     sách chính của học sinh bị đẩy sang kho tài liệu.
  3. Khối 20 trang mà model chỉ trả 8 trang thì được nhận như đủ. Đây là kiểu
     tệ nhất: sách vào kho thiếu 12 trang và bot dạy sai mà không ai biết.
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

_SRC = _ROOT / "services" / "agent" / "sgk_taphuan.py"


def _load():
    """Nạp sgk_taphuan với các phụ thuộc nặng bị thay bằng ống rỗng.

    Chỉ soát hàm THUẦN (chuỗi/regex), không gọi mạng và không gọi model.
    """
    pkg = types.ModuleType("services")
    pkg.__path__ = [str(_ROOT / "services")]
    ag = types.ModuleType("services.agent")
    ag.__path__ = [str(_ROOT / "services" / "agent")]
    ng = types.ModuleType("services.net_guard")
    ng.safe_fetch = lambda *a, **k: b""
    sf = types.ModuleType("services.agent.sgk_fetch")
    sf.SUBJECTS = {}
    sf.normalize_subject = lambda s: s
    # Bảng thật ở sgk_fetch — COLLECTION_FOR_SET soi chiếu lại nó thay vì giữ
    # bản thứ hai, nên ống rỗng phải có để phép ánh xạ còn được soát.
    sf.KIND_COLLECTION = {
        "sgk": "kb_giao_duc", "nangcao": "kb_nangcao",
        "sgv": "kb_giao_duc_sgv", "vbt": "kb_giao_duc_vbt",
        "tap_huan": "kb_giao_duc_tailieu", "other": "kb_giao_duc_tailieu",
    }
    tw = types.ModuleType("services.agent.teacher_workspace")
    tw.SUBJECTS = {}
    for name, mod in (("services", pkg), ("services.agent", ag),
                      ("services.net_guard", ng),
                      ("services.agent.sgk_fetch", sf),
                      ("services.agent.teacher_workspace", tw)):
        sys.modules.setdefault(name, mod)
    spec = importlib.util.spec_from_file_location("_sgk_tp_test", _SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def m():
    return _load()


CDN = "https://cdn3.olm.vn/upload/taphuan"


class TestLayAnhTrang:
    def test_kieu_A_so_trang_trong_url(self, m):
        html = "".join(
            f'<img src="{CDN}/4714093295-page-{n}-99{n}.png" data-page="{n}">'
            for n in (3, 1, 2)
        )
        got = m.parse_page_images(html)
        assert len(got) == 3
        assert "-page-1-" in got[0] and "-page-3-" in got[2], "phải theo SỐ TRANG"

    def test_kieu_B_khong_co_so_trang_trong_url(self, m):
        """Kiểu đã làm regex cũ trả rỗng. Số trang nằm ở data-page."""
        html = "".join(
            f'<img src="/training/images/default/blank_book_page.png" '
            f'data-src="{CDN}/uuid{n}-20250721-177226{n}.jpg" '
            f'data-page="{n}" alt="page-{n}" class="js-lazy-page">'
            for n in (2, 1, 3)
        )
        got = m.parse_page_images(html)
        assert len(got) == 3, "kiểu B phải lấy được, không được trả rỗng"
        assert got == [f"{CDN}/uuid1-20250721-1772261.jpg",
                       f"{CDN}/uuid2-20250721-1772262.jpg",
                       f"{CDN}/uuid3-20250721-1772263.jpg"]

    def test_uu_tien_data_src_khong_lay_src(self, m):
        """src là ảnh TRẮNG dùng chung. Lấy src thì đủ số trang mà trang nào
        cũng trắng — OCR ra rỗng và không có lỗi nào để lần ra."""
        html = ('<img src="/training/images/default/blank_book_page.png" '
                f'data-src="{CDN}/that-1-1.jpg" data-page="1">')
        got = m.parse_page_images(html)
        assert got == [f"{CDN}/that-1-1.jpg"]
        assert "blank_book_page" not in got[0]

    def test_bo_bia_vi_khong_co_so_trang(self, m):
        """Bìa chèn vào sẽ làm lệch toàn bộ cách đánh số trang của prompt OCR."""
        html = (f'<img src="{CDN}/bia-cover.jpg" alt="cover-first">'
                f'<img data-src="{CDN}/t1.jpg" data-page="1">'
                f'<img src="{CDN}/bia-sau.jpg" alt="cover-last">')
        got = m.parse_page_images(html)
        assert got == [f"{CDN}/t1.jpg"]

    def test_bo_anh_ngoai_cdn(self, m):
        html = ('<img data-src="https://evil.example.com/x.jpg" data-page="1">'
                f'<img data-src="{CDN}/t1.jpg" data-page="2">')
        assert m.parse_page_images(html) == [f"{CDN}/t1.jpg"]

    def test_khong_tron_hai_he_danh_so(self, m):
        """Đo thật: `data-page` lệch 1 so với số trang trong URL (data-page=104
        ↔ -page-105-). Trộn lại thì cả quyển bị gán sai số trang, mà prompt OCR
        đánh số theo chính con số đó ⇒ sai âm thầm. URL phải thắng tuyệt đối."""
        html = "".join(
            f'<img data-src="{CDN}/2026/0413/471-page-{u}-99.png" data-page="{u - 1}">'
            for u in (105, 106, 107)
        )
        got = m.parse_page_images(html)
        assert got == [f"{CDN}/2026/0413/471-page-105-99.png",
                       f"{CDN}/2026/0413/471-page-106-99.png",
                       f"{CDN}/2026/0413/471-page-107-99.png"]

    def test_bia_khong_chen_vao_giua_khi_co_so_trang_url(self, m):
        """Bìa không có data-page nhưng CÓ số trang trong URL. Nếu để data-page
        của các trang sau chen vào cùng một từ điển thì trang thật bị bìa chiếm
        chỗ và biến mất — đúng cách một trang đã bị mất khi đo lần đầu."""
        html = (f'<img data-src="{CDN}/x-page-1-9.png" alt="cover-first">'
                f'<img data-src="{CDN}/x-page-2-9.png" data-page="1">'
                f'<img data-src="{CDN}/x-page-3-9.png" data-page="2">')
        got = m.parse_page_images(html)
        assert len(got) == 3, "không được mất trang nào"
        assert got[1].endswith("x-page-2-9.png")

    def test_trang_trung_so_lay_ban_dau(self, m):
        html = (f'<img data-src="{CDN}/a.jpg" data-page="5">'
                f'<img data-src="{CDN}/b.jpg" data-page="5">')
        assert m.parse_page_images(html) == [f"{CDN}/a.jpg"]

    def test_khong_co_data_page_thi_theo_thu_tu_tai_lieu(self, m):
        html = (f'<img data-src="{CDN}/x1.jpg">'
                f'<img data-src="{CDN}/x2.jpg">')
        assert m.parse_page_images(html) == [f"{CDN}/x1.jpg", f"{CDN}/x2.jpg"]

    def test_html_rong(self, m):
        assert m.parse_page_images("") == []
        assert m.parse_page_images("<p>không có ảnh</p>") == []

    def test_nhay_don_van_doc_duoc(self, m):
        html = f"<img data-src='{CDN}/t9.jpg' data-page='9'>"
        assert m.parse_page_images(html) == [f"{CDN}/t9.jpg"]


class TestPhanLoaiSach:
    @pytest.mark.parametrize("slug,kind", [
        ("sgk-toan-4-tap-mot.471", "sgk"),
        ("sgv-toan-1.490", "sgv"),
        ("vbt-toan-1-tap-1-bai-mau.472", "vbt"),
        ("tai-lieu-tap-huan-tieng-anh-2.496", "tap_huan"),
        # Bốn khe hở đã đo thật:
        ("shs-tieng-viet-2-tap-mot.453", "sgk"),          # Sách Học Sinh = SGK
        ("sgvtieng-viet-1-tap-hai.490", "sgv"),           # NXB gõ thiếu gạch nối
        ("tap-viet-1-tap-mot.472", "vbt"),                # vở luyện viết
        ("tieng-anh-2-global-success.491", "sgk"),        # slug TRẦN = sách HS
        # Hai tiền tố nữa, đo được khi quét tới lớp 10–11:
        ("sbt-toan-11-tap-hai-bai-mau.452", "vbt"),       # Sách Bài Tập (40 quyển)
        ("khbd-toan-11.453", "sgv"),                      # Kế hoạch bài dạy
    ])
    def test_tien_to(self, m, slug, kind):
        assert m.doc_kind(f"https://x/tap-huan/doc-sach/{slug}") == kind

    def test_tai_lieu_thang_sgk_khi_slug_chua_ca_hai(self, m):
        """"tai-lieu-tap-huan-day-hoc-theo-sgk-moi-mon-toan-1" là TÀI LIỆU tập
        huấn, không phải SGK — nếu xét bằng 'chứa sgk' thì phân sai."""
        u = "https://x/tap-huan/doc-sach/tai-lieu-tap-huan-day-hoc-theo-sgk-moi-mon-toan-1.452"
        assert m.doc_kind(u) == "tap_huan"

    def test_khong_nhan_ra_thi_other(self, m):
        assert m.doc_kind("https://x/tap-huan/doc-sach/abcxyz-la-gi.123") == "other"

    def test_bai_mau(self, m):
        assert m.is_sample("https://x/doc-sach/vbt-toan-1-tap-1-bai-mau.472")
        assert not m.is_sample("https://x/doc-sach/sgk-toan-1-tap-mot.469")

    def test_collection_theo_loai_va_bo(self, m):
        assert m.COLLECTION_FOR_SET("", "sgk") == "kb_giao_duc"
        assert m.COLLECTION_FOR_SET("3", "sgk") == "kb_giao_duc_bo3"
        # Loại THẮNG bộ: SGV của bộ 3 vẫn là sách giáo viên, không phải nội
        # dung học sinh của bộ 3.
        assert m.COLLECTION_FOR_SET("3", "sgv") == "kb_giao_duc_sgv"
        assert m.COLLECTION_FOR_SET("", "vbt") == "kb_giao_duc_vbt"
        assert m.COLLECTION_FOR_SET("", "tap_huan") == "kb_giao_duc_tailieu"
        assert m.COLLECTION_FOR_SET("", "other") == "kb_giao_duc_tailieu"

    def test_nhan_noi_ca_hai_tien_to_da_gop(self, m):
        """Kho gộp sgv-+khbd- và vbt-+sbt- vào cùng kho. Nhãn ghi mỗi "SGV" thì
        một quyển kế hoạch bài dạy vào kho lại tự nhận là sách giáo viên."""
        assert "KHBD" in m.DOC_KIND_LABEL["sgv"]
        assert "SBT" in m.DOC_KIND_LABEL["vbt"]

    def test_bon_kho_tach_biet(self, m):
        got = {m.COLLECTION_FOR_SET("", k) for k in ("sgk", "sgv", "vbt", "tap_huan")}
        assert len(got) == 4, f"phải là 4 kho khác nhau, đang là {got}"


class TestDoiChieuSoTrang:
    def test_doc_mot_moc(self, m):
        assert m._pages_seen("<<<TRANG 7>>>\nnội dung") == {7}

    def test_doc_nhieu_moc_va_khoang_trang(self, m):
        md = "<<<TRANG 1>>>\na\n<<< TRANG  2 >>>\nb\n<<<TRANG 3>>>"
        assert m._pages_seen(md) == {1, 2, 3}

    def test_khong_moc_thi_rong(self, m):
        assert m._pages_seen("chỉ là văn bản thường") == set()
        assert m._pages_seen("") == set()

    def test_phat_hien_thieu_trang(self, m):
        """Đúng cảnh đã mất 12 trang trong im lặng: khối 1–20, model trả 8."""
        md = "\n".join(f"<<<TRANG {n}>>>\nnội dung trang {n}" for n in range(1, 9))
        thieu = sorted(set(range(1, 21)) - m._pages_seen(md))
        assert thieu == list(range(9, 21)), "phải chỉ ra đúng 12 trang bị mất"

    def test_prompt_neu_so_trang_that(self, m):
        p = m._chunk_prompt(41, 60)
        assert "41" in p and "60" in p
        assert "20 mốc" in p, "phải đòi đủ số mốc để đối chiếu được"
        assert "<<<TRANG" in p

    def test_prompt_mot_trang(self, m):
        p = m._chunk_prompt(7, 7)
        assert "đúng 1 trang" in p and "trang số 7" in p

    def test_prompt_co_quy_tac_chong_bia(self, m):
        """Quy tắc quan trọng nhất: gặp chỗ khó thì ghi dấu, KHÔNG đoán."""
        p = m._chunk_prompt(1, 5)
        assert "[không đọc được]" in p
        assert "Không bịa" in p or "không bịa" in p
        assert "LaTeX" in p, "công thức phải ra LaTeX, không thì x² thành x2"


class TestLapVong:
    def test_lap_lien_ke_bi_bat(self, m):
        md = "\n".join(["Đây là một dòng dài đủ để tính."] * 10)
        assert m._looks_degenerate(md)

    def test_lap_khong_lien_ke_bi_bat(self, m):
        """Lặp xen kẽ: đầu ra dài, trông có nội dung, nhưng một dòng chiếm nửa."""
        md = "\n".join("Câu lặp lại rất nhiều lần đây." if i % 2 == 0
                       else "dòng chen vào số %d ở đây" % i
                       for i in range(24))
        assert m._looks_degenerate(md)

    def test_vo_bai_tap_ke_cham_khong_bao_dong_gia(self, m):
        """Vở bài tập có hàng chục dòng kẻ chấm để học sinh điền — giống nhau y
        hệt và liền kề. Tính chúng là 'lặp vòng' thì loại đúng loại sách cần."""
        md = ("<<<TRANG 5>>>\n# Bài 3: Điền vào chỗ trống\n"
              + "\n".join(["………………………………………………"] * 20)
              + "\n# Bài 4: Viết lại câu\n"
              + "\n".join(["_____________________"] * 15)
              + "\n| --- | --- |\n" * 12)
        assert not m._looks_degenerate(md)

    def test_van_ban_binh_thuong_khong_bao_dong(self, m):
        md = ("<<<TRANG 1>>>\n# Bài 1: Ôn tập\nHọc sinh đọc đoạn văn sau đây.\n"
              "Sau đó trả lời các câu hỏi bên dưới trang.\n"
              "1. Nhân vật chính trong bài là ai?\n"
              "2. Vì sao bạn ấy quyết định làm như vậy?\n"
              "<<<TRANG 2>>>\n# Bài 2: Luyện tập\nTính giá trị biểu thức sau.\n"
              "$a + b = 12$ với $a = 5$.\nGhi kết quả vào vở của em nhé.")
        assert not m._looks_degenerate(md)

    def test_dong_ngan_khong_tinh(self, m):
        """Dòng ngắn kiểu '1.' hay '|---|' lặp nhiều là BÌNH THƯỜNG trong bảng
        và danh sách — tính vào thì báo động giả liên tục."""
        assert not m._looks_degenerate("\n".join(["| --- |"] * 30))

    def test_rong(self, m):
        assert not m._looks_degenerate("")
