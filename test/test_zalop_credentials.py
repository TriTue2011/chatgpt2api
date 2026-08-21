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
    env = {
        "DATA_DIRECTORY": str(tmp_path),
        # Compose export mac dinh cho admin chinh.
        "ZALO_SERVER_ADMIN_USERNAME": "admin",
    }
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp, "_cfg", return_value={"zalo_personal_password": "mat-khau-cu"}
    ):
        assert zp._credentials() == ("admin", "mat-khau-moi")


def test_server_ngoai_van_uu_tien_password_cau_hinh(tmp_path: Path) -> None:
    (tmp_path / ".admin_password").write_text("chi-cua-server-nhung", encoding="utf-8")
    env = {
        "DATA_DIRECTORY": str(tmp_path),
        # Compose export username mac dinh nhung server ngoai van dung Settings.
        "ZALO_SERVER_ADMIN_USERNAME": "admin",
    }
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
    env = {
        "DATA_DIRECTORY": str(tmp_path),
        # Compose export mac dinh; Settings admin phu van phai la cap rieng.
        "ZALO_SERVER_ADMIN_USERNAME": "admin",
    }
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp,
        "_cfg",
        return_value={
            "zalo_personal_username": "admin-phu",
            "zalo_personal_password": "mat-khau-admin-phu",
        },
    ):
        assert zp._credentials() == ("admin-phu", "mat-khau-admin-phu")


def test_env_password_ep_dung_username_admin_duoc_quan_ly(tmp_path: Path) -> None:
    env = {
        "DATA_DIRECTORY": str(tmp_path),
        "ZALO_SERVER_ADMIN_PASSWORD": "mat-khau-tu-env",
    }
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp,
        "_cfg",
        return_value={
            "zalo_personal_username": "admin-phu",
            "zalo_personal_password": "mat-khau-admin-phu",
        },
    ):
        assert zp._credentials() == ("admin", "mat-khau-tu-env")


def test_server_ngoai_khong_ghep_env_username_voi_config_password(
    tmp_path: Path,
) -> None:
    env = {
        "DATA_DIRECTORY": str(tmp_path),
        # Compose luon export bien nay, ke ca khi server ngoai dung user khac.
        "ZALO_SERVER_ADMIN_USERNAME": "admin",
    }
    with patch.dict("os.environ", env, clear=True), patch.object(
        zp,
        "_cfg",
        return_value={
            "zalo_personal_server_url": "http://zalo-server-khac:3000",
            "zalo_personal_username": "tai-khoan-server-ngoai",
            "zalo_personal_password": "mat-khau-server-ngoai",
        },
    ):
        assert zp._credentials() == (
            "tai-khoan-server-ngoai",
            "mat-khau-server-ngoai",
        )
