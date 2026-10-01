"""Route web quản lý (ngoài giao thức MCP): đăng nhập + dashboard + API cho
trang /ui. Đăng ký vào FastMCP qua custom_route trong dang_ky_route() — PHẢI
gọi hàm này TRƯỚC khi main.py tạo `app = mcp.streamable_http_app()` (API xác
nhận từ source `mcp.server.fastmcp.FastMCP.custom_route`: route được gom vào
self._custom_starlette_routes, chỉ được đọc lúc streamable_http_app() build).

Đăng nhập dùng lại C2A_AUTH_KEY có sẵn trong .env (không phải tài khoản Zalo
thật) — tránh thêm 1 bí mật riêng cho UI này, theo yêu cầu người dùng khi
brainstorm (xem docs/superpowers/specs/2026-09-16-quan-ly-ui-design.md).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import date, datetime
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from app import giao_dien, pdf_cong_ty, storage
from app.c2a_client import hoi_ai_phan_tich
from app.config import C2A_AUTH_KEY
from app.jars import doc_cau_hinh, ghi_cau_hinh, ngay_bat_dau_chu_ky, thang_hien_tai, tim_hu
from app.markdown_an_toan import markdown_sang_html
from app.phan_tich_ai import phan_tich_json
from app.tools import (
    de_xuat_dieu_chinh, ghi_chi_cong_ty, ghi_chi_tieu, ghi_tam_ung_cong_ty, ghi_thu_nhap_them,
    giai_chi_cong_ty, tach_giao_dich, xem_ngan_sach,
)

logger = logging.getLogger("chi-tieu-bot.web")

COOKIE_NAME = "chitieu_session"

_TRANG_LOGIN = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Đăng nhập — chi-tieu-bot</title>
__THEME_HEAD__
<style>
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust:100%; text-size-adjust:100%; }
  body { background:var(--mau-nen); color:var(--mau-chu); font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         font-size:var(--co-chu-than); line-height:1.5; display:flex; align-items:center; justify-content:center;
         min-height:100vh; margin:0; padding:16px; }
  :focus-visible { outline:2px solid var(--mau-nhan); outline-offset:2px; }
  .the { background:var(--mau-the); padding:32px 24px; border-radius:12px; width:100%; max-width:320px; }
  h1 { font-size:var(--co-chu-trang); line-height:1.25; margin:0 0 20px; }
  input { width:100%; padding:10px 12px; border-radius:8px; border:1px solid var(--mau-vien-dam);
          background:var(--mau-nen); color:var(--mau-chu); font:inherit; font-size:var(--co-chu-nhap); margin-bottom:12px; }
  input::placeholder { color:var(--mau-chu-phu); opacity:1; }
  button { width:100%; padding:10px; border-radius:8px; border:none; background:var(--mau-nut);
           color:var(--mau-chu-tren-nut); font:inherit; font-weight:600; cursor:pointer; }
  .loi { color:var(--mau-nguy); font-size:var(--co-chu-phu); margin:-4px 0 12px; }
</style>
</head>
<body>
  <form class="the" method="post" action="/ui/dang-nhap">
    <h1>chi-tieu-bot — Quản lý</h1>
    __LOI__
    <input type="password" name="mat_khau" placeholder="Mật khẩu (C2A_AUTH_KEY)" autofocus>
    <button type="submit">Đăng nhập</button>
  </form>
</body>
</html>
""".replace("__THEME_HEAD__", giao_dien.THE_HEAD)

# Trang /ui (4 tab + màn Thêm mới) nằm ở app/trang_ui.html -- ~1700 dòng
# HTML/CSS/JS, quá dài để giữ trong chuỗi Python (spec
# 2026-09-23-thiet-ke-lai-ui-design.md). Đọc 1 lần lúc nạp module rồi thay
# marker như trang đăng nhập; _TRANG_UI vẫn là chuỗi hoàn chỉnh cho test.
_TRANG_UI = (
    (Path(__file__).resolve().parent / "trang_ui.html").read_text(encoding="utf-8")
    .replace("__THEME_HEAD__", giao_dien.THE_HEAD)
    .replace("__KHOA_LUU_CHE_DO__", giao_dien.KHOA_LUU_CHE_DO)
)


def _hash_key() -> str:
    return hashlib.sha256(C2A_AUTH_KEY.encode("utf-8")).hexdigest()


def _da_dang_nhap(request: Request) -> bool:
    if not C2A_AUTH_KEY:
        return False
    # hmac.compare_digest trên str chỉ chấp nhận ASCII, raise TypeError với
    # non-ASCII — encode UTF-8 trước để không crash khi cookie chứa bytes lạ
    # (bất kỳ ai cũng gửi được cookie này, kể cả chưa đăng nhập).
    return hmac.compare_digest(
        request.cookies.get(COOKIE_NAME, "").encode("utf-8"), _hash_key().encode("utf-8")
    )


