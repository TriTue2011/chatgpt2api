"""Phát ra loa: đủ loa + âm lượng + nội dung, và báo ĐÚNG kết quả thật.

Đo thật 02/08 trên Zalo (nguyên văn):

    18:10:13 người dùng : phát thông báo ra loa với nội dung chuẩn bị đi ăn gà rán thôi các con
    18:10:26 bot        : Em định Hẹn giờ / đọc thông báo ra loa: … — duyệt không?
    18:10:37 người dùng : phát ngay
    18:10:42 bot        : … muốn phát ra loa nào vậy: loa phòng khách hay tất cả loa?
    18:10:49 người dùng : loa phòng khách
    18:11:05 bot        : Em định Phát tiếng ra loa trong nhà: … — duyệt không?
    18:11:15 người dùng : âm lượng 60%
    18:11:22 bot        : Em định Hẹn giờ / đọc thông báo ra loa: … — duyệt không?
    18:11:24 người dùng : 1
    18:11:25 bot        : [đang đọc “chuẩn bị đi ăn gà rán thôi các con” ra loa phòng khách]

Loa im. Log máy chủ nói thẳng nguyên nhân:

    announce: phát lỗi ra loa phòng khách: Chưa đặt voice.public_base_url —
    loa trong nhà không tải được file từ localhost.

Ba lỗi tách bạch:
  1. `schedule(delay=0)` chạy qua `threading.Timer(0, …)` — thread NỀN. Hàm trả
     về TRƯỚC khi biết kết quả, lỗi chỉ vào `logger.warning`, người dùng nhận một
     câu báo thành công sai sự thật.
  2. Câu duyệt lặp lại mà mất sạch «loa phòng khách» và «60%» — mỗi lượt model
     định tuyến dựng lại args từ đầu.
  3. Không có bước nào hỏi âm lượng.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

GOC = pathlib.Path(__file__).resolve().parents[1]

NOI_DUNG = "chuẩn bị đi ăn gà rán thôi các con"


def _nap(nguon: pathlib.Path, ten: tuple[str, ...], extra: dict | None = None) -> dict:
    """Nạp RIÊNG vài hàm/biến — import cả module sẽ kéo theo config/DB/model."""
    src = nguon.read_text("utf-8")
    phan = ["from __future__ import annotations", "import re", "from typing import Any"]
    for n in ast.parse(src).body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ten:
            phan.append(ast.get_source_segment(src, n))
        if isinstance(n, (ast.FunctionDef,)) and n.name in ten:
            phan.append(ast.get_source_segment(src, n))
    ns: dict = {"re": re}
    ns.update(extra or {})
    exec("\n".join(phan), ns)
    return ns


LOA_CAST = {"id": "spk1", "name": "loa phòng khách", "kind": "cast",
            "host": "192.168.1.9"}
LOA_R1 = {"id": "r1a", "name": "loa R1", "kind": "r1", "host": "192.168.1.20",
          "max_vol": 15}
LOA_DLNA = {"id": "d1", "name": "loa gác", "kind": "dlna", "host": "192.168.1.30"}
LOA_BEP = {"id": "s2", "name": "loa bếp", "kind": "cast", "host": "192.168.1.10"}


def _ns_menu() -> dict:
    return _nap(GOC / "services" / "agent" / "capabilities.py",
                ("_LOA_MUC_AM", "_TEN_TAT_CA", "_LOA_TAT_CA", "_GIU_NGUYEN", "_MA_GIU",
                 "_ask_am_luong_loa", "_ask_chon_loa", "_ask_tuy_chon_loa",
                 "_ma_hoa_ke_hoach", "_giai_ma_ke_hoach", "_ask_am_luong_tung_loa",
                 "_nguoi_co_neu_am_luong", "_fold_loa", "_mot_dong"))


def _ns_doc() -> dict:
    return _nap(GOC / "services" / "agent" / "orchestrator.py",
                ("_NUT_LOA", "_NUT_CHON_LOA", "_NUT_LOA_NHIEU", "_NUT_TUY_CHON_LOA",
                 "_doc_nut_menu_loa"))


class MenuAmLuongTests(unittest.TestCase):
    def setUp(self):
        self.f = _ns_menu()["_ask_am_luong_loa"]

    def test_co_du_cac_muc_va_giu_nguyen(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, LOA_CAST, 0)["text"])
        nhan = [c["label"] for c in choices]
        self.assertEqual(nhan, ["30%", "50%", "70%", "100%", "Giữ nguyên âm lượng loa"])

    def test_nut_mang_du_loa_am_luong_noi_dung(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, LOA_CAST, 0)["text"])
        send = choices[1]["send"]        # 50%
        self.assertIn("«loa phòng khách»", send)
        self.assertIn("âm lượng 50%", send)
        self.assertTrue(send.endswith(NOI_DUNG))

    def test_co_hen_gio_thi_nut_mang_theo_thoi_diem(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, LOA_CAST, 120)["text"])
        self.assertIn("sau 2 phút", choices[0]["send"])

    def test_noi_dung_nhieu_dong_KHONG_pha_menu(self):
        """Cùng loại lỗi đã hạ menu chọn model ảnh/video: <<<ASK>>> bóc theo DÒNG."""
        from services.agent import ask_choices as ac
        nhieu_dong = "chuẩn bị đi ăn gà rán\nnhớ rửa tay\nrồi xuống nhà"
        _, choices = ac.extract(self.f(nhieu_dong, LOA_CAST, 0)["text"])
        self.assertEqual(len(choices), 5)
        self.assertNotIn("\n", choices[0]["send"])
        self.assertIn("rồi xuống nhà", choices[0]["send"])

    def test_ghi_chu_dai_am_luong_theo_LOAI_loa(self):
        self.assertIn("dải 0–100%", self.f(NOI_DUNG, LOA_CAST, 0)["text"])
        r1 = self.f(NOI_DUNG, LOA_R1, 0)["text"]
        self.assertIn("chỉ số 0–15", r1)

    def test_ghi_chu_noi_ro_se_tra_am_luong_ve_muc_cu(self):
        self.assertIn("trả âm lượng về mức cũ", self.f(NOI_DUNG, LOA_CAST, 0)["text"])

    def test_muc_model_doan_thanh_LUA_CHON_dau_menu(self):
        """Model tự điền volume thì mức đó là GỢI Ý, không phải hành động."""
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, LOA_CAST, 0, goi_y=60)["text"])
        self.assertEqual(choices[0]["label"], "60% (theo yêu cầu)")
        self.assertIn("âm lượng 60%", choices[0]["send"])
        self.assertEqual(len(choices), 6)      # 60% + 4 mức + giữ nguyên

    def test_goi_y_trung_muc_san_co_thi_khong_lap(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, LOA_CAST, 0, goi_y=50)["text"])
        self.assertEqual(len(choices), 5)
        self.assertEqual(choices[0]["label"], "50% (theo yêu cầu)")

    def test_goi_y_rac_thi_bo_qua(self):
        from services.agent import ask_choices as ac
        for x in ("to lên", 999, -5, None, ""):
            _, choices = ac.extract(self.f(NOI_DUNG, LOA_CAST, 0, goi_y=x)["text"])
            self.assertEqual(len(choices), 5, x)


class LietKeLoaTests(unittest.TestCase):
    """Phải LIỆT KÊ danh sách loa thật, không để model tự diễn đạt.

    Đo thật 21:25:46 — bot trả "Dạ anh muốn phát ra loa nào ạ — loa phòng khách
    hay tất cả loa?". Đó là lời MODEL tự nghĩ, không phải danh sách do tool liệt
    kê. Model tự hỏi nghĩa là nó tự đoán nhà có loa nào.
    """

    def setUp(self):
        self.f = _ns_menu()["_ask_chon_loa"]
        self.rows = [LOA_CAST, dict(LOA_CAST, id="s2", name="loa bếp",
                                    host="192.168.1.10")]

    def test_moi_loa_la_mot_nut(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, self.rows, 0)["text"])
        self.assertEqual(len(choices), 4)      # 2 loa + tuỳ chọn + tất cả
        self.assertIn("loa phòng khách", choices[0]["label"])
        self.assertIn("loa bếp", choices[1]["label"])

    def test_khong_nhac_gio_thi_ghi_ro_DOC_NGAY(self):
        self.assertIn("đọc ngay", self.f(NOI_DUNG, self.rows, 0)["text"])

    def test_co_hen_gio_thi_ghi_thoi_diem(self):
        ra = self.f(NOI_DUNG, self.rows, 120)["text"]
        self.assertIn("sau 2 phút", ra)
        self.assertNotIn("đọc ngay", ra)

    def test_noi_dung_nhieu_dong_khong_pha_menu(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(
            self.f("đi ngủ thôi\nnhớ tắt đèn\nrồi lên phòng", self.rows, 0)["text"])
        self.assertEqual(len(choices), 4)
        self.assertIn("rồi lên phòng", choices[0]["send"])


class DocLaiNutTests(unittest.TestCase):
    def setUp(self):
        self.f = _ns_doc()["_doc_nut_menu_loa"]

    def test_doc_dung_loa_am_luong_noi_dung(self):
        self.assertEqual(
            self.f(f"đọc ra loa «loa phòng khách» âm lượng 60%: {NOI_DUNG}"),
            {"text": NOI_DUNG, "speaker": "loa phòng khách", "volume": 60,
             "am_luong_da_chon": True})

    def test_co_bang_chung_NGUOI_da_chon_muc(self):
        """Không có cờ này thì handler coi mức là model đoán và hỏi lại."""
        got = self.f(f"đọc ra loa «loa bếp» âm lượng 30%: {NOI_DUNG}")
        self.assertTrue(got["am_luong_da_chon"])

    def test_giu_nguyen_thi_khong_hoi_lai_am_luong(self):
        got = self.f(f"đọc ra loa «loa bếp» âm lượng giữ nguyên: {NOI_DUNG}")
        self.assertTrue(got["giu_am_luong"])
        self.assertNotIn("volume", got)

    def test_doc_ca_hen_gio(self):
        got = self.f(f"đọc ra loa «loa phòng khách» âm lượng 30% sau 2 phút: {NOI_DUNG}")
        self.assertEqual(got["delay_minutes"], 2.0)
        self.assertEqual(got["volume"], 30)

    def test_cau_nguoi_go_va_cau_khac_khong_lot_vao_day(self):
        for c in ("phát thông báo ra loa với nội dung đi ăn cơm",
                  "âm lượng 60%", "xin chào", "mở nhạc ra loa R1 âm lượng 5", ""):
            self.assertIsNone(self.f(c), c)


class DanhSachDayDuTests(unittest.TestCase):
    """Yêu cầu 02/08: mỗi loa kèm DẢI âm lượng, cuối danh sách có «tuỳ chọn» và
    «tất cả» — cùng khuôn menu chọn model tạo ảnh/video."""

    def setUp(self):
        self.ns = _ns_menu()
        self.rows = [LOA_CAST, LOA_BEP, LOA_R1, LOA_DLNA]

    def _menu(self):
        from services.agent import ask_choices as ac
        return ac.extract(self.ns["_ask_chon_loa"](NOI_DUNG, self.rows, 0)["text"])

    def test_moi_loa_kem_dai_am_luong(self):
        _, c = self._menu()
        self.assertIn("dải 0–100%", c[0]["label"])
        self.assertIn("chỉ số 0–15", self.ns["_ask_chon_loa"](
            NOI_DUNG, [LOA_R1], 0)["text"])

    def test_loa_khong_chinh_duoc_thi_noi_ro(self):
        ra = self.ns["_ask_chon_loa"](NOI_DUNG, [LOA_DLNA], 0)["text"]
        self.assertIn("không chỉnh được âm lượng", ra)

    def test_hai_lua_chon_cuoi_dung_thu_tu(self):
        _, c = self._menu()
        nhan = [x["label"] for x in c]
        self.assertEqual(len(c), len(self.rows) + 2)
        self.assertIn("Tuỳ chọn", nhan[-2])
        self.assertEqual(nhan[-1], "Tất cả loa")

    def test_mot_loa_thi_khong_hien_tat_ca(self):
        """Một loa mà còn 'tất cả loa' thì vô nghĩa."""
        from services.agent import ask_choices as ac
        _, c = ac.extract(self.ns["_ask_chon_loa"](NOI_DUNG, [LOA_CAST], 0)["text"])
        self.assertNotIn("Tất cả loa", [x["label"] for x in c])

    def test_tuy_chon_hoi_lai_loa_va_am_luong(self):
        ra = self.ns["_ask_tuy_chon_loa"](NOI_DUNG, self.rows, 0)["text"]
        self.assertIn("những loa nào", ra)
        self.assertIn("âm lượng bao nhiêu", ra)
        for r in self.rows:                     # liệt kê kèm dải để biết gõ gì
            self.assertIn(str(r["name"]), ra)
        self.assertIn(NOI_DUNG, ra)             # nội dung không bị mất


class HoiAmLuongLanLuotTests(unittest.TestCase):
    """Yêu cầu 02/08: "chọn tất cả hay tuỳ chọn thì hỏi lần lượt âm lượng các loa
    được chọn". Mỗi lần một loa, kèm dải RIÊNG của loa đó."""

    def setUp(self):
        self.ns = _ns_menu()
        self.doc = _ns_doc()["_doc_nut_menu_loa"]
        self.rows = [LOA_CAST, LOA_BEP, LOA_R1, LOA_DLNA]

    def _chay_het(self, chon_muc: int = 1):
        """Bấm hết các vòng, trả kế hoạch cuối."""
        from services.agent import ask_choices as ac
        ke = [{"ten": r["name"], "vol": None} for r in self.rows]
        tieu_de = []
        for _ in range(10):
            hoi = self.ns["_ask_am_luong_tung_loa"](NOI_DUNG, ke, self.rows, 0)
            if not hoi:
                break
            t, c = ac.extract(hoi["text"])
            tieu_de.append(t.splitlines()[0])
            ke = self.ns["_giai_ma_ke_hoach"](self.doc(c[chon_muc]["send"])["ke_hoach"])
        return tieu_de, ke

    def test_hoi_tung_loa_mot_va_dem_dung(self):
        tieu_de, _ = self._chay_het()
        # 4 loa nhưng loa DLNA không chỉnh được → chỉ hỏi 3, mẫu số phải là 3.
        self.assertEqual(len(tieu_de), 3)
        self.assertIn("Loa 1/3", tieu_de[0])
        self.assertIn("Loa 2/3", tieu_de[1])
        self.assertIn("Loa 3/3", tieu_de[2])

    def test_moi_cau_hoi_kem_dai_rieng_cua_loa_do(self):
        from services.agent import ask_choices as ac
        ke = [{"ten": LOA_R1["name"], "vol": None}]
        t, _ = ac.extract(self.ns["_ask_am_luong_tung_loa"](
            NOI_DUNG, ke, [LOA_R1], 0)["text"])
        self.assertIn("chỉ số 0–15", t)

    def test_loa_khong_chinh_duoc_thi_KHONG_hoi(self):
        tieu_de, ke = self._chay_het()
        self.assertFalse([t for t in tieu_de if "loa gác" in t])
        muc = {m["ten"]: m["vol"] for m in ke}
        self.assertEqual(muc["loa gác"], self.ns["_GIU_NGUYEN"])

    def test_GIU_NGUYEN_khong_bi_hieu_thanh_0_phan_tram(self):
        """Lỗi thật: mã hoá 'giữ nguyên' bằng -1 thì giải mã kẹp về 0 = TẮT TIẾNG."""
        ma = self.ns["_ma_hoa_ke_hoach"]([("loa gác", self.ns["_GIU_NGUYEN"])])
        ra = self.ns["_giai_ma_ke_hoach"](ma)
        self.assertEqual(ra[0]["vol"], self.ns["_GIU_NGUYEN"])
        self.assertNotEqual(ra[0]["vol"], 0)

    def test_ke_hoach_di_tron_qua_ma_hoa(self):
        ke = [("loa phòng khách", 50), ("loa bếp", None), ("loa R1", 30)]
        ra = self.ns["_giai_ma_ke_hoach"](self.ns["_ma_hoa_ke_hoach"](ke))
        self.assertEqual([(m["ten"], m["vol"]) for m in ra],
                         [("loa phòng khách", 50), ("loa bếp", None), ("loa R1", 30)])

    def test_nut_ke_hoach_doc_lai_duoc_va_mang_thoi_diem(self):
        from services.agent import ask_choices as ac
        ke = [{"ten": LOA_CAST["name"], "vol": None}]
        _, c = ac.extract(self.ns["_ask_am_luong_tung_loa"](
            NOI_DUNG, ke, [LOA_CAST], 120)["text"])
        got = self.doc(c[0]["send"])
        self.assertEqual(got["delay_minutes"], 2.0)
        self.assertEqual(got["text"], NOI_DUNG)
        self.assertIn("=30", got["ke_hoach"])


