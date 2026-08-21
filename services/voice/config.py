"""Cấu hình kênh giọng nói (TTS/STT + loa) — đọc từ config key `voice`.

Nguyên tắc đóng gói (xem voices/piper/README.md):
  - CODE nằm trong image (binary piper, thư viện sherpa-onnx).
  - MODEL nằm NGOÀI image, trên volume `data/piper` + `data/stt` — tải bằng
    scripts/download_piper_voices.py và scripts/download_stt_model.py.
Nhờ vậy image không phình thêm ~1.3 GB model.

Backend theo thứ tự ưu tiên:
  local   — chạy thẳng trong tiến trình này (piper binary / sherpa-onnx)
  wyoming — gọi server Wyoming sẵn có (vd máy 192.168.1.100:10200/10401)
  off     — tắt

`auto` = thử local trước, không được thì wyoming.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from services.config import BASE_DIR, DATA_DIR, config

# Thư mục model (ngoài image, mount volume)
PIPER_DIR = Path(DATA_DIR) / "piper"
STT_DIR = Path(DATA_DIR) / "stt"
STT_EN_DIR = Path(DATA_DIR) / "stt-en"   # Parakeet-TDT (tiếng Anh)
#: Model nghe THÊM (Zipformer transducer k2-fsa — cùng dòng tiếng Việt, có
#: ys_log_probs + timestamps). Tải bằng scripts/download_stt_da_ngu.py.
STT_THEM_DIR = {
    "zh": Path(DATA_DIR) / "stt-zh",
    "ja": Path(DATA_DIR) / "stt-ja",
    "ko": Path(DATA_DIR) / "stt-ko",
}
#: SenseVoice-Small — MỘT model cho zh/ja/ko (và en/yue), thay ba Zipformer ở
#: trên. Đo 15/08/2026 trên đúng 150 bản thu FLEURS mỗi tiếng:
#:
#:     tiếng   Zipformer riêng từng tiếng      SenseVoice
#:     ko      55,5% sai ký tự · bỏ trắng 67   6,2% · bỏ trắng 0
#:     ja       9,8%                           7,0%
#:     zh      13,6%                          10,2%
#:
#: Tải nhẹ hơn hẳn (228 MB thay cho 1,3 GB); trên đĩa thì xấp xỉ nhau (229 MB
#: so với 295 MB) vì script cũ chỉ giữ lại bản int8.
STT_SENSE_DIR = Path(DATA_DIR) / "stt-sense"
KOKORO_DIR = Path(DATA_DIR) / "kokoro"   # Kokoro-82M (TTS tiếng Anh)
#: TTS cho phiên dịch đàm thoại — tải bằng scripts/download_tts_da_ngu.py.
KOKORO_ZH_DIR = Path(DATA_DIR) / "kokoro-zh"     # Kokoro đa ngữ v1.1 (100 giọng Trung)
SUPERTONIC_DIR = Path(DATA_DIR) / "supertonic"   # Supertonic-3 (31 tiếng, dùng ja/ko)
NGHI_DIR = Path(DATA_DIR) / "nghitts"    # 19 giọng NghiTTS (VITS tiếng Việt)
MEDIA_DIR = Path(DATA_DIR) / "voice" / "media"
# Manifest 19 giọng (nằm TRONG image — chỉ là danh mục, không phải model).
VOICES_MANIFEST = Path(BASE_DIR) / "voices" / "piper" / "voices.json"

_DEFAULT_VOICE = "ngochuyennew"

# Giọng namespaced: "vieneu:<Tên>" → VieNeu v3 Turbo, "kokoro:<tên>" → Kokoro
# tiếng Anh, "nghi:<mã>" → NghiTTS tiếng Việt, id trần → Piper.
VIENEU_PREFIX = "vieneu:"
VIENEU_BACKBONE_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
VIENEU_CODEC_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
KOKORO_PREFIX = "kokoro:"
NGHI_PREFIX = "nghi:"        # "nghi:<mã giọng>" → NghiTTS, xem nghitts_voices.py
# 11 giọng của gói kokoro-en-v0_19 (sherpa-onnx) — thứ tự = speaker id (sid).
KOKORO_VOICE_NAMES = [
    "af", "af_bella", "af_nicole", "af_sarah", "af_sky",
    "am_adam", "am_michael", "bf_emma", "bf_isabella", "bm_george", "bm_lewis",
]

# Nhãn tiếng Việt cho mã ngôn ngữ trong manifest.
_LANG_LABEL = {
    "vi": "Giọng Bắc/chuẩn",
    "vi-vn-x-south": "Giọng Nam bộ",
}


def voice_catalog() -> list[dict[str, Any]]:
    """Danh mục TẤT CẢ giọng từ manifest (19 giọng) — kèm cờ đã-tải-về-chưa.

    UI dùng để liệt kê đủ giọng cho người chọn/nghe thử, kể cả giọng chưa có
    file trên volume (khi đó nút nghe thử báo cần tải)."""
    try:
        data = json.loads(VOICES_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    downloaded = set(list_local_voices())
    default = str(data.get("default_voice") or _DEFAULT_VOICE)
    out: list[dict[str, Any]] = []
    for v in data.get("voices", []):
        if not isinstance(v, dict):
            continue
        vid = str(v.get("id") or "").strip()
        if not vid:
            continue
        lang = str(v.get("language") or "vi")
        out.append({
            "id": vid,
            "language": lang,
            "language_label": _LANG_LABEL.get(lang, lang),
            "downloaded": vid in downloaded,
            "default": vid == default,
        })
    # Giọng có trên volume nhưng thiếu trong manifest (người tự thêm) vẫn hiện.
    listed = {v["id"] for v in out}
    for vid in sorted(downloaded - listed):
        out.append({"id": vid, "language": "vi", "language_label": "",
                    "downloaded": True, "default": vid == default})
    # Giọng VieNeu (48 kHz, đọc được câu trộn Anh–Việt) — id "vieneu:<Tên>".
    vn_ready = vieneu_model_ready()
    for v in vieneu_voices():
        label = "VieNeu 48kHz"
        if v["gender"]:
            label += f" · {v['gender']}"
        out.append({
            "id": f"{VIENEU_PREFIX}{v['name']}",
            "language": "vi-en",
            "language_label": label,
            "downloaded": vn_ready,
            "default": False,
        })
    # Giọng NghiTTS tiếng Việt — id "nghi:<mã>". Tải từng giọng một nên cờ
    # downloaded xét RIÊNG từng giọng, không xét cả gói như Kokoro/VieNeu.
    from services.voice import nghitts_voices as _nv
    nghi_have = set(nghi_downloaded_ids())
    for nvoice in _nv.VOICES:
        out.append({
            "id": f"{NGHI_PREFIX}{nvoice.id}",
            "language": nvoice.language,
            "language_label": f"NghiTTS 22kHz · {nvoice.name} · "
                              + _LANG_LABEL.get(nvoice.language, nvoice.language),
            "downloaded": nvoice.id in nghi_have,
            "default": False,
        })
    # Giọng Kokoro tiếng Anh — id "kokoro:<tên>" (af=nữ Mỹ, am=nam Mỹ,
    # bf=nữ Anh, bm=nam Anh).
    kk_ready = kokoro_model_dir() is not None
    kk_label = {"af": "nữ Mỹ", "am": "nam Mỹ", "bf": "nữ Anh", "bm": "nam Anh"}
    for name in KOKORO_VOICE_NAMES:
        out.append({
            "id": f"{KOKORO_PREFIX}{name}",
            "language": "en",
            "language_label": "Kokoro EN · " + kk_label.get(name.split("_")[0], ""),
            "downloaded": kk_ready,
            "default": False,
        })
    # Kết quả ĐO phát âm (giọng tiếng Việt) — để người chọn giọng thấy giọng nào
    # rụng phụ âm thay vì phải nghe thử 52 giọng mới biết. Giọng chưa đo thì
    # không có trường này.
    from services.voice import chat_luong_giong as _clg
    for v in out:
        nx = _clg.nhan_xet(str(v.get("id") or ""))
        if nx is not None:
            v["phat_am"] = nx
    return out


def cfg() -> dict[str, Any]:
    try:
        c = config.get().get("voice")
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _sub(name: str) -> dict[str, Any]:
    v = cfg().get(name)
    return v if isinstance(v, dict) else {}


# ── TTS ──────────────────────────────────────────────────────────────────────


def tts_backend() -> str:
    """local | wyoming | auto | off"""
    b = str(_sub("tts").get("backend") or "auto").strip().lower()
    return b if b in {"local", "wyoming", "auto", "off"} else "auto"


def tts_voice() -> str:
    return str(_sub("tts").get("voice") or _DEFAULT_VOICE).strip() or _DEFAULT_VOICE


def tts_length_scale() -> float:
    """>1 = đọc chậm lại (piper --length-scale). Stack trên 200 dùng 1.1."""
    try:
        return float(_sub("tts").get("length_scale") or 1.1)
    except (TypeError, ValueError):
        return 1.1


def tts_wyoming_url() -> str:
    """tcp://host:port của wyoming-piper (trống = không dùng)."""
    return str(_sub("tts").get("wyoming_url") or "").strip()


