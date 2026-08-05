"""Câu duyệt GỬI TIN chỉ còn ba lựa chọn.

Đo thật 04/08 22:15–22:19 (Zalo cá nhân). Chủ máy gõ:

    Gửi vào nhóm homeassistant bằng zalo cá nhân với nội dung "mai đi họp"

và nhận lại câu duyệt chép nguyên nội dung ra:

    Em định Gửi tin cho người trong danh bạ (chọn bot):
    → homeassistant: mai đi họp
    Anh/chị duyệt không ạ?

Chủ máy nhắc BỐN lần "chỉ đưa ra lựa chọn, không nhắc lại nội dung". Bot xin lỗi,
còn lưu đúng câu dặn đó vào bộ nhớ — rồi lượt sau vẫn ra y hệt. Lý do: câu duyệt
do CODE dựng trong `approval_gate.format_proposal`, còn bộ nhớ chỉ đi vào prompt
của model, nên dặn kiểu gì cũng không chạm tới được chữ này. Cùng họ với lỗi ở
`test_ap_so_thich_trinh_bay.py`: ghi nhớ một điều mình không làm được thì tệ hơn
không nhớ.

Kèm theo là lỗi thứ hai trong chính đoạn chat đó: câu phàn nàn "Không nhắc lại
nội dung mà" bị tính là lời TỪ CHỐI (bắt đầu bằng "không") nên bot đáp "Dạ thôi
em không làm ạ".

File này khoá năm hành vi:
  * câu duyệt gửi tin CHỈ có ba lựa chọn — không mở lời, không người nhận,
    không nội dung;
  * ba kênh không chèn "..." lấp chỗ trống lên trên ba lựa chọn đó;
  * pending + audit vẫn giữ nội dung đầy đủ (tra lại được đã duyệt gửi cái gì);
  * lời duyệt phải là câu NGẮN — câu nói chuyện dài không bị tính là ok/thôi;
  * DÁN LẠI nguyên câu duyệt của bot không được tính là lời duyệt.
"""
from __future__ import annotations

import ast
import pathlib
import unicodedata
import unittest

from services.agent import approval_gate as gate
from services.agent import orchestrator as orch

GOC = pathlib.Path(__file__).resolve().parents[1]

NGUOI_NHAN = "homeassistant"
NOI_DUNG = "mai đi họp"


class CauDuyetGuiTinTests(unittest.TestCase):
    def _cau_duyet(self, **them) -> str:
        args = {"to": NGUOI_NHAN, "message": NOI_DUNG, "platform": "zalop"}
        args.update(them)
        return gate.format_proposal(
            "send_to_contact", args,
            description="Gửi tin nhắn tới contact đã lưu.",
            label="Gửi tin cho người trong danh bạ (chọn bot)",
        )

    def test_chi_con_ba_lua_chon(self):
        q = self._cau_duyet()
        for thua in (NOI_DUNG, NGUOI_NHAN, "Em định", "Anh/chị duyệt"):
            self.assertNotIn(thua, q)

    def test_van_du_lua_chon_de_duyet(self):
        q = self._cau_duyet()
        for phan in ("<<<ASK>>>", "Ok, làm đi", "Luôn luôn (khỏi hỏi lại)",
                     "Thôi", "<<<END>>>"):
            self.assertIn(phan, q)

    def test_tin_toi_tay_nguoi_dung_dung_la_ba_dong_so(self):
        """Kiểm tới tận chuỗi kênh Zalo gửi đi, không dừng ở khối <<<ASK>>>."""
        from services.agent import ask_choices

        loi, chon = ask_choices.extract(self._cau_duyet())
        self.assertEqual(
            ask_choices.format_numbered(loi, chon),
            "Chọn bằng cách trả lời số:\n"
            "1. Ok, làm đi\n"
            "2. Luôn luôn (khỏi hỏi lại)\n"
            "3. Thôi",
        )

    def test_kenh_khong_chen_dau_ba_cham_truoc_danh_sach(self):
        """Ba kênh đều từng lấp chỗ trống bằng "..." TRƯỚC khi ghép danh sách.

        `(out.get("text") or "").strip() or "..."` — câu duyệt nay không còn lời
        mở nào, nên chính chỗ lấp đó biến thành một dòng "..." lửng lơ ngay trên
        ba lựa chọn. Kiểm ở mức chuỗi nguồn vì import ba module kênh sẽ kéo theo
        cả zalo-server / Telegram client.
        """
        for ten in ("telegram_bot.py", "zalo_bot.py", "zalo_personal.py"):
            src = (GOC / "services" / ten).read_text("utf-8")
            self.assertNotIn('(out.get("text") or "").strip() or "..."', src, ten)

    def test_pending_va_audit_van_giu_noi_dung(self):
        """Giấu ở phần HIỆN RA thôi — bản tra lại vẫn phải thấy đã gửi gì."""
        s = gate.summarize_action("send_to_contact",
                                  {"to": NGUOI_NHAN, "message": NOI_DUNG})
        self.assertIn(NOI_DUNG, s)
        self.assertIn(NGUOI_NHAN, s)

    def test_tool_khac_giu_nguyen_cau_duyet(self):
        """Loa vẫn phải hiện đủ loa nào / âm lượng / nội dung (yêu cầu 02/08)."""
        q = gate.format_proposal(
            "announce_on_speaker",
            {"text": NOI_DUNG, "speaker": "loa phòng khách",
             "volume": 50, "am_luong_da_chon": True},
            label="Đọc thông báo ra loa",
        )
        self.assertIn(NOI_DUNG, q)
        self.assertIn("loa phòng khách", q)
        self.assertIn("50%", q)
        self.assertIn("Em định", q)
        self.assertIn("Anh/chị duyệt không ạ?", q)


