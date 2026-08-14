"""fw-nghe — faster-whisper large-v3 trên GPU, API HTTP cho phụ đề phim.

Trả segments + words (mốc từng từ) + avg_logprob (độ tự tin) — đủ thay
ys_log_probs + timestamps của transducer trong pipeline phụ đề, nên bên gateway
dùng lại được nguyên bộ gom khung `services/video_asr.py::gom_khung`.

Vì sao có dịch vụ này bên cạnh model nghe tại chỗ: đo trên bộ FLEURS (150 bản
thu mỗi tiếng, 14/08/2026) thì model tại chỗ bỏ trắng 7% đoạn tiếng Anh và 45%
đoạn tiếng Hàn — không trả chữ nào mà cũng không báo lỗi, nên phụ đề mất dòng
một cách im lặng. Xem `scripts/kiem_nghe.py` để đo lại và `docs/NGHE_GPU.md` để
biết cách bật.

Chạy trên máy có NVIDIA GPU (ở nhà: máy NVR 172.16.10.220, RTX 2060 Super 8 GB)::

    docker build -t fw-nghe .
    docker run -d --name fw-nghe --restart unless-stopped --gpus all \
        -p 5002:5000 -v fw-nghe-data:/data fw-nghe

Model tải lần đầu (~3 GB) vào volume `fw-nghe-data`, lần sau khởi động nhanh.
"""
import os
import tempfile
import threading
import time

from fastapi import FastAPI, File, Form, UploadFile

app = FastAPI()
# Một GPU 8 GB còn phải gánh camera (frigate/compreface) và máy dịch, nên chỉ
# cho một request giải mã một lúc — quá tải VRAM là CUDA OOM, cả tiến trình chết.
_lock = threading.Lock()
_model = None

MODEL = os.getenv("FW_MODEL", "large-v3")
COMPUTE = os.getenv("FW_COMPUTE", "int8_float16")


def _lay_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL, device="cuda", compute_type=COMPUTE,
                              download_root="/data")
    return _model


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "compute": COMPUTE}


@app.post("/nghe")
async def nghe(tep: UploadFile = File(...), lang: str = Form(""),
               batch: int = Form(8)):
    duoi = os.path.splitext(tep.filename or "a.wav")[1] or ".wav"
    fd, duong = tempfile.mkstemp(suffix=duoi)
    try:
        with os.fdopen(fd, "wb") as f:
            while True:
                khuc = await tep.read(1 << 20)
                if not khuc:
                    break
                f.write(khuc)
        model = _lay_model()
        t0 = time.time()
        with _lock:
            # batch<=1: đường thường (ít VRAM nhất) — card 8GB còn phải gánh
            # camera + máy dịch, lô to dễ OOM. Đo trên 2060S: batch 8 và 4 đều
            # OOM với video 10 phút, batch 2 chạy được.
            if int(batch) <= 1:
                segments, info = model.transcribe(
                    duong, language=(lang or None), word_timestamps=True,
                    vad_filter=True)
            else:
                from faster_whisper import BatchedInferencePipeline
                pipe = BatchedInferencePipeline(model=model)
                segments, info = pipe.transcribe(
                    duong, language=(lang or None), word_timestamps=True,
                    vad_filter=True, batch_size=int(batch))
            ra = []
            for s in segments:
                ra.append({
                    "bat_dau": round(s.start, 3), "ket_thuc": round(s.end, 3),
                    "chu": s.text.strip(), "tu_tin": round(s.avg_logprob, 4),
                    "tu": [{"t": round(w.start, 3), "k": round(w.end, 3),
                            "chu": w.word, "p": round(w.probability, 3)}
                           for w in (s.words or [])],
                })
        return {"lang": info.language,
                "xac_suat_lang": round(info.language_probability, 3),
                "dai_giay": round(info.duration, 1),
                "giay_xu_ly": round(time.time() - t0, 2), "doan": ra}
    finally:
        os.unlink(duong)
