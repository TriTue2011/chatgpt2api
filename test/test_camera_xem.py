"""Xem trực tiếp trong khung bộ đàm web: c2a đổi luồng camera thành MJPEG cho thẻ <img>."""
import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from api import camera as api_cam  # noqa: E402


def test_cat_jpeg_tach_anh_tron_giu_phan_do():
    a1 = b"\xff\xd8" + b"\x01\xff\x00\x02" + b"\xff\xd9"
    a2 = b"\xff\xd8" + b"\x03" + b"\xff\xd9"
    anh, du = api_cam.cat_jpeg(b"rac" + a1 + a2 + b"\xff\xd8\x04")
    assert anh == [a1, a2] and du == b"\xff\xd8\x04"
    anh, du = api_cam.cat_jpeg(du + b"\xff\xd9")
    assert anh == [b"\xff\xd8\x04\xff\xd9"] and du == b""


def test_lenh_mjpeg_doc_rtsp_tcp_ra_jpeg_lien_tuc():
    lenh = api_cam.lenh_mjpeg("rtsp://10.0.0.9:8554/cua-sub")
    assert lenh[lenh.index("-rtsp_transport") + 1] == "tcp"
    assert lenh[lenh.index("-i") + 1] == "rtsp://10.0.0.9:8554/cua-sub"
    assert lenh[-4:] == ["image2pipe", "-c:v", "mjpeg", "pipe:1"] or lenh[-5:-1] == ["-f", "image2pipe", "-c:v", "mjpeg"]
    assert "-an" in lenh
