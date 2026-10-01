"""Logic nghiệp vụ đứng sau các MCP tool — tách khỏi lớp giao thức MCP
để dễ test (xem test/test_tools.py) mà không cần dựng server MCP thật."""
from __future__ import annotations

import re
from datetime import date, datetime

from app import pdf_cong_ty, storage
from app.config import SELF_BASE_URL
from app.jars import (
    danh_sach_hu, tim_hu, thang_hien_tai, thu_nhap_thang, tinh_de_xuat_phan_bo,
    ngay_bat_dau_chu_ky, ngay_bat_dau_ky_sau, so_ngay_con_lai_trong_ky,
    tinh_ngan_sach_thang,
)

# Ngưỡng cảnh báo "sắp hết tiền" trong câu trả lời chat -- hằng số riêng,
# KHÔNG theo nguong_canh_bao() của cảnh báo chủ động.
NGUONG_SAP_HET_TONG = 0.8


def _ty_le_hieu_luc(hu: dict) -> float:
    """% đã dùng theo hạn mức HIỆU LỰC (sau tự bù). Hạn mức hiệu lực = 0:
    100% nếu đã chi hoặc đã nhường hết cho hũ khác (không còn đồng nào để
    chi ở hũ này), ngược lại 0%."""
    if hu["han_muc_hieu_luc"]:
        return round(hu["da_chi"] / hu["han_muc_hieu_luc"] * 100, 1)
    return 100.0 if (hu["da_chi"] > 0 or hu["da_nhuong"] > 0) else 0.0


def _ty_le_rieng(hu: dict) -> float:
    """% đã dùng theo hạn mức RIÊNG của hũ (trước tự bù) -- dùng cho câu
    "sát/vượt hạn mức": hũ chỉ bị rút tiền bù cho hũ khác không bị coi là
    vượt. Hạn mức = 0: có chi = 100%, không chi = 0% (quy tắc cũ)."""
    if hu["han_muc_truoc_bu"]:
        return round(hu["da_chi"] / hu["han_muc_truoc_bu"] * 100, 1)
    return 0.0 if hu["da_chi"] == 0 else 100.0


def _thong_tin_ky(tong_con_lai: int) -> dict:
    """Số ngày tới kỳ lương kế tiếp + trung bình được chi mỗi ngày (chỉ có
    nghĩa cho tháng HIỆN TẠI)."""
    hom_nay = datetime.now().date()
    ngay_bd = ngay_bat_dau_chu_ky()
    so_ngay = so_ngay_con_lai_trong_ky(hom_nay, ngay_bd)
    return {
        "so_ngay_con_lai": so_ngay,
        "ngay_bat_dau_ky_sau": ngay_bat_dau_ky_sau(hom_nay, ngay_bd).isoformat(),
        "trung_binh_moi_ngay_con_lai": tong_con_lai // so_ngay if tong_con_lai > 0 else 0,
    }


def _soan_canh_bao_tong(ngan_sach: dict, ky: dict) -> str | None:
    """ngan_sach: đầu ra tinh_ngan_sach_thang(); ky: đầu ra _thong_tin_ky()."""
    ky_sau = date.fromisoformat(ky["ngay_bat_dau_ky_sau"]).strftime("%d/%m")
    con_lai = ngan_sach["tong_con_lai"]
    if con_lai < 0:
        return (f"🚨 ĐÃ CHI VƯỢT TỔNG NGÂN SÁCH THÁNG {-con_lai:,} VNĐ! Các hũ đã bù hết. "
                f"Tuyệt đối không chi thêm cho tới kỳ lương {ky_sau}.")
    if ngan_sach["ty_le_tong_da_dung"] >= NGUONG_SAP_HET_TONG:
        return (f"⚠️ Đã dùng {ngan_sach['ty_le_tong_da_dung'] * 100:.0f}% tổng ngân sách tháng. "
                f"Chỉ còn {con_lai:,} VNĐ cho {ky['so_ngay_con_lai']} ngày tới kỳ lương {ky_sau} "
                f"(~{ky['trung_binh_moi_ngay_con_lai']:,} VNĐ/ngày).")
    return None