# Trần giá trị VNĐ chấp nhận từ client -- đủ dư dả cho 1 công cụ ngân sách cá
# nhân (1 nghìn tỷ VNĐ), nhưng chặn được giá trị "thiên văn" (1e308, 10**400,
# Infinity) lọt qua validation rồi làm vỡ tính toán ở downstream:
# Hu.han_muc() (app/jars.py), donut/% trên /ui, VÀ các tool MCP của Zalo bot
# (app/tools.py) -- tất cả đọc lại thu_nhap_thuc_linh_thang từ config sau khi
# nó đã được ghi, không chỉ ngay lúc validate.
GIOI_HAN_SO_TIEN_VND = 10**12
GIOI_HAN_TY_LE_PHAN_TRAM = 100.0
GIOI_HAN_NGAY_CHU_KY = 28.0


def _so_client_hop_le(x, gioi_han: float) -> bool:
    """True nếu x là số (int/float, KHÔNG phải bool) "đàng hoàng" để so sánh/
    tính toán tiếp: nằm trong [-gioi_han, gioi_han]. KHÔNG tự áp đặt dấu
    (dương/không âm) -- nơi gọi tự thêm điều kiện đó theo đúng ngữ nghĩa
    field (vd so_tien phải > 0, ty_le_phan_tram được = 0), SAU khi hàm này đã
    xác nhận x an toàn để so sánh.

    Dùng chung cho thu_nhap_thuc_linh_thang, ty_le_phan_tram (mỗi hũ), và
    so_tien -- validation logic này đã bị lỗi 2 lần vì viết rải rác từng chỗ
    một (I3, rồi round 2 tái phát ở api_sua_chi_tieu), nên giờ chỉ có 1 chỗ.

    Cố tình KHÔNG dùng math.isfinite(x)/math.isnan(x): với 1 int khổng lồ (ví
    dụ 10**400 -- gửi được qua JSON bình thường, httpx/json.loads không chặn),
    math.isfinite() tự nó raise OverflowError khi cố convert sang float trước
    khi kiểm tra hữu hạn -- đây chính là lỗi round 2 của hàm cũ (fix I3 gọi
    math.isfinite() trực tiếp trên input chưa qua bound-check). So sánh trực
    tiếp bằng toán tử quan hệ thì an toàn với MỌI kích thước int (Python so
    sánh int-int / int-float không giới hạn độ lớn, không bao giờ raise
    OverflowError -- đã verify thực nghiệm) và tự động loại cả NaN (NaN so
    sánh với bất kỳ số nào bằng <, <=, >, >= đều False) lẫn Infinity (luôn
    nằm ngoài mọi khoảng hữu hạn) mà không cần gọi math.isfinite/isnan.
    """
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    if x != x:  # NaN -- phòng thủ kép, dù so sánh khoảng bên dưới cũng tự loại NaN
        return False
    return -gioi_han <= x <= gioi_han


async def trang_login(request: Request) -> Response:
    if not C2A_AUTH_KEY:
        loi = '<p class="loi">Chưa cấu hình C2A_AUTH_KEY trong .env trên server.</p>'
        return HTMLResponse(_TRANG_LOGIN.replace("__LOI__", loi))
    return HTMLResponse(_TRANG_LOGIN.replace("__LOI__", ""))


