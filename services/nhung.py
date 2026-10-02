"""Model NHÚNG (embedding) chạy tại chỗ trên CPU — dùng chung cho mọi chỗ tìm theo nghĩa (chọn tool, tìm lại chuyện cũ).

Chủ máy 02/10/2026: "embedding + reranking áp vào toàn bộ mục khác (ngoài điều khiển HA), cứ dùng model tốt nhất".
Model nạp MỘT lần cho cả tiến trình, không mỗi nơi một bản — RAM .38 chật.

KHÔNG có reranker — đo cùng ngày trên bộ 297 câu: jina-reranker-v2 (int8) chấm lại 10 tool LÀM KÉM đi (AITeamVN
82,1 → 79,3%, gte 80,4 → 78,2%) và mất ~1,6 giây cho 10 ứng viên; bge-reranker-v2-m3 còn chậm hơn (phép đo chạy hơn
một giờ chưa xong). Với đoạn ngắn đều nhau như mô tả tool / tin nhắn, vector đã xếp đủ tốt.

Lần gọi đầu khởi luồng nền tải/nạp model (HF_HOME = data/hf, đổi ảnh không tải lại) và trả ``None``; người gọi
chạy đường cũ cho tới khi model sẵn. Model hỏng thì cũng ``None`` — không bao giờ tệ hơn đường cũ.
"""

from __future__ import annotations

import threading
from typing import Any

from utils.log import logger

#: (kho Hugging Face, tệp ONNX, tệp dữ liệu ngoài hoặc None, tệp tokenizer).
#:
#: Đo 02/10/2026 trên bộ 297 câu thật (chọn nhóm tool, 2 tool gần nhất gộp từ khoá, CPU .38): AITeamVN/Vietnamese_
#: Embedding 82,1% (108 ms/câu, RAM thêm ~1,7 GB); gte-multilingual-base int8 81,6% ở 256 token (24 ms/câu, RAM
#: ~0,66 GB; 80,4% ở 512); bge-m3 int8 81,6%; multilingual-e5-large 52,5% / 7 GB RAM. Chủ máy chọn gte: chạy GPU nhà
#: bản fp16 (~0,7 GB VRAM — AITeamVN ~2,5 GB làm GPU vượt 8 GB lúc Qwen-VL thức), lùi CPU bằng bản int8 này.
NHUNG = ("onnx-community/gte-multilingual-base", "onnx/model_int8.onnx", None, "tokenizer.json")
#: Câu người dùng và mô tả tool hiếm khi dài hơn; với gte cắt 256 đúng hơn 512 (81,6 / 80,4%).
TOI_DA_TOKEN = 256
LUONG = 2

_khoa = threading.Lock()
_dang_nap: set[str] = set()
_san: dict[str, tuple[Any, Any]] = {}       # "nhung" → (tokenizer, phiên ONNX)


def _nap(loai: str) -> None:
    try:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        kho, tep, du_lieu, tok = NHUNG
        if du_lieu:
            hf_hub_download(kho, du_lieu)
        t = Tokenizer.from_file(hf_hub_download(kho, tok))
        t.enable_truncation(TOI_DA_TOKEN)
        so = ort.SessionOptions()
        so.intra_op_num_threads = LUONG
        so.inter_op_num_threads = 1
        so.enable_cpu_mem_arena = False
        from services import onnx_xa
        # GPU nhà (bản fp16 trên fw-tach-am) khi có, lùi phiên CPU int8 này khi GPU hỏng (`onnx_xa`).
        _san[loai] = (t, onnx_xa.lai("gte_nhung", ort.InferenceSession(hf_hub_download(kho, tep), so,
                                                                       providers=["CPUExecutionProvider"])))
        logger.info({"event": "nhung_san", "loai": loai, "model": kho})
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "nhung_nap_loi", "loai": loai, "error": str(exc)[:200]})
    finally:
        with _khoa:
            _dang_nap.discard(loai)


def _lay(loai: str) -> tuple[Any, Any] | None:
    if loai in _san:
        return _san[loai]
    with _khoa:
        if loai not in _san and loai not in _dang_nap:
            _dang_nap.add(loai)
            threading.Thread(target=_nap, args=(loai,), name=f"nhung-{loai}", daemon=True).start()
    return None


def _vao(tok: Any, phien: Any, e: Any) -> dict[str, Any]:
    import numpy as np
    feed = {"input_ids": np.array([e.ids], dtype=np.int64), "attention_mask": np.array([e.attention_mask], dtype=np.int64)}
    if any(i.name == "token_type_ids" for i in phien.get_inputs()):
        feed["token_type_ids"] = np.array([e.type_ids], dtype=np.int64)
    return feed


def vec(chu: str):
    """Vector đã chuẩn hoá (numpy) của ``chu``; ``None`` khi model chưa sẵn / lỗi."""
    import numpy as np
    m = _lay("nhung")
    if m is None:
        return None
    tok, phien = m
    try:
        h = phien.run(None, _vao(tok, phien, tok.encode(str(chu or ""))))[0][0, 0]
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "nhung_loi", "error": str(exc)[:200]})
        return None
    return (h / (np.linalg.norm(h) or 1.0)).astype(np.float32)


def ten_model() -> str:
    """Định danh cấu hình model KÈM đường vừa chạy (gpu/cpu) — đổi model/cắt token, hay GPU hỏng nên lùi CPU (fp16 so
    với int8: cosine 0,97–0,99), thì vector cũ không còn so được với vector mới."""
    m = _san.get("nhung")
    return "|".join([*NHUNG[:2], str(TOI_DA_TOKEN), str(getattr(m[1], "duong", "cpu") if m else "cpu")])