def ghi_chi_tieu(hu_ma: str, so_tien: int, ghi_chu: str = "",
                 xac_nhan_vuot_tong: bool = False, nguon: str = "zalo") -> dict:
    hu = tim_hu(hu_ma)
    if hu is None:
        cac_ma = ", ".join(h.ma for h in danh_sach_hu())
        return {"loi": f"Không có hũ '{hu_ma}'. Các mã hợp lệ: {cac_ma}"}
    if so_tien <= 0 or so_tien > 10**12:
        return {"loi": "so_tien phải là số dương, tối đa 1,000,000,000,000 (1000 tỷ)"}

    thang = thang_hien_tai()
    truoc = tinh_ngan_sach_thang(thang)
    if so_tien > truoc["tong_con_lai"] and not xac_nhan_vuot_tong:
        vuot = so_tien - truoc["tong_con_lai"]
        return {
            "da_ghi": False,
            "can_xac_nhan": True,
            "hu": hu.ten,
            "so_tien_de_nghi_ghi": so_tien,
            "tong_con_lai": truoc["tong_con_lai"],
            "vuot_tong_neu_ghi": vuot,
            **_thong_tin_ky(truoc["tong_con_lai"]),
            "canh_bao": (
                f"⚠️ Khoản {so_tien:,} VNĐ sẽ làm VƯỢT tổng ngân sách tháng {vuot:,} VNĐ "
                f"(tổng cả tháng hiện chỉ còn {max(truoc['tong_con_lai'], 0):,} VNĐ)."
            ),
            "huong_dan": (
                "CHƯA GHI. Đọc canh_bao cho người dùng và hỏi họ có chắc đã thực sự chi "
                "khoản này không. Chỉ gọi lại với xac_nhan_vuot_tong=True khi người dùng "
                "đồng ý rõ ràng ở tin nhắn tiếp theo."
            ),
        }

    storage.ghi_chi_tieu(hu_ma, so_tien, ghi_chu, nguon=nguon, thang=thang)
    sau = tinh_ngan_sach_thang(thang)
    h = next(x for x in sau["hu"] if x["ma"] == hu_ma)
    ky = _thong_tin_ky(sau["tong_con_lai"])

    dong_canh_bao = []
    if h["duoc_bu"] > 0:
        nguon_bu = ", ".join(f"{b['ten']} {b['so_tien']:,}" for b in h["bu_tu"])
        dong_canh_bao.append(
            f"Hũ {h['ten']} đã vượt hạn mức {h['han_muc_truoc_bu']:,} VNĐ; đang được bù "
            f"tổng {h['duoc_bu']:,} VNĐ từ: {nguon_bu}."
        )
    canh_bao_tong = _soan_canh_bao_tong(sau, ky)
    if canh_bao_tong:
        dong_canh_bao.append(canh_bao_tong)

    # trang_thai theo hạn mức RIÊNG của hũ (trước tự bù), đúng logic cũ.
    han_muc_rieng = h["han_muc_truoc_bu"]
    return {
        "da_ghi": True,
        "hu": hu.ten,
        "so_tien_vua_ghi": so_tien,
        "da_chi_thang_nay": h["da_chi"],
        "han_muc_thang": h["han_muc_hieu_luc"],
        "con_lai": h["con_lai"],
        "ty_le_da_dung_phan_tram": _ty_le_hieu_luc(h),
        "trang_thai": (
            "vuot_han_muc" if h["da_chi"] >= han_muc_rieng
            else "canh_bao_80" if h["da_chi"] >= han_muc_rieng * 0.8
            else "binh_thuong"
        ),
        "han_muc_truoc_bu": han_muc_rieng,
        "duoc_bu": h["duoc_bu"],
        "bu_tu": h["bu_tu"],
        "tong_con_lai": sau["tong_con_lai"],
        **ky,
        "canh_bao": " ".join(dong_canh_bao) if dong_canh_bao else None,
    }


