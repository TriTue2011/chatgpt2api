"""RAG ngay câu đầu (chủ máy 03/10/2026). Không gọi mạng: hub và model đều giả.

Ngưỡng đo trên câu thật: điểm xếp lại ≥ 0,0 → chèn 70,8% câu kiến thức, chèn nhầm 2,3% tin nhắn thường.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402
from services import rag_dau  # noqa: E402

DOAN = [{"kho": "kb_giao_duc", "text": "Phép cộng có nhớ: đặt tính thẳng cột, cộng từ phải sang trái.", "source": "toan2", "diem": 1.2},
        {"kho": "ha_docs", "text": "Đèn phòng khách", "source": "ha", "diem": -0.4}]


def test_chi_chen_doan_du_diem(monkeypatch):
    monkeypatch.setattr(rag_dau, "tim", lambda cau: DOAN)
    k = rag_dau.khoi("dạy con phép cộng có nhớ thế nào")
    assert "Phép cộng có nhớ" in k and "Đèn phòng khách" not in k and "nêu nguồn" in k


def test_duoi_nguong_hoac_cau_ngan_hoac_hub_hong_thi_khong_chen(monkeypatch):
    monkeypatch.setattr(rag_dau, "tim", lambda cau: [DOAN[1]])
    assert rag_dau.khoi("bật đèn phòng khách") == ""
    goi = []
    monkeypatch.setattr(rag_dau, "tim", lambda cau: goi.append(cau) or DOAN)
    assert rag_dau.khoi("ok") == "" and goi == [], "tin quá ngắn: không tốn lượt tìm"

    def _hong(cau):
        raise OSError("hub tắt")
    monkeypatch.setattr(rag_dau, "tim", _hong)
    assert rag_dau.khoi("dạy con phép cộng có nhớ thế nào") == ""


def test_orchestrator_chen_vao_system_prompt_truoc_khi_goi_model(monkeypatch):
    from test._fakes import install_data_dir
    monkeypatch.setattr(rag_dau, "tim", lambda cau: DOAN)
    with install_data_dir():
        with mock.patch.object(orch, "call_model", return_value={"choices": [{"message": {"content": "Dạ"}}]}) as m:
            orch.orchestrate("dạy con phép cộng có nhớ thế nào", "zalop_rag")
    he = m.call_args.args[1][0]["content"]
    assert "Tài liệu trong kho nhà" in he and "Phép cộng có nhớ" in he


def test_hub_tim_moi_kho_gop_roi_xep_lai(monkeypatch, tmp_path):
    hub = Path(__file__).resolve().parents[1] / "vn-mcp-hub"
    if str(hub) not in sys.path:
        sys.path.insert(0, str(hub))
    from src.rag import retriever as rt

    class _Col:
        def __init__(self, docs):
            self.docs = docs

        def count(self):
            return len(self.docs)

        def query(self, query_embeddings, n_results, include=None):
            ds = self.docs[:n_results]
            return {"distances": [[d for d, _ in ds]], "documents": [[t for _, t in ds]], "metadatas": [[{"source": t} for _, t in ds]]}
    kho = {"a": _Col([(0.1, "a gần"), (0.5, "a xa")]), "b": _Col([(0.3, "b vừa")]), "rong": _Col([])}
    r = rt.RAGRetriever()
    r._client = type("C", (), {"list_collections": lambda self: list(kho)})()
    r._duong, r._embed_fn = tmp_path, (lambda texts: [[0.0]])
    r._collections = dict(kho)
    monkeypatch.setattr(rt, "CHROMA_GTE_PATH", tmp_path)
    monkeypatch.setattr(rt, "duong_kho", lambda: tmp_path)
    monkeypatch.setattr(rt, "_goi_c2a", lambda url, body, timeout: {"diem": [0.2, 3.0, -1.0]})
    ra = r.tim_moi_kho("câu hỏi")
    assert [x["text"] for x in ra] == ["b vừa", "a gần", "a xa"] and ra[0]["kho"] == "b" and ra[0]["diem"] == 3.0
