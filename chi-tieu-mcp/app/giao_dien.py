"""Theme cho 2 trang HTML của /ui (trang chính + đăng nhập): màu 2 chế độ
sáng/tối, màu 6 hũ, thang cỡ chữ -- 1 nguồn duy nhất sinh ra CSS custom
properties, theo đúng tinh thần theme-ui (https://github.com/system-ui/theme-ui):
theme object -> biến CSS, `colors.modes.dark`, đặt chế độ màu từ localStorage
trước khi vẽ (như InitializeColorMode), cỡ chữ mobile-first theo breakpoint.
KHÔNG nhúng theme-ui thật (React + build step, quá nặng cho 2 trang HTML nhúng
trong app/web.py).

Dùng CSS custom properties thay vì hàm CSS light-dark(): trình duyệt nhúng
trong Zalo/iOS < 17.5 chưa hỗ trợ light-dark(). Bảng màu tím Money Manager đã
được người dùng duyệt 23/09/2026 -- xem
docs/superpowers/specs/2026-09-23-giao-dien-sang-toi-design.md; mọi cặp
chữ/nền đạt WCAG >= 4.5:1 (test/test_giao_dien.py tự đo lại).
"""
from __future__ import annotations

# localStorage: "light"/"dark" = người dùng tự chọn; không có khoá = "Tự động"
# (theo hệ điều hành). Dùng chung cho script khởi tạo trong <head> (bên dưới)
# và nút đổi chế độ trong app/web.py.
KHOA_LUU_CHE_DO = "chitieu-che-do-mau"

MAU: dict[str, dict[str, str]] = {
    "sang": {
        "nen": "#F4F2FB",
        "the": "#FFFFFF",
        "vien": "#E7E4F3",
        "vien-dam": "#CFC8E6",
        "chu": "#1E1B3A",
        "chu-phu": "#5F5B7A",
        "nhan": "#4F2FD0",
        "nut": "#4F2FD0",
        "chu-tren-nut": "#FFFFFF",
        "chu-nut-tat": "#8C88A6",
        "nguy": "#C62F3B",
        "nen-nguy": "#FCE8EA",
        "chu-tren-nguy": "#9B1C28",
        "canh-bao": "#8A5A00",
        "nen-canh-bao": "#FFF3DC",
        "tot": "#1E7F4F",
        # /ui mới (spec 2026-09-23-thiet-ke-lai-ui-design.md): gradient đầu
        # trang 3 điểm + chữ trên nó, nút + nổi, phân đoạn, toast, nền xanh/cam
        # (tab Công ty), nền tím nhạt (tóm tắt AI, chip nhanh), nút đỏ.
        "dau-1": "#4326C4",
        "dau-2": "#6A3DDB",
        "dau-3": "#9148DC",
        "chu-tren-dau": "#FFFFFF",
        "fab-1": "#4F2FD0",
        "fab-2": "#8E46DC",
        "nen-phan-doan": "#E8E4F5",
        "nen-chon": "#FFFFFF",
        "chu-chon": "#4326C4",
        "nen-toast": "#1E1B3A",
        "chu-toast": "#FFFFFF",
        "nen-tot": "#EEF8F3",
        "cam": "#A2480C",
        "nen-cam": "#FEF3EA",
        "nen-nhan": "#F1ECFE",
        "nut-nguy": "#C62F3B",
    },
    "toi": {
        "nen": "#100E19",
        "the": "#1B1828",
        "vien": "#2C2840",
        "vien-dam": "#3D3856",
        "chu": "#ECEAF5",
        "chu-phu": "#A9A4C0",
        "nhan": "#A999FF",
        "nut": "#6B4FEA",
        "chu-tren-nut": "#FFFFFF",
        "chu-nut-tat": "#77728F",
        "nguy": "#FF8A8A",
        "nen-nguy": "#4A1C24",
        "chu-tren-nguy": "#FFC2C2",
        "canh-bao": "#FFC24D",
        "nen-canh-bao": "#3A3112",
        "tot": "#6FCF97",
        "dau-1": "#2A1C79",
        "dau-2": "#3A2396",
        "dau-3": "#52278A",
        "chu-tren-dau": "#FFFFFF",
        "fab-1": "#6B4FEA",
        "fab-2": "#9B5CF0",
        "nen-phan-doan": "#262238",
        "nen-chon": "#6B4FEA",
        "chu-chon": "#FFFFFF",
        "nen-toast": "#ECEAF5",
        "chu-toast": "#1E1B3A",
        "nen-tot": "#173A2A",
        "cam": "#FFB27A",
        "nen-cam": "#3D2412",
        "nen-nhan": "#251F3D",
        "nut-nguy": "#C23A47",
    },
}

