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