def xem_ngan_sach() -> dict:
    thang = thang_hien_tai()
    ns = tinh_ngan_sach_thang(thang)

    ket_qua = []
    for hu in ns["hu"]:
        ket_qua.append({
            "ma": hu["ma"],
            "ten": hu["ten"],
            "han_muc_thang": hu["han_muc_hieu_luc"],
            "da_chi": hu["da_chi"],
            "con_lai": hu["con_lai"],
            "ty_le_da_dung_phan_tram": _ty_le_hieu_luc(hu),
            "ty_le_phan_tram": hu["ty_le_phan_tram"],
            "han_muc_truoc_bu": hu["han_muc_truoc_bu"],
            "duoc_bu": hu["duoc_bu"],
            "da_nhuong": hu["da_nhuong"],
            "bu_tu": hu["bu_tu"],
        })

    canh_bao = None
    if ns["con_thieu_dac_biet"] > 0:
        dau = (
            f"Chi phí đặc biệt tháng này ({ns['tong_chi_phi_dac_biet']:,} VNĐ) "
            f"vượt quá cả 2 hũ Dự Phòng + Hưởng Thụ cộng lại; phần thiếu "
            f"{ns['con_thieu_dac_biet']:,} VNĐ"
        )
        if ns["thieu_dac_biet_chua_bu"] > 0:
            canh_bao = (
                f"{dau} tự bù từ các hũ khác theo thứ tự ưu tiên nhưng không đủ — "
                f"còn {ns['thieu_dac_biet_chua_bu']:,} VNĐ chưa có chỗ bù."
            )
        else:
            canh_bao = f"{dau} đã tự bù từ các hũ khác theo thứ tự ưu tiên."

    ky = _thong_tin_ky(ns["tong_con_lai"])
    return {
        "thang": thang,
        "thu_nhap_thuc_linh": ns["thu_nhap_hieu_qua"],
        "thu_nhap_co_dinh": thu_nhap_thang(),
        "hu": ket_qua,
        "tong_chi_phi_dac_biet_thang_nay": ns["tong_chi_phi_dac_biet"],
        "chi_phi_dac_biet_thang_nay": [
            {"id": k["id"], "mo_ta": k["mo_ta"], "so_tien": k["so_tien"]}
            for k in storage.danh_sach_chi_phi_dac_biet_trong_thang(thang)
        ],
        "canh_bao_chi_phi_dac_biet": canh_bao,
        "ngay_bat_dau_chu_ky": ngay_bat_dau_chu_ky(),
        "tong_ngan_sach": ns["tong_ngan_sach"],
        "tong_da_chi": ns["tong_da_chi"],
        "tong_con_lai": ns["tong_con_lai"],
        "ty_le_tong_da_dung_phan_tram": round(ns["ty_le_tong_da_dung"] * 100, 1),
        **ky,
        "canh_bao_tong": _soan_canh_bao_tong(ns, ky),
    }


