"""Cấu hình & tính toán hạn mức 6 Hũ (JARS system)."""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from app.config import JARS_CONFIG_MAU_PATH, JARS_CONFIG_PATH
from app import storage

logger = logging.getLogger("chi-tieu-bot.jars")

# Chỉ 1 luồng được tạo cấu hình từ mẫu -- xem _tao_cau_hinh_tu_mau().
_khoa_tao_tu_mau = threading.Lock()


@dataclass
class Hu:
    ma: str
    ten: str
    ty_le_phan_tram: float

    def han_muc(self, thu_nhap: int) -> int:
        return round(thu_nhap * self.ty_le_phan_tram / 100)


def doc_cau_hinh() -> dict:
    dam_bao_co_cau_hinh()
    with open(JARS_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def dam_bao_co_cau_hinh() -> None:
    """Chưa có data/jars_config.json (máy cài mới) thì tạo từ mẫu. KHÔNG đọc
    file đã có: app/main.py gọi hàm này lúc khởi động, file sửa tay hỏng cú
    pháp không được làm container chết ngay lúc lên rồi restart lặp."""
    if not os.path.exists(JARS_CONFIG_PATH):
        _tao_cau_hinh_tu_mau()


def _tao_cau_hinh_tu_mau() -> None:
    """Máy cài mới chưa có data/jars_config.json: chép mẫu 6 hũ chuẩn sang.

    Khoá + kiểm lại trong khoá: /ui tải nhiều API song song ngay lần mở đầu,
    các luồng cùng thấy "chưa có file" một lúc. File đã có thì KHÔNG BAO GIỜ
    ghi đè -- đó là cấu hình thật người dùng lưu qua /ui."""
    with _khoa_tao_tu_mau:
        if os.path.exists(JARS_CONFIG_PATH):
            return
        Path(JARS_CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(JARS_CONFIG_MAU_PATH, "r", encoding="utf-8") as f:
            ghi_cau_hinh(json.load(f))
        logger.info("Chưa có %s -- đã tạo từ mẫu %s", JARS_CONFIG_PATH, JARS_CONFIG_MAU_PATH)


def ghi_cau_hinh(cfg: dict) -> None:
    # Ghi qua file tạm rồi os.replace() (atomic trên POSIX) — tránh để lại file
    # jars_config.json bị cụt/hỏng nếu crash giữa lúc ghi. doc_cau_hinh() (Zalo
    # bot tools, scheduler, /ui) không tự phục hồi được nếu file hỏng.
    #
    # flush() + os.fsync() TRƯỚC os.replace(): os.replace() tự nó chỉ atomic
    # ở tầng filesystem (đổi tên), không đảm bảo NỘI DUNG đã thực sự xuống
    # đĩa -- không có fsync, os buffer có thể giữ dữ liệu trong RAM; process
    # crash vẫn an toàn (buffer OS còn sống), nhưng kernel panic/mất điện
    # giữa chừng thì không -- rename có thể landed trước khi data lên đĩa.
    #
    # Dọn file .tmp nếu có lỗi bất kỳ trước khi replace thành công (kể cả
    # json.dump() tự raise vì cfg chứa gì đó không serialize được) — nếu
    # không, file .tmp rơi rớt lại vĩnh viễn. Luôn raise lại lỗi gốc.
    tmp_path = f"{JARS_CONFIG_PATH}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, JARS_CONFIG_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def danh_sach_hu() -> list[Hu]:
    cfg = doc_cau_hinh()
    return [Hu(**h) for h in cfg["hu"]]


def tim_hu(ma: str) -> Hu | None:
    for h in danh_sach_hu():
        if h.ma == ma:
            return h
    return None


def thu_nhap_thang() -> int:
    return int(doc_cau_hinh()["thu_nhap_thuc_linh_thang"])


def nguong_canh_bao() -> list[float]:
    return list(doc_cau_hinh().get("nguong_canh_bao", [0.65, 0.8, 1.0]))


def nhan_dang_chu_ky(dt: datetime, ngay_bat_dau: int) -> str:
    """Nhãn chu kỳ lương (dạng "YYYY-MM") chứa thời điểm dt, dựa theo ngày
    bắt đầu chu kỳ (1-28). Nếu dt.day >= ngay_bat_dau, nhãn = tháng dương
    lịch chứa dt. Ngược lại, nhãn = tháng dương lịch TRƯỚC đó."""
    if dt.day >= ngay_bat_dau:
        return dt.strftime("%Y-%m")
    nam, thang = dt.year, dt.month - 1
    if thang == 0:
        thang, nam = 12, nam - 1
    return f"{nam:04d}-{thang:02d}"


def ngay_bat_dau_chu_ky() -> int:
    # Kẹp 1..28: jars_config.json sửa tay có thể có 0 hoặc 29-31, làm
    # date.replace(day=...)/date(...) trong ngay_bat_dau_ky_sau() raise --
    # sập xem_ngan_sach/ /ui/cảnh báo tổng, và ghi_chi_tieu ném lỗi SAU khi
    # đã ghi dòng (review M2). /api/cau-hinh đã tự chặn 1-28 khi lưu qua
    # /ui; giá trị ngoài khoảng chỉ phát sinh khi sửa tay file.
    return min(max(int(doc_cau_hinh().get("ngay_bat_dau_chu_ky", 1)), 1), 28)


def thang_hien_tai() -> str:
    return nhan_dang_chu_ky(datetime.now(), ngay_bat_dau_chu_ky())


def thu_nhap_hieu_qua(thang: str) -> int:
    """Thu nhập cố định + mọi khoản thu nhập phát sinh đã ghi trong đúng
    thang đó — dùng thay cho thu_nhap_thang() ở nơi tính hạn mức, để
    thưởng/thu thêm cũng được chia theo đúng tỷ lệ % hũ như lương."""
    return thu_nhap_thang() + storage.tong_thu_nhap_them_trong_thang(thang)


def tinh_han_muc_da_dieu_chinh(thang: str, han_muc_goc: dict[str, int]) -> dict:
    """han_muc_goc: {ma_hu: han_muc_thang} đã tính theo % cấu hình bình
    thường, CHƯA điều chỉnh. Trừ tổng chi_phi_dac_biet của thang vào
    du_phong trước (không cho âm), phần dư (nếu du_phong không đủ) trừ tiếp
    vào huong_thu (cũng không cho âm). KHÔNG cascade sang hũ khác, KHÔNG
    đụng jars_config.json dưới bất kỳ hình thức nào -- chỉ tính toán thuần
    trên han_muc_goc (dict truyền vào) + storage (bảng chi_phi_dac_biet).

    Trả về {"han_muc": {ma_hu: han_muc_da_dieu_chinh, ...},
            "tong_chi_phi_dac_biet": int,
            "con_thieu": int}  -- con_thieu > 0 nếu sau khi trừ hết cả 2 hũ
    vẫn còn dư; caller (tools.py) tự quyết định câu chữ cảnh báo (hàm này
    chỉ trả số liệu, không build message tiếng Việt)."""
    tong = storage.tong_chi_phi_dac_biet_trong_thang(thang)
    han_muc_moi = dict(han_muc_goc)
    con_lai_can_tru = tong

    if con_lai_can_tru > 0 and "du_phong" in han_muc_moi:
        tru = min(han_muc_moi["du_phong"], con_lai_can_tru)
        han_muc_moi["du_phong"] -= tru
        con_lai_can_tru -= tru

    if con_lai_can_tru > 0 and "huong_thu" in han_muc_moi:
        tru = min(han_muc_moi["huong_thu"], con_lai_can_tru)
        han_muc_moi["huong_thu"] -= tru
        con_lai_can_tru -= tru

    return {
        "han_muc": han_muc_moi,
        "tong_chi_phi_dac_biet": tong,
        "con_thieu": con_lai_can_tru,
    }


def tinh_de_xuat_phan_bo(thang: str) -> dict:
    """% đề xuất mỗi hũ = trung bình chi thực tế 3 tháng trước / thu nhập
    hiệu quả tháng đó, CHUẨN HOÁ để tổng luôn = 100.0. KHÔNG dùng "mức độ
    quan trọng" (chỉ AI thật mới suy luận cái đó, xem app/tools.py). Nếu
    không có bất kỳ khoản chi nào trong cả 3 tháng trước (hoặc thu nhập = 0),
    trả nguyên % đang cấu hình làm "đề xuất" và du_lieu_du=False, để
    caller/UI biết đây không phải đề xuất thật, tránh hiện đề xuất y hệt
    cấu hình hiện tại một cách vô nghĩa."""
    hus = danh_sach_hu()
    trung_binh_theo_hu = storage.trung_binh_chi_theo_hu_3_thang_truoc(thang)

    def _giu_nguyen_cau_hinh() -> dict:
        return {
            "thang": thang,
            "du_lieu_du": False,
            "de_xuat": [
                {"ma": h.ma, "ten": h.ten, "ty_le_phan_tram": h.ty_le_phan_tram}
                for h in hus
            ],
        }

    if not trung_binh_theo_hu:
        return _giu_nguyen_cau_hinh()

    thu_nhap = thu_nhap_hieu_qua(thang)
    if not thu_nhap:
        return _giu_nguyen_cau_hinh()

    ty_le_tho = {h.ma: trung_binh_theo_hu.get(h.ma, 0) / thu_nhap * 100 for h in hus}
    tong_tho = sum(ty_le_tho.values())
    if tong_tho <= 0:
        return _giu_nguyen_cau_hinh()

    he_so = 100.0 / tong_tho
    de_xuat = [
        {"ma": h.ma, "ten": h.ten, "ty_le_phan_tram": round(ty_le_tho[h.ma] * he_so, 1)}
        for h in hus
    ]

    # Sai số làm tròn (mỗi hũ làm tròn độc lập, KHÔNG còn hũ "cuối" theo vị
    # trí danh_sach_hu() nhận phần dư nữa -- bug gốc: hũ cuối trong cấu hình
    # thật của dự án là tu_do_tai_chinh, một hũ CHỈ ĐỂ TIẾT KIỆM nên thường
    # gần như không có chi tiêu ghi nhận; ép nó nhận phần dư có thể đẩy % của
    # nó về ÂM, vô nghĩa và bị /api/cau-hinh từ chối 400 sau khi UI đã hiện
    # tổng hợp lệ). Thay vào đó, dồn phần dư này vào hũ đang có tỷ lệ LỚN
    # NHẤT (max() theo giá trị, không theo vị trí -- hũ lớn nhất gần như chắc
    # chắn lớn hơn nhiều so với độ lớn phần dư, vài phần trăm của 1 đơn vị
    # làm tròn 0.1%, nên rẽ âm gần như không bao giờ xảy ra). Tie thì lấy hũ
    # đầu tiên max() gặp, không cần logic tie-break riêng.
    du = round(100.0 - sum(d["ty_le_phan_tram"] for d in de_xuat), 1)
    hu_lon_nhat = max(de_xuat, key=lambda d: d["ty_le_phan_tram"])
    # Chặn an toàn (không kỳ vọng xảy ra thực tế): nếu dư âm quá lớn so với
    # hũ lớn nhất, chặn ở 0.0 thay vì cho ra số âm -- chấp nhận tổng có thể
    # lệch nhẹ khỏi 100.0 trong trường hợp cực hiếm này, đổi lấy không bao
    # giờ âm.
    hu_lon_nhat["ty_le_phan_tram"] = max(0.0, round(hu_lon_nhat["ty_le_phan_tram"] + du, 1))

    return {"thang": thang, "du_lieu_du": True, "de_xuat": de_xuat}


# Thứ tự rút tiền bù hũ âm -- người dùng chốt 23/09/2026 (spec
# docs/superpowers/specs/2026-09-23-tu-bu-hu-am-design.md). Tự Do Tài Chính
# luôn bị đụng tới cuối cùng. Mã hũ không có trong danh sách (nếu sau này
# thêm hũ mới) xếp sau cùng, theo thứ tự cấu hình.
THU_TU_BU = ["huong_thu", "du_phong", "hoc_tap", "gia_dinh", "thiet_yeu", "tu_do_tai_chinh"]


def tinh_tu_bu(han_muc: dict[str, int], da_chi: dict[str, int], thieu_dac_biet: int = 0) -> dict:
    """Hàm THUẦN (không đọc DB/cấu hình). han_muc: hạn mức từng hũ SAU điều
    chỉnh chi phí đặc biệt (đầu ra tinh_han_muc_da_dieu_chinh), thứ tự key =
    thứ tự cấu hình. da_chi: đã chi từng hũ (thiếu key = 0). thieu_dac_biet:
    con_thieu của Tính năng D (phần chi phí đặc biệt vượt Dự Phòng + Hưởng Thụ).

    Phần thiếu được rút từ phần còn dư của các hũ khác theo THU_TU_BU -- rút
    cạn hũ trước rồi mới tới hũ sau. thieu_dac_biet được bù TRƯỚC, rồi tới các
    hũ âm theo thứ tự cấu hình. Không đủ bù thì hũ âm vẫn còn âm đúng phần
    thiếu (tong_con_lai âm)."""
    thu_tu_nhuong = [ma for ma in THU_TU_BU if ma in han_muc] + [
        ma for ma in han_muc if ma not in THU_TU_BU
    ]
    con_nhuong_duoc = {ma: max(0, han_muc[ma] - da_chi.get(ma, 0)) for ma in han_muc}
    da_nhuong = {ma: 0 for ma in han_muc}
    duoc_bu = {ma: 0 for ma in han_muc}
    bu_tu: dict[str, list[tuple[str, int]]] = {ma: [] for ma in han_muc}

    def rut(so_can: int) -> tuple[list[tuple[str, int]], int]:
        da_lay: list[tuple[str, int]] = []
        for ma in thu_tu_nhuong:
            if so_can <= 0:
                break
            lay = min(con_nhuong_duoc[ma], so_can)
            if lay <= 0:
                continue
            con_nhuong_duoc[ma] -= lay
            da_nhuong[ma] += lay
            so_can -= lay
            da_lay.append((ma, lay))
        return da_lay, so_can

    thieu_dac_biet = max(0, thieu_dac_biet)
    _, thieu_dac_biet_chua_bu = rut(thieu_dac_biet)

    for ma in han_muc:
        am = da_chi.get(ma, 0) - han_muc[ma]
        if am > 0:
            da_lay, chua_bu = rut(am)
            duoc_bu[ma] = am - chua_bu
            bu_tu[ma] = da_lay

    tong_ngan_sach = sum(han_muc.values()) - thieu_dac_biet
    tong_da_chi = sum(da_chi.get(ma, 0) for ma in han_muc)
    return {
        "han_muc_hieu_luc": {ma: han_muc[ma] - da_nhuong[ma] + duoc_bu[ma] for ma in han_muc},
        "duoc_bu": duoc_bu,
        "da_nhuong": da_nhuong,
        "bu_tu": bu_tu,
        "thieu_dac_biet_chua_bu": thieu_dac_biet_chua_bu,
        "tong_ngan_sach": tong_ngan_sach,
        "tong_da_chi": tong_da_chi,
        "tong_con_lai": tong_ngan_sach - tong_da_chi,
    }


def ngay_bat_dau_ky_sau(hom_nay: date, ngay_bat_dau: int) -> date:
    """Ngày bắt đầu kỳ lương KẾ TIẾP (luôn sau hom_nay). ngay_bat_dau 1-28."""
    if hom_nay.day < ngay_bat_dau:
        return hom_nay.replace(day=ngay_bat_dau)
    if hom_nay.month == 12:
        return date(hom_nay.year + 1, 1, ngay_bat_dau)
    return date(hom_nay.year, hom_nay.month + 1, ngay_bat_dau)


def so_ngay_con_lai_trong_ky(hom_nay: date, ngay_bat_dau: int) -> int:
    """Số ngày từ hom_nay (tính cả hôm nay) tới trước ngày bắt đầu kỳ lương
    kế tiếp -- luôn >= 1."""
    return (ngay_bat_dau_ky_sau(hom_nay, ngay_bat_dau) - hom_nay).days


def tinh_ngan_sach_thang(thang: str) -> dict:
    """Trạng thái ngân sách đầy đủ của 1 tháng -- NGUỒN DUY NHẤT cho mọi nơi
    cần hạn mức/đã chi/còn lại (tools.py, alerts.py). Gộp: thu nhập hiệu quả
    -> hạn mức theo % -> điều chỉnh chi phí đặc biệt (Tính năng D) -> tự bù
    hũ âm (tinh_tu_bu). Chỉ đọc, không ghi DB/cấu hình.

    ty_le_tong_da_dung là TỈ LỆ (0..n), không phải %. tong_ngan_sach <= 0 thì
    = 1.0 nếu đã chi hoặc ngân sách âm, ngược lại 0.0."""
    thu_nhap = thu_nhap_hieu_qua(thang)
    cac_hu = danh_sach_hu()
    han_muc_goc = {hu.ma: hu.han_muc(thu_nhap) for hu in cac_hu}
    dieu_chinh = tinh_han_muc_da_dieu_chinh(thang, han_muc_goc)
    han_muc_truoc_bu = dieu_chinh["han_muc"]
    da_chi = {hu.ma: storage.tong_chi_trong_thang(hu.ma, thang) for hu in cac_hu}
    bu = tinh_tu_bu(han_muc_truoc_bu, da_chi, dieu_chinh["con_thieu"])
    ten_theo_ma = {hu.ma: hu.ten for hu in cac_hu}

    hu_ket_qua = []
    for hu in cac_hu:
        hieu_luc = bu["han_muc_hieu_luc"][hu.ma]
        hu_ket_qua.append({
            "ma": hu.ma,
            "ten": hu.ten,
            "ty_le_phan_tram": hu.ty_le_phan_tram,
            "han_muc_truoc_bu": han_muc_truoc_bu[hu.ma],
            "da_chi": da_chi[hu.ma],
            "duoc_bu": bu["duoc_bu"][hu.ma],
            "da_nhuong": bu["da_nhuong"][hu.ma],
            "bu_tu": [
                {"ma": ma, "ten": ten_theo_ma[ma], "so_tien": so_tien}
                for ma, so_tien in bu["bu_tu"][hu.ma]
            ],
            "han_muc_hieu_luc": hieu_luc,
            "con_lai": hieu_luc - da_chi[hu.ma],
        })

    tong_ngan_sach = bu["tong_ngan_sach"]
    tong_da_chi = bu["tong_da_chi"]
    if tong_ngan_sach > 0:
        ty_le_tong = tong_da_chi / tong_ngan_sach
    else:
        ty_le_tong = 1.0 if (tong_da_chi > 0 or tong_ngan_sach < 0) else 0.0

    return {
        "thang": thang,
        "thu_nhap_hieu_qua": thu_nhap,
        "hu": hu_ket_qua,
        "tong_chi_phi_dac_biet": dieu_chinh["tong_chi_phi_dac_biet"],
        "con_thieu_dac_biet": dieu_chinh["con_thieu"],
        "thieu_dac_biet_chua_bu": bu["thieu_dac_biet_chua_bu"],
        "tong_ngan_sach": tong_ngan_sach,
        "tong_da_chi": tong_da_chi,
        "tong_con_lai": bu["tong_con_lai"],
        "ty_le_tong_da_dung": ty_le_tong,
    }
