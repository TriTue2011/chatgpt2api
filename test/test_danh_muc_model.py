"""Danh mục model cần tải — thẻ web «Model cần tải» (chủ máy 28/09/2026: "cái nào cần tải thì
hướng dẫn hết")."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services import danh_muc_model as dm  # noqa: E402

GOC = Path(__file__).resolve().parents[1]


@pytest.fixture
def gia(monkeypatch):
    from services import canh_camera_nha, nhin_nha
    from services.voice import config as v
    from services.voice import engines
    monkeypatch.setattr(v, "is_stt_enabled", lambda: True)
    monkeypatch.setattr(canh_camera_nha, "cfg", lambda: {"bat": False})
    monkeypatch.setattr(engines, "_giong_dang_gan", lambda: ["manhdung", "zerotts:maichi"])
    monkeypatch.setattr(engines, "_GIU_ASSIST", {"nghi"})
    monkeypatch.setattr(nhin_nha, "co_yolo", lambda: False)
    monkeypatch.setattr(v, "stt_model_dir", lambda: (_ for _ in ()).throw(OSError("hỏng")))
    return {x["ma"]: x for x in dm.danh_muc()}


def test_moi_muc_co_lenh_tai_script_that(gia):
    for x in gia.values():
        script = x["lenh"].split("scripts/", 1)[1].split()[0]
        assert (GOC / "scripts" / script).is_file(), x["lenh"]
        assert x["lenh"].startswith("docker exec c2a /app/.venv/bin/python scripts/")
        for t in x["them"]:
            assert (GOC / "scripts" / t["lenh"].split("scripts/", 1)[1].split()[0]).is_file()


def test_muc_do_theo_cau_hinh(gia):
    assert gia["stt_vi"]["muc_do"] == "can", "STT đang bật"
    assert gia["piper"]["muc_do"] == "can" and gia["zerotts"]["muc_do"] == "can", "giọng đang gán"
    assert gia["nghi"]["muc_do"] == "can", "giọng Home Assistant Assist đã gọi"
    assert gia["kokoro"]["muc_do"] == "tuy_chon"
    assert gia["yolo"]["muc_do"] == "tuy_chon", "camera chưa canh"


def test_kiem_hong_thi_bao_chua_co_khong_vo_trang(gia):
    assert gia["stt_vi"]["da_tai"] is False
    assert gia["yolo"]["da_tai"] is False


def test_huong_dan_co_du_moi_lenh_tai(gia):
    """HUONG_DAN mục 1.6 là bảng tay — mục mới trong danh mục mà quên ghi vào đó thì hỏng."""
    doc = (GOC / "HUONG_DAN.md").read_text(encoding="utf-8")
    for x in gia.values():
        if x["ma"] in ("yolo", "khuon_mat"):   # tên bản tuỳ cấu hình; bảng ghi bản mặc định
            continue
        for lenh in [x["lenh"], *(t["lenh"] for t in x["them"])]:
            assert lenh.split("scripts/", 1)[1] in doc, lenh


def test_moi_ban_yolo_va_bo_mat_co_lenh_tai(gia):
    from services import khuon_mat_nha, yolo_nha
    bt = {b["lenh"].split("scripts/", 1)[1] for x in gia.values() for b in x["bien_the"]}
    for m in yolo_nha.MODELS:
        assert f"download_nhin_nha.py --yolo {m.ma}" in bt
    for b in khuon_mat_nha.BO:
        assert f"download_nhin_nha.py --mat {b.ma}" in bt


def test_nut_tai_chi_chay_dung_lenh_trong_danh_muc(gia):
    import sys
    argv = dm.argv_cua(dm.LENH + "download_nhin_nha.py --yolo yolo26x")
    assert argv == [sys.executable, "scripts/download_nhin_nha.py", "--yolo", "yolo26x"]
    assert dm.argv_cua(dm.LENH + "download_piper_voices.py --pack full")[-2:] == ["--pack", "full"]
    for xau in ("download_stt_model.py; rm -r /app/data",       # ghép lệnh
                "download_nhin_nha.py --yolo yolo26n --dest /etc",  # thêm tham số
                "../../bin/sh",                                   # script lạ
                ""):
        with pytest.raises(ValueError):
            dm.argv_cua(dm.LENH + xau)
    with pytest.raises(ValueError):
        dm.argv_cua("python scripts/download_stt_model.py")      # không đúng tiền tố danh mục


def test_lenh_tai_tung_giong_va_goi():
    assert dm._script_giong("banmai") == "download_piper_voices.py --voice banmai"
    assert dm._script_giong("nghi:ban-mai") == "download_nghitts_voices.py ban-mai"
    assert dm._script_giong("kokorovi:hung_thinh") == "download_kokoro_vi.py hung_thinh"
    assert dm._script_giong("zerotts:maichi") == "download_zerotts.py"
    assert dm._script_giong("vieneu:Trúc Ly") == "download_vieneu_model.py", "gói liền — tên có dấu cách vẫn được"
    assert dm._script_giong("nghi:x; rm -r /") is None, "mã lạ ký tự không được ghép vào dòng lệnh"
    assert dm._script_giong("la:giong") is None


def test_nut_tai_nhan_lenh_giong_trong_danh_muc(gia, monkeypatch):
    from services.voice import config as v
    monkeypatch.setattr(v, "voice_catalog", lambda: [{"id": "banmai"}, {"id": "nghi:ban-mai"},
                                                     {"id": "nghi:x;y"}])
    assert dm.lenh_giong() == {"banmai": dm.LENH + "download_piper_voices.py --voice banmai",
                               "nghi:ban-mai": dm.LENH + "download_nghitts_voices.py ban-mai"}
    assert dm.argv_cua(dm.LENH + "download_nghitts_voices.py ban-mai")[-1] == "ban-mai"
    with pytest.raises(ValueError):
        dm.argv_cua(dm.LENH + "download_nghitts_voices.py chieu-thanh")   # không có trong danh mục giọng
