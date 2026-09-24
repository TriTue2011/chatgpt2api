"""Bộ đàm: mic điện thoại (thẻ WebRTC Camera → go2rtc) → loa camera (24/09/2026).

Chủ máy: "dùng mic điện thoại qua HA phát ra loa giữ nguyên gốc, rồi nghe được
người bên cam nói gì — giống như app Imou". go2rtc đẩy A-law 8 kHz qua một lệnh
``exec:…#backchannel=1``; lệnh ấy POST luồng tới c2a.

Hai điều phải giữ:

* Kênh nói chỉ mở khi có tiếng người và đóng sau một quãng im — camera tắt mic
  của nó suốt lúc kênh nói mở, mà trình duyệt gửi tiếng liên tục.
* Đường POST không có Bearer: chỉ chữ ký đúng camera, đúng phương thức mới qua.
"""
from __future__ import annotations

import bisect
import math
import os
import shutil
import struct
import subprocess
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import loa_camera as lc  # noqa: E402


def _alaw(pcm: bytes) -> bytes:
    """Mã hoá A-law bằng ffmpeg — bộ mã độc lập với bộ giải đang thử."""
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le",
                           "-ar", "8000", "-ac", "1", "-i", "pipe:0", "-f", "alaw", "pipe:1"],
                          input=pcm, capture_output=True, check=True).stdout


def _song(giay: float, db: float, tan_so: float = 440.0) -> bytes:
    bien = 32767 * 10 ** (db / 20) * math.sqrt(2)
    n = int(giay * 8000)
    return struct.pack(f"<{n}h", *(int(bien * math.sin(2 * math.pi * tan_so * i / 8000))
                                   for i in range(n)))


def _im(giay: float) -> bytes:
    return b"\x00" * (int(giay * 8000) * 2)


class PhatGia:
    mo: list["PhatGia"] = []

    def __init__(self, ten: str, rate: int, *a) -> None:
        self.ten, self.rate, self.pcm, self.dong = ten, rate, b"", False
        PhatGia.mo.append(self)

    def them(self, pcm: bytes) -> None:
        assert not self.dong
        self.pcm += pcm

    def xong(self, *a) -> float:
        self.dong = True
        return len(self.pcm) / (2 * self.rate)


@pytest.fixture
def phat_gia():
    PhatGia.mo = []
    with mock.patch.object(lc, "PhatLuong", PhatGia):
        yield PhatGia.mo


def _gui(phien: lc.BoDam, pcm: bytes, khuc_giay: float = 0.02) -> None:
    """Gửi như go2rtc: từng gói RTP 20 ms."""
    b = int(khuc_giay * 16000)
    for i in range(0, len(pcm), b):
        phien.them(_ma_hoa(pcm[i:i + b]))


def _ma_hoa(pcm: bytes) -> bytes:
    """A-law bằng tra ngược bảng giải (đủ chính xác cho đo mức; test riêng so ffmpeg)."""
    goc = sorted(range(256), key=lambda a: lc._ALAW[a])
    gia_tri = [lc._ALAW[a] for a in goc]
    ra = bytearray()
    for (x,) in struct.iter_unpack("<h", pcm):
        i = min(bisect.bisect_left(gia_tri, x), 255)
        if i > 0 and abs(gia_tri[i - 1] - x) <= abs(gia_tri[i] - x):
            i -= 1
        ra.append(goc[i])
    return bytes(ra)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")
def test_giai_alaw_khop_ffmpeg() -> None:
    ma = bytes(range(256))
    ffmpeg = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "alaw",
                             "-ar", "8000", "-ac", "1", "-i", "pipe:0", "-f", "s16le", "pipe:1"],
                            input=ma, capture_output=True, check=True).stdout
    assert lc.alaw_sang_pcm(ma) == ffmpeg


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")
def test_ma_hoa_trong_test_khop_ffmpeg() -> None:
    pcm = _song(0.1, -20)
    assert lc.alaw_sang_pcm(_ma_hoa(pcm)) == lc.alaw_sang_pcm(_alaw(pcm))