class NeuAmLuongTruocThiKhongHoiLaiTests(unittest.TestCase):
    """Yêu cầu 02/08: "nếu user nói tất cả các loa âm lượng 50% thì vẫn được"."""

    def setUp(self):
        self.f = _ns_menu()["_nguoi_co_neu_am_luong"]

    def test_nhan_dung_cau_co_neu_am_luong(self):
        for s in ("tất cả các loa âm lượng 50%", "phát ra loa bếp 40%",
                  "âm lượng 30", "mức 7", "volume 60"):
            self.assertTrue(self.f(s), s)

    def test_cau_khong_neu_thi_False(self):
        for s in ("phát thông báo ra loa", "chuẩn bị đi ngủ thôi các con", ""):
            self.assertFalse(self.f(s), s)

    def test_con_thieu_thong_tin_theo_cau_NGUOI_go(self):
        from services.agent import capabilities as caps
        a = {"text": NOI_DUNG, "speaker": "tất cả", "volume": 50}
        self.assertFalse(caps.con_thieu_thong_tin(
            "announce_on_speaker", a, "tất cả các loa âm lượng 50%"))
        # Model tự điền mà câu người dùng KHÔNG nêu → vẫn phải hỏi.
        self.assertTrue(caps.con_thieu_thong_tin(
            "announce_on_speaker", a, "phát thông báo ra loa"))

    def test_ke_hoach_con_dau_hoi_thi_van_thieu(self):
        from services.agent import capabilities as caps
        self.assertTrue(caps.con_thieu_thong_tin(
            "announce_on_speaker", {"text": "x", "ke_hoach": "loa A=50; loa B=?"}))
        self.assertFalse(caps.con_thieu_thong_tin(
            "announce_on_speaker", {"text": "x", "ke_hoach": "loa A=50; loa B=giu"}))

    def test_tuy_chon_thi_con_thieu(self):
        from services.agent import capabilities as caps
        self.assertTrue(caps.con_thieu_thong_tin(
            "announce_on_speaker", {"text": "x", "tuy_chon": True}))


