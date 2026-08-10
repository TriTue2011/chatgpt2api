"""Tạo video Flow chuyển sang gọi thẳng API, bỏ điều khiển giao diện.

Vì sao đổi được bây giờ: đường REST đã dựng ra MP4 thật, đo 10/08/2026 trên tài
khoản Main — 16:9 ra 2.148.351 byte sau 56 giây, 9:16 ra 2.354.476 byte sau 53
giây. Trước đó nó trả 403 suốt hai ngày, và nguyên nhân KHÔNG phải quyền tài
khoản mà là khoá model: `veo_3_1_t2v_lite_low_priority` (đúng cái đang làm mặc
định) bị Google từ chối bằng câu "The caller does not have permission", còn
`veo_3_1_t2v_lite` thì 200.

Vì sao NÊN đổi: đường giao diện đang hỏng ở đúng chỗ nó vốn mong manh — bấm
không thấy nút Tạo, trang không dựng xong trong 45 giây. Cùng lớp lỗi đã làm
đường ẢNH trả về sai khung hình.

Ba chỗ hợp đồng khác nhau, và cả ba đều hỏng IM LẶNG nếu đổi sai:

  1. Model: đường cũ nhận "flow/veo-3.1-lite" rồi tự dựng khoá; đường REST nhận
     NHÃN "Veo 3.1 - Lite". Bảng dựng khoá của đường cũ có hai lỗi đã đo —
     `veo_3_1_t2v_quality` không tồn tại, và nối `_portrait` cho bậc Lite là sai.
  2. Ảnh: đường cũ có hai trường rời `image` / `last_frame`; đường REST nhận MỘT
     danh sách và đọc THEO VỊ TRÍ. Đảo thứ tự là video chạy ngược.
  3. Tín dụng: đường cũ để số tín dụng trong `data[0].metadata`, đường REST để ở
     tầng ngoài. Đọc sai chỗ thì phần theo dõi vẫn chạy, chỉ là số không bao giờ
     đổi — hỏng mà không ai thấy.
"""
from __future__ import annotations

import ast
import types
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
NGUON = (GOC / "api/veo_video.py").read_text(encoding="utf-8")


def _nap_ham_thuan() -> types.SimpleNamespace:
    """Nạp RIÊNG mấy hàm/bảng thuần của lớp đổi hợp đồng, không import module.

    `api/veo_video.py` kéo theo pydantic model dùng cú pháp `str | None`, nên cả
    module không import được trên Python 3.9 (xem `test_video_limits.py` — lỗi
    này có từ trước). Ba hàm cần kiểm thì thuần: không import, không trạng thái.
    Bóc đúng chúng ra để test hành vi THẬT thay vì chỉ soi chuỗi.
    """
    can = {"_NHAN_MODEL_FLOW", "_NHAN_MODEL_MAC_DINH",
           "_nhan_model_flow", "_che_do_video", "_anh_video"}
    cay = ast.parse(NGUON)
    giu: list[ast.stmt] = []
    for nut in cay.body:
        if isinstance(nut, ast.FunctionDef) and nut.name in can:
            giu.append(nut)
        elif isinstance(nut, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in can for t in nut.targets):
            giu.append(nut)
    thieu = can - {getattr(n, "name", None) or n.targets[0].id for n in giu}
    assert not thieu, f"không tìm thấy trong nguồn: {sorted(thieu)}"
    ns: dict = {}
    exec(compile(ast.Module(body=giu, type_ignores=[]), "<veo_video>", "exec"), ns)
    return types.SimpleNamespace(**{k: ns[k] for k in can})


V = _nap_ham_thuan()
# Bỏ dòng chú thích trước khi soi: chú thích bản vá có nhắc lại hành vi cũ.
MA = "\n".join(l for l in NGUON.splitlines() if not l.lstrip().startswith("#"))


class GoiDungDuongREST(unittest.TestCase):
    def test_dia_chi_la_duong_rest(self):
        self.assertIn("/v1/google/flow/rest/generate-video", MA)

    def test_khong_con_goi_duong_giao_dien(self):
        self.assertNotIn('flow/generate-video"', MA)

    def test_phai_cho_xong_moi_tra(self):
        """Bên gọi này không có hàng đợi — không chờ là trả về tay không."""
        self.assertIn('"wait": True', MA)


class DoiNhanModel(unittest.TestCase):
    def test_cac_bac_doi_dung_nhan(self):
        self.assertEqual(V._nhan_model_flow("flow/veo-3.1-lite"), "Veo 3.1 - Lite")
        self.assertEqual(V._nhan_model_flow("flow/veo-3.1-fast"), "Veo 3.1 - Fast")
        self.assertEqual(V._nhan_model_flow("flow/veo-3.1-quality"), "Veo 3.1 - Quality")
        self.assertEqual(V._nhan_model_flow("flow/omni-flash"), "Omni Flash")

    def test_khong_phan_biet_hoa_thuong_va_thieu_tien_to(self):
        self.assertEqual(V._nhan_model_flow("FLOW/VEO-3.1-FAST"), "Veo 3.1 - Fast")
        self.assertEqual(V._nhan_model_flow("veo-3.1-fast"), "Veo 3.1 - Fast")

    def test_model_la_ve_bac_Lite_chu_KHONG_ve_Lower_Priority(self):
        """Bậc [Lower Priority] là thứ Google từ chối vì quyền — đặt làm mặc định
        là dựng lại đúng cái 403 đã chặn đường video hai ngày."""
        for la in ("", "model-nao-do", "flow/khong-co"):
            with self.subTest(model=la):
                nhan = V._nhan_model_flow(la)
                self.assertEqual(nhan, "Veo 3.1 - Lite")
                self.assertNotIn("Lower Priority", nhan)

    def test_khong_bang_nao_con_tro_vao_Lower_Priority(self):
        self.assertNotIn("Lower Priority", str(V._NHAN_MODEL_FLOW))


