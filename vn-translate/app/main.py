"""vn-translate — máy dịch tự chủ, API GIỐNG LibreTranslate.

Vì sao giả lập đúng API LibreTranslate: gateway chatgpt2api đã có client hoàn
chỉnh cho API đó (services/translate_service.py). Giữ đúng hợp đồng thì đổi
engine chỉ là đổi TRANSLATE_URL — không sửa một dòng client nào.

    POST /translate   {q: str|list, source, target, format?, api_key?}
        → {translatedText, detectedLanguage?, nganh?}
    POST /detect      {q} → [{confidence, language}]
    GET  /languages       → [{code, name, targets}]
    GET  /health          → {status: "ok"}
    GET  /frontend/settings → {filesTranslation: false, supportedFilesFormat: []}

Khác LibreTranslate ở phần LÕI:
- Engine NLLB-200 (CTranslate2, CPU): một model phủ mọi cặp, vi↔ja/ko/zh dịch
  THẲNG không bắc cầu qua tiếng Anh; tự chuyển model khi lỗi (engine.py).
- Tầng thuật ngữ CHUYÊN NGÀNH (terms.py): thuật ngữ dịch bằng bảng tra, engine
  chỉ dịch phần còn lại. Phản hồi kèm ``nganh`` — trường THÊM, client cũ không
  đọc cũng không sao.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import terms
from .engine import ISO2FLORES, TEN_NGON_NGU, KhongCoNgonNgu, co_chu, engine

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("vn-translate")

app = FastAPI(title="vn-translate", docs_url=None, redoc_url=None)

#: Ngôn ngữ khai ra ngoài — mặc định đúng bộ chủ máy cần. NLLB có 200; thêm mã
#: vào TT_LANGS (phải có trong engine.ISO2FLORES) là xong, không tải thêm gì.
LANGS = [x.strip() for x in os.getenv(
    "TT_LANGS", "en,vi,ja,ko,zh-Hans").split(",") if x.strip() in ISO2FLORES]
GLOSSARY_ON = os.getenv("TT_GLOSSARY", "1").strip().lower() not in ("0", "false", "off")


@app.exception_handler(Exception)
async def _loi_chung(request: Request, exc: Exception):
    # LibreTranslate trả {"error": "..."} — client gateway đọc đúng khoá này.
    logger.warning("lỗi %s %s: %s", request.method, request.url.path, str(exc)[:300])
    return JSONResponse({"error": str(exc)[:300]}, status_code=500)


async def _doc_body(request: Request) -> dict[str, Any]:
    """Nhận cả JSON lẫn form — LibreTranslate nhận cả hai, client nào quen kiểu
    nào cũng dùng được."""
    ct = (request.headers.get("content-type") or "").lower()
    if "json" in ct:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    form = await request.form()
    return dict(form)


def _detect(text: str) -> tuple[str, float]:
    """(mã ISO như LibreTranslate khai, độ tự tin 0..100)."""
    from langdetect import DetectorFactory, detect_langs
    DetectorFactory.seed = 0
    try:
        ung = detect_langs(str(text or "")[:4000])
    except Exception:
        return "en", 0.0
    for u in ung:
        ma = {"zh-cn": "zh-Hans", "zh-tw": "zh-Hant"}.get(u.lang, u.lang)
        if ma in LANGS or ma in ISO2FLORES:
            return ma, round(float(u.prob) * 100, 1)
    return "en", 0.0


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/languages")
def languages():
    return [{"code": m, "name": TEN_NGON_NGU.get(m, m), "targets": list(LANGS)}
            for m in LANGS]


@app.get("/frontend/settings")
def frontend_settings():
    # Không dịch tệp giữ-định-dạng (v1): khai rỗng để client gateway tự đi đường
    # trích-chữ — hành vi đã có sẵn bên đó, không cần sửa gì.
    return {"charLimit": -1, "apiKeys": False, "filesTranslation": False,
            "supportedFilesFormat": [], "suggestions": False}


@app.post("/detect")
async def detect(request: Request):
    body = await _doc_body(request)
    q = str(body.get("q") or "")
    if not q:
        return JSONResponse({"error": "Invalid request: missing q parameter"}, 400)
    ma, tin = _detect(q)
    return [{"confidence": tin, "language": ma}]


def _dich_nhieu(texts: list[str], nguon: str, dich: str) -> tuple[list[str], list[str]]:
    """Dịch cả LÔ qua tầng thuật ngữ + engine trong MỘT lần gọi model.

    Trước đây mỗi phần tử ``q`` là một lượt engine riêng — model toàn nhận lô
    1 câu, ``max_batch_size`` không bao giờ có tác dụng và GPU không bõ chuyến
    (đo 14/08: lô 120 câu chỉ nhanh 1,8× CPU, khớp đúng độ trễ từng-câu-một).
    Gom mảnh của MỌI phần tử vào một lượt ``translate_batch`` rồi chia lại.

    Chỉ gửi mảnh CÓ CHỮ; mảnh toàn dấu câu đi thẳng qua. Tokenizer NLLB nuốt
    khoảng trắng ở biên khi decode → phải đắp lại biên của mảnh GỐC, không thì
    thuật ngữ dính vào chữ bên cạnh ("áp-tô-mátbên cạnh" — đo thật 12/08).
    """
    nganh_ap: list[str] = []
    tung_text: list[list[tuple[bool, str]]] = []
    for text in texts:
        if not (text or "").strip():
            tung_text.append([(False, text)])
            continue
        doan: list[tuple[bool, str]] = [(True, text)]
        if GLOSSARY_ON:
            ds = terms.doan_nganh(text, nguon, dich)
            if ds:
                nganh_ap.extend(ten for _, ten, _ in ds if ten not in nganh_ap)
                cap = [c for _, _, cs in ds for c in cs]
                doan = terms.tach_thuat_ngu(text, cap)
        tung_text.append(doan)

    goi: list[str] = []
    vi_tri: list[tuple[int, int]] = []
    for ti, doan in enumerate(tung_text):
        for pi, (ok, s) in enumerate(doan):
            if ok and co_chu(s):
                goi.append(s)
                vi_tri.append((ti, pi))
    ra_engine = engine.dich(goi, nguon, dich) if goi else []

    ghep = [[s for _, s in doan] for doan in tung_text]
    for (ti, pi), ban in zip(vi_tri, ra_engine):
        goc = tung_text[ti][pi][1]
        trai = goc[:len(goc) - len(goc.lstrip())]
        phai = goc[len(goc.rstrip()):]
        ghep[ti][pi] = f"{trai}{ban.strip()}{phai}"
    return ["".join(g) for g in ghep], nganh_ap


@app.post("/translate")
async def translate(request: Request):
    body = await _doc_body(request)
    q = body.get("q")
    nguon = str(body.get("source") or "").strip()
    dich = str(body.get("target") or "").strip()
    if not q:
        return JSONResponse({"error": "Invalid request: missing q parameter"}, 400)
    if not nguon:
        return JSONResponse({"error": "Invalid request: missing source parameter"}, 400)
    if not dich:
        return JSONResponse({"error": "Invalid request: missing target parameter"}, 400)

    lo = isinstance(q, list)
    texts = [str(x) for x in q] if lo else [str(q)]

    da_detect = None
    if nguon == "auto":
        ma, tin = _detect("\n".join(texts))
        da_detect = {"confidence": tin, "language": ma}
        nguon = ma
    try:
        ra, nganh = _dich_nhieu(texts, nguon, dich)
    except KhongCoNgonNgu as exc:
        return JSONResponse({"error": str(exc)}, 400)

    kq: dict[str, Any] = {"translatedText": ra if lo else ra[0]}
    if da_detect:
        kq["detectedLanguage"] = [da_detect] * len(texts) if lo else da_detect
    if nganh:
        kq["nganh"] = nganh          # trường THÊM — client cũ bỏ qua vô hại
    return kq


@app.on_event("startup")
def _khoi_dong():
    """Nạp model NGAY khi container lên (không đợi request đầu): /health sống
    tức thì, còn lượt dịch đầu tiên không phải gánh 30–60s nạp model."""
    import threading
    threading.Thread(target=engine.khoi_dong, daemon=True).start()