class QuyDoiPhanTramSangChiSoTests(unittest.TestCase):
    """Yêu cầu 02/08: "loa có dải âm lượng là số thì từ % quy ra âm lượng số".

    Việc quy đổi ĐÃ có sẵn trong `speakers.set_volume` — chỉ có MỘT chỗ quy đổi,
    tầng trên luôn truyền tỉ lệ 0..1. Test này giữ điều đó lại.
    """

    def test_set_volume_quy_ra_chi_so_cho_R1(self):
        import pathlib
        src = (GOC / "services" / "voice" / "speakers.py").read_text("utf-8")
        i = src.index("def set_volume(")
        khuc = src[i:i + 700]
        self.assertIn("max_vol", khuc)
        self.assertIn('kind == "r1"', khuc)

    def test_tang_tren_chi_truyen_ti_le_khong_tu_quy_doi(self):
        """Bỏ dòng chú thích rồi mới soi — đừng bắt chính lời giải thích."""
        src = (GOC / "services" / "agent" / "capabilities.py").read_text("utf-8")
        i = src.index("def _phat_nhieu_loa(")
        than = src[i:i + 2200]
        than = than[than.index('"""', than.index('"""') + 3) + 3:]   # bỏ docstring
        than = "\n".join(l for l in than.splitlines()
                          if not l.lstrip().startswith("#"))
        self.assertIn("/ 100.0", than)
        self.assertNotIn("max_vol", than)


