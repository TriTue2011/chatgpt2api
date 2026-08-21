from pathlib import Path
from unittest.mock import patch

from services import zalo_personal as zp


def test_gateway_doc_mat_khau_tu_sinh_trong_data_directory(tmp_path: Path) -> None:
    password = "mat-khau-tu-sinh-cho-gateway"
    (tmp_path / ".admin_password").write_text(password, encoding="utf-8")
    env = {
        "DATA_DIRECTORY": str(tmp_path),
        "ZALO_SERVER_ADMIN_USERNAME": "admin-noi-bo",
    }
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp, "_cfg", return_value={}
    ):
        assert zp._credentials() == ("admin-noi-bo", password)


def test_env_password_van_co_uu_tien_cao_nhat(tmp_path: Path) -> None:
    (tmp_path / ".admin_password").write_text("tu-file", encoding="utf-8")
    env = {
        "DATA_DIRECTORY": str(tmp_path),
        "ZALO_SERVER_ADMIN_PASSWORD": "tu-env",
    }
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp, "_cfg", return_value={}
    ):
        assert zp._credentials() == ("admin", "tu-env")
