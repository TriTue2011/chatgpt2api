"""Test logic ngưỡng cảnh báo — không gọi C2A thật, monkeypatch gui_canh_bao."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _db_tam(tmp_path, monkeypatch):
    db_path = tmp_path / "chi_tieu_test.db"
    jars_path = tmp_path / "jars_config.json"
    jars_path.write_text(json.dumps({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        # thiet_yeu 90% để TỔNG ngân sách (10tr) đủ lớn: các test cảnh báo
        # TỪNG HŨ bên dưới không bị cảnh báo TỔNG (tính năng 2026-09-23) lẫn vào.
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 90.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    }), encoding="utf-8")

    import app.storage as storage
    monkeypatch.setattr(storage, "DB_PATH", db_path)
    storage.khoi_tao_db()

    import app.jars as jars
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", jars_path)
    yield


@pytest.mark.asyncio
async def test_gui_dung_1_canh_bao_khi_vuot_65_phan_tram(monkeypatch):
    from app import alerts, storage

    tin_da_gui = []

    async def _gia_lap_gui(text):
        tin_da_gui.append(text)
        return {"ok": True}

    monkeypatch.setattr(alerts, "gui_canh_bao", _gia_lap_gui)
    storage.ghi_chi_tieu("huong_thu", 700_000)  # han muc 1tr, 70% > nguong 65%

    da_gui = await alerts.kiem_tra_va_canh_bao()
    assert len(da_gui) == 1
    assert da_gui[0]["nguong"] == 0.65
    assert len(tin_da_gui) == 1


@pytest.mark.asyncio
async def test_khong_gui_lai_cung_nguong_trong_thang(monkeypatch):
    from app import alerts, storage

    tin_da_gui = []

    async def _gia_lap_gui(text):
        tin_da_gui.append(text)
        return {"ok": True}

    monkeypatch.setattr(alerts, "gui_canh_bao", _gia_lap_gui)
    storage.ghi_chi_tieu("huong_thu", 700_000)

    await alerts.kiem_tra_va_canh_bao()
    da_gui_lan_2 = await alerts.kiem_tra_va_canh_bao()  # chưa chi thêm, vẫn 70%

    assert da_gui_lan_2 == []
    assert len(tin_da_gui) == 1


@pytest.mark.asyncio
async def test_vuot_100_phan_tram_chi_gui_nguong_cao_nhat(monkeypatch):
    from app import alerts, storage

    tin_da_gui = []

    async def _gia_lap_gui(text):
        tin_da_gui.append(text)
        return {"ok": True}

    monkeypatch.setattr(alerts, "gui_canh_bao", _gia_lap_gui)
    storage.ghi_chi_tieu("huong_thu", 1_200_000)  # 120%, vuot ca 65/80/100 cung luc

    da_gui = await alerts.kiem_tra_va_canh_bao()
    assert len(da_gui) == 1
    assert da_gui[0]["nguong"] == 1.0


@pytest.mark.asyncio
async def test_khong_gui_canh_bao_gia_khi_co_thu_nhap_phat_sinh(monkeypatch):
    from app import alerts, storage

    tin_da_gui = []

    async def _gia_lap_gui(text):
        tin_da_gui.append(text)
        return {"ok": True}

    monkeypatch.setattr(alerts, "gui_canh_bao", _gia_lap_gui)
    storage.ghi_chi_tieu("huong_thu", 700_000)  # han muc theo luong co dinh = 1tr, 70% >= nguong 65%
    storage.ghi_thu_nhap_them("thuong", 10_000_000)  # thu nhap hieu qua: 10tr+10tr=20tr -> han muc that = 2tr, 700k/2tr = 35%, KHONG con vuot nguong nao

    da_gui = await alerts.kiem_tra_va_canh_bao()
    assert da_gui == []
    assert tin_da_gui == []


@pytest.mark.asyncio
async def test_dung_han_muc_da_dieu_chinh_boi_chi_phi_dac_biet(monkeypatch):
    """Bài học Tính năng B lặp lại đúng vị trí: alerts.py tính han_muc độc
    lập, phải áp dụng tinh_han_muc_da_dieu_chinh() y hệt xem_ngan_sach(),
    nếu không sẽ lệch. Fixture file này chỉ cấu hình hũ huong_thu (han muc
    goc 1tr) -- khai báo 800k chi phí đặc biệt co hẹp han_muc xuống 200k,
    700k đã chi tương đương 350% (vượt ngưỡng 100%) thay vì 70% (han muc
    goc, không vượt ngưỡng nào ngoài 65%)."""
    from app import alerts, storage
    from app.jars import thang_hien_tai

    tin_da_gui = []

    async def _gia_lap_gui(text):
        tin_da_gui.append(text)
        return {"ok": True}

    monkeypatch.setattr(alerts, "gui_canh_bao", _gia_lap_gui)
    storage.ghi_chi_tieu("huong_thu", 700_000)
    storage.ghi_chi_phi_dac_biet(thang_hien_tai(), "phat sinh lon", 800_000)

    da_gui = await alerts.kiem_tra_va_canh_bao()
    assert len(da_gui) == 1
    assert da_gui[0]["nguong"] == 1.0
    assert da_gui[0]["han_muc"] == 200_000


@pytest.mark.asyncio
async def test_gui_canh_bao_khi_han_muc_bi_dieu_chinh_ve_0_va_co_chi_tieu(monkeypatch):
    """I1 review Tính năng D: han_muc bị điều chỉnh về 0 (do khai báo chi
    phí đặc biệt) MÀ đã có chi tiêu thật -- trước fix, `if han_muc <= 0:
    continue` làm cảnh báo 100% không bao giờ được gửi cho đúng 2 hũ tính
    năng này điều chỉnh, đúng lúc ngân sách đang căng nhất."""
    from app import alerts, storage
    from app.jars import thang_hien_tai

    tin_da_gui = []

    async def _gia_lap_gui(text):
        tin_da_gui.append(text)
        return {"ok": True}

    monkeypatch.setattr(alerts, "gui_canh_bao", _gia_lap_gui)
    storage.ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi lon", 1_000_000)
    storage.ghi_chi_tieu("huong_thu", 500_000)

    da_gui = await alerts.kiem_tra_va_canh_bao()
    assert len(da_gui) == 1
    assert da_gui[0]["nguong"] == 1.0
    assert da_gui[0]["han_muc"] == 0
    assert len(tin_da_gui) == 1


@pytest.mark.asyncio
async def test_khong_gui_canh_bao_khi_han_muc_0_va_chua_chi_gi(monkeypatch):
    """Trường hợp nguyên gốc phải giữ đúng: han_muc = 0 (do điều chỉnh hết
    cả huong_thu) MÀ CHƯA chi đồng nào thì không được gửi cảnh báo (và không
    được crash ZeroDivisionError)."""
    from app import alerts, storage
    from app.jars import thang_hien_tai

    tin_da_gui = []

    async def _gia_lap_gui(text):
        tin_da_gui.append(text)
        return {"ok": True}

    monkeypatch.setattr(alerts, "gui_canh_bao", _gia_lap_gui)
    storage.ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi lon", 1_000_000)

    da_gui = await alerts.kiem_tra_va_canh_bao()
    assert da_gui == []
    assert tin_da_gui == []


# ---------------------------------------------------------------------------
# Cảnh báo TỔNG + tự bù (spec 2026-09-23-tu-bu-hu-am-design.md). Fixture:
# thu nhập 10tr, thiet_yeu 9tr, huong_thu 1tr -> tổng ngân sách 10tr.
# ---------------------------------------------------------------------------


def _gia_lap(monkeypatch):
    from app import alerts
    tin_da_gui = []

    async def _gia_lap_gui(text):
        tin_da_gui.append(text)
        return {"ok": True}

    monkeypatch.setattr(alerts, "gui_canh_bao", _gia_lap_gui)
    return tin_da_gui


@pytest.mark.asyncio
async def test_canh_bao_tong_gui_nguong_cao_nhat_kem_so_ngay(monkeypatch):
    from app import alerts, storage
    tin_da_gui = _gia_lap(monkeypatch)
    storage.ghi_chi_tieu("thiet_yeu", 8_500_000)  # tổng 85%

    da_gui = await alerts.kiem_tra_va_canh_bao()
    tong = [d for d in da_gui if d["hu"] == "__tong__"]
    assert len(tong) == 1
    assert tong[0]["nguong"] == 0.8
    assert tong[0]["han_muc"] == 10_000_000
    assert tong[0]["da_chi"] == 8_500_000
    tin_tong = [t for t in tin_da_gui if "tổng ngân sách" in t]
    assert len(tin_tong) == 1
    assert "Đã dùng 85%" in tin_tong[0]
    assert "Còn 1,500,000 VNĐ" in tin_tong[0]
    assert "ngày tới kỳ lương" in tin_tong[0]


@pytest.mark.asyncio
async def test_canh_bao_tong_khong_gui_trung(monkeypatch):
    from app import alerts, storage
    _gia_lap(monkeypatch)
    storage.ghi_chi_tieu("thiet_yeu", 8_500_000)

    await alerts.kiem_tra_va_canh_bao()
    da_gui_lan_2 = await alerts.kiem_tra_va_canh_bao()
    assert [d for d in da_gui_lan_2 if d["hu"] == "__tong__"] == []


@pytest.mark.asyncio
async def test_canh_bao_tong_vuot_tong_bao_do(monkeypatch):
    from app import alerts, storage
    tin_da_gui = _gia_lap(monkeypatch)
    storage.ghi_chi_tieu("thiet_yeu", 10_300_000)  # vượt tổng 300k

    da_gui = await alerts.kiem_tra_va_canh_bao()
    # F1/M1: mức vượt dùng khoá riêng __tong_vuot__ (tách khỏi __tong__) --
    # xem app/alerts.py::MA_TONG_VUOT.
    tong = [d for d in da_gui if d["hu"] == "__tong_vuot__"]
    assert tong[0]["nguong"] == 1.0
    assert any("🚨" in t and "300,000" in t for t in tin_da_gui)


@pytest.mark.asyncio
async def test_canh_bao_tong_dung_het_100_phan_tram(monkeypatch):
    from app import alerts, storage
    tin_da_gui = _gia_lap(monkeypatch)
    storage.ghi_chi_tieu("thiet_yeu", 10_000_000)

    await alerts.kiem_tra_va_canh_bao()
    assert any("Đã dùng hết 100% tổng ngân sách" in t for t in tin_da_gui)


@pytest.mark.asyncio
async def test_canh_bao_tong_100_roi_vuot_deu_duoc_gui(monkeypatch):
    """F1/M1: đạt đúng 100% rồi vượt tiếp phải gửi CẢ HAI cảnh báo tổng --
    khoá __tong_vuot__ tách khỏi __tong__ nên mức 1.0 đã gửi (cho "đã dùng
    hết 100%") không nuốt mất cảnh báo 🚨 "vượt tổng" sau đó."""
    from app import alerts, storage
    tin_da_gui = _gia_lap(monkeypatch)
    storage.ghi_chi_tieu("thiet_yeu", 10_000_000)  # đúng 100% tổng ngân sách

    await alerts.kiem_tra_va_canh_bao()
    tin_100 = [t for t in tin_da_gui if "Đã dùng hết 100% tổng ngân sách" in t]
    assert len(tin_100) == 1

    storage.ghi_chi_tieu("thiet_yeu", 300_000)  # vượt tổng thêm 300k
    await alerts.kiem_tra_va_canh_bao()
    tin_vuot = [t for t in tin_da_gui if "🚨" in t and "300,000" in t]
    assert len(tin_vuot) == 1

    so_luong_truoc = len(tin_da_gui)
    await alerts.kiem_tra_va_canh_bao()
    assert len(tin_da_gui) == so_luong_truoc  # chạy lại không gửi thêm


@pytest.mark.asyncio
async def test_canh_bao_tong_85_nhay_thang_len_115_van_gui_vuot(monkeypatch):
    """Đối chiếu với chuỗi 100%->vượt ở trên: nhảy thẳng từ dưới 100% lên
    vượt tổng trong 1 lần ghi (không dừng đúng ở mốc 100%) đã đúng từ trước
    fix M1 -- giữ test này làm bằng chứng không hồi quy."""
    from app import alerts, storage
    tin_da_gui = _gia_lap(monkeypatch)
    storage.ghi_chi_tieu("thiet_yeu", 8_500_000)  # tổng 85%
    await alerts.kiem_tra_va_canh_bao()

    storage.ghi_chi_tieu("thiet_yeu", 3_000_000)  # tổng 115%, vượt 1.5tr
    await alerts.kiem_tra_va_canh_bao()
    tin_vuot = [t for t in tin_da_gui if "🚨" in t]
    assert len(tin_vuot) == 1

    so_luong_truoc = len(tin_da_gui)
    await alerts.kiem_tra_va_canh_bao()
    assert len(tin_da_gui) == so_luong_truoc  # chạy lại không gửi thêm


@pytest.mark.asyncio
async def test_canh_bao_hu_100_phan_tram_duoc_bu_thi_noi_ro(monkeypatch):
    from app import alerts, storage
    tin_da_gui = _gia_lap(monkeypatch)
    storage.ghi_chi_tieu("huong_thu", 1_200_000)  # riêng 1tr -> bù 200k từ thiet_yeu

    da_gui = await alerts.kiem_tra_va_canh_bao()
    hu = [d for d in da_gui if d["hu"] == "huong_thu"]
    assert hu[0]["nguong"] == 1.0
    assert hu[0]["han_muc"] == 1_000_000  # hạn mức RIÊNG, không phải hiệu lực
    assert any("Đã tự bù 200,000 VNĐ" in t for t in tin_da_gui)


@pytest.mark.asyncio
async def test_canh_bao_tong_dung_dong_ho_gia_va_ngay_chu_ky_da_cau_hinh(monkeypatch):
    """F4/M4 (mutation test): tin cảnh báo tổng phải nêu đúng so_ngay/ky_sau
    tính từ ngay_bat_dau_chu_ky ĐÃ CẤU HÌNH (5), không phải mặc định 1 --
    đột biến M2 của reviewer ("ngay_bd = 1" trong alerts.py, bỏ qua
    ngay_bat_dau_chu_ky()) khiến 328 test cũ vẫn pass hết; chỉ test dùng
    đồng hồ giả + chu kỳ khác 1 này bắt được."""
    from datetime import datetime
    from app import alerts, jars, storage
    from app.jars import doc_cau_hinh, ghi_cau_hinh
    tin_da_gui = _gia_lap(monkeypatch)

    cfg = doc_cau_hinh()
    cfg["ngay_bat_dau_chu_ky"] = 5
    ghi_cau_hinh(cfg)

    class _DatetimeGiaLap(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 23, 10, 0)

    # Đồng hồ giả phải phủ CẢ jars.thang_hien_tai() lẫn nhãn kỳ của khoản chi:
    # chỉ giả alerts thì ngày 1–4 hằng tháng (giờ thật) nhãn kỳ của jars (đầu
    # kỳ ngày 5) lệch tháng dương lịch mà storage tự gán → khoản chi không được
    # tính, test đỏ theo lịch (đo 01/10/2026).
    monkeypatch.setattr(alerts, "datetime", _DatetimeGiaLap)
    monkeypatch.setattr(jars, "datetime", _DatetimeGiaLap)

    storage.ghi_chi_tieu("thiet_yeu", 8_500_000, thang=jars.thang_hien_tai())  # tổng 85%
    await alerts.kiem_tra_va_canh_bao()

    tin_tong = [t for t in tin_da_gui if "tổng ngân sách" in t]
    assert len(tin_tong) == 1
    assert "12 ngày tới kỳ lương 05/10" in tin_tong[0]


@pytest.mark.asyncio
async def test_hu_chi_bi_rut_bu_khong_bi_canh_bao(monkeypatch):
    """huong_thu nhường hết 1tr cho thiet_yeu nhưng chưa chi đồng nào của
    chính nó -> KHÔNG được cảnh báo hũ huong_thu."""
    from app import alerts, storage
    _gia_lap(monkeypatch)
    storage.ghi_chi_tieu("thiet_yeu", 9_500_000)  # riêng 9tr -> rút 500k từ huong_thu

    da_gui = await alerts.kiem_tra_va_canh_bao()
    assert [d for d in da_gui if d["hu"] == "huong_thu"] == []