def xem_lich_su(thang: str = "") -> dict:
    """Liệt kê các khoản chi tiêu CÁ NHÂN đã ghi trong 1 tháng (mặc định
    tháng hiện tại theo chu kỳ), KÈM id của từng khoản -- đây là cách DUY
    NHẤT để lấy id qua chat, vì xem_ngan_sach chỉ trả tổng theo hũ, không có
    id từng khoản. Dùng id lấy được ở đây để gọi tach_giao_dich khi phát
    hiện 1 khoản đã ghi cần tách lại (vd lỡ gộp nhiều mục đích vào 1 hũ).

    thang: định dạng 'YYYY-MM', để trống ('') thì lấy thang_hien_tai().

    Chỉ liệt kê bảng chi_tieu -- CÙNG phạm vi với tach_giao_dich, KHÔNG bao
    gồm giao dịch công ty (tạm ứng/chi công ty) hay khai báo chi phí đặc
    biệt."""
    thang_dung = (thang or "").strip() or thang_hien_tai()
    if not re.fullmatch(r"\d{4}-\d{2}", thang_dung):
        return {"loi": "thang phải đúng định dạng YYYY-MM"}
    giao_dich = []
    for r in storage.danh_sach_chi_trong_thang(thang_dung):
        hu = tim_hu(r["hu_ma"])
        giao_dich.append({
            "id": r["id"],
            "hu_ma": r["hu_ma"],
            "hu_ten": hu.ten if hu else r["hu_ma"],
            "so_tien": r["so_tien"],
            "ghi_chu": r["ghi_chu"],
            "thoi_gian": r["thoi_gian"],
        })
    return {"thang": thang_dung, "giao_dich": giao_dich, "so_luong": len(giao_dich)}


def tach_giao_dich(id: int, danh_sach: list[dict]) -> dict:
    """Tách 1 khoản chi ĐÃ GHI (thường do lỡ gộp nhiều mục đích vào 1 hũ)
    thành nhiều dòng theo đúng hũ. Xoá dòng gốc, ghi N dòng mới giữ nguyên
    thoi_gian/thang của dòng gốc (KHÔNG lấy giờ hiện tại). Tổng so_tien của
    danh_sach PHẢI đúng bằng số tiền dòng gốc -- không dung sai."""
    goc = storage.chi_tieu_theo_id(id)
    if goc is None:
        return {"loi": f"Không có khoản chi id {id}"}
    if len(danh_sach) < 2:
        return {"loi": "Cần ít nhất 2 mục để tách (danh_sach hiện có ít hơn 2)"}

    cac_ma_hop_le = {h.ma for h in danh_sach_hu()}
    for muc in danh_sach:
        if not isinstance(muc, dict):
            return {"loi": "mỗi mục trong danh_sach phải là object {hu_ma, so_tien, ghi_chu}"}
        hu_ma = muc.get("hu_ma", "")
        if hu_ma not in cac_ma_hop_le:
            return {"loi": f"Không có hũ '{hu_ma}'. Các mã hợp lệ: {', '.join(sorted(cac_ma_hop_le))}"}
        so_tien = muc.get("so_tien", 0)
        if isinstance(so_tien, bool) or not isinstance(so_tien, int) or so_tien <= 0 or so_tien > 10**12:
            return {"loi": f"so_tien của hũ '{hu_ma}' phải là số dương, tối đa 1,000,000,000,000 (1000 tỷ)"}
        ghi_chu = muc.get("ghi_chu", "")
        if not isinstance(ghi_chu, str):
            return {"loi": f"ghi_chu của hũ '{hu_ma}' phải là chuỗi"}

    tong_moi = sum(muc["so_tien"] for muc in danh_sach)
    if tong_moi != goc["so_tien"]:
        return {
            "loi": f"Tổng các mục ({tong_moi:,}đ) không khớp số tiền gốc "
                   f"({goc['so_tien']:,}đ), chênh {abs(tong_moi - goc['so_tien']):,}đ"
        }

    ids_moi = storage.tach_chi_tieu(id, danh_sach)

    ns = tinh_ngan_sach_thang(goc["thang"])
    theo_ma = {h["ma"]: h for h in ns["hu"]}

    ma_lien_quan: list[str] = []
    for muc in danh_sach:
        if muc["hu_ma"] not in ma_lien_quan:
            ma_lien_quan.append(muc["hu_ma"])

    chi_tiet = []
    for ma in ma_lien_quan:
        h = theo_ma[ma]
        chi_tiet.append({
            "ma": ma,
            "ten": h["ten"],
            "da_chi_thang_nay": h["da_chi"],
            "han_muc_thang": h["han_muc_hieu_luc"],
            "con_lai": h["con_lai"],
        })

    return {
        "da_tach": True,
        "id_goc": id,
        "id_moi": ids_moi,
        "so_luong_muc": len(danh_sach),
        "chi_tiet_hu_lien_quan": chi_tiet,
    }