class DocLaiNutChonLoaTests(unittest.TestCase):
    """Nút chọn loa: loa đã rõ, âm lượng CHƯA → handler còn phải hỏi tiếp."""

    def setUp(self):
        self.f = _ns_doc()["_doc_nut_menu_loa"]

    def test_doc_dung_loa_va_noi_dung(self):
        self.assertEqual(
            self.f(f"chọn loa «loa phòng khách» để đọc: {NOI_DUNG}"),
            {"text": NOI_DUNG, "speaker": "loa phòng khách"})

    def test_KHONG_co_co_am_luong_da_chon(self):
        """Thiếu cờ này thì `con_thieu_thong_tin` còn True → hỏi âm lượng tiếp."""
        got = self.f(f"chọn loa «loa bếp» để đọc: {NOI_DUNG}")
        self.assertNotIn("am_luong_da_chon", got)
        self.assertNotIn("volume", got)

    def test_mang_theo_thoi_diem(self):
        got = self.f(f"chọn loa «loa bếp» để đọc sau 2 phút: {NOI_DUNG}")
        self.assertEqual(got["delay_minutes"], 2.0)

    def test_cau_nguoi_go_khong_lot_vao_day(self):
        for c in ("chọn loa phòng khách", "phát ra loa phòng khách", "loa bếp"):
            self.assertIsNone(self.f(c), c)


class VongKhepKinTests(unittest.TestCase):
    """Nút menu sinh ra PHẢI đọc lại được — nếu không, âm lượng và loa lại bốc hơi."""

    def test_nut_chon_loa_doc_lai_duoc(self):
        from services.agent import ask_choices as ac
        ask = _ns_menu()["_ask_chon_loa"]
        doc = _ns_doc()["_doc_nut_menu_loa"]
        rows = [LOA_CAST, dict(LOA_CAST, id="s2", name="loa bếp")]
        _, choices = ac.extract(ask(NOI_DUNG, rows, 120)["text"])
        for c, r in zip(choices, rows):
            got = doc(c["send"])
            self.assertIsNotNone(got, c["send"])
            self.assertEqual(got["speaker"], r["name"])
            self.assertEqual(got["text"], NOI_DUNG)
            self.assertEqual(got["delay_minutes"], 2.0)

    def test_moi_nut_cua_menu_deu_doc_lai_duoc(self):
        from services.agent import ask_choices as ac
        ask = _ns_menu()["_ask_am_luong_loa"]
        doc = _ns_doc()["_doc_nut_menu_loa"]
        _, choices = ac.extract(ask(NOI_DUNG, LOA_CAST, 120, goi_y=60)["text"])
        self.assertEqual(len(choices), 6)
        for c in choices:
            got = doc(c["send"])
            self.assertIsNotNone(got, c["send"])
            self.assertEqual(got["speaker"], "loa phòng khách")
            self.assertEqual(got["text"], NOI_DUNG)
            self.assertEqual(got["delay_minutes"], 2.0)
            self.assertTrue(got["am_luong_da_chon"])
            self.assertTrue("volume" in got or got.get("giu_am_luong"))


class PhatNgayPhaiDongBoTests(unittest.TestCase):
    """delay=0 → chạy đồng bộ, lỗi thật phải NÉM RA, không chìm vào thread nền."""

    def setUp(self):
        from services.voice import announce as ann
        self.ann = ann
        self.rec = {"id": "spk1", "name": "loa phòng khách", "kind": "cast"}
        self._resolve_goc = ann._resolve_one
        ann._resolve_one = lambda q: self.rec

    def tearDown(self):
        self.ann._resolve_one = self._resolve_goc

    def _cam_voice(self, loi: str | None):
        """Cắm giả `services.voice.play_text_on` mà `_run` gọi bên trong."""
        import types
        mod = sys.modules.get("services.voice")
        goc = getattr(mod, "play_text_on", None)
        da_goi: list = []

        def _play(text, rec, voice_name="", *, files_out=None):
            da_goi.append((text, rec.get("name")))
            if loi:
                raise RuntimeError(loi)
            return "https://x/media/voice/abc.wav"

        mod.play_text_on = _play
        self.addCleanup(lambda: setattr(mod, "play_text_on", goc)
                        if goc is not None else None)
        assert isinstance(mod, types.ModuleType)
        return da_goi

    def test_phat_xong_moi_tra_ve(self):
        da_goi = self._cam_voice(None)
        ra = self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0)
        self.assertEqual(da_goi, [(NOI_DUNG, "loa phòng khách")])   # đã phát TRƯỚC khi trả về
        self.assertEqual(ra.get("status"), "done")

    def test_loi_thi_NEM_RA_chu_khong_bao_thanh_cong(self):
        self._cam_voice("Chưa đặt voice.public_base_url — loa trong nhà không "
                        "tải được file từ localhost.")
        with self.assertRaises(RuntimeError) as e:
            self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0)
        self.assertIn("public_base_url", str(e.exception))

    def test_hen_gio_van_chay_NEN_khong_chan_luot(self):
        self._cam_voice("boom")     # lỗi cũng không được ném — job chạy sau
        ra = self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=600)
        self.assertEqual(ra.get("status"), "scheduled")
        self.ann.cancel(ra["id"])