def test_im_lang_khong_mo_loa(phat_gia) -> None:
    """Mic tắt trong trình duyệt (số 0) và phòng yên: camera vẫn nghe được."""
    p = lc.BoDam("cửa")
    _gui(p, _im(3) + _song(2, -60))
    p.dong()
    assert phat_gia == []


def test_co_tieng_mo_loa_giu_dau_cau_roi_dong_khi_im(phat_gia) -> None:
    p = lc.BoDam("cửa")
    _gui(p, _im(1) + _song(1, -20))
    assert len(phat_gia) == 1 and not phat_gia[0].dong
    # Giữ 0,3 s ngay trước tiếng: âm đầu câu không mất.
    assert len(phat_gia[0].pcm) >= int((1 + lc.BO_DAM_DEM_GIAY - 0.03) * 16000)
    _gui(p, _im(lc.BO_DAM_IM_GIAY + 0.1))
    assert phat_gia[0].dong, "im đủ lâu mà kênh nói còn mở → không nghe được bên kia"
    # Câu sau mở phiên mới.
    _gui(p, _song(0.5, -20))
    assert len(phat_gia) == 2
    p.dong()
    assert phat_gia[1].dong
    assert p.giay > 1.5


def test_ngat_quang_ngan_giua_cau_khong_dong(phat_gia) -> None:
    p = lc.BoDam("cửa")
    _gui(p, _song(1, -25) + _im(0.6) + _song(1, -25))
    p.dong()
    assert len(phat_gia) == 1


def test_giu_nguyen_tieng_goc(phat_gia) -> None:
    """Không lọc, không đổi mức: tiếng ra loa đúng tiếng người nói."""
    tieng = _song(0.5, -12, 700)
    p = lc.BoDam("cửa")
    _gui(p, tieng)
    p.dong()
    ra = phat_gia[0].pcm
    assert ra == lc.alaw_sang_pcm(_ma_hoa(tieng))


def test_loa_tat_thi_bo_qua_khong_do_loi(phat_gia) -> None:
    loi = lc.LoiLoa("Loa của camera «cửa» đang tắt")
    with mock.patch.object(lc, "PhatLuong", side_effect=loi) as mo, \
            mock.patch.object(lc.logger, "warning") as canh_bao:
        p = lc.BoDam("cửa")
        _gui(p, _song(1, -20))
        p.dong()
    assert mo.call_count > 1          # mỗi khúc có tiếng thử lại (công tắc bật lại là nói được)
    assert canh_bao.call_count == 1   # nhưng chỉ ghi log một lần


# ── Route ────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import camera as api_camera

    app = FastAPI()
    app.include_router(api_camera.create_router())
    with mock.patch("api.camera.require_admin", lambda *a, **k: None), \
            mock.patch("services.camera_nha._lay", lambda ten: ("Cam cửa", {})):
        yield TestClient(app)


def _url_trong(nguon: str) -> str:
    return next(t for t in nguon.split("#")[0].split() if t.startswith("http"))


def test_dong_go2rtc_dung_cu_phap(client) -> None:
    d = client.get("/api/camera/bo_dam/Cam cửa/go2rtc",
                   params={"goc": "http://172.16.10.38:3030/"}).json()
    assert d["ok"], d
    nguon = d["nguon"]
    assert nguon.startswith("exec:ffmpeg ")
    assert nguon.endswith("#backchannel=1#audio=alaw/8000")
    url = _url_trong(nguon)
    # go2rtc tách lệnh theo dấu cách và tham số theo '#': URL không được chứa cả hai.
    assert url.startswith("http://172.16.10.38:3030/api/camera/bo_dam/Cam%20c")
    assert " " not in url and "#" not in url