def de_xuat_dieu_chinh() -> dict:
    """So sánh thực chi tháng này với hạn mức (như cũ), CỘNG THÊM so sánh xu
    hướng chi thực tế 3 tháng gần nhất với % đang cấu hình cho từng hũ — gợi ý
    cụ thể nên tăng/giảm bao nhiêu điểm %. KHÔNG tự sửa jars_config.json, chỉ
    đề xuất bằng lời để agent trình bày qua chat, hoặc admin tự cân nhắc rồi
    sửa qua trang /ui."""
    ngan_sach = xem_ngan_sach()
    thu_nhap = ngan_sach["thu_nhap_co_dinh"]
    # "Vượt" theo hạn mức RIÊNG của hũ -- hũ chỉ bị rút tiền bù cho hũ khác
    # không bị gọi là vượt. Gợi ý "tạm bù" cũ đã bỏ: giờ bù TỰ ĐỘNG.
    vuot = [h for h in ngan_sach["hu"] if _ty_le_rieng(h) >= 80]
    duoc_bu = [h for h in ngan_sach["hu"] if h["duoc_bu"] > 0]

    de_xuat = []
    if vuot:
        ten_vuot = ", ".join(h["ten"] for h in vuot)
        de_xuat.append(f"Các hũ đang sát/vượt hạn mức tháng này: {ten_vuot}. "
                        f"Cân nhắc giảm chi ở đây cho đến hết tháng.")
    if duoc_bu:
        ten_duoc_bu = ", ".join(h["ten"] for h in duoc_bu)
        de_xuat.append(f"Đã tự động bù phần vượt của {ten_duoc_bu} từ các hũ còn dư "
                        f"theo thứ tự ưu tiên. Tổng còn chi được: "
                        f"{ngan_sach['tong_con_lai']:,} VNĐ.")

    # Xu hướng 3 tháng: so % chi thực tế trung bình với % đang cấu hình. Chỉ
    # gợi ý khi lệch >= 5 điểm % — tránh gợi ý vặt vãnh từ nhiễu ngẫu nhiên
    # hàng tháng (vd 1 tháng lỡ mua món to bất thường).
    trung_binh_theo_hu = storage.trung_binh_chi_theo_hu_3_thang_truoc(ngan_sach["thang"])
    goi_y_xu_huong = []
    if thu_nhap and trung_binh_theo_hu:
        for h in ngan_sach["hu"]:
            tb = trung_binh_theo_hu.get(h["ma"], 0)
            if tb > 0:  # Chỉ gợi ý khi có dữ liệu thực tế
                ty_le_tb_thuc_te = round(tb / thu_nhap * 100, 1)
                lech = ty_le_tb_thuc_te - h["ty_le_phan_tram"]
                if abs(lech) >= 5:
                    huong = "thường xuyên chi ÍT hơn" if lech < 0 else "thường xuyên chi NHIỀU hơn"
                    goi_y_xu_huong.append(
                        f"Hũ \"{h['ten']}\": 3 tháng gần đây {huong} hạn mức đang cấu hình "
                        f"(trung bình thực tế {ty_le_tb_thuc_te:.1f}% thu nhập, đang cấu hình "
                        f"{h['ty_le_phan_tram']:.1f}%). Cân nhắc "
                        f"{'giảm' if lech < 0 else 'tăng'} % hũ này khoảng {abs(lech):.0f} điểm % "
                        f"qua trang quản lý."
                    )
    if goi_y_xu_huong:
        de_xuat.append("Dựa trên xu hướng chi thực tế 3 tháng gần đây (không chỉ tháng này):")
        de_xuat.extend(goi_y_xu_huong)

    if not de_xuat:
        de_xuat.append("Chi tiêu tháng này đang trong tầm kiểm soát, chưa hũ nào cần điều chỉnh.")

    return {
        "thang": ngan_sach["thang"],
        "de_xuat": de_xuat,
        "chi_tiet": ngan_sach["hu"],
        "phan_bo_de_xuat": tinh_de_xuat_phan_bo(ngan_sach["thang"]),
        "luong_co_dinh": thu_nhap_thang(),
        "thu_nhap_ngoai_luong_thang_nay": storage.tong_thu_nhap_them_trong_thang(ngan_sach["thang"]),
    }


