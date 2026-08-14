"""Gỡ watermark ngôi sao Gemini — services/gemini_watermark.py.

Cách kiểm không cần ảnh mẫu thật: TỰ DÁN watermark bằng đúng phép blend thuận
(watermarked = g·α·255 + (1−g·α)·gốc) với alpha map nhúng trong module, rồi
gọi gỡ và so với ảnh gốc. Blend thuận và phép đảo là nghịch đảo toán học nên
sai khác chỉ còn do làm tròn 8-bit.

Bộ mẫu Gemini thật (29 ảnh, repo gemini-watermark-remover) đã được chạy đối
chiếu lúc phát triển: 28/29 gỡ đúng vị trí ≤1px, 0/52 dương tính giả trên đối
chứng âm. Mẫu thật quá nặng để đưa vào repo nên test này chỉ giữ phần tổng hợp.
"""
from __future__ import annotations

import base64
import io
import os

import pytest
from PIL import Image

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.gemini_watermark import (  # noqa: E402
    _template,
    _v2_small_formula,
    maybe_remove_watermark,
    remove_watermark_bytes,
    strip_watermark_b64_items,
)

pytestmark = pytest.mark.integration


def _anh_nen(w: int, h: int) -> Image.Image:
    """Nền gradient mượt — giống ảnh sinh AI hơn nhiễu ngẫu nhiên."""
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (40 + (x * 160) // w, 60 + (y * 140) // h,
                        90 + ((x + y) * 120) // (w + h))
    return im


def _dan_watermark(im: Image.Image, margin: int, logo: int, gain: float) -> None:
    """Blend thuận đúng công thức Gemini: trắng 255, alpha = gain × template."""
    tpl = _template(logo)
    x0 = im.width - margin - logo
    y0 = im.height - margin - logo
    px = im.load()
    for row in range(logo):
        for col in range(logo):
            a = tpl[row * logo + col] * gain
            if a <= 0:
                continue
            r, g, b = px[x0 + col, y0 + row]
            px[x0 + col, y0 + row] = (
                round(a * 255 + (1 - a) * r),
                round(a * 255 + (1 - a) * g),
                round(a * 255 + (1 - a) * b),
            )


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _sai_khac_binh_quan(a: Image.Image, b: Image.Image) -> float:
    pa, pb = a.load(), b.load()
    total = n = 0
    for y in range(a.height):
        for x in range(a.width):
            for c in range(3):
                total += abs(pa[x, y][c] - pb[x, y][c])
                n += 1
    return total / n


def _kiem_go_sach(w: int, h: int, margin: int, logo: int, gain: float) -> None:
    goc = _anh_nen(w, h)
    dan = goc.copy()
    _dan_watermark(dan, margin, logo, gain)
    ra = remove_watermark_bytes(_png(dan))
    assert ra is not None, "phải dò thấy watermark vừa dán"
    ket_qua = Image.open(io.BytesIO(ra)).convert("RGB")
    x0, y0 = w - margin - logo, h - margin - logo
    vung_goc = goc.crop((x0, y0, x0 + logo, y0 + logo))
    vung_ra = ket_qua.crop((x0, y0, x0 + logo, y0 + logo))
    diff = _sai_khac_binh_quan(vung_goc, vung_ra)
    assert diff <= 3.0, f"vùng watermark phải về gần ảnh gốc, sai khác {diff:.2f}"


def test_go_v1_nho_gain_day_du():
    # V1 nhỏ kinh điển: logo 48 lề 32, đậm nguyên bản.
    _kiem_go_sach(1024, 768, margin=32, logo=48, gain=1.0)


def test_go_v2_lon_gain_mo():
    # V2 lớn (Gemini 3.5+): logo 96 lề 192, mờ ~0.65 (map V1 × 0.65 ≈ V2 thật).
    _kiem_go_sach(2752, 1536, margin=192, logo=96, gain=0.65)


def test_go_catalog_1k_le_lon():
    # Biến thể catalog 1k lề lớn: logo 48 lề 96 (cỡ 1376×768 hay gặp từ GMA).
    _kiem_go_sach(1376, 768, margin=96, logo=48, gain=0.6)


def test_go_tren_nen_toi_khong_go_lo():
    # Nền gần đen: unblend clip về 0 làm đường cong gain gần phẳng — trước đây
    # gain trôi về mép lưới 1.3 (gỡ lố ×4, in bóng sao vào vùng tối). Luật
    # "gain nhỏ nhất trong dung sai" phải giữ sai khác về mức làm tròn.
    goc = Image.new("RGB", (1024, 768), (6, 5, 7))
    dan = goc.copy()
    _dan_watermark(dan, margin=32, logo=48, gain=0.35)
    ra = remove_watermark_bytes(_png(dan))
    assert ra is not None
    ket_qua = Image.open(io.BytesIO(ra)).convert("RGB")
    x0, y0 = 1024 - 32 - 48, 768 - 32 - 48
    diff = _sai_khac_binh_quan(goc.crop((x0, y0, x0 + 48, y0 + 48)),
                               ket_qua.crop((x0, y0, x0 + 48, y0 + 48)))
    assert diff <= 3.0, f"nền tối phải về gần ảnh gốc, sai khác {diff:.2f}"


def test_giu_kenh_alpha_png_trong_suot():
    # PNG trong suốt (sticker/logo): watermark chỉ dán lên RGB — kênh alpha
    # phải giữ nguyên từng byte, không bị ép phẳng thành nền đen.
    goc = _anh_nen(1024, 768)
    _dan_watermark(goc, margin=32, logo=48, gain=1.0)
    alpha = Image.new("L", (1024, 768))
    ap = alpha.load()
    for y in range(768):
        for x in range(1024):
            ap[x, y] = (x * 255) // 1024
    rgba = goc.copy()
    rgba.putalpha(alpha)
    buf = io.BytesIO()
    rgba.save(buf, "PNG")
    ra = remove_watermark_bytes(buf.getvalue())
    assert ra is not None
    ket_qua = Image.open(io.BytesIO(ra))
    assert ket_qua.mode == "RGBA"
    assert list(ket_qua.getchannel("A").getdata()) == list(alpha.getdata())


def test_giu_dinh_dang_webp():
    # WEBP vào phải ra WEBP — đổi sang PNG là bytes lệch đuôi file/Content-Type
    # ở đường GMA, và phình dung lượng b64 nhiều lần.
    dan = _anh_nen(1024, 768)
    _dan_watermark(dan, margin=32, logo=48, gain=1.0)
    buf = io.BytesIO()
    dan.save(buf, "WEBP", quality=95)
    ra = remove_watermark_bytes(buf.getvalue())
    assert ra is not None
    assert Image.open(io.BytesIO(ra)).format == "WEBP"


def test_adapter_gemini_normalize_tu_go(monkeypatch):
    # Hook nằm trong adapter.normalize để MỌI đường dùng adapter (generations,
    # edits, image tasks) đều sạch — không chỉ /v1/images/generations.
    from services.config import config
    from services.image_providers.gemini_image import gemini_image_adapter
    monkeypatch.setitem(config.data, "remove_gemini_watermark", True)
    dan = _anh_nen(1024, 768)
    _dan_watermark(dan, margin=32, logo=48, gain=1.0)
    b64_dan = base64.b64encode(_png(dan)).decode("ascii")
    out = gemini_image_adapter.normalize({"data": [{"b64_json": b64_dan}]}, {})
    assert out["data"][0]["b64_json"] != b64_dan, "adapter phải gỡ watermark"


def test_anh_sach_giu_nguyen():
    # Không watermark → None (giữ ảnh gốc), tuyệt đối không tự ý sửa ảnh.
    assert remove_watermark_bytes(_png(_anh_nen(1024, 1024))) is None


def test_bytes_rac_khong_no():
    assert remove_watermark_bytes(b"khong phai anh") is None
    assert remove_watermark_bytes(b"") is None


def test_v2_small_formula_theo_allenk():
    # Các mốc chuẩn từ repo C++: 1376×768 (nửa canonical 2752) → lề 96 logo 48;
    # 1024×1024 (1024-class) → lề 71 logo giữ 36.
    assert _v2_small_formula(1376, 768) == (96, 48)
    assert _v2_small_formula(1024, 1024) == (71, 36)


def test_co_cau_hinh_tat_thi_bo_qua(monkeypatch):
    # Đối chứng dương trước (cùng bytes phải gỡ được khi cờ bật) rồi mới tắt cờ
    # — thiếu bước này thì None-vì-cờ-tắt và None-vì-dò-hỏng không phân biệt được.
    from services.config import config
    dan = _anh_nen(1024, 768)
    _dan_watermark(dan, margin=32, logo=48, gain=1.0)
    data = _png(dan)
    monkeypatch.setitem(config.data, "remove_gemini_watermark", True)
    assert maybe_remove_watermark(data, origin="test") is not None
    monkeypatch.setitem(config.data, "remove_gemini_watermark", False)
    assert maybe_remove_watermark(data, origin="test") is None


def test_strip_b64_items_thay_dung_muc(monkeypatch):
    from services.config import config
    monkeypatch.setitem(config.data, "remove_gemini_watermark", True)
    dan = _anh_nen(1024, 768)
    _dan_watermark(dan, margin=32, logo=48, gain=1.0)
    b64_dan = base64.b64encode(_png(dan)).decode("ascii")
    b64_sach = base64.b64encode(_png(_anh_nen(512, 512))).decode("ascii")
    items = [
        {"b64_json": b64_dan},
        {"b64_json": b64_sach},
        {"url": "https://example.com/x.png"},
    ]
    strip_watermark_b64_items(items, origin="test")
    assert items[0]["b64_json"] != b64_dan, "ảnh có watermark phải bị thay"
    assert items[1]["b64_json"] == b64_sach, "ảnh sạch giữ nguyên"
    assert "b64_json" not in items[2]
