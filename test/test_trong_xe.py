"""Trông xe — chỉ khi được nhờ: xe bị dời thì báo động, người nhà lấy xe thì thôi.

Chủ máy 27/09/2026: "trường hợp tôi yêu cầu em trông cho tôi xe ở cửa, báo động khi có trộm …
khi xe thay đổi tọa độ thì báo động bằng âm thanh, tin nhắn. Nhưng nếu nhận diện được người nhà
qua cam thì không báo động và dừng theo dõi, hoặc yêu cầu dừng theo dõi" — "chỉ giám sát khi được
yêu cầu, không giám sát khi yêu cầu dừng hoặc người nhà lấy xe đi".

Khung giả 200×200 xám 100; vùng xe (50..100) đổi sang 200 khi xe bị dắt đi. Không test nào phát
ra loa thật: `_phat` luôn bị thay.
"""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("cv2")

from services import camera_nha, nhin_nha, so_mat_nha, trong_xe, yolo_nha  # noqa: E402

pytestmark = pytest.mark.pure

HOP = [50, 50, 100, 100]
XE = yolo_nha.VatThe("motorcycle", 0.8, tuple(HOP))
NGUOI_CHE = yolo_nha.VatThe("person", 0.9, (60, 20, 90, 120))


def _khung(xe_con: bool = True):
    anh = np.full((200, 200, 3), 100, np.uint8)
    if not xe_con:
        anh[50:100, 50:100] = 200
    return anh


@pytest.fixture
def tx(tmp_path, monkeypatch):
    trong_xe._reset_for_tests(tmp_path / "trong_xe.json")
    canh = {"anh": _khung(), "vat": [XE], "mat": []}
    gui: list[tuple] = []
    loa: list[str] = []
    monkeypatch.setattr(trong_xe, "_khung", lambda cam, luong="phu": canh["anh"])
    monkeypatch.setattr(trong_xe, "_anh_ro", lambda cam: canh["anh"])
    monkeypatch.setattr(trong_xe, "_ve_xe", lambda anh, xe: "http://anh")
    monkeypatch.setattr(trong_xe, "_chay", lambda: None)
    monkeypatch.setattr(trong_xe, "_phat", lambda announce, ten, cau: loa.append(ten))
    monkeypatch.setattr(camera_nha, "tim", lambda ten: ("Cam cửa", {"name": "Cam cửa"}, ["Cam cửa"]))
    monkeypatch.setattr(nhin_nha, "vat_the", lambda anh, chi_nhan=None: [
        v for v in canh["vat"] if chi_nhan is None or v.nhan in chi_nhan])
    monkeypatch.setattr(nhin_nha, "co_mat", lambda: True)
    monkeypatch.setattr(nhin_nha, "phan_tich_khung", lambda anh: nhin_nha.KhungDaXem(200, 200, [], canh["mat"]))
    monkeypatch.setattr(so_mat_nha, "su_kien_gan", lambda *a, **k: [])
    from services import digest, thong_bao
    monkeypatch.setattr(thong_bao, "cai_dat", lambda k: {"bat": True, "kenh": ["zalop:acc:nhom", "tg:b:1"]})
    monkeypatch.setattr(digest, "send_targets", lambda kenh, tin, anh="": gui.append((list(kenh), tin)) or len(kenh))
    canh["gui"], canh["loa"] = gui, loa
    yield canh
    trong_xe._reset_for_tests(tmp_path / "trong_xe.json")


def _bat(canh):
    kq = trong_xe.bat("cửa", loa=["Loa khách"], dich="zalop:acc:nhom")
    trong_xe.kiem_mot_lan()                       # dựng mốc
    for _ in range(trong_xe.LAN_DO_NHIEU):         # bot tự đo độ nhiễu của chính vùng xe
        assert trong_xe.kiem_mot_lan() == ""
    return kq


def test_khong_thay_xe_thi_hoi_lai(tx):
    tx["vat"] = []
    with pytest.raises(trong_xe.LoiTrongXe):
        trong_xe.bat("cửa", loa=[])
    assert not trong_xe.trang_thai().get("bat")


