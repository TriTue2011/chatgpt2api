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


def test_server_nhung_uu_tien_file_chung_hon_config_cu(tmp_path: Path) -> None:
    (tmp_path / ".admin_password").write_text("mat-khau-moi", encoding="utf-8")
    env = {"DATA_DIRECTORY": str(tmp_path)}
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp, "_cfg", return_value={"zalo_personal_password": "mat-khau-cu"}
    ):
        assert zp._credentials() == ("admin", "mat-khau-moi")


def test_server_ngoai_van_uu_tien_password_cau_hinh(tmp_path: Path) -> None:
    (tmp_path / ".admin_password").write_text("chi-cua-server-nhung", encoding="utf-8")
    env = {"DATA_DIRECTORY": str(tmp_path)}
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp,
        "_cfg",
        return_value={
            "zalo_personal_server_url": "http://zalo-server-khac:3000",
            "zalo_personal_password": "mat-khau-server-ngoai",
        },
    ):
        assert zp._credentials() == ("admin", "mat-khau-server-ngoai")


def test_admin_phu_khong_dung_nham_password_chung_cua_admin_chinh(
    tmp_path: Path,
) -> None:
    (tmp_path / ".admin_password").write_text("mat-khau-admin-chinh", encoding="utf-8")
    env = {"DATA_DIRECTORY": str(tmp_path)}
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp,
        "_cfg",
        return_value={
            "zalo_personal_username": "admin-phu",
            "zalo_personal_password": "mat-khau-admin-phu",
        },
    ):
        assert zp._credentials() == ("admin-phu", "mat-khau-admin-phu")
