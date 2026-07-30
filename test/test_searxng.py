"""SearXNG là đường tìm kiếm THỨ N, tự dùng, không ai phải bấm bật.

Dự án vốn đã có lớp `SearXNGSearcher` từ trước mà chưa bao giờ chạy được, vì hai
lẽ: mặc định trỏ `http://localhost:8080` — trong Docker thì localhost là chính
container gateway — và không có service searxng nào trong stack. Không có gì báo,
nên nhìn như "SearXNG không hoạt động".

Đo thật 2026-07-30 trên máy chủ, 5 truy vấn tiếng Việt: 5/5 có kết quả, 0,3–1,1s;
`search_combo` tự thành `['mcp', 'searxng']`.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SS = ROOT / "services" / "search_service.py"
COMPOSE = ROOT / "docker-compose.yml"
SETTINGS = ROOT / "deploy" / "searxng" / "settings.yml"


class TestTuTimDuocService:
    def test_khong_con_mac_dinh_localhost(self):
        """localhost:8080 trong container = chính gateway, không phải searxng."""
        s = SS.read_text("utf-8")
        i = s.index("def searxng_base_url")
        body = s[i:i + 900]
        assert 'or "http://searxng:8080"' in body, \
            "phải mặc định là tên service trong compose"
        # Chỉ soi GIÁ TRỊ MẶC ĐỊNH, không soi docstring — docstring có quyền nhắc
        # lại localhost để kể vì sao bản cũ sai.
        assert 'or "http://localhost:8080"' not in body

    def test_thu_tu_config_env_service(self):
        s = SS.read_text("utf-8")
        i = s.index("def searxng_base_url")
        body = s[i:i + 900]
        assert body.index('cfg.get("base_url")') < body.index("SEARXNG_URL")
        assert body.index("SEARXNG_URL") < body.index("searxng:8080")


class TestTuVaoChuoiTimKiem:
    def test_search_combo_tu_noi_searxng(self):
        s = SS.read_text("utf-8")
        assert "_them_searxng" in s
        i = s.index("def search_combo")
        assert "self._them_searxng" in s[i:i + 1600]

    def test_noi_o_CUOI_khong_chen_len_truoc(self):
        """Không được đổi thứ tự người dùng đã chọn — searxng là lưới đỡ cuối."""
        s = SS.read_text("utf-8")
        i = s.index("def _them_searxng")
        body = s[i:i + 900]
        assert 'return ds + ["searxng"]' in body

    def test_co_duong_tat_han(self):
        """Người vận hành phải có đường nói 'đừng dùng' — nhưng mặc định là DÙNG."""
        s = SS.read_text("utf-8")
        i = s.index("def _them_searxng")
        body = s[i:i + 900]
        assert '"enabled") is False' in body

    def test_chi_them_khi_instance_song(self):
        """Thêm bừa thì mỗi lượt tìm tốn một request chết."""
        s = SS.read_text("utf-8")
        i = s.index("def _them_searxng")
        body = s[i:i + 900]
        assert "searxng_ready()" in body

    def test_khong_them_hai_lan(self):
        s = SS.read_text("utf-8")
        i = s.index("def _them_searxng")
        body = s[i:i + 900]
        assert 'if "searxng" in ds' in body

    def test_search_all_khong_danh_mat_searxng(self):
        """search_all rơi về backend đơn khi combo == ['chatgpt']; so bằng cứng sẽ
        không khớp nữa vì combo giờ có thêm 'searxng', và nếu so lỏng thì lại bỏ
        mất chính searxng vừa nối."""
        s = SS.read_text("utf-8")
        i = s.index("# --- Luong 2: Combo backends")
        body = s[i:i + 900]
        assert '[c for c in combo if c != "searxng"] == ["chatgpt"]' in body
        assert "self._them_searxng([self._get_active_backend()])" in body


class TestGoiDungThamSo:
    def test_truyen_language_tuong_minh(self):
        """default_lang của SearXNG là 'auto' — nó đoán theo Accept-Language của
        phía gọi, tức phụ thuộc thứ ta tình cờ gửi."""
        s = SS.read_text("utf-8")
        i = s.index("class SearXNGSearcher")
        body = s[i:i + 3000]
        assert '"language": _SEARXNG_LANG' in body
        assert re.search(r'_SEARXNG_LANG\s*=\s*"vi-VN"', s)

    def test_truyen_engines_va_timeout(self):
        """Không khai engines thì thời gian chờ bằng engine chậm nhất được chọn,
        mà settings gốc có engine tự khai timeout 20s."""
        s = SS.read_text("utf-8")
        i = s.index("class SearXNGSearcher")
        body = s[i:i + 3000]
        assert '"engines": _SEARXNG_ENGINES' in body
        assert '"timeout_limit"' in body

    def test_khong_dua_vao_google(self):
        """google bị bản gốc đánh inactive: engine KHÔNG được nạp, truyền
        engines=google là bị bỏ qua im lặng."""
        assert "google" not in re.search(
            r'_SEARXNG_ENGINES = "([^"]+)"', SS.read_text("utf-8")).group(1)

    def test_co_engine_du_phong(self):
        """Đo thật: startpage ăn CAPTCHA ngay lượt đầu, duckduckgo từ lượt 4 —
        chỉ bing gánh. Ba engine 'đúng tiếng Việt' có ngày treo cùng lúc."""
        eng = re.search(r'_SEARXNG_ENGINES = "([^"]+)"',
                        SS.read_text("utf-8")).group(1).split(",")
        assert "bing" in eng
        assert len(eng) >= 4, "thiếu engine dự phòng thì captcha là rỗng sạch"


class TestNoiRoNguyenNhanKhiLoi:
    def test_403_noi_ro_thieu_formats(self):
        """403 = settings.yml chưa mở json. Log trơ status thì nhìn y như 'không
        có kết quả' và không ai sửa được cấu hình."""
        s = SS.read_text("utf-8")
        assert "search.formats" in s
        assert "resp.status_code == 403" in s

    def test_429_noi_ro_limiter(self):
        s = SS.read_text("utf-8")
        assert "429" in s and "limiter" in s.lower()

    def test_log_unresponsive_engines(self):
        """Đây là dấu hiệu DUY NHẤT trong JSON cho biết engine nào bị chặn."""
        s = SS.read_text("utf-8")
        assert "unresponsive_engines" in s
        assert "searxng_engine_khong_tra_loi" in s

    def test_khong_doc_number_of_results(self):
        """Field này đã bị SearXNG xoá (2026-05-25) — tin vào nó là tin vào
        tutorial cũ."""
        s = SS.read_text("utf-8")
        assert "number_of_results" not in s