def test_post_dung_chu_ky_thi_phat(client, phat_gia) -> None:
    url = _url_trong(client.get("/api/camera/bo_dam/Cam cửa/go2rtc",
                                params={"goc": "http://testserver"}).json()["nguon"])
    duong = url.removeprefix("http://testserver")
    r = client.post(duong, content=_ma_hoa(_song(1, -20)))
    assert r.status_code == 200, r.text
    assert r.json()["giay"] > 0.9
    assert len(phat_gia) == 1 and phat_gia[0].ten == "Cam cửa" and phat_gia[0].dong
    assert phat_gia[0].rate == 8000           # go2rtc gửi A-law 8 kHz


def test_post_sai_chu_ky_hay_sai_camera_bi_chan(client, phat_gia) -> None:
    url = _url_trong(client.get("/api/camera/bo_dam/Cam cửa/go2rtc",
                                params={"goc": "http://testserver"}).json()["nguon"])
    duong = url.removeprefix("http://testserver")
    tieng = _ma_hoa(_song(0.5, -20))
    assert client.post("/api/camera/bo_dam/Cam cửa", content=tieng).status_code == 403
    assert client.post(duong.replace("sig=", "sig=0"), content=tieng).status_code == 403
    # Chữ ký của Cam cửa không dùng được cho camera khác.
    khac = duong.replace("Cam%20c%E1%BB%ADa", "Cam%20b%E1%BA%BFp")
    assert khac != duong
    assert client.post(khac, content=tieng).status_code == 403
    assert phat_gia == []


# ── Bộ đàm trong web c2a (WebSocket) ─────────────────────────────────────────

@pytest.fixture
def client_ws(phat_gia):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import camera as api_camera

    app = FastAPI()
    app.include_router(api_camera.create_router())
    # Mic camera giả: một lệnh in ra đúng 4096 byte rồi đứng chờ.
    mic = ["sh", "-c", "head -c 4096 /dev/zero | tr '\\0' 'A'; sleep 30"]
    with mock.patch("api.camera.require_admin", lambda *a, **k: {"id": "admin"}), \
            mock.patch("services.camera_nha._lay", lambda ten: (ten, {})), \
            mock.patch("services.ve_tinh_camera._lenh_mic", lambda cam: mic):
        yield TestClient(app)


def _ve(c, ten: str) -> str:
    return c.post(f"/api/camera/bo_dam/{ten}/ve").json()["ticket"]


def test_ws_nghe_camera_va_noi_ra_loa(client_ws, phat_gia) -> None:
    with client_ws.websocket_connect(f"/api/camera/bo_dam/cửa/ws?ve={_ve(client_ws, 'cửa')}") as ws:
        nghe = ws.receive_bytes()
        assert nghe == b"A" * 2048            # tiếng mic camera tới trình duyệt
        ws.send_bytes(struct.pack("<8000h", *[8000] * 8000))   # 0,5 s tiếng to (16 kHz)
        ws.send_text("het")                   # thả nút: đóng kênh nói ngay
        # Máy chủ xử lý bất đồng bộ: chờ tới khi kênh nói đóng (không cần im 1,5 s).
        import time
        het_han = time.monotonic() + 5
        while not (phat_gia and phat_gia[0].dong) and time.monotonic() < het_han:
            time.sleep(0.02)
    assert len(phat_gia) == 1 and phat_gia[0].dong
    assert len(phat_gia[0].pcm) == 16000
    assert phat_gia[0].rate == 16000          # trình duyệt gửi PCM 16 kHz


def test_ws_ve_sai_hay_ve_camera_khac_bi_tu_choi(client_ws) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as e:
        with client_ws.websocket_connect("/api/camera/bo_dam/cửa/ws?ve=bay") as ws:
            ws.receive_bytes()
    assert e.value.code == 4401
    ve_bep = _ve(client_ws, "bếp")
    with pytest.raises(WebSocketDisconnect):
        with client_ws.websocket_connect(f"/api/camera/bo_dam/cửa/ws?ve={ve_bep}") as ws:
            ws.receive_bytes()