def test_xe_nam_yen_khong_bao_dong(tx):
    kq = _bat(tx)
    assert kq["xe"][0]["nhan"] == "motorcycle" and kq["loa"] == ["Loa khách"]
    for _ in range(20):
        assert trong_xe.kiem_mot_lan() == ""
    assert tx["gui"] == [] and tx["loa"] == []


def test_xe_bi_dat_di_thi_bao_dong_mot_lan_moi_kenh(tx):
    _bat(tx)
    tx["anh"], tx["vat"] = _khung(xe_con=False), []
    kq = [trong_xe.kiem_mot_lan() for _ in range(trong_xe.LAN_XAC_NHAN)]
    assert kq == ["lech"] * (trong_xe.LAN_XAC_NHAN - 1) + ["bao_dong"]
    assert tx["loa"] == ["Loa khách"]
    assert len(tx["gui"]) == 2, "báo SỚM ở lượt lệch đầu + báo động — mỗi lần MỘT tin mỗi kênh"
    assert tx["gui"][0][0] == ["zalop:acc:nhom", "tg:b:1"]
    assert "vừa bị động tới" in tx["gui"][0][1] and "BÁO ĐỘNG" in tx["gui"][1][1]
    assert not trong_xe.trang_thai()["bat"], "báo động xong thì dừng, nhắn lại mới trông tiếp"


def test_mot_khung_yolo_mat_xe_khong_bao_dong(tx):
    """YOLO có lúc mất hẳn vật 1–2 khung (đo 27/09/2026) — ảnh vùng xe không đổi thì không đếm."""
    _bat(tx)
    tx["vat"] = []
    for _ in range(5):
        assert trong_xe.kiem_mot_lan() == ""
    assert tx["loa"] == []


def test_nguoi_nha_o_cho_xe_thi_thoi_khong_bao(tx):
    """Có người ở chỗ xe, nhìn mặt trên ảnh luồng chính ra người nhà → dừng trông, không báo."""
    _bat(tx)
    tx["anh"], tx["vat"] = _khung(xe_con=False), [NGUOI_CHE]
    tx["mat"] = [{"nguoi_id": "p1", "loai": "quen", "ten": "Con trai Trí Anh"}]
    assert trong_xe.kiem_mot_lan() == "nguoi_nha"
    assert tx["loa"] == [] and len(tx["gui"]) == 1
    assert "Con trai Trí Anh vừa lấy xe" in tx["gui"][0][1]


def test_ke_dat_xe_con_trong_khung_van_bao_ngay(tx):
    """23:07 ngày 27/09/2026: người vào 23:07:35, rời khung 23:07:58, bot báo 23:07:58 vì chờ người
    rời khung — "lấy trộm đi xa rồi mới báo". Nay người còn đứng đó: lượt lệch đầu BÁO SỚM, đủ
    LAN_XAC_NHAN lượt → báo động."""
    _bat(tx)
    tx["anh"], tx["vat"] = _khung(xe_con=False), [NGUOI_CHE]
    kq = [trong_xe.kiem_mot_lan() for _ in range(trong_xe.LAN_XAC_NHAN)]
    assert kq == ["lech"] * (trong_xe.LAN_XAC_NHAN - 1) + ["bao_dong"]
    assert "có người ở chỗ xe" in tx["gui"][0][1] and "BÁO ĐỘNG" in tx["gui"][-1][1]
    assert tx["loa"] == ["Loa khách"]


def test_khoi_dong_lai_van_phan_bang_moc_tren_dia(tx):
    """Mốc chỉ ở RAM thì sau khởi động lại chỉ còn MỘT khung YOLO để phán — đo 27/09/2026 ở Cam
    ban công, vật đứng yên mà YOLO thấy 1/3 khung, lượt đầu lỡ là bot thôi trông. Mốc ghi đĩa:
    khung YOLO lỡ mà ảnh vùng xe không đổi thì vẫn yên; xe đi thật thì báo như thường."""
    _bat(tx)
    trong_xe._moc.clear()                        # như vừa khởi động lại
    tx["vat"] = []
    assert [trong_xe.kiem_mot_lan() for _ in range(5)] == [""] * 5
    trong_xe._moc.clear()
    tx["anh"] = _khung(xe_con=False)
    kq = [trong_xe.kiem_mot_lan() for _ in range(trong_xe.LAN_XAC_NHAN)]
    assert kq[-1] == "bao_dong" and tx["loa"] == ["Loa khách"]


