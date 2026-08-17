"""Tách LỜI THOẠI khỏi nhạc/hiệu ứng bằng máy GPU, cho đường lồng tiếng.

**Vì sao phải tách.** Lồng tiếng mà map thẳng track TTS vào video là phim mất
sạch nhạc nền, tiếng bước chân, tiếng cửa — xem không còn ra phim. Còn trộn âm
gốc nhỏ đi thì lời thoại cũ vẫn lọt, hai giọng chồng nhau. Chỉ có source
separation mới bỏ được đúng phần giọng và giữ nguyên phần còn lại.

**Chạy ở đâu.** Cùng nếp với ``nghe_gpu`` và ``video_vision``: một dịch vụ nhỏ
trên máy GPU, gọi qua HTTP, có CẦU DAO nghỉ 5 phút khi hỏng. Máy chưa khai địa
chỉ thì hàm này ném lỗi và ``video_dub`` giữ lại SRT — KHÔNG âm thầm xuất video
mất nền, vì người dùng sẽ chỉ phát hiện ra sau khi đã xem.

**Hợp đồng với dịch vụ** (phải khớp khi dựng máy tách):

    POST {TACH_AM_URL_GPU}/tach?stem=nen
        body:      WAV 44.1 kHz stereo (streaming)
        headers:   X-API-Key, X-Job-Token, X-Filename
    → 200, thân là WAV stem NỀN do model ước lượng.
      Header ``X-Model`` ghi tên model để lưu vào ``prosody.json``.

    POST {TACH_AM_URL_GPU}/unload   (cùng X-API-Key và X-Job-Token)
"""
from __future__ import annotations

import logging
import os
import secrets
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from services import gpu_queue

logger = logging.getLogger(__name__)

#: Cầu dao — mốc thời gian được phép thử lại máy tách âm.
_nghi_toi = 0.0
NGHI_GIAY = 300.0

#: Separator cần dải tần đầy đủ và hai kênh; hạ xuống 16 kHz mono như đường
#: nghe sẽ cắt mất chũm choẹ/hiệu ứng cao tần rồi trả về nền nghe rỗng tuếch.
RATE_TACH = 44100


class LoiTachAm(RuntimeError):
    """Không tách được lời khỏi nền — caller không được tự ý bỏ track gốc."""


@dataclass(frozen=True)
class KetQuaTachAm:
    """Đường tệp WAV chỉ còn nhạc/hiệu ứng, và tên model đã tách."""

    background_path: str
    model: str = ""


def dung_duoc() -> bool:
    """Có máy tách âm để gọi không (đã khai địa chỉ, chưa bị cầu dao)."""
    return bool(dia_chi()) and time.time() >= _nghi_toi


def dia_chi() -> str:
    """Env ưu tiên config.json; cùng nếp với NGHE_URL_GPU trong dự án."""
    from services.config import config

    ten = "TACH_AM_URL_GPU"
    return str(os.getenv(ten) or config.data.get(ten.lower()) or "").strip().rstrip("/")


def _api_token() -> str:
    from services.config import config

    ten = "TACH_AM_API_TOKEN"
    return str(os.getenv(ten) or config.data.get(ten.lower()) or "").strip()


def _headers_api(*, job_token: str = "") -> dict[str, str]:
    token = _api_token()
    if not token:
        raise LoiTachAm("chưa khai TACH_AM_API_TOKEN")
    headers = {"X-API-Key": token}
    if job_token:
        headers["X-Job-Token"] = job_token
    return headers


def xac_nhan_san_sang(*, timeout: float = 5.0) -> None:
    """Fail-fast trước khi nghe/dịch cả phim rồi mới phát hiện thiếu separator."""
    url = dia_chi()
    if not url:
        raise LoiTachAm("chưa khai TACH_AM_URL_GPU")
    if time.time() < _nghi_toi:
        raise LoiTachAm("máy tách âm đang nghỉ 5 phút sau lỗi trước")
    import requests

    try:
        r = requests.get(f"{url}/health", headers=_headers_api(), timeout=timeout)
        r.raise_for_status()
        body = r.json() or {}
        if body.get("status") != "ok":
            raise RuntimeError(str(body.get("detail") or body.get("status") or "health lỗi"))
    except LoiTachAm:
        # Cấu hình thiếu không phải lỗi model, không mở cầu dao 5 phút.
        raise
    except Exception as exc:
        _ngat_cau_dao(f"health: {type(exc).__name__}: {exc}")
        raise LoiTachAm(f"máy tách lời chưa sẵn sàng: {str(exc)[:160]}") from exc