class TraAmLuongVeMucCuTests(unittest.TestCase):
    """Phát xong phải trả âm lượng về mức cũ — thông báo to một lần không nên đổi
    luôn mức nghe nhạc của cả nhà.

    Điểm dễ sai: `play_on()` TRẢ VỀ TRƯỚC KHI loa phát xong (chính `play_text_on`
    phải `time.sleep(độ dài câu 1)` mới dám push câu sau). Trả âm lượng ngay là
    tụt tiếng giữa câu — nên việc trả phải CHỜ đúng độ dài rồi mới làm, và chạy
    NỀN để không giữ lượt chat.
    """

    def setUp(self):
        from services.voice import announce as ann
        self.ann = ann
        self.rec = dict(LOA_CAST)
        self._resolve_goc = ann._resolve_one
        ann._resolve_one = lambda q: self.rec
        self.addCleanup(lambda: setattr(ann, "_resolve_one", self._resolve_goc))

    def _cam(self, *, loi_phat=None, muc_cu=0.25):
        """Cắm giả loa: ghi lại mọi lần đặt âm lượng theo thứ tự."""
        import services.voice as v
        from services.voice import speakers as vspk
        dat: list[float] = []
        goc = {"play": getattr(v, "play_text_on", None),
               "get": vspk.get_volume, "set": vspk.set_volume}

        def _play(text, rec, voice_name="", *, files_out=None):
            if loi_phat:
                raise RuntimeError(loi_phat)
            return "https://x/media/voice/abc.wav"

        v.play_text_on = _play
        vspk.get_volume = lambda rec: muc_cu
        vspk.set_volume = lambda rec, level: dat.append(round(float(level), 3))

        def _tra_lai():
            if goc["play"] is not None:
                v.play_text_on = goc["play"]
            vspk.get_volume, vspk.set_volume = goc["get"], goc["set"]
        self.addCleanup(_tra_lai)
        # Độ dài audio = 0 để phép đo không phải ngủ thật.
        self.ann._do_dai_audio = lambda url: 0.0
        return dat

    def test_dat_muc_moi_roi_tra_ve_muc_cu(self):
        dat = self._cam(muc_cu=0.25)
        self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0, volume=0.6)
        for _ in range(50):                     # việc trả chạy ở thread nền
            if len(dat) >= 2:
                break
            time.sleep(0.02)
        self.assertEqual(dat, [0.6, 0.25])

    def test_khong_yeu_cau_am_luong_thi_khong_cham_vao(self):
        dat = self._cam()
        self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0)
        time.sleep(0.05)
        self.assertEqual(dat, [])

    def test_phat_hong_van_tra_muc_cu(self):
        """Không để loa nằm ở mức thông báo chỉ vì lượt đó thất bại."""
        dat = self._cam(loi_phat="cast không nối được", muc_cu=0.25)
        with self.assertRaises(RuntimeError):
            self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0, volume=1.0)
        self.assertEqual(dat, [1.0, 0.25])

    def test_khong_doc_duoc_muc_cu_thi_khong_doan(self):
        import services.voice as v
        from services.voice import speakers as vspk
        dat = self._cam(muc_cu=0.25)
        vspk.get_volume = lambda rec: None          # loa không cho đọc
        self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0, volume=0.6)
        time.sleep(0.05)
        self.assertEqual(dat, [0.6])                # đặt mức mới, KHÔNG trả bừa
        self.assertTrue(callable(v.play_text_on))


class DiaChiCongKhaiTests(unittest.TestCase):
    """Địa chỉ công khai cho loa kéo file — đọc ĐÚNG chỗ đang có giá trị.

    Máy chủ 02/08: `config.get()["base_url"]` = '' (dict thô) nhưng
    `CHATGPT2API_BASE_URL` = 'https://gpt.vhtatn.io.vn' và
    `telegram_webhook_url` = 'https://gpt.vhtatn.io.vn'. Hàm cũ chỉ đọc dict thô
    nên báo "chưa đặt public_base_url" dù địa chỉ đã có ở hai nơi.
    """

    def setUp(self):
        from unittest import mock
        from services.config import config
        from services.voice import config as vc
        self.vc, self.config, self.mock = vc, config, mock

    def _chay(self, *, env=None, voice_rieng=None, tele=None) -> str:
        moi = {}
        if env is not None:
            moi["CHATGPT2API_BASE_URL"] = env
        with self.mock.patch.dict(os.environ, moi, clear=(env is None)), \
             self.mock.patch.dict(self.config.data, {
                 "base_url": "",
                 "telegram_webhook_url": tele or "",
                 "voice": {"public_base_url": voice_rieng or ""},
             }):
            return self.vc.public_base_url()

    def test_lay_tu_bien_moi_truong(self):
        self.assertEqual(self._chay(env="https://gpt.vhtatn.io.vn/"),
                         "https://gpt.vhtatn.io.vn")

    def test_khong_co_env_thi_lay_dia_chi_webhook_dung_chung(self):
        self.assertEqual(self._chay(tele="https://gpt.vhtatn.io.vn"),
                         "https://gpt.vhtatn.io.vn")

    def test_cai_rieng_cho_loa_thang_tat_ca(self):
        self.assertEqual(self._chay(env="https://a.example",
                                    voice_rieng="http://172.16.10.38"),
                         "http://172.16.10.38")

    def test_khong_co_gi_thi_rong(self):
        self.assertEqual(self._chay(), "")


