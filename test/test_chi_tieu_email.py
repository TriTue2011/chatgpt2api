"""Chi tiêu từ email — mỗi sổ tự nối hộp thư; đọc thư người gửi đã khai, tự ghi, báo để sửa (chủ máy 02/10/2026).

Không gọi mạng: IMAP và model đều là bản giả."""
from __future__ import annotations

import json
import os
from email.message import EmailMessage

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.chi_tieu import email_chi as ec, kho, ngan_sach as ns, nghiep_vu as nv  # noqa: E402

NGAN_HANG = "vcbdigibank@info.vietcombank.com.vn"


def _thu(uid: int, gui: str, chu_de: str, noi_dung: str, mid: str | None = None) -> tuple[int, bytes]:
    m = EmailMessage()
    m["From"] = f"Vietcombank <{gui}>"
    m["To"] = "chu@gmail.com"
    m["Subject"] = chu_de
    m["Date"] = "Fri, 02 Oct 2026 03:32:00 +0000"
    m["Message-ID"] = mid or f"<m{uid}@vcb>"
    m.set_content(noi_dung)
    return uid, m.as_bytes()


class ImapGia:
    """Hộp thư giả: SEARCH trả mọi UID theo người gửi (bỏ qua điều kiện ngày), FETCH trả thư thô."""

    def __init__(self, thu: list[tuple[int, bytes]]):
        self.thu = dict(thu)
        self.tim: list[str] = []
        self.untagged_responses = {"UIDVALIDITY": [b"7"]}

    def uid(self, lenh, *a):
        if lenh == "SEARCH":
            tc = a[-1]
            self.tim.append(tc)
            tu = int(tc.split()[1].split(":")[0]) if tc.startswith("UID") else 0
            ng = tc.split('FROM "')[1].rstrip('"')
            ds = [u for u, raw in self.thu.items() if ng.encode() in raw and u >= tu]
            return "OK", [" ".join(map(str, ds)).encode()]
        if lenh == "FETCH":
            assert a[1] == "(BODY.PEEK[])", "chỉ đọc — không được đánh dấu đã đọc"
            return "OK", [(b"1 (BODY[] {9}", self.thu[int(a[0])]), b")"]
        raise AssertionError(lenh)

    def logout(self):
        pass


def _model(map_noi_dung: dict[str, dict]):
    def goi(huong, de):
        for k, v in map_noi_dung.items():
            if k in de:
                return json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v
        return '{"loai": "khong"}'
    return goi


@pytest.fixture
def so(tmp_path):
    kho._reset_for_tests(tmp_path / "ct.db")
    s = kho.tao_so("Sổ thử", "u1")
    kho.sua_so(s["id"], luong=10_000_000, ngay_bat_dau=1)
    yield s["id"]


def _them(so_id, **k):
    return ec.luu_hop_thu(so_id, imap_host="imap.gmail.com", dia_chi="chu@gmail.com", mat_khau="abcd efgh ijkl mnop",
                          nguoi_gui=[NGAN_HANG], **k)["id"]


def test_luu_hop_thu_ma_hoa_mat_khau_va_bat_buoc_nguoi_gui(so):
    with pytest.raises(nv.LoiChiTieu):
        ec.luu_hop_thu(so, imap_host="imap.gmail.com", dia_chi="chu@gmail.com", mat_khau="x", nguoi_gui=[])
    with pytest.raises(nv.LoiChiTieu):
        ec.luu_hop_thu(so, imap_host="imap.gmail.com", dia_chi="chu@gmail.com", mat_khau="x", nguoi_gui=["ngân hàng"])
    id_ = _them(so)
    with kho.db() as c:
        luu = c.execute("SELECT mat_khau FROM hop_thu WHERE id=?", (id_,)).fetchone()[0]
    assert "abcd" not in luu and ec._giai_ma(luu) == "abcdefghijklmnop"
    ds = ec.ds_hop_thu(so)["hop_thu"]
    assert "mat_khau" not in ds[0] and ds[0]["nguoi_gui"] == [NGAN_HANG]


def test_so_khac_khong_dung_duoc_hop_thu(so):
    id_ = _them(so)
    khac = kho.tao_so("Sổ khác", "u2")["id"]
    with pytest.raises(nv.LoiChiTieu):
        ec.xoa_hop_thu(khac, id_)
    assert ec.ds_hop_thu(khac)["hop_thu"] == []


