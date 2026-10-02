"""Chọn nhóm tool THEO NGHĨA câu người dùng — model embedding chạy tại chỗ, trước khi gọi LLM.

Chủ máy 02/10/2026: "ngay khi rq đầu đầy tới rag + reranking trước khi đẩy sang model llm", "Không dùng code à,
phải dùng model", "Viết code để cho toàn bộ model của tôi đều làm được". Bảng từ khoá `_BANG_CHI_DUONG` chỉ bắt đủ
nhóm cho 41,3% câu cần tool (bộ 297 câu thật gán nhãn từ runs.sqlite); thiếu nhóm thì model — BẤT KỲ model nào —
không có schema để gọi. Chọn trước khi gọi LLM nên mọi model chính đều hưởng như nhau.

Đo cùng ngày trên bộ đó (CPU .38, 4 luồng): gte-multilingual-base int8 2 nhóm gộp với từ khoá → 81,6%; 24 ms/câu;
RAM thêm ~660 MB. Gemini embedding 2 nhóm 81,0% nhưng phải gọi mạng mỗi câu và khoá hay 429; bge-m3 / bản tiếng Việt
của AITeamVN ngang ngửa mà nặng gấp 2–6 lần; multilingual-e5-large chỉ 52,5%. Ngưỡng điểm không tách được câu tán gẫu
(trung vị điểm cao nhất 0,575 so với 0,599 của câu cần tool) nên lấy cố định 2 nhóm gần nhất.

Model chưa nạp xong / tải không được / lỗi → ``None``: người gọi chạy như cũ bằng từ khoá. Lần gọi đầu khởi luồng nền
nạp model và tính vector 101 tool (~22 s CPU một lần; lưu đĩa theo mã băm mô tả tool, đổi ảnh mà mô tả không đổi
thì khỏi tính lại).
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from utils.log import logger

KHO = "onnx-community/gte-multilingual-base"
TEP = "onnx/model_int8.onnx"
#: Mô tả tool dài nhất ~200 token; câu người dùng hiếm khi dài hơn — cắt để RAM và độ trễ không phụ thuộc tin dài.
TOI_DA_TOKEN = 256
SO_NHOM = 2

_khoa = threading.Lock()
_dang_nap = False
_san: dict[str, Any] | None = None      # {"tok", "phien", "vec", "nhom"} khi đã sẵn


def _tai_lieu() -> tuple[list[str], list[str]]:
    from services.agent import capabilities as caps
    ds = sorted(caps.CAPABILITIES.values(), key=lambda c: c.name)
    return [f"{c.name}: {c.description}" for c in ds], [caps.group_of(c.name) for c in ds]


def _nhung(tok: Any, phien: Any, chu: str):
    import numpy as np
    e = tok.encode(chu)
    h = phien.run(None, {"input_ids": np.array([e.ids], dtype=np.int64),
                         "attention_mask": np.array([e.attention_mask], dtype=np.int64)})[0][0, 0]
    return h / (np.linalg.norm(h) or 1.0)


def _nap() -> None:
    global _dang_nap, _san
    try:
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        from services.config import DATA_DIR

        tok = Tokenizer.from_file(hf_hub_download(KHO, "tokenizer.json"))
        tok.enable_truncation(TOI_DA_TOKEN)
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.inter_op_num_threads = 1
        so.enable_cpu_mem_arena = False
        phien = ort.InferenceSession(hf_hub_download(KHO, TEP), so, providers=["CPUExecutionProvider"])
        tai_lieu, nhom = _tai_lieu()
        bam = hashlib.sha256("\n".join([KHO, TEP, str(TOI_DA_TOKEN)] + tai_lieu).encode()).hexdigest()[:16]
        tep = DATA_DIR / "agent" / f"dinh_tuyen_nhung_{bam}.npy"
        if tep.exists():
            vec = np.load(tep)
        else:
            vec = np.stack([_nhung(tok, phien, t) for t in tai_lieu]).astype(np.float32)
            tep.parent.mkdir(parents=True, exist_ok=True)
            for cu in tep.parent.glob("dinh_tuyen_nhung_*.npy"):
                cu.unlink()
            np.save(tep, vec)
        _san = {"tok": tok, "phien": phien, "vec": vec, "nhom": nhom}
        logger.info({"event": "dinh_tuyen_nhung_san", "so_tool": len(nhom)})
    except Exception as exc:
        logger.warning({"event": "dinh_tuyen_nhung_hong", "error": str(exc)[:200]})
    finally:
        with _khoa:
            _dang_nap = False


def nhom_theo_nghia(chu: str, k: int = SO_NHOM) -> set[str] | None:
    """Nhóm của ``k`` tool có mô tả gần nghĩa ``chu`` nhất; ``None`` khi model chưa sẵn (lần đầu: khởi luồng nạp)."""
    global _dang_nap
    chu = str(chu or "").strip()
    if not chu:
        return set()
    if _san is None:
        with _khoa:
            if _san is None and not _dang_nap:
                _dang_nap = True
                threading.Thread(target=_nap, name="dinh-tuyen-nhung", daemon=True).start()
        return None
    try:
        diem = _san["vec"] @ _nhung(_san["tok"], _san["phien"], chu)
    except Exception as exc:
        logger.warning({"event": "dinh_tuyen_nhung_loi", "error": str(exc)[:200]})
        return None
    # nhóm của k TOOL gần nhất (hai tool cùng nhóm thì chỉ một nhóm) — đúng cách đã đo
    return {_san["nhom"][int(j)] for j in diem.argsort()[::-1][:k]}
