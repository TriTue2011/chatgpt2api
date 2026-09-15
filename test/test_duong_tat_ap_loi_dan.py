"""MỌI câu trả lời không do model viết đều phải đi qua lời dặn đã ghi nhớ.

Lời dặn ("trả lời ngắn gọn", "hỏi thời tiết thì thêm khuyến cáo") được tiêm vào
system prompt, nên lượt DO MODEL trả lời thì tôn trọng nó. Nhưng bot có cả chục
ĐƯỜNG TẮT trả lời trước khi model được gọi — tin tức, mã mục tin, lấy media, đọc
loa, workflow, kết quả tool trả thẳng — và mỗi đường tắt là một chỗ lời dặn bị
bỏ qua sạch. Bot vẫn "ghi nhớ" rồi hứa, người dùng tưởng đã xong.

Trước bản này, `_ap_so_thich` — hàm sinh ra đúng để vá chuyện đó — KHÔNG có một
chỗ gọi nào trong code chạy thật: chỉ bộ test gọi nó. Và nó đọc kho trí nhớ
CHUNG trong khi `remember` ghi vào kho riêng theo phạm vi, nên kể cả có gọi thì
cũng không thấy lời dặn nào.

File này khoá bốn tính chất:
  * đọc lời dặn ĐÚNG phạm vi của lượt;
  * lời dặn đòi THÊM phần (lưu ý/khuyến cáo) không bị lời nhắc "đừng thêm" chặn;
  * KHÔNG đụng vào tin có khối `<<<ASK>>>` (menu, câu hỏi xin duyệt);
  * mọi chỗ trả kết quả trong orchestrator đều đã CHỦ Ý chọn có áp hay không.
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402
from services.agent import state  # noqa: E402

GOC = "/Volumes/DATA/Code/chatgpt2api"
_ORCH = Path(orch.__file__)

DAN = "- Trả lời ngắn gọn thôi, và nhớ thêm phần lưu ý cho anh."


def _tra_loi(noi_dung: str):
    return {"choices": [{"message": {"content": noi_dung}}]}


class DocLoiDanDungPhamVi(unittest.TestCase):
    """`remember` ghi vào kho RIÊNG của phạm vi (kênh/chat/người).

    Đọc kho chung không thôi thì lời dặn vừa lưu xong không có tác dụng — đúng
    cái bẫy mà docstring `_so_thich_trinh_bay` đã ghi, mà `_ap_so_thich` lại
    mắc đúng vào.
    """

    def test_truyen_pham_vi_xuong_kho_tri_nho(self):
        thay = {}

        def _doc(*a, **kw):
            thay.update(kw)
            return DAN

        with patch.object(state, "load_memory", side_effect=_doc), \
             patch.object(orch, "call_model", return_value=_tra_loi("bản ngắn gọn")):
            orch._ap_so_thich("nội dung gốc dài vừa đủ", "hỏi gì", lambda k: "m",
                              pham_vi="zalo:99")
        self.assertEqual(thay.get("pham_vi"), "zalo:99",
                         "đọc nhầm kho = lời dặn vừa lưu không bao giờ có tác dụng")


class ChoPhepPhanThemTheoLoiDan(unittest.TestCase):
    """Lời nhắc cũ nói "TUYỆT ĐỐI KHÔNG thêm" — đúng cho DỮ KIỆN, nhưng model
    đọc là cấm luôn cả phần lưu ý mà chính người dùng đòi thêm."""

    def test_prompt_noi_ro_phan_them_duoc_phep(self):
        thay = {}

        def _bat(model, messages, **kw):
            thay["messages"] = messages
            return _tra_loi("bản đã bày lại, giữ nguyên nội dung gốc bên trong")

        with patch.object(state, "load_memory", return_value=DAN), \
             patch.object(orch, "call_model", side_effect=_bat):
            orch._ap_so_thich("nội dung gốc", "hỏi gì", lambda k: "m")
        he_thong = " ".join(str(m.get("content") or "") for m in thay["messages"]
                            if m.get("role") == "system")
        self.assertIn("được phép viết thêm", he_thong)
        self.assertIn("KHÔNG được đổi DỮ KIỆN", he_thong)

    def test_luot_bay_lai_khong_duoc_tra_web(self):
        """Chỉ viết lại đoạn văn đã có sẵn thì không được đi tìm kiếm: gateway
        sẽ tiêm kết quả tra về kèm "BẮT BUỘC ĐỌC VÀ TRẢ LỜI DỰA TRÊN ĐÂY",
        tranh chỗ với chính lời dặn, và tốn thêm hơn mười giây."""
        thay = {}

        def _bat(model, messages, **kw):
            thay.update(kw)
            return _tra_loi("bản đã bày lại, giữ nguyên nội dung gốc bên trong")

        with patch.object(state, "load_memory", return_value=DAN), \
             patch.object(orch, "call_model", side_effect=_bat):
            orch._ap_so_thich("nội dung gốc", "hỏi gì", lambda k: "m")
        self.assertEqual(thay.get("allowed_groups"), set())


class KhongDungVaoMenu(unittest.TestCase):
    """Từng dòng trong khối `<<<ASK>>>` là một NÚT do code dựng và code bóc lại.

    Nhờ model viết lại khối đó là mời nó xoá mất nút — người dùng nhận một câu
    hỏi chọn lựa mà không còn lựa chọn nào.
    """

    MENU = ('🔊 Đọc "chuẩn bị đi ngủ" ra loa nào ạ?\n'
            "<<<ASK>>>\nLoa phòng khách | phong_khach\nTất cả loa | tat_ca\n<<<END>>>")

    def test_giu_nguyen_va_khong_goi_model(self):
        goi = []
        with patch.object(state, "load_memory", return_value=DAN), \
             patch.object(orch, "call_model", side_effect=lambda *a, **k: goi.append(1)):
            ra = orch._ap_so_thich(self.MENU, "phát loa", lambda k: "m")
        self.assertEqual(ra, self.MENU)
        self.assertEqual(goi, [], "menu mà vẫn nhờ model viết lại = mất nút bấm")


class FinalizeChiApKhiDuocBao(unittest.TestCase):
    """`_finalize` là chỗ MỌI câu trả lời đi qua — cả lượt do model viết.

    Lượt model đã có trí nhớ trong system prompt, bày lại lần nữa vừa tốn một
    lượt gọi model vừa thêm chỗ sai. Nên bước áp lời dặn phải là CHỌN, không
    phải mặc định.
    """

    def test_khong_bao_thi_khong_goi_model(self):
        goi = []
        with patch.object(state, "load_memory", return_value=DAN), \
             patch.object(orch, "call_model", side_effect=lambda *a, **k: goi.append(1)):
            ra = orch._finalize("u1", {"text": "câu do model viết"})
        self.assertEqual(ra.get("text"), "câu do model viết")
        self.assertEqual(goi, [])

    def test_co_bao_thi_ap(self):
        with patch.object(state, "load_memory", return_value=DAN), \
             patch.object(orch, "call_model",
                          return_value=_tra_loi("câu do model viết, đã bày lại gọn")):
            ra = orch._finalize("u1", {"text": "câu do model viết"},
                                ap_loi_dan="hỏi gì đó")
        self.assertEqual(ra.get("text"), "câu do model viết, đã bày lại gọn")

    def test_khong_co_loi_dan_nao_thi_khong_ton_luot_model(self):
        goi = []
        with patch.object(state, "load_memory", return_value="- Anh tên là Việt."), \
             patch.object(orch, "call_model", side_effect=lambda *a, **k: goi.append(1)):
            ra = orch._finalize("u1", {"text": "kết quả đường tắt"},
                                ap_loi_dan="hỏi gì")
        self.assertEqual(ra.get("text"), "kết quả đường tắt")
        self.assertEqual(goi, [], "không ai dặn gì mà vẫn gọi model = tốn lượt vô ích")

    def test_bay_lai_truoc_roi_moi_danh_ma_muc(self):
        """Thứ tự phải là bày lại TRƯỚC, đánh mã mục SAU — mã A1/B2 phải trỏ vào
        đúng bản văn người dùng nhận được, và nguồn tra ("tin") không được rơi
        trên đường, kẻo lượt sau gõ "A1" không tra được gì."""
        from services.agent import muc_luc as _ml
        thay = {}

        def _bat_ml(result, user_id):
            thay["text"] = str(result.get("text") or "")
            thay["nguon"] = str(result.get("muc_luc_nguon") or "")
            return result

        with patch.object(state, "load_memory", return_value=DAN), \
             patch.object(orch, "call_model", return_value=_tra_loi("bản tin đã gọn lại")), \
             patch.object(_ml, "apply_to_result", side_effect=_bat_ml):
            orch._finalize("u1", {"text": "bản tin", "muc_luc_nguon": "tin"},
                           ap_loi_dan="tin tức")
        self.assertEqual(thay.get("text"), "bản tin đã gọn lại")
        self.assertEqual(thay.get("nguon"), "tin")

    def test_menu_di_qua_finalize_van_con_nut(self):
        """Chốt cuối: menu đi qua đường có áp lời dặn vẫn phải ra đủ nút."""
        with patch.object(state, "load_memory", return_value=DAN), \
             patch.object(orch, "call_model", return_value=_tra_loi("mất hết nút rồi")):
            ra = orch._finalize("u_menu", {"text": KhongDungVaoMenu.MENU},
                                ap_loi_dan="phát loa")
        self.assertEqual(len(ra.get("choices") or []), 2)


class MoiChoTraKetQuaDeuPhaiChonCoY(unittest.TestCase):
    """Đếm số chỗ gọi `_finalize` có / không áp lời dặn.

    Không phải để chốt một con số đẹp, mà để thêm một đường trả kết quả mới thì
    BẮT BUỘC phải dừng lại quyết định: câu này do model viết (trí nhớ đã có
    trong prompt → không áp), hay là văn bản đường tắt (phải áp). Chính vì chưa
    ai buộc phải quyết định mà `_ap_so_thich` nằm chết trong code suốt.

    Mười hai chỗ CỐ Ý không áp:
      * wizard Speech Persona và luồng Facebook — câu hỏi của một máy trạng
        thái, chữ nghĩa là giao diện chứ không phải câu trả lời;
      * menu chọn model ảnh, hai câu hỏi xin duyệt, tin gộp «kết quả + xin
        duyệt» — trong đó có khối `<<<ASK>>>` dựng bằng code;
      * đường tắt nhà thông minh — đã mang lời dặn theo ngay ở lượt diễn đạt
        của chính nó, áp lần hai là gọi model thêm một lượt cho cùng một câu;
      * câu do chính model viết ở cuối vòng agent — trí nhớ đã nằm trong system
        prompt của lượt đó;
      * báo MÃ MỤC không khớp (hết hạn / sai mã / bảng trống) — thông báo hệ
        thống chính xác, cố ý để CODE nói lý do thật; áp lời dặn là gọi model
        viết lại một câu ngắn cố định, vừa tốn lượt vừa dễ làm sai lý do.
      * menu chọn người nhận lịch và lượt chọn đã lưu — đây là biểu mẫu hành
        động do code dựng, giữ nguyên mã lựa chọn và payload đã xác thực; nhờ
        model bày lại có thể làm đổi nút hoặc đích nhận.
      * đường tắt THỜI TIẾT (15/09/2026) — câu trả lời thời tiết đã được áp lời
        dặn bằng `_ap_so_thich` ngay trước đó, rồi mới gắn nút «Đổi địa danh» /
        «Đúng rồi». Áp ở `_finalize` thì quá muộn: tin đã có khối `<<<ASK>>>`
        nên `_ap_so_thich` tự bỏ qua, lời dặn «thêm lưu ý, dặn dò» rơi mất.
    """

    def setUp(self):
        cay = ast.parse(_ORCH.read_text("utf-8"))
        self.co, self.khong = [], []
        for n in ast.walk(cay):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_finalize"):
                (self.co if any(k.arg == "ap_loi_dan" for k in n.keywords)
                 else self.khong).append(n.lineno)

    def test_so_cho_ap_loi_dan(self):
        # 11 gồm cả bản tin CHỦ ĐỀ ĐANG THEO DÕI: câu gửi thẳng cho người dùng
        # nên phải mang giọng và lời dặn của họ như mọi câu trả lời khác.
        # 12 từ 14/09/2026: nút menu MỞ NHẠC — cùng quyết định với nút menu loa
        # đọc thông báo: kết quả "[đang phát …]" là văn bản đường tắt nên áp;
        # khi nó là menu thì `_ap_so_thich` tự bỏ qua khối <<<ASK>>>.
        self.assertEqual(len(self.co), 12,
                         "thêm/bớt đường trả kết quả thì phải quyết định có áp "
                         "lời dặn hay không, rồi sửa con số này")

    def test_so_cho_co_y_khong_ap(self):
        self.assertEqual(len(self.khong), 12,
                         "một chỗ trả kết quả mới KHÔNG áp lời dặn phải có lý "
                         "do ghi trong docstring của lớp test này")


if __name__ == "__main__":
    unittest.main()