class MenuKhongBiNenTests(unittest.TestCase):
    """Menu là GIAO DIỆN — nén nó là phá mất lựa chọn (đo thật cả ảnh và video)."""

    def test_khoi_ASK_khong_bi_nen(self):
        from services.agent import tool_compress as tc
        menu = ("🎨 Chọn model ạ?\n<<<ASK>>>\n"
                + "\n".join(f"flow/m{i} | tạo ảnh bằng model flow/m{i}: {'x' * 900}"
                            for i in range(6))
                + "\n<<<END>>>")
        self.assertGreater(len(menu), 4000)          # vượt trần → chắc chắn bị nén nếu không chặn
        self.assertEqual(tc.compress(menu, tool_name="generate_image"), menu)

    def test_van_nen_output_thuong(self):
        from services.agent import tool_compress as tc
        tho = "\n".join(f"dòng log số {i} — chi tiết dài dòng ở đây" for i in range(400))
        self.assertLess(len(tc.compress(tho, tool_name="run_shell")), len(tho))

    def test_nhan_ca_JAVIS_ASK(self):
        from services.agent import tool_compress as tc
        self.assertTrue(tc.co_menu_chon('JAVIS_ASK ["a", "b"]'))
        self.assertFalse(tc.co_menu_chon("chỉ là văn bản thường"))


class ThuTuHoiRoiMoiDuyetTests(unittest.TestCase):
    """Hỏi ĐỦ trước, rồi mới có MỘT lần xác nhận thấy trọn việc.

    Đo thật 02/08 21:25 — chủ máy đã nói "loa phòng khách" mà câu duyệt hiện ra:

        Em định Đọc thông báo ra loa (ngay, hoặc hẹn giờ):
        chuẩn bị đi ngủ thôi các con
        Anh/chị duyệt không ạ?

    Không có loa, không có âm lượng. Sai ở THỨ TỰ: cổng duyệt hỏi trước khi thông
    tin đủ, nên người dùng bị bắt duyệt một việc chưa thấy hết.
    """

    def test_con_thieu_thong_tin_thi_chua_hoi_duyet(self):
        from services.agent import capabilities as caps
        # Model tự điền volume KHÔNG tính là người đã chọn.
        self.assertTrue(caps.con_thieu_thong_tin(
            "announce_on_speaker", {"text": "x", "speaker": "loa phòng khách"}))
        self.assertTrue(caps.con_thieu_thong_tin(
            "announce_on_speaker", {"text": "x", "speaker": "loa", "volume": 50}))

    def test_nguoi_da_chon_am_luong_thi_du_thong_tin(self):
        from services.agent import capabilities as caps
        for a in ({"text": "x", "speaker": "loa", "volume": 50, "am_luong_da_chon": True},
                  {"text": "x", "speaker": "loa", "giu_am_luong": True}):
            self.assertFalse(caps.con_thieu_thong_tin("announce_on_speaker", a), a)

    def test_khong_dung_den_capability_khac(self):
        from services.agent import capabilities as caps
        for ten in ("control_home", "send_to_contact", "generate_video", ""):
            self.assertFalse(caps.con_thieu_thong_tin(ten, {}), ten)

    def test_cau_duyet_hien_loa_am_luong_thoi_diem(self):
        from services.agent import approval_gate as ag
        s = ag.summarize_action("announce_on_speaker",
                                {"text": NOI_DUNG, "speaker": "loa phòng khách",
                                 "volume": 50})
        self.assertIn("loa phòng khách", s)
        self.assertIn("50%", s)
        self.assertIn("đọc ngay", s)
        self.assertIn(NOI_DUNG, s)

    def test_cau_duyet_hien_lich_khi_dat_lich(self):
        from services.agent import approval_gate as ag
        s = ag.summarize_action("announce_on_speaker",
                                {"text": NOI_DUNG, "speaker": "loa bếp",
                                 "when": "8h sáng mai"})
        self.assertIn("lịch: 8h sáng mai", s)
        self.assertNotIn("đọc ngay", s)

    def test_capability_khac_giu_nguyen_cach_tom_tat(self):
        """Chỉ thêm nhánh cho loa — đừng đổi câu duyệt của tool khác."""
        from services.agent import approval_gate as ag
        self.assertEqual(ag.summarize_action("send_to_contact",
                                             {"to": "Mẹ", "message": "con về muộn"}),
                         "→ Mẹ: con về muộn")
        self.assertEqual(ag.summarize_action("control_home", {"command": "bật đèn"}),
                         "bật đèn")


class DuongTatKhongMoThemQuyenTests(unittest.TestCase):
    """Nút bấm CHÍNH LÀ lời duyệt — nhưng chỉ-đọc và lọc thread vẫn chặn.

    Nội dung nút nói trọn việc (loa nào, âm lượng bao nhiêu, thời điểm, nội dung)
    và người dùng đọc đúng câu đó rồi bấm, nên nó là lời đồng ý CỤ THỂ HƠN câu
    "Em định …, duyệt không ạ?". Hỏi duyệt lần hai không thêm thông tin nào.

    Không có đường lách: chuỗi nút nằm trong `user_text` — thứ do NGƯỜI gửi. Tầng
    model không đặt được gì vào đó.
    """

    def setUp(self):
        self.code = "\n".join(
            l for l in (GOC / "services" / "agent" / "orchestrator.py")
            .read_text("utf-8").splitlines() if not l.lstrip().startswith("#"))
        self.khuc = self.code[self.code.index("_nut_loa = _doc_nut_menu_loa(user_text)"):][:1200]

    def test_van_qua_bo_loc_chuc_nang_theo_thread(self):
        self.assertIn('allow is None or "tts_speaker" in allow', self.khuc)

    def test_che_do_chi_doc_van_chan_cung(self):
        self.assertIn('approval_gate.is_blocked("announce_on_speaker"', self.khuc)

    def test_KHONG_hoi_duyet_lan_hai(self):
        self.assertNotIn("needs_approval", self.khuc)
        self.assertNotIn("set_pending", self.khuc)

    def test_van_ghi_audit_bang_cach_di_qua_execute(self):
        """`_execute` ghi `execute_change` — gọi thẳng handler thì mất bản ghi."""
        self.assertIn("_execute(_cap_loa,", self.khuc)

    def test_dat_truoc_fast_path_HA(self):
        self.assertLess(self.code.index("_nut_loa = _doc_nut_menu_loa(user_text)"),
                        self.code.index("if ha_fastpath and (allow is None"))

    def test_cong_duyet_duong_thuong_biet_hoi_du_truoc(self):
        i = self.code.index("approval_gate.needs_approval(user_id, name, risk=cap.risk)")
        self.assertIn("caps.con_thieu_thong_tin(name, args, user_text)",
                      self.code[i:i + 400])


