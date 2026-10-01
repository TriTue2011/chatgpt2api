"""Entry point: MCP server (Streamable HTTP) + scheduler cảnh báo chủ động.

Đăng ký URL `http://<host>:<MCP_SERVER_PORT>/mcp` vào C2A Settings -> MCP
Servers để bot Zalo hiện có gọi được 11 tool bên dưới khi chat.
"""
from __future__ import annotations

import logging

import asyncio
from typing import Annotated

from apscheduler.schedulers.background import BackgroundScheduler
from mcp.server.fastmcp import FastMCP
from pydantic import BeforeValidator

from app import jars, storage, tools, web
from app.alerts import kiem_tra_va_canh_bao
from app.config import ALERT_CHECK_INTERVAL_SECONDS, MCP_SERVER_PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("chi-tieu-bot")

# host="0.0.0.0" bắt buộc phải truyền tay: FastMCP mặc định host="127.0.0.1"
# khi không truyền, và mcp SDK tự bật DNS-rebinding protection cho đúng
# 127.0.0.1/localhost/::1 -- chặn Host header LAN thật (C2A gọi qua
# <IP-LAN>:8801) bằng 421, dù uvicorn.run() bên dưới đã bind 0.0.0.0.
mcp = FastMCP("chi-tieu-bot", stateless_http=True, host="0.0.0.0")


def _chan_true_false(gia_tri):
    if isinstance(gia_tri, bool):
        raise ValueError("phải là số nguyên (vd 50000), không nhận true/false")
    return gia_tri


# Kiểu cho MỌI tham số số nguyên của tool. pydantic (chế độ lỏng) ép true -> 1:
# `so_tien: true` từng ghi 1 VNĐ (review Hũ âm tự bù 23/09/2026, Rec 4) -- kiểm
# trong tools.py không bắt được vì tới đó giá trị đã là 1. Cố tình KHÔNG dùng
# StrictInt: nó chặn luôn "50000"/50000.0 mà pydantic đang ép đúng (LLM đôi
# khi gửi số dạng chuỗi). Schema LLM thấy vẫn là "integer".
SoNguyen = Annotated[int, BeforeValidator(_chan_true_false)]


@mcp.tool()
def ghi_chi_tieu(hu_ma: str, so_tien: SoNguyen, ghi_chu: str = "",
                 xac_nhan_vuot_tong: bool = False) -> dict:
    """Ghi 1 khoản chi vào 1 hũ ngân sách. MỖI tin báo chi là 1 khoản MỚI: LUÔN
    gọi tool này, kể cả khi lịch sử, tóm tắt hay ký ức đã có khoản giống hệt
    (đổ xăng, ăn sáng hằng ngày). Chỉ nói "đã ghi" khi tool này trả
    da_ghi=true ngay trong lượt này.

    hu_ma: mã hũ — 'thiet_yeu', 'gia_dinh', 'hoc_tap', 'du_phong', 'huong_thu',
    'tu_do_tai_chinh'.
    so_tien: số tiền VNĐ, số nguyên dương.
    ghi_chu: mô tả ngắn, vd 'ăn trưa với đồng nghiệp'.
    xac_nhan_vuot_tong: LUÔN để False ở lần gọi đầu tiên (xem quy tắc CHI VƯỢT
    TỔNG bên dưới).

    Trả về hạn mức/đã chi/còn lại của hũ đó trong tháng để agent báo lại ngay
    cho người dùng, không cần gọi thêm xem_ngan_sach. Hũ chi vượt hạn mức
    riêng được TỰ BÙ từ phần còn dư của các hũ khác (duoc_bu, bu_tu).

    Kết quả luôn có tong_con_lai (tổng còn chi được cả tháng), so_ngay_con_lai
    (số ngày tới kỳ lương) và trung_binh_moi_ngay_con_lai -- LUÔN nêu 3 số này
    trong câu trả lời. Nếu kết quả có canh_bao: PHẢI báo NGUYÊN VĂN cho người
    dùng, đặt ở đầu câu trả lời.

    CHI VƯỢT TỔNG: nếu kết quả có can_xac_nhan=True thì khoản chi CHƯA được
    ghi (vì sẽ làm vượt tổng ngân sách tháng). Đọc canh_bao cho người dùng,
    hỏi họ có chắc đã thực sự chi khoản này không, rồi DỪNG chờ trả lời. Chỉ
    gọi lại tool này (cùng hu_ma, so_tien, ghi_chu) với xac_nhan_vuot_tong=True
    khi người dùng đồng ý rõ ràng ở tin nhắn TIẾP THEO. TUYỆT ĐỐI không đặt
    xac_nhan_vuot_tong=True ngay lần gọi đầu, không tự xác nhận thay người dùng.

    CHI PHÍ ĐẶC BIỆT ĐÃ KHAI BÁO: khoản đã khai báo trước bằng
    khai_bao_chi_phi_dac_biet (vd học phí) ĐÃ bị trừ vào ngân sách lúc khai
    báo. Người dùng báo vừa trả khoản đó thì KHÔNG gọi tool này. Không chắc
    có phải khoản đã khai báo không thì gọi xem_ngan_sach, xem danh sách
    chi_phi_dac_biet_thang_nay trước.

    QUAN TRỌNG: Nếu người dùng mô tả một khoản chi bằng ngôn ngữ CHUNG CHUNG
    có vẻ gộp nhiều mục đích khác nhau (vd "chi tiêu sinh hoạt tháng này",
    "chi linh tinh", liệt kê nhiều món khác loại trong 1 câu), ĐỪNG tự chọn 1
    hũ để gộp hết -- hỏi lại người dùng muốn chia khoản này vào những hũ nào,
    số tiền mỗi hũ bao nhiêu, rồi gọi tool này riêng cho từng hũ. Không cần
    hỏi nếu mô tả rõ ràng 1 việc dù số tiền lớn (vd "đóng học phí 5 triệu" là
    rõ ràng thuộc 1 hũ, không cần chia). Nếu phát hiện 1 khoản ĐÃ ghi lầm kiểu
    này rồi, dùng tool tach_giao_dich để sửa lại thay vì ghi thêm/xoá tay.
    """
    return tools.ghi_chi_tieu(hu_ma, so_tien, ghi_chu, xac_nhan_vuot_tong)


