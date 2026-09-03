"""Bước LLM TÙY CHỌN cho dịch phụ đề — CHỈNH nghĩa-theo-ngữ-cảnh + MƯỢT câu, và
TỰ CHẮT LỌC thuật ngữ vào từ điển để lần sau bớt phụ thuộc LLM.

Vị trí trong đường dịch:
    NLLB dịch thô → hậu kỳ glossary (tất định) → **LLM (module này, tùy chọn)**.

Mặc định TẮT (giữ tự chủ, không gọi bên thứ ba). Bật thì trỏ tới một model —
NÊN là model cục bộ; nhưng dùng model online cũng được, và khi đó phần "học"
chắt lọc thuật ngữ LLM vừa dùng vào ``<src>.hoc.json`` để glossary tất định
ngày càng phủ rộng, tiến tới KHÔNG cần LLM nữa.

Hàm ``goi_model(model, messages) -> str`` do caller tiêm vào (thường bọc
``runtime.call_model`` + ``content_of``); tách vậy để test không chạm mạng/GPU.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

from services import thuat_ngu as tn

logger = logging.getLogger(__name__)

#: Số câu mỗi lượt gọi LLM. Gộp để đỡ số lượt, nhưng không quá lớn kẻo model
#: cắt bớt/loạn số dòng — mà lệch số dòng là cả lô rơi về bản nháp.
CAU_MOI_LO = 40

GoiModel = Callable[[str, list[dict]], str]


class LoiLLM(Exception):
    """Model trả lỗi / không gọi được — caller bọc ``call_model`` raise cái này."""


def _tach_dong_so(raw: str, n: int) -> list[str] | None:
    """Rã "1. ... 2. ..." thành đúng ``n`` dòng. Thiếu/dư/lệch số → None (để
    caller rơi về bản nháp, KHÔNG nhận kết quả méo)."""
    out: dict[int, str] = {}
    for dong in (raw or "").splitlines():
        m = re.match(r"\s*(\d+)\s*[.):\-]\s*(.*)$", dong)
        if not m:
            continue
        i = int(m.group(1))
        if 1 <= i <= n and i not in out:
            out[i] = m.group(2).strip()
    if len(out) != n:
        return None
    return [out[i] for i in range(1, n + 1)]


def _nhac_linh_vuc(linh_vuc: list[str]) -> str:
    return (", ".join(linh_vuc)).replace("_", " ") if linh_vuc else "chung"


def chinh(cap: list[tuple[str, str]], linh_vuc: list[str], src: str,
          model: str, goi_model: GoiModel) -> list[str]:
    """Chỉnh danh sách câu đã dịch cho ĐÚNG NGHĨA + MƯỢT, NẮN thuật ngữ cho chuẩn.

    ``cap`` = [(câu gốc, bản dịch nháp)]. Trả danh sách bản dịch đã chỉnh, ĐÚNG
    số câu. Bất kỳ trục trặc nào (model lỗi, lệch số dòng) → trả nguyên bản nháp
    cho lô đó: LLM chỉ được LÀM TỐT HƠN, không được làm hỏng phụ đề đã có.
    """
    if not cap or not model:
        return [b for _, b in cap]
    nhac = _nhac_linh_vuc(linh_vuc)
    system = (
        "Bạn là biên tập viên phụ đề tiếng Việt. Với mỗi câu, bạn nhận CÂU GỐC "
        "và một BẢN DỊCH NHÁP. Hãy chỉnh bản dịch cho đúng nghĩa theo ngữ cảnh "
        "và mượt, tự nhiên như người Việt nói. Bản nháp do máy dịch làm, nên "
        "thuật ngữ chuyên ngành trong đó có thể dịch thô hoặc sai: hãy thay "
        "bằng thuật ngữ chuẩn mà người trong ngành thật sự dùng. Chiều ngược "
        "lại thì KHÔNG: đã là thuật ngữ chuyên ngành thì không hạ xuống từ đời "
        "thường. KHÔNG thêm/bớt/gộp/tách câu. Trả về ĐÚNG số dòng, mỗi dòng "
        "một câu, đánh số 1., 2., 3.… và CHỈ ghi bản dịch đã chỉnh (không kèm "
        "câu gốc, không giải thích)."
    )
    ra: list[str] = []
    for i in range(0, len(cap), CAU_MOI_LO):
        lo = cap[i:i + CAU_MOI_LO]
        dong = [f"{j + 1}. GỐC: {g}  ||  NHÁP: {b}" for j, (g, b) in enumerate(lo)]
        user = (f"Lĩnh vực: {nhac}.\nChỉnh {len(lo)} câu sau, trả về "
                f"{len(lo)} dòng đã đánh số:\n\n" + "\n".join(dong))
        try:
            raw = goi_model(model, [{"role": "system", "content": system},
                                    {"role": "user", "content": user}])
            sua = _tach_dong_so(raw, len(lo))
        except Exception as exc:
            logger.warning("LLM chỉnh dịch lỗi (%s) — giữ bản nháp lô này",
                           str(exc)[:160])
            sua = None
        ra.extend(sua if sua else [b for _, b in lo])
    return ra


def chon_linh_vuc(cau_goc: list[str], model: str, goi_model: GoiModel) -> list[str]:
    """Hỏi model bản thoại thuộc lĩnh vực nào — CHỈ dùng khi thống kê chịu thua.

    ``thuat_ngu.doan_linh_vuc`` chấm lĩnh vực bằng cách đếm thuật ngữ ĐÃ CÓ
    trong kho, nên lĩnh vực nào kho chưa phủ thì nó không nhận ra; mà không
    nhận ra thì vòng học không chạy, và kho mãi không phủ thêm. Một lượt hỏi
    ngắn phá được vòng luẩn quẩn đó.

    Chỉ nhận nhãn có sẵn trong ``LINH_VUC_NHAN``; model nói gì khác (kể cả bịa
    lĩnh vực mới, hay bảo không rõ) đều trả [] — thà không học còn hơn học vào
    sai ngăn, vì ``ghi_hoc`` ghi rồi thì không đè lại.
    """
    if not cau_goc or not model:
        return []
    system = (
        "Bạn phân loại lĩnh vực chuyên môn của một bản thoại. Chọn ĐÚNG MỘT "
        "nhãn trong danh sách được cho. Nếu bản thoại là chuyện đời thường, "
        "không thuộc chuyên ngành nào, hãy trả 'khong_ro'. CHỈ ghi nhãn, không "
        "giải thích."
    )
    user = ("Danh sách nhãn: " + ", ".join(tn.LINH_VUC_NHAN)
            + "\n\nBản thoại:\n" + "\n".join(cau_goc[:40]))
    try:
        raw = goi_model(model, [{"role": "system", "content": system},
                                {"role": "user", "content": user}])
    except Exception as exc:
        logger.warning("hỏi lĩnh vực lỗi (%s) — bỏ qua vòng học lần này",
                       str(exc)[:160])
        return []
    thap = (raw or "").strip().lower()
    for slug in tn.LINH_VUC_NHAN:
        if re.search(r"(?<!\w)" + slug + r"(?!\w)", thap):
            logger.info("dịch LLM: model chấm lĩnh vực '%s'", slug)
            return [slug]
    return []


def _rã_json_terms(raw: str) -> list[dict]:
    """Bóc mảng JSON [{src, vi}] khỏi câu trả lời (kể cả khi bọc ```json)."""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
    m = re.search(r"\[.*\]", s, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    return [x for x in arr if isinstance(x, dict)]


def hoc_thuat_ngu(cap: list[tuple[str, str]], linh_vuc: list[str], src: str,
                  model: str, goi_model: GoiModel) -> dict[str, dict[str, str]]:
    """Chắt lọc thuật ngữ chuyên ngành LLM vừa dùng → {lĩnh vực: {term: thuật ngữ VI}}.

    Gọi MỘT lượt cho cả phim, hỏi model liệt kê cặp (thuật ngữ nguồn → thuật ngữ
    VI chuẩn). Gán vào lĩnh vực CHÍNH (đầu danh sách). Best-effort: hỏng thì trả
    rỗng — không bao giờ chặn đường dịch.
    """
    if not cap or not model or not linh_vuc:
        return {}
    nhac = _nhac_linh_vuc(linh_vuc)
    # Lấy mẫu vài chục câu để model có ngữ cảnh, khỏi nhồi cả phim.
    mau = cap[:60]
    dong = [f"- GỐC: {g}  ||  DỊCH: {b}" for g, b in mau]
    system = (
        "Bạn trích thuật ngữ chuyên ngành từ các cặp câu (gốc → dịch tiếng "
        "Việt). CHỈ lấy thuật ngữ chuyên ngành thật sự (không lấy từ đời "
        "thường, tên riêng, hư từ). Trả về DUY NHẤT một mảng JSON, mỗi phần tử "
        '{\"src\": \"thuật ngữ ở tiếng gốc\", \"vi\": \"thuật ngữ tiếng Việt chuẩn\"}. '
        "Tối đa 30 phần tử. Không giải thích, không văn xuôi."
    )
    user = f"Lĩnh vực: {nhac}. Các cặp câu:\n\n" + "\n".join(dong)
    try:
        raw = goi_model(model, [{"role": "system", "content": system},
                                {"role": "user", "content": user}])
    except Exception as exc:
        logger.warning("LLM chắt lọc thuật ngữ lỗi: %s", str(exc)[:160])
        return {}
    lv_chinh = linh_vuc[0]
    bang: dict[str, str] = {}
    for x in _rã_json_terms(raw):
        s_term = str(x.get("src") or "").strip()
        v_term = str(x.get("vi") or "").strip()
        # Bỏ rác: rỗng, hoặc "thuật ngữ" dài như cả câu (>60 ký tự thường là dịch cả câu).
        if s_term and v_term and len(s_term) <= 60 and len(v_term) <= 80:
            bang[s_term] = v_term
    return {lv_chinh: bang} if bang else {}


def chinh_va_hoc(cap: list[tuple[str, str]], linh_vuc: list[str], src: str,
                 model: str, goi_model: GoiModel) -> list[str]:
    """Chỉnh bằng LLM rồi (nếu biết tiếng nguồn + lĩnh vực) chắt lọc thuật ngữ
    vào ``<src>.hoc.json``. Trả bản dịch đã chỉnh.

    Phần "học" là best-effort và tách khỏi phần "chỉnh": lỗi học không được làm
    hỏng kết quả dịch.
    """
    sua = chinh(cap, linh_vuc, src, model, goi_model)
    if src and linh_vuc:
        try:
            moi = hoc_thuat_ngu(list(zip((g for g, _ in cap), sua)),
                                linh_vuc, src, model, goi_model)
            them = tn.ghi_hoc(src, moi) if moi else 0
            if them:
                logger.info("dịch LLM: học %d thuật ngữ mới cho '%s'", them, src)
        except Exception as exc:
            logger.warning("ghi thuật ngữ tự học lỗi: %s", str(exc)[:160])
    return sua
