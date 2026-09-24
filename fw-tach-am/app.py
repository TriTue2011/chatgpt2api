"""API tách lời gốc khỏi soundtrack để lồng TTS mà vẫn giữ nền phim.

Model chạy trong subprocess ``audio-separator``: khi request xong tiến trình
thoát và CUDA được nhả thật, không để model nằm trong VRAM cạnh Whisper/Qwen.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()

# ONNX MDX nhẹ hơn BS-Roformer, phù hợp card 8 GB còn chia VRAM cho Frigate.
# Có thể đổi model qua env sau benchmark, không cần sửa gateway.
MODEL = os.getenv("SEPARATOR_MODEL", "UVR-MDX-NET-Inst_HQ_3.onnx")
CHUNK_SECONDS = max(60, int(os.getenv("SEPARATOR_CHUNK_SECONDS", "300")))
# Số khối đưa vào GPU mỗi lượt. Khai qua env vì mỗi card một khác — 8 GB dùng
# chung với Frigate thì khác hẳn một card 24 GB rảnh.
#
# Đo 21/08/2026 trên chính máy này (RTX 2060S 8 GB, 4 nhân CPU, tệp 60 giây):
# batch=1 mất 130 giây, batch=4 mất 123 giây — chênh 5%, gần như không đổi.
# Cùng lúc đó tải GPU đo từ gateway chỉ trung bình 12% (đỉnh 95%, nền 6%).
# Nghĩa là nút thắt KHÔNG nằm ở số khối mỗi lượt mà ở phía CPU giữa các lượt
# gọi GPU; máy này chỉ có 4 nhân và còn cõng Frigate. Nâng batch trên card to
# và máy nhiều nhân có thể ăn, nên để chỉnh được, nhưng đừng trông đợi nó cứu
# tốc độ trên cấu hình hiện tại.
MDX_BATCH_SIZE = max(1, int(os.getenv("SEPARATOR_MDX_BATCH_SIZE", "1")))
TIMEOUT_SECONDS = max(300, int(os.getenv("SEPARATOR_TIMEOUT_SECONDS", "10800")))
MAX_UPLOAD_BYTES = max(1 << 20, int(os.getenv(
    "SEPARATOR_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024))))
API_TOKEN = os.getenv("SEPARATOR_API_TOKEN", "").strip()
#: VRAM trống tối thiểu trước khi mở tiến trình tách: thiếu thì từ chối (gateway
#: tách bằng CPU) thay vì CUDA OOM. Đo 24/09/2026, tách 60 giây trên GPU: đỉnh
#: thêm ~2,4 GB (3020 → 5442 MiB); nhận mặt + TTS của c2a nằm thường trực.
CAN_VRAM_MB = float(os.getenv("TACH_AM_CAN_VRAM_MB", "2600"))

_lock = threading.Lock()
_admission = threading.Lock()
_process_guard = threading.Lock()
_active_process: subprocess.Popen | None = None
_active_job_token = ""
_cancel_requested = False
_busy = False


class _FileResponseTuDon(FileResponse):
    """Xóa workspace cả khi client hủy/đứt giữa lúc stream WAV lớn."""

    def __init__(self, path: str, *, work_dir: str, **kwargs):
        super().__init__(path, **kwargs)
        self._work_dir = work_dir

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            shutil.rmtree(self._work_dir, ignore_errors=True)


def _don_orphan(root: str | None = None) -> None:
    """Dọn workspace còn lại sau container crash/restart giữa tệp."""
    base = Path(root or tempfile.gettempdir())
    for path in base.glob("fw-tach-am-*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


@app.on_event("startup")
def _startup_cleanup() -> None:
    _don_orphan()


def _xac_thuc(request: Request) -> None:
    """API GPU chỉ dành cho gateway; không để máy bất kỳ trong LAN chiếm GPU."""
    if not API_TOKEN:
        raise HTTPException(503, "Chưa cấu hình SEPARATOR_API_TOKEN.")
    supplied = request.headers.get("x-api-key", "")
    if not supplied or not hmac.compare_digest(supplied, API_TOKEN):
        raise HTTPException(401, "Sai API token.")


def _job_token(request: Request) -> str:
    token = request.headers.get("x-job-token", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
        raise HTTPException(400, "Thiếu hoặc sai X-Job-Token.")
    return token


@app.middleware("http")
async def _chi_nhan_mot_soundtrack(request: Request, call_next):
    """Xác thực và từ chối request thứ hai trước khi đọc body nhiều GB."""
    la_tach = request.method == "POST" and request.url.path in {"/tach", "/tach-nen"}
    if not la_tach:
        return await call_next(request)
    try:
        _xac_thuc(request)
        _job_token(request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    try:
        content_length = int(request.headers.get("content-length") or 0)
    except ValueError:
        content_length = 0
    # Body là audio raw. Chặn theo header trước khi đọc; endpoint vẫn đếm byte
    # thật trong request.stream() để chặn client chunked/khai gian.
    if content_length > MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"detail": "Soundtrack vượt giới hạn upload."}, status_code=413,
            headers={"Connection": "close"})
    if not _admission.acquire(blocking=False):
        return JSONResponse(
            {"detail": "Máy tách âm đang bận; hãy thử lại sau."}, status_code=429,
            headers={"Connection": "close"})
    try:
        return await call_next(request)
    finally:
        _admission.release()


#: Bọc audio-separator: nạp cublas/cudart CUDA 12 (Dockerfile, /opt/cu12) TRƯỚC
#: khi onnxruntime tạo phiên MDX. Không có bước này ORT không nạp được CUDA
#: (image chỉ có CUDA 13 của torch) và LẶNG LẼ chạy CPU — audio-separator chỉ
#: xem get_available_providers() nên vẫn log "enabling acceleration". cuDNN để
#: nguyên bản CUDA 13 của torch (cudnn=False): thử 24/09/2026 cả hai cách, torch
#: vẫn chạy STFT/conv trên GPU; không đè cuDNN là an toàn hơn.
#: Đo cùng ngày, 60 giây tiếng: CPU 130,1 s → GPU 20,1 s; bản ra trùng khớp
#: (tương quan 1,0).
_KHOI_DONG_TACH = (
    "import sys, onnxruntime as ort\n"
    "ort.preload_dlls(cuda=True, cudnn=False, directory=sys.argv.pop(1))\n"
    "from audio_separator.utils.cli import main\n"
    "sys.argv[0] = 'audio-separator'\n"
    "sys.exit(main())\n")


def _lenh_tach(input_path: str, output_dir: str) -> list[str]:
    dau = (["python3", "-c", _KHOI_DONG_TACH, ONNX_CU12_DIR]
           if Path(ONNX_CU12_DIR).is_dir() else ["audio-separator"])
    return [
        *dau, input_path,
        "--model_filename", MODEL,
        "--model_file_dir", "/data/models",
        "--output_dir", output_dir,
        "--output_format", "WAV",
        "--single_stem", "Instrumental",
        "--sample_rate", "44100",
        "--chunk_duration", str(CHUNK_SECONDS),
        "--mdx_batch_size", str(MDX_BATCH_SIZE),
        "--use_soundfile",
        "--use_autocast",
    ]


def _tim_track_nen(output_dir: str, input_path: str) -> str:
    input_real = Path(input_path).resolve()
    candidates = [
        p for p in Path(output_dir).iterdir()
        if p.is_file() and p.resolve() != input_real
        and p.suffix.lower() in {".wav", ".flac", ".m4a", ".mp3"}
        and p.stat().st_size >= 100
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"audio-separator phải trả đúng một track Instrumental, nhận {len(candidates)}")
    return str(candidates[0])


def _thoi_luong(path: str) -> float:
    p = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ], capture_output=True, text=True, timeout=60)
    try:
        value = float(p.stdout.strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Không đọc được thời lượng {Path(path).name}.") from exc
    if p.returncode or value <= 0:
        raise RuntimeError(f"Track {Path(path).name} không có thời lượng hợp lệ.")
    return value


def _kiem_tra_track_nen(input_path: str, output_path: str) -> None:
    """Không trả track bị cụt làm phim mất nhạc/hiệu ứng ở phần cuối."""
    original = _thoi_luong(input_path)
    background = _thoi_luong(output_path)
    tolerance = max(1.0, min(3.0, original * 0.001))
    if abs(background - original) > tolerance:
        raise RuntimeError(
            f"Track nền sai thời lượng: {background:.2f}s, cần {original:.2f}s "
            f"(dung sai {tolerance:.2f}s).")


def _dung_tien_trinh(proc: subprocess.Popen, *, cho_giay: float = 3.0) -> bool:
    """Dừng cả process group (audio-separator và ffmpeg con), chờ GPU nhả."""
    if proc.poll() is not None:
        return True
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        try:
            proc.terminate()
        except OSError:
            pass
    deadline = time.monotonic() + max(0.1, cho_giay)
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
        deadline = time.monotonic() + 1.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
    return proc.poll() is not None


def _dang_ky_job(job_token: str) -> None:
    """Đăng ký owner TRƯỚC khi schedule thread để đóng khe unload/Popen."""
    global _active_job_token, _cancel_requested, _busy
    with _process_guard:
        if _active_job_token or _active_process is not None:
            raise RuntimeError("Máy tách âm đang có job khác.")
        _active_job_token = job_token
        _cancel_requested = False
        _busy = True


def _bo_job_pending(job_token: str) -> None:
    """Dọn owner nếu request hỏng trong lúc upload, trước khi thread chạy."""
    global _active_job_token, _cancel_requested, _busy
    with _process_guard:
        if _active_job_token == job_token and _active_process is None:
            _active_job_token = ""
            _cancel_requested = False
            _busy = False


def _dung_dang_chay(job_token: str) -> tuple[bool, bool]:
    """Trả ``(đúng chủ, đã dừng)``; pending job sẽ bị chặn trước Popen."""
    global _cancel_requested
    with _process_guard:
        proc = _active_process
        owner = _active_job_token
        if not owner:
            return True, True
        if not hmac.compare_digest(owner, job_token):
            return False, False
        if proc is None:
            _cancel_requested = True
            return True, True
    if proc is None:  # pragma: no cover - đã return trong guard
        return True, True
    return True, _dung_tien_trinh(proc)


def _tach(input_path: str, output_dir: str, job_token: str) -> str:
    global _active_process, _active_job_token, _cancel_requested, _busy
    with _lock:
        try:
            with _process_guard:
                # Giữ guard xuyên Popen + publish để /unload không thể chen vào
                # khe thấy None rồi trả thành công trước khi process bắt đầu.
                if (_active_job_token != job_token or _cancel_requested):
                    raise RuntimeError("Job tách âm đã bị hủy trước khi khởi động.")
                g = _gpu_do()
                if g and g["vram_tong_mb"] - g["vram_dung_mb"] < CAN_VRAM_MB:
                    raise RuntimeError(
                        f"VRAM trống {g['vram_tong_mb'] - g['vram_dung_mb']:.0f} MB < cần "
                        f"{CAN_VRAM_MB:.0f} MB — GPU đang bận việc khác.")
                proc = subprocess.Popen(
                    _lenh_tach(input_path, output_dir), stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, start_new_session=True)
                _active_process = proc
                _active_job_token = job_token
            try:
                stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                _dung_tien_trinh(proc)
                proc.communicate()
                raise
            if proc.returncode:
                loi = (stderr or stdout or "audio-separator lỗi")[-600:]
                raise RuntimeError(loi)
            output = _tim_track_nen(output_dir, input_path)
            _kiem_tra_track_nen(input_path, output)
            return output
        finally:
            with _process_guard:
                if _active_job_token == job_token:
                    _active_process = None
                    _active_job_token = ""
                    _cancel_requested = False
                    _busy = False


def _gpu_do() -> dict | None:
    try:
        p = subprocess.run([
            "nvidia-smi",
            "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ], capture_output=True, text=True, timeout=5)
        values = [x.strip() for x in p.stdout.strip().splitlines()[0].split(",")]
        return {"nhiet_do_c": float(values[0]), "tai_pct": float(values[1]),
                "vram_dung_mb": float(values[2]), "vram_tong_mb": float(values[3])}
    except Exception:
        return None


def _cpu_do() -> dict | None:
    """Tải CPU của MÁY này — đọc thẳng /proc, không gọi tiến trình con nào.

    Vì sao cần bên cạnh telemetry GPU: đo 21/08/2026 cho thấy tách lời chạy
    1,65 giây cho mỗi giây tiếng trong khi GPU chỉ dùng trung bình 12%. Nghi
    nút thắt nằm ở CPU, nhưng máy này chỉ có 4 nhân nên SSH vào để đo lại chính
    là thêm tải và làm hỏng phép đo — thực tế phiên SSH treo hẳn trong lúc
    tách. Khai qua /health thì gateway đứng NGOÀI hỏi được, không tốn gì của
    máy đang đo.

    ``tai_1_phut`` so với ``so_nhan``: bằng nhau nghĩa là kín CPU. Ví dụ máy 4
    nhân mà load 4,0 là đã hết chỗ, thêm nhân sẽ nhanh lên.

    Kèm RAM và SWAP vì thiếu nhớ và thiếu nhân cho ra CÙNG một triệu chứng
    (chậm, đơ) nhưng cách chữa ngược nhau. Máy này báo swap dùng 59% ngay lúc
    rảnh — nếu lúc tách còn swap nữa thì thêm nhân CPU sẽ không cứu được gì,
    phải thêm RAM. Đây đúng là chỗ dễ chẩn nhầm nhất nên phải đo cả hai.
    """
    ket: dict = {}
    try:
        with open("/proc/loadavg", encoding="utf-8") as f:
            phan = f.read().split()
        ket.update({"tai_1_phut": float(phan[0]), "tai_5_phut": float(phan[1]),
                    "so_nhan": os.cpu_count() or 0})
    except Exception:
        return None
    try:
        so: dict[str, float] = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for dong in f:
                ten, _, phan_con = dong.partition(":")
                if ten in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                    so[ten] = float(phan_con.split()[0]) / 1024.0   # kB → MB
        ket.update({
            "ram_tong_mb": round(so.get("MemTotal", 0.0)),
            "ram_con_mb": round(so.get("MemAvailable", 0.0)),
            "swap_dung_mb": round(so.get("SwapTotal", 0.0) - so.get("SwapFree", 0.0)),
            "swap_tong_mb": round(so.get("SwapTotal", 0.0)),
        })
    except Exception:
        pass
    return ket


@app.get("/health")
def health(request: Request):
    _xac_thuc(request)
    missing = [name for name in ("audio-separator", "ffprobe")
               if not shutil.which(name)]
    if missing:
        raise HTTPException(503, "Thiếu binary: " + ", ".join(missing))
    return {"status": "ok", "model": MODEL, "chunk_seconds": CHUNK_SECONDS,
            "mdx_batch_size": MDX_BATCH_SIZE,
            "busy": _busy or _admission.locked(), "gpu": _gpu_do(),
            "cpu": _cpu_do()}


@app.post("/tach")
@app.post("/tach-nen")
async def tach_nen(request: Request, stem: str = "nen"):
    """Nhận raw audio body để giới hạn kích thước trước khi ghi hết vào /tmp."""
    _xac_thuc(request)
    job_token = _job_token(request)
    if str(stem or "").lower() not in {"nen", "instrumental"}:
        raise HTTPException(400, "Dịch vụ này chỉ xuất stem nền/Instrumental.")
    # Owner tồn tại trước cả lúc đọc body: timeout/unload ở bất kỳ khe nào cũng
    # đánh dấu cancel, không thể trả loaded=false rồi Popen chạy muộn phía sau.
    _dang_ky_job(job_token)
    task_started = False
    task: asyncio.Task | None = None
    work = ""
    try:
        work = tempfile.mkdtemp(prefix="fw-tach-am-")
        suffix = Path(request.headers.get("x-filename") or "soundtrack.wav").suffix.lower()
        if suffix not in {".flac", ".wav", ".m4a", ".mp3", ".aac", ".ogg"}:
            suffix = ".flac"
        input_path = str(Path(work) / f"input{suffix}")
        size = 0
        with Path(input_path).open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Soundtrack vượt giới hạn upload.")
                f.write(chunk)
        if size < 100:
            raise HTTPException(400, "Soundtrack rỗng hoặc không hợp lệ.")

        started = time.time()
        try:
            task = asyncio.create_task(asyncio.to_thread(
                _tach, input_path, work, job_token))
            task_started = True
            while not task.done():
                await asyncio.sleep(0.5)
                if await request.is_disconnected():
                    await asyncio.to_thread(_dung_dang_chay, job_token)
                    try:
                        await task
                    except Exception:
                        pass
                    raise HTTPException(499, "Client đã ngắt; tiến trình GPU đã dừng.")
            output = await task
        except HTTPException:
            raise
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(504, "Tách lời quá thời gian cho phép.") from exc
        except Exception as exc:
            raise HTTPException(503, f"Không tách được lời gốc: {str(exc)[:600]}") from exc
        response = _FileResponseTuDon(
            output, work_dir=work, media_type="audio/wav",
            filename="background.wav")
        response.headers["X-Separator-Model"] = MODEL.encode(
            "ascii", "ignore").decode()[:160] or "unknown"
        # Hợp đồng gateway đời đầu; giữ song song để cập nhật hai máy độc lập.
        response.headers["X-Model"] = response.headers["X-Separator-Model"]
        response.headers["X-Processing-Seconds"] = f"{time.time() - started:.2f}"
        return response
    except asyncio.CancelledError:
        if task_started:
            await asyncio.to_thread(_dung_dang_chay, job_token)
            if task is not None:
                try:
                    await task
                except Exception:
                    pass
        else:
            _bo_job_pending(job_token)
        if work:
            shutil.rmtree(work, ignore_errors=True)
        raise
    except Exception:
        if not task_started:
            _bo_job_pending(job_token)
        if work:
            shutil.rmtree(work, ignore_errors=True)
        raise


@app.post("/unload")
def unload(request: Request):
    """Chỉ chủ job được dừng process của mình; token khác nhận 409."""
    _xac_thuc(request)
    job_token = _job_token(request)
    owned, stopped = _dung_dang_chay(job_token)
    if not owned:
        raise HTTPException(409, "Job đang chạy thuộc request khác.")
    if not stopped:
        raise HTTPException(503, "Không dừng được tiến trình tách âm.")
    return {"status": "ok", "loaded": False, "busy": _busy, "gpu": _gpu_do()}


# ── Ba graph ONNX cố định của c2a chạy trên GPU (24/09/2026) ─────────────────
# Chủ máy chốt đưa nhận mặt và TTS lên GPU. c2a gửi TENSOR đầu vào của một
# trong ba graph dưới, máy này chạy trên CUDA rồi trả tensor đầu ra — tiền/hậu
# xử lý vẫn ở c2a, nên vector mặt và tiếng nói ra như chạy CPU tại chỗ.
#
# Graph cố định trong mã: tên, nguồn tải và sha256. Máy này TỰ tải từ nguồn
# gốc; không có đường nào để bên ngoài đưa graph lên. Không có CUDA thì 503 —
# c2a tự chạy CPU, máy NVR 4 nhân không bị ăn CPU thay. Phiên nằm thường trực
# (~0,6 GB VRAM): nhận mặt và đọc Assist phải trả lời ngay; việc GPU nặng khác
# đã xếp hàng ở c2a (services/gpu_queue.py).
_INSIGHTFACE = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
_KOKORO_VI = ("https://huggingface.co/contextboxai/Kokoro-Vietnamese/resolve/"
              "9f210d622209fcc216fe2ac6159fed2ff381cb8a/kokoro_vi.onnx")
ONNX_GRAPH = {
    # tên: (nguồn, tệp trong zip hoặc None, sha256)
    "det_10g": (_INSIGHTFACE, "det_10g.onnx",
                "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91"),
    "w600k_r50": (_INSIGHTFACE, "w600k_r50.onnx",
                  "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43"),
    "kokoro_vi": (_KOKORO_VI, None,
                  "da191277f58633649a9c0d2ae8012e80ef57ea8e2a56e30323c0f7df1ca29087"),
}
ONNX_DIR = Path(os.getenv("ONNX_DIR", "/data/onnx"))
#: Thư viện CUDA 12 + cuDNN 9 riêng cho onnxruntime-gpu (xem Dockerfile) —
#: image gốc chỉ có CUDA 13 của torch nên thiếu nó ORT âm thầm chạy CPU.
ONNX_CU12_DIR = os.getenv("ONNX_CU12_DIR", "/opt/cu12/lib")
ONNX_TOI_DA_CHAY = 32 * 1024 * 1024       # một lần chạy (ảnh dò mặt 640² ≈ 4,9 MB)
_onnx_phien: dict[str, object] = {}
_onnx_khoa = threading.Lock()


def _onnx_ten(ten: str) -> str:
    if ten not in ONNX_GRAPH:
        raise HTTPException(404, "Không có graph này.")
    return ten


def _onnx_tai(ten: str) -> Path:
    """Tải graph từ nguồn gốc về ONNX_DIR, kiểm sha256; đã có thì thôi."""
    import hashlib
    import urllib.request
    import zipfile

    nguon, trong_zip, sha = ONNX_GRAPH[ten]
    dich = ONNX_DIR / f"{ten}.onnx"
    if dich.is_file():
        return dich
    ONNX_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ONNX_DIR) as tam:
        tai = Path(tam) / "tai"
        with urllib.request.urlopen(nguon, timeout=120) as r, tai.open("wb") as f:  # noqa: S310 — URL hằng
            shutil.copyfileobj(r, f)
        if trong_zip:
            with zipfile.ZipFile(tai) as z:
                ten_day_du = next(n for n in z.namelist() if n.endswith(trong_zip))
                tai = Path(z.extract(ten_day_du, tam))
        if hashlib.sha256(tai.read_bytes()).hexdigest() != sha:
            raise RuntimeError(f"{ten}: sha256 không khớp nguồn đã ghim")
        tai.replace(dich)
    return dich


def _onnx_nap(ten: str):
    with _onnx_khoa:
        phien = _onnx_phien.get(ten)
        if phien is None:
            import onnxruntime as ort

            if Path(ONNX_CU12_DIR).is_dir():
                # Nạp lại nhiều lần vô hại: đã nạp thì ctypes dùng lại bản trong bộ nhớ.
                ort.preload_dlls(directory=ONNX_CU12_DIR)
            phien = ort.InferenceSession(str(_onnx_tai(ten)), providers=["CUDAExecutionProvider"])
            # CUDA hỏng thì ORT âm thầm lùi về CPU — không nhận, để c2a tự chạy.
            if phien.get_providers()[0] != "CUDAExecutionProvider":
                raise HTTPException(503, "Không có CUDA cho ONNX.")
            _onnx_phien[ten] = phien
        return phien


@app.get("/onnx/{ten}")
async def onnx_xem(ten: str, request: Request):
    """Nạp graph lên GPU (lần đầu tự tải) và trả tên/hình đầu vào, tên đầu ra."""
    _xac_thuc(request)
    phien = await asyncio.to_thread(_onnx_nap, _onnx_ten(ten))
    return {"vao": [{"ten": i.name, "hinh": [d if isinstance(d, int) else None for d in i.shape]}
                    for i in phien.get_inputs()],
            "ra": [o.name for o in phien.get_outputs()]}


@app.post("/onnx/{ten}/chay")
async def onnx_chay(ten: str, request: Request):
    """Thân là .npz các tensor đầu vào (không pickle); trả .npz đầu ra "o0", "o1"… theo thứ tự."""
    import io

    import numpy as np
    from fastapi.responses import Response

    _xac_thuc(request)
    ten = _onnx_ten(ten)
    than = await request.body()
    if len(than) > ONNX_TOI_DA_CHAY:
        raise HTTPException(413, "Đầu vào quá lớn.")
    try:
        with np.load(io.BytesIO(than), allow_pickle=False) as npz:
            vao = {k: npz[k] for k in npz.files}
    except Exception as exc:
        raise HTTPException(400, "Đầu vào không phải .npz hợp lệ.") from exc
    phien = await asyncio.to_thread(_onnx_nap, ten)
    try:
        ra = await asyncio.to_thread(phien.run, None, vao)
    except Exception as exc:
        raise HTTPException(400, f"ONNX lỗi: {str(exc)[:200]}") from exc
    buf = io.BytesIO()
    np.savez(buf, **{f"o{i}": np.asarray(x) for i, x in enumerate(ra)})
    return Response(buf.getvalue(), media_type="application/octet-stream")
