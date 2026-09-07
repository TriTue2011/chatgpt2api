"""Lưu theo loại/chủ đề; xóa phải xử lý bản cloud trước khi bỏ dấu vết local."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from services import rclone_service as rc
from services.agent import luu_tru_online as lt, so_da_luu as s


@pytest.fixture
def kho(tmp_path, monkeypatch):
    import services.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(lt, "_SO_PATH", tmp_path / "uploaded.json")
    cd = {"enabled": True, "kho": "drive", "thu_muc": "c2a"}
    monkeypatch.setattr(lt, "cai_dat", lambda *args, **kw: cd)
    monkeypatch.setattr(rc, "workspace_dir", lambda: tmp_path / "office")
    monkeypatch.setattr(s, "_cho_mo_ta", {})
    monkeypatch.setattr(s, "_cho_xoa", {})
    monkeypatch.setattr(s, "_xac_nhan_xoa", {})
    return cd


@pytest.mark.parametrize("ten,mo_ta,kenh,nhat_ky,mong", [
    ("anh.jpg", "hộp thuốc Concor", "zalop", False, "ảnh/thuốc"),
    ("quy-trinh-PCCC.docx", "", "tg", False, "word/pccc"),
    ("tep.docx", "phòng cháy chữa cháy", "tg", False, "word/pccc"),
    ("x.jsonl", "", "zalop", True, "nhật ký/zalo"),
    ("x.jsonl", "", "tg", True, "nhật ký/telegram"),
    ("anh-20260907-123456.jpg", "", "zalop", False, "ảnh/chưa phân loại"),
])
def test_phan_thu_muc(kho, ten, mo_ta, kenh, nhat_ky, mong):
    assert lt.duong_dan_dich(kho, ten, mo_ta=mo_ta, kenh=kenh, nhat_ky=nhat_ky) == "drive:c2a/" + mong


def test_lien_ket_cloud_song_qua_mat_trang_thai_cho(kho):
    uid, url = "zalop_nhom1", "http://x/images/a.jpg"
    s.dat_cho_mo_ta(uid, ref=url, ten="a.jpg")
    assert s.gan_ref_kho(uid, ref=url, ref_kho="drive:c2a/Ảnh/a.jpg")
    s._cho_mo_ta.clear()
    assert s.liet_ke(uid)[0]["ref_kho"] == "drive:c2a/Ảnh/a.jpg"


def test_khong_mat_muc_khi_chua_biet_duong_dan_cloud(kho):
    s.ghi("zalop_nhom1", ref="http://x/images/a.jpg", kind=s.KIND_ANH, ten="a.jpg")
    result = s.xoa_muc("zalop_nhom1", s.liet_ke("zalop_nhom1"))
    assert result["that_bai"]
    assert s.liet_ke("zalop_nhom1")


def test_ban_ghi_cu_tra_cloud_dung_pham_vi_va_xoa_sach_so(kho, monkeypatch):
    uid = "zalop_nhom1"
    ref = "drive:c2a/Ảnh/a.jpg"
    lt.ghi_so(ref, "zalop", "nhom1")
    lt.ghi_so("drive:khac/Ảnh/a.jpg", "zalop", "nhom2")
    s.ghi(uid, ref="http://x/images/a.jpg", kind=s.KIND_ANH, ten="a.jpg")
    xoa = Mock(return_value={"ok": True})
    monkeypatch.setattr(s, "_xoa_ref_kho", xoa)
    result = s.xoa_muc(uid, s.liet_ke(uid))
    assert len(result["da_xoa"]) == 1
    xoa.assert_called_once_with(ref)
    assert ref not in lt.so_da_day()
    assert "drive:khac/Ảnh/a.jpg" in lt.so_da_day()


def test_xoa_cloud_loi_giu_local_va_so_de_thu_lai(kho, tmp_path, monkeypatch):
    local = tmp_path / "office" / "a.docx"
    local.parent.mkdir()
    local.write_bytes(b"word")
    ref, uid = "drive:c2a/word/pccc/a.docx", "zalop_nhom1"
    lt.ghi_so(ref, "zalop", "nhom1", tep_cuc_bo=str(local))
    s.ghi(uid, ref=ref, kind=s.KIND_TAILIEU, ten="a.docx")
    monkeypatch.setattr(s, "_xoa_ref_kho", lambda ref: {"ok": False, "error": "timeout"})
    assert s.xoa_muc(uid, s.liet_ke(uid))["that_bai"]
    assert local.exists() and ref in lt.so_da_day() and s.liet_ke(uid)
    monkeypatch.setattr(s, "_xoa_ref_kho", lambda ref: {"ok": True})
    assert s.xoa_muc(uid, s.liet_ke(uid))["da_xoa"]
    assert not local.exists()
    assert ref not in lt.so_da_day()
    assert not s.liet_ke(uid)


@pytest.mark.parametrize("mo_ta_truoc", [True, False])
def test_mo_ta_va_upload_thu_tu_nao_cung_vao_dung_folder(kho, monkeypatch, mo_ta_truoc):
    uid, url = "zalop_nhom1", "http://x/images/a.jpg"
    ref = "drive:c2a/ảnh/chưa phân loại/a.jpg"
    dich = "drive:c2a/ảnh/thuốc/a.jpg"
    lt.ghi_so(ref, "zalop", "nhom1", thu_muc_goc="c2a")
    chuyen = Mock(return_value={"ok": True, "duong_dan": dich})
    monkeypatch.setattr(rc, "chuyen_tep", chuyen)
    s.dat_cho_mo_ta(uid, ref=url, ten="a.jpg")
    if mo_ta_truoc:
        s.xu_ly_tra_loi(uid, "thuốc Concor")
    assert s.gan_ref_kho(uid, ref=url, ref_kho=ref)
    if not mo_ta_truoc:
        s.xu_ly_tra_loi(uid, "thuốc Concor")
    assert s.liet_ke(uid)[0]["ref_kho"] == dich
    assert s.liet_ke(uid)[0]["ref"] == url
    chuyen.assert_called_once_with(ref, dich)
    assert dich in lt.so_da_day() and ref not in lt.so_da_day()


def test_chuyen_folder_loi_giu_ref_cu_va_bao_ro(kho, monkeypatch):
    uid, ref = "zalop_nhom1", "drive:c2a/word/chưa phân loại/a.docx"
    lt.ghi_so(ref, "zalop", "nhom1", thu_muc_goc="c2a")
    monkeypatch.setattr(rc, "chuyen_tep", lambda *args: {"ok": False, "error": "timeout"})
    s.dat_cho_mo_ta(uid, ref=ref, ten="a.docx", kind=s.KIND_TAILIEU)
    out = s.xu_ly_tra_loi(uid, "pccc")
    assert "Chưa chuyển được" in out["text"]
    assert s.liet_ke(uid)[0]["ref"] == ref
    assert ref in lt.so_da_day()


@pytest.mark.parametrize("cloud_ok", [True, False])
def test_xoa_tu_thu_vien_anh_phai_xoa_cloud(kho, tmp_path, monkeypatch, cloud_ok):
    from services import media_don

    local = tmp_path / "images" / "a.jpg"
    local.parent.mkdir()
    local.write_bytes(b"image")
    ref, uid = "drive:c2a/ảnh/thuốc/a.jpg", "zalop_nhom1"
    s.ghi(uid, ref="http://localhost/images/a.jpg", ref_kho=ref,
          kind=s.KIND_ANH, ten="a.jpg")
    lt.ghi_so(ref, "zalop", "nhom1")
    # Snapshot giống thao tác preview → xác nhận xóa thư viện.
    selected = media_don.chon("image", media_don.TAT_CA, thu_muc=local.parent)
    remote = Mock(return_value={"ok": cloud_ok, "error": "timeout"})
    monkeypatch.setattr(s, "_xoa_ref_kho", remote)
    assert media_don.xoa(selected) == int(cloud_ok)
    remote.assert_called_once_with(ref)
    assert local.exists() is not cloud_ok
    assert bool(s.liet_ke(uid)) is not cloud_ok
    assert (ref in lt.so_da_day()) is not cloud_ok


def test_xoa_muc_anh_don_ca_url_local(kho, tmp_path, monkeypatch):
    local = tmp_path / "images" / "a.jpg"
    local.parent.mkdir()
    local.write_bytes(b"image")
    ref, uid = "drive:c2a/ảnh/thuốc/a.jpg", "zalop_nhom1"
    s.ghi(uid, ref="http://localhost/images/a.jpg", ref_kho=ref,
          kind=s.KIND_ANH, ten="a.jpg")
    monkeypatch.setattr(s, "_xoa_ref_kho", lambda ref: {"ok": True})
    assert s.xoa_muc(uid, s.liet_ke(uid))["da_xoa"]
    assert not local.exists()


def test_don_qua_han_loi_khong_bao_da_xoa(kho, monkeypatch):
    from services.agent import nhat_ky_dong_bo as nk

    ref = "drive:c2a/word/pccc/a.docx"
    lt.ghi_so(ref, "zalop", "nhom1")
    luc = lt.so_da_day()[ref]["luc"]
    monkeypatch.setattr(rc, "xoa", lambda ref: {"ok": False, "error": "timeout"})
    assert nk.don_qua_han(now=luc + 400 * 86400)["xoa"] == 0
    assert ref in lt.so_da_day()


def test_ban_cu_nhieu_ket_qua_khong_xoa_nham(kho, monkeypatch):
    for root in ("c2a", "c2a/khac"):
        lt.ghi_so(f"drive:{root}/Ảnh/a.jpg", "zalop", "nhom1")
    uid = "zalop_nhom1"
    s.ghi(uid, ref="http://x/images/a.jpg", kind=s.KIND_ANH, ten="a.jpg")
    remote = Mock()
    monkeypatch.setattr(s, "_xoa_ref_kho", remote)
    assert s.xoa_muc(uid, s.liet_ke(uid))["that_bai"]
    remote.assert_not_called()


def test_luu_ngay_khong_nhan_doi_ban_workspace(kho, tmp_path, monkeypatch):
    from services.agent import luu_tru_day as ld

    local = tmp_path / "office" / "da_nhan" / "a.jpg"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"image")
    day = Mock(return_value=True)
    monkeypatch.setattr(ld, "day_nen", day)
    assert "Đang lưu" in ld.luu_ngay("zalop", "nhom1", tep=str(local), ten_tep="a.jpg")
    assert day.call_args.args[0] == str(local)
    assert list(local.parent.iterdir()) == [local]


def test_day_ghi_lai_duong_local_thuc_te(kho, tmp_path, monkeypatch):
    from services.agent import luu_tru_day as ld

    local = tmp_path / "office" / "a.docx"
    local.parent.mkdir()
    local.write_bytes(b"word")
    ref = "drive:c2a/word/pccc/a.docx"
    monkeypatch.setattr(rc, "gui_len", lambda *args: {"ok": True, "duong_dan": ref})
    ld._day(str(local), "drive:c2a/word/pccc", pham_vi=("zalop", "nhom1", "", ""),
            thu_muc_goc="c2a")
    assert lt.so_da_day()[ref]["tep_cuc_bo"] == str(local.resolve())


@pytest.mark.parametrize("custom", [False, True])
def test_tool_luu_phan_loai_va_xoa_du_ca_hai_ban(kho, tmp_path, monkeypatch, custom):
    from services.agent import capabilities as caps

    local = tmp_path / "office" / "a.docx"
    local.parent.mkdir()
    local.write_bytes(b"word")
    uid = "zalop_nhom1"
    monkeypatch.setattr(lt, "kho_ghi_duoc", lambda uid: {"kho": "drive", "thu_muc": "c2a"})
    folder = "drive:c2a/tự chọn" if custom else "drive:c2a/word/pccc"
    ref = folder + "/a.docx"
    gui = Mock(return_value={"ok": True, "duong_dan": ref})
    monkeypatch.setattr(rc, "gui_len", gui)
    params = {"op": "gui_len", "tep": "a.docx", "mo_ta": "pccc"}
    if custom:
        params["thu_muc"] = folder
    out = caps._h_kho_dam_may_gui(params, {"user_id": uid})
    assert ref in out["text"]
    gui.assert_called_once_with("a.docx", folder)
    assert s.liet_ke(uid)[0]["ref"] == ref
    monkeypatch.setattr(rc, "xoa", lambda ref: {"ok": True})
    out = caps._h_kho_dam_may_gui({"op": "xoa", "duong_dan": ref}, {"user_id": uid})
    assert "Đã xóa" in out["text"]
    assert not local.exists() and not s.liet_ke(uid) and ref not in lt.so_da_day()


def test_rclone_chuyen_khong_ghi_de_tep_khac(monkeypatch):
    run = Mock(return_value=(False, "", "destination changed"))
    monkeypatch.setattr(rc, "_chay", run)
    src, dst = "drive:c2a/word/a.docx", "drive:c2a/word/pccc/a.docx"
    result = rc.chuyen_tep(src, dst)
    assert not result["ok"] and result["duong_dan"] == src
    assert run.call_args.args[0] == ["moveto", src, dst, "--immutable"]


def test_local_da_doi_khong_bi_xoa_nham(kho, tmp_path, monkeypatch):
    local = tmp_path / "office" / "a.docx"
    local.parent.mkdir()
    local.write_bytes(b"old")
    uid, ref = "zalop_nhom1", "drive:c2a/word/pccc/a.docx"
    lt.ghi_so(ref, "zalop", "nhom1", tep_cuc_bo=str(local))
    s.ghi(uid, ref=ref, ten="a.docx", kind=s.KIND_TAILIEU)
    local.write_bytes(b"new content")
    remote = Mock(return_value={"ok": True})
    monkeypatch.setattr(s, "_xoa_ref_kho", remote)
    assert s.xoa_muc(uid, s.liet_ke(uid))["that_bai"]
    assert local.read_bytes() == b"new content"
    assert s.liet_ke(uid)[0]["da_xoa_cloud"] is True
    # Sau khi người dùng dọn bản mới, lần thử lại không xóa cloud lần hai.
    local.unlink()
    assert s.xoa_muc(uid, s.liet_ke(uid))["da_xoa"]
    remote.assert_called_once_with(ref)


def test_chu_de_khong_tao_duong_dan_thoat_thu_muc(kho):
    folder = lt.duong_dan_dich(kho, "x.docx", mo_ta="../../private\\secrets:token")
    assert folder == "drive:c2a/word/private secrets token"