@mcp.tool()
def tach_giao_dich(id: SoNguyen, danh_sach: list[dict]) -> dict:
    """Tách 1 khoản chi ĐÃ GHI (thường do lỡ gộp nhiều mục đích vào 1 hũ)
    thành nhiều dòng theo đúng hũ thực tế.

    id: id khoản chi cần tách (xem qua xem_lich_su để lấy đúng id, hoặc
    người dùng tự cho biết từ lịch sử /ui).
    danh_sach: list các mục {hu_ma, so_tien, ghi_chu}, MỖI mục 1 hũ. Tổng
    so_tien của danh_sach PHẢI đúng bằng số tiền của khoản gốc -- không tự
    làm tròn/chia đều, nếu người dùng chưa cho đủ chi tiết để khớp tổng thì
    hỏi lại thay vì tự đoán.

    Các dòng mới giữ nguyên thời điểm ghi nhận của khoản gốc (không tính vào
    ngày hôm nay), khoản gốc bị xoá sau khi tách thành công.
    """
    return tools.tach_giao_dich(id, danh_sach)


@mcp.tool()
def xem_ngan_sach() -> dict:
    """Xem tổng quan ngân sách tháng hiện tại: hạn mức, đã chi, còn lại của
    từng hũ trong mô hình 6 Hũ (JARS).

    Hạn mức từng hũ (han_muc_thang) ĐÃ tính tự bù: hũ chi vượt được bù từ
    phần còn dư của các hũ khác theo thứ tự ưu tiên (duoc_bu + bu_tu = nhận
    bù từ đâu; da_nhuong = đã nhường cho hũ khác; han_muc_truoc_bu = hạn mức
    riêng trước khi bù). Khi trả lời LUÔN nêu tong_con_lai (tổng còn chi được
    cả tháng) + so_ngay_con_lai + trung_binh_moi_ngay_con_lai. Có
    canh_bao_tong thì báo NGUYÊN VĂN. chi_phi_dac_biet_thang_nay = các khoản
    đã khai báo bằng khai_bao_chi_phi_dac_biet (đã trừ vào ngân sách).

    QUAN TRỌNG: số liệu này đổi sau MỖI giao dịch -- LUÔN gọi tool này để lấy
    số MỚI NHẤT mỗi khi được hỏi còn bao nhiêu tiền/ngân sách, kể cả đã hỏi
    y hệt trong cùng hội thoại. TUYỆT ĐỐI không tự trả lời bằng số đã nói ở
    lượt chat trước hay số nhớ được từ "ký ức dài hạn" -- số đó luôn có thể
    đã lỗi thời hoặc chưa từng được xác minh qua tool.
    """
    return tools.xem_ngan_sach()