def ghi_thu_nhap_them(mo_ta: str, so_tien: int) -> dict:
    if so_tien <= 0 or so_tien > 10**12:
        return {"loi": "so_tien phải là số dương, tối đa 1,000,000,000,000 (1000 tỷ)"}

    thang = thang_hien_tai()
    storage.ghi_thu_nhap_them(mo_ta, so_tien, thang=thang)
    ns = tinh_ngan_sach_thang(thang)
    han_muc_moi = [
        {"ma": h["ma"], "ten": h["ten"], "han_muc_thang": h["han_muc_hieu_luc"]}
        for h in ns["hu"]
    ]
    return {
        "da_ghi": True,
        "mo_ta": mo_ta,
        "so_tien_vua_ghi": so_tien,
        "thu_nhap_hieu_qua_thang": ns["thu_nhap_hieu_qua"],
        "han_muc_moi": han_muc_moi,
    }


def ghi_tam_ung_cong_ty(so_tien: int, mo_ta: str) -> dict:
    if so_tien <= 0 or so_tien > 10**12:
        return {"loi": "so_tien phải là số dương, tối đa 1,000,000,000,000 (1000 tỷ)"}
    if not mo_ta or not mo_ta.strip():
        return {"loi": "mo_ta không được để trống"}
    if len(mo_ta) > 500:
        # fpdf2's pdf.table() (app/pdf_cong_ty.py) raise ValueError neu 1
        # hang qua cao de render tren 1 trang -- thuc nghiem cho thay nguong
        # o ~1750 ky tu cho 1 giao dich. 500 la muc an toan, du du dai cho
        # mo ta thuc te, tranh giai chi bi ket vinh vien (khong sinh duoc
        # PDF, moi lan thu lai deu crash lai y het).
        return {"loi": "mo_ta quá dài, tối đa 500 ký tự"}
    storage.ghi_giao_dich_cong_ty("tam_ung", so_tien, mo_ta)
    return {
        "da_ghi": True,
        "so_tien_vua_ghi": so_tien,
        "mo_ta": mo_ta,
        "so_du_hien_tai": storage.so_du_cong_ty(),
    }


def ghi_chi_cong_ty(so_tien: int, mo_ta: str) -> dict:
    if so_tien <= 0 or so_tien > 10**12:
        return {"loi": "so_tien phải là số dương, tối đa 1,000,000,000,000 (1000 tỷ)"}
    if not mo_ta or not mo_ta.strip():
        return {"loi": "mo_ta không được để trống"}
    if len(mo_ta) > 500:
        # fpdf2's pdf.table() (app/pdf_cong_ty.py) raise ValueError neu 1
        # hang qua cao de render tren 1 trang -- thuc nghiem cho thay nguong
        # o ~1750 ky tu cho 1 giao dich. 500 la muc an toan, du du dai cho
        # mo ta thuc te, tranh giai chi bi ket vinh vien (khong sinh duoc
        # PDF, moi lan thu lai deu crash lai y het).
        return {"loi": "mo_ta quá dài, tối đa 500 ký tự"}
    storage.ghi_giao_dich_cong_ty("chi", so_tien, mo_ta)
    return {
        "da_ghi": True,
        "so_tien_vua_ghi": so_tien,
        "mo_ta": mo_ta,
        "so_du_hien_tai": storage.so_du_cong_ty(),
    }


