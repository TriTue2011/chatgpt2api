"""Flow phải tạo video BẰNG ĐÚNG MODEL người dùng chọn, và tài khoản đã kết
luận là bị xóa thì phải NẰM YÊN ở trạng thái 'deactivated'.

Đo thật 02/08 — hai lỗi riêng biệt, cùng một kiểu: một bước im lặng thất bại
rồi phần sau chạy tiếp như không có chuyện gì.

  A. CHỌN MODEL FLOW. Người dùng chọn `flow/veo-3.1-lite` (10 tín dụng). Cả
     chuỗi phần mềm truyền đúng chuỗi đó xuống solver. Nhưng bước đặt model
     trên giao diện lại bấm THẲNG vào chip cài đặt — mà chip là nút bật/tắt, và
     hàng "số bản ghi" ngay trên đã để bảng ở trạng thái MỞ. Cú bấm đó ĐÓNG bảng
     lại. Log lượt kiểm chứng 12:11:

         12:11:13  đã bấm chuột thật vào chip model (mở bảng)
         12:11:14  DANH SÁCH MODEL + TÍN DỤNG = []
         12:11:14  flow_dropdown_skip model=Veo 3.1 - Lite (Trigger not found)
         12:11:14  bảng cài đặt đã đóng — mở lại (trước khi kiểm chứng)
         12:11:16  ĐANG CHỌN = {... 'thoi_luong': '8s' ...}

     Model không bao giờ được đặt → Flow chạy bằng model còn sót của lượt trước.
     Hàng thời lượng '8s' còn nguyên là dấu vết: CHỈ Omni Flash mới có hàng đó.
     Kết quả: Omni Flash 8 giây, 12 tín dụng, cho một yêu cầu Lite 10 tín dụng.

     Ba chỗ hỏng nối nhau: (1) bấm chip đóng nhầm bảng; (2) `_set_dropdown` không
     trả kết quả nên người gọi không biết nó trượt; (3) bộ kiểm chứng chỉ soi
     thời lượng + số lượng, bỏ qua đúng cái đắt nhất là model.

  B. TRẠNG THÁI 'deactivated'. Đánh dấu tay lúc 12:08 cho benbap2011@gmail.com;
     job refresh_accounts gọi `remove_invalid_token` ghi đè ngược về 'error' rồi
     spawn tiếp một lượt khôi phục. Đánh dấu mà không bền thì vô nghĩa.

Test đọc mã nguồn (bỏ dòng chú thích trước khi soi — chú thích bản vá nhắc lại
hành vi cũ để giải thích): thứ cần khoá là các QUYẾT ĐỊNH rẽ nhánh. Dựng
Playwright + giao diện Flow giả cho việc này là đổi phép đo chắc chắn lấy phép
đo phụ thuộc mock.
"""
from __future__ import annotations

import pathlib
import unittest

GOC = pathlib.Path(__file__).resolve().parents[1]


def _code(p: pathlib.Path) -> str:
    return "\n".join(l for l in p.read_text("utf-8").splitlines()
                     if not l.lstrip().startswith("#"))


def _khuc(code: str, tu: str, den: str) -> str:
    i = code.index(tu)
    return code[i:code.index(den, i)]


class TestFlowDatDungModel(unittest.TestCase):
    def setUp(self):
        self.code = _code(GOC / "captcha-solver" / "src" / "solvers" / "flow_google.py")

    def test_khong_bam_chip_lam_dong_bang(self):
        """Bước model phải dùng _bao_dam_bang_mo (chỉ mở khi đang đóng)."""
        khuc = _khuc(self.code, "_MODEL_LABEL = {", "_set_dropdown(page, model_lbl")
        self.assertIn('_bao_dam_bang_mo("trước khi chọn model")', khuc)
        self.assertNotIn('"chip model (mở bảng)", _JS_CHIP', khuc)

    def test_set_dropdown_bao_duoc_thanh_bai(self):
        """Bản lồng dùng cho video phải trả True/False ở MỌI nhánh."""
        khuc = _khuc(self.code, "async def _set_dropdown(pg: Page",
                     "async def _bao_dam_bang_mo")
        self.assertIn("return False", khuc)       # không tìm thấy trigger / lỗi
        self.assertIn("return True", khuc)        # bấm trúng mục trong menu
        self.assertIn("return clicked", khuc)     # chỉ bấm thẳng ở bước 1
        # Không còn `return` trống — nó chính là chỗ nuốt mất kết quả.
        self.assertNotIn("\n                        return\n", khuc)

    def test_ket_qua_dat_model_duoc_dung(self):
        self.assertIn("_dat_model_ok = await _set_dropdown(page, model_lbl, \"model\")",
                      self.code)

    def test_lech_model_thi_dung_truoc_khi_bam_tao(self):
        i = self.code.index("model_mismatch")
        khuc = self.code[i - 700:i + 400]
        self.assertIn('"state": "failed"', khuc)
        self.assertIn("_chuan(model_lbl) not in _chuan(_model_that)", khuc)
        # Phải dừng TRƯỚC khi bấm Tạo, nếu không thì tín dụng đã tiêu mất rồi.
        self.assertLess(i, self.code.index("flow_video_submit"))

    def test_khong_doc_duoc_model_cung_dung(self):
        """Đặt trượt VÀ không đọc được model đang chọn → dừng, đừng đoán."""
        self.assertIn("model_unverified", self.code)
        i = self.code.index("model_unverified")
        self.assertLess(i, self.code.index("flow_video_submit"))


