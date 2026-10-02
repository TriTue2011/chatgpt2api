"""Chọn nhóm tool THEO NGHĨA câu người dùng — model nhúng tại chỗ (`services/nhung.py`), trước khi gọi LLM.

Chủ máy 02/10/2026: "ngay khi rq đầu đầy tới rag + reranking trước khi đẩy sang model llm", "Không dùng code à,
phải dùng model", "Viết code để cho toàn bộ model của tôi đều làm được". Bảng từ khoá `_BANG_CHI_DUONG` chỉ bắt đủ
nhóm cho 41,3% câu cần tool (bộ 297 câu thật gán nhãn từ runs.sqlite); thiếu nhóm thì model — BẤT KỲ model nào —
không có schema để gọi. Chọn trước khi gọi LLM nên mọi model chính đều hưởng như nhau.

Cách chọn: nhóm của ``SO_NHOM`` tool có vector gần câu nhất (gộp với từ khoá ở `_nhom_viec`). Số đo, lý do chọn model
và vì sao không reranker: docstring `services/nhung.py`. Ngưỡng điểm không tách được câu tán gẫu (trung vị điểm cao nhất
0,575 so với 0,599 của câu cần tool) nên lấy cố định.

Chưa sẵn (model đang nạp, vector tool đang tính) / lỗi → ``None``: người gọi chạy như cũ bằng từ khoá. Vector 101
tool tính ở luồng nền, lưu đĩa theo mã băm (model + ĐƯỜNG chạy + mô tả tool) — đổi ảnh mà mô tả không đổi thì khỏi
tính; GPU nhà hỏng thì lùi CPU và dùng bộ vector của đường CPU (vector fp16 và int8 không trùng hẳn).
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from utils.log import logger

SO_NHOM = 2

_khoa = threading.Lock()
_dang_tinh = False
_san: dict[str, Any] | None = None      # {"vec", "nhom", "model"} khi đã sẵn


def _tai_lieu() -> tuple[list[str], list[str]]:
    from services.agent import capabilities as caps
    ds = sorted(caps.CAPABILITIES.values(), key=lambda c: c.name)
    return [f"{c.name}: {c.description}" for c in ds], [caps.group_of(c.name) for c in ds]


def _tinh() -> None:
    """Vector cho mọi mô tả tool (luồng nền). Model nhúng chưa sẵn thì thôi — lượt sau gọi lại."""
    global _dang_tinh, _san
    try:
        import numpy as np

        from services import nhung
        from services.config import DATA_DIR

        tai_lieu, nhom = _tai_lieu()
        dau = nhung.vec(tai_lieu[0])           # chạy một lần để biết đường (GPU fp16 / CPU int8) trước khi tra đĩa
        if dau is None:
            return
        model = nhung.ten_model()
        bam = hashlib.sha256("\n".join([model] + tai_lieu).encode()).hexdigest()[:16]
        tep = DATA_DIR / "agent" / f"dinh_tuyen_nhung_{bam}.npy"
        if tep.exists():
            vec = np.load(tep)
        else:
            ds = [dau]
            for t in tai_lieu[1:]:
                v = nhung.vec(t)
                if v is None or nhung.ten_model() != model:
                    return                  # đổi đường giữa chừng — bộ vector lẫn hai đường thì bỏ, lượt sau tính lại
                ds.append(v)
            vec = np.stack(ds)
            tep.parent.mkdir(parents=True, exist_ok=True)
            np.save(tep, vec)               # mỗi đường một tệp (mã băm gồm đường) — GPU hỏng rồi lành không tính lại
        _san = {"vec": vec, "nhom": nhom, "model": model}
        logger.info({"event": "dinh_tuyen_nhung_san", "so_tool": len(nhom)})
    except Exception as exc:
        logger.warning({"event": "dinh_tuyen_nhung_hong", "error": str(exc)[:200]})
    finally:
        with _khoa:
            _dang_tinh = False


def nhom_theo_nghia(chu: str, k: int = SO_NHOM) -> set[str] | None:
    """Nhóm của ``k`` tool có mô tả gần nghĩa ``chu`` nhất; ``None`` khi chưa sẵn (khởi luồng tính)."""
    global _dang_tinh
    from services import nhung

    chu = str(chu or "").strip()
    if not chu:
        return set()
    v = nhung.vec(chu)
    if _san is None or _san["model"] != nhung.ten_model():
        with _khoa:
            if not _dang_tinh and v is not None:
                _dang_tinh = True
                threading.Thread(target=_tinh, name="dinh-tuyen-nhung", daemon=True).start()
        return None
    if v is None:
        return None
    # nhóm của k TOOL đứng đầu (hai tool cùng nhóm thì chỉ một nhóm) — đúng cách đã đo
    return {_san["nhom"][int(j)] for j in (_san["vec"] @ v).argsort()[::-1][:k]}