def test_quet_ghi_chi_thu_bo_otp_va_nguoi_la_roi_khong_ghi_lap(so, monkeypatch):
    id_ = _them(so)
    imap = ImapGia([
        _thu(11, NGAN_HANG, "Biến động số dư", "TK 1234567890123 -150,000VND GRAB DI LAM. So du 5,000,000"),
        _thu(12, NGAN_HANG, "Biến động số dư", "TK 1234567890123 +2,000,000VND LUONG THUONG"),
        _thu(13, NGAN_HANG, "Mã OTP", "OTP 123456"),
        # IMAP «FROM» khớp CHUỖI CON (tên hiển thị, Reply-To…) — thư người lạ vẫn có thể lọt vào kết quả tìm
        _thu(14, "quangcao@shop.vn", f"Chuyển tiếp từ {NGAN_HANG}", "giảm giá"),
    ])
    monkeypatch.setattr(ec, "_mo", lambda h: (imap, "7"))
    goi = _model({"GRAB": {"loai": "chi", "so_tien": 150000, "noi_dung": "Grab đi làm", "hu": "Thiết Yếu"},
                  "LUONG": {"loai": "thu", "so_tien": 2000000, "noi_dung": "Lương thưởng", "hu": ""}})
    da_gui: list[str] = []
    h = ec._mot(so, id_)
    kq = ec.quet_hop_thu(h, goi=goi, gui=lambda s, tin: da_gui.append(tin) or 1)
    assert kq["da_ghi"] == 2
    ky = ns.ky_hien_tai(kho.so(so))
    chi = kho.ds_chi(so, ky)
    assert [(x["so_tien"], x["nguon"], x["hu_id"]) for x in chi] == [(150000, "email", nv.tim_hu(so, "Thiết Yếu")["id"])]
    assert kho.tong_ky("thu_nhap_them", so, ky) == 2_000_000
    assert len(da_gui) == 2 and "150.000đ" in da_gui[0] and "Thiết Yếu" in da_gui[0] and "sửa" in da_gui[0]
    assert ec._mot(so, id_)["uid_cuoi"] == 14
    # quét lại: hỏi theo UID mới, không ghi lặp
    kq2 = ec.quet_hop_thu(ec._mot(so, id_), goi=goi, gui=lambda s, tin: da_gui.append(tin) or 1)
    assert kq2["da_ghi"] == 0 and imap.tim[-1].startswith("UID 15:*")


def test_model_loi_thi_dung_lai_luot_sau_doc_lai(so, monkeypatch):
    id_ = _them(so)
    imap = ImapGia([_thu(21, NGAN_HANG, "BDSD", "-50,000VND CAFE"), _thu(22, NGAN_HANG, "BDSD", "-70,000VND PHO")])
    monkeypatch.setattr(ec, "_mo", lambda h: (imap, "7"))
    hong = _model({"CAFE": {"loai": "chi", "so_tien": 50000, "noi_dung": "Cà phê", "hu": "Hưởng Thụ"}, "PHO": "xin lỗi"})
    ec.quet_hop_thu(ec._mot(so, id_), goi=hong, gui=lambda s, t: 1)
    assert ec._mot(so, id_)["uid_cuoi"] == 21, "thư model chưa hiểu không được đánh dấu xong"
    tot = _model({"PHO": {"loai": "chi", "so_tien": 70000, "noi_dung": "Phở", "hu": "Thiết Yếu"}})
    assert ec.quet_hop_thu(ec._mot(so, id_), goi=tot, gui=lambda s, t: 1)["da_ghi"] == 1


def test_cung_thu_o_hai_hop_thu_chi_ghi_mot_lan(so, monkeypatch):
    a, b = _them(so), _them(so, ten="Hộp 2")
    thu = [_thu(5, NGAN_HANG, "BDSD", "-99,000VND SACH", mid="<cung@vcb>")]
    monkeypatch.setattr(ec, "_mo", lambda h: (ImapGia(thu), "7"))
    goi = _model({"SACH": {"loai": "chi", "so_tien": 99000, "noi_dung": "Sách", "hu": "Học Tập"}})
    n = sum(ec.quet_hop_thu(ec._mot(so, x), goi=goi, gui=lambda s, t: 1)["da_ghi"] for x in (a, b))
    assert n == 1


def test_che_so_tai_khoan_khong_che_so_tien():
    assert ec.che_so("TK 1234567890123 -1,500,000VND") == "TK …0123 -1,500,000VND"
    assert ec.che_so("Thẻ 4111111111111111") == "Thẻ …1111"


def test_nguoi_gui_theo_ten_mien():
    assert ec._khop_nguoi_gui("a@info.vcb.com.vn", ["@vcb.com.vn"]), "tên miền con của ngân hàng"
    assert not ec._khop_nguoi_gui("x@gia-vcb.com.vn", ["@vcb.com.vn"]), "chỉ trùng đuôi chữ — giả mạo"
    assert not ec._khop_nguoi_gui("other@shop.vn", [NGAN_HANG])


def test_so_tien_model_tra_so_thuc_hay_chuoi_co_dau():
    for v, dung in ((185000, 185000), (185000.0, 185000), ("185,000", 185000), ("185.000 VND", 185000)):
        kq = ec.hieu_thu("BDSD", "x", ["Thiết Yếu"], lambda h, d, v=v: json.dumps({"loai": "chi", "so_tien": v, "hu": "Thiết Yếu"}))
        assert kq["so_tien"] == dung, v
    assert ec.hieu_thu("BDSD", "x", [], lambda h, d: '{"loai": "chi", "so_tien": 0}') is None