@mcp.tool()
def xem_lich_su(thang: str = "") -> dict:
    """Liệt kê các khoản chi tiêu cá nhân đã ghi trong 1 tháng, kèm id của
    từng khoản -- dùng để lấy đúng id trước khi gọi tach_giao_dich.

    thang: định dạng 'YYYY-MM', để trống thì lấy tháng hiện tại.

    Chỉ gồm chi tiêu cá nhân (bảng chi_tieu, cùng phạm vi với
    tach_giao_dich) -- KHÔNG gồm giao dịch công ty hay chi phí đặc biệt đã
    khai báo.
    """
    return tools.xem_lich_su(thang)


@mcp.tool()
def de_xuat_dieu_chinh() -> dict:
    """Phân tích chi tiêu tháng hiện tại, đề xuất hũ nào nên giảm chi (hũ chi
    vượt đã được TỰ BÙ từ các hũ còn dư theo thứ tự ưu tiên cố định --
    KHÔNG khuyên người dùng tự chuyển tiền giữa các hũ). Kèm % phân bổ đề
    xuất theo thuật toán (xu hướng chi 3 tháng, field "phan_bo_de_xuat") và
    lương cố định/thu nhập ngoài lương tách riêng (field
    "luong_co_dinh"/"thu_nhap_ngoai_luong_thang_nay") để tự suy luận hũ nào
    quan trọng hơn khi được hỏi trực tiếp. Không tự sửa hạn mức hay cấu
    hình hũ, chỉ đề xuất bằng lời.

    QUAN TRỌNG: LUÔN gọi tool này để lấy số MỚI NHẤT, không tự trả lời bằng
    số đã nhớ/đã nói trước đó (xem lý do ở docstring xem_ngan_sach)."""
    return tools.de_xuat_dieu_chinh()


@mcp.tool()
def ghi_thu_nhap_them(mo_ta: str, so_tien: SoNguyen) -> dict:
    """Ghi nhận 1 khoản thu nhập phát sinh NGOÀI lương cố định (thưởng, thu
    nhập thêm...). Tự động cộng vào thu nhập hiệu quả của tháng này, làm
    hạn mức MỌI hũ tăng theo đúng tỷ lệ % đang cấu hình — không cần sửa
    jars_config.json.

    mo_ta: mô tả ngắn, vd 'thưởng quý 3'.
    so_tien: số tiền VNĐ, số nguyên dương.

    Trả về hạn mức mới của từng hũ sau khi cộng, để agent báo lại cho
    người dùng biết ảnh hưởng cụ thể.
    """
    return tools.ghi_thu_nhap_them(mo_ta, so_tien)


@mcp.tool()
def ghi_tam_ung_cong_ty(so_tien: SoNguyen, mo_ta: str) -> dict:
    """Ghi nhận 1 khoản công ty tạm ứng (vd đi công tác). Tách biệt hoàn
    toàn khỏi 6 hũ cá nhân -- không ảnh hưởng ngân sách/hạn mức cá nhân.

    so_tien: số tiền VNĐ, số nguyên dương.
    mo_ta: bắt buộc, mô tả ngắn, vd 'đi công tác Đà Nẵng'.

    Trả về số dư tạm ứng công ty hiện tại (dương = đang giữ tiền công ty).
    """
    return tools.ghi_tam_ung_cong_ty(so_tien, mo_ta)


@mcp.tool()
def ghi_chi_cong_ty(so_tien: SoNguyen, mo_ta: str) -> dict:
    """Ghi nhận 1 khoản chi tiêu CÔNG VIỆC cần công ty hoàn ứng (vd taxi
    công tác). KHÁC với ghi_chi_tieu (chi tiêu cá nhân) -- dùng tool này khi
    người dùng nói rõ đây là tiền công ty/công việc, không phải tiền cá
    nhân.

    so_tien: số tiền VNĐ, số nguyên dương.
    mo_ta: bắt buộc, mô tả ngắn, vd 'taxi sân bay công tác'.

    Trả về số dư tạm ứng công ty hiện tại (âm = công ty đang nợ lại).
    """
    return tools.ghi_chi_cong_ty(so_tien, mo_ta)


