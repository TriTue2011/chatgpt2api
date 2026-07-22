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
KOKORO_DIR = Path(DATA_DIR) / "kokoro"   # Kokoro-82M (TTS tiếng Anh)
MEDIA_DIR = Path(DATA_DIR) / "voice" / "media"
# Manifest 19 giọng (nằm TRONG image — chỉ là danh mục, không phải model).
VOICES_MANIFEST = Path(BASE_DIR) / "voices" / "piper" / "voices.json"

_DEFAULT_VOICE = "ngochuyennew"

# Giọng namespaced: "vieneu:<Tên>" → VieNeu v3 Turbo, "kokoro:<tên>" → Kokoro
# tiếng Anh, id trần → Piper.
VIENEU_PREFIX = "vieneu:"
VIENEU_BACKBONE_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
VIENEU_CODEC_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
KOKORO_PREFIX = "kokoro:"
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
    if v.startswith((VIENEU_PREFIX, KOKORO_PREFIX)):
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
    has_local = has_piper or has_vieneu or has_kokoro
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
    hết quota. Ép: voice.tts.vieneu_threads hoặc voice.tts.num_threads.
    """
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
    - ``en``   — Parakeet English (chỉ khi ``stt.en_enabled: true``)
    - ``auto`` — dual VI+EN khi en_enabled và đủ 2 model
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
    """Bật STT tiếng Anh (Parakeet). Mặc định **tắt** — offline EN chưa chuẩn.

    Config: ``voice.stt.en_enabled: true`` để bật lại khi cần.
    """
    raw = _sub("stt").get("en_enabled")
    if raw is None:
        return False
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def stt_en_model_dir() -> Path | None:
    """Thư mục model Parakeet-TDT tiếng Anh (tải bằng download_stt_en_model.py).

    Trả None khi ``stt.en_enabled`` tắt — mọi caller coi như không có STT EN.
    """
    if not stt_en_enabled():
        return None
    d = str(_sub("stt").get("en_model_dir") or "").strip()
    base = Path(d) if d else STT_EN_DIR
    if not base.is_dir():
        return None
    if not list(base.glob("encoder*.onnx")):
        return None
    return base


def stt_threads() -> int:
    try:
        return max(1, int(_sub("stt").get("num_threads") or 4))
    except (TypeError, ValueError):
        return 4


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
    localhost. Ưu tiên voice.public_base_url, rồi base_url chung."""
    v = str(cfg().get("public_base_url") or "").strip()
    if v:
        return v.rstrip("/")
    try:
        return str(config.get().get("base_url") or "").strip().rstrip("/")
    except Exception:
        return ""


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
        },
        "public_base_url": public_base_url(),
    }
