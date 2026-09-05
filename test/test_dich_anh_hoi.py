"""Luồng hỏi khi dịch chữ trong ảnh: 1 tiếng → hỏi đích; nhiều tiếng → chọn
phần → hỏi đích; song ngữ → hỏi 2 tiếng. Mock OCR/detect/translate, không mạng."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


def _mock(monkeypatch, *, ocr, detect):
    import services.photo_intent as phi
    import services.translate_service as ts
    monkeypatch.setattr(ts, "is_configured", lambda: True)
    monkeypatch.setattr(ts, "_chuan_ma", lambda m, codes: m)
    monkeypatch.setattr(ts, "lang_codes", lambda: {"vi", "en", "zh", "ja", "ko", "fr"})
    monkeypatch.setattr(ts, "detect", detect)
    monkeypatch.setattr(ts, "translate", lambda text, tgt, src="auto": f"[{tgt}<{src}]{text}")
    monkeypatch.setattr(phi, "analyze_photo", lambda *a, **k: ocr)
    import services.dich_anh_hoi as d
    d._phien.clear()
    return d


def test_mot_tieng_hoi_thang_dich(monkeypatch):
    d = _mock(monkeypatch, ocr="Hello world\nGood morning",
              detect=lambda t: ("en", 90.0))
    r = d.khoi_dong("u1", b"img", channel="zalop")
    assert "Dịch sang tiếng gì" in r["text"]        # 1 tiếng → không hỏi nguồn
    r2 = d.tra_loi("u1", "1")                        # 1 = tiếng Việt
    assert "[vi<" in r2["text"]
    assert d.tra_loi("u1", "gì đó") is None          # hết phiên


def test_nhieu_tieng_chon_phan_roi_dich(monkeypatch):
    def det(t):
        return ("vi", 90.0) if "xin chao" in t.lower() or "chào" in t.lower() else ("en", 90.0)
    d = _mock(monkeypatch, ocr="Hello everyone\nXin chào cả nhà", detect=det)
    r = d.khoi_dong("u2", b"img")
    assert "nhiều thứ tiếng" in r["text"]
    # chọn "Chỉ tiếng Anh" (Anh nhiều dòng? ở đây mỗi tiếng 1 dòng, thứ tự theo đếm)
    r2 = d.tra_loi("u2", "1")
    assert "Dịch sang tiếng gì" in r2["text"]
    r3 = d.tra_loi("u2", "tiếng Nhật")
    assert "[ja<" in r3["text"]


def test_toan_bo(monkeypatch):
    d = _mock(monkeypatch, ocr="Hello\nXin chào",
              detect=lambda t: ("vi", 90.0) if "chào" in t.lower() else ("en", 90.0))
    d.khoi_dong("u3", b"img")
    # 2 tiếng → menu nguồn: mục "Toàn bộ" là số 3
    r = d.tra_loi("u3", "3")
    assert "Dịch sang tiếng gì" in r["text"]
    r2 = d.tra_loi("u3", "2")     # sang tiếng Anh
    assert "[en<" in r2["text"]


def test_song_ngu_hoi_hai_tieng(monkeypatch):
    d = _mock(monkeypatch, ocr="こんにちは", detect=lambda t: ("ja", 95.0))
    d.khoi_dong("u4", b"img")     # 1 tiếng (Nhật) → menu dịch
    r = d.tra_loi("u4", "6")      # 6 = Song ngữ
    assert "HAI tiếng" in r["text"]
    r2 = d.tra_loi("u4", "Việt và Anh")
    assert "【Tiếng Việt】" in r2["text"] and "【Tiếng Anh】" in r2["text"]
    assert "[vi<" in r2["text"] and "[en<" in r2["text"]


def test_song_ngu_thieu_tieng_hoi_lai(monkeypatch):
    d = _mock(monkeypatch, ocr="test", detect=lambda t: ("en", 90.0))
    d.khoi_dong("u5", b"img")
    d.tra_loi("u5", "6")
    r = d.tra_loi("u5", "Việt")        # mới 1 tiếng
    assert "ĐỦ HAI" in r["text"]


def test_khong_co_chu(monkeypatch):
    d = _mock(monkeypatch, ocr="KHONGCOCHU", detect=lambda t: ("", 0.0))
    r = d.khoi_dong("u6", b"img")
    assert "không thấy chữ" in r["text"].lower()