class LoiDuyetPhaiNganTests(unittest.TestCase):
    def test_cau_phan_nan_khong_bi_tinh_la_tu_choi(self):
        for cau in ("Không nhắc lại nội dung mà",
                    "Từ bây giờ không nhắc lại nội dung chỉ đưa ra lựa chọn",
                    "Anh đã yêu cầu không nhắc lại nội dung mà"):
            self.assertIsNone(orch._classify_reply(cau), cau)

    def test_dan_lai_cau_cua_bot_khong_phai_loi_duyet(self):
        """Chép nguyên câu bot vừa gửi rồi gửi lại: KHÔNG tính là duyệt.

        Bản cũ dò "luôn luôn" / "khỏi hỏi" ở BẤT KỲ đâu trong câu, mà chính câu
        duyệt của bot có sẵn hai chữ đó trong phần lựa chọn. Dán lại nguyên khối
        (chủ máy đã làm đúng thế lúc 22:16:18) là bot đọc thành "Luôn luôn (khỏi
        hỏi lại)" → chạy luôn việc đang chờ VÀ cấp quyền khỏi-hỏi vĩnh viễn cho
        tool đó. Lần đó thoát nạn chỉ vì pending đã bị xoá từ trước.
        """
        dan_lai = (
            "Em định Gửi tin cho người trong danh bạ (chọn bot):\n"
            "→ homeassistant: mai đi họp\n\n"
            "Anh/chị duyệt không ạ?\n\n"
            "Chọn bằng cách trả lời số:\n"
            "1. Ok, làm đi\n"
            "2. Luôn luôn (khỏi hỏi lại)\n"
            "3. Thôi"
        )
        self.assertIsNone(orch._classify_reply(dan_lai))
        self.assertIsNone(orch._classify_reply(
            gate.format_proposal("send_to_contact", {"to": NGUOI_NHAN,
                                                     "message": NOI_DUNG})))

    def test_loi_duyet_ngan_van_chay(self):
        for cau, mong in (("Thôi", "deny"),
                          ("thôi khỏi", "deny"),
                          ("ok", "once"),
                          ("Ok, làm đi", "once"),
                          ("ừ làm đi em", "once"),
                          ("Luôn luôn (khỏi hỏi lại)", "always"),
                          ("luôn luôn", "always")):
            self.assertEqual(orch._classify_reply(cau), mong, cau)


def _nap_ham(nguon: pathlib.Path, ten: str):
    """Nạp RIÊNG một hàm — import cả module sẽ kéo theo config/DB/model."""
    src = nguon.read_text("utf-8")
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef) and n.name == ten:
            ns: dict = {}
            exec(ast.get_source_segment(src, n), ns)
            return ns[ten]
    raise AssertionError(f"không thấy hàm {ten} trong {nguon}")


def _bo_dau(s: str) -> str:
    """Giống `ha_client._fold_diacritics` + đ→d — dạng chuỗi mà đường tắt nhận."""
    nfkd = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).replace("đ", "d")


_LA_CAU_HOI_GIO = _nap_ham(
    GOC / "services" / "protocol" / "openai_v1_chat_complete.py",
    "_la_cau_hoi_gio",
)


class HoiGioChuKhongPhaiDanDoTests(unittest.TestCase):
    """"Từ bây giờ …" là lời DẶN, không phải câu hỏi giờ.

    Đo thật 04/08 22:15:53 — chủ máy dặn "Từ bây giờ không nhắc lại nội dung chỉ
    đưa ra lựa chọn" thì nhận lại "Dạ, bây giờ là 22 giờ 15 phút, Thứ Ba…":
    đường tắt trả giờ chỉ tìm chuỗi con "bay gio" nên cướp mất lượt đó.
    """

    def test_loi_dan_khong_bi_tra_gio(self):
        for cau in ("Từ bây giờ không nhắc lại nội dung chỉ đưa ra lựa chọn",
                    "bây giờ anh muốn em trả lời ngắn thôi",
                    "từ bây giờ gửi tin thì hỏi lại em nhé"):
            self.assertFalse(_LA_CAU_HOI_GIO(_bo_dau(cau)), cau)

    def test_cau_hoi_gio_that_van_chay(self):
        for cau in ("mấy giờ rồi", "bây giờ là mấy giờ", "bây giờ",
                    "anh ơi cho em hỏi bây giờ là mấy giờ rồi ạ", "giờ rồi em"):
            self.assertTrue(_LA_CAU_HOI_GIO(_bo_dau(cau)), cau)


if __name__ == "__main__":
    unittest.main()