def _ngat_cau_dao(ly_do: str) -> None:
    global _nghi_toi
    _nghi_toi = time.time() + NGHI_GIAY
    logger.warning("máy tách âm GPU lỗi (%s) — nghỉ %.0f phút",
                   ly_do[:160], NGHI_GIAY / 60)


def _boc_wav_day_du(duong_video: str) -> str:
    """Video → WAV 44.1 kHz stereo để gửi đi tách."""
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", duong_video, "-vn", "-ac", "2", "-ar", str(RATE_TACH),
             "-c:a", "pcm_s16le", out],
            capture_output=True, timeout=1800)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        Path(out).unlink(missing_ok=True)
        raise LoiTachAm(f"không bóc được âm thanh để tách: {exc}") from exc
    except Exception:
        Path(out).unlink(missing_ok=True)
        raise
    if p.returncode or not Path(out).is_file() or Path(out).stat().st_size < 64:
        Path(out).unlink(missing_ok=True)
        loi = p.stderr.decode("utf-8", "ignore")[:180]
        raise LoiTachAm(f"không bóc được âm thanh để tách: {loi or 'ffmpeg lỗi'}")
    return out


def _nha_model(url: str, job_token: str) -> bool:
    """Nhả model tách để Whisper/Qwen không đụng VRAM của nó.

    Endpoint phải xác nhận tiến trình đúng job đã dừng trước khi hàng đợi GPU
    được nhả; nếu không, Whisper/Qwen có thể chạy chồng lên separator.
    """
    import requests

    try:
        r = requests.post(f"{url}/unload", headers=_headers_api(
            job_token=job_token), timeout=15)
        r.raise_for_status()
        body = r.json() or {}
        if body.get("status") != "ok" or body.get("loaded") is not False:
            raise RuntimeError(f"unload không xác nhận đã dừng: {body}")
        return True
    except Exception as exc:
        logger.warning("máy tách âm chưa nhả model: %s", str(exc)[:120])
        return False


