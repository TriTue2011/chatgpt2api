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

File này khoá chín hành vi:
  * câu duyệt gửi tin CHỈ có ba lựa chọn — không mở lời, không người nhận,
    không nội dung;
  * ba kênh không chèn "..." lấp chỗ trống lên trên ba lựa chọn đó;
  * pending + audit vẫn giữ nội dung đầy đủ (tra lại được đã duyệt gửi cái gì);
  * DẶN BẰNG LỜI đổi được cách hiện đó thật (capability `cai_dat_cau_duyet`),
    không phải chỉ được "ghi nhớ" rồi thôi;
  * người nhận trùng tên / nhiều kênh → hỏi bằng DANH SÁCH ĐÁNH SỐ bấm được,
    không bắt người dùng gõ lại tên kênh;
  * mọi menu đánh số MỘT kiểu "1. ", không dùng keycap "1️⃣" (vỡ phông Zalo);
  * lời duyệt phải là câu NGẮN — câu nói chuyện dài không bị tính là ok/thôi;
  * DÁN LẠI nguyên câu duyệt của bot không được tính là lời duyệt;
  * gửi FILE thì câu duyệt hiện TÊN FILE — tên file không phải nội dung tin, mà
    là thứ duy nhất phân biệt gửi đúng với gửi nhầm.
