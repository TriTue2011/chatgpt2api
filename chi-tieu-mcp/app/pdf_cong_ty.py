"""Sinh PDF báo cáo giải chi tạm ứng công ty -- tách riêng khỏi app/tools.py
để test độc lập (không cần DB, chỉ cần dữ liệu đã tính sẵn truyền vào)."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from app.config import BASE_DIR

# Đường dẫn đã xác nhận thực nghiệm (không đoán) sau khi cài gói Debian
# fonts-dejavu-core -- xem Dockerfile. Cùng đường dẫn này cũng có sẵn trên
# host dev (đã verify trực tiếp), nên test chạy được mà không cần build
# Docker trước.
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

THU_MUC_PDF = BASE_DIR / "data" / "tam_ung_pdf"


def duong_dan_pdf(giai_chi_id: int) -> Path:
    """Đường dẫn file PDF của 1 lần giải chi -- xác định hoàn toàn bởi id,
    không cần lưu riêng trong DB (tránh 1 cột dữ liệu suy ra được từ cột
    khác, dễ lệch nếu quên cập nhật đồng thời)."""
    return THU_MUC_PDF / f"giai-chi-{giai_chi_id}.pdf"


def tao_pdf_giai_chi(
    giai_chi_id: int, giao_dich: list, tong_tam_ung: int, tong_chi: int, so_du: int
) -> Path:
    """giao_dich: list các dict/Row có 'thoi_gian', 'loai', 'so_tien', 'mo_ta'.
    Ghi file ra đĩa tại THU_MUC_PDF/giai-chi-<id>.pdf, trả về Path đó."""
    THU_MUC_PDF.mkdir(parents=True, exist_ok=True)

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.add_font("DejaVu", "B", FONT_PATH_BOLD)

    pdf.set_font("DejaVu", "B", 14)
    pdf.cell(0, 10, f"Báo cáo giải chi tạm ứng công ty #{giai_chi_id}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("DejaVu", "", 9)
    # pdf.table() thay vi cell() thu cong -- Nội dung (mo_ta) không có giới
    # hạn độ dài (nhập từ Zalo bot), cell() cố định chiều rộng sẽ để văn bản
    # dài tràn ra ngoài trang thay vì xuống dòng. table() tự wrap và tự tính
    # chiều cao hàng dựa trên nội dung dài nhất trong hàng đó.
    # width=190 + col_widths=(38,25,35,92): giữ đúng layout cột hiện có
    # (trang A4 210mm - lề 10/10 = 190mm khả dụng; 38+25+35=98, còn lại 92
    # cho Nội dung, đúng như cell(0,...) trước đây tự chiếm phần còn lại).
    with pdf.table(
        width=190,
        col_widths=(38, 25, 35, 92),
        text_align="LEFT",
        line_height=8,
        headings_style=FontFace(family="DejaVu", fill_color=(230, 230, 230)),
    ) as table:
        hang_tieu_de = table.row()
        hang_tieu_de.cell("Ngày")
        hang_tieu_de.cell("Loại")
        hang_tieu_de.cell("Số tiền (VNĐ)")
        hang_tieu_de.cell("Nội dung")
        for gd in giao_dich:
            loai_hien_thi = "Tạm ứng" if gd["loai"] == "tam_ung" else "Chi"
            hang = table.row()
            hang.cell(str(gd["thoi_gian"])[:16].replace("T", " "))
            hang.cell(loai_hien_thi)
            hang.cell(f"{gd['so_tien']:,}")
            hang.cell(str(gd["mo_ta"]))

    pdf.ln(6)
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(0, 8, f"Tổng tạm ứng: {tong_tam_ung:,} VNĐ", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Tổng chi: {tong_chi:,} VNĐ", new_x="LMARGIN", new_y="NEXT")
    if so_du >= 0:
        pdf.cell(0, 8, f"Còn dư, phải hoàn công ty: {so_du:,} VNĐ", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 8, f"Chi vượt tạm ứng, công ty hoàn lại: {-so_du:,} VNĐ", new_x="LMARGIN", new_y="NEXT")

    duong_dan = duong_dan_pdf(giai_chi_id)
    pdf.output(str(duong_dan))
    return duong_dan