def _chay_curl(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess:
    """Seam nhỏ để test đường upload streaming mà không gọi mạng thật."""
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _doc_model_header(duong: str) -> str:
    """Lấy header cuối, không phụ thuộc hoa/thường hay CRLF của HTTP."""
    model = ""
    try:
        for line in Path(duong).read_text("utf-8", errors="replace").splitlines():
            ten, sep, value = line.partition(":")
            if sep and ten.strip().lower() in {"x-model", "x-separator-model"}:
                model = value.strip()
    except OSError:
        pass
    return model[:160]


def _doc_ma_http(duong: str) -> int:
    """Mã HTTP cuối cùng trong tệp header curl ghi ra; 0 nếu không đọc được."""
    ma = 0
    try:
        for line in Path(duong).read_text("utf-8", errors="replace").splitlines():
            if line.upper().startswith("HTTP/"):
                phan = line.split()
                if len(phan) > 1 and phan[1].isdigit():
                    ma = int(phan[1])
    except OSError:
        pass
    return ma


class _MayBan(RuntimeError):
    """Máy tách còn sống, chỉ đang kẹt việc khác — KHÔNG phải lỗi dịch vụ."""


#: Mã HTTP nói "yêu cầu này không chạy được", không phải "máy hỏng". 429 là
#: đang bận một soundtrack khác, 413 là tệp quá cỡ. Phạt cầu dao 5 phút vì hai
#: mã này là oan, và còn khoá luôn việc đang chạy nếu nó cần thử lại — cùng lý
#: lẽ với ``QuaTaiGpu`` ở ``nghe_gpu``.
_MA_KHONG_PHAI_LOI_MAY = {429, 413}


def tach_nen(duong_video: str, *, progress=None,
             tran_giay: float = 10_800.0) -> KetQuaTachAm:
    """Video → WAV chỉ còn nhạc/hiệu ứng. Ném ``LoiTachAm`` khi không làm được.

    ``progress`` nhận cùng chữ ký với đường lồng tiếng ``(xong, tổng, bước)``.
    Máy tách chạy cả tệp trong một lượt nên chỉ có hai mốc: gửi đi và nhận về —
    thà báo hai mốc thật còn hơn một con số bò đều do mình bịa.
    """
    def _bao(buoc: str, xong: int) -> None:
        if progress is None:
            return
        try:
            progress(xong, 2, buoc)
        except Exception:
            pass

    url = dia_chi()
    if not url:
        raise LoiTachAm(
            "chưa khai địa chỉ máy tách âm (TACH_AM_URL_GPU) nên không tách "
            "được lời khỏi nhạc")
    # Fail TRƯỚC khi bóc WAV nhiều GB. Không có chốt này thì thiếu token đi tới
    # tận lúc server trả 401, và cầu dao mở 5 phút — phạt một máy đang khoẻ vì
    # lỗi cấu hình phía mình. Preflight có kiểm, nhưng cấu hình đổi được giữa
    # preflight và lúc tách một phim dài.
    api_token = _api_token()
    if not api_token:
        raise LoiTachAm("chưa khai TACH_AM_API_TOKEN")
    if time.time() < _nghi_toi:
        raise LoiTachAm("máy tách âm đang trong thời gian nghỉ sau lỗi")

    _bao("đang bóc âm thanh để tách lời khỏi nhạc…", 0)
    wav = _boc_wav_day_du(duong_video)
    out = tempfile.NamedTemporaryFile(suffix=".nen.wav", delete=False).name
    headers = tempfile.NamedTemporaryFile(suffix=".headers", delete=False).name
    request_headers = tempfile.NamedTemporaryFile(
        suffix=".request-headers", delete=False).name
    job_token = secrets.token_urlsafe(24)
    Path(request_headers).write_text(
        f"X-API-Key: {api_token}\nX-Job-Token: {job_token}\n"
        "X-Filename: soundtrack.wav\nContent-Type: audio/wav\n", "utf-8")
    _bao("đang tách lời gốc khỏi nhạc/hiệu ứng trên máy GPU…", 1)
    try:
        try:
            with gpu_queue.giu("Tách âm GPU"):
                # Chỉ cần /unload nếu transport đứt/timeout khi server có thể
                # còn xử lý. Response 2xx chỉ được gửi SAU KHI subprocess đã
                # thoát; gọi unload lúc đó có thể chen đúng job kế tiếp.
                can_huy_job = True
                try:
                    # --upload-file để libcurl đọc dần từ đĩa; API đọc raw body
                    # theo chunk, nên WAV 150 phút không bị spool/cấp phát hai
                    # bản nhiều GB trước khi áp giới hạn.
                    p = _chay_curl([
                        "curl", "--fail-with-body", "--silent", "--show-error",
                        "--connect-timeout", "15", "--max-time",
                        str(max(1, round(tran_giay))),
                        "-D", headers, "-o", out,
                        "--request", "POST", "--upload-file", wav,
                        "--header", f"@{request_headers}",
                        "--", f"{url}/tach?stem=nen",
                    ], timeout=tran_giay + 30)
                    if p.returncode:
                        # curl 22 = server đã trả HTTP lỗi (429/4xx/5xx); job
                        # này hoặc chưa được nhận, hoặc server đã tự dừng xong.
                        if p.returncode == 22:
                            can_huy_job = False
                        loi = p.stderr.decode("utf-8", "ignore")[:200]
                        if _doc_ma_http(headers) in _MA_KHONG_PHAI_LOI_MAY:
                            raise _MayBan(loi or "máy tách âm đang bận")
                        raise RuntimeError(loi or f"curl lỗi {p.returncode}")
                    can_huy_job = False
                    model = _doc_model_header(headers)
                finally:
                    # Khi curl timeout/ngắt mạng, phải xác nhận ĐÚNG process
                    # của job này đã dừng rồi mới thoát khỏi hàng đợi.
                    if can_huy_job and not _nha_model(url, job_token):
                        raise RuntimeError("không xác nhận được GPU tách âm đã dừng")
        except (gpu_queue.QuaTaiGpu, _MayBan) as exc:
            # Bận không có nghĩa dịch vụ hỏng — không phạt cầu dao. Job sau chỉ
            # mất phần lồng tiếng của chính nó, vẫn giữ SRT, và lượt kế tiếp
            # gọi lại được ngay thay vì bị chặn thêm 5 phút.
            raise LoiTachAm(str(exc)) from exc
        except Exception as exc:
            _ngat_cau_dao(f"{type(exc).__name__}: {exc}")
            raise LoiTachAm(str(exc)[:200]) from exc
        if Path(out).stat().st_size < 64:
            _ngat_cau_dao("máy tách âm trả tệp rỗng")
            raise LoiTachAm("máy tách âm trả tệp rỗng")
        _bao("đã tách lời gốc, đang chuẩn bị giọng TTS…", 2)
        return KetQuaTachAm(out, model)
    except Exception:
        Path(out).unlink(missing_ok=True)
        raise
    finally:
        Path(wav).unlink(missing_ok=True)
        Path(headers).unlink(missing_ok=True)
        Path(request_headers).unlink(missing_ok=True)
