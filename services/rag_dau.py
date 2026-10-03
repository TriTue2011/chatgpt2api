"""RAG NGAY CÂU ĐẦU — tìm tài liệu trong kho nhà TRƯỚC khi đưa câu cho LLM, không chờ model tự gọi công cụ.

Chủ máy 03/10/2026: "ngay khi rq đầu đẩy tới rag + reranking trước khi đẩy sang model llm". Kho = mọi kho RAG của
vn-mcp-hub (gte + xếp lại trên GPU, `retriever.tim_moi_kho`, route `/api/rag/tim`).

CHÈN KHI NÀO — đo cùng ngày, không chọn bằng tay: 130 câu hỏi đặt từ đoạn THẬT của kho (đáp án nằm trong kho) và
346 tin nhắn THẬT của nhật ký (trò chuyện, lệnh nhà, tra ngoài kho). Điểm xếp lại cao nhất ≥ ``NGUONG`` = 0,0:
chèn được cho 70,8% câu kiến thức, chèn nhầm 2,3% tin nhắn thường (ngưỡng -0,5: 92,3% / 45,7% — quá nhiều nhầm;
0,5: 53,8% / 0,9%). Dưới ngưỡng thì không chèn gì — tán gẫu, lệnh nhà không bị nhồi tài liệu lạc đề.

Hub chậm/hỏng → không chèn (câu trả lời vẫn chạy như trước). Đoạn chèn qua `privacy_gate.redact_text` như
`search_sgk`: kho là dữ liệu không tin cậy.
"""
from __future__ import annotations

import json
import urllib.request

from utils.log import logger

HUB_TIM = "http://127.0.0.1:8005/api/rag/tim"
NGUONG = 0.0
TOI_DA_DOAN = 2
DOAN_TOI_DA_KY_TU = 900
HET_GIO = 3.0
#: Tin quá ngắn («ok», «có») không đáng tốn một lượt tìm ~230 ms — ngưỡng điểm cũng loại, đây chỉ để đỡ trễ.
CAU_NGAN_NHAT = 8


def tim(cau: str) -> list[dict]:
    req = urllib.request.Request(HUB_TIM, data=json.dumps({"cau": cau, "top": TOI_DA_DOAN}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=HET_GIO) as r:  # noqa: S310 — URL nội bộ cố định
        return list(json.loads(r.read().decode()).get("ket_qua") or [])


def khoi(cau: str) -> str:
    """Khối tài liệu cho system prompt; rỗng khi câu không cần (dưới ngưỡng) hoặc hub hỏng."""
    cau = " ".join(str(cau or "").split())
    if len(cau) < CAU_NGAN_NHAT:
        return ""
    try:
        ds = [x for x in tim(cau) if x.get("diem") is not None and float(x["diem"]) >= NGUONG][:TOI_DA_DOAN]
    except Exception as exc:  # noqa: BLE001 — RAG là phần thêm: hỏng thì trả lời như cũ
        logger.info({"event": "rag_dau_bo_qua", "loi": str(exc)[:120]})
        return ""
    if not ds:
        return ""
    phan = []
    for i, x in enumerate(ds, 1):
        doan = str(x.get("text") or "").strip()
        if len(doan) > DOAN_TOI_DA_KY_TU:
            doan = doan[:DOAN_TOI_DA_KY_TU] + "…"
        phan.append(f"[{i}] (kho {x.get('kho')}, nguồn {x.get('source')})\n{doan}")
    text = ("## Tài liệu trong kho nhà (tự tìm theo câu hỏi này)\n"
            "Dùng nếu đúng ý câu hỏi — trả lời dựa trên đó và nêu nguồn; không liên quan thì bỏ qua, đừng nhắc tới.\n\n"
            + "\n\n".join(phan))
    try:
        from services.privacy_gate import redact_text
        text = redact_text(text, session_id="rag:dau")
    except Exception:  # noqa: BLE001
        pass
    logger.info({"event": "rag_dau_chen", "so_doan": len(ds), "diem": [round(float(x["diem"]), 2) for x in ds]})
    return text
