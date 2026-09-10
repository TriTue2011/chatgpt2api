"""MQTT nhà: khám phá phổ quát, đọc bản khai, khớp tên, che mật khẩu.

Không chạm máy chủ MQTT thật. Phần khám phá test bằng cách gọi thẳng ``_nap_tin``
với tin giả — nhờ tách khỏi callback của paho nên không cần dựng máy chủ. Phần
gửi lệnh chỉ kiểm nhánh TỪ CHỐI (tên mập mờ, thực thể chỉ đọc); nhánh gửi thành
công cần một máy chủ thật, thuộc loại e2e nên không đưa vào CI.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import mqtt_nha as mq          # noqa: E402
from services.config import config           # noqa: E402


class _CauHinh:
    """Đặt cấu hình MQTT vào config mà không ghi ra đĩa."""

    def __init__(self, c: dict | None) -> None:
        self.c = c

    def __enter__(self):
        self._cu = config.data.get("mqtt")
        if self.c is None:
            config.data.pop("mqtt", None)
        else:
            config.data["mqtt"] = self.c
        self._p = mock.patch.object(config, "_save", lambda: None)
        self._p.start()
        return self

    def __exit__(self, *a) -> None:
        self._p.stop()
        if self._cu is None:
            config.data.pop("mqtt", None)
        else:
            config.data["mqtt"] = self._cu


@pytest.mark.pure
class BoLocTests(unittest.TestCase):
    """Bộ lọc đăng ký — chốt chặn quan trọng nhất của module này."""

    def test_khong_bao_gio_sinh_ra_dau_thang(self) -> None:
        """'#' bị EMQX từ chối IM LẶNG: nối được nhưng không tin nào về.

        Đây là lý do lớp này quét bằng '+'. Ai 'gọn lại' thành '#' sẽ mất sạch
        dữ liệu mà không thấy lỗi nào, nên test khoá cứng điều đó.
        """
        moi = mq.bo_loc_do_sau() + mq.bo_loc_khai_bao()
        self.assertTrue(moi, "phải có ít nhất một bộ lọc")
        for f in moi:
            self.assertNotEqual(f, "#", "không được đăng ký '#' trần")
            self.assertNotIn("#", f.split("/")[:1],
                             f"bộ lọc '{f}' bắt đầu bằng '#' — EMQX sẽ từ chối")
        self.assertNotIn("$SYS/#", moi)

    def test_do_sau_du_sau_tang(self) -> None:
        """Chỉ '+/+' thì ra 2 nhánh thay vì 5 — mất 60% thiết bị (đo thật)."""
        ds = mq.bo_loc_do_sau()
        self.assertEqual(ds[0], "+")
        self.assertEqual(ds[1], "+/+")
        self.assertGreaterEqual(len(ds), 6, "phải quét tới ít nhất 6 tầng")

    def test_bo_loc_khai_bao_co_hai_do_sau(self) -> None:
        ds = mq.bo_loc_khai_bao()
        self.assertIn("homeassistant/+/+/config", ds)
        self.assertIn("homeassistant/+/+/+/config", ds)


@pytest.mark.pure
class KhamPhaTests(unittest.TestCase):
    """Dò nhánh gốc rồi tự mở rộng — không khai báo trước gì cả."""

    def setUp(self) -> None:
        mq._reset_for_tests()

    def tearDown(self) -> None:
        mq._reset_for_tests()

    def test_nhanh_moi_thi_tu_dang_ky_ca_nhanh(self) -> None:
        da_dang_ky: list[str] = []

        def dang_ky(chu_de, qos=0):
            da_dang_ky.append(chu_de)

        mq._nap_tin("zigbee2mqtt/Bếp", b'{"state":"ON"}', dang_ky)
        self.assertIn("zigbee2mqtt/#", da_dang_ky)

        # Nhánh đã biết thì KHÔNG đăng ký lại — nếu không, mỗi tin là một lần
        # đăng ký thừa, nhà đông thiết bị sẽ ngập lệnh SUBSCRIBE.
        da_dang_ky.clear()
        mq._nap_tin("zigbee2mqtt/Nhà tắm", b'{"state":"OFF"}', dang_ky)
        self.assertEqual(da_dang_ky, [])

    def test_dem_duoc_nhieu_nhanh_goc(self) -> None:
        for ct in ("zigbee2mqtt/a", "frigate/bep/person", "tasmota/x/y",
                   "tele/DEV/LWT", "homeassistant/sensor/x/config"):
            mq._nap_tin(ct, b"1", None)
        self.assertEqual(mq.stats()["nhanh"], 5)

    def test_giu_gia_tri_moi_nhat(self) -> None:
        mq._nap_tin("zigbee2mqtt/Bếp", b"cu", None)
        mq._nap_tin("zigbee2mqtt/Bếp", b"moi", None)
        self.assertEqual(mq._gia_tri["zigbee2mqtt/Bếp"][0], "moi")

    def test_payload_khong_phai_utf8_khong_lam_sap(self) -> None:
        mq._nap_tin("zigbee2mqtt/X", b"\xff\xfe\x00binary", None)
        self.assertIn("zigbee2mqtt/X", mq._gia_tri)


@pytest.mark.pure
class BanKhaiTests(unittest.TestCase):
    """Đọc bản TỰ KHAI BÁO — dữ liệu thật lấy từ Zigbee2MQTT trên máy người dùng."""

    def setUp(self) -> None:
        mq._reset_for_tests()

    def tearDown(self) -> None:
        mq._reset_for_tests()

    def test_doc_ra_chu_de_dieu_khien(self) -> None:
        khai = {
            "name": "bình_nóng_lạnh",
            "state_topic": "zigbee2mqtt/Bình nóng lạnh",
            "command_topic": "zigbee2mqtt/Bình nóng lạnh/set",
            "payload_on": "ON", "payload_off": "OFF",
            "device": {"name": "Bình nóng lạnh"},
        }
        kq = mq.doc_ban_khai("homeassistant/switch/0xabc/state/config",
                             json.dumps(khai).encode())
        self.assertIsNotNone(kq)
        ten_tb, _ten_tt, mo_ta = kq
        self.assertEqual(ten_tb, "Bình nóng lạnh")
        self.assertEqual(mo_ta["dieu_khien"], "zigbee2mqtt/Bình nóng lạnh/set")
        self.assertEqual(mo_ta["bat"], "ON")

    def test_payload_rong_khong_phai_loi(self) -> None:
        """Payload rỗng là cách GỠ một thiết bị, không phải hỏng."""
        self.assertIsNone(mq.doc_ban_khai("homeassistant/switch/x/config", b""))

    def test_json_hong_thi_bo_qua(self) -> None:
        self.assertIsNone(mq.doc_ban_khai("homeassistant/switch/x/config", b"{khong-phai-json"))

    def test_KHONG_ghi_chu_de_LENH(self) -> None:
        """`<thiết bị>/set` là lệnh gửi đi, không phải quan sát về nhà.

        Đo thật 10/09/2026: mỗi lần bật đèn bếp sinh HAI bản ghi cùng giây —
        `zigbee2mqtt/Bếp | state_left = ON` và `zigbee2mqtt/Bếp/left | set =
        ON`. Ghi cả hai là đếm đôi mọi lần bật, và tệ hơn: `set` phần lớn do
        chính bot gửi mà lại mang `do_ai=0` nên trông như người làm.
        """
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "ghi") as g:
            mq._nap_tin("zigbee2mqtt/Bếp/left/set", b"ON", None)
        g.assert_not_called()

    def test_VAN_ghi_trang_thai_that(self) -> None:
        from services import lich_su_nha
        with mock.patch.object(lich_su_nha, "ghi") as g:
            mq._nap_tin("zigbee2mqtt/Bếp", b'{"state_left": "ON"}', None)
        g.assert_called_once()
        self.assertEqual(g.call_args[0][1], "zigbee2mqtt/Bếp")
        self.assertEqual(g.call_args[0][2], "state_left")

    def test_nap_tin_dung_so_thiet_bi(self) -> None:
        khai = {"name": "Left", "command_topic": "zigbee2mqtt/Bếp/left/set",
                "payload_on": "ON", "payload_off": "OFF",
                "device": {"name": "Bếp"}}
        mq._nap_tin("homeassistant/switch/0xbep/left/config",
                    json.dumps(khai).encode(), None)
        self.assertEqual(mq.stats()["thiet_bi"], 1)
        ds = mq.danh_sach_thiet_bi()
        bep = [d for d in ds if d["ten"] == "Bếp"]
        self.assertEqual(len(bep), 1)
        self.assertEqual(bep[0]["nguon"], "tu_khai_bao")
        self.assertEqual(len(bep[0]["dieu_khien"]), 1)


@pytest.mark.pure
class FrigateTests(unittest.TestCase):
    """Frigate không theo chuẩn tự khai báo nên có bộ nhận dạng riêng."""

    def setUp(self) -> None:
        mq._reset_for_tests()

    def tearDown(self) -> None:
        mq._reset_for_tests()

    def test_nhan_ra_chu_de_camera(self) -> None:
        f = mq.nhan_dang_frigate("frigate/phong-khach/person")
        self.assertEqual(f, {"camera": "phong-khach", "muc": "person",
                             "loai": "camera"})

    def test_nhan_ra_chu_de_he_thong(self) -> None:
        for m in ("events", "stats", "available", "reviews"):
            f = mq.nhan_dang_frigate(f"frigate/{m}")
            self.assertEqual(f["loai"], "he_thong")

    def test_khong_phai_frigate_thi_tra_none(self) -> None:
        self.assertIsNone(mq.nhan_dang_frigate("zigbee2mqtt/Bếp"))

    def test_gom_theo_camera_trong_danh_sach(self) -> None:
        mq._nap_tin("frigate/phong-khach/person", b"0", None)
        mq._nap_tin("frigate/phong-khach/all", b"0", None)
        mq._nap_tin("frigate/bep/person", b"1", None)
        ds = [d for d in mq.danh_sach_thiet_bi() if d["nguon"] == "frigate"]
        self.assertEqual(len(ds), 2, "hai camera thành hai mục")
        pk = [d for d in ds if "phong-khach" in d["ten"]][0]
        self.assertEqual(len(pk["doc"]), 2)


@pytest.mark.pure
class KhopTenTests(unittest.TestCase):
    """Khớp tên tiếng Việt. Mập mờ thì KHÔNG đoán — bật nhầm là không sửa được."""

    def setUp(self) -> None:
        mq._reset_for_tests()
        mq._so_thiet_bi.update({
            "Bình nóng lạnh": {"x": {"dieu_khien": "z/binh/set", "bat": "ON", "tat": "OFF"}},
            "Bếp": {"Left": {"dieu_khien": "z/bep/left/set", "bat": "ON", "tat": "OFF"},
                    "Linkquality": {"doc": "z/bep"}},
            "Nhà tắm": {"y": {"dieu_khien": "z/tam/set", "bat": "ON", "tat": "OFF"}},
        })

    def tearDown(self) -> None:
        mq._reset_for_tests()

    def test_khop_khong_dau(self) -> None:
        self.assertEqual(mq._khop_ten("binh nong lanh"), "Bình nóng lạnh")
        self.assertEqual(mq._khop_ten("bep"), "Bếp")

    def test_khong_dinh_tu_nao_thi_rong(self) -> None:
        self.assertEqual(mq._khop_ten("máy giặt"), "")

    def test_ten_rong_thi_rong(self) -> None:
        self.assertEqual(mq._khop_ten(""), "")

    def test_dieu_khien_ten_la_thi_bao_loi_kem_goi_y(self) -> None:
        with self.assertRaises(mq.LoiMqtt) as e:
            mq.dieu_khien("máy giặt", "x", True)
        self.assertIn("Bếp", str(e.exception), "phải gợi ý thiết bị đang có")

    def test_dieu_khien_thuc_the_chi_doc_thi_tu_choi(self) -> None:
        with self.assertRaises(mq.LoiMqtt) as e:
            mq.dieu_khien("Bếp", "Linkquality", True)
        self.assertIn("chỉ đọc", str(e.exception))

    def test_dieu_khien_thuc_the_khong_co_thi_liet_ke_cai_co(self) -> None:
        with self.assertRaises(mq.LoiMqtt) as e:
            mq.dieu_khien("Bếp", "Right", True)
        self.assertIn("Left", str(e.exception))

    def test_chua_quet_gi_thi_bao_quet_truoc(self) -> None:
        mq._reset_for_tests()
        with self.assertRaises(mq.LoiMqtt) as e:
            mq.dieu_khien("Bếp", "Left", True)
        self.assertIn("Quét", str(e.exception))


@pytest.mark.pure
class CauHinhTests(unittest.TestCase):
    """Cấu hình máy chủ: che mật khẩu, giữ mật khẩu cũ, bật/tắt."""

    def test_start_khong_chay_khi_chua_khai_host(self) -> None:
        with _CauHinh({"host": "", "enabled": True}):
            self.assertFalse(mq.start(), "chưa khai host thì không được chạy")

    def test_start_khong_chay_khi_tat_co(self) -> None:
        with _CauHinh({"host": "1.2.3.4", "enabled": False}):
            self.assertFalse(mq.start(), "enabled=false thì không được chạy")

    def test_start_khong_chay_khi_khong_co_khoa_mqtt(self) -> None:
        with _CauHinh(None):
            self.assertFalse(mq.start())

    def test_doc_cau_hinh_che_mat_khau(self) -> None:
        with _CauHinh({"host": "1.2.3.4", "username": "u", "password": "bimat"}):
            c = mq.doc_cau_hinh()
            self.assertEqual(c["password"], "***")
            self.assertEqual(c["username"], "u")

    def test_luu_giu_mat_khau_cu_khi_gui_dau_sao(self) -> None:
        """Web hiện '***'; không giữ thì mỗi lần sửa cổng là mất mật khẩu."""
        with _CauHinh({"host": "1.2.3.4", "port": 1883, "password": "bimat"}):
            mq.luu_cau_hinh("1.2.3.4", 8883, password="***")
            self.assertEqual(config.data["mqtt"]["password"], "bimat")
            self.assertEqual(config.data["mqtt"]["port"], 8883)

    def test_luu_doi_duoc_mat_khau(self) -> None:
        with _CauHinh({"host": "1.2.3.4", "password": "cu"}):
            mq.luu_cau_hinh("1.2.3.4", 1883, password="moi")
            self.assertEqual(config.data["mqtt"]["password"], "moi")

    def test_luu_thieu_host_thi_bao_loi(self) -> None:
        with _CauHinh({}):
            with self.assertRaises(mq.LoiMqtt):
                mq.luu_cau_hinh("")

    def test_luu_cong_sai_thi_bao_loi(self) -> None:
        with _CauHinh({}):
            with self.assertRaises(mq.LoiMqtt):
                mq.luu_cau_hinh("1.2.3.4", 99999)

    def test_danh_sach_khong_lo_mat_khau(self) -> None:
        with _CauHinh({"host": "1.2.3.4", "password": "SieuBiMat"}):
            mq._reset_for_tests()
            mq._nap_tin("zigbee2mqtt/X", b"1", None)
            chuoi = json.dumps(mq.danh_sach_thiet_bi(), ensure_ascii=False)
            self.assertNotIn("SieuBiMat", chuoi)
            mq._reset_for_tests()



class KhopTenCamera(unittest.TestCase):
    """Camera Frigate phải khớp được tên như thiết bị thường.

    Lỗi thật đã gặp (09/09/2026): hỏi "camera phòng khách" trả rỗng, bot không
    trả lời được, dù danh sách thiết bị CÓ 'Camera phong-khach'. Vì _khop_ten
    chỉ tra `_so_thiet_bi` (chuẩn tự khai báo) mà Frigate không đi đường đó.
    """

    def setUp(self) -> None:
        mq._reset_for_tests()
        mq._so_thiet_bi.update({t: {} for t in
                                ("Cảm biến phòng khách", "Quạt phòng khách",
                                 "Hiện diện bếp", "Phòng khách")})
        mq._gia_tri.update({f"frigate/{c}/person": ("1", 0.0)
                            for c in ("phong-khach", "bep", "cua")})

    def tearDown(self) -> None:
        mq._reset_for_tests()

    def test_khop_duoc_camera_frigate(self) -> None:
        self.assertEqual(mq._khop_ten("camera phòng khách"), "Camera phong-khach")

    def test_khop_ten_camera_viet_khong_dau(self) -> None:
        self.assertEqual(mq._khop_ten("Camera phong-khach"), "Camera phong-khach")

    def test_van_khop_dung_thiet_bi_thuong(self) -> None:
        """Sửa cho camera KHÔNG được làm hỏng khớp thiết bị Zigbee."""
        self.assertEqual(mq._khop_ten("quạt phòng khách"), "Quạt phòng khách")
        self.assertEqual(mq._khop_ten("hiện diện bếp"), "Hiện diện bếp")

    def test_map_mo_van_tra_rong(self) -> None:
        """Nguyên tắc cũ giữ nguyên: không chắc thì KHÔNG đoán."""
        self.assertEqual(mq._khop_ten("cái gì đó"), "")


class DemNguoiTuFrigate(unittest.TestCase):
    """Đọc số Frigate ĐÃ đếm thay vì chụp lại ảnh — và không được tin số CŨ.

    Lỗi thật 09/09/2026: gương MQTT rớt 150 phút, `person` đóng băng ở 1 trong
    khi Frigate thật đang là 0. Bot vẫn khẳng định "có 1 người". Số đã chết mà
    nói chắc chắn thì tệ hơn im lặng.
    """

    def setUp(self) -> None:
        mq._reset_for_tests()
        mq._gia_tri.update({
            "frigate/phong-khach/person": ("2", 1.0),
            "frigate/phong-khach/person/active": ("1", 1.0),
            "frigate/bep/person": ("0", 1.0),
        })

    def tearDown(self) -> None:
        mq._reset_for_tests()

    def test_doc_duoc_so_nguoi(self) -> None:
        mq._stats["last_tin_ts"] = time.time()
        d = mq.dem_nguoi()
        self.assertEqual(d["phong-khach"]["nguoi"], 2)
        self.assertEqual(d["phong-khach"]["dang_hoat_dong"], 1)
        self.assertEqual(d["bep"]["nguoi"], 0)

    def test_loc_theo_ten_camera(self) -> None:
        mq._stats["last_tin_ts"] = time.time()
        self.assertEqual(list(mq.dem_nguoi("bep")), ["bep"])

    def test_DU_LIEU_CU_KHONG_DUOC_TRA_SO(self) -> None:
        """Mấu chốt: rớt mạng thì thà báo không chắc còn hơn báo số đã chết."""
        mq._stats["last_tin_ts"] = time.time() - 9000      # 150 phút trước
        d = mq.dem_nguoi()
        self.assertTrue(d.get("_cu"), "dữ liệu cũ PHẢI bị đánh dấu")
        self.assertNotIn("phong-khach", d, "không được trả số khi đã cũ")

    def test_chua_nhan_tin_nao_cung_la_cu(self) -> None:
        mq._stats["last_tin_ts"] = 0
        self.assertTrue(mq.dem_nguoi().get("_cu"))

    def test_bo_qua_anh_snapshot(self) -> None:
        """person/snapshot là ảnh JPEG thô, không phải số đếm."""
        mq._stats["last_tin_ts"] = time.time()
        mq._gia_tri["frigate/cua/person/snapshot"] = ("\xff\xd8\xff", 1.0)
        self.assertNotIn("cua", mq.dem_nguoi())

if __name__ == "__main__":
    unittest.main()