def test_ws_ve_chi_dung_mot_lan(client_ws) -> None:
    from starlette.websockets import WebSocketDisconnect

    ve = _ve(client_ws, "cửa")
    with client_ws.websocket_connect(f"/api/camera/bo_dam/cửa/ws?ve={ve}") as ws:
        ws.receive_bytes()
    with pytest.raises(WebSocketDisconnect):
        with client_ws.websocket_connect(f"/api/camera/bo_dam/cửa/ws?ve={ve}") as ws:
            ws.receive_bytes()


# ── Trực tiếp thật, không thu hết rồi mới phát ───────────────────────────────
#
# Chủ máy 24/09/2026: "không live à, phải thu rồi phát thì không đúng yêu cầu".
# Đo trong c2a: ffmpeg đọc ống dẫn KHÔNG có cờ tắt dò định dạng thì 2,5 giây
# tiếng vào mà 0 byte ra. Test chạy ffmpeg thật và đòi tiếng ra khi đầu vào VẪN MỞ.

def _ra_truoc_khi_dong(lenh: list[str], khuc: bytes, so_khuc: int = 8) -> int:
    import threading
    import time

    p = subprocess.Popen(lenh, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    ra = []
    threading.Thread(target=lambda: ra.extend(iter(lambda: p.stdout.read1(65536), b"")),
                     daemon=True).start()
    try:
        for _ in range(so_khuc):
            p.stdin.write(khuc)
            p.stdin.flush()
            time.sleep(0.128)
        time.sleep(0.3)
        return sum(len(b) for b in ra)          # đo khi stdin CHƯA đóng
    finally:
        p.kill()
        p.wait()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")
def test_phat_luong_nha_tieng_ngay_khong_doi_het() -> None:
    khuc = struct.pack("<2048h", *([3000, -3000] * 1024))   # 128 ms PCM 16 kHz như trình duyệt
    ra = _ra_truoc_khi_dong(lc.lenh_doi_luong(16000), khuc)
    # 8 khúc × 128 ms = 1,024 s → 16 KB ở 8 kHz; cho phép thiếu một khúc đang xử lý.
    assert ra >= 7 * 2048, f"chỉ {ra} byte ra trong lúc đang nói — đang gom rồi mới phát"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg")
def test_dong_go2rtc_nha_tieng_ngay(client) -> None:
    nguon = client.get("/api/camera/bo_dam/Cam cửa/go2rtc",
                       params={"goc": "http://h"}).json()["nguon"]
    lenh = nguon.removeprefix("exec:").split("#")[0].split()
    lenh = lenh[: lenh.index("-method")] + ["pipe:1"]    # ghi ra ống thay vì POST
    khuc = _ma_hoa(struct.pack("<1024h", *([3000, -3000] * 512)))   # 128 ms A-law 8 kHz
    ra = _ra_truoc_khi_dong(lenh, khuc)
    assert ra >= 7 * 1024, f"chỉ {ra} byte ra trong lúc đang nói — đang gom rồi mới gửi"


def test_bo_dam_do_tieng_nhan_duoc_de_chan_doan(phat_gia) -> None:
    """Chủ máy 25/09/2026 "bật bộ đàm rồi không được": log phải nói được tiếng
    có tới máy chủ không và to cỡ nào — khỏi đoán hỏng ở điện thoại hay ở loa."""
    p = lc.BoDam("cửa", 16000)
    p.them_pcm(b"\x00" * 16000)                               # 0,5 s im ở 16 kHz
    p.them_pcm(struct.pack("<8000h", *[3000] * 8000))          # 0,5 s tiếng -20,8 dBFS
    p.dong()
    assert p.nhan_giay == pytest.approx(1.0)
    assert -22 < p.muc_max_db < -20
    assert p.giay > 0.4