class TestServiceTrongStack:
    def test_compose_co_searxng_khong_publish_cong(self):
        s = COMPOSE.read_text("utf-8")
        i = s.index("  searxng:")
        body = s[i:]
        assert "searxng/searxng" in body
        # Publish cổng = biến nó thành instance công khai; lúc đó phải bật limiter,
        # mà limiter chặn chính gateway (4 request/IP/giờ cho format=json).
        assert not re.search(r"^\s{4}ports:", body, re.M), "không được publish cổng"

    def test_compose_mount_settings_va_secret(self):
        s = COMPOSE.read_text("utf-8")
        i = s.index("  searxng:")
        body = s[i:]
        assert "/etc/searxng/settings.yml" in body, \
            "search.formats không có biến môi trường — buộc phải mount file"
        assert "SEARXNG_SECRET" in body, \
            "mount settings.yml thì entrypoint không tự sinh khoá, webapp exit(1)"

    def test_settings_mo_json_va_tat_limiter(self):
        s = SETTINGS.read_text("utf-8")
        assert re.search(r"formats:\s*\[html,\s*json\]", s), \
            "mặc định của SearXNG là [html] và trả 403 cho json"
        assert re.search(r"limiter:\s*false", s)

    def test_settings_giu_ca_html(self):
        """formats GHI ĐÈ chứ không merge — chỉ ghi [json] là mất luôn giao diện
        để soi khi cần."""
        s = SETTINGS.read_text("utf-8")
        assert "html" in re.search(r"formats:\s*\[([^\]]+)\]", s).group(1)
