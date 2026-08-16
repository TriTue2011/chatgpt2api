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
TIMEOUT_SECONDS = max(300, int(os.getenv("SEPARATOR_TIMEOUT_SECONDS", "10800")))
MAX_UPLOAD_BYTES = max(1 << 20, int(os.getenv(
    "SEPARATOR_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024))))
API_TOKEN = os.getenv("SEPARATOR_API_TOKEN", "").strip()

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


def _lenh_tach(input_path: str, output_dir: str) -> list[str]:
    return [
        "audio-separator", input_path,
        "--model_filename", MODEL,
        "--model_file_dir", "/data/models",
        "--output_dir", output_dir,
        "--output_format", "WAV",
        "--single_stem", "Instrumental",
        "--sample_rate", "44100",
        "--chunk_duration", str(CHUNK_SECONDS),
        "--mdx_batch_size", "1",
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


@app.get("/health")
def health(request: Request):
    _xac_thuc(request)
    missing = [name for name in ("audio-separator", "ffprobe")
               if not shutil.which(name)]
    if missing:
        raise HTTPException(503, "Thiếu binary: " + ", ".join(missing))
    return {"status": "ok", "model": MODEL, "chunk_seconds": CHUNK_SECONDS,
            "busy": _busy or _admission.locked(), "gpu": _gpu_do()}


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