async def dang_nhap(request: Request) -> Response:
    if not C2A_AUTH_KEY:
        loi = '<p class="loi">Chưa cấu hình C2A_AUTH_KEY trong .env trên server.</p>'
        # 503 (Service Unavailable) đúng nghĩa hơn 500 cho "thiếu cấu hình" --
        # không phải lỗi bất ngờ, mà là trạng thái server biết trước.
        return HTMLResponse(_TRANG_LOGIN.replace("__LOI__", loi), status_code=503)
    form = await request.form()
    mat_khau = str(form.get("mat_khau", ""))
    # Cùng lý do encode như _da_dang_nhap() — mật khẩu sai có dấu tiếng Việt
    # trước đây làm crash 500 thay vì trả 401.
    if not hmac.compare_digest(mat_khau.encode("utf-8"), C2A_AUTH_KEY.encode("utf-8")):
        loi = '<p class="loi">Sai mật khẩu.</p>'
        return HTMLResponse(_TRANG_LOGIN.replace("__LOI__", loi), status_code=401)
    resp = RedirectResponse("/ui", status_code=303)
    resp.set_cookie(COOKIE_NAME, _hash_key(), httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return resp


async def dang_xuat(request: Request) -> Response:
    resp = RedirectResponse("/ui/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


async def trang_chinh(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return RedirectResponse("/ui/login", status_code=303)
    return HTMLResponse(_TRANG_UI)


async def api_ngan_sach(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    ket_qua = xem_ngan_sach()
    # Ngày đầu kỳ hiện tại cho biểu đồ theo ngày trên /ui -- nhãn kỳ là tháng
    # BẮT ĐẦU kỳ (jars.nhan_dang_chu_ky) nên đầu kỳ = ngày chu kỳ của tháng đó.
    # Chỉ thêm ở tầng web, không đổi output tool MCP.
    ket_qua["ngay_bat_dau_ky_nay"] = f"{ket_qua['thang']}-{ngay_bat_dau_chu_ky():02d}"
    return JSONResponse(ket_qua)


async def api_lich_su(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    thang = request.query_params.get("thang") or thang_hien_tai()
    if not re.fullmatch(r"\d{4}-\d{2}", thang):
        return JSONResponse({"loi": "thang phải đúng định dạng YYYY-MM"}, status_code=400)
    giao_dich = [dict(r) for r in storage.danh_sach_chi_trong_thang(thang)]
    tong_tien = sum(r["so_tien"] for r in giao_dich)
    return JSONResponse({
        "thang": thang,
        "giao_dich": giao_dich,
        "so_luong": len(giao_dich),
        "tong_tien": tong_tien,
        "trung_binh_3_thang": storage.trung_binh_chi_3_thang_truoc(thang),
    })


async def api_thu_nhap_them(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    thang = request.query_params.get("thang") or thang_hien_tai()
    if not re.fullmatch(r"\d{4}-\d{2}", thang):
        return JSONResponse({"loi": "thang phải đúng định dạng YYYY-MM"}, status_code=400)
    danh_sach = [dict(r) for r in storage.danh_sach_thu_nhap_them_trong_thang(thang)]
    return JSONResponse({
        "thang": thang,
        "danh_sach": danh_sach,
        "tong_tien": sum(r["so_tien"] for r in danh_sach),
    })


async def api_de_xuat(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    return JSONResponse(de_xuat_dieu_chinh())


def _tien(so: int) -> str:
    return f"{so:,}".replace(",", ".") + "đ"


def _ngay_thang(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m")


async def api_hoi_ai_phan_tich(request: Request) -> Response:
    """Thẻ "Phân tích AI" (tab Phân bổ của /ui): xin AI trả JSON có cấu trúc
    (app/phan_tich_ai.py); AI không trả được JSON hợp lệ thì lùi về markdown
    -> HTML an toàn như trước (phan_tich_html)."""
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    de_xuat = de_xuat_dieu_chinh()
    ngan_sach = xem_ngan_sach()
    phan_bo = {d["ma"]: d["ty_le_phan_tram"] for d in de_xuat["phan_bo_de_xuat"]["de_xuat"]}
    cac_ma = [h["ma"] for h in de_xuat["chi_tiet"]]
    dong_hu = "\n".join(
        f"- {h['ma']} | {h['ten']} | cấu hình {h['ty_le_phan_tram']}% | đề xuất thuật toán "
        f"{phan_bo.get(h['ma'], h['ty_le_phan_tram'])}% | hạn mức {_tien(h['han_muc_thang'])} | "
        f"đã chi {_tien(h['da_chi'])} | còn lại {_tien(h['con_lai'])} | được bù {_tien(h['duoc_bu'])} | "
        f"đã nhường {_tien(h['da_nhuong'])}"
        for h in de_xuat["chi_tiet"]
    )
    bat_dau = f"{ngan_sach['thang']}-{ngay_bat_dau_chu_ky():02d}"
    prompt = (
        f"Đây là ngân sách cá nhân kỳ lương {ngan_sach['thang']} (từ {_ngay_thang(bat_dau)} tới trước "
        f"{_ngay_thang(ngan_sach['ngay_bat_dau_ky_sau'])}, còn {ngan_sach['so_ngay_con_lai']} ngày) "
        f"theo mô hình 6 Hũ (JARS).\n"
        f"Lương cố định: {_tien(de_xuat['luong_co_dinh'])}. Thu nhập ngoài lương kỳ này: "
        f"{_tien(de_xuat['thu_nhap_ngoai_luong_thang_nay'])}. Chi phí đặc biệt đã khai báo (đã trừ "
        f"vào ngân sách): {_tien(ngan_sach['tong_chi_phi_dac_biet_thang_nay'])}.\n"
        f"Tổng ngân sách: {_tien(ngan_sach['tong_ngan_sach'])}. Đã chi: {_tien(ngan_sach['tong_da_chi'])}. "
        f"Còn chi được: {_tien(ngan_sach['tong_con_lai'])} "
        f"(~{_tien(ngan_sach['trung_binh_moi_ngay_con_lai'])}/ngày).\n"
        f"Từng hũ (mã | tên | % cấu hình | % đề xuất thuật toán theo xu hướng chi 3 kỳ | hạn mức "
        f"sau tự bù | đã chi | còn lại | được bù | đã nhường cho hũ khác):\n{dong_hu}\n\n"
        f"Hãy: (1) đánh giá từng hũ -- mức độ quan trọng suy từ TÊN hũ và tình hình chi thực tế; "
        f"(2) tóm tắt tình hình kỳ này trong 1-2 câu; (3) việc nên làm ngay, tối đa 5 việc cụ thể "
        f"có số tiền; (4) tỉ lệ % gợi ý cho kỳ sau cho ĐỦ các mã hũ trên, tổng đúng 100.\n"
        f"Chỉ trả lời bằng đúng một object JSON hợp lệ, không markdown, không chữ nào ngoài JSON, đúng dạng:\n"
        f'{{"tom_tat": "...", "tung_hu": [{{"ma": "<mã hũ>", "danh_gia": "<tối đa 3 từ, vd Ổn / '
        f'Sắp hết / Vượt / Đã nhường hết / Còn nguyên>", "nhan_xet": "<1 câu ngắn>"}}], '
        f'"nen_lam": ["..."], "ty_le_goi_y": {{"<mã hũ>": <số %>}}}}\n'
        f"Viết tiếng Việt, ngắn gọn cho màn hình điện thoại."
    )
    try:
        phan_tich = await hoi_ai_phan_tich(prompt)
    except Exception:
        # KHÔNG trả lỗi thật về client -- có thể lộ C2A_BASE_URL nội bộ (vd
        # từ httpx.HTTPStatusError) hoặc KeyError repr. Log đầy đủ để debug,
        # trả thông báo cố định chung chung cho client (Fix 5 review).
        logger.warning("Hỏi AI phân tích thất bại", exc_info=True)
        return JSONResponse({"loi": "Không gọi được AI, thử lại sau."}, status_code=502)
    cau_truc = phan_tich_json(phan_tich, cac_ma)
    ket_qua = {
        "phan_tich": phan_tich,
        "phan_tich_cau_truc": cau_truc,
        "thang": ngan_sach["thang"],
        "thoi_gian": datetime.now().isoformat(timespec="seconds"),
    }
    if cau_truc is None:
        # Đổi sang HTML ở server (escape trước, chỉ sinh thẻ cố định -- xem
        # app/markdown_an_toan.py) để /ui gán innerHTML an toàn.
        ket_qua["phan_tich_html"] = markdown_sang_html(phan_tich)
    return JSONResponse(ket_qua)


async def api_cau_hinh(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"loi": "body phải là JSON hợp lệ"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"loi": "body phải là object JSON"}, status_code=400)

    thu_nhap = body.get("thu_nhap_thuc_linh_thang")
    hu = body.get("hu")
    ngay_bat_dau_chu_ky = body.get("ngay_bat_dau_chu_ky")
    if not _so_client_hop_le(thu_nhap, GIOI_HAN_SO_TIEN_VND) or thu_nhap <= 0:
        return JSONResponse({"loi": "thu_nhap_thuc_linh_thang phải là số dương"}, status_code=400)
    if (
        isinstance(ngay_bat_dau_chu_ky, bool)
        or not isinstance(ngay_bat_dau_chu_ky, int)
        or not _so_client_hop_le(ngay_bat_dau_chu_ky, GIOI_HAN_NGAY_CHU_KY)
        or ngay_bat_dau_chu_ky < 1
    ):
        return JSONResponse(
            {"loi": "ngay_bat_dau_chu_ky phải là số nguyên từ 1 đến 28"}, status_code=400
        )
    if not isinstance(hu, list) or not hu:
        return JSONResponse({"loi": "hu phải là danh sách không rỗng"}, status_code=400)
    if not all(isinstance(muc, dict) for muc in hu):
        return JSONResponse({"loi": "mỗi mục trong hu phải là object"}, status_code=400)
    if not all(isinstance(muc.get("ma"), str) for muc in hu):
        # isinstance(muc, dict) ở trên chỉ validate container -- ma vẫn có thể
        # là list/dict/số/None, khiến set(hu_codes) bên dưới raise
        # TypeError: unhashable type (nếu list/dict) hoặc âm thầm không khớp
        # mã hũ thật nào (nếu số/None).
        return JSONResponse({"loi": "mã hũ (ma) phải là chuỗi"}, status_code=400)

    cau_hinh_cu = doc_cau_hinh()
    ten_theo_ma = {h["ma"]: h["ten"] for h in cau_hinh_cu["hu"]}
    hu_codes = [m.get("ma") for m in hu]
    if len(hu) != len(set(hu_codes)) or set(ten_theo_ma) != set(hu_codes):
        return JSONResponse({"loi": "phải gửi đủ và đúng các mã hũ hiện có"}, status_code=400)

    tong_ty_le = 0.0
    hu_moi = []
    for muc in hu:
        ma = muc.get("ma")
        ty_le = muc.get("ty_le_phan_tram")
        if not _so_client_hop_le(ty_le, GIOI_HAN_TY_LE_PHAN_TRAM) or ty_le < 0:
            return JSONResponse({"loi": f"ty_le_phan_tram không hợp lệ cho hũ {ma}"}, status_code=400)
        tong_ty_le += ty_le
        hu_moi.append({"ma": ma, "ten": ten_theo_ma[ma], "ty_le_phan_tram": ty_le})

    if round(tong_ty_le, 1) != 100.0:
        return JSONResponse(
            {"loi": f"tổng tỷ lệ phải = 100%, hiện tại {tong_ty_le:.1f}%"}, status_code=400
        )

    ghi_cau_hinh({
        **cau_hinh_cu,
        "thu_nhap_thuc_linh_thang": int(thu_nhap),
        "hu": hu_moi,
        "nguong_canh_bao": cau_hinh_cu.get("nguong_canh_bao", [0.65, 0.8, 1.0]),
        "ngay_bat_dau_chu_ky": ngay_bat_dau_chu_ky,
    })
    return JSONResponse({"ok": True})


async def api_sua_chi_tieu(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"loi": "body phải là object JSON"}, status_code=400)
    so_tien = body.get("so_tien")
    ghi_chu = body.get("ghi_chu")
    hu_ma = body.get("hu_ma")
    # Task 1's storage.sua_chi_tieu() trả True vô điều kiện nếu cả 3 field đều
    # None (không check id) -- chặn ở đây để giữ đúng hợp đồng 404 khi id
    # không tồn tại, thay vì âm thầm trả 200.
    if so_tien is None and ghi_chu is None and hu_ma is None:
        return JSONResponse({"loi": "phải có ít nhất 1 trường để sửa"}, status_code=400)
    if so_tien is not None and (
        isinstance(so_tien, bool)
        or not isinstance(so_tien, int)
        or not _so_client_hop_le(so_tien, GIOI_HAN_SO_TIEN_VND)
        or so_tien <= 0
    ):
        return JSONResponse({"loi": "so_tien phải là số nguyên dương"}, status_code=400)
    if ghi_chu is not None and not isinstance(ghi_chu, str):
        return JSONResponse({"loi": "ghi_chu phải là chuỗi"}, status_code=400)
    if hu_ma is not None and tim_hu(hu_ma) is None:
        return JSONResponse({"loi": f"mã hũ không tồn tại: {hu_ma}"}, status_code=400)
    ok = storage.sua_chi_tieu(id_khoan, so_tien=so_tien, ghi_chu=ghi_chu, hu_ma=hu_ma)
    if not ok:
        return JSONResponse({"loi": "khoản chi không tồn tại"}, status_code=404)
    return JSONResponse({"ok": True})


async def api_xoa_chi_tieu(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    ok = storage.xoa_chi_tieu(id_khoan)
    if not ok:
        return JSONResponse({"loi": "khoản chi không tồn tại"}, status_code=404)
    return JSONResponse({"ok": True})


async def api_tach_giao_dich(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict) or not isinstance(body.get("danh_sach"), list):
        return JSONResponse({"loi": "body phải có field 'danh_sach' dạng list"}, status_code=400)
    ket_qua = tach_giao_dich(id_khoan, body["danh_sach"])
    if "loi" in ket_qua:
        return JSONResponse(ket_qua, status_code=400)
    return JSONResponse(ket_qua)


async def api_cong_ty(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    return JSONResponse({
        "so_du": storage.so_du_cong_ty(),
        "giao_dich_dang_mo": [dict(r) for r in storage.danh_sach_giao_dich_cong_ty_dang_mo()],
        "lich_su_giai_chi": [dict(r) for r in storage.danh_sach_lan_giai_chi()],
    })


async def api_sua_giao_dich_cong_ty(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    hang = storage.giao_dich_cong_ty_theo_id(id_khoan)
    if hang is None:
        return JSONResponse({"loi": "giao dịch không tồn tại"}, status_code=404)
    if hang["giai_chi_id"] is not None:
        return JSONResponse(
            {"loi": "giao dịch đã bị khoá bởi 1 lần giải chi, không thể sửa"}, status_code=400
        )
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"loi": "body phải là object JSON"}, status_code=400)
    so_tien = body.get("so_tien")
    mo_ta = body.get("mo_ta")
    if so_tien is None and mo_ta is None:
        return JSONResponse({"loi": "phải có ít nhất 1 trường để sửa"}, status_code=400)
    if so_tien is not None and (
        isinstance(so_tien, bool)
        or not isinstance(so_tien, int)
        or not _so_client_hop_le(so_tien, GIOI_HAN_SO_TIEN_VND)
        or so_tien <= 0
    ):
        return JSONResponse({"loi": "so_tien phải là số nguyên dương"}, status_code=400)
    if mo_ta is not None and (not isinstance(mo_ta, str) or not mo_ta.strip()):
        return JSONResponse({"loi": "mo_ta phải là chuỗi không rỗng"}, status_code=400)
    if mo_ta is not None and len(mo_ta) > 500:
        return JSONResponse({"loi": "mo_ta quá dài, tối đa 500 ký tự"}, status_code=400)
    storage.sua_giao_dich_cong_ty(id_khoan, so_tien=so_tien, mo_ta=mo_ta)
    return JSONResponse({"ok": True})


async def api_xoa_giao_dich_cong_ty(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    hang = storage.giao_dich_cong_ty_theo_id(id_khoan)
    if hang is None:
        return JSONResponse({"loi": "giao dịch không tồn tại"}, status_code=404)
    if hang["giai_chi_id"] is not None:
        return JSONResponse(
            {"loi": "giao dịch đã bị khoá bởi 1 lần giải chi, không thể xoá"}, status_code=400
        )
    storage.xoa_giao_dich_cong_ty(id_khoan)
    return JSONResponse({"ok": True})


async def api_giai_chi_cong_ty(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    ket_qua = giai_chi_cong_ty()
    if "loi" in ket_qua:
        return JSONResponse(ket_qua, status_code=400)
    return JSONResponse(ket_qua)


async def trang_pdf_giai_chi(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        giai_chi_id = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    duong_dan = pdf_cong_ty.duong_dan_pdf(giai_chi_id)
    if not duong_dan.exists():
        lan_giai_chi = storage.lan_giai_chi_theo_id(giai_chi_id)
        if lan_giai_chi is None:
            return JSONResponse({"loi": "không tìm thấy file PDF"}, status_code=404)
        # File co the da mat (thu muc data/tam_ung_pdf/ khong duoc backup,
        # gitignored) nhung ban ghi giai_chi_cong_ty van con -- sinh lai tu
        # du lieu da co trong DB thay vi 404 vinh vien.
        giao_dich = storage.giao_dich_theo_lan_giai_chi(giai_chi_id)
        try:
            pdf_cong_ty.tao_pdf_giai_chi(
                giai_chi_id, giao_dich, lan_giai_chi["tong_tam_ung"],
                lan_giai_chi["tong_chi"], lan_giai_chi["so_du"],
            )
        except Exception:
            return JSONResponse({"loi": "không tạo được file PDF"}, status_code=500)
    return FileResponse(duong_dan, media_type="application/pdf")


async def api_chi_phi_dac_biet(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    thang = request.query_params.get("thang") or thang_hien_tai()
    if not re.fullmatch(r"\d{4}-\d{2}", thang):
        return JSONResponse({"loi": "thang phải đúng định dạng YYYY-MM"}, status_code=400)
    danh_sach = [dict(r) for r in storage.danh_sach_chi_phi_dac_biet_trong_thang(thang)]
    return JSONResponse({
        "thang": thang,
        "danh_sach": danh_sach,
        "tong_tien": sum(r["so_tien"] for r in danh_sach),
    })


async def api_sua_chi_phi_dac_biet(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"loi": "body phải là object JSON"}, status_code=400)
    so_tien = body.get("so_tien")
    mo_ta = body.get("mo_ta")
    if so_tien is None and mo_ta is None:
        return JSONResponse({"loi": "phải có ít nhất 1 trường để sửa"}, status_code=400)
    if so_tien is not None and (
        isinstance(so_tien, bool)
        or not isinstance(so_tien, int)
        or not _so_client_hop_le(so_tien, GIOI_HAN_SO_TIEN_VND)
        or so_tien <= 0
    ):
        return JSONResponse({"loi": "so_tien phải là số nguyên dương"}, status_code=400)
    if mo_ta is not None and (not isinstance(mo_ta, str) or not mo_ta.strip()):
        return JSONResponse({"loi": "mo_ta phải là chuỗi không rỗng"}, status_code=400)
    ok = storage.sua_chi_phi_dac_biet(id_khoan, so_tien=so_tien, mo_ta=mo_ta)
    if not ok:
        return JSONResponse({"loi": "khoản chi phí đặc biệt không tồn tại"}, status_code=404)
    return JSONResponse({"ok": True})


async def api_xoa_chi_phi_dac_biet(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    ok = storage.xoa_chi_phi_dac_biet(id_khoan)
    if not ok:
        return JSONResponse({"loi": "khoản chi phí đặc biệt không tồn tại"}, status_code=404)
    return JSONResponse({"ok": True})


def _lui_nhan_thang(nhan: str, so_thang: int) -> str:
    """'YYYY-MM' lùi so_thang tháng (nhãn kỳ lương cũng là 'YYYY-MM')."""
    nam, thang = (int(x) for x in nhan.split("-"))
    tong = nam * 12 + (thang - 1) - so_thang
    return f"{tong // 12:04d}-{tong % 12 + 1:02d}"


def _la_so_tien(x) -> bool:
    return (not isinstance(x, bool) and isinstance(x, int)
            and _so_client_hop_le(x, GIOI_HAN_SO_TIEN_VND) and x > 0)


async def _body_object(request: Request) -> dict | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


async def api_them_chi_tieu(request: Request) -> Response:
    """Thêm khoản chi từ nút + của /ui. Đi qua đúng tools.ghi_chi_tieu (cổng
    vượt tổng của server): chưa xác nhận thì trả can_xac_nhan, KHÔNG ghi."""
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    body = await _body_object(request)
    if body is None:
        return JSONResponse({"loi": "body phải là object JSON"}, status_code=400)
    hu_ma = body.get("hu_ma")
    so_tien = body.get("so_tien")
    ghi_chu = body.get("ghi_chu", "")
    xac_nhan = body.get("xac_nhan_vuot_tong", False)
    if not isinstance(hu_ma, str) or tim_hu(hu_ma) is None:
        return JSONResponse({"loi": "mã hũ không tồn tại"}, status_code=400)
    if not _la_so_tien(so_tien):
        return JSONResponse({"loi": "so_tien phải là số nguyên dương"}, status_code=400)
    if not isinstance(ghi_chu, str):
        return JSONResponse({"loi": "ghi_chu phải là chuỗi"}, status_code=400)
    if not isinstance(xac_nhan, bool):
        return JSONResponse({"loi": "xac_nhan_vuot_tong phải là true/false"}, status_code=400)
    ket_qua = ghi_chi_tieu(hu_ma, so_tien, ghi_chu.strip(), xac_nhan, nguon="ui")
    if "loi" in ket_qua:
        return JSONResponse(ket_qua, status_code=400)
    return JSONResponse(ket_qua)


async def api_them_thu_nhap_them(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    body = await _body_object(request)
    if body is None:
        return JSONResponse({"loi": "body phải là object JSON"}, status_code=400)
    mo_ta = body.get("mo_ta")
    so_tien = body.get("so_tien")
    if not isinstance(mo_ta, str) or not mo_ta.strip():
        return JSONResponse({"loi": "mo_ta phải là chuỗi không rỗng"}, status_code=400)
    if not _la_so_tien(so_tien):
        return JSONResponse({"loi": "so_tien phải là số nguyên dương"}, status_code=400)
    ket_qua = ghi_thu_nhap_them(mo_ta.strip(), so_tien)
    if "loi" in ket_qua:
        return JSONResponse(ket_qua, status_code=400)
    return JSONResponse(ket_qua)


async def api_sua_thu_nhap_them(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    body = await _body_object(request)
    if body is None:
        return JSONResponse({"loi": "body phải là object JSON"}, status_code=400)
    so_tien = body.get("so_tien")
    mo_ta = body.get("mo_ta")
    if so_tien is None and mo_ta is None:
        return JSONResponse({"loi": "phải có ít nhất 1 trường để sửa"}, status_code=400)
    if so_tien is not None and not _la_so_tien(so_tien):
        return JSONResponse({"loi": "so_tien phải là số nguyên dương"}, status_code=400)
    if mo_ta is not None and (not isinstance(mo_ta, str) or not mo_ta.strip()):
        return JSONResponse({"loi": "mo_ta phải là chuỗi không rỗng"}, status_code=400)
    ok = storage.sua_thu_nhap_them(id_khoan, so_tien=so_tien,
                                   mo_ta=mo_ta.strip() if mo_ta is not None else None)
    if not ok:
        return JSONResponse({"loi": "khoản thu nhập không tồn tại"}, status_code=404)
    return JSONResponse({"ok": True})


async def api_xoa_thu_nhap_them(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    try:
        id_khoan = int(request.path_params["id"])
    except (KeyError, ValueError):
        return JSONResponse({"loi": "id không hợp lệ"}, status_code=400)
    if not storage.xoa_thu_nhap_them(id_khoan):
        return JSONResponse({"loi": "khoản thu nhập không tồn tại"}, status_code=404)
    return JSONResponse({"ok": True})


async def api_them_giao_dich_cong_ty(request: Request) -> Response:
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    body = await _body_object(request)
    if body is None:
        return JSONResponse({"loi": "body phải là object JSON"}, status_code=400)
    loai = body.get("loai")
    so_tien = body.get("so_tien")
    mo_ta = body.get("mo_ta")
    if loai not in ("tam_ung", "chi"):
        return JSONResponse({"loi": "loai phải là 'tam_ung' hoặc 'chi'"}, status_code=400)
    if not _la_so_tien(so_tien):
        return JSONResponse({"loi": "so_tien phải là số nguyên dương"}, status_code=400)
    if not isinstance(mo_ta, str) or not mo_ta.strip():
        return JSONResponse({"loi": "mo_ta phải là chuỗi không rỗng"}, status_code=400)
    ghi = ghi_tam_ung_cong_ty if loai == "tam_ung" else ghi_chi_cong_ty
    ket_qua = ghi(so_tien, mo_ta.strip())
    if "loi" in ket_qua:
        return JSONResponse(ket_qua, status_code=400)
    return JSONResponse(ket_qua)


async def api_thong_ke_ky(request: Request) -> Response:
    """Tổng chi so_ky kỳ gần nhất (cũ -> mới, kết thúc ở kỳ hiện tại) + tổng
    theo ngày của kỳ hiện tại -- cho biểu đồ Theo kỳ/Theo ngày + donut kỳ
    trước trên /ui. Chỉ bảng chi_tieu (chi phí đặc biệt đã trừ sẵn vào mức dự
    chi, không phải khoản chi của hũ nào)."""
    if not _da_dang_nhap(request):
        return JSONResponse({"loi": "chua dang nhap"}, status_code=401)
    so_ky_raw = request.query_params.get("so_ky", "6")
    if not re.fullmatch(r"\d{1,2}", so_ky_raw) or not 1 <= int(so_ky_raw) <= 12:
        return JSONResponse({"loi": "so_ky phải từ 1 đến 12"}, status_code=400)
    hien_tai = thang_hien_tai()
    ky = []
    for lui in range(int(so_ky_raw) - 1, -1, -1):
        thang = _lui_nhan_thang(hien_tai, lui)
        theo_hu = storage.tong_chi_theo_hu_trong_thang(thang)
        ky.append({"thang": thang, "tong_chi": sum(theo_hu.values()), "theo_hu": theo_hu})
    theo_ngay = [{"ngay": ngay, "tong": tong}
                 for ngay, tong in storage.tong_chi_theo_ngay_trong_thang(hien_tai)]
    return JSONResponse({"ky": ky, "theo_ngay": theo_ngay})


def dang_ky_route(mcp) -> None:
    """Đăng ký toàn bộ route web vào FastMCP. Gọi TRƯỚC main.py tạo
    app = mcp.streamable_http_app()."""
    mcp.custom_route("/ui/login", methods=["GET"])(trang_login)
    mcp.custom_route("/ui/dang-nhap", methods=["POST"])(dang_nhap)
    mcp.custom_route("/ui/dang-xuat", methods=["POST"])(dang_xuat)
    mcp.custom_route("/ui", methods=["GET"])(trang_chinh)
    mcp.custom_route("/api/ngan-sach", methods=["GET"])(api_ngan_sach)
    mcp.custom_route("/api/lich-su", methods=["GET"])(api_lich_su)
    mcp.custom_route("/api/thu-nhap-them", methods=["GET"])(api_thu_nhap_them)
    mcp.custom_route("/api/de-xuat", methods=["GET"])(api_de_xuat)
    mcp.custom_route("/api/de-xuat/hoi-ai", methods=["POST"])(api_hoi_ai_phan_tich)
    mcp.custom_route("/api/cau-hinh", methods=["POST"])(api_cau_hinh)
    mcp.custom_route("/api/chi-tieu", methods=["POST"])(api_them_chi_tieu)
    mcp.custom_route("/api/thu-nhap-them", methods=["POST"])(api_them_thu_nhap_them)
    mcp.custom_route("/api/thu-nhap-them/{id}", methods=["PATCH"])(api_sua_thu_nhap_them)
    mcp.custom_route("/api/thu-nhap-them/{id}", methods=["DELETE"])(api_xoa_thu_nhap_them)
    mcp.custom_route("/api/cong-ty/giao-dich", methods=["POST"])(api_them_giao_dich_cong_ty)
    mcp.custom_route("/api/thong-ke-ky", methods=["GET"])(api_thong_ke_ky)
    mcp.custom_route("/api/chi-tieu/{id}", methods=["PATCH"])(api_sua_chi_tieu)
    mcp.custom_route("/api/chi-tieu/{id}", methods=["DELETE"])(api_xoa_chi_tieu)
    mcp.custom_route("/api/chi-tieu/{id}/tach", methods=["POST"])(api_tach_giao_dich)
    mcp.custom_route("/api/cong-ty", methods=["GET"])(api_cong_ty)
    mcp.custom_route("/api/cong-ty/giao-dich/{id}", methods=["PATCH"])(api_sua_giao_dich_cong_ty)
    mcp.custom_route("/api/cong-ty/giao-dich/{id}", methods=["DELETE"])(api_xoa_giao_dich_cong_ty)
    mcp.custom_route("/api/cong-ty/giai-chi", methods=["POST"])(api_giai_chi_cong_ty)
    mcp.custom_route("/api/chi-phi-dac-biet", methods=["GET"])(api_chi_phi_dac_biet)
    mcp.custom_route("/api/chi-phi-dac-biet/{id}", methods=["PATCH"])(api_sua_chi_phi_dac_biet)
    mcp.custom_route("/api/chi-phi-dac-biet/{id}", methods=["DELETE"])(api_xoa_chi_phi_dac_biet)
    mcp.custom_route("/ui/tam-ung/{id}/pdf", methods=["GET"])(trang_pdf_giai_chi)