def test_khong_co_moc_thi_cho_nhieu_luot_moi_ket_luan_xe_da_di(tx):
    _bat(tx)
    trong_xe._moc.clear()
    trong_xe._tep_moc().unlink()
    tx["anh"], tx["vat"] = _khung(xe_con=False), []
    kq = [trong_xe.kiem_mot_lan() for _ in range(trong_xe.LAN_DO_NHIEU)]
    assert kq == [""] * (trong_xe.LAN_DO_NHIEU - 1) + ["mat_xe_khi_nghi"]
    assert tx["loa"] == [], "không chắc có trộm — chỉ nhắn, không hú loa"
    assert "khởi động lại" in tx["gui"][0][1]
    assert not trong_xe.trang_thai()["bat"] and not trong_xe._tep_moc().exists()


def test_luot_cu_theo_luong_chinh_thi_tat_khi_khoi_dong(tx, monkeypatch):
    """Lượt bật trước khi đổi sang luồng phụ: hộp xe theo toạ độ luồng chính — so với khung luồng
    phụ là lệch hẳn, báo nhầm. Khởi động lại thì tắt lượt đó."""
    trong_xe._luu({"bat": True, "camera": "Cam cửa", "xe": [{"nhan": "car", "hop": HOP}]})
    assert trong_xe.khoi_phuc() is False and not trong_xe.trang_thai()["bat"]
    trong_xe._luu({"bat": True, "camera": "Cam cửa", "xe": [{"nhan": "car", "hop": HOP}], "luong": "chinh"})
    assert trong_xe.khoi_phuc() is True


def test_dung_theo_yeu_cau(tx):
    _bat(tx)
    assert trong_xe.dung() and not trong_xe.dung()
    assert trong_xe.kiem_mot_lan() == ""


def test_dung_roi_trong_lai_ngay_van_co_luong_moi(tmp_path, monkeypatch):
    """Dùng chung một cờ dừng thì «dừng» rồi «trông xe» ngay gặp luồng cũ chưa kịp thoát —
    lượt mới không ai trông."""
    trong_xe._reset_for_tests(tmp_path / "t.json")
    monkeypatch.setattr(trong_xe, "CHU_KY", 30.0)
    trong_xe._luu({"bat": True, "camera": "Cam cửa", "xe": []})
    trong_xe._chay()
    cu = trong_xe._luong
    trong_xe.dung()
    trong_xe._luu({"bat": True, "camera": "Cam cửa", "xe": []})
    trong_xe._chay()
    moi = trong_xe._luong
    assert cu is not None and moi is not None and moi[0] is not cu[0]
    assert cu[1].is_set() and not moi[1].is_set()
    trong_xe._reset_for_tests(tmp_path / "t.json")


NGUOI_XA = yolo_nha.VatThe("person", 0.9, (150, 0, 195, 45))


def test_luc_bat_co_nguoi_di_lai_thi_cho_yen_roi_moi_do(tx):
    """27/09/2026 20:52 Cam phòng khách: chủ máy đặt xe đạp rồi đi ra đúng lúc bot đo 5 lượt đầu —
    vùng xe lệch tới 55,8 → ngưỡng 167; dắt xe đi thật chỉ lệch 32, bot im. Nay: chưa yên thì chờ,
    nhiễu đo bằng trung vị trên lượt yên."""
    rng = np.random.default_rng(0)
    tx["vat"] = [XE, NGUOI_XA]
    trong_xe.bat("cửa", loa=[], dich="zalop:acc:nhom")
    for _ in range(4):                               # người còn đi lại, cảnh đổi liên tục
        tx["anh"] = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
        assert trong_xe.kiem_mot_lan() == "cho_yen"
    tx["anh"], tx["vat"] = _khung(), [XE]            # người đã ra, cảnh yên
    kq = [trong_xe.kiem_mot_lan() for _ in range(trong_xe.LAN_DO_NHIEU + 1)]
    assert kq[0] == "cho_yen" and set(kq[1:]) == {""}
    anh = _khung(); anh[50:100, 50:100] = 130        # xe đi: vùng xe chỉ lệch 30
    tx["anh"], tx["vat"] = anh, []
    kq = [trong_xe.kiem_mot_lan() for _ in range(trong_xe.LAN_XAC_NHAN)]
    assert kq[-1] == "bao_dong" and "BÁO ĐỘNG" in tx["gui"][-1][1]


