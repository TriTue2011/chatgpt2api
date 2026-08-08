"""Hàng rào cho tài liệu (PDF / DOCX / PPTX / XLSX / EPUB) trước khi giải nén.

Cùng loại lỗi với ảnh bom nén, chỉ khác định dạng. `.docx`, `.pptx`, `.xlsx`,
`.epub` đều là **file ZIP**; một ZIP 40 KB có thể khai báo vài GB dữ liệu sau
giải nén. MarkItDown/OCR giải nén thật, nên trần byte ở tầng upload không thấy
gì — file thật sự nhỏ.

Kiểm rẻ trước khi đụng tới thư viện nặng:
1. ZIP: đọc BẢNG MỤC LỤC (`infolist`) — chỉ vài KB, không giải nén — rồi chặn
   theo số entry, tổng dung lượng sau giải nén, và **tỉ lệ nén**. Tỉ lệ mới là
   dấu hiệu đặc trưng của bom: tài liệu thật hiếm khi vượt 100:1, còn bom nén
   thường 1000:1 trở lên.
2. PDF: đếm số trang bằng cách quét chuỗi trong bytes, không dựng lại tài liệu.
3. Tên entry: chặn `..` và đường dẫn tuyệt đối (zip-slip) — MarkItDown không
   giải nén ra đĩa, nhưng nhánh OCR/tiện ích khác có thể.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile

logger = logging.getLogger(__name__)

# Tài liệu thật lớn nhất còn hợp lý (giáo trình quét ảnh vài trăm trang).
MAX_DOC_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 5_000
MAX_ZIP_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ZIP_RATIO = 150          # tổng-sau-giải-nén / kích-thước-file
MAX_PDF_PAGES = 3_000

_PDF_PAGE = re.compile(rb"/Type\s*/Page[^s]")


class DocRejected(ValueError):
    """Tài liệu bị từ chối ở biên. `.ly_do` là câu tiếng Việt cho người dùng."""

    def __init__(self, ly_do: str) -> None:
        self.ly_do = ly_do
        super().__init__(ly_do)


def _kiem_zip(raw: bytes, nhan: str) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        muc = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise DocRejected(f"Tệp{nhan} không phải ZIP hợp lệ: {exc}") from exc

    if len(muc) > MAX_ZIP_ENTRIES:
        raise DocRejected(
            f"Tài liệu{nhan} có quá nhiều thành phần: {len(muc)}, trần {MAX_ZIP_ENTRIES}."
        )

    tong = 0
    for m in muc:
        ten = m.filename or ""
        if ten.startswith("/") or ".." in ten.replace("\\", "/").split("/"):
            raise DocRejected(f"Tài liệu{nhan} chứa đường dẫn không hợp lệ: {ten[:80]!r}")
        tong += int(m.file_size or 0)
        if tong > MAX_ZIP_TOTAL_BYTES:
            raise DocRejected(
                f"Tài liệu{nhan} giải nén ra quá lớn: >{MAX_ZIP_TOTAL_BYTES // (1024 * 1024)}MB."
            )

    if raw and tong // max(1, len(raw)) > MAX_ZIP_RATIO:
        raise DocRejected(
            f"Tài liệu{nhan} có tỉ lệ nén bất thường: {tong // max(1, len(raw))}:1 "
            f"(trần {MAX_ZIP_RATIO}:1). Đây là dấu hiệu của tệp bom nén."
        )


def _kiem_pdf(raw: bytes, nhan: str) -> None:
    so_trang = len(_PDF_PAGE.findall(raw))
    if so_trang > MAX_PDF_PAGES:
        raise DocRejected(
            f"PDF{nhan} quá nhiều trang: ~{so_trang}, trần {MAX_PDF_PAGES}."
        )


def kiem_tai_lieu(raw: bytes | None, *, ten: str = "", max_bytes: int = MAX_DOC_BYTES) -> None:
    """Kiểm một tài liệu TRƯỚC khi đưa vào MarkItDown/OCR. Raise :class:`DocRejected`.

    Không giải nén, không dựng lại tài liệu — chỉ đọc bảng mục lục ZIP hoặc quét
    chuỗi trong bytes, nên gọi được ở biên mà gần như không tốn gì.
    """
    nhan = f" ({ten})" if ten else ""
    data = raw or b""
    if not data:
        raise DocRejected(f"Tệp{nhan} rỗng.")
    if len(data) > max_bytes:
        raise DocRejected(
            f"Tệp{nhan} quá lớn: {len(data) // (1024 * 1024)}MB, "
            f"trần {max_bytes // (1024 * 1024)}MB."
        )

    if data[:4] == b"PK\x03\x04":
        _kiem_zip(data, nhan)
    elif data[:5] == b"%PDF-":
        _kiem_pdf(data, nhan)
    # Định dạng khác (csv/html/txt) chỉ có trần byte ở trên — chúng không giải
    # nén nên không có bề mặt bom.


def kiem_tai_lieu_theo_duong_dan(duong_dan: str, *, max_bytes: int = MAX_DOC_BYTES) -> None:
    """Như :func:`kiem_tai_lieu` nhưng cho tệp ĐÃ NẰM TRÊN ĐĨA.

    Không nạp cả tệp vào RAM: `zipfile` mở theo đường dẫn chỉ đọc bảng mục lục ở
    cuối tệp, còn PDF thì quét theo khối. Nạp 100MB vào RAM chỉ để đi kiểm là tự
    tạo ra đúng vấn đề đang muốn chặn.
    """
    from pathlib import Path

    p = Path(duong_dan)
    ten = p.name
    nhan = f" ({ten})" if ten else ""
    try:
        co = p.stat().st_size
    except OSError as exc:
        raise DocRejected(f"Không đọc được tệp{nhan}: {exc}") from exc
    if co == 0:
        raise DocRejected(f"Tệp{nhan} rỗng.")
    if co > max_bytes:
        raise DocRejected(
            f"Tệp{nhan} quá lớn: {co // (1024 * 1024)}MB, trần {max_bytes // (1024 * 1024)}MB."
        )

    with p.open("rb") as f:
        dau = f.read(8)

    if dau[:4] == b"PK\x03\x04":
        try:
            zf = zipfile.ZipFile(str(p))
            muc = zf.infolist()
        except zipfile.BadZipFile as exc:
            raise DocRejected(f"Tệp{nhan} không phải ZIP hợp lệ: {exc}") from exc
        if len(muc) > MAX_ZIP_ENTRIES:
            raise DocRejected(
                f"Tài liệu{nhan} có quá nhiều thành phần: {len(muc)}, trần {MAX_ZIP_ENTRIES}."
            )
        tong = 0
        for m in muc:
            t = m.filename or ""
            if t.startswith("/") or ".." in t.replace("\\", "/").split("/"):
                raise DocRejected(f"Tài liệu{nhan} chứa đường dẫn không hợp lệ: {t[:80]!r}")
            tong += int(m.file_size or 0)
            if tong > MAX_ZIP_TOTAL_BYTES:
                raise DocRejected(
                    f"Tài liệu{nhan} giải nén ra quá lớn: >{MAX_ZIP_TOTAL_BYTES // (1024 * 1024)}MB."
                )
        if tong // max(1, co) > MAX_ZIP_RATIO:
            raise DocRejected(
                f"Tài liệu{nhan} có tỉ lệ nén bất thường: {tong // max(1, co)}:1 "
                f"(trần {MAX_ZIP_RATIO}:1). Đây là dấu hiệu của tệp bom nén."
            )
    elif dau[:5] == b"%PDF-":
        so_trang = 0
        with p.open("rb") as f:
            du = b""
            while True:
                khoi = f.read(1 << 20)
                if not khoi:
                    break
                # Nối 32 byte cuối khối trước để mẫu nằm vắt qua ranh giới khối
                # vẫn đếm được.
                so_trang += len(_PDF_PAGE.findall(du + khoi))
                du = khoi[-32:]
                if so_trang > MAX_PDF_PAGES:
                    raise DocRejected(
                        f"PDF{nhan} quá nhiều trang: >{MAX_PDF_PAGES}."
                    )
