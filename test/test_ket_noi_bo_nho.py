"""Kết nối bộ nhớ: bình đẳng (hai chiều) và chính phụ (một chiều).

Mặc định mọi phạm vi độc lập tuyệt đối (services/agent/scope.py). Tính năng này
mở đường ĐỌC giữa những phạm vi mà chủ máy khai là có liên quan:

  * bình đẳng — các thành viên đọc được của nhau, HAI CHIỀU;
  * chính phụ — CHÍNH đọc được PHỤ, PHỤ KHÔNG đọc được CHÍNH, MỘT CHIỀU.

Điều phải khoá chặt nhất là chiều CẤM: một lỗi ở đó không kêu, không có triệu
chứng, chỉ là dữ liệu của người này lặng lẽ hiện trong prompt của người kia.

Và: kết nối CHỈ mở đường đọc. Ghi vẫn vào phạm vi của chính lượt đó — nối rồi gỡ
mà dữ liệu đã chảy sang nhau thì không tách lại được nữa.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import scope, state  # noqa: E402

# Ba phạm vi độc lập để nối với nhau.
BO = "zalop_111"          # Zalo cá nhân 1-1
ME = "zalop_222"
NHOM = "-100"             # nhóm Telegram (chưa lọc user → thành viên dùng chung)
CON = "333"               # Telegram 1-1


def tv(kenh: str, chat: str, topic: str = "", user: str = "") -> dict:
    return {"kenh": kenh, "chat": chat, "topic": topic, "user": user}


class _CoCauHinh(unittest.TestCase):
    def setUp(self):
        self.cfg: dict = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def _noi(self, *moi):
        self.cfg["memory_links"] = list(moi)


class KhoaPhienTuThanhVien(_CoCauHinh):
    """Dựng lại khoá phiên từ thành viên — nghịch của tach_khoa_phien."""

    def test_di_va_ve_khong_lech(self):
        for kp in ("555", "-100", "-100#7", "zalo_123", "zalop_987"):
            with self.subTest(kp):
                sc = scope.tach_khoa_phien(kp)
                lai = scope.khoa_phien_tu_thanh_vien(
                    tv(sc.kenh, sc.chat, sc.topic, sc.actor))
                self.assertEqual(scope.khoa_du_lieu(lai), scope.khoa_du_lieu(kp))

    def test_co_nguoi_thi_gan_dung_hau_to(self):
        self.assertEqual(scope.khoa_phien_tu_thanh_vien(tv("tg", "-100", "7", "9")),
                         "-100#7:u9")
        self.assertEqual(scope.khoa_phien_tu_thanh_vien(tv("zalo", "123", "", "456")),
                         "zalo_123:u456")

    def test_thieu_chat_thi_rong(self):
        self.assertEqual(scope.khoa_phien_tu_thanh_vien(tv("tg", "")), "")


class BinhDang(_CoCauHinh):
    def test_hai_chieu(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertIn(scope.khoa_du_lieu(ME), scope.pham_vi_doc_them(BO))
        self.assertIn(scope.khoa_du_lieu(BO), scope.pham_vi_doc_them(ME))

    def test_khong_gom_chinh_no(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertNotIn(scope.khoa_du_lieu(BO), scope.pham_vi_doc_them(BO))

    def test_nguoi_ngoai_khong_duoc_gi(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertEqual(scope.pham_vi_doc_them(CON), [])

    def test_noi_duoc_NHIEU_thanh_vien(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222"),
                               tv("tg", "-100"), tv("tg", "333")]})
        self.assertEqual(len(scope.pham_vi_doc_them(BO)), 3)

    def test_noi_duoc_XUYEN_KENH(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("tg", "-100")]})
        self.assertIn(scope.khoa_du_lieu(NHOM), scope.pham_vi_doc_them(BO))
        self.assertIn(scope.khoa_du_lieu(BO), scope.pham_vi_doc_them(NHOM))

    def test_NHIEU_moi_noi_cong_don(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]},
                  {"id": "2", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("tg", "-100")]})
        ra = scope.pham_vi_doc_them(BO)
        self.assertIn(scope.khoa_du_lieu(ME), ra)
        self.assertIn(scope.khoa_du_lieu(NHOM), ra)


class ChinhPhu(_CoCauHinh):
    def _cha_con(self):
        self._noi({"id": "1", "kind": "chinh_phu",
                   "primary": [tv("zalop", "111"), tv("zalop", "222")],
                   "secondary": [tv("tg", "333"), tv("tg", "-100")]})

    def test_chinh_doc_duoc_phu(self):
        self._cha_con()
        ra = scope.pham_vi_doc_them(BO)
        self.assertIn(scope.khoa_du_lieu(CON), ra)
        self.assertIn(scope.khoa_du_lieu(NHOM), ra)

    def test_PHU_KHONG_doc_duoc_CHINH(self):
        """Chiều cấm. Sai ở đây thì không kêu, chỉ lặng lẽ rò."""
        self._cha_con()
        self.assertEqual(scope.pham_vi_doc_them(CON), [])
        self.assertEqual(scope.pham_vi_doc_them(NHOM), [])

    def test_hai_CHINH_khong_tu_dong_doc_cua_nhau(self):
        """Cùng làm chính không có nghĩa là bình đẳng với nhau."""
        self._cha_con()
        self.assertNotIn(scope.khoa_du_lieu(ME), scope.pham_vi_doc_them(BO))

    def test_hai_PHU_khong_doc_cua_nhau(self):
        self._cha_con()
        self.assertNotIn(scope.khoa_du_lieu(NHOM), scope.pham_vi_doc_them(CON))

    def test_vua_la_chinh_o_noi_nay_vua_la_phu_o_noi_kia(self):
        self._noi({"id": "1", "kind": "chinh_phu",
                   "primary": [tv("zalop", "111")], "secondary": [tv("tg", "333")]},
                  {"id": "2", "kind": "chinh_phu",
                   "primary": [tv("zalop", "222")], "secondary": [tv("zalop", "111")]})
        # BO là chính ở mối 1 → đọc được CON; là phụ ở mối 2 → không thấy ME.
        ra = scope.pham_vi_doc_them(BO)
        self.assertIn(scope.khoa_du_lieu(CON), ra)
        self.assertNotIn(scope.khoa_du_lieu(ME), ra)


class KhopThanhVien(_CoCauHinh):
    def test_o_trong_la_moi_gia_tri(self):
        """Nối 'cả nhóm' là một dòng, không phải liệt kê từng người."""
        self.cfg["thread_user_filters"] = {"tg:-100:9": ["device"]}   # nhóm có lọc
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("tg", "-100"), tv("zalop", "111")]})
        # Cả u9 lẫn u10 trong nhóm -100 đều khớp dòng 'cả nhóm'.
        for uid in ("9", "10"):
            self.assertIn(scope.khoa_du_lieu(BO),
                          scope.pham_vi_doc_them(f"-100:u{uid}"), uid)

    def test_neu_neu_dich_danh_NGUOI_thi_nguoi_khac_khong_khop(self):
        self.cfg["thread_user_filters"] = {"tg:-100:9": ["device"]}
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("tg", "-100", user="9"), tv("zalop", "111")]})
        self.assertTrue(scope.pham_vi_doc_them("-100:u9"))
        self.assertEqual(scope.pham_vi_doc_them("-100:u10"), [])

    def test_neu_dich_danh_TOPIC_thi_topic_khac_khong_khop(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("tg", "-100", topic="7"), tv("zalop", "111")]})
        self.assertTrue(scope.pham_vi_doc_them("-100#7"))
        self.assertEqual(scope.pham_vi_doc_them("-100#8"), [])

    def test_kenh_khac_thi_khong_khop_du_trung_id(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("tg", "123"), tv("zalop", "111")]})
        self.assertEqual(scope.pham_vi_doc_them("zalo_123"), [])


class CauHinhHong(_CoCauHinh):
    def test_khong_co_cau_hinh_thi_khong_noi_gi(self):
        self.assertEqual(scope.pham_vi_doc_them(BO), [])

    def test_tat_moi_noi_thi_ngung_hieu_luc(self):
        self._noi({"id": "1", "kind": "binh_dang", "enabled": False,
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertEqual(scope.pham_vi_doc_them(BO), [])

    def test_kieu_la_thi_bo_qua(self):
        self._noi({"id": "1", "kind": "khong_biet",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertEqual(scope.pham_vi_doc_them(BO), [])

    def test_cau_hinh_rac_khong_lam_vo(self):
        for rac in ("chuỗi", 123, [1, 2], [{"kind": "binh_dang"}], [{}], None):
            self.cfg["memory_links"] = rac
            self.assertEqual(scope.pham_vi_doc_them(BO), [], repr(rac))

    def test_thu_tu_on_dinh(self):
        """Prompt nhảy lung tung là hỏng cache và khó dò lỗi."""
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("tg", "-100"),
                               tv("tg", "333"), tv("zalop", "222")]})
        self.assertEqual(scope.pham_vi_doc_them(BO), scope.pham_vi_doc_them(BO))
        self.assertEqual(scope.pham_vi_doc_them(BO),
                         [scope.khoa_du_lieu(NHOM), scope.khoa_du_lieu(CON),
                          scope.khoa_du_lieu(ME)])


class TriNhoThatSuChayQua(_CoCauHinh):
    """Không chỉ tính đúng danh sách — trí nhớ phải thật sự đọc được."""

    def setUp(self):
        super().setUp()
        self.thu_muc = pathlib.Path(tempfile.mkdtemp(prefix="ket-noi-"))
        self.addCleanup(shutil.rmtree, self.thu_muc, True)
        self._goc = (state._MEMORY_FILE, state._MEMORY_DB_PATH,
                     state._MEMORY_SCOPE_DIR, state._mem_conn)
        state._MEMORY_FILE = self.thu_muc / "MEMORY.md"
        state._MEMORY_FILE.write_text("", encoding="utf-8")
        state._MEMORY_DB_PATH = self.thu_muc / "chung.sqlite"
        state._MEMORY_SCOPE_DIR = self.thu_muc / "memory"
        state._MEMORY_SCOPE_DIR.mkdir(parents=True, exist_ok=True)
        state._mem_conn = {}

    def tearDown(self):
        (state._MEMORY_FILE, state._MEMORY_DB_PATH,
         state._MEMORY_SCOPE_DIR, state._mem_conn) = self._goc

    def _doc(self, kp: str) -> str:
        return state.load_memory(pham_vi=scope.khoa_du_lieu(kp),
                                 doc_them=scope.pham_vi_doc_them(kp))

    def test_binh_dang_doc_duoc_fact_cua_nhau(self):
        state.append_memory("Mẹ thích hoa cúc trắng", pham_vi=scope.khoa_du_lieu(ME))
        self.assertNotIn("hoa cúc", self._doc(BO))     # chưa nối
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertIn("hoa cúc", self._doc(BO))

    def test_chinh_phu_MOT_CHIEU_tren_du_lieu_that(self):
        state.append_memory("Con đang ôn thi học kỳ", pham_vi=scope.khoa_du_lieu(CON))
        state.append_memory("Lương bố tháng này 30 triệu",
                            pham_vi=scope.khoa_du_lieu(BO))
        self._noi({"id": "1", "kind": "chinh_phu",
                   "primary": [tv("zalop", "111")], "secondary": [tv("tg", "333")]})
        self.assertIn("ôn thi", self._doc(BO))          # chính thấy phụ
        self.assertNotIn("Lương bố", self._doc(CON))    # phụ KHÔNG thấy chính

    def test_tim_kiem_toan_van_cung_theo_ket_noi(self):
        state.append_memory("Xe máy nhà mình biển 29X1", pham_vi=scope.khoa_du_lieu(ME))
        tim = lambda kp: state.search_memory(  # noqa: E731
            "biển xe", pham_vi=scope.khoa_du_lieu(kp),
            doc_them=scope.pham_vi_doc_them(kp))
        self.assertEqual(tim(BO), [])
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertTrue(tim(BO))

    def test_GHI_van_vao_pham_vi_cua_chinh_minh(self):
        """Nối chỉ mở đường ĐỌC. Ghi lẫn sang nhau thì gỡ nối không tách lại được."""
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        state.append_memory("Bố hẹn nha sĩ thứ Sáu", pham_vi=scope.khoa_du_lieu(BO))
        tep_me = state._memory_file(scope.khoa_du_lieu(ME))
        self.assertFalse(tep_me.exists() and "nha sĩ" in tep_me.read_text("utf-8"))
        # Gỡ nối → không còn thấy nữa, vì dữ liệu chưa từng chảy sang.
        self.cfg["memory_links"] = []
        self.assertNotIn("nha sĩ", self._doc(ME))

    def test_chan_trung_KHONG_tinh_fact_muon(self):
        """Trùng với fact mượn mà bỏ ghi thì gỡ nối là mất trắng điều vừa dặn."""
        fact = "Nhà có hai con mèo tam thể tên Mun và Bơ"
        state.append_memory(fact, pham_vi=scope.khoa_du_lieu(ME))
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertEqual(state.nho_hoac_cap_nhat(fact, pham_vi=scope.khoa_du_lieu(BO)),
                         "them")


class WikiChayQuaKetNoi(_CoCauHinh):
    def setUp(self):
        super().setUp()
        self.thu_muc = pathlib.Path(tempfile.mkdtemp(prefix="ket-noi-wiki-"))
        self.addCleanup(shutil.rmtree, self.thu_muc, True)
        from services.agent import wiki as w
        self.w = w
        w._reset_for_tests(self.thu_muc)

    def test_binh_dang_thay_ghi_chu_cua_nhau(self):
        pv_me = scope.khoa_du_lieu(ME)
        self.w.ingest("lịch tiêm phòng của con tháng này", title="tiêm phòng",
                      pham_vi=pv_me)
        doc = lambda kp: self.w.search(  # noqa: E731
            "tiêm phòng", pham_vi=scope.khoa_du_lieu(kp),
            doc_them=scope.pham_vi_doc_them(kp))
        self.assertEqual(doc(BO), [])
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertTrue(doc(BO))

    def test_phu_khong_doc_duoc_ghi_chu_cua_chinh(self):
        self.w.ingest("sổ tiết kiệm ngân hàng số 123456",
                      title="sổ tiết kiệm", pham_vi=scope.khoa_du_lieu(BO))
        self._noi({"id": "1", "kind": "chinh_phu",
                   "primary": [tv("zalop", "111")], "secondary": [tv("tg", "333")]})
        self.assertEqual(
            self.w.search("tiết kiệm", pham_vi=scope.khoa_du_lieu(CON),
                          doc_them=scope.pham_vi_doc_them(CON)), [])

    def test_read_theo_slug_cung_theo_ket_noi(self):
        out = self.w.ingest("mã khoá cửa nhà là 8642", title="khoá cửa",
                            pham_vi=scope.khoa_du_lieu(ME))
        slug = out["slug"]
        self.assertIsNone(self.w.read(slug, pham_vi=scope.khoa_du_lieu(BO)))
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})
        self.assertIsNotNone(self.w.read(slug, pham_vi=scope.khoa_du_lieu(BO),
                                         doc_them=scope.pham_vi_doc_them(BO)))


if __name__ == "__main__":
    unittest.main()
