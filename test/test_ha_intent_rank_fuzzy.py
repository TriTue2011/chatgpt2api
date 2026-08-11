"""Bộ xếp hạng đa tín hiệu cho lệnh nhà thông minh — chuẩn hoá + khớp mờ.

Nâng cấp lấy từ dự án assist-canonicalizer (luuquangvu), đọc 11/08:
  - chuẩn hoá NFKC + gấp dấu NGAY TRONG bộ xếp hạng, nên nhãn còn dấu
    ("Đèn trần Phòng khách") so được với câu đã gấp dấu ("den tran phong khac").
    Trước đây hai bên khác chuẩn hoá → mọi tín hiệu từ vựng về ~0 và bộ xếp
    hạng luôn trả None.
  - thêm tín hiệu BM25 (token hiếm nặng hơn token phổ biến như "đèn", "phòng").
  - pick_entity_fuzzy: câu không khớp chính xác tên nào vẫn chọn được thiết bị,
    với cổng chặt hơn để không điều khiển nhầm.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


# (entity_id, domain, tên gốc, khu vực)
NHA = [
    ("light.tran_pk", "light", "Đèn trần", "Phòng khách"),
    ("light.tran_lv", "light", "Đèn trần", "Phòng đọc"),
    ("light.hoc", "light", "Đèn học", "Phòng đọc"),
    ("light.ban_cong", "light", "Đèn ban công", ""),
    ("light.guong", "light", "Đèn gương", "Nhà tắm"),
    ("fan.tran_pk", "fan", "Quạt trần", "Phòng khách"),
    ("fan.thong_gio", "fan", "Quạt thông gió", "Nhà tắm"),
    ("climate.lv", "climate", "Điều hòa", "Phòng đọc"),
    ("switch.loc_khi", "switch", "Máy lọc không khí", "Phòng khách"),
    ("water_heater.nt", "water_heater", "Bình nóng lạnh", "Nhà tắm"),
    ("switch.suoi", "switch", "Máy sưởi", "Nhà tắm"),
    ("light.tu", "light", "Đèn tủ hồ sơ", "Phòng đọc"),
]


def _chi_muc():
    """Dựng đúng cấu trúc mà _ha_local_intent truyền vào bộ xếp hạng."""
    from services.ha_client import _fold_diacritics

    ent_by_name: dict[str, list[tuple[str, str, str]]] = {}
    area_of: dict[str, str] = {}
    for eid, dom, ten, khu in NHA:
        ent_by_name.setdefault(_fold_diacritics(ten).strip(), []).append((eid, dom, ten))
        if khu:
            area_of[eid] = khu
    return ent_by_name, area_of


class ChuanHoaTests(unittest.TestCase):
    def test_bo_dau_bo_dau_cau_gop_khoang_trang(self):
        from services.ha_intent_rank import normalize

        self.assertEqual(normalize("  Đèn học,  Phòng đọc! "), "den hoc phong doc")
        self.assertEqual(normalize("Đèn trần"), normalize("DEN   TRAN"))

    def test_nhan_con_dau_van_so_duoc_voi_cau_da_gap_dau(self):
        """Lỗi cũ: nhãn "Đèn học Phòng đọc" vs câu đã gấp dấu cho điểm ~0."""
        from services.ha_intent_rank import rank_candidates

        cands = [
            ("Đèn khách Phòng khách", "light.khach"),
            ("Đèn học Phòng đọc", "light.hoc"),
        ]
        hit = rank_candidates("bat den hoc phong doc", cands, service="HassTurnOn")
        self.assertIsNotNone(hit, "nhãn còn dấu phải khớp được câu đã gấp dấu")
        self.assertEqual(hit.payload, "light.hoc")

    def test_bm25_nang_token_hiem(self):
        """"trần"/"đèn" có ở mọi ứng viên; "ban công" là token phân biệt."""
        from services.ha_intent_rank import rank_candidates

        cands = [
            ("Đèn trần Phòng khách", "light.tran_pk"),
            ("Đèn trần Phòng đọc", "light.tran_lv"),
            ("Đèn ban công", "light.ban_cong"),
        ]
        hit = rank_candidates("den ban cong", cands, service="HassTurnOn")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.payload, "light.ban_cong")
        self.assertGreater(hit.bm25, 0.0)


class KhopMoTests(unittest.TestCase):
    def setUp(self):
        self.ent_by_name, self.area_of = _chi_muc()

    def _chon(self, cau: str, service: str = "HassTurnOn"):
        from services.ha_intent_rank import pick_entity_fuzzy

        return pick_entity_fuzzy(
            cau.split(), self.ent_by_name, self.area_of, service=service,
        )

    def test_loi_nhan_dang_o_ten_thiet_bi(self):
        # "máy lọc khí" — nhận dạng nuốt mất "không"
        got = self._chon("may loc khi phong khach")
        self.assertIsNotNone(got, "phải cứu được câu ASR nuốt chữ")
        self.assertEqual(got[0], "switch.loc_khi")

    def test_ten_dinh_chu(self):
        got = self._chon("den bancong")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "light.ban_cong")

    def test_loi_o_ten_khu_vuc_van_chon_dung_phong(self):
        # "phòng khác" ≠ "phòng khách": phải ra Đèn trần PHÒNG KHÁCH, không phải phòng đọc
        got = self._chon("den tran phong khac")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "light.tran_pk")

    def test_trung_ten_khong_noi_phong_thi_chan(self):
        # "Đèn trần" có ở 2 phòng → nhập nhằng → không được đoán bừa
        self.assertIsNone(self._chon("den tran"))

    def test_cau_khong_lien_quan_thi_chan(self):
        for cau in ("may giat", "tivi", "may hut bui", "cua cuon nha xe", "wifi"):
            with self.subTest(cau=cau):
                self.assertIsNone(self._chon(cau))

    def test_thiet_bi_khong_co_trong_nha_thi_chan(self):
        # quạt trần chỉ có ở phòng khách → hỏi phòng khác thì không được vơ bừa.
        # Tổng điểm ca này vẫn cao (3/4 từ trùng "Đèn trần Phòng đọc") — chặn
        # được là nhờ cổng CĂN TỪ: "quat" không có từ nào tương ứng.
        self.assertIsNone(self._chon("quat tran phong doc"))
        self.assertIsNone(self._chon("quat tran nha tam"))

    def test_dung_phong_nhung_sai_thiet_bi_thi_chan(self):
        # "máy sấy" ≠ "Máy sưởi": căn từ phải ghép MỘT–MỘT, không cho "say"
        # mượn chữ "may" mà "may" của câu đã dùng.
        self.assertIsNone(self._chon("may say nha tam"))
        # đúng thiết bị nhưng sai phòng
        self.assertIsNone(self._chon("binh nong lanh phong doc"))

    def test_tu_dem_cuoi_cau_khong_pha_khop(self):
        for cau, eid in (("den bancong cho anh", "light.ban_cong"),
                         ("may loc khi phong khach nhe", "switch.loc_khi"),
                         ("den tu ho so di", "light.tu")):
            with self.subTest(cau=cau):
                got = self._chon(cau)
                self.assertIsNotNone(got, "từ đệm không được làm hỏng khớp")
                self.assertEqual(got[0], eid)

    def test_bo_qua_tu_noi_va_doan_qua_dai(self):
        from services.ha_intent_rank import FUZZY_MAX_TOKENS

        # từ nối không được tính là từ khoá
        self.assertIsNotNone(self._chon("den bancong o"))
        # cả câu dài → để model xử lý
        dai = " ".join(["den"] * (FUZZY_MAX_TOKENS + 1))
        self.assertIsNone(self._chon(dai))

    def test_khong_co_thiet_bi_nao_thi_tra_none(self):
        from services.ha_intent_rank import pick_entity_fuzzy

        self.assertIsNone(pick_entity_fuzzy(["den"], {}, {}, service="HassTurnOn"))


@unittest.skipIf(sys.version_info < (3, 10),
                 "openai_v1_chat_complete dùng cú pháp kiểu 3.10+")
class DauNoiFastPathTests(unittest.TestCase):
    """Đường nhận lệnh thật: câu vào → tool_call ra.

    Đường khớp mờ CHỈ được chạy ở nhánh mà trước đây trả rỗng, nên các ca
    "đường cũ" ở đây là chốt chống hồi quy.
    """

    def setUp(self):
        states = [{"entity_id": eid, "attributes": {"friendly_name": ten}}
                  for eid, _, ten, _ in NHA]
        area_names, entity_area = {}, {}
        from services.ha_client import _fold_diacritics
        for eid, _, _, khu in NHA:
            if khu:
                area_names[_fold_diacritics(khu).strip()] = khu
                entity_area[eid] = khu
        idx = {"area_names": area_names, "entity_area": entity_area,
               "entity_aliases": {}}
        for ten, gia_tri in (("get_states", lambda use_cache=True: states),
                             ("get_exposed_entity_ids",
                              lambda use_cache=True: {s["entity_id"] for s in states}),
                             ("get_ha_area_index", lambda use_cache=True: idx)):
            vá = mock.patch(f"services.ha_client.{ten}", gia_tri)
            vá.start()
            self.addCleanup(vá.stop)

    def _goi(self, cau: str):
        import json

        from services.protocol.openai_v1_chat_complete import _ha_local_intent

        kq = _ha_local_intent([{"role": "user", "content": cau}])
        if not kq:
            return None
        return [(c["function"]["name"], json.loads(c["function"]["arguments"]))
                for c in kq]

    def _chi_mot(self, cau: str, service: str, eid: str):
        got = self._goi(cau)
        self.assertIsNotNone(got, f"«{cau}» phải ra lệnh điều khiển")
        self.assertEqual(len(got), 1, f"«{cau}» phải ra đúng 1 lệnh")
        self.assertEqual(got[0][0], service)
        self.assertEqual(got[0][1].get("_eids"), [eid])

    def test_duong_cu_khop_chinh_xac_khong_doi(self):
        self._chi_mot("bật đèn học", "HassTurnOn", "light.hoc")
        self._chi_mot("tắt đèn trần phòng đọc", "HassTurnOff", "light.tran_lv")

    def test_khop_mo_cuu_duoc_cau_nhan_dang_sai(self):
        # sai ở TÊN THIẾT BỊ / sai ở TÊN PHÒNG / dính chữ kèm từ đệm
        self._chi_mot("bật máy lọc khí phòng khách", "HassTurnOn", "switch.loc_khi")
        self._chi_mot("bật đèn trần phòng khác", "HassTurnOn", "light.tran_pk")
        self._chi_mot("bật đèn bancong cho anh", "HassTurnOn", "light.ban_cong")

    def test_khong_chac_thi_nhuong_cho_model(self):
        for cau in ("bật quạt trần phòng đọc",  # thiết bị không có ở phòng đó
                    "bật máy sấy nhà tắm",       # sấy ≠ sưởi
                    "bật đèn trần",              # trùng tên, không nói phòng
                    "bật máy giặt"):             # không có thiết bị nào
            with self.subTest(cau=cau):
                self.assertIsNone(self._goi(cau))

    def test_cau_hen_gio_van_de_model_tao_automation(self):
        self.assertIsNone(self._goi("bật đèn trần phòng khách lúc 10h30"))


if __name__ == "__main__":
    unittest.main()