# Màu đồ hoạ của từng hũ (vòng tiến độ, donut, icon, chấm màu) -- chỉ cần
# >= 3:1 so với nền thẻ và so với nền nhạt riêng của hũ (MAU_NEN_HU, nền tròn
# sau icon). Bảng theo bản mẫu /ui mới đã duyệt 23/09/2026: 6 tông tách bạch,
# KHÔNG dùng đỏ (đỏ dành cho trạng thái chi vượt -- bảng cũ tô Dự Phòng đỏ).
MAU_HU: dict[str, dict[str, str]] = {
    "sang": {
        "thiet_yeu": "#3F63F0",
        "gia_dinh": "#15966C",
        "hoc_tap": "#B07A06",
        "du_phong": "#0B8793",
        "huong_thu": "#CC3F7B",
        "tu_do_tai_chinh": "#D9621A",
    },
    "toi": {
        "thiet_yeu": "#7B96FF",
        "gia_dinh": "#45C79A",
        "hoc_tap": "#E7B13C",
        "du_phong": "#3CC3CF",
        "huong_thu": "#F07AAE",
        "tu_do_tai_chinh": "#FF9A5A",
    },
}

MAU_NEN_HU: dict[str, dict[str, str]] = {
    "sang": {
        "thiet_yeu": "#E7ECFF",
        "gia_dinh": "#E1F4EC",
        "hoc_tap": "#FAF0D9",
        "du_phong": "#DCF1F3",
        "huong_thu": "#FBE5EE",
        "tu_do_tai_chinh": "#FCE9DC",
    },
    "toi": {
        "thiet_yeu": "#232C57",
        "gia_dinh": "#133A2E",
        "hoc_tap": "#3A2F12",
        "du_phong": "#0F3538",
        "huong_thu": "#3F1A2C",
        "tu_do_tai_chinh": "#40230F",
    },
}

# Hiệu ứng không phải màu đặc (bóng, lớp mờ sau bottom sheet, kính mờ trên
# gradient đầu trang, nét biểu đồ trắng trong suốt) -- biến CSS --<tên>.
HIEU_UNG: dict[str, dict[str, str]] = {
    "sang": {
        "bong": "0 10px 30px rgba(52, 30, 140, 0.10)",
        "bong-nhe": "0 4px 18px rgba(52, 30, 140, 0.06)",
        "nen-phu": "rgba(20, 14, 50, 0.55)",
        "nen-kinh": "rgba(255, 255, 255, 0.14)",
        "vien-kinh": "rgba(255, 255, 255, 0.40)",
        "luoi-dau": "rgba(255, 255, 255, 0.18)",
        "vung-dau": "rgba(255, 255, 255, 0.16)",
        "net-phu-dau": "rgba(255, 255, 255, 0.75)",
        "cot-mo": "rgba(255, 255, 255, 0.28)",
    },
    "toi": {
        "bong": "0 10px 30px rgba(0, 0, 0, 0.45)",
        "bong-nhe": "0 4px 18px rgba(0, 0, 0, 0.35)",
        "nen-phu": "rgba(0, 0, 0, 0.62)",
        "nen-kinh": "rgba(255, 255, 255, 0.12)",
        "vien-kinh": "rgba(255, 255, 255, 0.34)",
        "luoi-dau": "rgba(255, 255, 255, 0.16)",
        "vung-dau": "rgba(255, 255, 255, 0.12)",
        "net-phu-dau": "rgba(255, 255, 255, 0.70)",
        "cot-mo": "rgba(255, 255, 255, 0.22)",
    },
}

