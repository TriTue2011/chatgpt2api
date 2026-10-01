"""Test app/markdown_an_toan.py -- đổi Markdown câu trả lời AI sang HTML an
toàn cho /ui (spec 2026-09-23-giao-dien-sang-toi-design.md, mục "Câu trả lời
AI")."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.markdown_an_toan import markdown_sang_html


def test_rong_va_chi_khoang_trang_tra_chuoi_rong():
    assert markdown_sang_html("") == ""
    assert markdown_sang_html("  \n \n") == ""


def test_tieu_de_1_den_3_thang_thanh_h3_4_den_6_thanh_h4():
    assert markdown_sang_html("# Một") == "<h3>Một</h3>"
    assert markdown_sang_html("### Ba") == "<h3>Ba</h3>"
    assert markdown_sang_html("#### Bốn") == "<h4>Bốn</h4>"
    assert markdown_sang_html("###### Sáu") == "<h4>Sáu</h4>"


def test_tieu_de_bo_day_thang_dong_nhung_giu_c_thang():
    assert markdown_sang_html("## Tiêu đề ##") == "<h3>Tiêu đề</h3>"
    assert markdown_sang_html("### C# là gì") == "<h3>C# là gì</h3>"


def test_thang_dinh_lien_chu_la_doan_van():
    assert markdown_sang_html("#hashtag") == "<p>#hashtag</p>"


def test_doan_van_cac_dong_lien_nhau_noi_bang_br():
    assert markdown_sang_html("dòng 1\ndòng 2\n\ndòng 3") == "<p>dòng 1<br>dòng 2</p>\n<p>dòng 3</p>"


def test_crlf_duoc_chuan_hoa():
    assert markdown_sang_html("a\r\nb") == "<p>a<br>b</p>"


def test_danh_sach_khong_so_ca_3_ky_hieu():
    assert markdown_sang_html("- a\n* b\n+ c") == "<ul><li>a</li><li>b</li><li>c</li></ul>"


def test_danh_sach_co_so_bat_dau_1_khong_co_start():
    assert markdown_sang_html("1. Một\n2) Hai") == "<ol><li>Một</li><li>Hai</li></ol>"


def test_danh_sach_co_so_bat_dau_khac_1_co_start():
    assert markdown_sang_html("3. Ba\n4. Bốn") == '<ol start="3"><li>Ba</li><li>Bốn</li></ol>'


def test_dong_thuong_ngay_sau_muc_noi_vao_muc():
    assert markdown_sang_html("- mục\n  tiếp theo") == "<ul><li>mục<br>tiếp theo</li></ul>"


def test_dong_trong_giua_2_muc_van_cung_danh_sach():
    assert markdown_sang_html("1. a\n\n2. b") == "<ol><li>a</li><li>b</li></ol>"


def test_danh_sach_long_theo_do_thut():
    assert markdown_sang_html("1. Đánh giá\n   - Thiết Yếu\n   - Dự phòng\n2. Nhận xét") == (
        "<ol><li>Đánh giá<ul><li>Thiết Yếu</li><li>Dự phòng</li></ul></li><li>Nhận xét</li></ol>"
    )


def test_bang_co_dong_phan_cach_co_thead():
    assert markdown_sang_html("| Hũ | Mức |\n|---|:---:|\n| Thiết Yếu | Cao |") == (
        '<div class="bang-cuon"><table><thead><tr><th>Hũ</th><th>Mức</th></tr></thead>'
        "<tbody><tr><td>Thiết Yếu</td><td>Cao</td></tr></tbody></table></div>"
    )


def test_bang_thieu_dong_phan_cach_tat_ca_la_td():
    """Đúng mẫu C2A trả thật 23/09 với model auto:text: bảng không có |---|."""
    assert markdown_sang_html(
        "## Mục A\n| Tên | Tỷ lệ |\n| Nhà (điện/nước) | 12–15% |\n- **8-10%** → tốt."
    ) == (
        "<h3>Mục A</h3>\n"
        '<div class="bang-cuon"><table><tbody><tr><td>Tên</td><td>Tỷ lệ</td></tr>'
        "<tr><td>Nhà (điện/nước)</td><td>12–15%</td></tr></tbody></table></div>\n"
        "<ul><li><strong>8-10%</strong> → tốt.</li></ul>"
    )


def test_bang_khong_co_ong_dau_dong_nhung_co_dong_phan_cach():
    assert markdown_sang_html("A | B\n---|---\n1 | 2") == (
        '<div class="bang-cuon"><table><thead><tr><th>A</th><th>B</th></tr></thead>'
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table></div>"
    )


def test_dong_phan_cach_o_giua_bang_bi_bo():
    ket_qua = markdown_sang_html("| a |\n|---|\n| b |\n|---|\n| c |")
    assert ket_qua.count("<tr>") == 3
    assert "---" not in ket_qua


def test_dong_co_ong_nhung_khong_phai_bang_la_doan_van():
    assert markdown_sang_html("A | B là 2 lựa chọn") == "<p>A | B là 2 lựa chọn</p>"


def test_rao_code_giu_nguyen_khong_dinh_dang():
    assert markdown_sang_html("```\nx = **a** <b>\n```") == "<pre><code>x = **a** &lt;b&gt;</code></pre>"


def test_trich_dan_va_ke_ngang():
    assert markdown_sang_html("> trích 1\n> trích 2") == "<blockquote>trích 1<br>trích 2</blockquote>"
    for ke in ("---", "***", "___", "- - -"):
        assert markdown_sang_html(ke) == "<hr>"


def test_inline_dam_nghieng_code():
    assert markdown_sang_html("**đậm** __đậm__ *nghiêng* ***cả hai*** `a*b*c`") == (
        "<p><strong>đậm</strong> <strong>đậm</strong> <em>nghiêng</em> "
        "<strong><em>cả hai</em></strong> <code>a*b*c</code></p>"
    )


def test_gach_duoi_trong_ma_hu_khong_thanh_dinh_dang():
    assert markdown_sang_html("thiet_yeu và tu_do_tai_chinh") == "<p>thiet_yeu và tu_do_tai_chinh</p>"


def test_dau_sao_dau_dong_dinh_chu_la_dam_khong_phai_danh_sach():
    assert markdown_sang_html("**Tổng kết:** ổn") == "<p><strong>Tổng kết:</strong> ổn</p>"


def test_link_va_anh_chi_giu_chu():
    assert markdown_sang_html("[Xem](https://vd.com/a_(b)) và ![ảnh](http://x/y.png)") == "<p>Xem và ảnh</p>"


def test_xss_the_html_bi_escape():
    ket_qua = markdown_sang_html("<script>alert(1)</script>\n<img src=x onerror=alert(1)>")
    assert "<script" not in ket_qua and "<img" not in ket_qua
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in ket_qua
    assert "&lt;img src=x onerror=alert(1)&gt;" in ket_qua


def test_xss_link_javascript_bi_bo_url():
    ket_qua = markdown_sang_html("[bấm](javascript:alert(1))")
    assert ket_qua == "<p>bấm</p>"
    assert "javascript" not in ket_qua and "href" not in ket_qua


def test_xss_the_trong_dam_va_dau_nhay_bi_escape():
    assert markdown_sang_html("**<b>x</b>**") == "<p><strong>&lt;b&gt;x&lt;/b&gt;</strong></p>"
    assert markdown_sang_html('" onmouseover="x') == "<p>&quot; onmouseover=&quot;x</p>"


def test_dau_vao_benh_ly_khong_bi_cham_bac_hai():
    """Hàm chạy đồng bộ trong request /api/de-xuat/hoi-ai -- bản thử regex
    đậm/link không giới hạn độ dài mất ~20 giây với dòng 80k ký tự."""
    for mau in ("**a " * 20000, "__a " * 20000, "[" * 10000 + "](" * 10000,
                "[a](x" * 20000, "# a" + " " * 50000 + "b"):
        bat_dau = time.perf_counter()
        markdown_sang_html(mau)
        assert time.perf_counter() - bat_dau < 2.0


def test_dong_phan_cach_bang_benh_ly_khong_bi_cham_bac_hai():
    """Review toàn nhánh 23/09/2026: regex dòng phân cách |---| bản đầu mở bằng
    `^\\s*\\|?\\s*` (2 cụm \\s* kề nhau) -> dòng có ống + dãy khoảng trắng dài
    ngay dưới 1 dòng có ống mất ~2 giây với 8.000 khoảng trắng, ~12 giây với
    20.000 (bậc hai), chặn cả event loop của MCP server."""
    for mau in ("a|b\n" + " " * 20000 + "|x", "a|b\n|-" + " " * 20000 + "-x",
                "a|b\n" + " " * 20000 + "|---|"):
        bat_dau = time.perf_counter()
        markdown_sang_html(mau)
        assert time.perf_counter() - bat_dau < 2.0
