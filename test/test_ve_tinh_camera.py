"""Trợ lý giọng nói qua camera (24/09 → 28/09/2026).

Đóng vai HA đúng như ``homeassistant/components/wyoming/assist_satellite.py``
(HA 2026.9): describe → info có ``satellite``; run-satellite → vệ tinh xin
pipeline; ping → pong; tiếng TTS/announce → phát ra loa rồi báo played.

Công tắc ``tro_ly_che_do`` (tat / ha / c2a) quyết định AI NGHE MIC — đúng một đường.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import struct
import wave
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import loa_camera  # noqa: E402
from services import ve_tinh_camera as vt  # noqa: E402

TEN = "Cam cửa"
IM = b"\x00\x00" * 1024                          # 64 ms im lặng
TO = struct.pack("<h", 3000) * 1024               # 64 ms tiếng to


class LoaGia:
    ds: list["LoaGia"] = []

    def __init__(self, ten, rate, width=2, channels=1):
        self.ten, self.rate, self.nhan, self.da_xong = ten, rate, b"", False
        LoaGia.ds.append(self)

    def them(self, pcm):
        self.nhan += pcm

    def xong(self, cho=0):
        self.da_xong = True
        return 1.0


class BoNgheGia:
    """Bắt được từ gọi ở khúc thứ ``bat_o`` (đếm từ 1)."""

    def __init__(self, bat_o=1):
        self.tu_goi, self.diem_cao, self.bat_o, self.dem, self.quen = "tro_ly", 0.0, bat_o, 0, 0

    def them(self, pcm):
        self.dem += 1
        self.diem_cao = 0.9
        return self.dem == self.bat_o

    def dat_lai(self):
        self.quen += 1


async def _gui(w, loai, data=None, payload=b""):
    d = json.dumps(data or {}).encode()
    h = {"type": loai, "data_length": len(d)}
    if payload:
        h["payload_length"] = len(payload)
    w.write(json.dumps(h).encode() + b"\n" + d + payload)
    await w.drain()


async def _doc(r, cho=2.0):
    h = json.loads(await asyncio.wait_for(r.readline(), cho))
    data = json.loads(await r.readexactly(h["data_length"])) if h.get("data_length") else {}
    p = await r.readexactly(h["payload_length"]) if h.get("payload_length") else b""
    return h["type"], data, p


def _tai(cam: dict) -> vt._Tai:
    """Tai không mở ffmpeg — test tự đẩy khúc mic bằng ``nhan_khuc``."""
    tai = vt._Tai(TEN)
    tai.cam = cam
    vt._tai[TEN] = tai
    return tai


async def _mo_ha():
    async def ket_noi(r, w):
        await vt._VeTinh(TEN, r, w).chay()

    server = await asyncio.start_server(ket_noi, "127.0.0.1", 0)
    r, w = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
    return server, r, w


@pytest.fixture(autouse=True)
def _sach():
    vt._tai.clear()
    vt._ket_noi.clear()
    LoaGia.ds.clear()
    yield
    vt._tai.clear()
    vt._ket_noi.clear()


# ── Chế độ và cổng ─────────────────────────────────────────────────────────

def test_che_do_ban_ghi_cu_va_moi():
    assert vt.che_do({}) == "tat"
    assert vt.che_do({"cho_nghe": "true"}) == "tat"            # chỉ đúng True mới tính
    assert vt.che_do({"cho_nghe": True, "ve_tinh_cong": 10801}) == "ha"
    assert vt.che_do({"cho_nghe": True, "tro_ly_che_do": "tat"}) == "tat"   # trường mới thắng
    assert vt.che_do({"tro_ly_che_do": "c2a"}) == "c2a"
    assert vt.che_do({"tro_ly_che_do": "la"}) == "tat"


def test_c2a_tu_tra_loi_luon_co_tu_goi():
    assert vt.tu_goi({"tro_ly_che_do": "c2a"}) == "tro_ly"
    assert vt.tu_goi({"tro_ly_che_do": "ha"}) == ""             # HA bắt
    assert vt.tu_goi({"tro_ly_che_do": "ha", "tu_goi": "hey_jarvis"}) == "hey_jarvis"


def test_cong_ve_tinh_mo_o_moi_che_do_de_ha_con_phat_thong_bao():
    """Đo 28/09/2026: HA dùng vệ tinh «Camera Cam bếp» để phát loa trong khi nghe tắt."""
    from services import camera_nha
    with mock.patch.object(camera_nha, "danh_sach", return_value=[
            {"name": "Cam cửa", "ve_tinh_cong": 10801},
            {"name": "Cam bếp", "ve_tinh_cong": "10803", "tro_ly_che_do": "c2a"},
            {"name": "Cam sân"}, {"name": "Cam hỏng", "ve_tinh_cong": "abc"}]):
        assert vt.ds_cong() == {10801: "Cam cửa", 10803: "Cam bếp"}


def test_cho_nghe_mac_dinh_tat():
    """Chủ máy 24/09/2026: tránh người ngoài cửa ra lệnh cho nhà — không khai là KHÔNG nghe."""
    from services import camera_nha
    for cam, muon in (({}, False), ({"cho_nghe": False}, False), ({"cho_nghe": True}, True),
                      ({"tro_ly_che_do": "c2a"}, True)):
        with mock.patch.object(camera_nha, "_lay", return_value=(TEN, cam)):
            assert vt.cho_nghe(TEN) is muon


# ── Qua Home Assistant ─────────────────────────────────────────────────────

async def _kich_ban_ha_bat():
    """HA tự bắt từ gọi: mic gửi liên tục; HA báo detection → ting; TTS → loa → played."""
    tai = _tai({"tro_ly_che_do": "ha", "ve_tinh_cong": 10801})
    ting = []
    with mock.patch.object(loa_camera, "PhatLuong", LoaGia), \
            mock.patch.object(loa_camera, "phat", lambda ten, wav: ting.append(ten)):
        server, r, w = await _mo_ha()
        ra = []
        await _gui(w, "describe")
        ra.append(await _doc(r))
        await _gui(w, "run-satellite")
        ra.append(await _doc(r))
        await tai.nhan_khuc(TO)
        await tai.nhan_khuc(TO)
        ra += [await _doc(r), await _doc(r)]
        await _gui(w, "ping", {"text": "x"})
        ra.append(await _doc(r))
        await _gui(w, "detection", {"name": "okay_nabu"})
        await asyncio.sleep(0.1)
        await _gui(w, "audio-start", {"rate": 22050, "width": 2, "channels": 1})
        await _gui(w, "audio-chunk", {"rate": 22050, "width": 2, "channels": 1}, b"\x02\x00" * 100)
        await asyncio.sleep(0.05)
        await tai.nhan_khuc(TO)                    # loa đang nói: mic bỏ tiếng, không gửi HA
        await _gui(w, "audio-stop")
        ra.append(await _doc(r))
        w.close()
        server.close()
        return ra, ting


def test_ha_bat_tu_goi_tu_dau_den_cuoi():
    ra, ting = asyncio.run(_kich_ban_ha_bat())
    assert [x[0] for x in ra] == ["info", "run-pipeline", "audio-chunk", "audio-chunk", "pong", "played"]
    assert ra[0][1]["satellite"]["name"] == "Camera Cam cửa"
    assert ra[1][1] == {"start_stage": "wake", "end_stage": "tts", "restart_on_end": True}
    assert ra[2][1]["rate"] == 16000 and len(ra[2][2]) == 2048
    assert ra[4][1] == {"text": "x"}
    assert ting == [TEN]
    loa = LoaGia.ds[0]
    assert (loa.ten, loa.rate, loa.nhan, loa.da_xong) == (TEN, 22050, b"\x02\x00" * 100, True)


async def _kich_ban_c2a_bat_cho_ha():
    """c2a bắt từ gọi (như loa R1): ting → detection → run-pipeline từ bước NGHE → mic tới khi HA
    trả chữ → audio-stop. Tiếng trước lúc gọi KHÔNG tới HA."""
    tai = _tai({"tro_ly_che_do": "ha", "ve_tinh_cong": 10801, "tu_goi": "tro_ly"})
    tai.bo_nghe = BoNgheGia(bat_o=2)
    ting = []
    with mock.patch.object(loa_camera, "phat", lambda ten, wav: ting.append(wav)), \
            mock.patch.object(vt, "_DEM_SAU_NOI", 0.0):
        server, r, w = await _mo_ha()
        await _gui(w, "run-satellite")
        try:
            await _doc(r, 0.2)
            im_truoc = False
        except TimeoutError:
            im_truoc = True
        await tai.nhan_khuc(TO)                    # chưa gọi — không gửi
        await tai.nhan_khuc(TO)                    # từ gọi
        ra = [await _doc(r), await _doc(r)]
        await asyncio.sleep(0.05)
        await tai.nhan_khuc(TO)
        await tai.nhan_khuc(TO)
        ra += [await _doc(r), await _doc(r)]
        await _gui(w, "transcript", {"text": "bật đèn"})
        ra.append(await _doc(r))
        w.close()
        server.close()
        return im_truoc, ra, ting


def test_c2a_bat_tu_goi_roi_xin_ha_tu_buoc_nghe():
    im_truoc, ra, ting = asyncio.run(_kich_ban_c2a_bat_cho_ha())
    assert im_truoc
    assert [x[0] for x in ra] == ["detection", "run-pipeline", "audio-chunk", "audio-chunk", "audio-stop"]
    assert ra[0][1]["name"] == "tro_ly"
    assert ra[1][1] == {"start_stage": "asr", "end_stage": "tts", "restart_on_end": False}
    assert len(ting) == 1 and ting[0][:4] == b"RIFF"


async def _kich_ban_cong_tac():
    """HA đòi nghe khi công tắc TẮT: không mic; bật «Qua HA» thì tự nghe."""
    cam = {"ve_tinh_cong": 10801}
    tai = _tai(cam)
    server, r, w = await _mo_ha()
    await _gui(w, "run-satellite")
    await tai.nhan_khuc(TO)
    try:
        await _doc(r, 0.3)
        im_lang = False
    except TimeoutError:
        im_lang = True
    cam["tro_ly_che_do"] = "ha"
    await vt._ghep_ha(TEN)
    await tai.nhan_khuc(TO)
    sau = [(await _doc(r))[0] for _ in range(2)]
    cam["tro_ly_che_do"] = "c2a"                    # đổi sang c2a: HA thôi nhận mic
    await vt._ghep_ha(TEN)
    await tai.nhan_khuc(TO)
    try:
        await _doc(r, 0.3)
        im_sau = False
    except TimeoutError:
        im_sau = True
    w.close()
    server.close()
    return im_lang, sau, im_sau


def test_cong_tac_quyet_ai_nghe_mic():
    im_lang, sau, im_sau = asyncio.run(_kich_ban_cong_tac())
    assert im_lang
    assert sau == ["run-pipeline", "audio-chunk"]
    assert im_sau


async def _kich_ban_phat_qua_han():
    tai = _tai({"tro_ly_che_do": "ha", "ve_tinh_cong": 10801})
    with mock.patch.object(loa_camera, "PhatLuong", LoaGia), \
            mock.patch.object(vt, "_PHAT_IM_TOI_DA", 0.2):
        server, r, w = await _mo_ha()
        await _gui(w, "audio-start", {"rate": 22050, "width": 2, "channels": 1})
        await _gui(w, "audio-chunk", {"rate": 22050, "width": 2, "channels": 1}, b"\x02\x00" * 10)
        ra = await _doc(r, 2.0)                    # HA không gửi audio-stop
        w.close()
        server.close()
        return ra, tai._dang_noi


def test_ha_quen_audio_stop_van_bao_played():
    """dahua_talk 0.2.9: không có played thì HA kẹt «Đang phản hồi» mãi."""
    ra, dang_noi = asyncio.run(_kich_ban_phat_qua_han())
    assert ra[0] == "played"
    assert LoaGia.ds[0].da_xong and not dang_noi


# ── c2a tự nghe, tự trả lời ────────────────────────────────────────────────

async def _kich_ban_tu_tra_loi():
    tai = _tai({"tro_ly_che_do": "c2a"})
    tai.bo_nghe = BoNgheGia(bat_o=3)
    noi, nghe = [], []

    def listen(wav, hint, **kw):
        with wave.open(io.BytesIO(wav)) as f:
            nghe.append((f.getframerate(), f.getnframes()))
        return " bật đèn bếp "

    with mock.patch.object(loa_camera, "phat", lambda ten, wav: None), \
            mock.patch.object(loa_camera, "noi", lambda ten, cau: noi.append((ten, cau))), \
            mock.patch("services.voice.listen", listen), \
            mock.patch("services.voice.vad_silero.doan_co_tieng", return_value=None), \
            mock.patch.object(vt, "_hoi_tac_tu", lambda ten, chu: f"Đã nghe: {chu}"), \
            mock.patch.object(vt, "_DEM_SAU_NOI", 0.0), \
            mock.patch.object(vt, "_XET_GIAY", 0.0):
        await tai.nhan_khuc(IM)                    # phòng yên
        await tai.nhan_khuc(TO)
        await tai.nhan_khuc(TO)                    # từ gọi — to, nhưng không được đẩy nền lên
        for _ in range(250):                       # chờ ting xong, lượt bắt đầu ghi
            if tai._nhan is not None:
                break
            await asyncio.sleep(0.02)
        for k in [TO] * 10 + [IM] * 20:            # nói 0,64 s rồi im 1,28 s
            await tai.nhan_khuc(k)
            await asyncio.sleep(0.005)
        for _ in range(100):
            if noi:
                break
            await asyncio.sleep(0.02)
        return noi, nghe, tai


def test_c2a_tu_nghe_tu_tra_loi_ra_loa_camera():
    noi, nghe, tai = asyncio.run(_kich_ban_tu_tra_loi())
    assert noi == [(TEN, "Đã nghe: bật đèn bếp")]
    rate, n = nghe[0]
    assert rate == 16000 and n <= 30 * 1024        # dừng ghi khi người nói dứt, không ghi tới 10 s
    assert tai.nghe_duoc == "bật đèn bếp" and not tai._dang_luot


def test_trang_thai_noi_theo_do_to_khi_chua_co_vad():
    with mock.patch("services.voice.vad_silero.doan_co_tieng", return_value=None):
        assert vt.trang_thai_noi(IM * 10, 150) == "chua"
        assert vt.trang_thai_noi(IM * 3 + TO * 5, 150) == "dang"
        assert vt.trang_thai_noi(TO * 5 + IM * 20, 150) == "xong"


def test_trang_thai_noi_theo_vad():
    with mock.patch("services.voice.vad_silero.doan_co_tieng", return_value=[(0.1, 0.5)]):
        assert vt.trang_thai_noi(IM * 24, 150) == "xong"      # 1,54 s; im từ 0,5 s
    with mock.patch("services.voice.vad_silero.doan_co_tieng", return_value=[]):
        assert vt.trang_thai_noi(TO * 16, 150) == "chua"      # to mà không phải tiếng nói


def test_mic_bo_tieng_luc_ting_va_quen_tieng_cu_sau_khi_noi():
    async def chay():
        tai = _tai({"tro_ly_che_do": "c2a"})
        tai.bo_nghe = BoNgheGia(bat_o=99)
        tai.chan(10)
        await tai.nhan_khuc(TO)
        truoc = tai.bo_nghe.dem
        tai._chan_toi = 0
        tai.bat_dau_noi()
        await tai.nhan_khuc(TO)
        with mock.patch.object(vt, "_DEM_SAU_NOI", 0.0):
            tai.het_noi()
        await tai.nhan_khuc(TO)
        return truoc, tai.bo_nghe.dem, tai.bo_nghe.quen

    truoc, dem, quen = asyncio.run(chay())
    assert (truoc, dem, quen) == (0, 1, 1)


# ── Mic, ting, lệnh ffmpeg ─────────────────────────────────────────────────

def test_mic_dung_im_thi_mo_lai():
    """ffmpeg treo mà không đóng (camera rớt mạng) — dahua_talk: "idle hàng giờ không ai biết"."""
    from services import camera_nha

    dem = []

    def lenh(cam):
        dem.append(1)
        return ["sleep", "5"]

    async def chay():
        tai = _tai({})
        task = asyncio.create_task(tai._doc_mic())
        await asyncio.sleep(0.8)
        task.cancel()

    with mock.patch.object(camera_nha, "_lay", return_value=(TEN, {})), \
            mock.patch.object(vt, "_lenh_mic", lenh), \
            mock.patch.object(vt, "_MIC_IM_GIAY", 0.2), \
            mock.patch.object(vt, "_MO_LAI_GIAY", 0.05):
        asyncio.run(chay())
    assert len(dem) >= 2


def test_tieng_ting_ngan_va_dung_dinh_dang():
    with wave.open(io.BytesIO(vt.tieng_ting())) as f:
        assert (f.getnchannels(), f.getsampwidth(), f.getframerate()) == (1, 2, 16000)
        assert 0.25 <= f.getnframes() / 16000 <= 0.35


def test_lenh_mic_ma_hoa_mat_khau_trong_url():
    lenh = vt._lenh_mic({"base": "http://172.16.10.200:1984/", "src": "cua", "src_ai": "cua-sub",
                         "username": "u", "password": "m@t:1"})
    url = lenh[lenh.index("-i") + 1]
    assert url == "http://u:m%40t%3A1@172.16.10.200:1984/api/stream.mp4?src=cua-sub&video=none&audio=all"
    assert lenh[-7:] == ["-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]


def test_loa_tat_thi_tu_choi_phat():
    from services import camera_nha
    with mock.patch.object(camera_nha, "_lay", return_value=(TEN, {"cho_loa": False})):
        with pytest.raises(loa_camera.LoiLoa, match="đang tắt"):
            loa_camera.phat(TEN, b"")
        with pytest.raises(loa_camera.LoiLoa, match="đang tắt"):
            loa_camera.PhatLuong(TEN, 22050)


def test_tang_mic_them_bo_loc_va_chan_dinh():
    """Mic camera nhỏ; ô Mic volume của HA 2026.9 không áp vào vệ tinh Wyoming."""
    goc = {"base": "http://h:1984", "src": "cua"}
    lenh = vt._lenh_mic(goc)
    assert lenh[lenh.index("-af") + 1] == "highpass=f=80"          # luôn bỏ DC
    lenh = vt._lenh_mic({**goc, "mic_tang_db": 12})
    assert lenh[lenh.index("-af") + 1].startswith("highpass=f=80,volume=12dB,alimiter=limit=0.9")
    assert vt.mic_tang_db({"mic_tang_db": 99}) == 30.0 and vt.mic_tang_db({"mic_tang_db": "x"}) == 0.0


# ── Từ gọi thật (thư viện chỉ có trong ảnh Docker) ─────────────────────────

def test_bo_nghe_that_im_lang_khong_day():
    pytest.importorskip("pyopen_wakeword")
    from services import tu_goi

    assert "tro_ly" in tu_goi.cac_tu_goi() and "okay_nabu" in tu_goi.cac_tu_goi()
    bo = tu_goi.BoNghe("tro_ly", "cao")
    assert not any(bo.them(IM) for _ in range(40))
    with pytest.raises(ValueError):
        tu_goi.BoNghe("khong_co")
    assert (tu_goi.nguong("thap"), tu_goi.nguong("la")) == (0.9, 0.7)


def test_tu_goi_khong_phai_tieng_nguoi_thi_bo():
    """Đo 28/09/2026: 12/21 lần mô hình từ gọi vượt ngưỡng trên mic thật là tiếng ồn (VAD rỗng)."""
    async def chay(vad):
        tai = _tai({"tro_ly_che_do": "c2a"})
        tai.bo_nghe = BoNgheGia(bat_o=1)
        bat = []

        async def bd():
            bat.append(1)

        tai._bat_duoc = bd
        with mock.patch("services.voice.vad_silero.doan_co_tieng", return_value=vad):
            await tai.nhan_khuc(TO)
        await asyncio.sleep(0.01)                      # lượt chạy bằng create_task
        return len(bat)

    assert asyncio.run(chay([])) == 0                  # VAD không thấy tiếng người
    assert asyncio.run(chay([(0.2, 1.0)])) == 1
    assert asyncio.run(chay(None)) == 1                # chưa có model VAD: tin mô hình từ gọi


def test_lenh_mic_camera_rtsp_doc_thang_luong_phu():
    """Camera khai kiểu RTSP (vd EZVIZ không qua go2rtc): mic đọc thẳng URL, luồng phụ nếu có."""
    lenh = vt._lenh_mic({"kind": "rtsp", "url": "rtsp://a:b@10.0.0.9:554/Streaming/Channels/101",
                         "url_ai": "rtsp://a:b@10.0.0.9:554/Streaming/Channels/102"})
    i = lenh.index("-i")
    assert lenh[i - 2:i] == ["-rtsp_transport", "tcp"]
    assert lenh[i + 1].endswith("/Channels/102")