class DuongTatHoiLoaTests(unittest.TestCase):
    """Câu xin phát ra loa phải ra MENU CHỌN LOA ngay, không nhờ model tự hỏi.

    Đo thật 02/08 23:15 trên Zalo (nguyên văn):

        23:15:29 người dùng : phát thông báo ra loa với nội dung chuẩn bị đi ngủ thôi các con
        23:15:36 bot        : Dạ anh muốn phát ra loa nào ạ — loa phòng khách hay tất cả loa?
        23:15:49 người dùng : Danh sách lựa chọn đâu
        23:16:05 người dùng : Thiếu lựa chọn

    Câu hỏi ở 23:15:36 là lời MODEL tự nghĩ ra: nhà có loa nào là nó đoán, và mỗi
    lượt hỏi tốn một vòng gọi model. Đường tắt nhận ý bằng regex rồi gọi thẳng
    capability nên `_ask_chon_loa` liệt kê loa THẬT, ra ngay từ lượt đầu.
    """

    def setUp(self):
        self.f = _nap(GOC / "services" / "agent" / "orchestrator.py",
                      ("_TAT_PHAT_LOA", "_KHONG_PHAI_PHAT_LOA", "_LOA_CO_THOI_DIEM",
                       "_la_yeu_cau_phat_loa"))["_la_yeu_cau_phat_loa"]

    def test_cau_that_cua_chu_may(self):
        got = self.f("phát thông báo ra loa với nội dung chuẩn bị đi ngủ thôi các con")
        self.assertEqual(got, {"text": "chuẩn bị đi ngủ thôi các con"})

    def test_neu_ten_loa_thi_mang_theo(self):
        got = self.f("thông báo ra loa phòng khách: cả nhà ăn cơm")
        self.assertEqual(got, {"text": "cả nhà ăn cơm", "speaker": "phòng khách"})

    def test_cac_cach_noi_khac(self):
        for cau in ("đọc ra loa nội dung là cả nhà ăn cơm",
                    "phát ra loa: cả nhà ăn cơm",
                    "nhắc cả nhà bằng loa rằng cả nhà ăn cơm",
                    "hãy thông báo ra loa noi dung cả nhà ăn cơm"):
            got = self.f(cau)
            self.assertIsNotNone(got, cau)
            self.assertEqual(got["text"], "cả nhà ăn cơm", cau)

    def test_co_thoi_diem_thi_nhuong_duong_model(self):
        """Bộ hiểu thời gian nằm ở tầng model + `reminders.parse_when`."""
        for cau in ("phát thông báo ra loa sau 5 phút: cả nhà ăn cơm",
                    "phát thông báo ra loa lúc 8h sáng mai: cả nhà ăn cơm",
                    "phát thông báo ra loa mỗi ngày: cả nhà ăn cơm"):
            self.assertIsNone(self.f(cau), cau)

    def test_gio_trong_LOI_CAN_DOC_khong_tinh_la_thoi_diem(self):
        got = self.f("phát thông báo ra loa: nhớ 7h sáng mai dậy sớm")
        self.assertEqual(got, {"text": "nhớ 7h sáng mai dậy sớm"})

    def test_khong_gianh_viec_cua_tool_khac(self):
        for cau in ("mở nhạc ra loa bếp: lofi chill",
                    "phát bài hát ra loa bếp: lofi",
                    "phát thông báo ra loa âm lượng 50%: cả nhà ăn cơm",
                    "cho xem danh sách loa",
                    "thêm loa mới",
                    "xin chào em"):
            self.assertIsNone(self.f(cau), cau)

    def test_noi_dung_nut_bam_KHONG_lot_vao_day(self):
        """Nút bấm đã có đường riêng (mục 1.48) — vào đây là hiện lại menu vô tận."""
        for cau in ("đọc ra loa «loa phòng khách» âm lượng 60%: cả nhà ăn cơm",
                    "chọn loa «loa bếp» để đọc: cả nhà ăn cơm",
                    "đọc ra loa nhiều «loa bếp=50; loa gác=?»: cả nhà ăn cơm"):
            self.assertIsNone(self.f(cau), cau)

    def test_thieu_noi_dung_thi_khong_doan_bua(self):
        for cau in ("phát thông báo ra loa", "phát thông báo ra loa phòng khách"):
            self.assertIsNone(self.f(cau), cau)

    def test_chi_di_tat_khi_CON_PHAI_HOI(self):
        """Đủ thông tin thì phải qua cổng duyệt ở đường thường, không đi tắt."""
        from services.agent import capabilities as caps
        args = self.f("phát thông báo ra loa với nội dung chuẩn bị đi ngủ thôi các con")
        self.assertTrue(caps.con_thieu_thong_tin("announce_on_speaker", args or {}))


class DuongTatHoiLoaKhongMoThemQuyenTests(unittest.TestCase):
    """Đường tắt rút ngắn đường đi, KHÔNG mở thêm quyền."""

    def setUp(self):
        self.code = "\n".join(
            l for l in (GOC / "services" / "agent" / "orchestrator.py")
            .read_text("utf-8").splitlines() if not l.lstrip().startswith("#"))
        self.khuc = self.code[self.code.index("_yc_loa = _la_yeu_cau_phat_loa(user_text)"):][:900]

    def test_van_qua_bo_loc_chuc_nang_theo_thread(self):
        self.assertIn('allow is None or "tts_speaker" in allow', self.khuc)

    def test_che_do_chi_doc_van_chan_cung(self):
        self.assertIn('approval_gate.is_blocked("announce_on_speaker"', self.khuc)

    def test_chi_chay_khi_con_thieu_thong_tin(self):
        self.assertIn('caps.con_thieu_thong_tin("announce_on_speaker", _yc_loa, user_text)',
                      self.khuc)

    def test_van_ghi_audit_bang_cach_di_qua_execute(self):
        self.assertIn("_execute(_cap_yc,", self.khuc)

    def test_dat_truoc_fast_path_HA(self):
        self.assertLess(self.code.index("_yc_loa = _la_yeu_cau_phat_loa(user_text)"),
                        self.code.index("if ha_fastpath and (allow is None"))