# Thang cỡ chữ mobile-first (như responsive array của theme-ui): "mac_dinh"
# cho mọi màn hình, "rong" ghi đè từ 40em (640px). "nhap" PHẢI giữ 16px: iOS
# Safari tự phóng to trang khi focus ô nhập có chữ < 16px.
CO_CHU: dict[str, dict[str, str]] = {
    "mac_dinh": {
        "nho": "12px",
        "phu": "13px",
        "than": "14px",
        "muc": "16px",
        "trang": "20px",
        "nhap": "16px",
        "so": "clamp(15px, 4vw, 20px)",
        "so-lon": "clamp(18px, 5.6vw, 24px)",
        # /ui mới: "Còn chi được" trên thẻ nổi + ô nhập số tiền ở màn Thêm mới
        "so-noi": "clamp(24px, 7vw, 30px)",
        "so-nhap": "clamp(28px, 9vw, 36px)",
    },
    "rong": {
        "than": "15px",
        "muc": "17px",
    },
}


def _khai_bao(bien: dict[str, str]) -> str:
    return "".join(f"  {ten}: {gia_tri};\n" for ten, gia_tri in bien.items())


def _bien_mau(che_do: str) -> dict[str, str]:
    bien = {f"--mau-{ten}": gia_tri for ten, gia_tri in MAU[che_do].items()}
    bien.update({f"--hu-{ma}": gia_tri for ma, gia_tri in MAU_HU[che_do].items()})
    bien.update({f"--nen-hu-{ma}": gia_tri for ma, gia_tri in MAU_NEN_HU[che_do].items()})
    bien.update({f"--{ten}": gia_tri for ten, gia_tri in HIEU_UNG[che_do].items()})
    return bien


def css_theme() -> str:
    """4 khối: :root (sáng + cỡ chữ) / tối theo hệ điều hành khi KHÔNG ép
    sáng / tối khi ép tối / cỡ chữ màn rộng. Ép chế độ = thuộc tính
    data-theme trên <html> (script trong THE_HEAD + nút đổi ở app/web.py)."""
    co_chu = {f"--co-chu-{ten}": gia_tri for ten, gia_tri in CO_CHU["mac_dinh"].items()}
    co_chu_rong = {f"--co-chu-{ten}": gia_tri for ten, gia_tri in CO_CHU["rong"].items()}
    toi = _khai_bao(_bien_mau("toi"))
    return (
        ":root {\n  color-scheme: light;\n" + _khai_bao(_bien_mau("sang")) + _khai_bao(co_chu) + "}\n"
        "@media (prefers-color-scheme: dark) {\n"
        ':root:not([data-theme="light"]) {\n  color-scheme: dark;\n' + toi + "}\n"
        "}\n"
        ':root[data-theme="dark"] {\n  color-scheme: dark;\n' + toi + "}\n"
        "@media (min-width: 40em) {\n:root {\n" + _khai_bao(co_chu_rong) + "}\n}\n"
    )


# Chạy TRƯỚC khi trình duyệt vẽ trang (nằm trong <head>, trước <style>) --
# như InitializeColorMode của theme-ui, tránh nháy màu khi người dùng đã chọn
# chế độ khác hệ điều hành. try/catch: localStorage có thể bị chặn (chế độ
# riêng tư, WebView trong app) -- khi đó cứ theo hệ điều hành.
_SCRIPT_KHOI_TAO = (
    "<script>(function(){try{var m=localStorage.getItem('" + KHOA_LUU_CHE_DO + "');"
    "if(m==='light'||m==='dark'){document.documentElement.setAttribute('data-theme',m);}}"
    "catch(e){}})();</script>"
)

THE_HEAD = _SCRIPT_KHOI_TAO + "\n<style>\n" + css_theme() + "</style>"