class SuyCheDoTheoAnh(unittest.TestCase):
    def test_khong_anh_la_van_ban_sang_video(self):
        self.assertEqual(V._che_do_video(None, None), "text_to_video")

    def test_mot_anh_la_anh_dau(self):
        self.assertEqual(V._che_do_video("AAA", None), "image_start")

    def test_hai_anh_la_noi_suy_hai_dau(self):
        self.assertEqual(V._che_do_video("AAA", "BBB"), "image_start_end")

    def test_chi_co_anh_cuoi_thi_KHONG_goi_la_noi_suy(self):
        """Nội suy đòi cả hai ảnh; gửi thiếu là solver trả 400 nói cần 2 ảnh."""
        self.assertEqual(V._che_do_video(None, "BBB"), "text_to_video")


class AnhGuiTheoDanhSachDungThuTu(unittest.TestCase):
    def test_anh_dau_dung_truoc_anh_cuoi(self):
        ds = V._anh_video("AAA", "BBB")
        self.assertEqual([a["image_b64"] for a in ds], ["AAA", "BBB"])

    def test_moi_anh_deu_co_ten(self):
        """Solver khai `images: list[dict[str, str]]` với khoá `name` — thiếu là 422."""
        for a in V._anh_video("AAA", "BBB"):
            self.assertTrue(a.get("name"))
            self.assertTrue(a.get("image_b64"))

    def test_khong_anh_thi_danh_sach_rong(self):
        self.assertEqual(V._anh_video(None, None), [])


class TinDungVanDuocGhi(unittest.TestCase):
    def test_doc_o_tang_ngoai_truoc(self):
        self.assertIn('data.get("remaining_credits")', MA)

    def test_van_doc_duoc_cho_cu(self):
        """Bản ghi cũ trong thư viện để tín dụng trong metadata."""
        self.assertIn('meta.get("remainingCredits")', MA)


class GoiSolverBangKHOA_CUA_SOLVER(unittest.TestCase):
    """Đo 10/08/2026: đường video chuyển tiếp khoá của NGƯỜI GỌI xuống solver.

    Solver trả 401 "invalid api key" và bên gọi nhận "Flow Video generation
    failed: invalid api key" — hỏng ở 0 giây, chưa từng chạm tới Google. Khoá
    solver trong cấu hình khác khoá bảng điều khiển (đã so: 'Tri…' so với
    'Anh…'), nên lỗi này chặn MỌI lượt gọi qua `/v1/video/generations`; nhật ký
    không có lượt video nào là khớp với điều đó.

    Vì sao trước giờ không ai thấy: mọi lượt tạo video thành công đều đi qua
    proxy `/api/captcha`, và proxy tự thay bằng khoá đúng. Đường nội bộ này thì
    không. Đường ẢNH vốn đã dùng khoá cấu hình (`flow_google.build_headers`).
    """

    def test_doc_khoa_tu_cau_hinh(self):
        self.assertIn('flow_cfg.get("captcha_solver_api_key")', MA)

    def test_khong_con_chuyen_tiep_khoa_nguoi_goi(self):
        self.assertNotIn('headers={"authorization": authorization or ""}', MA)

    def test_dung_dau_solver_khi_goi(self):
        self.assertIn("headers=dau_solver", MA)


class ChiKhongThuLAI_KHI_DA_TIEU_TIN_DUNG(unittest.TestCase):
    """Lằn ranh của đường REST là có Generation ID hay chưa.

    Đường cũ liệt kê các chuỗi lỗi "trước khi bấm Tạo" rồi CHỈ thử tài khoản khác
    khi khớp — nên một chuỗi bỏ sót ("never hydrated") làm hệ thống bỏ luôn hai
    tài khoản còn rảnh dù chẳng tài khoản nào tiêu tín dụng. Nay lật lại: mặc
    định là thử tiếp, chỉ dừng khi thấy dấu hiệu ĐÃ tiêu.
    """

    def test_hai_dau_hieu_da_tieu_duoc_neu_ro(self):
        self.assertIn('"gen_ids="', MA)
        self.assertIn('"google báo thất bại"', MA)

    def test_phep_kiem_la_phu_dinh(self):
        self.assertIn("return not any(k in low for k in _DAU_HIEU_DA_TIEU_TIN_DUNG)", MA)

    def test_khong_con_danh_sach_loi_cua_duong_giao_dien(self):
        for cu in ("never hydrated", "không vào được màn soạn", "chưa bấm tạo"):
            self.assertNotIn(cu, MA)


if __name__ == "__main__":
    unittest.main()