def piper_binary() -> str:
    """Đường dẫn binary piper; trống = chưa cài (Dockerfile chưa tải)."""
    explicit = str(_sub("tts").get("piper_bin") or "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("piper")
    if found:
        return found
    for p in ("/opt/piper/piper", "/usr/local/bin/piper"):
        if Path(p).exists():
            return p
    return ""


def voice_model_path(name: str = "") -> Path | None:
    """File .onnx của giọng trong data/piper (None nếu chưa tải)."""
    v = (name or tts_voice()).strip()
    if v.startswith((VIENEU_PREFIX, KOKORO_PREFIX, NGHI_PREFIX)):
        v = _DEFAULT_VOICE   # giọng namespaced không phải file Piper — fallback
    if not v:
        return None
    p = PIPER_DIR / (v if v.endswith(".onnx") else f"{v}.onnx")
    return p if p.is_file() else None


def list_local_voices() -> list[str]:
    """Giọng đã tải về volume (không tính file .json)."""
    try:
        return sorted(p.stem for p in PIPER_DIR.glob("*.onnx") if p.is_file())
    except Exception:
        return []


def is_tts_enabled() -> bool:
    """Bật khi backend != off VÀ thực sự có đường chạy được."""
    b = tts_backend()
    if b == "off":
        return False
    has_piper = bool(piper_binary()) and voice_model_path() is not None
    has_vieneu = vieneu_installed() and vieneu_model_ready()
    has_kokoro = kokoro_model_dir() is not None
    has_nghi = nghi_ready()
    has_local = has_piper or has_vieneu or has_kokoro or has_nghi
    has_wyoming = bool(tts_wyoming_url())
    if b == "local":
        return has_local
    if b == "wyoming":
        return has_wyoming
    return has_local or has_wyoming


# ── VieNeu-TTS v3 Turbo (ONNX/CPU, 48 kHz, song ngữ Việt–Anh) ────────────────
# Cùng nguyên tắc Piper: CODE (gói vieneu, cài --no-deps) trong image; MODEL
# ngoài image trong cache HuggingFace trên volume data/hf — tải bằng
# scripts/download_vieneu_model.py. Giọng chọn qua id "vieneu:<Tên>".


def hf_cache_dir() -> Path:
    """Cache HuggingFace (model VieNeu) — volume data/hf, đè bằng env HF_HOME."""
    env = os.environ.get("HF_HOME", "").strip()
    return Path(env) if env else Path(DATA_DIR) / "hf"


def vieneu_installed() -> bool:
    try:
        return importlib.util.find_spec("vieneu") is not None
    except Exception:
        return False


def cpu_has_vnni() -> bool:
    """CPU có AVX512-VNNI / AVX-VNNI (nhân int8 chuyên dụng) không.

    int8 ONNX (VieNeu + Kokoro) CHỈ nhanh khi có VNNI. Xeon E5 / Core cũ
    (AVX2) chạy int8 **chậm hơn fp32 ~2–2.5×** → phải chọn fp32.
    Linux: /proc/cpuinfo. Env VOICE_CPU_VNNI=0|1 để ép (test/LXC lạ).
    """
    env = os.environ.get("VOICE_CPU_VNNI", "").strip().lower()
    if env in {"1", "true", "yes"}:
        return True
    if env in {"0", "false", "no"}:
        return False
    try:
        info = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").lower()
        return ("avx512_vnni" in info) or ("avx_vnni" in info)
    except Exception:
        return False


def effective_cpu_count() -> int:
    """Số CPU thực sự dùng được (cgroup Docker/LXC), không phải host full.

    `os.cpu_count()` trong container hay trả 20+ core host dù LXC chỉ gán 4
    → auto-thread cũ chiếm hết quota → LLM/PDF chết. Đọc cgroup trước.
    """
    # cgroup v2: "max 100000" hoặc "200000 100000"
    for rel in ("/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/cpu.max"):
        try:
            p = Path(rel)
            if not p.is_file():
                continue
            parts = p.read_text(encoding="utf-8").strip().split()
            if len(parts) >= 2 and parts[0] != "max":
                quota, period = int(parts[0]), int(parts[1])
                if quota > 0 and period > 0:
                    return max(1, (quota + period - 1) // period)
        except Exception:
            pass
    # cgroup v1
    try:
        q = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        p = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if q.is_file() and p.is_file():
            quota, period = int(q.read_text()), int(p.read_text())
            if quota > 0 and period > 0:
                return max(1, (quota + period - 1) // period)
    except Exception:
        pass
    # cpuset list "0-3,8"
    for rel in (
        "/sys/fs/cgroup/cpuset.cpus.effective",
        "/sys/fs/cgroup/cpuset.cpus",
        "/sys/fs/cgroup/cpuset/cpuset.cpus",
    ):
        try:
            p = Path(rel)
            if not p.is_file():
                continue
            raw = p.read_text(encoding="utf-8").strip()
            if not raw:
                continue
            n = 0
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    a, b = part.split("-", 1)
                    n += int(b) - int(a) + 1
                else:
                    n += 1
            if n > 0:
                return n
        except Exception:
            pass
    return max(1, int(os.cpu_count() or 1))


# Runtime override sau khi đo TTFA (int8 chậm hơn target → chuyển fp32).
# Chỉ áp khi precision config = auto; user ép int8/fp32 thì không đụng.
_precision_override: str | None = None
_precision_override_reason: str = ""
_last_warm_ttfa_s: float | None = None
_precision_lock = threading.Lock()


def tts_precision_cfg() -> str:
    """Giá trị config thô: auto | int8 | fp32."""
    return str(
        _sub("tts").get("precision")
        or _sub("tts").get("vieneu_precision")
        or "auto"
    ).strip().lower() or "auto"


def tts_precision_locked() -> bool:
    """True khi user ép int8/fp32 trong config — không auto-đổi theo TTFA."""
    return tts_precision_cfg() in {"int8", "fp32"}


def ttfa_target_s() -> float:
    """Ngưỡng WARM TTFA (giây). int8 vượt ngưỡng → thử chuyển fp32.

    Mặc định 0.56 (đỉnh dải 0.49–0.56 user kỳ vọng). Config:
    voice.tts.ttfa_target_s
    """
    try:
        v = float(_sub("tts").get("ttfa_target_s") or 0.56)
        return max(0.2, min(v, 3.0))
    except (TypeError, ValueError):
        return 0.56


def set_tts_precision_override(precision: str, reason: str = "") -> None:
    """Ghi đè quant runtime (warmup adaptive). precision = int8|fp32|"" (xoá)."""
    global _precision_override, _precision_override_reason
    p = (precision or "").strip().lower()
    with _precision_lock:
        if p in {"int8", "fp32"}:
            _precision_override = p
            _precision_override_reason = (reason or "")[:200]
        else:
            _precision_override = None
            _precision_override_reason = ""


def tts_precision_override() -> str | None:
    with _precision_lock:
        return _precision_override


def tts_precision_override_reason() -> str:
    with _precision_lock:
        return _precision_override_reason


def record_warm_ttfa(seconds: float) -> None:
    global _last_warm_ttfa_s
    try:
        _last_warm_ttfa_s = float(seconds)
    except (TypeError, ValueError):
        pass


def last_warm_ttfa_s() -> float | None:
    return _last_warm_ttfa_s


def tts_precision_prefer() -> str:
    """Chọn quant ưa thích cho MỌI engine TTS (VieNeu + Kokoro): int8 | fp32.

    Thứ tự:
      1. Runtime override (sau đo TTFA int8 không đạt target → fp32)
      2. Config ép int8|fp32
      3. auto: có VNNI → int8; không VNNI → fp32

    Config:
      voice.tts.precision = auto|int8|fp32
      voice.tts.vieneu_precision = … (alias)
    """
    ov = tts_precision_override()
    if ov in {"int8", "fp32"}:
        return ov
    raw = tts_precision_cfg()
    if raw in {"int8", "fp32"}:
        return raw
    return "int8" if cpu_has_vnni() else "fp32"


def auto_tts_threads() -> int:
    """Số thread TTS tự động: đủ TTFA ~0.5s, **không** chiếm hết CPU LXC/host.

    Dựa trên effective_cpu_count() (cgroup), chừa ≥½ core cho LLM/PDF/gateway:
      ≤2 CPU → 1 thread
      3–4    → 2 thread  (½ của 4, còn 2 cho việc khác)
      5–8    → 2 thread
      ≥9     → min(3, n//4)  (16→3, vẫn chừa phần lớn)

    Ép tay: voice.tts.num_threads / voice.tts.vieneu_threads.
    """
    n = effective_cpu_count()
    if n <= 2:
        return 1
    if n <= 8:
        return 2
    return max(2, min(3, n // 4))


def _vieneu_subfolder(precision: str) -> str:
    return "onnx_int8" if precision == "int8" else "onnx_update"


def _vieneu_model_present(precision: str) -> bool:
    sub = _vieneu_subfolder(precision)
    return (_hf_has(VIENEU_BACKBONE_REPO, f"{sub}/vieneu_prefill.onnx")
            and _hf_has(VIENEU_CODEC_REPO, "moss_audio_tokenizer_decode_full.onnx"))


def vieneu_precision() -> str:
    """int8 | fp32 — auto theo `tts_precision_prefer()` + model đã tải.

    Không hardcode int8. Check VNNI → chọn; bản preferred chưa có thì fallback
    bản còn lại trên volume (vẫn chạy được, log qua status).
    """
    preferred = tts_precision_prefer()
    if _vieneu_model_present(preferred):
        return preferred
    other = "fp32" if preferred == "int8" else "int8"
    if _vieneu_model_present(other):
        return other
    return preferred


def vieneu_backend() -> str:
    """auto (mặc định — image :gpu có torch+CUDA sẽ tự chạy PyTorch/GPU,
    image thường không có torch nên vẫn ONNX/CPU) | onnx | pytorch."""
    b = str(_sub("tts").get("vieneu_backend") or "auto").strip().lower()
    return b if b in {"auto", "onnx", "pytorch"} else "auto"


def vieneu_style() -> str:
    """tu_nhien (hội thoại) | tin_tuc | doc_truyen."""
    s = str(_sub("tts").get("vieneu_style") or "tu_nhien").strip()
    return s if s in {"tu_nhien", "tin_tuc", "doc_truyen"} else "tu_nhien"


def tts_threads() -> int:
    """Intra-op threads Kokoro/sherpa (≥1). Mặc định = auto_tts_threads()."""
    raw = _sub("tts").get("num_threads")
    if raw is None or str(raw).strip() == "":
        return max(1, auto_tts_threads())
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return max(1, auto_tts_threads())


def vieneu_threads() -> int:
    """Intra-op threads VieNeu ONNX. Mặc định = auto_tts_threads() (cgroup-aware).

    Không dùng os.cpu_count() host (dễ lấy 20 trong LXC 4 core). Không chiếm
    hết quota. Ép: env VIENEU_THREADS, hoặc voice.tts.vieneu_threads /
    voice.tts.num_threads trong config.json.

    ENV ĐỨNG TRƯỚC config.json, cùng nếp với VOICE_CPU_VNNI ở trên: số này tuỳ
    MÁY (số nhân, có VNNI hay không) chứ không tuỳ người dùng, nên chỗ khai
    đúng của nó là docker compose của từng máy — sửa config.json trong volume
    thì mỗi lần dựng máy mới lại phải nhớ làm lại.

    Đo 21/08/2026 trên máy chủ (10 nhân, CPU không có VNNI nên chạy fp32):
    2 luồng → 3,91 giây/câu; 5 luồng → 3,10 giây/câu; 8 luồng → 4,07 giây/câu.
    Tức nâng lên có ăn một ít rồi QUAY ĐẦU — đừng đặt bằng số nhân của máy.
    """
    env = os.environ.get("VIENEU_THREADS", "").strip()
    if env:
        try:
            return max(0, int(env))
        except ValueError:
            pass
    raw = _sub("tts").get("num_threads")
    raw_vn = _sub("tts").get("vieneu_threads")
    if raw_vn is not None and str(raw_vn).strip() != "":
        raw = raw_vn
    if raw is None or str(raw).strip() == "":
        return auto_tts_threads()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return auto_tts_threads()


def vieneu_max_chars() -> int:
    """Độ dài chunk text tối đa mỗi lần prefill VieNeu (mặc định 128).

    Nhỏ hơn → prefill ngắn hơn → audio đầu ra sớm hơn trên câu dài.
    SDK mặc định 256; 128 cân bằng TTFA vs số lần gọi engine.
    """
    try:
        n = int(_sub("tts").get("vieneu_max_chars") or 128)
        return max(48, min(n, 256))
    except (TypeError, ValueError):
        return 128


def tts_warmup() -> bool:
    """Nạp model VieNeu/Kokoro lúc startup (mặc định bật) — lần đọc đầu không cold-start."""
    v = _sub("tts").get("warmup")
    if v is None:
        return True
    return bool(v)


def tts_cache_mb() -> int:
    """Trần RAM (MB) cho cache audio TTS. 0 = tắt. Mặc định 64 MB.

    Trợ lý nhà lặp lại vài chục câu ("Đã bật đèn phòng khách"...) — đọc lần hai
    trở đi lấy thẳng từ cache, không tốn CPU. Xem services/voice/tts_cache.py.
    """
    raw = _sub("tts").get("cache_mb")
    if raw is None or str(raw).strip() == "":
        return 64
    try:
        return max(0, min(int(raw), 512))
    except (TypeError, ValueError):
        return 64


def tts_sentence_silence_ms() -> int:
    """Khoảng lặng chèn GIỮA hai câu. 0 = tắt (đọc dính liền).

    Áp cho MỌI engine (Piper/Kokoro/NghiTTS/Wyoming/VieNeu): văn bản được cắt
    thành câu, mỗi câu một lần gọi engine, nối lại bằng đúng khoảng lặng này.
    Đặt 0 (cùng với clause_silence_ms) thì đọc trọn văn bản trong một lần gọi
    như trước — nhanh nhất, ngữ điệu liền mạch nhất.
    """
    raw = _sub("tts").get("sentence_silence_ms")
    if raw is None or str(raw).strip() == "":
        return 350
    try:
        return max(0, min(int(raw), 3000))
    except (TypeError, ValueError):
        return 350


def tts_clause_silence_ms() -> int:
    """Khoảng lặng sau dấu phẩy / chấm phẩy / hai chấm TRONG một câu. 0 = tắt.

    Bật (vd 180 ms, như add-on wyoming-vietnamese) thì mỗi mệnh đề thành một
    lần gọi engine riêng: nhịp nghỉ rõ hơn nhưng đổi lại engine đọc từng mệnh
    đề như một câu độc lập (ngữ điệu tách rời) và tốn thêm thời gian tổng hợp.
    Vì vậy mặc định 0 — người dùng tự bật trong Cài đặt nếu thích nhịp đó.
    """
    raw = _sub("tts").get("clause_silence_ms")
    if raw is None or str(raw).strip() == "":
        return 0
    try:
        return max(0, min(int(raw), 3000))
    except (TypeError, ValueError):
        return 0


def tts_silence_jitter_percent() -> int:
    """Dao động ±% quanh khoảng lặng để nhịp nghỉ không đều tăm tắp như máy đếm.

    0 = tắt dao động. Mặc định 25%.
    """
    raw = _sub("tts").get("silence_jitter_percent")
    if raw is None or str(raw).strip() == "":
        return 25
    try:
        return max(0, min(int(raw), 100))
    except (TypeError, ValueError):
        return 25


def _hf_has(repo: str, rel_pattern: str) -> bool:
    """File đã có trong cache HF chưa (hub/models--org--repo/snapshots/*/rel)."""
    root = hf_cache_dir() / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots"
    try:
        return any(root.glob(f"*/{rel_pattern}"))
    except Exception:
        return False


def vieneu_model_ready() -> bool:
    """True nếu có ít nhất một bản ONNX (int8 hoặc fp32) + codec."""
    return _vieneu_model_present("int8") or _vieneu_model_present("fp32")


def kokoro_model_dir() -> Path | None:
    """Thư mục model Kokoro EN (tải bằng download_kokoro_model.py). Chấp nhận
    cả bản fp32 (model.onnx) lẫn int8 (model.int8.onnx — nhẹ & nhanh hơn)."""
    d = str(_sub("tts").get("kokoro_dir") or "").strip()
    base = Path(d) if d else KOKORO_DIR
    if not base.is_dir():
        return None
    if not (base / "voices.bin").is_file() or not (base / "tokens.txt").is_file():
        return None
    if not list(base.glob("model*.onnx")):
        return None
    return base


def kokoro_model_file() -> Path | None:
    """File .onnx Kokoro — auto int8/fp32 giống VieNeu (theo VNNI + file có sẵn).

    Có VNNI + model.int8.onnx → int8; không VNNI → model.onnx (fp32) nếu có.
    Không hardcode ưu tiên int8 (int8 trên Xeon E5 làm chậm).
    """
    base = kokoro_model_dir()
    if base is None:
        return None
    hits = sorted(base.glob("model*.onnx"))
    if not hits:
        return None
    int8s = [p for p in hits if "int8" in p.name]
    fp32s = [p for p in hits if "int8" not in p.name]
    prefer = tts_precision_prefer()
    if prefer == "int8" and int8s:
        return int8s[0]
    if prefer == "fp32" and fp32s:
        return fp32s[0]
    # Fallback bản còn lại.
    if prefer == "int8" and fp32s:
        return fp32s[0]
    if prefer == "fp32" and int8s:
        return int8s[0]
    return hits[0]


# ── NghiTTS (19 giọng tiếng Việt, VITS 22,05 kHz qua sherpa-onnx) ────────────
# Cùng nguyên tắc Kokoro: danh mục trong image (nghitts_voices.py), model ngoài
# volume data/nghitts/<mã giọng>/ — tải bằng scripts/download_nghitts_voices.py.


def nghi_dir() -> Path:
    """Thư mục gốc chứa model NghiTTS; đè bằng ``voice.tts.nghi_dir``."""
    d = str(_sub("tts").get("nghi_dir") or "").strip()
    return Path(d) if d else NGHI_DIR


def nghi_voice_dir(voice_id: str) -> Path | None:
    """Thư mục một giọng khi đã đủ file dùng được, None nếu chưa.

    Đòi cả dấu ghi nhận đã-vá-metadata: model NghiTTS nguyên bản không có
    metadata nên sherpa-onnx từ chối nạp (xem nghitts_voices.sherpa_metadata).
    Thiếu dấu này mà vẫn nhận thì giọng hiện ra trong danh mục rồi bấm vào mới
    lỗi — thà coi như chưa tải.

    Mã giọng phải nằm trong danh mục — chặn luôn đường dẫn kiểu "../" đi ra
    ngoài thư mục model.
    """
    from services.voice import nghitts_voices as nv

    voice = nv.get(voice_id)
    if voice is None:
        return None
    base = nghi_dir() / voice.id
    need = (nv.MODEL_FILE, nv.CONFIG_FILE, nv.TOKENS_FILE, nv.PREPARED_FILE)
    return base if all((base / n).is_file() for n in need) else None


def nghi_downloaded_ids() -> list[str]:
    """Mã các giọng NghiTTS đã tải đủ file trên volume."""
    from services.voice import nghitts_voices as nv

    return [v.id for v in nv.VOICES if nghi_voice_dir(v.id) is not None]


def nghi_espeak_data_dir() -> Path | None:
    """Thư mục espeak-ng-data dùng cho phonemizer NghiTTS, None nếu không có.

    NghiTTS là VITS phonemizer espeak nên bắt buộc có dữ liệu này. KHÔNG cần
    thêm gì vào image: bản piper trong /opt/piper đã kèm sẵn (đã kiểm bản
    2023.11.14-2, có đủ vi_dict và lang/aav/vi). Gói Kokoro cũng kèm một bản.
    Thứ tự tìm: cạnh model → Kokoro → piper → hệ thống. Ép bằng
    ``voice.tts.nghi_espeak_dir``.
    """
    need = ("phondata", "phontab", "vi_dict", "lang/aav/vi")

    def ok(p: Path) -> bool:
        return all((p / n).is_file() for n in need)

    forced = str(_sub("tts").get("nghi_espeak_dir") or "").strip()
    if forced:
        p = Path(forced).expanduser()
        return p if ok(p) else None
    candidates = [
        nghi_dir() / "espeak-ng-data",
        KOKORO_DIR / "espeak-ng-data",
        Path("/opt/piper/espeak-ng-data"),
        Path("/usr/share/espeak-ng-data"),
        Path("/usr/lib/espeak-ng-data"),
    ]
    candidates += sorted(Path("/usr/lib").glob("*-linux-gnu/espeak-ng-data"))
    for c in candidates:
        try:
            if ok(c):
                return c
        except OSError:
            continue
    return None


def nghi_all_ids() -> list[str]:
    """Mã của mọi giọng trong danh mục, kể cả giọng chưa tải."""
    from services.voice import nghitts_voices as nv

    return [v.id for v in nv.VOICES]


def nghi_ready() -> bool:
    """Có ít nhất một giọng đã tải VÀ có espeak-ng-data để đọc."""
    return bool(nghi_downloaded_ids()) and nghi_espeak_data_dir() is not None


def nghi_max_loaded() -> int:
    """Số model NghiTTS giữ đồng thời trong RAM (mặc định 2).

    Mỗi model khoảng 60–80 MB; nạp cả 19 giọng là hơn 1 GB. Giữ vài giọng dùng
    gần đây là đủ cho nhà dùng 1–2 giọng, mà đổi giọng vẫn không phải nạp lại
    ngay lần sau.
    """
    raw = _sub("tts").get("nghi_max_loaded")
    if raw is None or str(raw).strip() == "":
        return 2
    try:
        return max(1, min(int(raw), 19))
    except (TypeError, ValueError):
        return 2


def kokoro_sid(name: str) -> int:
    """Tên giọng Kokoro → speaker id; sai tên = 0 (giọng af mặc định)."""
    try:
        return KOKORO_VOICE_NAMES.index(name)
    except ValueError:
        return 0


def vieneu_voices() -> list[dict[str, Any]]:
    """Giọng preset của VieNeu — đọc từ asset json trong package, KHÔNG nạp
    model (nạp model tốn RAM/thời gian, chỉ làm khi thật sự đọc)."""
    if not vieneu_installed():
        return []
    try:
        from importlib.resources import files
        raw = (files("vieneu") / "assets" / "voices_v3_turbo.json").read_text(
            encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for name, v in (data.get("presets") or {}).items():
        if not isinstance(v, dict):
            continue
        out.append({
            "name": str(name),
            "gender": str(v.get("gender") or ""),
            "description": str(v.get("description") or ""),
        })
    return out


# ── STT ──────────────────────────────────────────────────────────────────────


def stt_backend() -> str:
    b = str(_sub("stt").get("backend") or "auto").strip().lower()
    return b if b in {"local", "wyoming", "auto", "off"} else "auto"


def stt_wyoming_url() -> str:
    return str(_sub("stt").get("wyoming_url") or "").strip()


def stt_model_dir() -> Path | None:
    """Thư mục model Zipformer (phải có ít nhất encoder*.onnx)."""
    d = str(_sub("stt").get("model_dir") or "").strip()
    base = Path(d) if d else STT_DIR
    if not base.is_dir():
        return None
    if not list(base.glob("encoder*.onnx")):
        return None
    return base


def stt_language() -> str:
    """Ngôn ngữ STT do chatgpt2api cấu hình (Settings → Giọng nói).

    - ``vi``   — Zipformer tiếng Việt (mặc định; offline EN đã tắt)
    - ``en``   — Parakeet English (cần model trên đĩa)
    - ``auto`` — dò trong nhóm tiếng đã bật (xem ``stt_nhom_tieng``)
    """
    v = str(_sub("stt").get("language") or "vi").strip().lower().replace("_", "-")
    if v in {"auto", "mul", "multi", "und", "*"}:
        # EN STT off → auto collapses to vi
        if not stt_en_enabled():
            return "vi"
        return "auto"
    if v.startswith("en"):
        if not stt_en_enabled():
            return "vi"
        return "en"
    if v.startswith("vi"):
        return "vi"
    return "vi"


def stt_en_enabled() -> bool:
    """Còn để tương thích caller cũ — nay LUÔN True nếu model có trên đĩa.

    Bỏ cờ ``voice.stt.en_enabled`` (14/08): nó là di tích thời "offline EN chưa
    chuẩn", trong khi Parakeet đo được 21,3% WER trên talk show và các tiếng
    zh/ja/ko thêm sau KHÔNG có cờ nào tương tự — có model là dùng. Cờ này còn
    làm hỏng thầm: người dùng chọn `en` trong Cài đặt mà quên tick thì máy im
    lặng rơi về tiếng Việt.

    Đặt ``voice.stt.en_enabled: false`` vẫn TẮT được (đường lui cho ai đang
    dùng), nhưng mặc định là bật.
    """
    raw = _sub("stt").get("en_enabled")
    if raw is None:
        return True
    if isinstance(raw, str):
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return bool(raw)


def _stt_en_dir_raw() -> Path | None:
    """Thư mục model Parakeet, BỎ QUA cờ en_enabled — dùng để phân biệt lỗi
    "chưa tải model" với "tính năng đang tắt" (xem stt_en_model_present())."""
    d = str(_sub("stt").get("en_model_dir") or "").strip()
    base = Path(d) if d else STT_EN_DIR
    if not base.is_dir():
        return None
    if not list(base.glob("encoder*.onnx")):
        return None
    return base


def stt_en_model_dir() -> Path | None:
    """Thư mục model Parakeet-TDT tiếng Anh (tải bằng download_stt_en_model.py).

    Trả None khi ``stt.en_enabled`` tắt — mọi caller coi như không có STT EN.
    """
    if not stt_en_enabled():
        return None
    return _stt_en_dir_raw()


def stt_en_model_present() -> bool:
    """True nếu file model Parakeet đã tải, BẤT KỂ cờ en_enabled bật/tắt
    (giúp caller báo đúng "đang tắt" thay vì "chưa tải")."""
    return _stt_en_dir_raw() is not None


def kokoro_zh_sid() -> int:
    """Giọng Trung mặc định của Kokoro đa ngữ v1.1 (sid 0..102, 100 giọng
    Trung). Đổi giọng qua ``voice.tts.kokoro_zh_sid``."""
    raw = _sub("tts").get("kokoro_zh_sid")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


#: Giọng mặc định của từng tiếng dùng Supertonic, chọn theo SỐ ĐO ngày
#: 14/08/2026 (``scripts/kiem_phat_am.py ja --giong 0,5,8,9 --lap 5``):
#:
#:     giọng   lượt nghe hụt
#:     5 (F1)      2/55        ← chọn
#:     8 (F4)      2/55
#:     9 (F5)      7/55
#:     0 (M1)     10/55        ← mặc định cũ
#:
#: Chốt 5 chứ không phải 8 vì ở vòng đo 10 giọng trước đó, 5 đọc đúng trọn
#: 13/13 âm còn 8 được 11/13. Tiếng Hàn giữ 0: đo hôm ấy nó đọc đủ 16/16 âm.
#:
#: Đừng đọc bảng này bằng cột "đúng/13" như hai vòng đo đầu: cột đó lấy đa số
#: nên bão hoà — bốn giọng cùng 12/13 trong khi số lượt hụt chênh nhau năm lần.
SUPERTONIC_SID_MAC_DINH: dict[str, int] = {"ja": 5, "ko": 0}


def supertonic_sid(lang: str) -> int:
    """Giọng Supertonic cho ja/ko (sid 0..9: M1-M5 nam, F1-F5 nữ).

    Config ``voice.tts.supertonic_ja_sid`` / ``supertonic_ko_sid`` — chỉnh
    trong Cài đặt → Loa & giọng nói. Không đặt thì lấy giọng đã đo là đọc rõ
    nhất của tiếng đó (``SUPERTONIC_SID_MAC_DINH``)."""
    ma = str(lang or "").lower()
    raw = _sub("tts").get(f"supertonic_{ma}_sid")
    try:
        return min(9, max(0, int(raw)))
    except (TypeError, ValueError):
        return SUPERTONIC_SID_MAC_DINH.get(ma, 0)


#: Quy chuẩn cổng Wyoming (chủ máy chốt 14/08): **106xx = TTS, 107xx = STT**;
#: xx theo tiếng: 00 việt · 01 anh · 02 nhật · 03 trung · 04 hàn. Mỗi cổng
#: một integration HA, một vai — ghép pipeline Assist không lẫn tiếng.
WYOMING_CHUAN: dict[str, dict[str, int]] = {
    "tts": {"vi": 10600, "en": 10601, "ja": 10602, "zh": 10603, "ko": 10604},
    "stt": {"vi": 10700, "en": 10701, "ja": 10702, "zh": 10703, "ko": 10704},
}


def wyoming_cong(vai: str, lang: str) -> int:
    """Cổng Wyoming cho (vai ``tts``/``stt``, tiếng). 0 = tắt cổng đó.

    Mặc định theo ``WYOMING_CHUAN``; đè từng cổng qua
    ``voice.wyoming_server.tts_port_vi`` / ``stt_port_ja`` / … Nhớ publish
    cổng trong compose thì máy ngoài mới gọi vào được."""
    mac_dinh = WYOMING_CHUAN.get(vai, {}).get(lang, 0)
    raw = _wy().get(f"{vai}_port_{lang}")
    if raw in (None, ""):
        return mac_dinh
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return mac_dinh


def stt_them_model_dir(lang: str) -> Path | None:
    """Thư mục model nghe của ngôn ngữ THÊM (zh/ja/ko) — ``None`` khi chưa tải.

    Khác tiếng Anh (cờ ``en_enabled``), nhóm này không có cờ bật/tắt: chủ máy
    chủ động chạy ``scripts/download_stt_da_ngu.py`` là dùng được — chưa tải
    thì coi như tắt, bộ dò ngôn ngữ tự rơi về tiếng Việt.
    """
    base = STT_THEM_DIR.get(str(lang or "").lower())
    if base is None or not base.is_dir() or not list(base.glob("encoder*.onnx")):
        return None
    return base


#: Tiếng nghe bằng SenseVoice khi model đó có trên đĩa. Không để tiếng Việt ở
#: đây: SenseVoice KHÔNG biết tiếng Việt. Tiếng Anh cũng không, vì bộ dò ngôn
#: ngữ của phụ đề so vi với en bằng ys_log_probs của transducer, mà SenseVoice
#: không trả số đó — đổi en là đụng vào phép so đang chạy đúng.
STT_SENSE_TIENG_MAC_DINH = ("zh", "ja", "ko")


def stt_sense_model_dir() -> Path | None:
    """Thư mục model SenseVoice — ``None`` khi chưa tải (rơi về Zipformer).

    Nhận diện bằng chính file model, không bằng tên thư mục: gói phát hành đặt
    tên ``model.int8.onnx``.
    """
    base = STT_SENSE_DIR
    if not base.is_dir():
        return None
    return base if list(base.glob("model*.onnx")) else None


def stt_sense_tieng() -> tuple[str, ...]:
    """Những tiếng dùng SenseVoice. Đặt qua ``voice.stt.sense_tieng``."""
    raw = _sub("stt").get("sense_tieng")
    if raw is None or str(raw).strip() == "":
        return STT_SENSE_TIENG_MAC_DINH
    muc = ([str(x) for x in raw] if isinstance(raw, (list, tuple))
           else str(raw).replace(";", ",").split(","))
    return tuple(dict.fromkeys(x.strip().lower() for x in muc if x.strip()))


def stt_threads() -> int:
    """Intra-op threads STT (≥1). Mặc định = auto_tts_threads() (cgroup-aware,
    cùng idiom với tts_threads()) — không chiếm hết CPU LXC nhỏ khiến
    LLM/gateway đói CPU. Ép tay qua voice.stt.num_threads."""
    raw = _sub("stt").get("num_threads")
    if raw is None or str(raw).strip() == "":
        return max(1, auto_tts_threads())
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return max(1, auto_tts_threads())


def stt_gpu_url() -> str:
    """Máy nghe GPU (faster-whisper) cho PHỤ ĐỀ — ví dụ http://172.16.10.220:5002.

    Rỗng = tắt, mọi việc nghe đi model tại chỗ như cũ. Có giá trị thì chỉ những
    tiếng trong ``stt_gpu_tieng()`` mới sang GPU, và GPU lỗi thì tự rơi về tại
    chỗ (xem services/nghe_gpu.py). Dịch vụ nằm ở fw-nghe/ trong repo này.
    """
    import os

    return str(os.getenv("NGHE_URL_GPU")
               or _sub("stt").get("gpu_url") or "").strip().rstrip("/")


#: Tiếng gửi sang máy GPU khi có khai địa chỉ. Mặc định lấy theo SỐ ĐO trên bộ
#: FLEURS 14/08/2026 — chỉ những tiếng mà model tại chỗ bỏ trắng đoạn:
#: en bỏ trắng 7%, ko bỏ trắng 45%. Tiếng Việt giữ tại chỗ (9,3% sai từ, không
#: bỏ trắng bản nào) để việc thường ngày không phụ thuộc máy thứ hai.
STT_GPU_TIENG_MAC_DINH = ("en", "ko")


def stt_gpu_tieng() -> tuple[str, ...]:
    """Những tiếng nghe bằng máy GPU. Đặt qua voice.stt.gpu_tieng ("en,ko")."""
    raw = _sub("stt").get("gpu_tieng")
    if raw is None or str(raw).strip() == "":
        return STT_GPU_TIENG_MAC_DINH
    if isinstance(raw, (list, tuple)):
        muc = [str(x) for x in raw]
    else:
        muc = str(raw).replace(";", ",").split(",")
    return tuple(dict.fromkeys(
        x.strip().lower() for x in muc if x and x.strip()))


def has_local_stt() -> bool:
    if stt_model_dir() is None:
        return False
    try:
        import sherpa_onnx  # noqa: F401
        return True
    except Exception:
        return False


def is_stt_enabled() -> bool:
    b = stt_backend()
    if b == "off":
        return False
    if b == "local":
        return has_local_stt()
    if b == "wyoming":
        return bool(stt_wyoming_url())
    return has_local_stt() or bool(stt_wyoming_url())


# ── Wyoming server nhúng (TTS+STT cho Home Assistant) ───────────────────────


def _wy() -> dict[str, Any]:
    v = cfg().get("wyoming_server")
    return v if isinstance(v, dict) else {}


def wyoming_enabled() -> bool:
    """Mặc định BẬT — chỉ nghe trong container; muốn HA gọi tới phải publish
    port trong docker-compose (ports: "10600:10600")."""
    v = _wy().get("enabled")
    return True if v is None else bool(v)


def wyoming_mode() -> str:
    """Chế độ Wyoming — luôn multi một cổng (pattern microsoft-stt/tts).

    Giá trị ``locked`` còn đọc được nhưng **không** mở cổng thứ hai; production
    chỉ lắng nghe ``wyoming_port()`` (10600). Giữ key để không phá config cũ.
    """
    m = str(_wy().get("mode") or "multi").strip().lower()
    return m if m in {"multi", "locked"} else "multi"


def wyoming_port() -> int:
    """Cổng Wyoming multi duy nhất (mặc định 10600).

    Ưu tiên ``.port``, rồi ``.vi_port`` (tương thích config cũ).
    """
    w = _wy()
    for key in ("port", "vi_port"):
        raw = w.get(key)
        if raw not in (None, ""):
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    return 10600


def _lang_primary(language: str) -> str:
    """Ngôn ngữ chính = phần trước dấu '-' (vi-vn-x-south / vi-en → vi; en → en)."""
    return str(language or "").strip().lower().split("-", 1)[0]


def wyoming_vi_port() -> int:
    """Alias ``wyoming_port()`` — không còn cổng VI tách."""
    return wyoming_port()


def wyoming_en_port() -> int:
    """Deprecated: multi chỉ còn 1 cổng — trả cùng ``wyoming_port()``.

    Config ``.en_port`` bị bỏ qua (không mirror server).
    """
    return wyoming_port()


def wyoming_en_voice() -> str:
    """Giọng TTS mặc định cho CỔNG ANH khi client (HA) không gửi voice.

    Ưu tiên config `.en_voice`; else giọng Kokoro đầu tiên đã tải; else giọng
    Piper tag `en` đầu tiên đã tải; else vẫn trả id Kokoro mặc định (kể cả khi
    model chưa tải) — **không bao giờ** rơi về giọng Việt (Piper/VieNeu). Engine
    sẽ báo lỗi rõ «chưa tải Kokoro» thay vì đọc tiếng Việt trên cổng Anh.
    """
    explicit = str(_wy().get("en_voice") or "").strip()
    if explicit:
        return explicit
    if kokoro_model_dir() is not None:
        return f"{KOKORO_PREFIX}{KOKORO_VOICE_NAMES[0]}"
    for v in voice_catalog():
        if v.get("downloaded") and _lang_primary(str(v.get("language") or "")) == "en":
            return str(v.get("id") or "")
    # Không có giọng EN đã tải → vẫn ép id Kokoro (fail rõ ràng, không TTS Việt)
    if KOKORO_VOICE_NAMES:
        return f"{KOKORO_PREFIX}{KOKORO_VOICE_NAMES[0]}"
    return ""


# ── Media (file audio phát ra loa cần URL HTTP) ──────────────────────────────


def media_dir() -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def media_retention_hours() -> int:
    try:
        return max(1, int(cfg().get("media_retention_hours") or 24))
    except (TypeError, ValueError):
        return 24


def public_base_url() -> str:
    """Base URL để loa (Cast/DLNA) kéo file — loa nằm ở LAN nên KHÔNG dùng
    localhost. Ưu tiên voice.public_base_url, rồi địa chỉ công khai chung.

    Đo thật 02/08: loa im mà bot vẫn báo "[đang đọc …]". Log máy chủ:
    "Chưa đặt voice.public_base_url — loa trong nhà không tải được file từ
    localhost". Nhưng địa chỉ công khai ĐÃ có ở hai nơi:
        ENV CHATGPT2API_BASE_URL   = https://gpt.vhtatn.io.vn
        telegram_webhook_url       = https://gpt.vhtatn.io.vn
    Hàm này đọc `config.get().get("base_url")` — DICT THÔ, luôn rỗng, vì biến
    môi trường chỉ được đọc trong thuộc tính `config.base_url`. Nên nó không
    thấy gì cả.

    Chuỗi dưới đây khớp với `zalo_bot._public_base()` và `photo_intent`: cùng
    một địa chỉ công khai thì đọc cùng một chỗ, khỏi phải cấu hình lần thứ tư.
    """
    v = str(cfg().get("public_base_url") or "").strip()
    if v:
        return v.rstrip("/")
    try:
        # Thuộc tính (không phải dict thô) — nó mới đọc CHATGPT2API_BASE_URL.
        v = str(config.base_url or "").strip()
        if v:
            return v.rstrip("/")
        return str(config.get().get("telegram_webhook_url") or "").strip().rstrip("/")
    except Exception:
        return ""


#: Tính năng nào cần STT/TTS — mỗi tính năng MỘT cấu hình riêng, không dùng
#: chung (chủ máy chốt 14/08: "mỗi loại cần đến stt, tts phải có cài đặt riêng,
#: không chung nhau"). Khoá config: ``voice.dung_cho.<tên>.{stt_tieng,tts_giong}``.
TINH_NANG = {
    "tin_thoai": "Tin nhắn thoại gửi bot",
    "phu_de": "Phụ đề video / dịch tệp",
    "dam_thoai": "Đàm thoại hai chiều (mic)",
    "loa": "Thông báo ra loa",
}

#: Tiếng có thể nghe/đọc. Mở rộng ở đây là mở rộng cả UI lẫn bộ dò.
TIENG_HO_TRO = ("vi", "en", "ja", "zh", "ko")


def _dung_cho(ten: str) -> dict[str, Any]:
    d = _sub("dung_cho").get(str(ten or ""))
    return d if isinstance(d, dict) else {}


def stt_nhom_tieng(tinh_nang: str = "", session_id: str = "",
                   mac_dinh: list[str] | None = None) -> list[str]:
    """Nhóm tiếng đem NGHE cho một tính năng (và một thread, nếu có).

    Thứ tự tra: đè theo thread (``voice_sessions.json`` — xem ``session_voice``)
    → cấu hình của TÍNH NĂNG → ``mac_dinh`` do CHÍNH caller đưa → ``[]``.

    KHÔNG rơi về ``voice.stt.language``: ô đó là của riêng tin nhắn thoại. Rơi
    về nó nghĩa là ai đặt "chỉ tiếng Việt" cho voice note thì phụ đề video cũng
    thôi nhận ra tiếng Anh — đúng kiểu dùng chung cài đặt mà chủ máy yêu cầu bỏ
    (14/08). Mỗi tính năng tự khai mặc định của mình.

    Trả về DANH SÁCH vì thread chọn được nhiều tiếng. Một tiếng = khoá cứng,
    nhanh và chuẩn nhất; hai tiếng = dò bằng độ tự tin giải mã (đo 14/08: model
    đúng tiếng ~-0,04 so với model sai ~-0,5 — rất chắc); ba tiếng trở lên =
    mỗi tiếng thêm một lượt nghe nên chậm gấp N và dễ sai hơn.

    Chỉ giữ tiếng CÓ MODEL trên đĩa — chọn tiếng chưa tải thì im lặng bỏ qua
    còn tệ hơn báo thẳng, nên caller nào cần thì tự đối chiếu ``stt_co_model``.
    """
    ra: list[str] = []
    if session_id:
        try:
            from services.voice import session_voice as _sv
            cfg_s = _sv.get_session_voice_config(session_id) or {}
            ra = _tach_tieng(cfg_s.get("stt_nhom_tieng") or cfg_s.get("stt_language"))
        except Exception:
            ra = []
    if not ra and tinh_nang:
        ra = _tach_tieng(_dung_cho(tinh_nang).get("stt_tieng"))
    if not ra:
        ra = list(mac_dinh or [])
    return [x for x in ra if x in TIENG_HO_TRO]


def _tach_tieng(raw: Any) -> list[str]:
    """"vi,en" | ["vi","en"] | "auto" → danh sách mã tiếng (auto = mọi tiếng
    CÓ model, để bản cũ đặt "auto" vẫn hiểu được)."""
    if raw is None:
        return []
    if isinstance(raw, str):
        t = raw.strip().lower()
        if not t:
            return []
        if t in {"auto", "mul", "multi", "und", "*"}:
            return [x for x in TIENG_HO_TRO if stt_co_model(x)]
        raw = t.replace(";", ",").split(",")
    ra: list[str] = []
    for x in raw or []:
        ma = str(x or "").strip().lower().split("-", 1)[0]
        if ma and ma not in ra:
            ra.append(ma)
    return ra


def stt_co_model(lang: str) -> bool:
    """Tiếng này có model NGHE trên đĩa chưa."""
    ma = str(lang or "").lower()
    if ma == "vi":
        return stt_model_dir() is not None
    if ma == "en":
        return stt_en_model_dir() is not None
    return stt_them_model_dir(ma) is not None


def tts_giong_cho(tinh_nang: str, lang: str = "vi") -> str:
    """Giọng ĐỌC của một tính năng cho một tiếng.

    Đè theo tính năng (``voice.dung_cho.<tên>.tts_giong``) → bảng giọng theo
    tiếng (mục "Theo từng tiếng" trong Cài đặt) → giọng mặc định của máy.
    """
    rieng = str(_dung_cho(tinh_nang).get("tts_giong") or "").strip()
    if rieng:
        return rieng
    ma = str(lang or "vi").lower()
    if ma == "en":
        return wyoming_en_voice()
    if ma in ("zh", "ja", "ko"):
        return f"dangu:{ma}"
    return tts_voice()


def _so_giong_them() -> dict[str, int]:
    """Số giọng của model zh/ja/ko cho UI. Chỉ đếm khi model ĐÃ tải —
    ``so_giong_da_ngu`` nạp model để hỏi, gọi lúc chưa có file là tốn công
    vô ích (và /api/voice/status bị gọi mỗi lần mở trang Cài đặt)."""
    ra = {"zh": 0, "ja": 0, "ko": 0}
    co_zh = (KOKORO_ZH_DIR / "voices.bin").is_file()
    co_st = (SUPERTONIC_DIR / "tts.json").is_file()
    if not (co_zh or co_st):
        return ra
    try:
        from services.voice.engines import so_giong_da_ngu
    except Exception:
        return ra
    if co_zh:
        ra["zh"] = so_giong_da_ngu("zh")
    if co_st:
        ra["ja"] = ra["ko"] = so_giong_da_ngu("ja")
    return ra


def status() -> dict[str, Any]:
    """Trạng thái cho UI Settings / API."""
    return {
        "tts": {
            "enabled": is_tts_enabled(),
            "backend": tts_backend(),
            "voice": tts_voice(),
            "piper_bin": piper_binary(),
            "model_ready": voice_model_path() is not None,
            "wyoming_url": tts_wyoming_url(),
            "local_voices": list_local_voices(),
        },
        "tts_auto": {
            "cpu_has_vnni": cpu_has_vnni(),
            "effective_cpus": effective_cpu_count(),
            "precision_prefer": tts_precision_prefer(),
            "precision_cfg": tts_precision_cfg(),
            "precision_override": tts_precision_override(),
            "precision_override_reason": tts_precision_override_reason(),
            "ttfa_target_s": ttfa_target_s(),
            "last_warm_ttfa_s": last_warm_ttfa_s(),
            "threads_auto": auto_tts_threads(),
        },
        "vieneu": {
            "installed": vieneu_installed(),
            "model_ready": vieneu_model_ready(),
            "precision": vieneu_precision(),
            "precision_cfg": tts_precision_cfg(),
            "cpu_has_vnni": cpu_has_vnni(),
            "threads": vieneu_threads(),
            "max_chars": vieneu_max_chars(),
            "style": vieneu_style(),
            "voices": len(vieneu_voices()),
        },
        "nghitts": {
            "model_ready": nghi_ready(),
            "downloaded": nghi_downloaded_ids(),
            "voices": len(nghi_all_ids()),
            "espeak_data": str(nghi_espeak_data_dir() or ""),
            "max_loaded": nghi_max_loaded(),
            "threads": tts_threads(),
        },
        "kokoro": {
            "model_ready": kokoro_model_dir() is not None,
            "model_file": str(kokoro_model_file() or ""),
            "precision_prefer": tts_precision_prefer(),
            "threads": tts_threads(),
            "voices": len(KOKORO_VOICE_NAMES),
        },
        "wyoming_server": {
            "enabled": wyoming_enabled(),
            "mode": wyoming_mode(),
            # Một cổng multi (microsoft-stt/tts style). en_port = port (deprecated).
            "port": wyoming_port(),
            "vi_port": wyoming_port(),
            "en_port": wyoming_port(),
            "en_voice": wyoming_en_voice(),
        },
        "stt": {
            "enabled": is_stt_enabled(),
            "backend": stt_backend(),
            "model_ready": stt_model_dir() is not None,
            "en_enabled": stt_en_enabled(),
            "en_model_ready": stt_en_model_dir() is not None,
            "language": stt_language(),
            "sherpa_installed": has_local_stt(),
            "wyoming_url": stt_wyoming_url(),
            # Model nghe theo tiếng (zh/ja/ko) — có trên volume = dùng được
            # (cổng Wyoming 107xx tự mở). Tải: scripts/download_stt_da_ngu.py
            "them_ready": {
                lang: (stt_them_model_dir(lang) is not None
                       or (lang in stt_sense_tieng()
                           and stt_sense_model_dir() is not None))
                for lang in STT_THEM_DIR
            },
        },
        # Model ĐỌC theo tiếng — cho hàng "Theo từng tiếng" trong Cài đặt.
        "doc_them_ready": {
            "en": kokoro_model_dir() is not None,
            "zh": (KOKORO_ZH_DIR / "voices.bin").is_file(),
            "ja": (SUPERTONIC_DIR / "tts.json").is_file(),
            "ko": (SUPERTONIC_DIR / "tts.json").is_file(),
        },
        # Số giọng model zh/ja/ko có (đo 14/08: zh 103 · ja/ko 10) — UI dựng
        # danh sách chọn từ đây, không hardcode. Model chưa tải → 0.
        "so_giong_them": _so_giong_them(),
        "public_base_url": public_base_url(),
    }
