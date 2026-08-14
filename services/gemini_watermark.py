"""Gỡ watermark ngôi sao Gemini khỏi ảnh sinh ra — thuần Pillow, không thêm dependency.

Nguồn thuật toán (cả hai MIT):
- allenk/GeminiWatermarkTool (C++): khung engine, 4 ảnh capture nền đen, luật vị
  trí V1/V2, phép dò NCC kèm "snap" vài px quanh vị trí công thức.
- GargantuaX/gemini-watermark-remover (JS): catalog kích thước chính thức của
  Gemini 3.x (vị trí watermark theo từng cỡ ảnh), phép CHIẾU config sang cỡ ảnh
  gần-catalog, và ý tưởng hiệu chỉnh CƯỜNG ĐỘ alpha theo từng ảnh (alpha gain).

Nguyên lý: Gemini dán logo TRẮNG bằng alpha blending với alpha map cố định:
    watermarked = α·255 + (1−α)·gốc   →   gốc = (watermarked − α·255) / (1−α)
Alpha map suy từ ảnh chụp watermark trên nền đen: α = max(R,G,B)/255 từng điểm.
HÌNH ngôi sao giống nhau ở mọi biến thể; chỉ CƯỜNG ĐỘ khác (V1 đỉnh ≈0.51,
V2 ≈0.33, có ảnh còn mờ hơn) nên trước khi gỡ phải khớp hệ số gain g:
    α_thật = g · α_template
Cách khớp: thử lưới g, unblend vùng nghi ngờ rồi đo tương quan phần dư với
template — g đúng thì hình ngôi sao biến mất (|NCC| → 0). Phần dư này đồng
thời là bộ lọc dương tính giả: chi tiết ảnh tình cờ giống ngôi sao (đá trắng,
hoa văn) không thể "gỡ cho sạch" ở bất kỳ g nào nên bị loại.

Vùng xử lý tối đa ~96×96 điểm ảnh nên vòng lặp Python thuần đủ nhanh.

Chỉ gỡ được watermark NHÌN THẤY (ngôi sao góc phải-dưới). Watermark SynthID
chìm trong pixel vẫn còn nguyên — giới hạn cả hai repo gốc tự xác nhận.
Không dò thấy (ảnh không có watermark, hoặc Google đổi format) thì trả None
và giữ nguyên ảnh gốc — thà sót watermark còn hơn phá ảnh.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any

from PIL import Image, ImageChops

from services.gemini_watermark_assets import (
    BG_48_PNG_B64,
    BG_96_PNG_B64,
    BG_B_36_PNG_B64,
    BG_B_96_PNG_B64,
)

# ── Ngưỡng quyết định (hiệu chỉnh trên 29 mẫu thật + đối chứng âm, 13/08) ────
# NCC thô tối thiểu để một ứng viên đáng đem đi kiểm tra biên. Watermark mờ
# nhất trong bộ mẫu chuẩn vẫn ≥ 0.17; đối chứng âm cao nhất 0.14.
_RAW_MIN = 0.15
# Từ mức này trở lên coi như chắc chắn (mọi điểm giả đo được đều < 0.5) —
# nhận thẳng, khỏi qua gate biên; gate biên có thể trượt oan biến thể alpha lạ.
_RAW_SURE = 0.60
# Gate biên cho vùng nghi ngờ 0.15–0.60: trước gỡ thử phải CÓ chữ ký biên ngôi
# sao (điểm giả kiểu "cửa sổ lồng trong sao" hay "sai chỗ" đều ≈ 0.0),
_EDGE_PRESENT = 0.08
# ... sau gỡ thử ở gain tốt nhất biên phải SẠCH (anchor thật ≤ 0.23),
_EDGE_CLEAN = 0.25
# ... và phải TỤT thật sự so với trước gỡ — chi tiết ảnh thật không tụt được
# nên bị loại ở đây (đá trắng: tỉ lệ 0.96; nội dung kéo giãn: 0.72–0.73;
# watermark thật mờ nhất: 0.59).
_EDGE_DROP = 0.65
# Gain khớp được phải đạt mức tối thiểu — điểm giả chỉ "gỡ được" ở gain rất
# nhỏ (0.25), watermark thật mờ nhất cũng cần 0.45.
_GAIN_MIN = 0.30
# Chỉ tin vị trí snap khi tương quan đủ mạnh; yếu hơn thì thử thêm vị trí công thức.
_SNAP_ACCEPT = 0.60
_SNAP = 3
# Lưới gain thô → mịn: phủ watermark siêu mờ (0.3×) tới đậm hơn template (1.3×).
_GAINS_COARSE = [0.30, 0.45, 0.60, 0.75, 0.90, 1.05, 1.20]
_GAIN_MAX = 1.30
# Đảo blend: bỏ α nhiễu rất nhỏ, chặn trần để không chia cho số gần 0.
_ALPHA_MIN = 0.002
_ALPHA_MAX = 0.99

# ── Alpha map từ capture nền đen ─────────────────────────────────────────────
_SOURCE_B64 = {
    "v1_48": BG_48_PNG_B64,
    "v1_96": BG_96_PNG_B64,
    "v2_36": BG_B_36_PNG_B64,
    "v2_96": BG_B_96_PNG_B64,
}

# (source, size) → list[float] α theo hàng. Nạp lười, giữ vĩnh viễn (vài chục KB).
_alpha_cache: dict[tuple[str, int], list[float]] = {}


def _alpha_map(source: str, size: int) -> list[float]:
    key = (source, size)
    cached = _alpha_cache.get(key)
    if cached is not None:
        return cached
    im = Image.open(io.BytesIO(base64.b64decode(_SOURCE_B64[source])))
    if im.mode != "L":
        r, g, b = im.convert("RGB").split()
        im = ImageChops.lighter(ImageChops.lighter(r, g), b)
    if im.size != (size, size):
        im = im.resize((size, size), Image.BILINEAR)
    alpha = [v / 255.0 for v in im.getdata()]
    _alpha_cache[key] = alpha
    return alpha


def _template(logo: int) -> list[float]:
    """Alpha map cho cỡ logo. Ưu tiên map V1 (đậm nhất) để gain luôn ≤ ~1.3;
    36px chỉ tồn tại ở đời V2 nên lấy thẳng capture V2 36×36."""
    if logo == 36:
        return _alpha_map("v2_36", 36)
    if logo == 48:
        return _alpha_map("v1_48", 48)
    return _alpha_map("v1_96", logo)


# logo → template đã căn giữa (cho NCC giá trị) — tính một lần, dùng mọi ứng viên.
_tpl_centered_cache: dict[int, tuple[list[float], float]] = {}


def _template_centered(logo: int) -> tuple[list[float], float]:
    cached = _tpl_centered_cache.get(logo)
    if cached is None:
        cached = _center_template(_template(logo))
        _tpl_centered_cache[logo] = cached
    return cached


# ── Catalog kích thước chính thức của Gemini (từ repo JS) ────────────────────
# Gemini không sinh kích thước tùy ý — mỗi tier có danh sách cỡ rời rạc, và vị
# trí watermark đi theo tier. Tier: 05=0.5k, 1k (Gemini 3.x), f1k (2.5-flash),
# 2k, 4k, nm=2816x1536 lề mới.
_CATALOG: dict[str, list[tuple[int, int]]] = {
    "05": [(512, 512), (256, 1024), (192, 1536), (424, 632), (632, 424),
           (448, 600), (1024, 256), (600, 448), (464, 576), (576, 464),
           (1536, 192), (384, 688), (688, 384), (792, 168)],
    "1k": [(1024, 1024), (512, 2048), (384, 3072), (848, 1264), (1264, 848),
           (896, 1200), (2048, 512), (1200, 896), (928, 1152), (1152, 928),
           (3072, 384), (768, 1376), (1376, 768), (1408, 768), (1584, 672)],
    "2k": [(2048, 2048), (1024, 4096), (768, 6144), (1696, 2528), (2528, 1696),
           (1792, 2400), (4096, 1024), (2400, 1792), (1856, 2304), (2304, 1856),
           (6144, 768), (1536, 2752), (2752, 1536), (3168, 1344)],
    "nm": [(2816, 1536)],
    "4k": [(4096, 4096), (2048, 8192), (1536, 12288), (3392, 5056), (5056, 3392),
           (3584, 4800), (8192, 2048), (4800, 3584), (3712, 4608), (4608, 3712),
           (12288, 1536), (3072, 5504), (5504, 3072), (6336, 2688)],
    "f1k": [(832, 1248), (1248, 832), (864, 1184), (1184, 864), (896, 1152),
            (1152, 896), (768, 1344), (1344, 768), (1536, 672)],
}

# Config gốc theo tier: (lề phải, lề dưới, cạnh logo).
_TIER_BASES: dict[str, list[tuple[int, int, int]]] = {
    "05": [(32, 32, 48)],
    "1k": [(32, 32, 48), (64, 64, 96)],   # hiện hành + legacy
    "f1k": [(64, 64, 96)],
    "2k": [(64, 64, 96)],
    "4k": [(64, 64, 96)],
    "nm": [(192, 192, 96)],
}


def _v2_small_formula(width: int, height: int) -> tuple[int, int]:
    """(lề, cạnh logo) V2-nhỏ theo công thức allenk: ảnh nhỏ Gemini 3.5+ là bản
    thu của nguồn canonical 2752/2816/2848 theo cạnh dài; lề và logo co cùng tỉ lệ."""
    long_side = max(width, height)
    short_side = min(width, height)
    if long_side > 1100:
        doubled = 2.0 * long_side
        source = min((2752.0, 2816.0, 2848.0), key=lambda c: abs(doubled - c))
    elif short_side >= 566:
        source = 2752.0
    elif short_side >= 550:
        source = 2816.0
    else:
        source = 2848.0
    scale = long_side / source
    margin = round(192.0 * scale)
    ideal = round(96.0 * scale)
    return margin, (36 if ideal <= 40 else ideal)


def _candidates(width: int, height: int) -> list[tuple[int, int, int]]:
    """Các ứng viên (lề phải, lề dưới, cạnh logo) cho ảnh W×H.

    Gộp luật của cả hai repo: khớp catalog chính xác → config của tier + các
    biến thể (lề lớn 96 cho logo 48, lề mới 192 cho logo 96); không khớp →
    CHIẾU config từ cỡ catalog gần (cùng tỉ lệ ±5%, méo trục ≤12%, thu phóng
    0.25–1.6). Thừa ứng viên không sao — phép chấm điểm gỡ-thử sẽ loại; thiếu
    mới chết vì gỡ sai chỗ là phá ảnh.
    """
    out: list[tuple[int, int, int]] = []

    def add(mr: int, mb: int, logo: int) -> None:
        if not 24 <= logo <= 120:
            return
        if width - mr - logo < 0 or height - mb - logo < 0:
            return
        item = (mr, mb, logo)
        if item not in out:
            out.append(item)

    def add_base_and_variants(mr: int, mb: int, logo: int) -> None:
        add(mr, mb, logo)
        if logo == 48:
            add(96, 96, 48)
        if logo == 96 and (mr, mb) != (192, 192):
            add(192, 192, 96)

    exact = False
    for tier, sizes in _CATALOG.items():
        if (width, height) in sizes:
            exact = True
            for mr, mb, logo in _TIER_BASES[tier]:
                add_base_and_variants(mr, mb, logo)

    if not exact:
        aspect = width / height
        for tier, sizes in _CATALOG.items():
            for w, h in sizes:
                if abs(aspect - w / h) / (w / h) > 0.05:
                    continue
                sx, sy = width / w, height / h
                if abs(sx / sy - 1) > 0.12 or not 0.25 <= (sx + sy) / 2 <= 1.6:
                    continue
                scale = (sx + sy) / 2
                for mr, mb, logo in _TIER_BASES[tier]:
                    add(max(8, round(mr * sx)), max(8, round(mb * sy)),
                        round(logo * scale))
                    if logo == 48:
                        # Biến thể lề lớn chiếu theo cùng tỉ lệ; logo làm tròn
                        # LÊN theo repo JS (khớp thực nghiệm 42px của ảnh 1024×768).
                        add(max(8, round(96 * sx)), max(8, round(96 * sy)),
                            math.ceil(48 * scale))

    # Nhóm luật chung không phụ thuộc catalog.
    if width > 1024 and height > 1024:
        add(64, 64, 96)      # V1 lớn
        add(192, 192, 96)    # V2 lớn (Gemini 3.5+)
        add(146, 146, 96)    # Flow lớn (lề gốc 146 — xem chú thích dưới)
    else:
        add(32, 32, 48)      # V1 nhỏ
        margin, logo = _v2_small_formula(width, height)
        add(margin, margin, logo)
        # Flow (Google Labs) dùng cùng ngôi sao, độ mờ cỡ V2, nhưng neo lề gốc
        # 146 thay vì 192 (đo 14 ảnh Flow 1376×768 ngày 14/08/2026: lề 73,
        # logo 48 — đúng phép co 0.5 của canonical 2752). Tái dùng suy luận
        # tỉ lệ của công thức V2, chỉ đổi mốc lề.
        flow_margin = round(margin * 146.0 / 192.0)
        add(flow_margin, flow_margin, logo)
        add(96, 96, 36)      # catalog JS: 1k tier biến thể V2
        add(96, 96, 48)      # catalog JS: 1k tier lề lớn
    return out


# ── Tương quan NCC (tương đương TM_CCOEFF_NORMED trên vùng nhỏ) ──────────────

def _ncc_vals(window: list[float], tpl_centered: list[float], denom_t: float) -> float:
    n = len(window)
    mean_w = sum(window) / n
    num = 0.0
    sq = 0.0
    for i in range(n):
        wc = window[i] - mean_w
        num += wc * tpl_centered[i]
        sq += wc * wc
    if sq <= 1e-12:
        return 0.0
    return num / (denom_t * math.sqrt(sq))


def _center_template(tpl: list[float]) -> tuple[list[float], float]:
    n = len(tpl)
    mean_t = sum(tpl) / n
    tc = [v - mean_t for v in tpl]
    denom_t = math.sqrt(sum(v * v for v in tc))
    return tc, denom_t


def _extract(gray: list[float], gw: int, ox: int, oy: int, s: int) -> list[float]:
    reg: list[float] = []
    for row in range(s):
        base = (oy + row) * gw + ox
        reg.extend(gray[base:base + s])
    return reg


def _ncc_best(gray: list[float], gw: int, gh: int, logo: int) -> tuple[float, int, int]:
    """NCC lớn nhất khi trượt template logo×logo trên cửa sổ xám gw×gh.
    Trả (điểm, lệch_x, lệch_y) tính từ góc trái-trên cửa sổ."""
    tc, denom_t = _template_centered(logo)
    best, bx, by = -1.0, 0, 0
    for oy in range(gh - logo + 1):
        for ox in range(gw - logo + 1):
            score = _ncc_vals(_extract(gray, gw, ox, oy, logo), tc, denom_t)
            if score > best:
                best, bx, by = score, ox, oy
    return best, bx, by


# ── Khớp gain bằng NĂNG LƯỢNG BIÊN ───────────────────────────────────────────
# Unblend là phép affine per-pixel cùng hệ số cho cả 3 kênh nên áp thẳng lên độ
# xám cho kết quả đúng bằng xám-của-ảnh-đã-unblend. Metric phần dư đo trên BIÊN
# (Sobel magnitude) chứ không trên giá trị điểm ảnh: gỡ đúng gain thì đường viền
# ngôi sao biến mất; gỡ thiếu hay gỡ lố đều để lại biên DƯƠNG (magnitude không
# có dấu) nên không thể "null giả" bằng cách chỉnh g như NCC giá trị thô.

def _sobel_mag(vals: list[float], w: int, h: int) -> list[float]:
    out = [0.0] * (w * h)
    for y in range(1, h - 1):
        base = y * w
        for x in range(1, w - 1):
            i = base + x
            a, b, c = vals[i - w - 1], vals[i - w], vals[i - w + 1]
            d, e = vals[i - 1], vals[i + 1]
            f, g, hh = vals[i + w - 1], vals[i + w], vals[i + w + 1]
            gx = (c + 2 * e + hh) - (a + 2 * d + f)
            gy = (f + 2 * g + hh) - (a + 2 * b + c)
            out[i] = math.sqrt(gx * gx + gy * gy)
    return out


# logo → gradient template đã căn giữa, dùng cho NCC biên.
# (_template là hàm thuần theo logo nên khoá cache chỉ cần logo.)
_tpl_grad_cache: dict[int, tuple[list[float], float]] = {}


def _template_grad(logo: int) -> tuple[list[float], float]:
    cached = _tpl_grad_cache.get(logo)
    if cached is None:
        cached = _center_template(_sobel_mag(_template(logo), logo, logo))
        _tpl_grad_cache[logo] = cached
    return cached


def _unblend(region: list[float], tpl: list[float], gain: float) -> list[float]:
    un = list(region)
    for i, t in enumerate(tpl):
        a = t * gain
        if a < _ALPHA_MIN:
            continue
        if a > _ALPHA_MAX:
            a = _ALPHA_MAX
        v = (region[i] - a * 255.0) / (1.0 - a)
        un[i] = 0.0 if v < 0.0 else (255.0 if v > 255.0 else v)
    return un


# logo → trọng số viền template (Sobel chuẩn hoá tổng = 1) cho phép đo năng lượng.
_tpl_edge_weight_cache: dict[int, list[float]] = {}


def _template_edge_weights(logo: int) -> list[float]:
    cached = _tpl_edge_weight_cache.get(logo)
    if cached is None:
        grad = _sobel_mag(_template(logo), logo, logo)
        total = sum(grad)
        cached = [v / total for v in grad]
        _tpl_edge_weight_cache[logo] = cached
    return cached


def _edge_gain_fit(region: list[float], tpl: list[float], logo: int) -> tuple[float, float, float, float, float]:
    """Trả (gain đã chọn, NCC biên trước gỡ, |NCC biên| tại gain đó,
    năng lượng biên trước gỡ, năng lượng biên tại gain đó).

    CHỌN GAIN bằng NĂNG LƯỢNG biên tuyệt đối có trọng số theo viền template —
    không chuẩn hoá, nên nền phẳng không đánh lừa được: NCC chuẩn hoá cho dư âm
    làm tròn ±1 trên nền đen tương quan ~1, đường cong dốc dần về mép lưới và
    gain trôi lên 1.3 (gỡ lố ×4). Trong các gain năng lượng xấp xỉ nhau (≤ +5%)
    chọn gain NHỎ NHẤT — can thiệp ít nhất. GATE nhận/loại phía trên vẫn đo
    bằng |NCC| biên, đúng thang đã hiệu chỉnh trên 29 mẫu thật.
    """
    tgc, denom = _template_grad(logo)
    weights = _template_edge_weights(logo)

    def energy_at(gain: float) -> float:
        sob = _sobel_mag(_unblend(region, tpl, gain), logo, logo)
        return sum(s * w for s, w in zip(sob, weights))

    edge0 = _ncc_vals(_sobel_mag(region, logo, logo), tgc, denom)
    energy0 = sum(s * w for s, w in zip(_sobel_mag(region, logo, logo), weights))
    trials = [(g, energy_at(g)) for g in _GAINS_COARSE]
    floor = min(e for _, e in trials)
    best_g = min(g for g, e in trials if e <= floor * 1.05)
    best_e = next(e for g, e in trials if g == best_g)
    for g in (best_g - 0.10, best_g - 0.05, best_g + 0.05, best_g + 0.10):
        if _GAIN_MIN <= g <= _GAIN_MAX:
            e = energy_at(g)
            if e < best_e:
                best_g, best_e = g, e
    edge_min = abs(_ncc_vals(_sobel_mag(_unblend(region, tpl, best_g), logo, logo),
                             tgc, denom))
    return best_g, edge0, edge_min, energy0, best_e


def _detect(im: Image.Image) -> tuple[int, int, int, float, float, float] | None:
    """Dò watermark và khớp gain.

    Bước 1: chấm NCC thô (trượt ±_SNAP quanh vị trí công thức) cho mọi ứng viên.
    Bước 2: duyệt theo NCC thô giảm dần; ứng viên đầu tiên vượt cửa là kết quả:
      - raw ≥ _RAW_SURE: nhận thẳng (không điểm giả nào đo được cao cỡ này);
      - còn lại phải qua gate biên: có chữ ký biên ngôi sao, gỡ thử ở gain tốt
        nhất thì biên sạch và tụt rõ — chi tiết ảnh tình cờ giống sao (đá trắng,
        cửa sổ lồng trong sao thật) không qua được cửa này.
    Trả (x, y, cạnh logo, gain, NCC thô, NCC biên sau gỡ thử) hoặc None.
    """
    width, height = im.size
    # (raw, x_snap, y_snap, x_công_thức, y_công_thức, logo, xám, x1, y1, rộng cửa sổ)
    scored: list[tuple[float, int, int, int, int, int, list[float], int, int, int]] = []
    for margin_r, margin_b, logo in _candidates(width, height):
        pos_x = width - margin_r - logo
        pos_y = height - margin_b - logo
        x1 = max(0, pos_x - _SNAP)
        y1 = max(0, pos_y - _SNAP)
        x2 = min(width, pos_x + logo + _SNAP)
        y2 = min(height, pos_y + logo + _SNAP)
        if x2 - x1 < logo or y2 - y1 < logo:
            continue
        window = im.crop((x1, y1, x2, y2)).convert("L")
        gray = [float(v) for v in window.getdata()]
        gw = x2 - x1
        raw, off_x, off_y = _ncc_best(gray, gw, y2 - y1, logo)
        if raw >= _RAW_MIN:
            scored.append((raw, x1 + off_x, y1 + off_y, pos_x, pos_y, logo,
                           gray, x1, y1, gw))
    scored.sort(key=lambda item: item[0], reverse=True)

    for raw, sx, sy, pos_x, pos_y, logo, gray, x1, y1, gw in scored:
        tpl = _template(logo)
        # Vị trí thử: snap khi tương quan mạnh; yếu thì thêm cả vị trí công thức
        # (nền rối có thể kéo match lệch về phía chi tiết ảnh).
        positions = [(sx, sy)]
        if raw < _SNAP_ACCEPT and (pos_x, pos_y) != (sx, sy):
            positions.append((pos_x, pos_y))
        for px, py in positions:
            region = _extract(gray, gw, px - x1, py - y1, logo)
            gain, edge0, edge_min, energy0, energy_g = _edge_gain_fit(region, tpl, logo)
            if gain < _GAIN_MIN:
                continue
            # Gỡ thử phải GIẢM năng lượng biên thật sự (≥3%) — ngôi sao CHỤP
            # THẬT trong ảnh (bầu trời sao...) trùng hình dạng đến mấy thì gỡ
            # thử cũng chỉ làm biên tệ đi (+28% đo được), watermark thật sụt
            # 10–58%. Áp cho cả lối tắt raw ≥ _RAW_SURE.
            if energy_g > 0.97 * energy0:
                continue
            if raw < _RAW_SURE and not (
                edge0 >= _EDGE_PRESENT
                and edge_min <= _EDGE_CLEAN
                and edge_min <= _EDGE_DROP * edge0
            ):
                continue
            return px, py, logo, gain, raw, edge_min
    return None


def _reverse_blend(im: Image.Image, tpl: list[float], logo: int,
                   x: int, y: int, gain: float) -> None:
    px = im.load()
    for row in range(logo):
        trow = row * logo
        for col in range(logo):
            a = tpl[trow + col] * gain
            if a < _ALPHA_MIN:
                continue
            if a > _ALPHA_MAX:
                a = _ALPHA_MAX
            inv = 1.0 / (1.0 - a)
            a255 = a * 255.0
            r, g, b = px[x + col, y + row]
            px[x + col, y + row] = (
                min(255, max(0, round((r - a255) * inv))),
                min(255, max(0, round((g - a255) * inv))),
                min(255, max(0, round((b - a255) * inv))),
            )


def remove_watermark_bytes(data: bytes) -> bytes | None:
    """Gỡ watermark ngôi sao khỏi bytes ảnh nếu DÒ THẤY; None = giữ nguyên ảnh gốc.

    None khi: không đọc được ảnh, không phải ảnh tĩnh thường gặp, hoặc không dò
    thấy watermark ở các vị trí đã biết. Giữ nguyên ĐỊNH DẠNG nguồn (PNG→PNG,
    JPEG/WEBP→mã lại chất lượng 95) để đuôi file và Content-Type phía trên vẫn
    đúng; giữ nguyên kênh alpha — watermark chỉ dán lên RGB.
    """
    try:
        im = Image.open(io.BytesIO(data))
        fmt = (im.format or "").upper()
        if fmt not in {"PNG", "JPEG", "WEBP"} or getattr(im, "n_frames", 1) > 1:
            return None
        alpha = None
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            alpha = rgba.getchannel("A")
            im = rgba.convert("RGB")
        else:
            im = im.convert("RGB")
    except Exception:
        return None

    found = _detect(im)
    if not found:
        return None
    x, y, logo, gain, _raw, _residual = found
    _reverse_blend(im, _template(logo), logo, x, y, gain)

    if alpha is not None:
        im.putalpha(alpha)
    buf = io.BytesIO()
    if fmt == "PNG":
        im.save(buf, "PNG")
    else:
        im.save(buf, fmt, quality=95)
    return buf.getvalue()


def removal_enabled() -> bool:
    """Cờ cấu hình — để call site kiểm SỚM, trước khi tải/đọc/decode ảnh.

    Tắt cờ là tắt được cả phần tốn kém (tải ảnh về, đọc file, decode base64),
    không chỉ phần gỡ."""
    from services.config import config
    return config.remove_gemini_watermark


def maybe_remove_watermark(data: bytes, *, origin: str = "") -> bytes | None:
    """Cổng dùng ở các đường trả ảnh Gemini: kiểm cờ cấu hình, gỡ, ghi log.

    Trả bytes đã gỡ, hoặc None nghĩa là "cứ dùng ảnh gốc" (cờ tắt / không dò
    thấy / lỗi bất kỳ). Không bao giờ ném lỗi ra đường trả ảnh.
    """
    try:
        if not removal_enabled():
            return None
        cleaned = remove_watermark_bytes(data)
        if cleaned is not None:
            from utils.log import logger
            logger.info({"event": "gemini_watermark_removed", "origin": origin,
                         "bytes_in": len(data), "bytes_out": len(cleaned)})
        return cleaned
    except Exception as exc:
        from utils.log import logger
        logger.warning({"event": "gemini_watermark_error", "origin": origin,
                        "error": str(exc)[:200]})
        return None


def strip_watermark_b64_items(items: list[dict[str, Any]], *, origin: str = "") -> list[dict[str, Any]]:
    """Gỡ watermark tại chỗ cho các mục {"b64_json": ...} kiểu OpenAI images."""
    if not removal_enabled():
        return items
    for item in items:
        b64 = str(item.get("b64_json") or "")
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64)
        except Exception:
            continue
        cleaned = maybe_remove_watermark(raw, origin=origin)
        if cleaned is not None:
            item["b64_json"] = base64.b64encode(cleaned).decode("ascii")
    return items