class TestVaoDuocManSoanVideo(unittest.TestCase):
    """Nhận chế độ video KHÔNG được phụ thuộc nút gửi, và không bấm nhầm thư viện.

    Đo thật 02/08 trên profile ``google-mitbap0610`` (tài khoản Flow "Backup",
    đang ở index 0 nên mọi lượt video đều rơi vào nó):

        chip                   = 'Video · 8s|crop_16_9|x1'   ← ĐANG là chế độ video
        nút gửi (arrow_forward) = KHÔNG có
        ô nhập textarea         = offsetParent null (ẩn)
        nút khớp bộ tìm tab cũ  = ['videocam|Xem video']     ← nút LỌC THƯ VIỆN

    Bản cũ neo mọi thứ vào nút gửi rồi mới lần ra khung nhập, nên trang không có
    nút gửi là mù hoàn toàn: hàm kiểm chế độ trả False, vòng lặp bấm 'Xem video'
    ba lần (log ghi "đã bấm chuột thật vào tab Video" đủ 3 lần) rồi ném lỗi
    "giao diện vẫn ở chế độ tạo ẢNH" — sai cả nguyên nhân lẫn việc cần làm.

    Cùng lúc đó profile ``google-benbap2011`` CÓ nút gửi và chip đọc
    '🍌 Nano Banana 2|crop_16_9|x2', tức đây là trạng thái theo từng trang chứ
    không phải Flow đổi giao diện.
    """

    def setUp(self):
        self.code = _code(GOC / "captcha-solver" / "src" / "solvers" / "flow_google.py")
        self.ham = _khuc(self.code, "async def _dang_o_tab_video", "async def _bam_chuot_that")

    def test_nhan_che_do_qua_chip_khong_qua_nut_gui(self):
        self.assertIn("button[aria-haspopup=menu]", self.ham)
        self.assertIn("/crop_/", self.ham)
        # Không còn CỔNG "không có nút gửi thì bỏ ngay". Soi đúng câu lệnh đó
        # chứ không soi chữ 'arrow_forward' — chú thích của bản vá có nhắc lại
        # hành vi cũ để giải thích, và `_code()` chỉ bỏ chú thích Python (#),
        # không bỏ chú thích JS (//).
        self.assertNotIn("if (!send) return false", self.ham)
        self.assertNotIn("bs.find(b => /arrow_forward/i.test", self.ham)

    def test_bo_tim_tab_loai_nut_thu_vien_xem(self):
        khuc = _khuc(self.code, "_JS_TAB = ", "async def _mo_bang_cai_dat")
        self.assertIn("Xem", khuc)
        self.assertIn("return false", khuc)

    def test_chi_doi_o_nhap_KHONG_doi_nut_gui(self):
        """Nút gửi của Flow chỉ hiện SAU khi ô nhập có chữ.

        Đo thật 02/08 (google-mitbap0610): bản đầu của chốt này bắt cả hai, gặp
        'ô nhập hiện=True, nút gửi=False' rồi bỏ tài khoản đó oan — trong khi
        khung soạn ĐÃ có, chỉ là chưa gõ gì nên nút gửi chưa được render.
        """
        i = self.code.index("đã chuyển sang tab Video (đã kiểm chứng)")
        khuc = self.code[i:i + 1800]
        self.assertIn('if not _khung.get("oNhap"):', khuc)
        self.assertNotIn('_khung.get("oNhap") and _khung.get("nutGui")', khuc)

    def test_loi_chua_tieu_tin_dung_van_duoc_doi_tai_khoan(self):
        """Điều test này bảo vệ không đổi: một lượt hỏng mà CHƯA tiêu tín dụng thì
        không được chặn các tài khoản còn rảnh.

        Cách diễn đạt thì đã đổi. Trước đây là danh sách chuỗi lỗi "xảy ra trước
        khi bấm Tạo" của đường giao diện, và chính test này sinh ra vì danh sách
        đó bỏ sót "never hydrated". Nay video đi đường REST, nơi có đúng MỘT lằn
        ranh — đã có Generation ID hay chưa — nên logic lật lại: mặc định thử
        tiếp, chỉ dừng khi thấy dấu hiệu đã tiêu. Không còn danh sách để bỏ sót.
        """
        api = _code(GOC / "api" / "veo_video.py")
        dau_hieu = _khuc(api, "_DAU_HIEU_DA_TIEU_TIN_DUNG = (", ")")
        self.assertIn("gen_ids=", dau_hieu)
        self.assertIn("google báo thất bại", dau_hieu)
        self.assertIn("return not any(k in low for k in _DAU_HIEU_DA_TIEU_TIN_DUNG)", api)
        # Danh sách cũ phải biến mất hẳn — để lại là hai bộ luật cùng tồn tại.
        self.assertNotIn("_LOI_TRUOC_KHI_BAM_TAO", api)

    def test_chan_som_khi_khong_co_khung_soan(self):
        """Có đúng chế độ mà thiếu khung soạn thì phải dừng NGAY.

        Không dừng thì `_type_prompt` nuốt lỗi rồi vòng bấm 'Tạo' quay hết ngân
        sách (≥300s) — mỗi lượt treo 5 phút trước khi báo lỗi.
        """
        i = self.code.index("đã chuyển sang tab Video (đã kiểm chứng)")
        khuc = self.code[i:i + 1400]
        self.assertIn("oNhap", khuc)
        self.assertIn("nutGui", khuc)
        self.assertIn("Không vào được màn soạn", khuc)
        # Phải nằm TRƯỚC vòng bấm Tạo.
        self.assertLess(i, self.code.index("flow_video_submit"))

    def test_hai_dau_hieu_da_tieu_khop_dung_loi_solver_nem_ra(self):
        """Bộ nhận dạng phải khớp lỗi THẬT mà `flow_rest` ném, không phải chuỗi bịa.

        Đây là nửa còn lại của cùng một cặp: nhận dạng sai chuỗi thì bộ luật vô
        hiệu — hoặc chạy lại một lượt đã trừ tiền, hoặc chặn oan tài khoản rảnh.
        """
        rest = _code(GOC / "captcha-solver" / "src" / "solvers" / "flow_rest.py")
        # 504 hết giờ chờ: thông báo kèm gen_ids nên chắc chắn Google đã nhận việc.
        self.assertIn("gen_ids={', '.join(gen_ids)}", rest)
        # 502 Google nhận rồi mới dựng hỏng.
        self.assertIn("Google báo thất bại", rest)


