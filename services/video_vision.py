"""Ngữ cảnh hình cục bộ cho phụ đề, Qwen3-VL qua máy GPU trong LAN.

Vision chỉ là tầng nâng chất: không có URL, PySceneDetect, frame hay Qwen đều
không được làm đứt SRT. Khi chạy, CPU tìm cảnh trước; mỗi cảnh lấy tối đa hai
khung JPEG nhỏ rồi lần lượt gửi sang Qwen3-VL. Cả giai đoạn chia sẻ hàng đợi
GPU với Whisper và máy dịch.
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from services import gpu_queue

logger = logging.getLogger(__name__)

NGHI_GIAY = 300.0
_nghi_toi = 0.0
TOI_DA_FRAME_BYTE = 1_500_000
DUOI_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".3gp"}


class LoiVision(RuntimeError):
    """Qwen-VL hoặc tầng chuẩn bị frame không dùng được."""


@dataclass
class KetQuaVision:
    engine: str                     # off | gpu | fallback
    ranh_canh: list[float]
    mo_ta: list[str]
    canh_bao: str = ""
    so_canh_xu_ly: int = 0

    @property
    def so_canh(self) -> int:
        # 2 frame/cảnh vẫn chỉ là một cảnh; boundary chỉ lưu ranh GIỮA cảnh.
        if self.so_canh_xu_ly:
            return self.so_canh_xu_ly
        return len(self.ranh_canh) + 1 if self.mo_ta else 0


def _config(name: str, mac_dinh: str = "") -> str:
    """Env ưu tiên config.json; cùng nếp với NGHE_URL_GPU trong dự án."""
    from services.config import config

    return str(os.getenv(name) or config.data.get(name.lower()) or mac_dinh).strip()


def _so(name: str, mac_dinh: int, nho: int, lon: int) -> int:
    try:
        return min(lon, max(nho, int(_config(name, str(mac_dinh)))))
    except (TypeError, ValueError):
        return mac_dinh


def url_gpu() -> str:
    return _config("VISION_URL_GPU").rstrip("/")


def model() -> str:
    return _config("VISION_MODEL", "Qwen/Qwen3-VL-2B-Instruct-GGUF:Q4_K_M")


def dung_duoc() -> bool:
    return bool(url_gpu()) and time.time() >= _nghi_toi


def la_video(duong: str) -> bool:
    return Path(str(duong or "")).suffix.lower() in DUOI_VIDEO


def co_vram_an_toan() -> bool:
    """Không khởi động Qwen khi Frigate đang thiếu phần VRAM dự phòng.

    fw-nghe đã có telemetry ``nvidia-smi`` trong /health. Đọc nó trước khi gửi
    frame nên không cần mở Docker API nguy hiểm vào gateway. Nếu admin không
    khai telemetry hoặc nó tạm không đọc được thì không chặn tính năng: Qwen
    vẫn có circuit breaker/đường lui, còn máy đã có fw-nghe thì được bảo vệ.
    """
    import requests

    status = _config("VISION_GPU_STATUS_URL")
    if not status:
        try:
            from services.voice import config as vcfg
            status = vcfg.stt_gpu_url()
        except Exception:
            status = ""
    if not status:
        return True
    try:
        gpu = (requests.get(status.rstrip("/") + "/health", timeout=5).json()
               or {}).get("gpu") or {}
        free = float(gpu.get("vram_tong_mb")) - float(gpu.get("vram_dung_mb"))
        can = _so("VISION_MIN_FREE_MB", 3500, 512, 8000)
        if free < can:
            logger.info("bỏ Qwen3-VL: Frigate/GPU chỉ còn %.0f MB, cần %d MB", free, can)
            return False
    except Exception as exc:
        logger.info("không đọc được VRAM GPU trước vision: %s", str(exc)[:100])
    return True


def _ngat_cau_dao(ly_do: str) -> None:
    global _nghi_toi
    _nghi_toi = time.time() + NGHI_GIAY
    logger.warning("Qwen3-VL GPU lỗi (%s) — bỏ vision, nghỉ GPU %.0f phút",
                   ly_do[:160], NGHI_GIAY / 60)


def tach_canh(duong_video: str) -> list[tuple[float, float]]:
    """Tìm ranh cảnh bằng PySceneDetect, hoàn toàn CPU.

    Dùng high-level API được PySceneDetect duy trì qua 0.6→0.7; không phụ
    thuộc nội bộ FrameTimecode để video VFR vẫn có mốc giây đúng.
    """
    from scenedetect import ContentDetector, detect

    canh = detect(duong_video, ContentDetector(threshold=27.0), show_progress=False)
    ra: list[tuple[float, float]] = []
    for bat, ket in canh:
        b, k = float(bat.get_seconds()), float(ket.get_seconds())
        if k > b:
            ra.append((b, k))
    if not ra:
        raise LoiVision("PySceneDetect không tìm được cảnh nào")
    return ra


def _lay_mau_deu(canh: list[tuple[float, float]], toi_da_canh: int
                 ) -> list[tuple[float, float]]:
    if len(canh) <= toi_da_canh:
        return canh
    # Đều từ đầu đến cuối, không lấy 40 cảnh đầu rồi làm mù nửa sau video.
    chi_so = [round(i * (len(canh) - 1) / (toi_da_canh - 1))
              for i in range(toi_da_canh)]
    return [canh[i] for i in dict.fromkeys(chi_so)]


def chon_moc_khung(canh: list[tuple[float, float]], *, moi_canh: int = 1,
                   toi_da_canh: int = 40) -> list[float]:
    """Chọn một hoặc hai mốc *bên trong* mỗi cảnh, không lấy chính chỗ cut."""
    moi_canh = min(2, max(1, int(moi_canh)))
    canh = _lay_mau_deu(canh, max(1, int(toi_da_canh)))
    ra: list[float] = []
    for b, k in canh:
        dai = max(0.0, k - b)
        if moi_canh == 1:
            ra.append(round(b + dai / 2, 3))
        else:
            ra.extend((round(b + dai / 3, 3), round(b + dai * 2 / 3, 3)))
    return ra


def trich_khung(duong_video: str, moc_giay: float) -> bytes:
    """Bóc một JPEG nhỏ; không ghi frame tạm lên SSD và giới hạn payload LAN."""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss",
             f"{max(0.0, moc_giay):.3f}", "-i", duong_video, "-frames:v", "1",
             "-vf", "scale=768:768:force_original_aspect_ratio=decrease",
             "-q:v", "5", "-f", "image2", "pipe:1"],
            capture_output=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise LoiVision(f"không trích được frame: {exc}") from exc
    if p.returncode or not p.stdout:
        loi = (p.stderr or b"").decode("utf-8", "ignore")[:140]
        raise LoiVision(f"ffmpeg không trích được frame ({loi or 'lỗi không rõ'})")
    if len(p.stdout) > TOI_DA_FRAME_BYTE:
        raise LoiVision("frame vượt 1.5 MB sau khi thu nhỏ")
    return p.stdout


def phan_tich_khung(jpeg: bytes, moc_giay: float, loi_thoai: str = "") -> str:
    """Một frame → mô tả thực dụng, ngắn và không đoán danh tính vô căn cứ."""
    import requests

    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    prompt = (
        f"Đây là frame video tại {moc_giay:.1f}s. Mô tả cực ngắn bằng tiếng Việt: "
        "người/vật/bối cảnh/hành động có thể nhìn thấy. Nếu nhìn rõ, nêu thành phần "
        "giới tính bằng câu cụ thể như ‘hai phụ nữ’ hoặc ‘một nam một nữ’; không rõ "
        "thì ghi ‘giới tính không rõ’. Chỉ nêu quan hệ như ‘hai chị em’ khi hình hoặc "
        "lời thoại cho thấy chắc chắn, còn lại không đoán. Không khẳng định danh tính "
        "người nổi tiếng nếu hình không đủ chắc; không bịa lời thoại."
    )
    if loi_thoai.strip():
        prompt += " Lời thoại cùng cảnh (chỉ để đối chiếu, không dịch lại): " + loi_thoai[:700]
    try:
        r = requests.post(
            url_gpu() + "/v1/chat/completions",
            json={"model": model(), "temperature": 0.1, "max_tokens": 120,
                  "messages": [{"role": "user", "content": [
                      {"type": "text", "text": prompt},
                      {"type": "image_url", "image_url": {"url": data_url}},
                  ]}]},
            timeout=_so("VISION_TIMEOUT", 180, 10, 300),
        )
        r.raise_for_status()
        body = r.json()
        text = str(body["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        raise LoiVision(str(exc)[:200]) from exc
    if not text:
        raise LoiVision("Qwen3-VL trả mô tả rỗng")
    return text[:800]


def _doi_unload() -> bool:
    """Yêu cầu nhả model rồi chờ sleep tự động trước khi GPU sang công đoạn khác."""
    import requests

    url = url_gpu()
    if not url:
        return False
    try:
        # Endpoint chính thức; phiên bản chỉ có single-model có thể trả 404,
        # khi đó --sleep-idle-seconds trong compose vẫn là đường lui.
        requests.post(url + "/models/unload", json={"model": model()}, timeout=5)
    except Exception:
        pass
    het = time.monotonic() + 5.0
    while time.monotonic() < het:
        try:
            body = requests.get(url + "/props", timeout=2).json()
            if bool((body or {}).get("is_sleeping")):
                return True
        except Exception:
            return False
        time.sleep(0.2)
    return False


def phan_tich_video(duong_video: str, loi_thoai: list[object] | None = None
                     ) -> KetQuaVision:
    """Video → ngữ cảnh visual; mọi thất bại trả degradation, không raise.

    ``ranh_canh`` chỉ được trả khi Qwen thành công: caller dùng nó để không gộp
    lời thoại của hai cảnh vào một đơn vị dịch. Khi vision hỏng, đường lời thoại
    cũ giữ nguyên hoàn toàn.
    """
    if not la_video(duong_video) or not dung_duoc():
        return KetQuaVision("off", [], [])
    if not co_vram_an_toan():
        # Đây là backpressure do Frigate, không phải Qwen chết; tuyệt đối không
        # ngắt cầu dao 5 phút vì lượt sau card có thể đã rảnh.
        return KetQuaVision("fallback", [], [],
                             "Frigate đang chiếm VRAM; bỏ Qwen3-VL và dùng lời thoại.")
    try:
        canh_day_du = tach_canh(duong_video)
        toi_da = _so("VISION_MAX_SCENES", 40, 1, 120)
        canh = _lay_mau_deu(canh_day_du, toi_da)
        moc = chon_moc_khung(canh, moi_canh=_so("VISION_FRAMES_PER_SCENE", 1, 1, 2),
                             toi_da_canh=toi_da)
        khung = [trich_khung(duong_video, t) for t in moc]

        def _loi_thoai_o(moc_giay: float) -> str:
            return " ".join(str(getattr(d, "chu", "")) for d in (loi_thoai or [])
                            if float(getattr(d, "bat_dau", -1)) <= moc_giay
                            <= float(getattr(d, "ket_thuc", -1)))

        mo_ta: list[str] = []
        with gpu_queue.giu("Qwen3-VL"):
            for jpeg, t in zip(khung, moc):
                mo_ta.append(phan_tich_khung(jpeg, t, _loi_thoai_o(t)))
            da_unload = _doi_unload()
        canh_bao = ""
        if len(canh_day_du) > len(canh):
            canh_bao = (f"Vision lấy mẫu {len(canh)}/{len(canh_day_du)} cảnh để "
                         "giữ thời gian xử lý ổn định.")
        if not da_unload:
            canh_bao = (canh_bao + " " if canh_bao else "") + \
                        "Qwen3-VL sẽ tự nhả VRAM khi rảnh."
        # Tách câu dịch ở MỌI cut CPU đã biết, không chỉ 40 cảnh lấy mẫu Qwen.
        # ``so_canh_xu_ly`` vẫn là số cảnh thực sự gửi vision để status không
        # đánh lừa người dùng rằng Qwen đã xem hết một phim có hàng nghìn cut.
        return KetQuaVision("gpu", [b for b, _ in canh_day_du[1:]], mo_ta,
                             canh_bao, so_canh_xu_ly=len(canh))
    except gpu_queue.QuaTaiGpu as exc:
        # Whisper/dịch đang giữ lượt là backpressure bình thường. Không đẩy
        # Qwen vào circuit breaker vì ngay sau khi GPU rảnh nó vẫn tốt.
        logger.info("bỏ Qwen3-VL vì GPU đang bận: %s", str(exc)[:120])
        return KetQuaVision("fallback", [], [],
                             "GPU đang bận; bỏ Qwen3-VL và dùng lời thoại làm ngữ cảnh.")
    except Exception as exc:
        _ngat_cau_dao(f"{type(exc).__name__}: {exc}")
        return KetQuaVision("fallback", [], [],
                             "Qwen3-VL GPU lỗi; dùng lời thoại và tên tệp làm ngữ cảnh.")