def xem_so_du_cong_ty() -> dict:
    so_du = storage.so_du_cong_ty()
    dang_mo = storage.danh_sach_giao_dich_cong_ty_dang_mo()
    so_luong = len(dang_mo)
    if so_luong == 0:
        dien_giai = "Chưa có giao dịch tạm ứng/chi công ty nào trong kỳ này."
    elif so_du > 0:
        dien_giai = f"Đang giữ {so_du:,} VNĐ tiền công ty chưa chi hết."
    elif so_du < 0:
        dien_giai = f"Đã chi hộ công ty {-so_du:,} VNĐ, công ty còn nợ lại."
    else:
        dien_giai = "Số dư tạm ứng công ty hiện tại là 0 (tạm ứng khớp đúng chi tiêu)."
    return {
        "so_du": so_du,
        "so_luong_giao_dich": so_luong,
        "dien_giai": dien_giai,
        "giao_dich": [
            {"id": r["id"], "thoi_gian": r["thoi_gian"], "loai": r["loai"],
             "so_tien": r["so_tien"], "mo_ta": r["mo_ta"]}
            for r in dang_mo
        ],
    }


def giai_chi_cong_ty() -> dict:
    if not storage.danh_sach_giao_dich_cong_ty_dang_mo():
        return {"loi": "chưa có giao dịch nào để giải chi"}
    ket_qua = storage.giai_chi()
    giao_dich = storage.giao_dich_theo_lan_giai_chi(ket_qua["id"])
    try:
        pdf_cong_ty.tao_pdf_giai_chi(
            ket_qua["id"], giao_dich, ket_qua["tong_tam_ung"], ket_qua["tong_chi"], ket_qua["so_du"]
        )
    except Exception:
        # Ky da bi khoa durably trong DB (storage.giai_chi() da commit) --
        # loi sinh PDF o day KHONG duoc lam mat ket qua giai chi. Route
        # /ui/tam-ung/<id>/pdf (web.py) se tu sinh lai PDF khi truy cap, vi
        # duong_dan_pdf hoan toan suy ra duoc tu id + du lieu da co trong DB
        # (giai_chi_cong_ty + cong_ty_giao_dich) -- xem Fix 3.
        pass
    return {
        "da_giai_chi": True,
        "id": ket_qua["id"],
        "tong_tam_ung": ket_qua["tong_tam_ung"],
        "tong_chi": ket_qua["tong_chi"],
        "so_du": ket_qua["so_du"],
        "duong_dan_pdf": f"{SELF_BASE_URL}/ui/tam-ung/{ket_qua['id']}/pdf",
    }


def khai_bao_chi_phi_dac_biet(mo_ta: str, so_tien: int) -> dict:
    if so_tien <= 0 or so_tien > 10**12:
        return {"loi": "so_tien phải là số dương, tối đa 1,000,000,000,000 (1000 tỷ)"}
    if not mo_ta or not mo_ta.strip():
        return {"loi": "mo_ta không được để trống"}

    thang = thang_hien_tai()
    storage.ghi_chi_phi_dac_biet(thang, mo_ta, so_tien)
    ngan_sach = xem_ngan_sach()
    han_muc_theo_ma = {h["ma"]: h["han_muc_thang"] for h in ngan_sach["hu"]}

    return {
        "da_ghi": True,
        "thang": thang,
        "mo_ta": mo_ta,
        "so_tien_vua_ghi": so_tien,
        "han_muc_du_phong_moi": han_muc_theo_ma.get("du_phong", 0),
        "han_muc_huong_thu_moi": han_muc_theo_ma.get("huong_thu", 0),
        "canh_bao": ngan_sach["canh_bao_chi_phi_dac_biet"],
        "tong_con_lai": ngan_sach["tong_con_lai"],
        "canh_bao_tong": ngan_sach["canh_bao_tong"],
    }