class TestVideoXoayTaiKhoanKhiLoi(unittest.TestCase):
    """Lượt video thất bại phải đẩy tài khoản xuống và thử tài khoản khác.

    Đo thật 02/08: `_next_account()` chọn theo ưu tiên CỨNG (index 0 trước), mà
    nhánh video thất bại là raise 502 luôn — không đẩy tài khoản hỏng xuống,
    không thử cái khác. Nên "Backup" hỏng ở index 0 làm MỌI lượt tạo video hỏng
    mãi và không tự khỏi, dù các tài khoản còn lại vẫn tạo được bình thường.
    Nhánh tạo ẢNH đã có `_reorder_flow_account` từ trước; nhánh video thì chưa.
    """

    def setUp(self):
        self.code = _code(GOC / "api" / "veo_video.py")

    def test_co_vong_thu_nhieu_tai_khoan(self):
        self.assertIn("_reorder_flow_account", self.code)
        self.assertIn("_next_account(exclude=_da_thu)", self.code)

    def test_thanh_cong_thi_dua_len_dau_that_bai_thi_day_xuong(self):
        self.assertIn("_reorder_flow_account(acc, to_front=True)", self.code)
        self.assertIn("_reorder_flow_account(acc, to_front=False)", self.code)

    def test_loi_co_the_sau_khi_bam_tao_thi_KHONG_thu_lai(self):
        """Tín dụng đã trừ thì chạy lại là trừ lần hai."""
        i = self.code.index("_co_the_thu_tai_khoan_khac(_loi_cuoi)")
        khuc = self.code[i:i + 500]
        self.assertIn("break", khuc)
        self.assertIn("flow_video_khong_thu_lai", khuc)


class TestDeactivatedNamYen(unittest.TestCase):
    def test_khong_ha_deactivated_ve_error(self):
        code = _code(GOC / "services" / "account_service.py")
        khuc = _khuc(code, "def remove_invalid_token", "def _spawn_dead_recovery")
        self.assertIn('== "deactivated"', khuc)
        # Nhánh bỏ qua phải nằm TRƯỚC mọi lệnh hạ status về 'error'.
        self.assertLess(khuc.index('== "deactivated"'),
                        khuc.index('{"status": "error", "quota": 0}'))

    def test_khong_spawn_khoi_phuc_cho_deactivated(self):
        code = _code(GOC / "services" / "codex_error_recovery_scheduler.py")
        khuc = _khuc(code, "def schedule_dead_account_recovery", "def _scan_and_recover")
        self.assertIn('== "deactivated"', khuc)
        self.assertIn("dead_recovery_skip_deactivated", khuc)
        # Bỏ qua TRƯỚC khi dựng thread chạy cả thang T0–T3.
        self.assertLess(khuc.index("dead_recovery_skip_deactivated"),
                        khuc.index("threading.Thread"))


if __name__ == "__main__":
    unittest.main()