@mcp.tool()
def xem_so_du_cong_ty() -> dict:
    """Xem số dư tạm ứng công ty hiện tại (kỳ chưa giải chi) -- đang giữ bao
    nhiêu tiền công ty, hay công ty đang nợ lại bao nhiêu.

    Field giao_dich liệt kê TỪNG giao dịch trong kỳ (thoi_gian, loai
    'tam_ung'/'chi', so_tien, mo_ta) -- khi người dùng hỏi chi tiết các khoản,
    liệt kê từ đây, KHÔNG được nói là không có dữ liệu.

    QUAN TRỌNG: LUÔN gọi tool này để lấy số MỚI NHẤT, không tự trả lời bằng
    số đã nhớ/đã nói trước đó (xem lý do ở docstring xem_ngan_sach)."""
    return tools.xem_so_du_cong_ty()


@mcp.tool()
def giai_chi_cong_ty() -> dict:
    """Đóng kỳ tạm ứng công ty hiện tại và xuất báo cáo PDF liệt kê từng
    giao dịch (ngày/loại/số tiền/nội dung) kèm số dư cuối kỳ (dư phải hoàn
    công ty, hoặc thiếu công ty phải hoàn lại). Sau khi giải chi, giao dịch
    trong kỳ đó bị khoá (không sửa/xoá được nữa), kỳ mới bắt đầu trống.

    Trả về link PDF (duong_dan_pdf) để gửi lại cho người dùng mở bằng trình
    duyệt -- KHÔNG gửi được file đính kèm qua Zalo.
    """
    return tools.giai_chi_cong_ty()


@mcp.tool()
def khai_bao_chi_phi_dac_biet(mo_ta: str, so_tien: SoNguyen) -> dict:
    """Khai báo 1 khoản chi lớn biết trước CHỈ PHÁT SINH TRONG THÁNG NÀY (vd
    đóng học phí, viện phí đột xuất). Tự động co hẹp hạn mức hũ Dự Phòng
    trước, không đủ thì co hẹp tiếp Hưởng Thụ, vẫn thiếu thì tự bù tiếp từ
    các hũ khác theo thứ tự ưu tiên -- CHỈ áp dụng đúng tháng này, tháng sau
    tự động hết hiệu lực, không cần thao tác hoàn tác.

    Khai báo = ĐÃ CHI: khoản này bị trừ thẳng vào ngân sách tháng ngay lúc
    khai báo. Khi người dùng trả tiền thật cho khoản đã khai báo, KHÔNG gọi
    ghi_chi_tieu lại (sẽ bị trừ 2 lần) -- chỉ xác nhận là khoản đó đã được
    tính rồi.

    mo_ta: mô tả ngắn, vd 'đóng học phí kỳ 1'.
    so_tien: số tiền VNĐ, số nguyên dương.

    Trả về hạn mức Dự Phòng/Hưởng Thụ đã điều chỉnh để agent báo lại ngay
    cho người dùng.
    """
    return tools.khai_bao_chi_phi_dac_biet(mo_ta, so_tien)


def _vong_kiem_tra_canh_bao_sync() -> None:
    """Wrapper đồng bộ cho APScheduler BackgroundScheduler (chạy ở thread riêng,
    không đụng event loop chính của uvicorn) — asyncio.run() an toàn ở đây vì
    mỗi lần gọi tạo event loop riêng trong thread riêng của scheduler."""
    try:
        da_gui = asyncio.run(kiem_tra_va_canh_bao())
        if da_gui:
            logger.info("Đã gửi %d cảnh báo: %s", len(da_gui), da_gui)
    except Exception:
        logger.exception("Vòng kiểm tra cảnh báo lỗi")


def _khoi_dong_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _vong_kiem_tra_canh_bao_sync,
        "interval",
        seconds=ALERT_CHECK_INTERVAL_SECONDS,
        id="kiem_tra_canh_bao",
    )
    scheduler.start()
    return scheduler


# Khởi tạo DB + scheduler ngay khi module nạp — KHÔNG dùng Starlette on_event
# (bản mới của streamable_http_app() không còn hỗ trợ, xem lịch sử sửa lỗi
# 'Starlette object has no attribute on_event' ngày 16/09/2026).
storage.khoi_tao_db()
# Máy cài mới: tạo data/jars_config.json từ mẫu ngay lúc khởi động (log rõ),
# thay vì đợi request đầu tiên.
jars.dam_bao_co_cau_hinh()
_khoi_dong_scheduler()

web.dang_ky_route(mcp)
app = mcp.streamable_http_app()
logger.info("chi-tieu-bot MCP server sẵn sàng tại /mcp, cổng %d", MCP_SERVER_PORT)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=MCP_SERVER_PORT)