"""
from __future__ import annotations

import ast
import pathlib
import unicodedata
import unittest
from unittest import mock

from services.agent import approval_gate as gate
from services.agent import orchestrator as orch
from services.config import config

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


class DanBangLoiThiAnNgayTests(unittest.TestCase):
    """Dặn bằng lời phải ĐỔI ĐƯỢC câu duyệt — không chỉ được "ghi nhớ" rồi thôi.

    Yêu cầu 05/08: "thử làm yêu cầu 2 xem được không, nếu không được xây dựng
    code cho được" — yêu cầu 2 là "từ giờ về sau thêm nội dung vào câu lựa chọn".
    Trước đó bot chỉ lưu được vào bộ nhớ, mà bộ nhớ không chạm tới câu duyệt.
    """

    def _cau_duyet(self) -> str:
        return gate.format_proposal(
            "send_to_contact", {"to": NGUOI_NHAN, "message": NOI_DUNG},
            label="Gửi tin cho người trong danh bạ (chọn bot)")

    def test_bat_len_thi_cau_duyet_co_nguoi_nhan_va_noi_dung(self):
        with mock.patch.dict(config.data,
                             {"agent_approval": {"hien_noi_dung_gui_tin": True}}):
            q = self._cau_duyet()
        self.assertIn(NGUOI_NHAN, q)
        self.assertIn(NOI_DUNG, q)
        self.assertIn("Anh/chị duyệt không ạ?", q)

    def test_mac_dinh_va_khi_tat_thi_van_chi_ba_lua_chon(self):
        for cfg in ({}, {"hien_noi_dung_gui_tin": False}):
            with mock.patch.dict(config.data, {"agent_approval": cfg}):
                q = self._cau_duyet()
            self.assertNotIn(NOI_DUNG, q, cfg)
            self.assertNotIn(NGUOI_NHAN, q, cfg)

    def test_ghi_cai_dat_khong_lam_mat_khoa_anh_em(self):
        """`config.update` thay NGUYÊN CỤM agent_approval — đừng nuốt level/ttl."""
        with mock.patch.dict(config.data,
                             {"agent_approval": {"level": "supervised",
                                                 "ttl_seconds": 900}}), \
                mock.patch.object(config, "update") as ghi:
            gate.dat_hien_noi_dung_gui_tin(True)
        ghi.assert_called_once_with({"agent_approval": {
            "level": "supervised", "ttl_seconds": 900,
            "hien_noi_dung_gui_tin": True}})

    def test_tool_doi_duoc_ca_hai_chieu(self):
        from services.agent import capabilities as caps

        cap = caps.get("cai_dat_cau_duyet")
        self.assertIsNotNone(cap)
        self.assertEqual(caps.group_of("cai_dat_cau_duyet"), "contacts")
        for tham_so, mong in (({"hien_noi_dung": True}, True),
                              ({"hien_noi_dung": False}, False),
                              # Model hay trả CHUỖI — bool("false") là True.
                              ({"hien_noi_dung": "false"}, False),
                              ({"hien_noi_dung": "true"}, True)):
            with mock.patch.object(gate, "dat_hien_noi_dung_gui_tin") as dat:
                cap.handler(dict(tham_so), {})
            dat.assert_called_once_with(mong)

    def test_hoi_khong_kem_tham_so_thi_chi_bao_dang_de_kieu_nao(self):
        from services.agent import capabilities as caps

        with mock.patch.object(gate, "dat_hien_noi_dung_gui_tin") as dat, \
                mock.patch.dict(config.data, {"agent_approval": {}}):
            ra = caps.get("cai_dat_cau_duyet").handler({}, {})
        dat.assert_not_called()
        self.assertIn("ba lựa chọn", ra.get("text") or "")


class HoiLaiPhaiCoDanhSachDanhSoTests(unittest.TestCase):
    """Ứng viên là tập HỮU HẠN đã tra được → hỏi bằng danh sách đánh số.

    Yêu cầu 05/08: "những cái nào có lựa chọn sẵn thì danh sách đánh số để lựa
    chọn, còn cần user đánh thì mới không đưa ra lựa chọn theo kiểu đánh số".
    Bản cũ trả một câu văn "«X» chưa nêu rõ kênh — nói rõ giúp em: A; B" bắt
    người dùng gõ lại tên kênh.
    """

    def _goi(self, args: dict) -> dict:
        from services import channel_contacts as cc
        from services.agent import capabilities as caps

        def _thu_muc(pf: str):
            if pf == "zalop":
                return [{"bot_id": "", "bot_label": "", "thread_id": "111",
                         "kind": "group", "name": "homeassistant"}]
            if pf == "tg":
                return [{"bot_id": "222", "bot_label": "Bot Nhà", "thread_id": "333",
                         "kind": "group", "name": "homeassistant"}]
            return []

        with mock.patch.object(cc, "resolve_alias", return_value=[]), \
                mock.patch.object(cc, "list_directory", side_effect=_thu_muc):
            return caps.get("send_to_contact").handler(
                args, {"user_id": "zalop_9", "user_message": ""})

    def test_trung_ten_nhieu_kenh_thi_ra_danh_sach_bam_duoc(self):
        from services.agent import ask_choices

        ra = self._goi({"to": NGUOI_NHAN, "message": NOI_DUNG})
        loi, chon = ask_choices.extract(ra.get("text") or "")
        self.assertGreaterEqual(len(chon), 2)
        danh_sach = ask_choices.format_numbered(loi, chon)
        self.assertIn("1. ", danh_sach)
        self.assertIn("2. ", danh_sach)
        self.assertIn("Zalo cá nhân", danh_sach)
        self.assertIn("Telegram", danh_sach)
        # Bấm số nào là gửi thẳng vào ĐÚNG chat đó, không hỏi lại kênh lần nữa.
        self.assertTrue(any("111" in c["send"] for c in chon), chon)
        self.assertTrue(any("thôi" in c["send"].lower() for c in chon), chon)

    def test_khong_con_bat_nguoi_dung_go_lai_ten_kenh(self):
        ra = self._goi({"to": NGUOI_NHAN, "message": NOI_DUNG})
        self.assertNotIn("nói rõ giúp em", ra.get("text") or "")

    def test_tin_nhieu_dong_khong_lam_vo_danh_sach(self):
        """Menu bóc theo TỪNG DÒNG — tin xuống dòng sẽ đẻ ra lựa chọn rác."""
        from services.agent import ask_choices

        ra = self._goi({"to": NGUOI_NHAN, "message": "mai đi họp\n8h sáng nhé"})
        _, chon = ask_choices.extract(ra.get("text") or "")
        self.assertEqual(len(chon), 3, chon)
        self.assertTrue(all("8h sáng nhé" not in c["label"] for c in chon), chon)


class DinhDangZaloTests(unittest.TestCase):
    """Zalo cá nhân có 13 kiểu chữ (bảng TextStyle của zca-js), bot mới dùng 9.

    Yêu cầu 05/08: "màu thì cài đặt, nhưng in đậm / in nghiêng thì tự động thay
    đổi phù hợp với văn bản … khi cần thiết tôi yêu cầu không dùng nữa bằng ra
    lệnh cho bot". Nên danh sách / thụt lề / gạch chân bot TỰ áp, và đổi được
    bằng lời qua `cai_dat_dinh_dang` chứ không phải đi tick trong Settings.
    """

    def _md(self, text: str, **kw):
        from services.zalo_markdown import markdown_to_zalo_message

        return markdown_to_zalo_message(text, color="orange", size="normal", **kw)

    def test_dau_dau_dong_thanh_danh_sach_cua_zalo(self):
        ra = self._md("- mục một\n- mục hai")
        self.assertEqual(ra["msg"], "mục một\nmục hai")
        self.assertEqual([s["st"] for s in ra["styles"]], ["lst_1", "lst_1"])

    def test_danh_so_thanh_lst_2(self):
        ra = self._md("1. số một\n2. số hai")
        self.assertEqual(ra["msg"], "số một\nsố hai")
        self.assertEqual([s["st"] for s in ra["styles"]], ["lst_2", "lst_2"])

    def test_thut_le_theo_cap(self):
        ra = self._md("- cha\n  - con\n    - chau")
        self.assertIn("ind_10", [s["st"] for s in ra["styles"]])
        self.assertIn("ind_20", [s["st"] for s in ra["styles"]])

    def test_bo_dau_dau_dong_khong_lam_lech_vung_dam(self):
        """Bỏ '- ' làm chuỗi ngắn đi — style inline phía sau phải dời theo."""
        ra = self._md("- **đậm** trong mục")
        dam = [s for s in ra["styles"] if "b" in s["st"].split(",")][0]
        self.assertEqual(ra["msg"][dam["start"]:dam["start"] + dam["len"]], "đậm")

    def test_tat_thi_giu_nguyen_chu(self):
        ra = self._md("- mục một", danh_sach=False, thut_le=False)
        self.assertEqual(ra["msg"], "- mục một")
        self.assertEqual(ra["styles"], [])

    def test_tieu_de_cap_1_dung_f_18(self):
        """f_20 không có trong bảng TextStyle của zca-js — gửi lên là mã lạ."""
        ra = self._md("# Tiêu đề")
        self.assertIn("f_18", ra["styles"][0]["st"])
        self.assertNotIn("f_20", ra["styles"][0]["st"])

    def test_ra_lenh_bang_loi_doi_duoc_cai_dat(self):
        from services.agent import capabilities as caps

        self.assertEqual(caps.group_of("cai_dat_dinh_dang"), "contacts")
        with mock.patch.object(config, "update") as ghi:
            caps.get("cai_dat_dinh_dang").handler(
                {"nhan_manh": "false", "kieu": "italic", "danh_sach": False}, {})
        ghi.assert_called_once_with({
            "telegram_emphasis_enabled": False,
            "telegram_emphasis_style": "italic",
            "zalo_markdown_list": False,
        })

    def test_hoi_khong_kem_tham_so_thi_chi_bao_trang_thai(self):
        from services.agent import capabilities as caps

        with mock.patch.object(config, "update") as ghi:
            ra = caps.get("cai_dat_dinh_dang").handler({}, {})
        ghi.assert_not_called()
        self.assertIn("danh sách", ra.get("text") or "")


class DinhDangZaloBotTests(unittest.TestCase):
    """Zalo Bot: đo thật 05/08 11:19 trên Bot Mít Bắp.

    Gửi `parse_mode=markdown` thì Zalo hiện ĐÚNG đậm / nghiêng / gạch chân /
    màu / chữ to / chấm đầu dòng / đánh số. Đường `text_styles` cũng ăn b, u,
    lst_1, lst_2 nhưng `ind_10` KHÔNG thụt — nên giữ nguyên đường markdown.

    Hai kênh Zalo viết gạch chân khác nhau: cá nhân nhận mã `u` (từ `__…__`),
    Bot chỉ hiểu thẻ `{underline}`.
    """

    def _gui(self, text: str) -> str:
        from services.zalo_bot_format import build_send_message_payload

        return build_send_message_payload("1", text, rich=True)[0]["text"]

    def test_gach_chan_doi_sang_the_cua_zalo_bot(self):
        self.assertEqual(self._gui("__gach chan__"),
                         "{underline}gach chan{/underline}")

    def test_dau_dau_dong_giu_nguyen_cho_zalo_tu_ve(self):
        self.assertEqual(self._gui("- muc mot\n- muc hai"), "- muc mot\n- muc hai")

    def test_so_thu_tu_khong_bi_to_dam_lam_vo_danh_sach(self):
        """"1. mục" thành "**1**. mục" là danh sách vỡ — cả Zalo lẫn Telegram."""
        self.assertEqual(self._gui("1. so mot\n2) so hai"), "1. so mot\n2) so hai")

    def test_so_lieu_that_van_duoc_nhan_manh(self):
        ra = self._gui("Nhiet do 29°C, do am 79%")
        self.assertIn("**29°C**", ra)
        self.assertIn("**79%**", ra)

    def test_so_giua_cau_van_duoc_nhan_manh(self):
        self.assertIn("**2**", self._gui("Ban thang 1. Sau do 2 nguoi"))

    def test_zalo_ca_nhan_cung_huong_loi_sua_so_thu_tu(self):
        """Trước bản sửa, "**1**." làm `_RE_SO` hết khớp → mất luôn lst_2."""
        from services.telegram.emphasis import emphasize_text
        from services.zalo_markdown import markdown_to_zalo_message

        ra = markdown_to_zalo_message(emphasize_text("1. so mot\n2. so hai"),
                                      color="orange", size="normal")
        self.assertEqual(ra["msg"], "so mot\nso hai")
        self.assertEqual([s["st"] for s in ra["styles"]], ["lst_2", "lst_2"])


class MenuDanhSoMotKieuTests(unittest.TestCase):
    """Mọi menu đánh số theo MỘT kiểu: "1. ", không dùng keycap "1️⃣".

    Ảnh chụp 05/08 10:48 — menu PDF trên Zalo hiện ô vuông vỡ phông ở chỗ số,
    vì keycap là ký tự ghép Zalo dựng bằng font khác. `ask_choices` vốn đã dùng
    "1. " nên quy hết về kiểu đó.
    """

    def test_khong_con_keycap_trong_menu(self):
        for ten in ("pdf_intent.py", "photo_intent.py"):
            src = (GOC / "services" / ten).read_text("utf-8")
            self.assertNotIn('{n}️⃣', src, ten)

    def test_menu_pdf_danh_so_bang_dau_cham(self):
        from services import pdf_intent as pi

        t = pi.ask_text("a.pdf", {pi.WORD, pi.EXCEL})
        self.assertIn("1. ", t)
        self.assertIn("2. ", t)
        self.assertNotIn("️⃣", t)


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



class CauDuyetGuiFileTests(unittest.TestCase):
    """Gửi FILE thì câu duyệt hiện TÊN FILE, dù đang ở chế độ chỉ-ba-lựa-chọn.

    Chốt 05/08: tên file không phải "nội dung tin nhắn" — nó là thứ duy nhất
    phân biệt gửi đúng với gửi nhầm, nhất là khi người dùng nói "gửi file vừa
    tạo" và bot tự lấy file mới nhất. Gửi nhầm tài liệu vào nhóm thì không rút
    lại được.
    """

    def _duyet(self, **args) -> str:
        return gate.format_proposal("send_to_contact",
                                    {"to": NGUOI_NHAN, **args},
                                    label="Gửi tin cho người trong danh bạ")

    def test_co_file_thi_hien_ten_file(self):
        q = self._duyet(file="HTT_-_Phuong_an_CHCN_co_so.docx")
        self.assertIn("📎 HTT_-_Phuong_an_CHCN_co_so.docx", q)
        self.assertIn("<<<ASK>>>", q)
        # Vẫn không nhắc người nhận hay nội dung.
        self.assertNotIn(NGUOI_NHAN, q)

    def test_chi_hien_ten_khong_hien_ca_duong_dan(self):
        q = self._duyet(file="thu/muc/con/bao-cao.xlsx")
        self.assertIn("📎 bao-cao.xlsx", q)
        self.assertNotIn("thu/muc/con", q)

    def test_tin_chu_thuong_van_chi_ba_lua_chon(self):
        q = self._duyet(message=NOI_DUNG)
        self.assertNotIn("📎", q)
        self.assertNotIn(NOI_DUNG, q)

if __name__ == "__main__":
    unittest.main()
