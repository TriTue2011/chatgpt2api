"""Danh sách media WebUI không được lộ metadata nội bộ như một ảnh rác."""

from __future__ import annotations

import pytest

from test._fakes import install_data_dir


@pytest.mark.adapter
def test_bo_qua_marker_ttl_va_file_trong_thu_muc_an():
    from services import image_service

    with install_data_dir() as root:
        docs = root / "images" / "docs" / "abcdef123456"
        docs.mkdir(parents=True)
        (docs / ".expire-24h").touch()
        (docs / "video.mp4").write_bytes(b"video")
        an = root / "images" / ".tam"
        an.mkdir()
        (an / "rac.png").write_bytes(b"not-an-image")

        items = image_service._image_items(media_type="all")

    assert [x["name"] for x in items] == ["video.mp4"]