class AmLuongMacDinhKhongDuocDeTests(unittest.TestCase):
    """Mức mặc định của sổ loa không được đè lên mức chọn cho thông báo.

    Đo thật 02/08 23:16 — chủ máy chọn 0% cho "chuẩn bị đi ngủ thôi các con", bot
    báo "[đang đọc … ra loa phòng khách]" mà loa vẫn kêu. `announce._run` đặt
    đúng 0, nhưng `speakers._play_cast` đọc `rec["volume"]` (âm lượng mặc định
    khai trong Sổ loa) rồi vặn trở lại ngay trước khi phát.
    """

    def setUp(self):
        from services.voice import announce as ann
        from services.voice import speakers as vspk
        self.ann, self.vspk = ann, vspk
        self.rec = dict(LOA_CAST, volume=0.55)     # loa có mức mặc định trong sổ
        goc = ann._resolve_one
        ann._resolve_one = lambda q: self.rec
        self.addCleanup(lambda: setattr(ann, "_resolve_one", goc))
        self.ann._do_dai_audio = lambda url: 0.0

    def _cam(self):
        """Trả về list ghi lại `rec` mà mỗi lần phát nhận được."""
        import services.voice as v
        from services.voice import speakers as vspk
        da_phat: list[dict] = []
        goc = {"play": v.play_text_on, "get": vspk.get_volume, "set": vspk.set_volume}

        def _play(text, rec, voice_name="", *, files_out=None):
            da_phat.append(dict(rec))
            return "https://x/media/voice/abc.wav"

        v.play_text_on = _play
        vspk.get_volume = lambda rec: 0.25
        vspk.set_volume = lambda rec, level: None

        def _tra_lai():
            v.play_text_on = goc["play"]
            vspk.get_volume, vspk.set_volume = goc["get"], goc["set"]
        self.addCleanup(_tra_lai)
        return da_phat

    def test_co_chon_am_luong_thi_bo_muc_mac_dinh(self):
        da_phat = self._cam()
        self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0, volume=0.0)
        self.assertEqual(len(da_phat), 1)
        self.assertNotIn("volume", da_phat[0])
        self.assertEqual(da_phat[0]["name"], "loa phòng khách")

    def test_khong_ai_neu_am_luong_thi_muc_mac_dinh_van_co_tac_dung(self):
        da_phat = self._cam()
        self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0)
        self.assertEqual(da_phat[0].get("volume"), 0.55)

    def test_ham_bo_muc_mac_dinh_khong_dung_ban_goc(self):
        rec = {"id": "x", "name": "loa", "kind": "cast", "volume": 0.7}
        moi = self.vspk.bo_am_luong_mac_dinh(rec)
        self.assertNotIn("volume", moi)
        self.assertEqual(rec["volume"], 0.7)
        self.assertEqual(moi["name"], "loa")


class DatAmLuongHONGThiKhongBaoThanhCongTests(unittest.TestCase):
    """Loa chỉnh được âm lượng mà đặt không xong → NÉM RA, đừng đọc rồi báo xong.

    Cùng loại lỗi với `PhatNgayPhaiDongBoTests`: câu "[đang đọc …]" phải là lời
    thật. Đọc ở mức cũ lúc nửa đêm trong khi người dùng vừa chọn mức nhỏ là hỏng
    đúng cái họ chọn.
    """

    def setUp(self):
        from services.voice import announce as ann
        self.ann = ann
        self.ann._do_dai_audio = lambda url: 0.0

    def _cam(self, rec):
        import services.voice as v
        from services.voice import speakers as vspk
        goc = {"resolve": self.ann._resolve_one, "play": v.play_text_on,
               "get": vspk.get_volume, "set": vspk.set_volume}
        da_phat: list = []
        self.ann._resolve_one = lambda q: rec
        v.play_text_on = lambda *a, **k: (da_phat.append(1),
                                          "https://x/media/voice/a.wav")[1]
        vspk.get_volume = lambda rec: 0.25

        def _set(rec, level):
            raise RuntimeError("Không kết nối được loa Cast 192.168.1.9:8009.")
        vspk.set_volume = _set

        def _tra_lai():
            self.ann._resolve_one = goc["resolve"]
            v.play_text_on = goc["play"]
            vspk.get_volume, vspk.set_volume = goc["get"], goc["set"]
        self.addCleanup(_tra_lai)
        return da_phat

    def test_loa_cast_dat_khong_duoc_thi_nem_ra(self):
        da_phat = self._cam(dict(LOA_CAST))
        with self.assertRaises(RuntimeError) as e:
            self.ann.schedule("loa phòng khách", NOI_DUNG, delay_seconds=0, volume=0.0)
        self.assertIn("âm lượng", str(e.exception))
        self.assertEqual(da_phat, [])          # KHÔNG đọc ở mức cũ

    def test_loa_khong_chinh_duoc_am_luong_thi_van_doc(self):
        """DLNA/HA vốn không có nút âm lượng — đừng vì thế mà bỏ luôn thông báo."""
        da_phat = self._cam(dict(LOA_DLNA))
        self.ann.schedule("loa gác", NOI_DUNG, delay_seconds=0, volume=0.5)
        self.assertEqual(len(da_phat), 1)


class KhongGoiY0PhanTramTests(unittest.TestCase):
    """0% là thông báo không ai nghe thấy — đừng để nó thành ô đầu tiên.

    `goi_y` ở menu này LUÔN là mức tầng model tự điền: người dùng có nêu mức thì
    `_h_announce_on_speaker` đã bỏ qua bước hỏi. Đo thật 02/08 23:16 — câu người
    dùng không nhắc gì tới âm lượng, model điền 0, menu hiện "0% (theo yêu cầu)" ở
    đầu, chủ máy bấm ô 1 và loa đọc ở mức 0.
    """

    def setUp(self):
        self.f = _ns_menu()["_ask_am_luong_loa"]

    def test_goi_y_0_bi_bo(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, LOA_CAST, 0, goi_y=0)["text"])
        nhan = [c["label"] for c in choices]
        self.assertEqual(nhan, ["30%", "50%", "70%", "100%", "Giữ nguyên âm lượng loa"])

    def test_muc_khac_van_giu_nguyen_cach_cu(self):
        from services.agent import ask_choices as ac
        _, choices = ac.extract(self.f(NOI_DUNG, LOA_CAST, 0, goi_y=20)["text"])
        self.assertEqual(choices[0]["label"], "20% (theo yêu cầu)")


if __name__ == "__main__":
    unittest.main()