def test_tat_den_ca_phong_khong_bao_dong(tx):
    """Cả khung tối đi, YOLO mất xe: chưa phân biệt được đèn tắt với xe đi — không đếm."""
    _bat(tx)
    tx["anh"], tx["vat"] = np.full((200, 200, 3), 20, np.uint8), []
    for _ in range(6):
        assert trong_xe.kiem_mot_lan() == "doi_canh"
    assert tx["gui"] == []
    tx["anh"], tx["vat"] = np.full((200, 200, 3), 20, np.uint8), [XE]   # YOLO thấy lại xe → lấy lại mốc
    assert trong_xe.kiem_mot_lan() == "doi_sang"


def test_mac_dinh_khong_hu_loa_chi_nhan_tin(tx, monkeypatch):
    """Chủ máy 27/09/2026: "Tạm thời cảnh báo về zalo, không cảnh báo loa"."""
    from services.config import config
    from services.voice import speakers
    monkeypatch.setattr(speakers, "list_speakers", lambda: [{"name": "Loa khách"}])
    monkeypatch.setitem(config.data, "nhin_nha", {})
    assert trong_xe.bat("cửa", dich="zalop:acc:nhom")["loa"] == []
    trong_xe.kiem_mot_lan()
    for _ in range(trong_xe.LAN_DO_NHIEU):
        trong_xe.kiem_mot_lan()
    tx["anh"], tx["vat"] = _khung(xe_con=False), []
    kq = [trong_xe.kiem_mot_lan() for _ in range(trong_xe.LAN_XAC_NHAN)]
    assert kq[-1] == "bao_dong" and tx["loa"] == [] and "BÁO ĐỘNG" in tx["gui"][-1][1]
    monkeypatch.setitem(config.data, "nhin_nha", {"trong_xe": {"bao_loa": True}})
    assert trong_xe._loa_bao_dong() == ["Loa khách"]


def test_cai_dat_luong_trong_xe(monkeypatch):
    """Chủ máy 27/09/2026: "cài đặt luồng trông xe riêng, có thể chọn main hay sub như khuôn mặt"."""
    from services.config import config
    monkeypatch.setitem(config.data, "nhin_nha", {})
    assert trong_xe.cai_dat() == {"luong": "phu", "bao_loa": False}
    monkeypatch.setitem(config.data, "nhin_nha", {"trong_xe": {"luong": "khoa", "bao_loa": True}})
    assert trong_xe.cai_dat() == {"luong": "khoa", "bao_loa": True}
    monkeypatch.setitem(config.data, "nhin_nha", {"trong_xe": {"luong": "linh tinh"}})
    assert trong_xe.cai_dat()["luong"] == "phu"


def test_tool_trong_xe_gui_ve_dung_chat(tx, monkeypatch):
    from services.agent import capabilities as caps
    from services.agent import reminders as rem
    monkeypatch.setattr(rem, "_capture_delivery_ctx", lambda kenh: {"account": "acc"})
    monkeypatch.setattr(trong_xe, "bat", lambda camera, dich="": {
        "camera": "Cam cửa", "xe": [{"nhan": "motorcycle"}], "loa": ["L"], "anh": "http://a", "_dich": dich})
    ra = caps.CAPABILITIES["trong_xe"].handler({"lenh": "bat"}, {"user_id": "zalop_nhom:u123"})
    assert "xe máy ở Cam cửa" in ra["text"] and ra["image_url"] == "http://a"
    assert caps._dich_cua_ctx({"user_id": "zalop_nhom:u123"}) == "zalop:acc:nhom"
    assert caps._CAP_GROUP["trong_xe"] == "camera"
